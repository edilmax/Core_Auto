"""
Test Fase 38 / Tavola VIP - Backup automatico DB.

Copre: lo snapshot CONSISTENTE e completo (Online Backup API: cattura anche i
commit nel WAL), la retention SIZE-CAP (lo spazio totale resta sotto il tetto,
tiene sempre il piu' recente), il ripristino (gz e plain), e gli errori.
"""
import gzip
import os
import sqlite3
import tempfile
import unittest

import fase38_backup as bk


class _Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, "live.db")
        self.bkdir = os.path.join(self.dir, "backup")
        self._conn = self._crea_db(self.db, righe=300)

    def tearDown(self):
        try:
            self._conn.close()
        except Exception:
            pass
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def _crea_db(self, path, righe):
        con = sqlite3.connect(path)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA wal_autocheckpoint=0")   # i commit RESTANO nel WAL
        con.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT)")
        con.executemany("INSERT INTO t(v) VALUES(?)", [(f"r{i}",) for i in range(righe)])
        con.commit()
        return con  # tenuta aperta: niente checkpoint del WAL


class TestSnapshot(_Base):
    def test_snapshot_consistente_e_completo(self):
        r = bk.esegui_backup(self.db, self.bkdir)
        self.assertTrue(os.path.exists(r.percorso))
        self.assertGreater(r.bytes, 0)
        # ripristino e verifico: integrita' OK + TUTTE le 300 righe (erano nel WAL)
        dest = os.path.join(self.dir, "restored.db")
        bk.ripristina(r.percorso, dest)
        c = sqlite3.connect(dest)
        try:
            self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(c.execute("SELECT COUNT(*) FROM t").fetchone()[0], 300)
        finally:
            c.close()

    def test_snapshot_sotto_scritture_concorrenti(self):
        import threading
        stop = threading.Event()
        def scrittore():
            c = sqlite3.connect(self.db, timeout=30)
            i = 0
            while not stop.is_set() and i < 200:
                c.execute("INSERT INTO t(v) VALUES(?)", (f"x{i}",)); c.commit(); i += 1
            c.close()
        w = threading.Thread(target=scrittore)
        w.start()
        try:
            r = bk.esegui_backup(self.db, self.bkdir)   # backup MENTRE si scrive
        finally:
            stop.set(); w.join()
        dest = os.path.join(self.dir, "conc.db")
        bk.ripristina(r.percorso, dest)
        c = sqlite3.connect(dest)
        try:
            self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            n = c.execute("SELECT COUNT(*) FROM t").fetchone()[0]
            self.assertGreaterEqual(n, 300)            # snapshot consistente >= base
        finally:
            c.close()

    def test_lista_dir_inesistente(self):
        self.assertEqual(bk.lista_backup(os.path.join(self.dir, "vuota")), [])

    def test_db_mancante(self):
        with self.assertRaises(FileNotFoundError):
            bk.esegui_backup(os.path.join(self.dir, "no.db"), self.bkdir)

    def test_max_bytes_invalido(self):
        with self.assertRaises(ValueError):
            bk.esegui_backup(self.db, self.bkdir, max_bytes=0)

    def test_non_compresso(self):
        r = bk.esegui_backup(self.db, self.bkdir, comprimi=False)
        self.assertTrue(r.percorso.endswith(".db"))
        dest = os.path.join(self.dir, "r2.db")
        bk.ripristina(r.percorso, dest)
        c = sqlite3.connect(dest)
        try:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM t").fetchone()[0], 300)
        finally:
            c.close()


class TestRetention(_Base):
    def test_size_cap_non_sfora_mai(self):
        b1 = bk.esegui_backup(self.db, self.bkdir).bytes
        maxb = b1 * 3 + 1                      # spazio per ~3 backup
        rimossi_tot = 0
        for _ in range(8):
            r = bk.esegui_backup(self.db, self.bkdir, max_bytes=maxb)
            self.assertLessEqual(r.totale_bytes, maxb)   # MAI oltre il tetto
            rimossi_tot += r.rimossi
        self.assertLessEqual(r.num_backup, 3)
        self.assertGreater(rimossi_tot, 0)               # ha potato i vecchi

    def test_tiene_almeno_il_recente_anche_se_supera(self):
        bk.esegui_backup(self.db, self.bkdir)
        r = bk.esegui_backup(self.db, self.bkdir, max_bytes=1)  # tetto assurdo
        self.assertEqual(r.num_backup, 1)                 # resta SOLO il piu' recente
        self.assertEqual(len(bk.lista_backup(self.bkdir)), 1)

    def test_lista_ordinata_vecchio_recente(self):
        p = []
        for _ in range(3):
            p.append(bk.esegui_backup(self.db, self.bkdir, max_bytes=10**9).percorso)
        nomi = [os.path.basename(x[0]) for x in bk.lista_backup(self.bkdir)]
        # L'ordine giusto e' quello di CREAZIONE. Fino al 6/11/2026 qui c'era `sorted(nomi)`,
        # cioe' l'ordine alfabetico: lo stesso errore del codice (voce 265 di RIPRENDI).
        self.assertEqual(nomi, [os.path.basename(x) for x in p])
        self.assertEqual(len(nomi), 3)

    def test_DUE_BACKUP_NELLO_STESSO_ISTANTE_TIENE_IL_PIU_NUOVO(self):
        """6/11/2026, voce 265 di RIPRENDI. Due backup nello stesso scatto dell'orologio hanno lo
        stesso istante nel nome, e il secondo prende il suffisso «-2». Ordinati come TESTO,
        «...-125961-2.db.gz» viene PRIMA di «...-125961.db.gz» (il «-» sta prima del «.»): il
        backup nuovo passava per il piu' vecchio e la retention lo cancellava. La suite del 6/11
        lo ha preso per caso (FileNotFoundError alle 10:58); qui la collisione si costruisce
        apposta fermando l'orologio del modulo, cosi' la prova la vede ogni volta."""
        import datetime as _dt
        from unittest import mock
        fermo = _dt.datetime(2026, 11, 6, 10, 58, 46, 125961)
        with mock.patch.object(bk, "datetime") as orologio:
            orologio.datetime.now.return_value = fermo
            primo = bk.esegui_backup(self.db, self.bkdir, max_bytes=10**9).percorso
            secondo = bk.esegui_backup(self.db, self.bkdir, max_bytes=10**9).percorso
            self.assertNotEqual(primo, secondo, "premessa: il secondo prende il suffisso")
            self.assertEqual([x[0] for x in bk.lista_backup(self.bkdir)], [primo, secondo],
                             "l'ordine deve essere quello di creazione, non quello alfabetico")
            terzo = bk.esegui_backup(self.db, self.bkdir, max_bytes=1)   # tetto assurdo
        self.assertEqual([x[0] for x in bk.lista_backup(self.bkdir)], [terzo.percorso],
                         "deve restare SOLO il backup appena fatto")


class TestScript(unittest.TestCase):
    def test_script_backup_esiste(self):
        with open(os.path.join("deploy", "backup_tavolavip.sh"), encoding="utf-8") as f:
            s = f.read()
        self.assertIn("fase38_backup", s)
        self.assertIn("BACKUP_DIR", s)


if __name__ == "__main__":
    unittest.main()
