"""Test Fase 94 - Scheduler campagna. Clock e store iniettati: deterministico, no rete, no attese."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from fase94_scheduler_campagna import (SchedulerCampagna, StatoFile, StatoMemoria,
                                       crea_scheduler_campagna)


class MotoreFinto:
    """Conta le campagne eseguite; opzionalmente esplode (per il test d'isolamento)."""
    def __init__(self, esplodi=False):
        self.chiamate = 0
        self._boom = esplodi

    def esegui_campagna(self, lingue):
        self.chiamate += 1
        if self._boom:
            raise RuntimeError("motore giu")
        return {"post_generati": 3, "pubblicati": 0, "saltati": 3,
                "lingue": list(lingue)}


def clock_fisso(dt):
    return lambda: dt


class TestSchedulerCampagna(unittest.TestCase):
    def test_prima_volta_gira(self):
        m = MotoreFinto()
        s = SchedulerCampagna(m, StatoMemoria(), clock=clock_fisso(
            datetime(2026, 1, 1, tzinfo=timezone.utc)))
        rep = s.tick(["it"])
        self.assertTrue(rep["eseguito"])
        self.assertEqual(m.chiamate, 1)

    def test_no_burst_stesso_giorno(self):
        m = MotoreFinto()
        ora = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
        store = StatoMemoria()
        s = SchedulerCampagna(m, store, cadenza_giorni=1, clock=lambda: ora)
        self.assertTrue(s.tick(["it"])["eseguito"])
        # secondo tick poco dopo: NON deve ripubblicare
        rep2 = s.tick(["it"])
        self.assertFalse(rep2["eseguito"])
        self.assertEqual(m.chiamate, 1)

    def test_gira_dopo_la_cadenza(self):
        m = MotoreFinto()
        store = StatoMemoria()
        t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        s = SchedulerCampagna(m, store, cadenza_giorni=1, clock=lambda: t0)
        s.tick(["it"])
        # avanza il clock di +1 giorno
        s._clock = clock_fisso(t0 + timedelta(days=1))
        self.assertTrue(s.tick(["it"])["eseguito"])
        self.assertEqual(m.chiamate, 2)

    def test_cadenza_piu_giorni(self):
        m = MotoreFinto()
        t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        s = SchedulerCampagna(m, StatoMemoria(), cadenza_giorni=7, clock=lambda: t0)
        s.tick()
        s._clock = clock_fisso(t0 + timedelta(days=3))
        self.assertFalse(s.tick()["eseguito"])          # 3 < 7
        s._clock = clock_fisso(t0 + timedelta(days=7))
        self.assertTrue(s.tick()["eseguito"])           # 7 >= 7

    def test_errore_motore_non_consuma_finestra(self):
        m = MotoreFinto(esplodi=True)
        store = StatoMemoria()
        s = SchedulerCampagna(m, store, clock=clock_fisso(
            datetime(2026, 1, 1, tzinfo=timezone.utc)))
        rep = s.tick()
        self.assertFalse(rep["eseguito"])
        self.assertTrue(rep.get("errore"))
        self.assertIsNone(store.leggi())                # finestra NON consumata -> riprova

    def test_stato_corrotto_rigira(self):
        m = MotoreFinto()
        store = StatoMemoria("non-una-data")
        s = SchedulerCampagna(m, store, clock=clock_fisso(
            datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertTrue(s.tick()["eseguito"])

    def test_lingue_default(self):
        m = MotoreFinto()
        s = SchedulerCampagna(m, StatoMemoria(), clock=clock_fisso(
            datetime(2026, 1, 1, tzinfo=timezone.utc)))
        rep = s.tick()
        self.assertGreaterEqual(len(rep["lingue"]), 1)

    def test_stato_file_durevole_atomico(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "stato.json")
        st = StatoFile(p)
        self.assertIsNone(st.leggi())
        st.scrivi("2026-01-01T00:00:00+00:00")
        self.assertEqual(StatoFile(p).leggi(), "2026-01-01T00:00:00+00:00")  # ricaricato
        os.remove(p)
        os.rmdir(d)

    def test_persistenza_sopravvive_riavvio(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "s.json")
        t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        m = MotoreFinto()
        crea_scheduler_campagna(m, percorso=p, clock=lambda: t0).tick()
        # "riavvio": nuovo scheduler stesso file, stesso giorno -> NON ripubblica
        m2 = MotoreFinto()
        rep = crea_scheduler_campagna(m2, percorso=p, clock=lambda: t0).tick()
        self.assertFalse(rep["eseguito"])
        self.assertEqual(m2.chiamate, 0)
        os.remove(p)
        os.rmdir(d)

    def test_factory_memoria(self):
        m = MotoreFinto()
        s = crea_scheduler_campagna(m, ultimo=None, clock=clock_fisso(
            datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertTrue(s.tick()["eseguito"])


if __name__ == "__main__":
    unittest.main()
