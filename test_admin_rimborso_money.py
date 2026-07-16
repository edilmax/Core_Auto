"""
COERENZA denaro del RIMBORSO ADMIN (bug provato 2026-07-16).

Il bottone "Rimborsa" del pannello admin (`/api/admin/rimborso`) liberava SOLO le date, ma —
a differenza della cancellazione ospite/host — NON metteva in sicurezza i soldi: l'host restava
'maturato' e l'escrow si auto-rilasciava a 24h -> PAGAVAMO L'HOST mentre rimborsavamo l'ospite
= PERDITA PIENA. Fix: il rimborso admin trattiene il payout, chiude l'escrow, invalida il
pendente (riferimento = idem_key[:24]). Qui si prova che dopo il rimborso l'host NON viene pagato.
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

WH = "whsec_ar"


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://t/" + secrets.token_hex(4), "id": "cs_" + secrets.token_hex(4)}


class TestAdminRimborsoMoney(unittest.TestCase):
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
            commissione_bps=1000, psp_bps=0, stripe_secret_key="sk",
            stripe_webhook_secret=WH, stripe_success_url="https://x/ok",
            stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sys, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@ar.it", "password": "password1", "accetta_termini": True,
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

    def _maturato(self):
        return self.sys.payout.riepilogo(self.hid).get("EUR", {}).get("maturato", 0)

    def test_rimborso_admin_non_paga_l_host(self):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": "2026-09-05",
                       "check_out": "2026-09-08", "party": 2})
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@ar.it"})
        rif = b["riferimento"]
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": rif}}}})
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
        self.assertGreater(self._maturato(), 0, "setup: la prenotazione dev'essere pagata")
        # l'admin recupera l'idem_key come nel pannello, poi rimborsa
        s, adm = self.g("GET", "/api/admin/prenotazioni", None, {"X-Admin-Key": "ak"})
        idem = adm["prenotazioni"][0]["idem_key"]
        s, res = self.g("POST", "/api/admin/rimborso",
                        {"alloggio_id": "casa", "check_in": "2026-09-05",
                         "check_out": "2026-09-08", "idem_key": idem}, {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, res)
        # DOPO il rimborso: l'host non incassa piu' e l'escrow non si auto-rilascia
        self.assertEqual(self._maturato(), 0, "REGRESSIONE: payout host non trattenuto -> doppia perdita")
        self.assertEqual(self.sys.garanzia.stato(rif).get("stato"), "annullato",
                         "REGRESSIONE: escrow ancora aperto -> si auto-rilascia all'host")
        self.assertEqual(self.sys.pagamenti_pendenti.info(rif).get("stato"), "rimborsato")
        # l'auto-rilascio a 24h NON deve pagare l'host
        ril = self.sys.garanzia.auto_rilascia(ora_ts=int(time.time()) + 10**9, dettagli=True)
        self.assertEqual(ril, [], "REGRESSIONE: l'host viene pagato su prenotazione rimborsata")

    def test_rimborso_admin_idempotente(self):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": "2026-09-15",
                       "check_out": "2026-09-17", "party": 2})
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@ar.it"})
        s, adm = self.g("GET", "/api/admin/prenotazioni", None, {"X-Admin-Key": "ak"})
        idem = adm["prenotazioni"][0]["idem_key"]
        body = {"alloggio_id": "casa", "check_in": "2026-09-15",
                "check_out": "2026-09-17", "idem_key": idem}
        s1, _ = self.g("POST", "/api/admin/rimborso", body, {"X-Admin-Key": "ak"})
        s2, r2 = self.g("POST", "/api/admin/rimborso", body, {"X-Admin-Key": "ak"})
        self.assertEqual((s1, s2), (200, 200), "il rimborso ripetuto non deve fallire")
        self.assertTrue(r2.get("idempotente"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
