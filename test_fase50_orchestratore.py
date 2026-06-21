"""
Test dell'Orchestratore Mango (fase50, capstone). Funnel end-to-end: default-off,
stadi opzionali, isolamento dei guasti (un motore in fiamme non abbatte il ciclo ne'
contamina lo stadio-denaro), unico touchpoint col denaro via Ponte, osservabilita',
fuzzing.
"""
import os
import random
import unittest

from fase50_orchestratore import (
    OrchestratoreMango, OrchestratoreError, ReportCiclo, EsitoStadio,
    crea_orchestratore)


# ─────────────────────────────────────────────────────────────────────────────
# Stub dei 7 mattoni (duck-typed, stessa firma dei motori reali)
# ─────────────────────────────────────────────────────────────────────────────
class StubEsploratore:
    def __init__(self): self.chiamate = 0
    def esplora(self, fonti): self.chiamate += 1; return [("prop", len(fonti))]


class StubVenditore:
    def __init__(self): self.args = None
    def pianifica(self, leads, stato_per_lead, giorno, capacita):
        self.args = (leads, stato_per_lead, giorno, capacita)
        return [("outreach", len(leads))]


class StubAdvertising:
    def __init__(self): self.args = None
    def pianifica(self, budget_cents, campagne):
        self.args = (budget_cents, campagne)
        return [("alloc", budget_cents)]


class StubPonte:
    def __init__(self): self.chiamate = 0
    def aggancia(self, conversione):
        self.chiamate += 1
        return ("agganciata", conversione)


class MotoreInFiamme:
    def __getattr__(self, _):
        def _boom(*a, **k): raise RuntimeError("motore in fiamme")
        return _boom


def _orch(abilitato=True, **kw):
    base = dict(esploratore=StubEsploratore(), venditore=StubVenditore(),
                advertising=StubAdvertising(), ponte=StubPonte())
    base.update(kw)
    return crea_orchestratore(abilitato=abilitato, **base)


# ─────────────────────────────────────────────────────────────────────────────
class TestPipelineFelice(unittest.TestCase):
    def test_tutti_gli_stadi(self):
        o = _orch()
        r = o.esegui_ciclo(fonti=["f1", "f2"], leads=["l1"], giorno=1, capacita=5,
                           budget_cents=10000, campagne=["c1"], conversione={"k": "v"})
        self.assertTrue(r.ok_totale)
        self.assertEqual([s.nome for s in r.stadi],
                         ["esplora", "outreach", "advertising", "conversione"])
        self.assertEqual(r.conversione, ("agganciata", {"k": "v"}))

    def test_passaggio_argomenti_corretto(self):
        ven = StubVenditore(); adv = StubAdvertising()
        o = _orch(venditore=ven, advertising=adv)
        o.esegui_ciclo(leads=["a", "b"], stato_per_lead={"a": 1}, giorno=3, capacita=7,
                       budget_cents=500, campagne=["x"])
        self.assertEqual(ven.args, (["a", "b"], {"a": 1}, 3, 7))
        self.assertEqual(adv.args, (500, ["x"]))

    def test_stadi_opzionali_solo_input_presente(self):
        o = _orch()
        r = o.esegui_ciclo(conversione={"solo": "denaro"})   # solo il ponte
        self.assertEqual([s.nome for s in r.stadi], ["conversione"])
        self.assertTrue(r.ok_totale)

    def test_motore_assente_salta_stadio(self):
        o = crea_orchestratore(ponte=StubPonte(), abilitato=True)  # solo ponte montato
        r = o.esegui_ciclo(fonti=["f"], leads=["l"], conversione={"k": 1})
        self.assertEqual([s.nome for s in r.stadi], ["conversione"])


class TestDefaultOff(unittest.TestCase):
    def test_spento_non_tocca_nessun_motore(self):
        esp, pon = StubEsploratore(), StubPonte()
        o = crea_orchestratore(esploratore=esp, ponte=pon, abilitato=False)
        r = o.esegui_ciclo(fonti=["f"], conversione={"k": 1})
        self.assertFalse(r.abilitato)
        self.assertFalse(r.ok_totale)
        self.assertEqual(r.stadi, ())
        self.assertEqual(esp.chiamate, 0)
        self.assertEqual(pon.chiamate, 0)        # denaro MAI toccato da spento

    def test_env_accende(self):
        os.environ["MANGO_ORCHESTRATORE"] = "1"
        try:
            o = _orch(abilitato=None)
            self.assertTrue(o.abilitato)
            self.assertTrue(o.esegui_ciclo(conversione={"k": 1}).ok_totale)
        finally:
            del os.environ["MANGO_ORCHESTRATORE"]

    def test_env_assente_default_off(self):
        os.environ.pop("MANGO_ORCHESTRATORE", None)
        self.assertFalse(_orch(abilitato=None).abilitato)


class TestIsolamento(unittest.TestCase):
    def test_un_motore_in_fiamme_non_abbatte_il_ciclo(self):
        o = _orch(esploratore=MotoreInFiamme())
        r = o.esegui_ciclo(fonti=["f"], leads=["l"], giorno=1, capacita=1,
                           budget_cents=100, campagne=["c"], conversione={"k": 1})
        self.assertFalse(r.ok_totale)                    # c'e' un guasto
        self.assertFalse(r.stadio("esplora").ok)         # isolato
        self.assertIn("motore in fiamme", r.stadio("esplora").errore)
        # gli altri stadi proseguono comunque
        self.assertTrue(r.stadio("outreach").ok)
        self.assertTrue(r.stadio("advertising").ok)
        self.assertTrue(r.stadio("conversione").ok)      # denaro NON perso

    def test_ponte_in_fiamme_isolato(self):
        o = _orch(ponte=MotoreInFiamme())
        r = o.esegui_ciclo(conversione={"k": 1})
        self.assertFalse(r.stadio("conversione").ok)
        self.assertEqual(len(r.errori), 1)

    def test_errori_elenca_solo_i_falliti(self):
        o = _orch(esploratore=MotoreInFiamme(), advertising=MotoreInFiamme())
        r = o.esegui_ciclo(fonti=["f"], budget_cents=1, campagne=["c"],
                           conversione={"k": 1})
        self.assertEqual({s.nome for s in r.errori}, {"esplora", "advertising"})


class TestReport(unittest.TestCase):
    def test_stadio_inesistente_none(self):
        r = _orch().esegui_ciclo(conversione={"k": 1})
        self.assertIsNone(r.stadio("esplora"))

    def test_conversione_none_se_assente(self):
        r = _orch().esegui_ciclo(fonti=["f"])
        self.assertIsNone(r.conversione)

    def test_ciclo_vuoto_e_ok(self):
        r = _orch().esegui_ciclo()                       # abilitato ma nessun input
        self.assertTrue(r.abilitato)
        self.assertEqual(r.stadi, ())
        self.assertTrue(r.ok_totale)                     # all([]) == True


class TestFuzzing(unittest.TestCase):
    def test_fuzz_mai_eccezioni_e_invarianti(self):
        rnd = random.Random(50)
        for _ in range(5000):
            kw = {}
            esp = MotoreInFiamme() if rnd.random() < 0.5 else StubEsploratore()
            adv = MotoreInFiamme() if rnd.random() < 0.5 else StubAdvertising()
            pon = MotoreInFiamme() if rnd.random() < 0.3 else StubPonte()
            o = crea_orchestratore(esploratore=esp, venditore=StubVenditore(),
                                   advertising=adv, ponte=pon, abilitato=True)
            args = dict(fonti=["f"], leads=["l"], giorno=0, capacita=1,
                        budget_cents=10, campagne=["c"], conversione={"k": 1})
            # input opzionali rimossi a caso: lo stadio deve solo sparire, mai crashare
            for chiave in ("fonti", "leads", "budget_cents", "campagne", "conversione"):
                if rnd.random() < 0.3:
                    args[chiave] = None
            r = o.esegui_ciclo(**args)                   # NON deve mai sollevare
            self.assertIsInstance(r, ReportCiclo)
            self.assertTrue(r.abilitato)
            # ok_totale sse e solo se nessuno stadio eseguito e' fallito
            self.assertEqual(r.ok_totale, all(s.ok for s in r.stadi))


if __name__ == "__main__":
    unittest.main()
