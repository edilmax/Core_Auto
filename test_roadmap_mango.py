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
        # M1-M7: commissione, prezzo, split, esploratore, venditore, advertising,
        # ponte booking: fase43-49 (tutti i 7 mattoni Mango ora costruiti).
        for n in (43, 44, 45, 46, 47, 48, 49):
            self.assertTrue(self._esiste(n), "fase%d mancante" % n)

    def test_i_numeri_mango_futuri_sono_liberi(self):
        # mattoni a fase49; 50=orchestratore; 51=scheduler; 52=persistenza+metriche;
        # 53=health-guard; 54=loop/daemon; 55=bootstrap. Il blocco 56+ resta libero.
        for n in range(56, 59):
            self.assertFalse(self._esiste(n), "fase%d gia' occupata: rinumerare" % n)


if __name__ == "__main__":
    unittest.main()
