"""Rampa di lancio della commissione (land-grab): 0% primi ~3 mesi -> 8% -> 10% a regime.
Pura e blindata: fail-safe -> regime (mai regalare lo 0% per errore)."""
import unittest

from fase98_policy_commissione import commissione_bps_lancio


class TestRampaLancio(unittest.TestCase):
    def test_soglie_mesi(self):
        self.assertEqual(commissione_bps_lancio(0), 0)       # giorno 0 -> gratis
        self.assertEqual(commissione_bps_lancio(89), 0)      # entro 3 mesi -> gratis
        self.assertEqual(commissione_bps_lancio(90), 800)    # da 3 mesi -> 8%
        self.assertEqual(commissione_bps_lancio(364), 800)   # entro 1 anno -> 8%
        self.assertEqual(commissione_bps_lancio(365), 1000)  # da 1 anno -> 10% a regime
        self.assertEqual(commissione_bps_lancio(5000), 1000)

    def test_failsafe_regime_mai_gratis_per_errore(self):
        for bad in (-1, "x", None, True, 1.5):
            self.assertEqual(commissione_bps_lancio(bad), 1000, bad)

    def test_parametrizzabile(self):
        # numeri configurabili (il fondatore può calibrare)
        self.assertEqual(commissione_bps_lancio(10, giorni_gratis=30, bps_fase1=500,
                                                giorni_fase1=180, bps_regime=1200), 0)
        self.assertEqual(commissione_bps_lancio(100, giorni_gratis=30, bps_fase1=500,
                                                giorni_fase1=180, bps_regime=1200), 500)
        self.assertEqual(commissione_bps_lancio(200, giorni_gratis=30, bps_fase1=500,
                                                giorni_fase1=180, bps_regime=1200), 1200)


if __name__ == "__main__":
    unittest.main()
