"""
CORE_AUTO - Fase 70: Automated Turnover (coordinamento pulizie check-out -> check-in).

L'incubo operativo degli affitti brevi: tra il check-out di un ospite (es. 11:00) e il
check-in del successivo (es. 15:00) c'e' una FINESTRA strettissima per pulire. Se la
pulizia non e' fatta, il nuovo ospite trova sporco (recensione distrutta) o non puo'
entrare. I colossi non lo risolvono: lo scaricano sull'host. Noi lo automatizziamo a
costo zero.

Event-driven, FIFO con gate fisico:
  1. il CHECK-OUT genera automaticamente un task di turnover con la FINESTRA
     [check-out ore 11:00 .. prossimo check-in ore 15:00] (orari configurabili; se non
     c'e' un prossimo ospite, finestra aperta);
  2. il task si assegna a un addetto e si completa; e' 'pronto' se entro la finestra,
     'pronto_in_ritardo' se oltre;
  3. l'alloggio e' AGIBILE per un check-in SOLO se il turnover che lo prepara e'
     pronto -> gate del self check-in (fase64): la chiave digitale non deve aprire una
     stanza ancora sporca (fail-closed);
  4. ALLARME PROATTIVO: i turnover non finiti con la finestra che si chiude sono "a
     rischio" -> notifica (iniettabile, ISOLATA) per intervenire (ritardare il check-in,
     riassegnare, compensare) PRIMA che l'ospite arrivi.

VINCITRICE DEL BENCHMARK (4 modi di coordinare i turnover):
  V3 'event-driven con finestra + gate agibilita' + allarme ritardo'. Pulisce solo
  quando serve (al check-out), conosce la deadline reale (prossimo check-in), e blocca
  l'ingresso se non pronto. Le altre perdono: V1 'manuale' = errori e ritardi, ospite
  trova sporco; V2 'schedule fisso giornaliero' = spreca giorni vuoti o manca i
  back-to-back stretti; V4 'scheduling ML' = overkill, non-deterministico.

SOPRAVVIVENZA TOTALE: store durevole (conn-per-op, WAL, BEGIN IMMEDIATE, idem schema);
creazione idempotente (UNIQUE alloggio+checkout); transizioni atomiche; gate
agibilita' fail-closed; notificatore isolato; orologio iniettabile (test deterministici).
Tempi in epoch interi. Zero dipendenze.
"""
from __future__ import annotations

import datetime
import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("core_auto.turnover")

STATI_NON_PRONTO = ("da_fare", "in_corso")
STATI_PRONTO = ("pronto", "pronto_in_ritardo")


def _intero_nn(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _epoch_da_data_ora(data_iso: Any, ora: int) -> Optional[int]:
    try:
        d = datetime.date.fromisoformat(str(data_iso))
    except (ValueError, TypeError):
        return None
    if not (0 <= ora <= 23):
        return None
    dt = datetime.datetime(d.year, d.month, d.day, ora, 0, 0,
                           tzinfo=datetime.timezone.utc)
    return int(dt.timestamp())


@dataclass(frozen=True)
class EsitoTurnover:
    ok: bool
    motivo: str = ""
    stato: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Gestore turnover durevole
# ─────────────────────────────────────────────────────────────────────────────
class GestoreTurnover:
    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], *,
                 ora_checkout: int = 11, ora_checkin: int = 15,
                 notificatore: Optional[Callable[[Dict[str, Any]], None]] = None,
                 orologio: Optional[Callable[[], int]] = None) -> None:
        self._conn_factory = conn_factory
        self._ora_out = ora_checkout if 0 <= ora_checkout <= 23 else 11
        self._ora_in = ora_checkin if 0 <= ora_checkin <= 23 else 15
        self._notifica = notificatore
        self._now = orologio or (lambda: int(time.time()))
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
                    CREATE TABLE IF NOT EXISTS turnover (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        alloggio_id TEXT NOT NULL,
                        data_checkout TEXT NOT NULL,
                        data_checkin_successivo TEXT,
                        finestra_da INTEGER NOT NULL,
                        finestra_a INTEGER,
                        stato TEXT NOT NULL DEFAULT 'da_fare',
                        addetto_id TEXT,
                        costo_pulizia_cents INTEGER NOT NULL DEFAULT 0,
                        completato_da INTEGER,
                        creato_ts TEXT NOT NULL,
                        UNIQUE (alloggio_id, data_checkout))""")
                con.execute("CREATE INDEX IF NOT EXISTS idx_turn_checkin "
                            "ON turnover(alloggio_id, data_checkin_successivo)")
                con.execute("CREATE INDEX IF NOT EXISTS idx_turn_stato "
                            "ON turnover(stato, finestra_a)")
        finally:
            con.close()

    # ── creazione (dal check-out), idempotente ─────────────────────────────────
    def crea_turnover(self, alloggio_id: str, data_checkout: str,
                      prossimo_checkin: Optional[str] = None, *,
                      costo_pulizia_cents: int = 0) -> Optional[int]:
        """Crea il task di turnover con la finestra [checkout .. prossimo check-in].
        Idempotente su (alloggio, checkout). Ritorna l'id, o None se input invalido."""
        if not (isinstance(alloggio_id, str) and alloggio_id.strip()):
            return None
        finestra_da = _epoch_da_data_ora(data_checkout, self._ora_out)
        if finestra_da is None:
            return None
        finestra_a = None
        if prossimo_checkin:
            finestra_a = _epoch_da_data_ora(prossimo_checkin, self._ora_in)
            if finestra_a is None or finestra_a < finestra_da:
                return None
        costo = costo_pulizia_cents if _intero_nn(costo_pulizia_cents) else 0
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            esistente = con.execute("SELECT id FROM turnover WHERE alloggio_id=? AND "
                                    "data_checkout=?",
                                    (str(alloggio_id), str(data_checkout))).fetchone()
            if esistente is not None:
                con.execute("COMMIT")
                return int(esistente["id"])
            cur = con.execute(
                "INSERT INTO turnover (alloggio_id, data_checkout, "
                "data_checkin_successivo, finestra_da, finestra_a, costo_pulizia_cents, "
                "creato_ts) VALUES (?,?,?,?,?,?,?)",
                (str(alloggio_id), str(data_checkout),
                 str(prossimo_checkin) if prossimo_checkin else None,
                 finestra_da, finestra_a, costo, ts))
            tid = cur.lastrowid
            con.execute("COMMIT")
            return int(tid)
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    # ── assegnazione / completamento ───────────────────────────────────────────
    def assegna(self, turnover_id: int, addetto_id: str) -> EsitoTurnover:
        if not (isinstance(addetto_id, str) and addetto_id.strip()):
            return EsitoTurnover(False, "addetto_non_valido")
        return self._transizione(
            turnover_id, da=("da_fare",), a="in_corso", addetto=str(addetto_id))

    def completa(self, turnover_id: int) -> EsitoTurnover:
        """Completa il turnover: 'pronto' se entro la finestra, 'pronto_in_ritardo' se oltre."""
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            r = con.execute("SELECT stato, finestra_a FROM turnover WHERE id=?",
                            (turnover_id,)).fetchone()
            if r is None:
                con.execute("ROLLBACK")
                return EsitoTurnover(False, "inesistente")
            if r["stato"] in STATI_PRONTO:                # idempotente
                con.execute("COMMIT")
                return EsitoTurnover(True, "", stato=r["stato"])
            if r["stato"] not in STATI_NON_PRONTO:
                con.execute("ROLLBACK")
                return EsitoTurnover(False, "stato_non_valido")
            ora = self._now()
            in_ritardo = r["finestra_a"] is not None and ora > r["finestra_a"]
            stato = "pronto_in_ritardo" if in_ritardo else "pronto"
            con.execute("UPDATE turnover SET stato=?, completato_da=? WHERE id=?",
                        (stato, ora, turnover_id))
            con.execute("COMMIT")
            return EsitoTurnover(True, "", stato=stato)
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    def _transizione(self, turnover_id: int, *, da: tuple, a: str,
                     addetto: Optional[str] = None) -> EsitoTurnover:
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            r = con.execute("SELECT stato FROM turnover WHERE id=?",
                            (turnover_id,)).fetchone()
            if r is None:
                con.execute("ROLLBACK")
                return EsitoTurnover(False, "inesistente")
            if r["stato"] == a:
                con.execute("COMMIT")
                return EsitoTurnover(True, "", stato=a)
            if r["stato"] not in da:
                con.execute("ROLLBACK")
                return EsitoTurnover(False, "transizione_non_valida", stato=r["stato"])
            con.execute("UPDATE turnover SET stato=?, addetto_id=COALESCE(?, addetto_id) "
                        "WHERE id=?", (a, addetto, turnover_id))
            con.execute("COMMIT")
            return EsitoTurnover(True, "", stato=a)
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    # ── gate AGIBILITA' (per il self check-in fase64) ──────────────────────────
    def agibile(self, alloggio_id: str, data_checkin: str) -> bool:
        """L'alloggio e' pronto per un check-in in questa data? Fail-closed: se c'e' un
        turnover che lo prepara e NON e' pronto -> False (chiave non apre stanza sporca).
        Nessun turnover schedulato per quel check-in -> True (niente da pulire)."""
        con = self._apri()
        try:
            r = con.execute("SELECT stato FROM turnover WHERE alloggio_id=? AND "
                            "data_checkin_successivo=?",
                            (str(alloggio_id), str(data_checkin))).fetchone()
        finally:
            con.close()
        if r is None:
            return True
        return r["stato"] in STATI_PRONTO

    # ── allarme ritardi (proattivo) ────────────────────────────────────────────
    def a_rischio(self, *, ora: Optional[int] = None) -> List[Dict[str, Any]]:
        """Turnover non finiti con la finestra gia' chiusa (a rischio per il prossimo ospite)."""
        adesso = ora if _intero_nn(ora) else self._now()
        con = self._apri()
        try:
            righe = con.execute(
                "SELECT id, alloggio_id, data_checkout, data_checkin_successivo, "
                "finestra_a, stato FROM turnover WHERE stato IN ('da_fare','in_corso') "
                "AND finestra_a IS NOT NULL AND finestra_a < ? ORDER BY finestra_a",
                (adesso,)).fetchall()
        finally:
            con.close()
        return [dict(r) for r in righe]

    def segnala_ritardi(self, *, ora: Optional[int] = None) -> int:
        """Notifica (ISOLATA) ogni turnover a rischio. Ritorna quanti segnalati."""
        rischi = self.a_rischio(ora=ora)
        for r in rischi:
            if self._notifica is None:
                continue
            try:
                self._notifica({
                    "tipo": "turnover_a_rischio",
                    "alloggio_id": r["alloggio_id"],
                    "data_checkin_successivo": r["data_checkin_successivo"],
                    "testo": (f"Pulizia NON pronta per {r['alloggio_id']} prima del "
                              f"check-in {r['data_checkin_successivo']}. Intervieni."),
                })
            except Exception:
                logger.warning("Notifica turnover fallita (ignorata)", exc_info=True)
        return len(rischi)

    def stato_turnover(self, turnover_id: int) -> Optional[Dict[str, Any]]:
        con = self._apri()
        try:
            r = con.execute("SELECT * FROM turnover WHERE id=?",
                            (turnover_id,)).fetchone()
            return dict(r) if r else None
        finally:
            con.close()


# ─────────────────────────────────────────────────────────────────────────────
# Connessione condivisa per :memory:
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


def crea_gestore_turnover(percorso: str = ":memory:", *, ora_checkout: int = 11,
                          ora_checkin: int = 15,
                          notificatore: Optional[Callable[[Dict[str, Any]], None]] = None,
                          orologio: Optional[Callable[[], int]] = None) -> GestoreTurnover:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return GestoreTurnover(lambda: _ConnCondivisa(con), ora_checkout=ora_checkout,
                               ora_checkin=ora_checkin, notificatore=notificatore,
                               orologio=orologio)
    return GestoreTurnover(lambda: sqlite3.connect(percorso), ora_checkout=ora_checkout,
                           ora_checkin=ora_checkin, notificatore=notificatore,
                           orologio=orologio)
