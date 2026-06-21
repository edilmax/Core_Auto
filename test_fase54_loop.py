"""
Test del Loop/Daemon runner (fase54). Cadenza fixed-rate no-burst, gate via circuito
(fase53), ri-alimentazione metriche, tick isolato, default-off, shutdown, max_tick,
integrazione E2E pausa+recupero, input corrotti.
"""
import os
import unittest

from fase54_loop import LoopMango, LoopError, ReportLoop, EsitoTick, crea_loop
from fase53_healthguard import CircuitoFunnel, PoliticaSalute, APERTO, CHIUSO


# ─────────────────────────────────────────────────────────────────────────────
# Strumenti deterministici: clock virtuale + scheduler stub
# ─────────────────────────────────────────────────────────────────────────────
class Orologio:
    def __init__(self): self.t = 0.0; self.sleeps = []
    def __call__(self): return self.t
    def sleep(self, dt): self.sleeps.append(dt); self.t += max(0.0, dt)
    def avanza(self, dt): self.t += dt


class _MS:
    def __init__(self, eseguiti, falliti): self.eseguiti = eseguiti; self.falliti = falliti


class _Metriche:
    def __init__(self, falliti):
        self.cicli_totali = 100
        self.per_stadio = {"x": _MS(100, falliti)}
        self.conversioni_tentate = 0
        self.conversion_rate = 1.0


class _Store:
    def __init__(self, holder): self._holder = holder
    def metriche(self): return self._holder["m"]


class StubScheduler:
    """Registra gli avvii (clock) e consuma `durata` tempo virtuale per esecuzione."""
    def __init__(self, *, clock=None, durata=0.0, holder=None, esplode=False):
        self.clock = clock; self.durata = durata; self.esplode = esplode
        self.avvii = []; self.lavori_visti = []
        self.store = _Store(holder) if holder is not None else None
    def esegui(self, lavori):
        if self.clock is not None: self.avvii.append(self.clock())
        self.lavori_visti.append(lavori)
        if self.esplode: raise RuntimeError("scheduler in fiamme")
        if self.clock is not None: self.clock.t += self.durata
        return ("esito", len(lavori))


def _sorgente(n=1):
    return lambda: [{"id": i} for i in range(n)]


# ─────────────────────────────────────────────────────────────────────────────
class TestBase(unittest.TestCase):
    def test_tick_eseguito(self):
        sch = StubScheduler()
        loop = crea_loop(sch, _sorgente(3), abilitato=True, intervallo_s=0)
        r = loop.esegui(max_tick=1)
        self.assertTrue(r.abilitato)
        self.assertEqual(r.tick_eseguiti, 1)
        self.assertEqual(sch.lavori_visti, [[{"id": 0}, {"id": 1}, {"id": 2}]])

    def test_max_tick_limita(self):
        sch = StubScheduler()
        loop = crea_loop(sch, _sorgente(), abilitato=True, intervallo_s=0)
        r = loop.esegui(max_tick=5)
        self.assertEqual(len(r.tick), 5)
        self.assertEqual(r.tick_eseguiti, 5)

    def test_sorgente_none_tollerata(self):
        sch = StubScheduler()
        loop = crea_loop(sch, lambda: None, abilitato=True, intervallo_s=0)
        loop.esegui(max_tick=1)
        self.assertEqual(sch.lavori_visti, [[]])


class TestDefaultOff(unittest.TestCase):
    def test_spento_non_gira(self):
        sch = StubScheduler()
        loop = crea_loop(sch, _sorgente(), abilitato=False)
        r = loop.esegui(max_tick=3)
        self.assertFalse(r.abilitato)
        self.assertEqual(len(r.tick), 0)
        self.assertEqual(sch.lavori_visti, [])

    def test_env_accende(self):
        os.environ["MANGO_LOOP"] = "1"
        try:
            loop = crea_loop(StubScheduler(), _sorgente(), abilitato=None, intervallo_s=0)
            self.assertTrue(loop.abilitato)
            self.assertEqual(loop.esegui(max_tick=1).tick_eseguiti, 1)
        finally:
            del os.environ["MANGO_LOOP"]

    def test_env_assente_default_off(self):
        os.environ.pop("MANGO_LOOP", None)
        self.assertFalse(crea_loop(StubScheduler(), _sorgente(), abilitato=None).abilitato)


class TestGate(unittest.TestCase):
    def test_circuito_aperto_mette_in_pausa(self):
        class CircAperto:
            def consenti(self): return False
        sch = StubScheduler()
        loop = crea_loop(sch, _sorgente(), circuito=CircAperto(),
                         abilitato=True, intervallo_s=0)
        r = loop.esegui(max_tick=3)
        self.assertEqual(r.tick_in_pausa, 3)
        self.assertEqual(r.tick_eseguiti, 0)
        self.assertEqual(sch.lavori_visti, [])     # scheduler MAI chiamato in pausa


class TestIsolamento(unittest.TestCase):
    def test_tick_in_fiamme_non_abbatte_il_loop(self):
        sch = StubScheduler(esplode=True)
        loop = crea_loop(sch, _sorgente(), abilitato=True, intervallo_s=0)
        r = loop.esegui(max_tick=4)
        self.assertEqual(r.tick_errore, 4)
        self.assertEqual(r.tick_eseguiti, 0)       # nessun crash, loop completa

    def test_sorgente_in_fiamme_isolata(self):
        def boom(): raise RuntimeError("sorgente rotta")
        loop = crea_loop(StubScheduler(), boom, abilitato=True, intervallo_s=0)
        r = loop.esegui(max_tick=2)
        self.assertEqual(r.tick_errore, 2)


class TestShutdown(unittest.TestCase):
    def test_stop_ferma_il_loop(self):
        sch = StubScheduler()
        holder = {"loop": None}
        chiamate = {"n": 0}
        def sorg():
            chiamate["n"] += 1
            if chiamate["n"] >= 2:
                holder["loop"].stop()               # ferma SE STESSO dopo 2 giri
            return [{"id": 1}]
        loop = crea_loop(sch, sorg, abilitato=True, intervallo_s=0)
        holder["loop"] = loop
        r = loop.esegui()                           # nessun max_tick: si ferma solo via stop()
        self.assertGreaterEqual(r.tick_eseguiti, 1)
        self.assertLessEqual(len(r.tick), 2)


class TestTimingNoBurst(unittest.TestCase):
    def test_cadenza_costante_su_tick_veloci(self):
        clk = Orologio()
        sch = StubScheduler(clock=clk, durata=2.0)  # ogni tick consuma 2
        loop = crea_loop(sch, _sorgente(), abilitato=True, intervallo_s=10.0,
                         clock=clk, sleep=clk.sleep)
        loop.esegui(max_tick=5)
        # avvii a 0,10,20,30,40 -> gap costante = intervallo (no deriva da fixed-delay)
        gaps = [sch.avvii[i + 1] - sch.avvii[i] for i in range(len(sch.avvii) - 1)]
        self.assertTrue(all(abs(g - 10.0) < 1e-9 for g in gaps), gaps)

    def test_tick_lento_non_genera_raffica(self):
        clk = Orologio()
        # primo tick lento (15 > intervallo), poi veloci (2)
        durate = iter([15.0, 2.0, 2.0, 2.0])
        sch = StubScheduler(clock=clk)
        sch.esegui = _esegui_variabile(clk, durate, sch)
        loop = crea_loop(sch, _sorgente(), abilitato=True, intervallo_s=10.0,
                         clock=clk, sleep=clk.sleep)
        loop.esegui(max_tick=4)
        # nessuno sleep deve "comprimere" sotto 0; e dopo il tick lento si riparte a
        # ritmo, senza una sequenza di sleep=0 (raffiche)
        zeri_consecutivi = _max_run(sch_sleeps(clk), 0.0)
        self.assertLessEqual(zeri_consecutivi, 1)


class TestRecuperoE2E(unittest.TestCase):
    def test_pausa_e_recupero_autonomi(self):
        clk = Orologio()
        holder = {"m": _Metriche(falliti=90)}        # parte MALATO (90% guasti)
        sch = StubScheduler(clock=clk, durata=0.0, holder=holder)
        circ = CircuitoFunnel(PoliticaSalute(cooldown_s=10), clock=clk, abilitato=True)
        loop = crea_loop(sch, _sorgente(), circuito=circ, abilitato=True,
                         intervallo_s=0, clock=clk, sleep=clk.sleep)

        # tick 1: gira, osserva metriche critiche -> circuito APERTO
        loop.esegui(max_tick=1)
        self.assertEqual(circ.stato, APERTO)

        # guarisce la sorgente dati
        holder["m"] = _Metriche(falliti=1)           # 1% guasti = sano
        # tick 2 SUBITO: ancora in cooldown -> in pausa, scheduler non gira
        chiamate_prima = len(sch.lavori_visti)
        loop.esegui(max_tick=1)
        self.assertEqual(len(sch.lavori_visti), chiamate_prima)   # saltato
        # passa il cooldown -> semiaperto -> tick gira -> osserva sano -> CHIUSO
        clk.avanza(10)
        loop.esegui(max_tick=1)
        self.assertEqual(circ.stato, CHIUSO)


class TestInputCorrotti(unittest.TestCase):
    def test_scheduler_none(self):
        with self.assertRaises(LoopError):
            LoopMango(None, _sorgente(), abilitato=True)

    def test_sorgente_non_callable(self):
        with self.assertRaises(LoopError):
            LoopMango(StubScheduler(), [1, 2, 3], abilitato=True)

    def test_intervallo_negativo(self):
        with self.assertRaises(LoopError):
            crea_loop(StubScheduler(), _sorgente(), intervallo_s=-1, abilitato=True)

    def test_max_tick_negativo(self):
        loop = crea_loop(StubScheduler(), _sorgente(), abilitato=True, intervallo_s=0)
        with self.assertRaises(LoopError):
            loop.esegui(max_tick=-1)


# --- helper per il test del tick lento ---
def _esegui_variabile(clk, durate, sch):
    def esegui(lavori):
        sch.avvii.append(clk()); sch.lavori_visti.append(lavori)
        clk.t += next(durate)
        return ("esito", len(lavori))
    return esegui


def sch_sleeps(clk):
    return clk.sleeps


def _max_run(seq, valore):
    best = run = 0
    for x in seq:
        if x == valore:
            run += 1; best = max(best, run)
        else:
            run = 0
    return best


if __name__ == "__main__":
    unittest.main()
