"""
Test strutturale del deploy Casa VIP (anti-drift sulle proprieta' di sicurezza).
Non avvia Docker: verifica che i file di deploy mantengano le garanzie dichiarate
(non-root, zero pip, app non esposta sull'host, rete interna, backup, hardening nginx).
"""
import os
import unittest

try:
    import yaml
    HA_YAML = True
except ImportError:
    HA_YAML = False


def _leggi(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


class TestDockerfile(unittest.TestCase):
    def setUp(self):
        self.d = _leggi("Dockerfile.casavip")

    def test_non_root(self):
        self.assertIn("USER app", self.d)
        self.assertIn("10001", self.d)

    def test_zero_pip(self):
        # Casa VIP gira su pura stdlib: NESSUN pip install
        self.assertNotIn("pip install", self.d)

    def test_healthcheck_ed_expose(self):
        self.assertIn("HEALTHCHECK", self.d)
        self.assertIn("EXPOSE 8080", self.d)
        self.assertIn("/api/health", self.d)


@unittest.skipUnless(HA_YAML, "pyyaml non disponibile")
class TestCompose(unittest.TestCase):
    def setUp(self):
        self.c = yaml.safe_load(_leggi("docker-compose.casavip.yml"))

    def test_app_non_esposta_sull_host(self):
        app = self.c["services"]["app"]
        self.assertNotIn("ports", app)            # solo expose -> non raggiungibile da fuori
        self.assertIn("expose", app)

    def test_solo_nginx_esposto(self):
        self.assertIn("ports", self.c["services"]["nginx"])

    def test_self_healing(self):
        app = self.c["services"]["app"]
        self.assertEqual(app["restart"], "unless-stopped")
        self.assertIn("healthcheck", app)
        self.assertEqual(self.c["services"]["nginx"]["depends_on"]["app"]["condition"],
                         "service_healthy")

    def test_rete_interna_isolata(self):
        self.assertIn("interna", self.c["services"]["app"]["networks"])
        self.assertIn("interna", self.c["networks"])

    def test_backup_service(self):
        self.assertIn("backup", self.c["services"])
        self.assertIn("backup_casavip.sh", self.c["services"]["backup"]["command"][0])

    def test_volume_persistente(self):
        self.assertIn("casavip_data", self.c["volumes"])


class TestNginx(unittest.TestCase):
    def setUp(self):
        self.n = _leggi("deploy/nginx.casavip.conf")

    def test_hardening(self):
        self.assertIn("limit_req", self.n)                 # rate-limit
        self.assertIn("X-Content-Type-Options", self.n)    # security headers
        self.assertIn("%2e%2e", self.n)                    # blocco traversal encoded
        self.assertIn("/\\.", self.n)                      # blocco dotfile (location ~ /\.)
        self.assertIn("server_tokens off", self.n)
        self.assertIn("healthz", self.n)

    def test_https_pronto(self):
        self.assertIn("listen 443 ssl", self.n)
        self.assertIn("letsencrypt", self.n)


class TestFileDiSupporto(unittest.TestCase):
    def test_env_example(self):
        e = _leggi(".env.casavip.example")
        self.assertIn("CASAVIP_SEGRETO", e)
        self.assertIn("HOST_KEY", e)

    def test_script_presenti(self):
        self.assertTrue(os.path.isfile("deploy/genera_segreti.sh"))
        self.assertTrue(os.path.isfile("deploy/backup_casavip.sh"))

    def test_genera_segreti_usa_csprng(self):
        s = _leggi("deploy/genera_segreti.sh")
        self.assertTrue("openssl rand" in s or "secrets.token_hex" in s)
        self.assertIn("chmod 600", s)          # permessi ristretti sul file segreti

    def test_backup_atomico(self):
        b = _leggi("deploy/backup_casavip.sh")
        self.assertTrue(".backup" in b or ".backup(" in b)   # snapshot consistente
        self.assertIn("RETENTION", b)

    def test_gitignore_segreti(self):
        g = _leggi(".gitignore")
        self.assertIn(".env.casavip", g)


if __name__ == "__main__":
    unittest.main()
