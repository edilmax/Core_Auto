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
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("core_auto.vetrina")

LIMITE_TESTO = 4000
LIMITE_CAMPO = 256
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
    modalita_prenotazione: str = "immediata"   # immediata | su_richiesta (l'host sceglie)


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


def valida_scheda(data: Any) -> Tuple[bool, str, Optional[SchedaAlloggio]]:
    """Validatore BLINDATO (non solleva MAI). Denaro SOLO int cents; geo solo int."""
    if not isinstance(data, dict):
        return False, "payload_non_oggetto", None

    host_id = _stringa(data.get("host_id"), LIMITE_CAMPO)
    if host_id is None:
        return False, "host_id_non_valido", None
    slug = _stringa(data.get("slug"), LIMITE_CAMPO)
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
    modal = data.get("modalita_prenotazione", "immediata")
    if not isinstance(modal, str) or modal not in MODALITA_PRENOTAZIONE:
        modal = "immediata"

    return True, "", SchedaAlloggio(
        host_id=host_id, slug=slug, titolo=titolo, citta=citta,
        prezzo_notte_cents=prezzo, capacita=int(data["capacita"]),
        descrizione=descr.strip(), paese=paese.strip(),
        camere=int(data.get("camere", 1)), bagni=int(data.get("bagni", 1)),
        servizi=servizi, valuta=valuta, stato=stato,
        lat_micro=lat, lon_micro=lon, politica_cancellazione=pol,
        tassa_pp_notte_cents=t_pp, tassa_max_notti=t_max, tassa_perc_bps=t_perc,
        modalita_prenotazione=modal)


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
        if url is None or not (url.startswith("http://") or url.startswith("https://")):
            continue
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
                        modalita_prenotazione TEXT NOT NULL DEFAULT 'immediata',
                        creato_ts TEXT NOT NULL,
                        aggiornato_ts TEXT NOT NULL)""")
                for _c, _d in (("politica_cancellazione", "TEXT NOT NULL DEFAULT 'flessibile'"),
                               ("tassa_pp_notte_cents", "INTEGER NOT NULL DEFAULT 0"),
                               ("tassa_max_notti", "INTEGER NOT NULL DEFAULT 0"),
                               ("tassa_perc_bps", "INTEGER NOT NULL DEFAULT 0"),
                               ("modalita_prenotazione", "TEXT NOT NULL DEFAULT 'immediata'")):
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
                con.execute("CREATE INDEX IF NOT EXISTS idx_img_alloggio "
                            "ON alloggio_immagini(alloggio_id, ordine)")
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
                    "paese, prezzo_notte_cents, capacita, camere, bagni, servizi_mask, "
                    "valuta, stato, lat_micro, lon_micro, politica_cancellazione, "
                    "tassa_pp_notte_cents, tassa_max_notti, tassa_perc_bps, "
                    "modalita_prenotazione, creato_ts, aggiornato_ts) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (scheda.host_id, scheda.slug, scheda.titolo, scheda.descrizione,
                     scheda.citta, scheda.paese, scheda.prezzo_notte_cents, scheda.capacita,
                     scheda.camere, scheda.bagni, mask, scheda.valuta, scheda.stato,
                     scheda.lat_micro, scheda.lon_micro, scheda.politica_cancellazione,
                     scheda.tassa_pp_notte_cents, scheda.tassa_max_notti, scheda.tassa_perc_bps,
                     scheda.modalita_prenotazione, ora, ora))
                alloggio_id = cur.lastrowid
            else:
                alloggio_id = row["id"]
                con.execute(
                    "UPDATE alloggi SET host_id=?, titolo=?, descrizione=?, citta=?, "
                    "paese=?, prezzo_notte_cents=?, capacita=?, camere=?, bagni=?, "
                    "servizi_mask=?, valuta=?, stato=?, lat_micro=?, lon_micro=?, "
                    "politica_cancellazione=?, tassa_pp_notte_cents=?, tassa_max_notti=?, "
                    "tassa_perc_bps=?, modalita_prenotazione=?, aggiornato_ts=? WHERE id=?",
                    (scheda.host_id, scheda.titolo, scheda.descrizione, scheda.citta,
                     scheda.paese, scheda.prezzo_notte_cents, scheda.capacita, scheda.camere,
                     scheda.bagni, mask, scheda.valuta, scheda.stato, scheda.lat_micro,
                     scheda.lon_micro, scheda.politica_cancellazione,
                     scheda.tassa_pp_notte_cents, scheda.tassa_max_notti, scheda.tassa_perc_bps,
                     scheda.modalita_prenotazione, ora, alloggio_id))
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
    return CatalogoVetrina(lambda: sqlite3.connect(percorso), disponibilita=disponibilita)


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
