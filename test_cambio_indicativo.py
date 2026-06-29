"""Test conversione INDICATIVA (solo display, mai occulta): tasso mid, nessun markup; l'addebito
resta nella valuta dell'host (like-for-like). Senza provider -> nessun indicativo (0)."""
import unittest

from fase59_concierge import FirmaQuote, ProtocolloConcierge

SEG = b"x" * 16


class _Inv:
    pass


def _conc(tasso=None):
    return ProtocolloConcierge(_Inv(), FirmaQuote(SEG), tasso_cambio=tasso)


class TestIndicativo(unittest.TestCase):
    def test_converte_col_tasso_mid(self):
        c = _conc(lambda da, a: 1.1 if (da, a) == ("EUR", "USD") else None)
        self.assertEqual(c._converti_indicativo("EUR", "USD", 10000), 11000)   # mid, no markup

    def test_stessa_valuta_nessun_indicativo(self):
        c = _conc(lambda da, a: 1.1)
        self.assertEqual(c._converti_indicativo("EUR", "EUR", 10000), 0)

    def test_senza_tasso_zero(self):
        c = _conc(lambda da, a: None)                         # provider c'e' ma non ha il tasso
        self.assertEqual(c._converti_indicativo("EUR", "JPY", 10000), 0)

    def test_senza_provider_zero(self):
        self.assertEqual(_conc()._converti_indicativo("EUR", "USD", 10000), 0)  # gated off

    def test_input_invalidi(self):
        c = _conc(lambda da, a: 1.1)
        self.assertEqual(c._converti_indicativo("EUR", "", 10000), 0)
        self.assertEqual(c._converti_indicativo("EUR", "USD", -5), 0)


if __name__ == "__main__":
    unittest.main()
