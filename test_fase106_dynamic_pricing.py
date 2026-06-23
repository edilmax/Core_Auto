"""Test Fase 106 - Dynamic pricing. Puro, deterministico, cents interi."""
import unittest

from fase106_dynamic_pricing import (PoliticaPrezzo, calcola_prezzo,
                                     crea_politica_prezzo)


class TestPricing(unittest.TestCase):
    def test_base_neutro(self):
        # occupazione media 50%, mese aprile (10000), feriale, anticipo normale -> base
        r = calcola_prezzo(10000, occupazione_bps=5000, data="2026-04-08",
                           giorni_all_arrivo=30)
        self.assertEqual(r["fattori"]["occupazione"], 10000)
        self.assertEqual(r["fattori"]["stagione"], 10000)
        self.assertEqual(r["fattori"]["weekend"], 10000)
        self.assertEqual(r["prezzo_cents"], 10000)

    def test_domanda_alta_aumenta(self):
        r = calcola_prezzo(10000, occupazione_bps=9000, data="2026-04-08",
                           giorni_all_arrivo=30)
        self.assertEqual(r["fattori"]["occupazione"], 13000)
        self.assertEqual(r["prezzo_cents"], 13000)              # +30%

    def test_domanda_bassa_sconta(self):
        r = calcola_prezzo(10000, occupazione_bps=2000, data="2026-04-08",
                           giorni_all_arrivo=30)
        self.assertEqual(r["prezzo_cents"], 9000)               # -10%

    def test_weekend_e_stagione_agosto(self):
        # 2026-08-08 è sabato; agosto stagione 13000; occ media
        r = calcola_prezzo(10000, occupazione_bps=5000, data="2026-08-08",
                           giorni_all_arrivo=30)
        self.assertEqual(r["fattori"]["weekend"], 11500)
        self.assertEqual(r["fattori"]["stagione"], 13000)
        # 10000 * 1.3 * 1.15 = 14950
        self.assertEqual(r["prezzo_cents"], 14950)

    def test_last_minute_sconto(self):
        r = calcola_prezzo(10000, occupazione_bps=5000, data="2026-04-08",
                           giorni_all_arrivo=1)
        self.assertEqual(r["fattori"]["anticipo"], 8500)
        self.assertEqual(r["prezzo_cents"], 8500)

    def test_anticipo_lungo_premio(self):
        r = calcola_prezzo(10000, occupazione_bps=5000, data="2026-04-08",
                           giorni_all_arrivo=90)
        self.assertEqual(r["fattori"]["anticipo"], 10500)

    def test_cap_e_floor(self):
        pol = PoliticaPrezzo(cap_bps=12000, floor_bps=9500)
        alto = calcola_prezzo(10000, occupazione_bps=9000, data="2026-08-08",
                              giorni_all_arrivo=90, pol=pol)
        self.assertEqual(alto["prezzo_cents"], 12000)          # cappato a 120%
        basso = calcola_prezzo(10000, occupazione_bps=2000, data="2026-01-08",
                               giorni_all_arrivo=1, pol=pol)
        self.assertEqual(basso["prezzo_cents"], 9500)          # floored a 95%

    def test_base_invalido(self):
        self.assertEqual(calcola_prezzo(0)["prezzo_cents"], 0)
        self.assertEqual(calcola_prezzo(-5)["prezzo_cents"], 0)

    def test_cents_interi(self):
        r = calcola_prezzo(9999, occupazione_bps=9000, data="2026-07-04",
                           giorni_all_arrivo=5)
        self.assertIsInstance(r["prezzo_cents"], int)

    def test_factory(self):
        self.assertEqual(crea_politica_prezzo(weekend_bps=12000).weekend_bps, 12000)


if __name__ == "__main__":
    unittest.main()
