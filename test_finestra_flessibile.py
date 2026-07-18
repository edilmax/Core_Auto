# -*- coding: utf-8 -*-
"""CLEAN CODE (audit resilienza comp.3) — funzione PURA finestra_flessibile.

Prima questa logica era inline in _catalogo dentro un 'try/except: _n=0' -> non testabile
in isolamento e, su errore di parsing, disattivava la ricerca flessibile IN SILENZIO.
Estratta a funzione pura, ora è provabile sui bordi (±1 giorno) senza montare il server.
"""
import datetime
import unittest

from fase83_server import finestra_flessibile as ff


class TestFinestraFlessibile(unittest.TestCase):
    def test_caso_valido(self):
        # 2 notti, flex 3 -> range allargato di 3 giorni per lato, n=2
        self.assertEqual(ff("2026-09-10", "2026-09-12", 3),
                         ("2026-09-07", "2026-09-15", 2))

    def test_una_notte_flex_uno(self):
        self.assertEqual(ff("2026-09-10", "2026-09-11", 1),
                         ("2026-09-09", "2026-09-12", 1))

    def test_attraversa_il_mese(self):
        # boundary: il -flex scavalca l'inizio mese
        da, a, n = ff("2026-03-01", "2026-03-03", 2)
        self.assertEqual((da, a, n), ("2026-02-27", "2026-03-05", 2))

    def test_date_invertite_o_uguali_none(self):
        self.assertIsNone(ff("2026-09-12", "2026-09-10", 3))   # co < ci
        self.assertIsNone(ff("2026-09-10", "2026-09-10", 3))   # 0 notti

    def test_flex_non_positivo_none(self):
        self.assertIsNone(ff("2026-09-10", "2026-09-12", 0))
        self.assertIsNone(ff("2026-09-10", "2026-09-12", -1))

    def test_flex_non_intero_o_bool_none(self):
        self.assertIsNone(ff("2026-09-10", "2026-09-12", "3"))
        self.assertIsNone(ff("2026-09-10", "2026-09-12", 3.0))
        self.assertIsNone(ff("2026-09-10", "2026-09-12", True))   # bool NON è un flex valido

    def test_date_non_iso_none_mai_solleva(self):
        # il buco vecchio: un input rotto disattivava la feature in silenzio; ora è None esplicito
        for ci, co in [("oggi", "domani"), ("", ""), (None, None),
                       ("2026-13-40", "2026-09-12"), ("2026/09/10", "2026/09/12")]:
            self.assertIsNone(ff(ci, co, 3), "%r %r doveva dare None" % (ci, co))

    def test_purezza_bordi_coerenti_col_calcolo_diretto(self):
        # equivalenza con l'aritmetica di riferimento su una griglia di casi
        for dci in range(0, 5):
            for notti in range(1, 6):
                for flex in range(1, 8):
                    ci = datetime.date(2026, 6, 1) + datetime.timedelta(days=dci)
                    co = ci + datetime.timedelta(days=notti)
                    da, a, n = ff(ci.isoformat(), co.isoformat(), flex)
                    self.assertEqual(n, notti)
                    self.assertEqual(da, (ci - datetime.timedelta(days=flex)).isoformat())
                    self.assertEqual(a, (co + datetime.timedelta(days=flex)).isoformat())


if __name__ == "__main__":
    unittest.main(verbosity=2)
