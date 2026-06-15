"""
Test FASE 25 / BLOCCO 3 - Il Cervello (LLMProvider + ResilientBrain + AgenteIA).

Copre: cache, circuit breaker, timeout, ISOLAMENTO TOTALE (l'IA giu'/lenta/
difettosa non fa MAI crashare il sistema), analisi intento deterministica e
l'aggancio (loop agente) ai canali via Outbox.
"""
import os
import shutil
import tempfile
import threading
import time
import unittest

from fase25_brain import (LLMProvider, StubLLMProvider, ResilientBrain, AgenteIA,
                          Intento, RispostaAgente, rispondi_su_canale)


class _Counting(LLMProvider):
    def __init__(self, inner):
        self.inner, self.calls = inner, 0
    def genera(self, p):
        self.calls += 1
        return self.inner.genera(p)


class _Failing(LLMProvider):
    def genera(self, p):
        raise RuntimeError("LLM down")


class _Slow(LLMProvider):
    def __init__(self, d):
        self.d = d
    def genera(self, p):
        time.sleep(self.d)
        return "lento"


def _fn_intento(prompt):
    """Stub deterministico: classifica leggendo la PARTE messaggio del prompt."""
    msg = prompt.split("Messaggio:")[-1].lower()
    if "prenot" in msg:
        return "prenotazione"
    if "ciao" in msg or "salve" in msg:
        return "saluto"
    return "domanda_generica"


class TestResilientBrain(unittest.TestCase):

    def test_successo_e_cache(self):
        cp = _Counting(StubLLMProvider(risposta="X"))
        b = ResilientBrain(cp)
        self.addCleanup(b.stop)
        r1 = b.genera("ciao")
        r2 = b.genera("ciao")
        self.assertEqual((r1.esito, r1.ok), ("llm", True))
        self.assertEqual((r2.esito, r2.ok), ("cache", True))
        self.assertEqual(cp.calls, 1)

    def test_circuit_breaker_apre_e_cortocircuita(self):
        cf = _Counting(_Failing())
        b = ResilientBrain(cf, cb_threshold=3, cb_cooldown=999)
        self.addCleanup(b.stop)
        for i in range(20):
            self.assertFalse(b.genera(f"p{i}").ok)   # mai crash, sempre fallback
        self.assertEqual(cf.calls, 3)                 # poi corto-circuitato
        self.assertEqual(b.stato_circuito(), "open")

    def test_timeout_provider_lento(self):
        b = ResilientBrain(_Slow(0.4), timeout=0.05, cb_threshold=99)
        self.addCleanup(b.stop)
        t0 = time.perf_counter()
        r = b.genera("x")
        dt = time.perf_counter() - t0
        self.assertEqual(r.esito, "fallback_timeout")
        self.assertFalse(r.ok)
        self.assertLess(dt, 0.3)

    def test_non_solleva_mai(self):
        b = ResilientBrain(_Failing())
        self.addCleanup(b.stop)
        r = b.genera("x")
        self.assertFalse(r.ok)
        self.assertEqual(r.esito, "fallback_errore")
        self.assertTrue(r.testo)  # fallback non vuoto

    def test_concorrenza_no_crash(self):
        b = ResilientBrain(StubLLMProvider(risposta="ok"))
        self.addCleanup(b.stop)
        risultati = []
        def w(i):
            risultati.append(b.genera(f"p{i % 5}").ok)
        ts = [threading.Thread(target=w, args=(i,)) for i in range(30)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(len(risultati), 30)
        self.assertTrue(all(risultati))


class TestAgenteIA(unittest.TestCase):

    def test_intento_deterministico(self):
        ag = AgenteIA(StubLLMProvider(_fn_intento))
        self.addCleanup(ag.stop)
        self.assertEqual(ag.analizza_intento("vorrei prenotare"), Intento.PRENOTAZIONE)
        self.assertEqual(ag.analizza_intento("ciao"), Intento.SALUTO)
        self.assertEqual(ag.analizza_intento("che tempo fa"), Intento.DOMANDA_GENERICA)

    def test_intento_non_parsabile_sconosciuto(self):
        ag = AgenteIA(StubLLMProvider(risposta="blah blah"))
        self.addCleanup(ag.stop)
        self.assertEqual(ag.analizza_intento("x"), Intento.SCONOSCIUTO)

    def test_llm_giu_isolamento(self):
        ag = AgenteIA(_Failing())
        self.addCleanup(ag.stop)
        self.assertEqual(ag.analizza_intento("prenota casa"), Intento.SCONOSCIUTO)
        r = ag.genera_risposta("ciao")
        self.assertFalse(r.ok)
        self.assertTrue(r.testo)

    def test_genera_risposta_ok(self):
        ag = AgenteIA(StubLLMProvider(risposta="Buongiorno!"))
        self.addCleanup(ag.stop)
        r = ag.genera_risposta("ciao")
        self.assertTrue(r.ok)
        self.assertEqual(r.testo, "Buongiorno!")


class TestLoopAgenteCanale(unittest.TestCase):
    """rispondi_su_canale: brain -> Outbox -> canale (triangolo completo)."""

    def setUp(self):
        from fase16_outbox import OutboxPublisher, OutboxDispatcher, _connessione
        from fase24_channels import ChannelRegistry, StubChannelAdapter, collega_a_outbox
        self.tmp = tempfile.mkdtemp()
        os.environ["CORE_AUTO_DB"] = os.path.join(self.tmp, "b.db")
        OutboxPublisher._reset_instance()
        self.pub = OutboxPublisher(os.environ["CORE_AUTO_DB"])
        self.disp = OutboxDispatcher(os.environ["CORE_AUTO_DB"])
        self.reg = ChannelRegistry()
        self.wa = StubChannelAdapter("whatsapp")
        self.reg.register(self.wa)
        collega_a_outbox(self.disp, self.reg)
        self._connessione = _connessione

    def tearDown(self):
        from fase16_outbox import OutboxPublisher
        self.disp.stop()
        OutboxPublisher._reset_instance()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_risposta_accodata_e_consegnata(self):
        ag = AgenteIA(StubLLMProvider(risposta="Ti aiuto subito!"))
        self.addCleanup(ag.stop)
        r = rispondi_su_canale(ag, self.pub, "whatsapp", "+3912345", "ciao")
        self.assertTrue(r.ok)
        # processa l'outbox -> l'adapter riceve la risposta generata
        row = self._connessione(os.environ["CORE_AUTO_DB"]).execute(
            "SELECT * FROM outbox ORDER BY id DESC LIMIT 1").fetchone()
        self.disp._process(row)
        self.assertEqual(self.wa.sent[-1].text, "Ti aiuto subito!")


if __name__ == "__main__":
    unittest.main()
