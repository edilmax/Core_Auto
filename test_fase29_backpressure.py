"""
Test FASE 29 - Backpressure & Code di Priorita'.

Copre: ammissione a soglie (load shedding), headroom della priorita' ALTA,
ordine di servizio per priorita', ISOLAMENTO (handler che solleva non ferma il
motore), SOPRAVVIVENZA al picco estremo (coda limitata + 100% critici) e
concorrenza (tutti i task processati).
"""
import random
import threading
import time
import unittest

from fase29_backpressure import MotoreBackpressure, Priorita, EsitoSubmit


class TestAmmissione(unittest.TestCase):

    def test_shedding_a_soglia(self):
        m = MotoreBackpressure(lambda p: None, capacita=10, soglia_bassa=0.7)
        ammessi = sum(m.submit(i, Priorita.BASSA).ammesso for i in range(20))
        self.assertEqual(ammessi, 7)            # 70% di 10
        self.assertEqual(m.in_coda(), 7)
        self.assertEqual(m.stats()["scartati"], 13)

    def test_headroom_priorita_alta(self):
        m = MotoreBackpressure(lambda p: None, capacita=10, soglia_bassa=0.7,
                               soglia_normale=0.9)
        for i in range(7):
            m.submit(i, Priorita.BASSA)         # riempie fino al 70%
        # BASSA ora scartata, ma NORMALE (90%) e ALTA (100%) hanno headroom
        self.assertFalse(m.submit("b", Priorita.BASSA).ammesso)
        self.assertTrue(m.submit("n", Priorita.NORMALE).ammesso)
        self.assertTrue(m.submit("a", Priorita.ALTA).ammesso)

    def test_submit_ritorna_esito(self):
        m = MotoreBackpressure(lambda p: None, capacita=1)
        self.assertIsInstance(m.submit("x", Priorita.ALTA), EsitoSubmit)


class TestServizio(unittest.TestCase):

    def test_ordine_per_priorita(self):
        ordine = []
        m = MotoreBackpressure(lambda p: ordine.append(p), capacita=100, workers=1)
        m.submit("b1", Priorita.BASSA)
        m.submit("a1", Priorita.ALTA)
        m.submit("n1", Priorita.NORMALE)
        m.submit("a2", Priorita.ALTA)
        m.start()
        time.sleep(0.3)
        m.stop()
        self.assertEqual(ordine[:2], ["a1", "a2"])  # ALTA prima
        self.assertEqual(ordine[-1], "b1")          # BASSA per ultima

    def test_isolamento_handler_che_solleva(self):
        buoni = []
        def handler(p):
            if p == "bad":
                raise RuntimeError("kaboom")
            buoni.append(p)
        m = MotoreBackpressure(handler, workers=1)
        m.start()
        for p in ("ok1", "bad", "ok2"):
            m.submit(p, Priorita.NORMALE)
        time.sleep(0.3)
        m.stop()
        self.assertEqual(set(buoni), {"ok1", "ok2"})
        self.assertEqual(m.stats()["falliti"], 1)
        self.assertEqual(m.stats()["processati"], 2)

    def test_concorrenza_tutti_processati(self):
        cont = {"n": 0}
        lk = threading.Lock()
        def inc(_):
            with lk:
                cont["n"] += 1
        m = MotoreBackpressure(inc, capacita=5000, workers=4)
        m.start()
        for i in range(2000):
            m.submit(i, Priorita.NORMALE)
        m.stop(drain=True)
        self.assertEqual(cont["n"], 2000)

    def test_stop_no_drain_scarta_coda(self):
        lento = threading.Event()
        def handler(_):
            lento.wait(0.01)
        m = MotoreBackpressure(handler, capacita=1000, workers=1)
        for i in range(500):
            m.submit(i, Priorita.NORMALE)
        m.start()
        m.stop(drain=False)          # scarta la coda residua
        self.assertLessEqual(m.stats()["processati"], 500)


class TestSopravvivenzaPicco(unittest.TestCase):

    def test_picco_limitato_e_critici_protetti(self):
        m = MotoreBackpressure(lambda p: None, capacita=1000, soglia_bassa=0.7)
        random.seed(1)
        stream = [Priorita.BASSA] * 5000 + [Priorita.ALTA] * 100
        random.shuffle(stream)
        alta_ammessi = 0
        for i, pr in enumerate(stream):
            if m.submit(i, pr).ammesso and pr == Priorita.ALTA:
                alta_ammessi += 1
        self.assertLessEqual(m.stats()["picco"], 1000)   # coda limitata -> sopravvive
        self.assertEqual(alta_ammessi, 100)              # tutti i critici protetti


if __name__ == "__main__":
    unittest.main()
