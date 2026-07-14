"""
Collaudo — export iCal (.ics) del calendario host (fase135 attivata). L'host ottiene un URL
firmato da incollare su Booking/Airbnb: le date prenotate qui compaiono nel feed -> bloccate lì
(anti-overbooking). Solo il proprietario genera il link; token non valido -> None.
"""
import json
import shutil
import tempfile
import unittest
from urllib.parse import unquote

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE


class TestIcalExport(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{self.d}/c.db", db_inventario=f"{self.d}/i.db",
            db_registro_host=f"{self.d}/r.db", db_accettazioni=f"{self.d}/a.db"))
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        self.tok = self._reg("h1@ic.it")
        s, _ = self.g("POST", "/api/host/pubblica",
                      {"slug": "casa", "titolo": "Casa", "citta": "Roma",
                       "prezzo_notte_cents": 10000, "capacita": 2}, {"X-Host-Token": self.tok})
        self.assertEqual(s, 201)
        # apro le date poi prenoto (blocco inventario) -> deve comparire nel feed
        for g in ("2026-09-10", "2026-09-11"):
            self.sys.inventario.imposta_disponibilita("casa", g, unita_totali=1,
                                                      prezzo_netto_cents=10000)
        self.sys.inventario.blocca("casa", "2026-09-10", "2026-09-12",
                                   idem_key="b1", origine="test")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _reg(self, email):
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": email, "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        return c["token"]

    def test_link_e_feed(self):
        s, d = self.g("GET", "/api/host/ical_link", h={"X-Host-Token": self.tok},
                      q={"alloggio": "casa"})
        self.assertEqual(s, 200, d)
        self.assertIn("/ical/", d["url"])
        self.assertTrue(d["url"].endswith(".ics"))
        token = unquote(d["url"].split("/ical/")[1][:-4])
        ics = self.r._ical_export(token)
        self.assertIn("BEGIN:VCALENDAR", ics)
        self.assertIn("BEGIN:VEVENT", ics)
        self.assertIn("DTSTART;VALUE=DATE:20260910", ics)
        self.assertIn("DTEND;VALUE=DATE:20260912", ics)

    def test_solo_proprietario(self):
        altro = self._reg("h2@ic.it")
        s, d = self.g("GET", "/api/host/ical_link", h={"X-Host-Token": altro},
                      q={"alloggio": "casa"})
        self.assertEqual(s, 403, d)                     # non è tuo
        s, _ = self.g("GET", "/api/host/ical_link", q={"alloggio": "casa"})
        self.assertEqual(s, 401)                        # senza auth

    def test_token_non_valido(self):
        self.assertIsNone(self.r._ical_export("spazzatura.non.firmata"))
        self.assertIsNone(self.r._ical_export(""))

    def test_alloggio_mancante(self):
        s, _ = self.g("GET", "/api/host/ical_link", h={"X-Host-Token": self.tok})
        self.assertEqual(s, 422)


if __name__ == "__main__":
    unittest.main(verbosity=2)
