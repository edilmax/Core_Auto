"""PASSWORD DIMENTICATA + CAMBIA PASSWORD host (C2 mega-audit 2026-07-20).

Prima: NESSUN reset -> l'host che dimenticava la password era chiuso fuori PER SEMPRE
(email UNIQUE: nemmeno ri-registrarsi; nemmeno l'admin poteva aiutare). Guardie:
  - magic-link firmato 30 min, SINGLE-USE (impronta dell'hash: cambiata la password,
    ogni link in circolazione muore);
  - endpoint anti-enumerazione: SEMPRE 200, email inviata solo se l'account esiste;
  - throttle 60s per email (niente grandinate);
  - login con la nuova password OK, con la vecchia RIFIUTATO;
  - cambia_password (rotazione volontaria) con vecchia verificata;
  - email di benvenuto alla registrazione (fa emergere subito un refuso nell'email).
"""
import json
import os
import shutil
import tempfile
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256


class _EmailFinta:
    def __init__(self):
        self.inviate = []

    def invia(self, destinatario, oggetto, corpo_html):
        self.inviate.append({"a": destinatario, "ogg": oggetto, "html": corpo_html})
        return True


class TestPasswordResetHost(unittest.TestCase):
    def setUp(self):
        self.dir = d = tempfile.mkdtemp()
        os.environ["UPLOAD_DIR"] = f"{d}/uploads"
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_messaggi=f"{d}/m.db",
            db_garanzia=f"{d}/g.db"))
        self.mail = _EmailFinta()
        self.sis.email_provider = self.mail
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@pw.it", "password": "vecchia123",
                       "accetta_termini": True, "accetta_clausole": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]
        self._attendi_email(1)                       # benvenuto (thread in background)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _attendi_email(self, n, timeout=5.0):
        t0 = time.time()
        while len(self.mail.inviate) < n and time.time() - t0 < timeout:
            time.sleep(0.02)
        self.assertGreaterEqual(len(self.mail.inviate), n,
                                "email attese %d, arrivate %r" % (n, self.mail.inviate))

    def _estrai_token(self, html):
        import re
        m = re.search(r"#reset=([A-Za-z0-9._\-]+)", html)
        self.assertIsNotNone(m, html[:200])
        return m.group(1)

    def test_benvenuto_alla_registrazione(self):
        self.assertEqual(self.mail.inviate[0]["a"], "h@pw.it")
        self.assertIn("Benvenuto", self.mail.inviate[0]["ogg"])

    def test_flusso_reset_completo_e_single_use(self):
        s, o = self.g("POST", "/api/host/password_dimenticata", {"email": "h@pw.it"})
        self.assertEqual(s, 200)
        self._attendi_email(2)
        tok = self._estrai_token(self.mail.inviate[1]["html"])
        # reset con password corta -> rifiutato
        s, o = self.g("POST", "/api/host/password_reset",
                      {"token": tok, "password": "corta"})
        self.assertEqual(s, 400, o)
        # reset vero -> 200 + token di accesso fresco
        s, o = self.g("POST", "/api/host/password_reset",
                      {"token": tok, "password": "nuovissima1"})
        self.assertEqual(s, 200, o)
        self.assertTrue(o.get("token"))
        # login: nuova OK, vecchia RIFIUTATA
        s, o = self.g("POST", "/api/host/login",
                      {"email": "h@pw.it", "password": "nuovissima1"})
        self.assertEqual(s, 200, o)
        s, o = self.g("POST", "/api/host/login",
                      {"email": "h@pw.it", "password": "vecchia123"})
        self.assertEqual(s, 401, o)
        # SINGLE-USE: lo stesso link non funziona due volte (impronta cambiata)
        s, o = self.g("POST", "/api/host/password_reset",
                      {"token": tok, "password": "altraancora1"})
        self.assertEqual(s, 400, o)
        self.assertEqual(o.get("errore"), "link_non_valido")

    def test_anti_enumerazione_e_throttle(self):
        # email INESISTENTE: stessa risposta 200, NESSUNA email parte
        prima = len(self.mail.inviate)
        s, o = self.g("POST", "/api/host/password_dimenticata",
                      {"email": "fantasma@x.it"})
        self.assertEqual(s, 200)
        time.sleep(0.2)
        self.assertEqual(len(self.mail.inviate), prima)
        # THROTTLE: due richieste ravvicinate per la stessa email -> UNA sola email
        self.g("POST", "/api/host/password_dimenticata", {"email": "h@pw.it"})
        self._attendi_email(prima + 1)
        self.g("POST", "/api/host/password_dimenticata", {"email": "h@pw.it"})
        time.sleep(0.3)
        self.assertEqual(len(self.mail.inviate), prima + 1, "throttle bucato")

    def test_link_scaduto_e_manomesso(self):
        # token con exp nel passato (stessa firma di sistema)
        tok = self.sis.firma.codifica({"tipo": "host_pw_reset", "host_id": "h_x",
                                       "fp": "x" * 16, "exp": int(time.time()) - 10})
        s, o = self.g("POST", "/api/host/password_reset",
                      {"token": tok, "password": "validissima1"})
        self.assertEqual(s, 400)
        self.assertEqual(o.get("errore"), "link_scaduto")
        s, o = self.g("POST", "/api/host/password_reset",
                      {"token": "manomesso.xx", "password": "validissima1"})
        self.assertEqual(s, 400)
        self.assertEqual(o.get("errore"), "link_non_valido")

    def test_cambia_password_loggato(self):
        h = {"X-Host-Token": self.tok}
        s, o = self.g("POST", "/api/host/cambia_password",
                      {"vecchia": "SBAGLIATA", "nuova": "nuovabella1"}, h)
        self.assertEqual(s, 400, o)
        s, o = self.g("POST", "/api/host/cambia_password",
                      {"vecchia": "vecchia123", "nuova": "nuovabella1"}, h)
        self.assertEqual(s, 200, o)
        s, o = self.g("POST", "/api/host/login",
                      {"email": "h@pw.it", "password": "nuovabella1"})
        self.assertEqual(s, 200, o)
        # senza token host -> 401 (l'operatore con la sola host-key NON cambia password altrui)
        s, o = self.g("POST", "/api/host/cambia_password",
                      {"vecchia": "nuovabella1", "nuova": "ennesima1"},
                      {"X-Host-Key": "hk"})
        self.assertEqual(s, 401, o)


if __name__ == "__main__":
    unittest.main()
