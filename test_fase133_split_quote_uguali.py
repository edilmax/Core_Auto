"""Test Fase 133 - Split quote uguali. SQLite :memory:, cents interi."""
import unittest

from fase133_split_quote_uguali import crea_split_quote, riparti_uguale


class TestRiparti(unittest.TestCase):
    def test_conservazione_esatta(self):
        for tot, k in ((10000, 3), (100, 3), (1, 4), (999, 7), (12345, 10)):
            q = riparti_uguale(tot, k)
            self.assertEqual(sum(q), tot)
            self.assertEqual(len(q), k)
            self.assertLessEqual(max(q) - min(q), 1)        # quasi uguali

    def test_resto_primi(self):
        self.assertEqual(riparti_uguale(100, 3), [34, 33, 33])

    def test_invalidi(self):
        self.assertEqual(riparti_uguale(100, 0), [])
        self.assertEqual(riparti_uguale(-5, 3), [])
        self.assertEqual(riparti_uguale("x", 3), [])


def sp():
    s = crea_split_quote(":memory:")
    s.inizializza_schema()
    return s


class TestSplit(unittest.TestCase):
    def test_crea_e_stato(self):
        s = sp()
        self.assertTrue(s.crea_gruppo("g1", 10000, ["a", "b", "c"]))
        st = s.stato("g1")
        self.assertEqual(st["totale_cents"], 10000)
        self.assertEqual(sum(st["quote"].values()), 10000)
        self.assertFalse(st["completato"])

    def test_pagamento_e_completamento(self):
        s = sp()
        s.crea_gruppo("g1", 9000, ["a", "b", "c"])
        for p in ("a", "b", "c"):
            self.assertTrue(s.paga("g1", p))
        st = s.stato("g1")
        self.assertTrue(st["completato"])
        self.assertEqual(st["mancanti"], [])

    def test_paga_idempotente(self):
        s = sp()
        s.crea_gruppo("g1", 9000, ["a", "b", "c"])
        self.assertTrue(s.paga("g1", "a"))
        self.assertFalse(s.paga("g1", "a"))                 # già pagato

    def test_duplicato_gruppo(self):
        s = sp()
        s.crea_gruppo("g1", 9000, ["a", "b"])
        self.assertFalse(s.crea_gruppo("g1", 1, ["x"]))

    def test_partecipanti_duplicati(self):
        s = sp()
        self.assertFalse(s.crea_gruppo("g1", 9000, ["a", "a"]))

    def test_vuoto(self):
        self.assertEqual(sp().stato("gX"), {})


if __name__ == "__main__":
    unittest.main()
