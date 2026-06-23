"""Test Fase 105 - W3C Identity Gate. Puro; orologio iniettato per scadenza."""
import unittest

from fase105_identity_gate import GateIdentita, crea_gate_identita

SEG = b"s" * 32


class TestAnnuncio(unittest.TestCase):
    def setUp(self):
        self.g = crea_gate_identita(SEG)

    def test_emetti_verifica_ok(self):
        t = self.g.emetti_annuncio("h1", "casa-roma", "Casa a Roma", "Roma")
        self.assertTrue(self.g.verifica_annuncio(t, slug="casa-roma",
                        titolo="Casa a Roma", citta="Roma"))

    def test_manomissione_titolo_rifiutata(self):
        t = self.g.emetti_annuncio("h1", "casa-roma", "Casa a Roma", "Roma")
        self.assertFalse(self.g.verifica_annuncio(t, slug="casa-roma",
                         titolo="Villa di Lusso FALSA", citta="Roma"))

    def test_firma_rotta_rifiutata(self):
        t = self.g.emetti_annuncio("h1", "casa-roma", "Casa a Roma", "Roma")
        self.assertFalse(self.g.verifica_annuncio(t + "x", slug="casa-roma",
                         titolo="Casa a Roma", citta="Roma"))

    def test_segreto_diverso_rifiuta(self):
        t = self.g.emetti_annuncio("h1", "casa-roma", "Casa a Roma", "Roma")
        altro = crea_gate_identita(b"k" * 32)
        self.assertFalse(altro.verifica_annuncio(t, slug="casa-roma",
                         titolo="Casa a Roma", citta="Roma"))

    def test_input_invalido(self):
        self.assertIsNone(self.g.emetti_annuncio("", "casa", "t", "c"))


class TestRecensione(unittest.TestCase):
    def setUp(self):
        self.g = crea_gate_identita(SEG)

    def test_ok(self):
        t = self.g.emetti_recensione("p1", "casa-roma", 5, "Stupenda!")
        self.assertTrue(self.g.verifica_recensione(t, prenotazione_id="p1",
                        alloggio_slug="casa-roma", voto=5, testo="Stupenda!"))

    def test_testo_o_voto_manomessi(self):
        t = self.g.emetti_recensione("p1", "casa-roma", 5, "Stupenda!")
        self.assertFalse(self.g.verifica_recensione(t, prenotazione_id="p1",
                         alloggio_slug="casa-roma", voto=1, testo="Pessima"))

    def test_voto_fuori_range(self):
        self.assertIsNone(self.g.emetti_recensione("p1", "casa", 9, "x"))


class TestScadenza(unittest.TestCase):
    def test_scaduta_rifiutata(self):
        t0 = [1000]
        g = GateIdentita(SEG, ttl_sec=60, orologio=lambda: t0[0])
        tok = g.emetti_annuncio("h1", "casa", "T", "C")
        t0[0] += 120
        self.assertFalse(g.verifica_annuncio(tok, slug="casa", titolo="T", citta="C"))


if __name__ == "__main__":
    unittest.main()
