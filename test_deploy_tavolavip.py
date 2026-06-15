"""
Test deploy Tavola VIP - validazione STRUTTURALE dello stack di lancio standalone.

Nessun Docker richiesto (sempre verde): verifica che docker-compose.tavolavip.yml,
deploy/nginx.tavolavip.conf e lo smoke test rispettino i requisiti del go-live
(riuso immagine, volume SQLite, binding SICURO dei segreti, solo nginx esposto,
self-healing) SENZA toccare lo stack fortezza esistente.
"""
import os
import re
import unittest


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


COMPOSE = "docker-compose.tavolavip.yml"
NGINX = os.path.join("deploy", "nginx.tavolavip.conf")
SMOKE = os.path.join("deploy", "smoke_tavolavip.sh")


class TestComposeTavolaVIP(unittest.TestCase):
    def setUp(self):
        import yaml
        self.raw = _read(COMPOSE)
        self.doc = yaml.safe_load(self.raw)
        self.svc = self.doc["services"]

    def test_solo_booking_e_nginx(self):
        self.assertEqual(set(self.svc), {"booking", "nginx"})  # niente postgres

    def test_riusa_immagine_dockerfile(self):
        self.assertEqual(self.svc["booking"]["build"], ".")  # stessa immagine fortezza

    def test_command_avvia_app_booking(self):
        cmd = " ".join(self.svc["booking"]["command"])
        self.assertIn("gunicorn", cmd)
        self.assertIn("fase36_booking_api:crea_app_da_env()", cmd)

    def test_volume_sqlite_persistente(self):
        self.assertTrue(any("tavolavip_data:/data" in v
                            for v in self.svc["booking"]["volumes"]))
        self.assertTrue(self.svc["booking"]["environment"]["DB_PATH"].startswith("/data"))
        self.assertIn("tavolavip_data", self.doc["volumes"])

    def test_binding_sicuro_segreti_fail_fast(self):
        env = self.svc["booking"]["environment"]
        for chiave in ("STRIPE_API_KEY", "STRIPE_WEBHOOK_SECRET", "BOOKING_API_KEY"):
            self.assertIn(":?", str(env[chiave]), f"{chiave} deve essere fail-fast ${{VAR:?}}")

    def test_nessun_segreto_in_chiaro(self):
        self.assertNotRegex(self.raw, r"sk_(test|live)_[A-Za-z0-9]{6}")
        self.assertNotRegex(self.raw, r"whsec_[A-Za-z0-9]{6}")

    def test_solo_nginx_esposto(self):
        self.assertNotIn("ports", self.svc["booking"])
        self.assertTrue(any("80" in str(p) for p in self.svc["nginx"]["ports"]))

    def test_self_healing(self):
        for nome in ("booking", "nginx"):
            self.assertEqual(self.svc[nome].get("restart"), "unless-stopped", nome)
            self.assertIn("healthcheck", self.svc[nome], nome)

    def test_nginx_depends_booking_healthy(self):
        self.assertEqual(
            self.svc["nginx"]["depends_on"]["booking"]["condition"], "service_healthy")
        self.assertTrue(any("nginx.tavolavip.conf" in v
                            for v in self.svc["nginx"]["volumes"]))


class TestNginxTavolaVIP(unittest.TestCase):
    def setUp(self):
        self.conf = _read(NGINX)

    def test_reverse_proxy_su_booking(self):
        self.assertIn("upstream tavolavip_booking", self.conf)
        self.assertIn("server booking:8000", self.conf)
        self.assertIn("proxy_pass", self.conf)

    def test_healthz_e_sicurezza(self):
        self.assertIn("location = /healthz", self.conf)
        self.assertIn("server_tokens off", self.conf)
        self.assertIn("X-Content-Type-Options nosniff", self.conf)

    def test_webhook_location_dedicata(self):
        self.assertIn("location = /api/v1/payments/webhook", self.conf)


class TestSSL(unittest.TestCase):
    """Stack HTTPS (BLOCCO 5.1): TLS + redirect + HSTS, pronto da attivare."""
    def setUp(self):
        self.conf = _read(os.path.join("deploy", "nginx.tavolavip.ssl.conf"))
        import yaml
        self.raw = _read("docker-compose.tavolavip.ssl.yml")
        self.doc = yaml.safe_load(self.raw)
        self.svc = self.doc["services"]

    def test_conf_tls_e_redirect(self):
        self.assertIn("listen 443 ssl", self.conf)
        self.assertIn("ssl_certificate", self.conf)
        self.assertIn("return 301 https://", self.conf)              # 80 -> 443
        self.assertIn("Strict-Transport-Security", self.conf)        # HSTS
        self.assertIn("acme-challenge", self.conf)                   # rinnovo cert
        self.assertIn("server booking:8000", self.conf)

    def test_compose_espone_443_e_monta_certificati(self):
        ports = " ".join(str(p) for p in self.svc["nginx"]["ports"])
        self.assertIn("443", ports)
        self.assertIn("80", ports)
        vols = " ".join(self.svc["nginx"]["volumes"])
        self.assertIn("/etc/letsencrypt", vols)
        self.assertIn("nginx.tavolavip.ssl.conf", vols)

    def test_compose_binding_sicuro_e_no_segreti(self):
        env = self.svc["booking"]["environment"]
        for chiave in ("STRIPE_API_KEY", "STRIPE_WEBHOOK_SECRET", "BOOKING_API_KEY"):
            self.assertIn(":?", str(env[chiave]))
        self.assertNotRegex(self.raw, r"sk_(test|live)_[A-Za-z0-9]{6}")


class TestSmokeEFortezzaIntatta(unittest.TestCase):
    def test_smoke_copre_le_chiamate_chiave(self):
        s = _read(SMOKE)
        for atteso in ("/api/v1/health", "/api/v1/reservations",
                       "/api/v1/payments/webhook", "401", "409", "400",
                       "payment_url"):
            self.assertIn(atteso, s, atteso)

    def test_fortezza_compose_intatto(self):
        import yaml
        forte = yaml.safe_load(_read("docker-compose.yml"))
        self.assertEqual(set(forte["services"]), {"app", "postgres", "nginx"})


if __name__ == "__main__":
    unittest.main()
