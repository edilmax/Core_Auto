"""
Test FASE 17 - Money (centesimi interi, zero float).

Verifica che gli importi siano gestiti in centesimi interi, che i float vengano
rifiutati a monte, che la conversione di presentazione sia esatta e che gli
invarianti di ripartizione siano enforced.
"""
import unittest

from fase17_money import parse_cent, cents_to_str, valida_split


class TestParseCent(unittest.TestCase):

    def test_int_passthrough(self):
        self.assertEqual(parse_cent(100000), 100000)
        self.assertEqual(parse_cent(0), 0)

    def test_stringa_di_cifre(self):
        self.assertEqual(parse_cent("100000"), 100000)
        self.assertEqual(parse_cent("-50"), -50)
        self.assertEqual(parse_cent("  42 "), 42)

    def test_rifiuta_float(self):
        with self.assertRaises(ValueError):
            parse_cent(1000.0)
        with self.assertRaises(ValueError):
            parse_cent(0.1)

    def test_rifiuta_bool(self):
        with self.assertRaises(ValueError):
            parse_cent(True)

    def test_rifiuta_stringa_decimale(self):
        with self.assertRaises(ValueError):
            parse_cent("10.50")

    def test_rifiuta_none_e_oggetti(self):
        with self.assertRaises(ValueError):
            parse_cent(None)
        with self.assertRaises(ValueError):
            parse_cent(object())


class TestCentsToStr(unittest.TestCase):

    def test_conversioni(self):
        self.assertEqual(cents_to_str(123456), "1234.56")
        self.assertEqual(cents_to_str(0), "0.00")
        self.assertEqual(cents_to_str(5), "0.05")
        self.assertEqual(cents_to_str(-5), "-0.05")
        self.assertEqual(cents_to_str(100000), "1000.00")

    def test_rifiuta_float_e_bool(self):
        with self.assertRaises(ValueError):
            cents_to_str(12.34)
        with self.assertRaises(ValueError):
            cents_to_str(True)


class TestValidaSplit(unittest.TestCase):

    def test_split_corretto(self):
        """Uno split che quadra passa, e passa NEL MODO DOCUMENTATO.

        Prima la riga era `valida_split(100000, 10000, 90000)  # non solleva`: verificava
        davvero qualcosa (se sollevasse, il test cadrebbe), ma senza dirlo. Se un domani
        la funzione smettesse di sollevare e tornasse l'errore come valore, questo test
        resterebbe verde mentre il controllo sui soldi sarebbe sparito.
        """
        self.assertIsNone(valida_split(100000, 10000, 90000),
                          "valida_split non deve restituire nulla: segnala per eccezione")

    def test_split_non_quadra(self):
        with self.assertRaises(ValueError):
            valida_split(100000, 10000, 80000)

    def test_negativi_rifiutati(self):
        with self.assertRaises(ValueError):
            valida_split(100000, -10000, 110000)

    def test_non_interi_rifiutati(self):
        with self.assertRaises(ValueError):
            valida_split(1000.0, 100.0, 900.0)


class TestBombProof(unittest.TestCase):
    """Dimostra che i centesimi interi non soffrono l'imprecisione dei float."""

    def test_float_sarebbe_impreciso(self):
        # Il classico: in float 0.1 + 0.2 != 0.3.
        self.assertNotEqual(0.1 + 0.2, 0.3)

    def test_centesimi_sono_esatti(self):
        # 10 + 20 = 30 centesimi, esatto, sempre.
        self.assertEqual(10 + 20, 30)

    def test_ripartizione_somma_esatta(self):
        # 100.00 EUR diviso in tre: nessuna perdita di centesimi.
        totale = 10000
        a, b, c = 3334, 3333, 3333
        self.assertEqual(a + b + c, totale)
        valida_split(totale, a, b + c)  # commissione=a, quota=b+c -> invariante regge

    def test_somma_molti_importi(self):
        # Somma di 1000 importi da 0.01 EUR = 10.00 EUR esatti (in float diverge).
        cents = sum(1 for _ in range(1000))  # 1000 * 1 cent
        self.assertEqual(cents, 1000)
        self.assertEqual(cents_to_str(cents), "10.00")


class TestEuroToCents(unittest.TestCase):

    def test_conversioni(self):
        from fase17_money import euro_to_cents
        self.assertEqual(euro_to_cents(80.0), 8000)
        self.assertEqual(euro_to_cents("80.50"), 8050)
        self.assertEqual(euro_to_cents(0), 0)
        self.assertEqual(euro_to_cents(80), 8000)

    def test_arrotondamento_half_up(self):
        from fase17_money import euro_to_cents
        self.assertEqual(euro_to_cents("0.005"), 1)   # 0.5 cent -> 1 (HALF_UP)
        self.assertEqual(euro_to_cents("0.004"), 0)

    def test_rifiuta_invalidi(self):
        from fase17_money import euro_to_cents
        with self.assertRaises(ValueError):
            euro_to_cents("abc")
        with self.assertRaises(ValueError):
            euro_to_cents(True)


class TestApplicaPercentuale(unittest.TestCase):

    def test_commissione_esatta(self):
        from decimal import Decimal
        from fase17_money import applica_percentuale
        self.assertEqual(applica_percentuale(8000, Decimal("0.10")), 800)
        self.assertEqual(applica_percentuale(333, Decimal("0.10")), 33)   # 33.3 -> 33
        self.assertEqual(applica_percentuale(8050, Decimal("0.10")), 805)

    def test_rifiuta_non_int(self):
        from decimal import Decimal
        from fase17_money import applica_percentuale
        with self.assertRaises(ValueError):
            applica_percentuale(80.0, Decimal("0.10"))


if __name__ == "__main__":
    unittest.main()
