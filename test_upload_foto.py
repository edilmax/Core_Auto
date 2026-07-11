"""Upload foto alloggio: base64 -> salva su UPLOAD_DIR -> URL /uploads/<nome>. Host-auth,
tipo dai magic bytes (mai fidarsi del content_type), tetto 5MB, fail-closed."""
import base64
import json
import os
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGA"
       "hKmMIQAAAABJRU5ErkJggg==")
HK = {"X-Host-Key": "hk"}


class TestUploadFoto(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.up = tempfile.mkdtemp()
        os.environ["UPLOAD_DIR"] = self.up
        d = self.dir
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"z" * 32, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db",
            db_messaggi=f"{d}/m.db", file_referral=f"{d}/ref.json"))
        self.r = crea_router(self.sis, host_key="hk")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        shutil.rmtree(self.up, ignore_errors=True)
        os.environ.pop("UPLOAD_DIR", None)

    def g(self, body, h=None):
        return self.r.gestisci("POST", "/api/host/upload_foto", {},
                               json.dumps(body), h or {})

    def test_richiede_auth(self):
        s, _ = self.g({"image_base64": PNG})
        self.assertEqual(s, 401)

    def test_png_ok_salva_e_url(self):
        s, d = self.g({"image_base64": PNG}, HK)
        self.assertEqual(s, 201)
        self.assertTrue(d["url"].startswith("/uploads/"))
        self.assertTrue(d["url"].endswith(".png"))
        self.assertTrue(os.path.isfile(os.path.join(self.up, d["url"].split("/")[-1])))

    def test_data_uri_ok(self):
        s, d = self.g({"image_base64": "data:image/png;base64," + PNG}, HK)
        self.assertEqual(s, 201)

    def test_base64_invalido(self):
        s, _ = self.g({"image_base64": "@@@non-base64@@@"}, HK)
        self.assertEqual(s, 422)

    def test_non_immagine_rifiutata(self):
        s, _ = self.g({"image_base64": base64.b64encode(b"ciao mondo").decode()}, HK)
        self.assertEqual(s, 422)      # byte non di un formato immagine supportato

    def test_troppo_grande(self):
        big = base64.b64encode(b"\xff\xd8\xff" + b"x" * (5 * 1024 * 1024)).decode()
        s, _ = self.g({"image_base64": big}, HK)
        self.assertEqual(s, 422)


if __name__ == "__main__":
    unittest.main()
