"""
Test Fase 88 - Registro Host self-service.

Copre: registrazione (termini obbligatori, email/password validate, email unica), password
mai in chiaro + hash robusto, login (giusto/sbagliato/sospeso, niente leak utenti), token
firmato verificabile + scadenza + manomissione, sospensione invalida il token.
"""
import logging
import sqlite3
import unittest

from fase59_concierge import FirmaQuote
from fase88_registro_host import (TTL_TOKEN_DEFAULT, RegistroHost, _ConnCondivisa,
                                  _hash_password, crea_registro_host)

SEG = b"0123456789abcdef0123456789abcdef"
# Il token di prova sta in una costante: passato come stringa letterale a un argomento chiamato
# `*_token` conta per bandit come segreto cablato (B106).
CANALE_LINE = "LINE-1"


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


# ═══════════════════════════════════════════════════════════════════════════════════════
# I 52 PUNTI SOPRAVVISSUTI DELLA NOTTE FRA IL 6 E IL 7 SETTEMBRE 2026 (Giudice, Blocco 7)
# ═══════════════════════════════════════════════════════════════════════════════════════

LOGGER_REGISTRO = "core_auto.registro_host"


class _Orecchio(logging.Handler):
    """Raccoglie i record del registro: serve a pretendere il SILENZIO (nessun ERROR
    quando l'ingresso e' semplicemente non valido) oltre che il grido."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class _ConnEsplosiva:
    """Involucro della connessione VERA che si rompe sulla prima istruzione che contiene
    `parola` (sqlite3.OperationalError), oppure -- se `cursore` e' dato -- risponde con
    quel cursore finto invece di eseguirla. Tutto il resto passa alla connessione vera.
    E' il modo di costruire A MANO lo stato «archivio rotto a meta' operazione» (D19),
    cosi' i rami `except` del modulo vengono attraversati davvero, uno per uno."""

    def __init__(self, con, parola, cursore=None):
        object.__setattr__(self, "_con", con)
        object.__setattr__(self, "_parola", parola)
        object.__setattr__(self, "_cursore", cursore)

    def execute(self, sql, *a, **k):
        if self._parola in str(sql):
            if self._cursore is not None:
                return self._cursore
            raise sqlite3.OperationalError("archivio rotto dal test su: " + self._parola)
        return self._con.execute(sql, *a, **k)

    def close(self):
        pass

    def __enter__(self):
        return self._con.__enter__()

    def __exit__(self, *a):
        return self._con.__exit__(*a)

    def __getattr__(self, name):
        return getattr(self._con, name)

    def __setattr__(self, name, value):
        setattr(self._con, name, value)


class _CursoreSenzaConteggio:
    """Un cursore che non sa quante righe ha toccato (rowcount -1: e' cio' che sqlite3
    risponde per le istruzioni che non sono DML). Non capita su una DELETE vera: si
    costruisce a mano per attraversare il ramo difensivo di `cancella_host`."""
    rowcount = -1


class TestI52PuntiSopravvissutiDellaNotteDel7Settembre(unittest.TestCase):
    """Il Giudice della notte fra il 6 e il 7 settembre 2026 (giudice_notte_blocchi_4_7) ha
    trovato 52 punti di questo modulo in cui il guasto passa e i test restano verdi.
    Qui c'e' UNA guardia per punto, col numero di riga nel nome, ognuna vista ROSSA col
    mutante iniettato con l'editor e poi ripristino byte-identico.

    Le famiglie:
      · `EsitoHost(False, ...)` -> `True`: i rifiuti che i vecchi test guardavano solo dal
        MOTIVO (`.errore`) e mai dall'ESITO (`.ok`): un rifiuto raccontato come successo;
      · `exc_info=True` -> `False`: il ramo `except` grida ma senza la traccia, cioe' un
        guasto senza nome nel registro (regola ferrea 9); la guardia pretende la TUPLA
        del tipo giusto, non «non e' nullo»;
      · `isinstance(x, str) and x` -> `or`: un ingresso non valido che finisce lo stesso
        nell'archivio: qui si pretende che l'archivio NON venga nemmeno aperto;
      · `r["campo"] or ""` -> `and`: il pannello host restituisce campi VUOTI al posto dei
        dati veri;
      · i confini (`>=`/`<`) e gli `or` delle scadenze, provati sul secondo esatto.
    """

    def setUp(self):
        self.orologio = {"t": 1_000_000}
        self.reg = crea_registro_host(":memory:", SEG, orologio=lambda: self.orologio["t"])

    # ── attrezzi ────────────────────────────────────────────────────────────────────
    def _reale(self, reg):
        """La connessione VERA sotto l'involucro condiviso della modalita' :memory:."""
        return reg._conn_factory()._con

    def _rompi(self, reg, parola, cursore=None):
        reale = self._reale(reg)
        reg._conn_factory = lambda: _ConnEsplosiva(reale, parola, cursore)

    def _conta_aperture(self, reg):
        fabbrica = reg._conn_factory
        conto = {"n": 0}

        def contata():
            conto["n"] += 1
            return fabbrica()
        reg._conn_factory = contata
        return conto

    def _ascolta(self):
        orecchio = _Orecchio()
        logging.getLogger(LOGGER_REGISTRO).addHandler(orecchio)
        self.addCleanup(logging.getLogger(LOGGER_REGISTRO).removeHandler, orecchio)
        return orecchio

    def _nato(self, reg, host_id):
        con = reg._apri()
        try:
            r = con.execute("SELECT creato_ts FROM host WHERE host_id=?", (host_id,)).fetchone()
        finally:
            con.close()
        self.assertIsNotNone(r, "host %s non trovato" % host_id)
        return int(r[0])

    def _pw_hash(self, reg, host_id):
        con = reg._apri()
        try:
            r = con.execute("SELECT pw_hash FROM host WHERE host_id=?", (host_id,)).fetchone()
        finally:
            con.close()
        return r["pw_hash"]

    def _host(self, email="host@mail.it", **kw):
        e = self.reg.registra(email, "passwordlunga", accetta_termini=True, **kw)
        self.assertTrue(e.ok, e.errore)
        return e

    def _pretendi_traccia(self, cm, livello):
        """Il ramo except ha lasciato nel registro LA traccia (tupla exc_info) del tipo
        giusto, al livello dichiarato: non «qualcosa di non nullo»."""
        self.assertEqual(1, len(cm.records), [r.getMessage() for r in cm.records])
        rec = cm.records[0]
        self.assertEqual(livello, rec.levelno, "livello sbagliato: %s" % rec.levelname)
        self.assertIsInstance(rec.exc_info, tuple,
                              "il registro NON porta la traccia dell'eccezione: guasto senza nome")
        self.assertTrue(issubclass(rec.exc_info[0], sqlite3.OperationalError),
                        "la traccia non e' quella del guasto costruito: %r" % (rec.exc_info[0],))

    # ── riga 87: la durata del gettone ─────────────────────────────────────────────
    def test_riga87_un_ttl_di_ZERO_ripiega_sul_valore_di_serie_e_il_gettone_vale_ANCHE_dopo(self):
        """Con `>=` un ttl di 0 viene accettato: il gettone nasce con scadenza uguale
        all'istante e vale ancora in quel secondo (per questo il vecchio test non lo
        vedeva), ma UN secondo dopo ogni host e' fuori dal proprio pannello."""
        reg = crea_registro_host(":memory:", SEG, orologio=lambda: self.orologio["t"], ttl_token=0)
        self.assertEqual(TTL_TOKEN_DEFAULT, reg._ttl, "ttl_token=0 e' stato accettato")
        e = reg.registra("a@b.it", "passwordlunga", accetta_termini=True)
        self.orologio["t"] += 1
        self.assertEqual(e.host_id, reg.verifica_token(e.token),
                         "un secondo dopo la registrazione il gettone non vale piu'")

    # ── righe 171 · 228 · 441 · 533 · 588 · 605 · 622 · 638: ingresso non valido ──
    def _non_apre_l_archivio(self, nome, chiamata, atteso):
        conto = self._conta_aperture(self.reg)
        for cattivo in ("", 123):
            self.assertEqual(atteso, chiamata(cattivo),
                             "%s(%r) non ha risposto col rifiuto" % (nome, cattivo))
        self.assertEqual(0, conto["n"], "%s ha APERTO l'archivio per un host_id non valido"
                         % nome)

    def test_riga171_deposita_impronte_con_host_id_non_valido_non_apre_l_archivio(self):
        self._non_apre_l_archivio("deposita_impronte", self.reg.deposita_impronte, 0)

    def test_riga228_riconosci_ritorno_con_host_id_non_valido_non_apre_l_archivio(self):
        self._non_apre_l_archivio("riconosci_ritorno",
                                  lambda h: self.reg.riconosci_ritorno(h, ("CIN1",)), None)

    def test_riga441_info_host_con_host_id_non_valido_non_apre_l_archivio(self):
        self._non_apre_l_archivio("info_host", self.reg.info_host, None)

    def test_riga533_imposta_verifica_con_host_id_non_valido_non_apre_l_archivio(self):
        self._non_apre_l_archivio("imposta_verifica",
                                  lambda h: self.reg.imposta_verifica(h, "verificato"), False)

    def test_riga588_imposta_stripe_account_con_host_id_non_valido_non_apre_l_archivio(self):
        self._non_apre_l_archivio("imposta_stripe_account",
                                  lambda h: self.reg.imposta_stripe_account(h, "acct_1"), False)

    def test_riga605_imposta_carta_con_host_id_non_valido_non_apre_l_archivio(self):
        self._non_apre_l_archivio("imposta_carta",
                                  lambda h: self.reg.imposta_carta(h, "cus_1", "pm_1"), False)

    def test_riga622_imposta_telegram_chat_con_host_id_non_valido_non_apre_l_archivio(self):
        self._non_apre_l_archivio("imposta_telegram_chat",
                                  lambda h: self.reg.imposta_telegram_chat(h, "42"), False)

    def test_riga638_cancella_host_con_host_id_non_valido_non_apre_l_archivio(self):
        self._non_apre_l_archivio("cancella_host", self.reg.cancella_host, 0)

    # ── riga 189: il deposito delle impronte grida CON la traccia ──────────────────
    def test_riga189_deposito_impronte_su_archivio_rotto_grida_ERROR_con_la_traccia(self):
        e = self._host()
        self._rompi(self.reg, "SELECT * FROM host")
        with self.assertLogs(LOGGER_REGISTRO, level="ERROR") as cm:
            self.assertEqual(0, self.reg.deposita_impronte(e.host_id))
        self._pretendi_traccia(cm, logging.ERROR)

    # ── riga 200: un valore VUOTO o non testuale non e' un'identita' ───────────────
    def test_riga200_un_telefono_VUOTO_non_riconosce_nessun_ritorno(self):
        """Stato costruito a mano: un'impronta della stringa vuota in cassaforte con una
        data vecchia. Il modulo deve saltare i valori vuoti PRIMA di cercarli: se li
        cercasse, ogni host senza telefono erediterebbe quella data e perderebbe i suoi
        90 giorni di promozione."""
        vecchia = self.orologio["t"] - 200 * 86400
        con = self.reg._apri()
        try:
            with con:
                con.execute("INSERT INTO host_impronte (impronta, creato_ts, ts) VALUES (?,?,?)",
                            (self.reg._firma.impronta(""), vecchia, vecchia))
        finally:
            con.close()
        e = self._host("nuovo@mail.it", telefono="")
        self.assertEqual(self.orologio["t"], self._nato(self.reg, e.host_id),
                         "un host NUOVO senza telefono ha ereditato l'anzianita' di un altro")

    def test_riga200_un_valore_NON_testuale_fra_gli_identificativi_non_fa_gridare_nessuno(self):
        e = self._host()
        orecchio = self._ascolta()
        self.assertIsNone(self.reg.riconosci_ritorno(e.host_id, (None, 42, "")))
        self.assertEqual([], [r.getMessage() for r in orecchio.records],
                         "un identificativo non testuale e' arrivato fino all'archivio")

    # ── riga 233: la struttura GIA' VISTA riporta l'anzianita' indietro ────────────
    def test_riga233_il_CIN_gia_visto_riporta_l_anzianita_alla_PRIMA_iscrizione(self):
        prima = self.orologio["t"]
        vecchio = self._host("vecchio@mail.it", telefono="+39 333 1111111")
        self.assertGreater(self.reg.deposita_impronte(vecchio.host_id, extra=("CIN-RM-0001",)), 0)
        self.reg.cancella_host(vecchio.host_id)
        self.orologio["t"] += 100 * 86400
        nuovo = self._host("nuovo@mail.it", telefono="+39 333 2222222")
        self.assertEqual(self.orologio["t"], self._nato(self.reg, nuovo.host_id))
        self.assertEqual(prima, self.reg.riconosci_ritorno(nuovo.host_id, ("CIN-RM-0001",)),
                         "la struttura gia' vista NON e' stata riconosciuta: 90 giorni riciclati")
        self.assertEqual(prima, self._nato(self.reg, nuovo.host_id))

    def test_riga233_una_struttura_MAI_vista_non_tocca_niente_e_non_grida(self):
        e = self._host()
        orecchio = self._ascolta()
        self.assertIsNone(self.reg.riconosci_ritorno(e.host_id, ("CIN-MAI-VISTO",)))
        self.assertEqual(self.orologio["t"], self._nato(self.reg, e.host_id))
        self.assertEqual([], [r.getMessage() for r in orecchio.records])

    # ── riga 244: la rilettura delle impronte grida ERROR con la traccia ───────────
    def test_riga244_riconosci_ritorno_su_archivio_rotto_grida_ERROR_con_la_traccia(self):
        e = self._host()
        self._rompi(self.reg, "host_impronte")
        with self.assertLogs(LOGGER_REGISTRO, level="ERROR") as cm:
            self.assertIsNone(self.reg.riconosci_ritorno(e.host_id, ("CIN-RM-0001",)))
        self._pretendi_traccia(cm, logging.ERROR)

    # ── riga 284: la scadenza del magic-link, sul secondo esatto e sui tipi storti ──
    def _link_forgiato(self, host_id, exp):
        return self.reg._firma.codifica({"tipo": "host_pw_reset", "host_id": host_id,
                                         "fp": self._pw_hash(self.reg, host_id)[:16],
                                         "exp": exp})

    def test_riga284_un_link_con_scadenza_NON_numerica_e_scaduto_non_un_errore_interno(self):
        e = self._host()
        esito = self.reg.reset_password(self._link_forgiato(e.host_id, "abc"), "nuovapassword1")
        self.assertIs(False, esito.ok)
        self.assertEqual("link_scaduto", esito.errore)

    def test_riga284_un_link_con_scadenza_BOOLEANA_e_scaduto_anche_a_orologio_zero(self):
        """`True` e' un int per Python: l'unico modo di respingerlo e' il controllo sul
        bool, e a orologio 0 (`True < 0` falso) e' quel controllo da solo a tenere."""
        e = self._host()
        self.orologio["t"] = 0
        esito = self.reg.reset_password(self._link_forgiato(e.host_id, True), "nuovapassword1")
        self.assertIs(False, esito.ok, "un link con scadenza booleana ha cambiato la password")
        self.assertEqual("link_scaduto", esito.errore)

    def test_riga284_il_link_vale_ancora_nel_SECONDO_ESATTO_della_scadenza(self):
        e = self._host()
        esito = self.reg.reset_password(self._link_forgiato(e.host_id, self.orologio["t"]),
                                        "nuovapassword1")
        self.assertIs(True, esito.ok, "link rifiutato nel secondo esatto della scadenza: %s"
                      % esito.errore)

    # ── righe 309 · 310: il ripristino su archivio rotto ───────────────────────────
    def test_riga309_310_reset_password_su_archivio_rotto_e_un_RIFIUTO_e_grida_con_la_traccia(self):
        self._host()
        link = self.reg.token_reset_password("host@mail.it")
        self._rompi(self.reg, "BEGIN IMMEDIATE")
        with self.assertLogs(LOGGER_REGISTRO, level="WARNING") as cm:
            esito = self.reg.reset_password(link, "nuovapassword1")
        self.assertIs(False, esito.ok, "un ripristino FALLITO e' raccontato come riuscito")
        self.assertEqual("errore_interno", esito.errore)
        self.assertEqual("", esito.token, "un ripristino fallito porta con se' un gettone")
        self._pretendi_traccia(cm, logging.WARNING)

    # ── righe 317-345: cambia_password ─────────────────────────────────────────────
    def test_riga318_cambia_password_con_ingressi_non_validi_e_un_RIFIUTO(self):
        e = self._host()
        for hid, vecchia in (("", "passwordlunga"), (123, "passwordlunga"), (e.host_id, None),
                             (None, "passwordlunga")):
            esito = self.reg.cambia_password(hid, vecchia, "nuovapassword1")
            self.assertIs(False, esito.ok, "cambio password accettato con %r/%r" % (hid, vecchia))
            self.assertEqual("credenziali_non_valide", esito.errore)
        self.assertTrue(self.reg.login("host@mail.it", "passwordlunga").ok)

    def test_riga319_320_la_nuova_password_di_8_caratteri_passa_e_quella_di_7_e_un_RIFIUTO(self):
        e = self._host()
        esito = self.reg.cambia_password(e.host_id, "passwordlunga", "sette77")
        self.assertIs(False, esito.ok, "password di 7 caratteri accettata")
        self.assertEqual("password_troppo_corta", esito.errore)
        esito = self.reg.cambia_password(e.host_id, "passwordlunga", "otto8888")
        self.assertIs(True, esito.ok, "password di 8 caratteri ESATTI rifiutata: %s" % esito.errore)
        self.assertTrue(self.reg.login("host@mail.it", "otto8888").ok)

    def test_riga328_cambia_password_di_un_host_INESISTENTE_o_SOSPESO_e_un_RIFIUTO(self):
        e = self._host()
        esito = self.reg.cambia_password("h_inesistente", "passwordlunga", "nuovapassword1")
        self.assertIs(False, esito.ok, "cambio password su host inesistente RIUSCITO")
        self.assertEqual("credenziali_non_valide", esito.errore)
        self.assertTrue(self.reg.imposta_stato(e.host_id, "sospeso"))
        esito = self.reg.cambia_password(e.host_id, "passwordlunga", "nuovapassword1")
        self.assertIs(False, esito.ok, "un host SOSPESO ha cambiato la password")
        self.assertEqual("credenziali_non_valide", esito.errore)

    def test_riga332_la_vecchia_password_SBAGLIATA_e_un_RIFIUTO_e_non_cambia_nulla(self):
        e = self._host()
        esito = self.reg.cambia_password(e.host_id, "sbagliata", "nuovapassword1")
        self.assertIs(False, esito.ok, "password cambiata senza conoscere quella vecchia")
        self.assertEqual("credenziali_non_valide", esito.errore)
        self.assertTrue(self.reg.login("host@mail.it", "passwordlunga").ok)
        self.assertFalse(self.reg.login("host@mail.it", "nuovapassword1").ok)

    def test_riga344_345_cambia_password_su_archivio_rotto_e_un_RIFIUTO_e_grida_con_la_traccia(self):
        e = self._host()
        self._rompi(self.reg, "BEGIN IMMEDIATE")
        with self.assertLogs(LOGGER_REGISTRO, level="WARNING") as cm:
            esito = self.reg.cambia_password(e.host_id, "passwordlunga", "nuovapassword1")
        self.assertIs(False, esito.ok, "un cambio password FALLITO e' raccontato come riuscito")
        self.assertEqual("errore_interno", esito.errore)
        self.assertEqual("", esito.token)
        self._pretendi_traccia(cm, logging.WARNING)

    # ── righe 349-390: registra ────────────────────────────────────────────────────
    def test_riga349_senza_dire_nulla_sui_termini_la_registrazione_e_un_RIFIUTO(self):
        """Il valore di serie del consenso e' NO: chi non lo dichiara non si iscrive."""
        esito = self.reg.registra("a@b.it", "passwordlunga")
        self.assertIs(False, esito.ok, "registrato SENZA accettare i termini")
        self.assertEqual("termini_non_accettati", esito.errore)
        self.assertFalse(self.reg.login("a@b.it", "passwordlunga").ok)

    def test_riga357_una_email_non_valida_e_un_RIFIUTO(self):
        esito = self.reg.registra("non-email", "passwordlunga", accetta_termini=True)
        self.assertIs(False, esito.ok, "registrazione RIUSCITA con una email non valida")
        self.assertEqual("email_non_valida", esito.errore)
        self.assertEqual("", esito.token)

    def test_riga358_la_password_di_8_caratteri_passa_e_quella_di_7_e_un_RIFIUTO(self):
        esito = self.reg.registra("a@b.it", "sette77", accetta_termini=True)
        self.assertIs(False, esito.ok, "password di 7 caratteri accettata alla registrazione")
        self.assertEqual("password_troppo_corta", esito.errore)
        esito = self.reg.registra("a@b.it", "otto8888", accetta_termini=True)
        self.assertIs(True, esito.ok, "password di 8 caratteri ESATTI rifiutata: %s" % esito.errore)

    def test_riga380_381_i_contatti_dati_alla_registrazione_vengono_SALVATI(self):
        e = self._host(telefono=" +39 333 7777777 ", line_token=CANALE_LINE,
                       wechat_webhook="https://wx.example/hook")
        info = self.reg.info_host(e.host_id)
        self.assertEqual("+39 333 7777777", info["telefono"], "telefono perso alla registrazione")
        self.assertEqual("LINE-1", info["line_token"], "line_token perso alla registrazione")
        self.assertEqual("https://wx.example/hook", info["wechat_webhook"],
                         "wechat_webhook perso alla registrazione")

    def test_riga380_381_i_contatti_ASSENTI_restano_VUOTI_non_la_parola_None(self):
        e = self._host(telefono=None, line_token=None, wechat_webhook=None)
        info = self.reg.info_host(e.host_id)
        for campo in ("telefono", "line_token", "wechat_webhook"):
            self.assertEqual("", info[campo], "%s assente salvato come %r" % (campo, info[campo]))

    def test_riga390_registra_su_archivio_rotto_e_un_RIFIUTO_e_grida_con_la_traccia(self):
        self._rompi(self.reg, "BEGIN IMMEDIATE")
        with self.assertLogs(LOGGER_REGISTRO, level="WARNING") as cm:
            esito = self.reg.registra("a@b.it", "passwordlunga", accetta_termini=True)
        self.assertIs(False, esito.ok)
        self.assertEqual("errore_interno", esito.errore)
        self._pretendi_traccia(cm, logging.WARNING)

    # ── righe 398 · 407: login ─────────────────────────────────────────────────────
    def test_riga398_login_con_email_non_valida_o_password_non_testuale_e_un_RIFIUTO(self):
        self._host()
        for email, pw in (("non-email", "passwordlunga"), ("host@mail.it", None),
                          ("host@mail.it", 12345678), (None, "passwordlunga")):
            esito = self.reg.login(email, pw)
            self.assertIs(False, esito.ok, "login RIUSCITO con %r/%r" % (email, pw))
            self.assertEqual("credenziali_non_valide", esito.errore)
            self.assertEqual("", esito.token)

    def test_riga407_login_di_una_email_MAI_registrata_e_un_RIFIUTO(self):
        self._host()
        esito = self.reg.login("nessuno@mail.it", "passwordlunga")
        self.assertIs(False, esito.ok, "login RIUSCITO per una email mai registrata")
        self.assertEqual("credenziali_non_valide", esito.errore)
        self.assertEqual("", esito.token)
        self.assertEqual("", esito.host_id)

    # ── riga 424: la scadenza del gettone d'accesso ────────────────────────────────
    def _gettone_forgiato(self, host_id, exp):
        return self.reg._firma.codifica({"tipo": "host_token", "host_id": host_id,
                                         "email": "host@mail.it", "exp": exp})

    def test_riga424_un_gettone_con_scadenza_NON_numerica_non_vale_e_non_esplode(self):
        e = self._host()
        self.assertIsNone(self.reg.verifica_token(self._gettone_forgiato(e.host_id, "abc")))
        self.assertIsNone(self.reg.verifica_token(self._gettone_forgiato(e.host_id, None)))

    def test_riga424_un_gettone_con_scadenza_BOOLEANA_non_vale_anche_a_orologio_zero(self):
        e = self._host()
        self.orologio["t"] = 0
        self.assertIsNone(self.reg.verifica_token(self._gettone_forgiato(e.host_id, True)),
                          "un gettone con scadenza booleana apre il pannello")

    def test_riga424_il_gettone_vale_ancora_nel_SECONDO_ESATTO_della_scadenza(self):
        e = self._host()
        self.assertEqual(e.host_id, self.reg.verifica_token(
            self._gettone_forgiato(e.host_id, self.orologio["t"])),
            "gettone rifiutato nel secondo esatto della scadenza")

    # ── righe 457-460 · 518 · 519 · 581: il pannello dice i dati VERI ──────────────
    def test_riga458_459_460_info_host_riporta_i_contatti_VERI_non_campi_vuoti(self):
        e = self._host("Host@Mail.it", telefono="+39 333 7777777", line_token=CANALE_LINE,
                       wechat_webhook="https://wx.example/hook", ragione_sociale="B&B Sole")
        self.assertTrue(self.reg.imposta_telegram_chat(e.host_id, "4242"))
        self.assertTrue(self.reg.imposta_stripe_account(e.host_id, "acct_1"))
        info = self.reg.info_host(e.host_id)
        atteso = {"email": "host@mail.it", "telefono": "+39 333 7777777", "line_token": "LINE-1",
                  "wechat_webhook": "https://wx.example/hook", "telegram_chat_id": "4242",
                  "stripe_account_id": "acct_1", "ragione_sociale": "B&B Sole"}
        for k, v in atteso.items():
            self.assertEqual(v, info[k], "info_host riporta %s=%r invece di %r" % (k, info[k], v))

    def _registro_su_archivio_VECCHIO(self):
        """Un archivio nato PRIMA delle migrazioni, con le colonne che ammettono NULL: e'
        l'unico modo di far arrivare un NULL alle letture del pannello (lo schema di oggi
        le dichiara NOT NULL DEFAULT ''). Stato costruito a mano (D19)."""
        con = sqlite3.connect(":memory:", check_same_thread=False)
        con.execute("""CREATE TABLE host (host_id TEXT PRIMARY KEY, email TEXT, salt TEXT,
            pw_hash TEXT, ragione_sociale TEXT, telefono TEXT, line_token TEXT,
            wechat_webhook TEXT, telegram_chat_id TEXT, stripe_account_id TEXT,
            termini_versione TEXT, termini_ts INTEGER, stato TEXT, creato_ts INTEGER,
            codice_fiscale TEXT, partita_iva TEXT, indirizzo_fiscale TEXT, paese TEXT,
            iban TEXT, tipo_soggetto TEXT, data_nascita TEXT, verifica_stato TEXT,
            verifica_note TEXT, verifica_ts TEXT, verifica_da TEXT, stripe_customer_id TEXT,
            stripe_payment_method TEXT)""")
        return RegistroHost(lambda: _ConnCondivisa(con), FirmaQuote(SEG),
                            orologio=lambda: self.orologio["t"])

    def test_riga457_info_host_su_archivio_VECCHIO_con_NULL_risponde_stringhe_vuote(self):
        reg = self._registro_su_archivio_VECCHIO()
        e = reg.registra("host@mail.it", "passwordlunga", accetta_termini=True)
        self.assertTrue(e.ok, e.errore)
        info = reg.info_host(e.host_id)
        for k, v in info.items():
            self.assertIsInstance(v, str, "info_host[%s] = %r: un NULL e' uscito dal pannello"
                                  % (k, v))
        self.assertEqual("", info["codice_fiscale"])

    def test_riga518_elenco_host_su_archivio_VECCHIO_con_NULL_risponde_stringhe_vuote(self):
        reg = self._registro_su_archivio_VECCHIO()
        self.assertTrue(reg.registra("host@mail.it", "passwordlunga", accetta_termini=True).ok)
        righe = reg.elenco_host()
        self.assertEqual(1, len(righe))
        for k, v in righe[0].items():
            self.assertIsInstance(v, str, "elenco_host[%s] = %r: un NULL e' uscito dall'audit"
                                  % (k, v))
        self.assertEqual("", righe[0]["iban"])

    def test_riga519_elenco_host_riporta_le_email_VERE(self):
        self._host("uno@mail.it")
        self._host("due@mail.it")
        self.assertEqual(["uno@mail.it", "due@mail.it"],
                         [r["email"] for r in self.reg.elenco_host()],
                         "l'audit DAC7 riporta email vuote o in ordine sbagliato")

    def test_riga581_cerca_host_riporta_le_email_VERE(self):
        e = self._host("cercami@mail.it", ragione_sociale="Villa Cerca")
        trovati = self.reg.cerca_host("cercami")
        self.assertEqual(1, trovati["totale"])
        self.assertEqual({"host_id": e.host_id, "email": "cercami@mail.it",
                          "ragione_sociale": "Villa Cerca", "stato": "attivo"}, trovati["host"][0])

    # ── righe 498 · 548 · 577 · 597 · 615 · 631: i rami ISOLATI gridano con la traccia ─
    def _grida_warning_e_risponde(self, parola, chiamata, atteso):
        self._rompi(self.reg, parola)
        with self.assertLogs(LOGGER_REGISTRO, level="WARNING") as cm:
            self.assertEqual(atteso, chiamata())
        self._pretendi_traccia(cm, logging.WARNING)

    def test_riga498_imposta_dati_fiscali_su_archivio_rotto_risponde_False_e_grida_con_la_traccia(self):
        e = self._host()
        self._grida_warning_e_risponde(
            "UPDATE host SET", lambda: self.reg.imposta_dati_fiscali(e.host_id, {"iban": "IT00"}),
            False)

    def test_riga548_imposta_verifica_su_archivio_rotto_risponde_False_e_grida_con_la_traccia(self):
        e = self._host()
        self._grida_warning_e_risponde(
            "verifica_stato=?", lambda: self.reg.imposta_verifica(e.host_id, "verificato"), False)

    def test_riga577_cerca_host_su_archivio_rotto_risponde_VUOTO_e_grida_con_la_traccia(self):
        self._host()
        self._grida_warning_e_risponde(
            "SELECT COUNT(*)", lambda: self.reg.cerca_host("host"), {"host": [], "totale": 0})

    def test_riga597_imposta_stripe_account_su_archivio_rotto_risponde_False_e_grida_con_la_traccia(self):
        e = self._host()
        self._grida_warning_e_risponde(
            "stripe_account_id=?", lambda: self.reg.imposta_stripe_account(e.host_id, "acct_1"),
            False)

    def test_riga615_imposta_carta_su_archivio_rotto_risponde_False_e_grida_con_la_traccia(self):
        e = self._host()
        self._grida_warning_e_risponde(
            "stripe_customer_id=?", lambda: self.reg.imposta_carta(e.host_id, "cus_1", "pm_1"),
            False)

    def test_riga631_imposta_telegram_chat_su_archivio_rotto_risponde_False_e_grida_con_la_traccia(self):
        e = self._host()
        self._grida_warning_e_risponde(
            "telegram_chat_id=?", lambda: self.reg.imposta_telegram_chat(e.host_id, "42"), False)

    # ── righe 506 · 559 · 561 · 562: i limiti ASSURDI ripiegano sul valore di serie ──
    def test_riga506_elenco_host_con_limite_ASSURDO_ripiega_e_riporta_tutti(self):
        for i in range(3):
            self._host("h%d@mail.it" % i)
        self.assertEqual(3, len(self.reg.elenco_host(limit=0)),
                         "un limite di 0 ha svuotato l'audit invece di ripiegare")
        self.assertEqual(3, len(self.reg.elenco_host(limit="5")))
        self.assertEqual(3, len(self.reg.elenco_host(limit=-1)))

    def test_riga559_un_termine_di_DUE_caratteri_cerca_e_uno_di_UNO_no(self):
        self._host("ab@mail.it")
        self.assertEqual(1, self.reg.cerca_host("ab")["totale"], "termine di 2 caratteri ignorato")
        self.assertEqual({"host": [], "totale": 0}, self.reg.cerca_host("a"))
        self.assertEqual({"host": [], "totale": 0}, self.reg.cerca_host(" a "))

    def test_riga561_cerca_host_con_limite_ASSURDO_ripiega_e_trova(self):
        self._host("cercami@mail.it")
        self.assertEqual(1, len(self.reg.cerca_host("cercami", limit=0)["host"]),
                         "un limite di 0 ha nascosto il risultato invece di ripiegare")
        self.assertEqual(1, len(self.reg.cerca_host("cercami", limit="3")["host"]))

    def test_riga562_cerca_host_con_scostamento_ASSURDO_ripiega_e_trova(self):
        self._host("cercami@mail.it")
        self.assertEqual(1, len(self.reg.cerca_host("cercami", offset=10 ** 7)["host"]),
                         "uno scostamento oltre il tetto ha nascosto il risultato")
        self.assertEqual(1, len(self.reg.cerca_host("cercami", offset="1")["host"]))

    # ── riga 644: mai un numero NEGATIVO di host cancellati ────────────────────────
    def test_riga644_cancella_host_con_un_cursore_che_non_conta_risponde_ZERO_mai_negativo(self):
        e = self._host()
        self._rompi(self.reg, "DELETE FROM host", cursore=_CursoreSenzaConteggio())
        self.assertEqual(0, self.reg.cancella_host(e.host_id),
                         "cancella_host ha risposto un conteggio negativo")


if __name__ == "__main__":
    unittest.main()
