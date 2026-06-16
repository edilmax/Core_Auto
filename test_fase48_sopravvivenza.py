"""
Suite di SOPRAVVIVENZA TOTALE per M6 (fase48) - Manifesto dell'Eternita'.
CHAOS (input corrotti, CircuitBreakerBudget anti-overspend), FUZZING (conservazione
+ no-overspend su migliaia di scenari), ISOLAMENTO (politica rotta non contagia),
IDEMPOTENZA.
"""
import random
import unittest

from fase48_advertising import (
    Campagna, PoliticaBudgetProporzionale, PoliticaBudget, MotoreAdvertising,
    CircuitBreakerBudget, crea_advertising, ripartisci_proporzionale)


def _c(id, prio=5, rich=10_000):
    return Campagna(id, "instagram", prio, rich)


class TestChaosAdvertising(unittest.TestCase):
    def test_campagna_corrotta_rifiutata(self):
        for kw in (dict(id="", canale="ig", priorita=1, richiesta_cents=1),
                   dict(id="a", canale="", priorita=1, richiesta_cents=1),
                   dict(id="a", canale="ig", priorita=-1, richiesta_cents=1),
                   dict(id="a", canale="ig", priorita=1, richiesta_cents=-1)):
            with self.assertRaises(ValueError):
                Campagna(**kw)

    def test_breaker_overspend_bloccato(self):
        class PoliticaPazza(PoliticaBudget):
            def alloca(self, budget, campagne): return [budget * 10 for _ in campagne]
            def descrizione(self): return "pazza"
        mot = MotoreAdvertising(PoliticaPazza())
        with self.assertRaises(CircuitBreakerBudget):
            mot.pianifica(10_000, [_c("a"), _c("b")])

    def test_breaker_numero_importi_errato(self):
        class PoliticaCorta(PoliticaBudget):
            def alloca(self, budget, campagne): return [1]      # troppo pochi
            def descrizione(self): return "corta"
        with self.assertRaises(CircuitBreakerBudget):
            MotoreAdvertising(PoliticaCorta()).pianifica(10_000, [_c("a"), _c("b")])


class TestFuzzingAdvertising(unittest.TestCase):
    def test_fuzz_mai_overspend(self):
        mot = crea_advertising()
        rng = random.Random(48)
        for _ in range(5000):
            k = rng.randint(0, 8)
            camp = [_c("c%d" % i, rng.randint(0, 10), rng.randint(1, 10**6)) for i in range(k)]
            budget = rng.randint(0, 500_000)
            alloc = mot.pianifica(budget, camp)
            tot = sum(x.importo_cents for x in alloc)
            self.assertLessEqual(tot, budget)               # MAI overspend
            self.assertTrue(all(x.importo_cents >= 0 for x in alloc))
            # se c'e' almeno una campagna viva e budget>0 -> spende tutto
            if budget > 0 and any(c.priorita > 0 for c in camp):
                self.assertEqual(tot, budget)

    def test_fuzz_ripartizione_conserva(self):
        rng = random.Random(7)
        for _ in range(20000):
            tot = rng.randint(0, 10**9)
            pesi = [rng.randint(0, 100) for _ in range(rng.randint(1, 6))]
            self.assertEqual(sum(ripartisci_proporzionale(tot, pesi)), tot if sum(pesi) else 0)


class TestIsolamentoIdempotenza(unittest.TestCase):
    def test_politica_rotta_non_contagia(self):
        class PoliticaEsplosiva(PoliticaBudget):
            def alloca(self, b, c): raise RuntimeError("rotta")
            def descrizione(self): return "x"
        with self.assertRaises(RuntimeError):
            MotoreAdvertising(PoliticaEsplosiva()).pianifica(10_000, [_c("a")])
        # il motore sano resta operativo
        ok = crea_advertising().pianifica(10_000, [_c("a")])
        self.assertEqual(ok[0].importo_cents, 10_000)

    def test_idempotenza(self):
        mot = crea_advertising()
        camp = [_c("a", 3), _c("b", 7), _c("c", 1)]
        a = [(x.campagna_id, x.importo_cents) for x in mot.pianifica(77_777, camp)]
        b = [(x.campagna_id, x.importo_cents) for x in mot.pianifica(77_777, camp)]
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
