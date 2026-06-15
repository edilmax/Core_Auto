"""
Test BLOCCO 5 / 1.4 - Validazione Postgres.

- TestComposeFile: valida STRUTTURALMENTE l'isola docker-compose (sempre, no docker).
- TestPostgresLive: valida il dialetto del Datastore contro un Postgres REALE.
  Si SALTA automaticamente se DATABASE_URL non e' impostato/raggiungibile, cosi'
  la suite resta verde anche senza PG. Per attivarlo:
      docker compose -f docker-compose.postgres.yml up -d
      $env:DATABASE_URL = "postgresql://core:core@localhost:5432/core_auto"
      python -m unittest test_postgres_live
"""
import os
import unittest

PG_URL = os.environ.get("DATABASE_URL", "")


def _pg_reachable() -> bool:
    if not PG_URL:
        return False
    try:
        import psycopg2
        conn = psycopg2.connect(PG_URL, connect_timeout=2)
        conn.close()
        return True
    except Exception:
        return False


class TestComposeFile(unittest.TestCase):
    """Validazione strutturale dell'isola Postgres (nessun docker richiesto)."""

    def setUp(self):
        import yaml
        with open("docker-compose.postgres.yml", encoding="utf-8") as f:
            self.doc = yaml.safe_load(f)

    def test_progetto_e_servizio_isolati(self):
        self.assertEqual(self.doc.get("name"), "core_auto_dev")
        self.assertIn("postgres", self.doc["services"])

    def test_immagine_e_healthcheck(self):
        svc = self.doc["services"]["postgres"]
        self.assertTrue(svc["image"].startswith("postgres:"))
        self.assertIn("healthcheck", svc)

    def test_volume_dedicato_persistente(self):
        svc = self.doc["services"]["postgres"]
        self.assertTrue(any("core_auto_pgdata" in v for v in svc["volumes"]))
        self.assertIn("core_auto_pgdata", self.doc["volumes"])

    def test_porta_mappata(self):
        svc = self.doc["services"]["postgres"]
        self.assertTrue(any("5432" in str(p) for p in svc["ports"]))


@unittest.skipUnless(_pg_reachable(),
                     "Postgres non raggiungibile (DATABASE_URL assente/spento): "
                     "test live saltato")
class TestPostgresLive(unittest.TestCase):
    """Valida il dialetto del Datastore contro un Postgres REALE (1.4)."""

    def setUp(self):
        from fase23_datastore import PostgresDatastore
        self.ds = PostgresDatastore(PG_URL)
        with self.ds.transaction() as c:
            self.ds.execute(c, "DROP TABLE IF EXISTS _core_auto_live")
            self.ds.execute(c, f"""CREATE TABLE _core_auto_live (
                id {self.ds.autoincrement_pk()},
                k TEXT UNIQUE,
                ts TIMESTAMPTZ NOT NULL DEFAULT {self.ds.now_expr()})""")

    def tearDown(self):
        with self.ds.transaction() as c:
            self.ds.execute(c, "DROP TABLE IF EXISTS _core_auto_live")

    def test_insert_returning_id_reale(self):
        with self.ds.transaction() as c:
            rid = self.ds.insert_returning_id(
                c, "INSERT INTO _core_auto_live (k) VALUES (?)", ("a",))
        self.assertGreater(rid, 0)

    def test_upsert_ignore_reale(self):
        sql = self.ds.upsert_ignore_sql("_core_auto_live", ["k"], "k")
        with self.ds.transaction() as c:
            self.ds.execute(c, sql, ("dup",))
        with self.ds.transaction() as c:
            self.ds.execute(c, sql, ("dup",))   # conflitto -> ignorato
        with self.ds.connection() as c:
            n = self.ds.execute(
                c, "SELECT COUNT(*) AS n FROM _core_auto_live WHERE k=?",
                ("dup",)).fetchone()["n"]
        self.assertEqual(n, 1)

    def test_rollback_reale(self):
        with self.assertRaises(Exception):
            with self.ds.transaction() as c:
                self.ds.execute(c, "INSERT INTO _core_auto_live (k) VALUES (?)", ("rb",))
                raise RuntimeError("boom")
        with self.ds.connection() as c:
            n = self.ds.execute(
                c, "SELECT COUNT(*) AS n FROM _core_auto_live WHERE k=?",
                ("rb",)).fetchone()["n"]
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
