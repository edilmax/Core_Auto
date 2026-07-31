"""LE MIGRAZIONI RIMASTE SCOPERTE — il debito dichiarato dall'onda 1, chiuso.

`test_migrazioni_schema.py` copre 14 archivi. Restavano fuori DUE debiti espliciti, ed e'
quello che chiude questo file. Nessuna riga di quel file e' stata toccata.


DEBITO (a) — TRE moduli hanno una `ALTER TABLE ... ADD COLUMN` e NESSUNA prova
-----------------------------------------------------------------------------
Cercando `ALTER TABLE` in tutti i `fase*.py` escono dieci moduli; sette hanno gia' la loro
classe. Questi tre no, e sono i piu' scomodi:

  · `fase34_prenotazioni`  -> `prenotazioni.ospite_telefono` e `pagamenti_split.riferimento_psp`.
    E' l'ARCHIVIO DELLE PRENOTAZIONI del motore Tavola VIP. Senza quelle due colonne
    `elenco()` e `stato()` sono "no such column: ospite_telefono" e
    `dettaglio_per_rimborso()` "no such column: riferimento_psp": la dashboard admin e il
    giro dei RIMBORSI muoiono in faccia all'utente su un database vero.
  · `fase63_recensioni`    -> le sei colonne `cat_pulizia ... cat_qualita_prezzo`.
    `elenco()` legge `r["cat_" + c]` per ognuna: su un archivio non migrato ogni lettura
    di recensioni ESPLODE, e l'INSERT di una recensione nuova nomina le sei colonne.
  · `fase16_outbox`        -> `outbox.priorita`.
    Il dispatcher fa `ORDER BY priorita ASC`: senza la colonna la consegna dei messaggi
    (allarmi Telegram, webhook partner) si ferma del tutto.

Lo schema VECCHIO di ognuno NON e' inventato: e' quello dei commit
`4445bf60` (fase34), `263e4bf7` (fase63), `1128c1fd` (fase16), riletti dalla storia git.


DEBITO (b) — CINQUE classi che provavano il NULLA
-------------------------------------------------
`TestMigrazioneAdminAccountsFase192`, `...DomandaFase158`, `...GaranziaFase160`,
`...PartnerFase201`, `...PayoutFase131` costruiscono un "vecchio.db" con lo schema
IDENTICO a quello di oggi: la migrazione non viene esercitata perche' non c'e' niente da
migrare, e il collaudo si riduce a una lettura.

RISULTATO DELL'ARCHEOLOGIA (fatto, non opinione): per quei cinque moduli il `CREATE TABLE`
non e' MAI cambiato. Ripercorrendo ogni commit che li ha toccati (1, 5, 12, 2 e 11
rispettivamente) l'insieme di tabelle/colonne/indici resta uno solo dal primo commit a
oggi. Uno schema precedente DIVERSO non esiste: copiarlo da git darebbe la stessa cosa.

Quindi qui quelle cinque prove sono state RIFATTE puntando dove il rischio esiste davvero
su un archivio di produzione vecchio: non lo schema, ma i DATI scritti dal codice di ALLORA
che la logica di OGGI — cresciuta parecchio nel frattempo — deve ancora trattare bene.
Ogni classe tiene comunque la sentinella di parita' colonne/indici verso un archivio nuovo
(il giorno in cui qualcuno aggiungera' una colonna senza la ALTER, diventa rossa qui), e in
piu' esercita la macchina a stati, la conservazione del denaro, la deduplica e il login su
righe nate prima.


DUE DIFETTI TROVATI E CHIUSI (dettaglio nel corpo delle classi)
---------------------------------------------------------------
1. GRAVE — `fase131_payout_dashboard`: fino al fix di `_norm_valuta` (2026-07-29) la riga
   di payout si scriveva con `valuta.upper()` SENZA strip, quindi ' EUR '. Quel fix ha
   corretto le scritture NUOVE e non ha RIPARATO le righe gia' in archivio: `riepilogo()`
   raggruppa sul valore GREZZO letto dal file, quindi la riga vecchia finisce sotto la
   chiave ' EUR ' e `da_pagare(host, 'EUR')` la salta -> soldi dovuti all'host INVISIBILI,
   bonifico mai fatto, e `elenca(valuta='EUR')` non la trova nemmeno per la compensazione
   delle penali. Una migrazione dei dati mancava del tutto.
   RIMEDIO (minimo e idempotente) in `inizializza_schema`:
       UPDATE payout SET valuta=UPPER(TRIM(valuta)) WHERE valuta<>UPPER(TRIM(valuta))
   Su un archivio pulito tocca ZERO righe. Guardia: `test_la_valuta_sporca_del_codice_vecchio_e_riparata`.

2. MEDIO — `fase16_outbox`: l'indice di fetch e' cambiato quando e' nata la priorita'
   (`idx_outbox_due` da `(status, next_retry_at, id)` a `(status, priorita, next_retry_at, id)`),
   ma `CREATE INDEX IF NOT EXISTS` NON sostituisce un indice che esiste gia' col quel nome:
   un archivio nato prima si tiene per sempre l'indice vecchio e il dispatcher ordina per
   priorita' senza indice. Stesso difetto gia' chiuso in `fase184` con DROP+CREATE.
   RIMEDIO: dopo la ALTER, se la definizione dell'indice non nomina `priorita`, si rifa'.
   Guardia: `test_definizione_indici_uguale_a_un_archivio_nuovo` sulla classe outbox.


VISTO ROSSO (regola aurea: nessun verde vale finche' non e' stato visto rosso)
------------------------------------------------------------------------------
Il 2026-07-29 sono stati iniettati QUATTORDICI guasti nel codice di produzione, uno alla
volta, eseguendo ogni volta la sola classe che li sorveglia e ripristinando poi il file
byte per byte (sha256 confrontato prima/dopo: identico in tutti e quattordici i casi,
`git status` senza modifiche impreviste). Tutti e quattordici sono stati VISTI ROSSI:

  · fase34, tolta la ALTER di `prenotazioni.ospite_telefono`
      -> OperationalError "table prenotazioni has no column named ospite_telefono";
  · fase34, tolta la ALTER di `pagamenti_split.riferimento_psp`
      -> `dettaglio_per_rimborso()` esplode = nessun rimborso possibile;
  · fase34, tolto il controllo di disponibilita' nella `crea`
      -> ROSSO: la notte gia' venduta nell'archivio vecchio verrebbe rivenduta;
  · fase63, tolto il ciclo che aggiunge le `cat_*`
      -> "no such column: cat_pulizia" su lettura E su scrittura delle recensioni;
  · fase63, tolto il controllo "gia' recensita"
      -> ROSSO: la recensione storica verrebbe sovrascritta;
  · fase16, tolta la ALTER di `outbox.priorita`
      -> "no such column: priorita" = consegna dei messaggi ferma;
  · fase16, tolto il DROP+CREATE di `idx_outbox_due`
      -> ROSSO: definizione dell'indice diversa da quella di un archivio nuovo;
  · fase131, tolta la riparazione della valuta
      -> ROSSO: `riepilogo` con la chiave fantasma ' EUR ', `da_pagare` 84640 invece di
         94540 (i 99,00 EUR della riga vecchia spariti);
  · fase131, tolta la tabella delle transizioni in `aggiorna_stato`
      -> ROSSO: da 'pagato' si tornerebbe indietro (bonifico pagabile due volte);
  · fase160, cambiato lo stato atteso dal REVIVE ('annullato' -> uno inesistente)
      -> ROSSO: la garanzia vecchia non risorge al pagamento tardivo;
  · fase160, tolto `AND sblocco_auto_ts<=?` dalla selezione dell'auto-rilascio
      -> ROSSO: pagata all'host anche la garanzia con la finestra ancora aperta;
  · fase192, tolto il controllo `attivo` nel login
      -> ROSSO: l'ex dipendente revocato rientrerebbe nel bunker;
  · fase158, tolto il `.lower()` sull'email
      -> ROSSO: 4 righe invece di 3, la stessa persona due volte in lista d'attesa;
  · fase201, tolto `WHERE ts > ?` dal tetto orario
      -> ROSSO: 'riprova_piu_tardi' per sempre, canale partner chiuso in silenzio.

La capacita' di fallire e' anche PERMANENTE e automatica in `TestIlControlloSaFallire`.
"""
import os
import re
import shutil
import sqlite3
import tempfile
import unittest

RADICE = os.path.dirname(os.path.abspath(__file__))
SEGRETO = b"segreto-di-collaudo-migrazioni-mancanti-32b"


# ---------------------------------------------------------------------------
# Attrezzi: sqlite3 nudo, cosi' il giudizio non dipende dal codice giudicato.
# ---------------------------------------------------------------------------
def colonne(percorso, tabella):
    con = sqlite3.connect(percorso)
    try:
        return [r[1] for r in con.execute("PRAGMA table_info(%s)" % tabella).fetchall()]
    finally:
        con.close()


def oggetti(percorso, tipo):
    con = sqlite3.connect(percorso)
    try:
        righe_ = con.execute("SELECT name FROM sqlite_master WHERE type=? ORDER BY name",
                             (tipo,)).fetchall()
    finally:
        con.close()
    return sorted(r[0] for r in righe_ if not r[0].startswith("sqlite_"))


def indici_sql(percorso):
    """{nome_indice: definizione normalizzata}. I NOMI non bastano: `CREATE INDEX IF NOT
    EXISTS` su un nome gia' presente e' un no-op silenzioso, quindi un archivio vecchio
    puo' tenersi per sempre una definizione DIVERSA da quella di un archivio nuovo."""
    con = sqlite3.connect(percorso)
    try:
        righe_ = con.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
        ).fetchall()
    finally:
        con.close()
    return dict((n, " ".join(s.split())) for n, s in righe_ if not n.startswith("sqlite_"))


def righe(percorso, tabella, colonne_volute, ordine):
    con = sqlite3.connect(percorso)
    try:
        # nomi di tabella/colonna non parametrizzabili: vengono tutti da costanti scritte
        # in questo file, mai da input esterno.
        sql = ("SELECT %s FROM %s ORDER BY %s"      # noqa: S608
               % (", ".join(colonne_volute), tabella, ordine))
        return [tuple(r) for r in con.execute(sql).fetchall()]
    finally:
        con.close()


def scrivi_db_vecchio(percorso, ddl, inserimenti):
    con = sqlite3.connect(percorso)
    try:
        with con:
            for istruzione in ddl:
                con.execute(istruzione)
            for sql, parametri in inserimenti:
                con.execute(sql, parametri)
    finally:
        con.close()


def sorgente(modulo):
    with open(os.path.join(RADICE, modulo + ".py"), "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Base comune. Ogni archivio dichiara il proprio schema VECCHIO, righe vecchie
# realistiche e come lo si apre col codice di OGGI.
# ---------------------------------------------------------------------------
class BaseMigrazione(object):
    MODULO = ""             # nome del modulo di produzione sotto esame
    DDL_V1 = ()             # schema come lo scriveva il commit indicato nella classe
    RIGHE_V1 = ()           # (sql, parametri) di dati realistici
    TABELLE = ()            # (nome_tabella, colonne_v1, order_by)
    COLONNE_AGGIUNTE = {}   # tabella -> colonne che la migrazione DEVE aggiungere

    # ---- da implementare nella sottoclasse -------------------------------
    def apri(self, percorso):
        raise NotImplementedError

    def leggi_col_prodotto(self, archivio):
        raise NotImplementedError

    def atteso_dal_prodotto(self):
        raise NotImplementedError

    # ---- attrezzatura ----------------------------------------------------
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="migrmanc_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.vecchio = os.path.join(self.dir, "vecchio.db")
        self.nuovo = os.path.join(self.dir, "nuovo.db")
        scrivi_db_vecchio(self.vecchio, self.DDL_V1, self.RIGHE_V1)

    def _foto_dati(self, percorso):
        return dict((tab, righe(percorso, tab, cols, ordine))
                    for tab, cols, ordine in self.TABELLE)

    def _foto_schema(self, percorso):
        stato = {"index": oggetti(percorso, "index"),
                 "trigger": oggetti(percorso, "trigger"),
                 "table": oggetti(percorso, "table"),
                 "index_sql": indici_sql(percorso)}
        for tab, _cols, _ord in self.TABELLE:
            stato["col:" + tab] = sorted(colonne(percorso, tab))
        return stato

    # ---- I CONTROLLI (uno per difetto) -----------------------------------
    def test_le_colonne_del_db_vecchio_sono_quelle_del_db_nuovo(self):
        """LA SENTINELLA: una colonna aggiunta al CREATE TABLE senza la ALTER esiste sul
        db nuovo e NON sul db vecchio. Qui diventa rossa, invece che in produzione."""
        self.apri(self.vecchio)
        self.apri(self.nuovo)               # archivio vergine, stesso codice
        for tab, _cols, _ord in self.TABELLE:
            attese = set(colonne(self.nuovo, tab))
            trovate = set(colonne(self.vecchio, tab))
            mancanti = sorted(attese - trovate)
            di_troppo = sorted(trovate - attese)
            self.assertEqual(
                mancanti, [],
                "%s: colonne MANCANTI nel db migrato: %r - il codice di oggi le usa nelle "
                "query, sui dati veri sarebbe 'no such column'" % (tab, mancanti))
            self.assertEqual(
                di_troppo, [],
                "%s: il db migrato ha colonne che il db nuovo non ha: %r" % (tab, di_troppo))

    def test_la_migrazione_aggiunge_proprio_le_colonne_dichiarate(self):
        """Le colonne nate DOPO devono comparire davvero, e prima NON devono esserci (se
        il formato vecchio le avesse gia', il caso non proverebbe nulla). Quando la classe
        non ne dichiara nessuna, dev'essere un FATTO verificato nel sorgente - il modulo
        non ha proprio nessuna ADD COLUMN - non una svista di chi ha scritto il collaudo."""
        if not self.COLONNE_AGGIUNTE:
            testo = sorgente(self.MODULO)
            self.assertNotIn(
                "ADD COLUMN", testo,
                "%s ha una ALTER TABLE ... ADD COLUMN ma questa classe non dichiara "
                "COLONNE_AGGIUNTE: la migrazione non verrebbe esercitata" % self.MODULO)
            return
        for tab, attese in self.COLONNE_AGGIUNTE.items():
            prima = set(colonne(self.vecchio, tab))
            for c in attese:
                self.assertNotIn(c, prima,
                                 "%s.%s c'e' gia' nel formato vecchio: il caso non e' quello "
                                 "di una migrazione" % (tab, c))
        self.apri(self.vecchio)
        for tab, attese in self.COLONNE_AGGIUNTE.items():
            dopo = set(colonne(self.vecchio, tab))
            for c in attese:
                self.assertIn(c, dopo,
                              "%s.%s non e' stata aggiunta dalla migrazione" % (tab, c))

    def test_nessuna_riga_persa_nessun_valore_alterato(self):
        prima = self._foto_dati(self.vecchio)
        self.apri(self.vecchio)
        dopo = self._foto_dati(self.vecchio)
        for tab, _cols, _ord in self.TABELLE:
            self.assertEqual(
                len(dopo[tab]), len(prima[tab]),
                "%s: la migrazione ha cambiato il NUMERO di righe (%d -> %d)"
                % (tab, len(prima[tab]), len(dopo[tab])))
            self.assertEqual(dopo[tab], prima[tab],
                             "%s: la migrazione ha ALTERATO i dati storici" % tab)
            self.assertGreater(len(dopo[tab]), 0,
                               "%s: il caso di prova e' vuoto, non proverebbe nulla" % tab)

    def test_il_prodotto_legge_i_dati_vecchi(self):
        archivio = self.apri(self.vecchio)
        self.assertEqual(self.leggi_col_prodotto(archivio), self.atteso_dal_prodotto())

    def test_riaprire_e_un_no_op(self):
        self.apri(self.vecchio)
        schema1 = self._foto_schema(self.vecchio)
        dati1 = self._foto_dati(self.vecchio)
        self.apri(self.vecchio)
        self.apri(self.vecchio)
        self.assertEqual(self._foto_schema(self.vecchio), schema1,
                         "la seconda/terza apertura ha cambiato lo SCHEMA: non e' idempotente")
        self.assertEqual(self._foto_dati(self.vecchio), dati1,
                         "la seconda/terza apertura ha toccato i DATI: non e' idempotente")

    def test_tabelle_indici_e_trigger_uguali_a_un_archivio_nuovo(self):
        self.apri(self.vecchio)
        self.apri(self.nuovo)
        self.assertEqual(oggetti(self.vecchio, "table"), oggetti(self.nuovo, "table"),
                         "tabelle diverse fra archivio migrato e archivio nuovo")
        self.assertEqual(oggetti(self.vecchio, "index"), oggetti(self.nuovo, "index"),
                         "indici diversi fra archivio migrato e archivio nuovo")
        self.assertEqual(oggetti(self.vecchio, "trigger"), oggetti(self.nuovo, "trigger"),
                         "trigger diversi fra archivio migrato e archivio nuovo")

    def test_definizione_indici_uguale_a_un_archivio_nuovo(self):
        """Non basta che l'indice si CHIAMI uguale: `CREATE INDEX IF NOT EXISTS` su un nome
        gia' presente non fa nulla, quindi un archivio vecchio puo' restare con la
        definizione di ieri (colonne diverse) e le query di oggi girano senza indice."""
        self.apri(self.vecchio)
        self.apri(self.nuovo)
        vecchi, nuovi = indici_sql(self.vecchio), indici_sql(self.nuovo)
        self.assertEqual(sorted(vecchi), sorted(nuovi))
        for nome in sorted(nuovi):
            self.assertEqual(
                vecchi.get(nome), nuovi[nome],
                "l'indice %s dell'archivio migrato ha una definizione DIVERSA da quella "
                "di un archivio nuovo:\n  vecchio: %s\n  nuovo:   %s"
                % (nome, vecchi.get(nome), nuovi[nome]))


# ===========================================================================
# (a) 1. PRENOTAZIONI (fase34) - `ospite_telefono` + `riferimento_psp`
#        schema vecchio = commit 4445bf60 (primo commit del modulo)
# ===========================================================================
class TestMigrazionePrenotazioniFase34(BaseMigrazione, unittest.TestCase):
    MODULO = "fase34_prenotazioni"
    DDL_V1 = (
        """
                    CREATE TABLE IF NOT EXISTS prenotazioni (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        candidato_url TEXT, ospite_nome TEXT DEFAULT '',
                        ospite_email TEXT DEFAULT '', check_in TEXT DEFAULT '',
                        check_out TEXT DEFAULT '', stato TEXT DEFAULT 'richiesta',
                        origine TEXT DEFAULT '', uid_ical TEXT DEFAULT '',
                        data_creazione TEXT)""",
        """
                    CREATE TABLE IF NOT EXISTS pagamenti_split (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        prenotazione_id INTEGER NOT NULL,
                        importo_totale INTEGER NOT NULL,
                        commissione_tavola INTEGER NOT NULL,
                        quota_partner INTEGER NOT NULL,
                        status TEXT DEFAULT 'pending',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (prenotazione_id)
                            REFERENCES prenotazioni(id) ON DELETE CASCADE)""",
        """
                    CREATE TABLE IF NOT EXISTS escrow_fondi (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        pagamento_id INTEGER NOT NULL,
                        stato TEXT DEFAULT 'bloccato', data_sblocco TIMESTAMP,
                        FOREIGN KEY (pagamento_id)
                            REFERENCES pagamenti_split(id) ON DELETE CASCADE)""",
        """
                    CREATE TABLE IF NOT EXISTS voucher_prenotazioni (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        prenotazione_id INTEGER UNIQUE,
                        codice_voucher TEXT UNIQUE,
                        pdf_path TEXT,
                        emesso_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (prenotazione_id)
                            REFERENCES prenotazioni(id) ON DELETE CASCADE)""",
        "CREATE INDEX IF NOT EXISTS idx_prenotazioni_overlap "
        "ON prenotazioni(candidato_url, stato)",
    )
    _P = ("INSERT INTO prenotazioni (id, candidato_url, ospite_nome, ospite_email, "
          "check_in, check_out, stato, origine, uid_ical, data_creazione) "
          "VALUES (?,?,?,?,?,?,?,?,?,?)")
    _S = ("INSERT INTO pagamenti_split (id, prenotazione_id, importo_totale, "
          "commissione_tavola, quota_partner, status, created_at) VALUES (?,?,?,?,?,?,?)")
    RIGHE_V1 = (
        (_P, (1, "trastevere-attico-vista", "Chiara Rossi", "chiara.rossi@example.com",
              "2026-08-10", "2026-08-12", "pagata", "sito", "uid-1@bookinvip",
              "2026-07-01T10:00:00")),
        (_P, (2, "trastevere-attico-vista", "Kenji Sato", "kenji.sato@example.jp",
              "2026-08-12", "2026-08-14", "pagata", "sito", "uid-2@bookinvip",
              "2026-07-02T09:30:00")),
        (_P, (3, "shinjuku-monolocale", "Laura Bianchi", "laura.bianchi@example.com",
              "2026-09-01", "2026-09-04", "annullata", "agente", "uid-3@bookinvip",
              "2026-06-20T08:00:00")),
        (_S, (1, 1, 37000, 2960, 34040, "paid", "2026-07-01 10:00:05")),
        (_S, (2, 2, 55000, 4400, 50600, "paid", "2026-07-02 09:30:05")),
        (_S, (3, 3, 52000, 4160, 47840, "pending", "2026-06-20 08:00:05")),
        ("INSERT INTO escrow_fondi (id, pagamento_id, stato, data_sblocco) VALUES (?,?,?,?)",
         (1, 1, "sbloccato", "2026-07-05 12:00:00")),
        ("INSERT INTO escrow_fondi (id, pagamento_id, stato, data_sblocco) VALUES (?,?,?,?)",
         (2, 2, "bloccato", None)),
        ("INSERT INTO voucher_prenotazioni (id, prenotazione_id, codice_voucher, pdf_path, "
         "emesso_il) VALUES (?,?,?,?,?)",
         (1, 1, "VIP-AABBCCDD1122", "/voucher/BV117.pdf", "2026-07-01 10:00:10")),
    )
    _COL_P = ("id", "candidato_url", "ospite_nome", "ospite_email", "check_in", "check_out",
              "stato", "origine", "uid_ical", "data_creazione")
    _COL_S = ("id", "prenotazione_id", "importo_totale", "commissione_tavola",
              "quota_partner", "status", "created_at")
    TABELLE = (("prenotazioni", _COL_P, "id"),
               ("pagamenti_split", _COL_S, "id"),
               ("escrow_fondi", ("id", "pagamento_id", "stato", "data_sblocco"), "id"),
               ("voucher_prenotazioni",
                ("id", "prenotazione_id", "codice_voucher", "pdf_path", "emesso_il"), "id"))
    COLONNE_AGGIUNTE = {"prenotazioni": ("ospite_telefono",),
                        "pagamenti_split": ("riferimento_psp",)}

    def apri(self, percorso):
        from fase34_prenotazioni import MotorePrenotazioni
        motore = MotorePrenotazioni(lambda: sqlite3.connect(percorso, timeout=30))
        motore.inizializza_schema()
        return motore

    def leggi_col_prodotto(self, archivio):
        dett = archivio.stato(1)
        return {
            # `stato()` SELECT-a esplicitamente ospite_telefono: senza migrazione e' 500
            "ospite_nome": dett["ospite_nome"],
            "ospite_telefono": dett["ospite_telefono"],
            "importo_totale": dett["importo_totale"],
            "commissione_tavola": dett["commissione_tavola"],
            "quota_partner": dett["quota_partner"],
            "status": dett["status"],
            # `elenco()` e' la dashboard admin
            "pagate": [r["id"] for r in archivio.elenco("pagata")],
            "telefoni": sorted(set(r["ospite_telefono"] for r in archivio.elenco())),
            # `dettaglio_per_rimborso()` SELECT-a riferimento_psp: senza migrazione niente rimborsi
            "rimborso": archivio.dettaglio_per_rimborso(1),
            # il voucher storico si ritrova, non se ne emette un secondo
            "voucher": archivio.emetti_voucher(1),
        }

    def atteso_dal_prodotto(self):
        return {
            "ospite_nome": "Chiara Rossi",
            "ospite_telefono": "",
            "importo_totale": 37000, "commissione_tavola": 2960, "quota_partner": 34040,
            "status": "paid",
            "pagate": [1, 2],
            "telefoni": [""],
            "rimborso": {"stato_prenotazione": "pagata", "pagamento_id": 1,
                         "riferimento_psp": "", "importo_totale": 37000},
            "voucher": "VIP-AABBCCDD1122",
        }

    def test_la_colonna_appena_migrata_e_SCRIVIBILE_dal_giro_dei_pagamenti(self):
        """Non basta che `riferimento_psp` compaia: il webhook del PSP ci scrive dentro.
        Una ADD COLUMN sbagliata puo' lasciare un vincolo che rifiuta l'UPDATE, e il
        riferimento del pagamento e' l'unica chiave per rimborsare davvero."""
        motore = self.apri(self.vecchio)
        self.assertEqual(motore.conferma_pagamento(3, "pi_3PtQ7xCollaudo01"), 3)
        dett = motore.dettaglio_per_rimborso(3)
        self.assertEqual(dett["riferimento_psp"], "pi_3PtQ7xCollaudo01")
        self.assertEqual(dett["stato_prenotazione"], "pagata")
        self.assertEqual(dett["importo_totale"], 52000)
        self.assertEqual(motore.stato(3)["status"], "paid")

    def test_il_giro_completo_del_rimborso_su_una_prenotazione_vecchia(self):
        """La prenotazione nata col vecchio schema dev'essere ancora RIMBORSABILE:
        richiesta -> dettaglio (serve riferimento_psp) -> chiusura."""
        motore = self.apri(self.vecchio)
        self.assertIs(motore.richiedi_rimborso(1), True)
        self.assertEqual(motore.stato(1)["stato"], "rimborso_richiesto")
        self.assertEqual(motore.dettaglio_per_rimborso(1)["stato_prenotazione"],
                         "rimborso_richiesto")
        self.assertIs(motore.completa_rimborso(1), True)
        self.assertEqual(motore.stato(1)["stato"], "rimborsata")
        self.assertEqual(motore.stato(1)["status"], "refunded")
        # e il doppio rimborso non passa
        self.assertIs(motore.completa_rimborso(1), False)

    def test_le_prenotazioni_vecchie_occupano_ancora_il_calendario(self):
        """Il dato storico non dev'essere solo leggibile: deve ancora BLOCCARE. Se la
        migrazione perdesse le righe, si rivenderebbe una notte gia' venduta."""
        from fase34_prenotazioni import RichiestaPrenotazione
        motore = self.apri(self.vecchio)
        sovrapposta = motore.crea(RichiestaPrenotazione(
            alloggio_id="trastevere-attico-vista", ospite_nome="Marco Neri",
            ospite_email="marco.neri@example.com", check_in="2026-08-11",
            check_out="2026-08-13", importo_totale_cents=40000,
            commissione_cents=3200, ospite_telefono="+393331234567"))
        self.assertIs(sovrapposta.ok, False)
        self.assertEqual(sovrapposta.motivo, "non_disponibile")
        self.assertIsNone(sovrapposta.prenotazione_id)
        # turnover in giornata: il 14 e' il check-out della #2 -> NON e' conflitto
        libera = motore.crea(RichiestaPrenotazione(
            alloggio_id="trastevere-attico-vista", ospite_nome="Marco Neri",
            ospite_email="marco.neri@example.com", check_in="2026-08-14",
            check_out="2026-08-16", importo_totale_cents=40000,
            commissione_cents=3200, ospite_telefono="+393331234567"))
        self.assertIs(libera.ok, True)
        self.assertEqual(libera.motivo, "creata")
        # il telefono nuovo va proprio nella colonna appena migrata
        self.assertEqual(motore.stato(libera.prenotazione_id)["ospite_telefono"],
                         "+393331234567")


# ===========================================================================
# (a) 2. RECENSIONI (fase63) - le sei `cat_*` dei sotto-voti
#        schema vecchio = commit 263e4bf7 (primo commit del modulo)
# ===========================================================================
class TestMigrazioneRecensioniFase63(BaseMigrazione, unittest.TestCase):
    MODULO = "fase63_recensioni"
    ORA = 1785000000
    DDL_V1 = (
        """
                    CREATE TABLE IF NOT EXISTS recensioni (
                        prenotazione_id TEXT PRIMARY KEY,
                        alloggio_id TEXT NOT NULL,
                        voto INTEGER NOT NULL,
                        testo TEXT NOT NULL DEFAULT '',
                        lingua TEXT NOT NULL DEFAULT 'en',
                        verificata INTEGER NOT NULL DEFAULT 0,
                        ts TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS idx_rec_alloggio ON recensioni(alloggio_id)",
    )
    _R = ("INSERT INTO recensioni (prenotazione_id, alloggio_id, voto, testo, lingua, "
          "verificata, ts) VALUES (?,?,?,?,?,?,?)")
    RIGHE_V1 = (
        (_R, ("BV-2026-000117", "trastevere-attico-vista", 5,
              "Terrazza stupenda e host presente. Torneremo.", "it", 1,
              "2026-06-01T09:00:00")),
        (_R, ("BV-2026-000118", "trastevere-attico-vista", 4,
              "Ottima posizione, un po' rumorosa la notte.", "it", 1,
              "2026-06-15T11:30:00")),
        (_R, ("BV-2026-000119", "shinjuku-monolocale", 3, "Small but clean.", "en", 1,
              "2026-06-20T08:00:00")),
    )
    TABELLE = (("recensioni", ("prenotazione_id", "alloggio_id", "voto", "testo", "lingua",
                               "verificata", "ts"), "prenotazione_id"),)
    COLONNE_AGGIUNTE = {"recensioni": ("cat_pulizia", "cat_comfort", "cat_posizione",
                                       "cat_servizi", "cat_host", "cat_qualita_prezzo")}

    def apri(self, percorso):
        from fase63_recensioni import crea_registro_recensioni
        return crea_registro_recensioni(percorso, SEGRETO, orologio=lambda: self.ORA)

    def leggi_col_prodotto(self, archivio):
        rie = archivio.riepilogo("trastevere-attico-vista")
        voci = archivio.elenco("trastevere-attico-vista")
        return {
            "conteggio": rie["conteggio"],
            # (5 + 4) * 100 // 2 = 450 -> 4,50 stelle, in centesimi interi
            "media_centesimi": rie["media_centesimi"],
            "distribuzione": rie["distribuzione"],
            # nessuna recensione vecchia ha i sotto-voti: la media per categoria e' VUOTA,
            # non zero (zero sarebbe una bugia: direbbe 'pulizia 0,00')
            "categorie": rie["categorie"],
            # `elenco()` legge r["cat_x"] per ognuna: senza migrazione esplode qui
            "quante_in_elenco": len(voci),
            "prima": voci[0]["prenotazione_id"],
            "testo_prima": voci[0]["testo"],
            "categorie_in_elenco": ["categorie" in v for v in voci],
            "gia_recensita": archivio.gia_recensita("BV-2026-000117"),
            "mai_recensita": archivio.gia_recensita("BV-2026-999999"),
        }

    def atteso_dal_prodotto(self):
        return {
            "conteggio": 2, "media_centesimi": 450,
            "distribuzione": {1: 0, 2: 0, 3: 0, 4: 1, 5: 1},
            "categorie": {},
            "quante_in_elenco": 2,
            "prima": "BV-2026-000118",     # ordinate per ts DESC
            "testo_prima": {"text": "Ottima posizione, un po' rumorosa la notte.",
                            "lang": "it"},
            "categorie_in_elenco": [False, False],
            "gia_recensita": True, "mai_recensita": False,
        }

    def test_una_recensione_nuova_coi_sotto_voti_convive_con_le_vecchie(self):
        """L'INSERT di oggi nomina tutte e sei le `cat_*`: su un archivio non migrato
        fallisce, e l'ospite che ha davvero soggiornato non riesce a recensire."""
        from fase59_concierge import FirmaQuote
        from fase63_recensioni import EmettitoreDiritto
        registro = self.apri(self.vecchio)
        diritto = EmettitoreDiritto(FirmaQuote(SEGRETO), ttl_giorni=90,
                                    orologio=lambda: self.ORA)
        token = diritto.emetti("BV-2026-000200", "trastevere-attico-vista")
        esito = registro.invia(token, 5, "Pulitissimo, posizione perfetta.", "it",
                               {"pulizia": 5, "posizione": 4})
        self.assertIs(esito.ok, True)
        self.assertIs(esito.verificata, True)
        self.assertEqual(esito.motivo, "")
        rie = registro.riepilogo("trastevere-attico-vista")
        self.assertEqual(rie["conteggio"], 3)
        self.assertEqual(rie["media_centesimi"], (5 + 4 + 5) * 100 // 3)   # 466
        # le medie per categoria contano SOLO chi ha compilato quella voce: una recensione,
        # non tre (le due storiche hanno NULL e devono restare fuori dal denominatore)
        self.assertEqual(rie["categorie"], {"pulizia": {"conteggio": 1, "media_centesimi": 500},
                                            "posizione": {"conteggio": 1,
                                                          "media_centesimi": 400}})
        voci = registro.elenco("trastevere-attico-vista")
        self.assertEqual([v["prenotazione_id"] for v in voci],
                         ["BV-2026-000200", "BV-2026-000118", "BV-2026-000117"])
        self.assertEqual(voci[0]["categorie"], {"pulizia": 5, "posizione": 4})
        self.assertNotIn("categorie", voci[1])

    def test_la_recensione_vecchia_resta_UNICA_per_soggiorno(self):
        """La difesa anti-doppio-voto e' sulla riga gia' in archivio: un diritto valido
        emesso oggi sulla stessa prenotazione storica non deve poter sovrascrivere."""
        from fase59_concierge import FirmaQuote
        from fase63_recensioni import EmettitoreDiritto
        registro = self.apri(self.vecchio)
        diritto = EmettitoreDiritto(FirmaQuote(SEGRETO), ttl_giorni=90,
                                    orologio=lambda: self.ORA)
        token = diritto.emetti("BV-2026-000117", "trastevere-attico-vista")
        esito = registro.invia(token, 1, "Ci ho ripensato.", "it", {"pulizia": 1})
        self.assertIs(esito.ok, False)
        self.assertEqual(esito.motivo, "gia_recensita")
        self.assertEqual(registro.riepilogo("trastevere-attico-vista")["media_centesimi"], 450)
        self.assertEqual(righe(self.vecchio, "recensioni", ("voto", "testo"),
                               "prenotazione_id")[0],
                         (5, "Terrazza stupenda e host presente. Torneremo."))


# ===========================================================================
# (a) 3. OUTBOX (fase16) - `priorita`, senza la quale la consegna si ferma
#        schema vecchio = commit 1128c1fd (primo commit del modulo)
# ===========================================================================
class TestMigrazioneOutboxFase16(BaseMigrazione, unittest.TestCase):
    MODULO = "fase16_outbox"
    DDL_V1 = (
        """CREATE TABLE IF NOT EXISTS outbox (
                   id             INTEGER PRIMARY KEY AUTOINCREMENT,
                   topic          TEXT NOT NULL,
                   partition_key  TEXT,
                   payload        TEXT NOT NULL,
                   headers        TEXT,
                   status         TEXT NOT NULL DEFAULT 'pending',
                   retry_count    INTEGER NOT NULL DEFAULT 0,
                   max_retries    INTEGER NOT NULL DEFAULT 3,
                   next_retry_at  TEXT,
                   locked_by      TEXT,
                   locked_at      TEXT,
                   last_error     TEXT,
                   correlation_id TEXT,
                   causation_id   TEXT,
                   created_at     TEXT NOT NULL DEFAULT (datetime('now')),
                   processed_at   TEXT
               )""",
        "CREATE INDEX IF NOT EXISTS idx_outbox_due ON outbox(status, next_retry_at, id)",
        "CREATE INDEX IF NOT EXISTS idx_outbox_processing "
        "ON outbox(locked_at) WHERE status='processing'",
    )
    _M = ("INSERT INTO outbox (id, topic, partition_key, payload, headers, status, "
          "retry_count, max_retries, next_retry_at, locked_by, locked_at, last_error, "
          "correlation_id, causation_id, created_at, processed_at) "
          "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
    RIGHE_V1 = (
        (_M, (1, "telegram_alert", None,
              '{"message": "prenotazione BV-2026-000117 confermata"}', None,
              "pending", 0, 3, None, None, None, None, "corr-117", None,
              "2020-01-01T10:00:00+00:00", None)),
        (_M, (2, "email_admin", "admin", '{"subject": "nuovo host a Roma"}',
              '{"X-Origine": "casavip"}', "failed", 1, 3, "2020-01-01T10:05:00+00:00",
              None, None, "handler ha restituito False", "corr-200", None,
              "2020-01-01T10:01:00+00:00", None)),
        (_M, (3, "audit_external", None, '{"event_type": "payout"}', None,
              "completed", 0, 3, None, None, None, None, None, None,
              "2019-12-30T09:00:00+00:00", "2019-12-30T09:00:01+00:00")),
        (_M, (4, "webhook_partner", "p1",
              '{"url": "https://partner.example.com/hook", "body": {"a": 1}}', None,
              "dead_letter", 3, 3, None, None, None, "timeout", "corr-9", None,
              "2019-12-29T08:00:00+00:00", None)),
    )
    _COL = ("id", "topic", "partition_key", "payload", "headers", "status", "retry_count",
            "max_retries", "next_retry_at", "locked_by", "locked_at", "last_error",
            "correlation_id", "causation_id", "created_at", "processed_at")
    TABELLE = (("outbox", _COL, "id"),)
    COLONNE_AGGIUNTE = {"outbox": ("priorita",)}

    def setUp(self):
        # il backend e' letto dall'ambiente ad ogni chiamata: qui dev'essere SQLite, e
        # l'ambiente va rimesso com'era per non condizionare gli altri collaudi.
        precedente = os.environ.get("DB_BACKEND")
        os.environ["DB_BACKEND"] = "sqlite"
        self.addCleanup(self._ripristina_backend, precedente)
        BaseMigrazione.setUp(self)

    @staticmethod
    def _ripristina_backend(precedente):
        if precedente is None:
            os.environ.pop("DB_BACKEND", None)
        else:
            os.environ["DB_BACKEND"] = precedente

    def apri(self, percorso):
        from fase16_outbox import inizializza_schema
        inizializza_schema(percorso)
        return percorso

    def _dispatcher(self, percorso):
        from fase16_outbox import OutboxDispatcher
        return OutboxDispatcher(db_path=percorso, poll=0.01, batch=10)

    def leggi_col_prodotto(self, archivio):
        disp = self._dispatcher(archivio)
        pronti = disp._fetch()          # la query che ORDINA per priorita'
        return {
            "stato": disp.status(),
            # solo pending/failed scaduti: il completato e il dead-letter restano fuori
            "pronti": [r["id"] for r in pronti],
            "topic_pronti": [r["topic"] for r in pronti],
            # la colonna appena migrata vale 1 (NORMALE) su tutte le righe storiche
            "priorita_storiche": sorted(set(r["priorita"] for r in pronti)),
            "dlq_profondita": disp.check_dlq_alert(),
        }

    def atteso_dal_prodotto(self):
        return {
            "stato": {"pending": 1, "failed": 1, "completed": 1, "dead_letter": 1},
            "pronti": [1, 2],
            "topic_pronti": ["telegram_alert", "email_admin"],
            "priorita_storiche": [1],
            "dlq_profondita": 1,
        }

    def test_un_messaggio_urgente_di_oggi_passa_davanti_a_quelli_storici(self):
        """La colonna migrata non deve solo esistere: deve ORDINARE. Se restasse
        inutilizzata, un allarme critico resterebbe in coda dietro le email vecchie."""
        from fase29_backpressure import Priorita
        self.apri(self.vecchio)
        con = sqlite3.connect(self.vecchio)
        try:
            with con:
                con.execute(
                    "INSERT INTO outbox (id, topic, payload, status, max_retries, "
                    "created_at, priorita) VALUES (?,?,?,'pending',?,?,?)",
                    (99, "telegram_alert", '{"message": "DLQ oltre soglia"}', 3,
                     "2020-01-02T00:00:00+00:00", int(Priorita.ALTA)))
        finally:
            con.close()
        pronti = self._dispatcher(self.vecchio)._fetch()
        self.assertEqual([r["id"] for r in pronti], [99, 1, 2])
        self.assertEqual([r["priorita"] for r in pronti], [int(Priorita.ALTA), 1, 1])

    def test_un_messaggio_storico_viene_davvero_consegnato(self):
        """Il pezzo che conta per l'utente: il messaggio rimasto in coda da prima della
        migrazione dev'essere consegnato e chiuso, non restare 'pending' per sempre."""
        self.apri(self.vecchio)
        disp = self._dispatcher(self.vecchio)
        visti = []
        disp.register("telegram_alert", lambda p: visti.append(p) or True)
        disp.register("email_admin", lambda p: visti.append(p) or True)
        for riga in disp._fetch():
            disp._process(riga)
        self.assertEqual([p.get("message") or p.get("subject") for p in visti],
                         ["prenotazione BV-2026-000117 confermata", "nuovo host a Roma"])
        # la chiave di idempotenza in uscita deriva dall'id: il partner puo' deduplicare
        self.assertEqual([p["_outbox"]["message_id"] for p in visti], [1, 2])
        self.assertEqual(disp.status(), {"completed": 3, "dead_letter": 1})
        self.assertEqual(disp._fetch(), [])

    def test_la_dlq_storica_si_rimette_in_coda(self):
        """Manutenzione sul dato vecchio: il messaggio morto si ripesca, quello bloccato
        in 'processing' da un dispatcher morto si recupera."""
        self.apri(self.vecchio)
        disp = self._dispatcher(self.vecchio)
        self.assertEqual(disp.requeue_dead_letter(4), 1)
        self.assertEqual(disp.status(), {"pending": 2, "failed": 1, "completed": 1})
        self.assertEqual(sorted(r["id"] for r in disp._fetch()), [1, 2, 4])
        con = sqlite3.connect(self.vecchio)
        try:
            with con:
                con.execute("UPDATE outbox SET status='processing', locked_by='morto', "
                            "locked_at='2020-01-01T00:00:00+00:00' WHERE id=1")
        finally:
            con.close()
        self.assertEqual(disp.reclaim_stuck(), 1)
        self.assertEqual(disp.status(), {"pending": 1, "failed": 2, "completed": 1})


# ===========================================================================
# (b) 4. PAYOUT (fase131) - i soldi che devono ARRIVARE all'host.
#
# Archeologia: 11 commit hanno toccato il modulo, il `CREATE TABLE payout` e l'indice
# `ix_payout_host` sono gli stessi dal primo (fd959c96). Nessuno schema precedente da
# ricostruire: il rischio vero sta nei DATI scritti dal codice di allora.
# ===========================================================================
class TestPayoutFase131DatiVecchi(BaseMigrazione, unittest.TestCase):
    MODULO = "fase131_payout_dashboard"
    ORA = 1785000000
    DDL_V1 = (
        """CREATE TABLE IF NOT EXISTS payout (
                    prenotazione_id TEXT PRIMARY KEY, host_id TEXT NOT NULL,
                    minori INTEGER NOT NULL, valuta TEXT NOT NULL,
                    stato TEXT NOT NULL, ts INTEGER NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS ix_payout_host ON payout(host_id)",
    )
    _I = ("INSERT INTO payout (prenotazione_id, host_id, minori, valuta, stato, ts) "
          "VALUES (?,?,?,?,?,?)")
    RIGHE_V1 = (
        (_I, ("BV-2026-000117", "h_a1b2c3d4", 34040, "EUR", "maturato", 1784000000)),
        (_I, ("BV-2026-000118", "h_a1b2c3d4", 50600, "EUR", "in_transito", 1784100000)),
        (_I, ("BV-2026-000119", "h_a1b2c3d4", 12000, "EUR", "pagato", 1783000000)),
        (_I, ("BV-2026-000120", "h_zzz99999", 38640, "JPY", "maturato", 1782000000)),
        # LA RIGA DEL DIFETTO: scritta da `valuta.upper()` senza strip (codice fino al
        # 2026-07-29). Sta in archivio con una chiave che nessuna lettura ritrova.
        (_I, ("BV-2026-000121", "h_a1b2c3d4", 9900, " EUR ", "maturato", 1784200000)),
    )
    TABELLE = (("payout", ("prenotazione_id", "host_id", "minori", "stato", "ts"),
                "prenotazione_id"),)

    def apri(self, percorso):
        from fase131_payout_dashboard import crea_payout_dashboard
        archivio = crea_payout_dashboard(percorso, orologio=lambda: self.ORA)
        archivio.inizializza_schema()
        return archivio

    def leggi_col_prodotto(self, archivio):
        return {
            "riepilogo": archivio.riepilogo("h_a1b2c3d4"),
            # 34040 (maturato) + 9900 (maturato con la valuta sporca) + 50600 (in transito)
            "da_pagare_eur": archivio.da_pagare("h_a1b2c3d4", "EUR"),
            "da_pagare_jpy": archivio.da_pagare("h_zzz99999", "JPY"),
            "conta_pagati": archivio.conta_pagati("h_a1b2c3d4"),
            "info_117": archivio.info("BV-2026-000117"),
            "stato_121": archivio.stato_di("BV-2026-000121"),
            "elenca_eur": [r["prenotazione_id"]
                           for r in archivio.elenca("h_a1b2c3d4", valuta="EUR")],
            "maturati_di_tutti": [r["prenotazione_id"]
                                  for r in archivio.tutti(stato="maturato")],
        }

    def atteso_dal_prodotto(self):
        return {
            "riepilogo": {"EUR": {"maturato": 43940, "in_transito": 50600, "pagato": 12000}},
            "da_pagare_eur": 94540,
            "da_pagare_jpy": 38640,
            "conta_pagati": 4,
            "info_117": {"prenotazione_id": "BV-2026-000117", "host_id": "h_a1b2c3d4",
                         "minori": 34040, "valuta": "EUR", "stato": "maturato"},
            "stato_121": "maturato",
            # FIFO per ts: 119 (1783000000), 117 (1784000000), 118, 121
            "elenca_eur": ["BV-2026-000119", "BV-2026-000117", "BV-2026-000118",
                           "BV-2026-000121"],
            "maturati_di_tutti": ["BV-2026-000120", "BV-2026-000117", "BV-2026-000121"],
        }

    def test_la_valuta_sporca_del_codice_vecchio_e_riparata(self):
        """DIFETTO GRAVE CHIUSO. Il fix di `_norm_valuta` (2026-07-29) ha corretto solo le
        scritture NUOVE: la riga gia' in archivio con ' EUR ' restava invisibile a
        `riepilogo`/`da_pagare`/`elenca` -> 99,00 EUR dovuti all'host che nessun bonifico
        avrebbe mai pagato. La riparazione vive in `inizializza_schema` ed e' idempotente."""
        prima = righe(self.vecchio, "payout", ("prenotazione_id", "valuta"),
                      "prenotazione_id")
        self.assertIn(("BV-2026-000121", " EUR "), prima,
                      "il caso di prova non parte davvero da una valuta sporca")
        archivio = self.apri(self.vecchio)
        dopo = dict(righe(self.vecchio, "payout", ("prenotazione_id", "valuta"),
                          "prenotazione_id"))
        self.assertEqual(dopo["BV-2026-000121"], "EUR")
        self.assertEqual(dopo["BV-2026-000117"], "EUR")     # le pulite non si toccano
        self.assertEqual(dopo["BV-2026-000120"], "JPY")
        self.assertEqual(sorted(archivio.riepilogo("h_a1b2c3d4")), ["EUR"],
                         "il riepilogo ha ancora una chiave-valuta fantasma")
        self.assertEqual(archivio.da_pagare("h_a1b2c3d4", "EUR"), 94540)
        # e la riparazione non e' una scopa che riscrive tutto ad ogni avvio
        self.apri(self.vecchio)
        self.assertEqual(dict(righe(self.vecchio, "payout",
                                    ("prenotazione_id", "valuta"), "prenotazione_id")), dopo)

    def test_la_macchina_a_stati_di_oggi_governa_le_righe_di_ieri(self):
        """Le transizioni sono nate DOPO parte di queste righe: devono valere lo stesso,
        altrimenti si paga due volte un bonifico gia' uscito."""
        archivio = self.apri(self.vecchio)
        self.assertIs(archivio.aggiorna_stato("BV-2026-000117", "in_transito"), True)
        self.assertIs(archivio.aggiorna_stato("BV-2026-000117", "pagato"), True)
        self.assertEqual(archivio.stato_di("BV-2026-000117"), "pagato")
        # 'pagato' e' terminale: da li' non si torna indietro
        self.assertIs(archivio.aggiorna_stato("BV-2026-000117", "maturato"), False)
        self.assertIs(archivio.aggiorna_stato("BV-2026-000117", "in_transito"), False)
        self.assertEqual(archivio.stato_di("BV-2026-000117"), "pagato")
        # stato inesistente: rifiutato, e la riga resta intatta
        self.assertIs(archivio.aggiorna_stato("BV-2026-000118", "liquidato"), False)
        self.assertEqual(archivio.stato_di("BV-2026-000118"), "in_transito")
        # dopo il bonifico del 117 restano da pagare 50600 + 9900
        self.assertEqual(archivio.da_pagare("h_a1b2c3d4", "EUR"), 60500)

    def test_l_importo_di_una_riga_vecchia_si_riallinea_senza_perdere_la_storia(self):
        """Split di controversia / penale: il ledger deve dire quanto l'host riceve
        DAVVERO anche su una prenotazione registrata mesi fa."""
        archivio = self.apri(self.vecchio)
        self.assertIs(archivio.imposta_importo("BV-2026-000117", 17020), True)
        self.assertEqual(archivio.info("BV-2026-000117")["minori"], 17020)
        self.assertEqual(archivio.da_pagare("h_a1b2c3d4", "EUR"), 17020 + 50600 + 9900)
        self.assertIs(archivio.aumenta_payout("BV-2026-000117", 1500), True)
        self.assertEqual(archivio.info("BV-2026-000117")["minori"], 18520)
        # importo non valido: rifiutato, nessuna scrittura
        self.assertIs(archivio.imposta_importo("BV-2026-000117", 0), False)
        self.assertIs(archivio.aumenta_payout("BV-2026-000117", -1), False)
        self.assertEqual(archivio.info("BV-2026-000117")["minori"], 18520)
        # le altre valute non si contaminano mai
        self.assertEqual(archivio.da_pagare("h_zzz99999", "JPY"), 38640)
        self.assertEqual(archivio.da_pagare("h_a1b2c3d4", "JPY"), 0)


# ===========================================================================
# (b) 5. GARANZIA / ESCROW (fase160) - i soldi TRATTENUTI.
#
# Archeologia: 12 commit, `CREATE TABLE garanzia` immutato dal primo (761bbee8). Il
# rischio non e' la colonna: e' che la logica cresciuta (auto-rilascio con CAS, revive,
# conservazione esatta) sbagli su righe aperte prima che quelle regole esistessero.
# ===========================================================================
class TestGaranziaFase160DatiVecchi(BaseMigrazione, unittest.TestCase):
    MODULO = "fase160_escrow_garanzia"
    ORA = 1785000000
    DDL_V1 = (
        """CREATE TABLE IF NOT EXISTS garanzia (
                    prenotazione_id TEXT PRIMARY KEY,
                    alloggio_id TEXT NOT NULL DEFAULT '',
                    importo_host_cents INTEGER NOT NULL,
                    host_riceve_cents INTEGER NOT NULL DEFAULT 0,
                    ospite_rimborso_cents INTEGER NOT NULL DEFAULT 0,
                    stato TEXT NOT NULL DEFAULT 'in_garanzia',
                    motivo TEXT NOT NULL DEFAULT '',
                    sblocco_auto_ts INTEGER NOT NULL,
                    aperto_ts INTEGER NOT NULL,
                    aggiornato_ts INTEGER NOT NULL)""",
    )
    _G = ("INSERT INTO garanzia (prenotazione_id, alloggio_id, importo_host_cents, "
          "host_riceve_cents, ospite_rimborso_cents, stato, motivo, sblocco_auto_ts, "
          "aperto_ts, aggiornato_ts) VALUES (?,?,?,?,?,?,?,?,?,?)")
    RIGHE_V1 = (
        (_G, ("BV-2026-000117", "trastevere-attico-vista", 34040, 0, 0, "in_garanzia", "",
              1784000000, 1783900000, 1783900000)),
        (_G, ("BV-2026-000118", "trastevere-attico-vista", 50600, 0, 0, "contestato",
              "riscaldamento guasto", 1784086400, 1784000000, 1784003600)),
        (_G, ("BV-2026-000119", "shinjuku-monolocale", 38640, 0, 0, "annullato", "",
              1783000000, 1782900000, 1782950000)),
        # aperta di recente: la finestra si chiude fra cinque giorni, NON va rilasciata
        (_G, ("BV-2026-000122", "shinjuku-monolocale", 21000, 0, 0, "in_garanzia", "",
              ORA + 5 * 86400, ORA - 86400, ORA - 86400)),
    )
    TABELLE = (("garanzia", ("prenotazione_id", "alloggio_id", "importo_host_cents",
                             "host_riceve_cents", "ospite_rimborso_cents", "stato",
                             "motivo", "sblocco_auto_ts", "aperto_ts", "aggiornato_ts"),
                "prenotazione_id"),)

    def apri(self, percorso):
        from fase160_escrow_garanzia import crea_escrow_garanzia
        archivio = crea_escrow_garanzia(percorso, orologio=lambda: self.ORA)
        archivio.inizializza_schema()
        return archivio

    def leggi_col_prodotto(self, archivio):
        s117 = archivio.stato("BV-2026-000117")
        return {
            "stato_117": s117["stato"], "importo_117": s117["importo_host_cents"],
            "unita": s117["money_unit"],
            "aperte": [r["prenotazione_id"] for r in archivio.aperte()],
            "contestate": [r["prenotazione_id"] for r in archivio.contestate()],
            "motivo_118": archivio.stato("BV-2026-000118")["motivo"],
            "stato_119": archivio.stato("BV-2026-000119")["stato"],
            "aperte_per_alloggio": archivio.aperte_per_alloggio("trastevere-attico-vista"),
            # il Guardiano: 1784000000 e' passato da (1785000000-1784000000)/3600 = 277 ore
            "in_ritardo": [(r["prenotazione_id"], r["ore_di_ritardo"])
                           for r in archivio.aperte_scadute(ora_ts=self.ORA, grazia_ore=48)],
        }

    def atteso_dal_prodotto(self):
        return {
            "stato_117": "in_garanzia", "importo_117": 34040, "unita": "cents_integer",
            "aperte": ["BV-2026-000117", "BV-2026-000122"],
            "contestate": ["BV-2026-000118"],
            "motivo_118": "riscaldamento guasto",
            "stato_119": "annullato",
            "aperte_per_alloggio": 2,      # in_garanzia + contestato, l'annullato no
            # solo la 117 e' in ritardo: la 122 ha la finestra ancora aperta
            "in_ritardo": [("BV-2026-000117", 277)],
        }

    def test_l_escrow_vecchio_scaduto_paga_l_host_una_volta_sola(self):
        """La riga e' rimasta aperta oltre la finestra: il giro automatico deve versarla
        all'host, e un secondo giro NON deve pagarla di nuovo."""
        archivio = self.apri(self.vecchio)
        primo = archivio.auto_rilascia(ora_ts=self.ORA, dettagli=True)
        self.assertEqual(primo, [{"prenotazione_id": "BV-2026-000117",
                                  "host_riceve_cents": 34040}])
        s = archivio.stato("BV-2026-000117")
        self.assertEqual(s["stato"], "rilasciato")
        self.assertEqual(s["host_riceve_cents"], 34040)
        self.assertEqual(s["ospite_rimborso_cents"], 0)
        self.assertEqual(s["host_riceve_cents"] + s["ospite_rimborso_cents"],
                         s["importo_host_cents"])
        self.assertEqual(archivio.auto_rilascia(ora_ts=self.ORA, dettagli=True), [])
        self.assertEqual(archivio.aperte_scadute(ora_ts=self.ORA, grazia_ore=48), [])
        # la disputa storica NON e' stata toccata dal giro automatico
        self.assertEqual(archivio.stato("BV-2026-000118")["stato"], "contestato")
        # e nemmeno la garanzia la cui finestra si chiude fra cinque giorni: pagarla ora
        # significherebbe togliere all'ospite il diritto di contestare
        s122 = archivio.stato("BV-2026-000122")
        self.assertEqual(s122["stato"], "in_garanzia")
        self.assertEqual(s122["host_riceve_cents"], 0)
        self.assertEqual([r["prenotazione_id"] for r in archivio.aperte()],
                         ["BV-2026-000122"])

    def test_un_escrow_vecchio_su_prenotazione_rimborsata_non_paga_l_host(self):
        """Prevenzione del Guardiano: se la prenotazione e' stata rimborsata, l'escrow
        rimasto aperto si chiude a zero invece di regalare i soldi all'host."""
        archivio = self.apri(self.vecchio)
        rilasciati = archivio.auto_rilascia(
            ora_ts=self.ORA, dettagli=True,
            salta_se=lambda rif: rif == "BV-2026-000117")
        self.assertEqual(rilasciati, [])
        s = archivio.stato("BV-2026-000117")
        self.assertEqual(s["stato"], "annullato")
        self.assertEqual(s["host_riceve_cents"], 0)
        self.assertEqual(s["ospite_rimborso_cents"], 0)

    def test_la_disputa_vecchia_si_risolve_a_conservazione_esatta(self):
        archivio = self.apri(self.vecchio)
        esito = archivio.risolvi("BV-2026-000118", rimborso_ospite_cents=20000)
        self.assertEqual(esito, {"ok": True, "stato": "risolto",
                                 "host_riceve_cents": 30600,
                                 "ospite_rimborso_cents": 20000})
        s = archivio.stato("BV-2026-000118")
        self.assertEqual(s["host_riceve_cents"] + s["ospite_rimborso_cents"], 50600)
        # e da 'risolto' non si risolve una seconda volta
        self.assertEqual(archivio.risolvi("BV-2026-000118", rimborso_ospite_cents=50600),
                         {"ok": False, "motivo": "stato_non_valido", "stato": "risolto"})
        self.assertEqual(archivio.stato("BV-2026-000118")["host_riceve_cents"], 30600)

    def test_un_pagamento_tardivo_risuscita_la_garanzia_annullata_vecchia(self):
        """Il REVIVE (CAS da 'annullato') deve funzionare anche sulla riga scritta prima
        che quella regola esistesse: altrimenti il booking risulta pagato con l'escrow
        morto e l'host non viene mai pagato in automatico."""
        archivio = self.apri(self.vecchio)
        self.assertIs(archivio.apri("BV-2026-000119", 38640,
                                    alloggio_id="shinjuku-monolocale",
                                    ora_checkin_ts=self.ORA, finestra_ore=72), True)
        s = archivio.stato("BV-2026-000119")
        self.assertEqual(s["stato"], "in_garanzia")
        self.assertEqual(s["importo_host_cents"], 38640)
        self.assertEqual(s["sblocco_auto_ts"], self.ORA + 72 * 3600)
        # una garanzia gia' DECISA invece non si tocca (la storia chiusa resta chiusa)
        archivio.conferma_ospite("BV-2026-000117")
        self.assertEqual(archivio.stato("BV-2026-000117")["stato"], "rilasciato")
        self.assertIs(archivio.apri("BV-2026-000117", 99999,
                                    alloggio_id="trastevere-attico-vista"), True)
        s117 = archivio.stato("BV-2026-000117")
        self.assertEqual(s117["stato"], "rilasciato")
        self.assertEqual(s117["importo_host_cents"], 34040)


# ===========================================================================
# (b) 6. DOMANDA / lista d'attesa (fase158) - il volano di partenza.
#
# Archeologia: 5 commit, `CREATE TABLE domanda` immutato dal primo (809a474c). Il rischio
# e' la DEDUPLICA su righe vecchie: la lista d'attesa e' quella a cui il flywheel manda
# l'email quando il primo host pubblica in citta'.
# ===========================================================================
class TestDomandaFase158DatiVecchi(BaseMigrazione, unittest.TestCase):
    MODULO = "fase158_domanda"
    ORA = 1785000000
    DDL_V1 = (
        """CREATE TABLE IF NOT EXISTS domanda (
                    email TEXT NOT NULL, citta TEXT NOT NULL,
                    check_in TEXT DEFAULT '', check_out TEXT DEFAULT '',
                    party INTEGER DEFAULT 1, ts INTEGER NOT NULL,
                    PRIMARY KEY (email, citta))""",
    )
    _D = ("INSERT INTO domanda (email, citta, check_in, check_out, party, ts) "
          "VALUES (?,?,?,?,?,?)")
    RIGHE_V1 = (
        (_D, ("davide.realmuto@example.com", "roma", "2026-09-01", "2026-09-04", 2,
              1784000000)),
        (_D, ("laura.bianchi@example.com", "roma", "", "", 1, 1783000000)),
        (_D, ("kenji.sato@example.jp", "tokyo", "2026-11-02", "2026-11-06", 3, 1782000000)),
    )
    TABELLE = (("domanda", ("email", "citta", "check_in", "check_out", "party", "ts"),
                "email, citta"),)

    def apri(self, percorso):
        from fase158_domanda import crea_gestore_domanda
        from fase59_concierge import FirmaQuote
        archivio = crea_gestore_domanda(percorso, firma=FirmaQuote(SEGRETO),
                                        orologio=lambda: self.ORA)
        archivio.inizializza_schema()
        return archivio

    def leggi_col_prodotto(self, archivio):
        return {"totale": archivio.conta(), "roma": archivio.conta("roma"),
                "roma_maiuscolo": archivio.conta("  Roma "),
                "email_roma": sorted(archivio.email_citta("roma")),
                "classifica": archivio.per_citta()}

    def atteso_dal_prodotto(self):
        return {"totale": 3, "roma": 2, "roma_maiuscolo": 2,
                "email_roma": ["davide.realmuto@example.com", "laura.bianchi@example.com"],
                "classifica": [{"citta": "roma", "richieste": 2},
                               {"citta": "tokyo", "richieste": 1}]}

    def test_la_stessa_persona_non_si_duplica_sulla_riga_vecchia(self):
        """Se la normalizzazione di oggi non combaciasse con quella di allora, la stessa
        casella entrerebbe DUE volte: prova sociale gonfiata e, quando parte il volano,
        due email allo stesso ospite. Deve fare UPDATE della riga storica."""
        archivio = self.apri(self.vecchio)
        self.assertIs(archivio.registra("  Davide.RealMuto@Example.COM  ", " ROMA ",
                                        check_in="2026-10-01", check_out="2026-10-05",
                                        party=4), True)
        self.assertEqual(archivio.conta(), 3)
        self.assertEqual(archivio.conta("roma"), 2)
        self.assertEqual(sorted(archivio.email_citta("roma")),
                         ["davide.realmuto@example.com", "laura.bianchi@example.com"])
        riga = dict(zip(("email", "citta", "check_in", "check_out", "party"),
                        righe(self.vecchio, "domanda",
                              ("email", "citta", "check_in", "check_out", "party"),
                              "email, citta")[0]))
        self.assertEqual(riga, {"email": "davide.realmuto@example.com", "citta": "roma",
                                "check_in": "2026-10-01", "check_out": "2026-10-05",
                                "party": 4})
        # la STESSA email in un'altra citta' e' invece una domanda NUOVA
        self.assertIs(archivio.registra("davide.realmuto@example.com", "milano"), True)
        self.assertEqual(archivio.conta(), 4)
        self.assertEqual(archivio.conta("milano"), 1)

    def test_il_credito_fondatore_sul_lead_storico_e_firmato_e_in_valuta(self):
        """Il volano promette un Credito Fondatore al lead in lista d'attesa: sul lead
        vecchio dev'essere un token FIRMATO, con la valuta dentro (senza, 500 unita'
        minori valevano 5 EUR anche su un annuncio in yen)."""
        from fase158_domanda import CREDITO_FONDATORE_CENTS, GIORNI_VALIDITA
        from fase59_concierge import FirmaQuote
        archivio = self.apri(self.vecchio)
        token = archivio.emette_credito_fondatore("Davide.RealMuto@Example.COM", "Roma")
        self.assertIsInstance(token, str)
        dati = FirmaQuote(SEGRETO).decodifica(token)
        self.assertEqual(dati["tipo"], "credito_fondatore")
        self.assertEqual(dati["email"], "davide.realmuto@example.com")
        self.assertEqual(dati["citta"], "roma")
        self.assertEqual(dati["valuta"], "EUR")
        self.assertEqual(dati["credito_cents"], CREDITO_FONDATORE_CENTS)
        self.assertEqual(dati["exp"], self.ORA + GIORNI_VALIDITA * 86400)
        # manomesso di un carattere -> la firma non regge
        rotto = token[:-1] + ("0" if token[-1] != "0" else "1")
        self.assertIsNone(FirmaQuote(SEGRETO).decodifica(rotto))

    def test_una_domanda_malformata_non_sporca_l_archivio_storico(self):
        archivio = self.apri(self.vecchio)
        for email, citta in (("non-una-email", "roma"), ("a@b", "roma"),
                             ("mario@example.com", "   "), (None, "roma"),
                             ("mario\x00rossi@example.com", "roma")):
            self.assertIs(archivio.registra(email, citta), False,
                          "accettata una domanda non valida: %r / %r" % (email, citta))
        self.assertEqual(archivio.conta(), 3)
        self.assertEqual(archivio.per_citta(), [{"citta": "roma", "richieste": 2},
                                                {"citta": "tokyo", "richieste": 1}])


# ===========================================================================
# (b) 7. PARTNER (fase201) - candidature con consenso GDPR.
#
# Archeologia: 2 commit, `CREATE TABLE partner` immutato dal primo (3e98c535). Cambiata
# invece la VALIDAZIONE dell'email (commit 40bbf45): l'archivio puo' contenere righe che
# oggi non sarebbero piu' accettate.
# ===========================================================================
class TestPartnerFase201DatiVecchi(BaseMigrazione, unittest.TestCase):
    MODULO = "fase201_partner"
    ORA = 1785000000
    DDL_V1 = (
        """CREATE TABLE IF NOT EXISTS partner (
                    email TEXT PRIMARY KEY, nome TEXT NOT NULL, tipo TEXT NOT NULL,
                    citta TEXT DEFAULT '', messaggio TEXT DEFAULT '',
                    consenso INTEGER NOT NULL, ts INTEGER NOT NULL)""",
    )
    _P = ("INSERT INTO partner (email, nome, tipo, citta, messaggio, consenso, ts) "
          "VALUES (?,?,?,?,?,?,?)")
    RIGHE_V1 = (
        (_P, ("agenzia.tevere@example.com", "Agenzia Tevere", "agenzia", "roma",
              "Gestiamo 14 appartamenti in centro.", 1, 1784000000)),
        (_P, ("marco.creator@example.com", "Marco Neri", "creator", "roma", "", 1,
              1783000000)),
        # scritta dal codice PRIMA che `_email_norm` rifiutasse gli spazi interni:
        # resta in archivio ma non e' piu' ri-registrabile
        (_P, ("mario rossi@example.com", "Mario Rossi", "property_manager", "milano",
              "Otto unita' in zona Navigli.", 1, 1782000000)),
    )
    TABELLE = (("partner", ("email", "nome", "tipo", "citta", "messaggio", "consenso", "ts"),
                "email"),)

    def apri(self, percorso):
        from fase201_partner import crea_gestore_partner
        archivio = crea_gestore_partner(percorso, orologio=lambda: self.ORA)
        archivio.inizializza_schema()
        return archivio

    def leggi_col_prodotto(self, archivio):
        elenco = archivio.candidati()
        return {"quanti": archivio.conta(),
                "email": [c["email"] for c in elenco],       # ts DESC
                "primo_nome": elenco[0]["nome"],
                "primo_messaggio": elenco[0]["messaggio"],
                "primo_tipo": elenco[0]["tipo"],
                "chiavi": sorted(elenco[0])}

    def atteso_dal_prodotto(self):
        return {"quanti": 3,
                "email": ["agenzia.tevere@example.com", "marco.creator@example.com",
                          "mario rossi@example.com"],
                "primo_nome": "Agenzia Tevere",
                "primo_messaggio": "Gestiamo 14 appartamenti in centro.",
                "primo_tipo": "agenzia",
                # l'elenco per l'admin non espone il consenso grezzo ne' altro
                "chiavi": ["citta", "email", "messaggio", "nome", "tipo", "ts"]}

    def test_la_candidatura_vecchia_si_aggiorna_e_non_si_sdoppia(self):
        archivio = self.apri(self.vecchio)
        esito = archivio.registra("Agenzia Tevere Srl", "  Agenzia.Tevere@Example.com  ",
                                  "agenzia", citta="Roma",
                                  messaggio="Ora ne gestiamo 22.", consenso=True)
        self.assertEqual(esito, {"ok": True})
        self.assertEqual(archivio.conta(), 3)
        primo = archivio.candidati()[0]
        self.assertEqual(primo["email"], "agenzia.tevere@example.com")
        self.assertEqual(primo["nome"], "Agenzia Tevere Srl")
        self.assertEqual(primo["messaggio"], "Ora ne gestiamo 22.")
        self.assertEqual(primo["ts"], self.ORA)

    def test_la_riga_storica_non_piu_valida_resta_ma_non_si_rigenera(self):
        """L'email con lo spazio interno e' stata scritta da una validazione piu' debole:
        il dato storico NON si perde (sarebbe una cancellazione silenziosa), ma oggi non
        si puo' aggiungerne un'altra dello stesso genere."""
        archivio = self.apri(self.vecchio)
        self.assertIn("mario rossi@example.com",
                      [c["email"] for c in archivio.candidati()])
        self.assertEqual(archivio.registra("Mario Rossi", "mario rossi@example.com",
                                           "property_manager", consenso=True),
                         {"errore": "email_non_valida"})
        self.assertEqual(archivio.conta(), 3)

    def test_il_consenso_gdpr_vale_anche_sull_archivio_vecchio(self):
        """Senza consenso ESPLICITO (True, non 'si') non si scrive NULLA: e' l'obbligo
        GDPR, e vale identico su un archivio che contiene gia' candidature."""
        archivio = self.apri(self.vecchio)
        self.assertEqual(archivio.registra("Nuovo Partner", "nuovo@example.com",
                                           "agenzia", consenso=False),
                         {"errore": "consenso_richiesto"})
        self.assertEqual(archivio.registra("Nuovo Partner", "nuovo@example.com",
                                           "agenzia", consenso="si"),
                         {"errore": "consenso_richiesto"})
        self.assertEqual(archivio.registra("Nuovo Partner", "nuovo@example.com",
                                           "agenzia", consenso=1),
                         {"errore": "consenso_richiesto"})
        self.assertEqual(archivio.conta(), 3)
        self.assertEqual(archivio.registra("Nuovo Partner", "nuovo@example.com",
                                           "tipo_inventato", consenso=True),
                         {"errore": "tipo_non_valido"})
        self.assertEqual(archivio.registra("X", "nuovo@example.com", "agenzia",
                                           consenso=True), {"errore": "nome_non_valido"})
        self.assertEqual(archivio.conta(), 3)
        self.assertEqual(archivio.registra("Nuovo Partner", "nuovo@example.com",
                                           "agenzia", consenso=True), {"ok": True})
        self.assertEqual(archivio.conta(), 4)

    def test_un_archivio_pieno_di_righe_vecchie_non_chiude_il_canale(self):
        """Il tetto e' ORARIO (`WHERE ts > adesso-3600`): se contasse tutte le righe,
        un archivio maturo - piu' di MAX_CANDIDATURE_ORA candidature storiche - direbbe
        'riprova_piu_tardi' per sempre e il canale partner morirebbe in silenzio."""
        from fase201_partner import MAX_CANDIDATURE_ORA
        con = sqlite3.connect(self.vecchio)
        try:
            with con:
                for i in range(MAX_CANDIDATURE_ORA + 5):
                    con.execute(
                        "INSERT INTO partner (email, nome, tipo, citta, messaggio, "
                        "consenso, ts) VALUES (?,?,?,?,?,?,?)",
                        ("storico%02d@example.com" % i, "Storico %02d" % i, "agenzia",
                         "roma", "", 1, self.ORA - 30 * 86400))
        finally:
            con.close()
        archivio = self.apri(self.vecchio)
        self.assertEqual(archivio.conta(), 3 + MAX_CANDIDATURE_ORA + 5)
        self.assertEqual(archivio.registra("Nuovo Partner", "nuovo@example.com",
                                           "agenzia", consenso=True), {"ok": True})
        self.assertEqual(archivio.conta(), 4 + MAX_CANDIDATURE_ORA + 5)
        self.assertEqual(archivio.candidati()[0]["email"], "nuovo@example.com")


# ===========================================================================
# (b) 8. OPERATORI ADMIN (fase192) - chi puo' entrare nel bunker.
#
# Archeologia: 1 solo commit (54185f57), schema immutato per definizione. Qui conta che
# le CREDENZIALI storiche continuino a funzionare - e che una revoca sia istantanea.
# ===========================================================================
class TestAdminAccountsFase192DatiVecchi(BaseMigrazione, unittest.TestCase):
    MODULO = "fase192_admin_accounts"
    SALT = bytes.fromhex("aabbccddeeff00112233445566778899")
    PASSWORD = "operatore-supporto-2026"
    DDL_V1 = (
        """CREATE TABLE IF NOT EXISTS admin_account (
                    email TEXT PRIMARY KEY, salt TEXT NOT NULL, pw_hash TEXT NOT NULL,
                    ruolo TEXT NOT NULL, attivo INTEGER NOT NULL DEFAULT 1,
                    creato_ts INTEGER NOT NULL, creato_da TEXT NOT NULL DEFAULT '')""",
    )
    TABELLE = (("admin_account", ("email", "salt", "pw_hash", "ruolo", "attivo",
                                  "creato_ts", "creato_da"), "email"),)

    def setUp(self):
        from fase192_admin_accounts import _hash
        self.RIGHE_V1 = (
            ("INSERT INTO admin_account (email, salt, pw_hash, ruolo, attivo, creato_ts, "
             "creato_da) VALUES (?,?,?,?,?,?,?)",
             ("supporto@bookinvip.com", self.SALT.hex(), _hash(self.PASSWORD, self.SALT),
              "supporto", 1, 1767225600, "root")),
            ("INSERT INTO admin_account (email, salt, pw_hash, ruolo, attivo, creato_ts, "
             "creato_da) VALUES (?,?,?,?,?,?,?)",
             ("exdipendente@bookinvip.com", self.SALT.hex(), _hash("vecchia-2025", self.SALT),
              "admin", 0, 1760000000, "root")),
        )
        BaseMigrazione.setUp(self)

    def apri(self, percorso):
        from fase192_admin_accounts import crea_admin_accounts
        return crea_admin_accounts(percorso)

    def leggi_col_prodotto(self, archivio):
        buono = archivio.verifica("supporto@bookinvip.com", self.PASSWORD)
        maiuscolo = archivio.verifica("  Supporto@BookinVIP.com ", self.PASSWORD)
        revocato = archivio.verifica("exdipendente@bookinvip.com", "vecchia-2025")
        sbagliata = archivio.verifica("supporto@bookinvip.com", "password-sbagliata")
        return {"ok": buono["ok"], "ruolo": buono["ruolo"],
                "maiuscolo_ok": maiuscolo["ok"],
                "revocato": revocato,
                "sbagliata": sbagliata,
                "ruolo_attivo": archivio.ruolo_attivo("supporto@bookinvip.com"),
                "ruolo_revocato": archivio.ruolo_attivo("exdipendente@bookinvip.com"),
                "quanti": len(archivio.lista()),
                "chiavi_lista": sorted(archivio.lista()[0])}

    def atteso_dal_prodotto(self):
        return {"ok": True, "ruolo": "supporto", "maiuscolo_ok": True,
                "revocato": {"ok": False, "errore": "account_revocato"},
                "sbagliata": {"ok": False, "errore": "credenziali_non_valide"},
                "ruolo_attivo": "supporto", "ruolo_revocato": None, "quanti": 2,
                # l'elenco non deve MAI far uscire salt e impronta della password
                "chiavi_lista": ["attivo", "creato_da", "creato_ts", "email", "ruolo"]}

    def test_i_permessi_dell_operatore_storico_sono_quelli_di_oggi(self):
        """Le azioni-soldi sono nate come lista chiusa: l'operatore 'supporto' registrato
        mesi fa non deve poterle fare, e un ruolo ignoto va negato (fail-closed)."""
        from fase192_admin_accounts import puo
        archivio = self.apri(self.vecchio)
        ruolo = archivio.ruolo_attivo("supporto@bookinvip.com")
        self.assertEqual(ruolo, "supporto")
        for azione in ("rimborso", "storno_penale", "cancella_attivita",
                       "alloggio_stato", "controversia_risolvi", "blocco_globale"):
            self.assertIs(puo(ruolo, azione), False, "supporto puo' fare %r" % azione)
        for azione in ("ricerca", "prenotazioni", "verifiche"):
            self.assertIs(puo(ruolo, azione), True)
        self.assertIs(puo("admin", "rimborso"), True)
        self.assertIs(puo(None, "ricerca"), False)
        self.assertIs(puo("root", "ricerca"), False)

    def test_promozione_e_revoca_sulla_riga_storica_hanno_effetto_istantaneo(self):
        archivio = self.apri(self.vecchio)
        self.assertIs(archivio.imposta_ruolo("SUPPORTO@bookinvip.com", "admin"), True)
        self.assertEqual(archivio.ruolo_attivo("supporto@bookinvip.com"), "admin")
        self.assertEqual(archivio.verifica("supporto@bookinvip.com",
                                           self.PASSWORD)["ruolo"], "admin")
        self.assertIs(archivio.imposta_ruolo("supporto@bookinvip.com", "capo"), False)
        self.assertEqual(archivio.ruolo_attivo("supporto@bookinvip.com"), "admin")
        self.assertIs(archivio.revoca("supporto@bookinvip.com"), True)
        self.assertIsNone(archivio.ruolo_attivo("supporto@bookinvip.com"))
        self.assertEqual(archivio.verifica("supporto@bookinvip.com", self.PASSWORD),
                         {"ok": False, "errore": "account_revocato"})
        # la revoca disattiva, NON cancella: l'account resta nell'audit storico
        self.assertEqual(len(archivio.lista()), 2)
        self.assertEqual(sorted(r["email"] for r in archivio.lista()),
                         ["exdipendente@bookinvip.com", "supporto@bookinvip.com"])
        self.assertIs(archivio.riattiva("exdipendente@bookinvip.com"), True)
        self.assertEqual(archivio.ruolo_attivo("exdipendente@bookinvip.com"), "admin")

    def test_un_account_inesistente_non_rivela_nulla(self):
        archivio = self.apri(self.vecchio)
        self.assertEqual(archivio.verifica("mai.esistito@bookinvip.com", "qualsiasi"),
                         {"ok": False, "errore": "credenziali_non_valide"})
        self.assertIsNone(archivio.ruolo_attivo("mai.esistito@bookinvip.com"))
        self.assertIs(archivio.imposta_ruolo("mai.esistito@bookinvip.com", "admin"), False)
        self.assertIs(archivio.revoca("mai.esistito@bookinvip.com"), False)
        self.assertEqual(len(archivio.lista()), 2)


# ===========================================================================
# IL CONTROLLO SA FALLIRE (visto rosso PERMANENTE)
# ===========================================================================
class TestIlControlloSaFallire(unittest.TestCase):
    """Un controllo che non puo' fallire e' un ornamento. Qui si simulano i guasti che
    questo file deve vedere e si pretende che i controlli li boccino - con la controprova
    che su un caso sano non gridano."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="migrmanc_rosso_")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def _db(self, ddl, dati, nome):
        p = os.path.join(self.dir, nome)
        scrivi_db_vecchio(p, ddl, dati)
        return p

    def test_una_colonna_mai_migrata_viene_vista(self):
        vecchio = self._db(("CREATE TABLE t (a INTEGER PRIMARY KEY, b TEXT)",),
                           (("INSERT INTO t (a, b) VALUES (?,?)", (1, "x")),), "v.db")
        nuovo = self._db(("CREATE TABLE t (a INTEGER PRIMARY KEY, b TEXT, "
                          "priorita INTEGER NOT NULL DEFAULT 1)",), (), "n.db")
        self.assertEqual(sorted(set(colonne(nuovo, "t")) - set(colonne(vecchio, "t"))),
                         ["priorita"])

    def test_una_colonna_migrata_non_da_falsi_allarmi(self):
        vecchio = self._db(("CREATE TABLE t (a INTEGER PRIMARY KEY, b TEXT)",), (), "v2.db")
        con = sqlite3.connect(vecchio)
        try:
            with con:
                con.execute("ALTER TABLE t ADD COLUMN priorita INTEGER NOT NULL DEFAULT 1")
        finally:
            con.close()
        nuovo = self._db(("CREATE TABLE t (a INTEGER PRIMARY KEY, b TEXT, "
                          "priorita INTEGER NOT NULL DEFAULT 1)",), (), "n2.db")
        self.assertEqual(sorted(colonne(vecchio, "t")), sorted(colonne(nuovo, "t")))

    def test_un_indice_con_lo_STESSO_NOME_ma_definizione_vecchia_viene_visto(self):
        """E' il difetto trovato in fase16: il nome combacia, la definizione no, e
        `CREATE INDEX IF NOT EXISTS` non se ne accorge. Il confronto per NOME e' cieco,
        quello per DEFINIZIONE no."""
        vecchio = self._db(("CREATE TABLE t (s TEXT, p INTEGER, n TEXT, id INTEGER)",
                            "CREATE INDEX IF NOT EXISTS ix_due ON t(s, n, id)"), (), "iv.db")
        nuovo = self._db(("CREATE TABLE t (s TEXT, p INTEGER, n TEXT, id INTEGER)",
                          "CREATE INDEX IF NOT EXISTS ix_due ON t(s, p, n, id)"), (), "in.db")
        con = sqlite3.connect(vecchio)
        try:                                   # il CREATE ... IF NOT EXISTS non sostituisce
            with con:
                con.execute("CREATE INDEX IF NOT EXISTS ix_due ON t(s, p, n, id)")
        finally:
            con.close()
        self.assertEqual(oggetti(vecchio, "index"), oggetti(nuovo, "index"),
                         "i NOMI combaciano: e' proprio questo che rende cieco il confronto")
        self.assertNotEqual(indici_sql(vecchio)["ix_due"], indici_sql(nuovo)["ix_due"],
                            "il confronto per DEFINIZIONE non vede l'indice rimasto vecchio")

    def test_un_dato_storico_alterato_viene_visto(self):
        p = self._db(("CREATE TABLE soldi (id INTEGER PRIMARY KEY, cents INTEGER NOT NULL)",),
                     (("INSERT INTO soldi (id, cents) VALUES (?,?)", (1, 34040)),), "s.db")
        prima = righe(p, "soldi", ("id", "cents"), "id")
        con = sqlite3.connect(p)
        try:
            with con:
                con.execute("UPDATE soldi SET cents=34039 WHERE id=1")
        finally:
            con.close()
        self.assertNotEqual(righe(p, "soldi", ("id", "cents"), "id"), prima,
                            "il confronto dei valori non vede un centesimo cambiato")

    def test_una_riga_persa_viene_vista(self):
        p = self._db(("CREATE TABLE soldi (id INTEGER PRIMARY KEY, cents INTEGER NOT NULL)",),
                     (("INSERT INTO soldi (id, cents) VALUES (?,?)", (1, 34040)),
                      ("INSERT INTO soldi (id, cents) VALUES (?,?)", (2, 50600))), "p.db")
        prima = righe(p, "soldi", ("id", "cents"), "id")
        con = sqlite3.connect(p)
        try:
            with con:
                con.execute("DELETE FROM soldi WHERE id=2")
        finally:
            con.close()
        dopo = righe(p, "soldi", ("id", "cents"), "id")
        self.assertEqual(len(prima), 2)
        self.assertEqual(len(dopo), 1)
        self.assertNotEqual(dopo, prima, "il confronto non vede una riga sparita")

    def test_una_valuta_sporca_e_diversa_da_una_pulita(self):
        """L'osservabile del difetto fase131: ' EUR ' e 'EUR' sono due chiavi diverse in
        un GROUP BY, ed e' esattamente cosi' che i soldi sparivano dalla dashboard."""
        p = self._db(("CREATE TABLE payout (rif TEXT PRIMARY KEY, valuta TEXT, m INTEGER)",),
                     (("INSERT INTO payout VALUES (?,?,?)", ("a", "EUR", 100)),
                      ("INSERT INTO payout VALUES (?,?,?)", ("b", " EUR ", 900))), "val.db")
        con = sqlite3.connect(p)
        try:
            gruppi = dict(con.execute("SELECT valuta, SUM(m) FROM payout GROUP BY valuta"))
        finally:
            con.close()
        self.assertEqual(gruppi, {"EUR": 100, " EUR ": 900})
        self.assertEqual(gruppi.get("EUR"), 100,
                         "senza riparazione la riga da 900 non entra nel totale 'EUR'")


# ===========================================================================
# NESSUNA `ALTER TABLE` SENZA PROVA: la guardia auto-applicante che impedisce
# al debito (a) di riaprirsi.
# ===========================================================================
class TestNessunaAlterTableSenzaProva(unittest.TestCase):

    # I moduli con schema coperto QUI (ogni voce = una classe di prova reale).
    COPERTI_QUI = ("fase34_prenotazioni", "fase63_recensioni", "fase16_outbox",
                   "fase131_payout_dashboard", "fase160_escrow_garanzia",
                   "fase158_domanda", "fase201_partner", "fase192_admin_accounts")

    @staticmethod
    def _moduli_con_alter():
        trovati = set()
        for nome in sorted(os.listdir(RADICE)):
            if not (nome.startswith("fase") and nome.endswith(".py")):
                continue
            modulo = nome[:-3]
            if "ALTER TABLE" in sorgente(modulo):
                trovati.add(modulo)
        return trovati

    @staticmethod
    def _coperti_dall_altro_file():
        """I moduli dichiarati in `test_migrazioni_schema.TestNessunArchivioSenzaProva`.
        Letti dal sorgente (nessun import): se la lista sparisse, questo test grida."""
        percorso = os.path.join(RADICE, "test_migrazioni_schema.py")
        with open(percorso, "r", encoding="utf-8") as f:
            testo = f.read()
        blocco = re.search(r"COPERTI\s*=\s*\((.*?)\)\n", testo, re.S)
        return set(re.findall(r"[\"'](fase\w+)[\"']", blocco.group(1))) if blocco else set()

    def test_le_classi_di_questo_file_coprono_i_moduli_dichiarati(self):
        provati = set()
        for nome, oggetto in sorted(globals().items()):
            if not (isinstance(oggetto, type) and issubclass(oggetto, BaseMigrazione)
                    and oggetto is not BaseMigrazione):
                continue
            # `apri` importa il modulo per nome: il nome compare fra i co_names solo se
            # l'import e' scritto li' dentro (import pigro, come nel prodotto). Cosi' la
            # classe non puo' dichiarare un MODULO che poi non apre davvero.
            self.assertIn(oggetto.MODULO, oggetto.apri.__code__.co_names,
                          "%s: `apri` non importa %s, il MODULO dichiarato non e' quello "
                          "davvero sotto esame" % (nome, oggetto.MODULO))
            provati.add(oggetto.MODULO)
            self.assertTrue(oggetto.DDL_V1, "%s: schema vecchio non dichiarato" % nome)
            self.assertTrue(oggetto.TABELLE, "%s: tabelle non dichiarate" % nome)
            self.assertTrue(oggetto.MODULO, "%s: MODULO non dichiarato" % nome)
            self.assertTrue(os.path.isfile(os.path.join(RADICE, oggetto.MODULO + ".py")),
                            "%s: MODULO inesistente (%s)" % (nome, oggetto.MODULO))
        self.assertEqual(sorted(provati), sorted(self.COPERTI_QUI),
                         "l'elenco dei moduli coperti non corrisponde alle classi di prova")

    def test_ogni_alter_table_del_prodotto_ha_la_sua_prova(self):
        """LA GUARDIA CHE CHIUDE IL DEBITO: se domani nasce un modulo con una ALTER TABLE
        e nessuno gli scrive la prova di migrazione, questo controllo lo dice - qui,
        invece che sul database vero al primo deploy."""
        altri = self._coperti_dall_altro_file()
        self.assertIn("fase57_vetrina", altri,
                      "l'elenco COPERTI di test_migrazioni_schema.py non e' piu' leggibile: "
                      "questa guardia diventerebbe cieca")
        scoperti = sorted(self._moduli_con_alter() - set(self.COPERTI_QUI) - altri)
        self.assertEqual(
            scoperti, [],
            "questi moduli MIGRANO lo schema (ALTER TABLE) e nessuna classe lo prova: %r - "
            "un database vero, al primo deploy, risponderebbe 'no such column'" % (scoperti,))

    def test_il_controllo_vedrebbe_un_modulo_scoperto(self):
        """Controprova: se il modulo scoperto ci fosse, l'insieme non sarebbe vuoto."""
        finti = self._moduli_con_alter() | {"fase999_immaginario"}
        scoperti = sorted(finti - set(self.COPERTI_QUI) - self._coperti_dall_altro_file())
        self.assertEqual(scoperti, ["fase999_immaginario"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
