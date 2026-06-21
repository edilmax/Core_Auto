"""
Test del Bootstrap / composition-root (fase55). Assemblaggio validato-con-report
dello stack Mango: config validata, default-off, fail-closed su incoerenza attiva,
degrado con avvisi, report di composizione, E2E sistema completo.
"""
import os
import unittest

from fase55_bootstrap import (
    ConfigMango, SistemaMango, ReportComposizione, BootstrapError, costruisci)


# ─────────────────────────────────────────────────────────────────────────────
# Stub dei 4 stadi (duck-typed, firme reali fase46/47/48/49)
# ─────────────────────────────────────────────────────────────────────────────
class _EsitoConv:
    def __init__(self, ok=True): self.ok = ok


class StubEsploratore:
    def esplora(self, fonti): return [("prop", len(fonti or []))]


class StubVenditore:
    def pianifica(self, leads, stato, giorno, capacita): return [("out", len(leads or []))]


class StubAdvertising:
    def pianifica(self, budget, campagne): return [("alloc", budget)]


class StubPonte:
    def __init__(self): self.chiamate = 0
    def aggancia(self, conv): self.chiamate += 1; return _EsitoConv(True)


def _orologio():
    stato = {"t": 0.0}
    def clock(): return stato["t"]
    def sleep(dt): stato["t"] += max(0.0, dt)
    return clock, sleep, stato


# ─────────────────────────────────────────────────────────────────────────────
class TestConfig(unittest.TestCase):
    def test_db_path_vuoto(self):
        with self.assertRaises(ValueError):
            ConfigMango(db_path="")

    def test_intervallo_negativo(self):
        with self.assertRaises(ValueError):
            ConfigMango(intervallo_s=-1)

    def test_costo_bool_rifiutato(self):
        with self.assertRaises(ValueError):
            ConfigMango(costo_token_ciclo=True)

    def test_cooldown_negativo(self):
        with self.assertRaises(ValueError):
            ConfigMango(cooldown_s=-5)

    def test_hg_attivo_default_uguale_master(self):
        self.assertTrue(ConfigMango(abilitato=True).hg_attivo)
        self.assertFalse(ConfigMango(abilitato=False).hg_attivo)

    def test_hg_override(self):
        self.assertFalse(ConfigMango(abilitato=True, abilitato_healthguard=False).hg_attivo)

    def test_da_env(self):
        os.environ["MANGO_ATTIVO"] = "1"
        try:
            self.assertTrue(ConfigMango.da_env().abilitato)
        finally:
            del os.environ["MANGO_ATTIVO"]
        os.environ.pop("MANGO_ATTIVO", None)
        self.assertFalse(ConfigMango.da_env().abilitato)


class TestAssemblaggio(unittest.TestCase):
    def test_costruisce_sistema_completo(self):
        s = costruisci(ConfigMango(abilitato=True),
                       esploratore=StubEsploratore(), venditore=StubVenditore(),
                       advertising=StubAdvertising(), ponte=StubPonte())
        self.assertIsInstance(s, SistemaMango)
        for comp in (s.store, s.orchestratore, s.scheduler, s.circuito, s.loop):
            self.assertIsNotNone(comp)

    def test_config_non_valida(self):
        with self.assertRaises(BootstrapError):
            costruisci({"abilitato": True})            # non e' una ConfigMango

    def test_report_attivi(self):
        s = costruisci(ConfigMango(abilitato=True),
                       esploratore=StubEsploratore(), ponte=StubPonte())
        a = s.report.attivi
        self.assertTrue(a["esploratore"])
        self.assertTrue(a["ponte"])
        self.assertFalse(a["venditore"])
        self.assertFalse(a["advertising"])
        self.assertTrue(a["loop"])


class TestFailClosed(unittest.TestCase):
    def test_attivo_senza_stadi_blocca(self):
        with self.assertRaises(BootstrapError):
            costruisci(ConfigMango(abilitato=True))    # acceso ma zero stadi

    def test_spento_senza_stadi_ok(self):
        # spento -> degrada, NON solleva (non e' incoerenza attiva)
        s = costruisci(ConfigMango(abilitato=False))
        self.assertFalse(s.report.attivi["loop"])


class TestAvvisi(unittest.TestCase):
    def test_avviso_default_off(self):
        s = costruisci(ConfigMango(abilitato=False))
        self.assertTrue(any("DEFAULT-OFF" in a for a in s.report.avvisi))

    def test_avviso_governatore_assente(self):
        s = costruisci(ConfigMango(abilitato=True), ponte=StubPonte())
        self.assertTrue(any("governatore" in a for a in s.report.avvisi))

    def test_avviso_money_path_off(self):
        s = costruisci(ConfigMango(abilitato=True), esploratore=StubEsploratore())
        self.assertTrue(any("money-path OFF" in a for a in s.report.avvisi))

    def test_avviso_healthguard_spento(self):
        s = costruisci(ConfigMango(abilitato=True, abilitato_healthguard=False),
                       ponte=StubPonte())
        self.assertTrue(any("health-guard spento" in a for a in s.report.avvisi))


class TestDefaultOff(unittest.TestCase):
    def test_avvia_spento_inerte(self):
        s = costruisci(ConfigMango(abilitato=False))
        ponte = StubPonte()
        r = s.avvia(max_tick=5)
        self.assertFalse(r.abilitato)
        self.assertEqual(ponte.chiamate, 0)
        self.assertEqual(s.metriche().cicli_totali, 0)


class TestE2E(unittest.TestCase):
    def test_sistema_completo_gira_e_prenota(self):
        clock, sleep, _ = _orologio()
        ponte = StubPonte()
        s = costruisci(
            ConfigMango(abilitato=True, intervallo_s=0, db_path=":memory:"),
            esploratore=StubEsploratore(), venditore=StubVenditore(),
            advertising=StubAdvertising(), ponte=ponte,
            sorgente=lambda: [{"fonti": ["f"], "leads": ["l"], "giorno": 1,
                               "capacita": 5, "budget_cents": 1000, "campagne": ["c"],
                               "conversione": {"id": 1}}],
            clock=clock, sleep=sleep)
        r = s.avvia(max_tick=3)
        self.assertTrue(r.abilitato)
        self.assertEqual(r.tick_eseguiti, 3)
        self.assertEqual(ponte.chiamate, 3)            # money-path raggiunto
        m = s.metriche()
        self.assertEqual(m.cicli_totali, 3)
        self.assertEqual(m.conversioni_riuscite, 3)

    def test_satellite_senza_ponte_osserva_non_prenota(self):
        clock, sleep, _ = _orologio()
        s = costruisci(
            ConfigMango(abilitato=True, intervallo_s=0),
            esploratore=StubEsploratore(),
            sorgente=lambda: [{"fonti": ["f1", "f2"]}],
            clock=clock, sleep=sleep)
        r = s.avvia(max_tick=2)
        self.assertEqual(r.tick_eseguiti, 2)
        m = s.metriche()
        self.assertEqual(m.cicli_totali, 2)
        self.assertEqual(m.conversioni_tentate, 0)     # nessuna prenotazione


if __name__ == "__main__":
    unittest.main()
