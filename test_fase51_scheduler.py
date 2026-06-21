"""
Test dello Scheduler/Runner Mango (fase51). Esecuzione ricorrente dell'orchestratore:
default-off, gate quota (differisci-e-continua), isolamento per-ciclo, persistenza
degli esiti, max_cicli, input corrotti, fuzzing.
"""
import os
import random
import unittest

from fase51_scheduler import (
    SchedulerMango, SchedulerError, EsitoEsecuzione, StoreCicliMemoria,
    crea_scheduler)


# ─────────────────────────────────────────────────────────────────────────────
# Stub orchestratore + governatore (duck-typed, firme reali fase50/fase32)
# ─────────────────────────────────────────────────────────────────────────────
class StubOrchestratore:
    def __init__(self): self.cicli = 0; self.kwargs = []
    def esegui_ciclo(self, **kw):
        self.cicli += 1
        self.kwargs.append(kw)
        return ("report", self.cicli)


class OrchInFiamme:
    def esegui_ciclo(self, **kw): raise RuntimeError("ciclo esploso")


class _EsitoGov:
    def __init__(self, concesso): self.concesso = concesso


class StubGovernatore:
    """Quota a finestra: concede `per_finestra` ogni `finestra` richieste."""
    def __init__(self, per_finestra=3, finestra=10):
        self.pf, self.f = per_finestra, finestra
        self.richieste = 0
        self.token_chiesti = []
    def acquisisci(self, token, priorita=None):
        pos = self.richieste % self.f
        self.richieste += 1
        self.token_chiesti.append(token)
        return _EsitoGov(pos < self.pf)


def _lavori(n):
    return [{"conversione": {"id": i}} for i in range(n)]


# ─────────────────────────────────────────────────────────────────────────────
class TestEsecuzioneBase(unittest.TestCase):
    def setUp(self):
        self.orch = StubOrchestratore()
        self.s = crea_scheduler(self.orch, abilitato=True)

    def test_esegue_tutti_i_lavori(self):
        e = self.s.esegui(_lavori(5))
        self.assertTrue(e.abilitato)
        self.assertEqual(e.cicli_eseguiti, 5)
        self.assertEqual(self.orch.cicli, 5)
        self.assertEqual(self.s.store.conteggio(), 5)

    def test_kwargs_passati_all_orchestratore(self):
        self.s.esegui([{"fonti": ["f"], "budget_cents": 10}])
        self.assertEqual(self.orch.kwargs[0], {"fonti": ["f"], "budget_cents": 10})

    def test_max_cicli_limita(self):
        e = self.s.esegui(_lavori(100), max_cicli=7)
        self.assertEqual(e.cicli_eseguiti, 7)
        self.assertEqual(self.orch.cicli, 7)

    def test_lista_vuota(self):
        e = self.s.esegui([])
        self.assertEqual(e.cicli_totali, 0)
        self.assertTrue(e.abilitato)


class TestDefaultOff(unittest.TestCase):
    def test_spento_non_esegue_nulla(self):
        orch = StubOrchestratore()
        s = crea_scheduler(orch, abilitato=False)
        e = s.esegui(_lavori(10))
        self.assertFalse(e.abilitato)
        self.assertEqual(e.cicli_eseguiti, 0)
        self.assertEqual(orch.cicli, 0)
        self.assertEqual(s.store.conteggio(), 0)

    def test_env_accende(self):
        os.environ["MANGO_SCHEDULER"] = "1"
        try:
            s = crea_scheduler(StubOrchestratore(), abilitato=None)
            self.assertTrue(s.abilitato)
            self.assertEqual(s.esegui(_lavori(2)).cicli_eseguiti, 2)
        finally:
            del os.environ["MANGO_SCHEDULER"]

    def test_env_assente_default_off(self):
        os.environ.pop("MANGO_SCHEDULER", None)
        self.assertFalse(crea_scheduler(StubOrchestratore(), abilitato=None).abilitato)


class TestQuota(unittest.TestCase):
    def test_differisci_e_continua_non_sfora(self):
        orch = StubOrchestratore()
        gov = StubGovernatore(per_finestra=3, finestra=10)
        s = crea_scheduler(orch, governatore=gov, abilitato=True)
        e = s.esegui(_lavori(100))
        # 100 lavori, 3 concessi ogni 10 -> 30 eseguiti, 70 differiti, 0 sforati
        self.assertEqual(e.cicli_eseguiti, 30)
        self.assertEqual(e.cicli_differiti, 70)
        self.assertEqual(orch.cicli, 30)            # l'orchestratore NON gira sui differiti
        self.assertEqual(s.store.conteggio(), 30)

    def test_costo_token_passato_al_governatore(self):
        gov = StubGovernatore(per_finestra=10, finestra=10)
        s = crea_scheduler(StubOrchestratore(), governatore=gov,
                           costo_token_ciclo=1234, abilitato=True)
        s.esegui(_lavori(3))
        self.assertEqual(gov.token_chiesti, [1234, 1234, 1234])

    def test_senza_governatore_nessun_tetto(self):
        orch = StubOrchestratore()
        s = crea_scheduler(orch, abilitato=True)
        self.assertEqual(s.esegui(_lavori(50)).cicli_eseguiti, 50)


class TestIsolamento(unittest.TestCase):
    def test_ciclo_in_fiamme_isolato(self):
        s = crea_scheduler(OrchInFiamme(), abilitato=True)
        e = s.esegui(_lavori(5))
        self.assertEqual(e.cicli_eseguiti, 0)
        self.assertEqual(e.cicli_errore, 5)         # tutti isolati, run non crasha
        self.assertEqual(s.store.conteggio(), 0)    # nessun report fasullo persistito

    def test_errore_non_ferma_il_run(self):
        # orchestratore che esplode solo a volte
        class Intermittente:
            def __init__(self): self.n = 0
            def esegui_ciclo(self, **kw):
                self.n += 1
                if self.n % 2 == 0: raise RuntimeError("boom")
                return ("ok", self.n)
        s = crea_scheduler(Intermittente(), abilitato=True)
        e = s.esegui(_lavori(10))
        self.assertEqual(e.cicli_eseguiti, 5)
        self.assertEqual(e.cicli_errore, 5)
        self.assertEqual(e.cicli_totali, 10)


class TestInputCorrotti(unittest.TestCase):
    def test_orchestratore_none(self):
        with self.assertRaises(SchedulerError):
            SchedulerMango(None, abilitato=True)

    def test_costo_negativo(self):
        with self.assertRaises(ValueError):
            crea_scheduler(StubOrchestratore(), costo_token_ciclo=-1, abilitato=True)

    def test_costo_bool_rifiutato(self):
        with self.assertRaises(ValueError):
            crea_scheduler(StubOrchestratore(), costo_token_ciclo=True, abilitato=True)

    def test_max_cicli_negativo(self):
        s = crea_scheduler(StubOrchestratore(), abilitato=True)
        with self.assertRaises(ValueError):
            s.esegui(_lavori(3), max_cicli=-1)

    def test_lavoro_none_tollerato(self):
        orch = StubOrchestratore()
        s = crea_scheduler(orch, abilitato=True)
        e = s.esegui([None, None])                  # None -> kwargs vuoti
        self.assertEqual(e.cicli_eseguiti, 2)


class TestStorePersonalizzato(unittest.TestCase):
    def test_store_iniettato_usato(self):
        store = StoreCicliMemoria()
        s = crea_scheduler(StubOrchestratore(), store=store, abilitato=True)
        s.esegui(_lavori(4))
        self.assertEqual(store.conteggio(), 4)
        self.assertEqual(len(store.tutti()), 4)


class TestFuzzing(unittest.TestCase):
    def test_fuzz_invarianti_quota_e_conteggi(self):
        rnd = random.Random(51)
        for _ in range(3000):
            n = rnd.randint(0, 60)
            pf = rnd.randint(1, 10)
            fin = rnd.randint(pf, 15)
            orch = StubOrchestratore()
            gov = StubGovernatore(per_finestra=pf, finestra=fin)
            s = crea_scheduler(orch, governatore=gov, abilitato=True)
            mx = rnd.choice([None, rnd.randint(0, n)])
            e = s.esegui(_lavori(n), max_cicli=mx)
            considerati = n if mx is None else min(n, mx)
            # invariante: eseguiti + differiti == lavori considerati (zero errori qui)
            self.assertEqual(e.cicli_eseguiti + e.cicli_differiti, considerati)
            self.assertEqual(e.cicli_errore, 0)
            self.assertEqual(orch.cicli, e.cicli_eseguiti)   # orch gira solo sui concessi
            self.assertEqual(s.store.conteggio(), e.cicli_eseguiti)
            self.assertLessEqual(e.cicli_eseguiti, considerati)


if __name__ == "__main__":
    unittest.main()
