"""MIGRAZIONI DI SCHEMA — un database VECCHIO, aperto dal codice di OGGI, non deve perdere
nulla e non deve esplodere.

IL BUCO CHE QUESTO FILE CHIUDE
------------------------------
Sul server vivono database SQLite nati mesi fa. Il codice, negli anni, ha aggiunto colonne
(`alloggi.indirizzo`, `alloggi.pin_manuale`, `alloggi.cin`, `host.stripe_account_id`,
`pendenti.corpo_json`, `tassa_riscossione.stornato`, `accettazioni.riferimento`,
`checkin.revocato`, `marche.qualificata`...). Ogni test della suite parte da un database
NUOVO: il `CREATE TABLE` scrive l'ultima versione dello schema e la migrazione non viene
MAI esercitata. E' il modo di rompersi n.8 del CLAUDE.md (ambiente diverso: locale != VPS)
nella sua forma piu' cara — la suite e' verde, il deploy sui dati veri esplode:

    sqlite3.OperationalError: no such column: stornato

perche' `totale_riscosso` filtra `stornato=0`, `info_host` SELECT-a venti colonne aggiunte
dopo, `elenco` accettazioni SELECT-a `riferimento`. Nessuna di quelle query e' difesa da un
try/except: sono 500 in faccia all'utente, o peggio, silenzi.

COSA VERIFICA, PER OGNI ARCHIVIO DEL PRODOTTO
---------------------------------------------
  1. si costruisce A MANO un database nel formato VECCHIO (il `CREATE TABLE` del primo
     commit di quel modulo, congelato qui sotto) e lo si riempie di righe realistiche;
  2. lo si apre col codice ATTUALE (`inizializza_schema` / prima query);
  3. LE COLONNE: l'insieme delle colonne del db migrato dev'essere IDENTICO a quello di un
     db nuovo di zecca creato dallo stesso codice. E' questa la guardia che manca a tutti:
     il giorno in cui qualcuno aggiunge una colonna al `CREATE TABLE` senza aggiungere la
     `ALTER TABLE ... ADD COLUMN`, il db nuovo ce l'ha e il db vecchio no -> ROSSO QUI,
     invece che in produzione. Stessa cosa per indici e trigger (l'immutabilita' del libro
     giornale e' fatta di trigger: su un archivio vecchio devono esserci anche li').
  4. I DATI: ogni riga vecchia dev'essere ancora presente e IDENTICA, valore per valore,
     sulle colonne che esistevano prima (nessuna riga persa, nessun numero cambiato);
  5. IL PRODOTTO: le API vere (`dettaglio`, `login`, `totale_riscosso`, `verifica_catena`,
     `elenco`...) devono leggere quei dati vecchi e restituire i valori ESATTI attesi;
  6. IDEMPOTENZA: riaprire una seconda e una terza volta dev'essere un no-op — stesso
     schema, stesse righe, stessi valori (una migrazione che riparte da capo a ogni avvio
     e' una bomba a orologeria su un file da centinaia di MB).

  7. IL DEPLOY VERO: `TestAvvioSuArchiviVecchi` ricostruisce una /data intera di archivi
     vecchi, accende il SISTEMA (bootstrap + router) e chiede al sito quello che
     chiederebbe un cliente. E' l'unico controllo che vede anche il CABLAGGIO: uno store
     a cui il bootstrap non chiama `inizializza_schema` non si migra mai.

VISTO ROSSO (regola aurea: nessun verde vale finche' non e' stato visto rosso)
------------------------------------------------------------------------------
Il 2026-07-29 ogni famiglia di controlli e' stata provata rimettendo il guasto nel codice
di produzione, uno alla volta; dopo ogni prova il file e' stato ripristinato byte per byte
e lo sha256 confrontato prima/dopo (tutti identici, `git status` pulito):

  - tolto `("indirizzo", "TEXT NOT NULL DEFAULT ''")` dalla lista di migrazione di
    `fase57_vetrina.inizializza_schema`
      -> ROSSO: "alloggi: colonne MANCANTI nel db migrato: ['indirizzo']";
  - tolta la `ALTER TABLE tassa_riscossione ADD COLUMN stornato` (fase147)
      -> ROSSO su 3 controlli + `storna()` che torna False (la tassa gia' rimborsata
         resterebbe da versare al Comune);
  - tolta la `ALTER TABLE accettazioni ADD COLUMN riferimento` (fase163)
      -> ROSSO: `elenco()` non legge piu' nulla, la prova legale sparisce;
  - tolta la `ALTER TABLE checkin ADD COLUMN revocato` (fase127)
      -> ROSSO: la colonna che spegne lo smart-pass non c'e';
  - tolta la `DROP INDEX IF EXISTS idx_marca_giorno` (fase184)
      -> ROSSO: indici diversi da un archivio nuovo, la marca qualificata verrebbe
         rifiutata come duplicato;
  - tolta la riga `tassa_comunale.inizializza_schema()` dal CABLAGGIO
    (`fase81_bootstrap_casavip`)
      -> ROSSO su `TestAvvioSuArchiviVecchi.test_dopo_l_accensione_ogni_archivio_e_migrato`
         ("tassa_riscossione.stornato non migrata all'accensione del sistema").

La prova e' anche automatizzata e PERMANENTE in `TestIlControlloSaFallire`, che simula una
migrazione dimenticata, una riga alterata, una riga persa e un trigger mancante, e pretende
che i controlli le boccino (con la controprova che su un caso sano NON gridano).
"""
import hashlib
import hmac
import os
import shutil
import sqlite3
import tempfile
import unittest


# ---------------------------------------------------------------------------
# Attrezzi (nessuna magia: sqlite3 nudo, cosi' il controllo e' indipendente dal
# codice che deve giudicare)
# ---------------------------------------------------------------------------
def colonne(percorso, tabella):
    """Nomi delle colonne, nell'ordine fisico, letti dal file."""
    con = sqlite3.connect(percorso)
    try:
        return [r[1] for r in con.execute("PRAGMA table_info(%s)" % tabella).fetchall()]
    finally:
        con.close()


def oggetti(percorso, tipo):
    """Nomi degli oggetti di schema di un tipo ('table'|'index'|'trigger'), esclusi
    quelli generati da SQLite (sqlite_autoindex_*, sqlite_sequence)."""
    con = sqlite3.connect(percorso)
    try:
        righe = con.execute(
            "SELECT name FROM sqlite_master WHERE type=? ORDER BY name", (tipo,)).fetchall()
    finally:
        con.close()
    return sorted(r[0] for r in righe if not r[0].startswith("sqlite_"))


def righe(percorso, tabella, colonne_volute, ordine):
    """Le righe come tuple di valori ESATTI, ordinate in modo stabile."""
    con = sqlite3.connect(percorso)
    try:
        # nomi di tabella/colonna non sono parametrizzabili in SQL; qui vengono tutti da
        # costanti scritte in questo file, mai da input esterno.
        sql = ("SELECT %s FROM %s ORDER BY %s"      # noqa: S608
               % (", ".join(colonne_volute), tabella, ordine))
        return [tuple(r) for r in con.execute(sql).fetchall()]
    finally:
        con.close()


def scrivi_db_vecchio(percorso, ddl, inserimenti):
    """Costruisce il database nel formato VECCHIO e lo riempie."""
    con = sqlite3.connect(percorso)
    try:
        with con:
            for istruzione in ddl:
                con.execute(istruzione)
            for sql, parametri in inserimenti:
                con.execute(sql, parametri)
    finally:
        con.close()


SEGRETO = b"segreto-di-collaudo-migrazioni-32bytes!!"


# ---------------------------------------------------------------------------
# La base comune: ogni archivio dichiara il proprio schema VECCHIO, le righe
# vecchie e come lo si apre col codice di oggi. I controlli sono questi, uguali
# per tutti.
# ---------------------------------------------------------------------------
class BaseMigrazione(object):
    DDL_V1 = ()             # schema del PRIMO commit del modulo (congelato)
    RIGHE_V1 = ()           # (sql, parametri) di dati realistici
    TABELLE = ()            # (nome_tabella, colonne_v1, order_by)
    COLONNE_AGGIUNTE = {}   # tabella -> colonne che la migrazione DEVE aggiungere

    # ---- da implementare nella sottoclasse -------------------------------
    def apri(self, percorso):
        raise NotImplementedError

    def leggi_col_prodotto(self, archivio):
        """Cosa risponde il PRODOTTO leggendo i dati vecchi."""
        raise NotImplementedError

    def atteso_dal_prodotto(self):
        raise NotImplementedError

    # ---- attrezzatura ----------------------------------------------------
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="migr_")
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
                 "table": oggetti(percorso, "table")}
        for tab, _cols, _ord in self.TABELLE:
            stato["col:" + tab] = sorted(colonne(percorso, tab))
        return stato

    # ---- I CONTROLLI (uno per difetto) -----------------------------------
    def test_le_colonne_del_db_vecchio_sono_quelle_del_db_nuovo(self):
        """LA GUARDIA CHIAVE: una colonna aggiunta al CREATE TABLE senza la ALTER
        corrispondente esiste sul db nuovo e NON sul db vecchio. Qui diventa rossa."""
        self.apri(self.vecchio)
        self.apri(self.nuovo)               # db vergine creato dallo stesso codice
        for tab, _cols, _ord in self.TABELLE:
            attese = set(colonne(self.nuovo, tab))
            trovate = set(colonne(self.vecchio, tab))
            mancanti = sorted(attese - trovate)
            di_troppo = sorted(trovate - attese)
            self.assertEqual(
                mancanti, [],
                "%s: colonne MANCANTI nel db migrato: %r — il codice di oggi le usa nelle "
                "query, sui dati veri sarebbe 'no such column'" % (tab, mancanti))
            self.assertEqual(
                di_troppo, [],
                "%s: il db migrato ha colonne che il db nuovo non ha: %r" % (tab, di_troppo))

    def test_la_migrazione_aggiunge_proprio_le_colonne_dichiarate(self):
        """Le colonne nate DOPO devono comparire davvero (e prima non c'erano: se il
        formato vecchio le avesse gia', questo controllo non proverebbe nulla)."""
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
                self.assertIn(c, dopo, "%s.%s non e' stata aggiunta dalla migrazione" % (tab, c))

    def test_nessuna_riga_persa_nessun_valore_alterato(self):
        prima = self._foto_dati(self.vecchio)
        self.apri(self.vecchio)
        dopo = self._foto_dati(self.vecchio)
        for tab, _cols, _ord in self.TABELLE:
            self.assertEqual(
                len(dopo[tab]), len(prima[tab]),
                "%s: la migrazione ha cambiato il NUMERO di righe (%d -> %d)"
                % (tab, len(prima[tab]), len(dopo[tab])))
            self.assertEqual(
                dopo[tab], prima[tab],
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

    def test_indici_e_trigger_uguali_a_un_archivio_nuovo(self):
        """Indici e trigger sono protezioni vere (unicita', immutabilita' del giornale):
        su un archivio vecchio devono esserci esattamente come su uno nuovo."""
        self.apri(self.vecchio)
        self.apri(self.nuovo)
        self.assertEqual(oggetti(self.vecchio, "index"), oggetti(self.nuovo, "index"),
                         "indici diversi fra archivio migrato e archivio nuovo")
        self.assertEqual(oggetti(self.vecchio, "trigger"), oggetti(self.nuovo, "trigger"),
                         "trigger diversi fra archivio migrato e archivio nuovo")
        self.assertEqual(oggetti(self.vecchio, "table"), oggetti(self.nuovo, "table"),
                         "tabelle diverse fra archivio migrato e archivio nuovo")


# ===========================================================================
# 1. CATALOGO (fase57) — 11 colonne aggiunte + `cin`: la migrazione piu' grossa
# ===========================================================================
class TestMigrazioneCatalogoFase57(BaseMigrazione, unittest.TestCase):
    DDL_V1 = (
        """CREATE TABLE IF NOT EXISTS alloggi (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                host_id TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                titolo TEXT NOT NULL,
                descrizione TEXT NOT NULL DEFAULT '',
                citta TEXT NOT NULL,
                paese TEXT NOT NULL DEFAULT '',
                prezzo_notte_cents INTEGER NOT NULL,
                capacita INTEGER NOT NULL,
                camere INTEGER NOT NULL DEFAULT 1,
                bagni INTEGER NOT NULL DEFAULT 1,
                servizi_mask INTEGER NOT NULL DEFAULT 0,
                valuta TEXT NOT NULL DEFAULT 'EUR',
                stato TEXT NOT NULL DEFAULT 'pubblicato',
                lat_micro INTEGER,
                lon_micro INTEGER,
                creato_ts TEXT NOT NULL,
                aggiornato_ts TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS alloggio_immagini (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alloggio_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                ordine INTEGER NOT NULL DEFAULT 0,
                alt TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (alloggio_id) REFERENCES alloggi(id) ON DELETE CASCADE)""",
        "CREATE INDEX IF NOT EXISTS idx_alloggi_stato_citta ON alloggi(stato, citta)",
        "CREATE INDEX IF NOT EXISTS idx_alloggi_stato_prezzo "
        "ON alloggi(stato, prezzo_notte_cents)",
        "CREATE INDEX IF NOT EXISTS idx_img_alloggio ON alloggio_immagini(alloggio_id, ordine)",
    )
    _INS = ("INSERT INTO alloggi (id, host_id, slug, titolo, descrizione, citta, paese, "
            "prezzo_notte_cents, capacita, camere, bagni, servizi_mask, valuta, stato, "
            "lat_micro, lon_micro, creato_ts, aggiornato_ts) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
    RIGHE_V1 = (
        (_INS, (1, "h_a1b2c3d4", "trastevere-attico-vista", "Attico a Trastevere",
                "Terrazza vista cupole, due camere.", "roma", "IT",
                18500, 4, 2, 1, 5, "EUR", "pubblicato", 41902782, 12496366,
                "2026-03-04T10:12:00", "2026-06-30T18:40:00")),
        (_INS, (2, "h_a1b2c3d4", "shinjuku-monolocale", "Monolocale a Shinjuku",
                "A due passi dalla stazione.", "tokyo", "JP",
                21000, 2, 1, 1, 1, "JPY", "pubblicato", 35689487, 139691711,
                "2026-04-19T09:00:00", "2026-07-01T08:05:00")),
        (_INS, (3, "h_zzz99999", "porto-cervo-villa", "Villa a Porto Cervo",
                "Piscina privata.", "porto cervo", "IT",
                92000, 8, 4, 3, 7, "EUR", "sospeso", 41131000, 9536000,
                "2026-05-02T11:00:00", "2026-05-02T11:00:00")),
        ("INSERT INTO alloggio_immagini (id, alloggio_id, url, ordine, alt) VALUES (?,?,?,?,?)",
         (1, 1, "/uploads/attico_terrazza.jpg", 0, "terrazza")),
        ("INSERT INTO alloggio_immagini (id, alloggio_id, url, ordine, alt) VALUES (?,?,?,?,?)",
         (2, 1, "/uploads/attico_salotto.jpg", 1, "salotto")),
    )
    _COL_V1 = ("id", "host_id", "slug", "titolo", "descrizione", "citta", "paese",
               "prezzo_notte_cents", "capacita", "camere", "bagni", "servizi_mask",
               "valuta", "stato", "lat_micro", "lon_micro", "creato_ts", "aggiornato_ts")
    TABELLE = (("alloggi", _COL_V1, "id"),
               ("alloggio_immagini", ("id", "alloggio_id", "url", "ordine", "alt"), "id"))
    COLONNE_AGGIUNTE = {"alloggi": ("indirizzo", "pin_manuale", "cin", "fuso",
                                    "politica_cancellazione", "tassa_pp_notte_cents",
                                    "tassa_max_notti", "tassa_perc_bps",
                                    "sconto_settimana_bps", "sconto_mese_bps",
                                    "modalita_prenotazione", "paga_in_struttura")}

    def apri(self, percorso):
        from fase57_vetrina import crea_catalogo
        return crea_catalogo(percorso)

    def leggi_col_prodotto(self, archivio):
        d = archivio.dettaglio("trastevere-attico-vista")
        jp = archivio.dettaglio("shinjuku-monolocale")
        return {
            "titolo": d["titolo"],
            "citta": d["citta"],
            "prezzo_notte_cents": d["prezzo_notte_cents"],
            "valuta": d["valuta"],
            "capacita": d["capacita"],
            "immagini": [i["url"] for i in d["immagini"]],
            # i default della migrazione devono essere quelli dichiarati, non None
            "politica": d["politica_cancellazione"],
            "modalita": d["modalita_prenotazione"],
            "tassa_pp": d["tassa_pp_notte_cents"],
            "yen": (jp["valuta"], jp["prezzo_notte_cents"]),
            # il sospeso NON deve comparire in dettaglio pubblico
            "sospeso": archivio.dettaglio("porto-cervo-villa"),
            "annunci_host": archivio.conta_alloggi_host("h_a1b2c3d4"),
            "uploads": sorted(archivio.nomi_uploads()),
        }

    def atteso_dal_prodotto(self):
        return {
            "titolo": "Attico a Trastevere",
            "citta": "roma",
            "prezzo_notte_cents": 18500,
            "valuta": "EUR",
            "capacita": 4,
            "immagini": ["/uploads/attico_terrazza.jpg", "/uploads/attico_salotto.jpg"],
            "politica": "flessibile",
            "modalita": "immediata",
            "tassa_pp": 0,
            "yen": ("JPY", 21000),
            "sospeso": None,
            "annunci_host": 2,
            "uploads": ["attico_salotto.jpg", "attico_terrazza.jpg"],
        }

    def test_la_ricerca_pubblica_trova_l_annuncio_vecchio(self):
        """Non basta che la riga sia leggibile: dev'essere ancora VENDIBILE."""
        from fase57_vetrina import CriteriRicerca
        catalogo = self.apri(self.vecchio)
        esito = catalogo.cerca(CriteriRicerca(citta="roma"))
        slug = [a["slug"] for a in esito["risultati"]]
        self.assertEqual(slug, ["trastevere-attico-vista"])
        self.assertEqual(esito["risultati"][0]["prezzo_notte_cents"], 18500)


# ===========================================================================
# 2. INVENTARIO (fase58) — nessuna colonna aggiunta: qui la guardia sorveglia
#    che resti cosi' (o che chi cambia lo schema scriva la migrazione)
# ===========================================================================
class TestMigrazioneInventarioFase58(BaseMigrazione, unittest.TestCase):
    DDL_V1 = (
        """CREATE TABLE IF NOT EXISTS inventario (
                alloggio_id TEXT NOT NULL,
                giorno TEXT NOT NULL,
                unita_totali INTEGER NOT NULL DEFAULT 0,
                unita_occupate INTEGER NOT NULL DEFAULT 0,
                prezzo_netto_cents INTEGER NOT NULL DEFAULT 0,
                chiuso INTEGER NOT NULL DEFAULT 0,
                min_notti INTEGER NOT NULL DEFAULT 1,
                aggiornato_ts TEXT NOT NULL,
                PRIMARY KEY (alloggio_id, giorno))""",
        """CREATE TABLE IF NOT EXISTS movimenti (
                idem_key TEXT PRIMARY KEY,
                alloggio_id TEXT NOT NULL,
                tipo TEXT NOT NULL,
                esito TEXT NOT NULL,
                check_in TEXT,
                check_out TEXT,
                origine TEXT DEFAULT '',
                ts TEXT NOT NULL)""",
    )
    _INV = ("INSERT INTO inventario (alloggio_id, giorno, unita_totali, unita_occupate, "
            "prezzo_netto_cents, chiuso, min_notti, aggiornato_ts) VALUES (?,?,?,?,?,?,?,?)")
    RIGHE_V1 = (
        (_INV, ("trastevere-attico-vista", "2026-08-10", 1, 0, 18500, 0, 2,
                "2026-07-01T10:00:00")),
        (_INV, ("trastevere-attico-vista", "2026-08-11", 1, 0, 18500, 0, 2,
                "2026-07-01T10:00:00")),
        (_INV, ("trastevere-attico-vista", "2026-08-12", 1, 1, 21000, 0, 1,
                "2026-07-02T09:30:00")),
        (_INV, ("trastevere-attico-vista", "2026-08-13", 1, 0, 21000, 1, 1,
                "2026-07-02T09:31:00")),
        ("INSERT INTO movimenti (idem_key, alloggio_id, tipo, esito, check_in, check_out, "
         "origine, ts) VALUES (?,?,?,?,?,?,?,?)",
         ("idem_2f7c9a11", "trastevere-attico-vista", "blocco", "ok",
          "2026-08-12", "2026-08-13", "sito", "2026-07-02T09:30:00")),
    )
    TABELLE = (("inventario", ("alloggio_id", "giorno", "unita_totali", "unita_occupate",
                               "prezzo_netto_cents", "chiuso", "min_notti", "aggiornato_ts"),
                "alloggio_id, giorno"),
               ("movimenti", ("idem_key", "alloggio_id", "tipo", "esito", "check_in",
                              "check_out", "origine", "ts"), "idem_key"))

    def apri(self, percorso):
        from fase58_channel_manager import crea_channel_manager
        return crea_channel_manager(percorso)

    def leggi_col_prodotto(self, archivio):
        libero = archivio.stato_giorno("trastevere-attico-vista", "2026-08-10")
        venduto = archivio.stato_giorno("trastevere-attico-vista", "2026-08-12")
        return {
            "prezzo_libero": libero["prezzo_netto_cents"],
            "min_notti": libero["min_notti"],
            "occupate_venduto": venduto["unita_occupate"],
            # due notti a partire dal 10 = disponibile (min_notti 2 rispettato)
            "due_notti": archivio.disponibile("trastevere-attico-vista",
                                              "2026-08-10", "2026-08-12"),
            # una notte sola sul minimo 2 = NON disponibile
            "una_notte": archivio.disponibile("trastevere-attico-vista",
                                              "2026-08-10", "2026-08-11"),
            # la notte gia' venduta non e' disponibile
            "venduta": archivio.disponibile("trastevere-attico-vista",
                                            "2026-08-12", "2026-08-13"),
            # la notte chiusa dall'host non e' disponibile
            "chiusa": archivio.disponibile("trastevere-attico-vista",
                                           "2026-08-13", "2026-08-14"),
            # calendario(da, a): estremo destro ESCLUSO -> 10, 11, 12
            "giorni_a_calendario": len(archivio.calendario("trastevere-attico-vista",
                                                           "2026-08-10", "2026-08-13")),
        }

    def atteso_dal_prodotto(self):
        return {"prezzo_libero": 18500, "min_notti": 2, "occupate_venduto": 1,
                "due_notti": True, "una_notte": False, "venduta": False, "chiusa": False,
                "giorni_a_calendario": 3}


# ===========================================================================
# 3. REGISTRO HOST (fase88) — 5 colonne canali + 13 fiscali/KYC/carta
# ===========================================================================
def _pw_hash_host(password, salt):
    from fase88_registro_host import PBKDF2_ITER
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITER).hex()


class TestMigrazioneRegistroHostFase88(BaseMigrazione, unittest.TestCase):
    SALT = bytes.fromhex("0f1e2d3c4b5a69788796a5b4c3d2e1f0")
    PASSWORD = "Trastevere!2026"
    DDL_V1 = (
        """CREATE TABLE IF NOT EXISTS host (
                host_id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                salt TEXT NOT NULL,
                pw_hash TEXT NOT NULL,
                ragione_sociale TEXT NOT NULL DEFAULT '',
                termini_versione TEXT NOT NULL,
                termini_ts INTEGER NOT NULL,
                stato TEXT NOT NULL DEFAULT 'attivo',
                creato_ts INTEGER NOT NULL)""",
    )
    TABELLE = (("host", ("host_id", "email", "salt", "pw_hash", "ragione_sociale",
                         "termini_versione", "termini_ts", "stato", "creato_ts"), "host_id"),)
    COLONNE_AGGIUNTE = {"host": ("telefono", "telegram_chat_id", "stripe_account_id",
                                 "codice_fiscale", "partita_iva", "iban", "verifica_stato",
                                 "stripe_customer_id", "stripe_payment_method")}

    def setUp(self):
        self.RIGHE_V1 = (
            ("INSERT INTO host (host_id, email, salt, pw_hash, ragione_sociale, "
             "termini_versione, termini_ts, stato, creato_ts) VALUES (?,?,?,?,?,?,?,?,?)",
             ("h_a1b2c3d4", "chiara.rossi@example.com", self.SALT.hex(),
              _pw_hash_host(self.PASSWORD, self.SALT), "Rossi Ospitalita' Srl",
              "2026-01", 1767225600, "attivo", 1767225600)),
            ("INSERT INTO host (host_id, email, salt, pw_hash, ragione_sociale, "
             "termini_versione, termini_ts, stato, creato_ts) VALUES (?,?,?,?,?,?,?,?,?)",
             ("h_zzz99999", "kenji.sato@example.jp", self.SALT.hex(),
              _pw_hash_host("Shinjuku!2026", self.SALT), "",
              "2026-01", 1769904000, "sospeso", 1769904000)),
        )
        BaseMigrazione.setUp(self)

    def apri(self, percorso):
        from fase88_registro_host import crea_registro_host
        return crea_registro_host(percorso, SEGRETO)

    def leggi_col_prodotto(self, archivio):
        buono = archivio.login("chiara.rossi@example.com", self.PASSWORD)
        sbagliato = archivio.login("chiara.rossi@example.com", "password-sbagliata")
        info = archivio.info_host("h_a1b2c3d4")
        return {
            "login_ok": buono.ok,
            "login_host_id": buono.host_id,
            "login_sbagliato": sbagliato.ok,
            "email": info["email"],
            "ragione_sociale": info["ragione_sociale"],
            # campi nati DOPO: devono esserci e valere '' (default della migrazione)
            "telefono": info["telefono"],
            "stripe_account_id": info["stripe_account_id"],
            "codice_fiscale": info["codice_fiscale"],
            "verifica_stato": info["verifica_stato"],
            "stripe_payment_method": info["stripe_payment_method"],
            "quanti": archivio.conta_host(),
            "token_valido": archivio.verifica_token(buono.token),
        }

    def atteso_dal_prodotto(self):
        return {"login_ok": True, "login_host_id": "h_a1b2c3d4", "login_sbagliato": False,
                "email": "chiara.rossi@example.com",
                "ragione_sociale": "Rossi Ospitalita' Srl",
                "telefono": "", "stripe_account_id": "", "codice_fiscale": "",
                "verifica_stato": "", "stripe_payment_method": "",
                "quanti": 2, "token_valido": "h_a1b2c3d4"}

    def test_i_dati_fiscali_si_scrivono_sulle_colonne_appena_migrate(self):
        """La migrazione non deve solo far comparire le colonne: devono essere SCRIVIBILI
        (una ADD COLUMN sbagliata puo' lasciare vincoli che rifiutano l'UPDATE)."""
        registro = self.apri(self.vecchio)
        ok = registro.imposta_dati_fiscali("h_a1b2c3d4", {
            "codice_fiscale": "RSSCHR85M41H501Z", "paese": "IT",
            "iban": "IT60X0542811101000000123456", "tipo_soggetto": "persona_fisica"})
        self.assertIs(ok, True)
        info = registro.info_host("h_a1b2c3d4")
        self.assertEqual(info["codice_fiscale"], "RSSCHR85M41H501Z")
        self.assertEqual(info["iban"], "IT60X0542811101000000123456")
        self.assertEqual(info["paese"], "IT")
        # e la password storica continua a funzionare dopo la scrittura
        self.assertIs(registro.login("chiara.rossi@example.com", self.PASSWORD).ok, True)


# ===========================================================================
# 4. PENDENTI (fase162) — host_id/email/quote_token/corpo_json + i due INTEGER
# ===========================================================================
class TestMigrazionePendentiFase162(BaseMigrazione, unittest.TestCase):
    ORA = 1785000000
    DDL_V1 = (
        """CREATE TABLE IF NOT EXISTS pendenti (
                riferimento TEXT PRIMARY KEY,
                alloggio_id TEXT NOT NULL, check_in TEXT NOT NULL, check_out TEXT NOT NULL,
                idem_key TEXT NOT NULL DEFAULT '',
                tassa_cents INTEGER NOT NULL DEFAULT 0, comune TEXT NOT NULL DEFAULT '',
                scadenza_ts INTEGER NOT NULL, stato TEXT NOT NULL DEFAULT 'in_attesa',
                creato_ts INTEGER NOT NULL)""",
    )
    _INS = ("INSERT INTO pendenti (riferimento, alloggio_id, check_in, check_out, idem_key, "
            "tassa_cents, comune, scadenza_ts, stato, creato_ts) VALUES (?,?,?,?,?,?,?,?,?,?)")
    RIGHE_V1 = (
        (_INS, ("BV-2026-000117", "trastevere-attico-vista", "2026-08-10", "2026-08-12",
                "idem_2f7c9a11", 900, "roma", ORA + 1200, "in_attesa", ORA - 600)),
        (_INS, ("BV-2026-000118", "trastevere-attico-vista", "2026-09-01", "2026-09-04",
                "idem_88bb1177", 1350, "roma", ORA - 60, "in_attesa", ORA - 3600)),
        (_INS, ("BV-2026-000119", "shinjuku-monolocale", "2026-10-05", "2026-10-07",
                "idem_5511aacc", 0, "", ORA + 7200, "pagato", ORA - 7200)),
    )
    TABELLE = (("pendenti", ("riferimento", "alloggio_id", "check_in", "check_out",
                             "idem_key", "tassa_cents", "comune", "scadenza_ts", "stato",
                             "creato_ts"), "riferimento"),)
    COLONNE_AGGIUNTE = {"pendenti": ("host_id", "email", "quote_token", "corpo_json",
                                     "promemoria_ts", "invito_recensione_ts")}

    def apri(self, percorso):
        from fase162_pagamenti_pendenti import crea_pagamenti_pendenti
        archivio = crea_pagamenti_pendenti(percorso, orologio=lambda: self.ORA)
        archivio.inizializza_schema()
        return archivio

    def leggi_col_prodotto(self, archivio):
        vivi = archivio.attivi_per_alloggio("trastevere-attico-vista")
        scaduti = archivio.scaduti()
        return {
            "vivi": sorted(r["riferimento"] for r in vivi),
            "tassa_del_vivo": vivi[0]["tassa_cents"],
            "comune_del_vivo": vivi[0]["comune"],
            # i campi nati dopo devono leggersi come stringa vuota, non esplodere
            "host_id_del_vivo": vivi[0]["host_id"],
            "corpo_json_del_vivo": vivi[0]["corpo_json"],
            "scaduti": sorted(r["riferimento"] for r in scaduti),
            "idem": sorted(archivio.idem_keys()),
        }

    def atteso_dal_prodotto(self):
        return {"vivi": ["BV-2026-000117"], "tassa_del_vivo": 900, "comune_del_vivo": "roma",
                "host_id_del_vivo": "", "corpo_json_del_vivo": "",
                "scaduti": ["BV-2026-000118"],
                "idem": ["idem_2f7c9a11", "idem_5511aacc", "idem_88bb1177"]}


# ===========================================================================
# 5. PAYOUT (fase131) — i soldi che devono arrivare all'host
# ===========================================================================
class TestMigrazionePayoutFase131(BaseMigrazione, unittest.TestCase):
    DDL_V1 = (
        """CREATE TABLE IF NOT EXISTS payout (
                prenotazione_id TEXT PRIMARY KEY, host_id TEXT NOT NULL,
                minori INTEGER NOT NULL, valuta TEXT NOT NULL,
                stato TEXT NOT NULL, ts INTEGER NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS ix_payout_host ON payout(host_id)",
    )
    _INS = ("INSERT INTO payout (prenotazione_id, host_id, minori, valuta, stato, ts) "
            "VALUES (?,?,?,?,?,?)")
    RIGHE_V1 = (
        (_INS, ("BV-2026-000117", "h_a1b2c3d4", 34040, "EUR", "maturato", 1784000000)),
        (_INS, ("BV-2026-000118", "h_a1b2c3d4", 51060, "EUR", "pagato", 1783000000)),
        (_INS, ("BV-2026-000119", "h_zzz99999", 38640, "JPY", "maturato", 1782000000)),
    )
    TABELLE = (("payout", ("prenotazione_id", "host_id", "minori", "valuta", "stato", "ts"),
                "prenotazione_id"),)

    def apri(self, percorso):
        from fase131_payout_dashboard import crea_payout_dashboard
        archivio = crea_payout_dashboard(percorso)
        archivio.inizializza_schema()
        return archivio

    def leggi_col_prodotto(self, archivio):
        info = archivio.info("BV-2026-000117")
        return {"minori": info["minori"], "valuta": info["valuta"], "stato": info["stato"],
                "host": info["host_id"],
                "da_pagare_eur": archivio.da_pagare("h_a1b2c3d4", "EUR"),
                # conta_pagati = prenotazioni che hanno PRODOTTO (maturato+in_transito+pagato)
                "pagati": archivio.conta_pagati("h_a1b2c3d4"),
                "stato_altrui": archivio.stato_di("BV-2026-000119")}

    def atteso_dal_prodotto(self):
        # solo il 'maturato' e' ancora da pagare: il 'pagato' e' gia' uscito
        return {"minori": 34040, "valuta": "EUR", "stato": "maturato", "host": "h_a1b2c3d4",
                "da_pagare_eur": 34040, "pagati": 2, "stato_altrui": "maturato"}


# ===========================================================================
# 6. TASSA DI SOGGIORNO (fase147) — `stornato` aggiunta dopo, e le query la USANO
# ===========================================================================
class TestMigrazioneTassaFase147(BaseMigrazione, unittest.TestCase):
    DDL_V1 = (
        """CREATE TABLE IF NOT EXISTS tassa_regola (
                comune TEXT PRIMARY KEY, regola_json TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS tassa_riscossione (
                prenotazione_id TEXT PRIMARY KEY, comune TEXT NOT NULL,
                importo INTEGER NOT NULL, ts INTEGER NOT NULL)""",
    )
    _INS = ("INSERT INTO tassa_riscossione (prenotazione_id, comune, importo, ts) "
            "VALUES (?,?,?,?)")
    RIGHE_V1 = (
        ("INSERT INTO tassa_regola (comune, regola_json) VALUES (?,?)",
         ("roma", '{"per_persona_notte_cents": 450, "max_notti": 10}')),
        (_INS, ("BV-2026-000117", "roma", 900, 1784000000)),
        (_INS, ("BV-2026-000118", "roma", 1350, 1783000000)),
        (_INS, ("BV-2026-000120", "firenze", 600, 1782000000)),
    )
    TABELLE = (("tassa_riscossione", ("prenotazione_id", "comune", "importo", "ts"),
                "prenotazione_id"),
               ("tassa_regola", ("comune", "regola_json"), "comune"))
    COLONNE_AGGIUNTE = {"tassa_riscossione": ("stornato",)}

    def apri(self, percorso):
        from fase147_tassa_comunale import crea_tassa_comunale
        archivio = crea_tassa_comunale(percorso)
        archivio.inizializza_schema()
        return archivio

    def leggi_col_prodotto(self, archivio):
        return {"roma": archivio.totale_riscosso("roma"),
                "firenze": archivio.totale_riscosso("firenze"),
                "regola_roma": archivio.regola("roma")}

    def atteso_dal_prodotto(self):
        # se `stornato` non venisse aggiunta, totale_riscosso (WHERE stornato=0) esploderebbe
        return {"roma": 2250, "firenze": 600,
                "regola_roma": {"per_persona_notte_cents": 450, "max_notti": 10}}

    def test_lo_storno_funziona_sulle_righe_nate_prima_della_colonna(self):
        """Il tombstone del rimborso dev'essere applicabile ANCHE alla riscossione
        vecchia: senza, si verserebbe al Comune una tassa gia' restituita all'ospite."""
        archivio = self.apri(self.vecchio)
        self.assertIs(archivio.storna("BV-2026-000117"), True)
        self.assertEqual(archivio.totale_riscosso("roma"), 1350)
        # idempotente: stornare due volte non deve togliere due volte
        archivio.storna("BV-2026-000117")
        self.assertEqual(archivio.totale_riscosso("roma"), 1350)


# ===========================================================================
# 7. GARANZIA / ESCROW (fase160) — i soldi trattenuti
# ===========================================================================
class TestMigrazioneGaranziaFase160(BaseMigrazione, unittest.TestCase):
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
    _INS = ("INSERT INTO garanzia (prenotazione_id, alloggio_id, importo_host_cents, "
            "host_riceve_cents, ospite_rimborso_cents, stato, motivo, sblocco_auto_ts, "
            "aperto_ts, aggiornato_ts) VALUES (?,?,?,?,?,?,?,?,?,?)")
    RIGHE_V1 = (
        (_INS, ("BV-2026-000117", "trastevere-attico-vista", 34040, 0, 0,
                "in_garanzia", "", 1785086400, 1785000000, 1785000000)),
        (_INS, ("BV-2026-000118", "trastevere-attico-vista", 51060, 0, 0,
                "contestato", "riscaldamento guasto", 1784086400, 1784000000, 1784003600)),
    )
    TABELLE = (("garanzia", ("prenotazione_id", "alloggio_id", "importo_host_cents",
                             "host_riceve_cents", "ospite_rimborso_cents", "stato",
                             "motivo", "sblocco_auto_ts", "aperto_ts", "aggiornato_ts"),
                "prenotazione_id"),)

    def apri(self, percorso):
        from fase160_escrow_garanzia import crea_escrow_garanzia
        archivio = crea_escrow_garanzia(percorso)
        archivio.inizializza_schema()
        return archivio

    def leggi_col_prodotto(self, archivio):
        s = archivio.stato("BV-2026-000117")
        return {"stato": s["stato"], "importo": s["importo_host_cents"],
                "unita": s["money_unit"],
                "aperte": sorted(r["prenotazione_id"] for r in archivio.aperte()),
                "contestate": sorted(r["prenotazione_id"] for r in archivio.contestate()),
                "motivo_contestata": archivio.stato("BV-2026-000118")["motivo"]}

    def atteso_dal_prodotto(self):
        return {"stato": "in_garanzia", "importo": 34040, "unita": "cents_integer",
                "aperte": ["BV-2026-000117"], "contestate": ["BV-2026-000118"],
                "motivo_contestata": "riscaldamento guasto"}


# ===========================================================================
# 8. LIBRO GIORNALE (fase177) — la catena di hash e i trigger di immutabilita'
# ===========================================================================
def _riga_giornale(prev, evento_id, ts, tipo, riferimento, soggetto, dare, avere,
                   importo, valuta, causale, emittente):
    from fase177_financial_controller import FinancialController
    canonico = FinancialController._canonico(evento_id, ts, tipo, riferimento, soggetto,
                                             dare, avere, importo, valuta, causale,
                                             emittente, prev)
    h = hashlib.sha256(canonico.encode("utf-8")).hexdigest()
    return h, (evento_id, ts, tipo, riferimento, soggetto, dare, avere, importo,
               valuta, causale, emittente, prev, h)


class TestMigrazioneGiornaleFase177(BaseMigrazione, unittest.TestCase):
    DDL_V1 = (
        """CREATE TABLE IF NOT EXISTS libro_giornale (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                evento_id TEXT NOT NULL UNIQUE,
                ts INTEGER NOT NULL,
                tipo TEXT NOT NULL,
                riferimento TEXT NOT NULL,
                soggetto TEXT NOT NULL,
                conto_dare TEXT NOT NULL,
                conto_avere TEXT NOT NULL,
                importo_cents INTEGER NOT NULL CHECK (importo_cents > 0),
                valuta TEXT NOT NULL,
                causale TEXT NOT NULL,
                emittente TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                hash TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS ix_lg_rif ON libro_giornale(riferimento)",
        "CREATE INDEX IF NOT EXISTS ix_lg_soggetto ON libro_giornale(soggetto)",
        """CREATE TABLE IF NOT EXISTS note (
                nota_id TEXT PRIMARY KEY,
                tipo TEXT NOT NULL CHECK (tipo IN ('credito','debito')),
                riferimento TEXT NOT NULL,
                causale TEXT NOT NULL,
                ts INTEGER NOT NULL,
                emittente TEXT NOT NULL,
                soggetto TEXT NOT NULL,
                importo_cents INTEGER NOT NULL CHECK (importo_cents > 0),
                valuta TEXT NOT NULL,
                stato TEXT NOT NULL DEFAULT 'emessa',
                storno_di TEXT,
                giornale_seq INTEGER NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS ix_note_rif ON note(riferimento)",
        """CREATE TABLE IF NOT EXISTS debiti (
                debito_id TEXT PRIMARY KEY,
                host_id TEXT NOT NULL,
                riferimento TEXT NOT NULL,
                residuo_cents INTEGER NOT NULL CHECK (residuo_cents >= 0),
                valuta TEXT NOT NULL,
                stato TEXT NOT NULL,
                tentativi INTEGER NOT NULL DEFAULT 0,
                prossimo_ts INTEGER,
                aggiornato_ts INTEGER NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS ix_debiti_host ON debiti(host_id, stato)",
    )
    _SQL = ("INSERT INTO libro_giornale (evento_id, ts, tipo, riferimento, soggetto, "
            "conto_dare, conto_avere, importo_cents, valuta, causale, emittente, "
            "prev_hash, hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)")
    _COL = ("seq", "evento_id", "ts", "tipo", "riferimento", "soggetto", "conto_dare",
            "conto_avere", "importo_cents", "valuta", "causale", "emittente",
            "prev_hash", "hash")
    TABELLE = (("libro_giornale", _COL, "seq"),
               ("debiti", ("debito_id", "host_id", "riferimento", "residuo_cents",
                           "valuta", "stato", "tentativi", "prossimo_ts",
                           "aggiornato_ts"), "debito_id"))

    def setUp(self):
        h1, r1 = _riga_giornale("GENESI", "inc:BV-2026-000117", 1784000000, "incasso",
                                "BV-2026-000117", "ospite", "cassa", "debiti_v_host",
                                37000, "EUR", "incasso soggiorno", "sistema")
        h2, r2 = _riga_giornale(h1, "comm:BV-2026-000117", 1784000001,
                                "commissione_netta", "BV-2026-000117", "h_a1b2c3d4",
                                "debiti_v_host", "ricavi_commissione", 2960, "EUR",
                                "commissione 8%", "sistema")
        h3, r3 = _riga_giornale(h2, "pay:BV-2026-000117", 1784000002, "payout_host",
                                "BV-2026-000117", "h_a1b2c3d4", "debiti_v_host", "cassa",
                                34040, "EUR", "bonifico host", "sistema")
        self.TESTA = h3
        self.RIGHE_V1 = (
            (self._SQL, r1), (self._SQL, r2), (self._SQL, r3),
            ("INSERT INTO debiti (debito_id, host_id, riferimento, residuo_cents, valuta, "
             "stato, tentativi, prossimo_ts, aggiornato_ts) VALUES (?,?,?,?,?,?,?,?,?)",
             ("D-000042", "h_a1b2c3d4", "BV-2026-000118", 12000, "EUR", "aperto",
              1, 1785000000, 1784500000)),
        )
        BaseMigrazione.setUp(self)

    def apri(self, percorso):
        from fase177_financial_controller import crea_financial_controller
        archivio = crea_financial_controller(percorso)
        archivio.inizializza_schema()
        return archivio

    def leggi_col_prodotto(self, archivio):
        catena = archivio.verifica_catena()
        return {"catena_ok": catena["ok"], "righe": catena["righe"], "testa": catena["testa"],
                "movimenti": [m["tipo"] for m in archivio.movimenti("BV-2026-000117")],
                "importi": [m["importo_cents"] for m in archivio.movimenti("BV-2026-000117")],
                "quanti": archivio.conta_movimenti(),
                "debito": archivio.debiti_host("h_a1b2c3d4")[0]["residuo_cents"]}

    def atteso_dal_prodotto(self):
        return {"catena_ok": True, "righe": 3, "testa": self.TESTA,
                "movimenti": ["incasso", "commissione_netta", "payout_host"],
                "importi": [37000, 2960, 34040], "quanti": 3, "debito": 12000}

    def test_un_giornale_senza_trigger_li_riceve_alla_riapertura(self):
        """L'immutabilita' del libro giornale NON e' solo codice: sono due trigger nel
        file. Un archivio arrivato senza (ripristino parziale, tabella ricreata a mano)
        sarebbe modificabile in silenzio. Alla riapertura i trigger devono tornare."""
        senza = os.path.join(self.dir, "senza_trigger.db")
        scrivi_db_vecchio(senza, self.DDL_V1, self.RIGHE_V1)
        self.assertEqual(oggetti(senza, "trigger"), [],
                         "il caso di prova deve partire DAVVERO senza trigger")
        con = sqlite3.connect(senza)
        try:                                   # prima: la manomissione passa
            with con:
                con.execute("UPDATE libro_giornale SET importo_cents=1 WHERE seq=1")
                con.execute("UPDATE libro_giornale SET importo_cents=37000 WHERE seq=1")
        finally:
            con.close()
        self.apri(senza)
        self.assertEqual(oggetti(senza, "trigger"), ["lg_no_delete", "lg_no_update"])
        con = sqlite3.connect(senza)
        try:                                   # dopo: abortisce
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("UPDATE libro_giornale SET importo_cents=1 WHERE seq=1")
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("DELETE FROM libro_giornale WHERE seq=1")
        finally:
            con.close()
        self.assertEqual(righe(senza, "libro_giornale", ("importo_cents",), "seq"),
                         [(37000,), (2960,), (34040,)])

    def test_una_riga_nuova_si_aggancia_alla_catena_vecchia(self):
        """Il giornale e' una catena: la prima riga scritta dopo la migrazione deve
        agganciarsi all'ULTIMO hash storico, non ripartire da GENESI."""
        archivio = self.apri(self.vecchio)
        esito = archivio.registra(evento_id="inc:BV-2026-000200", tipo="incasso",
                                  riferimento="BV-2026-000200", soggetto="ospite",
                                  conto_dare="cassa", conto_avere="debiti_v_host",
                                  importo_cents=52000, valuta="EUR",
                                  causale="incasso soggiorno", emittente="sistema")
        self.assertIsNotNone(esito)
        self.assertEqual(esito["seq"], 4)
        prev = righe(self.vecchio, "libro_giornale", ("prev_hash",), "seq")[3][0]
        self.assertEqual(prev, self.TESTA)
        self.assertIs(archivio.verifica_catena()["ok"], True)


# ===========================================================================
# 9. ACCETTAZIONI FIRMATE (fase163) — `riferimento` aggiunta dopo, senza
#    invalidare le firme gia' in archivio (valore legale)
# ===========================================================================
class TestMigrazioneAccettazioniFase163(BaseMigrazione, unittest.TestCase):
    DDL_V1 = (
        """CREATE TABLE IF NOT EXISTS accettazioni (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                host_id TEXT NOT NULL,
                documento TEXT NOT NULL,
                versione TEXT NOT NULL,
                doc_sha256 TEXT NOT NULL,
                lang TEXT NOT NULL DEFAULT 'it',
                ip TEXT NOT NULL DEFAULT '',
                user_agent TEXT NOT NULL DEFAULT '',
                vessatorie INTEGER NOT NULL DEFAULT 0,
                accettato_ts INTEGER NOT NULL,
                firma TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS idx_acc_host ON accettazioni(host_id)",
    )
    TABELLE = (("accettazioni", ("id", "host_id", "documento", "versione", "doc_sha256",
                                 "lang", "ip", "user_agent", "vessatorie", "accettato_ts",
                                 "firma"), "id"),)
    COLONNE_AGGIUNTE = {"accettazioni": ("riferimento",)}
    DOC_HASH = "9f" * 32
    TS = 1767225600

    def _firma_v1(self, host_id, documento, versione, lang, ip, ua, vex, ts):
        """La firma COM'ERA prima che esistesse `riferimento` (nessun campo in coda)."""
        canonico = "|".join([host_id, documento, versione, self.DOC_HASH, lang, ip, ua,
                             str(int(vex)), str(int(ts))])
        return hmac.new(SEGRETO, canonico.encode("utf-8"), hashlib.sha256).hexdigest()

    def setUp(self):
        from fase163_accettazioni import DOCUMENTO_HOST
        self.DOCUMENTO = DOCUMENTO_HOST
        firma = self._firma_v1("h_a1b2c3d4", DOCUMENTO_HOST, "2026-01", "it",
                               "203.0.113.9", "Mozilla/5.0 (iPhone)", 1, self.TS)
        self.FIRMA = firma
        self.RIGHE_V1 = (
            ("INSERT INTO accettazioni (id, host_id, documento, versione, doc_sha256, lang, "
             "ip, user_agent, vessatorie, accettato_ts, firma) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
             (1, "h_a1b2c3d4", DOCUMENTO_HOST, "2026-01", self.DOC_HASH, "it",
              "203.0.113.9", "Mozilla/5.0 (iPhone)", 1, self.TS, firma)),
        )
        BaseMigrazione.setUp(self)

    def apri(self, percorso):
        from fase163_accettazioni import crea_registro_accettazioni
        return crea_registro_accettazioni(percorso, SEGRETO)

    def leggi_col_prodotto(self, archivio):
        voci = archivio.elenco("h_a1b2c3d4")
        return {"quante": len(voci), "integra": voci[0]["integra"],
                "firma": voci[0]["firma"], "riferimento": voci[0]["riferimento"],
                "vessatorie": voci[0]["vessatorie"], "ip": voci[0]["ip"],
                "conta": archivio.conta(), "righe_sigillo": archivio.sigillo()["righe"]}

    def atteso_dal_prodotto(self):
        return {"quante": 1, "integra": True, "firma": self.FIRMA, "riferimento": "",
                "vessatorie": True, "ip": "203.0.113.9", "conta": 1, "righe_sigillo": 1}

    def test_la_prova_vecchia_resta_valida_e_una_manomessa_no(self):
        """La prova serve in causa: dopo la migrazione la firma storica deve ancora
        tornare, e alterare un campo dev'essere ancora smascherato."""
        archivio = self.apri(self.vecchio)
        self.assertIs(archivio.elenco("h_a1b2c3d4")[0]["integra"], True)
        con = sqlite3.connect(self.vecchio)
        try:
            with con:
                con.execute("UPDATE accettazioni SET vessatorie=0 WHERE id=1")
        finally:
            con.close()
        self.assertIs(archivio.elenco("h_a1b2c3d4")[0]["integra"], False)


# ===========================================================================
# 10. OPERATORI ADMIN (fase192) — chi puo' entrare nel bunker
# ===========================================================================
class TestMigrazioneAdminAccountsFase192(BaseMigrazione, unittest.TestCase):
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
             ("exdipendente@bookinvip.com", self.SALT.hex(), _hash("vecchia", self.SALT),
              "admin", 0, 1760000000, "root")),
        )
        BaseMigrazione.setUp(self)

    def apri(self, percorso):
        from fase192_admin_accounts import crea_admin_accounts
        return crea_admin_accounts(percorso)

    def leggi_col_prodotto(self, archivio):
        buono = archivio.verifica("supporto@bookinvip.com", self.PASSWORD)
        revocato = archivio.verifica("exdipendente@bookinvip.com", "vecchia")
        return {"ok": buono["ok"], "ruolo": buono["ruolo"],
                "revocato_ok": revocato["ok"], "revocato_errore": revocato["errore"],
                "ruolo_attivo": archivio.ruolo_attivo("supporto@bookinvip.com"),
                "ruolo_revocato": archivio.ruolo_attivo("exdipendente@bookinvip.com"),
                "quanti": len(archivio.lista())}

    def atteso_dal_prodotto(self):
        return {"ok": True, "ruolo": "supporto", "revocato_ok": False,
                "revocato_errore": "account_revocato", "ruolo_attivo": "supporto",
                "ruolo_revocato": None, "quanti": 2}


# ===========================================================================
# 11. PARTNER (fase201) — PII con consenso GDPR
# ===========================================================================
class TestMigrazionePartnerFase201(BaseMigrazione, unittest.TestCase):
    DDL_V1 = (
        """CREATE TABLE IF NOT EXISTS partner (
                email TEXT PRIMARY KEY, nome TEXT NOT NULL, tipo TEXT NOT NULL,
                citta TEXT DEFAULT '', messaggio TEXT DEFAULT '',
                consenso INTEGER NOT NULL, ts INTEGER NOT NULL)""",
    )
    _INS = ("INSERT INTO partner (email, nome, tipo, citta, messaggio, consenso, ts) "
            "VALUES (?,?,?,?,?,?,?)")
    RIGHE_V1 = (
        (_INS, ("agenzia.tevere@example.com", "Agenzia Tevere", "gestore", "roma",
                "Gestiamo 14 appartamenti in centro.", 1, 1784000000)),
        (_INS, ("pulizie.aurora@example.com", "Pulizie Aurora", "servizi", "roma",
                "", 1, 1783000000)),
    )
    TABELLE = (("partner", ("email", "nome", "tipo", "citta", "messaggio", "consenso", "ts"),
                "email"),)

    def apri(self, percorso):
        from fase201_partner import crea_gestore_partner
        archivio = crea_gestore_partner(percorso)
        archivio.inizializza_schema()
        return archivio

    def leggi_col_prodotto(self, archivio):
        elenco = archivio.candidati()
        return {"quanti": archivio.conta(),
                "email": [c["email"] for c in elenco],
                "primo_nome": elenco[0]["nome"],
                "primo_messaggio": elenco[0]["messaggio"]}

    def atteso_dal_prodotto(self):
        return {"quanti": 2,
                "email": ["agenzia.tevere@example.com", "pulizie.aurora@example.com"],
                "primo_nome": "Agenzia Tevere",
                "primo_messaggio": "Gestiamo 14 appartamenti in centro."}


# ===========================================================================
# 12. DOMANDA / lista d'attesa (fase158) — l'unico dato vero rimasto in prod
# ===========================================================================
class TestMigrazioneDomandaFase158(BaseMigrazione, unittest.TestCase):
    DDL_V1 = (
        """CREATE TABLE IF NOT EXISTS domanda (
                email TEXT NOT NULL, citta TEXT NOT NULL,
                check_in TEXT DEFAULT '', check_out TEXT DEFAULT '',
                party INTEGER DEFAULT 1, ts INTEGER NOT NULL,
                PRIMARY KEY (email, citta))""",
    )
    _INS = ("INSERT INTO domanda (email, citta, check_in, check_out, party, ts) "
            "VALUES (?,?,?,?,?,?)")
    RIGHE_V1 = (
        (_INS, ("realmutodavide@example.com", "roma", "2026-09-01", "2026-09-04", 2,
                1784000000)),
        (_INS, ("laura.bianchi@example.com", "roma", "", "", 1, 1783000000)),
        (_INS, ("kenji.sato@example.jp", "tokyo", "2026-11-02", "2026-11-06", 3,
                1782000000)),
    )
    TABELLE = (("domanda", ("email", "citta", "check_in", "check_out", "party", "ts"),
                "email, citta"),)

    def apri(self, percorso):
        from fase158_domanda import crea_gestore_domanda
        archivio = crea_gestore_domanda(percorso)
        archivio.inizializza_schema()
        return archivio

    def leggi_col_prodotto(self, archivio):
        return {"totale": archivio.conta(), "roma": archivio.conta("roma"),
                "email_roma": sorted(archivio.email_citta("roma")),
                "classifica": archivio.per_citta()}

    def atteso_dal_prodotto(self):
        return {"totale": 3, "roma": 2,
                "email_roma": ["laura.bianchi@example.com", "realmutodavide@example.com"],
                "classifica": [{"citta": "roma", "richieste": 2},
                               {"citta": "tokyo", "richieste": 1}]}


# ===========================================================================
# 13. CHECK-IN DIGITALE (fase127) — `revocato` aggiunta dopo (apre la porta!)
# ===========================================================================
class TestMigrazioneCheckinFase127(BaseMigrazione, unittest.TestCase):
    DDL_V1 = (
        """CREATE TABLE IF NOT EXISTS checkin (
                prenotazione_id TEXT PRIMARY KEY, alloggio_id TEXT NOT NULL,
                ospiti_json TEXT NOT NULL, ts INTEGER NOT NULL,
                completato INTEGER NOT NULL DEFAULT 1)""",
    )
    _INS = ("INSERT INTO checkin (prenotazione_id, alloggio_id, ospiti_json, ts, completato) "
            "VALUES (?,?,?,?,?)")
    RIGHE_V1 = (
        (_INS, ("BV-2026-000117", "trastevere-attico-vista",
                '[{"nome": "Chiara", "documento": "CA12345AA"}]', 1784000000, 1)),
        (_INS, ("BV-2026-000118", "trastevere-attico-vista", "[]", 1783000000, 0)),
    )
    TABELLE = (("checkin", ("prenotazione_id", "alloggio_id", "ospiti_json", "ts",
                            "completato"), "prenotazione_id"),)
    COLONNE_AGGIUNTE = {"checkin": ("revocato",)}

    def apri(self, percorso):
        from fase127_checkin_digitale import crea_checkin_digitale
        archivio = crea_checkin_digitale(percorso, _PassFinto())
        archivio.inizializza_schema()
        return archivio

    def leggi_col_prodotto(self, archivio):
        return {"completo": archivio.completato("BV-2026-000117"),
                "incompleto": archivio.completato("BV-2026-000118"),
                "pass_emesso": archivio.sblocca("BV-2026-000117",
                                                "trastevere-attico-vista"),
                "pass_negato": archivio.sblocca("BV-2026-000118",
                                                "trastevere-attico-vista")}

    def atteso_dal_prodotto(self):
        return {"completo": True, "incompleto": False,
                "pass_emesso": "PASS:BV-2026-000117", "pass_negato": None}

    def test_la_revoca_funziona_su_un_checkin_nato_prima_della_colonna(self):
        """Senza `revocato` il check-in di una prenotazione cancellata resterebbe valido
        e - con serratura smart - la porta si aprirebbe lo stesso."""
        archivio = self.apri(self.vecchio)
        self.assertIs(archivio.revoca("BV-2026-000117"), True)
        self.assertIs(archivio.completato("BV-2026-000117"), False)
        self.assertIsNone(archivio.sblocca("BV-2026-000117", "trastevere-attico-vista"))


class _PassFinto(object):
    """Emettitore smart-pass finto: serve solo a provare che il gate legge il dato vecchio."""

    def emetti(self, prenotazione, alloggio, **kw):
        return "PASS:%s" % prenotazione


# ===========================================================================
# 14. MARCHE TEMPORALI (fase184) — `qualificata` + l'indice unico SOSTITUITO
# ===========================================================================
class TestMigrazioneMarcheFase184(BaseMigrazione, unittest.TestCase):
    DDL_V1 = (
        """CREATE TABLE IF NOT EXISTS marche (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                giorno TEXT NOT NULL,
                ambito TEXT NOT NULL DEFAULT 'registri',
                impronta TEXT NOT NULL,
                canonico TEXT NOT NULL DEFAULT '',
                stato TEXT NOT NULL,
                tsa TEXT NOT NULL DEFAULT '',
                policy TEXT NOT NULL DEFAULT '',
                seriale TEXT NOT NULL DEFAULT '',
                gen_time INTEGER NOT NULL DEFAULT 0,
                richiesto_ts INTEGER NOT NULL,
                token_b64 TEXT NOT NULL DEFAULT '',
                errore TEXT NOT NULL DEFAULT '')""",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_marca_giorno "
        "ON marche(giorno, ambito) WHERE stato='ok'",
        "CREATE INDEX IF NOT EXISTS idx_marca_ts ON marche(richiesto_ts)",
    )
    _INS = ("INSERT INTO marche (id, giorno, ambito, impronta, canonico, stato, tsa, policy, "
            "seriale, gen_time, richiesto_ts, token_b64, errore) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)")
    RIGHE_V1 = (
        (_INS, (1, "2026-07-01", "registri", "ab" * 32, "sigillo:registri", "ok",
                "freetsa.org", "1.2.3.4.1", "0x5f2a", 1783900000, 1783900005,
                "MIIB0DCCAT", "")),
        (_INS, (2, "2026-07-02", "registri", "cd" * 32, "sigillo:registri", "errore",
                "", "", "", 0, 1783986400, "", "tsa_irraggiungibile")),
    )
    TABELLE = (("marche", ("id", "giorno", "ambito", "impronta", "canonico", "stato", "tsa",
                           "policy", "seriale", "gen_time", "richiesto_ts", "token_b64",
                           "errore"), "id"),)
    COLONNE_AGGIUNTE = {"marche": ("qualificata",)}

    def apri(self, percorso):
        from fase184_marca_temporale import ArchivioMarche
        return ArchivioMarche(percorso)

    def leggi_col_prodotto(self, archivio):
        voci = archivio.elenco()
        per_id = dict((v["id"], v) for v in voci)
        return {"quante": archivio.conta(),
                "marcato_01": archivio.gia_marcato("2026-07-01"),
                "marcato_02": archivio.gia_marcato("2026-07-02"),
                # nato prima della colonna: NON qualificata, ed e' la verita'
                "qualificata_01": per_id[1]["qualificata"],
                "solo_qualificata_01": archivio.gia_marcato("2026-07-01",
                                                            solo_qualificata=True),
                "tsa_01": per_id[1]["tsa"], "errore_02": per_id[2]["errore"]}

    def atteso_dal_prodotto(self):
        return {"quante": 2, "marcato_01": True, "marcato_02": False,
                "qualificata_01": 0, "solo_qualificata_01": False,
                "tsa_01": "freetsa.org", "errore_02": "tsa_irraggiungibile"}

    def test_l_indice_unico_vecchio_e_sostituito_da_quello_nuovo(self):
        """L'archivio e' append-only: la marca QUALIFICATA deve poter affiancare il
        ripiego preso prima. Col vecchio indice unico (giorno, ambito) sarebbe stata
        rifiutata come duplicato e la prova migliore andrebbe persa."""
        self.assertIn("idx_marca_giorno", oggetti(self.vecchio, "index"))
        archivio = self.apri(self.vecchio)
        self.assertNotIn("idx_marca_giorno", oggetti(self.vecchio, "index"))
        self.assertIn("idx_marca_giorno_rango", oggetti(self.vecchio, "index"))
        esito = archivio.scrivi(giorno="2026-07-01", ambito="registri",
                                impronta="ef" * 32, canonico="sigillo:registri",
                                esito={"ok": True, "token": b"\x30\x82\x01",
                                       "tsa": "qtsa.example.eu", "policy": "0.4.0.2023.1.1",
                                       "seriale": "0x77", "gen_time": 1784000000,
                                       "qualificata": True},
                                ora_ts=1784000001)
        self.assertIs(esito["ok"], True)
        self.assertEqual(archivio.conta(), 3)
        self.assertIs(archivio.gia_marcato("2026-07-01", solo_qualificata=True), True)


# ===========================================================================
# IL DEPLOY VERO: il SISTEMA INTERO acceso su una cartella di archivi VECCHI
# ===========================================================================
class TestAvvioSuArchiviVecchi(unittest.TestCase):
    """I collaudi qui sopra aprono UN archivio alla volta. Un deploy no: accende tutto
    insieme su /data, dove gli archivi sono tutti vecchi. Qui si ricostruisce quella
    cartella e si accende il sistema VERO (bootstrap + router), poi si chiede al sito
    quello che chiederebbe un cliente. Se un solo store non venisse migrato - o se
    qualcuno dimenticasse di chiamargli `inizializza_schema` nel cablaggio - il sito
    risponderebbe 500 proprio qui, come farebbe sul server."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="migr_deploy_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        c57 = TestMigrazioneCatalogoFase57
        c58 = TestMigrazioneInventarioFase58
        c88 = TestMigrazioneRegistroHostFase88
        c162 = TestMigrazionePendentiFase162
        c131 = TestMigrazionePayoutFase131
        c147 = TestMigrazioneTassaFase147
        c160 = TestMigrazioneGaranziaFase160
        self.file = {}
        righe_host = (
            ("INSERT INTO host (host_id, email, salt, pw_hash, ragione_sociale, "
             "termini_versione, termini_ts, stato, creato_ts) VALUES (?,?,?,?,?,?,?,?,?)",
             ("h_a1b2c3d4", "chiara.rossi@example.com", c88.SALT.hex(),
              _pw_hash_host(c88.PASSWORD, c88.SALT), "Rossi Ospitalita' Srl",
              "2026-01", 1767225600, "attivo", 1767225600)),)
        for chiave, classe, righe_v1 in (
                ("catalogo", c57, c57.RIGHE_V1), ("inventario", c58, c58.RIGHE_V1),
                ("registro_host", c88, righe_host), ("pendenti", c162, c162.RIGHE_V1),
                ("payout", c131, c131.RIGHE_V1), ("tassa", c147, c147.RIGHE_V1),
                ("garanzia", c160, c160.RIGHE_V1)):
            p = os.path.join(self.dir, chiave + ".db")
            scrivi_db_vecchio(p, classe.DDL_V1, righe_v1)
            self.file[chiave] = p

    def _accendi(self):
        import json
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        from fase83_server import crea_router
        sistema = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEGRETO[:32], con_registrazione_host=True,
            db_catalogo=self.file["catalogo"], db_inventario=self.file["inventario"],
            db_registro_host=self.file["registro_host"],
            db_pendenti=self.file["pendenti"], db_payout=self.file["payout"],
            db_tassa_comunale=self.file["tassa"], db_garanzia=self.file["garanzia"],
            db_accettazioni=os.path.join(self.dir, "accettazioni.db"),
            commissione_bps=1000, psp_bps=300))
        router = crea_router(sistema, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")

        def chiama(metodo, percorso, corpo=None, intestazioni=None, query=None):
            return router.gestisci(metodo, percorso, query or {},
                                   json.dumps(corpo) if corpo is not None else None,
                                   intestazioni or {})

        return sistema, chiama

    def test_il_sito_serve_l_annuncio_nato_col_vecchio_schema(self):
        _sistema, chiama = self._accendi()
        stato, corpo = chiama("GET", "/api/catalogo", query={"citta": "roma"})
        self.assertEqual(stato, 200, corpo)
        slug = [a["slug"] for a in corpo["risultati"]]
        self.assertEqual(slug, ["trastevere-attico-vista"])
        stato, dett = chiama("GET", "/api/catalogo/trastevere-attico-vista")
        self.assertEqual(stato, 200, dett)
        self.assertEqual(dett["prezzo_notte_cents"], 18500)
        self.assertEqual(dett["valuta"], "EUR")
        self.assertEqual(dett["titolo"], "Attico a Trastevere")

    def test_l_host_di_prima_entra_ancora_col_sistema_acceso(self):
        _sistema, chiama = self._accendi()
        stato, corpo = chiama("POST", "/api/host/login",
                              {"email": "chiara.rossi@example.com",
                               "password": TestMigrazioneRegistroHostFase88.PASSWORD})
        self.assertEqual(stato, 200, corpo)
        self.assertTrue(corpo.get("token"))
        stato, annunci = chiama("GET", "/api/host/alloggi",
                                None, {"X-Host-Token": corpo["token"]})
        self.assertEqual(stato, 200, annunci)

    def test_le_sonde_di_salute_rispondono_su_archivi_vecchi(self):
        _sistema, chiama = self._accendi()
        for percorso in ("/api/health/ready", "/api/health/db"):
            stato, corpo = chiama("GET", percorso)
            self.assertEqual(stato, 200, "%s -> %s %s" % (percorso, stato, corpo))

    def test_dopo_l_accensione_ogni_archivio_e_migrato(self):
        """Il cablaggio: ogni store dev'essere stato aperto DAVVERO all'avvio (se
        qualcuno dimenticasse `inizializza_schema` nel bootstrap, la colonna nuova
        resterebbe assente e il primo cliente vedrebbe un 500)."""
        self._accendi()
        attese = {"catalogo": ("alloggi", "indirizzo"),
                  "registro_host": ("host", "stripe_account_id"),
                  "pendenti": ("pendenti", "corpo_json"),
                  "tassa": ("tassa_riscossione", "stornato")}
        for chiave, (tabella, colonna) in attese.items():
            self.assertIn(colonna, colonne(self.file[chiave], tabella),
                          "%s: %s.%s non migrata all'accensione del sistema"
                          % (chiave, tabella, colonna))

    def test_i_dati_veri_non_si_perdono_all_accensione(self):
        prima = righe(self.file["catalogo"], "alloggi",
                      TestMigrazioneCatalogoFase57._COL_V1, "id")
        pendenti_prima = righe(self.file["pendenti"], "pendenti", ("riferimento", "stato"),
                               "riferimento")
        self._accendi()
        self.assertEqual(righe(self.file["catalogo"], "alloggi",
                               TestMigrazioneCatalogoFase57._COL_V1, "id"), prima)
        self.assertEqual(righe(self.file["pendenti"], "pendenti", ("riferimento", "stato"),
                               "riferimento"), pendenti_prima)
        self.assertEqual(len(prima), 3)


# ===========================================================================
# IL CONTROLLO SA FALLIRE (visto rosso permanente)
# ===========================================================================
class TestIlControlloSaFallire(unittest.TestCase):
    """Regola aurea: un controllo che non puo' fallire e' un ornamento. Qui si simulano
    i due guasti che questo file deve vedere - una migrazione DIMENTICATA e un dato
    storico ALTERATO - e si pretende che i controlli li boccino."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="migr_rosso_")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def _archivio_finto(self, ddl, righe_da_scrivere, nome):
        p = os.path.join(self.dir, nome)
        scrivi_db_vecchio(p, ddl, righe_da_scrivere)
        return p

    def test_una_migrazione_dimenticata_viene_vista(self):
        """Db vecchio senza `stornato`, codice che NON migra: il confronto con un db
        nuovo (che la colonna ce l'ha) deve trovare la mancanza."""
        vecchio = self._archivio_finto(
            ("CREATE TABLE t (a INTEGER PRIMARY KEY, b TEXT)",),
            (("INSERT INTO t (a, b) VALUES (?,?)", (1, "x")),), "vecchio.db")
        nuovo = self._archivio_finto(
            ("CREATE TABLE t (a INTEGER PRIMARY KEY, b TEXT, stornato INTEGER DEFAULT 0)",),
            (), "nuovo.db")
        mancanti = sorted(set(colonne(nuovo, "t")) - set(colonne(vecchio, "t")))
        self.assertEqual(mancanti, ["stornato"],
                         "il confronto delle colonne non vede la migrazione mancante")

    def test_una_migrazione_presente_non_da_falsi_allarmi(self):
        vecchio = self._archivio_finto(
            ("CREATE TABLE t (a INTEGER PRIMARY KEY, b TEXT)",), (), "v2.db")
        con = sqlite3.connect(vecchio)
        try:
            with con:
                con.execute("ALTER TABLE t ADD COLUMN stornato INTEGER NOT NULL DEFAULT 0")
        finally:
            con.close()
        nuovo = self._archivio_finto(
            ("CREATE TABLE t (a INTEGER PRIMARY KEY, b TEXT, "
             "stornato INTEGER NOT NULL DEFAULT 0)",), (), "n2.db")
        self.assertEqual(sorted(colonne(vecchio, "t")), sorted(colonne(nuovo, "t")))

    def test_un_dato_storico_alterato_viene_visto(self):
        p = self._archivio_finto(
            ("CREATE TABLE soldi (id INTEGER PRIMARY KEY, cents INTEGER NOT NULL)",),
            (("INSERT INTO soldi (id, cents) VALUES (?,?)", (1, 34040)),), "soldi.db")
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
        p = self._archivio_finto(
            ("CREATE TABLE soldi (id INTEGER PRIMARY KEY, cents INTEGER NOT NULL)",),
            (("INSERT INTO soldi (id, cents) VALUES (?,?)", (1, 34040)),
             ("INSERT INTO soldi (id, cents) VALUES (?,?)", (2, 51060))), "persa.db")
        prima = righe(p, "soldi", ("id", "cents"), "id")
        self.assertEqual(len(prima), 2)
        con = sqlite3.connect(p)
        try:
            with con:
                con.execute("DELETE FROM soldi WHERE id=2")
        finally:
            con.close()
        dopo = righe(p, "soldi", ("id", "cents"), "id")
        self.assertEqual(len(dopo), 1)
        self.assertNotEqual(dopo, prima, "il confronto non vede una riga sparita")

    def test_un_trigger_mancante_viene_visto(self):
        senza = self._archivio_finto(("CREATE TABLE t (a INTEGER)",), (), "senza.db")
        con_trigger = self._archivio_finto(
            ("CREATE TABLE t (a INTEGER)",
             "CREATE TRIGGER t_no_update BEFORE UPDATE ON t "
             "BEGIN SELECT RAISE(ABORT, 'vietato'); END"), (), "con.db")
        self.assertEqual(oggetti(senza, "trigger"), [])
        self.assertEqual(oggetti(con_trigger, "trigger"), ["t_no_update"])
        self.assertNotEqual(oggetti(senza, "trigger"), oggetti(con_trigger, "trigger"))


# ===========================================================================
# NESSUN ARCHIVIO DIMENTICATO: se nasce un modulo con un CREATE TABLE nuovo e
# nessuno gli scrive la prova di migrazione, questo controllo lo dice.
# ===========================================================================
class TestNessunArchivioSenzaProva(unittest.TestCase):

    # I moduli con schema COPERTO qui sopra. Ogni voce = una classe di prova reale.
    COPERTI = ("fase57_vetrina", "fase58_channel_manager", "fase88_registro_host",
               "fase162_pagamenti_pendenti", "fase131_payout_dashboard",
               "fase147_tassa_comunale", "fase160_escrow_garanzia",
               "fase177_financial_controller", "fase163_accettazioni",
               "fase192_admin_accounts", "fase201_partner", "fase158_domanda",
               "fase127_checkin_digitale", "fase184_marca_temporale")

    def test_ogni_modulo_coperto_ha_la_sua_classe_di_prova(self):
        moduli_provati = set()
        for nome, oggetto in sorted(globals().items()):
            if not (isinstance(oggetto, type) and issubclass(oggetto, BaseMigrazione)
                    and oggetto is not BaseMigrazione):
                continue
            sorgente = oggetto.apri.__code__.co_names
            moduli_provati.update(n for n in sorgente if n.startswith("fase"))
            # ogni classe deve davvero costruire qualcosa e dichiarare le sue tabelle
            self.assertTrue(oggetto.DDL_V1, "%s: schema vecchio non dichiarato" % nome)
            self.assertTrue(oggetto.TABELLE, "%s: tabelle non dichiarate" % nome)
        # `apri` importa il modulo per nome: il nome del modulo compare fra i co_names
        # solo se l'import e' scritto li' dentro (import lazy, come nel prodotto).
        self.assertEqual(sorted(moduli_provati), sorted(self.COPERTI),
                         "l'elenco dei moduli coperti non corrisponde alle classi di prova")

    def test_i_moduli_coperti_esistono_e_hanno_uno_schema(self):
        radice = os.path.dirname(os.path.abspath(__file__))
        senza = []
        for modulo in self.COPERTI:
            percorso = os.path.join(radice, modulo + ".py")
            self.assertTrue(os.path.isfile(percorso), "modulo sparito: %s" % modulo)
            with open(percorso, "r", encoding="utf-8") as f:
                testo = f.read()
            if "CREATE TABLE IF NOT EXISTS" not in testo:
                senza.append(modulo)
        self.assertEqual(senza, [],
                         "questi moduli non creano piu' tabelle: la voce va tolta o "
                         "corretta -> %r" % (senza,))


if __name__ == "__main__":
    unittest.main(verbosity=2)
