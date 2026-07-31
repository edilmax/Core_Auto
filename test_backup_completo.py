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
import subprocess
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


class TestRipristinoAPezziNonPassa(unittest.TestCase):
    """IL RESTORE VIENE ESEGUITO DAVVERO, non letto.

    DIFETTO PROVATO il 2026-07-29 da una revisione ostile, su due forme distinte:

      · STRACCIATO — il passo [3] prende per OGNI archivio il suo snapshot piu' recente.
        Se l'ultimo giro di backup e' morto a meta' (disco pieno, container ucciso, un solo
        `.gz` perso), `finanza.db` torna da ieri e `catalogo.db` da stamattina: prenotazioni
        senza le righe di giornale che le pagano. Lo script stampava «RESTORE OK — dati
        integri» e usciva 0.
      · INCOMPLETO — un pacchetto troncato (tar a meta', pull interrotto) veniva ripristinato
        e dichiarato OK: host, accettazioni e payout semplicemente non c'erano.

    Chi rimette in piedi il server alle 3 di notte si fida di quella riga verde. Un test che
    legge il testo dello script non avrebbe visto nulla di tutto questo: la logica sta nel
    COMPORTAMENTO (e in bash le trappole vere sono le subshell, che cancellano i contatori).
    Per questo qui si costruisce un pacchetto cifrato vero e si guarda il codice d'uscita.
    """

    PASS = "passphrase-di-prova-non-e-un-segreto"

    @classmethod
    def setUpClass(cls):
        import shutil as _sh
        cls.bash = _sh.which("bash")
        cls.openssl = _sh.which("openssl")
        mancanti = [n for n, v in (("bash", cls.bash), ("openssl", cls.openssl)) if not v]
        if mancanti:
            # ⛔ SUL GIUDICE NON SI SALTA. Su Linux (la CI, e il server vero) questi due
            # strumenti ci sono sempre: se mancano non e' «ambiente diverso», e' una guardia
            # sul RIPRISTINO DEI DATI che sta per sparire in silenzio -- cioe' esattamente il
            # difetto che questo file esiste per impedire. Li' vale ROSSO.
            # Altrove (un computer senza Git Bash) resta un salto DICHIARATO: quella macchina
            # non puo' nemmeno eseguire il deploy, quindi non puo' verificarlo.
            if sys.platform.startswith("linux"):
                raise AssertionError(
                    "mancano %s: la guardia del restore NON e' stata eseguita, e su Linux "
                    "questo non e' un salto legittimo" % ", ".join(mancanti))
            raise unittest.SkipTest(
                "servono bash e openssl per provare deploy/restore_offsite.sh (mancano: %s)"
                % ", ".join(mancanti))

    def _db(self, percorso):
        con = sqlite3.connect(percorso)
        with con:
            con.execute("CREATE TABLE t (x INTEGER)")
            con.execute("INSERT INTO t VALUES (1)")
        con.close()

    def _pacchetto(self, archivi, manifesto=None):
        """archivi: [(nome_db, timestamp)] · manifesto: elenco di nomi .db.gz, o None."""
        import gzip
        import hashlib
        import shutil as _sh
        import tarfile
        d = tempfile.mkdtemp()
        self.addCleanup(_sh.rmtree, d, True)
        dentro = os.path.join(d, "dentro")
        os.makedirs(dentro)
        for nome, ts in archivi:
            crudo = os.path.join(d, "%s-%s.db" % (nome, ts))   # due istantanee, due file
            self._db(crudo)
            gz = os.path.join(dentro, "%s-%s.db.gz" % (nome, ts))
            with open(crudo, "rb") as f, gzip.open(gz, "wb") as g:
                g.write(f.read())
            with open(gz, "rb") as f:
                h = hashlib.sha256(f.read()).hexdigest()
            with open(gz + ".sha256", "w", encoding="utf-8") as f:
                f.write("%s  %s\n" % (h, os.path.basename(gz)))
        if manifesto is not None:
            ts_man = max(ts for _, ts in archivi)
            with open(os.path.join(dentro, "MANIFEST-%s.txt" % ts_man), "w",
                      encoding="utf-8") as f:
                f.write("# backup manifest %s\n" % ts_man)
                for riga in manifesto:
                    f.write(riga + "\n")
        tgz = os.path.join(d, "backup.tar.gz")
        with tarfile.open(tgz, "w:gz") as t:
            for n in sorted(os.listdir(dentro)):
                t.add(os.path.join(dentro, n), arcname=n)
        enc = os.path.join(d, "pacchetto.tar.gz.enc")
        r = subprocess.run([self.openssl, "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "100000",
                            "-in", tgz, "-out", enc, "-pass", "env:BV_PASS"],
                           env=dict(os.environ, BV_PASS=self.PASS),
                           capture_output=True, text=True)
        self.assertEqual(0, r.returncode, "cifratura del pacchetto di prova fallita: %s" % r.stderr)
        return d, enc

    def _restore(self, d, enc, parziale=False):
        env = dict(os.environ, BV_PASS=self.PASS)
        if parziale:
            env["BV_RESTORE_PARZIALE"] = "1"
        script = os.path.join(DEPLOY, "restore_offsite.sh").replace("\\", "/")
        r = subprocess.run([self.bash, script, enc.replace("\\", "/"),
                            os.path.join(d, "dest").replace("\\", "/")],
                           cwd=d, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180)
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    def test_un_pacchetto_SANO_passa(self):
        """L'altra direzione, obbligatoria: se il controllo nuovo bocciasse anche i pacchetti
        buoni, il ripristino d'emergenza sarebbe impossibile — un difetto peggiore."""
        d, enc = self._pacchetto([("finanza", "20260101-000000"),
                                  ("catalogo", "20260101-000000")],
                                 manifesto=["finanza-20260101-000000.db.gz",
                                            "catalogo-20260101-000000.db.gz"])
        codice, uscita = self._restore(d, enc)
        self.assertEqual(0, codice, "un pacchetto completo e coerente e' stato RIFIUTATO:\n%s" % uscita)
        self.assertIn("RESTORE OK", uscita)

    def test_archivi_da_DUE_giri_diversi_vengono_RIFIUTATI(self):
        d, enc = self._pacchetto([("finanza", "20260101-000000"),
                                  ("finanza", "20260102-000000"),
                                  ("catalogo", "20260101-000000")],
                                 manifesto=["finanza-20260102-000000.db.gz"])
        codice, uscita = self._restore(d, enc)
        self.assertNotEqual(0, codice,
                            "ripristino STRACCIATO (giornale di ieri + catalogo di oggi) "
                            "dichiarato buono:\n%s" % uscita)
        self.assertIn("STRACCIATO", uscita)

    def test_un_archivio_del_manifesto_MANCANTE_viene_RIFIUTATO(self):
        d, enc = self._pacchetto([("finanza", "20260101-000000")],
                                 manifesto=["finanza-20260101-000000.db.gz",
                                            "registro_host-20260101-000000.db.gz"])
        codice, uscita = self._restore(d, enc)
        self.assertNotEqual(0, codice,
                            "pacchetto INCOMPLETO dichiarato buono:\n%s" % uscita)
        self.assertIn("INCOMPLETO", uscita)
        self.assertIn("registro_host", uscita, "non dice QUALE archivio manca")

    def test_senza_manifesto_non_si_puo_dire_che_e_completo(self):
        """«Non lo so» non e' «va bene»: un pacchetto troncato ha esattamente questo aspetto."""
        d, enc = self._pacchetto([("finanza", "20260101-000000")], manifesto=None)
        codice, uscita = self._restore(d, enc)
        self.assertNotEqual(0, codice, "pacchetto senza manifesto dichiarato completo:\n%s" % uscita)
        self.assertIn("NESSUN MANIFESTO", uscita)

    def test_la_scappatoia_dichiarata_funziona_ma_va_SCELTA(self):
        """Se l'unica copia rimasta e' mista, chi sa cosa sta facendo deve poter procedere —
        ma consapevolmente, non in silenzio."""
        d, enc = self._pacchetto([("finanza", "20260101-000000"),
                                  ("finanza", "20260102-000000"),
                                  ("catalogo", "20260101-000000")],
                                 manifesto=["finanza-20260102-000000.db.gz"])
        codice, uscita = self._restore(d, enc, parziale=True)
        self.assertEqual(0, codice, "la scappatoia dichiarata non funziona:\n%s" % uscita)
        self.assertIn("ACCETTATO su tua richiesta", uscita)


if __name__ == "__main__":
    unittest.main()
