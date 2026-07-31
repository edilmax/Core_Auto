"""CONTRATTO DI PERSISTENZA — la FORMA degli archivi e' congelata qui, colonna per colonna.

IL BUCO CHE QUESTO FILE CHIUDE
------------------------------
Il patrimonio del progetto non e' il codice: sono i DATI. Il codice si riscrive in un
pomeriggio, gli archivi no. Eppure fino a oggi nessuno sorvegliava la **forma** degli
archivi: una colonna rinominata, un indice perso in una rifattorizzazione, un trigger di
immutabilita' che non viene piu' creato, un vincolo `UNIQUE` caduto, un `CHECK` sparito —
tutte cose che la suite non vede, perche' ogni test costruisce il database dallo stesso
`CREATE TABLE` che sta verificando. Il codice e' d'accordo con se stesso: e' verde.

Il conto arriva mesi dopo, sui dati veri, e non e' un errore rumoroso:

  - `sqlite3.OperationalError: no such column: comune`  (colonna rinominata: 500 in faccia);
  - due host con la stessa email (l'`UNIQUE` non c'e' piu': login ambiguo);
  - una riga del libro giornale modificata in silenzio (il trigger non e' stato ricreato);
  - `importo REAL`: 900 centesimi diventano 899.9999999999999 e la tassa versata al Comune
    non torna piu' — una perdita che si scopre in sede di rendicontazione, non prima.

Qui la forma reale di OGNI archivio del prodotto viene estratta da `sqlite_master` /
`PRAGMA` e confrontata con un ATTESO scritto in chiaro nel test. Chi cambia lo schema deve
cambiare anche il contratto: e' una decisione consapevole, non un incidente. E il messaggio
di rosso dice ESATTAMENTE cosa e' cambiato (quale tabella, quale colonna, atteso/trovato),
perche' un rosso illeggibile viene disattivato dal primo che ha fretta.

COSA VERIFICA, PER OGNUNO DEI 17 ARCHIVI
---------------------------------------
 1. SCHEMA CONGELATO — insieme delle tabelle; per ogni tabella le colonne con **nome,
    tipo dichiarato, NOT NULL, posizione nella chiave primaria** e nell'ORDINE fisico;
    indici espliciti (SQL normalizzato); vincoli impliciti (`PRIMARY KEY`/`UNIQUE`, letti
    dagli autoindex); espressioni `CHECK`; chiavi esterne con la loro `ON DELETE`; trigger
    (SQL normalizzato: un trigger svuotato del corpo non passa).
 2. INVARIANTI TECNICI — `journal_mode=WAL` sul file (durevolezza + lettori concorrenti);
    **ogni** connessione nasce con `timeout=30` (bug storico #36: col default di 5s, sotto
    burst, i writer non si accodavano e tornavano «database is locked» → 503 su una
    prenotazione vera); **nessuna connessione resta aperta** dopo le operazioni (un
    descrittore che non si chiude e' un file lock che non si rilascia: su WAL blocca il
    checkpoint e, moltiplicato per le richieste, esaurisce i descrittori del processo).
    Non si guarda il codice sorgente: si spia `sqlite3.connect` e si interroga
    `PRAGMA busy_timeout` sulla connessione VERA che lo store apre.
 3. TIPI E VINCOLI DEL DENARO — le colonne di denaro sono dichiarate `INTEGER` e MAI
    `REAL`; l'elenco delle colonne di denaro non e' scritto a mano ma **ricavato dai nomi**
    e confrontato con quello dichiarato (una colonna di denaro nuova non puo' entrare in
    silenzio); ogni tabella ha una chiave primaria; e dopo una scrittura VERA il
    `typeof()` dei valori di denaro in archivio dev'essere `'integer'` (un float scritto
    dentro una colonna INTEGER SQLite lo conserva com'e': la dichiarazione da sola non
    basta, serve guardare il valore).
 4. L'ARCHIVIO FUNZIONA — ogni store viene fatto scrivere e rileggere con le sue API vere,
    e il risultato e' confrontato valore per valore. Senza questo, i nove controlli sopra
    passerebbero anche su un archivio con lo schema perfetto e le scritture rotte.

VISTO ROSSO (regola aurea: nessun verde vale finche' non e' stato visto rosso)
------------------------------------------------------------------------------
Ogni famiglia di controlli e' stata provata rompendo il codice di produzione che sorveglia.
Per non interferire con gli altri lavori in corso sugli stessi file, il guasto e' stato
iniettato su una COPIA byte-identica del modulo, messa davanti al repo nel `sys.path`
(stesso nome di modulo, stesso testo, UNA riga cambiata): e' lo stesso codice, importato
davvero, non una simulazione — e i file del repo sono usciti con lo stesso sha256 con cui
erano entrati. Quindici prove, quindici rossi:

  - `fase201_partner`: colonna `citta` rinominata in `city`
      → ROSSO «partner.citta: colonna SPARITA (attesa: "citta TEXT")» +
              «partner.city: colonna NUOVA non dichiarata nel contratto»;
  - `fase147_tassa_comunale`: `importo INTEGER` → `importo REAL`
      → ROSSO su DUE controlli diversi: «colonna di DENARO non INTEGER:
        [('tassa_riscossione.importo', 'REAL')]» e «colonne a virgola mobile in archivio»;
  - `fase113_messaggistica`: tolta la `CREATE INDEX ix_msg_pren`
      → ROSSO «indice SPARITO: ix_msg_pren»;
  - `fase177_financial_controller`: tolto il trigger `lg_no_update`
      → ROSSO «trigger SPARITO: lg_no_update» (il libro giornale tornava modificabile);
  - `fase177_financial_controller`: tolto `CHECK (importo_cents > 0)`
      → ROSSO su DUE controlli: «libro_giornale: CHECK spariti: ('importo_cents > 0',)» e
        `test_il_check_rifiuta_un_importo_non_positivo` («IntegrityError not raised»: una
        riga da 0 centesimi entrava in contabilita');
  - `fase88_registro_host`: tolto `UNIQUE` da `email`
      → ROSSO su DUE controlli: «host: vincoli impliciti spariti: ('unique(email)',)» e
        `test_due_host_non_possono_avere_la_stessa_email`. NOTA IMPORTANTE: la prima
        versione di quel secondo controllo chiamava solo `registra()` due volte ed e'
        rimasta VERDE senza il vincolo (il codice fa una SELECT preventiva) — era un finto
        verde, trovato proprio da questa prova. Ora il controllo tenta anche l'INSERT
        diretto in archivio, ed e' rosso;
  - `fase149_deposito_cauzionale`: `timeout=30` → `timeout=5`
      → ROSSO «connessioni aperte con busy_timeout diverso da 30000 ms: [5000]»;
  - `fase143_kyc_host`: tolta la `PRAGMA journal_mode=WAL`
      → ROSSO «journal_mode del file: 'delete' invece di 'wal'»;
  - `fase158_domanda`: tolto il `con.close()` dal `finally` di `registra`
      → ROSSO «2 connessione(i) mai chiuse dopo le operazioni (aperte in totale: 6)»;
  - `fase160_escrow_garanzia`: tabella `garanzia` rinominata `garanzie`
      → ROSSO «Lists differ: ['garanzie'] != ['garanzia']»;
  - `fase65_split_payment`: `riparti_equo` con la divisione a virgola mobile (`/`)
      → ROSSO «in quote.dovuto_cents ci sono valori di denaro non interi: ['real']»;
  - `fase65_split_payment`: `riparti_equo` senza il resto (largest-remainder tolto)
      → ROSSO sull'esercizio: un centesimo del gruppo spariva (raccolto 10000 invece di
        10001, mancante 20001 invece di 20000).

Una cosa che questa batteria NON ha visto rossa, e va detta: sostituire
`imp = _cent(importo)` con `float(...)` in `fase160` e' rimasto VERDE — perche' SQLite,
su una colonna INTEGER, converte da sola un float SENZA parte decimale (34040.0 → 34040).
Il controllo sul `typeof()` vede solo i float con resto (quelli che perdono denaro davvero,
come 10000.333…): e' un limite reale di quel controllo, non un difetto del prodotto.

La prova e' anche AUTOMATICA e PERMANENTE in `TestIlControlloSaFallire`, che costruisce a
mano archivi guasti (colonna rinominata, denaro in REAL, colonna di denaro nuova non
dichiarata, indice/trigger/UNIQUE/CHECK/FK persi, trigger svuotato, chiave primaria
assente, WAL spento, connessione non chiusa, timeout a 5s, valore float in archivio) e
pretende che ogni controllo li bocci — con la controprova che sull'archivio sano NON grida.

COSA HA TROVATO IL PRIMO GIRO (2026-07-29), per non perderlo
-------------------------------------------------------------
La notizia buona, e va detta per intero: sui 17 archivi NON esiste una sola colonna di
denaro dichiarata REAL, tutti e 17 aprono in WAL, tutti e 17 passano `timeout=30` a
`sqlite3.connect` e nessuno dei 17 lascia una connessione aperta dopo le operazioni. Il
sospetto piu' grave (il float in archivio) non si e' materializzato da nessuna parte.

Restano tre cose aperte, scritte qui perche' non si perdano:

  1. `fase149_deposito_cauzionale` e' COSTRUITO ma NON CABLATO: `crea_deposito_cauzionale`
     non e' chiamato da nessuna parte del prodotto, non esiste un campo `db_*` per lui in
     `ConfigCasaVIP` e quindi non c'e' nemmeno la riga nel `docker-compose`. Oggi non si
     perde niente (e' spento); il giorno che lo si accende, senza quella riga l'archivio
     finirebbe in `/app/data` e sparirebbe a ogni deploy — la trappola esatta che
     `test_db_persistenti` esiste per impedire. Il suo schema e' congelato qui lo stesso,
     cosi' l'accensione parte gia' sorvegliata.
  2. `fase113_messaggistica.conversazioni_host` raggruppa per `host_id`, ma l'unico indice
     e' `(prenotazione_id, id)`: e' una scansione completa di `messaggi` a ogni apertura
     del pannello host. Innocuo adesso, non lo sara' con la scala. Il contratto congela
     l'indice che c'e' davvero: se un giorno se ne aggiunge uno su `host_id`, va aggiornato.
  3. Sette archivi del prodotto sono ancora SCOPERTI (elencati in
     `TestOgniArchivioHaIlSuoContratto.SCOPERTI`): recensioni, viral, marche temporali,
     check-in, crediti single-use e le due cache. Marche e accettazioni sono prove legali:
     le accettazioni sono gia' congelate, le marche no. E' l'onda 2 di questo lavoro.
"""

import contextlib
import os
import re
import shutil
import sqlite3
import tempfile
import unittest

SEGRETO = b"segreto-di-collaudo-persistenza-32b!"
ORA = 1785000000            # orologio fisso: gli esiti attesi sono numeri esatti

# Un nome di colonna che contiene una di queste parole custodisce DENARO (o una quantita'
# che si comporta come denaro: bps, notti tassabili). Deve essere INTEGER, sempre.
NOMI_DI_DENARO = re.compile(
    r"cents|importo|minori|prezzo|deposito|voucher|residuo|dovuto|totale|tassa"
    r"|autorizzato|catturato|bps")


# ---------------------------------------------------------------------------
# Attrezzi: si legge il FILE con sqlite3 nudo, mai il codice che deve essere
# giudicato (un controllo che chiede al sorvegliato come sta non e' un controllo)
# ---------------------------------------------------------------------------
def _con(percorso):
    return sqlite3.connect(percorso)


def _normalizza(sql):
    return re.sub(r"\s+", " ", sql or "").strip()


def tabelle(percorso):
    """Nomi delle tabelle del prodotto (escluse quelle interne di SQLite)."""
    con = _con(percorso)
    try:
        righe = con.execute("SELECT name FROM sqlite_master WHERE type='table' "
                            "ORDER BY name").fetchall()
    finally:
        con.close()
    return tuple(r[0] for r in righe if not r[0].startswith("sqlite_"))


def descrittori_colonne(percorso, tabella):
    """Una riga per colonna: «nome TIPO [NOT NULL] [PKn]», nell'ordine fisico.

    E' la dichiarazione completa che conta: cambiare il tipo, togliere un NOT NULL o
    spostare una colonna nella chiave primaria sono tre modi diversi di rompere i dati."""
    con = _con(percorso)
    try:
        righe = con.execute("PRAGMA table_info(%s)" % tabella).fetchall()
    finally:
        con.close()
    fuori = []
    for (_i, nome, tipo, notnull, _dflt, pk) in righe:
        d = "%s %s" % (nome, tipo or "")
        if notnull:
            d += " NOT NULL"
        if pk:
            d += " PK%d" % pk
        fuori.append(d.strip())
    return tuple(fuori)


def indici_espliciti(percorso):
    """Indici creati a mano (CREATE INDEX): nome -> SQL normalizzato."""
    con = _con(percorso)
    try:
        righe = con.execute("SELECT name, sql FROM sqlite_master WHERE type='index' "
                            "AND sql IS NOT NULL ORDER BY name").fetchall()
    finally:
        con.close()
    return dict((n, _normalizza(s)) for n, s in righe if not n.startswith("sqlite_"))


def vincoli_impliciti(percorso):
    """Vincoli PRIMARY KEY / UNIQUE dichiarati nella tabella: tabella -> ('pk(a, b)',
    'unique(email)'). Sono le protezioni contro i doppioni: due host con la stessa email,
    due riscossioni sulla stessa prenotazione."""
    fuori = {}
    con = _con(percorso)
    try:
        for tab in [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                if not r[0].startswith("sqlite_")]:
            voci = []
            for riga in con.execute("PRAGMA index_list(%s)" % tab).fetchall():
                origine = riga[3]
                if origine not in ("pk", "u"):
                    continue
                colonne = [r[2] for r in con.execute("PRAGMA index_info(%s)" % riga[1])]
                voci.append("%s(%s)" % ("pk" if origine == "pk" else "unique",
                                        ", ".join(colonne)))
            fuori[tab] = tuple(sorted(voci))
    finally:
        con.close()
    return fuori


def check_espressioni(percorso):
    """Espressioni CHECK per tabella, estratte con un contatore di parentesi (una regex
    si mangerebbe la prima parentesi chiusa e restituirebbe testo a caso)."""
    fuori = {}
    con = _con(percorso)
    try:
        righe = con.execute("SELECT name, sql FROM sqlite_master WHERE type='table' "
                            "ORDER BY name").fetchall()
    finally:
        con.close()
    for nome, sql in righe:
        if nome.startswith("sqlite_"):
            continue
        testo = _normalizza(sql)
        alto = testo.upper()
        trovate, i = [], 0
        while True:
            j = alto.find("CHECK", i)
            if j < 0:
                break
            k = j + len("CHECK")
            while k < len(testo) and testo[k] == " ":
                k += 1
            if k >= len(testo) or testo[k] != "(":
                i = j + len("CHECK")
                continue
            livello, m = 0, k
            while m < len(testo):
                if testo[m] == "(":
                    livello += 1
                elif testo[m] == ")":
                    livello -= 1
                    if livello == 0:
                        break
                m += 1
            trovate.append(testo[k + 1:m].strip())
            i = m + 1
        fuori[nome] = tuple(sorted(trovate))
    return fuori


def chiavi_esterne(percorso):
    """tabella -> ('colonna -> tabella.colonna ON DELETE X', ...)."""
    fuori = {}
    con = _con(percorso)
    try:
        for tab in [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                if not r[0].startswith("sqlite_")]:
            voci = []
            for r in con.execute("PRAGMA foreign_key_list(%s)" % tab).fetchall():
                voci.append("%s -> %s.%s ON DELETE %s" % (r[3], r[2], r[4], r[6]))
            fuori[tab] = tuple(sorted(voci))
    finally:
        con.close()
    return fuori


def trigger_normalizzati(percorso):
    """nome -> SQL normalizzato. Il CORPO conta: un trigger svuotato non protegge nulla."""
    con = _con(percorso)
    try:
        righe = con.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger' "
                            "ORDER BY name").fetchall()
    finally:
        con.close()
    return dict((n, _normalizza(s)) for n, s in righe)


def journal_mode(percorso):
    con = _con(percorso)
    try:
        return con.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        con.close()


def colonne_a_virgola_mobile(percorso):
    """Colonne il cui TIPO DICHIARATO ha affinita' a virgola mobile: in un archivio di
    denaro non devono esistere."""
    fuori = []
    for tab in tabelle(percorso):
        con = _con(percorso)
        try:
            righe = con.execute("PRAGMA table_info(%s)" % tab).fetchall()
        finally:
            con.close()
        for (_i, nome, tipo, _nn, _d, _pk) in righe:
            t = (tipo or "").upper()
            if "REAL" in t or "FLOA" in t or "DOUB" in t or t == "NUMERIC" or t == "":
                fuori.append("%s.%s %s" % (tab, nome, tipo or "(nessun tipo)"))
    return sorted(fuori)


def tabelle_senza_chiave_primaria(percorso):
    fuori = []
    for tab in tabelle(percorso):
        con = _con(percorso)
        try:
            righe = con.execute("PRAGMA table_info(%s)" % tab).fetchall()
        finally:
            con.close()
        if not any(r[5] for r in righe):
            fuori.append(tab)
    return sorted(fuori)


def colonne_di_denaro(percorso):
    """Colonne di denaro RICAVATE dai nomi: cosi' l'elenco dichiarato nel contratto non
    puo' restare indietro quando ne nasce una nuova."""
    fuori = []
    for tab in tabelle(percorso):
        con = _con(percorso)
        try:
            righe = con.execute("PRAGMA table_info(%s)" % tab).fetchall()
        finally:
            con.close()
        for (_i, nome, tipo, _nn, _d, _pk) in righe:
            if NOMI_DI_DENARO.search(nome):
                fuori.append(("%s.%s" % (tab, nome), (tipo or "").upper()))
    return sorted(fuori)


def tipi_dei_valori(percorso, tabella, colonna):
    """`typeof()` DISTINTI dei valori realmente in archivio, + quante righe."""
    con = _con(percorso)
    try:
        # nomi di tabella/colonna non sono parametrizzabili in SQL; qui vengono tutti da
        # costanti scritte in questo file (i contratti congelati), mai da input esterno.
        tipi = [r[0] for r in con.execute(
            "SELECT DISTINCT typeof(%s) FROM %s"                       # noqa: S608
            % (colonna, tabella)).fetchall()]
        quante = con.execute("SELECT COUNT(*) FROM %s" % tabella).fetchone()[0]  # noqa: S608
    finally:
        con.close()
    return sorted(tipi), quante


# ---------------------------------------------------------------------------
# Diff leggibili: un rosso che non dice COSA e' cambiato viene ignorato
# ---------------------------------------------------------------------------
def differenze_colonne(tabella, attese, reali):
    da = dict((d.split(" ", 1)[0], d) for d in attese)
    dr = dict((d.split(" ", 1)[0], d) for d in reali)
    fuori = []
    for nome in sorted(set(da) - set(dr)):
        fuori.append('%s.%s: colonna SPARITA (attesa: "%s") — le query del prodotto la '
                     'usano ancora: sui dati veri sarebbe "no such column"'
                     % (tabella, nome, da[nome]))
    for nome in sorted(set(dr) - set(da)):
        fuori.append('%s.%s: colonna NUOVA non dichiarata nel contratto (trovata: "%s") — '
                     'se e\' voluta, aggiungila qui' % (tabella, nome, dr[nome]))
    for nome in sorted(set(da) & set(dr)):
        if da[nome] != dr[nome]:
            fuori.append('%s.%s: DICHIARAZIONE cambiata — atteso "%s", trovato "%s"'
                         % (tabella, nome, da[nome], dr[nome]))
    if not fuori and tuple(attese) != tuple(reali):
        fuori.append("%s: ORDINE fisico delle colonne cambiato — atteso %r, trovato %r"
                     % (tabella, list(attese), list(reali)))
    return fuori


def differenze_mappa(etichetta, attesa, reale):
    fuori = []
    for nome in sorted(set(attesa) - set(reale)):
        fuori.append('%s SPARITO: %s (atteso: "%s")' % (etichetta, nome, attesa[nome]))
    for nome in sorted(set(reale) - set(attesa)):
        fuori.append('%s NUOVO non dichiarato: %s (trovato: "%s")'
                     % (etichetta, nome, reale[nome]))
    for nome in sorted(set(attesa) & set(reale)):
        if attesa[nome] != reale[nome]:
            fuori.append('%s CAMBIATO: %s — atteso "%s", trovato "%s"'
                         % (etichetta, nome, attesa[nome], reale[nome]))
    return fuori


def differenze_insiemi(etichetta, attese, reali):
    """attese/reali: dict tabella -> tuple di voci."""
    fuori = []
    for tab in sorted(set(attese) | set(reali)):
        a, r = set(attese.get(tab, ())), set(reali.get(tab, ()))
        if a - r:
            fuori.append("%s: %s spariti: %s" % (tab, etichetta, tuple(sorted(a - r))))
        if r - a:
            fuori.append("%s: %s nuovi non dichiarati: %s"
                         % (tab, etichetta, tuple(sorted(r - a))))
    return fuori


# ---------------------------------------------------------------------------
# La spia sulle connessioni: si osserva la connessione VERA che lo store apre
# (nessuna lettura del sorgente: il sorgente puo' mentire, il PRAGMA no)
# ---------------------------------------------------------------------------
class Spia(object):
    def __init__(self):
        self.conn = []

    def mai_chiuse(self):
        return [c for c in self.conn if not getattr(c, "_chiusa", False)]

    def timeout_ms(self):
        return sorted(set(getattr(c, "_busy_ms", None) for c in self.conn))


@contextlib.contextmanager
def spia_connessioni(spia):
    vero = sqlite3.connect

    class _ConnSpiata(sqlite3.Connection):
        def close(self):
            self._chiusa = True
            return sqlite3.Connection.close(self)

    def finto(database, *a, **k):
        k.setdefault("factory", _ConnSpiata)
        con = vero(database, *a, **k)
        con._chiusa = False
        con._busy_ms = con.execute("PRAGMA busy_timeout").fetchone()[0]
        spia.conn.append(con)
        return con

    sqlite3.connect = finto
    try:
        yield spia
    finally:
        sqlite3.connect = vero
        for c in spia.conn:                 # niente descrittori appesi dopo il test
            try:
                sqlite3.Connection.close(c)
            except sqlite3.Error:
                pass


# ---------------------------------------------------------------------------
# La base comune. Ogni archivio dichiara il proprio contratto e come si esercita.
# ---------------------------------------------------------------------------
class BaseContratto(object):
    ETICHETTA = ""          # a cosa serve l'archivio, in una riga
    COLONNE = {}            # tabella -> descrittori, nell'ordine fisico
    INDICI = {}             # nome -> CREATE INDEX normalizzato
    UNICI = {}              # tabella -> ('pk(...)', 'unique(...)')
    CHECK = {}              # tabella -> espressioni CHECK
    FK = {}                 # tabella -> ('col -> tab.col ON DELETE X',)
    TRIGGER = {}            # nome -> CREATE TRIGGER normalizzato
    DENARO = ()             # ('tabella.colonna', ...) che DEVONO essere INTEGER

    # ---- da implementare nella sottoclasse -------------------------------
    def costruisci(self, percorso):
        raise NotImplementedError

    def esercita(self, archivio):
        """Scrittura + rilettura con le API VERE. Ritorna un dizionario di valori."""
        raise NotImplementedError

    def atteso_esercizio(self):
        raise NotImplementedError

    # ---- attrezzatura ----------------------------------------------------
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="contratto_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.db = os.path.join(self.dir, "archivio.db")

    def _vergine(self):
        """Un archivio NUOVO, creato dal codice di oggi: e' la forma che avranno i dati
        veri del prossimo host che si iscrive."""
        archivio = self.costruisci(self.db)
        if hasattr(archivio, "inizializza_schema"):
            archivio.inizializza_schema()
        return archivio

    def _esercitato(self):
        """Archivio nuovo + una scrittura e una rilettura vere, sotto la spia."""
        spia = Spia()
        with spia_connessioni(spia):
            archivio = self._vergine()
            esito = self.esercita(archivio)
        return spia, esito

    # ---- 1. SCHEMA CONGELATO --------------------------------------------
    def test_le_tabelle_sono_quelle_congelate(self):
        self._vergine()
        self.assertEqual(
            sorted(tabelle(self.db)), sorted(self.COLONNE),
            "%s: l'insieme delle TABELLE e' cambiato. Se e' voluto, aggiorna il "
            "contratto qui sopra; se non lo e', i dati veri non hanno piu' dove stare."
            % self.ETICHETTA)

    def test_le_colonne_sono_quelle_congelate(self):
        self._vergine()
        fuori = []
        for tab in sorted(self.COLONNE):
            fuori += differenze_colonne(tab, self.COLONNE[tab],
                                        descrittori_colonne(self.db, tab))
        self.assertEqual(fuori, [],
                         "%s: lo SCHEMA e' cambiato senza aggiornare il contratto.\n  - %s"
                         % (self.ETICHETTA, "\n  - ".join(fuori)))

    def test_gli_indici_sono_quelli_congelati(self):
        self._vergine()
        fuori = differenze_mappa("indice", dict(self.INDICI), indici_espliciti(self.db))
        self.assertEqual(fuori, [],
                         "%s: gli INDICI non sono quelli dichiarati. Un indice perso non "
                         "rompe niente subito: rende lente le query finche' l'archivio "
                         "non e' grande, e allora il sito va giu'.\n  - %s"
                         % (self.ETICHETTA, "\n  - ".join(fuori)))

    def test_i_vincoli_di_unicita_sono_quelli_congelati(self):
        self._vergine()
        fuori = differenze_insiemi("vincoli impliciti", dict(self.UNICI),
                                   vincoli_impliciti(self.db))
        self.assertEqual(fuori, [],
                         "%s: PRIMARY KEY / UNIQUE cambiati. Sono le protezioni contro i "
                         "DOPPIONI (due host con la stessa email, due riscossioni sulla "
                         "stessa prenotazione).\n  - %s"
                         % (self.ETICHETTA, "\n  - ".join(fuori)))

    def test_i_check_e_le_chiavi_esterne_sono_quelli_congelati(self):
        self._vergine()
        fuori = (differenze_insiemi("CHECK", dict(self.CHECK), check_espressioni(self.db))
                 + differenze_insiemi("chiavi esterne", dict(self.FK),
                                      chiavi_esterne(self.db)))
        self.assertEqual(fuori, [],
                         "%s: CHECK o FOREIGN KEY cambiati. Un CHECK perso lascia entrare "
                         "in archivio il dato assurdo (un importo negativo, un tipo che "
                         "non esiste) e nessuno se ne accorge.\n  - %s"
                         % (self.ETICHETTA, "\n  - ".join(fuori)))

    def test_i_trigger_sono_quelli_congelati(self):
        self._vergine()
        fuori = differenze_mappa("trigger", dict(self.TRIGGER),
                                 trigger_normalizzati(self.db))
        self.assertEqual(fuori, [],
                         "%s: i TRIGGER non sono quelli dichiarati (si confronta anche il "
                         "CORPO: un trigger svuotato non protegge nulla).\n  - %s"
                         % (self.ETICHETTA, "\n  - ".join(fuori)))

    # ---- 2. INVARIANTI TECNICI ------------------------------------------
    def test_il_file_e_in_wal(self):
        self._vergine()
        self.assertEqual(
            journal_mode(self.db), "wal",
            "%s: journal_mode del file diverso da 'wal'. Senza WAL i lettori bloccano lo "
            "scrittore: sotto carico la ricerca fa aspettare chi prenota." % self.ETICHETTA)

    def test_ogni_connessione_nasce_con_trenta_secondi_di_attesa(self):
        """Bug storico #36: col default di 5s, sotto burst, il writer non si accodava e
        tornava «database is locked» -> 503 su una prenotazione vera."""
        spia, _ = self._esercitato()
        self.assertGreater(len(spia.conn), 0,
                           "%s: la spia non ha visto NESSUNA connessione: il controllo non "
                           "starebbe verificando niente" % self.ETICHETTA)
        self.assertEqual(spia.timeout_ms(), [30000],
                         "%s: connessioni aperte con busy_timeout diverso da 30000 ms: %r"
                         % (self.ETICHETTA, spia.timeout_ms()))

    def test_nessuna_connessione_resta_aperta_dopo_le_operazioni(self):
        """Un descrittore che non si chiude e' un lock che non si rilascia: su WAL blocca
        il checkpoint e, moltiplicato per le richieste, esaurisce i descrittori."""
        spia, _ = self._esercitato()
        appese = spia.mai_chiuse()
        self.assertEqual(
            len(appese), 0,
            "%s: %d connessione(i) mai chiuse dopo le operazioni (aperte in totale: %d)"
            % (self.ETICHETTA, len(appese), len(spia.conn)))

    # ---- 3. TIPI E VINCOLI DEL DENARO -----------------------------------
    def test_l_elenco_delle_colonne_di_denaro_e_aggiornato(self):
        """Se nasce una colonna di denaro nuova, deve entrare nel contratto: altrimenti
        il controllo sui tipi la salterebbe per sempre."""
        self._vergine()
        trovate = tuple(n for n, _t in colonne_di_denaro(self.db))
        self.assertEqual(
            trovate, tuple(self.DENARO),
            "%s: le colonne che custodiscono DENARO non sono quelle dichiarate — "
            "attese %r, trovate %r" % (self.ETICHETTA, tuple(self.DENARO), trovate))

    def test_le_colonne_di_denaro_sono_intere(self):
        self._vergine()
        sbagliate = [(n, t) for n, t in colonne_di_denaro(self.db) if t != "INTEGER"]
        self.assertEqual(
            sbagliate, [],
            "%s: colonna di DENARO non INTEGER: %r. Un float in archivio e' una perdita "
            "che si scopre dopo mesi (900 centesimi che diventano 899.9999999999999)."
            % (self.ETICHETTA, sbagliate))

    def test_nessuna_colonna_ha_affinita_a_virgola_mobile(self):
        self._vergine()
        mobili = colonne_a_virgola_mobile(self.db)
        self.assertEqual(
            mobili, [],
            "%s: colonne a virgola mobile (o senza tipo) in archivio: %r"
            % (self.ETICHETTA, mobili))

    def test_ogni_tabella_ha_una_chiave_primaria(self):
        self._vergine()
        senza = tabelle_senza_chiave_primaria(self.db)
        self.assertEqual(
            senza, [],
            "%s: tabelle senza chiave primaria: %r. Senza, una riga duplicata non e' "
            "distinguibile e non si puo' correggere." % (self.ETICHETTA, senza))

    def test_i_valori_di_denaro_in_archivio_sono_interi(self):
        """La dichiarazione INTEGER non basta: SQLite accetta e CONSERVA un float dentro
        una colonna INTEGER. Qui si guarda il valore vero dopo una scrittura vera."""
        _spia, _esito = self._esercitato()
        for voce in self.DENARO:
            tab, col = voce.split(".", 1)
            tipi, quante = tipi_dei_valori(self.db, tab, col)
            self.assertGreater(quante, 0,
                               "%s: %s e' vuota dopo l'esercizio: il controllo sui tipi "
                               "non starebbe verificando niente" % (self.ETICHETTA, tab))
            self.assertEqual(tipi, ["integer"],
                             "%s: in %s ci sono valori di denaro non interi: %r"
                             % (self.ETICHETTA, voce, tipi))

    # ---- 4. L'ARCHIVIO FUNZIONA -----------------------------------------
    def test_l_archivio_scrive_e_rilegge(self):
        _spia, esito = self._esercitato()
        self.assertEqual(esito, self.atteso_esercizio(),
                         "%s: scrittura/rilettura non danno i valori attesi" % self.ETICHETTA)


# ===========================================================================
# 1. CATALOGO (fase57) — le schede vendibili
# ===========================================================================
class TestContrattoCatalogoFase57(BaseContratto, unittest.TestCase):
    ETICHETTA = "fase57 catalogo (le schede in vendita)"
    COLONNE = {
        "alloggi": (
            "id INTEGER PK1", "host_id TEXT NOT NULL", "slug TEXT NOT NULL",
            "titolo TEXT NOT NULL", "descrizione TEXT NOT NULL", "citta TEXT NOT NULL",
            "paese TEXT NOT NULL", "fuso TEXT NOT NULL", "indirizzo TEXT NOT NULL",
            "prezzo_notte_cents INTEGER NOT NULL", "capacita INTEGER NOT NULL",
            "camere INTEGER NOT NULL", "bagni INTEGER NOT NULL",
            "servizi_mask INTEGER NOT NULL", "valuta TEXT NOT NULL", "stato TEXT NOT NULL",
            "lat_micro INTEGER", "lon_micro INTEGER",
            "politica_cancellazione TEXT NOT NULL", "tassa_pp_notte_cents INTEGER NOT NULL",
            "tassa_max_notti INTEGER NOT NULL", "tassa_perc_bps INTEGER NOT NULL",
            "sconto_settimana_bps INTEGER NOT NULL", "sconto_mese_bps INTEGER NOT NULL",
            "modalita_prenotazione TEXT NOT NULL", "pin_manuale INTEGER NOT NULL",
            "paga_in_struttura INTEGER NOT NULL", "creato_ts TEXT NOT NULL",
            "aggiornato_ts TEXT NOT NULL", "cin TEXT NOT NULL"),
        "alloggio_immagini": (
            "id INTEGER PK1", "alloggio_id INTEGER NOT NULL", "url TEXT NOT NULL",
            "ordine INTEGER NOT NULL", "alt TEXT NOT NULL"),
    }
    INDICI = {
        "idx_alloggi_host": "CREATE INDEX idx_alloggi_host ON alloggi(host_id)",
        "idx_alloggi_stato_agg":
            "CREATE INDEX idx_alloggi_stato_agg ON alloggi(stato, aggiornato_ts)",
        "idx_alloggi_stato_citta":
            "CREATE INDEX idx_alloggi_stato_citta ON alloggi(stato, citta)",
        "idx_alloggi_stato_prezzo":
            "CREATE INDEX idx_alloggi_stato_prezzo ON alloggi(stato, prezzo_notte_cents)",
        "idx_img_alloggio":
            "CREATE INDEX idx_img_alloggio ON alloggio_immagini(alloggio_id, ordine)",
    }
    UNICI = {"alloggi": ("unique(slug)",), "alloggio_immagini": ()}
    CHECK = {"alloggi": (), "alloggio_immagini": ()}
    FK = {"alloggi": (),
          "alloggio_immagini": ("alloggio_id -> alloggi.id ON DELETE CASCADE",)}
    TRIGGER = {}
    DENARO = ("alloggi.prezzo_notte_cents", "alloggi.sconto_mese_bps",
              "alloggi.sconto_settimana_bps", "alloggi.tassa_max_notti",
              "alloggi.tassa_perc_bps", "alloggi.tassa_pp_notte_cents")

    def costruisci(self, percorso):
        from fase57_vetrina import crea_catalogo
        return crea_catalogo(percorso)

    def esercita(self, archivio):
        from fase57_vetrina import SchedaAlloggio
        idn = archivio.pubblica(
            SchedaAlloggio(host_id="h_a1b2c3d4", slug="trastevere-attico-vista",
                           titolo="Attico a Trastevere", citta="roma", paese="IT",
                           prezzo_notte_cents=18500, capacita=4,
                           tassa_pp_notte_cents=450),
            ({"url": "/uploads/attico_terrazza.jpg", "alt": "terrazza"},))
        d = archivio.dettaglio("trastevere-attico-vista")
        return {"id": idn, "titolo": d["titolo"], "prezzo": d["prezzo_notte_cents"],
                "valuta": d["valuta"], "capacita": d["capacita"],
                "tassa_pp": d["tassa_pp_notte_cents"],
                "immagini": [i["url"] for i in d["immagini"]],
                "citta_pubblicate": archivio.citta_pubblicate(),
                "annunci_host": archivio.conta_alloggi_host("h_a1b2c3d4")}

    def atteso_esercizio(self):
        return {"id": 1, "titolo": "Attico a Trastevere", "prezzo": 18500,
                "valuta": "EUR", "capacita": 4, "tassa_pp": 450,
                "immagini": ["/uploads/attico_terrazza.jpg"],
                "citta_pubblicate": ["roma"], "annunci_host": 1}


# ===========================================================================
# 2. INVENTARIO (fase58) — il calendario che impedisce l'overbooking
# ===========================================================================
class TestContrattoInventarioFase58(BaseContratto, unittest.TestCase):
    ETICHETTA = "fase58 inventario (il calendario anti-overbooking)"
    COLONNE = {
        "inventario": (
            "alloggio_id TEXT NOT NULL PK1", "giorno TEXT NOT NULL PK2",
            "unita_totali INTEGER NOT NULL", "unita_occupate INTEGER NOT NULL",
            "prezzo_netto_cents INTEGER NOT NULL", "chiuso INTEGER NOT NULL",
            "min_notti INTEGER NOT NULL", "aggiornato_ts TEXT NOT NULL"),
        "movimenti": (
            "idem_key TEXT PK1", "alloggio_id TEXT NOT NULL", "tipo TEXT NOT NULL",
            "esito TEXT NOT NULL", "check_in TEXT", "check_out TEXT", "origine TEXT",
            "ts TEXT NOT NULL"),
    }
    INDICI = {"ix_movimenti_blocchi": "CREATE INDEX ix_movimenti_blocchi ON "
                                      "movimenti(alloggio_id, tipo, esito, check_in)"}
    UNICI = {"inventario": ("pk(alloggio_id, giorno)",), "movimenti": ("pk(idem_key)",)}
    CHECK = {"inventario": (), "movimenti": ()}
    FK = {"inventario": (), "movimenti": ()}
    TRIGGER = {}
    DENARO = ("inventario.prezzo_netto_cents",)

    def costruisci(self, percorso):
        from fase58_channel_manager import crea_channel_manager
        return crea_channel_manager(percorso)

    def esercita(self, archivio):
        for giorno in ("2026-08-10", "2026-08-11"):
            archivio.imposta_disponibilita("trastevere-attico-vista", giorno,
                                           unita_totali=1, prezzo_netto_cents=18500,
                                           min_notti=2)
        blocco = archivio.blocca("trastevere-attico-vista", "2026-08-10", "2026-08-12",
                                 idem_key="idem_2f7c9a11")
        stato = archivio.stato_giorno("trastevere-attico-vista", "2026-08-10")
        return {"blocco_ok": blocco.ok,
                "prezzo": stato["prezzo_netto_cents"], "min_notti": stato["min_notti"],
                "occupate": stato["unita_occupate"],
                "ancora_disponibile": archivio.disponibile("trastevere-attico-vista",
                                                           "2026-08-10", "2026-08-12"),
                "giorni_a_calendario": len(archivio.calendario(
                    "trastevere-attico-vista", "2026-08-10", "2026-08-12"))}

    def atteso_esercizio(self):
        return {"blocco_ok": True, "prezzo": 18500, "min_notti": 2, "occupate": 1,
                "ancora_disponibile": False, "giorni_a_calendario": 2}


# ===========================================================================
# 3. REGISTRO HOST (fase88) — chi puo' entrare e incassare
# ===========================================================================
class TestContrattoRegistroHostFase88(BaseContratto, unittest.TestCase):
    ETICHETTA = "fase88 registro host (identita' e accesso)"
    COLONNE = {
        "host": (
            "host_id TEXT PK1", "email TEXT NOT NULL", "salt TEXT NOT NULL",
            "pw_hash TEXT NOT NULL", "ragione_sociale TEXT NOT NULL",
            "telefono TEXT NOT NULL", "line_token TEXT NOT NULL",
            "wechat_webhook TEXT NOT NULL", "telegram_chat_id TEXT NOT NULL",
            "stripe_account_id TEXT NOT NULL", "termini_versione TEXT NOT NULL",
            "termini_ts INTEGER NOT NULL", "stato TEXT NOT NULL",
            "creato_ts INTEGER NOT NULL", "codice_fiscale TEXT NOT NULL",
            "partita_iva TEXT NOT NULL", "indirizzo_fiscale TEXT NOT NULL",
            "paese TEXT NOT NULL", "iban TEXT NOT NULL", "tipo_soggetto TEXT NOT NULL",
            "data_nascita TEXT NOT NULL", "verifica_stato TEXT NOT NULL",
            "verifica_note TEXT NOT NULL", "verifica_ts TEXT NOT NULL",
            "verifica_da TEXT NOT NULL", "stripe_customer_id TEXT NOT NULL",
            "stripe_payment_method TEXT NOT NULL"),
        # ANTI-RICICLO DELLA PROMOZIONE (aggiunta il 2026-07-31, dopo che questo contratto
        # era stato scritto): impronte IRREVERSIBILI di email, telefono, codice fiscale e CIN,
        # per impedire che un host si cancelli e si ri-iscriva ripartendo dal 0% dei primi 90
        # giorni. Non contiene dati personali in chiaro: solo il risultato della firma HMAC.
        # Schema letto dal codice E confermato sull'archivio VERO in produzione.
        "host_impronte": (
            "impronta TEXT PK1", "creato_ts INTEGER NOT NULL", "ts INTEGER NOT NULL"),
    }
    INDICI = {}
    UNICI = {"host": ("pk(host_id)", "unique(email)"),
             "host_impronte": ("pk(impronta)",)}
    CHECK = {"host": (), "host_impronte": ()}
    FK = {"host": (), "host_impronte": ()}
    TRIGGER = {}
    DENARO = ()

    def costruisci(self, percorso):
        from fase88_registro_host import crea_registro_host
        return crea_registro_host(percorso, SEGRETO, orologio=lambda: ORA)

    def esercita(self, archivio):
        esito = archivio.registra("chiara.rossi@example.com", "Trastevere!2026",
                                  accetta_termini=True,
                                  ragione_sociale="Rossi Ospitalita' Srl")
        info = archivio.info_host(esito.host_id)
        return {"registrato": esito.ok,
                "login_ok": archivio.login("chiara.rossi@example.com",
                                           "Trastevere!2026").ok,
                "login_sbagliato": archivio.login("chiara.rossi@example.com",
                                                  "password-sbagliata").ok,
                "email": info["email"], "ragione_sociale": info["ragione_sociale"],
                "esiste": archivio.esiste_host(esito.host_id),
                "token_del_titolare": archivio.verifica_token(esito.token) == esito.host_id,
                "quanti": archivio.conta_host()}

    def atteso_esercizio(self):
        return {"registrato": True, "login_ok": True, "login_sbagliato": False,
                "email": "chiara.rossi@example.com",
                "ragione_sociale": "Rossi Ospitalita' Srl", "esiste": True,
                "token_del_titolare": True, "quanti": 1}

    def test_due_host_non_possono_avere_la_stessa_email(self):
        """Il vincolo UNIQUE non e' un dettaglio di schema: e' la ragione per cui il
        login sa a CHI appartiene un'email. Non basta che il CODICE rifiuti il doppione
        (lo fa gia' con una SELECT preventiva, e resterebbe verde anche senza vincolo):
        deve rifiutarlo l'ARCHIVIO, che e' l'unica difesa quando due richieste arrivano
        nello stesso istante o quando un domani si scrive da un'altra strada."""
        archivio = self._vergine()
        primo = archivio.registra("chiara.rossi@example.com", "Trastevere!2026",
                                  accetta_termini=True)
        secondo = archivio.registra("chiara.rossi@example.com", "AltraPassword!9",
                                    accetta_termini=True)
        self.assertIs(primo.ok, True)
        self.assertIs(secondo.ok, False)
        self.assertEqual(archivio.conta_host(), 1)
        con = sqlite3.connect(self.db)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("INSERT INTO host (host_id, email, salt, pw_hash, "
                            "termini_versione, termini_ts, creato_ts) "
                            "VALUES (?,?,?,?,?,?,?)",
                            ("h_gemello", "chiara.rossi@example.com", "00", "00",
                             "2026-01", ORA, ORA))
            self.assertEqual(con.execute("SELECT COUNT(*) FROM host").fetchone()[0], 1)
        finally:
            con.close()


# ===========================================================================
# 4. PAYOUT (fase131) — i soldi che devono arrivare all'host
# ===========================================================================
class TestContrattoPayoutFase131(BaseContratto, unittest.TestCase):
    ETICHETTA = "fase131 payout (i soldi dovuti all'host)"
    COLONNE = {
        "payout": ("prenotazione_id TEXT PK1", "host_id TEXT NOT NULL",
                   "minori INTEGER NOT NULL", "valuta TEXT NOT NULL",
                   "stato TEXT NOT NULL", "ts INTEGER NOT NULL"),
    }
    INDICI = {"ix_payout_host": "CREATE INDEX ix_payout_host ON payout(host_id)"}
    UNICI = {"payout": ("pk(prenotazione_id)",)}
    CHECK = {"payout": ()}
    FK = {"payout": ()}
    TRIGGER = {}
    DENARO = ("payout.minori",)

    def costruisci(self, percorso):
        from fase131_payout_dashboard import crea_payout_dashboard
        return crea_payout_dashboard(percorso, orologio=lambda: ORA)

    def esercita(self, archivio):
        archivio.registra_maturato("BV-2026-000117", "h_a1b2c3d4", 34040, "EUR")
        archivio.registra_maturato("BV-2026-000118", "h_a1b2c3d4", 51060, "EUR")
        # il bonifico parte e arriva: maturato -> in_transito -> pagato
        archivio.aggiorna_stato("BV-2026-000118", "in_transito")
        archivio.aggiorna_stato("BV-2026-000118", "pagato")
        info = archivio.info("BV-2026-000117")
        return {"minori": info["minori"], "valuta": info["valuta"],
                "stato": info["stato"], "host": info["host_id"],
                "da_pagare": archivio.da_pagare("h_a1b2c3d4", "EUR"),
                "prodotti": archivio.conta_pagati("h_a1b2c3d4")}

    def atteso_esercizio(self):
        # solo il 'maturato' e' ancora da pagare: il 'pagato' e' gia' uscito
        return {"minori": 34040, "valuta": "EUR", "stato": "maturato",
                "host": "h_a1b2c3d4", "da_pagare": 34040, "prodotti": 2}


# ===========================================================================
# 5. TASSA DI SOGGIORNO (fase147) — denaro di terzi, si versa al Comune
# ===========================================================================
class TestContrattoTassaFase147(BaseContratto, unittest.TestCase):
    ETICHETTA = "fase147 tassa di soggiorno (denaro del Comune)"
    COLONNE = {
        "tassa_regola": ("comune TEXT PK1", "regola_json TEXT NOT NULL"),
        "tassa_riscossione": ("prenotazione_id TEXT PK1", "comune TEXT NOT NULL",
                              "importo INTEGER NOT NULL", "ts INTEGER NOT NULL",
                              "stornato INTEGER NOT NULL"),
    }
    INDICI = {}
    UNICI = {"tassa_regola": ("pk(comune)",),
             "tassa_riscossione": ("pk(prenotazione_id)",)}
    CHECK = {"tassa_regola": (), "tassa_riscossione": ()}
    FK = {"tassa_regola": (), "tassa_riscossione": ()}
    TRIGGER = {}
    DENARO = ("tassa_riscossione.importo",)

    def costruisci(self, percorso):
        from fase147_tassa_comunale import crea_tassa_comunale
        return crea_tassa_comunale(percorso, orologio=lambda: ORA)

    def esercita(self, archivio):
        archivio.imposta_regola("roma", {"per_persona_notte_cents": 450, "max_notti": 10})
        return {"riscossa_1": archivio.registra_riscossione("BV-2026-000117", "roma", 900),
                "riscossa_2": archivio.registra_riscossione("BV-2026-000118", "roma", 1350),
                "totale": archivio.totale_riscosso("roma"),
                "regola": archivio.regola("roma"),
                "stornata": archivio.storna("BV-2026-000117"),
                "totale_dopo_storno": archivio.totale_riscosso("roma")}

    def atteso_esercizio(self):
        return {"riscossa_1": True, "riscossa_2": True, "totale": 2250,
                "regola": {"per_persona_notte_cents": 450, "max_notti": 10},
                "stornata": True, "totale_dopo_storno": 1350}


# ===========================================================================
# 6. DOMANDA / LISTA D'ATTESA (fase158) — il cold-start del mercato
# ===========================================================================
class TestContrattoDomandaFase158(BaseContratto, unittest.TestCase):
    ETICHETTA = "fase158 domanda (lista d'attesa per citta')"
    COLONNE = {
        "domanda": ("email TEXT NOT NULL PK1", "citta TEXT NOT NULL PK2",
                    "check_in TEXT", "check_out TEXT", "party INTEGER",
                    "ts INTEGER NOT NULL"),
    }
    INDICI = {}
    UNICI = {"domanda": ("pk(email, citta)",)}
    CHECK = {"domanda": ()}
    FK = {"domanda": ()}
    TRIGGER = {}
    DENARO = ()

    def costruisci(self, percorso):
        from fase158_domanda import crea_gestore_domanda
        return crea_gestore_domanda(percorso, orologio=lambda: ORA)

    def esercita(self, archivio):
        return {"prima": archivio.registra("ospite@example.com", "Roma",
                                           check_in="2026-08-10",
                                           check_out="2026-08-12", party=2),
                "doppione": archivio.registra("ospite@example.com", "ROMA"),
                "email_non_valida": archivio.registra("non-una-email", "Roma"),
                "conta_roma": archivio.conta("roma"),
                "conta_tutto": archivio.conta(),
                "emails": archivio.email_citta("roma")}

    def atteso_esercizio(self):
        # dedup su (email, citta) normalizzate: la seconda iscrizione non crea una riga
        return {"prima": True, "doppione": True, "email_non_valida": False,
                "conta_roma": 1, "conta_tutto": 1, "emails": ["ospite@example.com"]}


# ===========================================================================
# 7. GARANZIA / ESCROW (fase160) — i soldi trattenuti fra ospite e host
# ===========================================================================
class TestContrattoGaranziaFase160(BaseContratto, unittest.TestCase):
    ETICHETTA = "fase160 garanzia (escrow fra ospite e host)"
    COLONNE = {
        "garanzia": ("prenotazione_id TEXT PK1", "alloggio_id TEXT NOT NULL",
                     "importo_host_cents INTEGER NOT NULL",
                     "host_riceve_cents INTEGER NOT NULL",
                     "ospite_rimborso_cents INTEGER NOT NULL", "stato TEXT NOT NULL",
                     "motivo TEXT NOT NULL", "sblocco_auto_ts INTEGER NOT NULL",
                     "aperto_ts INTEGER NOT NULL", "aggiornato_ts INTEGER NOT NULL"),
    }
    INDICI = {}
    UNICI = {"garanzia": ("pk(prenotazione_id)",)}
    CHECK = {"garanzia": ()}
    FK = {"garanzia": ()}
    TRIGGER = {}
    DENARO = ("garanzia.host_riceve_cents", "garanzia.importo_host_cents",
              "garanzia.ospite_rimborso_cents")

    def costruisci(self, percorso):
        from fase160_escrow_garanzia import crea_escrow_garanzia
        return crea_escrow_garanzia(percorso, orologio=lambda: ORA)

    def esercita(self, archivio):
        archivio.apri("BV-2026-000117", 34040, alloggio_id="trastevere-attico-vista")
        archivio.apri("BV-2026-000118", 51060, alloggio_id="trastevere-attico-vista")
        archivio.contesta("BV-2026-000118", "riscaldamento guasto")
        s = archivio.stato("BV-2026-000117")
        return {"stato": s["stato"], "importo": s["importo_host_cents"],
                "unita": s["money_unit"],
                "aperte": sorted(r["prenotazione_id"] for r in archivio.aperte()),
                "contestate": sorted(r["prenotazione_id"]
                                     for r in archivio.contestate()),
                "motivo": archivio.stato("BV-2026-000118")["motivo"]}

    def atteso_esercizio(self):
        return {"stato": "in_garanzia", "importo": 34040, "unita": "cents_integer",
                "aperte": ["BV-2026-000117"], "contestate": ["BV-2026-000118"],
                "motivo": "riscaldamento guasto"}


# ===========================================================================
# 8. PENDENTI (fase162) — il hold fra «prenoto» e «ho pagato»
# ===========================================================================
class TestContrattoPendentiFase162(BaseContratto, unittest.TestCase):
    ETICHETTA = "fase162 pagamenti pendenti (il hold prima dell'incasso)"
    COLONNE = {
        "pendenti": ("riferimento TEXT PK1", "alloggio_id TEXT NOT NULL",
                     "check_in TEXT NOT NULL", "check_out TEXT NOT NULL",
                     "idem_key TEXT NOT NULL", "tassa_cents INTEGER NOT NULL",
                     "comune TEXT NOT NULL", "host_id TEXT NOT NULL",
                     "email TEXT NOT NULL", "quote_token TEXT NOT NULL",
                     "corpo_json TEXT NOT NULL", "scadenza_ts INTEGER NOT NULL",
                     "stato TEXT NOT NULL", "promemoria_ts INTEGER NOT NULL",
                     "creato_ts INTEGER NOT NULL",
                     "invito_recensione_ts INTEGER NOT NULL"),
    }
    INDICI = {}
    UNICI = {"pendenti": ("pk(riferimento)",)}
    CHECK = {"pendenti": ()}
    FK = {"pendenti": ()}
    TRIGGER = {}
    DENARO = ("pendenti.tassa_cents",)

    def costruisci(self, percorso):
        from fase162_pagamenti_pendenti import crea_pagamenti_pendenti
        return crea_pagamenti_pendenti(percorso, orologio=lambda: ORA)

    def esercita(self, archivio):
        archivio.registra("BV-2026-000117", alloggio_id="trastevere-attico-vista",
                          check_in="2026-08-10", check_out="2026-08-12",
                          idem_key="idem_2f7c9a11", tassa_cents=900, comune="roma",
                          host_id="h_a1b2c3d4", email="ospite@example.com",
                          scadenza_ts=ORA + 1200)
        archivio.registra("BV-2026-000118", alloggio_id="trastevere-attico-vista",
                          check_in="2026-09-01", check_out="2026-09-04",
                          idem_key="idem_88bb1177", scadenza_ts=ORA - 60)
        info = archivio.info("BV-2026-000117")
        return {"tassa": info["tassa_cents"], "comune": info["comune"],
                "host": info["host_id"], "stato": info["stato"],
                "vivi": sorted(r["riferimento"] for r in
                               archivio.attivi_per_alloggio("trastevere-attico-vista")),
                "scaduti": sorted(r["riferimento"] for r in archivio.scaduti()),
                "idem": sorted(archivio.idem_keys())}

    def atteso_esercizio(self):
        return {"tassa": 900, "comune": "roma", "host": "h_a1b2c3d4",
                "stato": "in_attesa", "vivi": ["BV-2026-000117"],
                "scaduti": ["BV-2026-000118"],
                "idem": ["idem_2f7c9a11", "idem_88bb1177"]}


# ===========================================================================
# 9. ACCETTAZIONI FIRMATE (fase163) — la prova legale del consenso
# ===========================================================================
class TestContrattoAccettazioniFase163(BaseContratto, unittest.TestCase):
    ETICHETTA = "fase163 accettazioni (prova legale del consenso)"
    COLONNE = {
        "accettazioni": ("id INTEGER PK1", "host_id TEXT NOT NULL",
                         "documento TEXT NOT NULL", "versione TEXT NOT NULL",
                         "doc_sha256 TEXT NOT NULL", "lang TEXT NOT NULL",
                         "ip TEXT NOT NULL", "user_agent TEXT NOT NULL",
                         "vessatorie INTEGER NOT NULL", "accettato_ts INTEGER NOT NULL",
                         "firma TEXT NOT NULL", "riferimento TEXT NOT NULL"),
    }
    INDICI = {"idx_acc_host": "CREATE INDEX idx_acc_host ON accettazioni(host_id)"}
    UNICI = {"accettazioni": ()}
    CHECK = {"accettazioni": ()}
    FK = {"accettazioni": ()}
    TRIGGER = {}
    DENARO = ()

    def costruisci(self, percorso):
        from fase163_accettazioni import crea_registro_accettazioni
        return crea_registro_accettazioni(percorso, SEGRETO, now=lambda: ORA)

    def esercita(self, archivio):
        esito = archivio.registra("h_a1b2c3d4", ip="203.0.113.9",
                                  user_agent="Mozilla/5.0", vessatorie=True,
                                  riferimento="vs_1a2b3c")
        voci = archivio.elenco("h_a1b2c3d4")
        return {"ok": esito["ok"], "id": esito["id"], "lunghezza_firma": len(esito["firma"]),
                "documento": voci[0]["documento"], "vessatorie": voci[0]["vessatorie"],
                "riferimento": voci[0]["riferimento"], "ip": voci[0]["ip"],
                "quante": archivio.conta()}

    def atteso_esercizio(self):
        return {"ok": True, "id": 1, "lunghezza_firma": 64,
                "documento": "contratto_host", "vessatorie": True,
                "riferimento": "vs_1a2b3c", "ip": "203.0.113.9", "quante": 1}


# ===========================================================================
# 10. LIBRO GIORNALE (fase177) — la contabilita' immutabile
# ===========================================================================
class TestContrattoGiornaleFase177(BaseContratto, unittest.TestCase):
    ETICHETTA = "fase177 financial controller (giornale, note, debiti)"
    COLONNE = {
        "libro_giornale": ("seq INTEGER PK1", "evento_id TEXT NOT NULL",
                           "ts INTEGER NOT NULL", "tipo TEXT NOT NULL",
                           "riferimento TEXT NOT NULL", "soggetto TEXT NOT NULL",
                           "conto_dare TEXT NOT NULL", "conto_avere TEXT NOT NULL",
                           "importo_cents INTEGER NOT NULL", "valuta TEXT NOT NULL",
                           "causale TEXT NOT NULL", "emittente TEXT NOT NULL",
                           "prev_hash TEXT NOT NULL", "hash TEXT NOT NULL"),
        "note": ("nota_id TEXT PK1", "tipo TEXT NOT NULL", "riferimento TEXT NOT NULL",
                 "causale TEXT NOT NULL", "ts INTEGER NOT NULL",
                 "emittente TEXT NOT NULL", "soggetto TEXT NOT NULL",
                 "importo_cents INTEGER NOT NULL", "valuta TEXT NOT NULL",
                 "stato TEXT NOT NULL", "storno_di TEXT",
                 "giornale_seq INTEGER NOT NULL"),
        "debiti": ("debito_id TEXT PK1", "host_id TEXT NOT NULL",
                   "riferimento TEXT NOT NULL", "residuo_cents INTEGER NOT NULL",
                   "valuta TEXT NOT NULL", "stato TEXT NOT NULL",
                   "tentativi INTEGER NOT NULL", "prossimo_ts INTEGER",
                   "aggiornato_ts INTEGER NOT NULL"),
    }
    INDICI = {
        "ix_debiti_host": "CREATE INDEX ix_debiti_host ON debiti(host_id, stato)",
        "ix_lg_rif": "CREATE INDEX ix_lg_rif ON libro_giornale(riferimento)",
        "ix_lg_soggetto": "CREATE INDEX ix_lg_soggetto ON libro_giornale(soggetto)",
        "ix_note_rif": "CREATE INDEX ix_note_rif ON note(riferimento)",
    }
    UNICI = {"libro_giornale": ("unique(evento_id)",), "note": ("pk(nota_id)",),
             "debiti": ("pk(debito_id)",)}
    CHECK = {"libro_giornale": ("importo_cents > 0",),
             "note": ("importo_cents > 0", "tipo IN ('credito','debito')"),
             "debiti": ("residuo_cents >= 0",)}
    FK = {"libro_giornale": (), "note": (), "debiti": ()}
    TRIGGER = {
        "lg_no_delete": "CREATE TRIGGER lg_no_delete BEFORE DELETE ON libro_giornale "
                        "BEGIN SELECT RAISE(ABORT, 'libro giornale: DELETE vietato'); END",
        "lg_no_update": "CREATE TRIGGER lg_no_update BEFORE UPDATE ON libro_giornale "
                        "BEGIN SELECT RAISE(ABORT, 'libro giornale: UPDATE vietato'); END",
    }
    DENARO = ("debiti.residuo_cents", "libro_giornale.importo_cents",
              "note.importo_cents")

    def costruisci(self, percorso):
        from fase177_financial_controller import crea_financial_controller
        return crea_financial_controller(percorso, orologio=lambda: ORA)

    def esercita(self, archivio):
        from fase131_payout_dashboard import crea_payout_dashboard
        payout = crea_payout_dashboard(os.path.join(self.dir, "payout.db"),
                                       orologio=lambda: ORA)
        payout.inizializza_schema()
        archivio.registra(evento_id="inc:BV-2026-000117", tipo="incasso",
                          riferimento="BV-2026-000117", soggetto="ospite",
                          conto_dare="cassa", conto_avere="debiti_v_host",
                          importo_cents=37000, valuta="EUR",
                          causale="incasso soggiorno", emittente="sistema")
        penale = archivio.processa_penale(riferimento="BV-2026-000900",
                                          host_id="h_a1b2c3d4", penale_cents=5550,
                                          valuta="EUR", payout=payout)
        catena = archivio.verifica_catena()
        return {"catena_ok": catena["ok"], "righe": catena["righe"],
                "movimenti": [(m["tipo"], m["importo_cents"])
                              for m in archivio.movimenti("BV-2026-000117")],
                "penale": (penale["penale_cents"], penale["offset_cents"],
                           penale["residuo_cents"]),
                "nota": archivio.note_per_riferimento("BV-2026-000900")[0]["importo_cents"],
                "debito": archivio.debiti_host("h_a1b2c3d4")[0]["residuo_cents"],
                "quanti": archivio.conta_movimenti()}

    def atteso_esercizio(self):
        return {"catena_ok": True, "righe": 2,
                "movimenti": [("incasso", 37000)],
                "penale": (5550, 0, 5550), "nota": 5550, "debito": 5550, "quanti": 2}

    def test_i_trigger_rendono_il_giornale_davvero_immutabile(self):
        """Il contratto dice che i due trigger ci sono; qui si prova che FUNZIONANO —
        e' la differenza fra una riga di schema e una protezione."""
        archivio = self._vergine()
        archivio.registra(evento_id="inc:BV-1", tipo="incasso", riferimento="BV-1",
                          soggetto="ospite", conto_dare="cassa",
                          conto_avere="debiti_v_host", importo_cents=37000,
                          valuta="EUR", causale="incasso", emittente="sistema")
        con = sqlite3.connect(self.db)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("UPDATE libro_giornale SET importo_cents=1 WHERE seq=1")
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("DELETE FROM libro_giornale WHERE seq=1")
            self.assertEqual(
                con.execute("SELECT importo_cents FROM libro_giornale").fetchall(),
                [(37000,)])
        finally:
            con.close()

    def test_il_check_rifiuta_un_importo_non_positivo(self):
        """`CHECK (importo_cents > 0)` e' l'ultima rete sotto il codice: se un giorno una
        via nuova scrivesse 0 o un negativo, l'archivio deve rifiutarlo."""
        self._vergine()
        con = sqlite3.connect(self.db)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute(
                    "INSERT INTO libro_giornale (evento_id, ts, tipo, riferimento, "
                    "soggetto, conto_dare, conto_avere, importo_cents, valuta, causale, "
                    "emittente, prev_hash, hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("x", ORA, "incasso", "BV-1", "ospite", "cassa", "debiti_v_host",
                     0, "EUR", "c", "sistema", "GENESI", "h"))
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM libro_giornale").fetchone()[0], 0)
        finally:
            con.close()


# ===========================================================================
# 11. OPERATORI ADMIN (fase192) — chi puo' toccare i soldi dal pannello
# ===========================================================================
class TestContrattoAdminAccountsFase192(BaseContratto, unittest.TestCase):
    ETICHETTA = "fase192 operatori admin (ruoli del pannello)"
    COLONNE = {
        "admin_account": ("email TEXT PK1", "salt TEXT NOT NULL", "pw_hash TEXT NOT NULL",
                          "ruolo TEXT NOT NULL", "attivo INTEGER NOT NULL",
                          "creato_ts INTEGER NOT NULL", "creato_da TEXT NOT NULL"),
    }
    INDICI = {}
    UNICI = {"admin_account": ("pk(email)",)}
    CHECK = {"admin_account": ()}
    FK = {"admin_account": ()}
    TRIGGER = {}
    DENARO = ()

    def costruisci(self, percorso):
        from fase192_admin_accounts import crea_admin_accounts
        return crea_admin_accounts(percorso, orologio=lambda: ORA)

    def esercita(self, archivio):
        creato = archivio.crea("operatore@example.com", "password-lunga-8+", "supporto")
        buono = archivio.verifica("operatore@example.com", "password-lunga-8+")
        cattivo = archivio.verifica("operatore@example.com", "password-sbagliata")
        archivio.revoca("operatore@example.com")
        return {"creato": creato["ok"], "ruolo": creato["ruolo"],
                "verifica_ok": buono["ok"], "verifica_ruolo": buono["ruolo"],
                "verifica_cattiva": cattivo["ok"],
                "dopo_revoca": archivio.verifica("operatore@example.com",
                                                 "password-lunga-8+")["ok"],
                "ruolo_attivo": archivio.ruolo_attivo("operatore@example.com"),
                "quanti": len(archivio.lista())}

    def atteso_esercizio(self):
        return {"creato": True, "ruolo": "supporto", "verifica_ok": True,
                "verifica_ruolo": "supporto", "verifica_cattiva": False,
                "dopo_revoca": False, "ruolo_attivo": None, "quanti": 1}


# ===========================================================================
# 12. PARTNER (fase201) — candidature con consenso GDPR
# ===========================================================================
class TestContrattoPartnerFase201(BaseContratto, unittest.TestCase):
    ETICHETTA = "fase201 partner (candidature con consenso)"
    COLONNE = {
        "partner": ("email TEXT PK1", "nome TEXT NOT NULL", "tipo TEXT NOT NULL",
                    "citta TEXT", "messaggio TEXT", "consenso INTEGER NOT NULL",
                    "ts INTEGER NOT NULL"),
    }
    INDICI = {}
    UNICI = {"partner": ("pk(email)",)}
    CHECK = {"partner": ()}
    FK = {"partner": ()}
    TRIGGER = {}
    DENARO = ()

    def costruisci(self, percorso):
        from fase201_partner import crea_gestore_partner
        return crea_gestore_partner(percorso, orologio=lambda: ORA)

    def esercita(self, archivio):
        con_consenso = archivio.registra("Studio Rossi", "studio@example.com", "agenzia",
                                         citta="Roma", messaggio="Gestiamo 12 alloggi",
                                         consenso=True)
        senza = archivio.registra("Studio Bianchi", "bianchi@example.com", "agenzia",
                                  consenso=False)
        voci = archivio.candidati()
        return {"con_consenso": con_consenso, "senza_consenso": senza,
                "quanti": archivio.conta(),
                "email": [v["email"] for v in voci], "citta": voci[0]["citta"]}

    def atteso_esercizio(self):
        # GDPR: senza consenso ESPLICITO non si scrive NULLA
        return {"con_consenso": {"ok": True}, "senza_consenso": {"errore": "consenso_richiesto"},
                "quanti": 1, "email": ["studio@example.com"], "citta": "Roma"}


# ===========================================================================
# 13. CODA INTELLIGENTE (fase67) — depositi degli ospiti in lista
# ===========================================================================
class TestContrattoCodaFase67(BaseContratto, unittest.TestCase):
    ETICHETTA = "fase67 coda intelligente (depositi degli ospiti in lista)"
    COLONNE = {
        "coda": ("id INTEGER PK1", "alloggio_id TEXT NOT NULL", "finestra TEXT NOT NULL",
                 "ospite_id TEXT NOT NULL", "deposito_cents INTEGER NOT NULL",
                 "voucher_cents INTEGER NOT NULL", "stato TEXT NOT NULL",
                 "offerto_da INTEGER", "creato_ts TEXT NOT NULL"),
        "liberazioni": ("alloggio_id TEXT PK1", "liberati INTEGER NOT NULL",
                        "non_liberati INTEGER NOT NULL"),
    }
    INDICI = {"idx_coda_chiave": "CREATE INDEX idx_coda_chiave ON "
                                 "coda(alloggio_id, finestra, stato, id)"}
    UNICI = {"coda": ("unique(alloggio_id, finestra, ospite_id)",),
             "liberazioni": ("pk(alloggio_id)",)}
    CHECK = {"coda": (), "liberazioni": ()}
    FK = {"coda": (), "liberazioni": ()}
    TRIGGER = {}
    DENARO = ("coda.deposito_cents", "coda.voucher_cents")

    def costruisci(self, percorso):
        from fase67_coda_intelligente import crea_gestore_coda
        return crea_gestore_coda(percorso, orologio=lambda: ORA)

    def esercita(self, archivio):
        primo = archivio.iscrivi("trastevere-attico-vista", "2026-08-10", "2026-08-12",
                                 "osp_1")
        secondo = archivio.iscrivi("trastevere-attico-vista", "2026-08-10", "2026-08-12",
                                   "osp_2")
        ripetuto = archivio.iscrivi("trastevere-attico-vista", "2026-08-10", "2026-08-12",
                                    "osp_1")
        archivio.registra_liberazione("trastevere-attico-vista", True)
        coda = archivio.stato_coda("trastevere-attico-vista", "2026-08-10", "2026-08-12")
        return {"primo": (primo.ok, primo.posizione), "secondo": (secondo.ok, secondo.posizione),
                "ripetuto_idempotente": ripetuto.idempotente,
                "posizione_1": archivio.posizione("trastevere-attico-vista", "2026-08-10",
                                                  "2026-08-12", "osp_1"),
                "in_coda": [(r["ospite_id"], r["stato"], r["deposito_cents"],
                             r["voucher_cents"]) for r in coda],
                "prob_bps": archivio.prob_liberazione_bps("trastevere-attico-vista")}

    def atteso_esercizio(self):
        # un solo campione (< min_campione=20): la stima resta fail-closed a 0 bps
        return {"primo": (True, 1), "secondo": (True, 2), "ripetuto_idempotente": True,
                "posizione_1": 1,
                "in_coda": [("osp_1", "in_coda", 2000, 2500),
                            ("osp_2", "in_coda", 2000, 2500)],
                "prob_bps": 0}


# ===========================================================================
# 14. SPLIT DI GRUPPO (fase65) — il conto diviso fra amici
# ===========================================================================
class TestContrattoSplitFase65(BaseContratto, unittest.TestCase):
    ETICHETTA = "fase65 split di gruppo (conto diviso)"
    COLONNE = {
        "conti": ("conto_id TEXT PK1", "prenotazione_id TEXT NOT NULL",
                  "alloggio_id TEXT NOT NULL", "totale_cents INTEGER NOT NULL",
                  "stato TEXT NOT NULL", "scadenza INTEGER", "creato_ts TEXT NOT NULL"),
        "quote": ("conto_id TEXT NOT NULL PK1", "partecipante_id TEXT NOT NULL PK2",
                  "dovuto_cents INTEGER NOT NULL", "pagato INTEGER NOT NULL",
                  "pagamento_idem TEXT"),
    }
    INDICI = {"ix_conti_pren": "CREATE INDEX ix_conti_pren ON conti(prenotazione_id, stato)"}
    UNICI = {"conti": ("pk(conto_id)",), "quote": ("pk(conto_id, partecipante_id)",)}
    CHECK = {"conti": (), "quote": ()}
    FK = {"conti": (), "quote": ()}
    TRIGGER = {}
    DENARO = ("conti.totale_cents", "quote.dovuto_cents")

    def costruisci(self, percorso):
        from fase65_split_payment import crea_gestore_split
        return crea_gestore_split(percorso, orologio=lambda: ORA)

    def esercita(self, archivio):
        conto_id = archivio.crea_conto("BV-2026-000117", "trastevere-attico-vista",
                                       30001, ("anna", "bruno", "carla"),
                                       conto_id="c_collaudo")
        pagata = archivio.registra_pagamento("c_collaudo", "anna", idem_key="idem_anna")
        stato = archivio.stato_conto("c_collaudo")
        return {"conto_id": conto_id, "quota_pagata": pagata.ok,
                "totale": stato["totale_cents"],
                "raccolto": stato["raccolto_cents"], "mancante": stato["mancante_cents"],
                "quote": [(q["partecipante_id"], q["dovuto_cents"], q["pagato"])
                          for q in stato["quote"]],
                "completato": stato["completato"]}

    def atteso_esercizio(self):
        # 30001 / 3 = 10001 + 10000 + 10000 (largest remainder: mai un centesimo perso)
        return {"conto_id": "c_collaudo", "quota_pagata": True, "totale": 30001,
                "raccolto": 10001, "mancante": 20000,
                "quote": [("anna", 10001, True), ("bruno", 10000, False),
                          ("carla", 10000, False)],
                "completato": False}


# ===========================================================================
# 15. MESSAGGISTICA (fase113) — le conversazioni host/ospite
# ===========================================================================
class TestContrattoMessaggisticaFase113(BaseContratto, unittest.TestCase):
    ETICHETTA = "fase113 messaggistica (conversazioni host/ospite)"
    COLONNE = {
        "messaggi": ("id INTEGER PK1", "prenotazione_id TEXT NOT NULL",
                     "host_id TEXT NOT NULL", "guest_id TEXT NOT NULL",
                     "mittente TEXT NOT NULL", "testo TEXT NOT NULL",
                     "ts INTEGER NOT NULL", "letto INTEGER NOT NULL"),
    }
    INDICI = {"ix_msg_pren": "CREATE INDEX ix_msg_pren ON messaggi(prenotazione_id, id)"}
    UNICI = {"messaggi": ()}
    CHECK = {"messaggi": ()}
    FK = {"messaggi": ()}
    TRIGGER = {}
    DENARO = ()

    def costruisci(self, percorso):
        from fase113_messaggistica import crea_messaggistica
        return crea_messaggistica(percorso, orologio=lambda: ORA)

    def esercita(self, archivio):
        scritto = archivio.invia("BV-2026-000117", "h_a1b2c3d4", "g_ospite",
                                 "h_a1b2c3d4", "Benvenuta, le chiavi sono in cassetta")
        estraneo = archivio.invia("BV-2026-000117", "h_a1b2c3d4", "g_ospite",
                                  "h_intruso", "fatemi entrare")
        thread = archivio.thread("BV-2026-000117", "h_a1b2c3d4")
        return {"scritto": scritto, "estraneo_respinto": estraneo,
                "quanti": len(thread), "mittente": thread[0]["mittente"],
                "testo": thread[0]["testo"], "ts": thread[0]["ts"],
                "del_host": archivio.conta_messaggi_host("h_a1b2c3d4")}

    def atteso_esercizio(self):
        return {"scritto": True, "estraneo_respinto": False, "quanti": 1,
                "mittente": "h_a1b2c3d4",
                "testo": "Benvenuta, le chiavi sono in cassetta", "ts": ORA,
                "del_host": 1}


# ===========================================================================
# 16. KYC HOST (fase143) — l'esito della verifica identita' (MAI i documenti)
# ===========================================================================
class TestContrattoKycFase143(BaseContratto, unittest.TestCase):
    ETICHETTA = "fase143 KYC host (esito verifica, mai i documenti)"
    COLONNE = {
        "kyc": ("host_id TEXT PK1", "stato TEXT NOT NULL", "session_ref TEXT NOT NULL",
                "ts INTEGER NOT NULL"),
    }
    INDICI = {}
    UNICI = {"kyc": ("pk(host_id)",)}
    CHECK = {"kyc": ()}
    FK = {"kyc": ()}
    TRIGGER = {}
    DENARO = ()

    def costruisci(self, percorso):
        from fase143_kyc_host import crea_kyc_host
        return crea_kyc_host(percorso, orologio=lambda: ORA)

    def esercita(self, archivio):
        avviato = archivio.registra_avvio("h_a1b2c3d4", "vs_1a2b3c")
        in_corso = archivio.stato("h_a1b2c3d4")
        archivio.conferma("h_a1b2c3d4", "verificato")
        return {"avviato": avviato, "stato_iniziale": in_corso,
                "stato_finale": archivio.stato("h_a1b2c3d4"),
                "verificato": archivio.verificato("h_a1b2c3d4"),
                "sessione": archivio.sessione("h_a1b2c3d4"),
                "sconosciuto": archivio.stato("h_mai_visto")}

    def atteso_esercizio(self):
        return {"avviato": True, "stato_iniziale": "in_corso",
                "stato_finale": "verificato", "verificato": True,
                "sessione": "vs_1a2b3c", "sconosciuto": "non_avviata"}


# ===========================================================================
# 17. DEPOSITO CAUZIONALE (fase149) — la pre-autorizzazione sulla carta
# ===========================================================================
class TestContrattoDepositoFase149(BaseContratto, unittest.TestCase):
    ETICHETTA = "fase149 deposito cauzionale (pre-autorizzazione carta)"
    COLONNE = {
        "cauzione": ("prenotazione_id TEXT PK1", "psp_ref TEXT NOT NULL",
                     "autorizzato INTEGER NOT NULL", "catturato INTEGER NOT NULL",
                     "stato TEXT NOT NULL", "ts INTEGER NOT NULL"),
    }
    INDICI = {}
    UNICI = {"cauzione": ("pk(prenotazione_id)",)}
    CHECK = {"cauzione": ()}
    FK = {"cauzione": ()}
    TRIGGER = {}
    DENARO = ("cauzione.autorizzato", "cauzione.catturato")

    def costruisci(self, percorso):
        from fase149_deposito_cauzionale import crea_deposito_cauzionale
        return crea_deposito_cauzionale(percorso, capture=lambda *a, **k: True,
                                        release=lambda *a, **k: True,
                                        orologio=lambda: ORA)

    def esercita(self, archivio):
        autorizzato = archivio.autorizza("BV-2026-000117", "pi_3Nabcdef", 20000)
        catturato = archivio.cattura_danno("BV-2026-000117", 4500)
        s = archivio.stato("BV-2026-000117")
        return {"autorizzato": autorizzato, "catturato": catturato,
                "psp_ref": s["psp_ref"], "autorizzato_cents": s["autorizzato_cents"],
                "catturato_cents": s["catturato_cents"],
                "rilasciato_cents": s["rilasciato_cents"], "stato": s["stato"],
                "sconosciuto": archivio.stato("BV-mai-vista")}

    def atteso_esercizio(self):
        return {"autorizzato": True, "catturato": True, "psp_ref": "pi_3Nabcdef",
                "autorizzato_cents": 20000, "catturato_cents": 4500,
                "rilasciato_cents": 15500, "stato": "catturato_parziale",
                "sconosciuto": {}}


# ===========================================================================
# LA PROVA CHE I CONTROLLI SANNO FALLIRE (permanente, ripetibile)
# ---------------------------------------------------------------------------
# Ogni guardia qui sopra viene messa davanti al guasto che dovrebbe vedere. Senza
# questa classe, i 200+ verdi sarebbero soltanto «non ho visto niente».
# ===========================================================================
SANO = (
    """CREATE TABLE pagamenti (
            riferimento TEXT PRIMARY KEY,
            host_id TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            importo_cents INTEGER NOT NULL CHECK (importo_cents > 0),
            ts INTEGER NOT NULL)""",
    """CREATE TABLE righe (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            riferimento TEXT NOT NULL,
            FOREIGN KEY (riferimento) REFERENCES pagamenti(riferimento) ON DELETE CASCADE)""",
    "CREATE INDEX ix_pag_host ON pagamenti(host_id)",
    "CREATE TRIGGER pag_no_delete BEFORE DELETE ON pagamenti "
    "BEGIN SELECT RAISE(ABORT, 'vietato'); END",
)
RIGA_SANA = ("INSERT INTO pagamenti (riferimento, host_id, email, importo_cents, ts) "
             "VALUES ('BV-1', 'h_1', 'a@example.com', 37000, %d)" % ORA)

COLONNE_SANE = ("riferimento TEXT PK1", "host_id TEXT NOT NULL", "email TEXT NOT NULL",
                "importo_cents INTEGER NOT NULL", "ts INTEGER NOT NULL")


def _scrivi(percorso, istruzioni, wal=True):
    con = sqlite3.connect(percorso)
    try:
        if wal:
            con.execute("PRAGMA journal_mode=WAL")
        with con:
            for i in istruzioni:
                con.execute(i)
    finally:
        con.close()


class TestIlControlloSaFallire(unittest.TestCase):
    """Ogni metodo: prima si prova che sull'archivio SANO il controllo tace, poi si
    inietta UN guasto e si pretende il rosso, con il messaggio giusto."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="rosso_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.sano = os.path.join(self.dir, "sano.db")
        _scrivi(self.sano, SANO + (RIGA_SANA,))

    def _guasto(self, nome, istruzioni, wal=True):
        p = os.path.join(self.dir, nome + ".db")
        _scrivi(p, istruzioni, wal=wal)
        return p

    # ---- schema ----------------------------------------------------------
    def test_riconosce_una_colonna_rinominata(self):
        self.assertEqual(
            differenze_colonne("pagamenti", COLONNE_SANE,
                               descrittori_colonne(self.sano, "pagamenti")), [])
        guasto = self._guasto("rinominata", (
            "CREATE TABLE pagamenti (riferimento TEXT PRIMARY KEY, host TEXT NOT NULL, "
            "email TEXT NOT NULL UNIQUE, importo_cents INTEGER NOT NULL, "
            "ts INTEGER NOT NULL)",))
        fuori = differenze_colonne("pagamenti", COLONNE_SANE,
                                   descrittori_colonne(guasto, "pagamenti"))
        self.assertEqual(len(fuori), 2, fuori)
        self.assertIn("pagamenti.host_id: colonna SPARITA", fuori[0])
        self.assertIn("pagamenti.host: colonna NUOVA non dichiarata", fuori[1])

    def test_riconosce_un_tipo_cambiato_in_virgola_mobile(self):
        guasto = self._guasto("reale", (
            "CREATE TABLE pagamenti (riferimento TEXT PRIMARY KEY, host_id TEXT NOT NULL, "
            "email TEXT NOT NULL UNIQUE, importo_cents REAL NOT NULL, "
            "ts INTEGER NOT NULL)",))
        fuori = differenze_colonne("pagamenti", COLONNE_SANE,
                                   descrittori_colonne(guasto, "pagamenti"))
        self.assertEqual(len(fuori), 1, fuori)
        self.assertIn('atteso "importo_cents INTEGER NOT NULL", '
                      'trovato "importo_cents REAL NOT NULL"', fuori[0])
        self.assertEqual(colonne_a_virgola_mobile(self.sano), [])
        self.assertEqual(colonne_a_virgola_mobile(guasto),
                         ["pagamenti.importo_cents REAL"])
        self.assertEqual([n for n, t in colonne_di_denaro(guasto) if t != "INTEGER"],
                         ["pagamenti.importo_cents"])

    def test_riconosce_una_colonna_di_denaro_nuova_non_dichiarata(self):
        guasto = self._guasto("nuovo_denaro", (
            "CREATE TABLE pagamenti (riferimento TEXT PRIMARY KEY, host_id TEXT NOT NULL, "
            "email TEXT NOT NULL UNIQUE, importo_cents INTEGER NOT NULL, "
            "mancia_cents INTEGER NOT NULL, ts INTEGER NOT NULL)",))
        self.assertEqual([n for n, _t in colonne_di_denaro(self.sano)],
                         ["pagamenti.importo_cents"])
        self.assertEqual([n for n, _t in colonne_di_denaro(guasto)],
                         ["pagamenti.importo_cents", "pagamenti.mancia_cents"])

    def test_riconosce_un_indice_sparito(self):
        self.assertEqual(differenze_mappa("indice", indici_espliciti(self.sano),
                                          indici_espliciti(self.sano)), [])
        guasto = self._guasto("senza_indice", SANO[:2] + SANO[3:])
        fuori = differenze_mappa("indice", indici_espliciti(self.sano),
                                 indici_espliciti(guasto))
        self.assertEqual(len(fuori), 1, fuori)
        self.assertIn("indice SPARITO: ix_pag_host", fuori[0])

    def test_riconosce_un_trigger_sparito_e_uno_svuotato(self):
        guasto = self._guasto("senza_trigger", SANO[:3])
        fuori = differenze_mappa("trigger", trigger_normalizzati(self.sano),
                                 trigger_normalizzati(guasto))
        self.assertEqual(len(fuori), 1, fuori)
        self.assertIn("trigger SPARITO: pag_no_delete", fuori[0])
        # e un trigger che c'e' ma non protegge piu' nulla
        svuotato = self._guasto("trigger_svuotato", SANO[:3] + (
            "CREATE TRIGGER pag_no_delete BEFORE DELETE ON pagamenti "
            "BEGIN SELECT 1; END",))
        fuori2 = differenze_mappa("trigger", trigger_normalizzati(self.sano),
                                  trigger_normalizzati(svuotato))
        self.assertEqual(len(fuori2), 1, fuori2)
        self.assertIn("trigger CAMBIATO: pag_no_delete", fuori2[0])

    def test_riconosce_un_vincolo_di_unicita_perso(self):
        self.assertEqual(
            differenze_insiemi("vincoli impliciti", vincoli_impliciti(self.sano),
                               vincoli_impliciti(self.sano)), [])
        guasto = self._guasto("senza_unique", (
            "CREATE TABLE pagamenti (riferimento TEXT PRIMARY KEY, host_id TEXT NOT NULL, "
            "email TEXT NOT NULL, importo_cents INTEGER NOT NULL, ts INTEGER NOT NULL)",))
        fuori = differenze_insiemi("vincoli impliciti",
                                   {"pagamenti": vincoli_impliciti(self.sano)["pagamenti"]},
                                   {"pagamenti": vincoli_impliciti(guasto)["pagamenti"]})
        self.assertEqual(fuori, ["pagamenti: vincoli impliciti spariti: "
                                 "('unique(email)',)"])

    def test_riconosce_un_check_perso(self):
        guasto = self._guasto("senza_check", (
            "CREATE TABLE pagamenti (riferimento TEXT PRIMARY KEY, host_id TEXT NOT NULL, "
            "email TEXT NOT NULL UNIQUE, importo_cents INTEGER NOT NULL, "
            "ts INTEGER NOT NULL)",))
        self.assertEqual(check_espressioni(self.sano)["pagamenti"],
                         ("importo_cents > 0",))
        fuori = differenze_insiemi("CHECK",
                                   {"pagamenti": ("importo_cents > 0",)},
                                   {"pagamenti": check_espressioni(guasto)["pagamenti"]})
        self.assertEqual(fuori, ["pagamenti: CHECK spariti: ('importo_cents > 0',)"])

    def test_riconosce_una_chiave_esterna_persa(self):
        self.assertEqual(chiavi_esterne(self.sano)["righe"],
                         ("riferimento -> pagamenti.riferimento ON DELETE CASCADE",))
        guasto = self._guasto("senza_fk", SANO[:1] + (
            "CREATE TABLE righe (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "riferimento TEXT NOT NULL)",) + SANO[2:])
        fuori = differenze_insiemi("chiavi esterne",
                                   {"righe": chiavi_esterne(self.sano)["righe"]},
                                   {"righe": chiavi_esterne(guasto)["righe"]})
        self.assertEqual(len(fuori), 1, fuori)
        self.assertIn("righe: chiavi esterne spariti", fuori[0])

    def test_riconosce_una_tabella_senza_chiave_primaria(self):
        self.assertEqual(tabelle_senza_chiave_primaria(self.sano), [])
        guasto = self._guasto("senza_pk", (
            "CREATE TABLE pagamenti (riferimento TEXT, host_id TEXT NOT NULL, "
            "importo_cents INTEGER NOT NULL)",))
        self.assertEqual(tabelle_senza_chiave_primaria(guasto), ["pagamenti"])

    def test_riconosce_il_wal_spento(self):
        self.assertEqual(journal_mode(self.sano), "wal")
        guasto = self._guasto("senza_wal", SANO, wal=False)
        self.assertEqual(journal_mode(guasto), "delete")

    def test_riconosce_un_valore_a_virgola_mobile_in_archivio(self):
        """SQLite ACCETTA e conserva un float dentro una colonna INTEGER: la
        dichiarazione da sola non protegge, serve guardare il valore."""
        self.assertEqual(tipi_dei_valori(self.sano, "pagamenti", "importo_cents"),
                         (["integer"], 1))
        guasto = self._guasto("float_dentro", SANO)
        con = sqlite3.connect(guasto)
        try:
            with con:
                con.execute("INSERT INTO pagamenti (riferimento, host_id, email, "
                            "importo_cents, ts) VALUES ('BV-2','h_1','b@example.com',"
                            "899.9999999999999, ?)", (ORA,))
        finally:
            con.close()
        self.assertEqual(tipi_dei_valori(guasto, "pagamenti", "importo_cents"),
                         (["real"], 1))

    def test_riconosce_una_connessione_mai_chiusa(self):
        spia = Spia()
        with spia_connessioni(spia):
            buona = sqlite3.connect(self.sano, timeout=30)
            buona.execute("SELECT 1").fetchone()
            buona.close()
            self.assertEqual(spia.mai_chiuse(), [])
            cattiva = sqlite3.connect(self.sano, timeout=30)   # dimenticata aperta
            cattiva.execute("SELECT 1").fetchone()
            self.assertEqual(len(spia.mai_chiuse()), 1)
        self.assertEqual(len(spia.conn), 2)

    def test_riconosce_il_timeout_sbagliato(self):
        spia = Spia()
        with spia_connessioni(spia):
            buona = sqlite3.connect(self.sano, timeout=30)
            buona.close()
            self.assertEqual(spia.timeout_ms(), [30000])
            cattiva = sqlite3.connect(self.sano)               # default: 5 secondi
            cattiva.close()
        self.assertEqual(spia.timeout_ms(), [5000, 30000])

    def test_la_spia_rimette_a_posto_sqlite3(self):
        """Se la spia non restituisse `sqlite3.connect` originale, avvelenerebbe tutti i
        test successivi della suite: sarebbe un difetto peggiore di quelli che cerca."""
        prima = sqlite3.connect
        try:
            with spia_connessioni(Spia()):
                self.assertIsNot(sqlite3.connect, prima)
                raise RuntimeError("guasto durante l'uso della spia")
        except RuntimeError:
            pass
        self.assertIs(sqlite3.connect, prima)


# ===========================================================================
# NESSUN ARCHIVIO PUO' NASCERE SENZA CONTRATTO
# ===========================================================================
class TestOgniArchivioHaIlSuoContratto(unittest.TestCase):
    """Cricchetto di completezza: gli archivi del prodotto sono dichiarati in
    `ConfigCasaVIP` come campi `db_*`. Se ne nasce uno nuovo, o va congelato qui, o va
    messo per iscritto fra quelli ancora scoperti: quello che non e' scritto da nessuna
    parte e' esattamente cio' che si perde."""

    # archivio (campo di configurazione) -> classe di questo file che ne congela lo schema
    CONGELATI = {
        "db_catalogo": "TestContrattoCatalogoFase57",
        "db_inventario": "TestContrattoInventarioFase58",
        "db_registro_host": "TestContrattoRegistroHostFase88",
        "db_payout": "TestContrattoPayoutFase131",
        "db_tassa_comunale": "TestContrattoTassaFase147",
        "db_domanda": "TestContrattoDomandaFase158",
        "db_garanzia": "TestContrattoGaranziaFase160",
        "db_pendenti": "TestContrattoPendentiFase162",
        "db_accettazioni": "TestContrattoAccettazioniFase163",
        "db_finanza": "TestContrattoGiornaleFase177",
        "db_admin_accounts": "TestContrattoAdminAccountsFase192",
        "db_partner": "TestContrattoPartnerFase201",
        "db_coda": "TestContrattoCodaFase67",
        "db_split": "TestContrattoSplitFase65",
        "db_messaggi": "TestContrattoMessaggisticaFase113",
        "db_kyc": "TestContrattoKycFase143",
    }
    # ancora SCOPERTI, per iscritto (onda 2 del contratto di persistenza): recensioni,
    # viral loop, marche temporali RFC 3161, check-in digitale, crediti single-use e le
    # due cache rigenerabili (geocache/poicache, che non custodiscono patrimonio).
    SCOPERTI = ("db_recensioni", "db_viral", "db_marche", "db_checkin",
                "db_credito_usati", "db_geocache", "db_poicache",
                # `db_deposito` (fase149, deposito cauzionale) e' stato CABLATO il 2026-07-30,
                # cioe' dopo che questo contratto e' stato scritto: il guardiano lo ha colto
                # da solo. Dichiarato SCOPERTO, non congelato -- e va scritto per cosa
                # significa: la cauzione e' un HOLD sulla carta dell'ospite, quindi il giorno
                # in cui muove denaro davvero questo archivio va tolto da qui e congelato.
                "db_deposito")

    def test_ogni_archivio_di_configurazione_e_congelato_o_dichiarato_scoperto(self):
        from fase81_bootstrap_casavip import ConfigCasaVIP
        campi = set(c for c in ConfigCasaVIP.__dataclass_fields__ if c.startswith("db_"))
        self.assertGreater(len(campi), 15, "configurazione non letta")
        censiti = set(self.CONGELATI) | set(self.SCOPERTI)
        nuovi = sorted(campi - censiti)
        self.assertEqual(
            nuovi, [],
            "Archivio NUOVO senza contratto di persistenza: %s.\n"
            "Il patrimonio del progetto sono i dati: congela il suo schema in questo "
            "file (una classe come le altre) oppure mettilo per iscritto in SCOPERTI "
            "spiegando perche' puo' aspettare." % ", ".join(nuovi))
        spariti = sorted(censiti - campi)
        self.assertEqual(spariti, [],
                         "Questi archivi non esistono piu' in configurazione: %s. "
                         "Togli il contratto, altrimenti sorveglia il nulla."
                         % ", ".join(spariti))

    def test_le_classi_dichiarate_esistono_davvero(self):
        """Un contratto che punta a una classe cancellata e' un contratto vuoto."""
        mancanti = [c for c in self.CONGELATI.values() if c not in globals()]
        self.assertEqual(mancanti, [],
                         "classi dichiarate nel censimento ma inesistenti: %r" % mancanti)
        for nome in self.CONGELATI.values():
            classe = globals()[nome]
            self.assertTrue(issubclass(classe, BaseContratto),
                            "%s non e' un contratto di persistenza" % nome)
            self.assertGreater(len(classe.COLONNE), 0,
                               "%s non congela nessuna tabella" % nome)

    def test_i_diciassette_archivi_sono_tutti_esercitati(self):
        """Nessuna classe puo' congelare uno schema senza provare che ci si scrive."""
        contratti = sorted(n for n, o in globals().items()
                           if isinstance(o, type) and issubclass(o, BaseContratto)
                           and o is not BaseContratto)
        self.assertEqual(len(contratti), 17,
                         "attesi 17 contratti di persistenza, trovati %d: %r"
                         % (len(contratti), contratti))
        for nome in contratti:
            classe = globals()[nome]
            self.assertNotEqual(classe.ETICHETTA, "", "%s senza etichetta" % nome)
            self.assertIsNot(classe.esercita, BaseContratto.esercita,
                             "%s non esercita l'archivio" % nome)
            self.assertIsNot(classe.atteso_esercizio, BaseContratto.atteso_esercizio,
                             "%s non dichiara l'esito atteso" % nome)


if __name__ == "__main__":
    unittest.main(verbosity=2)
