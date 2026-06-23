"""Test Fase 111 - Cancellazione flessibile + rimborso. Puro, cents interi."""
import unittest

from fase111_cancellazione import (POLITICHE, PoliticaCancellazione, calcola_rimborso,
                                   crea_politica_cancellazione)


class TestRimborso(unittest.TestCase):
    def test_flessibile_pieno(self):
        r = calcola_rimborso(10000, 5, politica="flessibile")
        self.assertEqual(r["rimborso_cents"], 10000)        # >=1 giorno -> 100%
        self.assertEqual(r["trattenuto_cents"], 0)

    def test_flessibile_stesso_giorno_meta(self):
        r = calcola_rimborso(10000, 0, politica="flessibile")
        self.assertEqual(r["rimborso_cents"], 5000)         # 0 giorni -> 50%

    def test_moderata_scaglioni(self):
        self.assertEqual(calcola_rimborso(10000, 5, politica="moderata")["rimborso_cents"], 10000)
        self.assertEqual(calcola_rimborso(10000, 3, politica="moderata")["rimborso_cents"], 5000)
        self.assertEqual(calcola_rimborso(10000, 0, politica="moderata")["rimborso_cents"], 0)

    def test_rigida(self):
        self.assertEqual(calcola_rimborso(10000, 20, politica="rigida")["rimborso_cents"], 10000)
        self.assertEqual(calcola_rimborso(10000, 10, politica="rigida")["rimborso_cents"], 5000)
        self.assertEqual(calcola_rimborso(10000, 2, politica="rigida")["rimborso_cents"], 0)

    def test_fee_pulizia_sempre_resa(self):
        # rigida, 2 giorni -> soggiorno 0%, ma pulizia 2000 sempre rimborsata
        r = calcola_rimborso(12000, 2, politica="rigida", fee_pulizia_cents=2000)
        self.assertEqual(r["rimborso_cents"], 2000)
        self.assertEqual(r["trattenuto_cents"], 10000)

    def test_input_invalido_failclosed(self):
        self.assertEqual(calcola_rimborso(0, 5)["rimborso_cents"], 0)
        self.assertEqual(calcola_rimborso(-5, 5)["rimborso_cents"], 0)
        self.assertEqual(calcola_rimborso(10000, -3, politica="moderata")["rimborso_cents"], 0)

    def test_cents_interi_e_conservazione(self):
        r = calcola_rimborso(9999, 3, politica="moderata")
        self.assertIsInstance(r["rimborso_cents"], int)
        self.assertEqual(r["rimborso_cents"] + r["trattenuto_cents"], 9999)

    def test_politica_custom(self):
        pol = crea_politica_cancellazione("x", [(2, 10000), (0, 2000)])
        self.assertIsInstance(pol, PoliticaCancellazione)
        self.assertEqual(calcola_rimborso(10000, 0, politica=pol)["rimborso_cents"], 2000)

    def test_politica_sconosciuta_usa_flessibile(self):
        self.assertEqual(calcola_rimborso(10000, 5, politica="boh")["politica"], "flessibile")


if __name__ == "__main__":
    unittest.main()
