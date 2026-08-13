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

    @staticmethod
    def _fra(giorni):
        """Una data scritta come INTENZIONE, non come cifra sul calendario."""
        import datetime
        return (datetime.date.today() + datetime.timedelta(days=giorni)).isoformat()

    @staticmethod
    def _comp(iso):
        """La stessa data nel formato compatto che usa iCal (20260910)."""
        return iso.replace("-", "")

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
        # ⛔ DATE RELATIVE, e la storia di questo punto vale piu' della riparazione. Il
        # 2026-07-19 questo test era «date-dipendente» (con certi «oggi» i due periodi
        # finivano adiacenti e l'export li FONDEVA) e fu riparato **cablando le date**:
        # 2026-09-10..12 e 2026-09-20..23. Ha funzionato per tre settimane e poi e' diventato
        # una BOMBA A TEMPO, misurata il 2026-08-13: sarebbe stato rosso da solo il
        # **2026-09-11**, perche' il feed esporta il futuro e quelle date sarebbero passate.
        # 💡 La cura non era cablare: era tenere il DIVARIO fra i due periodi (che era il
        # difetto vero) scrivendolo come intenzione. Cosi' vale per qualunque «oggi».
        self.pren0, self.pren1 = self._fra(28), self._fra(30)   # nostra prenotazione [0,1)
        for g in (self._fra(28), self._fra(29)):
            self.sys.inventario.imposta_disponibilita("casa", g, unita_totali=1,
                                                      prezzo_netto_cents=10000)
        self.sys.inventario.blocca("casa", self.pren0, self.pren1,
                                   idem_key="b1", origine="test")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _reg(self, email):
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": email, "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
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
        self.assertIn("DTSTART;VALUE=DATE:" + self._comp(self.pren0), ics)
        self.assertIn("DTEND;VALUE=DATE:" + self._comp(self.pren1), ics)

    def test_solo_proprietario(self):
        altro = self._reg("h2@ic.it")
        s, d = self.g("GET", "/api/host/ical_link", h={"X-Host-Token": altro},
                      q={"alloggio": "casa"})
        self.assertEqual(s, 403, d)                     # non è tuo
        s, _ = self.g("GET", "/api/host/ical_link", q={"alloggio": "casa"})
        self.assertEqual(s, 401)                        # senza auth

    def test_import_e_chiusure_si_propagano_nell_export(self):
        """COERENZA cross-canale (buco provato 2026-07-16): l'export deve includere NON solo le
        nostre prenotazioni ma anche i BLOCCHI IMPORTATI via iCal (unita_totali=0) e i giorni
        CHIUSI dall'host — altrimenti una data presa su Airbnb non arriva a Booking (overbooking).
        Prima il feed leggeva solo elenco_prenotazioni (movimenti) e ometteva import/chiusure."""
        import datetime
        # blocco importato in una finestra FUTURA con GAP dalla nostra prenotazione
        # (setUp: 2026-09-10..12). FIX 2026-07-19: prima era `oggi + 50 giorni` -> con
        # certe date di "oggi" il blocco finiva ADIACENTE al 09-10 e l'export li FONDEVA
        # in un unico range (DTSTART:20260910 spariva) = test date-dipendente. Ora fisso
        # e non adiacente (09-20..23), robusto a qualsiasi "oggi" prima di settembre 2026.
        # dieci giorni DOPO la fine della nostra prenotazione: il divario e' la cosa che
        # conta (adiacenti, l'export li fonde in un range solo e l'asserzione crolla)
        imp0 = datetime.date.today() + datetime.timedelta(days=40)
        imp1 = imp0 + datetime.timedelta(days=3)          # import: [imp0, imp1) esclusivo
        comp = lambda s: s.isoformat().replace("-", "")
        # IMPORT da "Airbnb" via endpoint reale
        ics = (f"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:ab1\r\n"
               f"DTSTART;VALUE=DATE:{comp(imp0)}\r\nDTEND;VALUE=DATE:{comp(imp1)}\r\n"
               f"END:VEVENT\r\nEND:VCALENDAR\r\n")
        s, res = self.g("POST", "/api/host/ical",
                        {"alloggio_id": "casa", "ical": ics}, {"X-Host-Token": self.tok})
        self.assertEqual(s, 200, res)
        self.assertEqual(res.get("giorni_bloccati"), 3)
        # export
        s, d = self.g("GET", "/api/host/ical_link", h={"X-Host-Token": self.tok},
                      q={"alloggio": "casa"})
        token = unquote(d["url"].split("/ical/")[1][:-4])
        feed = self.r._ical_export(token)
        # la NOSTRA prenotazione (setUp: fra 28 e 30 giorni) c'e' ancora
        self.assertIn("DTSTART;VALUE=DATE:" + self._comp(self.pren0), feed,
                      "persa la nostra prenotazione")
        # la data IMPORTATA ora si propaga nel feed (DTEND esclusivo = imp1)
        self.assertIn("DTSTART;VALUE=DATE:" + comp(imp0), feed,
                      "REGRESSIONE: blocco importato NON esportato -> overbooking cross-canale")
        self.assertIn("DTEND;VALUE=DATE:" + comp(imp1), feed)

    def test_token_non_valido(self):
        self.assertIsNone(self.r._ical_export("spazzatura.non.firmata"))
        self.assertIsNone(self.r._ical_export(""))

    def test_alloggio_mancante(self):
        s, _ = self.g("GET", "/api/host/ical_link", h={"X-Host-Token": self.tok})
        self.assertEqual(s, 422)


if __name__ == "__main__":
    unittest.main(verbosity=2)
