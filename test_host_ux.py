"""
Test UX pannello host (semplificazione richiesta dal fondatore):
  - AUTO-ID: pubblicare SENZA slug -> il server genera uno slug pulito, numerato e UNIVOCO;
    due annunci con lo stesso titolo -> due slug diversi. L'host non digita mai un codice.
  - /api/host/alloggi ricavato dal TOKEN (niente host_id a mano) + espone l'id NUMERICO;
    il parametro host_id è ignorato (non puoi vedere gli alloggi altrui).
  - CANCELLA FOTO: caricata per sbaglio -> /api/host/foto_elimina la rimuove dal disco;
    path-safe (niente traversal), idempotente.
"""
import base64
import json
import os
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE

SEG = b"S" * 32
PNG1x1 = base64.b64encode(
    bytes.fromhex("89504e470d0a1a0a0000000d494844520000000100000001010300000025db56"
                  "ca00000003504c5445000000a77a3dda0000000149444154789c6360000002"
                  "00010005000601a5f645000000004945" + "4e44ae426082")).decode()


class TestHostUX(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.environ["UPLOAD_DIR"] = os.path.join(self.dir, "uploads")
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, con_registrazione_host=True,
            db_catalogo=f"{self.dir}/c.db", db_inventario=f"{self.dir}/i.db",
            db_registro_host=f"{self.dir}/r.db", db_accettazioni=f"{self.dir}/acc.db"))
        self.r = crea_router(self.sys, host_key="operatore")
        self.h = {"X-Host-Token": self._registra("mario@bnb.it")}

    def tearDown(self):
        os.environ.pop("UPLOAD_DIR", None)
        shutil.rmtree(self.dir, ignore_errors=True)

    def _registra(self, email):
        s, c = self.r.gestisci("POST", "/api/host/registrazione", body=json.dumps(
            {"email": email, "password": "passwordlunga", "ragione_sociale": "B&B",
             "accetta_termini": True, "accetta_clausole": True,
             "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE}))
        self.assertEqual(s, 201, c)
        return c["token"]

    def _pubblica(self, **extra):
        corpo = {"titolo": "Casa a Roma", "citta": "Roma", "prezzo_notte_cents": 9500,
                 "capacita": 4}
        corpo.update(extra)
        return self.r.gestisci("POST", "/api/host/pubblica", headers=self.h,
                               body=json.dumps(corpo))

    # ── AUTO-ID ───────────────────────────────────────────────────────────────
    def test_pubblica_senza_slug_genera_slug(self):
        s, c = self._pubblica()                       # NESSUNO slug fornito
        self.assertEqual(s, 201, c)
        self.assertTrue(c["slug"], "slug non generato")
        self.assertRegex(c["slug"], r"^[a-z0-9-]+$")  # pulito (url-safe)
        self.assertIn("casa", c["slug"])              # derivato dal titolo
        self.assertIsInstance(c.get("id"), int)       # id numerico per l'admin

    def test_due_titoli_uguali_slug_diversi(self):
        s1, c1 = self._pubblica()
        s2, c2 = self._pubblica()                     # stesso titolo -> slug DIVERSO (numerato)
        self.assertEqual((s1, s2), (201, 201))
        self.assertNotEqual(c1["slug"], c2["slug"], "collisione di slug!")
        # due alloggi distinti sotto lo stesso host
        _, miei = self.r.gestisci("GET", "/api/host/alloggi", {}, headers=self.h)
        self.assertEqual(len(miei["alloggi"]), 2)
        self.assertEqual(len({a["id"] for a in miei["alloggi"]}), 2)   # id numerici distinti

    def test_slug_esplicito_rispettato(self):
        s, c = self._pubblica(slug="villa-mare")
        self.assertEqual(c["slug"], "villa-mare")     # se lo fornisce, si rispetta

    def test_alloggi_dal_token_espone_id(self):
        self._pubblica()
        _, miei = self.r.gestisci("GET", "/api/host/alloggi", {}, headers=self.h)
        self.assertEqual(len(miei["alloggi"]), 1)
        a = miei["alloggi"][0]
        self.assertIsInstance(a["id"], int)
        self.assertIn("slug", a); self.assertIn("titolo", a)

    # ── CANCELLA FOTO ─────────────────────────────────────────────────────────
    def _carica_foto(self):
        s, c = self.r.gestisci("POST", "/api/host/upload_foto", headers=self.h,
                               body=json.dumps({"image_base64": PNG1x1}))
        self.assertEqual(s, 201, c)
        return c["url"]

    def test_foto_elimina_rimuove_file(self):
        url = self._carica_foto()
        nome = url.rsplit("/", 1)[-1]
        percorso = os.path.join(os.environ["UPLOAD_DIR"], nome)
        self.assertTrue(os.path.isfile(percorso))     # c'è
        s, c = self.r.gestisci("POST", "/api/host/foto_elimina", headers=self.h,
                               body=json.dumps({"url": url}))
        self.assertEqual(s, 200, c)
        self.assertTrue(c["eliminata"])
        self.assertFalse(os.path.isfile(percorso))    # sparito dal disco

    def test_foto_elimina_idempotente(self):
        url = self._carica_foto()
        self.r.gestisci("POST", "/api/host/foto_elimina", headers=self.h,
                        body=json.dumps({"url": url}))
        s, c = self.r.gestisci("POST", "/api/host/foto_elimina", headers=self.h,
                               body=json.dumps({"url": url}))
        self.assertEqual(s, 200)                       # ri-cancellare non è un errore

    def test_foto_elimina_path_traversal_bloccato(self):
        # crea un file "segreto" fuori dalla cartella upload
        segreto = os.path.join(self.dir, "segreto.txt")
        with open(segreto, "w") as f:
            f.write("dati")
        for cattivo in ("/uploads/../segreto.txt", "/uploads/../../etc/passwd",
                        "/etc/passwd", "../segreto.txt"):
            s, c = self.r.gestisci("POST", "/api/host/foto_elimina", headers=self.h,
                                   body=json.dumps({"url": cattivo}))
            self.assertIn(s, (200, 422))
        self.assertTrue(os.path.isfile(segreto), "traversal ha cancellato un file esterno!")

    def test_foto_elimina_richiede_auth(self):
        s, _ = self.r.gestisci("POST", "/api/host/foto_elimina",
                               body=json.dumps({"url": "/uploads/x.png"}))
        self.assertEqual(s, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
