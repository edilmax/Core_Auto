# -*- coding: utf-8 -*-
"""Guardia MIGRAZIONE RETROATTIVA della valuta nei pagamenti agli host (fase131).

IL DIFETTO: fino al 2026-07-29 la riga di payout si scriveva con `valuta.upper()` SENZA strip,
quindi ' EUR ' invece di 'EUR'. Il fix di `_norm_valuta` ha corretto solo le scritture NUOVE:
le righe GIA' IN ARCHIVIO restano sporche. `riepilogo` raggruppa sul valore grezzo letto dal
file, quindi quelle righe finiscono sotto una chiave che `da_pagare`/`elenca` non cercano mai:
**soldi dovuti all'host invisibili e bonifico mai fatto**.

LA CORREZIONE (una istruzione SQL in `inizializza_schema`, idempotente):
    UPDATE payout SET valuta=UPPER(TRIM(valuta)) WHERE valuta<>UPPER(TRIM(valuta))
Su un archivio pulito tocca ZERO righe.

VISTO ROSSO: togliendo quella riga da fase131_payout_dashboard.py questi test falliscono.
"""
import os
import shutil
import sqlite3
import tempfile
import unittest

from fase131_payout_dashboard import crea_payout_dashboard

HOST = "h_storico"


class TestPayoutValutaStorica(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.db = os.path.join(self.d, "payout.db")
        con = sqlite3.connect(self.db)
        with con:      # archivio scritto dal CODICE VECCHIO: valuta con spazi
            con.execute("""CREATE TABLE IF NOT EXISTS payout (
                prenotazione_id TEXT PRIMARY KEY, host_id TEXT NOT NULL,
                minori INTEGER NOT NULL, valuta TEXT NOT NULL,
                stato TEXT NOT NULL, ts INTEGER NOT NULL)""")
            con.executemany(
                "INSERT INTO payout (prenotazione_id, host_id, minori, valuta, stato, ts) "
                "VALUES (?,?,?,?,?,?)",
                [("rif_vecchio_1", HOST, 9900, " EUR ", "maturato", 1750000000),
                 ("rif_vecchio_2", HOST, 4200, "eur",   "maturato", 1750000100),
                 ("rif_sano",      HOST, 3000, "EUR",   "maturato", 1750000200)])
        con.close()

    def _valute_in_archivio(self):
        con = sqlite3.connect(self.db)
        try:
            return sorted(r[0] for r in con.execute("SELECT valuta FROM payout"))
        finally:
            con.close()

    # ── LA PROVA CHE CONTA ──────────────────────────────────────────────────
    def test_le_righe_storiche_diventano_visibili(self):
        """Prima: 9900 e 4200 invisibili sotto chiavi ' EUR ' e 'eur'. Dopo: tutto in 'EUR'."""
        d = crea_payout_dashboard(self.db)
        d.inizializza_schema()                       # <- qui avviene la migrazione
        righe = d.elenca(HOST, valuta="EUR")
        self.assertEqual(len(righe), 3,
                         "righe storiche ancora invisibili a elenca(): %s" % righe)
        self.assertEqual(sum(int(r["minori"]) for r in righe), 9900 + 4200 + 3000)

    def test_l_archivio_e_ripulito_sul_disco(self):
        d = crea_payout_dashboard(self.db)
        d.inizializza_schema()
        self.assertEqual(self._valute_in_archivio(), ["EUR", "EUR", "EUR"])

    def test_nessuna_riga_persa_nessun_importo_alterato(self):
        """La migrazione tocca SOLO la valuta: identificativi, importi e stati restano."""
        d = crea_payout_dashboard(self.db)
        d.inizializza_schema()
        con = sqlite3.connect(self.db)
        try:
            dati = {r[0]: (r[1], r[2], r[3]) for r in con.execute(
                "SELECT prenotazione_id, host_id, minori, stato FROM payout")}
        finally:
            con.close()
        self.assertEqual(dati, {"rif_vecchio_1": (HOST, 9900, "maturato"),
                                "rif_vecchio_2": (HOST, 4200, "maturato"),
                                "rif_sano": (HOST, 3000, "maturato")})

    def test_riaprire_non_tocca_piu_nulla(self):
        """Idempotente: al secondo avvio l'UPDATE non ha piu' righe da correggere."""
        crea_payout_dashboard(self.db).inizializza_schema()
        prima = self._valute_in_archivio()
        crea_payout_dashboard(self.db).inizializza_schema()
        self.assertEqual(self._valute_in_archivio(), prima)

    def test_archivio_nuovo_zero_righe_toccate(self):
        """Su un archivio pulito la migrazione e' un no-op: nessun effetto collaterale."""
        db2 = os.path.join(self.d, "nuovo.db")
        d = crea_payout_dashboard(db2)
        d.inizializza_schema()
        d.registra_in_attesa("rif_nuovo", HOST, 5000, "EUR")
        d.inizializza_schema()                        # secondo avvio
        righe = d.elenca(HOST, valuta="EUR")
        self.assertEqual([(r["prenotazione_id"], int(r["minori"])) for r in righe],
                         [("rif_nuovo", 5000)])


if __name__ == "__main__":
    unittest.main()
