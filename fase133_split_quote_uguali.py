"""
CORE_AUTO - Fase 133: Split-payment di gruppo a quote uguali (conservazione esatta).

Divide un totale (cents interi) fra N partecipanti in quote il più possibile UGUALI con
CONSERVAZIONE ESATTA al centesimo (largest-remainder: i primi resti prendono +1). Tracking
durevole opzionale dei pagamenti per partecipante + completamento. Complementare a fase65
(split generico): qui split equo deterministico + helper di ripartizione resti. PURO per il
calcolo; store SQLite per lo stato. BLINDATO: input invalido → [] / no-op.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger("core_auto.split_quote_uguali")


def riparti_uguale(totale_cents: Any, n: Any) -> List[int]:
    """N quote intere che sommano ESATTAMENTE a totale_cents (i primi (resto) hanno +1)."""
    tot = totale_cents if isinstance(totale_cents, int) and \
        not isinstance(totale_cents, bool) and totale_cents >= 0 else -1
    k = n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else 0
    if tot < 0 or k == 0:
        return []
    base, resto = divmod(tot, k)
    return [base + (1 if i < resto else 0) for i in range(k)]


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


class SplitQuoteUguali:
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
                con.execute("""CREATE TABLE IF NOT EXISTS split_quota (
                    gruppo_id TEXT NOT NULL, partecipante TEXT NOT NULL,
                    quota INTEGER NOT NULL, pagato INTEGER NOT NULL DEFAULT 0,
                    ts INTEGER NOT NULL,
                    PRIMARY KEY (gruppo_id, partecipante))""")
        finally:
            con.close()

    def crea_gruppo(self, gruppo_id: str, totale_cents: int,
                    partecipanti: Sequence[str]) -> bool:
        parti = [str(p) for p in partecipanti if p] if \
            isinstance(partecipanti, (list, tuple)) else []
        if not gruppo_id or len(parti) != len(set(parti)) or not parti:
            return False
        quote = riparti_uguale(totale_cents, len(parti))
        if not quote:
            return False
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            if con.execute("SELECT 1 FROM split_quota WHERE gruppo_id=?",
                           (str(gruppo_id),)).fetchone():
                con.execute("ROLLBACK")
                return False
            for p, q in zip(parti, quote):
                con.execute("INSERT INTO split_quota (gruppo_id, partecipante, quota, ts) "
                            "VALUES (?,?,?,?)", (str(gruppo_id), p, q, self._now()))
            con.execute("COMMIT")
            return True
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            logger.warning("crea_gruppo fallita (ISOLATA)", exc_info=True)
            return False
        finally:
            con.close()

    def paga(self, gruppo_id: str, partecipante: str) -> bool:
        con = self._apri()
        try:
            with con:
                cur = con.execute("UPDATE split_quota SET pagato=1 WHERE gruppo_id=? "
                                  "AND partecipante=? AND pagato=0",
                                  (str(gruppo_id), str(partecipante)))
            return cur.rowcount > 0
        except Exception:
            return False
        finally:
            con.close()

    def stato(self, gruppo_id: str) -> Dict[str, Any]:
        con = self._apri()
        try:
            rows = con.execute("SELECT partecipante, quota, pagato FROM split_quota "
                               "WHERE gruppo_id=? ORDER BY rowid",
                               (str(gruppo_id),)).fetchall()
            if not rows:
                return {}
            quote = {p: q for p, q, _ in rows}
            pagato = sum(q for _, q, pg in rows if pg)
            totale = sum(q for _, q, _ in rows)
            return {"quote": quote, "pagato_cents": pagato, "totale_cents": totale,
                    "completato": pagato == totale,
                    "mancanti": [p for p, _, pg in rows if not pg]}
        except Exception:
            return {}
        finally:
            con.close()


def crea_split_quote(percorso: str, *, orologio: Any = None) -> SplitQuoteUguali:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return SplitQuoteUguali(lambda: _ConnCondivisa(con), orologio=orologio)
    return SplitQuoteUguali(lambda: sqlite3.connect(percorso, timeout=30), orologio=orologio)
