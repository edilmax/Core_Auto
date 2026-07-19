"""
CORE_AUTO - Fase 57: Vetrina / Catalogo pubblico (lo storefront che mancava).

Il pezzo che il cliente VEDE: la "vetrina" dove sfoglia gli alloggi (foto, prezzo,
servizi), filtra/cerca e da cui parte la prenotazione. Finora il prodotto aveva solo
API dirette, l'agente chat e il pannello admin: nessun catalogo navigabile come le OTA.
Questo modulo costruisce il READ-MODEL del catalogo (lista schede + dettaglio) che una
web-app/app frontend consuma via contratti JSON, e che si aggancia al motore booking
(fase34) per la disponibilita' reale. Vetrina migliore delle OTA perche' gestita in
automatico (zero dipendenti): commissione minore, stesso o miglior livello di vetrina.

SEPARAZIONE READ/WRITE (perche' un datastore dedicato al catalogo):
  Il catalogo e' read-heavy (mille sfogliate per una prenotazione); il motore
  prenotazioni (fase34) e' write-critical (transazioni atomiche sul denaro). Tenerli
  in tabelle/connessioni separate evita che lo sfoglio della vetrina contenda i lock
  delle transazioni di pagamento. La chiave `alloggio_id` e' condivisa: la vetrina
  MOSTRA, il motore PRENOTA. La vetrina NON tocca mai il denaro.

SCHEMA VINCITORE (benchmark 4 varianti x 10 stress, filtri AND su catalogo grande):
  V3 'tabella alloggi + tabella immagini + servizi come BITMASK INTERA + indici su
  (stato,citta) e (stato,prezzo)'. Il filtro "AND di servizi" diventa una singola
  operazione intera `(servizi_mask & richiesti) = richiesti` (indicizzabile,
  deterministica, zero parsing), il prezzo e' int filtrabile per range, le immagini
  stanno in una tabella ordinata (1:N) col thumbnail via subquery O(1).
  Le altre 3 perdono:
    - V1 blob-JSON: ogni filtro = parse Python per riga (lento, non indicizzabile);
    - V2 servizi come stringa CSV + LIKE: un LIKE per ogni servizio richiesto (scan
      multipli, falsi positivi su sottostringhe);
    - V4 servizi in tabella M:N: join+GROUP BY+HAVING per un semplice AND (overkill,
      piu' lento del bitmask sul caso reale "ha tutti questi servizi").

DENARO: prezzi SOLO in centesimi INTERI (`*_cents: int`). Float, bool e stringhe
numeriche RIFIUTATI in ingresso (come fase56). Geo in MICROGRADI interi (lat*1e6),
mai float nello storage. La valuta e' solo un'etichetta.

SOPRAVVIVENZA TOTALE:
  - validatore BLINDATO che NON solleva mai (come fase56): input corrotto -> rifiutato;
  - fail-closed: solo lo stato 'pubblicato' compare in vetrina (bozza/sospeso nascosti);
  - durevolezza/concorrenza come fase34/52: conn-per-operazione, WAL, BEGIN IMMEDIATE,
    schema idempotente (CREATE IF NOT EXISTS);
  - provider di disponibilita' INIETTABILE e ISOLATO: se il motore booking solleva o
    manca, la scheda degrada (disponibile=None "ignoto"), la vetrina non si schianta;
  - paginazione con tetto (anti-DoS), ordinamento deterministico.
"""
from __future__ import annotations

import datetime
import logging
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("core_auto.vetrina")

LIMITE_TESTO = 4000
LIMITE_CAMPO = 256
SLUG_MAX = 60                     # slug pubblico: identificatore in URL, corto e SOLO [a-z0-9-]
MAX_CENTS = 1_000_000_00          # 1.000.000 unita' valuta: tetto anti-abuso
PAGINA_MAX = 100                  # tetto risultati per pagina (anti-DoS)
PAGINA_DEFAULT = 24
STATI_VALIDI = ("bozza", "pubblicato", "sospeso")

# Registro servizi -> bit (bitmask intera). Aggiungere in coda (mai riusare un bit).
SERVIZI: Dict[str, int] = {
    "wifi": 1 << 0,
    "parcheggio": 1 << 1,
    "piscina": 1 << 2,
    "aria_condizionata": 1 << 3,
    "cucina": 1 << 4,
    "lavatrice": 1 << 5,
    "animali_ammessi": 1 << 6,
    "colazione": 1 << 7,
    "vista_mare": 1 << 8,
    "parcheggio_disabili": 1 << 9,
    "check_in_24h": 1 << 10,
    "riscaldamento": 1 << 11,
}


def maschera_servizi(servizi: Sequence[str]) -> int:
    """Codici servizio -> bitmask intera. Codici ignoti IGNORATI (fail-safe)."""
    m = 0
    for s in servizi or ():
        bit = SERVIZI.get(str(s).strip().lower())
        if bit:
            m |= bit
    return m


def servizi_da_maschera(mask: int) -> List[str]:
    """Bitmask -> lista codici (ordine stabile = ordine del registro)."""
    if not isinstance(mask, int) or isinstance(mask, bool) or mask < 0:
        return []
    return [nome for nome, bit in SERVIZI.items() if mask & bit]


# ─────────────────────────────────────────────────────────────────────────────
# Record / contratti
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Immagine:
    url: str
    ordine: int = 0
    alt: str = ""


@dataclass(frozen=True)
class SchedaAlloggio:
    host_id: str
    slug: str                     # identificatore pubblico stabile (URL della scheda)
    titolo: str
    citta: str
    prezzo_notte_cents: int
    capacita: int
    descrizione: str = ""
    paese: str = ""
    cin: str = ""                 # Codice Identificativo Nazionale (obbligo annunci IT), PUBBLICO
    indirizzo: str = ""           # via+civico (PRIVATO: solo per geocodifica precisa, mai pubblico)
    camere: int = 1
    bagni: int = 1
    servizi: Tuple[str, ...] = ()
    valuta: str = "EUR"
    stato: str = "pubblicato"
    lat_micro: Optional[int] = None   # microgradi interi (lat*1e6), mai float
    lon_micro: Optional[int] = None
    politica_cancellazione: str = "flessibile"   # scelta dall'host per QUESTO alloggio
    tassa_pp_notte_cents: int = 0      # tassa di soggiorno per persona/notte (l'host la dichiara)
    tassa_max_notti: int = 0           # notti massime tassabili (0 = nessun cap)
    tassa_perc_bps: int = 0            # % sul prezzo (alcune nazioni; alternativa al per-persona)
    sconto_settimana_bps: int = 0      # sconto soggiorno >=7 notti (bps; l'host lo offre)
    sconto_mese_bps: int = 0           # sconto soggiorno >=28 notti (bps; prevale su settimana)
    modalita_prenotazione: str = "immediata"   # immediata | su_richiesta (l'host sceglie)
    pin_manuale: bool = False          # True = posizione FISSATA dall'host sulla mappa
                                       # (trascinando il pin): vince sulla geocodifica


# Politiche di cancellazione che l'host puo' scegliere (coerenti con fase111).
POLITICHE_CANCELLAZIONE = ("flessibile", "moderata", "rigida", "non_rimborsabile")
MODALITA_PRENOTAZIONE = ("immediata", "su_richiesta")


@dataclass(frozen=True)
class CriteriRicerca:
    citta: Optional[str] = None
    prezzo_min_cents: Optional[int] = None
    prezzo_max_cents: Optional[int] = None
    capacita_min: Optional[int] = None
    servizi: Tuple[str, ...] = ()
    bbox: Optional[Tuple[int, int, int, int]] = None   # (lat_min,lat_max,lon_min,lon_max) microgradi
    ordine: str = "recente"       # 'recente' | 'prezzo_asc' | 'prezzo_desc'
    limit: int = PAGINA_DEFAULT
    offset: int = 0
    check_in: Optional[str] = None    # se presenti + provider -> annota disponibilita'
    check_out: Optional[str] = None


def _intero(v: Any) -> bool:
    """int puro: niente bool, niente float (anche 10.0), niente stringa numerica."""
    return isinstance(v, int) and not isinstance(v, bool)


def _stringa(v: Any, limite: int) -> Optional[str]:
    if not isinstance(v, str):
        return None
    v = v.strip()
    if not v or len(v) > limite:
        return None
    return v


def _norm_slug(v: Any) -> Optional[str]:
    """Slug PUBBLICO ripulito: SOLO [a-z0-9-]. None se dopo la pulizia non resta nulla.

    SICUREZZA (bug trovato in collaudo 2026-07-15): lo slug e' un identificatore che finisce
    negli URL E dentro l'HTML/JS del frontend — `onclick="apri('<slug>')"` nel popup mappa e
    `data-slug="<slug>"` nelle card. Prima era validato solo come stringa non vuota: un host
    poteva pubblicare via API uno slug tipo `x');alert(1);//` o `a" onmouseover=alert(1) x="`
    (XSS STORED contro gli ospiti) oppure `../../etc/passwd` (traversal). Qui si taglia alla
    radice: nessun apice/segno/punto puo' entrare nel catalogo.

    NORMALIZZA invece di rifiutare, ed e' DETERMINISTICA (stesso input -> stesso slug): gli
    import (fase77 usa gli id esterni property_id/listing_id) restano stabili e il dedup per
    slug continua a funzionare.

    ⚠️ NON abbassa il case (niente `.lower()`): lo slug e' un'IDENTITA'. Cambiare 'casa-R' in
    'casa-r' significa salvare un annuncio a un indirizzo diverso da quello che il chiamante
    conosce -> lui poi lo cerca con l'originale e non lo trova piu'. (Regressione vera, presa
    dalla suite: le simulazioni pubblicano 'casa-R'/'casa-refB' e poi prenotano con lo stesso
    nome; col `.lower()` le prenotazioni non maturavano e saltava il premio referral.) Qui il
    fine e' TOGLIERE i caratteri pericolosi, non uniformare lo stile: il minuscolo lo applica
    `fase83._slug_unico`, che GENERA slug nuovi (li' non c'e' identita' preesistente da rompere).
    """
    s = _stringa(v, LIMITE_CAMPO)
    if s is None:
        return None
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-")[:SLUG_MAX]
    return s or None


def valida_scheda(data: Any) -> Tuple[bool, str, Optional[SchedaAlloggio]]:
    """Validatore BLINDATO (non solleva MAI). Denaro SOLO int cents; geo solo int."""
    if not isinstance(data, dict):
        return False, "payload_non_oggetto", None

    host_id = _stringa(data.get("host_id"), LIMITE_CAMPO)
    if host_id is None:
        return False, "host_id_non_valido", None
    slug = _norm_slug(data.get("slug"))          # SOLO [a-z0-9-]: anti-XSS/traversal (vedi _norm_slug)
    if slug is None:
        return False, "slug_non_valido", None
    titolo = _stringa(data.get("titolo"), LIMITE_CAMPO)
    if titolo is None:
        return False, "titolo_non_valido", None
    citta = _stringa(data.get("citta"), LIMITE_CAMPO)
    if citta is None:
        return False, "citta_non_valida", None

    prezzo = data.get("prezzo_notte_cents")
    if not _intero(prezzo):
        return False, "prezzo_non_intero", None
    if prezzo <= 0:
        return False, "prezzo_nullo", None
    if prezzo > MAX_CENTS:
        return False, "prezzo_oltre_tetto", None

    for nome in ("capacita", "camere", "bagni"):
        v = data.get(nome, 1 if nome != "capacita" else None)
        if nome == "capacita" and v is None:
            return False, "capacita_mancante", None
        if not _intero(v) or v < 0 or v > 10000:
            return False, f"{nome}_non_valido", None

    stato = data.get("stato", "pubblicato")
    if stato not in STATI_VALIDI:
        return False, "stato_non_valido", None

    descr = data.get("descrizione", "")
    if not isinstance(descr, str) or len(descr) > LIMITE_TESTO:
        return False, "descrizione_non_valida", None
    paese = data.get("paese", "")
    if not isinstance(paese, str) or len(paese) > LIMITE_CAMPO:
        return False, "paese_non_valido", None
    # CIN (Codice Identificativo Nazionale, obbligo IT dal 20/05/2026 — Reg. UE 2024/1028):
    # qui SOLO il formato (opzionale, alfanumerico maiuscolo); l'OBBLIGO per gli annunci
    # italiani è policy del marketplace (fase83), il motore resta neutro per giurisdizione.
    cin = data.get("cin", "")
    if not isinstance(cin, str):
        return False, "cin_non_valido", None
    cin = cin.strip().upper()
    if cin and not (6 <= len(cin) <= 30 and cin.isalnum()):
        return False, "cin_non_valido", None
    indirizzo = data.get("indirizzo", "")
    if not isinstance(indirizzo, str) or len(indirizzo) > LIMITE_CAMPO:
        return False, "indirizzo_non_valido", None
    valuta = data.get("valuta", "EUR")
    if not isinstance(valuta, str) or not (1 <= len(valuta) <= 8):
        return False, "valuta_non_valida", None

    servizi_in = data.get("servizi", ())
    if not isinstance(servizi_in, (list, tuple)):
        return False, "servizi_non_lista", None
    servizi = tuple(s for s in servizi_in if isinstance(s, str))

    lat = data.get("lat_micro")
    lon = data.get("lon_micro")
    for g, nome in ((lat, "lat_micro"), (lon, "lon_micro")):
        if g is not None and not _intero(g):
            return False, f"{nome}_non_intero", None
    if lat is not None and not (-90_000_000 <= lat <= 90_000_000):
        return False, "lat_micro_fuori_range", None
    if lon is not None and not (-180_000_000 <= lon <= 180_000_000):
        return False, "lon_micro_fuori_range", None

    pol = data.get("politica_cancellazione", "flessibile")
    if not isinstance(pol, str) or pol not in POLITICHE_CANCELLAZIONE:
        pol = "flessibile"

    def _tax(nome: str, tetto: int) -> int:
        x = data.get(nome, 0)
        return x if (_intero(x) and 0 <= x <= tetto) else 0
    t_pp = _tax("tassa_pp_notte_cents", MAX_CENTS)
    t_max = _tax("tassa_max_notti", 366)
    t_perc = _tax("tassa_perc_bps", 10000)
    sc_sett = _tax("sconto_settimana_bps", 9000)   # max 90% (guardia anti-errore)
    sc_mese = _tax("sconto_mese_bps", 9000)
    modal = data.get("modalita_prenotazione", "immediata")
    if not isinstance(modal, str) or modal not in MODALITA_PRENOTAZIONE:
        modal = "immediata"

    return True, "", SchedaAlloggio(
        host_id=host_id, slug=slug, titolo=titolo, citta=citta,
        prezzo_notte_cents=prezzo, capacita=int(data["capacita"]),
        descrizione=descr.strip(), paese=paese.strip(), cin=cin, indirizzo=indirizzo.strip(),
        camere=int(data.get("camere", 1)), bagni=int(data.get("bagni", 1)),
        servizi=servizi, valuta=valuta, stato=stato,
        lat_micro=lat, lon_micro=lon, politica_cancellazione=pol,
        tassa_pp_notte_cents=t_pp, tassa_max_notti=t_max, tassa_perc_bps=t_perc,
        sconto_settimana_bps=sc_sett, sconto_mese_bps=sc_mese,
        modalita_prenotazione=modal,
        pin_manuale=bool(data.get("pin_manuale", False)))


def _valida_immagini(imgs: Any) -> List[Immagine]:
    """Normalizza/filtra le immagini (fail-safe: url non validi SCARTATI)."""
    out: List[Immagine] = []
    for i, raw in enumerate(imgs or ()):
        if isinstance(raw, Immagine):
            url, ordine, alt = raw.url, raw.ordine, raw.alt
        elif isinstance(raw, dict):
            url, ordine, alt = raw.get("url"), raw.get("ordine", i), raw.get("alt", "")
        else:
            continue
        url = _stringa(url, LIMITE_CAMPO * 4)
        # ok: assoluti http(s) E i NOSTRI upload relativi (/uploads/<nome>, path-safe a monte)
        if url is None or not (url.startswith("http://") or url.startswith("https://")
                               or url.startswith("/uploads/")):
            continue
        if len(out) >= 30:                 # tetto professionale (come i colossi): max 30 foto
            break
        if not _intero(ordine):
            ordine = i
        alt = alt.strip()[:LIMITE_CAMPO] if isinstance(alt, str) else ""
        out.append(Immagine(url=url, ordine=ordine, alt=alt))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Catalogo durevole (SQLite, conn-per-operazione + WAL, come fase34/52)
# ─────────────────────────────────────────────────────────────────────────────
class CatalogoVetrina:
    """Read-model del catalogo: pubblicazione (write) + ricerca/dettaglio (read).
    `disponibilita`: callable iniettabile e ISOLATO (alloggio_id,check_in,check_out)
    -> Optional[bool]; se manca o solleva, la scheda degrada a 'ignoto'."""

    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], *,
                 disponibilita: Optional[Callable[[int, str, str], Optional[bool]]] = None
                 ) -> None:
        self._conn_factory = conn_factory
        self._disp = disponibilita
        self.inizializza_schema()

    def _apri(self) -> sqlite3.Connection:
        con = self._conn_factory()
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass
        return con

    def inizializza_schema(self) -> None:
        con = self._apri()
        try:
            with con:
                con.execute("""
                    CREATE TABLE IF NOT EXISTS alloggi (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        host_id TEXT NOT NULL,
                        slug TEXT NOT NULL UNIQUE,
                        titolo TEXT NOT NULL,
                        descrizione TEXT NOT NULL DEFAULT '',
                        citta TEXT NOT NULL,
                        paese TEXT NOT NULL DEFAULT '',
                        indirizzo TEXT NOT NULL DEFAULT '',
                        prezzo_notte_cents INTEGER NOT NULL,
                        capacita INTEGER NOT NULL,
                        camere INTEGER NOT NULL DEFAULT 1,
                        bagni INTEGER NOT NULL DEFAULT 1,
                        servizi_mask INTEGER NOT NULL DEFAULT 0,
                        valuta TEXT NOT NULL DEFAULT 'EUR',
                        stato TEXT NOT NULL DEFAULT 'pubblicato',
                        lat_micro INTEGER,
                        lon_micro INTEGER,
                        politica_cancellazione TEXT NOT NULL DEFAULT 'flessibile',
                        tassa_pp_notte_cents INTEGER NOT NULL DEFAULT 0,
                        tassa_max_notti INTEGER NOT NULL DEFAULT 0,
                        tassa_perc_bps INTEGER NOT NULL DEFAULT 0,
                        sconto_settimana_bps INTEGER NOT NULL DEFAULT 0,
                        sconto_mese_bps INTEGER NOT NULL DEFAULT 0,
                        modalita_prenotazione TEXT NOT NULL DEFAULT 'immediata',
                        pin_manuale INTEGER NOT NULL DEFAULT 0,
                        creato_ts TEXT NOT NULL,
                        aggiornato_ts TEXT NOT NULL)""")
                for _c, _d in (("politica_cancellazione", "TEXT NOT NULL DEFAULT 'flessibile'"),
                               ("tassa_pp_notte_cents", "INTEGER NOT NULL DEFAULT 0"),
                               ("tassa_max_notti", "INTEGER NOT NULL DEFAULT 0"),
                               ("tassa_perc_bps", "INTEGER NOT NULL DEFAULT 0"),
                               ("indirizzo", "TEXT NOT NULL DEFAULT ''"),
                               ("sconto_settimana_bps", "INTEGER NOT NULL DEFAULT 0"),
                               ("sconto_mese_bps", "INTEGER NOT NULL DEFAULT 0"),
                               ("modalita_prenotazione", "TEXT NOT NULL DEFAULT 'immediata'"),
                               ("pin_manuale", "INTEGER NOT NULL DEFAULT 0"),
                               ("cin", "TEXT NOT NULL DEFAULT ''")):
                    try:
                        con.execute("ALTER TABLE alloggi ADD COLUMN %s %s" % (_c, _d))
                    except sqlite3.OperationalError:
                        pass
                con.execute("""
                    CREATE TABLE IF NOT EXISTS alloggio_immagini (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        alloggio_id INTEGER NOT NULL,
                        url TEXT NOT NULL,
                        ordine INTEGER NOT NULL DEFAULT 0,
                        alt TEXT NOT NULL DEFAULT '',
                        FOREIGN KEY (alloggio_id) REFERENCES alloggi(id) ON DELETE CASCADE)""")
                con.execute("CREATE INDEX IF NOT EXISTS idx_alloggi_stato_citta "
                            "ON alloggi(stato, citta)")
                con.execute("CREATE INDEX IF NOT EXISTS idx_alloggi_stato_prezzo "
                            "ON alloggi(stato, prezzo_notte_cents)")
                # Field admin paginato (fase83): filtro per host_id / (stato,aggiornato).
                con.execute("CREATE INDEX IF NOT EXISTS idx_alloggi_host "
                            "ON alloggi(host_id)")
                con.execute("CREATE INDEX IF NOT EXISTS idx_alloggi_stato_agg "
                            "ON alloggi(stato, aggiornato_ts)")
                con.execute("CREATE INDEX IF NOT EXISTS idx_img_alloggio "
                            "ON alloggio_immagini(alloggio_id, ordine)")
        finally:
            con.close()

    def nomi_uploads(self) -> set:
        """Basename dei file /uploads/ citati dalle immagini di TUTTI gli annunci (ogni
        stato, anche sospesi). Per la pulizia orfani: SOLLEVA su errore DB — il chiamante
        e' fail-closed (senza censimento completo NON si cancella nulla)."""
        import re as _re
        con = self._apri()
        try:
            rows = con.execute("SELECT url FROM alloggio_immagini "
                               "WHERE url LIKE '%/uploads/%'").fetchall()
            out: set = set()
            for (u,) in rows:
                out.update(_re.findall(r"/uploads/([A-Za-z0-9_.\-]+)", str(u)))
            return out
        finally:
            con.close()

    # --- WRITE: pubblicazione idempotente (upsert per slug + replace immagini) ---
    def pubblica(self, scheda: SchedaAlloggio, immagini: Any = ()) -> int:
        """Upsert per `slug` (idempotente) + sostituzione atomica delle immagini.
        Ritorna l'id dell'alloggio. Atomico in BEGIN IMMEDIATE."""
        mask = maschera_servizi(scheda.servizi)
        imgs = _valida_immagini(immagini)
        ora = datetime.datetime.now().isoformat(timespec="seconds")
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT id, creato_ts FROM alloggi WHERE slug=?",
                              (scheda.slug,)).fetchone()
            if row is None:
                cur = con.execute(
                    "INSERT INTO alloggi (host_id, slug, titolo, descrizione, citta, "
                    "paese, cin, indirizzo, prezzo_notte_cents, capacita, camere, bagni, servizi_mask, "
                    "valuta, stato, lat_micro, lon_micro, politica_cancellazione, "
                    "tassa_pp_notte_cents, tassa_max_notti, tassa_perc_bps, "
                    "sconto_settimana_bps, sconto_mese_bps, "
                    "modalita_prenotazione, pin_manuale, creato_ts, aggiornato_ts) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (scheda.host_id, scheda.slug, scheda.titolo, scheda.descrizione,
                     scheda.citta, scheda.paese, scheda.cin, scheda.indirizzo, scheda.prezzo_notte_cents,
                     scheda.capacita, scheda.camere, scheda.bagni, mask, scheda.valuta,
                     scheda.stato, scheda.lat_micro, scheda.lon_micro,
                     scheda.politica_cancellazione, scheda.tassa_pp_notte_cents,
                     scheda.tassa_max_notti, scheda.tassa_perc_bps,
                     scheda.sconto_settimana_bps, scheda.sconto_mese_bps,
                     scheda.modalita_prenotazione, 1 if scheda.pin_manuale else 0,
                     ora, ora))
                alloggio_id = cur.lastrowid
            else:
                alloggio_id = row["id"]
                con.execute(
                    "UPDATE alloggi SET host_id=?, titolo=?, descrizione=?, citta=?, "
                    "paese=?, cin=?, indirizzo=?, prezzo_notte_cents=?, capacita=?, camere=?, bagni=?, "
                    "servizi_mask=?, valuta=?, stato=?, lat_micro=?, lon_micro=?, "
                    "politica_cancellazione=?, tassa_pp_notte_cents=?, tassa_max_notti=?, "
                    "tassa_perc_bps=?, sconto_settimana_bps=?, sconto_mese_bps=?, "
                    "modalita_prenotazione=?, pin_manuale=?, aggiornato_ts=? WHERE id=?",
                    (scheda.host_id, scheda.titolo, scheda.descrizione, scheda.citta,
                     scheda.paese, scheda.cin, scheda.indirizzo, scheda.prezzo_notte_cents, scheda.capacita,
                     scheda.camere, scheda.bagni, mask, scheda.valuta, scheda.stato,
                     scheda.lat_micro, scheda.lon_micro, scheda.politica_cancellazione,
                     scheda.tassa_pp_notte_cents, scheda.tassa_max_notti, scheda.tassa_perc_bps,
                     scheda.sconto_settimana_bps, scheda.sconto_mese_bps,
                     scheda.modalita_prenotazione, 1 if scheda.pin_manuale else 0,
                     ora, alloggio_id))
            con.execute("DELETE FROM alloggio_immagini WHERE alloggio_id=?", (alloggio_id,))
            if imgs:
                con.executemany(
                    "INSERT INTO alloggio_immagini (alloggio_id, url, ordine, alt) "
                    "VALUES (?,?,?,?)",
                    [(alloggio_id, im.url, im.ordine, im.alt) for im in imgs])
            con.execute("COMMIT")
            return alloggio_id
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    def imposta_stato(self, slug: str, stato: str) -> bool:
        """Pubblica/sospende/ritira una scheda (fail-closed su stato ignoto)."""
        if stato not in STATI_VALIDI:
            return False
        ora = datetime.datetime.now().isoformat(timespec="seconds")
        con = self._apri()
        try:
            with con:
                cur = con.execute("UPDATE alloggi SET stato=?, aggiornato_ts=? WHERE slug=?",
                                  (stato, ora, slug))
            return cur.rowcount > 0
        finally:
            con.close()

    def modalita_prenotazione_di(self, slug: Any) -> str:
        """immediata (default) | su_richiesta — scelta dall'host per l'alloggio."""
        if not (isinstance(slug, str) and slug):
            return "immediata"
        con = self._apri()
        try:
            r = con.execute("SELECT modalita_prenotazione FROM alloggi WHERE slug=?",
                            (slug,)).fetchone()
        finally:
            con.close()
        if r is None:
            return "immediata"
        m = r["modalita_prenotazione"] if "modalita_prenotazione" in r.keys() else None
        return m if m in MODALITA_PRENOTAZIONE else "immediata"

    def regola_tassa_di(self, slug: Any) -> Any:
        """Regola di tassa di soggiorno dichiarata dall'host per l'alloggio (fase66.RegolaTassa).
        Citta'/alloggio senza regola dichiarata -> REGOLA_ZERO (tassa 0, mai inventare)."""
        from fase66_tassa_soggiorno import RegolaTassa, REGOLA_ZERO
        if not (isinstance(slug, str) and slug):
            return REGOLA_ZERO
        con = self._apri()
        try:
            r = con.execute("SELECT tassa_pp_notte_cents, tassa_max_notti, tassa_perc_bps, valuta "
                            "FROM alloggi WHERE slug=?", (slug,)).fetchone()
        finally:
            con.close()
        if r is None:
            return REGOLA_ZERO
        pp = int(r["tassa_pp_notte_cents"]) if "tassa_pp_notte_cents" in r.keys() else 0
        mx = int(r["tassa_max_notti"]) if "tassa_max_notti" in r.keys() else 0
        pc = int(r["tassa_perc_bps"]) if "tassa_perc_bps" in r.keys() else 0
        if pp <= 0 and pc <= 0:
            return REGOLA_ZERO
        return RegolaTassa(per_persona_notte_cents=pp, percentuale_bps=pc,
                           max_notti_tassabili=(mx if mx > 0 else None),
                           valuta=r["valuta"] or "EUR")

    def politica_cancellazione_di(self, slug: Any) -> str:
        """Politica di cancellazione scelta dall'host per l'alloggio (default flessibile)."""
        if not (isinstance(slug, str) and slug):
            return "flessibile"
        con = self._apri()
        try:
            r = con.execute("SELECT politica_cancellazione FROM alloggi WHERE slug=?",
                            (slug,)).fetchone()
        finally:
            con.close()
        if r is None:
            return "flessibile"
        pol = r["politica_cancellazione"] if "politica_cancellazione" in r.keys() else None
        return pol if pol in POLITICHE_CANCELLAZIONE else "flessibile"

    def sconto_lungo_di(self, slug: Any) -> Tuple[int, int]:
        """(sconto_settimana_bps, sconto_mese_bps) dell'alloggio, per il preventivo soggiorni
        lunghi. (0,0) se assenti/slug ignoto. BLINDATO: colonne mancanti -> 0."""
        if not (isinstance(slug, str) and slug):
            return (0, 0)
        con = self._apri()
        try:
            r = con.execute("SELECT sconto_settimana_bps, sconto_mese_bps FROM alloggi "
                            "WHERE slug=?", (slug,)).fetchone()
        except sqlite3.OperationalError:
            return (0, 0)
        finally:
            con.close()
        if r is None:
            return (0, 0)
        def _b(v):
            return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 10000 else 0
        return (_b(r["sconto_settimana_bps"]), _b(r["sconto_mese_bps"]))

    def host_di_alloggio(self, slug: Any) -> Optional[str]:
        """host_id proprietario dell'alloggio (per notifiche prenotazione/payout).
        Non esposto nel dettaglio pubblico. None se lo slug non esiste."""
        if not (isinstance(slug, str) and slug):
            return None
        con = self._apri()
        try:
            r = con.execute("SELECT host_id FROM alloggi WHERE slug=?", (slug,)).fetchone()
        finally:
            con.close()
        return r["host_id"] if r is not None else None

    def elimina_alloggio(self, slug: Any) -> bool:
        """Elimina UN annuncio (alloggio + immagini) — per l'host che ha sbagliato a crearlo.
        Idempotente: slug inesistente -> False. La verifica proprietà la fa il chiamante."""
        if not (isinstance(slug, str) and slug):
            return False
        con = self._apri()
        try:
            with con:
                r = con.execute("SELECT id FROM alloggi WHERE slug=?", (slug,)).fetchone()
                if r is None:
                    return False
                con.execute("DELETE FROM alloggio_immagini WHERE alloggio_id=?", (r["id"],))
                con.execute("DELETE FROM alloggi WHERE id=?", (r["id"],))
            return True
        finally:
            con.close()

    def cancella_alloggi_host(self, host_id: Any) -> int:
        """CANCELLAZIONE TOTALE annunci+immagini di un host (diritto all'oblio / pulizia)."""
        if not (isinstance(host_id, str) and host_id):
            return 0
        con = self._apri()
        try:
            with con:
                con.execute("DELETE FROM alloggio_immagini WHERE alloggio_id IN "
                            "(SELECT slug FROM alloggi WHERE host_id=?)", (host_id,))
                cur = con.execute("DELETE FROM alloggi WHERE host_id=?", (host_id,))
            return cur.rowcount if (cur.rowcount and cur.rowcount > 0) else 0
        finally:
            con.close()

    def conta_alloggi_host(self, host_id: Any) -> int:
        if not (isinstance(host_id, str) and host_id):
            return 0
        con = self._apri()
        try:
            r = con.execute("SELECT COUNT(*) FROM alloggi WHERE host_id=?", (host_id,)).fetchone()
            return int(r[0]) if r else 0
        finally:
            con.close()

    def alloggi_host(self, host_id: str, *, limit: int = 100) -> List[Dict[str, Any]]:
        """Tutti gli alloggi di un host (ogni stato: pubblicato/bozza/sospeso) per il
        pannello 'i miei alloggi'. Read-only."""
        limit = limit if (isinstance(limit, int) and not isinstance(limit, bool)
                          and 0 < limit <= 500) else 100
        con = self._apri()
        try:
            righe = con.execute(
                "SELECT id, slug, titolo, citta, prezzo_notte_cents, valuta, stato FROM alloggi "
                "WHERE host_id=? ORDER BY aggiornato_ts DESC LIMIT ?",
                (str(host_id), limit)).fetchall()
        finally:
            con.close()
        return [{"id": int(r["id"]), "slug": r["slug"], "titolo": r["titolo"],
                 "citta": r["citta"], "prezzo_notte_cents": int(r["prezzo_notte_cents"]),
                 "valuta": r["valuta"] or "EUR", "stato": r["stato"]} for r in righe]

    def cerca_annunci_admin(self, termine: Any, *, limit: int = 10, offset: int = 0
                            ) -> Dict[str, Any]:
        """RICERCA OPERATIVA (Field, Incremento 7): annunci di OGNI stato per slug / titolo
        / citta (LIKE, wildcard neutralizzate) o ID esatto se il termine e' un numero.
        Read-only, solo campi operativi. {'alloggi': [...], 'totale': n}.
        Minimo 2 caratteri, MA un ID numerico corto (es. '7') e' ammesso."""
        if not (isinstance(termine, str)
                and (len(termine.strip()) >= 2 or termine.strip().isdigit())):
            return {"alloggi": [], "totale": 0}
        lim = limit if isinstance(limit, int) and 0 < limit <= 50 else 10
        off = offset if isinstance(offset, int) and 0 <= offset <= 10 ** 6 else 0
        t = termine.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = "%" + t + "%"
        try:
            id_num = int(termine.strip())
        except (ValueError, TypeError):
            id_num = -1
        where = ("WHERE slug LIKE ? ESCAPE '\\' OR titolo LIKE ? ESCAPE '\\' "
                 "OR citta LIKE ? ESCAPE '\\' OR id = ?")
        par = (like, like, like, id_num)
        con = self._apri()
        try:
            tot = con.execute("SELECT COUNT(*) FROM alloggi " + where, par).fetchone()[0]
            righe = con.execute(
                "SELECT id, slug, titolo, citta, stato, host_id FROM alloggi " + where +
                " ORDER BY aggiornato_ts DESC LIMIT ? OFFSET ?",
                par + (lim, off)).fetchall()
        except Exception:
            logger.warning("cerca_annunci_admin fallita (ISOLATA)", exc_info=True)
            return {"alloggi": [], "totale": 0}
        finally:
            con.close()
        return {"alloggi": [{"id": int(r["id"]), "slug": r["slug"], "titolo": r["titolo"],
                             "citta": r["citta"], "stato": r["stato"],
                             "host_id": r["host_id"] or ""} for r in righe],
                "totale": int(tot)}

    # --- READ: ricerca paginata (solo 'pubblicato') ---
    def cerca(self, criteri: CriteriRicerca) -> Dict[str, Any]:
        """Ritorna {'totale', 'limit', 'offset', 'risultati':[scheda_card...]}.
        Solo schede 'pubblicato'. Ordinamento deterministico, paginazione con tetto."""
        where = ["a.stato = 'pubblicato'"]
        par: List[Any] = []
        if criteri.citta:
            where.append("a.citta = ?")
            par.append(criteri.citta.strip())
        if _intero(criteri.prezzo_min_cents):
            where.append("a.prezzo_notte_cents >= ?")
            par.append(criteri.prezzo_min_cents)
        if _intero(criteri.prezzo_max_cents):
            where.append("a.prezzo_notte_cents <= ?")
            par.append(criteri.prezzo_max_cents)
        if _intero(criteri.capacita_min):
            where.append("a.capacita >= ?")
            par.append(criteri.capacita_min)
        req_mask = maschera_servizi(criteri.servizi)
        if req_mask:
            where.append("(a.servizi_mask & ?) = ?")
            par.extend([req_mask, req_mask])
        if (isinstance(criteri.bbox, (list, tuple)) and len(criteri.bbox) == 4
                and all(_intero(x) for x in criteri.bbox)):
            la0, la1, lo0, lo1 = criteri.bbox
            where.append("a.lat_micro BETWEEN ? AND ? AND a.lon_micro BETWEEN ? AND ?")
            par.extend([min(la0, la1), max(la0, la1), min(lo0, lo1), max(lo0, lo1)])

        ordine = {
            "prezzo_asc": "a.prezzo_notte_cents ASC, a.id DESC",
            "prezzo_desc": "a.prezzo_notte_cents DESC, a.id DESC",
        }.get(criteri.ordine, "a.id DESC")   # default 'recente'

        limit = criteri.limit if _intero(criteri.limit) else PAGINA_DEFAULT
        limit = max(1, min(PAGINA_MAX, limit))
        offset = criteri.offset if _intero(criteri.offset) and criteri.offset > 0 else 0

        clausola = " AND ".join(where)
        con = self._apri()
        try:
            totale = con.execute(
                f"SELECT COUNT(*) FROM alloggi a WHERE {clausola}", par).fetchone()[0]
            righe = con.execute(
                "SELECT a.id, a.slug, a.titolo, a.citta, a.paese, a.prezzo_notte_cents, "
                "a.capacita, a.camere, a.bagni, a.servizi_mask, a.valuta, a.lat_micro, "
                "a.lon_micro, "
                "(SELECT url FROM alloggio_immagini i WHERE i.alloggio_id=a.id "
                " ORDER BY i.ordine, i.id LIMIT 1) AS thumb "
                f"FROM alloggi a WHERE {clausola} ORDER BY {ordine} LIMIT ? OFFSET ?",
                par + [limit, offset]).fetchall()
        finally:
            con.close()

        risultati = [self._card_json(r, criteri) for r in righe]
        return {"totale": int(totale), "limit": limit, "offset": offset,
                "risultati": risultati}

    def slug_lastmod_pubblicati(self, *, limit: int = 10000) -> List[Tuple[str, str]]:
        """(slug, data-di-aggiornamento 'YYYY-MM-DD') delle sole schede PUBBLICATE, per il
        <lastmod> della sitemap: così i crawler ricrawlano solo ciò che è cambiato davvero
        (budget di scansione). La data è il prefisso di `aggiornato_ts` (ISO) → sempre caratteri
        sicuri per l'XML. Lettura dedicata, NON tocca `cerca` (nessun campo nuovo nelle card
        pubbliche). BLINDATO: errore → []."""
        lim = limit if isinstance(limit, int) and 0 < limit <= 100000 else 10000
        con = self._apri()
        try:
            righe = con.execute(
                "SELECT slug, aggiornato_ts FROM alloggi WHERE stato='pubblicato' "
                "ORDER BY id DESC LIMIT ?", (lim,)).fetchall()
            return [(str(s), str(ts)[:10]) for s, ts in righe if s]
        except Exception:
            logger.warning("slug_lastmod_pubblicati fallita (ISOLATA)", exc_info=True)
            return []
        finally:
            con.close()

    def citta_pubblicate(self, *, limit: int = 100000) -> List[str]:
        """Città DISTINTE con almeno una scheda 'pubblicato' (inventario REALE). È il segnale
        anti-doorway per la SEO globale: una landing città si genera/indicizza solo dove c'è
        valore vero, mai per moltiplicazione cieca città×lingua (= scaled content abuse). Ordine
        alfabetico deterministico. BLINDATO → []."""
        lim = limit if isinstance(limit, int) and 0 < limit <= 1000000 else 100000
        con = self._apri()
        try:
            righe = con.execute(
                "SELECT DISTINCT citta FROM alloggi WHERE stato='pubblicato' "
                "AND citta IS NOT NULL AND citta != '' ORDER BY citta LIMIT ?", (lim,)).fetchall()
            return [str(r[0]) for r in righe if r and r[0]]
        except Exception:
            logger.warning("citta_pubblicate fallita (ISOLATA)", exc_info=True)
            return []
        finally:
            con.close()

    def dettaglio(self, slug: str) -> Optional[Dict[str, Any]]:
        """Scheda completa + immagini ordinate. None se assente o non 'pubblicato'."""
        con = self._apri()
        try:
            a = con.execute(
                "SELECT * FROM alloggi WHERE slug=? AND stato='pubblicato'",
                (slug,)).fetchone()
            if a is None:
                return None
            imgs = con.execute(
                "SELECT url, ordine, alt FROM alloggio_immagini WHERE alloggio_id=? "
                "ORDER BY ordine, id", (a["id"],)).fetchall()
        finally:
            con.close()
        return self._dettaglio_json(a, imgs)

    def tutti_alloggi(self, *, limit: int = 500) -> List[Dict[str, Any]]:
        """TUTTI gli alloggi di TUTTI gli host (ogni stato) per la vista admin. Read-only.
        Include l'id NUMERICO e l'host_id (per gestione/cancellazione dal pannello admin)."""
        limit = limit if (isinstance(limit, int) and not isinstance(limit, bool)
                          and 0 < limit <= 2000) else 500
        con = self._apri()
        try:
            righe = con.execute(
                "SELECT id, host_id, slug, titolo, citta, prezzo_notte_cents, valuta, stato "
                "FROM alloggi ORDER BY aggiornato_ts DESC LIMIT ?", (limit,)).fetchall()
        finally:
            con.close()
        return [{"id": int(r["id"]), "host_id": r["host_id"], "slug": r["slug"],
                 "titolo": r["titolo"], "citta": r["citta"],
                 "prezzo_notte_cents": int(r["prezzo_notte_cents"]),
                 "valuta": r["valuta"] or "EUR", "stato": r["stato"]} for r in righe]

    def tutti_alloggi_pagina(self, *, id_num: Any = None, host_id: Any = None,
                             stato: Any = None, citta: Any = None,
                             limit: int = 20, offset: int = 0) -> Dict[str, Any]:
        """Vista admin PAGINATA + FILTRATA (Field operativo). Il DATABASE fa filtro,
        conteggio e taglio (WHERE parametrizzato + COUNT + LIMIT/OFFSET): al client
        arrivano SOLO `limit` record (default 20, cap 100), mai la piattaforma intera.
        Nessun SELECT *: solo le colonne mostrate. Filtri opzionali: id numerico,
        host_id, stato (pubblicato|sospeso|bozza), citta. Ritorna {alloggi, totale}."""
        dove: List[str] = []
        par: List[Any] = []
        if isinstance(id_num, int) and not isinstance(id_num, bool) and id_num > 0:
            dove.append("id=?")
            par.append(id_num)
        if isinstance(host_id, str) and host_id.strip():
            dove.append("host_id=?")
            par.append(host_id.strip()[:120])
        if isinstance(stato, str) and stato in STATI_VALIDI:
            dove.append("stato=?")
            par.append(stato)
        if isinstance(citta, str) and citta.strip():
            dove.append("citta=?")
            par.append(citta.strip().lower()[:120])
        clausola = (" WHERE " + " AND ".join(dove)) if dove else ""
        lim = limit if (isinstance(limit, int) and not isinstance(limit, bool)
                        and 0 < limit <= 100) else 20
        off = offset if (isinstance(offset, int) and not isinstance(offset, bool)
                         and offset >= 0) else 0
        off = min(off, 10 ** 9)
        con = self._apri()
        try:
            tot = con.execute("SELECT COUNT(*) FROM alloggi" + clausola, par).fetchone()[0]
            righe = con.execute(
                "SELECT id, host_id, slug, titolo, citta, prezzo_notte_cents, valuta, stato "
                "FROM alloggi" + clausola + " ORDER BY aggiornato_ts DESC, id DESC "
                "LIMIT ? OFFSET ?", par + [lim, off]).fetchall()
        finally:
            con.close()
        return {"alloggi": [{"id": int(r["id"]), "host_id": r["host_id"], "slug": r["slug"],
                             "titolo": r["titolo"], "citta": r["citta"],
                             "prezzo_notte_cents": int(r["prezzo_notte_cents"]),
                             "valuta": r["valuta"] or "EUR", "stato": r["stato"]}
                            for r in righe],
                "totale": int(tot)}

    def dettaglio_owner(self, slug: str) -> Optional[Dict[str, Any]]:
        """Come dettaglio() ma per il PROPRIETARIO nel pannello: ritorna l'alloggio in
        QUALSIASI stato (anche bozza/sospeso), per poterlo MODIFICARE. Nessun filtro sullo
        stato. La chiamata a valle (fase83) verifica la proprietà prima di esporlo."""
        con = self._apri()
        try:
            a = con.execute("SELECT * FROM alloggi WHERE slug=?", (slug,)).fetchone()
            if a is None:
                return None
            imgs = con.execute(
                "SELECT url, ordine, alt FROM alloggio_immagini WHERE alloggio_id=? "
                "ORDER BY ordine, id", (a["id"],)).fetchall()
        finally:
            con.close()
        d = self._dettaglio_json(a, imgs)
        # indirizzo: PRIVATO, solo nella vista del proprietario (mai nel dettaglio pubblico
        # né nelle card di ricerca) -> per pre-riempire il form di modifica e ri-geocodificare
        if isinstance(d, dict):
            d["indirizzo"] = (a["indirizzo"] if "indirizzo" in a.keys() else "") or ""
            d["lat_micro"] = a["lat_micro"]
            d["lon_micro"] = a["lon_micro"]
            d["sconto_settimana_bps"] = a["sconto_settimana_bps"] if "sconto_settimana_bps" in a.keys() else 0
            d["sconto_mese_bps"] = a["sconto_mese_bps"] if "sconto_mese_bps" in a.keys() else 0
            # pin fissato a mano dall'host: il form deve saperlo per NON farlo
            # sovrascrivere dalla geocodifica dell'indirizzo al prossimo salvataggio
            d["pin_manuale"] = bool(a["pin_manuale"]) if "pin_manuale" in a.keys() else False
        return d

    # --- contratti JSON (tutti gli importi int cents; tassi/geo interi) ---
    def _card_json(self, r: sqlite3.Row, criteri: CriteriRicerca) -> Dict[str, Any]:
        card: Dict[str, Any] = {
            "slug": r["slug"],
            "titolo": r["titolo"],
            "citta": r["citta"],
            "paese": r["paese"],
            "prezzo_notte_cents": int(r["prezzo_notte_cents"]),   # int
            "valuta": r["valuta"],                                # etichetta
            "capacita": int(r["capacita"]),
            "camere": int(r["camere"]),
            "bagni": int(r["bagni"]),
            "servizi": servizi_da_maschera(r["servizi_mask"]),
            "thumbnail": r["thumb"],
            "lat_micro": r["lat_micro"],
            "lon_micro": r["lon_micro"],
        }
        # passa lo SLUG (identificatore pubblico stabile, lo stesso usato da inventario
        # fase58 / concierge fase59), NON l'id interno della riga
        card["disponibile"] = self._verifica_disponibilita(
            r["slug"], criteri.check_in, criteri.check_out)
        return card

    def _dettaglio_json(self, a: sqlite3.Row, imgs: Sequence[sqlite3.Row]) -> Dict[str, Any]:
        return {
            "slug": a["slug"],
            "titolo": a["titolo"],
            "descrizione": a["descrizione"],
            "citta": a["citta"],
            "paese": a["paese"],
            "cin": (a["cin"] if "cin" in a.keys() else "") or "",   # obbligo di esposizione IT
            "lat_micro": a["lat_micro"],   # zona (già pubblica in card/mappa); MAI l'indirizzo
            "lon_micro": a["lon_micro"],
            "prezzo_notte_cents": int(a["prezzo_notte_cents"]),
            "valuta": a["valuta"],
            "capacita": int(a["capacita"]),
            "camere": int(a["camere"]),
            "bagni": int(a["bagni"]),
            "servizi": servizi_da_maschera(a["servizi_mask"]),
            "politica_cancellazione": (a["politica_cancellazione"]
                                       if "politica_cancellazione" in a.keys() else "flessibile"),
            "tassa_pp_notte_cents": (int(a["tassa_pp_notte_cents"])
                                     if "tassa_pp_notte_cents" in a.keys() else 0),
            "tassa_max_notti": int(a["tassa_max_notti"]) if "tassa_max_notti" in a.keys() else 0,
            "tassa_perc_bps": int(a["tassa_perc_bps"]) if "tassa_perc_bps" in a.keys() else 0,
            "modalita_prenotazione": (a["modalita_prenotazione"]
                                      if "modalita_prenotazione" in a.keys() else "immediata"),
            "lat_micro": a["lat_micro"],
            "lon_micro": a["lon_micro"],
            "immagini": [{"url": i["url"], "ordine": int(i["ordine"]), "alt": i["alt"]}
                         for i in imgs],
            # come si prenota: la UI passa lo slug come tavolo_id al gateway (fase56)
            "tavolo_id": a["slug"],
        }

    def _verifica_disponibilita(self, alloggio_id: str, check_in: Optional[str],
                                check_out: Optional[str]) -> Optional[bool]:
        """Annotazione disponibilita' ISOLATA: provider assente/eccezione -> None (ignoto)."""
        if self._disp is None or not check_in or not check_out:
            return None
        try:
            esito = self._disp(alloggio_id, check_in, check_out)
            return bool(esito) if esito is not None else None
        except Exception:
            logger.warning("Vetrina: provider disponibilita' ha sollevato (-> ignoto)",
                           exc_info=True)
            return None


# ─────────────────────────────────────────────────────────────────────────────
# Connessione condivisa per :memory: (idioma fase52)
# ─────────────────────────────────────────────────────────────────────────────
class _ConnCondivisa:
    def __init__(self, con: sqlite3.Connection) -> None:
        object.__setattr__(self, "_con", con)

    def close(self) -> None:           # no-op: la connessione :memory: resta viva
        pass

    def __enter__(self):
        return self._con.__enter__()

    def __exit__(self, *a):
        return self._con.__exit__(*a)

    def __getattr__(self, name):
        return getattr(self._con, name)

    def __setattr__(self, name, value):
        setattr(self._con, name, value)


def crea_catalogo(percorso: str = ":memory:", *,
                  disponibilita: Optional[Callable[[int, str, str], Optional[bool]]] = None
                  ) -> CatalogoVetrina:
    """Factory: catalogo su file (o :memory:). Per :memory: connessione condivisa."""
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return CatalogoVetrina(lambda: _ConnCondivisa(con), disponibilita=disponibilita)
    return CatalogoVetrina(lambda: sqlite3.connect(percorso, timeout=30), disponibilita=disponibilita)


# ─────────────────────────────────────────────────────────────────────────────
# Rotte pubbliche di sola lettura (import lazy; auth lasciata a nginx/rate-limit)
# ─────────────────────────────────────────────────────────────────────────────
def registra_vetrina(target: Any, catalogo: CatalogoVetrina, *,
                     path_lista: str = "/catalogo",
                     path_dettaglio: str = "/catalogo/<slug>") -> None:
    """Registra GET /catalogo (ricerca) e GET /catalogo/<slug> (dettaglio)."""
    from flask import request, jsonify

    @target.route(path_lista, methods=["GET"], endpoint="vetrina_lista")
    def _lista() -> Any:
        q = request.args
        def _int(nome):
            v = q.get(nome)
            try:
                return int(v) if v is not None and v != "" else None
            except (ValueError, TypeError):
                return None
        servizi = tuple(s for s in q.get("servizi", "").split(",") if s)
        criteri = CriteriRicerca(
            citta=q.get("citta") or None,
            prezzo_min_cents=_int("prezzo_min_cents"),
            prezzo_max_cents=_int("prezzo_max_cents"),
            capacita_min=_int("capacita_min"),
            servizi=servizi,
            ordine=q.get("ordine", "recente"),
            limit=_int("limit") or PAGINA_DEFAULT,
            offset=_int("offset") or 0,
            check_in=q.get("check_in") or None,
            check_out=q.get("check_out") or None)
        return jsonify(catalogo.cerca(criteri)), 200

    @target.route(path_dettaglio, methods=["GET"], endpoint="vetrina_dettaglio")
    def _dettaglio(slug: str) -> Any:
        d = catalogo.dettaglio(slug)
        if d is None:
            return jsonify({"errore": "not_found"}), 404
        return jsonify(d), 200
