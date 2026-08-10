"""CORPUS DI DATI VERI — archivi scritti A MANO, come se fossero nati mesi fa.

PERCHE' ESISTE
--------------
Ogni test della suite parte da archivi VUOTI e li riempie chiamando le funzioni di
scrittura del prodotto. Il risultato e' che il prodotto legge sempre e solo cio' che il
prodotto stesso ha appena scritto, oggi, con le regole di oggi: coordinate sempre
presenti, testi sempre validati, stati sempre coerenti. In produzione, invece, vivono 24
archivi pieni di righe nate mesi fa, scritte da versioni precedenti, riparate a mano,
importate da iCal, lasciate a meta' da un utente che ha chiuso il browser.

Questo modulo scrive quegli archivi con `sqlite3` NUDO: nessun import da `fase*.py`.
E' la condizione che rende il collaudo utile — se il corpus lo generassero le stesse
funzioni che poi lo leggono, un difetto nel modello dei dati sarebbe invisibile per
costruzione (scrivo cio' che so leggere).

COSA C'E' DENTRO (vario di proposito)
-------------------------------------
  * annunci con e senza indirizzo, con e senza CIN, con e senza coordinate (NULL),
    pubblicati / sospesi / in bozza, in EUR / JPY / GBP, con titoli pieni di accenti,
    apostrofi tipografici ed emoji, una descrizione da 8.000 caratteri, un annuncio
    di un host CANCELLATO (riga orfana) e una foto agganciata a un annuncio che non
    esiste piu';
  * inventario con giorni pieni, chiusi, a prezzo zero, a zero unita' e giorni MAI
    caricati (buco nel calendario);
  * movimenti (prenotazioni) attivi, rilasciati, rifiutati, con date NULL, con
    `origine` NULL, con la chiave `reblock:` e un doppione logico sulle stesse date;
  * pagamenti pendenti in OGNI stato, con soggiorno a cavallo d'anno, date invertite
    e date malformate;
  * payout in ogni stato, uno a importo ZERO, uno in valuta diversa, uno orfano;
  * tassa di soggiorno con regola valida, regola NON-JSON, regola JSON che non e' un
    oggetto, riscossioni e un tombstone di storno;
  * escrow in ogni stato (in_garanzia / contestato / rilasciato / risolto / annullato);
  * accettazioni firmate (firma HMAC ricalcolata qui, in modo indipendente), una con
    riferimento esterno, una di versione VECCHIA e una MANOMESSA;
  * libro giornale hash-incatenato (catena ricalcolata qui secondo il formato
    documentato), note e debiti, con un anno fiscale precedente da ignorare;
  * recensioni verificate e non, con categorie NULL, emoji e una riga orfana;
  * contatore DAC7 su file JSON.

I VALORI SONO SCELTI PERCHE' SI POSSANO CALCOLARE A MANO: il collaudo che legge questo
corpus asserisce numeri esatti, non "non e' 500".
"""
import calendar
import hashlib
import hmac
import json
import os
import sqlite3

# 32 byte esatti: e' il formato che il sistema si aspetta per l'HMAC.
SEGRETO = b"corpus-dati-reali-collaudo".ljust(32, b"!")
assert len(SEGRETO) == 32

PBKDF2_ITER = 200_000          # ri-dichiarato qui: il corpus non importa il prodotto

# ── identita' del corpus (le usano i collaudi) ──────────────────────────────
HOST_ROMA = "h_roma_0001"
HOST_TOKYO = "h_tokyo_002"
HOST_SOSPESO = "h_sosp_0003"
HOST_CANCELLATO = "h_canc_0004"

EMAIL_ROMA = "chiara.rossi@example.com"
PASSWORD_ROMA = "Trastevere!2025"
EMAIL_TOKYO = "kenji.tanaka@example.jp"
PASSWORD_TOKYO = "Shinjuku!2025"

SLUG_ROMA = "trastevere-attico-vista"
SLUG_TOKYO = "shinjuku-monolocale"
SLUG_SOSPESO = "porto-cervo-villa"
SLUG_BOZZA = "bozza-mai-finita"
SLUG_SENZA_GEO = "roma-senza-coordinate"
SLUG_LONDRA = "londra-loft-lungo"
SLUG_ORFANO = "orfano-host-cancellato"
SLUG_MILANO = "milano-citta-studi"
SLUG_SPARITO = "alloggio-cancellato-2024"     # non esiste piu' nel catalogo

# IN PRODUZIONE il riferimento della prenotazione E' la chiave di idempotenza del blocco
# (fase59: `riferimento = idem[:24]`), e payout / garanzia / tassa / giornale / recensioni
# usano quello STESSO identificativo. Il corpus rispetta questo legame — altrimenti non
# proverebbe le letture che incrociano gli archivi.
REF_PAGATA = "IDEM-2026-0001"          # pagata, soggiorno di 3 notti
REF_ATTESA = "IDEM-2026-0002"          # hold mai pagato (scaduto)
REF_SCADUTA = "IDEM-2026-0003"         # scaduta, alloggio di Tokyo, poi rilasciata
REF_REBLOCK = "IDEM-2026-0006"         # pagata TARDI: il blocco vive sotto 'reblock:<rif>'
REF_CANCELLATA = "IDEM-2026-0007"      # cancellata dall'host, blocco rilasciato
REF_DOPPIONE = "IDEM-2026-0008"        # stesse date della prima (doppione storico)
REF_SENZA_GEO = "IDEM-2026-0009"       # pagata sull'annuncio senza coordinate
REF_CAVALLO_ANNO = "IDEM-2025-0006"    # soggiorno a cavallo fra 2025 e 2026
REF_DA_RIMBORSARE = "IDEM-2026-9994"
REF_DATE_INVERTITE = "IDEM-2026-9995"  # check_out PRIMA del check_in
REF_DATA_VUOTA = "IDEM-2026-9996"      # check_in stringa vuota
REF_JP = "IDEM-JP-000003"
REF_ORFANO = "IDEM-ORF-00001"          # punta a un alloggio e a un host spariti
REF_ANNO_PRIMA = "IDEM-2025-9001"      # esercizio fiscale precedente

# ⛔ QUESTO VALORE SI SCRIVE A MANO, E DEVE RESTARE COSI'. Il corpus non importa il
# prodotto (lo pretende `test_il_corpus_e_scritto_senza_il_prodotto`): se leggesse la
# versione da fase163 il collaudo confronterebbe il prodotto con se stesso e non
# potrebbe piu' accorgersi di niente. Provato il 2026-08-10: agganciarlo al motore fa
# diventare rossa quella guardia, ed e' giusto cosi'.
# Quando fase163 alza la versione, questa riga si aggiorna A MANO -- e chi se ne
# dimentica lo scopre subito, perche' `test_una_versione_vecchia_del_contratto_obbliga_a_
# riaccettare` diventa rossa. E' il segnale, non un fastidio.
CONTRATTO_VERSIONE_CORRENTE = "2026-08-10"    # deve combaciare con fase163 (a mano)
CONTRATTO_VERSIONE_VECCHIA = "2026-01-11"     # una versione DAVVERO vecchia, mai corrente
PRIVACY_VERSIONE_CORRENTE = "2026-07-20"

TITOLO_ROMA = "Attico «da sogno» a Trastevere \U0001f3db️ — l’affaccio sulle cupole"
DESCRIZIONE_LUNGA = ("Loft su due livelli nel cuore di Shoreditch. " * 200)[:8000]


def _ts(anno, mese, giorno, ora=12, minuto=0):
    """Istante UTC intero (il prodotto legge i ts con utcfromtimestamp)."""
    return calendar.timegm((anno, mese, giorno, ora, minuto, 0, 0, 0, 0))


ts_utc = _ts          # nome pubblico: i collaudi ricalcolano gli istanti allo stesso modo


def _pw(password, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                               bytes.fromhex(salt_hex), PBKDF2_ITER).hex()


SALT_ROMA = "a1b2c3d4e5f6071829304a5b6c7d8e9f"
SALT_TOKYO = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"
SALT_INERTE = "deadbeefdeadbeefdeadbeefdeadbeef"


# ═══════════════════════════════════════════════════════════════════════════
# SCHEMI (versione ODIERNA, scritti a mano: il corpus non chiede nulla al prodotto)
# ═══════════════════════════════════════════════════════════════════════════
DDL_CATALOGO = (
    """CREATE TABLE IF NOT EXISTS alloggi (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id TEXT NOT NULL, slug TEXT NOT NULL UNIQUE, titolo TEXT NOT NULL,
        descrizione TEXT NOT NULL DEFAULT '', citta TEXT NOT NULL,
        paese TEXT NOT NULL DEFAULT '', fuso TEXT NOT NULL DEFAULT '',
        indirizzo TEXT NOT NULL DEFAULT '', prezzo_notte_cents INTEGER NOT NULL,
        capacita INTEGER NOT NULL, camere INTEGER NOT NULL DEFAULT 1,
        bagni INTEGER NOT NULL DEFAULT 1, servizi_mask INTEGER NOT NULL DEFAULT 0,
        valuta TEXT NOT NULL DEFAULT 'EUR', stato TEXT NOT NULL DEFAULT 'pubblicato',
        lat_micro INTEGER, lon_micro INTEGER,
        politica_cancellazione TEXT NOT NULL DEFAULT 'flessibile',
        tassa_pp_notte_cents INTEGER NOT NULL DEFAULT 0,
        tassa_max_notti INTEGER NOT NULL DEFAULT 0,
        tassa_perc_bps INTEGER NOT NULL DEFAULT 0,
        sconto_settimana_bps INTEGER NOT NULL DEFAULT 0,
        sconto_mese_bps INTEGER NOT NULL DEFAULT 0,
        modalita_prenotazione TEXT NOT NULL DEFAULT 'immediata',
        pin_manuale INTEGER NOT NULL DEFAULT 0,
        paga_in_struttura INTEGER NOT NULL DEFAULT 1,
        creato_ts TEXT NOT NULL, aggiornato_ts TEXT NOT NULL,
        cin TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS alloggio_immagini (
        id INTEGER PRIMARY KEY AUTOINCREMENT, alloggio_id INTEGER NOT NULL,
        url TEXT NOT NULL, ordine INTEGER NOT NULL DEFAULT 0,
        alt TEXT NOT NULL DEFAULT '')""",
)

DDL_INVENTARIO = (
    """CREATE TABLE IF NOT EXISTS inventario (
        alloggio_id TEXT NOT NULL, giorno TEXT NOT NULL,
        unita_totali INTEGER NOT NULL DEFAULT 0,
        unita_occupate INTEGER NOT NULL DEFAULT 0,
        prezzo_netto_cents INTEGER NOT NULL DEFAULT 0,
        chiuso INTEGER NOT NULL DEFAULT 0, min_notti INTEGER NOT NULL DEFAULT 1,
        aggiornato_ts TEXT NOT NULL, PRIMARY KEY (alloggio_id, giorno))""",
    """CREATE TABLE IF NOT EXISTS movimenti (
        idem_key TEXT PRIMARY KEY, alloggio_id TEXT NOT NULL, tipo TEXT NOT NULL,
        esito TEXT NOT NULL, check_in TEXT, check_out TEXT,
        origine TEXT DEFAULT '', ts TEXT NOT NULL)""",
)

DDL_REGISTRO_HOST = (
    """CREATE TABLE IF NOT EXISTS host (
        host_id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, salt TEXT NOT NULL,
        pw_hash TEXT NOT NULL, ragione_sociale TEXT NOT NULL DEFAULT '',
        telefono TEXT NOT NULL DEFAULT '', line_token TEXT NOT NULL DEFAULT '',
        wechat_webhook TEXT NOT NULL DEFAULT '',
        telegram_chat_id TEXT NOT NULL DEFAULT '',
        stripe_account_id TEXT NOT NULL DEFAULT '',
        termini_versione TEXT NOT NULL, termini_ts INTEGER NOT NULL,
        stato TEXT NOT NULL DEFAULT 'attivo', creato_ts INTEGER NOT NULL,
        codice_fiscale TEXT NOT NULL DEFAULT '', partita_iva TEXT NOT NULL DEFAULT '',
        indirizzo_fiscale TEXT NOT NULL DEFAULT '', paese TEXT NOT NULL DEFAULT '',
        iban TEXT NOT NULL DEFAULT '', tipo_soggetto TEXT NOT NULL DEFAULT '',
        data_nascita TEXT NOT NULL DEFAULT '', verifica_stato TEXT NOT NULL DEFAULT '',
        verifica_note TEXT NOT NULL DEFAULT '', verifica_ts TEXT NOT NULL DEFAULT '',
        verifica_da TEXT NOT NULL DEFAULT '',
        stripe_customer_id TEXT NOT NULL DEFAULT '',
        stripe_payment_method TEXT NOT NULL DEFAULT '')""",
)

DDL_PENDENTI = (
    """CREATE TABLE IF NOT EXISTS pendenti (
        riferimento TEXT PRIMARY KEY, alloggio_id TEXT NOT NULL,
        check_in TEXT NOT NULL, check_out TEXT NOT NULL,
        idem_key TEXT NOT NULL DEFAULT '', tassa_cents INTEGER NOT NULL DEFAULT 0,
        comune TEXT NOT NULL DEFAULT '', host_id TEXT NOT NULL DEFAULT '',
        email TEXT NOT NULL DEFAULT '', quote_token TEXT NOT NULL DEFAULT '',
        corpo_json TEXT NOT NULL DEFAULT '', scadenza_ts INTEGER NOT NULL,
        stato TEXT NOT NULL DEFAULT 'in_attesa',
        promemoria_ts INTEGER NOT NULL DEFAULT 0, creato_ts INTEGER NOT NULL,
        invito_recensione_ts INTEGER NOT NULL DEFAULT 0)""",
)

DDL_PAYOUT = (
    """CREATE TABLE IF NOT EXISTS payout (
        prenotazione_id TEXT PRIMARY KEY, host_id TEXT NOT NULL,
        minori INTEGER NOT NULL, valuta TEXT NOT NULL, stato TEXT NOT NULL,
        ts INTEGER NOT NULL)""",
)

DDL_TASSA = (
    """CREATE TABLE IF NOT EXISTS tassa_regola (
        comune TEXT PRIMARY KEY, regola_json TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS tassa_riscossione (
        prenotazione_id TEXT PRIMARY KEY, comune TEXT NOT NULL,
        importo INTEGER NOT NULL, ts INTEGER NOT NULL,
        stornato INTEGER NOT NULL DEFAULT 0)""",
)

DDL_GARANZIA = (
    """CREATE TABLE IF NOT EXISTS garanzia (
        prenotazione_id TEXT PRIMARY KEY, alloggio_id TEXT NOT NULL DEFAULT '',
        importo_host_cents INTEGER NOT NULL,
        host_riceve_cents INTEGER NOT NULL DEFAULT 0,
        ospite_rimborso_cents INTEGER NOT NULL DEFAULT 0,
        stato TEXT NOT NULL DEFAULT 'in_garanzia', motivo TEXT NOT NULL DEFAULT '',
        sblocco_auto_ts INTEGER NOT NULL, aperto_ts INTEGER NOT NULL,
        aggiornato_ts INTEGER NOT NULL)""",
)

DDL_ACCETTAZIONI = (
    """CREATE TABLE IF NOT EXISTS accettazioni (
        id INTEGER PRIMARY KEY AUTOINCREMENT, host_id TEXT NOT NULL,
        documento TEXT NOT NULL, versione TEXT NOT NULL, doc_sha256 TEXT NOT NULL,
        lang TEXT NOT NULL DEFAULT 'it', ip TEXT NOT NULL DEFAULT '',
        user_agent TEXT NOT NULL DEFAULT '', vessatorie INTEGER NOT NULL DEFAULT 0,
        accettato_ts INTEGER NOT NULL, firma TEXT NOT NULL,
        riferimento TEXT NOT NULL DEFAULT '')""",
)

DDL_FINANZA = (
    """CREATE TABLE IF NOT EXISTS libro_giornale (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, evento_id TEXT NOT NULL UNIQUE,
        ts INTEGER NOT NULL, tipo TEXT NOT NULL, riferimento TEXT NOT NULL,
        soggetto TEXT NOT NULL, conto_dare TEXT NOT NULL, conto_avere TEXT NOT NULL,
        importo_cents INTEGER NOT NULL CHECK (importo_cents > 0),
        valuta TEXT NOT NULL, causale TEXT NOT NULL, emittente TEXT NOT NULL,
        prev_hash TEXT NOT NULL, hash TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS note (
        nota_id TEXT PRIMARY KEY,
        tipo TEXT NOT NULL CHECK (tipo IN ('credito','debito')),
        riferimento TEXT NOT NULL, causale TEXT NOT NULL, ts INTEGER NOT NULL,
        emittente TEXT NOT NULL, soggetto TEXT NOT NULL,
        importo_cents INTEGER NOT NULL CHECK (importo_cents > 0),
        valuta TEXT NOT NULL, stato TEXT NOT NULL DEFAULT 'emessa',
        storno_di TEXT, giornale_seq INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS debiti (
        debito_id TEXT PRIMARY KEY, host_id TEXT NOT NULL, riferimento TEXT NOT NULL,
        residuo_cents INTEGER NOT NULL CHECK (residuo_cents >= 0),
        valuta TEXT NOT NULL, stato TEXT NOT NULL,
        tentativi INTEGER NOT NULL DEFAULT 0, prossimo_ts INTEGER,
        aggiornato_ts INTEGER NOT NULL)""",
)

DDL_RECENSIONI = (
    """CREATE TABLE IF NOT EXISTS recensioni (
        prenotazione_id TEXT PRIMARY KEY, alloggio_id TEXT NOT NULL,
        voto INTEGER NOT NULL, testo TEXT NOT NULL DEFAULT '',
        lingua TEXT NOT NULL DEFAULT 'en', verificata INTEGER NOT NULL DEFAULT 0,
        ts TEXT NOT NULL, cat_pulizia INTEGER, cat_comfort INTEGER,
        cat_posizione INTEGER, cat_servizi INTEGER, cat_host INTEGER,
        cat_qualita_prezzo INTEGER)""",
)


# ═══════════════════════════════════════════════════════════════════════════
# RIGHE
# ═══════════════════════════════════════════════════════════════════════════
_A = ("INSERT INTO alloggi (id, host_id, slug, titolo, descrizione, citta, paese, fuso, "
      "indirizzo, prezzo_notte_cents, capacita, camere, bagni, servizi_mask, valuta, "
      "stato, lat_micro, lon_micro, politica_cancellazione, tassa_pp_notte_cents, "
      "tassa_max_notti, tassa_perc_bps, sconto_settimana_bps, sconto_mese_bps, "
      "modalita_prenotazione, pin_manuale, paga_in_struttura, creato_ts, aggiornato_ts, "
      "cin) VALUES (" + ",".join("?" * 30) + ")")

# servizi_mask dell'attico: wifi(1) + piscina(4) + un bit di un servizio RITIRATO (1<<20).
# Un bit sconosciuto e' cio' che resta negli archivi quando un servizio viene tolto dal
# registro: il prodotto deve ignorarlo, non inciampare.
MASK_ATTICO = 1 | 4 | (1 << 20)

RIGHE_CATALOGO = (
    (_A, (1, HOST_ROMA, SLUG_ROMA, TITOLO_ROMA,
          "Terrazza vista cupole, due camere, l’ascensore c’è. ☕ \U0001f6cb️",
          "roma", "IT", "Europe/Rome", "Via della Lungaretta 12, int. 4",
          18500, 4, 2, 1, MASK_ATTICO, "EUR", "pubblicato", 41902782, 12496366,
          "moderata", 450, 10, 0, 500, 1500, "immediata", 1, 1,
          "2025-11-03T10:12:00", "2026-06-30T18:40:00", "IT058091C2X3Y4Z5W6")),
    (_A, (2, HOST_TOKYO, SLUG_TOKYO, "新宿のワンルーム",
          "駅から徒歩2分。", "tokyo", "JP", "Asia/Tokyo", "",
          21000, 2, 1, 1, 1, "JPY", "pubblicato", 35689487, 139691711,
          "rigida", 0, 0, 0, 0, 0, "su_richiesta", 0, 0,
          "2025-12-19T09:00:00", "2026-07-01T08:05:00", "")),
    (_A, (3, HOST_ROMA, SLUG_SOSPESO, "Villa a Porto Cervo",
          "Piscina privata, vista sul golfo.", "Porto Cervo", "IT", "Europe/Rome",
          "Località Cala di Volpe snc",
          92000, 8, 4, 3, 4 | 256, "EUR", "sospeso", 41131000, 9536000,
          "non_rimborsabile", 0, 0, 0, 0, 0, "immediata", 0, 1,
          "2026-01-02T11:00:00", "2026-05-02T11:00:00", "")),
    (_A, (4, HOST_ROMA, SLUG_BOZZA, "Senza titolo", "", "roma", "IT", "", "",
          0, 1, 1, 1, 0, "EUR", "bozza", None, None,
          "flessibile", 0, 0, 0, 0, 0, "immediata", 0, 1,
          "2026-04-18T22:31:00", "2026-04-18T22:31:00", "")),
    (_A, (5, HOST_ROMA, SLUG_SENZA_GEO,
          "Camera \U0001f31e luminosa vicino San Giovanni", "", "roma", "IT", "", "",
          7900, 2, 1, 1, 1 | 2, "EUR", "pubblicato", None, None,
          "flessibile", 300, 0, 0, 0, 0, "immediata", 0, 1,
          "2026-02-01T08:00:00", "2026-03-05T09:00:00", "")),
    (_A, (6, HOST_TOKYO, SLUG_LONDRA, "Loft a Shoreditch", DESCRIZIONE_LUNGA,
          "londra", "GB", "Europe/London", "12 Rivington Street",
          33000, 3, 1, 1, 0, "GBP", "pubblicato", 51526000, -83000,
          "moderata", 0, 0, 500, 0, 0, "immediata", 0, 1,
          "2026-03-11T12:00:00", "2026-03-30T12:00:00", "")),
    (_A, (7, HOST_CANCELLATO, SLUG_ORFANO, "Bilocale vicino Termini",
          "Annuncio di un host che non esiste piu' nel registro.", "roma", "IT", "", "",
          12000, 3, 1, 1, 1, "EUR", "pubblicato", 41900000, 12500000,
          "flessibile", 0, 0, 0, 0, 0, "immediata", 0, 1,
          "2025-09-09T09:09:00", "2026-07-02T09:09:00", "")),
    (_A, (8, HOST_TOKYO, SLUG_MILANO, "Monolocale Città Studi",
          "Vicino al Politecnico.", "Milano", "IT", "Europe/Rome", "Via Pascoli 3",
          9500, 2, 1, 1, 1, "EUR", "pubblicato", 45478000, 9227000,
          "flessibile", 0, 0, 0, 0, 0, "immediata", 0, 1,
          "2026-05-20T10:00:00", "2026-05-20T10:00:00", "")),
    # foto: l'ordine sul database NON e' quello di inserimento (thumb = ordine piu' basso)
    ("INSERT INTO alloggio_immagini (id, alloggio_id, url, ordine, alt) VALUES (?,?,?,?,?)",
     (1, 1, "/uploads/attico_terrazza.jpg", 1, "terrazza al tramonto")),
    ("INSERT INTO alloggio_immagini (id, alloggio_id, url, ordine, alt) VALUES (?,?,?,?,?)",
     (2, 1, "/uploads/attico_salotto.jpg", 0, "")),
    # FOTO ORFANA: l'annuncio 999 e' stato cancellato, la riga e' rimasta
    ("INSERT INTO alloggio_immagini (id, alloggio_id, url, ordine, alt) VALUES (?,?,?,?,?)",
     (3, 999, "/uploads/fantasma.jpg", 0, "annuncio sparito")),
)

_I = ("INSERT INTO inventario (alloggio_id, giorno, unita_totali, unita_occupate, "
      "prezzo_netto_cents, chiuso, min_notti, aggiornato_ts) VALUES (?,?,?,?,?,?,?,?)")
_AGG = "2026-08-01T00:00:00"

RIGHE_INVENTARIO = (
    (_I, (SLUG_ROMA, "2026-09-01", 1, 1, 18500, 0, 1, _AGG)),      # pieno
    (_I, (SLUG_ROMA, "2026-09-02", 1, 1, 18500, 0, 1, _AGG)),      # pieno
    (_I, (SLUG_ROMA, "2026-09-03", 1, 1, 18500, 0, 1, _AGG)),      # pieno
    (_I, (SLUG_ROMA, "2026-09-04", 1, 0, 18500, 1, 1, _AGG)),      # chiuso dall'host
    (_I, (SLUG_ROMA, "2026-09-05", 1, 0, 18500, 0, 3, _AGG)),      # libero ma min 3 notti
    (_I, (SLUG_ROMA, "2026-09-06", 1, 0, 0, 0, 1, _AGG)),          # PREZZO ZERO
    (_I, (SLUG_ROMA, "2026-09-07", 1, 0, 0, 0, 1, _AGG)),          # PREZZO ZERO
    (_I, (SLUG_ROMA, "2026-09-08", 0, 0, 18500, 0, 1, _AGG)),      # ZERO unita'
    # 2026-09-09 volutamente ASSENTE: buco nel calendario (giorno mai caricato)
    (_I, (SLUG_ROMA, "2026-09-10", 2, 1, 20000, 0, 1, _AGG)),
    # VENDUTO **E** CHIUSO: l'host ha posato la chiusura DOPO la vendita. La vista deve
    # dire 'pieno' (c'e' un ospite dentro), mai 'chiuso' (che nasconderebbe la
    # prenotazione viva). Fuori dalla finestra usata dalle metriche, di proposito.
    (_I, (SLUG_ROMA, "2026-09-11", 1, 1, 18500, 1, 1, _AGG)),
    (_I, (SLUG_SENZA_GEO, "2026-03-01", 1, 1, 7900, 0, 1, _AGG)),
    (_I, (SLUG_SPARITO, "2026-07-01", 1, 1, 5000, 0, 1, _AGG)),    # ORFANO
)

_M = ("INSERT INTO movimenti (idem_key, alloggio_id, tipo, esito, check_in, check_out, "
      "origine, ts) VALUES (?,?,?,?,?,?,?,?)")

RIGHE_MOVIMENTI = (
    (_M, (REF_PAGATA, SLUG_ROMA, "blocco", "occupato",
          "2026-09-01", "2026-09-04", "web", "2026-08-20T09:15:00")),
    # origine NULL: colonna nullable, il codice la tratta come stringa
    (_M, (REF_ATTESA, SLUG_ROMA, "blocco", "occupato",
          "2026-09-10", "2026-09-11", None, "2026-08-22T11:00:00")),
    # DATE NULL: import iCal andato storto mesi fa
    (_M, (REF_SCADUTA, SLUG_TOKYO, "blocco", "occupato",
          None, None, "ical", "2026-08-23T08:00:00")),
    (_M, ("rilascio:" + REF_SCADUTA, SLUG_TOKYO, "rilascio", "liberato",
          None, None, "rimborso", "2026-08-24T08:00:00")),
    # ORFANO: punta a un annuncio che non e' piu' in catalogo
    (_M, (REF_ORFANO, SLUG_SPARITO, "blocco", "occupato",
          "2026-07-01", "2026-07-05", "web", "2026-06-01T10:00:00")),
    # tentativo RIFIUTATO: non e' una prenotazione
    (_M, ("IDEM-2026-0005", SLUG_ROMA, "blocco", "rifiutato",
          "2026-09-01", "2026-09-04", "web", "2026-08-19T18:00:00")),
    # chiave di RE-BLOCCO tardivo: il riferimento resta REF_REBLOCK
    (_M, ("reblock:" + REF_REBLOCK, SLUG_ROMA, "blocco", "occupato",
          "2026-10-01", "2026-10-05", "web", "2026-08-25T10:00:00")),
    # prenotazione poi RILASCIATA (archivio)
    (_M, (REF_CANCELLATA, SLUG_ROMA, "blocco", "occupato",
          "2026-05-01", "2026-05-04", "web", "2026-04-01T10:00:00")),
    (_M, ("rilascio:" + REF_CANCELLATA, SLUG_ROMA, "rilascio", "liberato",
          "2026-05-01", "2026-05-04", "rimborso", "2026-04-15T10:00:00")),
    # DOPPIONE logico: stesse date, stesso alloggio, chiave diversa
    (_M, (REF_DOPPIONE, SLUG_ROMA, "blocco", "occupato",
          "2026-09-01", "2026-09-04", "web", "2026-08-21T09:15:00")),
    (_M, (REF_SENZA_GEO, SLUG_SENZA_GEO, "blocco", "occupato",
          "2026-03-01", "2026-03-08", "web", "2026-02-10T10:00:00")),
)

_H = ("INSERT INTO host (host_id, email, salt, pw_hash, ragione_sociale, telefono, "
      "line_token, wechat_webhook, telegram_chat_id, stripe_account_id, "
      "termini_versione, termini_ts, stato, creato_ts, codice_fiscale, partita_iva, "
      "indirizzo_fiscale, paese, iban, tipo_soggetto, data_nascita, verifica_stato, "
      "verifica_note, verifica_ts, verifica_da, stripe_customer_id, "
      "stripe_payment_method) VALUES (" + ",".join("?" * 27) + ")")


def _righe_host():
    return (
        (_H, (HOST_ROMA, EMAIL_ROMA, SALT_ROMA, _pw(PASSWORD_ROMA, SALT_ROMA),
              "Rossi Ospitalità S.r.l.", "+39 06 1234567", "", "", "998877",
              "acct_1RomaLive", "1.0", _ts(2025, 11, 3), "attivo", _ts(2025, 11, 3),
              "RSSCHR85M41H501Z", "IT01234567890", "Via della Lungaretta 12, Roma",
              "IT", "IT60X0542811101000000123456", "societa", "1985-08-01",
              "verificato", "documenti ok", str(_ts(2026, 1, 15)), "super-admin",
              "cus_Roma1", "pm_Roma1")),
        # host senza NESSUN dato fiscale: incompleto per il DAC7
        (_H, (HOST_TOKYO, EMAIL_TOKYO, SALT_TOKYO, _pw(PASSWORD_TOKYO, SALT_TOKYO),
              "田中ゲストハウス", "", "", "", "", "",
              "1.0", _ts(2025, 12, 19), "attivo", _ts(2025, 12, 19),
              "", "", "", "", "", "", "", "", "", "", "", "", "")),
        (_H, (HOST_SOSPESO, "mario.sospeso@example.com", SALT_INERTE,
              "0" * 64, "Sospeso di Mario", "", "", "", "", "",
              "1.0", _ts(2026, 2, 2), "sospeso", _ts(2026, 2, 2),
              "SSPMRA70A01H501X", "", "", "IT", "", "persona_fisica", "1970-01-01",
              "revocato", "documenti non conformi", str(_ts(2026, 3, 1)),
              "super-admin", "", "")),
        (_H, (HOST_CANCELLATO, "ex.host@example.com", SALT_INERTE, "0" * 64,
              "", "", "", "", "", "", "1.0", _ts(2025, 6, 1), "cancellato",
              _ts(2025, 6, 1), "", "", "", "", "", "", "", "", "", "", "", "", "")),
    )


_P = ("INSERT INTO pendenti (riferimento, alloggio_id, check_in, check_out, idem_key, "
      "tassa_cents, comune, host_id, email, quote_token, corpo_json, scadenza_ts, "
      "stato, promemoria_ts, creato_ts, invito_recensione_ts) "
      "VALUES (" + ",".join("?" * 16) + ")")

# corpo_json ODIERNO: breakdown completo (la forma che scrive il prodotto oggi)
CORPO_MODERNO = json.dumps({
    "netto_host_cents": 16650, "prezzo_guest_cents": 19850, "totale_cents": 19850,
    "commissione_cents": 1850, "costo_pagamento_cents": 600,
    "sconto_credito_cents": 0, "credito_id": "", "tassa_soggiorno_cents": 1350,
    "valuta": "EUR", "host_id": HOST_ROMA, "voucher_token": "vt_1",
    "modo_pagamento": "", "saldo_in_loco_cents": 0, "anticipo_online_cents": 0,
    "titolo": TITOLO_ROMA})
# corpo_json VECCHIO: prima che il breakdown fosse completo (mancano tre campi)
CORPO_LEGACY = json.dumps({
    "netto_host_cents": 22000, "prezzo_guest_cents": 24900, "totale_cents": 24900,
    "commissione_cents": 2000, "valuta": "EUR", "host_id": HOST_ROMA})
# corpo_json ARCAICO: nemmeno il prezzo dell'ospite
CORPO_ARCAICO = json.dumps({"netto_host_cents": 7100, "valuta": "EUR"})

RIGHE_PENDENTI = (
    (_P, (REF_PAGATA, SLUG_ROMA, "2026-09-01", "2026-09-04", REF_PAGATA,
          1350, "roma", HOST_ROMA, "ospite1@example.com", "qt_1", CORPO_MODERNO,
          _ts(2026, 8, 20, 10), "pagato", 0, _ts(2026, 8, 20, 9), 0)),
    # corpo_json VUOTO (prenotazione nata prima che il campo esistesse) + hold SCADUTO
    (_P, (REF_ATTESA, SLUG_ROMA, "2026-09-10", "2026-09-11", REF_ATTESA,
          0, "", HOST_ROMA, "ospite2@example.com", "", "",
          _ts(2026, 8, 22, 12), "in_attesa", 0, _ts(2026, 8, 22, 11), 0)),
    (_P, (REF_SCADUTA, SLUG_TOKYO, "2026-08-01", "2026-08-03", REF_SCADUTA,
          0, "", HOST_TOKYO, "ospite3@example.jp", "", "{}",
          _ts(2026, 7, 1), "scaduto", 0, _ts(2026, 6, 30), 0)),
    # pagata TARDI: il blocco vive con la chiave 'reblock:<rif>'
    (_P, (REF_REBLOCK, SLUG_ROMA, "2026-10-01", "2026-10-05", "reblock:" + REF_REBLOCK,
          0, "roma", HOST_ROMA, "ospite6@example.com", "", CORPO_LEGACY,
          _ts(2026, 8, 25, 12), "pagato", 0, _ts(2026, 8, 25, 9), 0)),
    (_P, (REF_CANCELLATA, SLUG_ROMA, "2026-05-01", "2026-05-04", REF_CANCELLATA,
          800, "roma", HOST_ROMA, "ospite4@example.com", "", CORPO_LEGACY,
          _ts(2026, 4, 15), "cancellata_host", 0, _ts(2026, 3, 25), 0)),
    (_P, (REF_DOPPIONE, SLUG_ROMA, "2026-09-01", "2026-09-04", REF_DOPPIONE,
          0, "roma", HOST_ROMA, "ospite8@example.com", "", CORPO_LEGACY,
          _ts(2026, 8, 21, 10), "pagato", 0, _ts(2026, 8, 21, 9), 0)),
    (_P, (REF_SENZA_GEO, SLUG_SENZA_GEO, "2026-03-01", "2026-03-08", REF_SENZA_GEO,
          0, "roma", HOST_ROMA, "ospite9@example.com", "", CORPO_ARCAICO,
          _ts(2026, 2, 10, 11), "pagato", 0, _ts(2026, 2, 10, 10), 0)),
    # soggiorno a CAVALLO D'ANNO: 2 notti nel 2025, 2 nel 2026 (nessun movimento:
    # e' una riga rimasta sola, come capita agli archivi veri)
    (_P, (REF_CAVALLO_ANNO, SLUG_ROMA, "2025-12-30", "2026-01-03", REF_CAVALLO_ANNO,
          900, "roma", HOST_ROMA, "ospite5@example.com", "", CORPO_LEGACY,
          _ts(2025, 12, 20), "pagato", 0, _ts(2025, 12, 19), 0)),
    (_P, (REF_DA_RIMBORSARE, SLUG_ROMA, "2026-06-10", "2026-06-12", REF_DA_RIMBORSARE,
          0, "roma", HOST_ROMA, "ospite7@example.com", "", CORPO_LEGACY,
          _ts(2026, 6, 1), "da_rimborsare", 0, _ts(2026, 5, 20), 0)),
    # DATE INVERTITE (riparazione manuale andata male): il report deve saltarla
    (_P, (REF_DATE_INVERTITE, SLUG_ROMA, "2026-04-10", "2026-04-03",
          REF_DATE_INVERTITE, 0, "roma", HOST_ROMA, "ospite10@example.com", "", "",
          _ts(2026, 4, 1), "pagato", 0, _ts(2026, 3, 30), 0)),
    # DATA MALFORMATA (stringa vuota)
    (_P, (REF_DATA_VUOTA, SLUG_ROMA, "", "2026-04-20", REF_DATA_VUOTA,
          0, "roma", HOST_ROMA, "ospite11@example.com", "", "",
          _ts(2026, 4, 10), "pagato", 0, _ts(2026, 4, 9), 0)),
)

_PO = ("INSERT INTO payout (prenotazione_id, host_id, minori, valuta, stato, ts) "
       "VALUES (?,?,?,?,?,?)")

RIGHE_PAYOUT = (
    (_PO, (REF_PAGATA, HOST_ROMA, 15300, "EUR", "maturato", _ts(2026, 9, 4))),
    (_PO, (REF_REBLOCK, HOST_ROMA, 24000, "EUR", "pagato", _ts(2026, 10, 5))),
    (_PO, (REF_SENZA_GEO, HOST_ROMA, 0, "EUR", "in_transito", _ts(2026, 3, 8))),  # ZERO
    (_PO, (REF_ATTESA, HOST_ROMA, 5000, "EUR", "trattenuto", _ts(2026, 8, 23))),
    (_PO, (REF_CANCELLATA, HOST_ROMA, 3000, "EUR", "maturato", _ts(2026, 5, 4))),
    (_PO, (REF_JP, HOST_TOKYO, 47000, "JPY", "maturato", _ts(2026, 8, 2))),
    (_PO, (REF_ORFANO, HOST_CANCELLATO, 9000, "EUR", "maturato", _ts(2025, 7, 1))),
)

RIGHE_TASSA = (
    ("INSERT INTO tassa_regola (comune, regola_json) VALUES (?,?)",
     ("roma", json.dumps({"ppn_cents": 450, "max_notti": 10, "perc_bps": 0,
                          "cap_persona_cents": 0}))),
    # regola scritta male anni fa: NON e' JSON
    ("INSERT INTO tassa_regola (comune, regola_json) VALUES (?,?)",
     ("comune-rotto", "{ppn_cents: 300")),
    # JSON valido ma non un oggetto
    ("INSERT INTO tassa_regola (comune, regola_json) VALUES (?,?)",
     ("comune-lista", "[450, 10]")),
    ("INSERT INTO tassa_riscossione (prenotazione_id, comune, importo, ts, stornato) "
     "VALUES (?,?,?,?,?)", (REF_PAGATA, "roma", 1350, _ts(2026, 8, 20), 0)),
    ("INSERT INTO tassa_riscossione (prenotazione_id, comune, importo, ts, stornato) "
     "VALUES (?,?,?,?,?)", (REF_CAVALLO_ANNO, "roma", 900, _ts(2025, 12, 20), 0)),
    # TOMBSTONE di storno ODIERNO: importo azzerato, non va piu' versato al Comune
    ("INSERT INTO tassa_riscossione (prenotazione_id, comune, importo, ts, stornato) "
     "VALUES (?,?,?,?,?)", (REF_CANCELLATA, "", 0, _ts(2026, 4, 16), 1)),
    # TOMBSTONE VECCHIO: storno segnato col solo flag, l'importo e' rimasto scritto.
    # Vale il FLAG: contarlo vorrebbe dire versare al Comune una tassa restituita.
    ("INSERT INTO tassa_riscossione (prenotazione_id, comune, importo, ts, stornato) "
     "VALUES (?,?,?,?,?)", (REF_DA_RIMBORSARE, "roma", 1200, _ts(2026, 6, 2), 1)),
    ("INSERT INTO tassa_riscossione (prenotazione_id, comune, importo, ts, stornato) "
     "VALUES (?,?,?,?,?)", (REF_ATTESA, "firenze", 700, _ts(2026, 8, 22), 0)),
)

_G = ("INSERT INTO garanzia (prenotazione_id, alloggio_id, importo_host_cents, "
      "host_riceve_cents, ospite_rimborso_cents, stato, motivo, sblocco_auto_ts, "
      "aperto_ts, aggiornato_ts) VALUES (?,?,?,?,?,?,?,?,?,?)")

RIGHE_GARANZIA = (
    (_G, (REF_PAGATA, SLUG_ROMA, 15300, 0, 0, "in_garanzia", "",
          _ts(2026, 9, 2, 10), _ts(2026, 8, 20), _ts(2026, 8, 20))),
    (_G, (REF_CAVALLO_ANNO, SLUG_ROMA, 24000, 24000, 0, "rilasciato", "",
          _ts(2025, 12, 31), _ts(2025, 12, 30), _ts(2026, 1, 1))),
    (_G, (REF_CANCELLATA, SLUG_ROMA, 8000, 0, 0, "contestato",
          "riscaldamento non funzionante — l’host non risponde",
          _ts(2026, 5, 2), _ts(2026, 5, 1), _ts(2026, 5, 3))),
    (_G, (REF_DA_RIMBORSARE, SLUG_ROMA, 6000, 0, 0, "annullato", "",
          _ts(2026, 6, 11), _ts(2026, 6, 10), _ts(2026, 6, 10))),
    (_G, (REF_SENZA_GEO, SLUG_SENZA_GEO, 7900, 4900, 3000, "risolto",
          "rimborso parziale", _ts(2026, 3, 2), _ts(2026, 3, 1), _ts(2026, 3, 4))),
    # importo ZERO su un alloggio ORFANO, e sblocco gia' passato da mesi
    (_G, (REF_ORFANO, SLUG_SPARITO, 0, 0, 0, "in_garanzia", "",
          _ts(2025, 7, 2), _ts(2025, 7, 1), _ts(2025, 7, 1))),
)


DOC_SHA_FINTO = hashlib.sha256(b"contratto host - copia archiviata").hexdigest()
PRIVACY_SHA_FINTO = hashlib.sha256(b"informativa privacy - copia archiviata").hexdigest()


def _firma_accettazione(host_id, documento, versione, doc_sha, lang, ip, ua,
                        vessatorie, ts, riferimento=""):
    """Ricalcolo INDIPENDENTE della firma (formato documentato in fase163)."""
    canonico = "|".join([host_id, documento, versione, doc_sha, lang, ip, ua,
                         str(int(vessatorie)), str(int(ts))])
    if riferimento:
        canonico += "|" + str(riferimento)
    return hmac.new(SEGRETO, canonico.encode("utf-8"), hashlib.sha256).hexdigest()


def _righe_accettazioni():
    _AC = ("INSERT INTO accettazioni (id, host_id, documento, versione, doc_sha256, "
           "lang, ip, user_agent, vessatorie, accettato_ts, firma, riferimento) "
           "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)")
    voci = [
        # (id, host, documento, versione, doc_sha, lang, ip, ua, vex, ts, rif, manomessa)
        (1, HOST_ROMA, "contratto_host", CONTRATTO_VERSIONE_CORRENTE, DOC_SHA_FINTO,
         "it", "93.45.11.7", "Mozilla/5.0 (iPhone)", 1, _ts(2025, 11, 3, 10), "", False),
        (2, HOST_ROMA, "privacy_gdpr", PRIVACY_VERSIONE_CORRENTE, PRIVACY_SHA_FINTO,
         "it", "93.45.11.7", "Mozilla/5.0 (iPhone)", 0, _ts(2025, 11, 3, 10, 1),
         "", False),
        # riferimento esterno (sessione Stripe Identity): entra nella firma
        (3, HOST_ROMA, "identita_stripe", "1.0", DOC_SHA_FINTO,
         "it", "93.45.11.7", "Mozilla/5.0 (iPhone)", 0, _ts(2026, 1, 15, 9),
         "vs_1AbCdEfGhIjK", False),
        # host giapponese: contratto di una versione VECCHIA -> deve riaccettare
        (4, HOST_TOKYO, "contratto_host", CONTRATTO_VERSIONE_VECCHIA, DOC_SHA_FINTO,
         "ja", "203.0.113.9", "Mozilla/5.0 (Android)", 1, _ts(2025, 12, 19, 8),
         "", False),
        # riga MANOMESSA: la firma non torna
        (5, HOST_SOSPESO, "contratto_host", CONTRATTO_VERSIONE_CORRENTE, DOC_SHA_FINTO,
         "it", "10.0.0.1", "curl/8.4", 1, _ts(2026, 2, 2, 7), "", True),
    ]
    out = []
    for (id_, h, doc, ver, sha, lang, ip, ua, vex, ts, rif, rotta) in voci:
        firma = _firma_accettazione(h, doc, ver, sha, lang, ip, ua, vex, ts, rif)
        if rotta:
            firma = "0" * 64
        out.append((_AC, (id_, h, doc, ver, sha, lang, ip, ua, vex, ts, firma, rif)))
    return tuple(out)


# ── libro giornale: la catena si ricalcola QUI, secondo il formato documentato ──
GIORNALE = (
    # (evento_id, ts, tipo, riferimento, soggetto, dare, avere, importo, valuta, causale)
    ("incasso:" + REF_PAGATA, _ts(2026, 2, 10, 9), "incasso", REF_PAGATA,
     "host:" + HOST_ROMA, "cassa_piattaforma", "debiti_vs_host", 19850, "EUR",
     "incasso soggiorno"),
    ("tassa_incassata:" + REF_PAGATA, _ts(2026, 2, 10, 9, 1), "tassa_incassata",
     REF_PAGATA, "comune:roma", "cassa_piattaforma", "debiti_vs_comune", 1350, "EUR",
     "tassa di soggiorno"),
    ("commissione:" + REF_PAGATA, _ts(2026, 2, 10, 9, 2), "commissione", REF_PAGATA,
     "host:" + HOST_ROMA, "debiti_vs_host", "ricavi_commissioni", 1850, "EUR",
     "commissione netta"),
    ("payout_host:" + REF_PAGATA, _ts(2026, 2, 12, 9), "payout_host", REF_PAGATA,
     "host:" + HOST_ROMA, "debiti_vs_host", "cassa_piattaforma", 16650, "EUR",
     "bonifico host"),
    # prenotazione STORICA senza riga 'commissione' (formato pre-2026-07): la
    # commissione va dedotta dal bonifico
    ("incasso:" + REF_REBLOCK, _ts(2026, 5, 12, 10), "incasso", REF_REBLOCK,
     "host:" + HOST_ROMA, "cassa_piattaforma", "debiti_vs_host", 24900, "EUR",
     "incasso soggiorno"),
    ("tassa_incassata:" + REF_REBLOCK, _ts(2026, 5, 12, 10, 1), "tassa_incassata",
     REF_REBLOCK, "comune:roma", "cassa_piattaforma", "debiti_vs_comune", 900, "EUR",
     "tassa di soggiorno"),
    ("payout_host:" + REF_REBLOCK, _ts(2026, 5, 14, 10), "payout_host", REF_REBLOCK,
     "host:" + HOST_ROMA, "debiti_vs_host", "cassa_piattaforma", 22000, "EUR",
     "bonifico host"),
    # host giapponese, valuta diversa, terzo trimestre
    ("incasso:" + REF_JP, _ts(2026, 8, 1, 3), "incasso", REF_JP,
     "host:" + HOST_TOKYO, "cassa_piattaforma", "debiti_vs_host", 50000, "JPY",
     "incasso soggiorno"),
    ("commissione:" + REF_JP, _ts(2026, 8, 1, 3, 1), "commissione", REF_JP,
     "host:" + HOST_TOKYO, "debiti_vs_host", "ricavi_commissioni", 5000, "JPY",
     "commissione netta"),
    ("payout_host:" + REF_JP, _ts(2026, 8, 3, 3), "payout_host", REF_JP,
     "host:" + HOST_TOKYO, "debiti_vs_host", "cassa_piattaforma", 45000, "JPY",
     "bonifico host"),
    # rimborso SENZA incasso registrato (prenotazione nata prima del giornale)
    ("rimborso:" + REF_DA_RIMBORSARE, _ts(2026, 6, 1, 11), "rimborso",
     REF_DA_RIMBORSARE, "ospite:ospite7@example.com", "debiti_vs_ospite",
     "cassa_piattaforma", 12000, "EUR", "rimborso integrale"),
    # nota di credito su una cancellazione host
    ("nota:credito:" + REF_CANCELLATA, _ts(2026, 6, 15, 8), "nota_credito",
     REF_CANCELLATA, "host:" + HOST_ROMA, "costi_rimborsi", "debiti_vs_soggetto",
     3000, "EUR", "nota di credito per cancellazione host"),
    # ANNO PRECEDENTE: non deve entrare nel report 2026
    ("incasso:" + REF_ANNO_PRIMA, _ts(2025, 7, 1, 9), "incasso", REF_ANNO_PRIMA,
     "host:" + HOST_ROMA, "cassa_piattaforma", "debiti_vs_host", 10000, "EUR",
     "incasso soggiorno"),
    ("payout_host:" + REF_ANNO_PRIMA, _ts(2025, 7, 3, 9), "payout_host",
     REF_ANNO_PRIMA, "host:" + HOST_ROMA, "debiti_vs_host", "cassa_piattaforma",
     9000, "EUR", "bonifico host"),
)

EMITTENTE = "sistema"


def _righe_giornale():
    sql = ("INSERT INTO libro_giornale (seq, evento_id, ts, tipo, riferimento, soggetto, "
           "conto_dare, conto_avere, importo_cents, valuta, causale, emittente, "
           "prev_hash, hash) VALUES (" + ",".join("?" * 14) + ")")
    out = []
    prev = "GENESI"
    for seq, (ev, ts, tipo, rif, sog, dare, avere, imp, val, causale) in enumerate(
            GIORNALE, start=1):
        canonico = "|".join([ev, str(ts), tipo, rif, sog, dare, avere, str(imp), val,
                             causale, EMITTENTE, prev])
        h = hashlib.sha256(canonico.encode("utf-8")).hexdigest()
        out.append((sql, (seq, ev, ts, tipo, rif, sog, dare, avere, imp, val, causale,
                          EMITTENTE, prev, h)))
        prev = h
    return tuple(out)


SEQ_NOTA_CREDITO = [i for i, g in enumerate(GIORNALE, start=1)
                    if g[0] == "nota:credito:" + REF_CANCELLATA][0]

RIGHE_NOTE = (
    ("INSERT INTO note (nota_id, tipo, riferimento, causale, ts, emittente, soggetto, "
     "importo_cents, valuta, stato, storno_di, giornale_seq) "
     "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
     ("NC-2026-000001", "credito", REF_CANCELLATA, "cancellazione host",
      _ts(2026, 6, 15, 8), "admin", "host:" + HOST_ROMA, 3000, "EUR", "emessa", None,
      SEQ_NOTA_CREDITO)),
)

RIGHE_DEBITI = (
    # prossimo_ts NULL (colonna nullable): il codice lo legge come intero
    ("INSERT INTO debiti (debito_id, host_id, riferimento, residuo_cents, valuta, "
     "stato, tentativi, prossimo_ts, aggiornato_ts) VALUES (?,?,?,?,?,?,?,?,?)",
     ("DBT-0001", HOST_ROMA, REF_CANCELLATA, 3000, "EUR", "aperto", 0, None,
      _ts(2026, 6, 15, 9))),
    ("INSERT INTO debiti (debito_id, host_id, riferimento, residuo_cents, valuta, "
     "stato, tentativi, prossimo_ts, aggiornato_ts) VALUES (?,?,?,?,?,?,?,?,?)",
     ("DBT-0002", HOST_ROMA, REF_ATTESA, 0, "EUR", "saldato", 3, _ts(2026, 7, 1),
      _ts(2026, 7, 1))),
    ("INSERT INTO debiti (debito_id, host_id, riferimento, residuo_cents, valuta, "
     "stato, tentativi, prossimo_ts, aggiornato_ts) VALUES (?,?,?,?,?,?,?,?,?)",
     ("DBT-0003", HOST_TOKYO, REF_JP, 1200, "JPY", "aperto", 1, _ts(2026, 9, 1),
      _ts(2026, 8, 20))),
)

_R = ("INSERT INTO recensioni (prenotazione_id, alloggio_id, voto, testo, lingua, "
      "verificata, ts, cat_pulizia, cat_comfort, cat_posizione, cat_servizi, cat_host, "
      "cat_qualita_prezzo) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)")

RIGHE_RECENSIONI = (
    (_R, (REF_PAGATA, SLUG_ROMA, 5,
          "Vista pazzesca \U0001f60d, l’host è gentilissimo. Torneremo!",
          "it", 1, "2026-09-06T10:00:00", 5, 5, None, None, None, None)),
    (_R, (REF_CAVALLO_ANNO, SLUG_ROMA, 4, "Bene, ma il riscaldamento faceva rumore.",
          "it", 1, "2026-01-05T09:00:00", 4, None, None, None, None, None)),
    (_R, (REF_DOPPIONE, SLUG_ROMA, 5, "", "en", 1, "2026-03-10T09:00:00",
          None, None, None, None, None, None)),
    # NON verificata: fuori da conteggi e medie
    (_R, ("IDEM-FAKE-0001", SLUG_ROMA, 1, "Pessimo!!!", "it", 0,
          "2026-09-07T10:00:00", 1, 1, 1, 1, 1, 1)),
    # ORFANA: l'annuncio non esiste piu'
    (_R, (REF_ORFANO, SLUG_SPARITO, 3, "Nella media.", "en", 1,
          "2026-07-10T09:00:00", None, None, None, None, None, None)),
)

HOST_DAC7_PARZIALE = "h_vecchio_2024"     # record scritto da una versione precedente
HOST_DAC7_ROTTO = "h_rotto_0005"          # record che non e' nemmeno un oggetto

DAC7_JSON = {
    HOST_ROMA: {"pren": 42, "ricavi": 250000, "dati": True},
    HOST_TOKYO: {"pren": 3, "ricavi": 50000, "dati": False},
    HOST_SOSPESO: {"pren": 0, "ricavi": 0, "dati": False},
    # FORMA VECCHIA: mancano 'ricavi' e 'dati' (il contatore nacque con la sola conta)
    HOST_DAC7_PARZIALE: {"pren": 5},
    # riparazione a mano finita male: al posto del record c'e' una stringa
    HOST_DAC7_ROTTO: "5 prenotazioni",
}


# ═══════════════════════════════════════════════════════════════════════════
# COSTRUZIONE
# ═══════════════════════════════════════════════════════════════════════════
def _scrivi(percorso, ddl, righe):
    con = sqlite3.connect(percorso)
    try:
        with con:
            for istruzione in ddl:
                con.execute(istruzione)
            for sql, parametri in righe:
                con.execute(sql, parametri)
    finally:
        con.close()


def costruisci_corpus(cartella):
    """Scrive l'intero corpus in `cartella` e ritorna {nome: percorso}."""
    p = lambda n: os.path.join(cartella, n)      # noqa: E731
    _scrivi(p("catalogo.db"), DDL_CATALOGO, RIGHE_CATALOGO)
    _scrivi(p("inventario.db"), DDL_INVENTARIO, RIGHE_INVENTARIO + RIGHE_MOVIMENTI)
    _scrivi(p("registro_host.db"), DDL_REGISTRO_HOST, _righe_host())
    _scrivi(p("pendenti.db"), DDL_PENDENTI, RIGHE_PENDENTI)
    _scrivi(p("payout.db"), DDL_PAYOUT, RIGHE_PAYOUT)
    _scrivi(p("tassa.db"), DDL_TASSA, RIGHE_TASSA)
    _scrivi(p("garanzia.db"), DDL_GARANZIA, RIGHE_GARANZIA)
    _scrivi(p("accettazioni.db"), DDL_ACCETTAZIONI, _righe_accettazioni())
    _scrivi(p("finanza.db"), DDL_FINANZA,
            _righe_giornale() + RIGHE_NOTE + RIGHE_DEBITI)
    _scrivi(p("recensioni.db"), DDL_RECENSIONI, RIGHE_RECENSIONI)
    with open(p("dac7.json"), "w", encoding="utf-8") as f:
        json.dump(DAC7_JSON, f)
    return {"catalogo": p("catalogo.db"), "inventario": p("inventario.db"),
            "registro_host": p("registro_host.db"), "pendenti": p("pendenti.db"),
            "payout": p("payout.db"), "tassa": p("tassa.db"),
            "garanzia": p("garanzia.db"), "accettazioni": p("accettazioni.db"),
            "finanza": p("finanza.db"), "recensioni": p("recensioni.db"),
            "dac7": p("dac7.json")}


def conta_righe(percorso, tabella):
    """Conteggio grezzo, per le controprove del collaudo."""
    con = sqlite3.connect(percorso)
    try:
        # nome di tabella da costante di questo file, mai da input esterno
        return int(con.execute("SELECT COUNT(*) FROM %s" % tabella).fetchone()[0])  # noqa: S608
    finally:
        con.close()
