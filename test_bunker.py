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

    def test_scaduta_la_RISPOSTA_e_NO_non_solo_il_motivo(self):
        """IL BUCO TROVATO DALLA MUTAZIONE il 2026-07-31, ed e' da manuale.

        La prova qui sopra controlla SOLO il `motivo` della sessione scaduta, mai che la
        risposta sia «no». Quindi rovesciando `"ok": False` in `"ok": True` su quella riga
        il motivo resta identico e il test passa lo stesso: **una sessione amministratore
        SCADUTA verrebbe accettata**, con la suite tutta verde.

        Due righe piu' sotto, `test_logout_server_side_revoca` fa la cosa giusta e asserisce
        ENTRAMBI. Stessa classe, due misure diverse: e' l'asimmetria che solo un guasto
        simulato riesce a vedere.

        Questo cancello e' la porta dell'amministratore -- quella dietro cui si firmano
        rimborsi e si muovono payout. Qui si asserisce l'ESITO, non il commento all'esito.
        """
        tok = self.b.crea_sessione("203.0.113.5")
        self.clock["t"] += bk.DURATA_SESSIONE_SEC + 1
        r = self.b.valida_sessione(tok, "203.0.113.5")
        self.assertIs(False, r["ok"],
                      "sessione SCADUTA accettata: la porta dell'amministratore resta "
                      "aperta oltre la scadenza. Risposta: %r" % (r,))
        self.assertEqual("sessione_scaduta", r["motivo"])

    def test_il_CONFINE_della_scadenza_e_chiuso(self):
        """Al secondo ESATTO della scadenza la sessione e' gia' morta (`<=`, non `<`).
        Un mutante che stringe il confine e' sopravvissuto: nessuno provava quel punto."""
        tok = self.b.crea_sessione("203.0.113.5")
        self.clock["t"] += bk.DURATA_SESSIONE_SEC          # esattamente l'istante di scadenza
        r = self.b.valida_sessione(tok, "203.0.113.5")
        self.assertIs(False, r["ok"],
                      "al secondo esatto della scadenza la sessione e' ancora valida: "
                      "una finestra in piu' su una porta d'amministrazione. Risposta: %r" % (r,))
        self.assertEqual("sessione_scaduta", r["motivo"])

    def test_bunker_NON_CONFIGURATO_non_apre(self):
        """Senza chiave di firma il cancello non puo' verificare NIENTE: deve dire no.
        Il mutante che gli fa dire «ok» e' sopravvissuto -- un fail-OPEN sulla porta
        dell'amministratore, che e' il guasto peggiore possibile su una porta."""
        spento = bk.crea_bunker(None, password="X", orologio=lambda: self.clock["t"])
        tok = self.b.crea_sessione("203.0.113.5")
        r = spento.valida_sessione(tok, "203.0.113.5")
        self.assertIs(False, r["ok"],
                      "un bunker senza chiave di firma ha APERTO: fail-open sulla porta "
                      "dell'amministratore. Risposta: %r" % (r,))
        self.assertEqual("bunker_non_configurato", r["motivo"])

    def test_il_secondo_fattore_NON_si_apre_su_un_ERRORE(self):
        """Se il calcolo del codice esplode, il secondo fattore deve dire NO.

        Il mutante che trasforma quel `return False` in `return True` e' sopravvissuto:
        un guasto qualunque (segreto malformato, libreria assente) avrebbe aperto la porta
        a QUALSIASI codice. E' il fail-open classico, sul fattore che dovrebbe essere il
        piu' forte.
        """
        vero = bk._codice_at

        def _esplode(*a, **k):
            raise RuntimeError("calcolo del codice guasto")

        bk._codice_at = _esplode
        try:
            self.assertFalse(bk.verifica_totp(SEG_RFC, "287082", ora=59),
                             "con il calcolo del codice guasto il secondo fattore ha "
                             "ACCETTATO: qualunque codice aprirebbe")
            self.assertEqual("", self.b.verifica_secondo_fattore("287082"),
                             "il bunker riconosce un secondo fattore che non ha potuto "
                             "verificare")
        finally:
            bk._codice_at = vero
        # e a guasto rientrato il cancello torna a funzionare (niente danno permanente)
        self.clock["t"] = 59
        self.assertEqual("totp", self.b.verifica_secondo_fattore("287082"))

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

    def test_logout_FALLITO_non_puo_dichiarare_ok(self):
        """IL LOGOUT DEL BUNKER NON PUO' MENTIRE.

        La descrizione di `_bunker_logout` promette: «quel token e' morto SUBITO, non solo
        cancellato dal browser». Se `bunker.revoca()` esplode, la promessa e' FALSA -- il
        token resta VIVO -- e la risposta diceva comunque `{"ok": True}` con un semplice
        `logger.warning`.

        Conta in uno scenario preciso, ed e' quello che conta davvero: si fa logout PROPRIO
        perche' si sospetta che il token sia stato rubato. E' l'unico momento in cui la
        revoca serve, ed e' l'unico in cui il suo fallimento fa danno. Ed e' il pannello dei
        soldi, dietro doppia chiave.

        Stessa famiglia del rimborso admin che rispondeva "fatto" sui passi falliti: uno
        strumento che dichiara un successo che non c'e' stato.

        VISTO ROSSO: prima rispondeva ok=True senza una parola, e nemmeno un ERROR.
        """
        s, out = self._login(self._codice_ora())
        sess = out["sessione"]

        class _RevocaRotta:
            def __init__(self, vero): self._v = vero
            def __getattr__(self, n): return getattr(self._v, n)
            def revoca(self, tok): raise RuntimeError("denylist non scrivibile")
        self.sis.bunker = _RevocaRotta(self.sis.bunker)

        with self.assertLogs("core_auto", level="ERROR") as reg:
            s, body = self.r.gestisci("POST", "/api/bunker/logout", {}, None,
                                      {"X-Bunker-Session": sess, "X-Forwarded-For": "203.0.113.1"})
        self.assertEqual(s, 200, "il cookie va tolto comunque: %r" % (body,))
        self.assertIs(body.get("revocata"), False,
                      "la risposta dichiara un logout che NON e' avvenuto: %r" % (body,))
        self.assertTrue(any("revoc" in x.lower() for x in reg.output),
                        "il fallimento della revoca non e' udibile: %r" % (reg.output,))

    def test_logout_RIUSCITO_lo_dichiara_e_non_grida(self):
        """Prova di rimozione: sul percorso sano `revocata` e' True e nessun ERROR."""
        import logging
        catturati = []

        class _Spia(logging.Handler):
            def emit(self, record):
                if record.levelno >= logging.ERROR:
                    catturati.append(record.getMessage())
        lg = logging.getLogger("core_auto")
        h = _Spia(); lg.addHandler(h); self.addCleanup(lambda: lg.removeHandler(h))
        s, out = self._login(self._codice_ora())
        s, body = self.r.gestisci("POST", "/api/bunker/logout", {}, None,
                                  {"X-Bunker-Session": out["sessione"],
                                   "X-Forwarded-For": "203.0.113.1"})
        self.assertEqual(s, 200)
        self.assertIs(body.get("revocata"), True, "logout riuscito non dichiarato: %r" % (body,))
        self.assertEqual(catturati, [], "grida su un logout riuscito: %r" % (catturati,))

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


class TestBunkerSeiBuchiTrovatiDallaMutazione(unittest.TestCase):
    """⛔ SEI BUCHI VERI NEL CANCELLO DELL'AMMINISTRAZIONE (mutazione, 2026-08-02).

    Campagna su TUTTI e 41 i punti di `fase180_bunker`: 35 uccisi, 6 sopravvissuti. Il
    modulo ha UN SOLO file di prove -- questo -- e la campagna l'ha usato tutto: non c'e'
    nessuna scorciatoia che possa aver creato falsi allarmi. Sono sei buchi reali.

    E' il posto da cui si fanno rimborsi, cancellazioni e si tocca l'integrita' del sistema:
    la porta piu' importante della macchina, con addosso meno prove di quante ne abbia una
    pagina di marketing.
    """

    def setUp(self):
        self.firma = FirmaQuote(b"S" * 32)
        self.clock = {"t": 1000.0}
        self.b = bk.crea_bunker(self.firma, totp_secret=SEG_RFC,
                                password="PasswordSuperAdmin@1",
                                break_glass="ROMPI-IL-VETRO-9",
                                orologio=lambda: self.clock["t"])

    def test_un_codice_di_sei_lettere_ACCENTATE_non_fa_esplodere_la_porta(self):
        """⛔ `if len(c) != _CIFRE or not c.isdigit(): return False` con un `and`.

        Il primo controllo esiste per fermare SUBITO cio' che non e' un codice. Con `and` un
        testo di sei caratteri non-numerici passa oltre e arriva a `hmac.compare_digest`,
        che su stringhe NON-ASCII **solleva TypeError** (documentato: «comparing strings with
        non-ASCII characters is not supported»).

        Risultato: chiunque puo' far ESPLODERE la pagina di accesso al bunker mandando
        `abcdéf`. Non e' un bypass -- e' un'eccezione non gestita su un ingresso di
        autenticazione, cioe' la porta dell'amministrazione che smette di aprirsi.
        """
        self.clock["t"] = 59
        for storto in ("abcdéf", "123 45", "abcdef", "12345", "1234567", "", "  1234  ",
                       "±23456", "12345 "):
            try:
                esito = bk.verifica_totp(SEG_RFC, storto, ora=59)
            except Exception as e:
                self.fail("il codice %r ha fatto ESPLODERE la verifica: %s: %s"
                          % (storto, type(e).__name__, e))
            self.assertFalse(esito, "codice non valido accettato: %r" % (storto,))
        # ...e attraverso l'ingresso vero, quello che usa la pagina
        for storto in ("abcdéf", "±23456"):
            try:
                self.assertEqual("", self.b.verifica_secondo_fattore(storto))
            except Exception as e:
                self.fail("il secondo fattore esplode su %r: %s: %s"
                          % (storto, type(e).__name__, e))
        # e il verso opposto: il codice GIUSTO continua a passare
        self.assertTrue(bk.verifica_totp(SEG_RFC, "287082", ora=59))
        self.assertEqual("totp", self.b.verifica_secondo_fattore("287082"))
        self.assertEqual("password", self.b.verifica_secondo_fattore("PasswordSuperAdmin@1"))
        self.assertEqual("break_glass", self.b.verifica_secondo_fattore("ROMPI-IL-VETRO-9"))

    def test_una_password_CON_ACCENTI_continua_a_funzionare(self):
        """⛔ LA META' CHE IMPEDISCE DI «RIPARARE» ROMPENDO.

        La riparazione ovvia sarebbe stata «rifiuta tutto cio' che non e' ASCII»: sbagliata,
        perche' una password legittima puo' contenere accenti (o cinese, o emoji) e la
        bloccherebbe -- chiudendo fuori dal proprio sistema dei soldi chi l'ha scelta. Si
        confrontano i BYTE: a tempo costante, e con qualunque carattere.

        Senza questa prova, un domani qualcuno potrebbe «semplificare» con un
        `if not c.isascii(): return ""` e la suite resterebbe verde.
        """
        b = bk.crea_bunker(self.firma, totp_secret=SEG_RFC,
                           password="PasswòrdÈ-Àccentata-2026",
                           break_glass="ROMPI-IL-VETRÖ-9",
                           orologio=lambda: self.clock["t"])
        self.assertEqual("password", b.verifica_secondo_fattore("PasswòrdÈ-Àccentata-2026"),
                         "una password con accenti non viene piu' riconosciuta: chi l'ha "
                         "scelta resta chiuso fuori dal bunker")
        self.assertEqual("break_glass", b.verifica_secondo_fattore("ROMPI-IL-VETRÖ-9"),
                         "il codice d'emergenza con accenti non funziona piu': e' proprio "
                         "quello che serve quando tutto il resto e' gia' andato storto")
        self.assertEqual("", b.verifica_secondo_fattore("PasswordE-Accentata-2026"),
                         "accetta la versione SENZA accenti: il confronto non e' esatto")
        self.assertEqual("", b.verifica_secondo_fattore("altro"))

    def test_una_revoca_che_NON_e_avvenuta_non_dice_di_essere_avvenuta(self):
        """`revoca` senza firma configurata deve rispondere **False**. Con `True` al posto di
        `False` risponde «logout fatto» **senza aver revocato niente**: chi chiude la
        sessione crede di essere uscito, e il token resta valido fino alla scadenza. E' la
        stessa famiglia del logout del bunker riparato il 2026-07-30 -- che rispondeva `ok`
        senza aver revocato -- tornata da un'altra porta."""
        spento = bk.crea_bunker(None, totp_secret=SEG_RFC,
                                orologio=lambda: self.clock["t"])
        self.assertFalse(spento.revoca("qualunque-cosa"),
                         "ha dichiarato una revoca che non poteva avvenire (nessuna firma "
                         "configurata): chi si disconnette crede di essere uscito")
        self.assertFalse(spento.valida_sessione("qualunque-cosa", "1.2.3.4")["ok"])

    def test_una_revoca_su_un_token_STORTO_rifiuta_senza_esplodere(self):
        """`if not isinstance(dati, dict) or dati.get("k") != "bunker" or not
        dati.get("nonce")` con un `and`: un token manomesso supera i tre controlli e si
        arriva a `dati["nonce"]` su qualcosa che non ha quel campo -> eccezione non gestita
        sull'ingresso di logout. Una porta che si rompe quando la spingono storto."""
        buono = self.b.crea_sessione("1.2.3.4")
        self.assertTrue(self.b.revoca(buono), "la revoca vera non funziona piu'")
        senza_nonce = self.firma.codifica({"k": "bunker", "exp": 99999})
        for storto in (None, "", "non-un-token", 12345, senza_nonce,
                       self.firma.codifica({"k": "altro", "nonce": "x", "exp": 99999})):
            try:
                self.assertFalse(self.b.revoca(storto),
                                 "revoca accettata su un token storto: %r" % (storto,))
            except Exception as e:
                self.fail("la revoca esplode su %r: %s: %s" % (storto, type(e).__name__, e))

    def test_la_lista_dei_revocati_si_SVUOTA_da_sola(self):
        """`if e <= ora` con `<`: i nonce che scadono **esattamente adesso** non vengono mai
        buttati via. Su un server che gira per mesi la lista dei revocati cresce e non
        scende: memoria che si mangia da sola, un logout alla volta. Il modulo lo dichiara --
        «la denylist si auto-pulisce» -- ed e' una promessa che va mantenuta."""
        t = self.b.valida_sessione(self.b.crea_sessione("1.2.3.4"), "1.2.3.4")
        self.assertTrue(t["ok"])
        tok = self.b.crea_sessione("1.2.3.4")
        self.assertTrue(self.b.revoca(tok))
        self.assertEqual(1, len(self.b._revocati), "il nonce revocato non e' stato registrato")
        # l'orologio arriva ESATTAMENTE alla scadenza di quel nonce
        scadenza = list(self.b._revocati.values())[0]
        self.clock["t"] = float(scadenza)
        self.b.revoca(self.b.crea_sessione("9.9.9.9"))     # un giro qualunque fa pulizia
        self.assertNotIn(tok, self.b._revocati)
        self.assertEqual(1, len(self.b._revocati),
                         "la lista dei revocati non si e' svuotata al momento esatto della "
                         "scadenza: su un server che gira per mesi cresce e basta (%r)"
                         % (self.b._revocati,))

    def test_IMPORTARE_il_bunker_non_stampa_e_non_genera_segreti(self):
        """⛔ `if __name__ == "__main__":` con `!=`.

        Quel blocco e' l'aiutante che genera il segreto TOTP per l'iscrizione al telefono.
        Con `!=` gira **all'importazione**: ogni volta che il server carica il modulo
        stamperebbe sullo standard output un `BUNKER_TOTP_SECRET=...` appena generato --
        cioe' un segreto di autenticazione finito nei log, e per giunta diverso da quello
        vero. Un segreto in un log e' un segreto bruciato.
        """
        import io
        import runpy
        import sys
        vecchio, cattura = sys.stdout, io.StringIO()
        sys.stdout = cattura
        try:
            runpy.run_path("fase180_bunker.py", run_name="fase180_bunker")
        finally:
            sys.stdout = vecchio
        uscita = cattura.getvalue()
        self.assertEqual("", uscita.strip(),
                         "importare il bunker stampa qualcosa: %r. Se contiene un segreto, "
                         "quel segreto e' bruciato." % (uscita[:200],))
        self.assertNotIn("BUNKER_TOTP_SECRET", uscita)

    def test_l_aiutante_di_iscrizione_funziona_anche_SENZA_argomenti(self):
        """`seg = sys.argv[1] if len(sys.argv) > 1 else genera_segreto()` con `>=`: lanciato
        senza argomenti va a prendere `sys.argv[1]` che non esiste -> esplode. E' il comando
        che il fondatore usa per iscrivere il telefono: se non parte, l'unico modo di
        configurare il secondo fattore non funziona."""
        import runpy
        import sys
        vecchio_argv, vecchio_out = sys.argv, sys.stdout
        import io
        cattura = io.StringIO()
        sys.argv, sys.stdout = ["fase180_bunker.py"], cattura
        try:
            runpy.run_path("fase180_bunker.py", run_name="__main__")
        except Exception as e:
            sys.argv, sys.stdout = vecchio_argv, vecchio_out
            self.fail("l'aiutante di iscrizione esplode senza argomenti: %s: %s"
                      % (type(e).__name__, e))
        finally:
            sys.argv, sys.stdout = vecchio_argv, vecchio_out
        uscita = cattura.getvalue()
        self.assertIn("BUNKER_TOTP_SECRET=", uscita,
                      "l'aiutante non stampa il segreto da mettere nel telefono: %r"
                      % (uscita[:200],))
        self.assertIn("otpauth://", uscita, "manca il codice da scansionare")


if __name__ == "__main__":
    unittest.main()
