"""
Test Fase 88 - Registro Host self-service.

Copre: registrazione (termini obbligatori, email/password validate, email unica), password
mai in chiaro + hash robusto, login (giusto/sbagliato/sospeso, niente leak utenti), token
firmato verificabile + scadenza + manomissione, sospensione invalida il token.
"""
import unittest

from fase88_registro_host import _hash_password, crea_registro_host

SEG = b"0123456789abcdef0123456789abcdef"


class TestRegistrazione(unittest.TestCase):
    def setUp(self):
        self.reg = crea_registro_host(":memory:", SEG)

    def test_registra_ok(self):
        e = self.reg.registra("Host@Mail.it", "passwordlunga", accetta_termini=True,
                              ragione_sociale="B&B Sole")
        self.assertTrue(e.ok)
        self.assertTrue(e.host_id.startswith("h_"))
        self.assertTrue(e.token)
        # il token identifica proprio quell'host
        self.assertEqual(self.reg.verifica_token(e.token), e.host_id)

    def test_termini_obbligatori(self):
        e = self.reg.registra("a@b.it", "passwordlunga", accetta_termini=False)
        self.assertFalse(e.ok)
        self.assertEqual(e.errore, "termini_non_accettati")

    def test_email_e_password_validate(self):
        self.assertEqual(self.reg.registra("non-email", "passwordlunga",
                                           accetta_termini=True).errore, "email_non_valida")
        self.assertEqual(self.reg.registra("a@b.it", "corta",
                                           accetta_termini=True).errore,
                         "password_troppo_corta")

    def test_email_unica(self):
        self.reg.registra("dup@b.it", "passwordlunga", accetta_termini=True)
        e = self.reg.registra("DUP@b.it", "altrapassword", accetta_termini=True)
        self.assertEqual(e.errore, "email_gia_registrata")    # case-insensitive

    def test_password_mai_in_chiaro(self):
        self.reg.registra("p@b.it", "segretissima", accetta_termini=True)
        con = self.reg._apri()
        try:
            row = con.execute("SELECT pw_hash, salt FROM host WHERE email='p@b.it'"
                              ).fetchone()
        finally:
            con.close()
        self.assertNotIn("segretissima", row["pw_hash"])
        self.assertEqual(len(row["pw_hash"]), 64)             # sha256 hex
        # l'hash dipende dal salt: due salt diversi -> hash diversi
        self.assertNotEqual(_hash_password("x", b"a" * 16), _hash_password("x", b"b" * 16))


class TestLogin(unittest.TestCase):
    def setUp(self):
        self.reg = crea_registro_host(":memory:", SEG)
        self.reg.registra("host@b.it", "passwordlunga", accetta_termini=True)

    def test_login_ok(self):
        e = self.reg.login("HOST@b.it", "passwordlunga")
        self.assertTrue(e.ok)
        self.assertTrue(self.reg.verifica_token(e.token))

    def test_login_password_errata(self):
        self.assertEqual(self.reg.login("host@b.it", "sbagliata").errore,
                         "credenziali_non_valide")

    def test_login_utente_inesistente(self):
        # stesso messaggio dell'errore password: niente enumerazione utenti
        self.assertEqual(self.reg.login("nessuno@b.it", "x").errore,
                         "credenziali_non_valide")

    def test_sospensione(self):
        e = self.reg.login("host@b.it", "passwordlunga")
        self.assertTrue(self.reg.imposta_stato(e.host_id, "sospeso"))
        self.assertEqual(self.reg.login("host@b.it", "passwordlunga").errore,
                         "account_sospeso")
        self.assertIsNone(self.reg.verifica_token(e.token))   # token non vale più


class TestToken(unittest.TestCase):
    def test_token_manomesso(self):
        reg = crea_registro_host(":memory:", SEG)
        self.assertIsNone(reg.verifica_token("falso.token"))
        self.assertIsNone(reg.verifica_token(""))
        self.assertIsNone(reg.verifica_token(None))

    def test_token_scaduto(self):
        t = {"v": 1000}
        reg = crea_registro_host(":memory:", SEG, orologio=lambda: t["v"], ttl_token=10)
        e = reg.registra("a@b.it", "passwordlunga", accetta_termini=True)
        self.assertTrue(reg.verifica_token(e.token))
        t["v"] = 2000                                          # ben oltre la scadenza
        self.assertIsNone(reg.verifica_token(e.token))

    def test_token_di_altro_segreto(self):
        e = crea_registro_host(":memory:", SEG).registra("a@b.it", "passwordlunga",
                                                         accetta_termini=True)
        altro = crea_registro_host(":memory:", b"X" * 32)
        self.assertIsNone(altro.verifica_token(e.token))       # firma di un altro segreto


if __name__ == "__main__":
    unittest.main()
