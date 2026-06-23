"""Test Fase 149 - Deposito cauzionale. SQLite :memory:, PSP iniettato: nessuna rete."""
import unittest

from fase149_deposito_cauzionale import crea_deposito_cauzionale


def dep(cap=lambda ref, imp: True, rel=lambda ref: True):
    d = crea_deposito_cauzionale(":memory:", capture=cap, release=rel)
    d.inizializza_schema()
    return d


class TestDeposito(unittest.TestCase):
    def test_autorizza_e_rilascia(self):
        d = dep()
        self.assertTrue(d.autorizza("p1", "pi_1", 30000))
        s = d.stato("p1")
        self.assertEqual(s["autorizzato_cents"], 30000)
        self.assertEqual(s["stato"], "autorizzato")
        self.assertTrue(d.rilascia("p1"))
        self.assertEqual(d.stato("p1")["stato"], "rilasciato")
        self.assertEqual(d.stato("p1")["rilasciato_cents"], 30000)

    def test_cattura_danno_conservazione(self):
        d = dep()
        d.autorizza("p1", "pi_1", 30000)
        self.assertTrue(d.cattura_danno("p1", 5000))
        s = d.stato("p1")
        self.assertEqual(s["catturato_cents"], 5000)
        self.assertEqual(s["rilasciato_cents"], 25000)     # 30000-5000
        self.assertEqual(s["stato"], "catturato_parziale")

    def test_danno_oltre_autorizzato_rifiutato(self):
        d = dep()
        d.autorizza("p1", "pi_1", 30000)
        self.assertFalse(d.cattura_danno("p1", 40000))     # > autorizzato

    def test_danno_zero_rilascia(self):
        d = dep()
        d.autorizza("p1", "pi_1", 30000)
        self.assertTrue(d.cattura_danno("p1", 0))
        self.assertEqual(d.stato("p1")["stato"], "rilasciato")

    def test_capture_psp_fallisce_rollback(self):
        d = dep(cap=lambda ref, imp: False)
        d.autorizza("p1", "pi_1", 30000)
        self.assertFalse(d.cattura_danno("p1", 5000))
        self.assertEqual(d.stato("p1")["stato"], "autorizzato")   # invariato

    def test_capture_gated_senza_psp(self):
        d = crea_deposito_cauzionale(":memory:")           # niente capture
        d.inizializza_schema()
        d.autorizza("p1", "pi_1", 30000)
        self.assertFalse(d.cattura_danno("p1", 5000))

    def test_input_invalido(self):
        d = dep()
        self.assertFalse(d.autorizza("", "pi_1", 30000))
        self.assertFalse(d.autorizza("p1", "pi_1", 0))
        self.assertEqual(d.stato("pX"), {})

    def test_idempotente_autorizza(self):
        d = dep()
        self.assertTrue(d.autorizza("p1", "pi_1", 30000))
        self.assertTrue(d.autorizza("p1", "pi_1", 30000))  # IGNORE, stesso importo


if __name__ == "__main__":
    unittest.main()
