#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test FASE 11 - Motore di esportazione dati (report CSV).

Test di integrazione via AssistenteGestionale su DB temporaneo. Il file CSV
generato viene rimosso esplicitamente con os nel tearDown.

Esecuzione:  python -m unittest test_fase11_report -v
"""

import csv
import datetime
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout

import assistente_gestionale as ag
from test_assistente_gestionale import config_di_prova


class TestFase11Report(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config = config_di_prova(self._tmp.name)
        with redirect_stdout(io.StringIO()):
            self.ass = ag.AssistenteGestionale(config=self.config)
        self.db = self.ass.db
        self.report = self.ass.report_manager
        self.csv_path = os.path.join(self._tmp.name, "report_commissioni.csv")

    def tearDown(self):
        # Pulizia esplicita del file CSV temporaneo, poi della cartella.
        if os.path.exists(self.csv_path):
            os.remove(self.csv_path)
        self._tmp.cleanup()

    def _crea_catena(self, commissione=100.0, quota=900.0):
        conn = self.db.connessione()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO prenotazioni (candidato_url, check_in, check_out, "
                "stato, data_creazione) VALUES (NULL, ?, ?, 'occupato', ?)",
                ("2026-07-01", "2026-07-05",
                 datetime.datetime.now().isoformat(timespec="seconds")))
            conn.commit()
            prenotazione_id = cur.lastrowid
        finally:
            conn.close()
        pagamento_id = self.ass.split_manager.registra_pagamento(
            prenotazione_id, 1000.0, commissione, quota)
        escrow_id = self.ass.escrow_manager.inizializza_escrow(pagamento_id)
        return pagamento_id, escrow_id

    def _forza_stato(self, escrow_id, stato):
        conn = self.db.connessione()
        try:
            conn.execute("UPDATE escrow_fondi SET stato = ? WHERE id = ?",
                         (stato, escrow_id))
            conn.commit()
        finally:
            conn.close()

    def _leggi_csv(self):
        with open(self.csv_path, newline="", encoding="utf-8") as f:
            return list(csv.reader(f))

    def test_export_csv_vuoto(self):
        n = self.report.esporta_commissioni_csv(self.csv_path)
        self.assertEqual(n, 0)
        self.assertTrue(os.path.exists(self.csv_path))
        righe = self._leggi_csv()
        self.assertEqual(len(righe), 1)  # solo intestazione
        self.assertEqual(righe[0][0], "ID_Pagamento")

    def test_export_csv_filtraggio(self):
        _, e_bloccato = self._crea_catena()          # resta 'bloccato'
        _, e_disputa = self._crea_catena()
        self._forza_stato(e_disputa, "DISPUTA")
        _, e_sbloccato = self._crea_catena()
        self._forza_stato(e_sbloccato, "sbloccato")
        n = self.report.esporta_commissioni_csv(self.csv_path)
        self.assertEqual(n, 1)  # solo il record sbloccato

    def test_export_csv_dati_corretti(self):
        pagamento_id, escrow = self._crea_catena(commissione=150.0, quota=850.0)
        self._forza_stato(escrow, "sbloccato")
        n = self.report.esporta_commissioni_csv(self.csv_path)
        self.assertEqual(n, 1)
        righe = self._leggi_csv()
        self.assertEqual(len(righe), 2)  # intestazione + 1 record
        dati = righe[1]  # saltata l'intestazione
        self.assertEqual(int(dati[0]), pagamento_id)        # ID_Pagamento
        self.assertEqual(float(dati[2]), 150.0)             # Commissione_Piattaforma
        self.assertEqual(float(dati[3]), 850.0)             # Quota_Partner
        self.assertEqual(dati[4], "sbloccato")              # Stato


if __name__ == "__main__":
    unittest.main(verbosity=2)
