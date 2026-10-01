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
import os
import re
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

    # ── post-pagamento: /grazie e /annullato (Stripe success/cancel) DEVONO servire la pagina ──
    def test_pagine_post_pagamento_non_404(self):
        # erano un 404 -> l'ospite DOPO aver pagato vedeva pagina morta (vicolo cieco).
        for p in ("/grazie", "/annullato"):
            st, hd, body, _ = self.req("GET", p)
            self.assertEqual(st, 200, "%s deve servire la pagina (era 404 post-pagamento)" % p)
            self.assertIn("<", body, "%s non serve HTML" % p)

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


class TestIlSitoServeSoloIlSito(unittest.TestCase):
    """⛔ IL DIFETTO, sondato sul sito vero il 30/9 sera: `_statico` serviva a chiunque OGNI
    file in cima a `deploy/` -- `/genera_segreti.sh`, `/backup_casavip.sh`,
    `/nginx.casavip.conf`, `/copia_db.py` rispondevano 200 -- e il 1/10 nel contenitore c'era
    anche una copia `index.html.bak.<numero>`. Spostarli non si puo': il cron del VPS ne chiama
    tre per percorso. Le due direzioni, su una copia di `deploy/` servita dal server vero:
    script, configurazioni e copie -> 404; le pagine e i file che le pagine chiamano -> serviti."""
    WEB = (".html", ".js", ".css", ".json", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".ico")
    SONDATI = ("genera_segreti.sh", "backup_casavip.sh", "nginx.casavip.conf", "copia_db.py")
    COPIA = "index.html.bak.1783682091"

    @classmethod
    def setUpClass(cls):
        qui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deploy")
        cls.dir = tempfile.mkdtemp()
        cls.sito = os.path.join(cls.dir, "deploy")
        os.mkdir(cls.sito)
        for nome in os.listdir(qui):
            if os.path.isfile(os.path.join(qui, nome)):
                shutil.copyfile(os.path.join(qui, nome), os.path.join(cls.sito, nome))
        shutil.copyfile(os.path.join(qui, "index.html"), os.path.join(cls.sito, cls.COPIA))
        # un file per ogni estensione ammessa, piu' una scritta in maiuscolo: nel repository
        # mancano css e immagini e `manifest.json` non e' versionato, e senza questi una voce
        # tolta dall'elenco della produzione non farebbe diventare rosso niente.
        for nome in ["banco" + e for e in cls.WEB] + ["maiuscole.PNG"]:
            with open(os.path.join(cls.sito, nome), "w", encoding="utf-8") as f:
                f.write("banco " + nome)
        d = cls.dir
        # come test_happy_altro: niente marca temporale in rete, niente pulizia degli
        # uploads veri del computer, e il gate acceso (le pagine riservate devono dare 302).
        cls._env_prec = {k: os.environ.get(k) for k in
                         ("MARCA_TEMPORALE", "UPLOAD_DIR", "OUTREACH_OPTOUT_FILE", "PAGE_GATE")}
        os.environ["MARCA_TEMPORALE"] = "0"
        os.environ["UPLOAD_DIR"] = d + "/uploads"
        os.environ["OUTREACH_OPTOUT_FILE"] = d + "/optout.json"
        os.environ.pop("PAGE_GATE", None)
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"s" * 32,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_finanza=f"{d}/fin.db"))
        cls.porta = _porta_libera()
        threading.Thread(
            target=fase83_server.servi,
            kwargs=dict(sistema=sis, host="127.0.0.1", porta=cls.porta,
                        cartella_statica=cls.sito, host_key="hk", admin_key="ak"),
            daemon=True).start()
        for _ in range(200):
            try:
                pronto = cls._get("/robots.txt")[0] == 200
            except (OSError, http.client.HTTPException):
                pronto = False                      # il server non ascolta ancora
            if pronto:
                break
            time.sleep(0.03)

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._env_prec.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.dir, ignore_errors=True)

    @classmethod
    def _get(cls, percorso):
        c = http.client.HTTPConnection("127.0.0.1", cls.porta, timeout=6)
        c.request("GET", percorso)
        r = c.getresponse()
        corpo = r.read().decode("utf-8", "replace")
        c.close()
        return r.status, corpo

    def test_SCRIPT_CONFIGURAZIONI_E_COPIE_NON_ESCONO_DAL_SITO(self):
        fuori = sorted(n for n in os.listdir(self.sito)
                       if os.path.splitext(n)[1].lower() not in self.WEB)
        # S1: un elenco vuoto direbbe «non esce niente» senza aver guardato niente.
        for atteso in self.SONDATI + (self.COPIA,):
            self.assertIn(atteso, fuori, "manca dal banco un file sondato sul sito vero")
        usciti = []
        for nome in fuori:
            with open(os.path.join(self.sito, nome), "rb") as f:
                inizio = f.read(60).decode("utf-8", "replace").strip()
            for percorso in ("/" + nome, "/qualunque/" + nome):
                st, corpo = self._get(percorso)
                if st != 404 or (inizio and inizio in corpo):
                    usciti.append("%s -> %s" % (percorso, st))
        self.assertEqual(usciti, [], "%d richieste su %d hanno avuto il file"
                         % (len(usciti), 2 * len(fuori)))

    def test_UN_FILE_CHE_NON_C_E_O_UN_NOME_RIFIUTATO_DANNO_404(self):
        # la condizione riscritta in `_statico` porta anche i due controlli di prima: il file
        # che non esiste e il nome che `percorso_statico_sicuro` rifiuta (None).
        for percorso in ("/non-esiste.html", "/.env"):
            self.assertEqual(self._get(percorso)[0], 404, percorso)

    def test_LE_PAGINE_E_I_FILE_CHE_CHIAMANO_ESCONO_ANCORA(self):
        riservate = {"admin.html", "bunker.html", "host.html"}
        sito = sorted(n for n in os.listdir(self.sito)
                      if os.path.splitext(n)[1].lower() in self.WEB)
        chiamati = set()
        for n in sito:
            if n.endswith((".html", ".js")):
                with open(os.path.join(self.sito, n), encoding="utf-8") as f:
                    chiamati |= set(re.findall(
                        r'["\'](/[A-Za-z0-9_\-]+\.[a-z]+)(?:\?[^"\']*)?["\']', f.read()))
        chiamati = {c for c in chiamati if os.path.isfile(os.path.join(self.sito, c[1:]))}
        # S7: la premessa e' che le pagine chiamino davvero file che stanno in `deploy/`.
        for atteso in ("/app.js", "/icon.svg", "/privacy.html"):
            self.assertIn(atteso, chiamati)
        rotti = []
        for percorso in sorted({"/" + n for n in sito} | chiamati | {"/", "/grazie"}):
            st, _ = self._get(percorso)
            atteso = 302 if os.path.basename(percorso) in riservate else 200
            if st != atteso:
                rotti.append("%s -> %s (atteso %s)" % (percorso, st, atteso))
        self.assertEqual(rotti, [])


if __name__ == "__main__":
    unittest.main()
