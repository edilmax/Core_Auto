#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test FASE 10 - Dashboard finanziaria.

Test di integrazione via AssistenteGestionale su DB temporaneo. Dove serve un
escrow si costruisce la catena prenotazione -> pagamento_split -> escrow; gli
stati escrow si forzano via SQL diretto per un controllo preciso delle metriche.

Esecuzione:  python -m unittest test_fase10_dashboard -v
"""

import datetime
import io
import tempfile
import unittest
from contextlib import redirect_stdout

import assistente_gestionale as ag
from test_assistente_gestionale import config_di_prova


class TestFase10Dashboard(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config = config_di_prova(self._tmp.name)
        with redirect_stdout(io.StringIO()):
            self.ass = ag.AssistenteGestionale(config=self.config)
        self.db = self.ass.db
        self.dash = self.ass.dashboard_manager

    def tearDown(self):
        self._tmp.cleanup()

    def _crea_catena(self, importo=100000, commissione=10000, quota=90000):
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
            prenotazione_id, importo, commissione, quota)
        escrow_id = self.ass.escrow_manager.inizializza_escrow(pagamento_id)
        return prenotazione_id, pagamento_id, escrow_id

    def _forza_stato(self, escrow_id, stato):
        conn = self.db.connessione()
        try:
            conn.execute("UPDATE escrow_fondi SET stato = ? WHERE id = ?",
                         (stato, escrow_id))
            conn.commit()
        finally:
            conn.close()

    def test_dashboard_db_vuoto(self):
        m = self.dash.get_riepilogo_finanziario()
        self.assertEqual(m.commissioni_nette, 0)
        self.assertEqual(m.fondi_partner_bloccati, 0)
        self.assertEqual(m.escrow_in_disputa, 0)
        self.assertEqual(m.notifiche_non_lette, 0)

    def test_dashboard_fondi_bloccati(self):
        _, _, escrow = self._crea_catena(quota=90000)  # 900 EUR in centesimi
        # Stato 'bloccato' (iniziale): quota partner conteggiata, commissioni 0.
        m = self.dash.get_riepilogo_finanziario()
        self.assertEqual(m.fondi_partner_bloccati, 90000)
        self.assertEqual(m.commissioni_nette, 0)
        # Stato 'DA_APPROVARE_ADMIN': resta tra i fondi bloccati.
        self._forza_stato(escrow, "DA_APPROVARE_ADMIN")
        m2 = self.dash.get_riepilogo_finanziario()
        self.assertEqual(m2.fondi_partner_bloccati, 90000)
        self.assertEqual(m2.commissioni_nette, 0)

    def test_dashboard_commissioni_incassate(self):
        _, _, escrow = self._crea_catena(commissione=10000, quota=90000)
        self._forza_stato(escrow, "DA_APPROVARE_ADMIN")
        self.assertTrue(self.ass.escrow_manager.approva_sblocco_admin(escrow))
        m = self.dash.get_riepilogo_finanziario()
        self.assertEqual(m.commissioni_nette, 10000)
        self.assertEqual(m.fondi_partner_bloccati, 0)

    def test_dashboard_allarmi_dispute(self):
        _, _, escrow = self._crea_catena()
        self._forza_stato(escrow, "DISPUTA")
        self.ass.notifiche_manager.crea_notifica("ALERT_A", "prima")
        self.ass.notifiche_manager.crea_notifica("ALERT_B", "seconda")
        m = self.dash.get_riepilogo_finanziario()
        self.assertEqual(m.escrow_in_disputa, 1)
        self.assertEqual(m.notifiche_non_lette, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
