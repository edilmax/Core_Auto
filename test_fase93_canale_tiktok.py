"""Test Fase 93 - Canale TikTok. fetch STUB: nessuna rete."""
import unittest

from fase90_marketing import GeneratoreContenuti
from fase93_canale_tiktok import CanaleTikTok, crea_canale_tiktok_da_env

POST = GeneratoreContenuti().crea("guest", "it")


class TestCanaleTikTok(unittest.TestCase):
    def test_pubblica_senza_video_false(self):
        c = CanaleTikTok("TOK", fetch=lambda *a, **k: {"data": {"publish_id": "1"}})
        self.assertFalse(c.pubblica(POST))                    # video-first

    def test_pubblica_video_ok(self):
        visti = {}
        c = CanaleTikTok("TOK", fetch=lambda url, data, headers:
                         visti.update(data=data, headers=headers)
                         or {"data": {"publish_id": "1"}})
        self.assertTrue(c.pubblica_video(POST, "https://x/v.mp4"))
        self.assertEqual(visti["headers"]["Authorization"], "Bearer TOK")
        self.assertEqual(visti["data"]["source_info"]["video_url"], "https://x/v.mp4")

    def test_gated(self):
        self.assertFalse(CanaleTikTok("").pubblica_video(POST, "https://x/v.mp4"))
        self.assertFalse(CanaleTikTok("TOK").pubblica_video(POST, ""))

    def test_isolato(self):
        def boom(*a, **k):
            raise RuntimeError("tk giu")
        self.assertFalse(CanaleTikTok("TOK", fetch=boom).pubblica_video(POST, "https://x/v"))

    def test_factory_env(self):
        self.assertIsNone(crea_canale_tiktok_da_env({}))
        self.assertIsNotNone(crea_canale_tiktok_da_env(
            {"TIKTOK_ACCESS_TOKEN": "t"}, fetch=lambda *a, **k: {}))


if __name__ == "__main__":
    unittest.main()
