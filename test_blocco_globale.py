"""GUARDIA — KILL-SWITCH GLOBALE d'emergenza (fase191): congela i movimenti di denaro.

Prova che l'interruttore, quando ACCESO (via bunker/super-admin o via env), fa rispondere 503
'transazioni_sospese' agli endpoint che muovono denaro (book, rimborso), e che da SPENTO non
cambia nulla. Il toggle e' riservato al super-admin (bunker): un admin senza la 2a chiave e'
respinto 403. Vista ROSSA: senza la guardia, book ad interruttore acceso NON darebbe 503.
"""
import json
import os
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

IP = {"X-Forwarded-For": "203.0.113.7"}


class TestBloccoGlobale(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"h" * 32, db_payout=self.d + "/pay.db",
            db_finanza=self.d + "/fin.db", bunker_password="SuperPw@1"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak", base_url="https://x")
        self.bg = self.sis.blocco_globale
        self.g("POST", "/api/host/pubblica", {"host_id": "h", "slug": "casa", "titolo": "C",
               "citta": "Roma", "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
               "servizi": [], "immagini": []}, {"X-Host-Key": "hk"})

    def tearDown(self):
        os.environ.pop("BLOCCO_GLOBALE", None)
        shutil.rmtree(self.d, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _sessione_bunker(self):
        h = dict(IP); h["X-Admin-Key"] = "ak"
        s, out = self.g("POST", "/api/bunker/login", {"codice": "SuperPw@1"}, h)
        self.assertEqual(s, 200, out)
        return out["sessione"]

    def _book_status(self):
        # body JSON valido (non None) -> arriva alla guardia; senza freeze prosegue (non 503)
        return self.g("POST", "/api/concierge/book", {"quote_token": "x"})[0]

    # ── stato di partenza ──────────────────────────────────────────────
    def test_dormiente_di_default(self):
        self.assertFalse(self.bg.attivo())
        self.assertNotEqual(self._book_status(), 503, "a interruttore SPENTO book non deve dare 503")

    # ── accensione via bunker (super-admin) ────────────────────────────
    def test_toggle_solo_super_admin(self):
        # admin senza sessione bunker -> 403
        s, o = self.g("POST", "/api/bunker/blocco_globale", {"attivo": True},
                      {"X-Admin-Key": "ak", **IP})
        self.assertEqual(s, 403, o)
        self.assertFalse(self.bg.attivo(), "un 403 non deve aver acceso nulla")
        # con sessione bunker -> 200 e ACCESO
        sess = self._sessione_bunker()
        h = {"X-Admin-Key": "ak", "X-Bunker-Session": sess, **IP}
        s, o = self.g("POST", "/api/bunker/blocco_globale", {"attivo": True, "motivo": "incidente"}, h)
        self.assertEqual(s, 200, o)
        self.assertTrue(self.bg.attivo())
        # stato leggibile riporta il motivo
        s, st = self.g("GET", "/api/bunker/blocco_globale", None, h)
        self.assertEqual(s, 200); self.assertTrue(st["attivo"])
        self.assertEqual((st.get("dettaglio") or {}).get("motivo"), "incidente")
        # spegnimento
        s, o = self.g("POST", "/api/bunker/blocco_globale", {"attivo": False}, h)
        self.assertEqual(s, 200); self.assertFalse(self.bg.attivo())

    # ── effetto sui MOVIMENTI DI DENARO (vista ROSSA) ──────────────────
    def test_freeze_blocca_book_e_rimborso(self):
        self.assertNotEqual(self._book_status(), 503)     # prima: non bloccato
        self.bg.imposta(True, motivo="test")
        self.assertEqual(self._book_status(), 503, "book durante il freeze deve dare 503")
        # rimborso (admin+bunker) durante il freeze -> 503 anche con auth valida
        sess = self._sessione_bunker()
        h = {"X-Admin-Key": "ak", "X-Bunker-Session": sess, **IP}
        s, o = self.g("POST", "/api/admin/rimborso",
                      {"alloggio_id": "casa", "check_in": "2027-12-10",
                       "check_out": "2027-12-12", "idem_key": "k1"}, h)
        self.assertEqual(s, 503, "rimborso durante il freeze deve dare 503: %s" % (o,))
        self.assertEqual(o.get("errore"), "transazioni_sospese")
        # spegnimento -> book non piu' 503
        self.bg.imposta(False)
        self.assertNotEqual(self._book_status(), 503)

    # ── env autorevole (hard block server-level) ───────────────────────
    def test_env_hard_block(self):
        os.environ["BLOCCO_GLOBALE"] = "1"
        self.assertTrue(self.bg.attivo(), "env BLOCCO_GLOBALE=1 deve bloccare")
        self.assertEqual(self._book_status(), 503)
        os.environ["BLOCCO_GLOBALE"] = "0"
        self.assertFalse(self.bg.attivo())


if __name__ == "__main__":
    unittest.main(verbosity=2)
