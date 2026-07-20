"""
COERENZA del ledger tassa di soggiorno (bug provato 2026-07-16).

La tassa (pass-through alla citta') era registrata nel ledger al pagamento ma NON stornata
quando la prenotazione veniva rimborsata (la tassa e' restituita all'ospite) -> `totale_riscosso`
(rendicontazione citta') sovra-contava i rimborsati -> report/versamento gonfiato. Fix: storno
del ledger sui percorsi di rimborso (cancellazione ospite/host, rimborso admin).
"""
import json
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_ts"


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://t/" + secrets.token_hex(4), "id": "cs_" + secrets.token_hex(4)}


class TestTassaStorno(unittest.TestCase):
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
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db",
            db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db",
            stripe_secret_key="sk", stripe_webhook_secret=WH,
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sys, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@ts.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.tok = c["token"]
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa", "titolo": "Casa", "citta": "Roma", "prezzo_notte_cents": 50000,
                "capacita": 4, "politica_cancellazione": "flessibile",
                "tassa_pp_notte_cents": 200}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa", "da": "2026-09-01", "a": "2026-09-30",
                "unita_totali": 1, "prezzo_netto_cents": 50000}, {"X-Host-Token": self.tok})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _book_paga(self, ci, co):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@ts.it"})
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": b["riferimento"]}}}})
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
        return b

    def _ledger(self):
        return self.sys.tassa_comunale.totale_riscosso("Roma")

    def test_cancellazione_ospite_storna_la_tassa(self):
        b = self._book_paga("2026-09-05", "2026-09-08")
        self.assertEqual(self._ledger(), 1200, "setup: tassa collezionata al pagamento")
        s, canc = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200, canc)
        self.assertEqual(canc.get("tassa_rimborsata_cents"), 1200)
        self.assertEqual(self._ledger(), 0, "REGRESSIONE: ledger citta' sovra-conta un rimborsato")

    def test_paga_e_NON_cancella_la_tassa_resta(self):
        self._book_paga("2026-09-12", "2026-09-15")
        self.assertEqual(self._ledger(), 1200, "una prenotazione non cancellata deve restare a ledger")

    def test_rimborso_admin_storna_la_tassa(self):
        b = self._book_paga("2026-09-20", "2026-09-23")
        self.assertEqual(self._ledger(), 1200)
        s, adm = self.g("GET", "/api/admin/prenotazioni", None, {"X-Admin-Key": "ak"})
        idem = adm["prenotazioni"][0]["idem_key"]
        self.g("POST", "/api/admin/rimborso",
               {"alloggio_id": "casa", "check_in": "2026-09-20", "check_out": "2026-09-23",
                "idem_key": idem}, {"X-Admin-Key": "ak"})
        self.assertEqual(self._ledger(), 0, "il rimborso admin deve stornare la tassa")


if __name__ == "__main__":
    unittest.main(verbosity=2)
