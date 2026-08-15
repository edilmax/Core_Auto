"""MACCHINA NUOVA — accensione da zero, fail-closed, ripristino del backup, doppio avvio.

Questi quattro capitoli rispondono alle domande che nessun test unitario pone, perche'
guardano il PRODOTTO INSTALLATO e non le sue funzioni:

  1. AVVIO DA ZERO. Si prende una cartella dati VUOTA (server appena comprato, volume
     Docker appena creato) e si accende `main_casavip.py` PER DAVVERO, in un processo
     separato, esattamente come fa il container: tutti gli schemi devono nascere, le tre
     sonde di salute devono rispondere, il sito deve servire pagine e accettare la prima
     scrittura senza un solo dato preesistente. E al riavvio quel dato dev'essere ancora li'.

  2. FAIL-CLOSED. Se manca una variabile critica il prodotto NON deve partire "aperto":
     o si rifiuta di partire (SystemExit 2) o risponde 401 ovunque. Meglio il sito giu'
     che il sito aperto. Si prova OGNI variabile critica, una per volta, lanciando il
     processo vero e leggendo il suo codice di uscita.

     DUE DIFETTI VERI trovati proprio cosi' il 2026-07-29 (guardie qui sotto, entrambe
     viste ROSSE sul codice di prima):
       (a) `CASAVIP_SEGRETO=x` (refuso, variabile troncata) non veniva rifiutato: il ramo
           `except ValueError` faceva `raw.encode()[:64].ljust(16, b"0")`, cioe' la chiave
           di firma diventava `b"x000000000000000"` — INDOVINABILE. Con quella si firmano
           voucher, gettoni host, cookie di sessione e crediti: un refuso nel `.env`
           spalancava la piattaforma in silenzio, senza un solo errore nei log.
       (b) `DB_FINANZA=` (variabile presente ma VUOTA) non veniva rifiutato: il percorso
           vuoto arriva a `sqlite3.connect("")`, che apre un database TEMPORANEO cancellato
           alla chiusura della connessione. Siccome ogni chiamata apre la sua connessione,
           il libro giornale immutabile smetteva di esistere ad ogni riga: schema perso,
           `no such table: libro_giornale`. E la sonda `/api/health/db` SALTA i percorsi
           vuoti, quindi continuava a dire "ok". Silenzio totale su una perdita di soldi.

  3. RIPRISTINO DEL BACKUP. Si usa il meccanismo VERO del prodotto, non una sua imitazione:
     `deploy/backup_casavip.sh` (lo stesso comando del container `backup` del compose,
     `DATA_DIR=/data BACKUP_DIR=/data/backup`), il pacchetto cifrato come lo fa
     `deploy/pull_offsite.sh`, e `deploy/restore_offsite.sh` per tornare indietro. Si
     distrugge l'intera cartella dati (backup compresi: nel compose vivono NEL volume) e
     si ripristina dalla sola copia offsite. Il confronto e' RIGA PER RIGA su ogni tabella
     di ogni archivio, piu' schema, piu' `integrity_check`, piu' la catena di hash del
     giornale. Due prove al contrario (il rosso di questa guardia): un archivio corrotto
     di UN byte dev'essere rifiutato, e un giornale manomesso dev'essere denunciato.

  4. DOPPIO AVVIO. Due processi che aprono gli stessi archivi (deploy sovrapposto, sidecar
     di backup, riavvio prima che il vecchio sia morto) non devono corrompere nulla:
     SQLite in WAL lo permette. Si verificano letture e scritture concorrenti da due
     processi VERI, sul sito e sul libro giornale, e alla fine catena intatta e archivi integri.

NOTE DI SICUREZZA DEL COLLAUDO (imparate a spese altrui):
  · i processi figli ricevono un ambiente COSTRUITO A MANO (lista bianca): niente chiavi
    Stripe/SMTP dello sviluppatore, niente DB_* ereditati -> nessuna chiamata a servizi
    veri, nessuna scrittura fuori dalla cartella temporanea;
  · MARCA_TEMPORALE=0 (niente marca RFC 3161 verso una TSA vera), GEOCODING/POI_OSM=false
    (niente rete), PULIZIA_UPLOADS=0 e UPLOAD_DIR/OUTREACH_OPTOUT_FILE in cartella
    temporanea (un test, in passato, ha cancellato file veri dello sviluppatore).
"""
from __future__ import annotations

import gzip
import http.client
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
DEPLOY = os.path.join(QUI, "deploy")

# Ambiente del processo figlio: LISTA BIANCA. Tutto cio' che non e' qui dentro non passa
# (le chiavi vere dello sviluppatore restano fuori dal collaudo).
VARIABILI_DI_SISTEMA = (
    "PATH", "SYSTEMROOT", "COMSPEC", "TEMP", "TMP", "WINDIR", "PATHEXT", "APPDATA",
    "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMDATA", "SYSTEMDRIVE", "USERPROFILE", "HOME",
    "LANG", "LC_ALL", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE", "OS", "LD_LIBRARY_PATH",
)

# Schemi che DEVONO nascere al primo avvio, con le tabelle che li rendono utili.
# (sottoinsieme: aggiungere tabelle e' lecito, perderle no)
TABELLE_ATTESE = {
    "accettazioni.db": {"accettazioni"},
    "admin_accounts.db": {"admin_account"},
    "catalogo.db": {"alloggi", "alloggio_immagini"},
    "checkin.db": {"checkin"},
    "coda.db": {"coda", "liberazioni"},
    "credito_usati.db": {"crediti_usati"},
    # Aggiunto il 2026-07-31: il deposito cauzionale (fase149) e' stato CABLATO il 2026-07-30,
    # cioe' il giorno DOPO che questo inventario e' stato scritto. Il test lo ha colto da solo
    # («in piu': ['deposito.db']») -- ed e' esattamente il suo mestiere. Nome della tabella
    # letto dall'archivio VERO in produzione, non indovinato.
    "deposito.db": {"cauzione"},
    "domanda.db": {"domanda"},
    "finanza.db": {"libro_giornale", "note", "debiti"},
    "garanzia.db": {"garanzia"},
    "inventario.db": {"inventario", "movimenti"},
    "kyc.db": {"kyc"},
    "messaggi.db": {"messaggi"},
    "partner.db": {"partner"},
    "payout.db": {"payout"},
    "pendenti.db": {"pendenti"},
    "recensioni.db": {"recensioni"},
    "registro_host.db": {"host"},
    "split.db": {"conti", "quote"},
    "tassa_comunale.db": {"tassa_regola", "tassa_riscossione"},
    "viral.db": {"crediti", "referral_codici", "referral_eventi"},
}
# Archivi a schema PIGRO: il loro componente e' spento in collaudo (niente rete, niente
# marca temporale), quindi nascono come file vuoti. Il file deve esserci lo stesso.
SCHEMI_PIGRI = ("geocache.db", "poicache.db", "marche.db")


# ─────────────────────────── attrezzi ───────────────────────────
def _porta_libera():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta = s.getsockname()[1]
    s.close()
    return porta


def _campi_db():
    """I nomi dei campi `db_*` della configurazione: nessuna lista scritta a mano."""
    from fase81_bootstrap_casavip import ConfigCasaVIP
    return sorted(c for c in vars(ConfigCasaVIP()) if c.startswith("db_"))


def _ambiente(cartella_dati, porta=None, extra=None):
    """Ambiente MINIMO e controllato per il processo figlio."""
    env = {k: v for k, v in os.environ.items() if k.upper() in VARIABILI_DI_SISTEMA}
    env.update({
        "CASAVIP_SEGRETO": "ab" * 32,
        "HOST_KEY": "chiave-host-collaudo",
        "ADMIN_KEY": "chiave-admin-collaudo",
        "DATA_DIR": cartella_dati,
        "HOST": "127.0.0.1",
        "STATIC_DIR": "deploy",
        "MARCA_TEMPORALE": "0",          # niente TSA vera
        "GEOCODING": "false",            # niente rete
        "POI_OSM": "false",              # niente rete
        "PULIZIA_UPLOADS": "0",          # nessuna cancellazione di file
        "UPLOAD_DIR": os.path.join(cartella_dati, "uploads"),
        "OUTREACH_OPTOUT_FILE": os.path.join(cartella_dati, "outreach_optout.json"),
        "FILE_REFERRAL": os.path.join(cartella_dati, "referral.json"),
        "CAMPAGNA_STATO_FILE": os.path.join(cartella_dati, "campagna_stato.json"),
        "DOMANDA_ALLARME_FILE": os.path.join(cartella_dati, "domanda_allarme.json"),
        "DOMANDA_SOGLIA": "1000000",     # nessun allarme durante il collaudo
        "PYTHONIOENCODING": "utf-8",
    })
    for campo in _campi_db():
        env["DB_" + campo[3:].upper()] = os.path.join(cartella_dati, campo[3:] + ".db")
    if porta is not None:
        env["PORTA"] = str(porta)
    for chiave, valore in (extra or {}).items():
        if valore is None:
            env.pop(chiave, None)
        else:
            env[chiave] = valore
    return env


def _http(porta, metodo, percorso, corpo=None, intestazioni=None, timeout=20):
    conn = http.client.HTTPConnection("127.0.0.1", porta, timeout=timeout)
    try:
        testa = dict(intestazioni or {})
        if corpo is not None:
            testa.setdefault("Content-Type", "application/json")
        conn.request(metodo, percorso, body=corpo, headers=testa)
        r = conn.getresponse()
        grezzo = r.read()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, \
            grezzo.decode("utf-8", "replace")
    finally:
        conn.close()


def _corpo_json(testo):
    return json.loads(testo)


def _istantanea(cartella):
    """Fotografia RIGA PER RIGA di ogni archivio: schema + contenuto di ogni tabella.

    Le righe si confrontano come insieme-con-molteplicita' (l'ordine fisico in SQLite
    non e' un impegno); l'ORDINE del giornale e' verificato a parte dalla catena di hash,
    che e' l'unico posto dove l'ordine e' un fatto e non un dettaglio.
    """
    foto = {}
    for nome in sorted(os.listdir(cartella)):
        if not nome.endswith(".db"):
            continue
        con = sqlite3.connect(os.path.join(cartella, nome))
        try:
            con.text_factory = bytes
            schema = con.execute(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name").fetchall()
            foto[nome + "::schema"] = [tuple(r) for r in schema]
            tabelle = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            for tab in tabelle:
                nome_tab = tab.decode("utf-8") if isinstance(tab, bytes) else tab
                righe = con.execute('SELECT * FROM "%s"' % nome_tab).fetchall()
                foto["%s::%s" % (nome, nome_tab)] = sorted(repr(tuple(r)) for r in righe)
        finally:
            con.close()
    return foto


def _tabelle(percorso_db):
    con = sqlite3.connect(percorso_db)
    try:
        return {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    finally:
        con.close()


def _pragma(percorso_db, nome_pragma):
    con = sqlite3.connect(percorso_db)
    try:
        return con.execute("PRAGMA " + nome_pragma).fetchone()[0]
    finally:
        con.close()


def _posix(percorso):
    """Percorso in forma POSIX: `C:\\x\\y` -> `/c/x/y`. Serve perche' gli attrezzi degli
    script (tar, openssl, find) sono programmi POSIX: `C:/...` verrebbe letto da tar come
    un host remoto ("Cannot connect to C")."""
    p = os.path.abspath(percorso).replace("\\", "/")
    if os.name == "nt" and len(p) > 1 and p[1] == ":":
        p = "/" + p[0].lower() + p[2:]
    return p


def _shell_posix():
    """La shell con cui girano gli script di deploy. Su Linux/CI e' /bin/bash. Su Windows
    e' quella di Git — MAI `C:\\Windows\\System32\\bash.exe`, che e' il ponte verso WSL e
    puo' non avere nessuna distribuzione installata."""
    if os.name != "nt":
        return shutil.which("bash") or shutil.which("sh")
    candidati = [os.environ.get("GIT_BASH", "")]
    basi = [os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramW6432", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]
    git = shutil.which("git")
    if git:
        basi.append(os.path.dirname(os.path.dirname(git)))
        basi.append(os.path.dirname(os.path.dirname(os.path.dirname(git))))
    for base in basi:
        if not base:
            continue
        candidati += [os.path.join(base, "Git", "bin", "bash.exe"),
                      os.path.join(base, "Git", "usr", "bin", "bash.exe"),
                      os.path.join(base, "bin", "bash.exe"),
                      os.path.join(base, "usr", "bin", "bash.exe")]
    trovata = shutil.which("bash")
    if trovata and "system32" not in trovata.lower():
        candidati.append(trovata)
    for c in candidati:
        if c and os.path.isfile(c):
            return c
    return None


def _sh(comando, cwd=None, env=None, timeout=300):
    """Esegue una riga di shell POSIX con la shell trovata sopra."""
    shell = _shell_posix()
    proc = subprocess.run([shell, "-c", comando], cwd=cwd or QUI,
                          env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          timeout=timeout)
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def _spegni(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=25)
        except subprocess.TimeoutExpired:          # pragma: no cover
            proc.kill()
            proc.wait(timeout=25)


def _leggi_log(percorso_log):
    try:
        with open(percorso_log, "rb") as f:
            return f.read().decode("utf-8", "replace")
    except OSError:                                # pragma: no cover
        return ""


def _cifra_pacchetto(cartella_backup, pacchetto, passphrase):
    """Fabbrica la copia offsite ESATTAMENTE come il passo 4 di `deploy/pull_offsite.sh`:
    tar della cartella backup, cifratura AES-256-CBC/PBKDF2 con la passphrase
    dall'ambiente, checksum accanto. (Il passo 1-3 dello script vero e' il PULL via SSH
    dal VPS: qui i backup sono gia' in locale. Che i parametri di cifratura siano ancora
    gli stessi dello script lo verifica `test_la_cifratura_del_pull_e_quella_del_restore_
    combaciano`: se un giorno divergessero, questo collaudo se ne accorgerebbe.)"""
    ambiente = dict(os.environ)
    ambiente["BV_PASS"] = passphrase
    comando = (
        "set -eu; ( cd '{backup}' && tar -czf '{tar}' . ); "
        "openssl enc -aes-256-cbc -pbkdf2 -iter 100000 -salt -in '{tar}' -out '{enc}' "
        "-pass env:BV_PASS; "
        "{{ sha256sum '{enc}' 2>/dev/null || shasum -a 256 '{enc}'; }} > '{enc}.sha256'"
    ).format(backup=_posix(cartella_backup), tar=_posix(pacchetto + ".tar.gz"),
             enc=_posix(pacchetto))
    return _sh(comando, env=ambiente)


class Prodotto(object):
    """Un'istanza VERA del prodotto: processo separato, come nel container."""

    def __init__(self, cartella_dati, porta=None, extra=None):
        self.cartella = cartella_dati
        self.porta = porta or _porta_libera()
        self.cartella_log = tempfile.mkdtemp(prefix="c3_log_")
        self.percorso_log = os.path.join(self.cartella_log, "avvio.log")
        self._flusso = open(self.percorso_log, "wb")
        self.proc = subprocess.Popen([PY, "main_casavip.py"], cwd=QUI,
                                     env=_ambiente(cartella_dati, self.porta, extra),
                                     stdout=self._flusso, stderr=subprocess.STDOUT)

    @property
    def log(self):
        return _leggi_log(self.percorso_log)

    def attendi(self, attesa=120.0):
        """Aspetta che la sonda di LIVENESS risponda; solleva se il processo muore."""
        scadenza = time.time() + attesa
        while time.time() < scadenza:
            if self.proc.poll() is not None:
                raise AssertionError("il prodotto e' MORTO durante l'avvio (uscita %s):\n%s"
                                     % (self.proc.poll(), self.log))
            try:
                stato, _h, _c = _http(self.porta, "GET", "/api/health/live", timeout=4)
                if stato == 200:
                    return self
            except (OSError, http.client.HTTPException):
                pass
            time.sleep(0.05)
        raise AssertionError("il prodotto non ha risposto entro %ss:\n%s"   # pragma: no cover
                             % (attesa, self.log))

    def spegni(self):
        _spegni(self.proc)
        try:
            self._flusso.close()
        except OSError:                            # pragma: no cover
            pass
        shutil.rmtree(self.cartella_log, ignore_errors=True)

    def get(self, percorso, intestazioni=None):
        return _http(self.porta, "GET", percorso, intestazioni=intestazioni)

    def post(self, percorso, oggetto, intestazioni=None):
        return _http(self.porta, "POST", percorso, corpo=json.dumps(oggetto),
                     intestazioni=intestazioni)


# ═══════════════ 1. AVVIO DA ZERO (macchina appena comprata) ═══════════════
class TestAvvioDaZero(unittest.TestCase):
    """Cartella dati VUOTA -> il prodotto si accende e il sito funziona."""

    @classmethod
    def setUpClass(cls):
        cls.radice = tempfile.mkdtemp(prefix="c3_zero_")
        cls.addClassCleanup(shutil.rmtree, cls.radice, True)
        cls.dati = os.path.join(cls.radice, "data")
        os.makedirs(cls.dati)
        cls.contenuto_iniziale = sorted(os.listdir(cls.dati))
        cls.app = Prodotto(cls.dati)
        cls.addClassCleanup(cls.app.spegni)
        cls.app.attendi()
        # FOTO SUBITO DOPO L'ACCENSIONE, prima che una qualsiasi richiesta tocchi i file:
        # senza questa, l'esito dipenderebbe dall'ORDINE dei test (la sonda /api/health/db
        # apre ogni archivio e cosi' lo CREA). Un test che dipende dall'ordine e' un
        # finto verde in attesa di succedere.
        cls.creati_dall_avvio = sorted(os.listdir(cls.dati))

    def test_la_cartella_era_vuota_e_ora_ci_sono_tutti_gli_schemi(self):
        """Nessun dato preesistente: ogni archivio e il suo schema nascono all'accensione."""
        self.assertEqual(self.contenuto_iniziale, [],
                         "la cartella dati non era vuota: la prova non vale")
        archivi = {n for n in self.creati_dall_avvio if n.endswith(".db")}
        self.assertEqual(archivi, set(TABELLE_ATTESE),
                         "l'accensione non crea piu' gli stessi archivi.\n  in meno: %s\n"
                         "  in piu': %s\n(se hai aggiunto un archivio, dichiaralo in "
                         "TABELLE_ATTESE con le sue tabelle)"
                         % (sorted(set(TABELLE_ATTESE) - archivi),
                            sorted(archivi - set(TABELLE_ATTESE))))
        for nome, attese in sorted(TABELLE_ATTESE.items()):
            trovate = _tabelle(os.path.join(self.dati, nome))
            mancanti = attese - trovate
            self.assertEqual(mancanti, set(),
                             "%s: schema NON nato, tabelle mancanti %s (presenti: %s)"
                             % (nome, sorted(mancanti), sorted(trovate)))

    def test_gli_archivi_a_schema_pigro_non_sono_una_sorpresa(self):
        """Tre archivi NON nascono all'accensione, e va bene cosi': i loro componenti sono
        spenti in questa configurazione (geocoding e POI senza rete, marca temporale senza
        TSA). Dichiararlo qui impedisce che, il giorno in cui uno di questi diventasse
        essenziale, la sua assenza passi per normale."""
        for nome in SCHEMI_PIGRI:
            self.assertNotIn(nome, self.creati_dall_avvio,
                             "%s ora nasce all'avvio: spostalo in TABELLE_ATTESE" % nome)
        # e comunque la sonda di salute non ci inciampa: li apre e li dichiara sani
        stato, _h, corpo = self.app.get("/api/health/db")
        self.assertEqual(stato, 200)
        salute = _corpo_json(corpo)["db"]
        for nome in SCHEMI_PIGRI:
            campo = "db_" + nome[:-3]
            self.assertEqual(salute.get(campo), "ok", "%s: %s" % (campo, salute.get(campo)))

    def test_ogni_archivio_configurato_esiste_ed_e_integro(self):
        """Nessun percorso dimenticato: OGNI campo `db_*` della configurazione ha il suo
        file su disco, integro. La lista viene dalla configurazione, non dalla memoria."""
        self.app.get("/api/health/db")     # tocca anche i tre archivi a schema pigro
        for campo in _campi_db():
            percorso = os.path.join(self.dati, campo[3:] + ".db")
            self.assertTrue(os.path.isfile(percorso),
                            "%s: nessun file creato in %s" % (campo, percorso))
            self.assertEqual(_pragma(percorso, "integrity_check"), "ok",
                             "%s: archivio NON integro appena creato" % campo)

    def test_gli_archivi_vivi_sono_in_wal(self):
        """WAL: e' cio' che permette lettori e scrittore insieme (e il doppio avvio)."""
        for nome in sorted(TABELLE_ATTESE):
            self.assertEqual(_pragma(os.path.join(self.dati, nome), "journal_mode"), "wal",
                             "%s non e' in WAL: due processi si bloccherebbero" % nome)

    def test_le_tre_sonde_di_salute_rispondono(self):
        """LIVE / READY / DB: l'orchestratore deve poter distinguere i tre stati."""
        stato, _h, corpo = self.app.get("/api/health/live")
        self.assertEqual(stato, 200)
        self.assertEqual(_corpo_json(corpo),
                         {"status": "live", "money_unit": "cents_integer"})

        stato, _h, corpo = self.app.get("/api/health/ready")
        self.assertEqual(stato, 200)
        self.assertEqual(_corpo_json(corpo), {"status": "ready"})

        stato, _h, corpo = self.app.get("/api/health/db")
        self.assertEqual(stato, 200)
        dati = _corpo_json(corpo)
        self.assertEqual(dati["status"], "ok")
        # la sonda deve NOMINARE ogni archivio configurato e dirlo "ok": se ne salta uno
        # (percorso vuoto!) il guasto resterebbe invisibile
        self.assertEqual(sorted(dati["db"]), _campi_db(),
                         "la sonda /api/health/db non copre tutti gli archivi")
        self.assertEqual(sorted(set(dati["db"].values())), ["ok"],
                         "archivi non sani appena creati: %s" % dati["db"])

        stato, _h, corpo = self.app.get("/api/health")
        self.assertEqual(stato, 200)
        salute = _corpo_json(corpo)
        # I campi stabili restano fissati esatti. `guardiano` (aggiunto il 2026-08-15) VARIA
        # col battito del Guardiano dei soldi, quindi si fissa l'INSIEME dei valori ammessi:
        # e' un contratto piu' STRETTO di prima, non piu' largo -- un valore inventato fa
        # rosso. Lo legge la sentinella esterna su GitHub, che il volume non lo vede e da
        # fuori puo' solo fare una richiesta HTTP.
        self.assertEqual({k: v for k, v in salute.items() if k != "guardiano"},
                         {"status": "ok", "money_unit": "cents_integer"})
        self.assertIn(salute.get("guardiano"), ("ok", "muto", "sconosciuto"),
                      "stato del Guardiano non riconoscibile dalla salute: %r" % (salute,))

    def test_il_sito_funziona_senza_nessun_dato(self):
        """Vetrina vuota, non rotta: la prima persona che arriva vede un sito, non un 500."""
        stato, testa, corpo = self.app.get("/")
        self.assertEqual(stato, 200)
        self.assertIn("text/html", testa.get("content-type", ""))
        self.assertTrue(corpo.lstrip().startswith("<!DOCTYPE html>"), corpo[:80])
        self.assertGreater(len(corpo), 2000, "pagina sospettosamente vuota")

        stato, _h, corpo = self.app.get("/api/catalogo")
        self.assertEqual(stato, 200)
        dati = _corpo_json(corpo)
        self.assertEqual(dati["totale"], 0)
        self.assertEqual(dati["risultati"], [])

        for percorso, atteso in (("/feed.xml", "<rss"), ("/sitemap.xml", "<urlset"),
                                 ("/robots.txt", "User-agent: *")):
            stato, _h, corpo = self.app.get(percorso)
            self.assertEqual(stato, 200, "%s risponde %s" % (percorso, stato))
            self.assertIn(atteso, corpo, "%s: contenuto inatteso" % percorso)

    def test_la_prima_scrittura_riesce_e_finisce_su_disco(self):
        """Macchina vergine: la prima riga di dati della storia dev'essere accettata,
        rileggibile dall'API e PRESENTE nel file (non solo in memoria)."""
        stato, _h, corpo = self.app.post(
            "/api/domanda", {"email": "primo.ospite@esempio.it", "citta": "Roma"})
        self.assertEqual(stato, 201, corpo)
        self.assertIs(_corpo_json(corpo)["ok"], True)

        stato, _h, corpo = self.app.get("/api/domanda/conta?citta=Roma")
        self.assertEqual(stato, 200)
        self.assertEqual(_corpo_json(corpo), {"citta": "Roma", "richieste": 1})

        con = sqlite3.connect(os.path.join(self.dati, "domanda.db"))
        try:
            righe = con.execute("SELECT COUNT(*) FROM domanda WHERE email=?",
                                ("primo.ospite@esempio.it",)).fetchone()[0]
        finally:
            con.close()
        self.assertEqual(righe, 1, "la scrittura non e' arrivata sul file")

    def test_le_api_riservate_restano_chiuse_a_chi_non_ha_le_chiavi(self):
        """L'altra faccia del fail-closed: acceso e configurato, ma senza credenziali
        nessuno entra. `/api/host/payout?host_id=<altrui>` e' la rotta che, col ramo
        dev-open, restituiva i soldi di chiunque."""
        for percorso in ("/api/host/payout?host_id=chiunque",
                         "/api/host/prenotazioni?host_id=chiunque",
                         "/api/admin/prenotazioni",
                         "/api/admin/alloggi"):
            stato, _h, corpo = self.app.get(percorso)
            self.assertEqual(stato, 401, "%s NON e' protetta (risponde %s: %s)"
                             % (percorso, stato, corpo[:120]))
            self.assertEqual(_corpo_json(corpo), {"errore": "unauthorized"})
        # chiave sbagliata = come nessuna chiave
        stato, _h, corpo = self.app.get("/api/admin/prenotazioni",
                                        {"X-Admin-Key": "chiave-sbagliata"})
        self.assertEqual(stato, 401, corpo[:120])
        # il super-admin (bunker) non e' configurato -> le sue rotte NON si aprono
        stato, _h, corpo = self.app.get("/api/bunker/guardiano")
        self.assertIn(stato, (401, 403), "rotta bunker aperta senza super-admin: %s" % corpo[:120])

    def test_senza_segreto_del_webhook_nessun_pagamento_viene_creduto(self):
        """Variabile critica dei SOLDI: senza STRIPE_WEBHOOK_SECRET la piattaforma non ha
        modo di riconoscere Stripe da un impostore. Fail-closed = rifiutare l'evento, non
        'crederci lo stesso': un 200 qui vorrebbe dire prenotazioni confermate GRATIS."""
        evento = json.dumps({"type": "checkout.session.completed",
                             "data": {"object": {"id": "cs_falso",
                                                 "metadata": {"riferimento": "RIF-FALSO"}}}})
        stato, _h, corpo = _http(self.app.porta, "POST", "/api/payments/webhook",
                                 corpo=evento)
        self.assertEqual(stato, 503, "evento di pagamento accettato senza segreto: %s" % corpo)
        self.assertEqual(_corpo_json(corpo), {"errore": "webhook_non_configurato"})


class TestWebhookConfiguratoMaSenzaFirma(unittest.TestCase):
    """L'altra meta' del webhook: il segreto C'E', ma la firma no (o e' inventata)."""

    def test_una_firma_inventata_non_conferma_niente(self):
        radice = tempfile.mkdtemp(prefix="c3_webhook_")
        self.addCleanup(shutil.rmtree, radice, True)
        dati = os.path.join(radice, "data")
        os.makedirs(dati)
        app = Prodotto(dati, extra={"STRIPE_WEBHOOK_SECRET": "whsec_collaudo_c3"})
        self.addCleanup(app.spegni)
        app.attendi()
        evento = json.dumps({"type": "checkout.session.completed",
                             "data": {"object": {"id": "cs_falso",
                                                 "metadata": {"riferimento": "RIF-FALSO"}}}})
        for firma, come in (("", "assente"),
                            ("t=1,v1=00" * 4, "inventata"),
                            ("t=1,v1=" + "a" * 64, "plausibile ma falsa")):
            with self.subTest(firma=come):
                stato, _h, corpo = _http(app.porta, "POST", "/api/payments/webhook",
                                         corpo=evento,
                                         intestazioni={"Stripe-Signature": firma,
                                                       "Content-Type": "application/json"})
                self.assertEqual(stato, 400,
                                 "firma %s ACCETTATA (%s): pagamenti confermabili da "
                                 "chiunque" % (come, corpo[:120]))
                self.assertEqual(_corpo_json(corpo), {"errore": "firma_non_valida"})


class TestIDatiSopravvivonoAlRiavvio(unittest.TestCase):
    """Il deploy ricrea il container: i dati stanno nel volume, non nel processo."""

    def test_quello_che_scrivo_lo_ritrovo_dopo_il_riavvio(self):
        radice = tempfile.mkdtemp(prefix="c3_riavvio_")
        self.addCleanup(shutil.rmtree, radice, True)
        dati = os.path.join(radice, "data")
        os.makedirs(dati)

        primo = Prodotto(dati)
        self.addCleanup(primo.spegni)
        primo.attendi()
        stato, _h, corpo = primo.post("/api/domanda",
                                      {"email": "prima.del.deploy@esempio.it",
                                       "citta": "Lisbona"})
        self.assertEqual(stato, 201, corpo)
        primo.spegni()
        self.assertIsNotNone(primo.proc.poll(), "il primo processo non e' morto")

        secondo = Prodotto(dati)                       # stesso volume, processo nuovo
        self.addCleanup(secondo.spegni)
        secondo.attendi()
        stato, _h, corpo = secondo.get("/api/domanda/conta?citta=Lisbona")
        self.assertEqual(stato, 200)
        self.assertEqual(_corpo_json(corpo), {"citta": "Lisbona", "richieste": 1},
                         "il dato NON e' sopravvissuto al riavvio")


# ═══════════════ 2. FAIL-CLOSED (meglio il sito giu' che il sito aperto) ═══════════════
class TestFailClosed(unittest.TestCase):
    """Ogni variabile critica, una per volta: senza, il prodotto NON parte aperto."""

    PARTITO = "PARTITO"        # ha aperto la porta e risponde: NON si e' rifiutato
    BLOCCATO = "BLOCCATO"      # ne' morto ne' vivo entro il tempo dato

    def _esito(self, extra, attesa=90.0):
        """Lancia il prodotto vero e dice com'e' finita: codice d'uscita, PARTITO o BLOCCATO."""
        radice = tempfile.mkdtemp(prefix="c3_fc_")
        self.addCleanup(shutil.rmtree, radice, True)
        dati = os.path.join(radice, "data")
        os.makedirs(dati)
        app = Prodotto(dati, extra=extra)
        self.addCleanup(app.spegni)
        scadenza = time.time() + attesa
        while time.time() < scadenza:
            uscita = app.proc.poll()
            if uscita is not None:
                return uscita, app.log
            try:
                stato, _h, _c = _http(app.porta, "GET", "/api/health/live", timeout=2)
                if stato == 200:
                    return self.PARTITO, app.log
            except (OSError, http.client.HTTPException):
                pass
            time.sleep(0.05)
        return self.BLOCCATO, app.log              # pragma: no cover

    def _deve_rifiutare(self, extra, atteso_nel_log):
        uscita, log = self._esito(extra)
        self.assertEqual(uscita, 2,
                         "con %s il prodotto NON si e' rifiutato di partire (esito %r).\n"
                         "Un avvio riuscito qui significa piattaforma APERTA.\n%s"
                         % (extra, uscita, log[-1500:]))
        self.assertIn("RIFIUTO DI PARTIRE", log,
                      "si e' fermato ma senza dire perche': chi lo installa non capirebbe")
        self.assertIn(atteso_nel_log, log,
                      "il motivo non nomina la variabile colpevole (%s):\n%s"
                      % (atteso_nel_log, log[-1500:]))

    # ── controllo positivo: lo stesso ambiente, completo, PARTE ────────────────
    def test_controllo_positivo_lambiente_completo_parte(self):
        """Senza questo, ogni rifiuto qui sotto potrebbe essere colpa dell'attrezzatura
        e non del prodotto: e' la prova che l'unica differenza e' la variabile tolta."""
        uscita, log = self._esito({})
        self.assertEqual(uscita, self.PARTITO,
                         "l'ambiente completo NON parte (esito %r): i rifiuti qui sotto "
                         "non proverebbero nulla.\n%s" % (uscita, log[-1500:]))

    # ── chiavi d'accesso ──────────────────────────────────────────────────────
    def test_senza_chiave_host_o_admin_non_parte(self):
        """Il ramo dev-open del router (`if self._host_key is None: return True`) fa
        passare CHIUNQUE: se la chiave sparisce dall'ambiente, `/api/host/payout?host_id=
        <altrui>` servirebbe payout e dati personali di qualsiasi host."""
        for chiave in ("HOST_KEY", "ADMIN_KEY"):
            for valore, come in ((None, "assente"), ("", "vuota"), ("   ", "solo spazi")):
                with self.subTest(chiave=chiave, come=come):
                    self._deve_rifiutare({chiave: valore}, chiave)

    def test_le_chiavi_segnaposto_dellesempio_non_bastano(self):
        """`.env.casavip.example` sta su GitHub: i suoi segnaposto sono PUBBLICI. Chi copia
        l'esempio e dimentica di cambiarli avrebbe chiave admin e chiave di firma note al
        mondo intero — un sito 'protetto' da una password stampata sul giornale."""
        for chiave, segnaposto in (("HOST_KEY", "cambiami_chiave_host"),
                                   ("ADMIN_KEY", "cambiami_chiave_admin"),
                                   ("CASAVIP_SEGRETO", "cambiami_64_caratteri_hex")):
            with self.subTest(chiave=chiave):
                self._deve_rifiutare({chiave: segnaposto}, chiave)

    def test_i_segnaposto_sorvegliati_sono_ancora_quelli_dellesempio(self):
        """Se l'esempio cambia i suoi segnaposto, la guardia sopra diventa un ornamento."""
        with open(os.path.join(QUI, ".env.casavip.example"), encoding="utf-8") as f:
            esempio = f.read()
        for segnaposto in ("cambiami_chiave_host", "cambiami_chiave_admin",
                           "cambiami_64_caratteri_hex"):
            self.assertIn(segnaposto, esempio,
                          "il segnaposto %r non e' piu' nell'esempio: aggiorna la guardia "
                          "in main_casavip.py e qui" % segnaposto)

    # ── segreto HMAC ──────────────────────────────────────────────────────────
    def test_un_segreto_hmac_debole_non_parte(self):
        """DIFETTO CHIUSO 2026-07-29. `CASAVIP_SEGRETO=x` (refuso, variabile troncata da
        uno script, copia-incolla monco) diventava `b'x000000000000000'`: quindici zeri e
        una lettera. Con quella chiave si firmano voucher, gettoni host, cookie di
        sessione e crediti — cioe' si entra e si crea denaro. E nei log non appariva nulla."""
        for valore in ("x", "00", "12345678901234"):     # 1, 2 e 14 byte: tutti sotto i 16
            with self.subTest(segreto=valore):
                self._deve_rifiutare({"CASAVIP_SEGRETO": valore}, "CASAVIP_SEGRETO")

    def test_il_segreto_assente_e_casuale_mai_una_costante(self):
        """Senza segreto il prodotto parte (comodita' di sviluppo, e lo dice nei log), ma
        la chiave dev'essere CASUALE: se ripiegasse su una costante sarebbe peggio che
        non averla, perche' sembrerebbe configurato."""
        import main_casavip
        vecchio = os.environ.pop("CASAVIP_SEGRETO", None)
        self.addCleanup(lambda: os.environ.__setitem__("CASAVIP_SEGRETO", vecchio)
                        if vecchio is not None else None)
        with self.assertLogs(level="WARNING") as registrati:
            primo = main_casavip._segreto()
            secondo = main_casavip._segreto()
        self.assertTrue(any("CASAVIP_SEGRETO" in r.getMessage() for r in registrati.records),
                        "il ripiego effimero deve essere DETTO nei log")
        for segreto in (primo, secondo):
            self.assertIsInstance(segreto, bytes)
            self.assertGreaterEqual(len(segreto), 16)
            self.assertNotIn(segreto, (b"0" * 16, b"\x00" * 16, b"changeme" * 2,
                                       b"cambiami" * 2))
        self.assertNotEqual(primo, secondo, "il segreto 'casuale' e' sempre lo stesso")

    def test_un_segreto_forte_viene_usato_tale_e_quale(self):
        """L'altra meta' della guardia: cio' che e' buono NON dev'essere alterato."""
        import main_casavip
        vecchio = os.environ.get("CASAVIP_SEGRETO")
        self.addCleanup(lambda: os.environ.update({"CASAVIP_SEGRETO": vecchio})
                        if vecchio is not None else os.environ.pop("CASAVIP_SEGRETO", None))
        os.environ["CASAVIP_SEGRETO"] = "5a" * 32
        self.assertEqual(main_casavip._segreto(), bytes.fromhex("5a" * 32))
        os.environ["CASAVIP_SEGRETO"] = "una-frase-lunga-e-segreta-abbastanza"
        self.assertEqual(main_casavip._segreto(),
                         b"una-frase-lunga-e-segreta-abbastanza")

    # ── percorsi dei database ─────────────────────────────────────────────────
    def test_un_percorso_di_database_vuoto_non_parte(self):
        """DIFETTO CHIUSO 2026-07-29. `DB_FINANZA=` (variabile presente ma vuota, tipico
        di un `.env` modificato a mano) arrivava fino a `sqlite3.connect("")`, che apre un
        database TEMPORANEO cancellato alla chiusura della connessione. Ogni chiamata apre
        la sua connessione -> il libro giornale immutabile spariva tra una riga e l'altra
        ('no such table: libro_giornale'), e `/api/health/db` SALTA i percorsi vuoti,
        quindi continuava a rispondere 'ok'. Perdita di prove contabili in silenzio."""
        for variabile in ("DB_FINANZA", "DB_ACCETTAZIONI", "DB_CATALOGO"):
            for valore, come in (("", "vuoto"), ("   ", "solo spazi")):
                with self.subTest(variabile=variabile, come=come):
                    self._deve_rifiutare({variabile: valore}, variabile)

    def test_un_percorso_vuoto_farebbe_davvero_sparire_il_giornale(self):
        """La prova del DANNO che la guardia sopra evita: non una teoria, il fatto."""
        from fase177_financial_controller import crea_financial_controller
        contabilita = crea_financial_controller("")
        contabilita.inizializza_schema()
        with self.assertRaises(sqlite3.OperationalError) as ctx:
            contabilita.conta_movimenti()
        self.assertIn("libro_giornale", str(ctx.exception))


# ═══════════════ 3. RIPRISTINO DEL BACKUP (il giorno che il server muore) ═══════════════
def _movimenti_di_prova(percorso_finanza, quanti=5, prefisso="DRILL"):
    """Righe VERE nel libro giornale immutabile, scritte dal motore dei soldi del prodotto."""
    from fase177_financial_controller import crea_financial_controller
    contabilita = crea_financial_controller(percorso_finanza)
    contabilita.inizializza_schema()
    for i in range(quanti):
        riga = contabilita.movimento(tipo="incasso", riferimento="%s-%03d" % (prefisso, i),
                                     soggetto="ospite%d" % i, importo_cents=12345 + i,
                                     valuta="EUR", causale="collaudo ripristino",
                                     emittente=prefisso)
        if riga is None:                                   # pragma: no cover
            raise AssertionError("il giornale non ha accettato il movimento %d" % i)
    return contabilita


class TestRipristinoDelBackup(unittest.TestCase):
    """Backup -> pacchetto cifrato -> distruzione totale -> ripristino -> confronto."""

    PASSPHRASE = "collaudo-c3-frase-lunga-e-segreta"

    @classmethod
    def setUpClass(cls):
        if _shell_posix() is None:                         # pragma: no cover
            # ⛔ SUL GIUDICE NON SI SALTA (allineato a test_backup_completo il 2026-07-31).
            # Su Linux -- la CI, e il server vero -- una shell POSIX c'e' SEMPRE: se manca non
            # e' «ambiente diverso», e' una guardia sul RIPRISTINO DEI DATI che sparisce in
            # silenzio, cioe' proprio il guasto che questa classe esiste per impedire. Li'
            # vale ROSSO. Altrove resta un salto DICHIARATO: una macchina che non sa eseguire
            # gli script di deploy non puo' nemmeno verificarli.
            if sys.platform.startswith("linux"):
                raise AssertionError(
                    "shell POSIX assente: la prova di RIPRISTINO non e' stata eseguita, e "
                    "su Linux questo non e' un salto legittimo")
            raise unittest.SkipTest(
                "shell POSIX non installata: gli script di deploy non sono eseguibili qui")
        cls.radice = tempfile.mkdtemp(prefix="c3_restore_")
        cls.addClassCleanup(shutil.rmtree, cls.radice, True)
        cls.dati = os.path.join(cls.radice, "data")
        os.makedirs(cls.dati)
        # come nel compose: il backup vive DENTRO il volume dei dati (percio' la copia
        # offsite e' l'unica scialuppa quando il volume muore)
        cls.backup = os.path.join(cls.dati, "backup")
        cls.offsite = os.path.join(cls.radice, "offsite")
        os.makedirs(cls.offsite)

        # ── 1) dati VERI, scritti dal prodotto vero ────────────────────────────
        app = Prodotto(cls.dati)
        try:
            app.attendi()
            for citta in ("Roma", "Lisbona", "Tokyo"):
                stato, _h, corpo = app.post(
                    "/api/domanda", {"email": "ospite.%s@esempio.it" % citta.lower(),
                                     "citta": citta})
                assert stato == 201, (stato, corpo)
            stato, _h, corpo = app.post("/api/host/registrazione", {
                "email": "host.prova@esempio.it", "password": "password12",
                "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
                "ragione_sociale": "Prova Srl"})
            cls.registrazione_host = (stato, corpo)
        finally:
            app.spegni()
        _movimenti_di_prova(os.path.join(cls.dati, "finanza.db"))

        # ── 2) fotografia PRIMA del disastro ───────────────────────────────────
        cls.foto_originale = _istantanea(cls.dati)
        cls.archivi_originali = sorted(n for n in os.listdir(cls.dati) if n.endswith(".db"))

        # ── 3) backup con lo SCRIPT VERO (lo stesso comando del container) ─────
        ambiente = dict(os.environ)
        ambiente.update({"DATA_DIR": _posix(cls.dati), "BACKUP_DIR": _posix(cls.backup),
                         "BV_PASS": cls.PASSPHRASE})
        cls.uscita_backup, cls.log_backup = _sh(
            "sh deploy/backup_casavip.sh", env=ambiente)
        cls.elenco_backup = sorted(os.listdir(cls.backup)) if os.path.isdir(cls.backup) else []

        # ── 4) pacchetto offsite cifrato, come fa deploy/pull_offsite.sh ───────
        cls.pacchetto = os.path.join(cls.offsite, "bookinvip-collaudo.tar.gz.enc")
        cls.uscita_pacchetto, cls.log_pacchetto = _cifra_pacchetto(
            cls.backup, cls.pacchetto, cls.PASSPHRASE)

        # ── 5) DISASTRO: sparisce tutto il volume, backup compresi ─────────────
        shutil.rmtree(cls.dati, ignore_errors=True)
        cls.volume_distrutto = not os.path.exists(cls.dati)

        # ── 6) ripristino con lo SCRIPT VERO ──────────────────────────────────
        cls.ripristino = os.path.join(cls.radice, "ripristino")
        cls.uscita_restore, cls.log_restore = _sh(
            "BV_PASS=\"$BV_PASS\" bash deploy/restore_offsite.sh '%s' '%s'"
            % (_posix(cls.pacchetto), _posix(cls.ripristino)), env=ambiente)

    def test_il_backup_ha_salvato_ogni_archivio_con_il_suo_checksum(self):
        """Scoperta automatica: un archivio nuovo non puo' restare fuori dal backup."""
        self.assertEqual(self.uscita_backup, 0, self.log_backup)
        salvati = {n.split("-")[0] for n in self.elenco_backup if n.endswith(".db.gz")}
        attesi = {n[:-3] for n in self.archivi_originali}
        self.assertEqual(salvati, attesi,
                         "il backup non copre gli stessi archivi.\n  saltati: %s\n%s"
                         % (sorted(attesi - salvati), self.log_backup))
        for nome in self.elenco_backup:
            if nome.endswith(".db.gz"):
                self.assertIn(nome + ".sha256", self.elenco_backup,
                              "%s senza checksum: nessuno saprebbe se e' corrotto" % nome)
        self.assertTrue(any(n.startswith("MANIFEST-") for n in self.elenco_backup),
                        "manca il manifesto del giro: %s" % self.elenco_backup)

    def test_il_ripristino_riporta_i_dati_IDENTICI_riga_per_riga(self):
        """Il cuore: dopo la distruzione totale, ogni riga di ogni tabella torna uguale."""
        self.assertTrue(self.volume_distrutto, "il volume non e' stato distrutto davvero")
        self.assertEqual(self.uscita_restore, 0,
                         "il ripristino e' fallito:\n%s" % self.log_restore)
        self.assertIn("RESTORE OK", self.log_restore, self.log_restore)

        foto = _istantanea(self.ripristino)
        self.assertEqual(sorted(n for n in os.listdir(self.ripristino) if n.endswith(".db")),
                         self.archivi_originali, "sono tornati archivi diversi")
        # confronto RIGA PER RIGA, tabella per tabella, archivio per archivio
        self.assertEqual(sorted(foto), sorted(self.foto_originale),
                         "tabelle diverse dopo il ripristino")
        for chiave in sorted(self.foto_originale):
            self.assertEqual(foto[chiave], self.foto_originale[chiave],
                             "contenuto DIVERSO dopo il ripristino: %s" % chiave)
        # e non e' un confronto a vuoto: c'erano dati veri
        self.assertGreaterEqual(
            len(self.foto_originale["domanda.db::domanda"]), 3,
            "la fotografia originale e' vuota: il confronto non proverebbe nulla")
        self.assertEqual(len(self.foto_originale["finanza.db::libro_giornale"]), 5)
        self.assertEqual(len(self.foto_originale["registro_host.db::host"]), 1,
                         "host non registrato: %r" % (self.registrazione_host,))

    def test_ogni_archivio_ripristinato_e_integro_e_il_giornale_e_intatto(self):
        """`integrity_check` su tutto, e la catena di hash del giornale ricalcolata dal
        motore vero: i soldi non si accontentano di 'il file si apre'."""
        self.assertEqual(self.uscita_restore, 0, self.log_restore)
        for nome in os.listdir(self.ripristino):
            if nome.endswith(".db"):
                self.assertEqual(_pragma(os.path.join(self.ripristino, nome),
                                         "integrity_check"), "ok",
                                 "%s ripristinato ROTTO" % nome)
        self.assertIn("CATENA_OK_5_righe", self.log_restore,
                      "lo script non ha verificato la catena del giornale:\n%s"
                      % self.log_restore)
        from fase177_financial_controller import crea_financial_controller
        contabilita = crea_financial_controller(os.path.join(self.ripristino, "finanza.db"))
        esito = contabilita.verifica_catena()
        self.assertTrue(esito["ok"], "catena rotta dopo il ripristino: %s" % esito)
        self.assertEqual(esito["righe"], 5)

    def test_un_archivio_corrotto_di_un_byte_viene_RIFIUTATO(self):
        """Il rosso di questa guardia: se il ripristino accettasse una copia corrotta,
        tutta la sua verifica sarebbe un ornamento."""
        cartella = tempfile.mkdtemp(prefix="c3_corrotto_")
        self.addCleanup(shutil.rmtree, cartella, True)
        dati = os.path.join(cartella, "data")
        os.makedirs(dati)
        _movimenti_di_prova(os.path.join(dati, "finanza.db"), quanti=3, prefisso="COR")
        backup = os.path.join(cartella, "backup")
        ambiente = dict(os.environ)
        ambiente.update({"DATA_DIR": _posix(dati), "BACKUP_DIR": _posix(backup),
                         "BV_PASS": self.PASSPHRASE})
        uscita, log = _sh("sh deploy/backup_casavip.sh", env=ambiente)
        self.assertEqual(uscita, 0, log)

        archivio = [n for n in os.listdir(backup) if n.endswith(".db.gz")][0]
        percorso = os.path.join(backup, archivio)
        with open(percorso, "r+b") as f:            # UN byte girato, checksum intatto
            f.seek(20)
            byte = f.read(1)
            f.seek(20)
            f.write(bytes([byte[0] ^ 0xFF]))
        pacchetto = os.path.join(cartella, "corrotto.tar.gz.enc")
        uscita, log = _cifra_pacchetto(backup, pacchetto, self.PASSPHRASE)
        self.assertEqual(uscita, 0, log)

        uscita, log = _sh("BV_PASS=\"$BV_PASS\" bash deploy/restore_offsite.sh '%s' '%s'"
                          % (_posix(pacchetto), _posix(os.path.join(cartella, "out"))),
                          env=ambiente)
        self.assertNotEqual(uscita, 0,
                            "una copia CORROTTA e' stata accettata come buona:\n%s" % log)
        self.assertIn("CHECKSUM ROTTO", log, log)
        self.assertNotIn("RESTORE OK", log, log)

    def test_un_giornale_manomesso_viene_DENUNCIATO(self):
        """L'altro rosso: chi rimette in piedi il server deve sapere se qualcuno ha messo
        le mani nei conti mentre erano fuori casa."""
        cartella = tempfile.mkdtemp(prefix="c3_manomesso_")
        self.addCleanup(shutil.rmtree, cartella, True)
        dati = os.path.join(cartella, "data")
        os.makedirs(dati)
        finanza = os.path.join(dati, "finanza.db")
        _movimenti_di_prova(finanza, quanti=3, prefisso="MAN")
        con = sqlite3.connect(finanza)              # riga FALSA appesa in fondo
        try:
            with con:
                con.execute(
                    "INSERT INTO libro_giornale (evento_id, ts, tipo, riferimento, soggetto,"
                    " conto_dare, conto_avere, importo_cents, valuta, causale, emittente,"
                    " prev_hash, hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("FALSO-1", 1800000000, "incasso", "MAN-999", "ladro",
                     "cassa_piattaforma", "debiti_vs_host", 9999999, "EUR",
                     "riga inventata", "intruso", "hash-che-non-esiste", "hash-inventato"))
        finally:
            con.close()
        backup = os.path.join(cartella, "backup")
        ambiente = dict(os.environ)
        ambiente.update({"DATA_DIR": _posix(dati), "BACKUP_DIR": _posix(backup),
                         "BV_PASS": self.PASSPHRASE})
        uscita, log = _sh("sh deploy/backup_casavip.sh", env=ambiente)
        self.assertEqual(uscita, 0, log)
        pacchetto = os.path.join(cartella, "manomesso.tar.gz.enc")
        uscita, log = _cifra_pacchetto(backup, pacchetto, self.PASSPHRASE)
        self.assertEqual(uscita, 0, log)

        uscita, log = _sh("BV_PASS=\"$BV_PASS\" bash deploy/restore_offsite.sh '%s' '%s'"
                          % (_posix(pacchetto), _posix(os.path.join(cartella, "out"))),
                          env=ambiente)
        self.assertNotEqual(uscita, 0, "giornale manomesso accettato in silenzio:\n%s" % log)
        self.assertIn("GIORNALE MANOMESSO", log, log)
        self.assertIn("ROTTA_SEQ_4", log, "non dice DOVE si e' rotta la catena:\n%s" % log)

    def test_la_passphrase_sbagliata_non_apre_il_pacchetto(self):
        """Le copie offsite sono cifrate: senza la frase segreta non si leggono."""
        ambiente = dict(os.environ)
        ambiente["BV_PASS"] = "frase-sbagliata-di-proposito"
        uscita, log = _sh("BV_PASS=\"$BV_PASS\" bash deploy/restore_offsite.sh '%s' '%s'"
                          % (_posix(self.pacchetto),
                             _posix(os.path.join(self.radice, "out_sbagliata"))),
                          env=ambiente)
        self.assertNotEqual(uscita, 0, "pacchetto aperto con la passphrase SBAGLIATA:\n%s" % log)
        self.assertNotIn("RESTORE OK", log)


class TestMeccanismoDiBackupDelCompose(unittest.TestCase):
    """Il container `backup` del compose: quello che gira davvero ogni 6 ore."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(QUI, "docker-compose.casavip.yml"), encoding="utf-8") as f:
            cls.compose = f.read()

    def test_il_container_backup_usa_lo_script_del_prodotto_sul_volume(self):
        self.assertIn("sh deploy/backup_casavip.sh", self.compose,
                      "il container di backup non lancia piu' lo script collaudato qui")
        self.assertIn("DATA_DIR: /data", self.compose)
        self.assertIn("BACKUP_DIR: /data/backup", self.compose)

    def test_la_sentinella_del_container_riconosce_un_backup_vecchio(self):
        """L'healthcheck del container e' un `python -c` scritto nel compose: qui viene
        ESEGUITO per davvero su tre situazioni (fresco, vecchio, assente). Un controllo
        che non sa dire di no e' un controllo che non controlla."""
        import re
        trovato = re.search(r'test: \["CMD", "python", "-c", "([^"]+)"\]',
                            self.compose[self.compose.index("casavip_backup"):])
        self.assertIsNotNone(trovato, "healthcheck del container backup non trovato")
        comando = trovato.group(1)
        self.assertIn("/data/backup/*.gz", comando)

        cartella = tempfile.mkdtemp(prefix="c3_sentinella_")
        self.addCleanup(shutil.rmtree, cartella, True)
        finto = os.path.join(cartella, "backup")
        os.makedirs(finto)
        locale = comando.replace("/data/backup", finto.replace("\\", "/"))

        def esito():
            return subprocess.run([PY, "-c", locale], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, timeout=60).returncode

        self.assertEqual(esito(), 1, "cartella VUOTA giudicata sana")
        archivio = os.path.join(finto, "catalogo-20260101-000000.db.gz")
        with gzip.open(archivio, "wb") as f:
            f.write(b"contenuto")
        self.assertEqual(esito(), 0, "backup FRESCO giudicato malato")
        vecchio = time.time() - 30 * 3600          # 30 ore: oltre le 7 ammesse
        os.utime(archivio, (vecchio, vecchio))
        self.assertEqual(esito(), 1, "backup di 30 ORE giudicato fresco")

    def test_la_cifratura_del_pull_e_quella_del_restore_combaciano(self):
        """Il pacchetto offsite lo cifra `pull_offsite.sh` e lo apre `restore_offsite.sh`:
        se i due parametri divergono, il giorno del disastro il pacchetto non si apre.
        (E' anche il contratto che questo collaudo imita quando fabbrica il pacchetto.)"""
        with open(os.path.join(DEPLOY, "pull_offsite.sh"), encoding="utf-8") as f:
            pull = f.read()
        with open(os.path.join(DEPLOY, "restore_offsite.sh"), encoding="utf-8") as f:
            restore = f.read()
        parametri = "-aes-256-cbc -pbkdf2 -iter 100000"
        self.assertIn(parametri, pull, "la cifratura offsite e' cambiata")
        self.assertIn(parametri, restore, "il ripristino non usa gli stessi parametri")
        for testo, nome in ((pull, "pull_offsite.sh"), (restore, "restore_offsite.sh")):
            self.assertIn("-pass env:BV_PASS", testo,
                          "%s: la passphrase non passa piu' dall'ambiente" % nome)


# ═══════════════ 4. DOPPIO AVVIO (due processi, stessi archivi) ═══════════════
SCRITTORE_GIORNALE = '''"""Scrittore indipendente del libro giornale (processo separato)."""
import sys
sys.path.insert(0, sys.argv[1])
from fase177_financial_controller import crea_financial_controller

contabilita = crea_financial_controller(sys.argv[2])
prefisso, quante = sys.argv[3], int(sys.argv[4])
for i in range(quante):
    riga = contabilita.movimento(tipo="incasso", riferimento="%s-%03d" % (prefisso, i),
                                 soggetto="ospite", importo_cents=1000 + i, valuta="EUR",
                                 causale="doppio avvio", emittente=prefisso)
    if riga is None:
        print("RIFIUTATO alla riga %d" % i)
        sys.exit(3)
print("OK %d" % quante)
'''


class TestDoppioAvvio(unittest.TestCase):
    """Due processi vivi sugli stessi archivi: deploy sovrapposto, sidecar, riavvio lento."""

    def test_due_istanze_del_prodotto_scrivono_e_leggono_senza_pestarsi(self):
        radice = tempfile.mkdtemp(prefix="c3_doppio_")
        self.addCleanup(shutil.rmtree, radice, True)
        dati = os.path.join(radice, "data")
        os.makedirs(dati)

        prima = Prodotto(dati)
        self.addCleanup(prima.spegni)
        prima.attendi()
        seconda = Prodotto(dati)                    # STESSI archivi, altro processo
        self.addCleanup(seconda.spegni)
        seconda.attendi()

        # CONTESA VERA: piu' fili per istanza. Con un solo filo per parte le scritture si
        # accodano da sole e il collaudo non toccherebbe mai il lucchetto (provato: con
        # `timeout=0` sul database restava verde lo stesso = finto verde).
        fili_per_istanza, per_filo = 3, 5
        per_istanza = fili_per_istanza * per_filo
        esiti = {"prima": [], "seconda": [], "letture": []}
        blocco = threading.Lock()

        def scrivi(app, etichetta, filo):
            for i in range(per_filo):
                stato, _h, corpo = app.post(
                    "/api/domanda", {"email": "%s.%d.%02d@esempio.it" % (etichetta, filo, i),
                                     "citta": "Doppiavvio"})
                with blocco:
                    esiti[etichetta].append((stato, corpo[:90]))

        def leggi():
            for _ in range(30):
                stato, _h, _c = prima.get("/api/catalogo")
                with blocco:
                    esiti["letture"].append(stato)

        fili = [threading.Thread(target=leggi)]
        for etichetta, app in (("prima", prima), ("seconda", seconda)):
            for filo in range(fili_per_istanza):
                fili.append(threading.Thread(target=scrivi, args=(app, etichetta, filo)))
        for f in fili:
            f.start()
        for f in fili:
            f.join(timeout=180)
        for f in fili:
            self.assertFalse(f.is_alive(), "una scrittura concorrente si e' bloccata")

        for etichetta in ("prima", "seconda"):
            stati = sorted(s for s, _c in esiti[etichetta])
            self.assertEqual(stati, [201] * per_istanza,
                             "l'istanza '%s' ha perso scritture: %s"
                             % (etichetta, esiti[etichetta]))
        self.assertEqual(set(esiti["letture"]), {200},
                         "le letture si sono bloccate mentre l'altro processo scriveva")

        # ENTRAMBI i processi devono vedere TUTTE le righe (WAL: nessuna copia privata)
        for app, nome in ((prima, "prima"), (seconda, "seconda")):
            stato, _h, corpo = app.get("/api/domanda/conta?citta=Doppiavvio")
            self.assertEqual(stato, 200)
            self.assertEqual(_corpo_json(corpo),
                             {"citta": "Doppiavvio", "richieste": 2 * per_istanza},
                             "l'istanza '%s' non vede le scritture dell'altra" % nome)

        con = sqlite3.connect(os.path.join(dati, "domanda.db"))
        try:
            distinte = con.execute("SELECT COUNT(DISTINCT email) FROM domanda").fetchone()[0]
            totali = con.execute("SELECT COUNT(*) FROM domanda").fetchone()[0]
        finally:
            con.close()
        self.assertEqual((totali, distinte), (2 * per_istanza, 2 * per_istanza),
                         "righe perse o duplicate sotto doppio avvio")
        for nome in sorted(TABELLE_ATTESE):
            self.assertEqual(_pragma(os.path.join(dati, nome), "integrity_check"), "ok",
                             "%s corrotto dopo il doppio avvio" % nome)

    def test_due_processi_sul_libro_giornale_non_rompono_la_catena(self):
        """L'invariante piu' duro del prodotto: il giornale e' una CATENA, ogni riga
        contiene l'impronta della precedente. Due scrittori indipendenti che entrano
        insieme la biforcherebbero — se non fosse per BEGIN IMMEDIATE e il WAL."""
        cartella = tempfile.mkdtemp(prefix="c3_giornale_")
        self.addCleanup(shutil.rmtree, cartella, True)
        finanza = os.path.join(cartella, "finanza.db")
        from fase177_financial_controller import crea_financial_controller
        contabilita = crea_financial_controller(finanza)
        contabilita.inizializza_schema()

        script = os.path.join(cartella, "scrittore.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(SCRITTORE_GIORNALE)
        per_processo = 25
        processi = [subprocess.Popen(
            [PY, script, QUI, finanza, prefisso, str(per_processo)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT) for prefisso in ("ALFA", "BETA")]

        letture = []
        while any(p.poll() is None for p in processi):
            letture.append(contabilita.conta_movimenti())   # lettore VIVO durante le scritture
            time.sleep(0.02)
        uscite = []
        for p in processi:
            codice = p.wait(timeout=120)
            uscite.append((codice, p.stdout.read().decode("utf-8", "replace")))
            p.stdout.close()
        for i, (codice, testo) in enumerate(uscite):
            self.assertEqual(codice, 0, "scrittore %d fallito: %s" % (i, testo))
            self.assertIn("OK %d" % per_processo, testo)

        self.assertEqual(letture, sorted(letture),
                         "il conteggio letto durante le scritture e' DIMINUITO: %s" % letture)
        esito = contabilita.verifica_catena()
        self.assertTrue(esito["ok"], "catena SPEZZATA dal doppio scrittore: %s" % esito)
        self.assertEqual(esito["righe"], 2 * per_processo)
        con = sqlite3.connect(finanza)
        try:
            self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(
                con.execute("SELECT COUNT(DISTINCT evento_id) FROM libro_giornale"
                            ).fetchone()[0], 2 * per_processo, "eventi persi o doppi")
            self.assertEqual(
                con.execute("SELECT COUNT(DISTINCT prev_hash) FROM libro_giornale"
                            ).fetchone()[0], 2 * per_processo,
                "due righe con lo stesso predecessore: la catena si e' BIFORCATA")
            for prefisso in ("ALFA", "BETA"):
                self.assertEqual(
                    con.execute("SELECT COUNT(*) FROM libro_giornale WHERE emittente=?",
                                (prefisso,)).fetchone()[0], per_processo,
                    "mancano righe di %s" % prefisso)
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
