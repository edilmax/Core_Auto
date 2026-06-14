#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test FASE 7 - Motore di brokeraggio (split pagamenti, escrow, voucher).

Test di integrazione: usano l'orchestratore AssistenteGestionale (quindi anche
il cablaggio self.split_manager / self.escrow_manager / self.voucher_generator)
su un DB temporaneo. Per le foreign key si crea prima una prenotazione reale
(candidato_url = NULL -> esente da check FK verso candidati).

Esecuzione:  python -m unittest test_fase7_brokeraggio -v
"""

import datetime
import io
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout

import assistente_gestionale as ag
from test_assistente_gestionale import config_di_prova


class TestFase7Brokeraggio(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config = config_di_prova(self._tmp.name)
        with redirect_stdout(io.StringIO()):
            self.ass = ag.AssistenteGestionale(config=self.config)
        self.db = self.ass.db
        self.split_manager = self.ass.split_manager
        self.escrow_manager = self.ass.escrow_manager
        self.voucher_generator = self.ass.voucher_generator
        self.prenotazione_id = self._crea_prenotazione()

    def tearDown(self):
        self._tmp.cleanup()

    def _crea_prenotazione(self) -> int:
        conn = self.db.connessione()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO prenotazioni (candidato_url, check_in, check_out, "
                "stato, data_creazione) VALUES (NULL, ?, ?, 'occupato', ?)",
                ("2026-07-01", "2026-07-05",
                 datetime.datetime.now().isoformat(timespec="seconds")))
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def _query(self, sql, params=()):
        conn = self.db.connessione()
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def test_registra_pagamento_split(self):
        pid = self.split_manager.registra_pagamento(
            self.prenotazione_id, 100000, 10000, 90000)  # centesimi: 1000/100/900 EUR
        self.assertGreater(pid, 0)
        righe = self._query("SELECT * FROM pagamenti_split WHERE id = ?", (pid,))
        self.assertEqual(len(righe), 1)
        r = righe[0]
        self.assertEqual(r["prenotazione_id"], self.prenotazione_id)
        self.assertEqual(r["importo_totale"], 100000)
        self.assertEqual(r["commissione_tavola"], 10000)
        self.assertEqual(r["quota_partner"], 90000)
        self.assertEqual(r["status"], "pending")

    def test_inizializza_escrow(self):
        pid = self.split_manager.registra_pagamento(
            self.prenotazione_id, 50000, 5000, 45000)  # 500/50/450 EUR in centesimi
        eid = self.escrow_manager.inizializza_escrow(pid)
        self.assertGreater(eid, 0)
        righe = self._query(
            "SELECT * FROM escrow_fondi WHERE pagamento_id = ?", (pid,))
        self.assertEqual(len(righe), 1)
        self.assertEqual(righe[0]["stato"], "bloccato")
        self.assertIsNone(righe[0]["data_sblocco"])

    def test_sblocca_fondi_escrow(self):
        pid = self.split_manager.registra_pagamento(
            self.prenotazione_id, 80000, 8000, 72000)  # 800/80/720 EUR in centesimi
        self.escrow_manager.inizializza_escrow(pid)
        self.assertTrue(self.escrow_manager.sblocca_fondi(pid))
        righe = self._query(
            "SELECT stato, data_sblocco FROM escrow_fondi WHERE pagamento_id = ?",
            (pid,))
        self.assertEqual(righe[0]["stato"], "sbloccato")
        self.assertIsNotNone(righe[0]["data_sblocco"])

    def test_emetti_voucher_univoco(self):
        codice = self.voucher_generator.emetti_voucher(self.prenotazione_id)
        self.assertTrue(codice.startswith("TVP-"))
        righe = self._query(
            "SELECT codice_voucher FROM voucher_prenotazioni "
            "WHERE prenotazione_id = ?", (self.prenotazione_id,))
        self.assertEqual(len(righe), 1)
        self.assertEqual(righe[0]["codice_voucher"], codice)

    def test_rollback_su_errore(self):
        # prenotazione_id inesistente -> viola la FK -> IntegrityError + rollback.
        prima = self._query("SELECT COUNT(*) AS n FROM pagamenti_split")[0]["n"]
        with self.assertRaises(sqlite3.IntegrityError):
            self.split_manager.registra_pagamento(999999, 10000, 1000, 9000)
        dopo = self._query("SELECT COUNT(*) AS n FROM pagamenti_split")[0]["n"]
        self.assertEqual(prima, dopo)  # nessuna riga scritta (rollback ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
