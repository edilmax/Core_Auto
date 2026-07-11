"""Codice prenotazione leggibile (BVIP-XXXX-XXXX) + PIN check-in (4 cifre): stile Booking.
Deterministici e UGUALI per cliente e host; il PIN non è indovinabile (HMAC del segreto)."""
import unittest

from fase59_concierge import FirmaQuote, codice_prenotazione

SEG = b"k" * 32


class TestCodicePrenotazione(unittest.TestCase):
    def test_formato_bvip(self):
        c = codice_prenotazione("a5d660df6d99554875f212ac")
        self.assertEqual(c, "BVIP-A5D6-60DF")

    def test_deterministico(self):
        self.assertEqual(codice_prenotazione("abc123def456"),
                         codice_prenotazione("abc123def456"))

    def test_riferimento_corto_ha_padding(self):
        c = codice_prenotazione("ab")
        self.assertTrue(c.startswith("BVIP-AB00-"))
        self.assertEqual(len(c), len("BVIP-XXXX-XXXX"))

    def test_ignora_caratteri_strani(self):
        # solo alfanumerici, maiuscolo
        self.assertEqual(codice_prenotazione("a5-d6/60.df"), "BVIP-A5D6-60DF")

    def test_vuoto_non_solleva(self):
        self.assertEqual(codice_prenotazione(""), "BVIP-0000-0000")


class TestPinCheckin(unittest.TestCase):
    def setUp(self):
        self.firma = FirmaQuote(SEG)

    def test_quattro_cifre(self):
        pin = self.firma.pin_checkin("rif123")
        self.assertEqual(len(pin), 4)
        self.assertTrue(pin.isdigit())

    def test_deterministico_uguale_per_cliente_e_host(self):
        # cliente e host derivano lo STESSO pin dallo stesso riferimento
        self.assertEqual(self.firma.pin_checkin("REF-XYZ"), self.firma.pin_checkin("REF-XYZ"))

    def test_dipende_dal_riferimento(self):
        self.assertNotEqual(self.firma.pin_checkin("a"), self.firma.pin_checkin("b"))

    def test_dipende_dal_segreto_non_indovinabile(self):
        # con un segreto diverso il pin cambia -> non ricavabile senza il segreto
        altro = FirmaQuote(b"z" * 32)
        # (può coincidere per caso su 4 cifre, ma su più riferimenti no)
        diversi = sum(1 for r in ("r1", "r2", "r3", "r4", "r5")
                      if self.firma.pin_checkin(r) != altro.pin_checkin(r))
        self.assertGreaterEqual(diversi, 3)


if __name__ == "__main__":
    unittest.main()
