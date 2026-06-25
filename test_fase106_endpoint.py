"""Test rotta /api/host/prezzo_suggerito (fase106 cablato in fase83). Puro via gestisci."""
import unittest

from fase83_server import crea_router


class Sys:
    attivo = True
    registro_host = None


H = {"X-Host-Key": "hk"}


def _r():
    return crea_router(Sys(), host_key="hk")


class TestPrezzoSuggerito(unittest.TestCase):
    def test_calcolo(self):
        s, c = _r().gestisci("GET", "/api/host/prezzo_suggerito",
                             {"prezzo_base_cents": "10000", "occupazione_bps": "9000",
                              "data": "2026-08-08"}, None, H)
        self.assertEqual(s, 200)
        self.assertIn("prezzo_cents", c)
        self.assertGreater(c["prezzo_cents"], 10000)        # domanda alta + agosto -> su

    def test_base_invalido(self):
        s, _ = _r().gestisci("GET", "/api/host/prezzo_suggerito",
                             {"prezzo_base_cents": "0"}, None, H)
        self.assertEqual(s, 422)

    def test_query_non_numerica_default(self):
        s, c = _r().gestisci("GET", "/api/host/prezzo_suggerito",
                             {"prezzo_base_cents": "10000", "occupazione_bps": "x"}, None, H)
        self.assertEqual(s, 200)
        self.assertIsInstance(c["prezzo_cents"], int)

    def test_unauth(self):
        s, _ = _r().gestisci("GET", "/api/host/prezzo_suggerito",
                             {"prezzo_base_cents": "10000"}, None, {})
        self.assertEqual(s, 401)


if __name__ == "__main__":
    unittest.main()
