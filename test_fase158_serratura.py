"""SERRATURA ANTI-ACCUMULO (2026-09-23, ordine del fondatore: "accumulare crediti
sulla stessa citta' da nessuna parte, solo una volta" + "solo quando non ci sono
alloggi"). Stessa email+citta' -> lo STESSO token (mai uno nuovo); emissione
ripetuta = una sola."""
import unittest

from fase59_concierge import FirmaQuote
from fase158_domanda import crea_gestore_domanda

SEG = b"d" * 32


class TestSerraturaAntiAccumulo(unittest.TestCase):
    def setUp(self):
        self.d = crea_gestore_domanda(":memory:", firma=FirmaQuote(SEG))
        self.d.inizializza_schema()

    def test_stessa_email_stessa_citta_un_solo_token(self):
        t1 = self.d.emette_credito_fondatore("a@x.it", "Roma")
        t2 = self.d.emette_credito_fondatore("a@x.it", "Roma")
        t3 = self.d.emette_credito_fondatore("A@X.IT", " ROMA ")     # maiuscole/spazi = stessa
        self.assertTrue(t1 and t2 and t3)
        self.assertEqual(t1, t2, "stessa email+citta' ha prodotto DUE crediti: accumulo!")
        self.assertEqual(t2, t3, "case/spazi cambiano il token: buco di accumulo")

    def test_email_o_citta_diverse_token_diversi(self):
        a = self.d.emette_credito_fondatore("a@x.it", "Roma")
        b = self.d.emette_credito_fondatore("b@x.it", "Roma")
        c = self.d.emette_credito_fondatore("a@x.it", "Milano")
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, c)

    def test_emissione_ripetuta_resta_una(self):
        t1 = self.d.emette_credito_fondatore("ospite@x.it", "Roma")
        self.assertTrue(t1)
        for _ in range(5):
            self.assertEqual(t1, self.d.emette_credito_fondatore("ospite@x.it", "Roma"))


if __name__ == "__main__":
    unittest.main()
