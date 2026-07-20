"""Collaudo ramo CHECK-IN DIGITALE (2026-07-16, metodo libro) — 2 difetti chiusi:

(a) check-in accettato su prenotazione CANCELLATA (il voucher non scade mai) -> ospiti
    FANTASMA nello store (inquinano l'export alloggiati) e, a serratura smart attiva,
    'completato' abiliterebbe lo SBLOCCO PORTA di una prenotazione cancellata -> ora 409.
(b) il PANNELLO host non mostrava ne' codice ne' PIN (vivevano solo nell'email di avviso:
    host che la perde = nessun modo di verificare l'ospite alla porta) -> /api/host/
    prenotazioni ora porta codice+pin, identici a quelli del cliente; dopo un re-block
    tardivo (idem_key 'reblock:<rif>') il rif si estrae e il PIN resta GIUSTO.
"""
import datetime
import json
import shutil
import sqlite3
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, sweep_hold_una_passata
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE


class TestCheckinRamo(unittest.TestCase):
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
            db_checkin=f"{d}/ck.db", commissione_bps=1000, psp_bps=300,
            stripe_secret_key="sk_test_x", stripe_webhook_secret="whsec_x",
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/ko"))
        self.r = crea_router(self.sis, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@ck.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]
        oggi = datetime.date.today()
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa-ck", "titolo": "Casa CK", "citta": "Roma",
                "prezzo_notte_cents": 10000, "capacita": 2}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa-ck", "da": oggi.isoformat(),
                "a": (oggi + datetime.timedelta(days=40)).isoformat(),
                "unita_totali": 2, "prezzo_netto_cents": 10000}, {"X-Host-Token": self.tok})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None,
                               h or {})

    def _book(self, giorni=10):
        oggi = datetime.date.today()
        ci = (oggi + datetime.timedelta(days=giorni)).isoformat()
        co = (oggi + datetime.timedelta(days=giorni + 2)).isoformat()
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa-ck", "check_in": ci, "check_out": co, "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@ck.it"})
        return b

    def _paga(self, ref):
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": ref}}}})
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": firma_di_test(pl, "whsec_x", int(time.time()))})

    def test_checkin_su_cancellata_respinto(self):
        b = self._book()
        self._paga(b["riferimento"])
        s, _ = self.g("POST", "/api/concierge/cancella",
                      {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200)
        s, o = self.g("POST", "/api/checkin/pre_registra",
                      {"voucher_token": b["voucher_token"],
                       "ospiti": [{"nome": "Ghost Guest", "documento": "ZZ999999"}]})
        self.assertEqual(s, 409, o)
        self.assertEqual(o.get("errore"), "prenotazione_cancellata")
        self.assertFalse(self.sis.checkin.completato(b["riferimento"]))

    def test_checkin_su_pagata_ok(self):
        b = self._book(giorni=14)
        self._paga(b["riferimento"])
        s, o = self.g("POST", "/api/checkin/pre_registra",
                      {"voucher_token": b["voucher_token"],
                       "ospiti": [{"nome": "Mario Rossi", "documento": "AB123456"}]})
        self.assertEqual(s, 200, o)
        _, st = self.g("GET", "/api/checkin/stato",
                       q={"voucher_token": b["voucher_token"]})
        self.assertTrue(st["completato"])

    def test_pannello_host_porta_codice_e_pin(self):
        from fase59_concierge import codice_prenotazione
        b = self._book(giorni=18)
        self._paga(b["riferimento"])
        s, pr = self.g("GET", "/api/host/prenotazioni", h={"X-Host-Token": self.tok})
        self.assertEqual(s, 200)
        # prenotazione VIVA = non archiviata (dal 2026-07-18 lo stato di una viva e'
        # attiva/futura/confermata secondo la data; il criterio durevole e' 'archiviata').
        riga = [p for p in pr["prenotazioni"] if not p.get("archiviata")][0]
        self.assertEqual(riga["pin"], self.sis.firma.pin_checkin(b["riferimento"]))
        self.assertEqual(riga["codice"], codice_prenotazione(b["riferimento"]))

    def test_pin_giusto_anche_dopo_reblock_tardivo(self):
        b = self._book(giorni=22)
        ref = b["riferimento"]
        con = sqlite3.connect(f"{self.dir}/p.db")
        with con:
            con.execute("UPDATE pendenti SET scadenza_ts=? WHERE riferimento=?",
                        (int(time.time()) - 5, ref))
        con.close()
        sweep_hold_una_passata(self.sis, self.r)
        self._paga(ref)                       # tardivo -> re-block con idem 'reblock:<rif>'
        self.assertEqual(self.sis.pagamenti_pendenti.info(ref)["stato"], "pagato")
        s, pr = self.g("GET", "/api/host/prenotazioni", h={"X-Host-Token": self.tok})
        pin_atteso = self.sis.firma.pin_checkin(ref)
        pins = [p["pin"] for p in pr["prenotazioni"] if not p.get("archiviata")]
        self.assertIn(pin_atteso, pins,
                      "il PIN nel pannello deve derivare dal rif ORIGINALE, non da 'reblock:'")


if __name__ == "__main__":
    unittest.main(verbosity=2)
