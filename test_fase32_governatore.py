"""
Test FASE 32 / BLOCCO 3 - Governatore globale dei token (quota/costo LLM).

Copre: GovernatoreToken (Variante D) sliding-window log + riserve per priorita':
la GARANZIA DURA (nessuna finestra mobile supera mai il limite, anche su stream
avverso), il rilascio dopo la finestra, lo shed della bassa priorita' che protegge
i critici, la thread-safety; e il cablaggio nel ClientLLM (quota negata => l'IA NON
viene chiamata, si differisce) + la propagazione della priorita' in conversazione.
"""
import random
import threading
import unittest

from fase29_backpressure import Priorita
from fase30_llm import Messaggio, BudgetToken, ClientLLM
from fase32_governatore import GovernatoreToken, EsitoGovernatore
from fase25_brain import LLMProvider, StubLLMProvider, AgenteIA
from fase31_conversazione import AgenteConversazionale


class _Counting(LLMProvider):
    def __init__(self, inner):
        self.inner, self.calls = inner, 0
    def genera(self, p):
        self.calls += 1
        return self.inner.genera(p)


class _Clock:
    """Orologio simulato (deterministico)."""
    def __init__(self):
        self.t = 0.0
    def __call__(self):
        return self.t


# ── GovernatoreToken ─────────────────────────────────────────────────────────
class TestGovernatore(unittest.TestCase):
    def test_validazione(self):
        with self.assertRaises(ValueError):
            GovernatoreToken(0)
        with self.assertRaises(ValueError):
            GovernatoreToken(100, finestra_s=0)

    def test_concede_entro_il_limite_poi_nega(self):
        g = GovernatoreToken(100, clock=lambda: 0.0)
        self.assertTrue(g.acquisisci(60, Priorita.ALTA).concesso)
        self.assertTrue(g.acquisisci(40, Priorita.ALTA).concesso)  # somma 100
        e = g.acquisisci(1, Priorita.ALTA)
        self.assertFalse(e.concesso)
        self.assertEqual(e.motivo, "quota_superata")

    def test_rilascio_dopo_la_finestra(self):
        clk = _Clock()
        g = GovernatoreToken(100, finestra_s=60.0, clock=clk)
        self.assertTrue(g.acquisisci(100, Priorita.ALTA).concesso)
        clk.t = 30.0
        self.assertFalse(g.acquisisci(1, Priorita.ALTA).concesso)  # ancora in finestra
        clk.t = 61.0
        self.assertTrue(g.acquisisci(100, Priorita.ALTA).concesso)  # finestra liberata

    def test_riserve_proteggono_i_critici(self):
        g = GovernatoreToken(100, clock=lambda: 0.0)  # BASSA<=70, NORMALE<=90, ALTA<=100
        self.assertTrue(g.acquisisci(70, Priorita.BASSA).concesso)
        sh = g.acquisisci(10, Priorita.BASSA)
        self.assertFalse(sh.concesso)
        self.assertEqual(sh.motivo, "shed_priorita")            # bassa differita per prima
        self.assertTrue(g.acquisisci(10, Priorita.NORMALE).concesso)  # somma 80
        self.assertTrue(g.acquisisci(20, Priorita.ALTA).concesso)     # critico servito (100)

    def test_garanzia_dura_finestra_mobile(self):
        """Stream avverso casuale: NESSUNA finestra mobile supera mai il limite."""
        rng = random.Random(7)
        clk = _Clock()
        LIM, W = 1000, 60.0
        g = GovernatoreToken(LIM, finestra_s=W, soglia_bassa=1.0, soglia_normale=1.0,
                             clock=clk)
        log = []
        for _ in range(5000):
            clk.t += rng.uniform(0.0, 0.5)
            tok = rng.randint(1, 400)
            if g.acquisisci(tok, Priorita.ALTA).concesso:
                log.append((clk.t, tok))
        # per ogni concessione, il totale nella finestra (t-W, t] non supera LIM
        for te, _ in log:
            s = sum(t for ts, t in log if te - W < ts <= te)
            self.assertLessEqual(s, LIM)

    def test_thread_safe_non_sfora(self):
        g = GovernatoreToken(10_000, finestra_s=3600.0, soglia_bassa=1.0,
                             soglia_normale=1.0, clock=lambda: 0.0)
        def w():
            for _ in range(500):
                g.acquisisci(5, Priorita.ALTA)
        ts = [threading.Thread(target=w) for _ in range(8)]
        for t in ts: t.start()
        for t in ts: t.join()
        self.assertLessEqual(g.token_in_finestra(), 10_000)  # mai oltre il limite

    def test_memoria_limitata_sotto_carico(self):
        """Bucket-conservativo: la memoria resta O(finestra/bucket) anche con
        throughput estremo (vs 1 evento per richiesta del log esatto)."""
        clk = _Clock()
        W, B = 60.0, 1.0
        g = GovernatoreToken(10_000, finestra_s=W, bucket_s=B, soglia_bassa=1.0,
                             soglia_normale=1.0, clock=clk)
        for _ in range(50_000):           # alto TPS: molte richieste per finestra
            clk.t += 0.001
            g.acquisisci(1, Priorita.ALTA)
        self.assertLessEqual(g.stats()["bucket_attivi"], int(W / B) + 2)

    def test_purge_conservativo_non_sfora_finestra_mobile(self):
        """Stream a passo fine: il purge conservativo non concede mai oltre il
        limite in nessuna finestra mobile (la quantizzazione e' SICURA)."""
        clk = _Clock()
        W = 60.0
        g = GovernatoreToken(1000, finestra_s=W, soglia_bassa=1.0, soglia_normale=1.0,
                             clock=clk)
        log = []
        for _ in range(20_000):
            clk.t += 0.05
            if g.acquisisci(37, Priorita.ALTA).concesso:
                log.append((clk.t, 37))
        # max in finestra mobile (two-pointer)
        peggio = somma = i = 0
        for j in range(len(log)):
            somma += log[j][1]
            while log[i][0] <= log[j][0] - W:
                somma -= log[i][1]; i += 1
            peggio = max(peggio, somma)
        self.assertLessEqual(peggio, 1000)


# ── Cablaggio nel ClientLLM ──────────────────────────────────────────────────
class TestClientLLMGovernato(unittest.TestCase):
    def test_quota_negata_non_chiama_l_ia(self):
        cp = _Counting(StubLLMProvider(risposta="ok"))
        g = GovernatoreToken(100, clock=lambda: 0.0)
        c = ClientLLM(cp, BudgetToken(200, 80), governatore=g)  # costo ~ finale+80
        self.addCleanup(c.stop)
        r1 = c.chat([Messaggio("user", "ciao")])
        self.assertTrue(r1.ok)
        r2 = c.chat([Messaggio("user", "ciao")])  # supera la quota -> differito
        self.assertFalse(r2.ok)
        self.assertEqual(r2.esito, "differito_quota")
        self.assertEqual(cp.calls, 1)  # l'IA NON e' stata chiamata la 2a volta

    def test_priorita_alta_passa_quando_bassa_e_shed(self):
        g = GovernatoreToken(100, clock=lambda: 0.0)
        c = ClientLLM(StubLLMProvider(risposta="ok"), BudgetToken(200, 41), governatore=g)
        self.addCleanup(c.stop)
        # costo ~ finale(4)+41 = 45; BASSA soglia 70 -> 1a passa (45), 2a (90) shed
        self.assertTrue(c.chat([Messaggio("user", "ciao")], Priorita.BASSA).ok)
        self.assertFalse(c.chat([Messaggio("user", "ciao")], Priorita.BASSA).ok)
        # ALTA soglia 100: somma 45 + 45 = 90 <= 100 -> il critico passa comunque
        self.assertTrue(c.chat([Messaggio("user", "ciao")], Priorita.ALTA).ok)

    def test_default_off_invariato(self):
        c = ClientLLM(StubLLMProvider(risposta="X"), BudgetToken(200, 50))
        self.addCleanup(c.stop)
        for _ in range(10):
            self.assertTrue(c.chat([Messaggio("user", "ciao")]).ok)  # nessun limite


# ── Propagazione priorita' in conversazione ──────────────────────────────────
class TestConversazionePriorita(unittest.TestCase):
    def test_priorita_governa_la_quota(self):
        g = GovernatoreToken(100, clock=lambda: 0.0)
        ag = AgenteIA(StubLLMProvider(risposta="domanda_generica"))
        client = ClientLLM(StubLLMProvider(risposta="ok"), BudgetToken(200, 41),
                           governatore=g)
        conv = AgenteConversazionale(ag, client)
        self.addCleanup(conv.stop)
        self.assertTrue(conv.rispondi("+1", "ciao", priorita=Priorita.BASSA).ok)
        # quota satura per la bassa priorita' -> differita
        self.assertFalse(conv.rispondi("+2", "ciao", priorita=Priorita.BASSA).ok)
        # il critico passa
        self.assertTrue(conv.rispondi("+3", "ciao", priorita=Priorita.ALTA).ok)


if __name__ == "__main__":
    unittest.main()
