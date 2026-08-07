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
import sys
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


class TestGliStrumentiDiSalvataggioNONVIVONOSOLOSULSERVER(unittest.TestCase):
    """⛔ UNO STRUMENTO DI SALVATAGGIO CHE VIVE SOLO SULLA MACCHINA CHE DEVE SALVARE
    MUORE INSIEME A LEI.

    Trovato il 2026-08-07. I cinque strumenti con cui si genera e si verifica la
    chiavetta -- l'unica copia completa del prodotto -- stavano SOLO in `/root` sul
    VPS. Il giorno in cui quel server non c'e' piu' (che e' l'unico giorno in cui
    servono) non ci sono nemmeno loro: non stanno nel repository, e non stanno
    nemmeno dentro la chiavetta che loro stessi costruiscono. Chi ripristina si
    ritrova i dati e non il modo di rifarli.

    E uno dei cinque era anche SBAGLIATO. `impacchetta.sh` copiava i 25 database con
    `tar czf ... *.db`, che ha esattamente il difetto di `cp`: prende il file `.db` e
    lascia fuori il `-wal` accanto, dove SQLite tiene cio' che e' appena stato
    scritto. Misura di quel giorno: 0 file `-wal` presenti in quell'istante, quindi
    il tar prendeva tutto -- PER FORTUNA, NON PER COSTRUZIONE. Con traffico vero la
    prenotazione in corso nell'istante del tar sparisce dal backup senza un errore,
    e lo si scopre il giorno del ripristino, che e' il giorno peggiore.

    L'ultima prova di questa classe non e' un `grep`: esegue lo strumento VERO su un
    database col WAL sporco e pretende di riavere tutte le righe -- e nello stesso
    giro dimostra che la copia ingenua le perde davvero.
    """

    STRUMENTI = ("impacchetta.sh", "copia_db.py", "verifica_impronte.sh",
                 "verifica_pacchetti.sh", "prova_accensione.sh")

    def _leggi(self, nome):
        with open(os.path.join(DEPLOY, nome), encoding="utf-8") as f:
            return f.read()

    def test_i_cinque_strumenti_stanno_nel_repository(self):
        mancanti = [n for n in self.STRUMENTI
                    if not os.path.exists(os.path.join(DEPLOY, n))]
        self.assertEqual([], mancanti,
                         "questi strumenti di salvataggio NON sono nel repository: %r. "
                         "Se vivono solo in /root sul VPS, il giorno del guasto muoiono "
                         "insieme alla macchina che dovevano salvare -- e non finiscono "
                         "nemmeno dentro la chiavetta, che li contiene solo se stanno "
                         "qui" % mancanti)

    def test_impacchetta_NON_tocca_la_cartella_dei_database_VIVI(self):
        """La prima stesura di questa guardia era SBAGLIATA, e l'ha detto il rosso.

        Vietava `tar ... *.db` ovunque nel file. Cosi' colpiva due cose innocenti: il
        commento che RACCONTA il difetto vecchio (cioe' la memoria che D20 vuole
        conservare) e il `tar` sulle copie GIA' messe in salvo in /tmp/bk_chiavetta,
        che sono esattamente il risultato corretto. Una guardia che non sa distinguere
        l'attrezzo dal punto in cui lo si usa costringe a cancellare la spiegazione
        pur di farla tacere.

        L'invariante vero e' un altro, ed e' piu' semplice: la cartella dei database
        VIVI si tocca SOLO attraverso copia_db.py, che li legge con l'API di backup di
        sqlite3. Nessuna riga eseguibile di questo script ha motivo di nominare /data.
        """
        s = self._leggi("impacchetta.sh")
        codice = "\n".join(r for r in s.splitlines() if not r.lstrip().startswith("#"))
        self.assertNotIn(
            "/data", codice,
            "impacchetta.sh nomina /data (la cartella dei database VIVI) in una riga "
            "ESEGUIBILE. I 25 archivi si prendono solo attraverso copia_db.py: un "
            "`tar`/`cp` diretto su /data lascia fuori il -wal accanto, dove SQLite "
            "tiene cio' che e' appena stato scritto, e con traffico vero la "
            "prenotazione in corso sparisce dal backup senza un errore")
        self.assertIn("copia_db.py", codice,
                      "impacchetta.sh non usa copia_db.py: i database si copiano con "
                      "l'API di backup di sqlite3, che legge ATTRAVERSO il motore e "
                      "quindi vede anche cio' che sta nel WAL")

    def test_copia_db_usa_l_API_di_backup_e_APRE_le_copie(self):
        s = self._leggi("copia_db.py")
        self.assertIn(".backup(", s,
                      "copia_db.py non usa piu' Connection.backup(): senza quella e' "
                      "una copia di file come le altre, col difetto del WAL")
        self.assertIn("integrity_check", s,
                      "copia_db.py non apre piu' le copie: un archivio che non si apre "
                      "non e' un archivio, e lo si deve scoprire adesso e non il giorno "
                      "del guasto")

    def test_LA_COPIA_VIENE_ESEGUITA_DAVVERO_e_salva_cio_che_sta_nel_WAL(self):
        """Non un `grep`: lo strumento vero, su un database nello stato del server vivo.

        Si costruisce un database in modalita' WAL, ci si scrivono 500 righe e si
        LASCIA LA CONNESSIONE APERTA senza checkpoint -- e' esattamente lo stato in cui
        si trova il server mentre qualcuno sta prenotando. In quell'istante:
          · copiare il solo file `.db` (cio' che faceva `tar *.db`) restituisce un
            database SENZA quelle righe: il difetto, dimostrato qui e non raccontato;
          · `copia_db.py` deve restituirle tutte e 500.

        Se domani qualcuno «semplifica» copia_db.py in una copia di file, questa prova
        diventa rossa lo stesso giorno: e' la memoria del difetto, non la sua cronaca.
        """
        import shutil
        srcdir = tempfile.mkdtemp()
        dstdir = tempfile.mkdtemp()
        con = None
        try:
            percorso = os.path.join(srcdir, "prova.db")
            con = sqlite3.connect(percorso)
            modo = con.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            self.assertEqual("wal", str(modo).lower(),
                             "il database di prova non e' in WAL: cosi' la prova non "
                             "starebbe misurando niente (verde finto)")
            con.execute("PRAGMA wal_autocheckpoint=0")
            con.execute("CREATE TABLE prenotazioni (x INTEGER)")
            con.executemany("INSERT INTO prenotazioni VALUES (?)",
                            [(i,) for i in range(500)])
            con.commit()          # scritte e confermate, ma ancora dentro il -wal
            self.assertTrue(os.path.exists(percorso + "-wal"),
                            "nessun file -wal: senza, la prova non distingue le due "
                            "copie e direbbe verde per il motivo sbagliato")

            def righe(p):
                c = sqlite3.connect(p)
                try:
                    return c.execute("SELECT COUNT(*) FROM prenotazioni").fetchone()[0]
                except sqlite3.DatabaseError:
                    return -1     # la tabella non c'e' proprio: peggio ancora
                finally:
                    c.close()

            # (a) LA COPIA INGENUA: il solo file .db, cioe' cio' che prende `tar *.db`.
            #     Sta in srcdir con un'estensione diversa apposta, cosi' il glob *.db
            #     di copia_db.py non se la ritrova fra i sorgenti.
            ingenua = os.path.join(srcdir, "prova.copiaingenua")
            with open(percorso, "rb") as f, open(ingenua, "wb") as g:
                g.write(f.read())
            self.assertNotEqual(500, righe(ingenua),
                                "la copia del solo file .db contiene TUTTE le righe: "
                                "allora questa prova non dimostra piu' il difetto e va "
                                "rifatta, non cancellata")

            # (b) LO STRUMENTO VERO, eseguito.
            amb = dict(os.environ)
            amb["COPIA_DB_SORGENTE"] = srcdir
            amb["COPIA_DB_DESTINAZIONE"] = dstdir
            p = subprocess.run([sys.executable, os.path.join(DEPLOY, "copia_db.py")],
                               env=amb, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            uscita = p.stdout.decode("utf-8", "replace")
            self.assertEqual(0, p.returncode,
                             "copia_db.py e' uscito con codice %d:\n%s" % (p.returncode, uscita))
            self.assertEqual(500, righe(os.path.join(dstdir, "prova.db")),
                             "copia_db.py ha PERSO le righe che stavano nel WAL: e' "
                             "tornato a copiare il file invece di usare l'API di backup "
                             "di sqlite3.\n%s" % uscita)
        finally:
            if con is not None:
                con.close()
            shutil.rmtree(srcdir, ignore_errors=True)
            shutil.rmtree(dstdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
