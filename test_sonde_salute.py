"""
SONDE DI SALUTE (fase83): /api/health/live · /api/health/ready · /api/health/db.

Production-grade: un orchestratore/monitor deve distinguere "processo VIVO ma non pronto"
da "processo MORTO", e sapere se gli archivi sono raggiungibili — senza credenziali.

Rossi sul vecchio: prima queste 3 rotte non esistevano (404). READ-ONLY.
Test con sistema VERO (crea_sistema + RouterHTTP), archivi su file temporanei.
"""
import os
import tempfile
import unittest

import fase83_server
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema


def _router(dir_, *, abilitato=True, db_finanza=None):
    cfg = ConfigCasaVIP(
        abilitato=abilitato, segreto_hmac=b"h" * 32,
        db_catalogo=f"{dir_}/c.db", db_inventario=f"{dir_}/i.db",
        db_registro_host=f"{dir_}/r.db",
        db_finanza=db_finanza or f"{dir_}/fin.db")
    return fase83_server.RouterHTTP(crea_sistema(cfg))


class TestSondeSalute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.router = _router(cls.dir)

    # --- LIVENESS ---
    def test_live_200(self):
        s, c = self.router.gestisci("GET", "/api/health/live")
        self.assertEqual(s, 200)
        self.assertEqual(c["status"], "live")

    def test_live_risponde_ANCHE_a_sistema_spento(self):
        # IL punto delle sonde separate: la liveness bypassa il gate 'sistema_spento' (503).
        d2 = tempfile.mkdtemp()
        r2 = _router(d2, abilitato=False)
        self.assertEqual(r2.gestisci("GET", "/api/health/live")[0], 200)          # VIVO
        self.assertEqual(r2.gestisci("GET", "/api/health/ready")[0], 503)         # NON pronto
        self.assertEqual(r2.gestisci("GET", "/api/health/ready")[1]["status"], "not_ready")
        self.assertEqual(r2.gestisci("GET", "/api/health")[0], 503)               # la vecchia: spenta

    # --- READINESS ---
    def test_ready_200_se_attivo(self):
        s, c = self.router.gestisci("GET", "/api/health/ready")
        self.assertEqual(s, 200)
        self.assertEqual(c["status"], "ready")

    # --- DB HEALTH ---
    def test_db_200_elenca_archivi_ok(self):
        s, c = self.router.gestisci("GET", "/api/health/db")
        self.assertEqual(s, 200)
        self.assertEqual(c["status"], "ok")
        self.assertIn("db_finanza", c["db"])
        self.assertTrue(all(v == "ok" for v in c["db"].values()), c["db"])
        # gli archivi :memory: NON compaiono (saltati di proposito)
        self.assertTrue(all(isinstance(k, str) and k.startswith("db_") for k in c["db"]))

    def test_db_degradato_se_archivio_illeggibile(self):
        # un file che NON e' un database sqlite -> PRAGMA schema_version fallisce -> ERRORE isolato
        d3 = tempfile.mkdtemp()
        bad = f"{d3}/fin.db"
        with open(bad, "wb") as f:
            f.write(b"QUESTO NON E' UN DATABASE SQLITE" * 20)
        r3 = _router(d3, db_finanza=bad)
        s, c = r3.gestisci("GET", "/api/health/db")
        self.assertEqual(c["db"].get("db_finanza"), "ERRORE")
        self.assertEqual(s, 503)
        self.assertEqual(c["status"], "degraded")

    def test_db_read_only_non_scrive(self):
        # due giri: la sonda non deve creare/alterare nulla (e' sola lettura)
        prima = sorted(os.listdir(self.dir))
        self.router.gestisci("GET", "/api/health/db")
        self.router.gestisci("GET", "/api/health/db")
        self.assertEqual(sorted(os.listdir(self.dir)), prima)


if __name__ == "__main__":
    unittest.main()
