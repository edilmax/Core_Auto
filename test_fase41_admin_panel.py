"""
Test Fase 41 / Tavola VIP - Pannello Admin Web.

Sicurezza paranoica: Basic auth (manca/errata -> 401), CSRF obbligatorio sui POST
(manca/errato -> 403), flusso rimborsi gated (approva/rifiuta) e annulla che
toccano lo stato reale, auto-escape anti-XSS, header di sicurezza, e FAIL-CLOSED
quando le credenziali non sono configurate (503).
"""
import base64
import os
import sqlite3
import tempfile
import unittest

from fase41_admin_panel import crea_app_admin
from fase34_prenotazioni import MotorePrenotazioni, RichiestaPrenotazione
from fase35_pagamenti import StubPagamentoProvider, ServizioPagamenti

CSRF = "CSRF-TOKEN-FISSO"


def _hdr(utente="admin", password="segretissima"):
    tok = base64.b64encode(f"{utente}:{password}".encode()).decode()
    return {"Authorization": "Basic " + tok}


class _Base(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.motore = MotorePrenotazioni(lambda: sqlite3.connect(self.path, timeout=30))
        self.motore.inizializza_schema()
        self.servizio = ServizioPagamenti(self.motore, StubPagamentoProvider(segreto="s"))
        self.app = crea_app_admin(self.motore, self.servizio, utente="admin",
                                  password="segretissima", csrf_token=CSRF)
        self.c = self.app.test_client()

    def tearDown(self):
        for ext in ("", "-wal", "-shm", "-journal"):
            try:
                os.remove(self.path + ext)
            except OSError:
                pass

    def _prenota(self, alloggio="VIP-1", ci="2027-01-10", co="2027-01-12",
                 email="ospite@x.it"):
        return self.motore.crea(RichiestaPrenotazione(
            alloggio, "Mario", email, ci, co, 10000, 1000))

    def _rimborso_richiesto(self):
        e = self._prenota()
        self.motore.conferma_pagamento(e.pagamento_id)
        self.motore.richiedi_rimborso(e.prenotazione_id)
        return e.prenotazione_id


class TestAuth(_Base):
    def test_get_senza_auth_401(self):
        r = self.c.get("/admin")
        self.assertEqual(r.status_code, 401)
        self.assertIn("WWW-Authenticate", r.headers)

    def test_get_password_errata_401(self):
        self.assertEqual(self.c.get("/admin", headers=_hdr(password="x")).status_code, 401)

    def test_get_valido_200_mostra_dati(self):
        self._prenota(alloggio="VIP-42")
        r = self.c.get("/admin", headers=_hdr())
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        self.assertIn("Ponte di comando", body)
        self.assertIn("VIP-42", body)
        self.assertIn(CSRF, body)

    def test_header_sicurezza(self):
        r = self.c.get("/admin", headers=_hdr())
        self.assertEqual(r.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn("no-store", r.headers.get("Cache-Control", ""))


class TestCSRF(_Base):
    def test_post_senza_auth_401(self):
        pid = self._rimborso_richiesto()
        self.assertEqual(self.c.post(f"/admin/refund/{pid}/approve").status_code, 401)

    def test_post_auth_ma_senza_csrf_403(self):
        pid = self._rimborso_richiesto()
        r = self.c.post(f"/admin/refund/{pid}/approve", headers=_hdr())
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.motore.stato(pid)["stato"], "rimborso_richiesto")  # invariato

    def test_post_csrf_errato_403(self):
        pid = self._rimborso_richiesto()
        r = self.c.post(f"/admin/refund/{pid}/approve", headers=_hdr(),
                        data={"csrf": "SBAGLIATO"})
        self.assertEqual(r.status_code, 403)


class TestAzioni(_Base):
    def test_approva_rimborso(self):
        pid = self._rimborso_richiesto()
        r = self.c.post(f"/admin/refund/{pid}/approve", headers=_hdr(),
                        data={"csrf": CSRF})
        self.assertEqual(r.status_code, 303)
        self.assertEqual(self.motore.stato(pid)["stato"], "rimborsata")

    def test_rifiuta_rimborso(self):
        pid = self._rimborso_richiesto()
        self.c.post(f"/admin/refund/{pid}/reject", headers=_hdr(), data={"csrf": CSRF})
        self.assertEqual(self.motore.stato(pid)["stato"], "pagata")

    def test_annulla_prenotazione(self):
        e = self._prenota()
        self.c.post(f"/admin/reservation/{e.prenotazione_id}/cancel", headers=_hdr(),
                    data={"csrf": CSRF})
        self.assertEqual(self.motore.stato(e.prenotazione_id)["stato"], "annullata")


class TestSicurezzaVaria(_Base):
    def test_anti_xss_escape(self):
        self._prenota(email="<script>alert(1)</script>@x.it")
        body = self.c.get("/admin", headers=_hdr()).get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", body)   # deve essere escapato
        self.assertIn("&lt;script&gt;", body)

    def test_fail_closed_senza_credenziali(self):
        app = crea_app_admin(self.motore, self.servizio, utente=None, password=None)
        self.assertEqual(app.test_client().get("/admin").status_code, 503)


if __name__ == "__main__":
    unittest.main()
