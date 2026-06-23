"""Test Fase 137 - Fedeltà guest. SQLite :memory:, interi."""
import unittest

from fase137_fedelta_guest import crea_fedelta_guest, livello_per_punti


def fg():
    f = crea_fedelta_guest(":memory:")
    f.inizializza_schema()
    return f


class TestLivelli(unittest.TestCase):
    def test_soglie(self):
        self.assertEqual(livello_per_punti(0)[0], "bronze")
        self.assertEqual(livello_per_punti(500)[0], "silver")
        self.assertEqual(livello_per_punti(2000)[0], "gold")
        self.assertEqual(livello_per_punti(5000), ("platinum", 15000))


class TestFedelta(unittest.TestCase):
    def test_accredito_bronze(self):
        f = fg()
        # 100€ = 10000 cents -> 100 punti base * 1.0 (bronze) = 100
        self.assertEqual(f.accredita("p1", "g1", 10000), 100)
        s = f.saldo("g1")
        self.assertEqual(s["punti"], 100)
        self.assertEqual(s["livello"], "bronze")

    def test_idempotente(self):
        f = fg()
        f.accredita("p1", "g1", 10000)
        self.assertEqual(f.accredita("p1", "g1", 10000), 0)   # stesso pren -> 0
        self.assertEqual(f.saldo("g1")["punti"], 100)

    def test_moltiplicatore_livello(self):
        f = fg()
        # porta a silver (>=500 totali): 6 soggiorni da 100€ = 600 punti -> silver
        for i in range(6):
            f.accredita("p%d" % i, "g1", 10000)
        self.assertEqual(f.saldo("g1")["livello"], "silver")
        # ora accredito a silver: 100€ -> 100 base * 1.1 = 110
        self.assertEqual(f.accredita("pX", "g1", 10000), 110)

    def test_riscatto(self):
        f = fg()
        f.accredita("p1", "g1", 10000)                        # 100 punti = 100 cents
        self.assertEqual(f.riscatta("g1", 100), 100)
        self.assertEqual(f.saldo("g1")["punti"], 0)

    def test_riscatto_cap_e_disponibile(self):
        f = fg()
        f.accredita("p1", "g1", 10000)                        # 100 punti
        self.assertEqual(f.riscatta("g1", 999), 100)          # cap al disponibile
        f.accredita("p2", "g1", 10000)
        self.assertEqual(f.riscatta("g1", 100, max_cents=30), 30)  # cap max_cents

    def test_input_invalido(self):
        f = fg()
        self.assertEqual(f.accredita("", "g1", 10000), 0)
        self.assertEqual(f.accredita("p1", "g1", -5), 0)
        self.assertEqual(f.riscatta("g1", 0), 0)

    def test_saldo_vuoto(self):
        self.assertEqual(fg().saldo("gX")["punti"], 0)


if __name__ == "__main__":
    unittest.main()
