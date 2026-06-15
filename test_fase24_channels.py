"""
Test FASE 24 / BLOCCO 4 - Channel Adapters (tentacoli social).

Copre: registry/routing, fail-safe (canale ignoto, adapter che solleva),
delivery-id stabile, adapter stub/telegram non configurato, e l'integrazione
end-to-end con l'Outbox (consegna -> completed; canale rotto -> DLQ; concorrenza).
"""
import os
import shutil
import tempfile
import time
import unittest

from fase24_channels import (ChannelRegistry, StubChannelAdapter, ChannelMessage,
                             TelegramAdapter, collega_a_outbox, pubblica_messaggio,
                             TOPIC_CHANNEL_SEND)
from fase16_outbox import OutboxPublisher, OutboxDispatcher, _connessione


class TestRegistry(unittest.TestCase):
    """Routing e fail-safe del registry (nessun DB richiesto)."""

    def setUp(self):
        self.reg = ChannelRegistry()
        self.wa = StubChannelAdapter("whatsapp")
        self.ig = StubChannelAdapter("instagram")
        self.reg.register(self.wa)
        self.reg.register(self.ig)

    def test_register_get_channels(self):
        self.assertEqual(set(self.reg.channels()), {"whatsapp", "instagram"})
        self.assertIs(self.reg.get("whatsapp"), self.wa)

    def test_register_senza_nome(self):
        with self.assertRaises(ValueError):
            self.reg.register(StubChannelAdapter(""))

    def test_routing_canale_corretto(self):
        ok = self.reg.deliver({"channel": "whatsapp", "recipient": "+39", "text": "ciao"})
        self.assertTrue(ok)
        self.assertEqual(len(self.wa.sent), 1)
        self.assertEqual(self.wa.sent[0].text, "ciao")
        self.assertEqual(len(self.ig.sent), 0)

    def test_canale_ignoto_failsafe(self):
        self.assertFalse(self.reg.deliver({"channel": "tiktok", "text": "x"}))

    def test_adapter_che_solleva_failsafe(self):
        class _Boom(StubChannelAdapter):
            def send(self, m):
                raise RuntimeError("kaboom")
        self.reg.register(_Boom("boom"))
        self.assertFalse(self.reg.deliver({"channel": "boom", "text": "x"}))

    def test_delivery_id_propagato(self):
        self.reg.deliver({"channel": "whatsapp", "text": "x",
                          "_outbox": {"message_id": 42}})
        self.assertEqual(self.wa.sent[-1].metadata.get("delivery_id"), "outbox-42")

    def test_stub_fail(self):
        s = StubChannelAdapter("k", fail=True)
        self.assertFalse(s.send(ChannelMessage("k", "r", "t")))

    def test_telegram_non_configurato_noop(self):
        # Senza TELEGRAM_BOT_TOKEN, l'adapter considera consegnato (no DLQ in dev).
        self.assertTrue(TelegramAdapter().send(ChannelMessage("telegram", "", "hi")))


class TestOutboxIntegrazione(unittest.TestCase):
    """End-to-end: pubblicazione -> Outbox -> canale (con fail-safe ereditato)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "ch.db")
        os.environ["CORE_AUTO_DB"] = self.db
        OutboxPublisher._reset_instance()
        self.pub = OutboxPublisher(self.db)
        self.disp = OutboxDispatcher(self.db, poll=0.05, batch=10)
        self.reg = ChannelRegistry()
        self.wa = StubChannelAdapter("whatsapp")
        self.reg.register(self.wa)
        collega_a_outbox(self.disp, self.reg)

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

    def _status(self, mid):
        return self._row(mid)["status"]

    def test_end_to_end_consegna(self):
        mid = pubblica_messaggio(self.pub, "whatsapp", "+391234", "via outbox")
        self.disp._process(self._row(mid))
        self.assertEqual(self._status(mid), "completed")
        self.assertEqual(self.wa.sent[-1].text, "via outbox")
        self.assertEqual(self.wa.sent[-1].metadata.get("delivery_id"), f"outbox-{mid}")

    def test_canale_rotto_finisce_in_dlq(self):
        class _Boom(StubChannelAdapter):
            def send(self, m):
                raise RuntimeError("kaboom")
        self.reg.register(_Boom("boom"))
        mid = pubblica_messaggio(self.pub, "boom", "x", "fail", max_retries=1)
        self.disp._process(self._row(mid))
        self.assertEqual(self._status(mid), "dead_letter")

    def test_partition_key_e_topic(self):
        mid = pubblica_messaggio(self.pub, "whatsapp", "r", "t")
        row = self._row(mid)
        self.assertEqual(row["topic"], TOPIC_CHANNEL_SEND)
        self.assertEqual(row["partition_key"], "whatsapp")

    def test_concorrenza_molti_messaggi(self):
        for i in range(6):
            pubblica_messaggio(self.pub, "whatsapp", f"r{i}", f"m{i}")
        self.disp.start()
        try:
            deadline = time.time() + 5
            while time.time() < deadline:
                if self.disp.status().get("completed", 0) >= 6:
                    break
                time.sleep(0.05)
        finally:
            self.disp.stop()
        self.assertEqual(self.disp.status().get("completed", 0), 6)
        self.assertEqual(len(self.wa.sent), 6)


if __name__ == "__main__":
    unittest.main()
