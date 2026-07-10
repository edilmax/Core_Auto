"""Allarme domanda: soglia + anti-spam (una volta per città) + stato durevole + fail-closed."""
import os
import shutil
import tempfile
import unittest

from domanda_allarme import AllarmeDomanda


class TestAllarmeDomanda(unittest.TestCase):
    def test_soglia_e_antispam(self):
        a = AllarmeDomanda("", soglia=3)
        self.assertFalse(a.controlla("Roma", 2))     # sotto soglia
        self.assertTrue(a.controlla("Roma", 3))      # raggiunge la soglia -> scatta
        self.assertFalse(a.controlla("Roma", 9))     # già segnata -> MAI due volte (anti-spam)
        self.assertTrue(a.in_allarme("roma"))
        self.assertIn("roma", a.elenco())

    def test_failclosed(self):
        a = AllarmeDomanda("", soglia=2)
        self.assertFalse(a.controlla("", 9))
        self.assertFalse(a.controlla(None, 9))
        self.assertFalse(a.controlla("Bari", "x"))
        self.assertFalse(a.controlla("Bari", True))   # bool non è conteggio

    def test_stato_durevole(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "al.json")
            a = AllarmeDomanda(p, soglia=2)
            self.assertTrue(a.controlla("Milano", 5))
            b = AllarmeDomanda(p, soglia=2)            # riapertura: stato persistito su file
            self.assertTrue(b.in_allarme("Milano"))
            self.assertFalse(b.controlla("Milano", 9))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_soglia_default_e_invalida(self):
        self.assertEqual(AllarmeDomanda("").soglia, 5)
        self.assertEqual(AllarmeDomanda("", soglia=0).soglia, 5)     # invalida -> default
        self.assertEqual(AllarmeDomanda("", soglia=True).soglia, 5)  # bool -> default


if __name__ == "__main__":
    unittest.main()
