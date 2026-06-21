"""
CORE_AUTO - Fase 67: Coda Intelligente + Cancellazione Garantita (riempire i buchi).

Il problema che NESSUNO risolve bene: l'alloggio e' pieno, ma qualcuno cancellera'.
I colossi tappano il buco con armi che fanno danni:
  - overbooking (vendono piu' del reale) -> ospite arrabbiato, host penalizzato;
  - sconto last-minute PUBBLICO -> svaluta il prodotto, allena l'ospite ad aspettare;
  - code opache -> l'ospite non sa dove sta, abbandona.
La nostra mossa frega entrambi NEL SENSO BUONO (vincono tutti e due):

  1. L'ospite si mette in CODA con un DEPOSITO rimborsabile. Il deposito filtra
     l'intento reale (niente code frivole) e da' all'ospite un "posto" senza rischio:
     se si libera -> prenota al prezzo originale; se NON si libera -> il deposito
     diventa un VOUCHER maggiorato (guadagno psicologico); se cancella LUI -> lo perde.
  2. Quando l'host cancella, il buco si riempie da solo: offerta ISTANTANEA al primo
     in coda (FIFO), con finestra di risposta; se non risponde -> al secondo; se nessuno
     -> OFFERTA ESCLUSIVA scontata SOLO a chi era in coda (esclusivita', non sconto
     pubblico -> non svaluta il brand).
  3. La coda si offre SOLO se la probabilita' di liberazione e' affidabile (stima
     CONSERVATIVA dalla storia): se troppo bassa -> niente coda (fail-closed, non si
     promette un posto che non arrivera').

Tutto il DENARO (deposito, voucher, sconto esclusivo) e' calcolato dal CORE in
centesimi interi; la commissione Mango NON scende con lo sconto (resta al 5%).

VINCITRICE DEL BENCHMARK (4 modi di riempire i buchi):
  V3 'coda con deposito + offerta esclusiva FIFO + prob conservativa'. Riempie senza
  svalutare (esclusivo, non pubblico), il deposito filtra l'intento, FIFO e' equo e
  deterministico, fail-closed su prob bassa. Le altre perdono: V1 'overbooking' = rischio
  legale + ospiti arrabbiati; V2 'sconto pubblico' = svaluta e allena all'attesa; V4
  'asta dinamica' = complessa, opaca, iniqua.

SOPRAVVIVENZA TOTALE: store durevole (conn-per-op, WAL, BEGIN IMMEDIATE, idem schema);
iscrizione idempotente (UNIQUE); macchina a stati con transizioni atomiche; orologio e
prenotazione iniettati e ISOLATI; validatori BLINDATI; denaro intero. Zero dipendenze.
"""
from __future__ import annotations

import datetime
import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("core_auto.coda_intelligente")

MAX_CENTS = 1_000_000_00
STATI_ATTIVI = ("in_coda", "offerto")


def _intero(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _intero_pos(v: Any) -> bool:
    return _intero(v) and v > 0


def _finestra(check_in: Any, check_out: Any) -> Optional[str]:
    try:
        ci = datetime.date.fromisoformat(str(check_in))
        co = datetime.date.fromisoformat(str(check_out))
    except (ValueError, TypeError):
        return None
    if ci >= co:
        return None
    return f"{ci.isoformat()}|{co.isoformat()}"


@dataclass(frozen=True)
class PoliticaCoda:
    min_campione: int = 20          # sotto: nessuna stima (fail-closed)
    prior_k: int = 20               # smoothing conservativo verso 0
    soglia_bps: int = 2000          # prob minima per offrire la coda (20%)
    deposito_cents: int = 2000      # 20.00
    bonus_voucher_cents: int = 500  # voucher = deposito + bonus (25.00)
    timeout_offerta_sec: int = 7200  # 2h per rispondere
    sconto_esclusivo_bps: int = 1500  # 15%
    tetto_sconto_cents: int = 1500


@dataclass(frozen=True)
class EsitoIscrizione:
    ok: bool
    posizione: int = 0
    motivo: str = ""
    idempotente: bool = False


@dataclass(frozen=True)
class EsitoOfferta:
    esito: str                      # 'offerto'|'gia_offerto'|'coda_vuota'
    ospite_id: Optional[str] = None


@dataclass(frozen=True)
class EsitoAccetta:
    ok: bool
    motivo: str = ""
    idempotente: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Gestore coda durevole
# ─────────────────────────────────────────────────────────────────────────────
class GestoreCoda:
    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], *,
                 politica: Optional[PoliticaCoda] = None,
                 orologio: Optional[Callable[[], int]] = None) -> None:
        self._conn_factory = conn_factory
        self._pol = politica or PoliticaCoda()
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
                    CREATE TABLE IF NOT EXISTS coda (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        alloggio_id TEXT NOT NULL,
                        finestra TEXT NOT NULL,
                        ospite_id TEXT NOT NULL,
                        deposito_cents INTEGER NOT NULL,
                        voucher_cents INTEGER NOT NULL,
                        stato TEXT NOT NULL DEFAULT 'in_coda',
                        offerto_da INTEGER,
                        creato_ts TEXT NOT NULL,
                        UNIQUE (alloggio_id, finestra, ospite_id))""")
                con.execute("""
                    CREATE TABLE IF NOT EXISTS liberazioni (
                        alloggio_id TEXT PRIMARY KEY,
                        liberati INTEGER NOT NULL DEFAULT 0,
                        non_liberati INTEGER NOT NULL DEFAULT 0)""")
                con.execute("CREATE INDEX IF NOT EXISTS idx_coda_chiave "
                            "ON coda(alloggio_id, finestra, stato, id)")
        finally:
            con.close()

    # ── storia liberazioni + probabilita' conservativa ─────────────────────────
    def registra_liberazione(self, alloggio_id: str, liberato: bool) -> bool:
        if not isinstance(alloggio_id, str) or not alloggio_id.strip():
            return False
        col = "liberati" if liberato else "non_liberati"
        con = self._apri()
        try:
            with con:
                con.execute(
                    "INSERT INTO liberazioni (alloggio_id, liberati, non_liberati) "
                    "VALUES (?,?,?) ON CONFLICT(alloggio_id) DO UPDATE SET %s=%s+1"
                    % (col, col),
                    (alloggio_id, 1 if liberato else 0, 0 if liberato else 1))
            return True
        finally:
            con.close()

    def prob_liberazione_bps(self, alloggio_id: str) -> int:
        con = self._apri()
        try:
            r = con.execute("SELECT liberati, non_liberati FROM liberazioni "
                            "WHERE alloggio_id=?", (str(alloggio_id),)).fetchone()
        finally:
            con.close()
        lib = r["liberati"] if r else 0
        tot = lib + (r["non_liberati"] if r else 0)
        if tot < self._pol.min_campione:
            return 0                               # fail-closed: dati insufficienti
        return (lib * 10000) // (tot + self._pol.prior_k)   # smoothing verso 0

    def valuta_iscrizione(self, alloggio_id: str) -> Dict[str, Any]:
        """Decide se offrire la coda. disponibile solo se prob >= soglia (fail-closed)."""
        prob = self.prob_liberazione_bps(alloggio_id)
        if prob < self._pol.soglia_bps:
            return {"disponibile": False, "prob_bps": prob}
        deposito = self._pol.deposito_cents
        return {"disponibile": True, "prob_bps": prob,
                "deposito_cents": deposito,
                "voucher_cents": deposito + self._pol.bonus_voucher_cents}

    # ── iscrizione (idempotente, FIFO) ─────────────────────────────────────────
    def iscrivi(self, alloggio_id: str, check_in: str, check_out: str, ospite_id: str
                ) -> EsitoIscrizione:
        fin = _finestra(check_in, check_out)
        if fin is None:
            return EsitoIscrizione(False, motivo="date_non_valide")
        if not (isinstance(ospite_id, str) and ospite_id.strip()):
            return EsitoIscrizione(False, motivo="ospite_non_valido")
        deposito = self._pol.deposito_cents
        voucher = deposito + self._pol.bonus_voucher_cents
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            esistente = con.execute(
                "SELECT id, stato FROM coda WHERE alloggio_id=? AND finestra=? AND "
                "ospite_id=?", (str(alloggio_id), fin, str(ospite_id))).fetchone()
            if esistente is not None:
                con.execute("COMMIT")
                pos = self._posizione(str(alloggio_id), fin, esistente["id"])
                return EsitoIscrizione(True, posizione=pos, idempotente=True)
            con.execute(
                "INSERT INTO coda (alloggio_id, finestra, ospite_id, deposito_cents, "
                "voucher_cents, stato, creato_ts) VALUES (?,?,?,?,?, 'in_coda', ?)",
                (str(alloggio_id), fin, str(ospite_id), deposito, voucher, ts))
            con.execute("COMMIT")
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()
        return EsitoIscrizione(True, posizione=self.posizione(alloggio_id, check_in,
                                                              check_out, ospite_id))

    def _posizione(self, alloggio_id: str, fin: str, id_riga: int) -> int:
        con = self._apri()
        try:
            return con.execute(
                "SELECT COUNT(*) FROM coda WHERE alloggio_id=? AND finestra=? AND "
                "stato IN ('in_coda','offerto') AND id<=?",
                (alloggio_id, fin, id_riga)).fetchone()[0]
        finally:
            con.close()

    def posizione(self, alloggio_id: str, check_in: str, check_out: str,
                  ospite_id: str) -> int:
        fin = _finestra(check_in, check_out)
        if fin is None:
            return 0
        con = self._apri()
        try:
            r = con.execute("SELECT id, stato FROM coda WHERE alloggio_id=? AND "
                            "finestra=? AND ospite_id=?",
                            (str(alloggio_id), fin, str(ospite_id))).fetchone()
            if r is None or r["stato"] not in STATI_ATTIVI:
                return 0
            return con.execute(
                "SELECT COUNT(*) FROM coda WHERE alloggio_id=? AND finestra=? AND "
                "stato IN ('in_coda','offerto') AND id<=?",
                (str(alloggio_id), fin, r["id"])).fetchone()[0]
        finally:
            con.close()

    def rinuncia(self, alloggio_id: str, check_in: str, check_out: str,
                 ospite_id: str) -> Dict[str, Any]:
        """L'ospite cancella la coda: deposito TRATTENUTO (penale anti-frivolezza)."""
        fin = _finestra(check_in, check_out)
        if fin is None:
            return {"ok": False, "deposito_trattenuto_cents": 0}
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            r = con.execute("SELECT id, stato, deposito_cents FROM coda WHERE "
                            "alloggio_id=? AND finestra=? AND ospite_id=?",
                            (str(alloggio_id), fin, str(ospite_id))).fetchone()
            if r is None or r["stato"] not in STATI_ATTIVI:
                con.execute("ROLLBACK")
                return {"ok": False, "deposito_trattenuto_cents": 0}
            con.execute("UPDATE coda SET stato='rinunciato' WHERE id=?", (r["id"],))
            con.execute("COMMIT")
            return {"ok": True, "deposito_trattenuto_cents": int(r["deposito_cents"])}
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    # ── liberazione: offri al primo in coda ────────────────────────────────────
    def libera(self, alloggio_id: str, check_in: str, check_out: str) -> EsitoOfferta:
        """L'host ha cancellato -> offri il posto al primo in coda (FIFO). Se c'e' gia'
        un'offerta in corso, ritorna quella (non doppia-offerta)."""
        fin = _finestra(check_in, check_out)
        if fin is None:
            return EsitoOfferta("date_non_valide")
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            offerto = con.execute(
                "SELECT ospite_id FROM coda WHERE alloggio_id=? AND finestra=? AND "
                "stato='offerto' ORDER BY id LIMIT 1", (str(alloggio_id), fin)).fetchone()
            if offerto is not None:
                con.execute("COMMIT")
                return EsitoOfferta("gia_offerto", offerto["ospite_id"])
            primo = con.execute(
                "SELECT id, ospite_id FROM coda WHERE alloggio_id=? AND finestra=? AND "
                "stato='in_coda' ORDER BY id LIMIT 1", (str(alloggio_id), fin)).fetchone()
            if primo is None:
                con.execute("COMMIT")
                return EsitoOfferta("coda_vuota")
            con.execute("UPDATE coda SET stato='offerto', offerto_da=? WHERE id=?",
                        (self._now(), primo["id"]))
            con.execute("COMMIT")
            return EsitoOfferta("offerto", primo["ospite_id"])
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    def accetta(self, alloggio_id: str, check_in: str, check_out: str, ospite_id: str, *,
                prenota: Optional[Callable[[str, str, str, str], bool]] = None
                ) -> EsitoAccetta:
        """L'ospite offerto accetta entro la finestra -> prenotazione (delegata, isolata)."""
        fin = _finestra(check_in, check_out)
        if fin is None:
            return EsitoAccetta(False, "date_non_valide")
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            r = con.execute("SELECT id, stato, offerto_da FROM coda WHERE alloggio_id=? "
                            "AND finestra=? AND ospite_id=?",
                            (str(alloggio_id), fin, str(ospite_id))).fetchone()
            if r is None:
                con.execute("ROLLBACK")
                return EsitoAccetta(False, "non_in_coda")
            if r["stato"] == "confermato":
                con.execute("COMMIT")
                return EsitoAccetta(True, idempotente=True)
            if r["stato"] != "offerto":
                con.execute("ROLLBACK")
                return EsitoAccetta(False, "offerta_non_attiva")
            if r["offerto_da"] is None or \
                    self._now() - r["offerto_da"] > self._pol.timeout_offerta_sec:
                con.execute("ROLLBACK")
                return EsitoAccetta(False, "offerta_scaduta")
            con.execute("UPDATE coda SET stato='confermato' WHERE id=?", (r["id"],))
            con.execute("COMMIT")
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()
        # prenotazione delegata FUORI dal lock, isolata
        if prenota is not None:
            try:
                if not prenota(str(alloggio_id), str(check_in), str(check_out),
                               str(ospite_id)):
                    self._riapri(alloggio_id, fin, ospite_id)
                    return EsitoAccetta(False, "prenotazione_fallita")
            except Exception:
                logger.error("accetta: prenotazione ISOLATA ha sollevato", exc_info=True)
                self._riapri(alloggio_id, fin, ospite_id)
                return EsitoAccetta(False, "prenotazione_errore")
        return EsitoAccetta(True)

    def _riapri(self, alloggio_id: str, fin: str, ospite_id: str) -> None:
        """Rollback logico: se la prenotazione fallisce, l'offerta torna valida."""
        con = self._apri()
        try:
            with con:
                con.execute("UPDATE coda SET stato='offerto' WHERE alloggio_id=? AND "
                            "finestra=? AND ospite_id=? AND stato='confermato'",
                            (str(alloggio_id), fin, str(ospite_id)))
        finally:
            con.close()

    def scadi_offerte(self, alloggio_id: str, check_in: str, check_out: str) -> int:
        """Offerte non risposte entro il timeout -> 'scaduto' (poi libera() offre al next)."""
        fin = _finestra(check_in, check_out)
        if fin is None:
            return 0
        limite = self._now() - self._pol.timeout_offerta_sec
        con = self._apri()
        try:
            with con:
                cur = con.execute(
                    "UPDATE coda SET stato='scaduto' WHERE alloggio_id=? AND finestra=? "
                    "AND stato='offerto' AND offerto_da IS NOT NULL AND offerto_da<?",
                    (str(alloggio_id), fin, limite))
            return cur.rowcount
        finally:
            con.close()

    def prezzo_esclusivo(self, prezzo_cents: int) -> int:
        """Sconto esclusivo (solo coda) calcolato dal CORE, con tetto. Mai sotto 1."""
        if not _intero_pos(prezzo_cents):
            return 0
        sconto = min((prezzo_cents * self._pol.sconto_esclusivo_bps) // 10000,
                     self._pol.tetto_sconto_cents)
        return max(1, prezzo_cents - sconto)

    def converti_voucher(self, alloggio_id: str, check_in: str, check_out: str,
                         ospite_id: str) -> Dict[str, Any]:
        """Posto mai arrivato -> il deposito diventa voucher maggiorato (guadagno ospite)."""
        fin = _finestra(check_in, check_out)
        if fin is None:
            return {"ok": False, "voucher_cents": 0}
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            r = con.execute("SELECT id, stato, voucher_cents FROM coda WHERE "
                            "alloggio_id=? AND finestra=? AND ospite_id=?",
                            (str(alloggio_id), fin, str(ospite_id))).fetchone()
            if r is None or r["stato"] not in ("in_coda", "scaduto"):
                con.execute("ROLLBACK")
                return {"ok": False, "voucher_cents": 0}
            con.execute("UPDATE coda SET stato='voucher' WHERE id=?", (r["id"],))
            con.execute("COMMIT")
            return {"ok": True, "voucher_cents": int(r["voucher_cents"])}
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    def stato_coda(self, alloggio_id: str, check_in: str, check_out: str
                   ) -> List[Dict[str, Any]]:
        fin = _finestra(check_in, check_out)
        if fin is None:
            return []
        con = self._apri()
        try:
            righe = con.execute(
                "SELECT ospite_id, stato, deposito_cents, voucher_cents FROM coda "
                "WHERE alloggio_id=? AND finestra=? ORDER BY id",
                (str(alloggio_id), fin)).fetchall()
        finally:
            con.close()
        return [{"ospite_id": r["ospite_id"], "stato": r["stato"],
                 "deposito_cents": int(r["deposito_cents"]),
                 "voucher_cents": int(r["voucher_cents"])} for r in righe]


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


def crea_gestore_coda(percorso: str = ":memory:", *,
                      politica: Optional[PoliticaCoda] = None,
                      orologio: Optional[Callable[[], int]] = None) -> GestoreCoda:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return GestoreCoda(lambda: _ConnCondivisa(con), politica=politica,
                           orologio=orologio)
    return GestoreCoda(lambda: sqlite3.connect(percorso), politica=politica,
                       orologio=orologio)
