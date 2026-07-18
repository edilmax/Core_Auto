"""Collaudo ENFORCEMENT least-privilege (Bunker & Field, Incremento 3).

Regola del fondatore: "nessuno esegue operazioni distruttive senza il Bunker". Ma in modo
SICURO: l'enforcement scatta SOLO quando il super-admin e' configurato -> mai chiudersi
fuori prima, e i test/flussi senza Bunker restano invariati.
Invarianti:
  1. Bunker CONFIGURATO: le 4 distruttive (alloggio_stato, rimborso, controversia/risolvi,
     cancella_attivita) SENZA sessione Bunker -> 403 'bunker_richiesto'; CON sessione -> ok;
  2. Bunker SPENTO (default): le distruttive funzionano con la sola chiave admin (nessuna
     regressione: enforcement inattivo finche' non c'e' un super-admin);
  3. la sessione di un altro IP non vale (gia' coperto da test_bunker; qui il flusso e2e).
"""
import hashlib
import hmac
import json
import shutil
import tempfile
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

WHSEC = "whsec_test"
IP = {"X-Forwarded-For": "203.0.113.50"}


class TestEnforcement(unittest.TestCase):
    def _sistema(self, *, bunker):
        d = self.dir = tempfile.mkdtemp()
        kw = dict(abilitato=True, segreto_hmac=b"h" * 32, db_catalogo=f"{d}/c.db",
                  db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
                  db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db", db_garanzia=f"{d}/g.db",
                  db_tassa_comunale=f"{d}/tc.db", db_finanza=f"{d}/fin.db",
                  commissione_bps=1500, stripe_webhook_secret=WHSEC)
        if bunker:
            kw["bunker_password"] = "SuperPw@1"
        self.sis = crea_sistema(ConfigCasaVIP(**kw))
        self.sis.concierge._link = lambda dati: "https://pay/" + str(dati.get("riferimento", ""))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        self.g("POST", "/api/host/pubblica", {"host_id": "demo", "slug": "casa", "titolo": "C",
               "citta": "Roma", "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
               "servizi": [], "immagini": [], "tassa_pp_notte_cents": 0}, {"X-Host-Key": "hk"})
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa",
               "da": "2027-12-01", "a": "2027-12-31", "unita_totali": 3,
               "prezzo_netto_cents": 10000}, {"X-Host-Key": "hk"})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _sessione_bunker(self):
        h = dict(IP)
        h["X-Admin-Key"] = "ak"
        s, out = self.g("POST", "/api/bunker/login", {"codice": "SuperPw@1"}, h)
        self.assertEqual(s, 200, out)
        return out["sessione"]

    def _AK(self, sess=None):
        h = dict(IP)
        h["X-Admin-Key"] = "ak"
        if sess:
            h["X-Bunker-Session"] = sess
        return h

    def test_distruttive_richiedono_bunker_quando_configurato(self):
        self._sistema(bunker=True)
        # SENZA sessione bunker -> 403 su tutte e 4
        for m, p, body in (
            ("POST", "/api/admin/alloggio_stato", {"slug": "casa", "stato": "sospeso"}),
            ("POST", "/api/admin/rimborso", {"alloggio_id": "casa", "check_in": "2027-12-05",
                                             "check_out": "2027-12-07", "idem_key": "x" * 24}),
            ("POST", "/api/admin/controversia/risolvi", {"riferimento": "r", "percentuale_ospite": 50}),
            ("POST", "/api/admin/cancella_attivita", {"host_id": "demo"}),
        ):
            s, o = self.g(m, p, body, self._AK())
            self.assertEqual(s, 403, "%s doveva chiedere il bunker, ha dato %s" % (p, s))
            self.assertEqual(o.get("errore"), "bunker_richiesto")
        # CON sessione bunker -> alloggio_stato passa (200)
        sess = self._sessione_bunker()
        s, o = self.g("POST", "/api/admin/alloggio_stato",
                      {"slug": "casa", "stato": "sospeso"}, self._AK(sess))
        self.assertEqual(s, 200, o)
        self.assertEqual(o.get("stato"), "sospeso")

    def test_rimborso_reale_con_bunker(self):
        self._sistema(bunker=True)
        # prenota e paga
        _, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "casa",
                      "check_in": "2027-12-10", "check_out": "2027-12-12", "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "o@collaudo.invalid"})
        rif = b["riferimento"]
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": rif}}}})
        ts = str(int(time.time()))
        mac = hmac.new(WHSEC.encode(), f"{ts}.{pl}".encode(), hashlib.sha256).hexdigest()
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": "t=%s,v1=%s" % (ts, mac)})
        idem = self.sis.pagamenti_pendenti.info(rif)["idem_key"]
        corpo = {"alloggio_id": "casa", "check_in": "2027-12-10",
                 "check_out": "2027-12-12", "idem_key": idem}
        # senza bunker -> 403
        s, _ = self.g("POST", "/api/admin/rimborso", corpo, self._AK())
        self.assertEqual(s, 403)
        # con bunker -> 200
        s, o = self.g("POST", "/api/admin/rimborso", corpo, self._AK(self._sessione_bunker()))
        self.assertEqual(s, 200, o)

    def test_nessuna_regressione_bunker_spento(self):
        self._sistema(bunker=False)          # default: super-admin non configurato
        # le distruttive funzionano con la SOLA chiave admin (enforcement inattivo)
        s, o = self.g("POST", "/api/admin/alloggio_stato",
                      {"slug": "casa", "stato": "sospeso"}, {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, o)


if __name__ == "__main__":
    unittest.main()
