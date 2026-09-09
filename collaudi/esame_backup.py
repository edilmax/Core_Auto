"""L'ESAME DELLA CASELLA 1 DEL BLOCCO 8 (INFRASTRUTTURA) — il salvataggio si ripristina e si legge, non si guarda.

    python collaudi/esame_backup.py --file F.db.gz --sha F.db.gz.sha256 --manifest MANIFEST-TS.txt
                                                      ripristina UN backup vero in una cartella temporanea e lo legge
    ... --scrivi                                      ... e SCRIVE nella scheda (anche un rosso, col motivo)
    ... --con-guasto                                  tre guasti insieme (impronta sbagliata, pagina azzerata nella copia
                                                      ripristinata, tabella attesa che non esiste): deve gridare, NON scrive.
                                                      Il file originale NON viene toccato: il guasto vive nella copia.
    python collaudi/esame_backup.py --autoprova       costruisce un backup finto (db + gz + sha256 + manifesto, come li fa
                                                      deploy/backup_casavip.sh) e giudica nelle due direzioni

⛔ IL TESTO DELLA CASELLA NON SI RICOPIA: si legge da `collaudi/piano.py` (e' la chiave). ZERO rete e ZERO ssh da qui:
   il backup vero lo scarica B dal volume del VPS (/data/backup) e lo mette accanto al suo .sha256 e al MANIFEST del giro.

COSA MISURA, dichiarato (D18) — chat A, 2026-09-08. Il metodo viene da fonti lette prima di scrivere (D25):
  · Google SRE book, cap. «Data Integrity» (2016): «backups don't matter; what matters is recovery» · «you only know
    that you can recover your recent state if you actually do so» · i test di ripristino si automatizzano e si ripetono.
  · sqlite.org/fileformat.html: ogni database comincia con i 16 byte «SQLite format 3\\0»; la pagina e' a offset 16.
  · sqlite.org/pragma.html: `PRAGMA integrity_check` risponde UNA riga «ok» oppure le righe dei problemi (indici,
    record malformati, pagine mancanti, UNIQUE/CHECK/NOT NULL); `quick_check` salta UNIQUE e indici, qui NON si usa.
  · sqlite.org/uri.html: `mode=ro` apre in sola lettura; `immutable=1` spegne i lucchetti e NON si usa.
  Dentro casa (D10): fase38_backup.ripristina (gunzip), deploy/backup_casavip.sh (i nomi <db>-<TS>.db.gz, il .sha256 nel
  formato di sha256sum, il MANIFEST-<TS>.txt con i basename del giro), deploy/restore_offsite.sh (solo il pacchetto
  cifrato offsite: serve openssl e la passphrase), test_backup_completo (integrity_check su un db costruito, non su un
  backup vero), test_avvio_e_ripristino.TABELLE_ATTESE (le tabelle che ogni archivio DEVE avere: qui si leggono dal
  suo albero sintattico, non si ricopiano).

  ARCHIVIO    il file c'e' ed e' un gzip integro; l'impronta sha256 del .gz coincide con quella scritta nel .sha256
              (e il nome nel .sha256 e' il suo); il manifesto e' dello STESSO giro (stesso TS nel nome) e lo elenca;
              il giro ha salvato OGNI archivio di TABELLE_ATTESE (un backup a pezzi non e' un backup).
  RIPRISTINO  decompresso in una cartella temporanea; i primi 16 byte dicono «SQLite format 3\\0»; la pagina dichiarata
              nell'intestazione e' una potenza di 2 fra 512 e 65536 e la lunghezza del file ne e' un multiplo; aperto in
              SOLA LETTURA (`mode=ro`); `PRAGMA integrity_check` == «ok».
  CONTENUTO   ogni tabella attesa per QUEL database (TABELLE_ATTESE[<db>.db]) esiste; ogni tabella attesa si LEGGE
              (`SELECT COUNT(*)` e la prima riga), e il conteggio finisce nel dettaglio del passo.
  TEMPO       il ripristino (gunzip + apertura + integrity_check + letture) sta sotto TETTO_SECONDI, dichiarato.
Denominatore = passi. Un passo che esplode e' un rosso col nome dell'eccezione (S7), mai un silenzio.

⛔ D18: `precondizioni()` ferma il giro; `--autoprova` e `--con-guasto` (che non scrive mai); `NON_GUARDA`; guardia
   `test_pipeline_ci.TestLEsameDelBackupNonPuoBARARE`. `os.environ` non viene toccato; la cartella temporanea si cancella.
"""
import ast
import gzip
import hashlib
import io
import os
import pathlib
import re
import shutil
import sqlite3
import sys
import tempfile
import time

QUI = os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(QUI)
for _p in (RADICE, QUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import scheda  # noqa: E402
from piano import BLOCCHI  # noqa: E402

BLOCCO = 8
MARCA = "RIPRISTINATO"
COMANDO = "python collaudi/esame_backup.py --file <db.gz> --sha <.sha256> --manifest <MANIFEST.txt> --scrivi"
SITUAZIONI = ("archivio", "ripristino", "contenuto", "tempo")
TETTO_SECONDI = 120
MAGIA = b"SQLite format 3\x00"
NOME_ARCHIVIO = re.compile(r"^(?P<db>[A-Za-z0-9_]+)-(?P<ts>\d{8}-\d{6}(?:-\d+)*)\.db\.gz$")
NOME_TABELLA = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
FILE_TABELLE = "test_avvio_e_ripristino.py"
PASSI = []

NON_GUARDA = (
    "quante righe DEVE avere una tabella: qui si legge che le tabelle attese esistono e si leggono, e si stampa il "
    "conteggio; una tabella vuota (zero referral) e' legittima e non e' un rosso",
    "la catena di hash del giornale contabile (finanza.db): la ricalcola deploy/restore_offsite.sh, che qui non gira",
    "gli archivi a schema pigro (geocache, poicache, marche): non hanno tabelle attese, quindi non si giudicano",
    "il pacchetto offsite cifrato e la passphrase: questo esame legge il backup del volume /data/backup, non l'offsite",
    "se il backup e' RECENTE: l'ora nel nome del file sta nel dettaglio del passo, il giudizio sull'eta' non e' qui",
    "un ripristino DENTRO il contenitore vivo: qui si ripristina in una cartella temporanea del computer che esamina",
)


def passo(situazione, nome, ok, dettaglio=""):
    PASSI.append((situazione, nome, bool(ok), dettaglio))
    print("  %s  [%s] %s%s" % ("OK  " if ok else "ROSSO", situazione, nome, ("  -> " + dettaglio) if dettaglio else ""))
    return bool(ok)


def giudica(passi, situazioni=SITUAZIONI):
    motivi = []
    for s in situazioni:
        suoi = [p for p in passi if p[0] == s]
        if not suoi:
            motivi.append("situazione «%s» NON misurata" % s)
            continue
        for _s, nome, ok, dettaglio in suoi:
            if not ok:
                motivi.append("[%s] %s%s" % (s, nome, (" (%s)" % dettaglio) if dettaglio else ""))
    fuori = [p for p in passi if p[0] not in situazioni]
    if fuori:
        motivi.append("passi fuori dalle situazioni: %d" % len(fuori))
    return (not motivi), motivi, len(passi)


def condizione():
    blocco = [b for b in BLOCCHI if b["ordine"] == BLOCCO]
    cond = blocco[0]["finito_quando"] if len(blocco) == 1 else ()
    trovate = [c for c in cond if MARCA in str(c)]
    if len(trovate) != 1:
        raise RuntimeError("nel blocco %d trovo %d caselle con «%s»: ne serve UNA" % (BLOCCO, len(trovate), MARCA))
    return trovate[0]


def tabelle_attese(percorso=None):
    """TABELLE_ATTESE letto dall'albero sintattico di test_avvio_e_ripristino.py: l'assegnazione, non il testo (S6),
    e senza importare un modulo di test."""
    percorso = percorso or os.path.join(RADICE, FILE_TABELLE)
    with io.open(percorso, encoding="utf-8") as f:
        albero = ast.parse(f.read(), percorso)
    for nodo in albero.body:
        if isinstance(nodo, ast.Assign) and any(getattr(t, "id", None) == "TABELLE_ATTESE" for t in nodo.targets):
            valore = ast.literal_eval(nodo.value)
            if isinstance(valore, dict) and valore and all(isinstance(v, set) and v for v in valore.values()):
                return {k: set(v) for k, v in valore.items()}
            raise ValueError("TABELLE_ATTESE non e' un dizionario nome -> insieme non vuoto")
    raise LookupError("TABELLE_ATTESE non e' assegnato in %s" % os.path.basename(percorso))


def sha256_di(percorso):
    h = hashlib.sha256()
    with open(percorso, "rb") as f:
        for pezzo in iter(lambda: f.read(1 << 20), b""):
            h.update(pezzo)
    return h.hexdigest()


def _leggi_sha(percorso):
    """Il formato di sha256sum: «<64 hex>  <nome>» (o «*<nome>»). Torna (impronta, nome-o-None)."""
    with io.open(percorso, encoding="utf-8", errors="replace") as f:
        righe = [r.strip() for r in f if r.strip()]
    parti = righe[0].split() if righe else []
    impronta = parti[0].lower() if parti else ""
    nome = parti[1].lstrip("*") if len(parti) > 1 else None
    return impronta, nome


def _leggi_manifesto(percorso):
    with io.open(percorso, encoding="utf-8", errors="replace") as f:
        return [r.strip() for r in f if r.strip() and not r.startswith("#")]


# ---- ARCHIVIO ----
def misura_archivio(archivio, sha_file, manifesto, attese, sha_sbagliata=False):
    print("\n--- ARCHIVIO: c'e', e' integro, l'impronta coincide, il manifesto e' dello stesso giro e completo ---")
    nome = os.path.basename(archivio)
    m = NOME_ARCHIVIO.match(nome)
    passo("archivio", "il nome e' <db>-<TS>.db.gz (deploy/backup_casavip.sh)", m is not None, nome)
    db, ts = (m.group("db") + ".db", m.group("ts")) if m else (None, None)
    passo("archivio", "il file esiste e non e' vuoto", os.path.isfile(archivio) and os.path.getsize(archivio) > 0,
          "%d byte" % (os.path.getsize(archivio) if os.path.isfile(archivio) else 0))
    try:
        with gzip.open(archivio, "rb") as g:
            while g.read(1 << 20):
                pass
        passo("archivio", "il gzip e' integro (letto fino in fondo)", True)
    except Exception as e:                                        # noqa: BLE001 - un gzip rotto e' un rosso
        passo("archivio", "il gzip e' integro (letto fino in fondo)", False, "%s: %s" % (type(e).__name__, e))
    attesa, nome_nel_sha = _leggi_sha(sha_file)
    if sha_sbagliata:
        attesa = "0" * 64                                                        # IL GUASTO 1: impronta che non torna
    reale = sha256_di(archivio)
    passo("archivio", "sha256 del .gz == quello scritto nel .sha256", bool(attesa) and reale == attesa,
          "reale %s… atteso %s…" % (reale[:12], (attesa or "-")[:12]))
    passo("archivio", "il .sha256 porta il nome di QUESTO archivio", nome_nel_sha in (None, nome), repr(nome_nel_sha))
    righe = _leggi_manifesto(manifesto)
    m2 = re.match(r"^MANIFEST-(?P<ts>\d{8}-\d{6}(?:-\d+)*)\.txt$", os.path.basename(manifesto))
    passo("archivio", "il manifesto e' dello STESSO giro (stesso TS nel nome)", m2 is not None and ts is not None and m2.group("ts") == ts,
          "manifesto %s, archivio %s" % (m2.group("ts") if m2 else "?", ts))
    passo("archivio", "il manifesto elenca questo archivio", nome in righe, "%d voci" % len(righe))
    mancanti = sorted(k for k in attese if "%s-%s.db.gz" % (k[:-3], ts) not in righe)
    passo("archivio", "il giro ha salvato OGNI archivio di TABELLE_ATTESE (%d)" % len(attese), not mancanti,
          "mancano: %s" % mancanti if mancanti else "tutti")
    return db, ts


# ---- RIPRISTINO ----
def _pagina(intestazione):
    n = int.from_bytes(intestazione[16:18], "big")
    return 65536 if n == 1 else n


def misura_ripristino(archivio, cartella, azzera_pagina=False):
    print("\n--- RIPRISTINO: decompresso in %s, letto dai primi byte, aperto in sola lettura, integrity_check ---" % cartella)
    dest = os.path.join(cartella, "ripristinato.db")
    with gzip.open(archivio, "rb") as fi, open(dest, "wb") as fo:
        shutil.copyfileobj(fi, fo)
    with open(dest, "rb") as f:
        testa = f.read(100)
    dim = os.path.getsize(dest)
    passo("ripristino", "i primi 16 byte dicono «SQLite format 3\\0»", testa[:16] == MAGIA, repr(testa[:16]))
    pagina = _pagina(testa) if len(testa) >= 18 else 0
    passo("ripristino", "la pagina dichiarata e' una potenza di 2 fra 512 e 65536 e il file ne e' un multiplo",
          512 <= pagina <= 65536 and pagina & (pagina - 1) == 0 and dim % pagina == 0, "pagina %d, %d byte" % (pagina, dim))
    if azzera_pagina and pagina and dim >= 2 * pagina:
        with open(dest, "r+b") as f:                                             # IL GUASTO 2: nella COPIA, mai nell'originale
            f.seek(pagina)
            f.write(b"\x00" * pagina)
    con = None
    try:
        con = sqlite3.connect(pathlib.Path(dest).resolve().as_uri() + "?mode=ro", uri=True)
        righe = [r[0] for r in con.execute("PRAGMA integrity_check").fetchall()]
        passo("ripristino", "aperto in SOLA LETTURA e `PRAGMA integrity_check` == «ok»", righe == ["ok"], "; ".join(righe)[:160])
    except Exception as e:                                        # noqa: BLE001 - un database che non si apre e' un rosso
        passo("ripristino", "aperto in SOLA LETTURA e `PRAGMA integrity_check` == «ok»", False, "%s: %s" % (type(e).__name__, e))
    return con


# ---- CONTENUTO ----
def misura_contenuto(con, db, attese, tabella_finta=False):
    print("\n--- CONTENUTO: le tabelle attese per %s esistono e si leggono ---" % db)
    dovute = set(attese.get(db) or ())
    if tabella_finta:
        dovute = dovute | {"tabella_che_non_esiste"}                              # IL GUASTO 3
    passo("contenuto", "%s ha tabelle attese in TABELLE_ATTESE" % db, bool(dovute), ", ".join(sorted(dovute)))
    if con is None:
        passo("contenuto", "il database e' aperto", False, "nessuna connessione")
        return
    presenti = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    mancanti = sorted(dovute - presenti)
    passo("contenuto", "ogni tabella attesa esiste (%d presenti)" % len(presenti), not mancanti,
          "mancano: %s" % mancanti if mancanti else ", ".join(sorted(dovute)))
    for t in sorted(dovute & presenti):
        try:
            # il nome viene da TABELLE_ATTESE (costante del repository) ED e' fra quelli letti da sqlite_master; un
            # identificatore non puo' essere parametro di una query, quindi lo si vincola a [A-Za-z0-9_] prima di usarlo
            if not NOME_TABELLA.match(t):
                raise ValueError("nome di tabella fuori da [A-Za-z0-9_]: %r" % t)
            n = con.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]         # noqa: S608  # nosec B608
            con.execute('SELECT * FROM "%s" LIMIT 1' % t).fetchone()               # noqa: S608  # nosec B608
            passo("contenuto", "«%s» si legge" % t, True, "%d righe" % n)
        except Exception as e:                                    # noqa: BLE001 - una tabella illeggibile e' un rosso
            passo("contenuto", "«%s» si legge" % t, False, "%s: %s" % (type(e).__name__, e))


def misura_tutto(archivio, sha_file, manifesto, attese, con_guasto=False):
    """Le quattro situazioni in un posto solo, cronometrate; l'eccezione diventa un passo rosso (S7)."""
    avvio = time.monotonic()
    cartella = tempfile.mkdtemp(prefix="esame_backup_")
    con = None
    try:
        db, _ts = misura_archivio(archivio, sha_file, manifesto, attese, sha_sbagliata=con_guasto)
        con = misura_ripristino(archivio, cartella, azzera_pagina=con_guasto)
        misura_contenuto(con, db, attese, tabella_finta=con_guasto)
    except Exception as e:                                        # noqa: BLE001 - una misura rotta e' un rosso
        passo("ripristino", "la misura e' ESPLOSA", False, "%s: %s" % (type(e).__name__, e))
    finally:
        if con is not None:
            con.close()
        shutil.rmtree(cartella, ignore_errors=True)
    durata = time.monotonic() - avvio
    print("\n--- TEMPO ---")
    passo("tempo", "il ripristino letto e' stato cronometrato e sta sotto %d s" % TETTO_SECONDI, durata <= TETTO_SECONDI, "%.2f s" % durata)
    passo("tempo", "la cartella temporanea e' stata cancellata", not os.path.exists(cartella), cartella)


# ---- AUTOPROVA ----
def backup_finto(cartella, db="viral.db", ts="20260908-031500", tabelle=None, righe=5, altri=None, attese=None):
    """Un backup come lo produce deploy/backup_casavip.sh: <db>-<TS>.db.gz + .sha256 (formato sha256sum) + MANIFEST-<TS>.txt
    che elenca ogni archivio del giro (di serie: tutti quelli di TABELLE_ATTESE)."""
    attese = attese if attese is not None else tabelle_attese()
    tabelle = tabelle if tabelle is not None else sorted(attese.get(db) or {"t"})
    vivo = os.path.join(cartella, db)
    con = sqlite3.connect(vivo)
    with con:
        for t in tabelle:
            if not NOME_TABELLA.match(t):
                raise ValueError("nome di tabella fuori da [A-Za-z0-9_]: %r" % t)
            # identificatore vincolato a [A-Za-z0-9_] due righe sopra: non e' un parametro
            crea = 'CREATE TABLE "%s" (id INTEGER PRIMARY KEY, valore TEXT)' % t
            inserisci = 'INSERT INTO "%s" (valore) VALUES (?)' % t                      # noqa: S608  # nosec B608
            con.execute(crea)
            con.executemany(inserisci, [("r%d" % i,) for i in range(righe)])
    con.close()
    nome = "%s-%s.db.gz" % (db[:-3], ts)
    archivio = os.path.join(cartella, nome)
    with open(vivo, "rb") as fi, gzip.open(archivio, "wb") as fo:
        shutil.copyfileobj(fi, fo)
    os.remove(vivo)
    sha_file = archivio + ".sha256"
    with io.open(sha_file, "w", encoding="utf-8") as f:
        f.write("%s  %s\n" % (sha256_di(archivio), nome))
    manifesto = os.path.join(cartella, "MANIFEST-%s.txt" % ts)
    elenco = altri if altri is not None else ["%s-%s.db.gz" % (k[:-3], ts) for k in sorted(attese)]
    with io.open(manifesto, "w", encoding="utf-8") as f:
        f.write("# backup manifest %s\n" % ts)
        for r in elenco:
            f.write(r + "\n")
    return archivio, sha_file, manifesto


def _giudizio_su(cartella, con_guasto=False, **k):
    attese = k.pop("attese", None) or tabelle_attese()
    archivio, sha_file, manifesto = backup_finto(cartella, attese=attese, **k)
    del PASSI[:]
    flusso, vero = io.StringIO(), sys.stdout
    sys.stdout = flusso
    try:
        misura_tutto(archivio, sha_file, manifesto, attese, con_guasto)
    finally:
        sys.stdout = vero
    return giudica(PASSI)


def autoprova():
    attese = tabelle_attese()
    radice = tempfile.mkdtemp(prefix="esame_backup_autoprova_")
    righe, riuscita = [], True
    try:
        casi = [
            ("backup sano di viral.db (tabelle attese, manifesto completo)", {}, True),
            ("backup sano di finanza.db", {"db": "finanza.db"}, True),
            ("i tre guasti insieme (--con-guasto)", {"con_guasto": True}, False),
            ("una tabella attesa manca (referral_eventi)", {"tabelle": ["crediti", "referral_codici"]}, False),
            ("il manifesto e' di un altro giro", {"altri": None, "ts_manifesto_diverso": True}, False),
            ("il manifesto non elenca l'archivio", {"altri": ["finanza-20260908-031500.db.gz"]}, False),
            ("il giro non ha salvato finanza.db", {"altri": ["viral-20260908-031500.db.gz"]}, False),
            ("un archivio che non e' un database (gz di testo)", {"testo": True}, False),
            ("nome fuori formato", {"db": "viral.db", "ts": "ieri"}, False),
        ]
        for i, (nome, k, atteso) in enumerate(casi):
            cartella = os.path.join(radice, "caso%d" % i)
            os.makedirs(cartella)
            k = dict(k)
            testo = k.pop("testo", False)
            ts_diverso = k.pop("ts_manifesto_diverso", False)
            if testo or ts_diverso:
                archivio, sha_file, manifesto = backup_finto(cartella, attese=attese)
                if testo:
                    with gzip.open(archivio, "wb") as fo:
                        fo.write(b"questo non e' un database\n" * 40)
                    with io.open(sha_file, "w", encoding="utf-8") as f:
                        f.write("%s  %s\n" % (sha256_di(archivio), os.path.basename(archivio)))
                if ts_diverso:
                    nuovo = os.path.join(cartella, "MANIFEST-20260101-000000.txt")
                    os.replace(manifesto, nuovo)
                    manifesto = nuovo
                del PASSI[:]
                flusso, vero = io.StringIO(), sys.stdout
                sys.stdout = flusso
                try:
                    misura_tutto(archivio, sha_file, manifesto, attese)
                finally:
                    sys.stdout = vero
                verde, motivi, den = giudica(PASSI)
            else:
                verde, motivi, den = _giudizio_su(cartella, attese=attese, **k)
            ok = verde == atteso
            riuscita = riuscita and ok
            righe.append("   %-62s -> %-6s (atteso %-6s) den %d%s" % (nome, "VERDE" if verde else "ROSSO", "VERDE" if atteso else "ROSSO", den,
                                                                        "" if ok else "   ⛔ NON E' QUELLO CHE DOVEVA DIRE: %s" % "; ".join(motivi)[:200]))
        # il lettore di TABELLE_ATTESE nelle due direzioni: da un file che non l'assegna deve ESPLODERE, non tacere
        finto = os.path.join(radice, "senza_tabelle.py")
        with io.open(finto, "w", encoding="utf-8") as f:
            f.write("ALTRO = {'a.db': {'t'}}\n")
        try:
            tabelle_attese(finto)
            ok = False
        except LookupError:
            ok = True
        riuscita = riuscita and ok and len(attese) >= 20
        righe.append("   %-62s -> %s" % ("il lettore di TABELLE_ATTESE (%d archivi; esplode se manca)" % len(attese), "OK" if ok else "⛔ ROTTO"))
    finally:
        shutil.rmtree(radice, ignore_errors=True)
        del PASSI[:]
    return riuscita, righe


def precondizioni():
    fuori = []
    try:
        testo = " ".join(str(condizione()).split())
        fuori.append(("la casella esiste nel piano, una sola, e parla del ripristino", "RIPRISTINATO" in testo, testo[:70]))
    except Exception as e:
        fuori.append(("la casella esiste nel piano, una sola", False, str(e)))
    try:
        impronta = scheda.impronta_del_blocco(BLOCCO)
        fuori.append(("il blocco ha un'impronta", bool(impronta), impronta or "il piano non si legge"))
    except Exception as e:
        fuori.append(("il blocco ha un'impronta", False, str(e)))
    try:
        attese = tabelle_attese()
        fuori.append(("TABELLE_ATTESE si legge da %s" % FILE_TABELLE, len(attese) >= 20, "%d archivi" % len(attese)))
    except Exception as e:
        fuori.append(("TABELLE_ATTESE si legge da %s" % FILE_TABELLE, False, str(e)))
    d = tempfile.mkdtemp(prefix="esame_backup_pre_")
    scrivibile = os.path.isdir(d)
    shutil.rmtree(d, ignore_errors=True)
    fuori.append(("la cartella temporanea si crea e si cancella", scrivibile and not os.path.exists(d), d))
    return all(ok for _, ok, _ in fuori), fuori


def _stampa_non_guarda():
    print("-" * 86)
    print("⛔ COSA QUESTO ESAME NON HA ESAMINATO (D18 punto 3)")
    for r in NON_GUARDA:
        print("   · %s" % r)


def _argomento(argv, nome):
    return argv[argv.index(nome) + 1] if nome in argv and argv.index(nome) + 1 < len(argv) else None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    os.chdir(RADICE)
    del PASSI[:]
    print("=" * 86)
    print("🧾 ESAME DEL BLOCCO 8 — casella 1: il salvataggio si ripristina e si legge")
    print("=" * 86)
    if "--autoprova" in argv:
        print("🔁 AUTOPROVA — un backup costruito, giudicato nelle due direzioni (D18 punto 2)")
        riuscita, righe = autoprova()
        for r in righe:
            print(r)
        _stampa_non_guarda()
        print("=" * 86)
        print("VERDETTO: %s" % ("✅ il giudizio grida sul backup rotto e tace su quello sano" if riuscita
                                else "⛔ IL GIUDIZIO NON E' AFFIDABILE"))
        return 0 if riuscita else 1
    con_guasto = "--con-guasto" in argv
    if con_guasto and "--scrivi" in argv:
        print("⛔ FERMO: `--con-guasto` non scrive. Serve a vedere l'esame gridare; registrare quel")
        print("   rosso metterebbe nella scheda un backup rotto apposta.")
        return 2
    tutte_ok, righe = precondizioni()
    print("PRIMA DI MISURARE, L'ESAME MISURA SE STESSO (D18 punto 1)")
    for nome, ok, motivo in righe:
        print("  %-9s %-76s %s" % ("OK" if ok else "⛔ NO", nome, motivo))
    if not tutte_ok:
        print("VERDETTO: ⛔ FERMO — una precondizione non regge, quindi NON misuro e NON scrivo.")
        _stampa_non_guarda()
        return 2
    archivio, sha_file, manifesto = _argomento(argv, "--file"), _argomento(argv, "--sha"), _argomento(argv, "--manifest")
    ambiente_prima = dict(os.environ)
    cartella_finta = None
    if not (archivio and sha_file and manifesto):
        if con_guasto:
            cartella_finta = tempfile.mkdtemp(prefix="esame_backup_finto_")
            archivio, sha_file, manifesto = backup_finto(cartella_finta)
            print("backup FINTO dell'autoprova (--file/--sha/--manifest assenti): il guasto si vede lo stesso, ma NON e' il VPS")
        else:
            print("VERDETTO: ⛔ FERMO — servono --file <db.gz> --sha <.sha256> --manifest <MANIFEST.txt> (il backup vero lo scarica B)")
            _stampa_non_guarda()
            return 2
    if con_guasto:
        print("⚠️  PASSATA COI GUASTI DENTRO: impronta sbagliata; una pagina azzerata nella COPIA; una tabella attesa inventata")
    print("archivio: %s\nsha256:   %s\nmanifesto: %s" % (archivio, sha_file, manifesto))
    try:
        misura_tutto(archivio, sha_file, manifesto, tabelle_attese(), con_guasto)
    finally:
        if cartella_finta:
            shutil.rmtree(cartella_finta, ignore_errors=True)
    passo("tempo", "l'ambiente (os.environ) e' identico a prima della misura", dict(os.environ) == ambiente_prima)
    verde, motivi, denominatore = giudica(PASSI)
    print("")
    print("VERDETTO: %s — passi %d, rossi %d, denominatore %d"
          % ("✅ VERDE" if verde else "⛔ ROSSO", len(PASSI), sum(1 for p in PASSI if not p[2]), denominatore))
    for m in motivi:
        print("   perche': %s" % m)
    if "--scrivi" in argv:
        riga = scheda.registra(condizione(), esito=verde, denominatore=denominatore, comando=COMANDO, ordine=BLOCCO,
                               motivo="; ".join(motivi)[:600] or None)
        print("  SCRITTA nella scheda: blocco %d · esito %s · denominatore %d · impronta %s · motivo: %s"
              % (riga["blocco"], riga["esito"], riga["denominatore"], riga["impronta"], riga.get("motivo") or "-"))
    else:
        print("")
        print("(non ho scritto niente: aggiungi --scrivi per registrare nella scheda)")
    _stampa_non_guarda()
    print("=" * 86)
    return 0 if verde else 1


if __name__ == "__main__":
    sys.exit(main())
