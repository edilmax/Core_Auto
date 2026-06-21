"""
Test Fase 66 - Tassa di soggiorno (jurisdiction-agnostic).

Copre: default ZERO (giurisdizione ignota/non configurata), componente fissa
per-persona-notte, cap notti, esenzioni, componente percentuale, combinazione, tetto
per-persona, registro + da_env, fail-closed su input invalidi, purezza interi.
"""
import os
import unittest

from fase66_tassa_soggiorno import (
    REGOLA_ZERO, CalcoloTassa, RegistroTasse, RegolaTassa, calcola_tassa,
    crea_registro_tasse,
)


class TestDefaultZero(unittest.TestCase):
    def test_regola_zero(self):
        c = calcola_tassa(REGOLA_ZERO, notti=3, ospiti=2, imponibile_cents=30000)
        self.assertEqual(c.tassa_cents, 0)

    def test_giurisdizione_ignota_zero(self):
        reg = crea_registro_tasse()
        c = reg.calcola("citta-mai-vista", notti=5, ospiti=4, imponibile_cents=50000)
        self.assertEqual(c.tassa_cents, 0)            # mai inventare una tassa


class TestComponenteFissa(unittest.TestCase):
    def test_per_persona_notte(self):
        regola = RegolaTassa(per_persona_notte_cents=350)   # 3.50 a persona/notte
        c = calcola_tassa(regola, notti=3, ospiti=2)
        # 350 * 3 notti * 2 ospiti = 2100
        self.assertEqual(c.tassa_cents, 2100)
        self.assertEqual(c.componente_fissa_cents, 2100)

    def test_cap_notti(self):
        regola = RegolaTassa(per_persona_notte_cents=350, max_notti_tassabili=7)
        c = calcola_tassa(regola, notti=10, ospiti=1)   # solo 7 notti tassate
        self.assertEqual(c.notti_tassabili, 7)
        self.assertEqual(c.tassa_cents, 350 * 7)

    def test_esenzioni(self):
        regola = RegolaTassa(per_persona_notte_cents=350)
        c = calcola_tassa(regola, notti=2, ospiti=4, esenti=2)  # 2 bambini esenti
        self.assertEqual(c.ospiti_tassabili, 2)
        self.assertEqual(c.tassa_cents, 350 * 2 * 2)

    def test_tetto_per_persona(self):
        regola = RegolaTassa(per_persona_notte_cents=500,
                             tetto_per_persona_soggiorno_cents=1000)
        c = calcola_tassa(regola, notti=10, ospiti=2)   # 500*10=5000 cappato a 1000
        self.assertEqual(c.tassa_cents, 1000 * 2)


class TestComponentePercentuale(unittest.TestCase):
    def test_percentuale(self):
        regola = RegolaTassa(percentuale_bps=500)       # 5%
        c = calcola_tassa(regola, notti=3, ospiti=2, imponibile_cents=20000)
        self.assertEqual(c.componente_percentuale_cents, 1000)  # 5% di 20000
        self.assertEqual(c.tassa_cents, 1000)

    def test_percentuale_intera_no_float(self):
        regola = RegolaTassa(percentuale_bps=333)       # 3.33%
        c = calcola_tassa(regola, notti=1, ospiti=1, imponibile_cents=9999)
        self.assertEqual(c.componente_percentuale_cents, (333 * 9999) // 10000)
        self.assertIsInstance(c.componente_percentuale_cents, int)

    def test_combinata(self):
        regola = RegolaTassa(per_persona_notte_cents=200, percentuale_bps=300)
        c = calcola_tassa(regola, notti=2, ospiti=2, imponibile_cents=10000)
        fissa = 200 * 2 * 2          # 800
        perc = (300 * 10000) // 10000  # 300
        self.assertEqual(c.tassa_cents, fissa + perc)


class TestFailClosed(unittest.TestCase):
    def test_input_invalidi_zero(self):
        regola = RegolaTassa(per_persona_notte_cents=350)
        for notti, ospiti in ((-1, 2), (3, -1), (3.0, 2), (3, True)):
            c = calcola_tassa(regola, notti=notti, ospiti=ospiti)
            self.assertEqual(c.tassa_cents, 0)

    def test_regola_non_regola(self):
        c = calcola_tassa("non una regola", notti=3, ospiti=2)
        self.assertEqual(c.tassa_cents, 0)

    def test_imponibile_invalido_ignorato(self):
        regola = RegolaTassa(percentuale_bps=500)
        c = calcola_tassa(regola, notti=1, ospiti=1, imponibile_cents=-100)
        self.assertEqual(c.componente_percentuale_cents, 0)


class TestRegistroEnv(unittest.TestCase):
    def test_da_env(self):
        os.environ["TASSE_TEST_X"] = "roma=350:10:0,amsterdam=0::700"
        try:
            reg = RegistroTasse.da_env("TASSE_TEST_X")
            roma = reg.calcola("Roma", notti=15, ospiti=2)   # case-insensitive, cap 10
            self.assertEqual(roma.tassa_cents, 350 * 10 * 2)
            ams = reg.calcola("amsterdam", notti=2, ospiti=1, imponibile_cents=10000)
            self.assertEqual(ams.tassa_cents, (700 * 10000) // 10000)  # 7%
            self.assertEqual(reg.calcola("berlino", notti=2, ospiti=1).tassa_cents, 0)
        finally:
            del os.environ["TASSE_TEST_X"]

    def test_da_env_malformato_ignorato(self):
        os.environ["TASSE_TEST_Y"] = "spazzatura,roma=abc:def,valida=100::0"
        try:
            reg = RegistroTasse.da_env("TASSE_TEST_Y")
            self.assertEqual(reg.calcola("roma", notti=1, ospiti=1).tassa_cents, 0)
            self.assertEqual(reg.calcola("valida", notti=2, ospiti=1).tassa_cents, 200)
        finally:
            del os.environ["TASSE_TEST_Y"]


class TestContratto(unittest.TestCase):
    def test_as_dict_interi(self):
        regola = RegolaTassa(per_persona_notte_cents=350)
        d = calcola_tassa(regola, notti=2, ospiti=2).as_dict()
        self.assertEqual(d["money_unit"], "cents_integer")
        self.assertIsInstance(d["tassa_cents"], int)


if __name__ == "__main__":
    unittest.main()
