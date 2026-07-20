"""BOMBARDAMENTO Vista Multi-Alloggio /api/host/calendario_tutti (2026-07-17,
strategia "10.000 menti" — N thread sulla STESSA vista nello stesso istante).

Barriera unica: V viste host A (PC || telefono || tablet) || W scritture tariffe/chiusure
|| B ospiti prenota+paga || P pubblica nuovi alloggi || X viste host RIVALE.

INVARIANTI:
  - I1 VISTA SEMPRE VIVA: ogni chiamata 200 con struttura {alloggi:[{slug,titolo,giorni}]}.
  - I2 CELLE BEN FORMATE: stato ammesso, giorni == range richiesto in ordine.
  - I3 ISOLAMENTO SOTTO CARICO: la vista di un host non contiene MAI slug altrui.
  - I5 VENDUTA MAI NASCOSTA: una notte PAGATA prima della tempesta resta 'pieno'
    in OGNI vista concorrente, anche se l'host la sta chiudendo (bug #35:
    'chiuso' vinceva su 'pieno' e la prenotazione viva spariva dalla vista).
  - I4 VERITA' FINALE: dopo la tempesta la vista == DB (+ hold vivi) per ogni
    slug/giorno; ogni alloggio pubblicato durante la tempesta e' presente.

Prova pesante (scratchpad): 10 seed x ~2.700 richieste (viste+scritture+pagamenti
concorrenti) = 40s, ZERO violazioni (dopo il fix #35). Qui guardia snella: 2 seed.
NB sonda: db_viral DEVE essere un file (il fallback :memory: usa una connessione
condivisa fra thread -> 'transaction within a transaction' FINTI, artefatto).
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

WH = "whsec_ct"
STATI_OK = {"libero", "pieno", "chiuso", "non_caricato", "in_trattativa"}


def _fake_fetch(url, body, headers):
    return {"url": "https://x/cs", "id": "cs_" + str(time.time_ns())}


class TestBombardamentoCalendarioTutti(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def _sistema(self, d):
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_garanzia=f"{d}/g.db", db_viral=f"{d}/v.db", commissione_bps=1500,
            psp_bps=300, stripe_secret_key="sk", stripe_webhook_secret=WH,
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
        r = crea_router(sis, host_key="hk", base_url="https://b.com")
        return sis, r

    def _tempesta(self, seed):
        rnd = random.Random(seed)
        d = tempfile.mkdtemp()
        try:
            sis, r = self._sistema(d)

            def g(m, p, b=None, h=None, q=None):
                return r.gestisci(m, p, q or {},
                                  json.dumps(b) if b is not None else None, h or {})

            def paga(rif):
                pl = json.dumps({"type": "checkout.session.completed",
                                 "data": {"object": {"metadata": {"riferimento": rif}}}})
                r.gestisci("POST", "/api/payments/webhook", {}, pl,
                           {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})

            def registra(email):
                _, c = g("POST", "/api/host/registrazione",
                         {"email": email, "password": "password1", "accetta_termini": True,
                          "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                          "versione": CONTRATTO_HOST_VERSIONE})
                return {"X-Host-Token": c["token"]}

            HA, HB = registra("a@ct.it"), registra("b@ct.it")
            oggi = datetime.date.today()
            da = oggi.isoformat()
            a = (oggi + datetime.timedelta(days=10)).isoformat()
            gg_attesi = [(oggi + datetime.timedelta(days=i)).isoformat() for i in range(10)]
            slugs_a = ["a-casa%d" % i for i in range(4)]
            for sl, H in [(s, HA) for s in slugs_a] + [("b-casa0", HB)]:
                g("POST", "/api/host/pubblica", {"slug": sl, "titolo": "T " + sl,
                  "citta": "Roma", "prezzo_notte_cents": 20000, "capacita": 4}, H)
                g("POST", "/api/host/disponibilita_range",
                  {"alloggio_id": sl, "da": da, "a": a,
                   "unita_totali": 1, "prezzo_netto_cents": 20000}, H)
            D = gg_attesi[5]
            D1 = (oggi + datetime.timedelta(days=6)).isoformat()
            _, q0 = g("POST", "/api/concierge/quote",
                      {"alloggio_id": "a-casa0", "check_in": D, "check_out": D1, "party": 2})
            _, b0 = g("POST", "/api/concierge/book",
                      {"quote_token": q0["quote_token"], "email": "pre@ct.it"})
            paga(b0["riferimento"])

            errs, lock, pubblicati = [], threading.Lock(), []
            nV, nX, nW, nB, nP = 8, 3, 8, 5, 2
            barrier = threading.Barrier(nV + nX + nW + nB + nP)

            def err(*e):
                with lock:
                    errs.append(e)

            def controlla(s, dv, prefisso, tag):
                if s != 200 or not isinstance(dv.get("alloggi"), list):
                    return err("I1_VISTA_KO", tag, s)
                for x in dv["alloggi"]:
                    sl = x.get("slug", "")
                    if not sl.startswith(prefisso):
                        return err("I3_LEAK", tag, sl)
                    gg = [c.get("giorno") for c in x.get("giorni", [])]
                    if gg != gg_attesi:
                        return err("I2_RANGE", tag, sl, len(gg))
                    for c in x["giorni"]:
                        if c.get("stato") not in STATI_OK:
                            return err("I2_STATO", tag, sl, c.get("stato"))
                    if sl == "a-casa0" and \
                            {c["giorno"]: c["stato"] for c in x["giorni"]}[D] != "pieno":
                        return err("I5_VENDUTA_NASCOSTA", tag,
                                   {c["giorno"]: c["stato"] for c in x["giorni"]}[D])

            def vista(H, prefisso, tag):
                barrier.wait()
                for k in range(2):
                    s, dv = g("GET", "/api/host/calendario_tutti", h=H, q={"da": da, "a": a})
                    controlla(s, dv, prefisso, "%s/%d" % (tag, k))

            def scrivi(i):
                barrier.wait()
                for k in range(3):
                    g("POST", "/api/host/disponibilita",
                      {"alloggio_id": rnd.choice(slugs_a), "giorno": rnd.choice(gg_attesi),
                       "unita_totali": 1, "prezzo_netto_cents": rnd.choice([5000, 30000]),
                       "chiuso": rnd.random() < 0.25}, HA)

            def prenota(i):
                barrier.wait()
                i0 = rnd.randrange(0, 9)
                _, qq = g("POST", "/api/concierge/quote",
                          {"alloggio_id": rnd.choice(slugs_a), "check_in": gg_attesi[i0],
                           "check_out": (oggi + datetime.timedelta(days=i0 + 1)).isoformat(),
                           "party": 2})
                if qq.get("quote_token"):
                    _, bb = g("POST", "/api/concierge/book",
                              {"quote_token": qq["quote_token"], "email": "m%d@ct.it" % i})
                    if bb.get("riferimento") and rnd.random() < 0.7:
                        paga(bb["riferimento"])

            def pubblica(i):
                barrier.wait()
                sl = "a-nuova%d" % i
                s, _ = g("POST", "/api/host/pubblica", {"slug": sl, "titolo": "N",
                         "citta": "Roma", "prezzo_notte_cents": 15000, "capacita": 2}, HA)
                if s in (200, 201):
                    with lock:
                        pubblicati.append(sl)

            ths = ([threading.Thread(target=vista, args=(HA, "a-", "A%d" % i))
                    for i in range(nV)] +
                   [threading.Thread(target=vista, args=(HB, "b-", "B%d" % i))
                    for i in range(nX)] +
                   [threading.Thread(target=scrivi, args=(i,)) for i in range(nW)] +
                   [threading.Thread(target=prenota, args=(i,)) for i in range(nB)] +
                   [threading.Thread(target=pubblica, args=(i,)) for i in range(nP)])
            rnd.shuffle(ths)
            for t in ths:
                t.start()
            for t in ths:
                t.join(60)

            s, dv = g("GET", "/api/host/calendario_tutti", h=HA, q={"da": da, "a": a})
            self.assertEqual(s, 200)
            coni = sqlite3.connect(f"{d}/i.db")
            coni.row_factory = sqlite3.Row
            db = {(r2["alloggio_id"], r2["giorno"]): dict(r2)
                  for r2 in coni.execute("SELECT * FROM inventario").fetchall()}
            coni.close()
            visti = set()
            for x in dv["alloggi"]:
                sl = x["slug"]
                visti.add(sl)
                hold_gg = set()
                for h in sis.pagamenti_pendenti.attivi_per_alloggio(sl):
                    h0 = datetime.date.fromisoformat(h["check_in"])
                    h1 = datetime.date.fromisoformat(h["check_out"])
                    for i in range((h1 - h0).days):
                        hold_gg.add((h0 + datetime.timedelta(days=i)).isoformat())
                for c in x["giorni"]:
                    row = db.get((sl, c["giorno"]))
                    if row is None:
                        atteso = {"non_caricato"}
                    elif row["unita_totali"] > 0 and \
                            row["unita_occupate"] >= row["unita_totali"]:
                        atteso = {"pieno", "in_trattativa"} \
                            if c["giorno"] in hold_gg else {"pieno"}
                    elif row["chiuso"]:
                        atteso = {"chiuso"}
                    elif row["unita_occupate"] >= row["unita_totali"]:
                        atteso = {"pieno"}
                    else:
                        atteso = {"libero"}
                    if c["stato"] not in atteso:
                        err("I4_VERITA", sl, c["giorno"], c["stato"], sorted(atteso))
            for sl in pubblicati:
                if sl not in visti:
                    err("I4_PUBBLICATO_SPARITO", sl)
            self.assertEqual(errs, [], "seed=%d: %s" % (seed, errs[:4]))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_tempesta_2_seed(self):
        for seed in range(2):
            self._tempesta(seed)

    def test_venduta_poi_chiusa_resta_piena(self):
        """Bug #35 SEQUENZIALE: notte pagata -> host la 'chiude' -> la vista
        (singola e multi) deve mostrarla PIENA, mai nascondere la prenotazione."""
        d = tempfile.mkdtemp()
        try:
            sis, r = self._sistema(d)

            def g(m, p, b=None, h=None, q=None):
                return r.gestisci(m, p, q or {},
                                  json.dumps(b) if b is not None else None, h or {})

            _, c = g("POST", "/api/host/registrazione",
                     {"email": "s@ct.it", "password": "password1", "accetta_termini": True,
                      "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                      "versione": CONTRATTO_HOST_VERSIONE})
            H = {"X-Host-Token": c["token"]}
            oggi = datetime.date.today()
            da = oggi.isoformat()
            a = (oggi + datetime.timedelta(days=5)).isoformat()
            g("POST", "/api/host/pubblica", {"slug": "casa", "titolo": "C",
              "citta": "Roma", "prezzo_notte_cents": 20000, "capacita": 2}, H)
            g("POST", "/api/host/disponibilita_range",
              {"alloggio_id": "casa", "da": da, "a": a,
               "unita_totali": 1, "prezzo_netto_cents": 20000}, H)
            D = (oggi + datetime.timedelta(days=2)).isoformat()
            D1 = (oggi + datetime.timedelta(days=3)).isoformat()
            _, q0 = g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": D, "check_out": D1, "party": 2})
            _, b0 = g("POST", "/api/concierge/book",
                      {"quote_token": q0["quote_token"], "email": "x@ct.it"})
            pl = json.dumps({"type": "checkout.session.completed",
                             "data": {"object": {"metadata":
                                                 {"riferimento": b0["riferimento"]}}}})
            r.gestisci("POST", "/api/payments/webhook", {}, pl,
                       {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
            s, _ = g("POST", "/api/host/disponibilita",
                     {"alloggio_id": "casa", "giorno": D, "unita_totali": 1,
                      "prezzo_netto_cents": 20000, "chiuso": True}, H)
            self.assertEqual(s, 200)
            _, v1 = g("GET", "/api/host/calendario", h=H,
                      q={"alloggio": "casa", "da": da, "a": a})
            st1 = {x["giorno"]: x["stato"] for x in v1["giorni"]}
            self.assertEqual(st1[D], "pieno")
            _, v2 = g("GET", "/api/host/calendario_tutti", h=H, q={"da": da, "a": a})
            st2 = {x["giorno"]: x["stato"] for x in v2["alloggi"][0]["giorni"]}
            self.assertEqual(st2[D], "pieno")
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
