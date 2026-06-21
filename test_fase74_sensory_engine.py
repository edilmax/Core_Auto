"""
Test Fase 74 - Sensory Engine (Sensory Score).

Copre: punteggio per-dimensione (ideale=100, peggiore=0, interpolazione, clamp), sia
"basso meglio" (rumore/CO2) sia "alto meglio" (lux), dimensione ignota / valore non
intero, composito pesato sui presenti (assenti non penalizzano), nessun dato -> None,
badge a soglia (fail-closed), livelli, config custom, purezza interi, robustezza.
"""
import unittest

from fase74_sensory_engine import (
    METRICHE_DEFAULT, MetricaSensoriale, SensoryEngine, crea_sensory_engine,
)


class TestPunteggioDimensione(unittest.TestCase):
    def setUp(self):
        self.e = crea_sensory_engine()

    def test_silenzio_basso_meglio(self):
        self.assertEqual(self.e.punteggio_dimensione("silenzio", 30), 100)  # ideale
        self.assertEqual(self.e.punteggio_dimensione("silenzio", 70), 0)    # peggiore
        self.assertEqual(self.e.punteggio_dimensione("silenzio", 50), 50)   # mezzo

    def test_clamp(self):
        self.assertEqual(self.e.punteggio_dimensione("silenzio", 20), 100)  # < ideale
        self.assertEqual(self.e.punteggio_dimensione("silenzio", 90), 0)    # > peggiore

    def test_aria_co2(self):
        self.assertEqual(self.e.punteggio_dimensione("aria", 400), 100)
        self.assertEqual(self.e.punteggio_dimensione("aria", 1400), 0)

    def test_luce_alto_meglio(self):
        self.assertEqual(self.e.punteggio_dimensione("luce", 1000), 100)
        self.assertEqual(self.e.punteggio_dimensione("luce", 0), 0)
        self.assertEqual(self.e.punteggio_dimensione("luce", 500), 50)

    def test_dimensione_ignota(self):
        self.assertIsNone(self.e.punteggio_dimensione("telepatia", 50))

    def test_valore_non_intero(self):
        self.assertIsNone(self.e.punteggio_dimensione("silenzio", 50.0))
        self.assertIsNone(self.e.punteggio_dimensione("silenzio", True))
        self.assertIsNone(self.e.punteggio_dimensione("silenzio", "50"))


class TestComposito(unittest.TestCase):
    def setUp(self):
        self.e = crea_sensory_engine()

    def test_media_pesata(self):
        r = self.e.punteggio_composito({"silenzio": 30, "aria": 400})  # 100 e 100
        self.assertEqual(r["composito"], 100)
        self.assertEqual(set(r["dettaglio"].keys()), {"silenzio", "aria"})

    def test_assenti_non_penalizzano(self):
        # solo silenzio presente e perfetto -> composito 100, non diluito dagli assenti
        r = self.e.punteggio_composito({"silenzio": 30})
        self.assertEqual(r["composito"], 100)
        self.assertEqual(list(r["dettaglio"].keys()), ["silenzio"])

    def test_pesi(self):
        # silenzio(peso30)=100, ascensore(peso5)=0 -> (100*30+0*5)/35 = 85
        r = self.e.punteggio_composito({"silenzio": 30, "ascensore": 90})
        self.assertEqual(r["composito"], (100 * 30 + 0 * 5) // 35)

    def test_nessun_dato_none(self):
        self.assertIsNone(self.e.punteggio_composito({}))
        self.assertIsNone(self.e.punteggio_composito({"ignota": 5, "silenzio": 1.5}))

    def test_non_dict(self):
        self.assertIsNone(self.e.punteggio_composito("non dict"))

    def test_livello_presente(self):
        r = self.e.punteggio_composito({"silenzio": 30})
        self.assertEqual(r["livello"], "eccellente")


class TestBadge(unittest.TestCase):
    def setUp(self):
        self.e = crea_sensory_engine()

    def test_badge_eccellente(self):
        b = self.e.badge("aria", 400)        # score 100
        self.assertEqual(b, ("eccellente", 100))

    def test_badge_buono(self):
        # silenzio a 44 dB -> score = (100*(44-70))//(30-70) = 65 -> buono
        b = self.e.badge("silenzio", 44)
        self.assertEqual(b[0], "buono")
        self.assertGreaterEqual(b[1], 65)

    def test_nessun_badge_sotto_soglia(self):
        self.assertIsNone(self.e.badge("silenzio", 55))   # score 37 -> niente badge
        self.assertIsNone(self.e.badge("ignota", 10))


class TestLivello(unittest.TestCase):
    def test_soglie(self):
        self.assertEqual(SensoryEngine.livello(90), "eccellente")
        self.assertEqual(SensoryEngine.livello(70), "buono")
        self.assertEqual(SensoryEngine.livello(40), "base")


class TestConfigCustom(unittest.TestCase):
    def test_metriche_custom(self):
        e = crea_sensory_engine({"rumore": MetricaSensoriale(0, 100, peso=1)})
        self.assertEqual(e.punteggio_dimensione("rumore", 0), 100)
        self.assertIsNone(e.punteggio_dimensione("silenzio", 30))  # non in config custom

    def test_default_intatto(self):
        self.assertIn("silenzio", METRICHE_DEFAULT)


class TestRobustezza(unittest.TestCase):
    def test_mai_solleva(self):
        e = crea_sensory_engine()
        for bad in (None, 123, "x", [], {}):
            try:
                e.punteggio_dimensione("silenzio", bad)
                e.punteggio_composito(bad)
                e.badge("silenzio", bad)
            except Exception as ex:  # pragma: no cover
                self.fail(f"sollevato su {bad!r}: {ex}")

    def test_interi(self):
        r = crea_sensory_engine().punteggio_composito({"silenzio": 40})
        self.assertIsInstance(r["composito"], int)


if __name__ == "__main__":
    unittest.main()
