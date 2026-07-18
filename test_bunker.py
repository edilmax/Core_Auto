"""Collaudo BUNKER (fase180) — 2FA TOTP + sessione blindata.

Sicurezza-critica: il TOTP e' provato contro il VETTORE UFFICIALE RFC 6238 (secret
"12345678901234567890", SHA1) -> l'implementazione e' esatta, non "sembra giusta".
Invarianti:
  1. TOTP: codice giusto al tempo giusto = ok; sbagliato = no; drift +-1 passo tollerato,
     +-2 no; formati ostili (non 6 cifre) = no;
  2. sessione: firmata, scade a 15 min, LEGATA all'IP (token rubato da altro IP = negato),
     manomessa = negata;
  3. secondo fattore: TOTP valido -> 'totp'; break-glass -> 'break_glass'; altro -> ''.
"""
import base64
import json
import shutil
import tempfile
import time
import unittest

import fase180_bunker as bk
from fase59_concierge import FirmaQuote
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

# vettore RFC 6238: secret ASCII "12345678901234567890" -> base32
SEG_RFC = base64.b32encode(b"12345678901234567890").decode("ascii")


class TestTOTP(unittest.TestCase):
    def test_vettore_ufficiale_rfc6238(self):
        # a t=59s (passo 1) il codice a 8 cifre RFC e' 94287082 -> a 6 cifre = 287082
        self.assertEqual(bk._codice_at(SEG_RFC, 59 // 30), "287082")
        self.assertTrue(bk.verifica_totp(SEG_RFC, "287082", ora=59))
        # a t=1111111109 il codice 8-cifre e' 07081804 -> 6 cifre 081804
        self.assertTrue(bk.verifica_totp(SEG_RFC, "081804", ora=1111111109))

    def test_sbagliato_e_formati_ostili(self):
        self.assertFalse(bk.verifica_totp(SEG_RFC, "000000", ora=59))
        for cattivo in ("", "12345", "1234567", "abcdef", None, 287082):
            self.assertFalse(bk.verifica_totp(SEG_RFC, cattivo, ora=59))

    def test_drift(self):
        base = 59
        self.assertTrue(bk.verifica_totp(SEG_RFC, "287082", ora=base))
        # +-1 passo (30s) tollerato
        self.assertTrue(bk.verifica_totp(SEG_RFC, "287082", ora=base + 25))
        self.assertTrue(bk.verifica_totp(SEG_RFC, "287082", ora=base - 25))
        # +-2 passi NO
        self.assertFalse(bk.verifica_totp(SEG_RFC, "287082", ora=base + 70))

    def test_segreto_e_uri(self):
        s = bk.genera_segreto()
        self.assertGreaterEqual(len(s), 30)
        uri = bk.otpauth_uri(s, account="super-admin")
        self.assertIn("otpauth://totp/", uri)
        self.assertIn("secret=" + s, uri)


class TestSessione(unittest.TestCase):
    def setUp(self):
        self.firma = FirmaQuote(b"S" * 32)
        self.clock = {"t": 1000.0}
        self.b = bk.crea_bunker(self.firma, totp_secret=SEG_RFC,
                                password="PasswordSuperAdmin@1",
                                break_glass="ROMPI-IL-VETRO-9",
                                orologio=lambda: self.clock["t"])

    def test_secondo_fattore(self):
        self.clock["t"] = 59
        self.assertEqual(self.b.verifica_secondo_fattore("287082"), "totp")
        self.assertEqual(self.b.verifica_secondo_fattore("PasswordSuperAdmin@1"), "password")
        self.assertEqual(self.b.verifica_secondo_fattore("ROMPI-IL-VETRO-9"), "break_glass")
        self.assertEqual(self.b.verifica_secondo_fattore("000000"), "")
        self.assertEqual(self.b.verifica_secondo_fattore(""), "")
        # solo password configurata -> il bunker e' comunque configurato
        solo_pw = bk.crea_bunker(self.firma, password="X")
        self.assertTrue(solo_pw.configurato)
        self.assertEqual(solo_pw.verifica_secondo_fattore("X"), "password")

    def test_sessione_valida_scade_e_legata_ip(self):
        tok = self.b.crea_sessione("203.0.113.5")
        self.assertTrue(tok)
        self.assertTrue(self.b.valida_sessione(tok, "203.0.113.5")["ok"])
        # IP diverso -> negata (token rubato riusato altrove)
        r = self.b.valida_sessione(tok, "198.51.100.1")
        self.assertFalse(r["ok"])
        self.assertEqual(r["motivo"], "ip_non_coincidente")
        # scade a 15 min
        self.clock["t"] += bk.DURATA_SESSIONE_SEC + 1
        self.assertEqual(self.b.valida_sessione(tok, "203.0.113.5")["motivo"],
                         "sessione_scaduta")

    def test_manomessa(self):
        tok = self.b.crea_sessione("203.0.113.5")
        self.assertFalse(self.b.valida_sessione(tok + "x", "203.0.113.5")["ok"])
        self.assertFalse(self.b.valida_sessione("robaccia", "203.0.113.5")["ok"])
        # un token firmato ma NON di tipo bunker (es. un altro payload) e' rifiutato
        altro = self.firma.codifica({"k": "quote", "exp": 9999999999})
        self.assertFalse(self.b.valida_sessione(altro, "203.0.113.5")["ok"])

    def test_configurato(self):
        self.assertTrue(self.b.configurato)
        spento = bk.crea_bunker(self.firma, totp_secret="", break_glass="")
        self.assertFalse(spento.configurato)

    def test_logout_server_side_revoca(self):
        tok = self.b.crea_sessione("203.0.113.5")
        self.assertTrue(self.b.valida_sessione(tok, "203.0.113.5")["ok"])
        self.assertTrue(self.b.revoca(tok))            # LOGOUT server-side
        r = self.b.valida_sessione(tok, "203.0.113.5")
        self.assertFalse(r["ok"])                      # il token e' morto SUBITO
        self.assertEqual(r["motivo"], "sessione_revocata")
        # revocare robaccia non esplode
        self.assertFalse(self.b.revoca("robaccia"))


class TestBunkerEndpoint(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_finanza=f"{d}/fin.db",
            bunker_totp_secret=SEG_RFC, bunker_recovery="ROMPI9"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak")
        self.assertTrue(self.sis.bunker.configurato)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _codice_ora(self):
        return bk._codice_at(SEG_RFC, int(time.time() // 30))

    def _login(self, codice, admin="ak", ip="203.0.113.1"):
        h = {"X-Forwarded-For": ip}
        if admin is not None:
            h["X-Admin-Key"] = admin
        return self.r.gestisci("POST", "/api/bunker/login", {},
                               json.dumps({"codice": codice}), h)

    def test_login_flusso_completo(self):
        # senza chiave admin -> 401 (1° fattore mancante)
        s, _ = self._login(self._codice_ora(), admin=None)
        self.assertEqual(s, 401)
        # chiave admin ok ma TOTP sbagliato -> 403
        s, _ = self._login("000000")
        self.assertEqual(s, 403)
        # chiave admin + TOTP giusto -> 200 + sessione
        s, out = self._login(self._codice_ora())
        self.assertEqual(s, 200, out)
        self.assertTrue(out["sessione"])
        self.assertEqual(out["scade_tra_sec"], 900)
        sess = out["sessione"]
        # stato: senza sessione -> 403; con sessione (stesso IP) -> 200
        s, _ = self.r.gestisci("GET", "/api/bunker/stato", {}, None,
                               {"X-Forwarded-For": "203.0.113.1"})
        self.assertEqual(s, 403)
        s, rep = self.r.gestisci("GET", "/api/bunker/stato", {}, None,
                                 {"X-Bunker-Session": sess, "X-Forwarded-For": "203.0.113.1"})
        self.assertEqual(s, 200, rep)
        self.assertTrue(rep["bunker"])
        self.assertIn("diagnosi", rep)
        # sessione riusata da un ALTRO IP -> negata
        s, _ = self.r.gestisci("GET", "/api/bunker/stato", {}, None,
                               {"X-Bunker-Session": sess, "X-Forwarded-For": "9.9.9.9"})
        self.assertEqual(s, 403)

    def test_break_glass(self):
        s, out = self._login("ROMPI9")
        self.assertEqual(s, 200)
        self.assertEqual(out["modo"], "break_glass")

    def test_logout_endpoint_uccide_la_sessione(self):
        s, out = self._login(self._codice_ora())
        sess = out["sessione"]
        # la sessione funziona
        s, _ = self.r.gestisci("GET", "/api/bunker/stato", {}, None,
                               {"X-Bunker-Session": sess, "X-Forwarded-For": "203.0.113.1"})
        self.assertEqual(s, 200)
        # LOGOUT server-side
        s, _ = self.r.gestisci("POST", "/api/bunker/logout", {}, None,
                               {"X-Bunker-Session": sess, "X-Forwarded-For": "203.0.113.1"})
        self.assertEqual(s, 200)
        # ora la STESSA sessione e' morta (revocata sul server, non solo nel browser)
        s, _ = self.r.gestisci("GET", "/api/bunker/stato", {}, None,
                               {"X-Bunker-Session": sess, "X-Forwarded-For": "203.0.113.1"})
        self.assertEqual(s, 403)

    def test_bunker_spento_503(self):
        d = tempfile.mkdtemp()
        try:
            sis = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=b"S" * 32,
                db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
                db_registro_host=f"{d}/r.db"))   # nessun segreto bunker
            r = crea_router(sis, admin_key="ak")
            s, _ = r.gestisci("POST", "/api/bunker/login", {},
                              json.dumps({"codice": "123456"}), {"X-Admin-Key": "ak"})
            self.assertEqual(s, 503)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
