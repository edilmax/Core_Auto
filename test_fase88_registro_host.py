"""
Test Fase 88 - Registro Host self-service.

Copre: registrazione (termini obbligatori, email/password validate, email unica), password
mai in chiaro + hash robusto, login (giusto/sbagliato/sospeso, niente leak utenti), token
firmato verificabile + scadenza + manomissione, sospensione invalida il token.
"""
import unittest

from fase88_registro_host import _hash_password, crea_registro_host

SEG = b"0123456789abcdef0123456789abcdef"


class TestLaRISPOSTAVersoIlMondoEsternoDiceIlVero(unittest.TestCase):
    """`as_dict` e' cio' che il sito RESTITUISCE a chi si registra o entra: e' il confine fra
    il registro e il mondo. La mutazione ha rovesciato il suo `ok` e nessuno se n'e' accorto,
    perche' tutte le prove guardavano l'oggetto interno (`e.ok`) e mai la risposta vera.

    Un successo raccontato come fallimento manda via un host appena registrato; un fallimento
    raccontato come successo gli fa credere di essere dentro quando non lo e'. In entrambi i
    casi il registro sarebbe a posto e il cliente no.
    """

    def setUp(self):
        self.reg = crea_registro_host(":memory:", SEG)

    def test_il_SUCCESSO_si_racconta_come_successo(self):
        e = self.reg.registra("nuovo@mail.it", "passwordlunga", accetta_termini=True)
        d = e.as_dict()
        self.assertIs(True, d["ok"], "una registrazione RIUSCITA viene raccontata come "
                                     "fallita: %r" % (d,))
        self.assertEqual(e.host_id, d["host_id"])
        self.assertEqual(e.token, d["token"])
        self.assertNotIn("errore", d, "un successo non deve portare un errore con se'")

    def test_il_FALLIMENTO_si_racconta_come_fallimento(self):
        e = self.reg.registra("x@y.it", "corta", accetta_termini=True)
        d = e.as_dict()
        self.assertIs(False, d["ok"], "un rifiuto viene raccontato come successo: %r" % (d,))
        self.assertTrue(d.get("errore"), "il rifiuto non dice perche'")
        self.assertNotIn("token", d,
                         "una risposta di FALLIMENTO porta con se' un gettone d'accesso")


class TestIlTEMPODiVitaDelGettoneNonSiAzzera(unittest.TestCase):
    """La durata del gettone d'accesso e' validata all'avvio: se il valore e' assurdo si
    ripiega sul valore di serie. La mutazione ha indebolito quel controllo in due modi e
    nessuno se n'e' accorto: con `>=` un `ttl=0` verrebbe accettato e ogni gettone nascerebbe
    GIA' SCADUTO -- nessuno riuscirebbe piu' a entrare, e il motivo sarebbe invisibile."""

    def test_un_ttl_ASSURDO_ripiega_sul_valore_di_serie(self):
        for cattivo in (0, -1, True, False, "3600", None, 3.5):
            reg = crea_registro_host(":memory:", SEG, ttl_token=cattivo)
            e = reg.registra("a@b.it", "passwordlunga", accetta_termini=True)
            self.assertTrue(e.ok)
            self.assertEqual(e.host_id, reg.verifica_token(e.token),
                             "con ttl_token=%r il gettone non vale: ogni host resterebbe "
                             "fuori dal proprio pannello" % (cattivo,))

    def test_un_ttl_VALIDO_viene_rispettato(self):
        reg = crea_registro_host(":memory:", SEG, ttl_token=7200)
        self.assertEqual(7200, reg._ttl, "un ttl valido e' stato scartato")


class TestLAntiRicicloNonPerdeIlSuoAPPIGLIOPiuForte(unittest.TestCase):
    """L'ANTI-RICICLO PROVATO SUI GUASTI, non solo sul caso felice.

    Scritto la mattina del 2026-07-31, la mutazione l'ha passato al setaccio la sera stessa e
    ha trovato che quasi nessuna delle sue condizioni era sorvegliata. Serve a impedire che un
    host si cancelli e si ri-iscriva per ripartire dal **-0% dei primi 90 giorni**: e' una
    protezione sui SOLDI, non un dettaglio.

    IL PIU' GRAVE: `for v in (extra or ())`. Rovesciando quell'`or` in `and`, l'elenco delle
    impronte EXTRA diventa sempre vuoto -- e le extra sono il **CIN della struttura**, cioe'
    l'unico identificativo che lo Stato rilascia e che un host **non puo' cambiare**. Email e
    telefono si cambiano in due minuti; il CIN no. Perdendolo, la protezione resta in piedi
    solo sulla carta: nessun errore, nessun log, e il primo furbo che si ri-iscrive con
    un'altra email riparte da zero.
    """

    def setUp(self):
        self.reg = crea_registro_host(":memory:", SEG)

    def _riga(self, **campi):
        base = {"email": "h@mail.it", "telefono": "+393331112233",
                "codice_fiscale": "RSSMRA80A01H501U", "partita_iva": ""}
        base.update(campi)
        return base

    def test_il_CIN_finisce_DAVVERO_fra_le_impronte(self):
        senza = self.reg._impronte_di(self._riga())
        con_cin = self.reg._impronte_di(self._riga(), ("IT058091C2XXXXXXXX",))
        self.assertEqual(len(senza) + 1, len(con_cin),
                         "il CIN passato come identificativo EXTRA non e' stato impresso: "
                         "l'anti-riciclo perde l'unico appiglio che l'host non puo' cambiare")
        self.assertTrue(set(senza).issubset(set(con_cin)),
                        "le impronte del registro sono cambiate aggiungendo un extra")

    def test_piu_identificativi_extra_contano_TUTTI(self):
        r = self.reg._impronte_di(self._riga(), ("CIN-UNO", "CIN-DUE"))
        self.assertEqual(len(set(r)), len(r), "impronte duplicate")
        self.assertEqual(5, len(r), "attese 3 dal registro + 2 extra, ottenute %d" % len(r))

    def test_i_valori_VUOTI_o_non_testuali_non_diventano_impronte(self):
        """Un'impronta di stringa vuota sarebbe la STESSA per tutti: un host qualunque
        risulterebbe «gia' visto» e si vedrebbe negare i 90 giorni che gli spettano.
        Negarli per sbaglio significa rubargli dei soldi."""
        pulite = self.reg._impronte_di(self._riga(partita_iva=""))
        sporche = self.reg._impronte_di(self._riga(partita_iva=""), ("", "   ", None, 12345))
        self.assertEqual(pulite, sporche,
                         "un valore vuoto o non testuale e' diventato un'impronta: due host "
                         "diversi risulterebbero la stessa persona")

    def test_deposita_impronte_RIFIUTA_un_host_id_non_valido(self):
        for cattivo in ("", None, 123, b"h_1"):
            self.assertEqual(0, self.reg.deposita_impronte(cattivo),
                             "host_id non valido accettato: %r" % (cattivo,))

    def test_deposita_impronte_su_host_INESISTENTE_non_inventa_nulla(self):
        self.assertEqual(0, self.reg.deposita_impronte("h_mai_esistito"))

    def test_il_deposito_e_IDEMPOTENTE(self):
        """Chiamarlo due volte non deve moltiplicare le impronte ne' spostare la data."""
        e = self.reg.registra("via@mail.it", "passwordlunga", accetta_termini=True,
                              telefono="+393334445566")
        primo = self.reg.deposita_impronte(e.host_id, extra=("CIN-X",))
        secondo = self.reg.deposita_impronte(e.host_id, extra=("CIN-X",))
        self.assertEqual(primo, secondo, "il secondo deposito conta un numero diverso")
        con = self.reg._apri()
        try:
            n = con.execute("SELECT COUNT(*) FROM host_impronte").fetchone()[0]
        finally:
            con.close()
        self.assertEqual(primo, n, "le impronte si sono moltiplicate: %d righe per %d impronte"
                         % (n, primo))


class TestIlRipristinoPasswordRIFIUTADavvero(unittest.TestCase):
    """IL PUNTO PIU' PERICOLOSO TROVATO DALLA MUTAZIONE il 2026-07-31.

    `reset_password` e' il magic-link: chi lo attraversa **cambia la password di un host** ed
    entra nel suo pannello -- pagamenti, dati, incassi. E' la via classica per impadronirsi di
    un account.

    Il modulo ha 4 rifiuti in quella funzione (link non valido · link scaduto · password
    troppo corta · link gia' usato). La mutazione li ha rovesciati tutti e quattro in
    «accettato» e **nessun test se n'e' accorto**: nel file del registro non c'era una sola
    prova sul ripristino, e gli altri file che lo nominano provano solo il caso FELICE.
    Un rifiuto che nessuno verifica e' una porta che sembra chiusa.

    Il codice di produzione E' CORRETTO: qui si aggiungono le guardie che mancavano, piu' i
    due CONFINI (la scadenza e la lunghezza minima) che nessuno toccava.
    """

    def setUp(self):
        self.reg = crea_registro_host(":memory:", SEG)
        self.e = self.reg.registra("host@mail.it", "passwordlunga", accetta_termini=True)
        self.assertTrue(self.e.ok)

    def _link(self):
        t = self.reg.token_reset_password("host@mail.it")
        self.assertTrue(t, "il magic-link non viene emesso: la prova non vale")
        return t

    def test_un_link_MANOMESSO_non_cambia_la_password(self):
        for cattivo in (self._link() + "x", "robaccia", "", None, 12345):
            e = self.reg.reset_password(cattivo, "nuovapasswordlunga")
            self.assertFalse(e.ok, "link manomesso ACCETTATO: %r" % (cattivo,))
            self.assertEqual("link_non_valido", e.errore)
        # e la password vecchia funziona ancora: nessun effetto collaterale
        self.assertTrue(self.reg.login("host@mail.it", "passwordlunga").ok)

    def test_un_link_di_ALTRO_TIPO_non_vale_come_ripristino(self):
        """Un gettone firmato da noi ma nato per un'altra cosa non deve aprire questa porta."""
        altro = self.reg._firma.codifica({"tipo": "quote", "host_id": self.e.host_id,
                                          "exp": 9999999999})
        esito = self.reg.reset_password(altro, "nuovapasswordlunga")
        self.assertFalse(esito.ok, "un gettone di tipo diverso ha cambiato la password")
        self.assertEqual("link_non_valido", esito.errore)

    def test_un_link_SCADUTO_non_cambia_la_password(self):
        orologio = {"t": 1_000_000}
        reg = crea_registro_host(":memory:", SEG, orologio=lambda: orologio["t"])
        reg.registra("a@b.it", "passwordlunga", accetta_termini=True)
        tok = reg.token_reset_password("a@b.it")
        orologio["t"] += 1801                       # il link dura 30 minuti
        esito = reg.reset_password(tok, "nuovapasswordlunga")
        self.assertFalse(esito.ok, "link SCADUTO accettato: la porta resta aperta per sempre")
        self.assertEqual("link_scaduto", esito.errore)
        self.assertTrue(reg.login("a@b.it", "passwordlunga").ok)

    def test_un_link_GIA_USATO_non_vale_una_seconda_volta(self):
        """SINGLE-USE: dentro il link c'e' l'impronta dell'hash attuale, quindi appena la
        password cambia il link diventa carta straccia. Se non fosse cosi', chiunque abbia
        visto quel link una volta potrebbe rientrare quando vuole."""
        tok = self._link()
        self.assertTrue(self.reg.reset_password(tok, "primanuovapassword").ok)
        esito = self.reg.reset_password(tok, "secondanuovapassword")
        self.assertFalse(esito.ok, "il magic-link e' stato riusato: NON e' single-use")
        self.assertEqual("link_non_valido", esito.errore)
        # e la password buona resta la prima nuova
        self.assertTrue(self.reg.login("host@mail.it", "primanuovapassword").ok)
        self.assertFalse(self.reg.login("host@mail.it", "secondanuovapassword").ok)

    def test_una_password_TROPPO_CORTA_viene_rifiutata_e_il_CONFINE_e_giusto(self):
        """Il minimo e' 8 caratteri: 7 no, 8 SI. Il mutante che stringeva il confine a 9
        e' sopravvissuto -- nessuno provava quel punto, e avrebbe rifiutato password
        legittime senza che nessuno capisse perche'."""
        esito = self.reg.reset_password(self._link(), "corta12")          # 7
        self.assertFalse(esito.ok, "password di 7 caratteri accettata")
        self.assertEqual("password_troppo_corta", esito.errore)
        for cattiva in (None, 12345678, b"ottobyte"):
            self.assertFalse(self.reg.reset_password(self._link(), cattiva).ok,
                             "password non testuale accettata: %r" % (cattiva,))
        self.assertTrue(self.reg.reset_password(self._link(), "otto1234").ok,
                        "password di 8 caratteri ESATTI rifiutata: il confine e' storto")

    def test_a_host_SOSPESO_non_si_emette_nemmeno_il_link(self):
        """Anti-enumerazione: a un host non attivo non si dice «non esiste», si tace --
        ma soprattutto non gli si apre una porta."""
        self.reg.sospendi(self.e.host_id) if hasattr(self.reg, "sospendi") else None
        con = self.reg._apri()
        con.execute("UPDATE host SET stato='sospeso' WHERE host_id=?", (self.e.host_id,))
        con.commit()
        con.close()
        self.assertIsNone(self.reg.token_reset_password("host@mail.it"),
                          "emesso un magic-link per un host SOSPESO")

    def test_un_link_IN_MANO_smette_di_valere_se_l_host_viene_SOSPESO(self):
        """IL CASO CHE MANCAVA, e resta il piu' pericoloso di tutti.

        Provare che a un host sospeso non si EMETTE il link non basta: bisogna provare che
        un link gia' consegnato smetta di funzionare. Lo scenario e' esattamente quello di
        un host bloccato per frode che rientra con un link vecchio, si rimette la password
        e si riprende il pannello -- pagamenti compresi.

        Il controllo di produzione c'e' (`stato != "attivo"` nella riga del rifiuto), ma
        nessuno lo verificava: il mutante che lo indebolisce era sopravvissuto anche alle
        cinque guardie nuove qui sopra.
        """
        tok = self._link()                      # link consegnato mentre l'host e' attivo
        con = self.reg._apri()
        con.execute("UPDATE host SET stato='sospeso' WHERE host_id=?", (self.e.host_id,))
        con.commit()
        con.close()
        esito = self.reg.reset_password(tok, "nuovapasswordlunga")
        self.assertFalse(esito.ok,
                         "un host SOSPESO ha cambiato la password con un link ricevuto "
                         "prima del blocco: rientra nel pannello e nei pagamenti")
        self.assertEqual("link_non_valido", esito.errore)

    def test_un_link_di_un_host_CANCELLATO_non_vale(self):
        """L'altra faccia: se la riga dell'host non c'e' piu', il link non deve aprire
        nulla (ne' esplodere in faccia a chi lo usa)."""
        tok = self._link()
        con = self.reg._apri()
        con.execute("DELETE FROM host WHERE host_id=?", (self.e.host_id,))
        con.commit()
        con.close()
        esito = self.reg.reset_password(tok, "nuovapasswordlunga")
        self.assertFalse(esito.ok, "link di un host CANCELLATO accettato")
        self.assertEqual("link_non_valido", esito.errore)

    def test_a_una_email_INESISTENTE_non_si_emette_il_link(self):
        self.assertIsNone(self.reg.token_reset_password("mai-vista@mail.it"))
        self.assertIsNone(self.reg.token_reset_password("non-e-una-email"))


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
