#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test FASE 8 - Motore di feedback (human-in-the-loop).

Test di integrazione via AssistenteGestionale su DB temporaneo. Per ogni caso
si costruisce la catena reale prenotazione -> pagamento_split -> escrow, cosi'
le foreign key sono soddisfatte. Principio verificato: il sistema non sblocca
mai i fondi da solo; solo approva_sblocco_admin converte DA_APPROVARE_ADMIN ->
sbloccato.

Esecuzione:  python -m unittest test_fase8_feedback -v
"""

import datetime
import io
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout

import assistente_gestionale as ag
from test_assistente_gestionale import config_di_prova


class TestFase8Feedback(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config = config_di_prova(self._tmp.name)
        with redirect_stdout(io.StringIO()):
            self.ass = ag.AssistenteGestionale(config=self.config)
        self.db = self.ass.db
        self.split_manager = self.ass.split_manager
        self.escrow_manager = self.ass.escrow_manager
        self.feedback = self.ass.feedback_manager

    def tearDown(self):
        self._tmp.cleanup()

    def _crea_catena(self, check_out: str = "2026-07-05"):
        """Crea prenotazione -> pagamento -> escrow. Restituisce gli id."""
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
            prenotazione_id, 100000, 10000, 90000)  # centesimi: 1000/100/900 EUR
        escrow_id = self.escrow_manager.inizializza_escrow(pagamento_id)
        return prenotazione_id, pagamento_id, escrow_id

    def _escrow(self, escrow_id: int):
        conn = self.db.connessione()
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute("SELECT * FROM escrow_fondi WHERE id = ?",
                                (escrow_id,)).fetchone()
        finally:
            conn.close()

    def _recensioni(self, prenotazione_id: int):
        conn = self.db.connessione()
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute("SELECT * FROM recensioni_clienti WHERE "
                                "prenotazione_id = ?", (prenotazione_id,)).fetchall()
        finally:
            conn.close()

    def test_recensione_positiva_attesa_admin(self):
        pren, _, escrow = self._crea_catena()
        res = self.feedback.inserisci_recensione(pren, escrow, "POSITIVO",
                                                 "Ottimo servizio")
        self.assertEqual(res["escrow_stato"], "DA_APPROVARE_ADMIN")
        self.assertEqual(self._escrow(escrow)["stato"], "DA_APPROVARE_ADMIN")

    def test_recensione_negativa_disputa(self):
        pren, _, escrow = self._crea_catena()
        res = self.feedback.inserisci_recensione(pren, escrow, "NEGATIVO",
                                                 "Pessima esperienza")
        self.assertEqual(res["escrow_stato"], "DISPUTA")
        self.assertEqual(self._escrow(escrow)["stato"], "DISPUTA")

    def test_silenzio_assenso_attesa_admin(self):
        # check_out 3 giorni fa (> 48h), nessuna recensione.
        scaduto = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
        pren, _, escrow = self._crea_catena(check_out=scaduto)
        processati = self.feedback.esegui_silenzio_assenso(ore_limite=48)
        self.assertEqual(processati, 1)
        recensioni = self._recensioni(pren)
        self.assertEqual(len(recensioni), 1)
        self.assertEqual(recensioni[0]["esito"], "SILENZIO_ASSENSO")
        self.assertEqual(self._escrow(escrow)["stato"], "DA_APPROVARE_ADMIN")

    def test_approva_sblocco_admin_successo(self):
        pren, _, escrow = self._crea_catena()
        self.feedback.inserisci_recensione(pren, escrow, "POSITIVO", "ok")
        self.assertTrue(self.escrow_manager.approva_sblocco_admin(escrow))
        riga = self._escrow(escrow)
        self.assertEqual(riga["stato"], "sbloccato")
        self.assertIsNotNone(riga["data_sblocco"])

    def test_approva_sblocco_admin_fallimento(self):
        # Escrow 'bloccato': l'admin NON puo' sbloccare (solo da DA_APPROVARE_ADMIN).
        _, _, escrow_bloccato = self._crea_catena()
        self.assertFalse(self.escrow_manager.approva_sblocco_admin(escrow_bloccato))
        self.assertEqual(self._escrow(escrow_bloccato)["stato"], "bloccato")
        # Escrow in 'DISPUTA': neppure qui si sblocca.
        pren2, _, escrow_disputa = self._crea_catena()
        self.feedback.inserisci_recensione(pren2, escrow_disputa, "NEGATIVO", "ko")
        self.assertFalse(self.escrow_manager.approva_sblocco_admin(escrow_disputa))
        self.assertEqual(self._escrow(escrow_disputa)["stato"], "DISPUTA")


if __name__ == "__main__":
    unittest.main(verbosity=2)
