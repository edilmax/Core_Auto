"""
Test funzionali dell'Advertising del Core (fase48, M6). Allocazione budget
proporzionale (vincitrice), conservazione, no-starvation, esclusione campagne morte,
separazione contenuto/denaro, iniezione, fail-closed (CircuitBreakerBudget),
input corrotti, fuzzing.
"""
import random
import unittest

from fase48_advertising import (
    Campagna, AllocazioneCampagna, PoliticaBudgetProporzionale, PoliticaBudget,
    StubGeneratoreContenuti, MotoreAdvertising, crea_advertising,
    ripartisci_proporzionale, CircuitBreakerBudget)


def _c(id, prio=5, rich=10_000, canale="instagram"):
    return Campagna(id, canale, prio, rich)


class TestAllocazione(unittest.TestCase):
    def setUp(self):
        self.mot = crea_advertising()

    def test_conservazione_spende_tutto(self):
        camp = [_c("a", 1), _c("b", 3), _c("c", 6)]
        alloc = self.mot.pianifica(100_000, camp)
        self.assertEqual(sum(x.importo_cents for x in alloc), 100_000)

    def test_proporzionale_alla_priorita(self):
        camp = [_c("bassa", 1), _c("alta", 9)]
        alloc = {x.campagna_id: x.importo_cents for x in self.mot.pianifica(100_000, camp)}
        self.assertGreater(alloc["alta"], alloc["bassa"])

    def test_campagna_morta_esclusa(self):
        camp = [_c("morta", 0), _c("viva", 5)]
        alloc = {x.campagna_id: x.importo_cents for x in self.mot.pianifica(10_000, camp)}
        self.assertEqual(alloc["morta"], 0)
        self.assertEqual(alloc["viva"], 10_000)

    def test_no_starvation(self):
        camp = [_c("a", 3), _c("b", 2), _c("c", 1)]
        alloc = self.mot.pianifica(1000, camp)
        self.assertTrue(all(x.importo_cents >= 1 for x in alloc))

    def test_separazione_contenuto_denaro(self):
        testo = self.mot.contenuto(_c("hotelroma", canale="whatsapp"))
        self.assertIn("hotelroma", testo)
        self.assertIn("whatsapp", testo)

    def test_iniezione_generatore(self):
        class GenUrlato(StubGeneratoreContenuti):
            def genera(self, c): return "OFFERTA!!!"
        mot = crea_advertising(generatore=GenUrlato())
        self.assertEqual(mot.contenuto(_c("x")), "OFFERTA!!!")


class TestBudgetLimite(unittest.TestCase):
    def setUp(self):
        self.mot = crea_advertising()

    def test_budget_zero(self):
        alloc = self.mot.pianifica(0, [_c("a", 5), _c("b", 3)])
        self.assertTrue(all(x.importo_cents == 0 for x in alloc))

    def test_budget_minore_del_numero_campagne(self):
        # 2 cent, 3 campagne vive: solo le 2 piu' prioritarie ricevono 1 cent
        camp = [_c("a", 1), _c("b", 9), _c("c", 5)]
        alloc = {x.campagna_id: x.importo_cents for x in self.mot.pianifica(2, camp)}
        self.assertEqual(sum(alloc.values()), 2)
        self.assertEqual(alloc["b"], 1)
        self.assertEqual(alloc["c"], 1)
        self.assertEqual(alloc["a"], 0)

    def test_un_solo_cent(self):
        camp = [_c("a", 4), _c("b", 7)]
        alloc = {x.campagna_id: x.importo_cents for x in self.mot.pianifica(1, camp)}
        self.assertEqual(alloc["b"], 1)
        self.assertEqual(alloc["a"], 0)

    def test_tutte_morte(self):
        alloc = self.mot.pianifica(10_000, [_c("a", 0), _c("b", 0)])
        self.assertTrue(all(x.importo_cents == 0 for x in alloc))

    def test_lista_vuota(self):
        self.assertEqual(self.mot.pianifica(10_000, []), [])

    def test_mai_overspend(self):
        camp = [_c("a", 1), _c("b", 2), _c("c", 3)]
        for budget in (0, 1, 2, 3, 4, 5, 17, 100, 99_999):
            alloc = self.mot.pianifica(budget, camp)
            self.assertLessEqual(sum(x.importo_cents for x in alloc), budget)


class TestCircuitBreaker(unittest.TestCase):
    def test_overspend_blocca(self):
        class PolGolosa(PoliticaBudget):
            def alloca(self, budget_cents, campagne):
                return [budget_cents + 1 for _ in campagne]
            def descrizione(self): return "golosa"
        mot = crea_advertising(politica=PolGolosa())
        with self.assertRaises(CircuitBreakerBudget):
            mot.pianifica(1_000, [_c("a")])

    def test_lunghezza_errata_blocca(self):
        class PolCorta(PoliticaBudget):
            def alloca(self, budget_cents, campagne):
                return [0]
            def descrizione(self): return "corta"
        mot = crea_advertising(politica=PolCorta())
        with self.assertRaises(CircuitBreakerBudget):
            mot.pianifica(1_000, [_c("a"), _c("b")])

    def test_importo_negativo_blocca(self):
        class PolNegativa(PoliticaBudget):
            def alloca(self, budget_cents, campagne):
                return [-1 for _ in campagne]
            def descrizione(self): return "negativa"
        mot = crea_advertising(politica=PolNegativa())
        with self.assertRaises(ValueError):
            mot.pianifica(1_000, [_c("a")])


class TestInputCorrotti(unittest.TestCase):
    def setUp(self):
        self.mot = crea_advertising()

    def test_budget_negativo(self):
        with self.assertRaises(ValueError):
            self.mot.pianifica(-1, [_c("a")])

    def test_budget_bool_rifiutato(self):
        with self.assertRaises(ValueError):
            self.mot.pianifica(True, [_c("a")])

    def test_priorita_negativa(self):
        with self.assertRaises(ValueError):
            Campagna("a", "instagram", -1, 10_000)

    def test_priorita_bool_rifiutata(self):
        with self.assertRaises(ValueError):
            Campagna("a", "instagram", True, 10_000)

    def test_richiesta_negativa(self):
        with self.assertRaises(ValueError):
            Campagna("a", "instagram", 5, -1)

    def test_id_vuoto(self):
        with self.assertRaises(ValueError):
            Campagna("", "instagram", 5, 10_000)

    def test_canale_vuoto(self):
        with self.assertRaises(ValueError):
            Campagna("a", "", 5, 10_000)


class TestRipartizione(unittest.TestCase):
    def test_conserva_centesimi(self):
        for tot in (0, 1, 7, 99, 100_001):
            self.assertEqual(sum(ripartisci_proporzionale(tot, [1, 2, 3])), tot)

    def test_pesi_tutti_zero(self):
        self.assertEqual(ripartisci_proporzionale(100, [0, 0, 0]), [0, 0, 0])

    def test_lista_pesi_vuota(self):
        self.assertEqual(ripartisci_proporzionale(0, []), [])


class TestFuzzing(unittest.TestCase):
    def setUp(self):
        self.mot = crea_advertising()

    def test_conservazione_e_no_overspend(self):
        rnd = random.Random(48)
        for _ in range(2_000):
            n = rnd.randint(0, 12)
            camp = [_c(f"c{i}", prio=rnd.randint(0, 9)) for i in range(n)]
            budget = rnd.randint(0, 1_000_000)
            alloc = self.mot.pianifica(budget, camp)
            tot = sum(x.importo_cents for x in alloc)
            self.assertLessEqual(tot, budget)
            self.assertTrue(all(x.importo_cents >= 0 for x in alloc))
            vive = [c for c in camp if c.priorita > 0]
            if vive and budget >= len(vive):
                self.assertEqual(tot, budget)  # spende tutto quando puo'
                vivi_id = {c.id for c in vive}
                for x in alloc:
                    if x.campagna_id in vivi_id:
                        self.assertGreaterEqual(x.importo_cents, 1)  # no-starvation
                    else:
                        self.assertEqual(x.importo_cents, 0)  # morte escluse

    def test_ripartizione_fuzz_conserva(self):
        rnd = random.Random(2025)
        for _ in range(2_000):
            tot = rnd.randint(0, 5_000_000)
            pesi = [rnd.randint(0, 20) for _ in range(rnd.randint(0, 10))]
            parti = ripartisci_proporzionale(tot, pesi)
            self.assertEqual(len(parti), len(pesi))
            self.assertTrue(all(p >= 0 for p in parti))
            atteso = tot if (pesi and sum(pesi) > 0) else 0
            self.assertEqual(sum(parti), atteso)


if __name__ == "__main__":
    unittest.main()
