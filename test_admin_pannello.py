"""
Test pannello admin — vista "Tutti gli annunci" (gestione per ID numerico) + cambio stato.
L'admin vede TUTTI gli annunci di TUTTI gli host (id numerico + host_id + valuta) e può
sospendere/ripubblicare qualsiasi annuncio. Tutto gated dalla X-Admin-Key.
"""
import json
import os
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE

SEG = b"S" * 32


class TestAdminPannello(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, con_registrazione_host=True,
            db_catalogo=f"{self.dir}/c.db", db_inventario=f"{self.dir}/i.db",
            db_registro_host=f"{self.dir}/r.db", db_accettazioni=f"{self.dir}/acc.db"))
        self.r = crea_router(self.sys, host_key="hk", admin_key="ak")
        self.AK = {"X-Admin-Key": "ak"}

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _host_pubblica(self, email, titolo, **extra):
        s, c = self.r.gestisci("POST", "/api/host/registrazione", body=json.dumps(
            {"email": email, "password": "passwordlunga", "accetta_termini": True,
             "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
             "versione": CONTRATTO_HOST_VERSIONE}))
        self.assertEqual(s, 201, c)
        tok, hid = c["token"], c["host_id"]
        corpo = {"titolo": titolo, "citta": "Roma", "prezzo_notte_cents": 9000, "capacita": 2}
        corpo.update(extra)
        s, p = self.r.gestisci("POST", "/api/host/pubblica",
                               headers={"X-Host-Token": tok}, body=json.dumps(corpo))
        self.assertEqual(s, 201, p)
        return hid, p["slug"]

    def test_admin_vede_tutti_gli_annunci_con_id_e_host(self):
        h1, s1 = self._host_pubblica("a@x.it", "Casa A")
        h2, s2 = self._host_pubblica("b@x.it", "Bangkok B", valuta="THB",
                                     prezzo_notte_cents=350000)
        s, d = self.r.gestisci("GET", "/api/admin/alloggi", headers=self.AK)
        self.assertEqual(s, 200, d)
        per_slug = {a["slug"]: a for a in d["alloggi"]}
        self.assertIn(s1, per_slug)
        self.assertIn(s2, per_slug)                       # annunci di host DIVERSI
        self.assertEqual(per_slug[s1]["host_id"], h1)
        self.assertEqual(per_slug[s2]["host_id"], h2)
        self.assertIsInstance(per_slug[s1]["id"], int)     # id numerico per la gestione
        self.assertEqual(per_slug[s2]["valuta"], "THB")    # valuta corretta

    def test_admin_alloggi_richiede_chiave(self):
        s, _ = self.r.gestisci("GET", "/api/admin/alloggi")            # niente chiave
        self.assertEqual(s, 401)
        s, _ = self.r.gestisci("GET", "/api/admin/alloggi",
                               headers={"X-Admin-Key": "sbagliata"})
        self.assertEqual(s, 401)

    def test_admin_sospende_e_ripubblica_qualsiasi_annuncio(self):
        _, slug = self._host_pubblica("c@x.it", "Casa C")
        s, r = self.r.gestisci("POST", "/api/admin/alloggio_stato", headers=self.AK,
                               body=json.dumps({"slug": slug, "stato": "sospeso"}))
        self.assertEqual(s, 200, r)
        _, d = self.r.gestisci("GET", "/api/admin/alloggi", headers=self.AK)
        a = next(x for x in d["alloggi"] if x["slug"] == slug)
        self.assertEqual(a["stato"], "sospeso")
        # non appare più nel catalogo pubblico
        s, cat = self.r.gestisci("GET", "/api/catalogo", {"citta": "Roma"})
        self.assertNotIn(slug, [x["slug"] for x in cat.get("risultati", [])])
        # ripubblica
        s, r = self.r.gestisci("POST", "/api/admin/alloggio_stato", headers=self.AK,
                               body=json.dumps({"slug": slug, "stato": "pubblicato"}))
        self.assertEqual(s, 200, r)

    def test_admin_stato_invalido_e_auth(self):
        _, slug = self._host_pubblica("d@x.it", "Casa D")
        s, _ = self.r.gestisci("POST", "/api/admin/alloggio_stato", headers=self.AK,
                               body=json.dumps({"slug": slug, "stato": "onlinee"}))
        self.assertEqual(s, 422)                           # stato non valido
        s, _ = self.r.gestisci("POST", "/api/admin/alloggio_stato",
                               body=json.dumps({"slug": slug, "stato": "sospeso"}))
        self.assertEqual(s, 401)                           # senza chiave admin


if __name__ == "__main__":
    unittest.main()
