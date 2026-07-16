"""BOMBARDAMENTO su-richiesta -> approvazione (2026-07-17, strategia "10.000 menti",
modulo Su-Richiesta -> Approvazione Host — i 3 scenari del briefing).

Per ogni alloggio su_richiesta con una richiesta PENDENTE dell'ospite A, nello STESSO
istante (barriera): host APPROVA A, host RIFIUTA A (gara decisione), K ospiti B tentano
l'ISTANTANEO sulle stesse date, lo sweeper SCADE gli hold.

INVARIANTI DURI (devono valere sempre):
  - NO OVERBOOKING: per ogni notte, unita_occupate <= unita_totali (la richiesta pendente
    TIENE la stanza -> B non puo' prenotarla; se A viene rifiutata/scade, al piu' un B vince).
  - AL PIU' 1 PAGATO per alloggio (mai A finalizzato E un B confermato sulla stessa notte).
  - il router non solleva mai (0 eccezioni).

Prova su vasta scala (scratchpad): 300 richieste, 2700 thread concorrenti, 10 seed
-> 0 errori, 0 violazioni. Qui gira una versione veloce come GUARDIA quotidiana.
"""
import datetime
import json
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, sweep_hold_una_passata
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_sr"


def _fake_fetch(url, body, headers):
    return {"url": "https://x/cs", "id": "cs_" + str(time.time_ns())}


class TestBombardamentoSuRichiesta(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def _tempesta(self, seed, n_alloggi, b_per_alloggio):
        import random
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
            r = crea_router(sis, host_key="hk", admin_key="ak", base_url="https://b.com")

            def g(m, p, b=None, h=None):
                return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

            def paga(rif):
                pl = json.dumps({"type": "checkout.session.completed",
                                 "data": {"object": {"metadata": {"riferimento": rif}}}})
                r.gestisci("POST", "/api/payments/webhook", {}, pl,
                           {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})

            _, c = g("POST", "/api/host/registrazione",
                     {"email": "h@sr.it", "password": "password1", "accetta_termini": True,
                      "accetta_clausole": True, "doc_sha256": doc_sha256(),
                      "versione": CONTRATTO_HOST_VERSIONE})
            tok = c["token"]
            H = {"X-Host-Token": tok}
            oggi = datetime.date.today()
            casi = []
            for i in range(n_alloggi):
                slug = "casa%d" % i
                g("POST", "/api/host/pubblica",
                  {"slug": slug, "titolo": "C%d" % i, "citta": "Roma",
                   "prezzo_notte_cents": 20000, "capacita": 4,
                   "modalita_prenotazione": "su_richiesta"}, H)
                ci = (oggi + datetime.timedelta(days=3 + i)).isoformat()
                co = (oggi + datetime.timedelta(days=5 + i)).isoformat()
                g("POST", "/api/host/disponibilita_range",
                  {"alloggio_id": slug, "da": oggi.isoformat(),
                   "a": (oggi + datetime.timedelta(days=90)).isoformat(),
                   "unita_totali": 1, "prezzo_netto_cents": 20000}, H)
                _, q = g("POST", "/api/concierge/quote",
                         {"alloggio_id": slug, "check_in": ci, "check_out": co, "party": 2})
                _, bA = g("POST", "/api/concierge/book",
                          {"quote_token": q["quote_token"], "email": "A@sr.it"})
                if bA.get("stato") == "in_attesa_host":
                    casi.append((slug, bA["riferimento"], ci, co))
            self.assertGreater(len(casi), 0, "setup: nessuna richiesta pendente")

            errs = []
            threads = []
            per_alloggio = 2 + b_per_alloggio + 1
            total = len(casi) * per_alloggio
            barrier = threading.Barrier(total)

            def mk(fn):
                def f():
                    barrier.wait()
                    try:
                        fn()
                    except Exception as e:
                        errs.append((type(e).__name__, str(e)[:80]))
                return f

            for (slug, rifA, ci, co) in casi:
                threads.append(threading.Thread(target=mk(
                    lambda rifA=rifA: g("POST", "/api/host/richieste/approva",
                                        {"riferimento": rifA}, H))))
                threads.append(threading.Thread(target=mk(
                    lambda rifA=rifA: g("POST", "/api/host/richieste/rifiuta",
                                        {"riferimento": rifA}, H))))
                for k in range(b_per_alloggio):
                    def istantaneo(slug=slug, ci=ci, co=co, k=k):
                        _, q = g("POST", "/api/concierge/quote",
                                 {"alloggio_id": slug, "check_in": ci, "check_out": co,
                                  "party": 2})
                        if q.get("quote_token"):
                            _, bB = g("POST", "/api/concierge/book",
                                      {"quote_token": q["quote_token"], "email": "B%d@sr.it" % k})
                            rifB = bB.get("riferimento")
                            if rifB and bB.get("stato") in ("confermata", "in_attesa_pagamento"):
                                paga(rifB)
                    threads.append(threading.Thread(target=mk(istantaneo)))
                threads.append(threading.Thread(target=mk(lambda: sweep_hold_una_passata(sis, r))))

            for t in threads:
                t.start()
            for t in threads:
                t.join(60)
            for (slug, rifA, ci, co) in casi:
                recA = sis.pagamenti_pendenti.info(rifA)
                if recA and recA.get("stato") == "in_attesa":
                    paga(rifA)
            sweep_hold_una_passata(sis, r)

            viol = []
            coni = sqlite3.connect(f"{d}/i.db")
            coni.row_factory = sqlite3.Row
            for row in coni.execute("SELECT alloggio_id,giorno,unita_totali,unita_occupate "
                                    "FROM inventario"):
                if row["unita_occupate"] > row["unita_totali"] or row["unita_occupate"] < 0:
                    viol.append(("OVERBOOKING", dict(row)))
            coni.close()
            conp = sqlite3.connect(f"{d}/p.db")
            for (slug, rifA, ci, co) in casi:
                pagati = conp.execute("SELECT COUNT(*) FROM pendenti WHERE alloggio_id=? "
                                      "AND stato='pagato'", (slug,)).fetchone()[0]
                if pagati > 1:
                    viol.append(("DOPPIO_PAGATO", slug, pagati))
            conp.close()
            self.assertEqual(errs, [], f"seed={seed}: il router ha SOLLEVATO: {errs[:3]}")
            self.assertEqual(viol, [], f"seed={seed}: invariante ROTTA: {viol[:5]}")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_tempesta_seed_1(self):
        self._tempesta(1, n_alloggi=8, b_per_alloggio=5)

    def test_tempesta_seed_2(self):
        self._tempesta(2, n_alloggi=8, b_per_alloggio=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
