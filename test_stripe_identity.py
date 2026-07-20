"""Collaudo STRIPE IDENTITY (Incremento 11): verifica documentale automatica, no-PII.

Il documento viaggia dal telefono dell'host DIRETTAMENTE a Stripe (flusso hosted):
da noi vivono SOLO gli esiti (fase143). GATED da env STRIPE_IDENTITY_KEY: la macchina
è pronta, si accende con la chiave.
Invarianti:
  1. SENZA chiave: kyc_avvia -> 503 onesto; kyc_stato -> configurato False;
  2. CON chiave (provider finto): avvia -> sessione creata, stato 'in_corso', url
     hosted restituito; l'header porta la chiave; il body MAI dati del documento;
  3. webhook identity verified/canceled (firma valida) -> verificato / respinto
     (respinto è RITENTABILE: nuova avvia riparte);
  4. SYNC live: in_corso + Stripe dice 'verified' -> kyc_stato transita da solo;
  5. dashboard Verifiche: colonna identity in lista e dettaglio; fascicolo la include;
  6. DOPPIA SICUREZZA SOVRANA: host con identity VERIFICATA ma verifica manuale
     REVOCATA -> i bonifici restano FERMI (il super-admin comanda sempre);
  7. PRIVACY: nel registro kyc solo stato+session_ref (vs_...), nessun altro campo.
"""
import datetime
import json
import os
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
import fase143_kyc_host as f143
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE

AK = {"X-Admin-Key": "ak"}


class _ConnectContatore:
    def __init__(self):
        self.chiamate = []

    def trasferisci(self, acct, importo, valuta, rif):
        self.chiamate.append((acct, int(importo), valuta, str(rif)))
        return "tr_ok"


class TestStripeIdentity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(
            lambda u, b, h: {"url": "https://checkout.stripe.test/cs", "id": "cs_1"})

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        os.environ.pop("STRIPE_IDENTITY_KEY", None)
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"I" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/acc.db",
            db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db", db_garanzia=f"{d}/g.db",
            db_finanza=f"{d}/fin.db", db_kyc=f"{d}/kyc.db", bunker_password="SuperPw@1",
            commissione_bps=1000, psp_bps=300,
            stripe_secret_key="sk_test_x", stripe_webhook_secret="whsec_x",
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/ko"))
        self.connect = _ConnectContatore()
        self.sis.connect = self.connect
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@idn.it", "password": "password1",
                       "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.hid, self.tok = c["host_id"], c["token"]
        self.hk = {"X-Host-Token": self.tok}
        # provider FINTO: registra le chiamate, mai rete vera
        self.chiamate_api = []
        orig_crea = f143.stripe_identity_crea

        def _fetch_finto(percorso, dati, chiave):
            self.chiamate_api.append((percorso, dati, chiave))
            if dati is not None:                     # create
                return {"id": "vs_test_1", "url": "https://verify.stripe.test/vs_test_1"}
            return {"status": self._stato_remoto}    # get
        self._fetch_finto = _fetch_finto
        self._stato_remoto = "processing"
        # patch: le funzioni modulo usano fetch iniettabile -> le richiamo via wrapper
        self._orig_crea = f143.stripe_identity_crea
        self._orig_stato = f143.stripe_identity_stato
        f143_crea = self._orig_crea
        f143_stato = self._orig_stato
        f143.stripe_identity_crea = (lambda chiave, hid, ret, **k:
                                     f143_crea(chiave, hid, ret,
                                               fetch=self._fetch_finto))
        f143.stripe_identity_stato = (lambda chiave, sid, **k:
                                      f143_stato(chiave, sid,
                                                 fetch=self._fetch_finto))

    def tearDown(self):
        f143.stripe_identity_crea = self._orig_crea
        f143.stripe_identity_stato = self._orig_stato
        os.environ.pop("STRIPE_IDENTITY_KEY", None)
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None,
                               h or {})

    # ── 1) GATED: senza chiave la macchina è pronta ma spenta ─────────────────
    def test_gated_senza_chiave(self):
        s, d = self.g("GET", "/api/host/kyc_stato", None, self.hk)
        self.assertEqual(s, 200)
        self.assertFalse(d["configurato"])
        self.assertEqual(d["stato"], "non_avviata")
        s, d = self.g("POST", "/api/host/kyc_avvia", {}, self.hk)
        self.assertEqual(s, 503)
        self.assertEqual(d["errore"], "identity_non_configurato")

    # ── 2) avvio con chiave: sessione hosted + in_corso ───────────────────────
    def test_avvia_con_chiave(self):
        os.environ["STRIPE_IDENTITY_KEY"] = "sk_ident_test"
        s, d = self.g("POST", "/api/host/kyc_avvia", {}, self.hk)
        self.assertEqual(s, 200, d)
        self.assertEqual(d["stato"], "in_corso")
        self.assertTrue(d["url"].startswith("https://verify.stripe.test/"))
        self.assertEqual(self.sis.kyc.stato(self.hid), "in_corso")
        self.assertEqual(self.sis.kyc.sessione(self.hid), "vs_test_1")
        percorso, dati, chiave = self.chiamate_api[0]
        self.assertEqual(chiave, "sk_ident_test")            # usa la chiave giusta
        self.assertEqual(dati["metadata[host_id]"], self.hid)
        self.assertNotIn("document", json.dumps(dati).lower().replace(
            '"type": "document"', ""))                       # nessun dato documento nostro

    # ── 3) webhook verified/canceled -> esiti; respinto è ritentabile ─────────
    def test_webhook_esiti(self):
        os.environ["STRIPE_IDENTITY_KEY"] = "sk_ident_test"
        self.g("POST", "/api/host/kyc_avvia", {}, self.hk)

        def _wh(status):
            pl = json.dumps({"type": "identity.verification_session." + status,
                             "data": {"object": {"id": "vs_test_1", "status": status,
                                                 "metadata": {"host_id": self.hid}}}})
            sig = firma_di_test(pl, "whsec_x", int(time.time()))
            return self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                                   {"Stripe-Signature": sig})[0]
        self.assertEqual(_wh("canceled"), 200)
        self.assertEqual(self.sis.kyc.stato(self.hid), "respinto")
        s, d = self.g("POST", "/api/host/kyc_avvia", {}, self.hk)   # RITENTA
        self.assertEqual(s, 200)
        self.assertEqual(_wh("verified"), 200)
        self.assertEqual(self.sis.kyc.stato(self.hid), "verificato")

    # ── 4) SYNC live: in_corso + Stripe 'verified' -> transita da solo ────────
    def test_sync_live(self):
        os.environ["STRIPE_IDENTITY_KEY"] = "sk_ident_test"
        self.g("POST", "/api/host/kyc_avvia", {}, self.hk)
        self._stato_remoto = "verified"
        s, d = self.g("GET", "/api/host/kyc_stato", None, self.hk)
        self.assertEqual(d["stato"], "verificato")

    # ── 5) dashboard: colonna identity in lista, dettaglio e fascicolo ────────
    def test_dashboard_colonna_identity(self):
        os.environ["STRIPE_IDENTITY_KEY"] = "sk_ident_test"
        self.g("POST", "/api/host/kyc_avvia", {}, self.hk)
        s, d = self.g("GET", "/api/admin/verifiche", None, AK)
        riga = {h["host_id"]: h for h in d["host"]}[self.hid]
        self.assertEqual(riga["documenti"]["identity"], "in_corso")
        s, d = self.g("GET", "/api/admin/verifiche/dettaglio", None, AK,
                      {"host_id": self.hid})
        self.assertIn(d["identity"], ("in_corso", "verificato"))
        s, out = self.g("POST", "/api/bunker/login", {"codice": "SuperPw@1"},
                        {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9"})
        hb = {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9",
              "X-Bunker-Session": out["sessione"]}
        s, d = self.g("GET", "/api/admin/verifiche/fascicolo", None, hb,
                      {"host_id": self.hid})
        self.assertEqual(d["fascicolo"]["identity"]["session_ref"], "vs_test_1")

    # ── 6) DOPPIA SICUREZZA: la revoca manuale comanda anche su identity ok ───
    def test_revoca_manuale_sovrana(self):
        os.environ["STRIPE_IDENTITY_KEY"] = "sk_ident_test"
        self.sis.kyc.registra_avvio(self.hid, "vs_test_1")
        self.sis.kyc.conferma(self.hid, "verificato")        # Stripe dice OK
        s, out = self.g("POST", "/api/bunker/login", {"codice": "SuperPw@1"},
                        {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9"})
        hb = {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9",
              "X-Bunker-Session": out["sessione"]}
        s, _ = self.g("POST", "/api/admin/verifica_stato",
                      {"host_id": self.hid, "stato": "revocato",
                       "motivo": "frode sospetta"}, hb)
        self.assertEqual(s, 200)
        # prenotazione pagata + payout: il transfer NON parte (manuale > automatico)
        oggi = datetime.date.today()
        self.g("POST", "/api/host/pubblica", {"slug": "casa-i", "titolo": "I",
               "citta": "Roma", "prezzo_notte_cents": 10000, "capacita": 2}, self.hk)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa-i",
               "da": oggi.isoformat(),
               "a": (oggi + datetime.timedelta(days=40)).isoformat(),
               "unita_totali": 1, "prezzo_netto_cents": 10000}, self.hk)
        _, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "casa-i",
                      "check_in": (oggi + datetime.timedelta(days=20)).isoformat(),
                      "check_out": (oggi + datetime.timedelta(days=22)).isoformat(),
                      "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "o@idn.it"})
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata":
                                             {"riferimento": b["riferimento"]}}}})
        sig = firma_di_test(pl, "whsec_x", int(time.time()))
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": sig})
        self.sis.registro_host.imposta_stripe_account(self.hid, "acct_x")
        netto = self.sis.payout.riepilogo(self.hid)["EUR"]["maturato"]
        self.r._trasferisci_all_host(b["riferimento"], netto)
        self.assertEqual(self.connect.chiamate, [])          # FERMO: il manuale comanda

    # ── 7) PRIVACY: nel registro solo stato + session_ref ─────────────────────
    def test_privacy_solo_esiti(self):
        os.environ["STRIPE_IDENTITY_KEY"] = "sk_ident_test"
        self.g("POST", "/api/host/kyc_avvia", {}, self.hk)
        import sqlite3
        con = sqlite3.connect(f"{self.dir}/kyc.db")
        cols = [r[1] for r in con.execute("PRAGMA table_info(kyc)")]
        con.close()
        self.assertEqual(set(cols), {"host_id", "stato", "session_ref", "ts"})


if __name__ == "__main__":
    unittest.main()
