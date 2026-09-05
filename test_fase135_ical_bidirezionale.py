"""Test Fase 135 - iCal bidirezionale. Roundtrip con fase82.analizza_ical."""
import unittest

from fase82_ical_sync import analizza_ical
from fase135_ical_bidirezionale import crea_sync_bidirezionale, genera_ical

PREN = [
    {"slug": "casa-1", "check_in": "2026-08-01", "check_out": "2026-08-05"},
    {"slug": "casa-1", "check_in": "2026-09-10", "check_out": "2026-09-12", "uid": "X1"},
]


class TestExport(unittest.TestCase):
    def test_struttura_ics(self):
        ics = genera_ical(PREN)
        self.assertTrue(ics.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertIn("DTSTART;VALUE=DATE:20260801", ics)
        self.assertIn("DTEND;VALUE=DATE:20260805", ics)
        self.assertEqual(ics.count("BEGIN:VEVENT"), 2)
        self.assertIn("UID:X1@bookinvip.com", ics)

    def test_roundtrip_fase82(self):
        ics = genera_ical(PREN)
        eventi = analizza_ical(ics)
        self.assertIn(("2026-08-01", "2026-08-05"), eventi)
        self.assertIn(("2026-09-10", "2026-09-12"), eventi)

    def test_record_invalidi_saltati(self):
        ics = genera_ical([{"check_in": "2026-08-05", "check_out": "2026-08-01"},  # inverso
                           {"check_in": "x"}, None, "y",
                           {"check_in": "2026-08-01", "check_out": "2026-08-02"}])
        self.assertEqual(ics.count("BEGIN:VEVENT"), 1)

    def test_escape_summary(self):
        ics = genera_ical([{"check_in": "2026-08-01", "check_out": "2026-08-02",
                            "summary": "a;b,c"}])
        self.assertIn("SUMMARY:a\\;b\\,c", ics)

    def test_vuoto_valido(self):
        ics = genera_ical([])
        self.assertEqual(ics.count("BEGIN:VEVENT"), 0)
        self.assertIn("END:VCALENDAR", ics)


class TestBidirezionale(unittest.TestCase):
    def test_esporta(self):
        s = crea_sync_bidirezionale()
        self.assertIn("VCALENDAR", s.esporta(PREN))

    def test_importa_isolato(self):
        s = crea_sync_bidirezionale()
        # inventario incompatibile -> isolato, non solleva
        self.assertIsInstance(s.importa(genera_ical(PREN), object(), "casa-1"), dict)


class TestLeGuardieDeiPuntiScoperti(unittest.TestCase):
    """Una guardia per ogni punto che il Giudice della mutazione ha trovato SCOPERTO
    (2026-09-05, Blocco 2 casella 4): il guasto passava e i test restavano verdi."""

    def test_anno_mese_e_giorno_fuori_scala_non_producono_eventi(self):
        # riga 22: le tre condizioni sulla data valgono INSIEME (anno di 4 cifre, mese
        # 1-12, giorno 1-31). Con un `or` al posto di un `and` un mese 13 o un anno di
        # due cifre finirebbero nel feed che Airbnb e Booking importano.
        for ci, co in (("2026-13-01", "2026-13-02"),
                       ("2026-01-32", "2026-01-33"),
                       ("26-01-01", "26-01-02")):
            with self.subTest(check_in=ci):
                ics = genera_ical([{"check_in": ci, "check_out": co}])
                self.assertEqual(ics.count("BEGIN:VEVENT"), 0)

    def test_stesso_giorno_zero_notti_nessun_evento(self):
        # riga 50: `ci < co` -- arrivo e partenza uguali sono zero notti: nessun
        # evento (con `<=` uscirebbe un VEVENT a durata zero, e DTEND e' esclusivo).
        ics = genera_ical([{"check_in": "2026-08-01", "check_out": "2026-08-01"}])
        self.assertEqual(ics.count("BEGIN:VEVENT"), 0)


if __name__ == "__main__":
    unittest.main()
