"""Test Fase 92 - Canale X. fetch STUB: nessuna rete, credenziali fittizie."""
import unittest

from fase90_marketing import GeneratoreContenuti
from fase92_canale_x import CanaleX, crea_canale_x_da_env

POST = GeneratoreContenuti().crea("host", "it")
CRED = ("ck", "cs", "tok", "ts")


class TestCanaleX(unittest.TestCase):
    def test_pubblica_ok(self):
        visti = {}
        c = CanaleX(*CRED, fetch=lambda url, data, headers:
                    visti.update(data=data, headers=headers) or {"data": {"id": "1"}})
        self.assertTrue(c.pubblica(POST))
        self.assertIn("Authorization", visti["headers"])      # firma OAuth presente
        self.assertTrue(visti["headers"]["Authorization"].startswith("OAuth "))

    def test_troncamento_280(self):
        visti = {}
        lungo = type(POST)("host", "it", "x" * 500, (), "")     # testo 500 char
        CanaleX(*CRED, fetch=lambda url, data, headers:
                visti.update(data=data) or {"data": {"id": "1"}}).pubblica(lungo)
        self.assertEqual(len(visti["data"]["text"]), 280)

    def test_gated(self):
        self.assertFalse(CanaleX("", "", "", "").pubblica(POST))

    def test_isolato(self):
        def boom(*a, **k):
            raise RuntimeError("x giu")
        self.assertFalse(CanaleX(*CRED, fetch=boom).pubblica(POST))

    def test_factory_env(self):
        self.assertIsNone(crea_canale_x_da_env({}))
        env = {"X_API_KEY": "k", "X_API_SECRET": "s", "X_ACCESS_TOKEN": "t",
               "X_ACCESS_SECRET": "x"}
        self.assertIsNotNone(crea_canale_x_da_env(env, fetch=lambda *a, **k: {}))


if __name__ == "__main__":
    unittest.main()
