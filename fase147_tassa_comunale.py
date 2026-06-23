"""
CORE_AUTO - Fase 147: Tassa di soggiorno comunale automatica (registro + ledger riscossioni).

Estende fase66 (calcolo jurisdiction-agnostic, default ZERO) con: un REGISTRO durevole di
regole per-comune (per-persona-notte cents + cap notti + % su imponibile + esenti), il calcolo
AUTOMATICO per prenotazione, e un LEDGER durevole delle riscossioni (idempotente) per la
rendicontazione al comune. Voce SEPARATA e visibile (pass-through autorità, non nostro margine).
Comune ignoto → ZERO (mai inventare una tassa). Cents interi. SQLite durevole. BLINDATO.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("core_auto.tassa_comunale")

REGOLA_ZERO = {"ppn_cents": 0, "max_notti": 0, "perc_bps": 0, "cap_persona_cents": 0}


def _i(v: Any, d: int = 0) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else d


def calcola_tassa(regola: Dict[str, Any], ospiti: int, notti: int, *,
                  esenti: int = 0, imponibile_cents: int = 0) -> int:
    r = regola if isinstance(regola, dict) else REGOLA_ZERO
    osp, n = _i(ospiti), _i(notti)
    paganti = max(0, osp - _i(esenti))
    maxn = _i(r.get("max_notti"))
    notti_tass = min(n, maxn) if maxn > 0 else n
    base = paganti * notti_tass * _i(r.get("ppn_cents"))
    perc = _i(imponibile_cents) * _i(r.get("perc_bps")) // 10000
    tassa = base + perc
    cap = _i(r.get("cap_persona_cents"))
    if cap > 0 and paganti > 0:
        tassa = min(tassa, cap * paganti)
    return max(0, tassa)


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


class TassaComunale:
    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], *,
                 orologio: Optional[Callable[[], int]] = None) -> None:
        self._cf = conn_factory
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
                con.execute("""CREATE TABLE IF NOT EXISTS tassa_regola (
                    comune TEXT PRIMARY KEY, regola_json TEXT NOT NULL)""")
                con.execute("""CREATE TABLE IF NOT EXISTS tassa_riscossione (
                    prenotazione_id TEXT PRIMARY KEY, comune TEXT NOT NULL,
                    importo INTEGER NOT NULL, ts INTEGER NOT NULL)""")
        finally:
            con.close()

    def _norm(self, comune: str) -> str:
        return str(comune).strip().lower()

    def imposta_regola(self, comune: str, regola: Dict[str, Any]) -> bool:
        if not comune or not isinstance(regola, dict):
            return False
        con = self._apri()
        try:
            with con:
                con.execute("INSERT OR REPLACE INTO tassa_regola (comune, regola_json) "
                            "VALUES (?,?)", (self._norm(comune), json.dumps(regola)))
            return True
        except Exception:
            logger.warning("imposta_regola fallita (ISOLATA)", exc_info=True)
            return False
        finally:
            con.close()

    def regola(self, comune: str) -> Dict[str, Any]:
        con = self._apri()
        try:
            r = con.execute("SELECT regola_json FROM tassa_regola WHERE comune=?",
                            (self._norm(comune),)).fetchone()
            return json.loads(r[0]) if r else dict(REGOLA_ZERO)
        except Exception:
            return dict(REGOLA_ZERO)
        finally:
            con.close()

    def applica(self, comune: str, ospiti: int, notti: int, *,
                esenti: int = 0, imponibile_cents: int = 0) -> int:
        """Tassa per una prenotazione nel comune. Comune ignoto → 0."""
        return calcola_tassa(self.regola(comune), ospiti, notti,
                             esenti=esenti, imponibile_cents=imponibile_cents)

    def registra_riscossione(self, prenotazione_id: str, comune: str,
                             importo_cents: int) -> bool:
        if not prenotazione_id or _i(importo_cents, -1) < 0:
            return False
        con = self._apri()
        try:
            with con:
                con.execute("INSERT OR IGNORE INTO tassa_riscossione (prenotazione_id, "
                            "comune, importo, ts) VALUES (?,?,?,?)",
                            (str(prenotazione_id), self._norm(comune),
                             int(importo_cents), self._now()))
            return True
        except Exception:
            return False
        finally:
            con.close()

    def totale_riscosso(self, comune: str) -> int:
        con = self._apri()
        try:
            r = con.execute("SELECT SUM(importo) FROM tassa_riscossione WHERE comune=?",
                            (self._norm(comune),)).fetchone()
            return int(r[0]) if r and r[0] else 0
        finally:
            con.close()


def crea_tassa_comunale(percorso: str, *, orologio: Any = None) -> TassaComunale:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return TassaComunale(lambda: _ConnCondivisa(con), orologio=orologio)
    return TassaComunale(lambda: sqlite3.connect(percorso), orologio=orologio)
