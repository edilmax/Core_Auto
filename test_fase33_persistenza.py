"""
Test FASE 33 / BLOCCO 3 - Stato conversazionale durevole e cross-worker.

Copre: durabilita' (sopravvive a 'restart' = nuova istanza), correttezza
CROSS-WORKER (un'istanza fresca rilegge cio' che un'altra ha scritto), ancora-
intento preservata oltre il ring dopo reload, coda recente, potatura durevole
(righe-per-chat limitate), niente duplicato dell'ancora, thread-safety, e
l'INTEGRAZIONE con AgenteConversazionale: la chat CONTINUA dopo un restart.
"""
import os
import sqlite3
import tempfile
import threading
import unittest

from fase33_persistenza import (MemoriaConversazioniDurevole,
                                crea_memoria_conversazioni)
from fase31_conversazione import MemoriaConversazioni
from fase25_brain import AgenteIA, StubLLMProvider
from fase30_llm import ClientLLM, BudgetToken
from fase31_conversazione import AgenteConversazionale


def _fn_intento(prompt):
    return "prenotazione" if "prenot" in prompt.lower() else "domanda_generica"


class _Tmp(unittest.TestCase):
    """Base: crea un db temporaneo isolato e lo pulisce (con -wal/-shm)."""
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
    def tearDown(self):
        for ext in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + ext)
            except OSError:
                pass
    def _rows(self, conv):
        c = sqlite3.connect(self.path)
        try:
            return c.execute("SELECT COUNT(*) FROM memoria_conversazioni WHERE conv=?",
                             (conv,)).fetchone()[0]
        finally:
            c.close()


class TestDurabilita(_Tmp):
    def test_recovery_dopo_restart(self):
        m = MemoriaConversazioniDurevole(location=self.path)
        m.registra("+1", "user", "ciao")
        m.registra("+1", "assistant", "salve")
        # 'restart': istanza nuova sullo stesso DB
        m2 = MemoriaConversazioniDurevole(location=self.path)
        cron = m2.cronologia("+1")
        testi = [x.contenuto for x in cron]
        self.assertIn("ciao", testi)
        self.assertIn("salve", testi)

    def test_cross_worker(self):
        a = MemoriaConversazioniDurevole(location=self.path)
        b = MemoriaConversazioniDurevole(location=self.path)  # altro 'worker'
        a.registra("+9", "user", "scritto da A")
        # B non ha cache di +9 -> ricostruisce dal DB condiviso
        testi = [x.contenuto for x in b.cronologia("+9")]
        self.assertIn("scritto da A", testi)

    def test_ancora_preservata_oltre_il_ring_dopo_reload(self):
        m = MemoriaConversazioniDurevole(location=self.path, max_turni=4)
        m.registra("+2", "user", "INTENTO trullo a Roma")
        for i in range(20):
            m.registra("+2", "assistant", f"riempi {i}")
        m2 = MemoriaConversazioniDurevole(location=self.path, max_turni=4)
        testo = " ".join(x.contenuto for x in m2.cronologia("+2"))
        self.assertIn("INTENTO trullo a Roma", testo)   # intento durevole + immune
        self.assertIn("riempi 19", testo)               # coda recente

    def test_potatura_limita_le_righe(self):
        m = MemoriaConversazioniDurevole(location=self.path, max_turni=4, pota_ogni=4)
        for i in range(40):
            m.registra("+3", "user" if i == 0 else "assistant", f"t{i}")
        # ancora + ultimi max_turni + al piu' pota_ogni accumulati tra due potature
        self.assertLessEqual(self._rows("+3"), 1 + 4 + 4)

    def test_niente_duplicato_ancora_su_chat_corta(self):
        m = MemoriaConversazioniDurevole(location=self.path, max_turni=6)
        m.registra("+4", "user", "UNICO")
        m2 = MemoriaConversazioniDurevole(location=self.path, max_turni=6)
        testi = [x.contenuto for x in m2.cronologia("+4")]
        self.assertEqual(testi.count("UNICO"), 1)

    def test_dimentica(self):
        m = MemoriaConversazioniDurevole(location=self.path)
        m.registra("+5", "user", "x")
        m.dimentica("+5")
        self.assertEqual(m.cronologia("+5"), [])
        self.assertEqual(self._rows("+5"), 0)

    def test_num_sessioni_distinte(self):
        m = MemoriaConversazioniDurevole(location=self.path)
        for i in range(5):
            m.registra(f"+{i}", "user", "x")
            m.registra(f"+{i}", "assistant", "y")
        self.assertEqual(m.num_sessioni(), 5)

    def test_validazione(self):
        with self.assertRaises(ValueError):
            MemoriaConversazioniDurevole(location=self.path, max_turni=0)


class TestFactory(_Tmp):
    def test_default_off_in_ram(self):
        m = crea_memoria_conversazioni(durevole=False)
        self.assertIsInstance(m, MemoriaConversazioni)

    def test_flag_acceso_durevole(self):
        m = crea_memoria_conversazioni(durevole=True, location=self.path)
        self.assertIsInstance(m, MemoriaConversazioniDurevole)
        m.registra("+1", "user", "x")
        m2 = crea_memoria_conversazioni(durevole=True, location=self.path)
        self.assertTrue(m2.cronologia("+1"))  # durevole


class TestConcorrenza(_Tmp):
    def test_thread_safe_e_durevole(self):
        m = MemoriaConversazioniDurevole(location=self.path, max_cache=20)
        def w(k):
            for i in range(10):
                m.registra(f"chat_{k}", "user" if i % 2 == 0 else "assistant", f"m{i}")
        ts = [threading.Thread(target=w, args=(k,)) for k in range(8)]
        for t in ts: t.start()
        for t in ts: t.join()
        # istanza fresca: tutte le 8 chat sono durevoli
        m2 = MemoriaConversazioniDurevole(location=self.path)
        self.assertEqual(m2.num_sessioni(), 8)
        for k in range(8):
            self.assertTrue(m2.cronologia(f"chat_{k}"))


class TestIntegrazioneRestart(_Tmp):
    """Il test KILLER: la conversazione CONTINUA dopo un restart dell'agente."""
    def _agente(self):
        mem = MemoriaConversazioniDurevole(location=self.path, max_turni=6)
        ag = AgenteIA(StubLLMProvider(_fn_intento))
        client = ClientLLM(StubLLMProvider(risposta="ok"), BudgetToken(300, 50))
        conv = AgenteConversazionale(ag, client, mem,
                                     system_prompt="Sei un assistente immobiliare.")
        self.addCleanup(conv.stop)
        return conv, mem

    def test_conversazione_continua_dopo_restart(self):
        conv1, _ = self._agente()
        conv1.rispondi("+39333", "vorrei prenotare un trullo")
        conv1.rispondi("+39333", "per agosto")
        # RESTART: nuovo agente + nuova memoria durevole sullo STESSO DB
        conv2, mem2 = self._agente()
        cron = mem2.cronologia("+39333")
        testo = " ".join(x.contenuto for x in cron)
        self.assertIn("vorrei prenotare un trullo", testo)  # intento sopravvive
        self.assertIn("per agosto", testo)                  # contesto sopravvive
        # e un nuovo turno si aggancia allo storico esistente
        r = conv2.rispondi("+39333", "confermo")
        self.assertTrue(r.ok)
        self.assertIn("confermo", " ".join(
            x.contenuto for x in mem2.cronologia("+39333")))


if __name__ == "__main__":
    unittest.main()
