"""
Test Fase 91 - Canali social reali. fetch STUB: nessuna rete, nessuna credenziale vera.
"""
import unittest

from fase90_marketing import GeneratoreContenuti
from fase91_canali_social import (
    CanaleMetaGraph, CanaleTelegram, crea_canali_da_env,
)

POST = GeneratoreContenuti().crea("host", "it")


class TestTelegram(unittest.TestCase):
    def test_pubblica_ok(self):
        visti = {}
        c = CanaleTelegram("TOK", "@canale",
                           fetch=lambda url, data=None: visti.update(url=url, data=data)
                           or {"ok": True})
        self.assertTrue(c.pubblica(POST))
        self.assertIn("botTOK/sendMessage", visti["url"])
        self.assertEqual(visti["data"]["chat_id"], "@canale")

    def test_gated_senza_token(self):
        self.assertFalse(CanaleTelegram("", "@c").pubblica(POST))

    def test_isolato(self):
        def boom(url, data=None):
            raise RuntimeError("tg giu")
        self.assertFalse(CanaleTelegram("T", "@c", fetch=boom).pubblica(POST))


class TestMeta(unittest.TestCase):
    def test_fb_feed(self):
        visti = {}
        c = CanaleMetaGraph("PAGE", "PTOK",
                            fetch=lambda url, data=None: visti.update(url=url, data=data)
                            or {"id": "123_456"})
        self.assertTrue(c.pubblica(POST))
        self.assertIn("/PAGE/feed", visti["url"])
        self.assertEqual(visti["data"]["access_token"], "PTOK")
        self.assertIn("message", visti["data"])

    def test_ig_due_passi(self):
        chiamate = []
        def fk(url, data=None):
            chiamate.append(url)
            return {"id": "container" if url.endswith("/media") else "pubblicato"}
        c = CanaleMetaGraph("PAGE", "PTOK", ig_user_id="IG1", fetch=fk)
        self.assertTrue(c.pubblica_instagram(POST, "https://bookinvip.com/card.png"))
        self.assertTrue(chiamate[0].endswith("/IG1/media"))           # container
        self.assertTrue(chiamate[1].endswith("/IG1/media_publish"))   # publish

    def test_ig_senza_image_url(self):
        c = CanaleMetaGraph("P", "T", ig_user_id="IG1", fetch=lambda *a, **k: {"id": "x"})
        self.assertFalse(c.pubblica_instagram(POST, ""))

    def test_gated(self):
        self.assertFalse(CanaleMetaGraph("", "").pubblica(POST))


class TestFactoryEnv(unittest.TestCase):
    def test_solo_configurati(self):
        env = {"TELEGRAM_BOT_TOKEN": "T", "TELEGRAM_CHAT_ID": "@c"}
        canali = crea_canali_da_env(env, fetch=lambda *a, **k: {"ok": True, "id": "1"})
        self.assertIn("telegram", canali)
        self.assertNotIn("meta", canali)                              # meta non configurato

    def test_meta_configurato(self):
        env = {"META_PAGE_ID": "P", "META_PAGE_TOKEN": "T"}
        canali = crea_canali_da_env(env, fetch=lambda *a, **k: {"id": "1"})
        self.assertIn("meta", canali)

    def test_vuoto(self):
        self.assertEqual(crea_canali_da_env({}), {})


if __name__ == "__main__":
    unittest.main()
