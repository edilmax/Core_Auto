"""
Test anti-drift della radiografia ARCHITETTURA.md: la mappa deve esistere, coprire
le 4 sezioni richieste, citare TUTTI i moduli del prodotto (fase34..fase42) e i
concetti chiave (centesimi, isolamento, /metrics, il flusso dati). Cosi' il
documento non diverge silenziosamente dal codice.
"""
import os
import unittest


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestArchitettura(unittest.TestCase):
    def setUp(self):
        self.doc = _read("ARCHITETTURA.md")

    def test_quattro_sezioni(self):
        for sezione in ("Anatomia del repository", "Flusso dei dati",
                        "fail-safe", "Manutenzione"):
            self.assertIn(sezione, self.doc, sezione)

    def test_cita_tutti_i_moduli_prodotto(self):
        for n in range(34, 43):                      # fase34..fase42
            self.assertIn("fase{}".format(n), self.doc, "manca fase%d" % n)

    def test_concetti_chiave(self):
        for c in ("centesimi", "isolamento", "/metrics", "fail-closed", "WAL"):
            self.assertIn(c, self.doc, c)

    def test_flusso_dati_e_manutenzione(self):
        for c in ("payment_url", "webhook", "rimborso", "inizializza_schema",
                  "PRAGMA integrity_check", "smoke_tavolavip.sh"):
            self.assertIn(c, self.doc, c)

    def test_moduli_citati_esistono(self):
        # ogni faseNN citata nella mappa deve avere il file reale nel repo
        for n in range(34, 43):
            self.assertTrue(any(f.startswith("fase{}_".format(n)) and f.endswith(".py")
                                for f in os.listdir(".")),
                            "file fase%d_*.py mancante" % n)


if __name__ == "__main__":
    unittest.main()
