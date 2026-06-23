"""Test Fase 125 - Confronto OTA risparmio guest. Puro, cents/bps interi."""
import unittest

from fase125_confronto_guest import PoliticaConfrontoGuest, confronta_guest


class TestConfrontoGuest(unittest.TestCase):
    def test_calcolo_base(self):
        c = confronta_guest(10000)                          # netto host 100
        # OTA: 100 +15% = 115 base; +14% fee = 16.10; tot 131.10
        self.assertEqual(c["ota_base_cents"], 11500)
        self.assertEqual(c["ota_guest_fee_cents"], 1610)
        self.assertEqual(c["ota_totale_cents"], 13110)
        # noi: 100 + 12% = 112
        self.assertEqual(c["nostro_totale_cents"], 11200)
        self.assertEqual(c["risparmio_guest_cents"], 1910)

    def test_dcc_solo_se_valuta_diversa(self):
        senza = confronta_guest(10000, valuta_diversa=False)
        con = confronta_guest(10000, valuta_diversa=True)
        self.assertEqual(senza["ota_dcc_cents"], 0)
        self.assertGreater(con["ota_dcc_cents"], 0)
        self.assertGreater(con["risparmio_guest_cents"], senza["risparmio_guest_cents"])

    def test_risparmio_bps(self):
        c = confronta_guest(10000)
        self.assertEqual(c["risparmio_bps"], 1910 * 10000 // 13110)

    def test_zero_failclosed(self):
        c = confronta_guest(0)
        self.assertEqual(c["risparmio_guest_cents"], 0)
        c2 = confronta_guest("x")
        self.assertEqual(c2["ota_totale_cents"], 0)

    def test_politica_custom(self):
        pol = PoliticaConfrontoGuest(ota_markup_host_bps=2500, ota_guest_fee_bps=1500,
                                     nostra_guest_fee_bps=1000)
        c = confronta_guest(10000, pol=pol)
        self.assertGreater(c["risparmio_guest_cents"], 0)

    def test_cents_interi(self):
        c = confronta_guest(9999, valuta_diversa=True)
        for v in c.values():
            self.assertIsInstance(v, int)


if __name__ == "__main__":
    unittest.main()
