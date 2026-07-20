"""
COERENZA delle METRICHE AVANZATE host (bug provato 2026-07-16).

`/api/host/metriche_avanzate` passava a `calcola_metriche` le prenotazioni da
`elenco_prenotazioni` (movimenti), che NON portano prezzo/valuta/voto -> revenue/ADR/RevPAR/rating
SEMPRE 0 (la dashboard mostrava incasso €0 con prenotazioni reali). Fix: arricchimento dal
pendente PAGATO + recensioni, e metriche PER valuta (¥ + € non si sommano). Qui:
  (1) single-currency: revenue reale non-zero; (2) non pagata non conta; (3) multi-valuta separata.
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

WH = "whsec_met"


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://t/" + secrets.token_hex(4), "id": "cs_" + secrets.token_hex(4)}


class TestMetricheAvanzate(unittest.TestCase):
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
            valuta="EUR", stripe_secret_key="sk", stripe_webhook_secret=WH,
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@met.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.tok = c["token"]

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _listing(self, slug, valuta, prezzo):
        self.g("POST", "/api/host/pubblica",
               {"slug": slug, "titolo": slug, "citta": "X", "prezzo_notte_cents": prezzo,
                "capacita": 4, "politica_cancellazione": "flessibile", "valuta": valuta},
               {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": slug, "da": "2026-09-01", "a": "2026-09-30",
                "unita_totali": 1, "prezzo_netto_cents": prezzo, "valuta": valuta},
               {"X-Host-Token": self.tok})

    def _book(self, slug, ci, co, paga=True):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": slug, "check_in": ci, "check_out": co, "party": 2})
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@met.it"})
        if paga:
            pl = json.dumps({"type": "checkout.session.completed",
                             "data": {"object": {"metadata": {"riferimento": b["riferimento"]}}}})
            self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                            {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
        return b

    def _metriche(self):
        s, m = self.g("GET", "/api/host/metriche_avanzate", None, {"X-Host-Token": self.tok})
        self.assertEqual(s, 200, m)
        return m

    def test_revenue_reale_non_zero(self):
        self._listing("casa", "EUR", 50000)
        self._book("casa", "2026-09-05", "2026-09-08")       # 3 notti pagate
        self._book("casa", "2026-09-12", "2026-09-15")       # 3 notti pagate
        m = self._metriche()["metriche"]
        self.assertEqual(m["revenue_cents"], 300000, "REGRESSIONE: revenue a zero con prenotazioni pagate")
        self.assertEqual(m["adr_cents"], 50000)
        self.assertEqual(m["notti_vendute"], 6)

    def test_hold_non_pagato_non_conta(self):
        self._listing("casa", "EUR", 50000)
        self._book("casa", "2026-09-05", "2026-09-08", paga=False)   # solo hold
        m = self._metriche()["metriche"]
        self.assertEqual(m["revenue_cents"], 0, "un hold non pagato non e' revenue")

    def test_multivaluta_non_si_somma(self):
        self._listing("tokyo", "JPY", 20000)
        self._listing("roma", "EUR", 10000)
        self._book("tokyo", "2026-09-05", "2026-09-07")      # 2 notti JPY -> 40000 yen
        self._book("roma", "2026-09-05", "2026-09-08")       # 3 notti EUR -> 30000 cent
        m = self._metriche()
        per = m.get("metriche_per_valuta", {})
        self.assertIn("JPY", per)
        self.assertIn("EUR", per)
        self.assertEqual(per["JPY"]["revenue_cents"], 40000)
        self.assertEqual(per["EUR"]["revenue_cents"], 30000)
        # il riquadro singolo NON deve essere la somma mescolata 70000
        self.assertNotEqual(m["metriche"]["revenue_cents"], 70000,
                            "REGRESSIONE: valute diverse sommate in un numero senza senso")


if __name__ == "__main__":
    unittest.main(verbosity=2)
