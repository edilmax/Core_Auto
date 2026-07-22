"""GUARDIA — registrazione/login host: blindati MA gentili con chi sbaglia in buona fede.

Nasce da un caso VERO nei log di produzione (2026-07-22): un host e' finito in lockout sul
login provando la password. Diagnosi e bonifica:

  1. RATE LIMITER ricalibrato: 8 tentativi/min (era 5), primo blocco 30s (era 60), blocco
     MASSIMO 10 min (era 60). Difende dal brute-force, ma un host onesto non resta mai
     chiuso fuori un'ora. Resta PER IP (mai per-email: sarebbe un DoS sull'host onesto).
  2. I CAMPI OPZIONALI (Line/WeChat) compilati male danno un errore CHIARO e SPECIFICO, e
     NON passano dal rate limiter del login: sbagliare un campo opzionale non deve MAI
     consumare i tentativi d'accesso ne' far scattare 'troppi_tentativi'.
  3. "email gia' registrata" (-> accedi) e' DISTINTA da "credenziali non valide" (-> login
     fallito), e i codici hanno messaggi chiari in 8 lingue (mai piu' il codice grezzo).

Questa guardia prova tutte e tre le cose, dal server al testo mostrato all'utente.
"""

import io
import json
import os
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import (crea_router, _line_token_valido, _wechat_webhook_valido)
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

QUI = os.path.dirname(os.path.abspath(__file__))
IP = {"X-Forwarded-For": "203.0.113.7"}       # un IP finto ma reale-forma per il rate limit


class _Base(unittest.TestCase):

    def setUp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"A" * 32, con_registrazione_host=True,
            db_registro_host="%s/r.db" % d, db_accettazioni="%s/a.db" % d,
            db_catalogo="%s/c.db" % d, db_inventario="%s/i.db" % d))
        self.r = crea_router(self.sys, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")

    def g(self, m, p, b=None, h=None):
        head = dict(IP)
        head.update(h or {})
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, head)

    def _registra(self, **extra):
        corpo = {"email": "host@x.com", "password": "password1",
                 "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
                 "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE}
        corpo.update(extra)
        return self.g("POST", "/api/host/registrazione", corpo)


class TestValidatoriCanali(unittest.TestCase):
    """I campi OPZIONALI sono opzionali: vuoto = valido; compilato male = no."""

    def test_line_token(self):
        for buono in ("", "aBc12345token", "XYZ_abc-123456789"):
            self.assertTrue(_line_token_valido(buono), buono)
        for cattivo in ("mario@gmail.com", "ha spazi", "https://x.com/a", "corto"):
            self.assertFalse(_line_token_valido(cattivo), cattivo)

    def test_wechat_webhook(self):
        for buono in ("", "https://qyapi.weixin.qq.com/cgi-bin/webhook?key=x"):
            self.assertTrue(_wechat_webhook_valido(buono), buono)
        for cattivo in ("mario@gmail.com", "testo a caso", "http://x.com", "ftp://x.y"):
            self.assertFalse(_wechat_webhook_valido(cattivo), cattivo)


class TestCampiOpzionaliNonBloccano(_Base):

    def test_line_sbagliato_da_errore_specifico(self):
        st, c = self._registra(email="a@x.com", line_token="mario@gmail.com")
        self.assertEqual(st, 422, c)
        self.assertEqual(c.get("errore"), "line_token_non_valido")
        self.assertEqual(c.get("campo"), "line_token")

    def test_wechat_sbagliato_da_errore_specifico(self):
        st, c = self._registra(email="b@x.com", wechat_webhook="mario@gmail.com")
        self.assertEqual(st, 422, c)
        self.assertEqual(c.get("errore"), "wechat_webhook_non_valido")
        self.assertEqual(c.get("campo"), "wechat_webhook")

    def test_campo_opzionale_NON_consuma_i_tentativi_di_login(self):
        """Il cuore della richiesta: 10 registrazioni con un campo opzionale sbagliato non
        devono far scattare 'troppi_tentativi' al login (percorsi separati, la
        registrazione non tocca il rate limiter)."""
        for i in range(10):
            st, _c = self._registra(email="c@x.com", line_token="@non valido@")
            self.assertEqual(st, 422)
        # dopo dieci registrazioni fallite, il login NON e' bloccato
        st, c = self.g("POST", "/api/host/login",
                       {"email": "nessuno@x.com", "password": "qualsiasi1"})
        self.assertNotEqual(st, 429,
                            "un campo opzionale sbagliato ha consumato i tentativi di login")
        self.assertEqual(c.get("errore"), "credenziali_non_valide")

    def test_campo_valido_o_vuoto_lascia_registrare(self):
        st, c = self._registra(email="ok@x.com", line_token="",
                               wechat_webhook="https://qyapi.weixin.qq.com/cgi-bin/x?key=1")
        self.assertEqual(st, 201, c)


class TestErroriDistinti(_Base):

    def test_gia_registrata_vs_credenziali_non_valide(self):
        st, c = self._registra(email="dup@x.com", password="password1")
        self.assertEqual(st, 201, c)
        # ri-registrare la STESSA email -> 'email_gia_registrata' (accedi, non registrarti)
        st, c = self._registra(email="dup@x.com", password="password1")
        self.assertEqual(st, 409, c) if st == 409 else self.assertIn(st, (409, 422, 400), c)
        self.assertEqual(c.get("errore"), "email_gia_registrata")
        # login con password SBAGLIATA -> 'credenziali_non_valide' (distinto)
        st, c = self.g("POST", "/api/host/login",
                       {"email": "dup@x.com", "password": "sbagliata9"})
        self.assertEqual(st, 401, c)
        self.assertEqual(c.get("errore"), "credenziali_non_valide")

    def test_login_giusto_funziona(self):
        self._registra(email="vero@x.com", password="password1")
        st, c = self.g("POST", "/api/host/login",
                       {"email": "vero@x.com", "password": "password1"})
        self.assertEqual(st, 200, c)
        self.assertTrue(c.get("token"))


class TestRateLimiterRicalibrato(_Base):

    def test_otto_tentativi_prima_del_blocco_poi_429(self):
        self._registra(email="rl@x.com", password="password1")
        # 8 tentativi sbagliati sono ammessi (soglia 8/min), il 9° blocca
        visti = []
        for i in range(9):
            st, _c = self.g("POST", "/api/host/login",
                            {"email": "rl@x.com", "password": "sbagliata%d" % i})
            visti.append(st)
        self.assertTrue(all(s == 401 for s in visti[:8]),
                        "un tentativo prima dell'ottavo e' stato bloccato: %s" % visti)
        self.assertEqual(visti[8], 429, "il 9° tentativo non e' bloccato: %s" % visti)

    def test_il_login_giusto_azzera_e_non_penalizza_il_vero(self):
        self._registra(email="rl2@x.com", password="password1")
        for i in range(5):
            self.g("POST", "/api/host/login",
                   {"email": "rl2@x.com", "password": "no%d" % i})
        # dopo 5 errori, la password GIUSTA passa (sotto soglia 8) e azzera lo storico
        st, c = self.g("POST", "/api/host/login",
                       {"email": "rl2@x.com", "password": "password1"})
        self.assertEqual(st, 200, c)

    def test_soglia_e_blocco_massimo_ricalibrati_nel_codice(self):
        with io.open(os.path.join(QUI, "fase83_server.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("soglia=8", src, "la soglia non e' 8")
        self.assertIn("max_blocco_sec=600", src, "il blocco massimo non e' 10 minuti")
        self.assertNotIn("max_blocco_sec=3600", src, "e' rimasto il blocco da un'ora")


class TestMessaggiChiariLocalizzati(unittest.TestCase):
    """Il testo mostrato all'utente non e' piu' il codice grezzo."""

    def _appjs(self):
        with io.open(os.path.join(QUI, "deploy", "app.js"), encoding="utf-8") as f:
            return f.read()

    def test_ogni_codice_auth_ha_un_messaggio_in_8_lingue(self):
        import re
        src = self._appjs()
        self.assertIn("BV.ERR_AUTH", src, "manca il dizionario dei messaggi auth")
        # tutte le 8 lingue presenti nel blocco ERR_AUTH
        blocco = src[src.index("BV.ERR_AUTH"):src.index("BV.fraseErrore")]
        for lg in ("it", "en", "es", "fr", "de", "pt", "ja", "zh"):
            self.assertRegex(blocco, r"\b%s:\{" % lg, "ERR_AUTH manca la lingua %s" % lg)
        # ogni codice-chiave presente
        for cod in ("troppi_tentativi", "credenziali_non_valide", "email_gia_registrata",
                    "line_token_non_valido", "wechat_webhook_non_valido", "consensi_mancanti"):
            self.assertIn(cod + ":", blocco, "ERR_AUTH non spiega '%s'" % cod)

    def test_fraseErrore_usa_i_messaggi_auth(self):
        src = self._appjs()
        # fraseErrore deve consultare ERR_AUTH prima di ripiegare sul codice grezzo
        fe = src[src.index("BV.fraseErrore"):src.index("BV.fraseErrore") + 600]
        self.assertIn("ERR_AUTH", fe,
                      "fraseErrore non usa i messaggi auth: mostrerebbe il codice grezzo")


class TestValidazioneClientNellaPagina(unittest.TestCase):
    """La pagina host valida i campi opzionali PRIMA di inviare, con errore sotto il campo."""

    def _host(self):
        with io.open(os.path.join(QUI, "deploy", "host.html"), encoding="utf-8") as f:
            return f.read()

    def test_ci_sono_i_validatori_e_gli_errori_di_campo(self):
        h = self._host()
        for pezzo in ("function lineTokenValido", "function wechatWebhookValido",
                      "function validaCanali", 'id="err_line"', 'id="err_wechat"',
                      "class=\"fieldErr\""):
            self.assertIn(pezzo, h, "manca nella pagina host: %s" % pezzo)

    def test_la_registrazione_si_ferma_se_i_canali_sono_invalidi(self):
        h = self._host()
        # nel click di registrazione, validaCanali() blocca prima della chiamata al server
        reg = h[h.index("btnRegister').onclick"):]
        reg = reg[:reg.index("authPost('/api/host/registrazione'")]
        self.assertIn("validaCanali()", reg,
                      "il tasto Registrati non valida i canali prima di inviare")


if __name__ == "__main__":
    unittest.main(verbosity=2)
