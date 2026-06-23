"""
CORE_AUTO - Fase 117: Wishlist / preferiti guest.

Liste di preferiti per guest (più liste nominate, default "Preferiti"). Aggiungi/rimuovi
alloggi (per slug), elenca, conta. Store DUREVOLE (SQLite WAL, conn-per-op + _ConnCondivisa
per :memory:). Idempotente (PK guest+lista+slug). BLINDATO: errore → False/[]/0.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any, Callable, List, Optional

logger = logging.getLogger("core_auto.wishlist")
LISTA_DEFAULT = "Preferiti"


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


class Wishlist:
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
                con.execute("""CREATE TABLE IF NOT EXISTS wishlist (
                    guest_id TEXT NOT NULL, lista TEXT NOT NULL, slug TEXT NOT NULL,
                    ts INTEGER NOT NULL,
                    PRIMARY KEY (guest_id, lista, slug))""")
        finally:
            con.close()

    def aggiungi(self, guest_id: str, slug: str, *, lista: str = LISTA_DEFAULT) -> bool:
        if not (guest_id and slug):
            return False
        con = self._apri()
        try:
            with con:
                con.execute("INSERT OR IGNORE INTO wishlist (guest_id, lista, slug, ts) "
                            "VALUES (?,?,?,?)",
                            (str(guest_id), str(lista or LISTA_DEFAULT), str(slug),
                             self._now()))
            return True
        except Exception:
            logger.warning("wishlist.aggiungi fallita (ISOLATA)", exc_info=True)
            return False
        finally:
            con.close()

    def rimuovi(self, guest_id: str, slug: str, *, lista: str = LISTA_DEFAULT) -> bool:
        if not (guest_id and slug):
            return False
        con = self._apri()
        try:
            with con:
                cur = con.execute("DELETE FROM wishlist WHERE guest_id=? AND lista=? "
                                  "AND slug=?",
                                  (str(guest_id), str(lista or LISTA_DEFAULT), str(slug)))
            return cur.rowcount > 0
        except Exception:
            return False
        finally:
            con.close()

    def elenca(self, guest_id: str, *, lista: str = LISTA_DEFAULT) -> List[str]:
        if not guest_id:
            return []
        con = self._apri()
        try:
            rows = con.execute("SELECT slug FROM wishlist WHERE guest_id=? AND lista=? "
                               "ORDER BY ts, slug",
                               (str(guest_id), str(lista or LISTA_DEFAULT))).fetchall()
            return [r[0] for r in rows]
        except Exception:
            return []
        finally:
            con.close()

    def liste(self, guest_id: str) -> List[str]:
        if not guest_id:
            return []
        con = self._apri()
        try:
            rows = con.execute("SELECT DISTINCT lista FROM wishlist WHERE guest_id=? "
                               "ORDER BY lista", (str(guest_id),)).fetchall()
            return [r[0] for r in rows]
        except Exception:
            return []
        finally:
            con.close()

    def contiene(self, guest_id: str, slug: str, *, lista: str = LISTA_DEFAULT) -> bool:
        return str(slug) in self.elenca(guest_id, lista=lista)


def crea_wishlist(percorso: str, *, orologio: Any = None) -> Wishlist:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return Wishlist(lambda: _ConnCondivisa(con), orologio=orologio)
    return Wishlist(lambda: sqlite3.connect(percorso), orologio=orologio)
