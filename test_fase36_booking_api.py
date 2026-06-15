"""
Test Fase 36 / Tavola VIP - API HTTP prenotazioni (Flask test client, E2E).

Il flusso reale che gira sul server: POST /reservations -> 201 + payment_url;
webhook firmato -> conferma + voucher; overlap -> 409; cancel; auth via API-key;
webhook con firma errata -> 400 senza cambiare stato.
"""
import json
import os
import sqlite3
import tempfile
import unittest

from fase34_prenotazioni import MotorePrenotazioni
from fase35_pagamenti import StubPagamentoProvider, ServizioPagamenti
from fase36_booking_api import crea_app_booking, crea_app_da_env


class _Base(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.motore = MotorePrenotazioni(lambda: sqlite3.connect(self.path, timeout=30))
        self.motore.inizializza_schema()
        self.provider = StubPagamentoProvider(segreto="whsec")
        self.servizio = ServizioPagamenti(self.motore, self.provider)
        self.app = crea_app_booking(self.motore, self.servizio, api_key="K1")
        self.c = self.app.test_client()
    def tearDown(self):
        for ext in ("", "-wal", "-shm", "-journal"):
            try:
                os.remove(self.path + ext)
            except OSError:
                pass
    def _crea(self, ci="2026-10-01", co="2026-10-05", alloggio="tavolo-1"):
        return self.c.post("/api/v1/reservations", headers={"X-Booking-Key": "K1"},
                           json={"alloggio_id": alloggio, "ospite_nome": "Mario",
                                 "ospite_email": "m@x.it", "check_in": ci,
                                 "check_out": co, "importo_totale_cents": 20000,
                                 "commissione_cents": 2000})


class TestBookingAPI(_Base):
    def test_crea_ritorna_link(self):
        r = self._crea()
        self.assertEqual(r.status_code, 201)
        d = r.get_json()
        self.assertEqual(d["stato"], "in_attesa_pagamento")
        self.assertTrue(d["payment_url"])
        self.assertIn("prenotazione_id", d)

    def test_auth_richiesta(self):
        r = self.c.post("/api/v1/reservations", json={})  # niente X-Booking-Key
        self.assertEqual(r.status_code, 401)

    def test_payload_invalido(self):
        r = self.c.post("/api/v1/reservations", headers={"X-Booking-Key": "K1"},
                        json={"alloggio_id": "t1"})  # mancano campi
        self.assertEqual(r.status_code, 400)

    def test_importo_float_rifiutato(self):
        r = self.c.post("/api/v1/reservations", headers={"X-Booking-Key": "K1"},
                        json={"alloggio_id": "t1", "check_in": "2026-10-01",
                              "check_out": "2026-10-03",
                              "importo_totale_cents": 200.50,  # float -> rifiutato
                              "commissione_cents": 2000})
        self.assertEqual(r.status_code, 400)

    def test_overlap_conflitto_409(self):
        self.assertEqual(self._crea().status_code, 201)
        self.assertEqual(self._crea("2026-10-03", "2026-10-08").status_code, 409)

    def test_turnover_ok(self):
        self.assertEqual(self._crea("2026-10-01", "2026-10-05").status_code, 201)
        self.assertEqual(self._crea("2026-10-05", "2026-10-09").status_code, 201)

    def test_stato_e_not_found(self):
        pid = self._crea().get_json()["prenotazione_id"]
        self.assertEqual(self.c.get(f"/api/v1/reservations/{pid}",
                                    headers={"X-Booking-Key": "K1"}).status_code, 200)
        self.assertEqual(self.c.get("/api/v1/reservations/99999",
                                    headers={"X-Booking-Key": "K1"}).status_code, 404)

    def test_cancel_libera_il_tavolo(self):
        pid = self._crea().get_json()["prenotazione_id"]
        r = self.c.post(f"/api/v1/reservations/{pid}/cancel",
                        headers={"X-Booking-Key": "K1"})
        self.assertEqual(r.status_code, 200)
        # ora le stesse date sono di nuovo prenotabili
        self.assertEqual(self._crea().status_code, 201)

    def test_webhook_conferma_e_voucher(self):
        d = self._crea().get_json()
        payload, firma = self.provider.firma_evento(d["pagamento_id"], pagato=True)
        r = self.c.post("/api/v1/payments/webhook", data=payload,
                        headers={"X-Pagamento-Firma": firma,
                                 "Content-Type": "application/json"})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["esito"], "confermato")
        self.assertTrue(body["voucher"].startswith("VIP-"))

    def test_webhook_firma_errata_400_senza_stato(self):
        d = self._crea().get_json()
        payload, _ = self.provider.firma_evento(d["pagamento_id"])
        r = self.c.post("/api/v1/payments/webhook", data=payload,
                        headers={"X-Pagamento-Firma": "BAD",
                                 "Content-Type": "application/json"})
        self.assertEqual(r.status_code, 400)
        st = self.c.get(f"/api/v1/reservations/{d['prenotazione_id']}",
                        headers={"X-Booking-Key": "K1"}).get_json()
        self.assertEqual(st["stato"], "in_attesa_pagamento")  # invariato


class TestBootstrapDaEnv(unittest.TestCase):
    """crea_app_da_env: il servizio si auto-configura dalle variabili d'ambiente."""
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._salva = {k: os.environ.get(k) for k in
                       ("DB_PATH", "BOOKING_API_KEY", "STRIPE_API_KEY")}
        os.environ["DB_PATH"] = self.path
        os.environ["BOOKING_API_KEY"] = "BK"
        os.environ.pop("STRIPE_API_KEY", None)  # niente Stripe -> stub
    def tearDown(self):
        for k, v in self._salva.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for ext in ("", "-wal", "-shm", "-journal"):
            try:
                os.remove(self.path + ext)
            except OSError:
                pass

    def test_app_da_env_prenota(self):
        app = crea_app_da_env()
        c = app.test_client()
        r = c.post("/api/v1/reservations", headers={"X-Booking-Key": "BK"},
                   json={"alloggio_id": "t1", "check_in": "2026-11-01",
                         "check_out": "2026-11-03", "importo_totale_cents": 9000,
                         "commissione_cents": 900})
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.get_json()["payment_url"])


if __name__ == "__main__":
    unittest.main()
