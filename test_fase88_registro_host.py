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


class TestPromozioneNonSiRicicla(unittest.TestCase):
    """LA PROMOZIONE 0% DEI PRIMI 90 GIORNI NON SI RICICLA.

    La commissione a rampa (0% primi 90 giorni · 8% fino a un anno · 10% a regime) parte da
    `creato_ts`. La cancellazione totale (fase156) fa DELETE e non lasciava tracce: bastava
    farsi cancellare e ri-registrarsi per avere altri 90 giorni a commissione zero, e
    nessuno se ne sarebbe accorto.

    Ora, PRIMA di cancellare, restano SOLO IMPRONTE IRREVERSIBILI (HMAC con la nostra
    chiave) di email, telefono, codice fiscale, P.IVA e CIN degli annunci -- MAI i dati.
    Dall'impronta non si risale a niente e non si puo' contattare nessuno; serve solo a
    riconoscere che quella struttura e' gia' stata da noi.

    Email e telefono si cambiano in dieci secondi. CODICE FISCALE e CIN no: quelli li
    rilascia lo Stato. Per questo sono le chiavi che contano davvero.

    ⚠️ E la direzione OPPOSTA vale quanto l'altra: un host DAVVERO NUOVO deve avere i suoi
    90 giorni. Riconoscerlo per sbaglio significherebbe RUBARGLI dei soldi -- stesso peso
    di un falso allarme.
    """

    def setUp(self):
        self.reg = crea_registro_host(":memory:", SEG)

    def _nato(self, host_id):
        """`info_host` non espone `creato_ts`: si legge qui, senza aggiungere un metodo alla
        produzione solo per rendere provabile il test."""
        con = self.reg._apri()
        try:
            r = con.execute("SELECT creato_ts FROM host WHERE host_id=?", (host_id,)).fetchone()
        finally:
            con.close()
        self.assertIsNotNone(r, "host %s non trovato" % host_id)
        return int(r[0])

    def _invecchia(self, host_id, giorni):
        """Sposta indietro la data d'iscrizione. Si fa QUI, con una UPDATE nel test: non si
        aggiunge un metodo alla produzione solo per rendere provabile un test."""
        con = self.reg._apri()
        try:
            with con:
                con.execute("UPDATE host SET creato_ts=creato_ts-? WHERE host_id=?",
                            (int(giorni) * 86400, host_id))
        finally:
            con.close()

    def test_stessa_email_dopo_la_cancellazione_NON_azzera_l_anzianita(self):
        e1 = self.reg.registra("furbo@x.it", "passwordlunga", accetta_termini=True,
                               telefono="+39 333 1234567")
        self._invecchia(e1.host_id, 200)                 # host di 200 giorni
        vecchio = self._nato(e1.host_id)

        self.assertGreater(self.reg.deposita_impronte(e1.host_id), 0, "impronte non depositate")
        self.reg.cancella_host(e1.host_id)

        e2 = self.reg.registra("furbo@x.it", "passwordlunga", accetta_termini=True)
        self.assertTrue(e2.ok, e2.errore)
        self.assertEqual(self._nato(e2.host_id), vecchio,
                         "la promozione si e' riciclata: l'anzianita' e' ripartita da zero")

    def test_email_NUOVA_ma_stesso_telefono_viene_riconosciuto(self):
        e1 = self.reg.registra("uno@x.it", "passwordlunga", accetta_termini=True,
                               telefono="+39 333 9999999")
        self._invecchia(e1.host_id, 200)
        vecchio = self._nato(e1.host_id)
        self.reg.deposita_impronte(e1.host_id)
        self.reg.cancella_host(e1.host_id)

        e2 = self.reg.registra("due@x.it", "passwordlunga", accetta_termini=True,
                               telefono="+39 333 9999999")      # email nuova, stesso numero
        self.assertEqual(self._nato(e2.host_id), vecchio,
                         "cambiando solo l'email la promozione si e' riciclata")

    def test_un_host_DAVVERO_NUOVO_ha_i_suoi_90_giorni(self):
        """Prova di rimozione: nessun falso riconoscimento, o gli rubiamo la promozione."""
        e1 = self.reg.registra("vecchio@x.it", "passwordlunga", accetta_termini=True,
                               telefono="+39 333 1111111")
        self.reg.deposita_impronte(e1.host_id)
        self.reg.cancella_host(e1.host_id)

        import time as _t
        e2 = self.reg.registra("nuovo@x.it", "passwordlunga", accetta_termini=True,
                               telefono="+39 333 2222222")      # nessun legame col primo
        self.assertGreaterEqual(self._nato(e2.host_id), int(_t.time()) - 5,
                                "a un host NUOVO abbiamo rubato i 90 giorni di promozione")

    def test_le_impronte_non_contengono_i_dati(self):
        """Si conservano IMPRONTE, non dati: nella tabella non dev'esserci nulla di leggibile."""
        e1 = self.reg.registra("chiaro@x.it", "passwordlunga", accetta_termini=True,
                               telefono="+39 333 4444444")
        self.reg.deposita_impronte(e1.host_id)
        con = self.reg._apri()
        try:
            righe = con.execute("SELECT impronta FROM host_impronte").fetchall()
        finally:
            con.close()
        tutto = " ".join(str(r[0]) for r in righe)
        self.assertGreater(len(righe), 0, "nessuna impronta depositata")
        self.assertNotIn("chiaro@x.it", tutto, "l'email e' conservata IN CHIARO")
        self.assertNotIn("4444444", tutto, "il telefono e' conservato IN CHIARO")


if __name__ == "__main__":
    unittest.main()
