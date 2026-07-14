"""
Collaudo — calendario MULTI-ALLOGGIO (vista d'insieme): con più alloggi l'host vede QUALE è
occupato in che data. GET /api/host/calendario_tutti -> per ogni SUO alloggio il calendario
(colori) nel range, con marcatura 'in_trattativa'. Solo i propri (host dal token).
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE


class TestCalendarioTutti(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{self.d}/c.db", db_inventario=f"{self.d}/i.db",
            db_registro_host=f"{self.d}/r.db", db_accettazioni=f"{self.d}/a.db"))
        self.r = crea_router(self.sys, host_key="hk")
        self.tok = self._reg("h@ct.it")
        for slug in ("uno", "due"):
            self.g("POST", "/api/host/pubblica",
                   {"slug": slug, "titolo": "Casa " + slug, "citta": "Roma",
                    "prezzo_notte_cents": 10000, "capacita": 2}, {"X-Host-Token": self.tok})
            for gg in ("2026-09-01", "2026-09-02"):
                self.sys.inventario.imposta_disponibilita(slug, gg, unita_totali=1,
                                                          prezzo_netto_cents=10000)
        # "uno" prenotato l'1/9; "due" resta libero -> l'host deve distinguere
        self.sys.inventario.blocca("uno", "2026-09-01", "2026-09-02", idem_key="b", origine="t")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _reg(self, email):
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": email, "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        return c["token"]

    def test_vista_insieme(self):
        s, d = self.g("GET", "/api/host/calendario_tutti", h={"X-Host-Token": self.tok},
                      q={"da": "2026-09-01", "a": "2026-09-03"})
        self.assertEqual(s, 200, d)
        per = {a["slug"]: {g["giorno"]: g["stato"] for g in a["giorni"]} for a in d["alloggi"]}
        self.assertEqual(set(per), {"uno", "due"})
        self.assertEqual(per["uno"]["2026-09-01"], "pieno")     # occupato
        self.assertEqual(per["due"]["2026-09-01"], "libero")    # libero -> l'host distingue
        # ogni alloggio ha il titolo (per la riga della griglia)
        self.assertTrue(all(a.get("titolo") for a in d["alloggi"]))

    def test_solo_i_propri_e_auth(self):
        s, _ = self.g("GET", "/api/host/calendario_tutti",
                      q={"da": "2026-09-01", "a": "2026-09-03"})
        self.assertEqual(s, 401)                                # senza auth
        s, _ = self.g("GET", "/api/host/calendario_tutti", h={"X-Host-Token": self.tok})
        self.assertEqual(s, 422)                                # date mancanti
        altro = self._reg("altro@ct.it")                        # host senza alloggi
        s, d = self.g("GET", "/api/host/calendario_tutti", h={"X-Host-Token": altro},
                      q={"da": "2026-09-01", "a": "2026-09-03"})
        self.assertEqual(s, 200)
        self.assertEqual(d["alloggi"], [])                      # vede solo i SUOI (nessuno)


if __name__ == "__main__":
    unittest.main(verbosity=2)
