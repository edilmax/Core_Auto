"""
CORE_AUTO - Fase 23 / BLOCCO 1: Datastore abstraction (seam Postgres-ready).

Isola la persistenza dietro un'interfaccia unica (`Datastore`) cosi' che il
passaggio da SQLite a PostgreSQL sia uno SWAP del backend, non una riscrittura.

Compartimento stagno: questo modulo NON e' importato da nessuno al boot; chi lo
adotta lo fa via import lazy + feature-flag. Il backend si sceglie con
DB_BACKEND (default 'sqlite'); richiedere 'postgres' senza psycopg2 installato
FALLISCE in modo CHIARO (fail-closed), senza rompere l'import del modulo.

Cosa astrae (i punti dove SQLite e Postgres divergono davvero):
  - provisioning connessione (+ PRAGMA di resilienza su SQLite),
  - transazione esplicita (BEGIN IMMEDIATE su SQLite, BEGIN su PG),
  - placeholder dei parametri ('?' vs '%s'),
  - espressione "ora" (datetime('now') vs now()),
  - DDL della PK auto-incrementante (AUTOINCREMENT vs BIGSERIAL),
  - upsert "ignora se esiste" (INSERT OR IGNORE vs ON CONFLICT DO NOTHING).
"""
from __future__ import annotations

import logging
import os
import sqlite3
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, Iterator, Sequence

logger = logging.getLogger("core_auto.datastore")

BACKEND_SQLITE = "sqlite"
BACKEND_POSTGRES = "postgres"


class Datastore(ABC):
    """Interfaccia comune ai backend di persistenza."""

    backend: str = ""
    placeholder: str = "?"

    # --- connessione / transazione ---
    @abstractmethod
    def _connect_raw(self) -> Any:
        """Apre una connessione nativa gia' configurata."""

    @abstractmethod
    def _begin(self, conn: Any) -> None: ...

    @abstractmethod
    def _commit(self, conn: Any) -> None: ...

    @abstractmethod
    def _rollback(self, conn: Any) -> None: ...

    @contextmanager
    def connection(self) -> Iterator[Any]:
        """Connessione-per-operazione: aperta, restituita, sempre chiusa."""
        conn = self._connect_raw()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        """Transazione esplicita: BEGIN -> commit su successo, rollback su errore."""
        conn = self._connect_raw()
        try:
            self._begin(conn)
            yield conn
            self._commit(conn)
        except Exception:
            try:
                self._rollback(conn)
            except Exception:  # pragma: no cover - difensivo
                pass
            raise
        finally:
            conn.close()

    # --- primitive di dialetto (override nei backend) ---
    @abstractmethod
    def now_expr(self) -> str: ...

    @abstractmethod
    def autoincrement_pk(self) -> str: ...

    def upsert_ignore_sql(self, table: str, columns: Sequence[str],
                          conflict_col: str) -> str:
        """INSERT che ignora il conflitto sulla chiave (dialetto-specifico)."""
        cols = ", ".join(columns)
        ph = ", ".join([self.placeholder] * len(columns))
        return self._upsert_ignore_tail(f"INSERT INTO {table} ({cols}) VALUES ({ph})",
                                        conflict_col)

    @abstractmethod
    def _upsert_ignore_tail(self, base: str, conflict_col: str) -> str: ...


class SqliteDatastore(Datastore):
    """Backend SQLite (WAL + PRAGMA di resilienza, autocommit per BEGIN manuale)."""

    backend = BACKEND_SQLITE
    placeholder = "?"

    def __init__(self, db_path: str):
        self.db_path = db_path
        cartella = os.path.dirname(db_path)
        if cartella:
            os.makedirs(cartella, exist_ok=True)
        # WAL e' persistente: impostato una sola volta qui (non per-connessione).
        conn = sqlite3.connect(db_path, timeout=30.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.commit()
        finally:
            conn.close()

    def _connect_raw(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _begin(self, conn: sqlite3.Connection) -> None:
        conn.execute("BEGIN IMMEDIATE")  # un solo writer: RMW atomico

    def _commit(self, conn: sqlite3.Connection) -> None:
        conn.execute("COMMIT")

    def _rollback(self, conn: sqlite3.Connection) -> None:
        conn.execute("ROLLBACK")

    def now_expr(self) -> str:
        return "datetime('now')"

    def autoincrement_pk(self) -> str:
        return "INTEGER PRIMARY KEY AUTOINCREMENT"

    def _upsert_ignore_tail(self, base: str, conflict_col: str) -> str:
        return base.replace("INSERT INTO", "INSERT OR IGNORE INTO", 1)


class PostgresDatastore(Datastore):
    """Backend PostgreSQL (psycopg2). Lazy-import: l'assenza del driver NON rompe
    il modulo, ma istanziare questo backend senza psycopg2 FALLISCE chiaramente."""

    backend = BACKEND_POSTGRES
    placeholder = "%s"

    def __init__(self, dsn: str):
        try:
            import psycopg2  # noqa: F401 - lazy, opzionale
        except ImportError as exc:
            raise RuntimeError(
                "Backend Postgres richiesto ma 'psycopg2' non e' installato. "
                "Installa psycopg2-binary o usa DB_BACKEND=sqlite.") from exc
        self.dsn = dsn

    def _connect_raw(self) -> Any:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(self.dsn,
                                cursor_factory=psycopg2.extras.RealDictCursor)
        conn.autocommit = True  # transazioni gestite a mano (come SQLite)
        return conn

    def _begin(self, conn: Any) -> None:
        conn.cursor().execute("BEGIN")

    def _commit(self, conn: Any) -> None:
        conn.cursor().execute("COMMIT")

    def _rollback(self, conn: Any) -> None:
        conn.cursor().execute("ROLLBACK")

    def now_expr(self) -> str:
        return "now()"

    def autoincrement_pk(self) -> str:
        return "BIGSERIAL PRIMARY KEY"

    def _upsert_ignore_tail(self, base: str, conflict_col: str) -> str:
        return f"{base} ON CONFLICT ({conflict_col}) DO NOTHING"


def get_datastore(location: str = None) -> Datastore:
    """Factory: sceglie il backend da DB_BACKEND (default 'sqlite').

    Args:
        location: percorso file (sqlite) o DSN (postgres); se assente, da env
            (DB_PATH per sqlite, DATABASE_URL per postgres).

    Returns:
        L'istanza Datastore.

    Raises:
        RuntimeError: backend sconosciuto o Postgres senza driver (fail-closed).
    """
    backend = os.environ.get("DB_BACKEND", BACKEND_SQLITE).strip().lower()
    if backend == BACKEND_SQLITE:
        return SqliteDatastore(location or os.environ.get("DB_PATH",
                                                          "data/marketplace.db"))
    if backend == BACKEND_POSTGRES:
        return PostgresDatastore(location or os.environ.get("DATABASE_URL", ""))
    raise RuntimeError(f"DB_BACKEND sconosciuto: {backend!r} (usa sqlite|postgres)")
