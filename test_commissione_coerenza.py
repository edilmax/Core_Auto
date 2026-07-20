"""
COERENZA commissione end-to-end: il payout REALE dell'host == `netto_host_cents` del preventivo.
La promessa centrale ("ti diciamo quanto incassi, e incassi ESATTAMENTE quello") deve reggere
per ogni commissione/costo-carta/fonte. Se diverge, l'host e' promesso X e pagato Y = bug grave.
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

WH = "whsec_cc"


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://t/" + secrets.token_hex(4), "id": "cs_" + secrets.token_hex(4)}


class TestCommissioneCoerente(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def _run(self, bps, psp, fonte):
        d = tempfile.mkdtemp()
        try:
            sysx = crea_sistema(ConfigCasaVIP(
                abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
                db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
                db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db",
                db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db",
                commissione_bps=bps, psp_bps=psp, stripe_secret_key="sk",
                stripe_webhook_secret=WH, stripe_success_url="https://x/ok",
                stripe_cancel_url="https://x/no"))
            r = crea_router(sysx, host_key="hk", base_url="https://bookinvip.com")

            def g(m, p, b=None, h=None):
                return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})
            s, c = g("POST", "/api/host/registrazione",
                     {"email": "h@cc.it", "password": "password1", "accetta_termini": True,
                      "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                      "versione": CONTRATTO_HOST_VERSIONE})
            tok, hid = c["token"], c["host_id"]
            g("POST", "/api/host/pubblica",
              {"slug": "casa", "titolo": "Casa", "citta": "Roma", "prezzo_notte_cents": 50000,
               "capacita": 4, "politica_cancellazione": "flessibile"}, {"X-Host-Token": tok})
            g("POST", "/api/host/disponibilita_range",
              {"alloggio_id": "casa", "da": "2026-09-01", "a": "2026-09-30",
               "unita_totali": 1, "prezzo_netto_cents": 50000}, {"X-Host-Token": tok})
            s, q = g("POST", "/api/concierge/quote",
                     {"alloggio_id": "casa", "check_in": "2026-09-05", "check_out": "2026-09-08",
                      "party": 2, "fonte": fonte})
            self.assertEqual(s, 200, q)
            nh = q["netto_host_cents"]
            s, b = g("POST", "/api/concierge/book",
                     {"quote_token": q["quote_token"], "email": "cli@cc.it"})
            self.assertEqual(s, 201, b)
            rif = b["riferimento"]
            pl = json.dumps({"type": "checkout.session.completed",
                             "data": {"object": {"metadata": {"riferimento": rif}}}})
            r.gestisci("POST", "/api/payments/webhook", {}, pl,
                       {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
            maturato = sysx.payout.riepilogo(hid).get("EUR", {}).get("maturato", 0)
            self.assertEqual(maturato, nh,
                             f"bps={bps} psp={psp} fonte={fonte}: host promesso {nh}, pagato {maturato}")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_marketplace_con_costo_carta(self):
        self._run(1000, 300, "marketplace")     # config PROD tipica

    def test_diretto_e_fisso_5pct(self):
        self._run(1500, 300, "diretto")         # diretto resta 5% anche con config 15%

    def test_commissione_alta(self):
        self._run(1500, 0, "marketplace")


if __name__ == "__main__":
    unittest.main(verbosity=2)
