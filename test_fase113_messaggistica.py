"""Test Fase 113 - Messaggistica host-guest. SQLite :memory:."""
import unittest

from fase113_messaggistica import Messaggistica, crea_messaggistica, maschera_pii


def msg():
    m = crea_messaggistica(":memory:")
    m.inizializza_schema()
    return m


class TestMessaggistica(unittest.TestCase):
    def test_invio_e_thread(self):
        m = msg()
        self.assertTrue(m.invia("p1", "H", "G", "G", "Ciao a che ora il check-in?"))
        self.assertTrue(m.invia("p1", "H", "G", "H", "Dalle 15"))
        t = m.thread("p1", "H")
        self.assertEqual(len(t), 2)
        self.assertEqual(t[0]["mittente"], "G")

    def test_mittente_fuori_thread_rifiutato(self):
        m = msg()
        self.assertFalse(m.invia("p1", "H", "G", "X", "spam"))

    def test_testo_vuoto_rifiutato(self):
        m = msg()
        self.assertFalse(m.invia("p1", "H", "G", "H", "   "))

    def test_estraneo_non_legge(self):
        m = msg()
        m.invia("p1", "H", "G", "H", "privato")
        self.assertEqual(m.thread("p1", "ESTRANEO"), [])

    def test_maschera_pii(self):
        m = msg()
        m.invia("p1", "H", "G", "G", "scrivimi a mario@x.com o +39 333 1234567")
        testo = m.thread("p1", "H")[0]["testo"]
        self.assertNotIn("mario@x.com", testo)
        self.assertIn("[email rimossa]", testo)
        self.assertIn("[contatto rimosso]", testo)

    def test_maschera_pii_pura(self):
        self.assertEqual(maschera_pii("ok"), "ok")
        self.assertIn("[email rimossa]", maschera_pii("a@b.com"))

    def test_segna_letti(self):
        m = msg()
        m.invia("p1", "H", "G", "G", "uno")
        m.invia("p1", "H", "G", "G", "due")
        self.assertEqual(m.segna_letti("p1", "H"), 2)       # H legge i 2 di G
        self.assertEqual(m.segna_letti("p1", "H"), 0)       # già letti

    def test_isolato_input_vuoto(self):
        m = msg()
        self.assertFalse(m.invia("", "H", "G", "H", "x"))
        self.assertEqual(m.thread("", "H"), [])


if __name__ == "__main__":
    unittest.main()
