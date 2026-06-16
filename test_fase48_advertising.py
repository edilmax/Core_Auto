"""
Test funzionali dell'Advertising del Core (fase48, M6). Allocazione budget
proporzionale (vincitrice), conservazione, no-starvation, esclusione campagne morte,
separazione contenuto/denaro, iniezione.
"""
import unittest

from fase48_advertising import (
    Campagna, AllocazioneCampagna, PoliticaBudgetProporzionale, PoliticaBudget,
    StubGeneratoreContenuti, MotoreAdvertising, crea_advertising,
    ripartisci_proporzionale)


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


class TestRipartizione(unittest.TestCase):
    def test_conserva_centesimi(self):
        for tot in (0, 1, 7, 99, 100_001):
            self.assertEqual(sum(ripartisci_proporzionale(tot, [1, 2, 3])), tot)


if __name__ == "__main__":
    unittest.main()
