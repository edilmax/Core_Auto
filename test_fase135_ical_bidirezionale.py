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


if __name__ == "__main__":
    unittest.main()
