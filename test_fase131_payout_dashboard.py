"""Test Fase 131 - Payout dashboard. SQLite :memory:."""
import unittest

from fase131_payout_dashboard import crea_payout_dashboard


def pd():
    p = crea_payout_dashboard(":memory:")
    p.inizializza_schema()
    return p


class TestPayout(unittest.TestCase):
    def test_maturato_e_riepilogo_per_valuta(self):
        p = pd()
        self.assertTrue(p.registra_maturato("p1", "h1", 9700, "USD"))
        self.assertTrue(p.registra_maturato("p2", "h1", 5000, "EUR"))
        r = p.riepilogo("h1")
        self.assertEqual(r["USD"]["maturato"], 9700)
        self.assertEqual(r["EUR"]["maturato"], 5000)

    def test_transizioni_valide(self):
        p = pd()
        p.registra_maturato("p1", "h1", 9700, "USD")
        self.assertTrue(p.aggiorna_stato("p1", "in_transito"))
        self.assertTrue(p.aggiorna_stato("p1", "pagato"))
        self.assertFalse(p.aggiorna_stato("p1", "maturato"))   # pagato è terminale

    def test_transizione_illegale(self):
        p = pd()
        p.registra_maturato("p1", "h1", 9700, "USD")
        self.assertFalse(p.aggiorna_stato("p1", "pagato"))     # maturato->pagato no
        self.assertFalse(p.aggiorna_stato("p1", "boh"))

    def test_da_pagare(self):
        p = pd()
        p.registra_maturato("p1", "h1", 9700, "USD")
        p.registra_maturato("p2", "h1", 3000, "USD")
        p.aggiorna_stato("p2", "in_transito")
        self.assertEqual(p.da_pagare("h1", "USD"), 12700)
        p.aggiorna_stato("p2", "pagato")
        self.assertEqual(p.da_pagare("h1", "USD"), 9700)       # pagato escluso

    def test_input_invalido(self):
        p = pd()
        self.assertFalse(p.registra_maturato("p1", "h1", -5, "USD"))
        self.assertFalse(p.registra_maturato("p1", "h1", 100, "EURO"))
        self.assertFalse(p.registra_maturato("", "h1", 100, "USD"))

    def test_idempotente(self):
        p = pd()
        p.registra_maturato("p1", "h1", 9700, "USD")
        p.registra_maturato("p1", "h1", 9999, "USD")           # IGNORE
        self.assertEqual(p.riepilogo("h1")["USD"]["maturato"], 9700)

    def test_host_vuoto(self):
        self.assertEqual(pd().riepilogo("hX"), {})


if __name__ == "__main__":
    unittest.main()
