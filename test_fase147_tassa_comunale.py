"""Test Fase 147 - Tassa comunale. SQLite :memory:, cents interi."""
import unittest

from fase147_tassa_comunale import calcola_tassa, crea_tassa_comunale


def tc():
    t = crea_tassa_comunale(":memory:")
    t.inizializza_schema()
    return t


class TestCalcolo(unittest.TestCase):
    def test_per_persona_notte(self):
        # 2 paganti * 3 notti * 1.50 = 9.00
        self.assertEqual(calcola_tassa({"ppn_cents": 150}, 2, 3), 900)

    def test_cap_notti(self):
        self.assertEqual(calcola_tassa({"ppn_cents": 100, "max_notti": 2}, 1, 10), 200)

    def test_esenti(self):
        self.assertEqual(calcola_tassa({"ppn_cents": 100}, 3, 2, esenti=1), 400)  # 2 paganti

    def test_percentuale_su_imponibile(self):
        self.assertEqual(calcola_tassa({"perc_bps": 500}, 1, 1, imponibile_cents=10000), 500)

    def test_cap_persona(self):
        r = {"ppn_cents": 100, "cap_persona_cents": 250}
        self.assertEqual(calcola_tassa(r, 2, 10), 500)     # cap 2.50/persona * 2

    def test_zero_e_invalidi(self):
        self.assertEqual(calcola_tassa({}, 2, 3), 0)
        self.assertEqual(calcola_tassa({"ppn_cents": 100}, -1, 3), 0)


class TestRegistro(unittest.TestCase):
    def test_regola_e_applica(self):
        t = tc()
        self.assertTrue(t.imposta_regola("Roma", {"ppn_cents": 350, "max_notti": 10}))
        self.assertEqual(t.applica("roma", 2, 3), 2100)    # case-insensitive
        self.assertEqual(t.applica("CittaIgnota", 2, 3), 0)  # ignoto -> 0

    def test_ledger_riscossioni(self):
        t = tc()
        t.imposta_regola("Roma", {"ppn_cents": 350})
        imp = t.applica("Roma", 2, 2)
        self.assertTrue(t.registra_riscossione("p1", "Roma", imp))
        self.assertTrue(t.registra_riscossione("p2", "Roma", 700))
        self.assertEqual(t.totale_riscosso("roma"), imp + 700)

    def test_riscossione_idempotente(self):
        t = tc()
        t.registra_riscossione("p1", "Roma", 100)
        t.registra_riscossione("p1", "Roma", 999)          # IGNORE
        self.assertEqual(t.totale_riscosso("Roma"), 100)

    def test_input_invalido(self):
        t = tc()
        self.assertFalse(t.imposta_regola("", {"ppn_cents": 1}))
        self.assertFalse(t.registra_riscossione("", "Roma", 100))
        self.assertFalse(t.registra_riscossione("p1", "Roma", -5))


if __name__ == "__main__":
    unittest.main()
