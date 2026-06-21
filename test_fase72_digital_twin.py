"""
Test Fase 72 - Digital Twin (telemetria + manutenzione predittiva).

Copre: registrazione letture + stato, validazione (no float), anomalie (fuori banda),
predizione guasti (trend su/giu verso soglia, stabile non predice, gia' oltre non
predice), agibilita' (critici in banda / assenti / fuori banda), report pre/post,
robustezza, stress concorrente. Orologio iniettato.
"""
import os
import shutil
import tempfile
import threading
import unittest

from fase72_digital_twin import (
    Anomalia, DigitalTwin, PredizioneGuasto, SensoreConfig, crea_digital_twin,
)

# temperatura in centi-gradi, umidita' in per-mille
TEMP = SensoreConfig(banda_min=1800, banda_max=2500, critico=True)
UMID = SensoreConfig(banda_min=300, banda_max=600, soglia_guasto=800, direzione="su")
CONFIG = {"temp": TEMP, "umidita": UMID}


class TestLetture(unittest.TestCase):
    def setUp(self):
        self.t = crea_digital_twin()

    def test_registra_e_stato(self):
        self.t.registra_lettura("casa", "temp", 2100, ts=100)
        self.t.registra_lettura("casa", "temp", 2200, ts=200)
        st = self.t.stato("casa")
        self.assertEqual(st["temp"]["valore"], 2200)     # l'ultima

    def test_valore_float_rifiutato(self):
        self.assertFalse(self.t.registra_lettura("casa", "temp", 21.5, ts=100))
        self.assertFalse(self.t.registra_lettura("casa", "temp", True, ts=100))

    def test_input_invalido(self):
        self.assertFalse(self.t.registra_lettura("", "temp", 2000))
        self.assertFalse(self.t.registra_lettura("casa", "", 2000))


class TestAnomalie(unittest.TestCase):
    def test_fuori_banda(self):
        t = crea_digital_twin()
        t.registra_lettura("casa", "temp", 3000, ts=100)   # troppo caldo (>2500)
        an = t.anomalie("casa", CONFIG)
        self.assertEqual(len(an), 1)
        self.assertEqual(an[0].sensore, "temp")
        self.assertIsInstance(an[0], Anomalia)

    def test_in_banda_nessuna(self):
        t = crea_digital_twin()
        t.registra_lettura("casa", "temp", 2100, ts=100)
        self.assertEqual(t.anomalie("casa", CONFIG), [])


class TestPredizione(unittest.TestCase):
    def test_trend_su_verso_soglia(self):
        t = crea_digital_twin()
        # umidita' sale 400->500->600->700 in 3000s; soglia guasto 800
        for i, v in enumerate((400, 500, 600, 700)):
            t.registra_lettura("casa", "umidita", v, ts=1000 + i * 1000)
        pred = t.predici_guasti("casa", CONFIG, orizzonte_sec=2000)
        self.assertEqual(len(pred), 1)
        self.assertEqual(pred[0].sensore, "umidita")
        self.assertGreaterEqual(pred[0].valore_proiettato, 800)
        self.assertIsInstance(pred[0], PredizioneGuasto)

    def test_stabile_non_predice(self):
        t = crea_digital_twin()
        for i in range(5):
            t.registra_lettura("casa", "umidita", 450, ts=1000 + i * 1000)
        self.assertEqual(t.predici_guasti("casa", CONFIG, orizzonte_sec=10000), [])

    def test_gia_oltre_soglia_non_predice(self):
        t = crea_digital_twin()
        for i, v in enumerate((820, 850, 900)):
            t.registra_lettura("casa", "umidita", v, ts=1000 + i * 1000)
        # gia' oltre la soglia -> e' anomalia, non predizione
        self.assertEqual(t.predici_guasti("casa", CONFIG, orizzonte_sec=10000), [])

    def test_trend_giu(self):
        t = crea_digital_twin()
        cfg = {"batteria": SensoreConfig(banda_min=0, banda_max=10000,
                                         soglia_guasto=1000, direzione="giu")}
        for i, v in enumerate((5000, 4000, 3000, 2000)):
            t.registra_lettura("casa", "batteria", v, ts=1000 + i * 1000)
        pred = t.predici_guasti("casa", cfg, orizzonte_sec=2000)
        self.assertEqual(len(pred), 1)
        self.assertLessEqual(pred[0].valore_proiettato, 1000)

    def test_orizzonte_breve_non_predice(self):
        t = crea_digital_twin()
        for i, v in enumerate((400, 410, 420)):     # sale lentamente
            t.registra_lettura("casa", "umidita", v, ts=1000 + i * 1000)
        self.assertEqual(t.predici_guasti("casa", CONFIG, orizzonte_sec=100), [])


class TestAgibilita(unittest.TestCase):
    def test_critico_in_banda_pronto(self):
        t = crea_digital_twin()
        t.registra_lettura("casa", "temp", 2100, ts=100)
        self.assertTrue(t.pronto_per_arrivo("casa", CONFIG))

    def test_critico_fuori_banda_non_pronto(self):
        t = crea_digital_twin()
        t.registra_lettura("casa", "temp", 3000, ts=100)
        self.assertFalse(t.pronto_per_arrivo("casa", CONFIG))

    def test_critico_assente_fail_closed(self):
        t = crea_digital_twin()
        t.registra_lettura("casa", "umidita", 400, ts=100)  # solo umidita', temp manca
        self.assertFalse(t.pronto_per_arrivo("casa", CONFIG))


class TestReport(unittest.TestCase):
    def test_pre_post(self):
        t = crea_digital_twin()
        t.registra_lettura("casa", "energia", 100, ts=1000)
        t.registra_lettura("casa", "energia", 250, ts=5000)
        r = t.report_soggiorno("casa", "energia", 1000, 5000)
        self.assertEqual(r, {"inizio": 100, "fine": 250, "delta": 150})

    def test_intervallo_vuoto(self):
        t = crea_digital_twin()
        self.assertIsNone(t.report_soggiorno("casa", "x", 0, 100))


class TestRobustezza(unittest.TestCase):
    def test_mai_solleva(self):
        t = crea_digital_twin()
        for bad in (None, 123, ""):
            try:
                t.registra_lettura(bad, bad, bad)
                t.stato(bad)
                t.anomalie(bad, {})
                t.predici_guasti(bad, {}, orizzonte_sec=100)
                t.pronto_per_arrivo(bad, {})
            except Exception as e:  # pragma: no cover
                self.fail(f"sollevato su {bad!r}: {e}")


class TestStress(unittest.TestCase):
    def test_letture_concorrenti_10x(self):
        for rip in range(10):
            d = tempfile.mkdtemp()
            try:
                t = crea_digital_twin(os.path.join(d, f"tw{rip}.db"))
                errori = []
                lock = threading.Lock()

                def worker(i):
                    try:
                        for k in range(20):
                            t.registra_lettura("casa", "s%d" % i, k, ts=1000 + k)
                    except Exception as ex:  # pragma: no cover
                        with lock:
                            errori.append(ex)

                th = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
                for x in th:
                    x.start()
                for x in th:
                    x.join()
                self.assertEqual(errori, [])
                self.assertEqual(len(t.stato("casa")), 8)   # 8 sensori distinti
            finally:
                shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
