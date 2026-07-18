"""Guardia PERMANENTE: il backup deve salvare OGNI database, e il restore deve saper
verificare la catena di hash del giornale contabile.

Nasce da un fantasma VERO trovato il 2026-07-18: il backup aveva una LISTA FISSA di
database scritta a mano e NON conteneva finanza.db (il giornale immutabile appena
costruito) ne' checkin/coda/split/geocache/poicache. Il libro contabile "per
l'integrita' totale delle transazioni" non veniva salvato da nessuna parte.
Ora il backup fa SCOPERTA AUTOMATICA (glob su *.db): questa guardia impedisce a
chiunque di ricadere nella lista fissa, e verifica che gli script offsite esistano.
"""
import os
import re
import sqlite3
import tempfile
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.path.join(QUI, "deploy")


class TestBackupCompleto(unittest.TestCase):
    def _leggi(self, nome):
        with open(os.path.join(DEPLOY, nome), encoding="utf-8") as f:
            return f.read()

    def test_backup_scopre_ogni_db_non_lista_fissa(self):
        s = self._leggi("backup_casavip.sh")
        # deve iterare su TUTTI i *.db della cartella dati (scoperta automatica)
        self.assertRegex(s, r'for\s+src\s+in\s+"\$DATA_DIR"/\*\.db',
                         "il backup deve fare glob *.db (scoperta automatica), non lista fissa")
        # e NON deve esserci la vecchia lista fissa che dimenticava finanza.db
        self.assertNotIn("for db in catalogo inventario registro_host", s,
                         "e' tornata la LISTA FISSA: finanza.db verrebbe di nuovo dimenticato")
        # deve produrre un checksum per ogni archivio (integrita' end-to-end)
        self.assertIn(".sha256", s, "manca il checksum per archivio")

    def test_script_offsite_presenti(self):
        for nome in ("pull_offsite.sh", "restore_offsite.sh"):
            self.assertTrue(os.path.exists(os.path.join(DEPLOY, nome)),
                            "manca deploy/%s (backup offsite)" % nome)
        pull = self._leggi("pull_offsite.sh")
        # PULL (il PC tira dal VPS) + cifratura obbligatoria: mai copie in chiaro
        self.assertIn("openssl enc -aes-256-cbc", pull, "l'offsite deve essere cifrato")
        self.assertIn("BV_PASS", pull, "serve una passphrase (mai copie in chiaro)")

    def test_restore_verifica_catena_hash(self):
        rest = self._leggi("restore_offsite.sh")
        self.assertIn("integrity_check", rest, "il restore deve fare PRAGMA integrity_check")
        self.assertIn("libro_giornale", rest,
                      "il restore deve ricalcolare la catena hash del giornale")
        self.assertIn("MANOMESSO", rest, "il restore deve saper URLARE se la catena e' rotta")

    def test_ricostruzione_db_da_gzip_e_integra(self):
        """Simula il cuore del restore: un DB gzippato torna un DB valido e integro
        (la logica bash e' provata dall'esercitazione; qui si blinda l'invariante)."""
        import gzip
        d = tempfile.mkdtemp()
        try:
            src = os.path.join(d, "prova.db")
            con = sqlite3.connect(src)
            with con:
                con.execute("CREATE TABLE t (x INTEGER)")
                con.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(300)])
            con.close()
            gz = src + ".gz"
            with open(src, "rb") as f, gzip.open(gz, "wb") as g:
                g.write(f.read())
            dest = os.path.join(d, "restored.db")
            with gzip.open(gz, "rb") as g, open(dest, "wb") as f:
                f.write(g.read())
            c = sqlite3.connect(dest)
            try:
                self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(c.execute("SELECT COUNT(*) FROM t").fetchone()[0], 300)
            finally:
                c.close()
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
