"""Payout 'in_attesa': una prenotazione non pagata NON conta come guadagno finché non paga.
Pagata -> 'maturato'; hold scaduto -> rimossa. Chiude il bug dei 'guadagni fantasma'."""
import os
import shutil
import sqlite3
import tempfile
import unittest

from fase131_payout_dashboard import PayoutDashboard


class TestPayoutInAttesa(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, "payout.db")
        self.pd = PayoutDashboard(lambda: sqlite3.connect(self.db))
        self.pd.inizializza_schema()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_in_attesa_non_e_maturato(self):
        self.pd.registra_in_attesa("REF1", "host1", 17400, "EUR")
        r = self.pd.riepilogo("host1")
        self.assertEqual(r.get("EUR", {}).get("in_attesa"), 17400)
        self.assertNotIn("maturato", r.get("EUR", {}))     # NON conta come guadagno

    def test_pagamento_promuove_a_maturato(self):
        self.pd.registra_in_attesa("REF2", "host1", 17400, "EUR")
        self.assertTrue(self.pd.aggiorna_stato("REF2", "maturato"))
        r = self.pd.riepilogo("host1")
        self.assertEqual(r.get("EUR", {}).get("maturato"), 17400)
        self.assertNotIn("in_attesa", r.get("EUR", {}))

    def test_hold_scaduto_rimuove_payout(self):
        self.pd.registra_in_attesa("REF3", "host1", 17400, "EUR")
        self.assertTrue(self.pd.rimuovi("REF3"))
        self.assertEqual(self.pd.riepilogo("host1"), {})    # niente guadagno fantasma

    def test_rimuovi_idempotente(self):
        self.assertTrue(self.pd.rimuovi("inesistente"))     # non solleva

    def test_maturato_diretto_resta(self):
        # book senza pagamento online (conferma immediata) -> maturato diretto
        self.pd.registra_maturato("REF4", "host1", 9000, "EUR")
        self.assertEqual(self.pd.riepilogo("host1").get("EUR", {}).get("maturato"), 9000)


if __name__ == "__main__":
    unittest.main()
