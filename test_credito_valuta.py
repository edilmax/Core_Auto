"""Collaudo ramo MULTI-VALUTA del credito (2026-07-16, metodo libro) — like-for-like.

BUG PROVATO: i token credito (`credito_fondatore` waitlist + Credito Viaggio anti-
rimpianto) portavano `credito_cents` SENZA valuta -> le unita' venivano applicate a
QUALSIASI valuta d'annuncio: (a) un credito €5 su un annuncio JPY scontava ¥500 (≈€3:
promessa disattesa); (b) al contrario, un Credito Viaggio nato da una penale in valuta
DEBOLE (5000 unita' minori = pochi euro-cent) si spendeva come €50 di sconto su un
annuncio EUR — leak di valore cross-valuta FARMABILE (self-booking + cancellazione).

Fix: il credito porta la SUA `valuta` (fase158 = EUR; anti-rimpianto = valuta della
prenotazione cancellata; legacy senza campo = EUR) e `fase59._sconto_credito` sconta
SOLO annunci nella stessa valuta (mai FX, onesto e conservativo).
"""
import datetime
import json
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE


class TestCreditoValuta(unittest.TestCase):
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
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/acc.db",
            db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db", db_garanzia=f"{d}/g.db",
            db_domanda=f"{d}/dom.db", db_credito_usati=f"{d}/cu.db",
            commissione_bps=1500, psp_bps=300,
            stripe_secret_key="sk_test_x", stripe_webhook_secret="whsec_x",
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/ko"))
        self.r = crea_router(self.sis, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@cv.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]
        self.oggi = datetime.date.today()
        for slug, val in (("casa-eur", "EUR"), ("casa-jpy", "JPY")):
            self.g("POST", "/api/host/pubblica",
                   {"slug": slug, "titolo": slug, "citta": "Roma",
                    "prezzo_notte_cents": 50000, "capacita": 2, "valuta": val,
                    "politica_cancellazione": "rigida"}, {"X-Host-Token": self.tok})
            self.g("POST", "/api/host/disponibilita_range",
                   {"alloggio_id": slug, "da": self.oggi.isoformat(),
                    "a": (self.oggi + datetime.timedelta(days=40)).isoformat(),
                    "unita_totali": 2, "prezzo_netto_cents": 50000},
                   {"X-Host-Token": self.tok})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None,
                               h or {})

    def _quota(self, slug, giorni=10, cred=None):
        b = {"alloggio_id": slug,
             "check_in": (self.oggi + datetime.timedelta(days=giorni)).isoformat(),
             "check_out": (self.oggi + datetime.timedelta(days=giorni + 2)).isoformat(),
             "party": 2}
        if cred:
            b["credito_token"] = cred
        s, q = self.g("POST", "/api/concierge/quote", b)
        self.assertEqual(s, 200, q)
        return q

    def _credito_eur(self):
        _, dom = self.g("POST", "/api/domanda", {"email": "cli@cv.it", "citta": "roma"})
        return dom["credito_token"]

    def test_credito_eur_su_annuncio_eur(self):
        q = self._quota("casa-eur", cred=self._credito_eur())
        self.assertEqual(q["sconto_credito_cents"], 500)      # regressione zero

    def test_credito_eur_su_annuncio_jpy_zero(self):
        q = self._quota("casa-jpy", cred=self._credito_eur())
        self.assertEqual(q["sconto_credito_cents"], 0,
                         "€5 NON valgono ¥500: cross-valuta = sconto 0")

    def test_credito_viaggio_eredita_la_valuta(self):
        # prenota+paga+cancella su JPY con penale (arrivo a 2gg: niente ripensamento 48h)
        q = self._quota("casa-jpy", giorni=2)
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@cv.it"})
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": b["riferimento"]}}}})
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": firma_di_test(pl, "whsec_x", int(time.time()))})
        s, canc = self.g("POST", "/api/concierge/cancella",
                         {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200, canc)
        self.assertGreater(canc["credito_viaggio_cents"], 0)
        cv_tok = canc["credito_viaggio_token"]
        self.assertEqual(self.sis.firma.decodifica(cv_tok).get("valuta"), "JPY")
        # spendibile SOLO su annunci JPY
        self.assertGreater(self._quota("casa-jpy", giorni=20,
                                       cred=cv_tok)["sconto_credito_cents"], 0)
        self.assertEqual(self._quota("casa-eur", giorni=20,
                                     cred=cv_tok)["sconto_credito_cents"], 0,
                         "LEAK chiuso: credito nato in JPY non si spende come EUR")

    def test_legacy_senza_valuta_vale_eur(self):
        # un token emesso PRIMA del fix (senza campo valuta) deve valere come EUR
        import secrets
        legacy = self.sis.firma.codifica({"tipo": "credito_fondatore", "email": "x@x.it",
                                          "citta": "roma", "credito_cents": 500,
                                          "exp": int(time.time()) + 86400,
                                          "nonce": secrets.token_hex(8)})
        self.assertEqual(self._quota("casa-eur", giorni=24,
                                     cred=legacy)["sconto_credito_cents"], 500)
        self.assertEqual(self._quota("casa-jpy", giorni=24,
                                     cred=legacy)["sconto_credito_cents"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
