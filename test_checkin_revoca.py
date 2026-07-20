"""Collaudo BUG #30 (2026-07-17, bombardamento concorrente check-in/smart-pass):
la CANCELLAZIONE non revocava il CHECK-IN.

BUG PROVATO (40/40 seed in concorrenza, e anche SEQUENZIALE): un ospite fa il check-in
(`completato=True`), poi cancella (o viene rimborsato dall'host/admin) -> la riga check-in
restava `completato=True` -> `sblocca()` avrebbe emesso lo smart-pass su una prenotazione
CANCELLATA (sblocco porta indebito quando c'e' una serratura vera) + ospiti-fantasma
nell'export Alloggiati Web (dati di ospiti che non soggiorneranno).

Fix: `fase127.revoca` (TOMBSTONE permanente completato=0 + revocato=1) cablato nei 3
percorsi di cancellazione (`_cancella_prenotazione`, `_host_cancella`, `_admin_rimborso`);
`pre_registra` in BEGIN IMMEDIATE rifiuta se `revocato` -> chiude la TOCTOU in cui una
pre-registrazione in volo re-inseriva DOPO la revoca (la cancellazione e' terminale).
"""
import datetime
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

WH = "whsec_ck"


class TestCheckinRevoca(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(
            lambda u, b, h: {"url": "https://x/cs", "id": "cs_1"})

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_garanzia=f"{d}/g.db", db_checkin=f"{d}/ck.db", commissione_bps=1500, psp_bps=300,
            stripe_secret_key="sk", stripe_webhook_secret=WH,
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@ck.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]
        oggi = datetime.date.today()
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa", "titolo": "C", "citta": "Roma", "prezzo_notte_cents": 20000,
                "capacita": 6, "politica_cancellazione": "flessibile"}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa", "da": oggi.isoformat(),
                "a": (oggi + datetime.timedelta(days=30)).isoformat(),
                "unita_totali": 1, "prezzo_netto_cents": 20000}, {"X-Host-Token": self.tok})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _prenota_paga_checkin(self, giorni=10):
        oggi = datetime.date.today()
        ci = (oggi + datetime.timedelta(days=giorni)).isoformat()
        co = (oggi + datetime.timedelta(days=giorni + 2)).isoformat()
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@ck.it"})
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": b["riferimento"]}}}})
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
        s, o = self.g("POST", "/api/checkin/pre_registra",
                      {"voucher_token": b["voucher_token"],
                       "ospiti": [{"nome": "Mario Rossi", "documento": "AB123456"}]})
        self.assertEqual(s, 200, o)
        self.assertTrue(self.sis.checkin.completato(b["riferimento"]))
        return b

    def test_cancellazione_ospite_revoca_checkin(self):
        b = self._prenota_paga_checkin()
        s, _ = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200)
        self.assertFalse(self.sis.checkin.completato(b["riferimento"]),
                         "check-in NON revocato dopo cancellazione ospite")
        self.assertIsNone(self.sis.checkin.sblocca(b["riferimento"], "casa"),
                          "smart-pass ancora emettibile su cancellata")

    def test_host_cancella_revoca_checkin(self):
        b = self._prenota_paga_checkin()
        s, _ = self.g("POST", "/api/host/cancella", {"riferimento": b["riferimento"]},
                      {"X-Host-Token": self.tok})
        self.assertEqual(s, 200)
        self.assertFalse(self.sis.checkin.completato(b["riferimento"]))

    def test_admin_rimborso_revoca_checkin(self):
        b = self._prenota_paga_checkin()
        _, adm = self.g("GET", "/api/admin/prenotazioni", None, {"X-Admin-Key": "ak"})
        idem = next(p["idem_key"] for p in adm["prenotazioni"]
                    if str(p["idem_key"])[:24] == b["riferimento"])
        s, _ = self.g("POST", "/api/admin/rimborso",
                      {"alloggio_id": "casa", "check_in": b.get("check_in") or "",
                       "check_out": b.get("check_out") or "", "idem_key": idem},
                      {"X-Admin-Key": "ak"})
        # idem_key completo garantisce rif = idem[:24]
        self.assertIn(s, (200, 409))
        if s == 200:
            self.assertFalse(self.sis.checkin.completato(b["riferimento"]))

    def test_tombstone_blocca_reregistrazione_dopo_revoca(self):
        b = self._prenota_paga_checkin()
        self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        # una pre-registrazione TARDIVA (tombstone gia' posato) deve essere respinta
        s, o = self.g("POST", "/api/checkin/pre_registra",
                      {"voucher_token": b["voucher_token"],
                       "ospiti": [{"nome": "Ghost Guest", "documento": "ZZ999999"}]})
        self.assertIn(s, (409,), o)
        self.assertFalse(self.sis.checkin.completato(b["riferimento"]))

    def test_concorrenza_prereg_vs_cancel_mai_completato_su_cancellata(self):
        b = self._prenota_paga_checkin(giorni=15)
        rif, vt = b["riferimento"], b["voucher_token"]
        N = 20
        barrier = threading.Barrier(N + 1)

        def prereg(i):
            barrier.wait()
            self.g("POST", "/api/checkin/pre_registra",
                   {"voucher_token": vt,
                    "ospiti": [{"nome": "O %d" % i, "documento": "AB1234%d" % (i % 10)}]})

        def cancel():
            barrier.wait()
            self.g("POST", "/api/concierge/cancella", {"voucher_token": vt})

        ths = [threading.Thread(target=prereg, args=(i,)) for i in range(N)]
        ths.append(threading.Thread(target=cancel))
        for t in ths:
            t.start()
        for t in ths:
            t.join(30)
        st = self.sis.pagamenti_pendenti.info(rif)
        if st and st.get("stato") in ("rimborsato", "cancellata_host"):
            self.assertFalse(self.sis.checkin.completato(rif),
                             "TOCTOU: check-in completato su prenotazione cancellata")


if __name__ == "__main__":
    unittest.main(verbosity=2)
