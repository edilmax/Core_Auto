"""Collaudo GATEKEEPER server-side (zero information leakage).

Invariante centrale: NESSUN byte della struttura di una pagina riservata
(/admin.html, /bunker.html, /host.html) viene spedito a chi non ha una sessione valida.
Chi non è autenticato riceve 302 verso il login del ruolo (form soltanto, zero dashboard).
Con sessione valida la pagina è servita ma marcata no-store (dopo il logout non riappare).
L'auth dell'API (header token) resta invariata; il cookie è HttpOnly + Secure + SameSite=Lax.

Girato contro un VERO server HTTP (il gate, i redirect, i cookie e gli header stanno
nell'handler, non nel router) — http.client, redirect NON seguiti, cookie gestiti a mano.
"""
import http.client
import shutil
import socket
import tempfile
import threading
import time
import unittest

import fase83_server
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema


def _porta_libera():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class TestGatekeeper(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        d = cls.dir
        cls.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"g" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_finanza=f"{d}/fin.db", bunker_password="SuperPw@1"))
        cls.host_id = cls.sis.registro_host.registra(
            "gate@x.it", "password12", accetta_termini=True).host_id
        cls.porta = _porta_libera()
        cls.t = threading.Thread(
            target=fase83_server.servi,
            kwargs=dict(sistema=cls.sis, host="127.0.0.1", porta=cls.porta,
                        cartella_statica="deploy", host_key="hk", admin_key="ak"),
            daemon=True)
        cls.t.start()
        # attendi che il server risponda
        for _ in range(200):
            try:
                st, _h, _b, _c = cls._grezzo("GET", "/robots.txt")
                if st == 200:
                    break
            except Exception:
                pass
            time.sleep(0.03)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    @classmethod
    def _grezzo(cls, metodo, path, headers=None, body=None):
        c = http.client.HTTPConnection("127.0.0.1", cls.porta, timeout=6)
        c.request(metodo, path, body=body, headers=headers or {})
        r = c.getresponse()
        dati = r.read().decode("utf-8", "replace")
        tutti = r.getheaders()
        hd = {k.lower(): v for k, v in tutti}
        cookies = [v for (k, v) in tutti if k.lower() == "set-cookie"]
        c.close()
        return r.status, hd, dati, cookies

    def req(self, metodo, path, headers=None, body=None):
        return self._grezzo(metodo, path, headers, body)

    @staticmethod
    def _valore_cookie(set_cookie_str):
        return set_cookie_str.split(";", 1)[0].split("=", 1)[1]

    # ── 1) chi NON è loggato non riceve struttura: 302 al login ────────────────
    def test_dashboard_senza_sessione_reindirizza(self):
        for pagina, dove in (("/admin.html", "/entra-admin"),
                             ("/bunker.html", "/entra-bunker"),
                             ("/host.html", "/entra-host")):
            st, hd, body, _ = self.req("GET", pagina)
            self.assertEqual(st, 302, pagina)
            self.assertEqual(hd.get("location"), dove, pagina)
            self.assertIn("no-store", hd.get("cache-control", ""), pagina)
            # nessun frammento di dashboard nel corpo del redirect
            self.assertNotIn("adminkey", body)
            self.assertNotIn("/api/admin/rimborso", body)

    # ── 2) la pagina di login è pubblica ma contiene SOLO il form ──────────────
    def test_pagina_login_pubblica_senza_dashboard(self):
        st, hd, body, _ = self.req("GET", "/entra-admin")
        self.assertEqual(st, 200)
        self.assertIn("no-store", hd.get("cache-control", ""))
        self.assertIn("noindex", body)
        self.assertIn("/api/admin/login", body)          # il form punta al login
        self.assertNotIn("/api/admin/rimborso", body)    # nessun endpoint sensibile
        self.assertNotIn("Prenotazioni", body)           # nessuna struttura dashboard

    # ── 3) login admin -> cookie firmato -> pagina servita (no-store) ──────────
    def test_admin_login_apre_la_pagina(self):
        st, hd, body, cookies = self.req(
            "POST", "/api/admin/login", {"X-Admin-Key": "ak"})
        self.assertEqual(st, 200, body)
        sc = next((c for c in cookies if c.startswith("bv_admin=")), "")
        self.assertTrue(sc, "manca Set-Cookie bv_admin")
        self.assertIn("HttpOnly", sc)
        self.assertIn("Secure", sc)
        self.assertIn("SameSite=Lax", sc)
        cookie = self._valore_cookie(sc)
        st, hd, body, _ = self.req("GET", "/admin.html", {"Cookie": "bv_admin=" + cookie})
        self.assertEqual(st, 200)
        self.assertIn("no-store", hd.get("cache-control", ""))
        self.assertIn("adminkey", body)                  # ORA sì: struttura dashboard servita

    def test_admin_chiave_errata_niente_cookie(self):
        st, hd, body, cookies = self.req(
            "POST", "/api/admin/login", {"X-Admin-Key": "SBAGLIATA"})
        self.assertEqual(st, 401)
        self.assertFalse([c for c in cookies if c.startswith("bv_admin=")])

    # ── 4) cookie manomesso o di livello sbagliato: respinto ───────────────────
    def test_cookie_manomesso_respinto(self):
        st, hd, _b, _ = self.req("GET", "/admin.html",
                                 {"Cookie": "bv_admin=admin|9999999999|x|deadbeef"})
        self.assertEqual(st, 302)

    def test_cookie_di_altro_livello_non_apre(self):
        # un cookie HOST valido non deve aprire la pagina ADMIN
        _s, _h, _b, cookies = self.req(
            "POST", "/api/host/login", None,
            body='{"email":"gate@x.it","password":"password12"}')
        sc = next((c for c in cookies if c.startswith("bv_host=")), "")
        self.assertTrue(sc)
        host_cookie = self._valore_cookie(sc)
        st, _h, _b, _c = self.req("GET", "/admin.html",
                                  {"Cookie": "bv_admin=" + host_cookie})
        self.assertEqual(st, 302)                         # livello 'host' != 'admin'

    # ── 5) host e bunker: login emette il cookie e apre la pagina ──────────────
    def test_host_login_apre_la_pagina(self):
        _s, _h, _b, cookies = self.req(
            "POST", "/api/host/login", None,
            body='{"email":"gate@x.it","password":"password12"}')
        sc = next((c for c in cookies if c.startswith("bv_host=")), "")
        self.assertTrue(sc, "manca Set-Cookie bv_host")
        cookie = self._valore_cookie(sc)
        st, hd, _b, _c = self.req("GET", "/host.html", {"Cookie": "bv_host=" + cookie})
        self.assertEqual(st, 200)
        self.assertIn("no-store", hd.get("cache-control", ""))

    def test_bunker_login_apre_la_pagina(self):
        _s, _h, _b, cookies = self.req(
            "POST", "/api/bunker/login", {"X-Admin-Key": "ak"},
            body='{"codice":"SuperPw@1"}')
        sc = next((c for c in cookies if c.startswith("bv_bunker=")), "")
        self.assertTrue(sc, "manca Set-Cookie bv_bunker")
        cookie = self._valore_cookie(sc)
        st, _h, _b, _c = self.req("GET", "/bunker.html", {"Cookie": "bv_bunker=" + cookie})
        self.assertEqual(st, 200)

    # ── 6) logout: cancella TUTTI i cookie (Max-Age=0) ─────────────────────────
    def test_logout_cancella_i_cookie(self):
        _s, _h, _b, cookies = self.req("POST", "/api/gate/logout")
        nomi = {c.split("=", 1)[0] for c in cookies}
        self.assertEqual(nomi, {"bv_admin", "bv_host", "bv_bunker"})
        for c in cookies:
            self.assertIn("Max-Age=0", c)

    # ── 7) firma scaduta: respinta (livello router, deterministico) ────────────
    def test_cookie_scaduto_respinto(self):
        r = fase83_server.crea_router(self.sis, admin_key="ak")
        self.assertTrue(r._gate_valida(r._gate_firma("admin", 3600), "admin"))
        self.assertFalse(r._gate_valida(r._gate_firma("admin", -5), "admin"))
        # firma di un altro segreto non passa
        self.assertFalse(r._gate_valida("admin|9999999999|x|deadbeef", "admin"))

    # ── 8) kill-switch d'emergenza PAGE_GATE=0: serve senza gate ───────────────
    def test_killswitch_disattiva_il_gate(self):
        import os
        os.environ["PAGE_GATE"] = "0"
        try:
            st, hd, body, _ = self.req("GET", "/admin.html")
            self.assertEqual(st, 200)                     # servita anche senza cookie
            self.assertIn("no-store", hd.get("cache-control", ""))
        finally:
            os.environ.pop("PAGE_GATE", None)


if __name__ == "__main__":
    unittest.main()
