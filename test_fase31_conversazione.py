"""
Test FASE 31 / BLOCCO 3 - Cablaggio cervello budget-aware (multi-turno).

Copre: MemoriaConversazioni (Variante D) limitata su DUE dimensioni (ring per chat
+ LRU globale) con ANCORA-intento immune allo scorrimento, thread-safe; l'
AgenteConversazionale (intento + risposta budget-aware, fallback non memorizzato,
isolamento); e i DUE aganci default-off al nucleo (AgenteIA.client e
GatewayAgente.conversazione) col budget mai sforato end-to-end.
"""
import threading
import unittest

from fase25_brain import LLMProvider, StubLLMProvider, AgenteIA, Intento
from fase30_llm import Messaggio, BudgetToken, ClientLLM
from fase31_conversazione import (MemoriaConversazioni, AgenteConversazionale,
                                  RispostaConversazione)
from fase28_gateway import GatewayAgente, ClientRegistry


class _Failing(LLMProvider):
    def genera(self, p):
        raise RuntimeError("LLM down")


def _fn_intento(prompt):
    msg = prompt.split("Messaggio:")[-1].lower()
    if "prenot" in msg:
        return "prenotazione"
    if "ciao" in msg:
        return "saluto"
    return "domanda_generica"


# ── MemoriaConversazioni (Variante D) ────────────────────────────────────────
class TestMemoria(unittest.TestCase):
    def test_validazione(self):
        with self.assertRaises(ValueError):
            MemoriaConversazioni(max_sessioni=0)
        with self.assertRaises(ValueError):
            MemoriaConversazioni(max_turni=0)

    def test_ordine_system_ancora_recenti(self):
        m = MemoriaConversazioni(max_turni=4)
        m.registra("r", "user", "INTENTO: trullo a Roma")
        m.registra("r", "assistant", "ok")
        cron = m.cronologia("r", system="Sei un assistente.")
        self.assertEqual(cron[0].ruolo, "system")
        self.assertEqual(cron[0].contenuto, "Sei un assistente.")
        self.assertEqual(cron[1].contenuto, "INTENTO: trullo a Roma")  # ancora

    def test_ring_limita_i_turni(self):
        m = MemoriaConversazioni(max_turni=4)
        for i in range(20):
            m.registra("r", "user", f"t{i}")
        cron = m.cronologia("r")  # ancora + ring(4); ancora fuori dal ring
        self.assertLessEqual(len(cron), 5)

    def test_ancora_preservata_oltre_il_ring(self):
        m = MemoriaConversazioni(max_turni=3)
        m.registra("r", "user", "INTENTO: cerco trullo")  # turno 0 = ancora
        for i in range(10):
            m.registra("r", "assistant", f"riempi {i}")
        testo = " ".join(x.contenuto for x in m.cronologia("r"))
        self.assertIn("INTENTO: cerco trullo", testo)  # intento immune al ring

    def test_lru_globale_sfratta_le_idle(self):
        m = MemoriaConversazioni(max_sessioni=10, max_turni=4)
        for i in range(100):
            m.registra(f"chat_{i}", "user", "x")
        self.assertEqual(m.num_sessioni(), 10)  # tetto duro sul numero di chat
        self.assertEqual(m.cronologia("chat_0"), [])  # sfrattata

    def test_dimentica(self):
        m = MemoriaConversazioni()
        m.registra("r", "user", "x")
        m.dimentica("r")
        self.assertEqual(m.num_sessioni(), 0)

    def test_thread_safe(self):
        m = MemoriaConversazioni(max_sessioni=50, max_turni=8)
        def w(k):
            for i in range(50):
                m.registra(f"chat_{k}_{i % 5}", "user", f"m{i}")
                m.cronologia(f"chat_{k}_{i % 5}")
        ts = [threading.Thread(target=w, args=(k,)) for k in range(10)]
        for t in ts: t.start()
        for t in ts: t.join()
        self.assertLessEqual(m.num_sessioni(), 50)  # mai sopra il cap, nessun crash


# ── AgenteConversazionale ────────────────────────────────────────────────────
class TestAgenteConversazionale(unittest.TestCase):
    def _make(self, provider, **kw):
        ag = AgenteIA(StubLLMProvider(_fn_intento))
        client = ClientLLM(provider, BudgetToken(120, 20))
        conv = AgenteConversazionale(ag, client, **kw)
        self.addCleanup(conv.stop)
        return conv

    def test_risposta_e_intento(self):
        conv = self._make(StubLLMProvider(risposta="Disponibile!"))
        r = conv.rispondi("+39111", "vorrei prenotare")
        self.assertIsInstance(r, RispostaConversazione)
        self.assertTrue(r.ok)
        self.assertEqual(r.testo, "Disponibile!")
        self.assertEqual(r.intento, Intento.PRENOTAZIONE)

    def test_memoria_cresce_ma_budget_mai_sforato(self):
        conv = self._make(StubLLMProvider(risposta="ok"),
                          system_prompt="Sei un assistente immobiliare.")
        for i in range(40):  # chat lunga: la memoria + compressione tengono il budget
            r = conv.rispondi("+39222", f"messaggio numero {i} con dettagli vari")
            self.assertLessEqual(r.token_input, 100)  # input_max = 120 - 20
        self.assertEqual(conv.num_sessioni(), 1)

    def test_fallback_non_memorizzato(self):
        conv = self._make(_Failing())
        r = conv.rispondi("+39333", "ciao")
        self.assertFalse(r.ok)
        # il fallback non deve finire nello storico (non inquina il contesto)
        cron = conv._memoria.cronologia("+39333")
        self.assertTrue(all(msg.ruolo != "assistant" for msg in cron))

    def test_intento_precalcolato_non_rianalizza(self):
        conv = self._make(StubLLMProvider(risposta="ok"))
        r = conv.rispondi("+39444", "testo qualsiasi", intento=Intento.RECLAMO)
        self.assertEqual(r.intento, Intento.RECLAMO)


# ── Aggancio AgenteIA (client opzionale) ─────────────────────────────────────
class TestAgganciAgenteIA(unittest.TestCase):
    def test_default_off_invariato(self):
        ag = AgenteIA(StubLLMProvider(risposta="X"))
        self.addCleanup(ag.stop)
        self.assertEqual(ag.genera_risposta("ciao").testo, "X")

    def test_client_iniettato_applica_budget(self):
        client = ClientLLM(StubLLMProvider(risposta="risposta breve"),
                           BudgetToken(80, 20))
        ag = AgenteIA(StubLLMProvider(_fn_intento), client=client)
        self.addCleanup(ag.stop)
        # contesto enorme: il ClientLLM lo comprime entro il budget, niente crash
        r = ag.genera_risposta("domanda", contesto="C" * 100_000)
        self.assertTrue(r.ok)
        self.assertEqual(r.testo, "risposta breve")


# ── Aggancio Gateway (conversazione opzionale) ───────────────────────────────
class TestAgganciGateway(unittest.TestCase):
    def test_gateway_multi_turno_budget_aware(self):
        clients = ClientRegistry({"k1": "cliente1"})
        ag = AgenteIA(StubLLMProvider(_fn_intento))
        client = ClientLLM(StubLLMProvider(risposta="Ti aiuto!"), BudgetToken(120, 20))
        conv = AgenteConversazionale(ag, client,
                                     system_prompt="Sei un assistente.")
        self.addCleanup(conv.stop)
        gw = GatewayAgente(clients, ag, conversazione=conv)
        data = {"channel": "whatsapp", "recipient": "+39999", "text": "ciao"}
        r1 = gw.processa("k1", data)
        r2 = gw.processa("k1", data)
        self.assertEqual(r1.status, 200)
        self.assertEqual(r1.corpo["risposta"], "Ti aiuto!")
        self.assertEqual(r2.status, 200)
        self.assertEqual(conv.num_sessioni(), 1)  # stessa chat, una sola sessione

    def test_gateway_default_off_usa_agente(self):
        clients = ClientRegistry({"k1": "cliente1"})
        ag = AgenteIA(StubLLMProvider(risposta="domanda_generica"))
        self.addCleanup(ag.stop)
        gw = GatewayAgente(clients, ag)  # nessuna conversazione -> path classico
        data = {"channel": "wa", "recipient": "+1", "text": "che ore sono"}
        r = gw.processa("k1", data)
        self.assertEqual(r.status, 200)


if __name__ == "__main__":
    unittest.main()
