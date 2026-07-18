"""Collaudo SALA DI CONTROLLO Bunker (Incremento 4): integrità + log, sotto sessione Bunker.

Read-only, solo dal Bunker. Invarianti:
  1. /api/bunker/integrita: SENZA sessione -> 403; CON -> {catena, diagnosi}; se il giornale
     e' MANOMESSO la catena lo dice (ok=False + seq_rotta);
  2. /api/bunker/log: SENZA sessione -> 403; CON -> ultime N righe del log persistente,
     N clampato (1..300); righe presenti quando il log esiste;
  3. tutto gated: nessun accesso alla sala senza il 2° muro.
"""
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router


class TestSalaControllo(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.finanza_path = f"{d}/fin.db"
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"h" * 32, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_finanza=self.finanza_path, bunker_password="SuperPw@1"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak")
        # un movimento nel giornale (cosi' la catena ha qualcosa da verificare)
        self.sis.finanza.movimento(tipo="incasso", riferimento="R1", soggetto="host:h",
                                   importo_cents=1000, valuta="EUR", causale="t")
        # DATA_DIR -> temp, con un app.log finto per il test del log
        self._old_env = os.environ.get("DATA_DIR")
        os.environ["DATA_DIR"] = d
        with open(f"{d}/app.log", "w", encoding="utf-8") as f:
            f.write("2026-07-19 10:00:00 INFO core_auto.server avvio\n")
            f.write("2026-07-19 10:01:00 CRITICAL core_auto.server BUNKER: accesso NEGATO ip=1.2.3.4\n")

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = self._old_env
        shutil.rmtree(self.dir, ignore_errors=True)

    def _sessione(self):
        s, out = self.r.gestisci("POST", "/api/bunker/login", {},
                                 json.dumps({"codice": "SuperPw@1"}),
                                 {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9"})
        self.assertEqual(s, 200, out)
        return out["sessione"]

    def _h(self, sess=None):
        h = {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9"}
        if sess:
            h["X-Bunker-Session"] = sess
        return h

    def test_integrita_gated_e_catena(self):
        s, _ = self.r.gestisci("GET", "/api/bunker/integrita", {}, None, self._h())
        self.assertEqual(s, 403)                       # senza sessione
        sess = self._sessione()
        s, d = self.r.gestisci("GET", "/api/bunker/integrita", {}, None, self._h(sess))
        self.assertEqual(s, 200, d)
        self.assertTrue(d["catena"]["ok"])             # giornale integro
        self.assertIn("diagnosi", d)
        # MANOMISSIONE del giornale -> la sala la denuncia
        con = sqlite3.connect(self.finanza_path)
        con.execute("DROP TRIGGER lg_no_update")
        with con:
            con.execute("UPDATE libro_giornale SET importo_cents=9 WHERE seq=1")
        con.close()
        s, d = self.r.gestisci("GET", "/api/bunker/integrita", {}, None, self._h(sess))
        self.assertFalse(d["catena"]["ok"])
        self.assertEqual(d["catena"]["seq_rotta"], 1)

    def test_log_gated_e_righe(self):
        s, _ = self.r.gestisci("GET", "/api/bunker/log", {}, None, self._h())
        self.assertEqual(s, 403)                       # senza sessione
        sess = self._sessione()
        s, d = self.r.gestisci("GET", "/api/bunker/log", {"n": "50"}, None, self._h(sess))
        self.assertEqual(s, 200, d)
        self.assertIsInstance(d["righe"], list)
        testo = "\n".join(d["righe"])
        self.assertIn("BUNKER: accesso NEGATO", testo)  # gli eventi critici ci sono
        # clamp: n enorme -> non esplode
        s, d = self.r.gestisci("GET", "/api/bunker/log", {"n": "99999"}, None, self._h(sess))
        self.assertEqual(s, 200)
        self.assertLessEqual(len(d["righe"]), 300)


if __name__ == "__main__":
    unittest.main()
