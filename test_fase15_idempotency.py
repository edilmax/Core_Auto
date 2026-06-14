"""
Test FASE 15 - Idempotency Manager + decoratore @idempotent.

Copre: acquisizione/lock, conflitto fingerprint, replay in cache, scoping per
token, concorrenza (exactly-once), sweep lock morti, TTL/purge, e l'integrazione
del decoratore con Flask (replay, conflitto, passthrough, no-cache sui 5xx).
"""
import os
import shutil
import sqlite3
import tempfile
import threading
import unittest

from flask import Flask, jsonify

from fase15_idempotency import IdempotencyManager, EsitoAcquisizione


class _BaseIdem(unittest.TestCase):
    """Setup comune: DB temporaneo isolato + singleton azzerato per ogni test."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "idem.db")
        os.environ["CORE_AUTO_DB"] = self.db
        os.environ["IDEMPOTENCY_TTL_HOURS"] = "24"
        os.environ["IDEMPOTENCY_LOCK_TIMEOUT_MIN"] = "5"
        IdempotencyManager._reset_instance()
        self.mgr = IdempotencyManager(self.db)
        self.fp = self.mgr.fingerprint("POST", "/api/v1/escrow/create",
                                       b'{"importo":100}')

    def tearDown(self) -> None:
        IdempotencyManager._reset_instance()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestManager(_BaseIdem):

    def test_prima_acquire_acquisito_con_token(self):
        r = self.mgr.acquire("k1", self.fp, "corr-1")
        self.assertEqual(r.esito, EsitoAcquisizione.ACQUISITO)
        self.assertTrue(r.token)

    def test_seconda_acquire_in_corso_con_retry_after(self):
        self.mgr.acquire("k1", self.fp)
        r = self.mgr.acquire("k1", self.fp)
        self.assertEqual(r.esito, EsitoAcquisizione.IN_CORSO)
        self.assertGreater(r.retry_after, 0)

    def test_conflitto_su_body_diverso(self):
        self.mgr.acquire("k1", self.fp)
        fp2 = self.mgr.fingerprint("POST", "/api/v1/escrow/create",
                                   b'{"importo":999}')
        r = self.mgr.acquire("k1", fp2)
        self.assertEqual(r.esito, EsitoAcquisizione.CONFLITTO)

    def test_store_e_replay_in_cache(self):
        r1 = self.mgr.acquire("k1", self.fp)
        self.assertTrue(self.mgr.store("k1", r1.token, 201, '{"escrow_id":7}',
                                       {"Content-Type": "application/json"}))
        r2 = self.mgr.acquire("k1", self.fp)
        self.assertEqual(r2.esito, EsitoAcquisizione.IN_CACHE)
        self.assertEqual(r2.risposta["status"], 201)
        self.assertEqual(r2.risposta["body"], '{"escrow_id":7}')
        self.assertEqual(r2.risposta["headers"]["Content-Type"], "application/json")

    def test_store_con_token_errato_rifiutato(self):
        self.mgr.acquire("k1", self.fp)
        self.assertFalse(self.mgr.store("k1", "token-falso", 500, "x"))

    def test_release_token_scoped(self):
        r = self.mgr.acquire("k1", self.fp)
        self.assertFalse(self.mgr.release("k1", "altro-token"))
        self.assertTrue(self.mgr.release("k1", r.token))
        # dopo il release (nessuna risposta) -> ri-acquisibile
        self.assertEqual(self.mgr.acquire("k1", self.fp).esito,
                         EsitoAcquisizione.ACQUISITO)

    def test_concorrenza_exactly_once(self):
        risultati = []
        barriera = threading.Barrier(20)

        def worker():
            barriera.wait()
            risultati.append(self.mgr.acquire("conc", self.fp).esito)

        ts = [threading.Thread(target=worker) for _ in range(20)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(
            sum(1 for e in risultati if e == EsitoAcquisizione.ACQUISITO), 1)

    def test_sweep_lock_morto_e_riacquisizione(self):
        self.mgr.acquire("morto", self.fp)
        conn = self.mgr._conn()
        conn.execute("UPDATE idempotency_keys SET locked_at="
                     "'2000-01-01T00:00:00+00:00' WHERE idempotency_key='morto'")
        conn.close()
        self.assertGreaterEqual(self.mgr.sweep(), 1)
        self.assertEqual(self.mgr.acquire("morto", self.fp).esito,
                         EsitoAcquisizione.ACQUISITO)

    def test_ttl_scaduto_riacquisisce_non_replay(self):
        IdempotencyManager._reset_instance()
        os.environ["IDEMPOTENCY_TTL_HOURS"] = "0"
        mgr = IdempotencyManager(self.db)
        r = mgr.acquire("ttl", self.fp)
        mgr.store("ttl", r.token, 200, "{}")
        self.assertEqual(mgr.acquire("ttl", self.fp).esito,
                         EsitoAcquisizione.ACQUISITO)

    def test_purge_expired(self):
        IdempotencyManager._reset_instance()
        os.environ["IDEMPOTENCY_TTL_HOURS"] = "0"
        mgr = IdempotencyManager(self.db)
        r = mgr.acquire("ttl", self.fp)
        mgr.store("ttl", r.token, 200, "{}")
        self.assertGreaterEqual(mgr.purge_expired(), 1)

    def test_singleton_ignora_db_path_diverso(self):
        altro = IdempotencyManager("/un/altro/path.db")
        self.assertIs(altro, self.mgr)

    def test_fingerprint_deterministico_e_sensibile(self):
        a = self.mgr.fingerprint("POST", "/x", b"body")
        b = self.mgr.fingerprint("POST", "/x", b"body")
        c = self.mgr.fingerprint("POST", "/x", b"BODY")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(len(a), 64)  # SHA-256 esadecimale completo

    def test_acquire_ritenta_su_busy_poi_riesce(self):
        from unittest import mock
        self.mgr._acquire_backoff = 0.0  # niente attese nel test
        chiamate = {"n": 0}
        reale = self.mgr._acquire_once

        def flaky(*a, **k):
            chiamate["n"] += 1
            if chiamate["n"] < 3:
                raise sqlite3.OperationalError("database is locked")
            return reale(*a, **k)

        with mock.patch.object(self.mgr, "_acquire_once", side_effect=flaky):
            r = self.mgr.acquire("retry", self.fp)
        self.assertEqual(r.esito, EsitoAcquisizione.ACQUISITO)
        self.assertEqual(chiamate["n"], 3)  # ha ritentato fino al successo

    def test_acquire_non_ritenta_errori_non_busy(self):
        from unittest import mock
        self.mgr._acquire_backoff = 0.0
        with mock.patch.object(self.mgr, "_acquire_once",
                               side_effect=sqlite3.OperationalError("no such table")):
            with self.assertRaises(sqlite3.OperationalError):
                self.mgr.acquire("x", self.fp)


class TestDecoratore(_BaseIdem):
    """Verifica il decoratore @idempotent isolato (senza fortress)."""

    def _make_app(self):
        from app import idempotent
        app = Flask(__name__)
        app.extensions["core_auto"] = {"idempotency": self.mgr}
        contatore = {"n": 0}

        @app.route("/op", methods=["POST"])
        @idempotent
        def op():
            contatore["n"] += 1
            return jsonify({"n": contatore["n"]}), 201

        @app.route("/boom", methods=["POST"])
        @idempotent
        def boom():
            contatore["n"] += 1
            return jsonify({"err": True}), 500

        return app, contatore

    def test_replay_exactly_once(self):
        app, contatore = self._make_app()
        c = app.test_client()
        h = {"Idempotency-Key": "abc"}
        r1 = c.post("/op", headers=h, json={"a": 1})
        r2 = c.post("/op", headers=h, json={"a": 1})
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 201)
        self.assertEqual(r1.get_json(), r2.get_json())   # stessa risposta
        self.assertEqual(contatore["n"], 1)              # eseguito una sola volta
        self.assertEqual(r2.headers.get("Idempotent-Replay"), "true")

    def test_conflitto_body_diverso(self):
        app, _ = self._make_app()
        c = app.test_client()
        h = {"Idempotency-Key": "abc"}
        c.post("/op", headers=h, json={"a": 1})
        r = c.post("/op", headers=h, json={"a": 2})
        self.assertEqual(r.status_code, 422)

    def test_senza_header_passthrough(self):
        app, contatore = self._make_app()
        c = app.test_client()
        c.post("/op", json={"a": 1})
        c.post("/op", json={"a": 1})
        self.assertEqual(contatore["n"], 2)  # nessuna idempotenza -> 2 esecuzioni

    def test_5xx_non_in_cache(self):
        app, contatore = self._make_app()
        c = app.test_client()
        h = {"Idempotency-Key": "boom-key"}
        r1 = c.post("/boom", headers=h, json={})
        r2 = c.post("/boom", headers=h, json={})
        self.assertEqual(r1.status_code, 500)
        self.assertEqual(r2.status_code, 500)
        self.assertEqual(contatore["n"], 2)  # 5xx rilascia il lock -> retry esegue


if __name__ == "__main__":
    unittest.main()
