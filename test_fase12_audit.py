#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test FASE 12 - Audit log immutabile.

Verifica scrittura/lettura tramite AuditManager e l'immutabilita' garantita dai
trigger SQL (UPDATE/DELETE su audit_logs devono essere respinti).

Esecuzione:  python -m unittest test_fase12_audit -v
"""

import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout

import assistente_gestionale as ag
from test_assistente_gestionale import config_di_prova


class TestFase12Audit(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config = config_di_prova(self._tmp.name)
        with redirect_stdout(io.StringIO()):
            self.gestionale = ag.AssistenteGestionale(config=self.config)
        self.audit_manager = self.gestionale.audit_manager

    def tearDown(self):
        self._tmp.cleanup()

    def test_registra_e_leggi(self):
        dettagli = {"importo": 100, "valuta": "EUR", "nota": "primo log"}
        log_id = self.audit_manager.registra_azione(
            "ESCROW", 42, ag.AzioneAudit.ESCROW_CREATO, dettagli,
            utente_id=7, utente_tipo="ADMIN", ip_address="127.0.0.1",
            session_id="sess-1")
        self.assertGreater(log_id, 0)

        crono = self.audit_manager.get_cronologia_entita("ESCROW", 42)
        self.assertEqual(len(crono), 1)
        rec = crono[0]
        self.assertIsInstance(rec, ag.AuditRecord)
        self.assertEqual(rec.entita_tipo, "ESCROW")
        self.assertEqual(rec.entita_id, 42)
        self.assertEqual(rec.azione, "ESCROW_CREATO")
        self.assertEqual(json.loads(rec.dettagli), dettagli)
        self.assertEqual(rec.utente_id, 7)
        self.assertEqual(rec.utente_tipo, "ADMIN")
        self.assertIsNotNone(rec.data_creazione)

    def test_immutabilita_update(self):
        log_id = self.audit_manager.registra_azione(
            "ESCROW", 1, ag.AzioneAudit.ESCROW_CREATO, {"x": 1})
        with self.assertRaises(sqlite3.Error):
            self.gestionale.db.esegui_query(
                "UPDATE audit_logs SET azione = 'MANOMESSO' WHERE id = ?",
                (log_id,))
        # Il record e' rimasto invariato.
        rec = self.audit_manager.get_cronologia_entita("ESCROW", 1)[0]
        self.assertEqual(rec.azione, "ESCROW_CREATO")

    def test_immutabilita_delete(self):
        log_id = self.audit_manager.registra_azione(
            "ESCROW", 2, ag.AzioneAudit.ESCROW_CREATO, {"x": 2})
        with self.assertRaises(sqlite3.Error):
            self.gestionale.db.esegui_query(
                "DELETE FROM audit_logs WHERE id = ?", (log_id,))
        # Il record esiste ancora.
        self.assertEqual(len(self.audit_manager.get_cronologia_entita("ESCROW", 2)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
