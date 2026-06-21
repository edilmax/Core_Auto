"""
Test di Persistenza durevole + metriche del funnel (fase52). Store SQLite drop-in
per fase51, metriche aggregate (conversion rate, guasti per stadio), durevolezza
cross-connessione, estrazione difensiva, integrazione con scheduler/orchestratore,
concorrenza, fuzzing.
"""
import os
import random
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from fase52_persistenza_metriche import (
    StoreCicliSQLite, MetricheFunnel, MetricheStadio, riepiloga,
    crea_store_sqlite)


# ─────────────────────────────────────────────────────────────────────────────
# Fake ReportCiclo / EsitoStadio (forma reale fase50) + EsitoConversione (fase49)
# ─────────────────────────────────────────────────────────────────────────────
class _EsitoConv:
    def __init__(self, ok): self.ok = ok


class _Stadio:
    def __init__(self, nome, ok, errore="", risultato=None):
        self.nome = nome; self.ok = ok; self.errore = errore; self.risultato = risultato


class _Report:
    def __init__(self, stadi, abilitato=True):
        self.abilitato = abilitato; self.stadi = tuple(stadi)
    @property
    def ok_totale(self):
        return self.abilitato and all(s.ok for s in self.stadi)


def _rep(esplora=True, conversione=None):
    """conversione: None=assente, True/False=esito interno EsitoConversione.ok."""
    stadi = [_Stadio("esplora", esplora, "" if esplora else "X: boom")]
    if conversione is not None:
        stadi.append(_Stadio("conversione", True, risultato=_EsitoConv(conversione)))
    return _Report(stadi)


# ─────────────────────────────────────────────────────────────────────────────
class TestAppendConteggio(unittest.TestCase):
    def setUp(self):
        self.store = crea_store_sqlite(":memory:")

    def test_append_incrementa(self):
        self.assertEqual(self.store.conteggio(), 0)
        self.store.append(_rep())
        self.store.append(_rep())
        self.assertEqual(self.store.conteggio(), 2)

    def test_drop_in_interfaccia(self):
        # ha l'interfaccia di StoreCicli (append + conteggio) attesa da fase51
        self.assertTrue(hasattr(self.store, "append"))
        self.assertTrue(hasattr(self.store, "conteggio"))


class TestMetriche(unittest.TestCase):
    def setUp(self):
        self.store = crea_store_sqlite(":memory:")

    def test_store_vuoto(self):
        m = self.store.metriche()
        self.assertEqual(m.cicli_totali, 0)
        self.assertEqual(m.conversion_rate, 0.0)
        self.assertEqual(m.per_stadio, {})

    def test_cicli_ok_contati(self):
        self.store.append(_rep(esplora=True))      # ok_totale True
        self.store.append(_rep(esplora=False))     # ok_totale False
        m = self.store.metriche()
        self.assertEqual(m.cicli_totali, 2)
        self.assertEqual(m.cicli_ok, 1)

    def test_breakdown_per_stadio(self):
        self.store.append(_rep(esplora=True))
        self.store.append(_rep(esplora=False))
        self.store.append(_rep(esplora=False))
        st = self.store.metriche().per_stadio["esplora"]
        self.assertEqual(st.eseguiti, 3)
        self.assertEqual(st.falliti, 2)
        self.assertEqual(st.ok, 1)

    def test_conversion_rate(self):
        self.store.append(_rep(conversione=True))
        self.store.append(_rep(conversione=True))
        self.store.append(_rep(conversione=False))
        self.store.append(_rep(conversione=None))   # nessun tentativo di conversione
        m = self.store.metriche()
        self.assertEqual(m.conversioni_tentate, 3)
        self.assertEqual(m.conversioni_riuscite, 2)
        self.assertAlmostEqual(m.conversion_rate, 2 / 3)


class TestDurevolezza(unittest.TestCase):
    def test_persiste_cross_connessione(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            s1 = StoreCicliSQLite(lambda: sqlite3.connect(path))
            s1.append(_rep(conversione=True))
            s1.append(_rep(esplora=False))
            # NUOVO store sullo stesso file: i dati ci sono ancora
            s2 = StoreCicliSQLite(lambda: sqlite3.connect(path))
            self.assertEqual(s2.conteggio(), 2)
            self.assertEqual(s2.metriche().conversioni_riuscite, 1)
        finally:
            for ext in ("", "-wal", "-shm"):
                try: os.remove(path + ext)
                except OSError: pass

    def test_schema_idempotente(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            StoreCicliSQLite(lambda: sqlite3.connect(path))
            s = StoreCicliSQLite(lambda: sqlite3.connect(path))  # re-init non rompe
            s.append(_rep())
            self.assertEqual(s.conteggio(), 1)
        finally:
            for ext in ("", "-wal", "-shm"):
                try: os.remove(path + ext)
                except OSError: pass


class TestRiepilogoDifensivo(unittest.TestCase):
    def test_report_minimale_non_crasha(self):
        class Vuoto: pass
        r = riepiloga(Vuoto())                       # nessun attributo
        self.assertEqual(r.n_stadi, 0)
        self.assertIsNone(r.conversione_riuscita)

    def test_append_report_malformato(self):
        class Strano:
            abilitato = True
            stadi = None                             # non iterabile-utile
        store = crea_store_sqlite(":memory:")
        store.append(Strano())                       # non deve sollevare
        self.assertEqual(store.conteggio(), 1)

    def test_conversione_senza_esito_interno(self):
        # stadio conversione ok ma risultato senza .ok -> considerato riuscito
        rep = _Report([_Stadio("conversione", True, risultato=object())])
        store = crea_store_sqlite(":memory:")
        store.append(rep)
        self.assertEqual(store.metriche().conversioni_riuscite, 1)


class TestIntegrazioneScheduler(unittest.TestCase):
    def test_store_sqlite_dentro_lo_scheduler(self):
        from fase50_orchestratore import crea_orchestratore
        from fase51_scheduler import crea_scheduler

        class StubPonte:
            def aggancia(self, c): return _EsitoConv(True)

        orch = crea_orchestratore(ponte=StubPonte(), abilitato=True)
        store = crea_store_sqlite(":memory:")
        sched = crea_scheduler(orch, store=store, abilitato=True)
        sched.esegui([{"conversione": {"id": i}} for i in range(5)])
        m = store.metriche()
        self.assertEqual(m.cicli_totali, 5)
        self.assertEqual(m.conversioni_riuscite, 5)


class TestConcorrenza(unittest.TestCase):
    def test_append_concorrenti_su_file(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            store = StoreCicliSQLite(lambda: sqlite3.connect(path, timeout=30))
            def job(i):
                store.append(_rep(esplora=(i % 2 == 0), conversione=(i % 3 == 0)))
            with ThreadPoolExecutor(max_workers=16) as ex:
                list(ex.map(job, range(200)))
            self.assertEqual(store.conteggio(), 200)
            m = store.metriche()
            self.assertEqual(m.per_stadio["esplora"].eseguiti, 200)
        finally:
            for ext in ("", "-wal", "-shm"):
                try: os.remove(path + ext)
                except OSError: pass


class TestFuzzing(unittest.TestCase):
    def test_fuzz_invarianti(self):
        rnd = random.Random(52)
        for _ in range(300):
            store = crea_store_sqlite(":memory:")
            n = rnd.randint(0, 40)
            attesi_conv_tent = attesi_conv_ok = 0
            for _ in range(n):
                conv = rnd.choice([None, True, False])
                store.append(_rep(esplora=rnd.random() < 0.7, conversione=conv))
                if conv is not None:
                    attesi_conv_tent += 1
                    attesi_conv_ok += int(conv)
            m = store.metriche()
            self.assertEqual(m.cicli_totali, n)
            self.assertLessEqual(m.cicli_ok, m.cicli_totali)
            self.assertEqual(m.conversioni_tentate, attesi_conv_tent)
            self.assertEqual(m.conversioni_riuscite, attesi_conv_ok)
            self.assertLessEqual(m.conversioni_riuscite, m.conversioni_tentate)
            if n and "esplora" in m.per_stadio:
                self.assertEqual(m.per_stadio["esplora"].eseguiti, n)


if __name__ == "__main__":
    unittest.main()
