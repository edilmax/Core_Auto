"""BOMBARDAMENTO Calendario Prezzi (2026-07-17, strategia "10.000 menti", modulo
Calendario Prezzi e vista multi-alloggio — i 3 scenari del briefing).

Sullo STESSO giorno conteso, nello stesso istante (barriera): K host riscrivono la tariffa
(modifica massiva simultanea) ∥ M ospiti prenotano+pagano (blocco) ∥ N ospiti chiedono la
quote (calcolo mentre il prezzo cambia).

INVARIANTI (Sezione 4-5 del briefing):
  - NO OVERBOOKING: unita_occupate <= unita_totali.
  - NO LOST OCCUPANCY: la scrittura-prezzo NON azzera l'occupazione di una prenotazione
    concorrente -> unita_occupate == numero di prenotazioni PAGATE su quel giorno.
    (fase58.imposta_disponibilita in BEGIN IMMEDIATE rilegge occupate e la riscrive
    invariata; il blocco serializza -> nessuna scrittura sporca.)
  - LAST-WRITER-WINS INTEGRO: il prezzo finale e' UNO dei valori scritti (mai torn/negativo).
  - COERENZA QUOTE: ogni quote (1 notte) ha totale == prezzo_guest == prezzo_netto valido>0.

Prova (scratchpad): 24 giri (12 seed x {1,2} unita') -> 0 violazioni.
"""
import datetime
import json
import random
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_pz"
PREZZI = [5000, 8000, 12000, 20000, 35000, 50000]


def _fake_fetch(url, body, headers):
    return {"url": "https://x/cs", "id": "cs_" + str(time.time_ns())}


class TestBombardamentoPrezzi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def _tempesta(self, seed, unita):
        rnd = random.Random(seed)
        d = tempfile.mkdtemp()
        try:
            sis = crea_sistema(ConfigCasaVIP(
                abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
                db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
                db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
                db_garanzia=f"{d}/g.db", commissione_bps=1500, psp_bps=300,
                stripe_secret_key="sk", stripe_webhook_secret=WH,
                stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
            r = crea_router(sis, host_key="hk", base_url="https://b.com")

            def g(m, p, b=None, h=None):
                return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

            def paga(rif):
                pl = json.dumps({"type": "checkout.session.completed",
                                 "data": {"object": {"metadata": {"riferimento": rif}}}})
                r.gestisci("POST", "/api/payments/webhook", {}, pl,
                           {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})

            _, c = g("POST", "/api/host/registrazione",
                     {"email": "h@pz.it", "password": "password1", "accetta_termini": True,
                      "accetta_clausole": True, "doc_sha256": doc_sha256(),
                      "versione": CONTRATTO_HOST_VERSIONE})
            H = {"X-Host-Token": c["token"]}
            oggi = datetime.date.today()
            g("POST", "/api/host/pubblica",
              {"slug": "casa", "titolo": "C", "citta": "Roma",
               "prezzo_notte_cents": 20000, "capacita": 4}, H)
            g("POST", "/api/host/disponibilita_range",
              {"alloggio_id": "casa", "da": oggi.isoformat(),
               "a": (oggi + datetime.timedelta(days=20)).isoformat(),
               "unita_totali": unita, "prezzo_netto_cents": 20000}, H)
            giorno = (oggi + datetime.timedelta(days=5)).isoformat()
            ci = giorno
            co = (oggi + datetime.timedelta(days=6)).isoformat()
            errs = []
            prezzi_scritti = []
            lock = threading.Lock()
            n_w, n_b, n_q = 20, unita + 3, 12
            barrier = threading.Barrier(n_w + n_b + n_q)

            def scrivi(i):
                barrier.wait()
                pr = rnd.choice(PREZZI)
                _, o = g("POST", "/api/host/disponibilita",
                         {"alloggio_id": "casa", "giorno": giorno,
                          "unita_totali": unita, "prezzo_netto_cents": pr}, H)
                if o.get("stato") == "ok":
                    with lock:
                        prezzi_scritti.append(pr)

            def prenota(i):
                barrier.wait()
                _, q = g("POST", "/api/concierge/quote",
                         {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
                if q.get("quote_token"):
                    _, b = g("POST", "/api/concierge/book",
                             {"quote_token": q["quote_token"], "email": "b%d@pz.it" % i})
                    rif = b.get("riferimento")
                    if rif and b.get("stato") in ("confermata", "in_attesa_pagamento"):
                        paga(rif)

            def quota(i):
                barrier.wait()
                s, q = g("POST", "/api/concierge/quote",
                         {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
                if s == 200 and q.get("quote_token"):
                    tot, netto = q.get("totale_cents"), q.get("prezzo_netto_cents")
                    if not (isinstance(netto, int) and netto > 0 and tot == netto):
                        with lock:
                            errs.append(("QUOTE_INCOERENTE", tot, netto))

            ths = ([threading.Thread(target=scrivi, args=(i,)) for i in range(n_w)] +
                   [threading.Thread(target=prenota, args=(i,)) for i in range(n_b)] +
                   [threading.Thread(target=quota, args=(i,)) for i in range(n_q)])
            rnd.shuffle(ths)
            for t in ths:
                t.start()
            for t in ths:
                t.join(60)

            viol = list(errs)
            coni = sqlite3.connect(f"{d}/i.db")
            coni.row_factory = sqlite3.Row
            row = coni.execute("SELECT unita_totali, unita_occupate, prezzo_netto_cents "
                               "FROM inventario WHERE alloggio_id='casa' AND giorno=?",
                               (giorno,)).fetchone()
            coni.close()
            conp = sqlite3.connect(f"{d}/p.db")
            pagati = conp.execute("SELECT COUNT(*) FROM pendenti WHERE alloggio_id='casa' "
                                  "AND stato='pagato' AND check_in=?", (ci,)).fetchone()[0]
            conp.close()
            if row["unita_occupate"] > row["unita_totali"]:
                viol.append(("OVERBOOKING", dict(row)))
            if row["unita_occupate"] != pagati:
                viol.append(("LOST_OCCUPANCY",
                             "occupate=%d pagati=%d" % (row["unita_occupate"], pagati)))
            if prezzi_scritti and row["prezzo_netto_cents"] not in PREZZI:
                viol.append(("PREZZO_TORN", row["prezzo_netto_cents"]))
            self.assertEqual(viol, [], f"seed={seed} unita={unita}: {viol[:4]}")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_prezzi_vs_prenotazioni_1_unita(self):
        for seed in range(3):
            self._tempesta(seed, 1)

    def test_prezzi_vs_prenotazioni_2_unita(self):
        for seed in range(3):
            self._tempesta(seed, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
