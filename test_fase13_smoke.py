"""Smoke test fase13 (fortezza legacy Flask): chiude l'ultimo gap di copertura.
Testa le primitive PURE (HMAC, nonce anti-replay, rate-limit, singleton) senza app Flask.
Salta con grazia se le dipendenze legacy (flask/psutil/requests) non sono installate."""
import sqlite3
import unittest

try:
    import fase13_protocollo_finale as F
    DISPONIBILE = True
except Exception:
    DISPONIBILE = False


@unittest.skipUnless(DISPONIBILE, "fase13 (stack legacy Flask) non importabile in questo ambiente")
class TestFase13Smoke(unittest.TestCase):
    def test_canonical_string_deterministico(self):
        a = F._canonical_string(["x", 1, "y"])
        b = F._canonical_string(["x", 1, "y"])
        self.assertIsInstance(a, bytes)
        self.assertEqual(a, b)
        self.assertNotEqual(a, F._canonical_string(["x", 2, "y"]))

    def test_hmac_firma_e_verifica(self):
        ts = "1700000000"
        sig = F.SecurityManager.generate_signature("payload", ts)
        self.assertTrue(F.SecurityManager.verify_signature("payload", ts, sig))
        self.assertFalse(F.SecurityManager.verify_signature("payloadX", ts, sig))  # tamper
        self.assertFalse(F.SecurityManager.verify_signature("payload", ts, sig + "00"))

    def test_nonce_anti_replay(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE nonce_usati (nonce TEXT PRIMARY KEY, expires_at INTEGER)")
        sm = F.SecurityManager()
        self.assertTrue(sm.is_nonce_valid("n1", conn=con))      # prima volta -> ok
        self.assertFalse(sm.is_nonce_valid("n1", conn=con))     # replay -> rifiutato

    def test_rate_limiter_allow_then_stats(self):
        rl = F.RateLimiter()
        ok, info = rl.is_allowed("1.2.3.4")
        self.assertTrue(ok)
        self.assertIsInstance(info, dict)
        self.assertIsInstance(rl.get_stats("1.2.3.4"), dict)

    def test_singleton_security_e_ratelimiter(self):
        self.assertIs(F.get_security_manager(), F.get_security_manager())
        self.assertIs(F.get_rate_limiter(), F.get_rate_limiter())

    def test_timestamp_window(self):
        import time
        now = str(int(time.time()))
        self.assertTrue(F.SecurityManager.is_timestamp_valid(now))
        self.assertFalse(F.SecurityManager.is_timestamp_valid("1000000000"))  # vecchio


if __name__ == "__main__":
    unittest.main()
