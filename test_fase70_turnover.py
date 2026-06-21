"""
Test Fase 70 - Automated Turnover.

Copre: creazione con finestra + idempotenza, date invalide, assegna/completa (in tempo
e in ritardo), gate agibilita' (pronto/non pronto/assente), allarme ritardi (a_rischio
+ segnala isolato), robustezza, stress concorrente. Orologio iniettato.
"""
import os
import shutil
import tempfile
import threading
import unittest

from fase70_turnover import (
    EsitoTurnover, GestoreTurnover, _epoch_da_data_ora, crea_gestore_turnover,
)

# finestra default: checkout 11:00, checkin successivo 15:00
DA = _epoch_da_data_ora("2026-09-10", 11)
A = _epoch_da_data_ora("2026-09-10", 15)        # stesso giorno, back-to-back


class TestCreazione(unittest.TestCase):
    def setUp(self):
        self.g = crea_gestore_turnover()

    def test_crea_con_finestra(self):
        tid = self.g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        st = self.g.stato_turnover(tid)
        self.assertEqual(st["finestra_da"], DA)
        self.assertEqual(st["finestra_a"], A)
        self.assertEqual(st["stato"], "da_fare")

    def test_idempotente(self):
        a = self.g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        b = self.g.crea_turnover("casa", "2026-09-10", "2026-09-12")
        self.assertEqual(a, b)                  # stesso (alloggio, checkout) -> stesso task

    def test_senza_prossimo_checkin(self):
        tid = self.g.crea_turnover("casa", "2026-09-10")
        self.assertIsNone(self.g.stato_turnover(tid)["finestra_a"])

    def test_date_invalide(self):
        self.assertIsNone(self.g.crea_turnover("casa", "non-data"))
        # prossimo check-in prima del checkout -> invalido
        self.assertIsNone(self.g.crea_turnover("casa", "2026-09-10", "2026-09-09"))
        self.assertIsNone(self.g.crea_turnover("", "2026-09-10"))


class TestCompletamento(unittest.TestCase):
    def test_pronto_in_tempo(self):
        g = crea_gestore_turnover(orologio=lambda: DA + 3600)   # 1h dopo checkout, < A
        tid = g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        self.assertTrue(g.assegna(tid, "addetto1").ok)
        e = g.completa(tid)
        self.assertEqual(e.stato, "pronto")

    def test_pronto_in_ritardo(self):
        g = crea_gestore_turnover(orologio=lambda: A + 3600)    # oltre la finestra
        tid = g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        g.assegna(tid, "addetto1")
        e = g.completa(tid)
        self.assertEqual(e.stato, "pronto_in_ritardo")

    def test_completa_idempotente(self):
        g = crea_gestore_turnover(orologio=lambda: DA + 3600)
        tid = g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        g.completa(tid)
        e = g.completa(tid)
        self.assertTrue(e.ok)
        self.assertEqual(e.stato, "pronto")

    def test_assegna_inesistente(self):
        g = crea_gestore_turnover()
        self.assertFalse(g.assegna(99999, "x").ok)


class TestAgibilita(unittest.TestCase):
    def test_non_pronto_blocca(self):
        g = crea_gestore_turnover()
        g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        # turnover 'da_fare' -> check-in del 2026-09-10 NON agibile (fail-closed)
        self.assertFalse(g.agibile("casa", "2026-09-10"))

    def test_pronto_agibile(self):
        g = crea_gestore_turnover(orologio=lambda: DA + 3600)
        tid = g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        g.completa(tid)
        self.assertTrue(g.agibile("casa", "2026-09-10"))

    def test_nessun_turnover_agibile(self):
        g = crea_gestore_turnover()
        # nessuna pulizia schedulata per quel check-in -> agibile
        self.assertTrue(g.agibile("casa", "2026-12-25"))

    def test_in_ritardo_resta_agibile(self):
        g = crea_gestore_turnover(orologio=lambda: A + 3600)
        tid = g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        g.completa(tid)                          # pronto_in_ritardo
        self.assertTrue(g.agibile("casa", "2026-09-10"))   # pulito, anche se tardi


class TestAllarmeRitardi(unittest.TestCase):
    def test_a_rischio(self):
        g = crea_gestore_turnover(orologio=lambda: A + 7200)   # finestra chiusa
        g.crea_turnover("casa", "2026-09-10", "2026-09-10")    # 'da_fare', in ritardo
        rischi = g.a_rischio()
        self.assertEqual(len(rischi), 1)
        self.assertEqual(rischi[0]["alloggio_id"], "casa")

    def test_non_a_rischio_se_pronto(self):
        g = crea_gestore_turnover(orologio=lambda: A + 7200)
        tid = g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        g.completa(tid)
        self.assertEqual(g.a_rischio(), [])

    def test_segnala_isolato(self):
        ricevute = []
        g = crea_gestore_turnover(orologio=lambda: A + 7200,
                                  notificatore=ricevute.append)
        g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        n = g.segnala_ritardi()
        self.assertEqual(n, 1)
        self.assertEqual(ricevute[0]["tipo"], "turnover_a_rischio")

    def test_segnala_notificatore_che_solleva(self):
        def boom(_):
            raise RuntimeError("canale giu'")
        g = crea_gestore_turnover(orologio=lambda: A + 7200, notificatore=boom)
        g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        self.assertEqual(g.segnala_ritardi(), 1)   # non si schianta


class TestRobustezza(unittest.TestCase):
    def test_mai_solleva(self):
        g = crea_gestore_turnover()
        for bad in (None, 123, ""):
            try:
                g.crea_turnover(bad, bad, bad)
                g.assegna(bad, bad)
                g.completa(bad)
                g.agibile(bad, bad)
                g.a_rischio(ora=bad)
            except Exception as e:  # pragma: no cover
                self.fail(f"sollevato su {bad!r}: {e}")


class TestStress(unittest.TestCase):
    def test_crea_concorrenti_10x(self):
        for rip in range(10):
            d = tempfile.mkdtemp()
            try:
                g = crea_gestore_turnover(os.path.join(d, f"t{rip}.db"))
                errori = []
                lock = threading.Lock()

                def worker(i):
                    try:
                        tid = g.crea_turnover("casa%d" % i, "2026-09-10", "2026-09-10")
                        with lock:
                            errori.append(tid is not None)
                    except Exception as ex:  # pragma: no cover
                        with lock:
                            errori.append(ex)

                th = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
                for t in th:
                    t.start()
                for t in th:
                    t.join()
                self.assertTrue(all(x is True for x in errori))
            finally:
                shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
