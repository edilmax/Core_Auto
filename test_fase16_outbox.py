"""
Test FASE 16 - Outbox Publisher & Dispatcher.

Copre: publish atomico, validazione payload, dispatch success/no-handler,
retry+backoff, DLQ, requeue, reclaim dei messaggi orfani, purge, status,
anti-SSRF del webhook, ciclo di vita start/stop.
"""
import os
import shutil
import tempfile
import time
import unittest

from fase16_outbox import (OutboxDispatcher, OutboxMessage, OutboxPublisher,
                           _connessione, _url_sicuro, _ip_non_instradabile,
                           _verifica_peer)


class _Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "outbox.db")
        os.environ["CORE_AUTO_DB"] = self.db
        OutboxPublisher._reset_instance()
        self.pub = OutboxPublisher(self.db)
        self.disp = OutboxDispatcher(self.db, poll=0.05, batch=10)

    def tearDown(self):
        self.disp.stop()
        OutboxPublisher._reset_instance()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _row(self, mid):
        c = _connessione(self.db)
        try:
            return c.execute("SELECT * FROM outbox WHERE id=?", (mid,)).fetchone()
        finally:
            c.close()


class TestPublisher(_Base):

    def test_publish_in_transazione(self):
        c = _connessione(self.db)
        c.execute("BEGIN IMMEDIATE")
        mid = self.pub.publish(c, OutboxMessage("audit_external", {"event_type": "x"}))
        c.execute("COMMIT")
        c.close()
        self.assertGreater(mid, 0)
        self.assertEqual(self._row(mid)["status"], "pending")

    def test_publish_standalone(self):
        mid = self.pub.publish_standalone(OutboxMessage("audit_external", {"a": 1}))
        self.assertEqual(self._row(mid)["status"], "pending")

    def test_publish_rollback_non_persiste(self):
        # Promessa transazionale: se la txn del chiamante fa rollback, il
        # messaggio outbox NON deve restare persistito.
        c = _connessione(self.db)
        c.execute("BEGIN IMMEDIATE")
        self.pub.publish(c, OutboxMessage("test", {"a": 1}))
        c.execute("ROLLBACK")
        n = c.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
        c.close()
        self.assertEqual(n, 0)

    def test_publish_payload_non_serializzabile(self):
        c = _connessione(self.db)
        c.execute("BEGIN IMMEDIATE")
        try:
            with self.assertRaises(ValueError):
                self.pub.publish(c, OutboxMessage("t", {"x": object()}))
        finally:
            c.execute("ROLLBACK")
            c.close()

    def test_publish_oltre_limite(self):
        orig = OutboxPublisher._MAX_PAYLOAD_BYTES
        OutboxPublisher._MAX_PAYLOAD_BYTES = 50
        try:
            c = _connessione(self.db)
            c.execute("BEGIN IMMEDIATE")
            with self.assertRaises(ValueError):
                self.pub.publish(c, OutboxMessage("t", {"big": "x" * 1000}))
            c.execute("ROLLBACK")
            c.close()
        finally:
            OutboxPublisher._MAX_PAYLOAD_BYTES = orig

    def test_topic_obbligatorio(self):
        c = _connessione(self.db)
        c.execute("BEGIN IMMEDIATE")
        try:
            with self.assertRaises(ValueError):
                self.pub.publish(c, OutboxMessage("", {"a": 1}))
        finally:
            c.execute("ROLLBACK")
            c.close()

    def test_singleton_ignora_db_path_diverso(self):
        altro = OutboxPublisher("/un/altro/path.db")
        self.assertIs(altro, self.pub)


class TestDispatcher(_Base):

    def _process_per_id(self, mid):
        self.disp._process(self._row(mid))

    def test_dispatch_successo(self):
        mid = self.pub.publish_standalone(OutboxMessage("audit_external", {"event_type": "y"}))
        self._process_per_id(mid)
        self.assertEqual(self._row(mid)["status"], "completed")
        self.assertIsNotNone(self._row(mid)["processed_at"])

    def test_no_handler_resta_pending(self):
        mid = self.pub.publish_standalone(OutboxMessage("topic_ignoto", {"a": 1}))
        self._process_per_id(mid)
        self.assertEqual(self._row(mid)["status"], "pending")

    def test_retry_con_backoff(self):
        self.disp.register("flaky", lambda p: False)
        mid = self.pub.publish_standalone(OutboxMessage("flaky", {"a": 1}, max_retries=3))
        self._process_per_id(mid)
        r = self._row(mid)
        self.assertEqual(r["status"], "failed")
        self.assertEqual(r["retry_count"], 1)
        self.assertIsNotNone(r["next_retry_at"])

    def test_dlq_dopo_max_retries(self):
        self.disp.register("flaky", lambda p: False)
        mid = self.pub.publish_standalone(OutboxMessage("flaky", {"a": 1}, max_retries=2))
        self._process_per_id(mid)   # retry_count 1 -> failed
        self._process_per_id(mid)   # retry_count 2 -> dead_letter
        r = self._row(mid)
        self.assertEqual(r["status"], "dead_letter")
        self.assertEqual(r["retry_count"], 2)

    def test_handler_che_solleva_e_trattato_come_fallimento(self):
        def boom(p):
            raise RuntimeError("kaboom")
        self.disp.register("boom", boom)
        mid = self.pub.publish_standalone(OutboxMessage("boom", {"a": 1}, max_retries=3))
        self._process_per_id(mid)
        r = self._row(mid)
        self.assertEqual(r["status"], "failed")  # mai bloccato in 'processing'
        self.assertIn("eccezione handler", r["last_error"])

    def test_process_salta_record_gia_completato(self):
        mid = self.pub.publish_standalone(OutboxMessage("audit_external", {"e": 1}))
        self._process_per_id(mid)  # -> completed
        snap = self._row(mid)
        self.disp._process(snap)   # ri-processo lo stesso snapshot: CAS rowcount 0
        self.assertEqual(self._row(mid)["status"], "completed")

    def test_requeue_dead_letter(self):
        self.disp.register("flaky", lambda p: False)
        mid = self.pub.publish_standalone(OutboxMessage("flaky", {"a": 1}, max_retries=1))
        self._process_per_id(mid)  # -> dead_letter
        self.assertEqual(self.disp.requeue_dead_letter(mid), 1)
        self.assertEqual(self._row(mid)["status"], "pending")

    def test_reclaim_stuck(self):
        mid = self.pub.publish_standalone(OutboxMessage("audit_external", {"e": 1}))
        c = _connessione(self.db)
        c.execute("UPDATE outbox SET status='processing', locked_by='dead', "
                  "locked_at='2000-01-01T00:00:00+00:00' WHERE id=?", (mid,))
        c.close()
        self.assertGreaterEqual(self.disp.reclaim_stuck(), 1)
        self.assertEqual(self._row(mid)["status"], "failed")

    def test_purge_completed(self):
        mid = self.pub.publish_standalone(OutboxMessage("audit_external", {"e": 1}))
        self._process_per_id(mid)  # completed
        c = _connessione(self.db)
        c.execute("UPDATE outbox SET processed_at='2000-01-01T00:00:00+00:00' WHERE id=?", (mid,))
        c.close()
        self.assertGreaterEqual(self.disp.purge_completed(retention_hours=1), 1)
        self.assertIsNone(self._row(mid))

    def test_status_metriche(self):
        self.pub.publish_standalone(OutboxMessage("audit_external", {"e": 1}))
        s = self.disp.status()
        self.assertEqual(s.get("pending"), 1)

    def test_process_inietta_meta_outbox(self):
        # FASE 21: l'handler riceve _outbox.message_id (chiave delivery stabile),
        # ma il body resta intatto.
        captured = {}
        self.disp.register("meta", lambda p: captured.update(p) or True)
        mid = self.pub.publish_standalone(OutboxMessage("meta", {"body": {"x": 1}}))
        self._process_per_id(mid)
        self.assertEqual(captured.get("_outbox", {}).get("message_id"), mid)
        self.assertEqual(captured.get("body"), {"x": 1})       # body non inquinato
        self.assertNotIn("_outbox", captured.get("body", {}))

    def test_webhook_headers_idempotency_key(self):
        h = OutboxDispatcher._webhook_headers({"_outbox": {"message_id": 42}})
        self.assertEqual(h["Idempotency-Key"], "outbox-42")
        self.assertEqual(h["X-Outbox-Delivery-Id"], "42")
        # senza meta: nessuna idempotency-key in uscita
        self.assertNotIn("Idempotency-Key", OutboxDispatcher._webhook_headers({}))

    def test_start_stop(self):
        self.disp.start()
        time.sleep(0.2)
        self.disp.stop()
        self.assertFalse(self.disp._running)

    def test_backoff_limiti_e_cap(self):
        # NB: con full jitter la monotonicita' per-campione NON e' garantita
        # (specie attorno al cap); si verificano gli invarianti reali: ogni
        # delay sta in [1, min(2**i, cap)] e a retry alti e' limitato dal cap.
        cap = self.disp._backoff_cap_s
        for i in range(14):
            d = self.disp._backoff(i)
            self.assertGreaterEqual(d, 1)
            self.assertLessEqual(d, min(2 ** i, cap))
        self.assertLessEqual(self.disp._backoff(50), cap)


class TestAntiSSRF(_Base):

    def test_url_sicuro_blocca_interni_e_scheme(self):
        self.assertFalse(_url_sicuro("http://169.254.169.254/latest/meta-data/"))
        self.assertFalse(_url_sicuro("http://127.0.0.1:8000/x"))
        self.assertFalse(_url_sicuro("http://10.0.0.5/x"))
        self.assertFalse(_url_sicuro("ftp://example.com"))
        self.assertFalse(_url_sicuro("non-un-url"))

    def test_url_sicuro_ammette_ip_pubblico(self):
        # IP numerico pubblico: nessuna dipendenza dal DNS di rete.
        self.assertTrue(_url_sicuro("https://1.1.1.1/webhook"))

    def test_webhook_rifiuta_url_non_sicuro(self):
        self.assertFalse(self.disp._h_webhook({"url": "http://127.0.0.1/x", "body": {}}))

    def test_allowlist_host(self):
        os.environ["OUTBOX_WEBHOOK_ALLOWLIST"] = "1.1.1.1"
        try:
            self.assertTrue(_url_sicuro("https://1.1.1.1/x"))
            self.assertFalse(_url_sicuro("https://8.8.8.8/x"))  # fuori allowlist
        finally:
            os.environ.pop("OUTBOX_WEBHOOK_ALLOWLIST", None)

    def test_ip_non_instradabile(self):
        for blocco in ("127.0.0.1", "10.0.0.1", "192.168.1.1", "169.254.169.254",
                       "::1", "non-un-ip"):
            self.assertTrue(_ip_non_instradabile(blocco), blocco)
        for ok in ("1.1.1.1", "8.8.8.8"):
            self.assertFalse(_ip_non_instradabile(ok), ok)

    def test_verifica_peer_blocca_interno_al_connect(self):
        # FASE 20: chiusura DNS-rebinding -> valida l'IP REALE del peer.
        class _FakeSock:
            def __init__(self, ip):
                self.ip, self.closed = ip, False
            def getpeername(self):
                return (self.ip, 443)
            def close(self):
                self.closed = True

        interno = _FakeSock("10.0.0.5")
        with self.assertRaises(OSError):
            _verifica_peer(interno)
        self.assertTrue(interno.closed)  # socket chiuso

        pubblico = _FakeSock("1.1.1.1")
        _verifica_peer(pubblico)          # non solleva
        self.assertFalse(pubblico.closed)


if __name__ == "__main__":
    unittest.main()
