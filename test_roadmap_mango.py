"""
Test anti-drift di ROADMAP_MANGO.md: il piano di riattivazione di Mango deve
esistere, coprire i 7 mattoni (fase43..fase49), il protocollo d'isolamento e il
fatto chiave che il motore booking NON viene toccato.
"""
import os
import unittest


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestRoadmapMango(unittest.TestCase):
    def setUp(self):
        self.doc = _read("ROADMAP_MANGO.md")

    def test_sette_mattoni(self):
        for n in range(43, 50):                      # fase43..fase49
            self.assertIn("fase{}".format(n), self.doc, "manca fase%d" % n)

    def test_protocollo_isolamento(self):
        for c in ("default-off", "lazy", "gate di regressione", "denaro dal SISTEMA",
                  "RicercaProvider", "492"):
            self.assertIn(c, self.doc, c)

    def test_correzione_presupposto(self):
        # deve chiarire che 24-33 sono gia' costruite e che Mango riusa l'esistente
        for c in ("Rana Inversa", "compliant", "non importano"):
            self.assertIn(c, self.doc, c)

    def _esiste(self, n):
        return any(f.startswith("fase{}_".format(n)) and f.endswith(".py")
                   for f in os.listdir("."))

    def test_mattoni_core_costruiti(self):
        # M1 commissione, M2 prezzo, M3 proposte/split, M4 esploratore: fase43-46 esistono.
        for n in (43, 44, 45, 46):
            self.assertTrue(self._esiste(n), "fase%d mancante" % n)

    def test_i_numeri_mango_futuri_sono_liberi(self):
        # i mattoni Mango futuri (fase47..fase49) NON devono collidere con file esistenti
        for n in range(47, 50):
            self.assertFalse(self._esiste(n), "fase%d gia' occupata: rinumerare" % n)


if __name__ == "__main__":
    unittest.main()
