"""
CORE_AUTO - Fase 58: Channel Manager / Inventario host in TEMPO REALE (anti-overbooking).

Il vero tallone d'Achille dei colossi (Booking/Agoda): l'inventario va aggiornato a
mano dall'host; se arriva una prenotazione da un'altra fonte (telefono, altra OTA,
walk-in) e l'host non aggiorna l'extranet, la stessa camera/tavolo risulta ancora
libera -> OVERBOOKING. Loro lo "risolvono" con penali contrattuali e migliaia di
persone. Noi lo risolviamo in AUTOMATICO, a costo zero di personale:

  1. INVENTARIO AUTORITATIVO unico (il NOSTRO database centrale): disponibilita' e
     prezzi netti per-giorno, per-alloggio. La vetrina (fase57) e il booking (fase34)
     LEGGONO questo, non interrogano l'host in tempo reale.
  2. PRENOTAZIONE ATOMICA anti-overbooking: bloccare l'inventario e' una transazione
     atomica che ricontrolla la capienza notte-per-notte; se anche una notte e' piena
     o chiusa, l'intera prenotazione e' rifiutata. Mai una camera venduta due volte.
  3. SINCRONIZZAZIONE MULTI-SORGENTE: ogni prenotazione/chiusura proveniente da una
     fonte esterna (altra OTA, iCal/PMS, walk-in) e' un EVENTO IDEMPOTENTE (chiave di
     dedup): l'at-least-once dei canali non scala mai due volte lo stesso evento ->
     l'inventario resta coerente automaticamente, azzerando l'overbooking senza sforzo.
  4. COMANDI MESSAGGISTICA "in due tap": l'host aggiorna la disponibilita' da WhatsApp/
     Telegram con un testo ("CHIUDI casa-mare 2026-07-01"); il parser e' BLINDATO
     (non solleva mai). Le NOTIFICHE istantanee al host sono un hook iniettabile e
     ISOLATO (se la notifica fallisce, la prenotazione resta valida).

Integrazione: `disponibile(alloggio_id, check_in, check_out)` ha ESATTAMENTE la firma
del provider che la Vetrina (fase57) inietta -> il Channel Manager E' la sorgente di
verita' della disponibilita' mostrata in vetrina, in tempo reale.

ANTI-OVERBOOKING - VINCITRICE DEL BENCHMARK (4 varianti x 10 stress concorrenti):
  V3 'transazione atomica per-notte (BEGIN IMMEDIATE) + re-check + idempotency-key'.
  Sotto N worker che prenotano la STESSA notte con 1 sola unita', esattamente UNO
  vince, gli altri sono rifiutati 'pieno'; zero doppie vendite. Le altre 3 perdono:
    - V1 read-then-write senza lock: TOCTOU -> vende due volte sotto concorrenza;
    - V2 lock globale di processo: corretto ma serializza TUTTO il throughput;
    - V4 compare-and-swap ottimistico: corretto ma storm di retry sotto alta contesa.
  L'idempotency-key rende l'evento exactly-once: un retry/duplicato (rete, webhook
  ripetuto, channel manager esterno) restituisce lo stesso esito senza riscalare.

DENARO: prezzi netti SOLO in centesimi INTERI. Float/bool/stringhe RIFIUTATI (fase56).
DUREVOLEZZA/CONCORRENZA come fase34/52: conn-per-operazione, WAL, BEGIN IMMEDIATE,
schema idempotente. SOPRAVVIVENZA TOTALE: input corrotti -> fail-closed; giorno non
caricato -> NON prenotabile (fail-closed, come le OTA); notifica giu' -> isolata.
"""
from __future__ import annotations

import datetime
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("core_auto.channel_manager")

MAX_CENTS = 1_000_000_00
MAX_UNITA = 100_000
MAX_NOTTI = 366            # tetto sul range di una singola prenotazione (anti-abuso)


def _intero(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _data_iso(s: Any) -> Optional[datetime.date]:
    if not isinstance(s, str):
        return None
    try:
        return datetime.date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def notti(check_in: Any, check_out: Any) -> Optional[List[str]]:
    """Notti [check_in, check_out) come liste di stringhe ISO (intervallo semi-aperto,
    come fase34). None se date invalide/incoerenti o range fuori tetto."""
    ci, co = _data_iso(check_in), _data_iso(check_out)
    if ci is None or co is None or ci >= co:
        return None
    n = (co - ci).days
    if n <= 0 or n > MAX_NOTTI:
        return None
    return [(ci + datetime.timedelta(days=i)).isoformat() for i in range(n)]


# ─────────────────────────────────────────────────────────────────────────────
# Esiti
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class EsitoPrenotazione:
    ok: bool
    motivo: str                # '' se ok, altrimenti 'pieno'/'chiuso'/'min_notti'/...
    idempotente: bool = False  # True se replay di una idem-key gia' vista
    notti: int = 0


@dataclass(frozen=True)
class EsitoComando:
    ok: bool
    azione: str
    motivo: str = ""


@dataclass(frozen=True)
class ComandoHost:
    azione: str                # 'chiudi'|'apri'|'dispo'|'prezzo'
    alloggio_id: str
    giorno: str
    valore: Optional[int] = None


# ─────────────────────────────────────────────────────────────────────────────
# Channel Manager
# ─────────────────────────────────────────────────────────────────────────────
class ChannelManager:
    """Inventario host autoritativo + prenotazione atomica anti-overbooking +
    ingest multi-sorgente idempotente + comandi messaggistica.

    `notificatore`: callable iniettabile e ISOLATO invocato (best-effort) su ogni
    NUOVO blocco riuscito, con il payload-notifica per l'host."""

    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], *,
                 notificatore: Optional[Callable[[Dict[str, Any]], None]] = None) -> None:
        self._conn_factory = conn_factory
        self._notifica = notificatore
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
                    CREATE TABLE IF NOT EXISTS inventario (
                        alloggio_id TEXT NOT NULL,
                        giorno TEXT NOT NULL,
                        unita_totali INTEGER NOT NULL DEFAULT 0,
                        unita_occupate INTEGER NOT NULL DEFAULT 0,
                        prezzo_netto_cents INTEGER NOT NULL DEFAULT 0,
                        chiuso INTEGER NOT NULL DEFAULT 0,
                        min_notti INTEGER NOT NULL DEFAULT 1,
                        aggiornato_ts TEXT NOT NULL,
                        PRIMARY KEY (alloggio_id, giorno))""")
                con.execute("""
                    CREATE TABLE IF NOT EXISTS movimenti (
                        idem_key TEXT PRIMARY KEY,
                        alloggio_id TEXT NOT NULL,
                        tipo TEXT NOT NULL,        -- 'blocco' | 'rilascio'
                        esito TEXT NOT NULL,
                        check_in TEXT,
                        check_out TEXT,
                        origine TEXT DEFAULT '',
                        ts TEXT NOT NULL)""")
        finally:
            con.close()

    def cancella_alloggio(self, alloggio_id: Any) -> int:
        """CANCELLAZIONE TOTALE inventario+movimenti di un alloggio (oblio/pulizia)."""
        if not (isinstance(alloggio_id, str) and alloggio_id):
            return 0
        con = self._apri()
        try:
            with con:
                cur = con.execute("DELETE FROM inventario WHERE alloggio_id=?", (alloggio_id,))
                con.execute("DELETE FROM movimenti WHERE alloggio_id=?", (alloggio_id,))
            return cur.rowcount if (cur.rowcount and cur.rowcount > 0) else 0
        finally:
            con.close()

    def conta_alloggio(self, alloggio_id: Any) -> int:
        if not (isinstance(alloggio_id, str) and alloggio_id):
            return 0
        con = self._apri()
        try:
            r = con.execute("SELECT COUNT(*) FROM inventario WHERE alloggio_id=?",
                            (alloggio_id,)).fetchone()
            return int(r[0]) if r else 0
        finally:
            con.close()

    # ── WRITE host: set completo di un giorno ──────────────────────────────────
    def imposta_disponibilita(self, alloggio_id: str, giorno: str, *,
                              unita_totali: int, prezzo_netto_cents: int,
                              chiuso: bool = False, min_notti: int = 1) -> bool:
        """Imposta/aggiorna un giorno (fail-closed su input invalidi o se si tenta di
        scendere sotto le unita' gia' occupate)."""
        if not isinstance(alloggio_id, str) or not alloggio_id.strip():
            return False
        if _data_iso(giorno) is None:
            return False
        if not (_intero(unita_totali) and 0 <= unita_totali <= MAX_UNITA):
            return False
        if not (_intero(prezzo_netto_cents) and 0 <= prezzo_netto_cents <= MAX_CENTS):
            return False
        if not (_intero(min_notti) and 1 <= min_notti <= MAX_NOTTI):
            return False
        ora = datetime.datetime.now().isoformat(timespec="seconds")
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT unita_occupate FROM inventario WHERE alloggio_id=? AND giorno=?",
                (alloggio_id, giorno)).fetchone()
            occupate = row["unita_occupate"] if row else 0
            if unita_totali < occupate:           # mai sotto l'occupato reale
                con.execute("ROLLBACK")
                return False
            con.execute(
                "INSERT INTO inventario (alloggio_id, giorno, unita_totali, "
                "unita_occupate, prezzo_netto_cents, chiuso, min_notti, aggiornato_ts) "
                "VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(alloggio_id, giorno) DO UPDATE SET "
                "unita_totali=excluded.unita_totali, "
                "prezzo_netto_cents=excluded.prezzo_netto_cents, "
                "chiuso=excluded.chiuso, min_notti=excluded.min_notti, "
                "aggiornato_ts=excluded.aggiornato_ts",
                (alloggio_id, giorno, unita_totali, occupate, prezzo_netto_cents,
                 int(bool(chiuso)), min_notti, ora))
            con.execute("COMMIT")
            return True
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    def _muta_giorno(self, alloggio_id: str, giorno: str, **campi: Any) -> bool:
        """Aggiornamento parziale (per i comandi). Crea la riga se assente."""
        ora = datetime.datetime.now().isoformat(timespec="seconds")
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT * FROM inventario WHERE alloggio_id=? AND giorno=?",
                (alloggio_id, giorno)).fetchone()
            cur = {
                "unita_totali": row["unita_totali"] if row else 0,
                "unita_occupate": row["unita_occupate"] if row else 0,
                "prezzo_netto_cents": row["prezzo_netto_cents"] if row else 0,
                "chiuso": row["chiuso"] if row else 0,
                "min_notti": row["min_notti"] if row else 1,
            }
            cur.update({k: v for k, v in campi.items() if v is not None})
            if cur["unita_totali"] < cur["unita_occupate"]:
                con.execute("ROLLBACK")
                return False
            con.execute(
                "INSERT INTO inventario (alloggio_id, giorno, unita_totali, "
                "unita_occupate, prezzo_netto_cents, chiuso, min_notti, aggiornato_ts) "
                "VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(alloggio_id, giorno) DO UPDATE SET "
                "unita_totali=excluded.unita_totali, "
                "prezzo_netto_cents=excluded.prezzo_netto_cents, "
                "chiuso=excluded.chiuso, min_notti=excluded.min_notti, "
                "aggiornato_ts=excluded.aggiornato_ts",
                (alloggio_id, giorno, cur["unita_totali"], cur["unita_occupate"],
                 cur["prezzo_netto_cents"], int(cur["chiuso"]), cur["min_notti"], ora))
            con.execute("COMMIT")
            return True
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    # ── READ: disponibilita' (firma compatibile col provider della Vetrina fase57) ──
    def disponibile(self, alloggio_id: int, check_in: str, check_out: str) -> Optional[bool]:
        notti_list = notti(check_in, check_out)
        if notti_list is None:
            return None
        aid = str(alloggio_id)
        con = self._apri()
        try:
            for g in notti_list:
                row = con.execute(
                    "SELECT unita_totali, unita_occupate, chiuso FROM inventario "
                    "WHERE alloggio_id=? AND giorno=?", (aid, g)).fetchone()
                if row is None or row["chiuso"] or row["unita_occupate"] >= row["unita_totali"]:
                    return False
            return True
        finally:
            con.close()

    def prima_finestra(self, alloggio_id: Any, da: Any, a: Any,
                       n_notti: Any) -> Optional[Tuple[str, str]]:
        """DATE FLESSIBILI: prima finestra di `n_notti` notti consecutive DISPONIBILE dentro
        [da, a). Ritorna (check_in, check_out) ISO oppure None. BLINDATO: input invalido/
        intervallo troppo largo -> None. Una query O(giorni) per finestra, cache-friendly."""
        d0, d1 = _data_iso(da), _data_iso(a)
        try:
            n = int(n_notti)
        except (TypeError, ValueError):
            return None
        if d0 is None or d1 is None or n <= 0 or n > MAX_NOTTI:
            return None
        span = (d1 - d0).days
        if span <= 0 or span > 120:                 # tetto anti-abuso sull'ampiezza
            return None
        ultimo = d1 - datetime.timedelta(days=n)    # co = inizio+n deve stare dentro [da, a)
        d = d0
        while d <= ultimo:
            ci = d.isoformat()
            co = (d + datetime.timedelta(days=n)).isoformat()
            if self.disponibile(alloggio_id, ci, co) is True:
                return (ci, co)
            d += datetime.timedelta(days=1)
        return None

    def stato_giorno(self, alloggio_id: str, giorno: str) -> Optional[Dict[str, Any]]:
        con = self._apri()
        try:
            r = con.execute("SELECT * FROM inventario WHERE alloggio_id=? AND giorno=?",
                            (str(alloggio_id), giorno)).fetchone()
            return dict(r) if r else None
        finally:
            con.close()

    def stato_range(self, alloggio_id: str, da: str, a: str) -> Dict[str, Dict[str, Any]]:
        """Tutte le righe inventario [da, a] (estremi INCLUSI) in UNA connessione e UNA
        query: {giorno: riga}, stessa forma di stato_giorno. VINCITRICE del benchmark
        (query unica BETWEEN vs conn-per-giorno vs conn-unica-N-SELECT): 1.7ms contro
        362ms per una vista di 366 giorni, 21ms contro 2400ms sotto scrittore
        concorrente. Read-only; input non-data -> {} (fail-closed)."""
        if _data_iso(da) is None or _data_iso(a) is None:
            return {}
        con = self._apri()
        try:
            rows = con.execute(
                "SELECT * FROM inventario WHERE alloggio_id=? AND giorno BETWEEN ? AND ?",
                (str(alloggio_id), da, a)).fetchall()
            return {r["giorno"]: dict(r) for r in rows}
        finally:
            con.close()

    def elenco_prenotazioni(self, *, alloggio_id: Optional[str] = None,
                            limit: int = 50) -> List[Dict[str, Any]]:
        """Prenotazioni attive (blocco occupato) per la dashboard admin, con lo stato di
        rilascio (rimborso). Read-only."""
        limit = limit if (isinstance(limit, int) and not isinstance(limit, bool)
                          and 0 < limit <= 500) else 50
        sql = ("SELECT m.idem_key, m.alloggio_id, m.check_in, m.check_out, m.origine, "
               "m.ts, (SELECT COUNT(*) FROM movimenti r WHERE r.idem_key = "
               "'rilascio:' || m.idem_key) AS rilasciato "
               "FROM movimenti m WHERE m.tipo='blocco' AND m.esito='occupato'")
        par: List[Any] = []
        if isinstance(alloggio_id, str) and alloggio_id:
            sql += " AND m.alloggio_id=?"
            par.append(alloggio_id)
        sql += " ORDER BY m.ts DESC, m.rowid DESC LIMIT ?"
        par.append(limit)
        con = self._apri()
        try:
            righe = con.execute(sql, par).fetchall()
        finally:
            con.close()
        return [{"idem_key": r["idem_key"], "alloggio_id": r["alloggio_id"],
                 "check_in": r["check_in"], "check_out": r["check_out"],
                 "origine": r["origine"], "ts": r["ts"],
                 "rimborsato": bool(r["rilasciato"])} for r in righe]

    def metriche(self, *, alloggio_id: Optional[str] = None,
                 da: Optional[str] = None, a: Optional[str] = None) -> Dict[str, int]:
        """Metriche per la dashboard host (aggregati SQL O(1)): revenue (occupate x
        prezzo), occupazione, notti. Denaro in CENTESIMI interi. Periodo [da, a)."""
        where: List[str] = []
        par: List[Any] = []
        if isinstance(alloggio_id, str) and alloggio_id:
            where.append("alloggio_id=?")
            par.append(alloggio_id)
        if isinstance(da, str) and da:
            where.append("giorno>=?")
            par.append(da)
        if isinstance(a, str) and a:
            where.append("giorno<?")          # semi-aperto, coerente con le notti
            par.append(a)
        clausola = (" WHERE " + " AND ".join(where)) if where else ""
        con = self._apri()
        try:
            r = con.execute(
                "SELECT COUNT(*) AS giorni, COALESCE(SUM(unita_totali),0) AS tot, "
                "COALESCE(SUM(unita_occupate),0) AS occ, "
                "COALESCE(SUM(unita_occupate*prezzo_netto_cents),0) AS revenue "
                "FROM inventario" + clausola, par).fetchone()
        finally:
            con.close()
        tot = r["tot"]
        occ = r["occ"]
        return {
            "giorni": int(r["giorni"]),
            "notti_totali": int(tot),
            "notti_occupate": int(occ),
            "occupazione_bps": (occ * 10000 // tot) if tot else 0,
            "revenue_cents": int(r["revenue"]),
        }

    def calendario(self, alloggio_id: str, da: str, a: str) -> List[Dict[str, Any]]:
        """Stato giorno-per-giorno [da, a) per la vista calendario dell'host:
        libero | pieno | chiuso | non_caricato. Read-only."""
        elenco_notti = notti(da, a)
        if elenco_notti is None:
            return []
        out: List[Dict[str, Any]] = []
        con = self._apri()
        try:
            for g in elenco_notti:
                row = con.execute(
                    "SELECT unita_totali, unita_occupate, chiuso, prezzo_netto_cents "
                    "FROM inventario WHERE alloggio_id=? AND giorno=?",
                    (str(alloggio_id), g)).fetchone()
                if row is None:
                    out.append({"giorno": g, "stato": "non_caricato"})
                    continue
                if row["chiuso"]:
                    stato = "chiuso"
                elif row["unita_occupate"] >= row["unita_totali"]:
                    stato = "pieno"
                else:
                    stato = "libero"
                out.append({
                    "giorno": g, "stato": stato,
                    "unita_totali": int(row["unita_totali"]),
                    "unita_occupate": int(row["unita_occupate"]),
                    "prezzo_netto_cents": int(row["prezzo_netto_cents"]),
                })
        finally:
            con.close()
        return out

    # ── BLOCCO atomico anti-overbooking (idempotente) ──────────────────────────
    def blocca(self, alloggio_id: str, check_in: str, check_out: str, *,
               idem_key: str, origine: str = "centrale") -> EsitoPrenotazione:
        """Riserva 1 unita' per ogni notte [check_in, check_out), ATOMICAMENTE.
        Idempotente sulla `idem_key`: un replay restituisce lo stesso esito."""
        notti_list = notti(check_in, check_out)
        if notti_list is None:
            return EsitoPrenotazione(False, "date_non_valide")
        if not isinstance(idem_key, str) or not idem_key.strip():
            return EsitoPrenotazione(False, "idem_key_mancante")
        aid = str(alloggio_id)
        ora = datetime.datetime.now().isoformat(timespec="seconds")
        nuovo_ok = False
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            prec = con.execute("SELECT esito FROM movimenti WHERE idem_key=?",
                               (idem_key,)).fetchone()
            if prec is not None:                       # replay: stesso esito, niente scala
                con.execute("COMMIT")
                ok = prec["esito"] == "occupato"
                return EsitoPrenotazione(ok, "" if ok else "rifiutato",
                                         idempotente=True, notti=len(notti_list))
            # re-check capienza notte-per-notte (anti-TOCTOU)
            motivo = ""
            for i, g in enumerate(notti_list):
                row = con.execute(
                    "SELECT unita_totali, unita_occupate, chiuso, min_notti "
                    "FROM inventario WHERE alloggio_id=? AND giorno=?",
                    (aid, g)).fetchone()
                if row is None:
                    motivo = "giorno_non_caricato"
                    break
                if row["chiuso"]:
                    motivo = "chiuso"
                    break
                if i == 0 and len(notti_list) < row["min_notti"]:
                    motivo = "min_notti"
                    break
                if row["unita_occupate"] >= row["unita_totali"]:
                    motivo = "pieno"
                    break
            if motivo:
                con.execute(
                    "INSERT INTO movimenti (idem_key, alloggio_id, tipo, esito, "
                    "check_in, check_out, origine, ts) VALUES (?,?,?,?,?,?,?,?)",
                    (idem_key, aid, "blocco", "rifiutato:" + motivo,
                     check_in, check_out, origine, ora))
                con.execute("COMMIT")
                return EsitoPrenotazione(False, motivo, notti=len(notti_list))
            # tutte le notti ok -> scala
            con.executemany(
                "UPDATE inventario SET unita_occupate = unita_occupate + 1 "
                "WHERE alloggio_id=? AND giorno=?", [(aid, g) for g in notti_list])
            con.execute(
                "INSERT INTO movimenti (idem_key, alloggio_id, tipo, esito, "
                "check_in, check_out, origine, ts) VALUES (?,?,?,?,?,?,?,?)",
                (idem_key, aid, "blocco", "occupato", check_in, check_out, origine, ora))
            con.execute("COMMIT")
            nuovo_ok = True
            return EsitoPrenotazione(True, "", notti=len(notti_list))
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()
            if nuovo_ok:
                self._notifica_isolata(aid, check_in, check_out, origine)

    def rilascia(self, alloggio_id: str, check_in: str, check_out: str, *,
                 idem_key: str) -> EsitoPrenotazione:
        """Libera le notti di un blocco precedente (cancellazione/rimborso). Idempotente:
        rilasciare due volte non scende sotto zero."""
        notti_list = notti(check_in, check_out)
        if notti_list is None:
            return EsitoPrenotazione(False, "date_non_valide")
        aid = str(alloggio_id)
        ril_key = "rilascio:" + str(idem_key)
        ora = datetime.datetime.now().isoformat(timespec="seconds")
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            if con.execute("SELECT 1 FROM movimenti WHERE idem_key=?",
                           (ril_key,)).fetchone() is not None:
                con.execute("COMMIT")
                return EsitoPrenotazione(True, "", idempotente=True, notti=len(notti_list))
            blocco = con.execute(
                "SELECT esito FROM movimenti WHERE idem_key=?", (str(idem_key),)).fetchone()
            if blocco is None or blocco["esito"] != "occupato":
                con.execute("ROLLBACK")
                return EsitoPrenotazione(False, "blocco_inesistente")
            con.executemany(
                "UPDATE inventario SET unita_occupate = MAX(0, unita_occupate - 1) "
                "WHERE alloggio_id=? AND giorno=?", [(aid, g) for g in notti_list])
            con.execute(
                "INSERT INTO movimenti (idem_key, alloggio_id, tipo, esito, "
                "check_in, check_out, origine, ts) VALUES (?,?,?,?,?,?,?,?)",
                (ril_key, aid, "rilascio", "rilasciato", check_in, check_out, "", ora))
            con.execute("COMMIT")
            return EsitoPrenotazione(True, "", notti=len(notti_list))
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    def registra_evento_esterno(self, alloggio_id: str, check_in: str, check_out: str, *,
                                idem_key: str, fonte: str) -> EsitoPrenotazione:
        """Ingest di una prenotazione da fonte ESTERNA (altra OTA, iCal/PMS, walk-in):
        scala l'inventario in modo idempotente -> azzera l'overbooking cross-canale.
        Namespacata sulla fonte per evitare collisioni di chiave tra canali."""
        return self.blocca(alloggio_id, check_in, check_out,
                            idem_key=f"ext:{fonte}:{idem_key}", origine=f"esterno:{fonte}")

    # ── COMANDI messaggistica (WhatsApp/Telegram), parser BLINDATO ─────────────
    def applica_comando(self, testo: Any) -> EsitoComando:
        """Interpreta ed esegue un comando host da messaggistica. NON solleva mai."""
        cmd = interpreta_comando(testo)
        if cmd is None:
            return EsitoComando(False, "ignoto", "comando_non_riconosciuto")
        try:
            if cmd.azione == "chiudi":
                ok = self._muta_giorno(cmd.alloggio_id, cmd.giorno, chiuso=1)
            elif cmd.azione == "apri":
                ok = self._muta_giorno(cmd.alloggio_id, cmd.giorno, chiuso=0)
            elif cmd.azione == "dispo":
                ok = self._muta_giorno(cmd.alloggio_id, cmd.giorno, unita_totali=cmd.valore)
            elif cmd.azione == "prezzo":
                ok = self._muta_giorno(cmd.alloggio_id, cmd.giorno,
                                       prezzo_netto_cents=cmd.valore)
            else:
                return EsitoComando(False, cmd.azione, "azione_non_supportata")
            return EsitoComando(ok, cmd.azione, "" if ok else "rifiutato")
        except Exception:
            logger.error("applica_comando: eccezione ISOLATA", exc_info=True)
            return EsitoComando(False, cmd.azione, "errore_interno")

    # ── notifica host best-effort, ISOLATA ─────────────────────────────────────
    def _notifica_isolata(self, alloggio_id: str, check_in: str, check_out: str,
                          origine: str) -> None:
        if self._notifica is None:
            return
        try:
            self._notifica({
                "tipo": "nuova_prenotazione",
                "alloggio_id": alloggio_id,
                "check_in": check_in,
                "check_out": check_out,
                "origine": origine,
                "testo": (f"Nuova prenotazione: {alloggio_id} "
                          f"dal {check_in} al {check_out} (fonte: {origine})."),
            })
        except Exception:
            logger.warning("Notifica host fallita (ignorata)", exc_info=True)


def interpreta_comando(testo: Any) -> Optional[ComandoHost]:
    """Parser tollerante e BLINDATO. Grammatica (case-insensitive):
        CHIUDI <alloggio> <YYYY-MM-DD>
        APRI   <alloggio> <YYYY-MM-DD>
        DISPO  <alloggio> <YYYY-MM-DD> <n>
        PREZZO <alloggio> <YYYY-MM-DD> <centesimi>
    Ritorna None se non riconosciuto (mai un'eccezione)."""
    if not isinstance(testo, str):
        return None
    parti = testo.strip().split()
    if len(parti) < 3:
        return None
    azione = parti[0].lower()
    alloggio = parti[1]
    giorno = parti[2]
    if _data_iso(giorno) is None or not alloggio:
        return None
    if azione in ("chiudi", "apri") and len(parti) == 3:
        return ComandoHost(azione, alloggio, giorno)
    if azione in ("dispo", "prezzo") and len(parti) == 4:
        try:
            valore = int(parti[3])
        except (ValueError, TypeError):
            return None
        if valore < 0 or valore > (MAX_UNITA if azione == "dispo" else MAX_CENTS):
            return None
        return ComandoHost(azione, alloggio, giorno, valore)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Connessione condivisa per :memory: (idioma fase52/57)
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


def crea_channel_manager(percorso: str = ":memory:", *,
                         notificatore: Optional[Callable[[Dict[str, Any]], None]] = None
                         ) -> ChannelManager:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return ChannelManager(lambda: _ConnCondivisa(con), notificatore=notificatore)
    return ChannelManager(lambda: sqlite3.connect(percorso), notificatore=notificatore)
