#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test FASE 9 - Notifiche admin (CRUD + generazione dai flussi di feedback).

Test di integrazione via AssistenteGestionale su DB temporaneo. Dove serve un
escrow si costruisce la catena reale prenotazione -> pagamento_split -> escrow.

Esecuzione:  python -m unittest test_fase9_notifiche -v
"""

import datetime
import io
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout

import assistente_gestionale as ag
from test_assistente_gestionale import config_di_prova


class TestFase9Notifiche(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config = config_di_prova(self._tmp.name)
        with redirect_stdout(io.StringIO()):
            self.ass = ag.AssistenteGestionale(config=self.config)
        self.db = self.ass.db
        self.split_manager = self.ass.split_manager
        self.escrow_manager = self.ass.escrow_manager
        self.feedback = self.ass.feedback_manager
        self.notifiche = self.ass.notifiche_manager

    def tearDown(self):
        self._tmp.cleanup()

    def _crea_catena(self, check_out: str = "2026-07-05"):
        conn = self.db.connessione()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO prenotazioni (candidato_url, check_in, check_out, "
                "stato, data_creazione) VALUES (NULL, ?, ?, 'occupato', ?)",
                ("2026-07-01", check_out,
                 datetime.datetime.now().isoformat(timespec="seconds")))
            conn.commit()
            prenotazione_id = cur.lastrowid
        finally:
            conn.close()
        pagamento_id = self.split_manager.registra_pagamento(
            prenotazione_id, 1000.0, 100.0, 900.0)
        escrow_id = self.escrow_manager.inizializza_escrow(pagamento_id)
        return prenotazione_id, pagamento_id, escrow_id

    def _notifiche(self):
        conn = self.db.connessione()
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute("SELECT * FROM notifiche_admin "
                                "ORDER BY id").fetchall()
        finally:
            conn.close()

    def test_crud_notifiche(self):
        n1 = self.notifiche.crea_notifica("TEST", "prima")
        n2 = self.notifiche.crea_notifica("TEST", "seconda")
        self.assertGreater(n2, n1)
        non_lette = self.notifiche.get_notifiche_non_lette()
        self.assertEqual(len(non_lette), 2)
        # Ordinamento decrescente: la piu' recente (id maggiore) per prima.
        self.assertEqual(non_lette[0]["id"], n2)
        self.assertGreater(non_lette[0]["id"], non_lette[1]["id"])
        # segna_come_letta rimuove dalla lista delle non lette.
        self.assertTrue(self.notifiche.segna_come_letta(n1))
        rimaste = self.notifiche.get_notifiche_non_lette()
        self.assertEqual(len(rimaste), 1)
        self.assertEqual(rimaste[0]["id"], n2)
        # id inesistente -> False
        self.assertFalse(self.notifiche.segna_come_letta(999999))

    def test_notifica_recensione_positiva(self):
        pren, _, escrow = self._crea_catena()
        self.feedback.inserisci_recensione(pren, escrow, "POSITIVO", "ottimo")
        righe = self._notifiche()
        self.assertEqual(len(righe), 1)
        self.assertEqual(righe[0]["tipo_alert"], "SBLOCCO_RICHIESTO")
        self.assertEqual(righe[0]["escrow_id"], escrow)
        self.assertEqual(righe[0]["letto"], 0)

    def test_notifica_recensione_negativa(self):
        pren, _, escrow = self._crea_catena()
        self.feedback.inserisci_recensione(pren, escrow, "NEGATIVO", "pessimo")
        righe = self._notifiche()
        self.assertEqual(len(righe), 1)
        self.assertEqual(righe[0]["tipo_alert"], "DISPUTA_APERTA")
        self.assertEqual(righe[0]["escrow_id"], escrow)

    def test_notifica_silenzio_assenso(self):
        scaduto = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
        _, _, escrow = self._crea_catena(check_out=scaduto)
        processati = self.feedback.esegui_silenzio_assenso(ore_limite=48)
        self.assertEqual(processati, 1)
        righe = self._notifiche()
        # UNA sola notifica, di tipo SILENZIO_ASSENSO (niente SBLOCCO_RICHIESTO spurio).
        self.assertEqual(len(righe), 1)
        self.assertEqual(righe[0]["tipo_alert"], "SILENZIO_ASSENSO")
        self.assertEqual(righe[0]["escrow_id"], escrow)


if __name__ == "__main__":
    unittest.main(verbosity=2)
