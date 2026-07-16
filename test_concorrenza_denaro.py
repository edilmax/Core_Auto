"""
INDISTRUTTIBILITA' sotto CARICO: money-path in concorrenza.

Molti thread corrono a prenotare+pagare la STESSA stanza/date (1 unita'). Invarianti che devono
valere SEMPRE, anche con la gara:
  - NO OVERBOOKING: per ogni giorno, unita_occupate <= unita_totali (mai la stanza doppia).
  - UN SOLO VINCITORE pagato: al piu' 1 payout 'maturato' per quella stanza/date.
  - NO DOPPIO PAYOUT: nessun riferimento con piu' di una riga payout.
  - CONSERVAZIONE: il maturato dell'host == netto_host del preventivo del vincitore (non sommato).
La mega-sim copre la concorrenza ma NON gira nel giro quotidiano; questo si', ed e' veloce.
"""
import json
import shutil
import tempfile
import threading
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_cc2"


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://t/" + secrets.token_hex(6), "id": "cs_" + secrets.token_hex(6)}


class TestConcorrenzaDenaro(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        d = self.dir
        self.sys = crea_sistema(ConfigCasaVIP(     # DB su FILE: ogni thread la sua connessione
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db",
            db_garanzia=f"{d}/g.db", commissione_bps=1000, psp_bps=300,
            stripe_secret_key="sk", stripe_webhook_secret=WH,
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@cc2.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.tok, self.hid = c["token"], c["host_id"]
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa", "titolo": "Casa", "citta": "Roma", "prezzo_notte_cents": 50000,
                "capacita": 4, "politica_cancellazione": "flessibile"}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa", "da": "2026-09-01", "a": "2026-09-30",
                "unita_totali": 1, "prezzo_netto_cents": 50000}, {"X-Host-Token": self.tok})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def test_gara_stessa_stanza_un_solo_vincitore_pagato(self):
        N = 30
        barriera = threading.Barrier(N)
        confermati = []
        lock = threading.Lock()

        def tenta():
            barriera.wait()                              # massima contesa: partono insieme
            s, q = self.g("POST", "/api/concierge/quote",
                          {"alloggio_id": "casa", "check_in": "2026-09-10",
                           "check_out": "2026-09-13", "party": 2})
            if s != 200 or not q.get("quote_token"):
                return
            s, b = self.g("POST", "/api/concierge/book",
                          {"quote_token": q["quote_token"], "email": "cli@cc2.it"})
            if s != 201 or not b.get("riferimento"):
                return
            rif = b["riferimento"]
            pl = json.dumps({"type": "checkout.session.completed",
                             "data": {"object": {"metadata": {"riferimento": rif}}}})
            self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                            {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
            with lock:
                confermati.append(rif)

        ths = [threading.Thread(target=tenta) for _ in range(N)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()

        # NO OVERBOOKING: per ogni notte contesa, occupate <= totali (== 1)
        for giorno in ("2026-09-10", "2026-09-11", "2026-09-12"):
            st = self.sys.inventario.stato_giorno("casa", giorno)
            self.assertIsNotNone(st, giorno)
            self.assertLessEqual(st["unita_occupate"], st["unita_totali"],
                                 f"OVERBOOKING il {giorno}: {st}")
            self.assertLessEqual(st["unita_occupate"], 1, f"stanza doppia il {giorno}")

        # UN SOLO VINCITORE pagato + CONSERVAZIONE
        rie = self.sys.payout.riepilogo(self.hid).get("EUR", {})
        maturato = rie.get("maturato", 0)
        pagati = [r for r in (self.sys.pagamenti_pendenti.info(x) for x in confermati)
                  if r and r.get("stato") == "pagato"]
        self.assertLessEqual(len(pagati), 1,
                             f"piu' di un pagamento confermato sulla stessa stanza: {len(pagati)}")
        if pagati:
            dj = json.loads(pagati[0].get("corpo_json") or "{}")
            self.assertEqual(maturato, dj.get("netto_host_cents"),
                             "CONSERVAZIONE: il maturato non combacia col netto_host del vincitore")
        else:
            self.assertEqual(maturato, 0, "nessun vincitore ma payout maturato > 0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
