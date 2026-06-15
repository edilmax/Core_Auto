"""
Test FASE 30 / BLOCCO 4 - Client LLM reale (Token Budget + Compressione).

Copre: stima/troncamento token, validazione budget, compressione Variante C
(preserva intento + coda recente, riassume il mezzo), il TOKEN BUDGET SPIETATO
(non sfora MAI, nemmeno con un messaggio piu' grande della finestra), un test di
STRESS a proprieta' (centinaia di conversazioni avverse casuali, mai uno sforo),
l'ereditarieta' della resilienza dal ResilientBrain (cache + isolamento) e il
riassuntore-LLM con degrado sicuro.
"""
import random
import unittest

from fase25_brain import LLMProvider, StubLLMProvider
from fase30_llm import (Messaggio, StimatoreEuristico, BudgetToken,
                        CompressoreContesto, ClientLLM, RispostaChat,
                        crea_riassuntore_llm)


class _Failing(LLMProvider):
    def genera(self, p):
        raise RuntimeError("LLM down")


class _Counting(LLMProvider):
    def __init__(self, inner):
        self.inner, self.calls = inner, 0
    def genera(self, p):
        self.calls += 1
        return self.inner.genera(p)


def _chat_lunga(n_filler=60):
    msgs = [Messaggio("system", "Sei un assistente immobiliare.")]
    msgs.append(Messaggio("user", "INTENTO: prenotare un trullo a Roma sotto i 100 euro"))
    for i in range(n_filler):
        ruolo = "assistant" if i % 2 else "user"
        msgs.append(Messaggio(ruolo, f"messaggio di riempimento numero {i} bla bla bla"))
    msgs.append(Messaggio("user", "ok ma per quali date sono disponibili?"))
    return msgs


# ── Messaggio ────────────────────────────────────────────────────────────────
class TestMessaggio(unittest.TestCase):
    def test_ruolo_non_valido(self):
        with self.assertRaises(ValueError):
            Messaggio("robot", "x")

    def test_immutabile(self):
        m = Messaggio("user", "ciao")
        with self.assertRaises(Exception):
            m.contenuto = "altro"  # frozen


# ── Stimatore ────────────────────────────────────────────────────────────────
class TestStimatore(unittest.TestCase):
    def setUp(self):
        self.st = StimatoreEuristico(char_per_token=4, overhead_msg=3)

    def test_conta_vuoto_e_pieno(self):
        self.assertEqual(self.st.conta(""), 0)
        self.assertEqual(self.st.conta("abcd"), 1)
        self.assertEqual(self.st.conta("a" * 40), 10)

    def test_tronca_rispetta_il_tetto(self):
        s = "a" * 100
        for n in (0, 1, 5, 25, 100):
            self.assertLessEqual(self.st.conta(self.st.tronca(s, n)), n)

    def test_conta_messaggi_include_overhead(self):
        m = [Messaggio("user", "abcd")]  # 1 token + 3 overhead
        self.assertEqual(self.st.conta_messaggi(m), 4)


# ── Budget ───────────────────────────────────────────────────────────────────
class TestBudget(unittest.TestCase):
    def test_input_max(self):
        self.assertEqual(BudgetToken(1000, 200).input_max, 800)

    def test_validazione(self):
        for f, r in ((0, 0), (100, -1), (100, 100), (100, 200)):
            with self.assertRaises(ValueError):
                BudgetToken(f, r)


# ── Compressione (Variante C) ────────────────────────────────────────────────
class TestCompressore(unittest.TestCase):
    def setUp(self):
        self.st = StimatoreEuristico()
        self.comp = CompressoreContesto(self.st)

    def test_no_op_se_gia_dentro(self):
        msgs = [Messaggio("user", "ciao")]
        self.assertEqual(self.comp.comprimi(msgs, 1000), msgs)

    def test_preserva_intento_e_coda_riassume_mezzo(self):
        msgs = _chat_lunga()
        budget = 60
        out = self.comp.comprimi(msgs, budget)
        testo = " ".join(m.contenuto for m in out)
        self.assertLessEqual(self.st.conta_messaggi(out), budget)
        self.assertIn("prenotare un trullo a Roma", testo)   # intento (ancora)
        self.assertIn("per quali date", testo)               # coda recente
        self.assertIn("riassunto", testo)                    # mezzo riassunto

    def test_messaggio_gigante_troncato_dentro_budget(self):
        """Un singolo messaggio piu' grande dell'intera finestra: SPIETATO."""
        msgs = [Messaggio("system", "Sei un assistente."),
                Messaggio("user", "X" * 100_000)]
        budget = 50
        out = self.comp.comprimi(msgs, budget)
        self.assertLessEqual(self.st.conta_messaggi(out), budget)
        self.assertTrue(any(m.contenuto for m in out))  # resta qualcosa di utile

    def test_riassuntore_iniettato(self):
        comp = CompressoreContesto(self.st, riassuntore=lambda r: "SOMMARIO_CUSTOM")
        out = comp.comprimi(_chat_lunga(), 60)
        self.assertTrue(any("SOMMARIO_CUSTOM" in m.contenuto for m in out))


# ── ClientLLM ────────────────────────────────────────────────────────────────
class TestClientLLM(unittest.TestCase):
    def test_chat_ok_e_passthrough(self):
        c = ClientLLM(StubLLMProvider(risposta="Disponibile!"),
                      BudgetToken(1000, 200))
        self.addCleanup(c.stop)
        r = c.chat([Messaggio("user", "avete posto?")])
        self.assertIsInstance(r, RispostaChat)
        self.assertTrue(r.ok)
        self.assertEqual(r.testo, "Disponibile!")
        self.assertFalse(r.compresso)

    def test_compressione_attiva_su_chat_lunga(self):
        c = ClientLLM(StubLLMProvider(risposta="ok"), BudgetToken(80, 20))
        self.addCleanup(c.stop)
        r = c.chat(_chat_lunga())
        self.assertTrue(r.compresso)
        self.assertLessEqual(r.token_input, c._budget.input_max)
        self.assertLess(r.token_input, r.token_originali)

    def test_budget_mai_sforato_caso_estremo(self):
        c = ClientLLM(StubLLMProvider(risposta="ok"), BudgetToken(60, 10))
        self.addCleanup(c.stop)
        msgs = [Messaggio("system", "S"), Messaggio("user", "Z" * 500_000)]
        r = c.chat(msgs)
        self.assertLessEqual(r.token_input, c._budget.input_max)

    def test_stress_proprieta_mai_sforo(self):
        """Centinaia di conversazioni avverse casuali: il budget NON si sfora MAI."""
        rng = random.Random(42)
        c = ClientLLM(StubLLMProvider(risposta="ok"), BudgetToken(120, 20))
        self.addCleanup(c.stop)
        for _ in range(300):
            n = rng.randint(0, 40)
            msgs = []
            if rng.random() < 0.7:
                msgs.append(Messaggio("system", "S" * rng.randint(0, 2000)))
            for i in range(n):
                ruolo = rng.choice(("user", "assistant"))
                msgs.append(Messaggio(ruolo, "w" * rng.randint(0, 5000)))
            r = c.chat(msgs)
            self.assertLessEqual(r.token_input, c._budget.input_max,
                                 f"SFORO con {len(msgs)} msg")

    def test_isolamento_llm_giu(self):
        c = ClientLLM(_Failing(), BudgetToken(1000, 200))
        self.addCleanup(c.stop)
        r = c.chat([Messaggio("user", "ciao")])
        self.assertFalse(r.ok)
        self.assertTrue(r.testo)  # fallback non vuoto, nessun crash

    def test_cache_ereditata(self):
        cp = _Counting(StubLLMProvider(risposta="X"))
        c = ClientLLM(cp, BudgetToken(1000, 200))
        self.addCleanup(c.stop)
        msgs = [Messaggio("user", "stessa domanda")]
        c.chat(msgs)
        r2 = c.chat(msgs)
        self.assertEqual(r2.esito, "cache")
        self.assertEqual(cp.calls, 1)


# ── Riassuntore-LLM ──────────────────────────────────────────────────────────
class TestRiassuntoreLLM(unittest.TestCase):
    def test_usa_llm_se_disponibile(self):
        riass = crea_riassuntore_llm(StubLLMProvider(risposta="sintesi viva"))
        out = riass([Messaggio("user", "blocco di testo da riassumere")])
        self.assertIn("sintesi viva", out)

    def test_degrada_se_llm_giu(self):
        riass = crea_riassuntore_llm(_Failing())
        out = riass([Messaggio("user", "a"), Messaggio("user", "b")])
        self.assertIn("riassunto di 2 messaggi", out)


if __name__ == "__main__":
    unittest.main()
