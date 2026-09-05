"""
CORE_AUTO - Fase 203: L'OROLOGIO DELL'iCAL -- la difesa dal RITARDO dei calendari esterni.

IL DIFETTO CHE CHIUDE (Blocco 2, casella 3; METODO_v4 §4.2). Airbnb, Booking e Vrbo
pubblicano il calendario dell'host come file iCal (.ics) e rileggono i feed altrui a
intervalli: Airbnb «automatically updates every 3 hours» e limita le richieste (Help Center,
art. 99, letto il 2026-09-05); Booking ogni 30-60 minuti, frequenza non configurabile, e «if
an iCal feed breaks, the platforms stop syncing silently» (Partner Help, 2026). Fra una
prenotazione presa sull'OTA e la lettura del feed passa da mezz'ora a tre ore: in quella
finestra la stessa notte risulta libera da noi, ed e' la «prenotazione fantasma». Fino al
2026-09-05 da noi l'iCal si importava UNA volta, incollando il testo (POST /api/host/ical):
difesa dal ritardo, zero.

LA DIFESA, in tre gesti deterministici (niente agenti):
  1. l'host salva l'URL del feed (solo https) per alloggio: `ArchivioFeed.salva`;
  2. il tick di fase83 rilegge ogni feed al piu' ogni RILETTURA_SEC (15 minuti) e SCRIVE nel
     registro una riga `ICAL SYNC | <ora esatta> | ...` con esito e giorni bloccati (METODO
     §4.2: «ogni sincronizzazione e' registrata con l'ora esatta»); un feed che fallisce
     ERRORI_PER_ALLARME letture di fila (un'ora) diventa un'anomalia del Guardiano: da noi un
     feed rotto non tace mai;
  3. PRIMA di confermare una prenotazione nostra, se l'ultimo tentativo ha piu' di
     RILETTURA_CONFERMA_SEC (60 s), il feed si rilegge ADESSO: le notti appena occupate
     sull'OTA vengono bloccate (fase82 -> fase58, `unita_totali=0`) e `blocca` rifiuta da
     solo. La finestra che governiamo si chiude a secondi. Se la rete fallisce si procede con
     l'ultima lettura buona -- FAIL-OPEN, dichiarato: mai perdere una prenotazione per un'OTA
     irraggiungibile -- e la riga del registro lo dice.

FUORI DAL PERIMETRO, dichiarato: il ritardo con cui le OTA leggono il NOSTRO feed (1-3 ore,
non governabile da qui); la «procedura scritta» per quando succede lo stesso (chi si sposta,
chi paga) e' una decisione del fondatore, non codice. Gli URL dei feed portano un segreto
(Airbnb): nel registro va SOLO l'host e un'impronta corta, mai l'URL intero.

SOPRAVVIVENZA: archivio durevole (conn-per-operazione, WAL, schema idempotente), nessuna
funzione pubblica solleva (un feed che fallisce e' un esito scritto), orologio e rete
INIETTABILI (`ora_ts`, `fetch`) per i collaudi senza tempo vero e senza rete.
"""
from __future__ import annotations

import datetime
import hashlib
import logging
import os
import sqlite3
import time
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("core_auto.ical_orologio")

MARCA = "ICAL SYNC"
MARCA_ROTTO = "ICAL FEED ROTTO"
RILETTURA_SEC = 900             # il tick rilegge ogni feed al piu' ogni 15 minuti
RILETTURA_CONFERMA_SEC = 60     # prima di confermare: rilettura se l'ultimo tentativo ha > 60 s
TIMEOUT_TICK_SEC = 10.0
TIMEOUT_CONFERMA_SEC = 5.0
MAX_BYTES = 1_000_000           # un feed piu' grande di 1 MB non e' un calendario
ERRORI_PER_ALLARME = 4          # 4 letture fallite di fila (un'ora di tick) -> anomalia
MAX_URL = 2048
NOME_ARCHIVIO = "ical_feed.db"
CHIAVE_ANOMALIA = "ical_feed_rotto"

# I due ganci INIETTABILI del modulo, per i collaudi senza tempo vero e senza rete (idioma
# fase67 `orologio=`): `OROLOGIO()` e' l'ora in secondi quando chi chiama non passa `ora_ts`;
# `RETE(url, timeout) -> str` sostituisce urllib quando chi chiama non passa `fetch`.
# In produzione restano None/time.time: nessuno li tocca.
OROLOGIO: Callable[[], float] = time.time
RETE: Optional[Callable[[str, float], str]] = None


def _intero(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _adesso(ora_ts: Optional[int]) -> int:
    return ora_ts if _intero(ora_ts) else int(OROLOGIO())


def _iso(ts: int) -> str:
    return datetime.datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def url_valido(url: Any) -> bool:
    """Solo https, senza spazi ne' a capo, lunghezza limitata: un URL e' un ingresso da fuori."""
    if not isinstance(url, str) or len(url) < 12 or len(url) > MAX_URL:
        return False
    if any(c.isspace() for c in url):
        return False
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return u.scheme == "https" and bool(u.hostname)


def url_breve(url: Any) -> str:
    """Cio' che si puo' scrivere nel registro: l'host e un'impronta corta. MAI l'URL intero:
    il feed di Airbnb porta un segreto nell'indirizzo."""
    try:
        host = urllib.parse.urlsplit(str(url)).hostname or "?"
    except ValueError:
        host = "?"
    return "%s#%s" % (host, hashlib.sha256(str(url).encode("utf-8")).hexdigest()[:8])


def _senza_segreti(testo: str, url: str) -> str:
    """Il testo di un errore senza l'URL intero e senza la sua parte con parametri (il
    segreto del feed sta li'): resta l'host con l'impronta corta."""
    fuori = str(testo).replace(str(url), url_breve(url))
    try:
        query = urllib.parse.urlsplit(str(url)).query
    except ValueError:
        query = ""
    if query:
        fuori = fuori.replace(query, "...")
    return fuori[:160]


def scarica(url: str, *, timeout: float,
            fetch: Optional[Callable[[str, float], str]] = None) -> str:
    """Il testo del feed. `fetch(url, timeout) -> str` e' iniettabile (collaudi senza rete).
    Di serie urllib: si leggono al massimo MAX_BYTES + 1 byte, e oltre il tetto e' un errore."""
    if not url_valido(url):
        raise ValueError("url non valido: solo https, senza spazi, al massimo %d caratteri"
                         % MAX_URL)
    fetch = fetch or RETE
    if fetch is not None:
        testo = str(fetch(url, timeout))
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "BookinVIP-iCal/1.0"})
        # solo https, validato qui sopra: non e' un'apertura di file ne' di schemi arbitrari
        with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310  # noqa: S310
            testo = r.read(MAX_BYTES + 1).decode("utf-8", "replace")
    if len(testo) > MAX_BYTES:
        raise ValueError("feed troppo grande (oltre %d byte)" % MAX_BYTES)
    return testo


class ArchivioFeed:
    """Gli URL salvati per alloggio e l'esito dell'ultima lettura (durevole, schema idempotente).
    `ultima_lettura_ts` e' l'ultima lettura RIUSCITA; `ultimo_tentativo_ts` l'ultimo tentativo:
    e' su questo che si decide se rileggere, cosi' un feed rotto non viene martellato a ogni
    prenotazione."""

    def __init__(self, conn_factory: Callable[[], sqlite3.Connection]) -> None:
        self._conn_factory = conn_factory
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
                    CREATE TABLE IF NOT EXISTS ical_feed (
                        alloggio_id TEXT NOT NULL,
                        url TEXT NOT NULL,
                        creato_ts INTEGER NOT NULL,
                        ultimo_tentativo_ts INTEGER NOT NULL DEFAULT 0,
                        ultima_lettura_ts INTEGER NOT NULL DEFAULT 0,
                        ultimo_esito TEXT NOT NULL DEFAULT '',
                        letture INTEGER NOT NULL DEFAULT 0,
                        errori_di_fila INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (alloggio_id, url))""")
        finally:
            con.close()

    def salva(self, alloggio_id: Any, url: Any, *, ora_ts: Optional[int] = None) -> bool:
        """Un feed per riga; ripetere lo stesso URL e' idempotente. Fail-closed su input."""
        if not (isinstance(alloggio_id, str) and alloggio_id.strip()) or not url_valido(url):
            return False
        ora = _adesso(ora_ts)
        con = self._apri()
        try:
            with con:
                con.execute("INSERT OR IGNORE INTO ical_feed (alloggio_id, url, creato_ts) "
                            "VALUES (?,?,?)", (alloggio_id, url, ora))
            return True
        finally:
            con.close()

    def rimuovi(self, alloggio_id: Any, url: Any) -> bool:
        if not isinstance(alloggio_id, str) or not isinstance(url, str):
            return False
        con = self._apri()
        try:
            with con:
                cur = con.execute("DELETE FROM ical_feed WHERE alloggio_id=? AND url=?",
                                  (alloggio_id, url))
            return max(0, cur.rowcount) > 0
        finally:
            con.close()

    def elenco(self, alloggio_id: Optional[str] = None) -> List[Dict[str, Any]]:
        con = self._apri()
        try:
            if alloggio_id is None:
                righe = con.execute(
                    "SELECT * FROM ical_feed ORDER BY alloggio_id, url").fetchall()
            else:
                righe = con.execute(
                    "SELECT * FROM ical_feed WHERE alloggio_id=? ORDER BY url",
                    (str(alloggio_id),)).fetchall()
            return [dict(r) for r in righe]
        finally:
            con.close()

    def registra_esito(self, alloggio_id: str, url: str, *, ora_ts: int, ok: bool,
                       dettaglio: str) -> int:
        """Aggiorna la riga del feed e restituisce gli errori di fila DOPO l'aggiornamento."""
        con = self._apri()
        try:
            with con:
                if ok:
                    con.execute(
                        "UPDATE ical_feed SET ultimo_tentativo_ts=?, ultima_lettura_ts=?, "
                        "ultimo_esito=?, letture=letture+1, errori_di_fila=0 "
                        "WHERE alloggio_id=? AND url=?",
                        (ora_ts, ora_ts, dettaglio[:200], alloggio_id, url))
                else:
                    con.execute(
                        "UPDATE ical_feed SET ultimo_tentativo_ts=?, ultimo_esito=?, "
                        "letture=letture+1, errori_di_fila=errori_di_fila+1 "
                        "WHERE alloggio_id=? AND url=?",
                        (ora_ts, dettaglio[:200], alloggio_id, url))
            r = con.execute("SELECT errori_di_fila FROM ical_feed WHERE alloggio_id=? AND url=?",
                            (alloggio_id, url)).fetchone()
            return int(r["errori_di_fila"]) if r else 0
        finally:
            con.close()


def rileggi(archivio: ArchivioFeed, inventario: Any, alloggio_id: str, *,
            ora_ts: Optional[int] = None, eta_massima_sec: int = RILETTURA_SEC,
            timeout: float = TIMEOUT_TICK_SEC,
            fetch: Optional[Callable[[str, float], str]] = None,
            motivo: str = "tick") -> List[Dict[str, Any]]:
    """Rilegge i feed dell'alloggio il cui ultimo tentativo ha piu' di `eta_massima_sec`
    (0 = tutti, adesso). Una riga nel registro per ogni lettura, con l'ora esatta. Un feed che
    fallisce e' un esito scritto, non un'eccezione: la sola cosa che puo' sollevare e'
    l'archivio stesso, e chi chiama lo isola."""
    from fase82_ical_sync import sincronizza
    ora = _adesso(ora_ts)
    esiti: List[Dict[str, Any]] = []
    for f in archivio.elenco(alloggio_id):
        url = f["url"]
        eta = ora - int(f.get("ultimo_tentativo_ts") or 0)
        if eta < eta_massima_sec:
            esiti.append({"feed": url_breve(url), "esito": "recente", "eta_sec": eta})
            continue
        t0 = time.perf_counter()
        try:
            testo = scarica(url, timeout=timeout, fetch=fetch)
            r = sincronizza(inventario, alloggio_id, testo)
            ms = int((time.perf_counter() - t0) * 1000)
            eventi = int(r.get("eventi", 0))
            bloccati = int(r.get("giorni_bloccati", 0))
            dettaglio = "eventi=%d giorni_bloccati=%d" % (eventi, bloccati)
            archivio.registra_esito(alloggio_id, url, ora_ts=ora, ok=True, dettaglio=dettaglio)
            logger.info("%s | %s | alloggio=%s | feed=%s | %s | ms=%d | esito=ok | motivo=%s",
                        MARCA, _iso(ora), alloggio_id, url_breve(url), dettaglio, ms, motivo)
            esiti.append({"feed": url_breve(url), "esito": "ok", "eventi": eventi,
                          "giorni_bloccati": bloccati, "ms": ms})
        except Exception as e:
            ms = int((time.perf_counter() - t0) * 1000)
            # codice, sottocodice e messaggio (ferrea 9), MAI l'URL intero ne' il suo segreto:
            # per questo NIENTE `exc_info` qui -- la traccia stamperebbe l'eccezione grezza,
            # che spesso porta l'URL dentro (ferrea 14: le chiavi non si stampano).
            dettaglio = "errore: %s: %s" % (type(e).__name__, _senza_segreti(str(e), url))
            errori = archivio.registra_esito(alloggio_id, url, ora_ts=ora, ok=False,
                                             dettaglio=dettaglio)
            logger.warning("%s | %s | alloggio=%s | feed=%s | %s | ms=%d | esito=errore | "
                           "errori_di_fila=%d | motivo=%s", MARCA, _iso(ora), alloggio_id,
                           url_breve(url), dettaglio, ms, errori, motivo)
            if errori >= ERRORI_PER_ALLARME:
                logger.critical("%s | alloggio=%s | feed=%s | errori_di_fila=%d: le date "
                                "dell'OTA non arrivano piu' da almeno %d minuti", MARCA_ROTTO,
                                alloggio_id, url_breve(url), errori,
                                errori * RILETTURA_SEC // 60)
            esiti.append({"feed": url_breve(url), "esito": "errore", "errori_di_fila": errori,
                          "ms": ms})
    return esiti


def archivio_di(sistema: Any) -> ArchivioFeed:
    """L'archivio dei feed del sistema, creato la prima volta accanto all'inventario
    (`ical_feed.db` nella stessa cartella di `db_inventario`; in memoria se l'inventario e'
    in memoria) e poi tenuto sul sistema."""
    arch = getattr(sistema, "ical_feed", None)
    if isinstance(arch, ArchivioFeed):
        return arch
    fin = getattr(getattr(sistema, "config", None), "db_inventario", "") or ""
    percorso = ":memory:" if fin in ("", ":memory:") \
        else os.path.join(os.path.dirname(os.path.abspath(fin)), NOME_ARCHIVIO)
    arch = crea_archivio_feed(percorso)
    try:
        sistema.ical_feed = arch
    except Exception:
        logger.warning("ical: archivio non agganciabile al sistema (si ricrea a ogni giro)",
                       exc_info=True)
    return arch


def giro_periodico(sistema: Any, *, ora_ts: Optional[int] = None,
                   fetch: Optional[Callable[[str, float], str]] = None) -> Dict[str, int]:
    """Il tick: ogni feed il cui ultimo tentativo ha piu' di RILETTURA_SEC. Mai solleva."""
    conteggio = {"feed": 0, "letti": 0, "errori": 0, "recenti": 0}
    try:
        inv = getattr(sistema, "inventario", None)
        if inv is None:
            return conteggio
        arch = archivio_di(sistema)
        for alloggio in sorted({f["alloggio_id"] for f in arch.elenco()}):
            for e in rileggi(arch, inv, alloggio, ora_ts=ora_ts, eta_massima_sec=RILETTURA_SEC,
                             timeout=TIMEOUT_TICK_SEC, fetch=fetch, motivo="tick"):
                conteggio["feed"] += 1
                if e["esito"] == "ok":
                    conteggio["letti"] += 1
                elif e["esito"] == "errore":
                    conteggio["errori"] += 1
                else:
                    conteggio["recenti"] += 1
    except Exception:
        logger.error("ical: giro periodico fallito (ISOLATO)", exc_info=True)
    return conteggio


def prima_di_confermare(sistema: Any, alloggio_id: Any, *, ora_ts: Optional[int] = None,
                        fetch: Optional[Callable[[str, float], str]] = None
                        ) -> List[Dict[str, Any]]:
    """Prima di `concierge.prenota`: rilegge i feed dell'alloggio se l'ultimo tentativo ha piu'
    di RILETTURA_CONFERMA_SEC. FAIL-OPEN sulla rete (dichiarato): se il feed non risponde si
    prosegue con l'ultima lettura buona, e il registro lo dice. Mai solleva."""
    try:
        inv = getattr(sistema, "inventario", None)
        if inv is None or not isinstance(alloggio_id, str) or not alloggio_id:
            return []
        arch = archivio_di(sistema)
        return rileggi(arch, inv, alloggio_id, ora_ts=ora_ts,
                       eta_massima_sec=RILETTURA_CONFERMA_SEC, timeout=TIMEOUT_CONFERMA_SEC,
                       fetch=fetch, motivo="conferma")
    except Exception:
        logger.error("ical: rilettura prima della conferma fallita (ISOLATA: si prosegue con "
                     "l'ultima lettura buona)", exc_info=True)
        return []


def con_feed_rotti(rapporto: Dict[str, Any], sistema: Any) -> Dict[str, Any]:
    """Arricchisce il rapporto del Guardiano (fase186.scansiona / fase202.giro_quotidiano)
    coi feed rotti: diventano un'anomalia (email), come le violazioni degli invarianti.
    Se questo pezzo fallisce, il rapporto resta quello di prima e lo dice."""
    try:
        rotti = anomalie(sistema)
        if rotti:
            an = rapporto.setdefault("anomalie", {})
            an[CHIAVE_ANOMALIA] = rotti
            rapporto["conta"] = int(rapporto.get("conta") or 0) + len(rotti)
            rapporto["pulito"] = False
    except Exception:
        logger.error("ical: feed rotti non aggiunti al rapporto (ISOLATO)", exc_info=True)
        rapporto.setdefault("non_eseguiti", []).append(
            "ical_feed: il controllo dei feed rotti e' fallito (vedi registro)")
    return rapporto


def anomalie(sistema: Any) -> List[str]:
    """I feed rotti da almeno ERRORI_PER_ALLARME letture di fila, per il Guardiano (fase186):
    un feed rotto che tace e' esattamente il difetto che le OTA hanno e noi no."""
    try:
        return ["ical_feed_rotto: alloggio %s, feed %s, %d letture fallite di fila "
                "(ultimo esito: %s)" % (f["alloggio_id"], url_breve(f["url"]),
                                        int(f.get("errori_di_fila") or 0),
                                        f.get("ultimo_esito") or "-")
                for f in archivio_di(sistema).elenco()
                if int(f.get("errori_di_fila") or 0) >= ERRORI_PER_ALLARME]
    except Exception:
        logger.error("ical: archivio dei feed illeggibile (ISOLATO)", exc_info=True)
        return ["ical_feed: archivio illeggibile (vedi registro)"]


# ─────────────────────────────────────────────────────────────────────────────
# Connessione condivisa per :memory: (idioma fase52/57/58)
# ─────────────────────────────────────────────────────────────────────────────
class _ConnCondivisa:
    def __init__(self, con: sqlite3.Connection) -> None:
        object.__setattr__(self, "_con", con)

    def close(self) -> None:
        pass

    def __enter__(self):
        return self._con.__enter__()

    def __exit__(self, *a):
        return self._con.__exit__(*a)

    def __getattr__(self, name):
        return getattr(self._con, name)

    def __setattr__(self, name, value):
        setattr(self._con, name, value)


def crea_archivio_feed(percorso: str = ":memory:") -> ArchivioFeed:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return ArchivioFeed(lambda: _ConnCondivisa(con))
    return ArchivioFeed(lambda: sqlite3.connect(percorso, timeout=30))
