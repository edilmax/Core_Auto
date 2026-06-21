"""
Test dell'Health-guard / Circuit del funnel (fase53). Diagnosi di salute pura,
macchina a stati del circuito (chiuso/aperto/semiaperto) con cooldown e recovery,
default-off (pura osservabilita'), kill-switch, metriche duck-typed parziali, fuzzing.
"""
import os
import random
import unittest

from fase53_healthguard import (
    PoliticaSalute, Diagnosi, valuta_salute, CircuitoFunnel, crea_circuito_funnel,
    CHIUSO, APERTO, SEMIAPERTO, SANO, DEGRADATO, CRITICO)


# ─────────────────────────────────────────────────────────────────────────────
# Fake MetricheFunnel / MetricheStadio (forma reale fase52)
# ─────────────────────────────────────────────────────────────────────────────
class _MS:
    def __init__(self, eseguiti, falliti): self.eseguiti = eseguiti; self.falliti = falliti


class _Metriche:
    def __init__(self, cicli_totali=100, per_stadio=None,
                 conversioni_tentate=0, conversion_rate=0.0):
        self.cicli_totali = cicli_totali
        self.per_stadio = per_stadio or {}
        self.conversioni_tentate = conversioni_tentate
        self.conversion_rate = conversion_rate


class _Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t
    def avanza(self, dt): self.t += dt


# ─────────────────────────────────────────────────────────────────────────────
class TestValutaSalute(unittest.TestCase):
    def test_campione_insufficiente_sempre_sano(self):
        m = _Metriche(cicli_totali=5, per_stadio={"x": _MS(5, 5)})  # 100% guasti...
        self.assertTrue(valuta_salute(m).sano)                       # ...ma campione < 20

    def test_sano(self):
        m = _Metriche(cicli_totali=100, per_stadio={"esplora": _MS(100, 5)})
        self.assertEqual(valuta_salute(m).stato, SANO)

    def test_critico_failure_rate_stadio(self):
        m = _Metriche(cicli_totali=100, per_stadio={"esplora": _MS(100, 80)})
        d = valuta_salute(m)
        self.assertEqual(d.stato, CRITICO)
        self.assertTrue(any("esplora" in s for s in d.motivi))

    def test_degradato_in_avvicinamento(self):
        # soglia 0.5, degrado a 0.8*0.5=0.4 -> fr=0.45 = degradato
        m = _Metriche(cicli_totali=100, per_stadio={"esplora": _MS(100, 45)})
        self.assertEqual(valuta_salute(m).stato, DEGRADATO)

    def test_critico_conversion_rate(self):
        m = _Metriche(cicli_totali=100, conversioni_tentate=50, conversion_rate=0.02)
        self.assertEqual(valuta_salute(m).stato, CRITICO)

    def test_conversion_rate_ignorato_sotto_campione(self):
        m = _Metriche(cicli_totali=100, conversioni_tentate=3, conversion_rate=0.0)
        self.assertEqual(valuta_salute(m).stato, SANO)

    def test_stadio_senza_esecuzioni_ignorato(self):
        m = _Metriche(cicli_totali=100, per_stadio={"x": _MS(0, 0)})
        self.assertEqual(valuta_salute(m).stato, SANO)


class TestPolitica(unittest.TestCase):
    def test_frazione_fuori_range(self):
        with self.assertRaises(ValueError):
            PoliticaSalute(max_failure_rate_stadio=1.5)
        with self.assertRaises(ValueError):
            PoliticaSalute(min_conversion_rate=-0.1)

    def test_min_campione_negativo(self):
        with self.assertRaises(ValueError):
            PoliticaSalute(min_campione=-1)

    def test_cooldown_negativo(self):
        with self.assertRaises(ValueError):
            PoliticaSalute(cooldown_s=-5)


class TestCircuitoDefaultOff(unittest.TestCase):
    def test_spento_non_mette_mai_in_pausa(self):
        c = crea_circuito_funnel(abilitato=False)
        critica = _Metriche(cicli_totali=100, per_stadio={"x": _MS(100, 100)})
        d = c.osserva(critica)
        self.assertEqual(d.stato, CRITICO)         # la diagnosi resta osservabile
        self.assertEqual(c.stato, CHIUSO)          # ...ma lo stato non si muove
        self.assertTrue(c.consenti())              # mai blocca

    def test_env_assente_default_off(self):
        os.environ.pop("MANGO_HEALTHGUARD", None)
        self.assertFalse(crea_circuito_funnel(abilitato=None).abilitato)

    def test_env_accende(self):
        os.environ["MANGO_HEALTHGUARD"] = "1"
        try:
            self.assertTrue(crea_circuito_funnel(abilitato=None).abilitato)
        finally:
            del os.environ["MANGO_HEALTHGUARD"]


class TestCircuitoStati(unittest.TestCase):
    def setUp(self):
        self.clock = _Clock()
        self.pol = PoliticaSalute(cooldown_s=10)
        self.c = crea_circuito_funnel(self.pol, clock=self.clock, abilitato=True)
        self.sana = _Metriche(cicli_totali=100, per_stadio={"x": _MS(100, 1)})
        self.critica = _Metriche(cicli_totali=100, per_stadio={"x": _MS(100, 100)})

    def test_apre_su_critico(self):
        self.c.osserva(self.critica)
        self.assertEqual(self.c.stato, APERTO)
        self.assertFalse(self.c.consenti())

    def test_resta_aperto_prima_del_cooldown(self):
        self.c.osserva(self.critica)
        self.clock.avanza(5)                       # < cooldown
        self.assertFalse(self.c.consenti())
        self.assertEqual(self.c.stato, APERTO)

    def test_semiaperto_dopo_cooldown(self):
        self.c.osserva(self.critica)
        self.clock.avanza(10)                       # >= cooldown
        self.assertTrue(self.c.consenti())          # prova consentita
        self.assertEqual(self.c.stato, SEMIAPERTO)

    def test_recupero_completo(self):
        self.c.osserva(self.critica)               # APERTO
        self.clock.avanza(10)
        self.c.osserva(self.sana)                  # in SEMIAPERTO + sano -> CHIUSO
        self.assertEqual(self.c.stato, CHIUSO)
        self.assertTrue(self.c.consenti())

    def test_ricade_aperto_se_ancora_critico(self):
        self.c.osserva(self.critica)
        self.clock.avanza(10)
        self.c.osserva(self.critica)               # ancora critico in semiaperto
        self.assertEqual(self.c.stato, APERTO)

    def test_kill_switch(self):
        self.c.forza_apertura()
        self.assertEqual(self.c.stato, APERTO)
        self.assertFalse(self.c.consenti())

    def test_kill_switch_inerte_se_spento(self):
        c = crea_circuito_funnel(abilitato=False)
        c.forza_apertura()
        self.assertEqual(c.stato, CHIUSO)


class TestDuckTyping(unittest.TestCase):
    def test_metriche_parziali_non_crashano(self):
        class Vuoto: pass
        self.assertTrue(valuta_salute(Vuoto()).sano)   # cicli_totali assente -> 0 -> sano

    def test_stadio_attributi_mancanti(self):
        class MSsenza: pass
        m = _Metriche(cicli_totali=100, per_stadio={"x": MSsenza()})
        self.assertEqual(valuta_salute(m).stato, SANO)


class TestFuzzing(unittest.TestCase):
    def test_fuzz_invarianti_macchina_a_stati(self):
        rnd = random.Random(53)
        clock = _Clock()
        c = crea_circuito_funnel(PoliticaSalute(cooldown_s=5), clock=clock,
                                 abilitato=True)
        for _ in range(20000):
            falliti = rnd.randint(0, 100)
            m = _Metriche(cicli_totali=100, per_stadio={"x": _MS(100, falliti)},
                          conversioni_tentate=rnd.choice([0, 50]),
                          conversion_rate=rnd.random())
            c.osserva(m)
            clock.avanza(rnd.choice([0, 1, 3, 10]))
            # invarianti duri:
            self.assertIn(c.stato, (CHIUSO, APERTO, SEMIAPERTO))
            if c.stato == APERTO:
                self.assertFalse(c.consenti() and c.stato == APERTO)  # aperto => non consente
            # consenti() coerente con lo stato corrente
            cons = c.consenti()
            self.assertEqual(cons, c.stato in (CHIUSO, SEMIAPERTO))

    def test_fuzz_spento_mai_blocca(self):
        rnd = random.Random(530)
        c = crea_circuito_funnel(abilitato=False)
        for _ in range(2000):
            m = _Metriche(cicli_totali=100,
                          per_stadio={"x": _MS(100, rnd.randint(0, 100))})
            c.osserva(m)
            self.assertTrue(c.consenti())
            self.assertEqual(c.stato, CHIUSO)


if __name__ == "__main__":
    unittest.main()
