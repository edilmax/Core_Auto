"""Test Fase 145 - Contratto PDF. Pura stdlib, deterministico."""
import unittest

from fase145_contratto_pdf import componi_contratto, genera_pdf

DATI = {"host": "Mario Rossi", "guest": "John Doe", "alloggio": "Casa Roma",
        "citta": "Roma", "check_in": "2026-08-01", "check_out": "2026-08-05",
        "ospiti": 2, "prezzo_cents": 11200, "valuta": "EUR", "riferimento": "REF1"}


class TestComponi(unittest.TestCase):
    def test_it_contiene_dati(self):
        r = componi_contratto(DATI)
        testo = "\n".join(r)
        self.assertIn("Mario Rossi", testo)
        self.assertIn("112.00 EUR", testo)
        self.assertIn("REF1", testo)
        self.assertIn("LOCAZIONE", testo)

    def test_en(self):
        self.assertIn("RENTAL AGREEMENT", "\n".join(componi_contratto(DATI, lingua="en")))

    def test_dati_mancanti_segnaposto(self):
        r = componi_contratto({})
        self.assertIn("________", "\n".join(r))
        self.assertIn("0.00", "\n".join(r))


class TestPDF(unittest.TestCase):
    def test_struttura_pdf(self):
        pdf = genera_pdf(DATI)
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        self.assertTrue(pdf.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"xref", pdf)
        self.assertIn(b"/Root 1 0 R", pdf)
        self.assertEqual(pdf.count(b"endobj"), 5)
        self.assertIn(b"startxref", pdf)

    def test_dati_nel_contenuto(self):
        pdf = genera_pdf(DATI)
        self.assertIn(b"Mario Rossi", pdf)
        self.assertIn(b"112.00", pdf)

    def test_xref_offset_corretti(self):
        pdf = genera_pdf(DATI)
        # ogni offset in xref deve puntare a "N 0 obj"
        i = pdf.index(b"xref")
        startxref = int(pdf.split(b"startxref\n")[1].split(b"\n")[0])
        self.assertEqual(pdf[startxref:startxref + 4], b"xref")
        self.assertEqual(i, startxref)

    def test_escape_parentesi(self):
        pdf = genera_pdf({"host": "A (test) \\ B"})
        self.assertIn(b"\\(test\\)", pdf)
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_deterministico(self):
        self.assertEqual(genera_pdf(DATI), genera_pdf(DATI))


if __name__ == "__main__":
    unittest.main()
