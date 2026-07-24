"""GUARDIA — Cambio valuta nel SUPER-ADMIN (bunker): stato + refresh, READ-only, gated.

Prova che il pannello super-admin espone lo stato del convertitore OXR (fase99) e puo' forzarne
il rinfresco, ma SOLO col super-admin (bunker); la chiave OXR resta un segreto (mai nell'output).
Vista ROSSA: senza sessione bunker gli endpoint danno 403 (non 200)."""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase99_multicurrency import crea_provider_tassi

IP = {"X-Forwarded-For": "203.0.113.9"}
RATES = {"EUR": 0.90, "GBP": 0.80, "JPY": 150.0}


class TestBunkerCambioValuta(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"h" * 32, db_payout=self.d + "/pay.db",
            bunker_password="SuperPw@1"))
        # inietta un provider tassi DETERMINISTICO (nessuna rete)
        self.sis.tassi = crea_provider_tassi("KEY", fetch=lambda url: {"rates": dict(RATES)})
        self.sis.tassi.aggiorna()
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak", base_url="https://x")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _sess(self):
        h = dict(IP); h["X-Admin-Key"] = "ak"
        s, out = self.g("POST", "/api/bunker/login", {"codice": "SuperPw@1"}, h)
        self.assertEqual(s, 200, out)
        return {"X-Admin-Key": "ak", "X-Bunker-Session": out["sessione"], **IP}

    def test_stato_richiede_super_admin(self):
        s, o = self.g("GET", "/api/bunker/cambio_valuta", None, {"X-Admin-Key": "ak", **IP})
        self.assertEqual(s, 403, o)              # senza sessione bunker -> negato
        s, o = self.g("POST", "/api/bunker/cambio_valuta/aggiorna", None, {"X-Admin-Key": "ak", **IP})
        self.assertEqual(s, 403, o)

    def test_stato_e_campioni_col_super_admin(self):
        h = self._sess()
        s, o = self.g("GET", "/api/bunker/cambio_valuta", None, h)
        self.assertEqual(s, 200, o)
        self.assertTrue(o.get("configurato"))
        self.assertFalse(o.get("mai_riuscito"))
        self.assertIn("EUR->USD", o.get("campioni", {}))     # tassi campione presenti
        # la CHIAVE OXR non deve MAI comparire nell'output (segreto)
        self.assertNotIn("KEY", json.dumps(o))
        self.assertNotIn("app_id", json.dumps(o).lower())

    def test_refresh_forza_aggiornamento(self):
        h = self._sess()
        s, o = self.g("POST", "/api/bunker/cambio_valuta/aggiorna", None, h)
        self.assertEqual(s, 200, o)
        self.assertTrue(o.get("aggiornato"), "il refresh deve rinfrescare i tassi iniettati")

    def test_convertitore_spento_non_rompe(self):
        self.sis.tassi = None
        h = self._sess()
        s, o = self.g("GET", "/api/bunker/cambio_valuta", None, h)
        self.assertEqual(s, 200, o)               # spento: risposta pulita, non crash
        self.assertFalse(o.get("configurato"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
