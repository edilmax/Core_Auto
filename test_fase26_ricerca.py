"""
Test FASE 26 / BLOCCO 3.1 - Motore di ricerca alloggi PROTETTO + orchestrazione.

Copre: filtro/ordine, cache (hit + TTL), ISOLAMENTO TOTALE (motore giu' -> []
fallback, mai crash) + circuit breaker (riduzione chiamate), provider REALE su
`candidati` (read-only) e l'orchestrazione intento -> ricerca/risposta.
"""
import os
import shutil
import tempfile
import time
import unittest

from fase26_ricerca import (CriteriRicerca, Proposta, RicercaProvider, RicercaStub,
                            RicercaTavolaVIP, MotoreRicercaProtetto,
                            gestisci_richiesta_alloggio, formatta_proposte)
from fase25_brain import AgenteIA, StubLLMProvider, Intento


_DATI = [Proposta("Trullo", "Roma", 80.0, "u1", 9.0),
         Proposta("Loft", "Roma", 200.0, "u2", 7.0),
         Proposta("Villa", "Milano", 300.0, "u3", 8.0)]


class _Counting(RicercaProvider):
    def __init__(self, inner):
        self.inner, self.calls = inner, 0
    def cerca(self, criteri):
        self.calls += 1
        return self.inner.cerca(criteri)


class TestMotoreProtetto(unittest.TestCase):

    def test_filtro_e_ordine(self):
        m = MotoreRicercaProtetto(RicercaStub(_DATI))
        r = m.cerca(CriteriRicerca("Roma", budget_max=100, limite=5))
        self.assertTrue(r.ok)
        self.assertEqual([p.titolo for p in r.proposte], ["Trullo"])  # Loft fuori budget

    def test_cache_hit(self):
        cp = _Counting(RicercaStub(_DATI))
        m = MotoreRicercaProtetto(cp)
        c = CriteriRicerca("Roma", limite=5)
        self.assertEqual(m.cerca(c).esito, "db")
        self.assertEqual(m.cerca(c).esito, "cache")
        self.assertEqual(cp.calls, 1)

    def test_cache_ttl_scade(self):
        cp = _Counting(RicercaStub(_DATI))
        m = MotoreRicercaProtetto(cp, cache_ttl=0.05)
        c = CriteriRicerca("Roma")
        m.cerca(c)
        time.sleep(0.07)
        self.assertEqual(m.cerca(c).esito, "db")  # TTL scaduto -> nuova query
        self.assertEqual(cp.calls, 2)

    def test_isolamento_guasto(self):
        m = MotoreRicercaProtetto(RicercaStub(fail=True))
        r = m.cerca(CriteriRicerca("Roma"))
        self.assertFalse(r.ok)
        self.assertEqual(r.esito, "fallback_errore")
        self.assertEqual(r.proposte, [])

    def test_circuit_breaker_riduce_chiamate(self):
        cp = _Counting(RicercaStub(fail=True))
        m = MotoreRicercaProtetto(cp, cb_threshold=3, cb_cooldown=999)
        for i in range(20):
            self.assertFalse(m.cerca(CriteriRicerca(f"x{i}")).ok)
        self.assertEqual(cp.calls, 3)
        self.assertEqual(m.stato_circuito(), "open")


class TestRicercaTavolaVIP(unittest.TestCase):
    """Provider REALE su `candidati` (read-only)."""

    def setUp(self):
        from assistente_gestionale import DatabaseCandidati
        self.tmp = tempfile.mkdtemp()
        self.db = DatabaseCandidati(os.path.join(self.tmp, "c.sqlite3"))
        conn = self.db.connessione()
        try:
            for url, tit, loc, prezzo, punt in [
                ("u1", "Trullo", "Roma", 80.0, 9.0),
                ("u2", "Loft", "Roma", 200.0, 7.0),
                ("u3", "Villa", "Milano", 300.0, 8.0)]:
                conn.execute(
                    "INSERT INTO candidati (url_candidato, titolo, localita, "
                    "prezzo, punteggio, data_trovato) VALUES (?, ?, ?, ?, ?, ?)",
                    (url, tit, loc, prezzo, punt, "2026-01-01"))
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_query_per_localita_e_budget(self):
        prov = RicercaTavolaVIP(self.db)
        proposte = prov.cerca(CriteriRicerca("Roma", budget_max=100, limite=5))
        self.assertEqual([p.titolo for p in proposte], ["Trullo"])

    def test_ordine_per_punteggio(self):
        prov = RicercaTavolaVIP(self.db)
        proposte = prov.cerca(CriteriRicerca("Roma", limite=5))
        self.assertEqual([p.titolo for p in proposte], ["Trullo", "Loft"])  # 9.0 > 7.0

    def test_nessun_risultato(self):
        prov = RicercaTavolaVIP(self.db)
        self.assertEqual(prov.cerca(CriteriRicerca("Napoli")), [])

    def test_end_to_end_protetto(self):
        m = MotoreRicercaProtetto(RicercaTavolaVIP(self.db))
        r = m.cerca(CriteriRicerca("Milano", limite=5))
        self.assertTrue(r.ok)
        self.assertEqual([p.titolo for p in r.proposte], ["Villa"])


class TestOrchestrazione(unittest.TestCase):

    @staticmethod
    def _fn(prompt):
        msg = prompt.split("Messaggio:")[-1].lower()
        return "ricerca_alloggio" if ("alloggio" in msg or "casa" in msg) else "saluto"

    def test_intento_ricerca_proposte_reali(self):
        ag = AgenteIA(StubLLMProvider(self._fn))
        self.addCleanup(ag.stop)
        m = MotoreRicercaProtetto(RicercaStub(_DATI))
        e = gestisci_richiesta_alloggio(ag, m, "cerco casa a Roma",
                                        CriteriRicerca("Roma", budget_max=100))
        self.assertEqual(e.intento, Intento.RICERCA_ALLOGGIO)
        self.assertEqual(len(e.proposte), 1)
        self.assertIn("Trullo", e.risposta)

    def test_intento_non_ricerca_usa_agente(self):
        ag = AgenteIA(StubLLMProvider(self._fn))
        self.addCleanup(ag.stop)
        m = MotoreRicercaProtetto(RicercaStub(_DATI))
        e = gestisci_richiesta_alloggio(ag, m, "ciao", CriteriRicerca())
        self.assertEqual(e.intento, Intento.SALUTO)
        self.assertEqual(e.proposte, [])

    def test_motore_giu_non_propaga(self):
        ag = AgenteIA(StubLLMProvider(self._fn))
        self.addCleanup(ag.stop)
        m = MotoreRicercaProtetto(RicercaStub(fail=True))
        e = gestisci_richiesta_alloggio(ag, m, "cerco casa", CriteriRicerca("Roma"))
        self.assertEqual(e.intento, Intento.RICERCA_ALLOGGIO)
        self.assertEqual(e.proposte, [])     # isolamento: nessun crash
        self.assertIn("non ho trovato", e.risposta.lower())


if __name__ == "__main__":
    unittest.main()
