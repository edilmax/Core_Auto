"""
CORE_AUTO - Fase 149: Deposito cauzionale pre-autorizzazione (hold, no addebito).

Gestisce la cauzione come PRE-AUTORIZZAZIONE sulla carta (hold), non come incasso: si
autorizza pre-arrivo, si CATTURA solo l'eventuale danno (≤ importo autorizzato), si RILASCIA
il resto al check-out. Macchina a stati durevole (SQLite) + handoff al PSP (capture/release
iniettabili, gated). Importi in CENTESIMI interi. Conservazione: catturato + rilasciato =
autorizzato. BLINDATO: transizioni validate, errore → False.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("core_auto.deposito_cauzionale")

STATI = ("autorizzato", "catturato_parziale", "rilasciato", "annullato")


class _ConnCondivisa:
    def __init__(self, con: sqlite3.Connection) -> None:
        object.__setattr__(self, "_con", con)

    def close(self) -> None:
        pass

    def __enter__(self):
        return self._con.__enter__()

    def __exit__(self, *a):
        return self._con.__exit__(*a)

    def __getattr__(self, n):
        return getattr(self._con, n)


def _pos(v: Any) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else -1


class DepositoCauzionale:
    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], *,
                 capture: Optional[Callable[[str, int], bool]] = None,
                 release: Optional[Callable[[str], bool]] = None,
                 orologio: Optional[Callable[[], int]] = None) -> None:
        self._cf = conn_factory
        self._capture = capture           # PSP: (psp_ref, importo) -> ok (gated)
        self._release = release           # PSP: psp_ref -> ok (gated)
        self._now = orologio or (lambda: int(time.time()))

    def _apri(self) -> sqlite3.Connection:
        con = self._cf()
        try:
            con.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass
        return con

    def inizializza_schema(self) -> None:
        con = self._apri()
        try:
            with con:
                con.execute("""CREATE TABLE IF NOT EXISTS cauzione (
                    prenotazione_id TEXT PRIMARY KEY, psp_ref TEXT NOT NULL,
                    autorizzato INTEGER NOT NULL, catturato INTEGER NOT NULL DEFAULT 0,
                    stato TEXT NOT NULL, ts INTEGER NOT NULL)""")
        finally:
            con.close()

    def autorizza(self, prenotazione_id: str, psp_ref: str, importo_cents: int) -> bool:
        if not (prenotazione_id and psp_ref) or _pos(importo_cents) <= 0:
            return False
        con = self._apri()
        try:
            with con:
                con.execute("INSERT OR IGNORE INTO cauzione (prenotazione_id, psp_ref, "
                            "autorizzato, stato, ts) VALUES (?,?,?, 'autorizzato', ?)",
                            (str(prenotazione_id), str(psp_ref), int(importo_cents),
                             self._now()))
                r = con.execute("SELECT autorizzato FROM cauzione WHERE prenotazione_id=?",
                                (str(prenotazione_id),)).fetchone()
            return bool(r and r[0] == int(importo_cents))
        except Exception:
            logger.warning("autorizza fallita (ISOLATA)", exc_info=True)
            return False
        finally:
            con.close()

    def _rec(self, con, pid):
        return con.execute("SELECT psp_ref, autorizzato, catturato, stato FROM cauzione "
                           "WHERE prenotazione_id=?", (str(pid),)).fetchone()

    def cattura_danno(self, prenotazione_id: str, importo_danno_cents: int) -> bool:
        """Cattura ≤ autorizzato per un danno, poi rilascia il resto. Gated dal PSP."""
        danno = _pos(importo_danno_cents)
        if danno < 0:
            return False
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            r = self._rec(con, prenotazione_id)
            if not r or r[3] != "autorizzato" or danno > r[1]:
                con.execute("ROLLBACK")
                return False
            psp_ref = r[0]
            if danno > 0:
                if self._capture is None or not self._safe(self._capture, psp_ref, danno):
                    con.execute("ROLLBACK")
                    return False
            else:
                # nessun danno -> rilascio totale
                if self._release is not None:
                    self._safe(self._release, psp_ref)
            con.execute("UPDATE cauzione SET catturato=?, stato=?, ts=? "
                        "WHERE prenotazione_id=?",
                        (danno, "catturato_parziale" if danno > 0 else "rilasciato",
                         self._now(), str(prenotazione_id)))
            con.execute("COMMIT")
            return True
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            logger.warning("cattura_danno fallita (ISOLATA)", exc_info=True)
            return False
        finally:
            con.close()

    def rilascia(self, prenotazione_id: str) -> bool:
        """Check-out senza danni: rilascia l'hold residuo. Gated dal PSP."""
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            r = self._rec(con, prenotazione_id)
            if not r or r[3] not in ("autorizzato", "catturato_parziale"):
                con.execute("ROLLBACK")
                return False
            if self._release is not None:
                self._safe(self._release, r[0])
            con.execute("UPDATE cauzione SET stato='rilasciato', ts=? "
                        "WHERE prenotazione_id=?", (self._now(), str(prenotazione_id)))
            con.execute("COMMIT")
            return True
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            return False
        finally:
            con.close()

    def stato(self, prenotazione_id: str) -> Dict[str, Any]:
        con = self._apri()
        try:
            r = self._rec(con, prenotazione_id)
            if not r:
                return {}
            return {"psp_ref": r[0], "autorizzato_cents": r[1], "catturato_cents": r[2],
                    "rilasciato_cents": r[1] - r[2], "stato": r[3]}
        finally:
            con.close()

    @staticmethod
    def _safe(fn, *a) -> bool:
        try:
            return bool(fn(*a))
        except Exception:
            logger.warning("PSP call fallita (ISOLATA)", exc_info=True)
            return False


def crea_deposito_cauzionale(percorso: str, *, capture: Any = None, release: Any = None,
                             orologio: Any = None) -> DepositoCauzionale:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return DepositoCauzionale(lambda: _ConnCondivisa(con), capture=capture,
                                  release=release, orologio=orologio)
    return DepositoCauzionale(lambda: sqlite3.connect(percorso), capture=capture,
                              release=release, orologio=orologio)
