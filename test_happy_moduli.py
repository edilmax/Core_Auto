# -*- coding: utf-8 -*-
"""HAPPY PATH — FETTA "moduli e flussi utente" (punto 2 del mandato).

I cinque moduli che una persona vera COMPILA a mano, provati come li usa lei: prima il caso
felice (dati giusti -> l'effetto succede DAVVERO), poi il caso in cui dimentica qualcosa
(errore standard, chiaro, e NIENTE scritto a metà).

  1. POST /api/host/registrazione   3 spunte obbligatorie -> 201 e account VERO
  2. POST /api/host/login           credenziali giuste -> token che apre le rotte host
  3. POST /api/partner              candidatura partner -> 201, GDPR-gated
  4. POST /api/domanda              lista d'attesa -> 201 col Credito Fondatore firmato
  5. POST /api/preventivo/email     preventivo via email -> 200 e email PARTITA

Ogni test asserisce (a) lo STATO esatto, (b) CHIAVI e TIPI del corpo, (c) un VALORE vero
(un host_id, un token che si verifica, un conteggio in archivio, l'email nello stub).
In più, ogni errore è un test di NON-SCRITTURA: il rifiuto non deve lasciare righe.

LATO PAGINA (modo-di-rompersi #3 «testi che mentono» e la regola «mai un codice tecnico in
faccia all'utente»): `TestMessaggiErrorePagine` prende i codici che questi cinque moduli
possono davvero restituire e pretende che il dizionario delle pagine li spieghi in tutte e
8 le lingue. Visto ROSSO il 2026-07-28 su 7 codici (account_sospeso + i 6 del preventivo
via email): l'utente leggeva `gia_inviato_riprova_piu_tardi` così com'era.

Zero rete: SMTP è uno stub in RAM, Stripe non serve, il geocoding resta spento.
Tutti i DB su FILE temporanei (mai :memory:, modo-di-rompersi #8).
"""
import datetime
import io
import json
import os
import re
import shutil
import tempfile
import unittest

from fase61_localizzazione import LINGUE_SUPPORTATE
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import MAX_PREVENTIVI_EMAIL_ORA, crea_router
from fase158_domanda import CREDITO_FONDATORE_CENTS
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

QUI = os.path.dirname(os.path.abspath(__file__))
BASE = datetime.date.today() + datetime.timedelta(days=30)
IP = {"X-Forwarded-For": "198.51.100.9", "User-Agent": "Mozilla/5.0 (collaudo moduli)"}


def _giorno(i):
    return (BASE + datetime.timedelta(days=i)).isoformat()


class _EmailStub:
    """Provider email in RAM: registra (destinatario, oggetto, html) e dice sempre sì."""

    def __init__(self):
        self.inviate = []
        self.esito = True

    def invia(self, dest, oggetto, html):
        self.inviate.append((dest, oggetto, html))
        return self.esito


class _Base(unittest.TestCase):
    """Sistema VERO su file temporanei: registro host, accettazioni, partner, domanda,
    catalogo/inventario (servono al preventivo) e provider email stub."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="happy_moduli_")
        d = self.d
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"M" * 32, con_registrazione_host=True,
            db_catalogo=d + "/cat.db", db_inventario=d + "/inv.db",
            db_registro_host=d + "/reg.db", db_accettazioni=d + "/acc.db",
            db_partner=d + "/part.db", db_domanda=d + "/dom.db",
            db_payout=d + "/payout.db", db_pendenti=d + "/pend.db",
            db_viral=d + "/viral.db", db_credito_usati=d + "/cred.db",
            file_referral=d + "/referral.json",
            commissione_bps=1000, psp_bps=300))
        self.mail = _EmailStub()
        self.sis.email_provider = self.mail
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def g(self, metodo, path, corpo=None, headers=None):
        """Una chiamata al router VERO, con un IP finto (il rate-limit del login è per IP)."""
        h = dict(IP)
        h.update(headers or {})
        return self.r.gestisci(metodo, path, {},
                               json.dumps(corpo) if corpo is not None else None, h)

    # ── moduli ────────────────────────────────────────────────────────────────────
    def modulo_registrazione(self, **extra):
        """Il modulo di registrazione host COMPILATO BENE (le 3 spunte incluse)."""
        m = {"email": "anna@example.com", "password": "password1",
             "ragione_sociale": "Casa di Anna",
             "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
             "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE, "lang": "it"}
        m.update(extra)
        return m

    def registra_host(self, **extra):
        st, corpo = self.g("POST", "/api/host/registrazione", self.modulo_registrazione(**extra))
        self.assertEqual(st, 201, corpo)
        return corpo


# ══════════════════════════════════════════════════════════════════════════════════
# 1. REGISTRAZIONE HOST — le 3 spunte obbligatorie
# ══════════════════════════════════════════════════════════════════════════════════
class TestModuloRegistrazioneHost(_Base):

    def test_completa_201_e_account_creato_davvero(self):
        st, c = self.g("POST", "/api/host/registrazione", self.modulo_registrazione())
        self.assertEqual(st, 201, c)
        # (b) chiavi e TIPI
        self.assertIs(c["ok"], True)
        self.assertIsInstance(c["host_id"], str)
        self.assertIsInstance(c["token"], str)
        # (c) valori VERI: l'id ha la forma del registro e il token si verifica
        self.assertTrue(c["host_id"].startswith("h_"), c["host_id"])
        self.assertEqual(self.sis.registro_host.verifica_token(c["token"]), c["host_id"])
        # l'account ESISTE in archivio (non è solo una risposta gentile)
        self.assertTrue(self.sis.registro_host.esiste_host(c["host_id"]))
        self.assertEqual(self.sis.registro_host.conta_host(), 1)
        self.assertEqual((self.sis.registro_host.info_host(c["host_id"]) or {})["email"],
                         "anna@example.com")

    def test_completa_registra_le_prove_firmate_dei_consensi(self):
        c = self.registra_host()
        acc = c["accettazione"]
        self.assertIs(acc["registrata"], True)
        self.assertIs(acc["vessatorie"], True)          # artt. 1341-1342 c.c.
        self.assertIs(acc["privacy_registrata"], True)  # GDPR, documento SEPARATO
        self.assertEqual(acc["versione"], CONTRATTO_HOST_VERSIONE)
        # due righe firmate in archivio (contratto + privacy), sigillo INTEGRO
        righe = self.sis.accettazioni.elenco(c["host_id"])
        self.assertEqual(len(righe), 2, righe)
        self.assertTrue(all(r["integra"] for r in righe), righe)
        stato = self.sis.accettazioni.stato_consensi(c["host_id"])
        self.assertIs(stato["contratto_corrente"], True)
        self.assertIs(stato["clausole_vessatorie"], True)
        self.assertIs(stato["privacy_corrente"], True)
        self.assertIs(stato["deve_riaccettare"], False)

    def test_il_token_appena_nato_apre_davvero_le_rotte_host(self):
        """Cablaggio (modo #2): il token della registrazione non è un ornamento."""
        c = self.registra_host()
        st, out = self.g("GET", "/api/host/alloggi", None, {"X-Host-Token": c["token"]})
        self.assertEqual(st, 200, out)
        self.assertIsInstance(out["alloggi"], list)

    def test_manca_UNA_spunta_422_con_l_elenco_di_quella_mancante(self):
        for chiave in ("accetta_termini", "accetta_clausole", "accetta_privacy"):
            with self.subTest(spunta=chiave):
                st, c = self.g("POST", "/api/host/registrazione",
                               self.modulo_registrazione(**{chiave: False,
                                                            "email": "x-%s@example.com" % chiave}))
                self.assertEqual(st, 422, c)
                self.assertEqual(c["errore"], "consensi_mancanti")
                self.assertEqual(c["mancanti"], [chiave])
                self.assertIsInstance(c["mancanti"], list)
        # EFFETTO: nessun account è nato da nessuno dei tre rifiuti
        self.assertEqual(self.sis.registro_host.conta_host(), 0)

    def test_campo_del_tutto_ASSENTE_stesso_errore_non_solo_quando_e_false(self):
        """Il buco classico: `False` bloccato, chiave mancante passata. Qui NO."""
        for chiave in ("accetta_termini", "accetta_clausole", "accetta_privacy"):
            with self.subTest(assente=chiave):
                modulo = self.modulo_registrazione(email="y-%s@example.com" % chiave)
                del modulo[chiave]
                st, c = self.g("POST", "/api/host/registrazione", modulo)
                self.assertEqual(st, 422, c)
                self.assertEqual(c["errore"], "consensi_mancanti")
                self.assertEqual(c["mancanti"], [chiave])
        self.assertEqual(self.sis.registro_host.conta_host(), 0)

    def test_nessuna_spunta_le_elenca_TUTTE_E_TRE(self):
        modulo = self.modulo_registrazione()
        for k in ("accetta_termini", "accetta_clausole", "accetta_privacy"):
            del modulo[k]
        st, c = self.g("POST", "/api/host/registrazione", modulo)
        self.assertEqual(st, 422, c)
        self.assertEqual(c["mancanti"],
                         ["accetta_termini", "accetta_clausole", "accetta_privacy"])

    def test_il_rifiuto_non_brucia_l_email_si_puo_riprovare(self):
        """Prova di NON-SCRITTURA forte: dopo il rifiuto la STESSA email si registra."""
        st, _ = self.g("POST", "/api/host/registrazione",
                       self.modulo_registrazione(accetta_privacy=False))
        self.assertEqual(st, 422)
        st, c = self.g("POST", "/api/host/registrazione", self.modulo_registrazione())
        self.assertEqual(st, 201, c)      # l'email NON era stata occupata a metà

    def test_errori_standard_degli_altri_campi(self):
        casi = (({"email": "senza-chiocciola"}, "email_non_valida"),
                ({"email": "b@example.com", "password": "corta"}, "password_troppo_corta"))
        for extra, atteso in casi:
            with self.subTest(atteso=atteso):
                st, c = self.g("POST", "/api/host/registrazione",
                               self.modulo_registrazione(**extra))
                self.assertEqual(st, 422, c)
                self.assertIs(c["ok"], False)
                self.assertEqual(c["errore"], atteso)
        self.assertEqual(self.sis.registro_host.conta_host(), 0)

    def test_email_gia_registrata_e_DISTINTA_dal_login_fallito(self):
        self.registra_host()
        st, c = self.g("POST", "/api/host/registrazione", self.modulo_registrazione())
        self.assertEqual(st, 422, c)
        self.assertEqual(c["errore"], "email_gia_registrata")   # -> «accedi», non «riprova»
        self.assertEqual(self.sis.registro_host.conta_host(), 1)  # nessun doppione


# ══════════════════════════════════════════════════════════════════════════════════
# 2. LOGIN HOST
# ══════════════════════════════════════════════════════════════════════════════════
class TestModuloLoginHost(_Base):

    def setUp(self):
        super().setUp()
        self.host = self.registra_host()

    def test_credenziali_giuste_200_e_token_valido(self):
        st, c = self.g("POST", "/api/host/login",
                       {"email": "anna@example.com", "password": "password1"})
        self.assertEqual(st, 200, c)
        self.assertIs(c["ok"], True)
        self.assertEqual(c["host_id"], self.host["host_id"])
        self.assertIsInstance(c["token"], str)
        # (c) il token è VERO: verifica lato registro e apre una rotta host
        self.assertEqual(self.sis.registro_host.verifica_token(c["token"]), self.host["host_id"])
        st2, out = self.g("GET", "/api/host/alloggi", None, {"X-Host-Token": c["token"]})
        self.assertEqual(st2, 200, out)
        # il gatekeeper di pagina riceve il suo cookie firmato
        nome, _valore, ttl = c["_cookie"][0]
        self.assertEqual(nome, "bv_host")
        self.assertGreater(ttl, 0)

    def test_email_con_spazi_ai_bordi_entra_lo_stesso(self):
        """Gentilezza provata: uno spazio incollato non deve dire «password sbagliata»."""
        st, c = self.g("POST", "/api/host/login",
                       {"email": "  Anna@Example.com  ", "password": "password1"})
        self.assertEqual(st, 200, c)
        self.assertEqual(c["host_id"], self.host["host_id"])

    def test_email_inesistente_e_password_sbagliata_NON_si_distinguono(self):
        """SCELTA DI SICUREZZA, non una svista: le due risposte sono IDENTICHE.

        Distinguerle regalerebbe a chiunque un oracolo per sapere se un indirizzo è
        registrato da noi (enumerazione utenti: chi risponde «questa email non esiste»
        conferma, per differenza, tutte le altre). La chiarezza per l'utente onesto NON si
        compra con quell'oracolo: si compra col MESSAGGIO, che dice cosa fare
        («Email o password non corretta ... oppure usa Password dimenticata?»).
        Il messaggio è verificato in TestMessaggiErrorePagine.
        """
        st1, c1 = self.g("POST", "/api/host/login",
                         {"email": "nessuno@example.com", "password": "password1"})
        st2, c2 = self.g("POST", "/api/host/login",
                         {"email": "anna@example.com", "password": "sbagliata9"})
        self.assertEqual((st1, st2), (401, 401), (c1, c2))
        self.assertEqual(c1, c2, "le due risposte devono essere INDISTINGUIBILI")
        self.assertEqual(c1["errore"], "credenziali_non_valide")
        self.assertIs(c1["ok"], False)
        self.assertNotIn("token", c1)            # nessun token consegnato per sbaglio

    def test_account_sospeso_e_un_errore_DISTINTO_e_onesto(self):
        """Qui distinguere è giusto: l'utente ESISTE e ha le credenziali giuste, ma è
        sospeso — dirgli «password sbagliata» lo manderebbe a resettarla per niente."""
        self.assertTrue(self.sis.registro_host.imposta_stato(self.host["host_id"], "sospeso"))
        st, c = self.g("POST", "/api/host/login",
                       {"email": "anna@example.com", "password": "password1"})
        self.assertEqual(st, 401, c)
        self.assertEqual(c["errore"], "account_sospeso")
        self.assertNotEqual(c["errore"], "credenziali_non_valide")

    def test_password_mancante_non_e_un_500(self):
        st, c = self.g("POST", "/api/host/login", {"email": "anna@example.com"})
        self.assertEqual(st, 401, c)
        self.assertEqual(c["errore"], "credenziali_non_valide")


# ══════════════════════════════════════════════════════════════════════════════════
# 3. MODULO PARTNER
# ══════════════════════════════════════════════════════════════════════════════════
class TestModuloPartner(_Base):

    MODULO = {"nome": "Luca Rossi", "email": "luca@example.com",
              "tipo": "property_manager", "citta": "Firenze",
              "messaggio": "Gestisco 12 appartamenti in centro.", "consenso": True}

    def test_completo_201_e_candidatura_leggibile_dall_admin(self):
        st, c = self.g("POST", "/api/partner", dict(self.MODULO))
        self.assertEqual(st, 201, c)
        self.assertEqual(c, {"ok": True})
        # (c) valore vero: la candidatura c'è, con i campi come li ha scritti la persona
        st2, out = self.g("GET", "/api/admin/partner", None, {"X-Admin-Key": "ak"})
        self.assertEqual(st2, 200, out)
        self.assertEqual(out["totale"], 1)
        self.assertIsInstance(out["candidati"], list)
        riga = out["candidati"][0]
        self.assertEqual(riga["email"], "luca@example.com")
        self.assertEqual(riga["tipo"], "property_manager")
        self.assertEqual(riga["citta"], "Firenze")

    def test_senza_consenso_422_consenso_richiesto_e_ZERO_righe(self):
        modulo = dict(self.MODULO)
        del modulo["consenso"]                       # casella mai spuntata: chiave assente
        st, c = self.g("POST", "/api/partner", modulo)
        self.assertEqual(st, 422, c)
        self.assertEqual(c, {"errore": "consenso_richiesto"})
        self.assertEqual(self.sis.partner.conta(), 0, "GDPR: senza consenso NIENTE in archivio")

    def test_consenso_finto_non_vale(self):
        """`consenso:"true"` (stringa) o `1` non sono una spunta: solo il booleano True."""
        for finto in ("true", 1, "si", [True]):
            with self.subTest(consenso=finto):
                st, c = self.g("POST", "/api/partner", dict(self.MODULO, consenso=finto))
                self.assertEqual(st, 422, c)
                self.assertEqual(c["errore"], "consenso_richiesto")
        self.assertEqual(self.sis.partner.conta(), 0)

    def test_campi_obbligatori_mancanti_errore_e_niente_scritto(self):
        for extra in ({"nome": "L"}, {"email": "non-una-email"}, {"tipo": "astronauta"}):
            with self.subTest(**extra):
                st, c = self.g("POST", "/api/partner", dict(self.MODULO, **extra))
                self.assertEqual(st, 422, c)
                self.assertIsInstance(c["errore"], str)
                self.assertTrue(c["errore"])
        self.assertEqual(self.sis.partner.conta(), 0)


# ══════════════════════════════════════════════════════════════════════════════════
# 4. LISTA D'ATTESA (/api/domanda) — il cuore del cold-start
# ══════════════════════════════════════════════════════════════════════════════════
class TestModuloListaAttesa(_Base):

    def test_email_valida_201_col_credito_fondatore(self):
        st, c = self.g("POST", "/api/domanda",
                       {"email": "ospite@example.com", "citta": "Napoli", "lang": "it"})
        self.assertEqual(st, 201, c)
        self.assertIs(c["ok"], True)
        self.assertIsInstance(c["credito_token"], str)
        self.assertIsInstance(c["credito_cents"], int)
        self.assertIsInstance(c["messaggio"], str)
        # (c) valori VERI: importo dal motore, città nel messaggio, iscrizione in archivio
        self.assertEqual(c["credito_cents"], CREDITO_FONDATORE_CENTS)
        self.assertGreater(c["credito_cents"], 0)
        self.assertIn("Napoli", c["messaggio"])
        self.assertEqual(self.sis.domanda.conta("Napoli"), 1)
        self.assertEqual(self.sis.domanda.email_citta("Napoli"), ["ospite@example.com"])
        # il credito è un token FIRMATO, non una stringa qualsiasi
        dati = self.sis.firma.decodifica(c["credito_token"])
        self.assertEqual(dati["tipo"], "credito_fondatore")
        self.assertEqual(dati["email"], "ospite@example.com")
        self.assertEqual(dati["citta"], "napoli")
        self.assertEqual(dati["credito_cents"], CREDITO_FONDATORE_CENTS)
        self.assertEqual(dati["valuta"], "EUR")

    def test_email_invalida_422_e_NIENTE_in_archivio(self):
        for cattiva in ("non-una-email", "", "   ", "a@b", None, 12345):
            with self.subTest(email=cattiva):
                st, c = self.g("POST", "/api/domanda", {"email": cattiva, "citta": "Napoli"})
                self.assertEqual(st, 422, c)
                self.assertEqual(c, {"errore": "email_non_valida"})
        self.assertEqual(self.sis.domanda.conta(), 0)

    def test_citta_mancante_NON_blocca_la_cattura(self):
        """Regola di prodotto: una email valida entra SEMPRE (è l'anti-vuoto)."""
        st, c = self.g("POST", "/api/domanda", {"email": "ospite2@example.com", "lang": "it"})
        self.assertEqual(st, 201, c)
        self.assertEqual(self.sis.domanda.conta("(qualsiasi)"), 1)
        self.assertIn("questa destinazione", c["messaggio"])

    def test_messaggio_nella_lingua_dell_ospite(self):
        st, c = self.g("POST", "/api/domanda",
                       {"email": "guest@example.com", "citta": "Lisbon", "lang": "en"})
        self.assertEqual(st, 201, c)
        self.assertIn("Founder Credit", c["messaggio"])
        self.assertNotIn("Credito Fondatore", c["messaggio"])

    def test_seconda_iscrizione_stessa_email_stessa_citta_non_duplica(self):
        for _ in range(3):
            st, _c = self.g("POST", "/api/domanda",
                            {"email": "bis@example.com", "citta": "Bari"})
            self.assertEqual(st, 201)
        self.assertEqual(self.sis.domanda.conta("Bari"), 1)

    def test_la_prova_sociale_conta_davvero(self):
        self.g("POST", "/api/domanda", {"email": "a@example.com", "citta": "Bologna"})
        self.g("POST", "/api/domanda", {"email": "b@example.com", "citta": "Bologna"})
        st, c = self.r.gestisci("GET", "/api/domanda/conta", {"citta": "Bologna"}, None, {})
        self.assertEqual(st, 200, c)
        self.assertEqual(c["richieste"], 2)


# ══════════════════════════════════════════════════════════════════════════════════
# 5. PREVENTIVO VIA EMAIL
# ══════════════════════════════════════════════════════════════════════════════════
class TestModuloPreventivoEmail(_Base):

    def setUp(self):
        super().setUp()
        # provider STACCATO mentre monto la scenografia: l'email di benvenuto dell'host parte
        # in un thread di sfondo e sporcherebbe il conteggio (e sarebbe una gara, non un test).
        self.sis.email_provider = None
        host = self.registra_host()
        self.sis.email_provider = self.mail
        self.tok = {"X-Host-Token": host["token"]}
        self.slug = "casa-moduli"
        st, c = self.g("POST", "/api/host/pubblica", {
            "slug": self.slug, "titolo": "Casa dei Moduli", "citta": "Roma", "paese": "IT",
            "cin": "IT058091C2X5V0ABCD", "descrizione": "Appartamento luminoso in centro.",
            "prezzo_notte_cents": 20000, "capacita": 4, "camere": 2, "bagni": 1,
            "valuta": "EUR", "servizi": ["wifi"], "immagini": []}, self.tok)
        self.assertEqual(st, 201, c)
        st, c = self.g("POST", "/api/host/disponibilita_range",
                       {"alloggio_id": self.slug, "da": _giorno(0), "a": _giorno(20),
                        "unita_totali": 2, "prezzo_netto_cents": 20000, "min_notti": 1},
                       self.tok)
        self.assertEqual(st, 200, c)

    def modulo(self, **extra):
        m = {"alloggio_id": self.slug, "check_in": _giorno(1), "check_out": _giorno(3),
             "party": 2, "email": "ospite@example.com", "lang": "it"}
        m.update(extra)
        return m

    def test_dati_validi_200_e_email_PARTITA(self):
        st, c = self.g("POST", "/api/preventivo/email", self.modulo())
        self.assertEqual(st, 200, c)
        self.assertEqual(c, {"stato": "inviata"})
        # (c) l'effetto è VERO: una email, al destinatario giusto, col link per finire
        self.assertEqual(len(self.mail.inviate), 1, self.mail.inviate)
        dest, oggetto, html = self.mail.inviate[0]
        self.assertEqual(dest, "ospite@example.com")
        self.assertIn("Casa dei Moduli", oggetto)
        self.assertIn("apri=" + self.slug, html)
        self.assertIn("ci=" + _giorno(1), html)
        self.assertIn("co=" + _giorno(3), html)

    def test_date_SPARITE_422_campi_mancanti_e_nessuna_email(self):
        for mancante in ("check_in", "check_out"):
            with self.subTest(manca=mancante):
                m = self.modulo()
                del m[mancante]
                st, c = self.g("POST", "/api/preventivo/email", m)
                self.assertEqual(st, 422, c)
                self.assertEqual(c, {"errore": "campi_mancanti"})
        # anche l'alloggio sparito è lo stesso errore standard
        m = self.modulo()
        del m["alloggio_id"]
        st, c = self.g("POST", "/api/preventivo/email", m)
        self.assertEqual((st, c), (422, {"errore": "campi_mancanti"}))
        self.assertEqual(self.mail.inviate, [], "un modulo incompleto non deve spedire nulla")

    def test_email_invalida_422_e_nessuna_email(self):
        for cattiva in ("senza-chiocciola", "a b@x.it", "x@y.it\r\nBcc: vittima@x.it", ""):
            with self.subTest(email=cattiva):
                st, c = self.g("POST", "/api/preventivo/email", self.modulo(email=cattiva))
                self.assertEqual(st, 422, c)
                self.assertEqual(c, {"errore": "email_non_valida"})
        self.assertEqual(self.mail.inviate, [])

    def test_date_impossibili_422_non_disponibile(self):
        st, c = self.g("POST", "/api/preventivo/email",
                       self.modulo(check_in=_giorno(3), check_out=_giorno(1)))
        self.assertEqual(st, 422, c)
        self.assertEqual(c, {"errore": "non_disponibile"})
        self.assertEqual(self.mail.inviate, [])

    def test_doppio_invio_identico_429_con_codice_parlante(self):
        self.assertEqual(self.g("POST", "/api/preventivo/email", self.modulo())[0], 200)
        st, c = self.g("POST", "/api/preventivo/email", self.modulo())
        self.assertEqual(st, 429, c)
        self.assertEqual(c, {"errore": "gia_inviato_riprova_piu_tardi"})
        self.assertEqual(len(self.mail.inviate), 1)   # una sola email, davvero

    def test_tetto_orario_per_indirizzo(self):
        """Cambiare data aggira il throttle per (email, date): il tetto per INDIRIZZO no."""
        for i in range(MAX_PREVENTIVI_EMAIL_ORA):
            st, c = self.g("POST", "/api/preventivo/email",
                           self.modulo(check_out=_giorno(3 + i)))
            self.assertEqual(st, 200, c)
        st, c = self.g("POST", "/api/preventivo/email", self.modulo(check_out=_giorno(9)))
        self.assertEqual(st, 429, c)
        self.assertEqual(c, {"errore": "troppe_richieste_per_questa_email"})
        self.assertEqual(len(self.mail.inviate), MAX_PREVENTIVI_EMAIL_ORA)

    def test_email_spenta_503_onesto(self):
        self.sis.email_provider = None
        st, c = self.g("POST", "/api/preventivo/email", self.modulo())
        self.assertEqual(st, 503, c)
        self.assertEqual(c, {"errore": "email_non_disponibile"})

    def test_invio_fallito_502_non_finge_successo(self):
        self.mail.esito = False
        st, c = self.g("POST", "/api/preventivo/email", self.modulo())
        self.assertEqual(st, 502, c)
        self.assertEqual(c, {"errore": "invio_fallito"})


# ══════════════════════════════════════════════════════════════════════════════════
# LATO PAGINA — «mai un codice tecnico in faccia all'utente»
# ══════════════════════════════════════════════════════════════════════════════════
LINGUE_PAGINA = ("it", "en", "es", "fr", "de", "pt", "ja", "zh")

# I codici che i moduli di QUESTA fetta possono davvero restituire a una persona.
# Chi li mostra: host.html (registrazione/login) e index.html (lista d'attesa, preventivo),
# entrambi via BV.fraseErrore in app.js -> il dizionario deve spiegarli tutti.
CODICI_VISIBILI = (
    # registrazione host
    "consensi_mancanti", "email_non_valida", "password_troppo_corta",
    "email_gia_registrata", "contratto_aggiornato",
    "line_token_non_valido", "wechat_webhook_non_valido",
    # login host
    "credenziali_non_valide", "account_sospeso", "troppi_tentativi",
    # preventivo via email (index.html)
    "campi_mancanti", "non_disponibile", "gia_inviato_riprova_piu_tardi",
    "troppe_richieste_per_questa_email", "email_non_disponibile", "invio_fallito",
    # pannello host — calendario prezzi (`GET /api/host/calendario_prezzi`).
    # ⛔ 2026-08-13: questi QUATTRO finivano grezzi in faccia all'host, e nessuna
    # guardia poteva vederlo: l'elenco qui sopra e' compilato A MANO, quindi il
    # denominatore non era «i codici che il server restituisce» ma «quelli che
    # qualcuno si e' ricordato di scrivere». Tre c'erano da prima; il quarto
    # (`range_date_non_valido`) e' nato quel giorno insieme alla rotta che lo usa.
    "alloggio_mancante", "date_mancanti", "non_tuo", "range_date_non_valido",
)


def _leggi(nome):
    with io.open(os.path.join(QUI, "deploy", nome), encoding="utf-8") as f:
        return f.read()


class TestMessaggiErrorePagine(unittest.TestCase):
    """Il dizionario delle pagine spiega OGNI codice che i moduli restituiscono, in 8 lingue.

    VISTO ROSSO il 2026-07-28: mancavano `account_sospeso` e i sei codici del preventivo
    via email, quindi l'host sospeso leggeva «account_sospeso» e l'ospite che ri-chiedeva
    il preventivo leggeva «gia_inviato_riprova_piu_tardi». Codice grezzo in faccia.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = _leggi("app.js")
        cls.host = _leggi("host.html")
        cls.index = _leggi("index.html")
        cls.partner = _leggi("partner.html")
        blocco = re.search(r"BV\.ERR_AUTH\s*=\s*\{.*?\n\s*\};", cls.app, re.S)
        assert blocco, "BV.ERR_AUTH non trovato in app.js"
        cls.dizionario = blocco.group(0)

    def test_il_dizionario_ha_tutte_e_8_le_lingue(self):
        for lg in LINGUE_PAGINA:
            self.assertRegex(self.dizionario, r"(?<![A-Za-z_])%s:\{" % lg,
                             "il dizionario errori non ha la lingua %s" % lg)
        self.assertEqual(sorted(LINGUE_PAGINA), sorted(LINGUE_SUPPORTATE),
                         "le lingue delle pagine non sono quelle del motore")

    def test_ogni_codice_visibile_ha_una_frase_in_TUTTE_le_8_lingue(self):
        for cod in CODICI_VISIBILI:
            with self.subTest(codice=cod):
                n = len(re.findall(r"(?<![A-Za-z_])%s:" % re.escape(cod), self.dizionario))
                self.assertEqual(n, len(LINGUE_PAGINA),
                                 "'%s' spiegato in %d lingue su 8: l'utente vedrebbe il "
                                 "codice grezzo nelle altre" % (cod, n))

    def test_le_frasi_non_sono_il_codice_stesso(self):
        """Guardia anti-finto-verde: una frase copia-incolla del codice non spiega niente."""
        for cod in CODICI_VISIBILI:
            for m in re.finditer(r"(?<![A-Za-z_])%s:\s*(['\"])(.*?)\1" % re.escape(cod),
                                 self.dizionario):
                frase = m.group(2)
                self.assertNotEqual(frase, cod)
                self.assertGreater(len(frase), 12, "%s: frase troppo corta %r" % (cod, frase))
                self.assertNotIn("_", frase.replace("\\_", ""),
                                 "%s: la frase sembra un codice tecnico (%r)" % (cod, frase))

    def test_le_pagine_passano_dal_dizionario_e_non_stampano_il_codice(self):
        for nome, pagina in (("host.html", self.host), ("index.html", self.index)):
            self.assertIn("BV.fraseErrore", pagina,
                          "%s non usa il dizionario: stamperebbe il codice grezzo" % nome)
        # ⛔ QUESTA GUARDIA E' STATA RESA PIU' FORTE IL 2026-08-18, non allentata.
        # Prima pretendeva che `ERR_AUTH` fosse consultato PRIMA di `return String(` -- cioe'
        # ammetteva che il codice grezzo finisse a schermo, purche' come ultima scelta. Il
        # percorso col browser (`collaudi/percorso_ospite_host.js`) ha dimostrato che
        # quell'ultima scelta si avverava davvero: col gateway muto l'ospite leggeva
        # `pagamento_non_disponibile` MENTRE pagava. Ora il contratto e' che il codice grezzo
        # non esca MAI, quindi `return String(` non deve piu' esistere e al suo posto ci va
        # una frase del dizionario. Il nome di questo test lo prometteva gia'.
        fe = self.app[self.app.index("BV.fraseErrore"):]
        self.assertNotIn("return String(", fe,
                         "fraseErrore ripiega ANCORA sul codice grezzo: e' cosi' che un "
                         "ospite legge 'pagamento_non_disponibile' mentre paga")
        self.assertLess(fe.index("ERR_AUTH"), fe.index("generico"),
                        "fraseErrore ripiega sulla frase generica PRIMA di consultare il "
                        "dizionario: i codici tradotti non verrebbero mai usati")

    def test_i_tre_moduli_puntano_alle_rotte_vere(self):
        """Cablaggio (modo #2): i moduli delle pagine chiamano le rotte che ho provato."""
        self.assertIn("/api/host/registrazione", self.host)
        self.assertIn("/api/host/login", self.host)
        self.assertIn("/api/domanda", self.index)
        self.assertIn("/api/preventivo/email", self.index)
        self.assertIn('fetch("/api/partner"', self.partner)

    def test_partner_html_ha_il_suo_messaggio_di_consenso_in_8_lingue(self):
        """partner.html è autonoma (non usa app.js): il consenso GDPR mancante deve avere
        una frase propria in tutte e 8 le lingue, mai `consenso_richiesto`."""
        self.assertEqual(self.partner.count('err_consenso:"'), 8,
                         "err_consenso non è in tutte e 8 le lingue di partner.html")
        self.assertNotIn("consenso_richiesto", self.partner,
                         "partner.html mostrerebbe il codice grezzo del server")
        # e la spunta blocca PRIMA della chiamata di rete
        js = self.partner[self.partner.index("onsubmit"):]
        self.assertLess(js.index("err_consenso"), js.index("fetch("))

    def test_le_tre_spunte_sono_nel_modulo_host_e_bloccano_lato_pagina(self):
        for campo in ("accetta_termini", "accetta_clausole", "accetta_privacy"):
            self.assertIn(campo, self.host, "host.html non invia %s" % campo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
