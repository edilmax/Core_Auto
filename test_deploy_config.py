"""
Test BLOCCO 5.0b - Validazione STRUTTURALE della config di deploy.

Nessun Docker richiesto (sempre verde): verifica che Dockerfile, compose, nginx,
.dockerignore e requirements rispettino i requisiti di sicurezza/self-healing
emersi dal benchmark (Variante C).
"""
import os
import unittest


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestDockerfile(unittest.TestCase):

    def setUp(self):
        self.df = _read("Dockerfile")

    def test_multi_stage(self):
        self.assertGreaterEqual(self.df.count("FROM "), 2)

    def test_non_root(self):
        self.assertIn("USER appuser", self.df)

    def test_base_slim_e_pinnata(self):
        self.assertIn("slim", self.df)
        for riga in self.df.splitlines():
            if riga.startswith("FROM "):
                self.assertIn(":", riga)
                self.assertNotIn(":latest", riga)

    def test_no_build_tools_nel_finale(self):
        finale = self.df.split("FROM ")[-1]
        for t in ("gcc", "build-essential", "apt-get install"):
            self.assertNotIn(t, finale)

    def test_pip_no_cache_e_healthcheck_e_cmd(self):
        self.assertIn("--no-cache-dir", self.df)
        self.assertIn("HEALTHCHECK", self.df)
        self.assertIn("gunicorn", self.df)


class TestComposeStack(unittest.TestCase):

    def setUp(self):
        import yaml
        self.doc = yaml.safe_load(_read("docker-compose.yml"))
        self.svc = self.doc["services"]

    def test_tre_servizi(self):
        self.assertEqual(set(self.svc), {"app", "postgres", "nginx"})

    def test_self_healing_restart(self):
        for nome in ("app", "postgres", "nginx"):
            self.assertEqual(self.svc[nome].get("restart"), "unless-stopped", nome)

    def test_healthcheck_ovunque(self):
        for nome in ("app", "postgres", "nginx"):
            self.assertIn("healthcheck", self.svc[nome], nome)

    def test_depends_on_healthy(self):
        self.assertEqual(
            self.svc["app"]["depends_on"]["postgres"]["condition"], "service_healthy")
        self.assertEqual(
            self.svc["nginx"]["depends_on"]["app"]["condition"], "service_healthy")

    def test_postgres_volume_persistente(self):
        self.assertTrue(any("core_auto_pgdata" in v for v in self.svc["postgres"]["volumes"]))
        self.assertIn("core_auto_pgdata", self.doc["volumes"])

    def test_solo_nginx_esposto(self):
        # app e postgres NON pubblicano porte sull'host (superficie minima).
        self.assertNotIn("ports", self.svc["app"])
        self.assertNotIn("ports", self.svc["postgres"])
        self.assertTrue(any("80" in str(p) for p in self.svc["nginx"]["ports"]))

    def test_nginx_monta_conf(self):
        self.assertTrue(any("deploy/nginx.conf" in v for v in self.svc["nginx"]["volumes"]))


class TestNginx(unittest.TestCase):

    def setUp(self):
        self.conf = _read(os.path.join("deploy", "nginx.conf"))

    def test_reverse_proxy(self):
        self.assertIn("upstream core_auto_app", self.conf)
        self.assertIn("server app:8000", self.conf)
        self.assertIn("proxy_pass", self.conf)

    def test_sicurezza_e_limiti(self):
        self.assertIn("X-Content-Type-Options nosniff", self.conf)
        self.assertIn("client_max_body_size 1m", self.conf)
        self.assertIn("server_tokens off", self.conf)

    def test_healthz(self):
        self.assertIn("location = /healthz", self.conf)


class TestDockerignoreEReq(unittest.TestCase):

    def test_dockerignore(self):
        di = _read(".dockerignore")
        for v in (".git/", "__pycache__/", "data/", "test_*.py", ".env"):
            self.assertIn(v, di)

    def test_requirements(self):
        req = _read("requirements.txt")
        for pkg in ("psycopg2-binary", "gunicorn", "flask"):
            self.assertIn(pkg, req.lower())


if __name__ == "__main__":
    unittest.main()
