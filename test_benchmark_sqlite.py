# -*- coding: utf-8 -*-
"""SISTEMA ⑧ — BENCHMARK DI CARICO SQLite sul money-path REALE (file DB, come prod).

Non un micro-benchmark sintetico: gira il SISTEMA vero (crea_sistema + router) su DB
SU FILE, con lettori (ricerche/preventivi), prenotatori (quote+book+webhook-pagamento)
e host che riscrivono tariffe IN CONCORRENZA. Misura latenza p50/p95 e portata, e
IMPONE gli invarianti:
  - ZERO errori 5xx e ZERO 'database is locked' (i writer si accodano, mai esplodere);
  - ZERO overbooking (ogni notte venduta al massimo 1 volta: contata dai NOSTRI esiti);
  - latenza: soglie STRETTE (p95 letture<1.5s, scritture<3s) SOLO nel giro manuale
    (BENCH_* espliciti o BENCH_STRICT=1); DENTRO la suite soglie larghe anti-patologia
    (10s/15s). Perche' (2026-07-19, anti-ballerino): una soglia assoluta in millisecondi
    dentro una suite di ~2700 test su una macchina condivisa misura il PC del momento,
    non il codice (p95 2.13s vs 1.5s con test verdi standalone) -> falsi rossi che
    corrodono la fiducia nel semaforo. Le patologie VERE restano coperte SEMPRE:
    lock/5xx/overbooking sono invarianti duri, e un p95 oltre 10s e' malato ovunque.

Scala via env: BENCH_LETTORI / BENCH_PRENOTATORI / BENCH_HOSTW / BENCH_SECONDI
(default piccoli per la suite; il giro "pesante" si lancia a mano con valori alti).
"""
import datetime
import json
import os
import random
import statistics
import tempfile
import threading
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_bench"
LETTORI = int(os.environ.get("BENCH_LETTORI", "6"))
PRENOTATORI = int(os.environ.get("BENCH_PRENOTATORI", "4"))
HOSTW = int(os.environ.get("BENCH_HOSTW", "2"))
SECONDI = float(os.environ.get("BENCH_SECONDI", "8"))
N_ALLOGGI = 10
N_GIORNI = 60
# soglie latenza: strette solo quando il bench e' lanciato apposta (vedi docstring)
STRICT = (os.environ.get("BENCH_STRICT") == "1"
          or any(k in os.environ for k in
                 ("BENCH_LETTORI", "BENCH_PRENOTATORI", "BENCH_HOSTW", "BENCH_SECONDI")))
SOGLIA_P95_LETTURE, SOGLIA_P95_SCRITTURE = (1.5, 3.0) if STRICT else (10.0, 15.0)


def _fake_fetch(url, body, headers):
    return {"url": "https://x/cs", "id": "cs_" + str(time.time_ns())}


class TestBenchmarkSqlite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def test_carico_concorrente_su_file(self):
        d = tempfile.mkdtemp()
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_garanzia=f"{d}/g.db", db_viral=f"{d}/v.db", commissione_bps=1500,
            psp_bps=300, stripe_secret_key="sk", stripe_webhook_secret=WH,
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
        r = crea_router(sis, host_key="hk", base_url="https://b.com")

        LAT = {"lettura": [], "scrittura": []}
        latlock = threading.Lock()
        err5xx, locked = [], []

        def g(tipo, m, p, b=None, h=None, q=None):
            t0 = time.perf_counter()
            st, c = r.gestisci(m, p, q or {},
                               json.dumps(b) if b is not None else None, h or {})
            dt = time.perf_counter() - t0
            with latlock:
                LAT[tipo].append(dt)
                if st >= 500:
                    err5xx.append((m, p, st, str(c)[:120]))
                if "locked" in str(c).lower():
                    locked.append((m, p))
            return st, c

        # setup: 1 host, N alloggi, N_GIORNI aperti (1 unita' per notte)
        _, c = g("scrittura", "POST", "/api/host/registrazione",
                 {"email": "bench@ct.it", "password": "password1", "accetta_termini": True,
                  "accetta_clausole": True, "doc_sha256": doc_sha256(),
                  "versione": CONTRATTO_HOST_VERSIONE})
        H = {"X-Host-Token": c["token"]}
        oggi = datetime.date.today()
        da = oggi.isoformat()
        a = (oggi + datetime.timedelta(days=N_GIORNI)).isoformat()
        slugs = ["bench-casa%d" % i for i in range(N_ALLOGGI)]
        for sl in slugs:
            g("scrittura", "POST", "/api/host/pubblica",
              {"slug": sl, "titolo": "B " + sl, "citta": "Roma",
               "prezzo_notte_cents": 15000, "capacita": 4}, H)
            g("scrittura", "POST", "/api/host/disponibilita_range",
              {"alloggio_id": sl, "da": da, "a": a,
               "unita_totali": 1, "prezzo_netto_cents": 15000}, H)

        deadline = time.monotonic() + SECONDI
        stop = threading.Event()
        notti_vendute = {}          # (slug, giorno) -> conteggio dei NOSTRI successi
        vlock = threading.Lock()
        contatori = {"ricerche": 0, "quote": 0, "prenotate": 0, "rifiutate": 0}

        def lettore(seed):
            rnd = random.Random(seed)
            while time.monotonic() < deadline:
                g("lettura", "GET", "/api/catalogo", None, None, {"citta": "Roma"})
                with vlock:
                    contatori["ricerche"] += 1
                if rnd.random() < 0.4:
                    i = rnd.randrange(N_GIORNI - 2)
                    ci = (oggi + datetime.timedelta(days=i)).isoformat()
                    co = (oggi + datetime.timedelta(days=i + 1)).isoformat()
                    g("lettura", "POST", "/api/concierge/quote",
                      {"alloggio_id": rnd.choice(slugs), "check_in": ci,
                       "check_out": co, "party": 2})
                    with vlock:
                        contatori["quote"] += 1

        def prenotatore(seed):
            rnd = random.Random(1000 + seed)
            while time.monotonic() < deadline:
                sl = rnd.choice(slugs)
                i = rnd.randrange(N_GIORNI - 2)
                ci = (oggi + datetime.timedelta(days=i)).isoformat()
                co = (oggi + datetime.timedelta(days=i + 1)).isoformat()
                st, q = g("lettura", "POST", "/api/concierge/quote",
                          {"alloggio_id": sl, "check_in": ci, "check_out": co, "party": 2})
                if st != 200 or not q.get("quote_token"):
                    with vlock:
                        contatori["rifiutate"] += 1
                    continue
                st, b = g("scrittura", "POST", "/api/concierge/book",
                          {"quote_token": q["quote_token"], "email": "cli@ct.it"})
                if st not in (200, 201) or not b.get("riferimento"):
                    with vlock:
                        contatori["rifiutate"] += 1
                    continue
                pl = json.dumps({"type": "checkout.session.completed",
                                 "data": {"object": {"metadata": {"riferimento": b["riferimento"]}}}})
                # il webhook vuole il corpo RAW firmato (niente ri-serializzazioni)
                t0w = time.perf_counter()
                st2, c2 = r.gestisci("POST", "/api/payments/webhook", {}, pl,
                                     {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
                with latlock:
                    LAT["scrittura"].append(time.perf_counter() - t0w)
                    if st2 >= 500:
                        err5xx.append(("POST", "webhook", st2, str(c2)[:120]))
                    if "locked" in str(c2).lower():
                        locked.append(("POST", "webhook"))
                if st2 == 200:
                    with vlock:
                        contatori["prenotate"] += 1
                        notti_vendute[(sl, ci)] = notti_vendute.get((sl, ci), 0) + 1
                else:
                    with vlock:
                        contatori["rifiutate"] += 1

        def hostw(seed):
            rnd = random.Random(2000 + seed)
            while time.monotonic() < deadline:
                i = rnd.randrange(N_GIORNI)
                giorno = (oggi + datetime.timedelta(days=i)).isoformat()
                g("scrittura", "POST", "/api/host/disponibilita",
                  {"alloggio_id": rnd.choice(slugs), "giorno": giorno,
                   "unita_totali": 1,
                   "prezzo_netto_cents": rnd.choice([12000, 15000, 18000])}, H)
                g("lettura", "GET", "/api/host/calendario", None, H,
                  {"alloggio": rnd.choice(slugs), "da": da, "a": a})

        threads = ([threading.Thread(target=lettore, args=(i,)) for i in range(LETTORI)]
                   + [threading.Thread(target=prenotatore, args=(i,)) for i in range(PRENOTATORI)]
                   + [threading.Thread(target=hostw, args=(i,)) for i in range(HOSTW)])
        t0 = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        durata = time.monotonic() - t0
        stop.set()

        def perc(v, p):
            if not v:
                return 0.0
            v = sorted(v)
            return v[min(len(v) - 1, int(len(v) * p))]

        tot_ops = len(LAT["lettura"]) + len(LAT["scrittura"])
        print("\n== BENCH SQLite: %d thread (%dL/%dP/%dH) · %.1fs · %d op (%.0f op/s) ==" % (
            LETTORI + PRENOTATORI + HOSTW, LETTORI, PRENOTATORI, HOSTW,
            durata, tot_ops, tot_ops / max(durata, 0.001)))
        print("   letture : n=%d  p50=%.0fms  p95=%.0fms" % (
            len(LAT["lettura"]), perc(LAT["lettura"], .5) * 1000, perc(LAT["lettura"], .95) * 1000))
        print("   scritture: n=%d  p50=%.0fms  p95=%.0fms" % (
            len(LAT["scrittura"]), perc(LAT["scrittura"], .5) * 1000, perc(LAT["scrittura"], .95) * 1000))
        print("   esiti: %s · 5xx=%d · locked=%d · soglie=%s" % (
            contatori, len(err5xx), len(locked),
            "STRETTE (giro manuale)" if STRICT else "larghe anti-patologia (in suite)"))

        # INVARIANTI (il benchmark e' anche una guardia)
        self.assertEqual(err5xx, [], "errori 5xx sotto carico")
        self.assertEqual(locked, [], "'database is locked' non deve MAI arrivare all'utente")
        self.assertGreater(contatori["prenotate"], 0, "nessuna prenotazione riuscita: bench non valido")
        self.assertLess(perc(LAT["lettura"], .95), SOGLIA_P95_LETTURE,
                        "p95 letture fuori soglia (%s)" % ("stretta" if STRICT else "larga: patologia"))
        self.assertLess(perc(LAT["scrittura"], .95), SOGLIA_P95_SCRITTURE,
                        "p95 scritture fuori soglia (%s)" % ("stretta" if STRICT else "larga: patologia"))
        for (sl, giorno), n in notti_vendute.items():
            self.assertLessEqual(n, 1, "OVERBOOKING su %s %s: %d" % (sl, giorno, n))


if __name__ == "__main__":
    unittest.main(verbosity=2)
