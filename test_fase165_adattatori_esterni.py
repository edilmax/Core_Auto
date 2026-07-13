"""
Test Fase 165 - Adattatori esterni (Groq/Gemini testo, Pollinations immagini, YouTube video).
Tutto con `fetch` INIETTATO: nessuna rete, nessuna chiave reale. Copre successo, quota->
QuotaEsaurita (rotazione), errori->None, gating da chiave, refresh token YouTube, e
l'integrazione col pool a rotazione (fase164).
"""
import unittest

from fase164_pool_ai import QuotaEsaurita
from fase165_adattatori_esterni import (
    AdattatoreGemini, AdattatoreGroq, AdattatorePollinations, AdattatoreYouTube,
    crea_pool_immagine_da_env, crea_pool_testo_da_env, crea_youtube_da_env,
)


def _fetch_finto(mappa):
    """Ritorna un fetch che, in base a una sottostringa dell'URL, dà (status, obj).
    Registra le chiamate in .chiamate."""
    reg = {"chiamate": []}
    def fetch(url, *, metodo="GET", intestazioni=None, corpo=None, timeout=30.0):
        reg["chiamate"].append({"url": url, "metodo": metodo, "corpo": corpo,
                                "intestazioni": intestazioni or {}})
        for chiave, risposta in mappa.items():
            if chiave in url:
                return risposta() if callable(risposta) else risposta
        return 0, None
    fetch.reg = reg
    return fetch


class TestGroq(unittest.TestCase):
    def test_successo(self):
        f = _fetch_finto({"groq.com": (200, {"choices": [{"message": {"content": "Ciao dal post"}}]})})
        a = AdattatoreGroq("KEY", fetch=f)
        self.assertEqual(a.genera_testo("scrivi un post"), "Ciao dal post")
        # ha mandato Authorization Bearer + POST
        c = f.reg["chiamate"][0]
        self.assertEqual(c["metodo"], "POST")
        self.assertIn("Bearer KEY", c["intestazioni"].get("Authorization", ""))

    def test_quota_solleva(self):
        f = _fetch_finto({"groq.com": (429, {"error": "rate"})})
        with self.assertRaises(QuotaEsaurita):
            AdattatoreGroq("KEY", fetch=f).genera_testo("x")

    def test_errore_none(self):
        f = _fetch_finto({"groq.com": (500, {"error": "server"})})
        self.assertIsNone(AdattatoreGroq("KEY", fetch=f).genera_testo("x"))

    def test_senza_chiave_none(self):
        f = _fetch_finto({"groq.com": (200, {"choices": [{"message": {"content": "x"}}]})})
        self.assertIsNone(AdattatoreGroq("", fetch=f).genera_testo("x"))
        self.assertEqual(f.reg["chiamate"], [])           # nemmeno chiama la rete


class TestGemini(unittest.TestCase):
    def test_successo(self):
        f = _fetch_finto({"generativelanguage": (200, {"candidates": [
            {"content": {"parts": [{"text": "Testo Gemini"}]}}]})})
        self.assertEqual(AdattatoreGemini("K", fetch=f).genera_testo("ciao"), "Testo Gemini")

    def test_quota_resource_exhausted(self):
        f = _fetch_finto({"generativelanguage": (200, {"error": {"status": "RESOURCE_EXHAUSTED"}})})
        with self.assertRaises(QuotaEsaurita):
            AdattatoreGemini("K", fetch=f).genera_testo("x")

    def test_quota_429(self):
        f = _fetch_finto({"generativelanguage": (429, {})})
        with self.assertRaises(QuotaEsaurita):
            AdattatoreGemini("K", fetch=f).genera_testo("x")


class TestPollinations(unittest.TestCase):
    def test_url_immagine(self):
        a = AdattatorePollinations()
        u = a.genera_immagine("casa a roma vista mare")
        self.assertTrue(u.startswith("https://image.pollinations.ai/prompt/"))
        self.assertIn("width=1080", u)
        self.assertIn("casa", u)                          # prompt url-encoded nel path

    def test_prompt_vuoto_none(self):
        self.assertIsNone(AdattatorePollinations().genera_immagine(""))


class TestYouTube(unittest.TestCase):
    def test_upload_successo(self):
        f = _fetch_finto({"upload/youtube": (200, {"id": "VID123"})})
        yt = AdattatoreYouTube(access_token="TOK", fetch=f)
        out = yt.pubblica_video(b"\x00\x01video", titolo="Il mio video", privacy="public")
        self.assertEqual(out, {"video_id": "VID123", "url": "https://youtu.be/VID123"})
        c = f.reg["chiamate"][0]
        self.assertIn("multipart/related", c["intestazioni"].get("Content-Type", ""))
        self.assertIn("Bearer TOK", c["intestazioni"].get("Authorization", ""))

    def test_senza_token_ne_refresh_none(self):
        f = _fetch_finto({})
        self.assertIsNone(AdattatoreYouTube(fetch=f).pubblica_video(b"v", titolo="t"))
        self.assertEqual(f.reg["chiamate"], [])

    def test_refresh_ottiene_token(self):
        f = _fetch_finto({"oauth2.googleapis.com/token": (200, {"access_token": "NUOVO"}),
                          "upload/youtube": (200, {"id": "V9"})})
        yt = AdattatoreYouTube(client_id="cid", client_secret="sec",
                               refresh_token="rt", fetch=f)
        out = yt.pubblica_video(b"video", titolo="t")
        self.assertEqual(out["video_id"], "V9")
        urls = [c["url"] for c in f.reg["chiamate"]]
        self.assertTrue(any("oauth2" in u for u in urls))  # ha rinfrescato il token
        self.assertTrue(any("upload/youtube" in u for u in urls))

    def test_401_rinnova_e_riprova(self):
        stato = {"n": 0}
        def upload():
            stato["n"] += 1
            return (401, {"error": "expired"}) if stato["n"] == 1 else (200, {"id": "OK2"})
        f = _fetch_finto({"oauth2.googleapis.com/token": (200, {"access_token": "T2"}),
                          "upload/youtube": upload})
        yt = AdattatoreYouTube(access_token="vecchio", client_id="c", client_secret="s",
                               refresh_token="r", fetch=f)
        out = yt.pubblica_video(b"v", titolo="t")
        self.assertEqual(out["video_id"], "OK2")           # dopo il 401 ha rinnovato e ripubblicato


class TestFactory(unittest.TestCase):
    def test_pool_testo_gating(self):
        f = _fetch_finto({})
        vuoto = crea_pool_testo_da_env({}, fetch=f)
        self.assertFalse(vuoto.genera("x")["ok"])          # nessuna chiave -> nessun provider
        uno = crea_pool_testo_da_env({"GROQ_API_KEY": "k"}, fetch=f)
        self.assertEqual(len(uno.stato()["provider"]), 1)
        due = crea_pool_testo_da_env({"GROQ_API_KEY": "k", "GEMINI_API_KEY": "g"}, fetch=f)
        self.assertEqual([p["nome"] for p in due.stato()["provider"]], ["groq", "gemini"])

    def test_pool_testo_rotazione_su_quota(self):
        # Groq esaurito -> il pool passa a Gemini (l'idea della rotazione)
        f = _fetch_finto({"groq.com": (429, {}),
                          "generativelanguage": (200, {"candidates": [
                              {"content": {"parts": [{"text": "da gemini"}]}}]})})
        pool = crea_pool_testo_da_env({"GROQ_API_KEY": "k", "GEMINI_API_KEY": "g"}, fetch=f)
        out = pool.genera({"prompt": "scrivi"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["provider"], "gemini")
        self.assertEqual(out["risultato"], "da gemini")
        self.assertEqual(out["tentati"], ["groq", "gemini"])

    def test_pool_immagine_ha_sempre_pollinations(self):
        pool = crea_pool_immagine_da_env({}, fetch=_fetch_finto({}))
        out = pool.genera("tramonto")
        self.assertTrue(out["ok"])
        self.assertEqual(out["provider"], "pollinations")
        self.assertTrue(out["risultato"].startswith("https://image.pollinations.ai/"))

    def test_youtube_gating(self):
        self.assertIsNone(crea_youtube_da_env({}))
        self.assertIsNotNone(crea_youtube_da_env({"YT_ACCESS_TOKEN": "t"}))
        self.assertIsNotNone(crea_youtube_da_env(
            {"YT_CLIENT_ID": "c", "YT_CLIENT_SECRET": "s", "YT_REFRESH_TOKEN": "r"}))


class TestUserAgent(unittest.TestCase):
    def test_user_agent_default_e_override(self):
        import urllib.request
        from fase165_adattatori_esterni import _fetch_reale
        catturati = {}

        class _Resp:
            status = 200
            def read(self):
                return b'{"ok": true}'
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            catturati["ua"] = req.get_header("User-agent")
            return _Resp()

        orig = urllib.request.urlopen
        urllib.request.urlopen = fake_urlopen
        try:
            st, obj = _fetch_reale("https://x/y")
            self.assertEqual(st, 200)
            self.assertIn("BookinVIP", catturati["ua"] or "")     # UA di default anti-Cloudflare
            _fetch_reale("https://x/y", intestazioni={"User-Agent": "Custom/9"})
            self.assertEqual(catturati["ua"], "Custom/9")          # override rispettato
        finally:
            urllib.request.urlopen = orig


if __name__ == "__main__":
    unittest.main()
