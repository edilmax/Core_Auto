"""GUARDIA — nuovi canali di marketing GRATUITI (Mastodon/Bluesky/Reddit): dormienti+gated,
pubblicazione corretta con fetch iniettato, robusti (malformato/errore -> False), cablati nella
factory. Vista ROSSA: senza credenziali il canale NON esiste (None) e NON pubblica."""
import unittest

from fase90_marketing import Post
from fase91_canali_social import crea_canali_da_env
from fase193_canale_mastodon import CanaleMastodon, crea_canale_mastodon_da_env
from fase194_canale_bluesky import CanaleBluesky, crea_canale_bluesky_da_env
from fase195_canale_reddit import CanaleReddit, crea_canale_reddit_da_env

POST = Post(tema="offerta", lingua="it", testo="Attico a Roma da 90€",
            hashtag=("#roma", "#viaggi"), link="https://bookinvip.com/a/roma")


class TestMastodon(unittest.TestCase):
    def test_gated_senza_env(self):
        self.assertIsNone(crea_canale_mastodon_da_env({}))

    def test_pubblica_ok(self):
        visti = {}
        def f(url, data, headers):
            visti["url"] = url; visti["data"] = data; visti["auth"] = headers.get("Authorization")
            return {"id": "123"}
        c = CanaleMastodon("mas.to", "TOK", fetch=f)
        self.assertTrue(c.pubblica(POST))
        self.assertTrue(visti["url"].endswith("/api/v1/statuses"))
        self.assertIn("Bearer TOK", visti["auth"])
        self.assertIn("bookinvip.com", visti["data"]["status"])   # link nel toot

    def test_malformato_e_errore_isolati(self):
        self.assertFalse(CanaleMastodon("mas.to", "T", fetch=lambda *a: {}).pubblica(POST))
        def boom(*a): raise RuntimeError("giu")
        self.assertFalse(CanaleMastodon("mas.to", "T", fetch=boom).pubblica(POST))


class TestBluesky(unittest.TestCase):
    def test_gated_senza_env(self):
        self.assertIsNone(crea_canale_bluesky_da_env({}))

    def test_pubblica_due_passi(self):
        chiamate = []
        def f(url, data, headers):
            chiamate.append(url)
            if url.endswith("createSession"):
                return {"accessJwt": "JWT", "did": "did:plc:abc"}
            return {"uri": "at://did/app.bsky.feed.post/1", "cid": "xxx"}
        c = CanaleBluesky("io.bsky.social", "app-pass", fetch=f,
                          orologio=lambda: "2027-01-01T00:00:00.000Z")
        self.assertTrue(c.pubblica(POST))
        self.assertTrue(any("createSession" in u for u in chiamate))
        self.assertTrue(any("createRecord" in u for u in chiamate))

    def test_sessione_fallita_no_post(self):
        c = CanaleBluesky("h", "p", fetch=lambda *a: {"error": "AuthError"})
        self.assertFalse(c.pubblica(POST))


class TestReddit(unittest.TestCase):
    def test_gated_senza_env(self):
        self.assertIsNone(crea_canale_reddit_da_env({}))

    def test_pubblica_token_poi_submit(self):
        chiamate = []
        def f(url, data, headers):
            chiamate.append(url)
            if "access_token" in url:
                return {"access_token": "TT"}
            return {"json": {"errors": []}}
        c = CanaleReddit("id", "sec", "user", "pw", "r/travel", fetch=f)
        self.assertTrue(c.pubblica(POST))
        self.assertTrue(any("access_token" in u for u in chiamate))
        self.assertTrue(any("submit" in u for u in chiamate))

    def test_errori_reddit_non_pubblicato(self):
        def f(url, data, headers):
            return {"access_token": "TT"} if "access_token" in url else {"json": {"errors": [["SUBREDDIT_NOTALLOWED", "no", "sr"]]}}
        self.assertFalse(CanaleReddit("i", "s", "u", "p", "sub", fetch=f).pubblica(POST))

    def test_senza_link_non_pubblica(self):
        senza_link = Post(tema="t", lingua="it", testo="x", hashtag=(), link="")
        self.assertFalse(CanaleReddit("i", "s", "u", "p", "sub", fetch=lambda *a: {}).pubblica(senza_link))


class TestFactory(unittest.TestCase):
    def test_factory_accende_i_gratuiti_con_env(self):
        env = {"MASTODON_INSTANCE": "mas.to", "MASTODON_TOKEN": "T",
               "BLUESKY_HANDLE": "h", "BLUESKY_APP_PASSWORD": "p",
               "REDDIT_CLIENT_ID": "i", "REDDIT_CLIENT_SECRET": "s",
               "REDDIT_USERNAME": "u", "REDDIT_PASSWORD": "pw", "REDDIT_SUBREDDIT": "r/x"}
        canali = crea_canali_da_env(env, fetch=lambda *a: {})
        for nome in ("mastodon", "bluesky", "reddit"):
            self.assertIn(nome, canali, "il canale %s non e' stato acceso dalla factory" % nome)

    def test_factory_vuota_senza_env(self):
        canali = crea_canali_da_env({}, fetch=lambda *a: {})
        for nome in ("mastodon", "bluesky", "reddit"):
            self.assertNotIn(nome, canali)


if __name__ == "__main__":
    unittest.main(verbosity=2)
