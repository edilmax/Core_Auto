"""
Collaudo del FIX single-use del Credito Fondatore/Viaggio (fase167).

BUG PROVATO (2026-07-16): il token `credito_fondatore` era un BEARER riusabile all'infinito
-> lo stesso credito da €50 scontava OGNI prenotazione (erosione sistematica del ricavo).
FIX: registro durevole dei crediti consumati; consumo alla FINALIZZAZIONE della prenotazione,
check al preventivo. Qui si prova: (1) lo store atomico nuovo/stesso/diverso; (2) end-to-end
un credito sconta la 1a prenotazione e NON le successive; (3) un credito mai usato funziona
(niente regressione); (4) fail-open (store rotto -> la prenotazione NON viene bloccata).
"""
import json
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE
from fase167_credito_single_use import crea_registro_crediti_usati

WHSEC = "whsec_cu"


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://checkout.test/" + secrets.token_hex(6),
            "id": "cs_test_" + secrets.token_hex(6)}


class TestRegistroCreditiUsati(unittest.TestCase):
    """Lo store puro: consumo atomico e stati nuovo/stesso/diverso."""
    def test_consuma_atomico(self):
        s = crea_registro_crediti_usati(":memory:")
        s.inizializza_schema()
        self.assertFalse(s.usato("cid1"))
        self.assertEqual(s.consuma("cid1", "REF1"), "nuovo")
        self.assertTrue(s.usato("cid1"))
        # stessa prenotazione -> idempotente (replay del book non allarma)
        self.assertEqual(s.consuma("cid1", "REF1"), "stesso")
        # prenotazione DIVERSA -> riuso rilevato
        self.assertEqual(s.consuma("cid1", "REF2"), "diverso")
        # credito vuoto -> 'nuovo' (niente da tracciare, non blocca nulla)
        self.assertEqual(s.consuma("", "REF3"), "nuovo")
        self.assertFalse(s.usato(""))

    def test_durevole_su_file(self):
        d = tempfile.mkdtemp()
        try:
            s1 = crea_registro_crediti_usati(f"{d}/cu.db")
            s1.inizializza_schema()
            s1.consuma("cidX", "REFX")
            s2 = crea_registro_crediti_usati(f"{d}/cu.db")   # nuovo handle, stesso file
            self.assertTrue(s2.usato("cidX"), "il consumo deve sopravvivere cross-worker")
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestSingleUseE2E(unittest.TestCase):
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
            db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db", db_credito_usati=f"{d}/cu.db",
            commissione_bps=1000, psp_bps=0,
            stripe_secret_key="sk_test_cu", stripe_webhook_secret=WHSEC,
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@cu.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa", "titolo": "Casa", "citta": "Roma",
                "prezzo_notte_cents": 50000, "capacita": 4,
                "politica_cancellazione": "flessibile"}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa", "da": "2026-09-01", "a": "2026-12-31",
                "unita_totali": 3, "prezzo_netto_cents": 50000}, {"X-Host-Token": self.tok})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, metodo, path, body=None, headers=None):
        return self.r.gestisci(metodo, path, {},
                               json.dumps(body) if body is not None else None, headers or {})

    def _credito(self, cents=5000, nonce="n1"):
        return self.sys.firma.codifica({"tipo": "credito_fondatore", "email": "x@x.it",
                                        "citta": "roma", "credito_cents": cents,
                                        "exp": int(time.time()) + 30 * 86400, "nonce": nonce})

    def _quote(self, ci, co, credito=None):
        body = {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2}
        if credito:
            body["credito_token"] = credito
        s, q = self.g("POST", "/api/concierge/quote", body)
        self.assertEqual(s, 200, q)
        return q

    def _book(self, q):
        return self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@x.it"})

    def test_credito_si_spende_una_volta_sola(self):
        cr = self._credito()
        q1 = self._quote("2026-09-05", "2026-09-08", cr)
        self.assertGreater(q1["sconto_credito_cents"], 0, "il credito deve scontare la 1a")
        s1, _ = self._book(q1)
        self.assertEqual(s1, 201)                       # finalizzata -> credito consumato
        # STESSO credito su prenotazioni successive -> NIENTE sconto
        q2 = self._quote("2026-10-05", "2026-10-08", cr)
        self.assertEqual(q2["sconto_credito_cents"], 0, "REGRESSIONE: credito riusabile")
        q3 = self._quote("2026-11-05", "2026-11-08", cr)
        self.assertEqual(q3["sconto_credito_cents"], 0, "REGRESSIONE: credito riusabile")

    def test_book_idempotente_non_rompe(self):
        cr = self._credito(nonce="n2")
        q = self._quote("2026-09-15", "2026-09-18", cr)
        s1, _ = self._book(q)
        s2, _ = self._book(q)                            # replay dello stesso book
        self.assertEqual((s1, s2), (201, 201), "il replay idempotente non deve fallire")

    def test_credito_mai_usato_funziona(self):
        # niente regressione: un credito fresco applica lo sconto normalmente
        q = self._quote("2026-09-25", "2026-09-28", self._credito(nonce="n3"))
        self.assertGreater(q["sconto_credito_cents"], 0)

    def test_fail_open_store_rotto_non_blocca_prenotazione(self):
        # se lo store solleva, la prenotazione NON deve essere bloccata (fail-open)
        class _Rotto:
            def usato(self, cid):
                raise RuntimeError("store giu'")

            def consuma(self, cid, rif):
                raise RuntimeError("store giu'")
        self.sys.credito_usati = _Rotto()
        # ricablo il concierge allo store rotto (il router usa self.sys.credito_usati al book)
        self.sys.concierge._credito_store = _Rotto()
        q = self._quote("2026-10-15", "2026-10-18", self._credito(nonce="n4"))
        s, b = self._book(q)
        self.assertEqual(s, 201, "un guasto dello store NON deve bloccare la prenotazione")


if __name__ == "__main__":
    unittest.main(verbosity=2)
