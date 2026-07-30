# -*- coding: utf-8 -*-
"""Guardia CABLAGGIO DEL DEPOSITO CAUZIONALE (fase149) — «costruito e dimenticato».

IL DIFETTO: `fase149_deposito_cauzionale` gestisce le PRE-AUTORIZZAZIONI sulla carta (hold su
denaro vero: si autorizza pre-arrivo, si cattura solo il danno, si rilascia il resto al
check-out) ma non era raggiungibile da NESSUNA parte del prodotto: `crea_deposito_cauzionale`
non veniva mai chiamato, non esisteva un campo `db_deposito` nella configurazione e quindi
nemmeno la riga nel docker-compose. Un modulo pagato e mai usabile — e, peggio, che ci faceva
credere di avere una tutela che non era attiva.

IL CABLAGGIO (4 punti obbligatori, nessuno superfluo):
  · `SistemaCasaVIP.deposito`            → il prodotto lo espone
  · `ConfigCasaVIP.db_deposito`          → si puo' scegliere dove vive l'archivio
  · creazione in `crea_sistema` + schema → nasce e si inizializza all'avvio
  · `DB_DEPOSITO` in main + compose      → in produzione l'archivio e' DUREVOLE (custodisce
                                           hold su carte: se vivesse in RAM, al riavvio si
                                           perderebbe la traccia di soldi bloccati ai clienti)

`capture`/`release` restano NON iniettati di proposito: il passaggio al gestore dei pagamenti
e' una decisione del fondatore, non un effetto collaterale del cablaggio.

VISTO ROSSO: togliendo il blocco di creazione da fase81_bootstrap_casavip.py questi test
falliscono (il sistema non espone il deposito e l'archivio non nasce).
"""
import os
import shutil
import sqlite3
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema


class TestDepositoCablato(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.percorso = os.path.join(self.d, "deposito.db")
        self.sis = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=b"h" * 32,
                                              db_deposito=self.percorso))

    # ── IL CABLAGGIO ────────────────────────────────────────────────────────
    def test_il_prodotto_espone_il_deposito(self):
        self.assertIsNotNone(getattr(self.sis, "deposito", None),
                             "il deposito cauzionale non e' collegato al sistema")

    def test_l_archivio_nasce_su_file_e_non_in_ram(self):
        """Custodisce hold su carte: in RAM si perderebbe la traccia di soldi bloccati."""
        self.assertTrue(os.path.isfile(self.percorso), "archivio del deposito non creato")
        con = sqlite3.connect(self.percorso)
        try:
            tabelle = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            con.close()
        self.assertTrue(tabelle, "schema del deposito non inizializzato: %s" % tabelle)

    def test_compare_fra_i_componenti_avviati(self):
        comp = " ".join((self.sis.report or {}).get("componenti", []))
        self.assertIn("deposito_cauzionale(149)", comp,
                      "il deposito non risulta fra i componenti avviati: %s" % comp)

    # ── LA MACCHINA FUNZIONA DAVVERO, NON SOLO ESISTE ───────────────────────
    def test_autorizza_e_rilascia_conservano_l_importo(self):
        """Il percorso che funziona SENZA gestore pagamenti: hold e rilascio totale.
        Invariante del modulo: catturato + rilasciato = autorizzato, al centesimo."""
        dep = self.sis.deposito
        self.assertTrue(dep.autorizza("rif_1", "pi_hold_1", 30000))
        self.assertTrue(dep.rilascia("rif_1"))
        st = dep.stato("rif_1")
        self.assertEqual(int(st["autorizzato_cents"]), 30000)
        self.assertEqual(int(st["catturato_cents"]) + int(st["rilasciato_cents"]),
                         int(st["autorizzato_cents"]), "conservazione rotta: %s" % st)
        self.assertEqual(st["stato"], "rilasciato")

    def test_trattenere_un_danno_e_RIFIUTATO_senza_gestore_pagamenti(self):
        """FATTO IMPORTANTE, non un difetto: `cattura_danno` e' gated dal PSP (fase149 riga
        ~109). Col cablaggio da solo, autorizzare e rilasciare funzionano, ma TRATTENERE i
        soldi di un danno viene RIFIUTATO — e l'archivio resta 'autorizzato', senza stati a
        meta'. Per trattenere davvero serve collegare capture/release al gestore pagamenti:
        e' una decisione del fondatore (muove denaro dei clienti)."""
        dep = self.sis.deposito
        self.assertTrue(dep.autorizza("rif_d", "pi_hold_d", 30000))
        self.assertFalse(dep.cattura_danno("rif_d", 12000),
                         "ha trattenuto un danno senza passare dal gestore pagamenti")
        st = dep.stato("rif_d")
        self.assertEqual(int(st["catturato_cents"]), 0, "trattenuto senza incassare: %s" % st)
        self.assertEqual(st["stato"], "autorizzato", "stato a meta' dopo un rifiuto: %s" % st)

    def test_il_dato_sopravvive_al_riavvio(self):
        """Un hold su una carta deve restare tracciato anche dopo un deploy."""
        self.sis.deposito.autorizza("rif_2", "pi_hold_2", 25000)
        sis2 = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=b"h" * 32,
                                          db_deposito=self.percorso))
        st = sis2.deposito.stato("rif_2")
        self.assertEqual(int(st["autorizzato_cents"]), 25000,
                         "hold perso al riavvio: l'archivio non e' durevole")

    # ── IL PSP RESTA DORMIENTE (scelta del fondatore) ───────────────────────
    def test_nessun_passaggio_automatico_al_gestore_pagamenti(self):
        dep = self.sis.deposito
        self.assertIsNone(getattr(dep, "_capture", None),
                          "capture verso il PSP iniettata dal cablaggio: decisione non nostra")
        self.assertIsNone(getattr(dep, "_release", None),
                          "release verso il PSP iniettata dal cablaggio: decisione non nostra")


class TestArchivioDurevoleInProduzione(unittest.TestCase):
    """La configurazione di produzione deve dare al deposito un archivio su FILE."""

    def test_compose_dichiara_db_deposito_su_data(self):
        with open("docker-compose.casavip.yml", encoding="utf-8") as f:
            compose = f.read()
        self.assertIn("DB_DEPOSITO: /data/deposito.db", compose,
                      "senza questa riga in produzione l'archivio vive in RAM: hold persi al riavvio")

    def test_main_legge_la_variabile(self):
        with open("main_casavip.py", encoding="utf-8") as f:
            main = f.read()
        self.assertIn('db_deposito=os.environ.get("DB_DEPOSITO"', main)


if __name__ == "__main__":
    unittest.main()
