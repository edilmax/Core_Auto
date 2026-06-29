"""Test end-to-end del loop referral via le rotte (fase76): genera codice -> registra
referee col codice_referral -> entrambi accreditati. Verifica anche che la fonte/commissione
non sia alterabile da parametri di tracking (floor 5% diretto strutturale)."""
import json
import unittest

from fase83_server import crea_router
from fase76_viral_loop import crea_viral_loop
from fase88_registro_host import crea_registro_host
from fase98_policy_commissione import commissione_bps_fonte

SEG = b"k" * 32


class Sys:
    attivo = True

    def __init__(self):
        self.registro_host = crea_registro_host(":memory:", SEG)
        self.registro_host.inizializza_schema()
        self.viral = crea_viral_loop(":memory:", SEG)


def _router():
    return crea_router(Sys(), host_key="hk", base_url="https://bookinvip.com")


class TestReferralFlow(unittest.TestCase):
    def _registra(self, r, email, codice=""):
        body = {"email": email, "password": "passw0rd!", "accetta_termini": True}
        if codice:
            body["codice_referral"] = codice
        s, c = r.gestisci("POST", "/api/host/registrazione", {}, json.dumps(body), {})
        return s, c

    def test_loop_completo(self):
        r = _router()
        sA, cA = self._registra(r, "a@host.it")
        self.assertEqual(sA, 201)
        hidA = cA["host_id"]
        # link/codice del referrer A (link ASSOLUTO, contiene il dominio)
        sL, cL = r.gestisci("GET", "/api/host/referral", {"host_id": hidA}, None,
                            {"X-Host-Key": "hk"})
        self.assertEqual(sL, 200)
        self.assertTrue(cL["link"].startswith("https://bookinvip.com/diventa-host.html?ref="))
        codice = cL["codice"] if "codice" in cL else cL["link"].split("ref=")[1]
        # B si registra COL codice -> loop chiuso, referral.ok True
        sB, cB = self._registra(r, "b@host.it", codice=codice)
        self.assertEqual(sB, 201)
        self.assertIn("referral", cB)
        self.assertTrue(cB["referral"]["ok"])

    def test_registrazione_senza_ref_non_rompe(self):
        s, c = self._registra(_router(), "solo@host.it")
        self.assertEqual(s, 201)
        self.assertNotIn("referral", c)            # nessun codice -> nessun referral, ok

    def test_floor_diretto_non_alterabile_da_tracking(self):
        # la commissione dipende SOLO dalla fonte, non da utm/ref: diretto resta 5%
        self.assertEqual(commissione_bps_fonte("diretto"), 500)
        self.assertEqual(commissione_bps_fonte("diretto", 9999), 500)


if __name__ == "__main__":
    unittest.main()
