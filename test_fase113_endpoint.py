"""Test rotte /api/messaggi (fase113 cablato nel server fase83). Puro via gestisci."""
import json
import unittest

from fase83_server import crea_router
from fase113_messaggistica import crea_messaggistica


class Sys:
    attivo = True

    def __init__(self, con_msg=True):
        self.registro_host = None
        self.messaggistica = None
        if con_msg:
            self.messaggistica = crea_messaggistica(":memory:")
            self.messaggistica.inizializza_schema()


H = {"X-Host-Key": "k"}


class TestMessaggiEndpoint(unittest.TestCase):
    def _router(self, con_msg=True):
        return crea_router(Sys(con_msg), host_key="k")

    def test_invia_e_thread(self):
        r = self._router()
        s, c = r.gestisci("POST", "/api/messaggi", {},
                          json.dumps({"prenotazione_id": "REF1", "guest_id": "g@x.it",
                                      "testo": "A che ora il check-in?"}), H)
        self.assertEqual(s, 201)
        s2, c2 = r.gestisci("GET", "/api/messaggi", {"prenotazione_id": "REF1"}, None, H)
        self.assertEqual(s2, 200)
        self.assertEqual(len(c2["messaggi"]), 1)
        self.assertEqual(c2["messaggi"][0]["mittente"], "host")

    def test_maschera_pii(self):
        r = self._router()
        r.gestisci("POST", "/api/messaggi", {},
                   json.dumps({"prenotazione_id": "R", "guest_id": "g@x.it",
                               "testo": "scrivimi a mario@gmail.com"}), H)
        c = r.gestisci("GET", "/api/messaggi", {"prenotazione_id": "R"}, None, H)[1]
        self.assertNotIn("mario@gmail.com", c["messaggi"][0]["testo"])

    def test_unauth(self):
        s, _ = self._router().gestisci("POST", "/api/messaggi", {}, "{}", {})
        self.assertEqual(s, 401)

    def test_gated_senza_modulo(self):
        s, c = crea_router(Sys(con_msg=False), host_key="k").gestisci(
            "POST", "/api/messaggi", {}, "{}", H)
        self.assertEqual(s, 503)

    def test_campi_invalidi(self):
        s, _ = self._router().gestisci("POST", "/api/messaggi", {},
                                       json.dumps({"prenotazione_id": "R"}), H)
        self.assertEqual(s, 422)


if __name__ == "__main__":
    unittest.main()
