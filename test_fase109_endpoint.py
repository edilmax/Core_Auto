"""Test rotte /api/host/invito* (fase109 cablato nel server fase83). Puro via gestisci."""
import json
import unittest

from fase83_server import crea_router
from fase109_referral_host import crea_referral_host

SEG = b"k" * 32
HOSTH = {"X-Host-Key": "hk"}
ADMINH = {"X-Admin-Key": "ak"}


class Sys:
    attivo = True

    def __init__(self, con_ref=True):
        self.registro_host = None
        self.referral = crea_referral_host(SEG) if con_ref else None


def _router(con_ref=True):
    return crea_router(Sys(con_ref), host_key="hk", admin_key="ak",
                       base_url="https://bookinvip.com")


class TestInvitoEndpoint(unittest.TestCase):
    def test_invito_link_e_crediti(self):
        r = _router()
        s, c = r.gestisci("GET", "/api/host/invito", {}, None, HOSTH)
        self.assertEqual(s, 200)
        self.assertIn("/diventa-host.html?ref=", c["link"])
        self.assertEqual(c["crediti_cents"], 0)
        self.assertTrue(c["codice"])

    def test_flusso_completo_bonus(self):
        r = _router()
        cod = r.gestisci("GET", "/api/host/invito", {}, None, HOSTH)[1]["codice"]
        # un nuovo host si registra col codice
        s1, _ = r.gestisci("POST", "/api/host/invito/registra", {},
                           json.dumps({"codice": cod, "nuovo_host_id": "hostB"}), {})
        self.assertEqual(s1, 201)
        # qualifica (prima prenotazione) -> bonus al referrer (admin)
        s2, c2 = r.gestisci("POST", "/api/host/invito/qualifica", {},
                            json.dumps({"nuovo_host_id": "hostB"}), ADMINH)
        self.assertEqual(s2, 200)
        self.assertEqual(c2["bonus_cents"], 1000)
        # il referrer 'host' ora ha crediti
        c3 = r.gestisci("GET", "/api/host/invito", {}, None, HOSTH)[1]
        self.assertEqual(c3["crediti_cents"], 1000)

    def test_registra_codice_falso(self):
        s, _ = _router().gestisci("POST", "/api/host/invito/registra", {},
                                  json.dumps({"codice": "falso", "nuovo_host_id": "x"}), {})
        self.assertEqual(s, 409)

    def test_qualifica_solo_admin(self):
        s, _ = _router().gestisci("POST", "/api/host/invito/qualifica", {},
                                  json.dumps({"nuovo_host_id": "x"}), HOSTH)
        self.assertEqual(s, 401)

    def test_invito_unauth(self):
        self.assertEqual(_router().gestisci("GET", "/api/host/invito", {}, None, {})[0], 401)

    def test_gated_senza_modulo(self):
        s, _ = _router(con_ref=False).gestisci("GET", "/api/host/invito", {}, None, HOSTH)
        self.assertEqual(s, 503)


if __name__ == "__main__":
    unittest.main()
