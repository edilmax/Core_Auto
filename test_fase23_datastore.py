"""
Test FASE 23 / BLOCCO 1 - Datastore abstraction (seam Postgres-ready).

Copre il backend SQLite (connessione, transazione commit/rollback, PRAGMA,
upsert-ignore), le primitive di dialetto Postgres e la selezione del backend
via DB_BACKEND (incluso il fail-closed se psycopg2 manca).
"""
import os
import shutil
import tempfile
import unittest

from fase23_datastore import (Datastore, SqliteDatastore, PostgresDatastore,
                              get_datastore, BACKEND_SQLITE)


class TestSqlite(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ds = SqliteDatastore(os.path.join(self.tmp, "t.db"))
        with self.ds.transaction() as c:
            c.execute(f"CREATE TABLE t (id {self.ds.autoincrement_pk()}, "
                      f"k TEXT UNIQUE, ts TEXT DEFAULT ({self.ds.now_expr()}))")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _count(self):
        with self.ds.connection() as c:
            return c.execute("SELECT COUNT(*) AS n FROM t").fetchone()["n"]

    def test_insert_e_select(self):
        with self.ds.transaction() as c:
            c.execute(f"INSERT INTO t (k) VALUES ({self.ds.placeholder})", ("a",))
        self.assertEqual(self._count(), 1)

    def test_rollback_su_errore(self):
        with self.assertRaises(RuntimeError):
            with self.ds.transaction() as c:
                c.execute(f"INSERT INTO t (k) VALUES ({self.ds.placeholder})", ("b",))
                raise RuntimeError("boom")
        self.assertEqual(self._count(), 0)  # nulla persistito

    def test_upsert_ignore(self):
        sql = self.ds.upsert_ignore_sql("t", ["k"], "k")
        self.assertIn("INSERT OR IGNORE", sql)
        with self.ds.transaction() as c:
            c.execute(sql, ("a",))
        with self.ds.transaction() as c:
            c.execute(sql, ("a",))   # conflitto -> ignorato
        self.assertEqual(self._count(), 1)

    def test_pragma_per_connessione(self):
        with self.ds.connection() as c:
            self.assertEqual(c.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(c.execute("PRAGMA busy_timeout").fetchone()[0], 30000)
            self.assertEqual(c.execute("PRAGMA journal_mode").fetchone()[0].lower(),
                             "wal")

    def test_dialetto(self):
        self.assertEqual(self.ds.placeholder, "?")
        self.assertEqual(self.ds.now_expr(), "datetime('now')")
        self.assertIn("AUTOINCREMENT", self.ds.autoincrement_pk())


class TestDialettoPostgres(unittest.TestCase):
    """Primitive di dialetto PG verificabili senza connessione/driver."""

    def setUp(self):
        # Bypassa __init__ (che richiederebbe psycopg2) per testare solo il dialetto.
        self.pg = PostgresDatastore.__new__(PostgresDatastore)

    def test_primitive(self):
        self.assertEqual(self.pg.placeholder, "%s")
        self.assertEqual(self.pg.now_expr(), "now()")
        self.assertEqual(self.pg.autoincrement_pk(), "BIGSERIAL PRIMARY KEY")

    def test_upsert_on_conflict(self):
        sql = self.pg.upsert_ignore_sql("t", ["k", "v"], "k")
        self.assertIn("INSERT INTO t (k, v) VALUES (%s, %s)", sql)
        self.assertIn("ON CONFLICT (k) DO NOTHING", sql)


class TestFactory(unittest.TestCase):

    def tearDown(self):
        os.environ.pop("DB_BACKEND", None)

    def test_default_sqlite(self):
        os.environ.pop("DB_BACKEND", None)
        ds = get_datastore(os.path.join(tempfile.mkdtemp(), "x.db"))
        self.assertIsInstance(ds, SqliteDatastore)
        self.assertEqual(ds.backend, BACKEND_SQLITE)

    def test_backend_sconosciuto(self):
        os.environ["DB_BACKEND"] = "mysql"
        with self.assertRaises(RuntimeError):
            get_datastore("x")

    def test_selezione_postgres(self):
        # Con driver -> costruisce; senza -> fail-closed con messaggio chiaro.
        os.environ["DB_BACKEND"] = "postgres"
        try:
            ds = get_datastore("postgresql://localhost/x")
            self.assertIsInstance(ds, PostgresDatastore)
        except RuntimeError as e:
            self.assertIn("psycopg2", str(e))


if __name__ == "__main__":
    unittest.main()
