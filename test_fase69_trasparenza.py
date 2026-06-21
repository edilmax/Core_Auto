"""
Test Fase 69 - Trasparenza Commissionale.

Copre: confronto base noi-vs-OTA, l'INVARIANTE (guadagno_extra + risparmio_guest ==
surplus, sempre), sconto al guest, tassa separata, PSP pass-through, benchmark
piattaforma, fail-closed, purezza interi.
"""
import unittest

from fase69_trasparenza import (
    OTA_BENCHMARK_BPS, PoliticaConfronto, confronta, confronta_piattaforma,
)


class TestConfrontoBase(unittest.TestCase):
    def test_host_guadagna_di_piu(self):
        pol = PoliticaConfronto(commissione_ota_bps=1800, commissione_nostra_bps=500)
        c = confronta(10000, politica=pol)
        self.assertEqual(c.commissione_ota_cents, 1800)
        self.assertEqual(c.host_netto_ota_cents, 8200)
        self.assertEqual(c.commissione_nostra_cents, 500)
        self.assertEqual(c.host_netto_nostro_cents, 9500)
        self.assertEqual(c.guadagno_extra_host_cents, 1300)   # 9500 - 8200

    def test_surplus(self):
        c = confronta(10000, politica=PoliticaConfronto(commissione_ota_bps=1800,
                                                        commissione_nostra_bps=500))
        self.assertEqual(c.surplus_disintermediazione_cents, 1300)  # 1800 - 500


class TestInvariante(unittest.TestCase):
    def test_invariante_senza_sconto(self):
        c = confronta(12345, politica=PoliticaConfronto(commissione_ota_bps=1700,
                                                        commissione_nostra_bps=400))
        self.assertEqual(c.guadagno_extra_host_cents + c.risparmio_guest_cents,
                         c.surplus_disintermediazione_cents)

    def test_invariante_con_sconto_e_psp(self):
        c = confronta(20000, politica=PoliticaConfronto(commissione_ota_bps=2000,
                      commissione_nostra_bps=500, psp_bps=200),
                      sconto_guest_cents=1500)
        # l'invariante regge anche con sconto al guest e PSP
        self.assertEqual(c.guadagno_extra_host_cents + c.risparmio_guest_cents,
                         c.surplus_disintermediazione_cents)
        self.assertEqual(c.risparmio_guest_cents, 1500)

    def test_invariante_fuzzing(self):
        for P in (100, 999, 10000, 33333, 250000):
            for ota in (1200, 1800, 2500):
                for nostra in (300, 500, 800):
                    for sconto in (0, 100, P // 3):
                        c = confronta(P, politica=PoliticaConfronto(
                            commissione_ota_bps=ota, commissione_nostra_bps=nostra),
                            sconto_guest_cents=sconto)
                        self.assertEqual(
                            c.guadagno_extra_host_cents + c.risparmio_guest_cents,
                            c.surplus_disintermediazione_cents,
                            f"P={P} ota={ota} nostra={nostra} sconto={sconto}")


class TestScontoTassa(unittest.TestCase):
    def test_sconto_al_guest(self):
        c = confronta(10000, politica=PoliticaConfronto(commissione_ota_bps=1800,
                      commissione_nostra_bps=500), sconto_guest_cents=500)
        self.assertEqual(c.imponibile_nostro_cents, 9500)
        self.assertEqual(c.commissione_nostra_cents, (9500 * 500) // 10000)  # 475
        self.assertEqual(c.guest_paga_nostro_cents, 9500)     # senza tassa
        self.assertEqual(c.risparmio_guest_cents, 500)

    def test_tassa_separata_visibile(self):
        c = confronta(10000, tassa_soggiorno_cents=600)
        self.assertEqual(c.tassa_soggiorno_cents, 600)
        self.assertEqual(c.guest_paga_nostro_cents, 10000 + 600)
        self.assertEqual(c.guest_paga_ota_cents, 10000 + 600)

    def test_psp_pass_through(self):
        c = confronta(10000, politica=PoliticaConfronto(commissione_nostra_bps=500,
                                                        psp_bps=200))
        self.assertEqual(c.psp_cents, 200)
        self.assertEqual(c.host_netto_nostro_cents, 10000 - 500 - 200)


class TestPiattaforma(unittest.TestCase):
    def test_benchmark_noto(self):
        c = confronta_piattaforma(10000, "Booking")
        self.assertEqual(c.commissione_ota_cents,
                         (10000 * OTA_BENCHMARK_BPS["booking"]) // 10000)

    def test_piattaforma_ignota_default(self):
        c = confronta_piattaforma(10000, "ota-mai-vista")
        atteso = (10000 * PoliticaConfronto().commissione_ota_bps) // 10000
        self.assertEqual(c.commissione_ota_cents, atteso)


class TestFailClosed(unittest.TestCase):
    def test_input_invalidi(self):
        for P in (0, -1, 10.0, True, None):
            c = confronta(P)
            self.assertEqual(c.host_netto_nostro_cents, 0)
            self.assertEqual(c.surplus_disintermediazione_cents, 0)

    def test_sconto_oltre_prezzo_ignorato(self):
        c = confronta(10000, sconto_guest_cents=99999)
        self.assertEqual(c.risparmio_guest_cents, 0)   # sconto > prezzo -> ignorato

    def test_as_dict_interi(self):
        d = confronta(10000).as_dict()
        self.assertEqual(d["money_unit"], "cents_integer")
        self.assertIsInstance(d["guadagno_extra_host_cents"], int)


if __name__ == "__main__":
    unittest.main()
