"""
Test Fase 78 - Sleep Guarantee Engine.

Copre: sleep score (buono/cattivo), garanzia soddisfatta (no rimborso) / non rispettata
(rimborso % in cents), boundary soglia, niente dati -> non_valutabile (no rimborso,
fail-closed), prezzo invalido, politica custom, rimborso intero, robustezza.
"""
import unittest

from fase78_sleep_guarantee import (
    GaranziaSonno, PoliticaSonno, SleepGuaranteeEngine, crea_sleep_guarantee,
)

SONNO_OTTIMO = {"durata": 480, "efficienza": 900, "silenzio": 30, "aria": 500,
                "temp_dev": 0}
SONNO_PESSIMO = {"durata": 300, "efficienza": 600, "silenzio": 55, "aria": 1200,
                 "temp_dev": 400}


class TestScore(unittest.TestCase):
    def test_ottimo_alto(self):
        e = crea_sleep_guarantee()
        self.assertEqual(e.sleep_score(SONNO_OTTIMO)["composito"], 100)

    def test_pessimo_basso(self):
        e = crea_sleep_guarantee()
        self.assertEqual(e.sleep_score(SONNO_PESSIMO)["composito"], 0)

    def test_nessun_dato_none(self):
        self.assertIsNone(crea_sleep_guarantee().sleep_score({}))


class TestGaranzia(unittest.TestCase):
    def setUp(self):
        self.e = crea_sleep_guarantee()   # soglia 80, rimborso 50%

    def test_soddisfatta_no_rimborso(self):
        g = self.e.valuta_garanzia(12000, SONNO_OTTIMO)
        self.assertEqual(g.stato, "soddisfatta")
        self.assertEqual(g.rimborso_cents, 0)
        self.assertEqual(g.score, 100)

    def test_non_rispettata_rimborso(self):
        g = self.e.valuta_garanzia(12000, SONNO_PESSIMO)
        self.assertEqual(g.stato, "rimborso")
        self.assertEqual(g.rimborso_cents, 6000)   # 50% di 12000

    def test_boundary_soglia(self):
        pol = PoliticaSonno(soglia_score=80, rimborso_bps=5000)
        e = crea_sleep_guarantee(pol)
        # costruisco un sonno con score esattamente >= 80: durata media alta
        buono = {"durata": 480, "efficienza": 900, "silenzio": 30, "aria": 1200,
                 "temp_dev": 400}
        g = e.valuta_garanzia(10000, buono)
        # silenzio/aria ok, aria/temp bassi -> verifico che lo stato dipenda dalla soglia
        self.assertIn(g.stato, ("soddisfatta", "rimborso"))
        if g.score >= 80:
            self.assertEqual(g.stato, "soddisfatta")
        else:
            self.assertEqual(g.stato, "rimborso")

    def test_non_valutabile(self):
        g = self.e.valuta_garanzia(12000, {})
        self.assertEqual(g.stato, "non_valutabile")
        self.assertEqual(g.rimborso_cents, 0)      # niente dati -> non si paga

    def test_prezzo_invalido_no_rimborso(self):
        g = self.e.valuta_garanzia(0, SONNO_PESSIMO)
        self.assertEqual(g.stato, "rimborso")
        self.assertEqual(g.rimborso_cents, 0)

    def test_rimborso_intero(self):
        g = self.e.valuta_garanzia(9999, SONNO_PESSIMO)
        self.assertEqual(g.rimborso_cents, (9999 * 5000) // 10000)
        self.assertIsInstance(g.rimborso_cents, int)


class TestPoliticaCustom(unittest.TestCase):
    def test_rimborso_full(self):
        e = crea_sleep_guarantee(PoliticaSonno(soglia_score=90, rimborso_bps=10000))
        g = e.valuta_garanzia(8000, SONNO_PESSIMO)
        self.assertEqual(g.rimborso_cents, 8000)   # 100%

    def test_soglia_alta_rende_difficile(self):
        e = crea_sleep_guarantee(PoliticaSonno(soglia_score=100))
        # score 100 esatto -> soddisfatta; qualsiasi imperfezione -> rimborso
        self.assertEqual(e.valuta_garanzia(10000, SONNO_OTTIMO).stato, "soddisfatta")


class TestRobustezza(unittest.TestCase):
    def test_mai_solleva(self):
        e = crea_sleep_guarantee()
        for bad in (None, 123, "x", []):
            try:
                e.sleep_score(bad)
                e.valuta_garanzia(10000, bad)
                e.valuta_garanzia(bad, SONNO_OTTIMO)
            except Exception as ex:  # pragma: no cover
                self.fail(f"sollevato su {bad!r}: {ex}")

    def test_as_dict(self):
        d = crea_sleep_guarantee().valuta_garanzia(12000, SONNO_OTTIMO).as_dict()
        self.assertEqual(d["money_unit"], "cents_integer")


if __name__ == "__main__":
    unittest.main()
