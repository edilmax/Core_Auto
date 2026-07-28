# -*- coding: utf-8 -*-
"""HAPPY PATH — FETTA "host": le 49 rotte /api/host* del router (fase83).

Mandato (livello 1): per OGNI rotta host una richiesta VALIDA e ben formata, con
l'autenticazione giusta e i dati corretti, deve rispondere con lo stato ATTESO e una
struttura JSON coerente. Non basta "non e' 500": ogni chiamata asserisce
  (a) lo STATO esatto,
  (b) le CHIAVI e i TIPI del corpo,
  (c) dove ha senso, un VALORE vero (uno slug, un totale, un conteggio).

Fixture: un host VERO (registrazione con le 3 spunte -> login -> token), un annuncio
pubblicato con disponibilita' aperta, un secondo annuncio "su richiesta" per il flusso
approva/rifiuta, e — dove serve — una prenotazione pagata via webhook firmato.

Niente rete: Stripe (fase85), Connect (fase101), carta off-session (fase183) e il
geocoder (fase166) sono sostituiti da doppi deterministici; SMTP e' uno stub in RAM.
Tutti i DB su FILE temporanei (mai :memory:, modo-di-rompersi #8).

La guardia strutturale `TestCoperturaRotteHost` legge le rotte host DAL SORGENTE del
router: se domani nasce una rotta /api/host/... senza copertura qui, questo test diventa
ROSSO da solo (nessun buco silenzioso).
"""
import datetime
import json
import os
import re
import shutil
import tempfile
import time
import unittest

import fase101_stripe_connect as _connect_mod
import fase183_carta_offsession as _carta_mod
import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256
from fase166_geocoder import crea_geocoder

WH = "whsec_happy_host"
BASE = datetime.date.today() + datetime.timedelta(days=30)

# PNG 1x1 valido (magic bytes riconosciuti da _ext_da_magic)
PNG_1x1_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
               "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

# registro vivo: (metodo, path) -> stato ottenuto. Serve alla TABELLA DI COPERTURA.
OTTENUTI = {}
# quante prove del modulo sono davvero partite: serve a NON giudicare la copertura
# quando si esegue una sola classe (`python -m unittest test_happy_host.TestFotoHost`).
PROVE_ESEGUITE = [0]

# Contratto dichiarato: (metodo, path) -> stato atteso sulla richiesta VALIDA.
ATTESI = {
    ("GET", "/api/host/accettazioni"): 200,
    ("GET", "/api/host/alloggi"): 200,
    ("GET", "/api/host/alloggio"): 200,
    ("POST", "/api/host/alloggio_elimina"): 200,
    ("GET", "/api/host/calendario"): 200,
    ("GET", "/api/host/calendario_prezzi"): 200,
    ("GET", "/api/host/calendario_tutti"): 200,
    ("POST", "/api/host/cambia_password"): 200,
    ("POST", "/api/host/cancella"): 200,
    ("POST", "/api/host/carta_link"): 200,
    ("GET", "/api/host/carta_stato"): 200,
    ("GET", "/api/host/contratto_stato"): 200,
    ("GET", "/api/host/conversazioni"): 200,
    ("GET", "/api/host/dac7_stato"): 200,
    ("POST", "/api/host/dati_fiscali"): 200,
    ("POST", "/api/host/disponibilita"): 200,
    ("POST", "/api/host/disponibilita_range"): 200,
    ("GET", "/api/host/export"): 200,
    ("POST", "/api/host/foto_elimina"): 200,
    ("GET", "/api/host/geocode"): 200,
    ("POST", "/api/host/ical"): 200,
    ("GET", "/api/host/ical_link"): 200,
    ("POST", "/api/host/importa"): 200,
    ("GET", "/api/host/invito"): 200,
    ("POST", "/api/host/invito/qualifica"): 200,
    ("POST", "/api/host/invito/registra"): 201,
    ("POST", "/api/host/kyc_avvia"): 503,        # DORMIENTE: gated da STRIPE_IDENTITY_KEY
    ("GET", "/api/host/kyc_stato"): 200,
    ("GET", "/api/host/link_diretto"): 200,
    ("POST", "/api/host/login"): 200,
    ("GET", "/api/host/metriche"): 200,
    ("GET", "/api/host/metriche_avanzate"): 200,
    ("POST", "/api/host/password_dimenticata"): 200,
    ("POST", "/api/host/password_reset"): 200,
    ("GET", "/api/host/payout"): 200,
    ("GET", "/api/host/prenotazioni"): 200,
    ("GET", "/api/host/prezzo_suggerito"): 200,
    ("POST", "/api/host/pubblica"): 201,
    ("GET", "/api/host/referral"): 200,
    ("POST", "/api/host/registrazione"): 201,
    ("POST", "/api/host/riaccetta"): 200,
    ("GET", "/api/host/richieste"): 200,
    ("POST", "/api/host/richieste/approva"): 200,
    ("POST", "/api/host/richieste/rifiuta"): 200,
    ("GET", "/api/host/seo_report"): 200,
    ("POST", "/api/host/stato"): 200,
    ("GET", "/api/host/stripe_link"): 200,
    ("GET", "/api/host/telegram_link"): 200,
    ("POST", "/api/host/upload_foto"): 201,
}

# Rotte host che NON si possono esercitare in isolamento (nessuna): tabella vuota, ma
# esplicita — se un domani se ne aggiunge una va motivata QUI, non dimenticata.
ESCLUSE = {}


def _giorno(i):
    return (BASE + datetime.timedelta(days=i)).isoformat()


def _fake_fetch_stripe(url, body, headers):
    import secrets
    return {"url": "https://stripe.finto/" + secrets.token_hex(4),
            "id": "cs_" + secrets.token_hex(8)}


def _fake_fetch_geo(url):
    if "reverse" in url:
        return {"address": {"suburb": "Trastevere"}}
    return [{"lat": "41.902782", "lon": "12.496366"}]


class _EmailStub:
    def __init__(self):
        self.inviate = []

    def invia(self, dest, oggetto, html):
        self.inviate.append((dest, oggetto, html))
        return True


class _BaseHost(unittest.TestCase):
    """Fixture comune: host vero + annuncio pubblicato + disponibilita' aperta."""

    def setUp(self):
        PROVE_ESEGUITE[0] += 1
        self.d = tempfile.mkdtemp(prefix="happy_host_")
        self.uploads = os.path.join(self.d, "uploads")
        os.makedirs(self.uploads, exist_ok=True)
        self._env_salvato = {k: os.environ.get(k)
                             for k in ("UPLOAD_DIR", "STRIPE_IDENTITY_KEY",
                                       "TELEGRAM_BOT_USERNAME", "SCATTO3_ATTIVO")}
        os.environ["UPLOAD_DIR"] = self.uploads
        os.environ.pop("STRIPE_IDENTITY_KEY", None)   # KYC deve restare DORMIENTE
        os.environ["TELEGRAM_BOT_USERNAME"] = "BookinVipInfo_bot"

        self._orig_stripe_fetch = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch_stripe)

        d = self.d
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"H" * 32, con_registrazione_host=True,
            db_catalogo=d + "/cat.db", db_inventario=d + "/inv.db",
            db_registro_host=d + "/reg.db", db_accettazioni=d + "/acc.db",
            db_pendenti=d + "/pend.db", db_payout=d + "/payout.db",
            db_garanzia=d + "/gar.db", db_finanza=d + "/fin.db",
            db_messaggi=d + "/msg.db", db_recensioni=d + "/rec.db",
            db_viral=d + "/viral.db", db_domanda=d + "/dom.db",
            db_partner=d + "/part.db", db_tassa_comunale=d + "/tassa.db",
            db_kyc=d + "/kyc.db", db_checkin=d + "/checkin.db",
            db_credito_usati=d + "/cred.db", db_split=d + "/split.db",
            db_coda=d + "/coda.db", db_geocache=d + "/geo.db",
            db_admin_accounts=d + "/admin.db",
            file_referral=d + "/referral.json",
            commissione_bps=1000, psp_bps=300,
            stripe_secret_key="sk_test_finta", stripe_webhook_secret=WH,
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/ko"))
        self.mail = _EmailStub()
        self.sis.email_provider = self.mail

        # geocoder DETERMINISTICO (zero rete): la rotta /api/host/geocode e' viva
        self.sis.geocoder = crea_geocoder(d + "/geo.db", fetch=_fake_fetch_geo)
        # Connect (fase101) e carta (fase183): doppi deterministici, stessa forma dei veri
        self.assertIsInstance(self.sis.connect, _connect_mod.ProviderConnect)
        self.sis.connect.crea_account = lambda email="": "acct_finto_1"
        self.sis.connect.link_onboarding = lambda acct, ritorno, **kw: \
            "https://connect.stripe.finto/setup/" + acct
        self.sis.connect.stato_account = lambda acct: {"pronto": True}
        self.sis.connect.trasferisci = lambda *a, **k: "tr_finto"
        self.assertIsInstance(self.sis.carta, _carta_mod.ProviderCarta)
        self.sis.carta.crea_link_carta = lambda **kw: "https://carta.stripe.finto/sess"

        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")

        self.email_host = "host@happy.it"
        self.password = "password1"
        st, corpo = self.chiama("POST", "/api/host/registrazione", {
            "email": self.email_host, "password": self.password,
            "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
            "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE,
            "ragione_sociale": "Casa Happy SRL", "lang": "it"},
            headers={}, atteso=201)
        self.host_id = corpo["host_id"]
        self.tok = {"X-Host-Token": corpo["token"]}

        self.slug = "casa-happy"
        self.chiama("POST", "/api/host/pubblica", self._scheda(self.slug, "Casa Happy"),
                    atteso=201)
        self.chiama("POST", "/api/host/disponibilita_range",
                    {"alloggio_id": self.slug, "da": _giorno(0), "a": _giorno(30),
                     "unita_totali": 2, "prezzo_netto_cents": 30000, "min_notti": 1},
                    atteso=200)

    def tearDown(self):
        _stripe.ProviderStripe._fetch_reale = self._orig_stripe_fetch
        for k, v in self._env_salvato.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.d, ignore_errors=True)

    # ── infrastruttura ────────────────────────────────────────────────────────────
    def _scheda(self, slug, titolo, **extra):
        d = {"slug": slug, "titolo": titolo, "citta": "Roma", "paese": "IT",
             "cin": "IT058091C2X5V0ABCD", "descrizione": "Appartamento luminoso in centro.",
             "prezzo_notte_cents": 30000, "capacita": 4, "camere": 2, "bagni": 1,
             "valuta": "EUR", "servizi": ["wifi", "aria condizionata"], "immagini": []}
        d.update(extra)
        return d

    def chiama(self, metodo, path, corpo=None, query=None, headers=None, atteso=None):
        """Una chiamata al router VERO. Registra lo stato ottenuto per la tabella."""
        h = self.tok if headers is None else headers
        st, out = self.r.gestisci(metodo, path, query or {},
                                  json.dumps(corpo) if corpo is not None else None, h)
        if path.startswith("/api/host"):
            OTTENUTI[(metodo, path)] = st
        if atteso is not None:
            self.assertEqual(st, atteso, "%s %s -> %d %r" % (metodo, path, st, out))
        return st, out

    def _pubblica_extra(self, slug, titolo, **extra):
        st, out = self.chiama("POST", "/api/host/pubblica",
                              self._scheda(slug, titolo, **extra), atteso=201)
        self.assertEqual(out["slug"], slug)
        return out

    def _prenota(self, slug, off=1, notti=2, party=2):
        """quote -> book sul router vero. Ritorna (riferimento, corpo del book)."""
        st, q = self.r.gestisci("POST", "/api/concierge/quote", {}, json.dumps(
            {"alloggio_id": slug, "check_in": _giorno(off),
             "check_out": _giorno(off + notti), "party": party}), {})
        self.assertEqual(st, 200, q)
        st, b = self.r.gestisci("POST", "/api/concierge/book", {}, json.dumps(
            {"quote_token": q["quote_token"], "email": "ospite@happy.it", "lang": "it"}), {})
        self.assertEqual(st, 201, b)
        return b["riferimento"], b

    def _paga(self, rif):
        """Webhook Stripe FIRMATO: la prenotazione passa a 'pagato'."""
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"id": "cs_" + rif[:10],
                                             "metadata": {"riferimento": rif}}}})
        st, _ = self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                                {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
        self.assertEqual(st, 200)
        self.assertEqual((self.sis.pagamenti_pendenti.info(rif) or {}).get("stato"), "pagato")


# ══════════════════════════════════════════════════════════════════════════════════
class TestAccountHost(_BaseHost):
    """registrazione · login · cambia_password · password_dimenticata · password_reset"""

    def test_registrazione_crea_account_e_prove_firmate(self):
        st, out = self.chiama("POST", "/api/host/registrazione", {
            "email": "secondo@happy.it", "password": "password2",
            "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
            "doc_sha256": doc_sha256(), "lang": "it"}, headers={}, atteso=201)
        self.assertTrue(out["ok"])
        self.assertTrue(out["host_id"].startswith("h_"), out)
        self.assertIsInstance(out["token"], str)
        self.assertTrue(out["token"])
        acc = out["accettazione"]
        self.assertEqual((acc["registrata"], acc["vessatorie"], acc["privacy_registrata"]),
                         (True, True, True), acc)
        self.assertEqual(acc["versione"], CONTRATTO_HOST_VERSIONE)
        # il token nuovo autentica DAVVERO quell'host (non e' una stringa decorativa)
        self.assertEqual(self.sis.registro_host.verifica_token(out["token"]), out["host_id"])

    def test_login_restituisce_token_e_cookie_di_sessione(self):
        st, out = self.chiama("POST", "/api/host/login",
                              {"email": self.email_host, "password": self.password},
                              headers={}, atteso=200)
        self.assertTrue(out["ok"])
        self.assertEqual(out["host_id"], self.host_id)
        self.assertEqual(self.sis.registro_host.verifica_token(out["token"]), self.host_id)
        nomi = [c[0] for c in out["_cookie"]]
        self.assertIn("bv_host", nomi, out)

    def test_cambia_password_e_nuovo_accesso(self):
        st, out = self.chiama("POST", "/api/host/cambia_password",
                              {"vecchia": self.password, "nuova": "password9"}, atteso=200)
        self.assertTrue(out["ok"])
        self.assertTrue(out["token"])
        st, dopo = self.chiama("POST", "/api/host/login",
                               {"email": self.email_host, "password": "password9"},
                               headers={}, atteso=200)
        self.assertTrue(dopo["ok"])

    def test_password_dimenticata_manda_il_magic_link(self):
        st, out = self.chiama("POST", "/api/host/password_dimenticata",
                              {"email": self.email_host, "lang": "it"}, headers={},
                              atteso=200)
        self.assertEqual(out, {"ok": True})            # anti-enumerazione: sempre ok
        for _ in range(50):                            # l'invio e' in un thread daemon
            if any(d == self.email_host for d, _o, _h in self.mail.inviate):
                break
            time.sleep(0.01)
        reset = [h for d, _o, h in self.mail.inviate if d == self.email_host
                 and "#reset=" in h]
        self.assertTrue(reset, "nessuna email di reset con magic-link: %r" % self.mail.inviate)

    def test_password_reset_col_token_valido(self):
        token = self.sis.registro_host.token_reset_password(self.email_host)
        self.assertTrue(token)
        st, out = self.chiama("POST", "/api/host/password_reset",
                              {"token": token, "password": "password7"}, headers={},
                              atteso=200)
        self.assertTrue(out["ok"])
        self.assertEqual(self.sis.registro_host.verifica_token(out["token"]), self.host_id)
        st, dopo = self.chiama("POST", "/api/host/login",
                               {"email": self.email_host, "password": "password7"},
                               headers={}, atteso=200)
        self.assertTrue(dopo["ok"])


# ══════════════════════════════════════════════════════════════════════════════════
class TestAnnunciHost(_BaseHost):
    """pubblica · alloggi · alloggio · stato · alloggio_elimina"""

    def test_pubblica_annuncio(self):
        st, out = self.chiama("POST", "/api/host/pubblica",
                              self._scheda("casa-due", "Casa Due"), atteso=201)
        self.assertEqual(out["stato"], "pubblicato")
        self.assertEqual(out["slug"], "casa-due")
        self.assertIsInstance(out["id"], int)
        self.assertGreater(out["id"], 0)
        self.assertEqual(self.sis.catalogo.host_di_alloggio("casa-due"), self.host_id)

    def test_alloggi_elenca_solo_i_propri(self):
        self._pubblica_extra("casa-due", "Casa Due")
        st, out = self.chiama("GET", "/api/host/alloggi", atteso=200)
        slugs = sorted(a["slug"] for a in out["alloggi"])
        self.assertEqual(slugs, ["casa-due", "casa-happy"])
        prima = out["alloggi"][0]
        for k in ("id", "slug", "titolo", "citta", "prezzo_notte_cents", "valuta", "stato"):
            self.assertIn(k, prima)
        self.assertEqual(prima["valuta"], "EUR")
        self.assertIsInstance(prima["prezzo_notte_cents"], int)

    def test_alloggio_dettaglio_per_il_form_di_modifica(self):
        st, out = self.chiama("GET", "/api/host/alloggio", query={"slug": self.slug},
                              atteso=200)
        self.assertEqual(out["slug"], self.slug)
        self.assertEqual(out["titolo"], "Casa Happy")
        self.assertEqual(out["citta"], "Roma")
        self.assertEqual(out["prezzo_notte_cents"], 30000)
        self.assertEqual(out["capacita"], 4)
        self.assertEqual(out["indirizzo"], "")
        self.assertEqual(out["stato"], "pubblicato")   # il proprietario DEVE vedere lo stato

    def test_stato_sospende_e_ripubblica(self):
        st, out = self.chiama("POST", "/api/host/stato",
                              {"slug": self.slug, "stato": "sospeso"}, atteso=200)
        self.assertEqual(out, {"stato": "sospeso"})
        self.assertEqual(self.sis.catalogo.dettaglio_owner(self.slug)["stato"], "sospeso")
        st, out = self.chiama("POST", "/api/host/stato",
                              {"slug": self.slug, "stato": "pubblicato"}, atteso=200)
        self.assertEqual(out, {"stato": "pubblicato"})
        self.assertEqual(self.sis.catalogo.dettaglio_owner(self.slug)["stato"], "pubblicato")

    def test_modifica_non_ripubblica_un_annuncio_sospeso(self):
        """GUARDIA (difetto VERO trovato qui il 2026-07-28, vista ROSSA sul codice vecchio).

        Il pannello pre-riempie il form da /api/host/alloggio e ri-salva su
        /api/host/pubblica SENZA il campo `stato` (host.html non lo manda): il default
        'pubblicato' di valida_scheda rimetteva ONLINE — e PRENOTABILE — un annuncio che
        l'host aveva SOSPESO, al primo ritocco di titolo/prezzo/foto. Ora lo stato di un
        annuncio esistente si conserva se non e' dichiarato (fase83._blinda_stato)."""
        self.chiama("POST", "/api/host/stato", {"slug": self.slug, "stato": "sospeso"},
                    atteso=200)
        corpo = self._scheda(self.slug, "Casa Happy ristrutturata")   # come host.html
        self.assertNotIn("stato", corpo)
        self.chiama("POST", "/api/host/pubblica", corpo, atteso=201)
        det = self.sis.catalogo.dettaglio_owner(self.slug)
        self.assertEqual(det["stato"], "sospeso", "la modifica ha ri-pubblicato da sola")
        self.assertEqual(det["titolo"], "Casa Happy ristrutturata")   # salvata comunque
        # conseguenza VERA (non un proxy): resta fuori dalla vetrina pubblica
        st, cat = self.r.gestisci("GET", "/api/catalogo", {"citta": "Roma"}, None, {})
        self.assertEqual(st, 200)
        self.assertNotIn(self.slug, [c.get("slug") for c in cat["risultati"]])

    def test_stato_dichiarato_nel_corpo_comanda_sempre(self):
        """Controllo POSITIVO della guardia sopra: la conservazione NON deve incollare
        l'annuncio allo stato vecchio — chi DICHIARA `stato` decide (altrimenti un
        sospeso non tornerebbe piu' online dal form)."""
        self.chiama("POST", "/api/host/stato", {"slug": self.slug, "stato": "sospeso"},
                    atteso=200)
        corpo = self._scheda(self.slug, "Casa Happy", stato="pubblicato")
        self.chiama("POST", "/api/host/pubblica", corpo, atteso=201)
        self.assertEqual(self.sis.catalogo.dettaglio_owner(self.slug)["stato"], "pubblicato")
        st, cat = self.r.gestisci("GET", "/api/catalogo", {"citta": "Roma"}, None, {})
        self.assertIn(self.slug, [c.get("slug") for c in cat["risultati"]])

    def test_alloggio_elimina_senza_prenotazioni(self):
        self._pubblica_extra("casa-sbagliata", "Casa Sbagliata")
        st, out = self.chiama("POST", "/api/host/alloggio_elimina",
                              {"slug": "casa-sbagliata"}, atteso=200)
        self.assertEqual(out, {"stato": "eliminato", "slug": "casa-sbagliata"})
        self.assertIsNone(self.sis.catalogo.host_di_alloggio("casa-sbagliata"))


# ══════════════════════════════════════════════════════════════════════════════════
class TestCalendarioHost(_BaseHost):
    """disponibilita · disponibilita_range · calendario · calendario_prezzi ·
    calendario_tutti · ical · ical_link"""

    def test_disponibilita_giorno_singolo(self):
        st, out = self.chiama("POST", "/api/host/disponibilita",
                              {"alloggio_id": self.slug, "giorno": _giorno(2),
                               "unita_totali": 1, "prezzo_netto_cents": 45000},
                              atteso=200)
        self.assertEqual(out, {"stato": "ok"})
        riga = self.sis.inventario.stato_giorno(self.slug, _giorno(2))
        self.assertEqual(riga["unita_totali"], 1)
        self.assertEqual(riga["prezzo_netto_cents"], 45000)

    def test_disponibilita_range_apre_il_periodo(self):
        st, out = self.chiama("POST", "/api/host/disponibilita_range",
                              {"alloggio_id": self.slug, "da": _giorno(40), "a": _giorno(47),
                               "unita_totali": 3, "prezzo_netto_cents": 25000,
                               "min_notti": 2}, atteso=200)
        self.assertEqual(out, {"giorni_impostati": 7})
        riga = self.sis.inventario.stato_giorno(self.slug, _giorno(45))
        self.assertEqual(riga["unita_totali"], 3)
        self.assertEqual(riga["prezzo_netto_cents"], 25000)

    def test_calendario_del_singolo_alloggio(self):
        st, out = self.chiama("GET", "/api/host/calendario",
                              query={"alloggio": self.slug, "da": _giorno(0),
                                     "a": _giorno(5)}, atteso=200)
        giorni = out["giorni"]
        self.assertEqual(len(giorni), 5)
        self.assertEqual([g["giorno"] for g in giorni], [_giorno(i) for i in range(5)])
        self.assertEqual({g["stato"] for g in giorni}, {"libero"})

    def test_calendario_prezzi_con_suggerimento_dinamico(self):
        # NOTA (asimmetria nota, non un guasto di questa rotta): fase119 usa un range
        # INCLUSIVO [da, a] — contratto fissato da test_fase119 (da==a -> 1 cella) —
        # mentre /api/host/calendario e /calendario_tutti (fase58) usano [da, a).
        # Con gli stessi due campi del pannello la griglia prezzi mostra 1 giorno in piu'.
        st, out = self.chiama("GET", "/api/host/calendario_prezzi",
                              query={"alloggio": self.slug, "da": _giorno(0),
                                     "a": _giorno(4)}, atteso=200)
        celle = out["celle"]
        self.assertEqual(len(celle), 5)
        self.assertEqual([c["giorno"] for c in celle], [_giorno(i) for i in range(5)])
        for c in celle:
            self.assertEqual(c["stato"], "libero")
            self.assertEqual(c["prezzo_cents"], 30000)
            self.assertIsInstance(c["prezzo_dinamico_cents"], int)
            self.assertGreater(c["prezzo_dinamico_cents"], 0)
            self.assertIsInstance(c["moltiplicatore_bps"], int)

    def test_calendario_tutti_vista_multi_alloggio(self):
        self._pubblica_extra("casa-due", "Casa Due")
        self.chiama("POST", "/api/host/disponibilita_range",
                    {"alloggio_id": "casa-due", "da": _giorno(0), "a": _giorno(3),
                     "unita_totali": 1, "prezzo_netto_cents": 10000}, atteso=200)
        st, out = self.chiama("GET", "/api/host/calendario_tutti",
                              query={"da": _giorno(0), "a": _giorno(3)}, atteso=200)
        per_slug = {a["slug"]: a for a in out["alloggi"]}
        self.assertEqual(sorted(per_slug), ["casa-due", "casa-happy"])
        self.assertEqual(per_slug["casa-due"]["titolo"], "Casa Due")
        self.assertEqual(len(per_slug["casa-due"]["giorni"]), 3)
        self.assertEqual({g["stato"] for g in per_slug["casa-happy"]["giorni"]}, {"libero"})

    def test_ical_import_blocca_le_date_dell_ota(self):
        ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
               "UID:airbnb-1\r\nDTSTART;VALUE=DATE:%s\r\nDTEND;VALUE=DATE:%s\r\n"
               "SUMMARY:Reserved\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
               % (_giorno(10).replace("-", ""), _giorno(13).replace("-", "")))
        st, out = self.chiama("POST", "/api/host/ical",
                              {"alloggio_id": self.slug, "ical": ics}, atteso=200)
        self.assertEqual(out, {"eventi": 1, "giorni_bloccati": 3})
        riga = self.sis.inventario.stato_giorno(self.slug, _giorno(11))
        self.assertEqual(riga["unita_totali"], 0)      # data presa sull'OTA: bloccata QUI

    def test_ical_link_firmato_ed_esportabile(self):
        st, out = self.chiama("GET", "/api/host/ical_link",
                              query={"alloggio": self.slug}, atteso=200)
        url = out["url"]
        self.assertTrue(url.startswith("https://bookinvip.com/ical/"), url)
        self.assertTrue(url.endswith(".ics"), url)
        from urllib.parse import unquote
        tok = unquote(url[len("https://bookinvip.com/ical/"):-len(".ics")])
        self.assertEqual(self.sis.firma.decodifica(tok),
                         {"k": "ical", "slug": self.slug})


# ══════════════════════════════════════════════════════════════════════════════════
class TestFotoHost(_BaseHost):
    """upload_foto · foto_elimina"""

    def test_upload_e_elimina_foto(self):
        st, out = self.chiama("POST", "/api/host/upload_foto",
                              {"image_base64": PNG_1x1_B64}, atteso=201)
        url = out["url"]
        self.assertTrue(url.startswith("/uploads/"), url)
        self.assertTrue(url.endswith(".png"), url)
        nome = url[len("/uploads/"):]
        self.assertTrue(os.path.isfile(os.path.join(self.uploads, nome)))
        st, out = self.chiama("POST", "/api/host/foto_elimina", {"url": url}, atteso=200)
        self.assertEqual(out, {"eliminata": True})
        self.assertFalse(os.path.exists(os.path.join(self.uploads, nome)))


# ══════════════════════════════════════════════════════════════════════════════════
class TestPrenotazioniHost(_BaseHost):
    """prenotazioni · metriche · metriche_avanzate · export · payout · cancella"""

    def test_prenotazioni_paginate_col_codice_e_pin(self):
        rif, _b = self._prenota(self.slug, off=1, notti=2)
        self._paga(rif)
        st, out = self.chiama("GET", "/api/host/prenotazioni",
                              query={"vista": "attive", "page": "1", "limit": "10"},
                              atteso=200)
        self.assertEqual((out["vista"], out["page"], out["limit"]), ("attive", 1, 10))
        self.assertEqual(out["totale"], 1)
        self.assertEqual(out["totale_attive"], 1)
        self.assertEqual(out["totale_archivio"], 0)
        self.assertEqual(out["pagine"], 1)
        p = out["prenotazioni"][0]
        self.assertEqual(p["slug"], self.slug)
        self.assertEqual(p["alloggio"], "Casa Happy")
        self.assertEqual((p["check_in"], p["check_out"]), (_giorno(1), _giorno(3)))
        self.assertEqual(p["stato"], "futura")
        self.assertFalse(p["archiviata"])
        self.assertEqual(p["pin"], self.sis.firma.pin_checkin(rif))
        self.assertTrue(p["codice"])

    def test_metriche_aggregano_solo_i_propri_annunci(self):
        rif, b = self._prenota(self.slug, off=1, notti=2)
        self._paga(rif)
        st, out = self.chiama("GET", "/api/host/metriche", atteso=200)
        self.assertEqual(out["valuta"], "EUR")
        self.assertEqual(out["money_unit"], "cents_integer")
        self.assertEqual(out["prenotazioni_attive"], 1)
        self.assertEqual(out["prenotazioni_rimborsate"], 0)
        self.assertEqual(out["notti_occupate"], 2)
        self.assertEqual(out["notti_totali"], 60)      # 30 giorni x 2 unita'
        self.assertEqual(out["occupazione_bps"],
                         out["notti_occupate"] * 10000 // out["notti_totali"])
        self.assertEqual(out["revenue_cents"], 60000)  # 2 notti x 30000 netti

    def test_metriche_avanzate_kpi(self):
        rif, b = self._prenota(self.slug, off=1, notti=2)
        self._paga(rif)
        st, out = self.chiama("GET", "/api/host/metriche_avanzate", atteso=200)
        self.assertEqual(out["prenotazioni"], 1)
        self.assertEqual(out["valuta"], "EUR")
        m = out["metriche"]
        for k in ("prenotazioni_totali", "prenotazioni_attive", "revenue_cents",
                  "notti_vendute", "occupazione_bps", "adr_cents", "revpar_cents",
                  "rating_medio_centi"):
            self.assertIn(k, m)
            self.assertIsInstance(m[k], int)
        self.assertEqual(m["prenotazioni_totali"], 1)
        self.assertEqual(m["notti_vendute"], 2)
        self.assertEqual(m["revenue_cents"], b["prezzo_guest_cents"])
        self.assertEqual(m["adr_cents"], b["prezzo_guest_cents"] // 2)

    def test_export_csv_contabile(self):
        rif, _b = self._prenota(self.slug, off=1, notti=2)
        self._paga(rif)
        st, out = self.chiama("GET", "/api/host/export", atteso=200)
        self.assertEqual(out["righe"], 1)
        csv = out["csv"]
        self.assertIsInstance(csv, str)
        righe = [r for r in csv.strip().splitlines() if r]
        self.assertEqual(len(righe), 2)                # intestazione + 1 prenotazione
        self.assertIn(self.slug, righe[1])
        self.assertIn(_giorno(1), righe[1])

    def test_payout_riepilogo_per_valuta(self):
        rif, b = self._prenota(self.slug, off=1, notti=2)
        self._paga(rif)
        st, out = self.chiama("GET", "/api/host/payout", atteso=200)
        self.assertIn("EUR", out["payout"], out)
        self.assertEqual(out["payout"]["EUR"], {"maturato": b["netto_host_cents"]})
        self.assertEqual(out["debiti_aperti_cents"], {})

    def test_cancella_prenotazione_pagata_rimborso_e_penale(self):
        rif, b = self._prenota(self.slug, off=1, notti=2)
        self._paga(rif)
        st, out = self.chiama("POST", "/api/host/cancella", {"riferimento": rif},
                              atteso=200)
        self.assertEqual(out["stato"], "cancellata_host")
        self.assertEqual(out["riferimento"], rif)
        self.assertEqual(out["valuta"], "EUR")
        self.assertEqual(out["rimborso_cliente_cents"], b["totale_cents"])
        self.assertEqual(out["penale_host_cents"], b["totale_cents"] * 15 // 100)
        # effetti VERI: date liberate, payout tolto, escrow annullato
        self.assertEqual(self.sis.inventario.stato_giorno(self.slug,
                                                          _giorno(1))["unita_occupate"], 0)
        self.assertEqual(self.sis.payout.riepilogo(self.host_id), {})
        self.assertEqual((self.sis.garanzia.stato(rif) or {}).get("stato"), "annullato")


# ══════════════════════════════════════════════════════════════════════════════════
class TestRichiesteHost(_BaseHost):
    """richieste · richieste/approva · richieste/rifiuta (annuncio 'su richiesta')"""

    def setUp(self):
        super().setUp()
        self.slug_sr = "casa-su-richiesta"
        self._pubblica_extra(self.slug_sr, "Casa Su Richiesta",
                             cin="IT058091C2X5V0WXYZ",
                             modalita_prenotazione="su_richiesta")
        self.chiama("POST", "/api/host/disponibilita_range",
                    {"alloggio_id": self.slug_sr, "da": _giorno(0), "a": _giorno(20),
                     "unita_totali": 1, "prezzo_netto_cents": 20000}, atteso=200)

    def test_richieste_elenca_quelle_da_approvare(self):
        rif, b = self._prenota(self.slug_sr, off=2, notti=2)
        self.assertEqual(b["stato"], "in_attesa_host")
        self.assertNotIn("payment_url", b)
        st, out = self.chiama("GET", "/api/host/richieste", atteso=200)
        self.assertEqual(len(out["richieste"]), 1)
        rq = out["richieste"][0]
        self.assertEqual(rq["riferimento"], rif)
        self.assertEqual(rq["alloggio_id"], self.slug_sr)
        self.assertEqual((rq["check_in"], rq["check_out"]), (_giorno(2), _giorno(4)))
        self.assertEqual(rq["stato"], "in_attesa_host")

    def test_approva_conferma_e_tiene_le_date(self):
        rif, _b = self._prenota(self.slug_sr, off=2, notti=2)
        st, out = self.chiama("POST", "/api/host/richieste/approva",
                              {"riferimento": rif}, atteso=200)
        self.assertEqual(out["stato"], "approvata")
        self.assertEqual(out["riferimento"], rif)
        pren = out["prenotazione"]
        # approvata -> il cliente riceve un link di pagamento FRESCO (24h) e paga dall'email
        self.assertEqual(pren["stato"], "in_attesa_pagamento")
        self.assertTrue(pren["payment_url"].startswith("https://stripe.finto/"))
        self.assertEqual(
            (self.sis.pagamenti_pendenti.info(rif) or {}).get("stato"), "in_attesa")
        self.assertEqual(self.sis.inventario.stato_giorno(self.slug_sr,
                                                          _giorno(2))["unita_occupate"], 1)
        # la richiesta non e' piu' in coda (decisa una volta sola)
        st, dopo = self.chiama("GET", "/api/host/richieste", atteso=200)
        self.assertEqual(dopo["richieste"], [])

    def test_rifiuta_libera_le_date(self):
        rif, _b = self._prenota(self.slug_sr, off=5, notti=2)
        self.assertEqual(self.sis.inventario.stato_giorno(self.slug_sr,
                                                          _giorno(5))["unita_occupate"], 1)
        st, out = self.chiama("POST", "/api/host/richieste/rifiuta",
                              {"riferimento": rif}, atteso=200)
        self.assertEqual(out, {"stato": "rifiutata", "riferimento": rif})
        self.assertEqual(self.sis.inventario.stato_giorno(self.slug_sr,
                                                          _giorno(5))["unita_occupate"], 0)
        st, dopo = self.chiama("GET", "/api/host/richieste", atteso=200)
        self.assertEqual(dopo["richieste"], [])


# ══════════════════════════════════════════════════════════════════════════════════
class TestLegaleFiscaleHost(_BaseHost):
    """contratto_stato · accettazioni · riaccetta · dati_fiscali · dac7_stato"""

    def test_contratto_stato_in_regola_dopo_la_registrazione(self):
        st, out = self.chiama("GET", "/api/host/contratto_stato", atteso=200)
        self.assertEqual(out["contratto_corrente"], True)
        self.assertEqual(out["clausole_vessatorie"], True)
        self.assertEqual(out["privacy_corrente"], True)
        self.assertEqual(out["deve_riaccettare"], False)
        self.assertEqual(out["versione_corrente"], CONTRATTO_HOST_VERSIONE)
        self.assertEqual(out["versione_accettata"], CONTRATTO_HOST_VERSIONE)
        self.assertEqual(out["doc_sha256"], doc_sha256())

    def test_accettazioni_sono_prove_integre(self):
        st, out = self.chiama("GET", "/api/host/accettazioni", atteso=200)
        righe = out["accettazioni"]
        self.assertEqual(len(righe), 2)                # contratto host + privacy
        self.assertTrue(all(r["integra"] for r in righe), righe)
        self.assertEqual({r["documento"] for r in righe},
                         {"contratto_host", "privacy_gdpr"})
        contratto = [r for r in righe if r["documento"] == "contratto_host"][0]
        self.assertEqual(contratto["host_id"], self.host_id)
        self.assertEqual(contratto["versione"], CONTRATTO_HOST_VERSIONE)
        self.assertTrue(contratto["vessatorie"])
        self.assertTrue(contratto["firma"])

    def test_riaccetta_aggiunge_prove_nuove_append_only(self):
        st, out = self.chiama("POST", "/api/host/riaccetta",
                              {"accetta_termini": True, "accetta_clausole": True,
                               "accetta_privacy": True, "doc_sha256": doc_sha256(),
                               "lang": "it"}, atteso=200)
        self.assertTrue(out["ok"])
        self.assertTrue(out["accettazione"]["registrata"])
        self.assertTrue(out["accettazione"]["vessatorie"])
        st, elenco = self.chiama("GET", "/api/host/accettazioni", atteso=200)
        self.assertEqual(len(elenco["accettazioni"]), 4)   # le vecchie restano

    def test_dati_fiscali_completi_sbloccano_il_dac7(self):
        st, prima = self.chiama("GET", "/api/host/dac7_stato", atteso=200)
        self.assertEqual(sorted(prima["mancanti"]),
                         ["codice_fiscale/partita_iva", "iban", "indirizzo_fiscale", "paese"])
        self.assertIn("payout_bloccati", prima)
        self.assertEqual(prima["payout_fermi_cents"], 0)
        st, out = self.chiama("POST", "/api/host/dati_fiscali",
                              {"codice_fiscale": "RSSMRA80A01H501U",
                               "indirizzo_fiscale": "Via Roma 1, Roma",
                               "paese": "IT", "iban": "IT60X0542811101000000123456",
                               "tipo_soggetto": "persona_fisica"}, atteso=200)
        self.assertEqual(out["salvato"], True)
        self.assertEqual(out["mancanti"], [])
        self.assertEqual(out["payout_riprovati"], 0)
        st, dopo = self.chiama("GET", "/api/host/dac7_stato", atteso=200)
        self.assertEqual(dopo["mancanti"], [])
        self.assertEqual(dopo["payout_bloccati"], False)
        self.assertEqual(dopo["dati"]["paese"], "IT")
        self.assertEqual(dopo["dati"]["codice_fiscale"], "RSSMRA80A01H501U")


# ══════════════════════════════════════════════════════════════════════════════════
class TestCrescitaHost(_BaseHost):
    """referral · invito · invito/registra · invito/qualifica · link_diretto ·
    telegram_link · conversazioni"""

    def test_referral_viral_codice_e_link(self):
        from urllib.parse import quote
        st, out = self.chiama("GET", "/api/host/referral", atteso=200)
        self.assertTrue(out["codice"])
        self.assertEqual(out["link"],
                         "https://bookinvip.com/diventa-host.html?ref="
                         + quote(out["codice"]))
        self.assertIsInstance(out["credito_cents"], int)
        self.assertGreaterEqual(out["credito_cents"], 0)
        # idempotente: lo stesso host ha SEMPRE lo stesso codice
        st, di_nuovo = self.chiama("GET", "/api/host/referral", atteso=200)
        self.assertEqual(di_nuovo["codice"], out["codice"])

    def test_invito_registra_qualifica_paga_il_bonus(self):
        st, inv = self.chiama("GET", "/api/host/invito", atteso=200)
        self.assertTrue(inv["codice"])
        self.assertTrue(inv["link"].startswith("https://bookinvip.com/diventa-host.html?ref="))
        self.assertEqual(inv["crediti_cents"], 0)
        st, reg = self.chiama("POST", "/api/host/invito/registra",
                              {"codice": inv["codice"], "nuovo_host_id": "h_invitato"},
                              headers={}, atteso=201)
        self.assertEqual(reg, {"stato": "registrato"})
        st, qual = self.chiama("POST", "/api/host/invito/qualifica",
                               {"nuovo_host_id": "h_invitato"},
                               headers={"X-Admin-Key": "ak"}, atteso=200)
        self.assertEqual(qual, {"bonus_cents": 1000})
        st, dopo = self.chiama("GET", "/api/host/invito", atteso=200)
        self.assertEqual(dopo["crediti_cents"], 1000)   # il credito e' arrivato davvero

    def test_link_diretto_al_5_percento(self):
        st, out = self.chiama("GET", "/api/host/link_diretto", atteso=200)
        self.assertEqual(out["link_generale"], "https://bookinvip.com/?fonte=diretto")
        self.assertEqual(out["commissione_bps"], 500)
        self.assertEqual(out["commissione"], "5%")
        alloggi = {a["slug"]: a for a in out["alloggi"]}
        self.assertIn(self.slug, alloggi)
        self.assertEqual(alloggi[self.slug]["titolo"], "Casa Happy")
        self.assertEqual(alloggi[self.slug]["link"],
                         "https://bookinvip.com/?fonte=diretto&apri=" + self.slug)

    def test_telegram_link_firmato(self):
        st, out = self.chiama("GET", "/api/host/telegram_link", atteso=200)
        link = out["link"]
        self.assertTrue(link.startswith("https://t.me/BookinVipInfo_bot?start="), link)
        payload = link.split("start=", 1)[1]
        self.assertEqual(self.r._tg_verifica_payload(payload), self.host_id)

    def test_conversazioni_dell_host(self):
        st, vuote = self.chiama("GET", "/api/host/conversazioni", atteso=200)
        self.assertEqual(vuote, {"conversazioni": []})
        st, _ = self.r.gestisci("POST", "/api/messaggi", {}, json.dumps(
            {"prenotazione_id": "REF-CHAT-1", "guest_id": "ospite",
             "testo": "Benvenuto, il check-in e' dalle 15."}), self.tok)
        self.assertEqual(st, 201)
        st, out = self.chiama("GET", "/api/host/conversazioni", atteso=200)
        self.assertEqual(len(out["conversazioni"]), 1)
        c = out["conversazioni"][0]
        self.assertEqual(c["prenotazione_id"], "REF-CHAT-1")
        self.assertEqual(c["messaggi"], 1)
        self.assertEqual(c["ultimo_mittente"], self.host_id)
        self.assertEqual(c["ultimo_testo"], "Benvenuto, il check-in e' dalle 15.")


# ══════════════════════════════════════════════════════════════════════════════════
class TestStrumentiHost(_BaseHost):
    """geocode · prezzo_suggerito · seo_report · importa · stripe_link · carta_link ·
    carta_stato · kyc_stato · kyc_avvia"""

    def test_geocode_centra_la_mini_mappa(self):
        st, out = self.chiama("GET", "/api/host/geocode",
                              query={"citta": "Roma", "indirizzo": "Via del Corso 1",
                                     "paese": "IT"}, atteso=200)
        self.assertEqual(out, {"lat_micro": 41902782, "lon_micro": 12496366})

    def test_prezzo_suggerito_dinamico(self):
        st, out = self.chiama("GET", "/api/host/prezzo_suggerito",
                              query={"prezzo_base_cents": "30000",
                                     "occupazione_bps": "9000",
                                     "data": _giorno(3), "giorni": "1"}, atteso=200)
        self.assertEqual(out["base_cents"], 30000)
        self.assertIsInstance(out["prezzo_cents"], int)
        self.assertGreater(out["prezzo_cents"], 0)
        self.assertIsInstance(out["moltiplicatore_bps"], int)
        self.assertIsInstance(out["fattori"], dict)
        # coerenza interna: prezzo = base * moltiplicatore (aritmetica intera)
        self.assertEqual(out["prezzo_cents"],
                         max(1, 30000 * out["moltiplicatore_bps"] // 10000))

    def test_seo_report_dell_annuncio(self):
        st, out = self.chiama("GET", "/api/host/seo_report",
                              query={"alloggio_id": self.slug}, atteso=200)
        self.assertIsInstance(out["punteggio"], int)
        self.assertGreaterEqual(out["punteggio"], 0)
        self.assertIsInstance(out["sotto_punteggi"], dict)
        self.assertIsInstance(out["query_vincibili"], list)
        self.assertIsInstance(out["cosa_migliorare"], list)
        self.assertIsInstance(out["citazioni_pronte"], int)

    def test_importa_export_di_un_colosso(self):
        st, out = self.chiama("POST", "/api/host/importa", {
            "sorgente": "airbnb",
            "dati": [{"listing_id": "12345", "listing_title": "Loft sul Tevere",
                      "city": "Roma", "nightly_price": "82.00", "currency": "EUR",
                      "accommodates": 3, "description": "Loft con vista",
                      "amenities": ["wifi"], "picture_urls": [],
                      "calendar": [{"date": _giorno(50), "units": 1, "price": "90.00"},
                                   {"date": _giorno(51), "units": 1}]}]}, atteso=200)
        self.assertEqual(out["totale"], 1)
        self.assertEqual(out["importati"], 1)
        ris = out["risultati"][0]
        self.assertTrue(ris["ok"])
        self.assertEqual(ris["titolo"], "Loft sul Tevere")
        self.assertEqual(ris["errori"], [])
        self.assertEqual(ris["notti_applicate"], 2)
        self.assertEqual(ris["slug"], "loft-sul-tevere")
        # l'annuncio importato e' DAVVERO suo e ha i prezzi giusti
        self.assertEqual(self.sis.catalogo.host_di_alloggio(ris["slug"]), self.host_id)
        det = self.sis.catalogo.dettaglio_owner(ris["slug"])
        self.assertEqual(det["prezzo_notte_cents"], 8200)
        self.assertEqual(self.sis.inventario.stato_giorno(
            ris["slug"], _giorno(50))["prezzo_netto_cents"], 9000)

    def test_stripe_link_collega_il_conto_dell_host(self):
        st, out = self.chiama("GET", "/api/host/stripe_link", atteso=200)
        self.assertEqual(out["account_id"], "acct_finto_1")
        self.assertEqual(out["link"], "https://connect.stripe.finto/setup/acct_finto_1")
        self.assertEqual(out["pronto"], True)
        # l'account e' stato SALVATO sull'host (non solo restituito)
        self.assertEqual(self.sis.registro_host.info_host(self.host_id)["stripe_account_id"],
                         "acct_finto_1")

    def test_carta_link_e_stato(self):
        st, prima = self.chiama("GET", "/api/host/carta_stato", atteso=200)
        self.assertEqual(prima, {"carta_collegata": False, "attivo": True})
        st, out = self.chiama("POST", "/api/host/carta_link", atteso=200)
        self.assertEqual(out["url"], "https://carta.stripe.finto/sess")
        self.assertIsInstance(out["mandato"], str)
        self.assertTrue(out["mandato"])

    def test_kyc_stato_e_avvio_dormiente(self):
        st, out = self.chiama("GET", "/api/host/kyc_stato", atteso=200)
        self.assertEqual(out["configurato"], False)   # nessuna STRIPE_IDENTITY_KEY
        self.assertIsInstance(out["stato"], str)
        self.assertTrue(out["stato"])
        # avvio: 503 ONESTO e documentato finche' la chiave non c'e' (macchina pronta)
        st, out = self.chiama("POST", "/api/host/kyc_avvia", {}, atteso=503)
        self.assertEqual(out, {"errore": "identity_non_configurato"})


# ══════════════════════════════════════════════════════════════════════════════════
class TestCoperturaRotteHost(unittest.TestCase):
    """GUARDIA AUTO-APPLICANTE: le rotte host DICHIARATE qui sono ESATTAMENTE quelle
    cablate nel router. Una rotta /api/host/... nuova e non coperta = ROSSO."""

    def test_dichiarate_uguali_a_quelle_del_router(self):
        base = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(base, "fase83_server.py"), encoding="utf-8") as f:
            sorgente = f.read()
        trovate = set(re.findall(
            r'metodo == "(GET|POST)" and path == "(/api/host[^"]*)"', sorgente))
        dichiarate = set(ATTESI) | set(ESCLUSE)
        self.assertEqual(trovate - dichiarate, set(),
                         "rotte host del router SENZA copertura happy-path")
        self.assertEqual(dichiarate - trovate, set(),
                         "rotte dichiarate qui che il router NON espone piu'")
        self.assertEqual(len(ATTESI), 49, "la fetta host sono 49 rotte")


def _prove_del_modulo():
    """Quante prove ha questo modulo in tutto (solo le classi che usano la fixture host)."""
    import sys
    n = 0
    for oggetto in vars(sys.modules[__name__]).values():
        if isinstance(oggetto, type) and issubclass(oggetto, _BaseHost) \
                and oggetto is not _BaseHost:
            n += len([m for m in dir(oggetto) if m.startswith("test_")])
    return n


def tearDownModule():
    """TABELLA DI COPERTURA — e GUARDIA, non ornamento.

    DIFETTO TROVATO IN REVISIONE OSTILE (2026-07-28): questa funzione STAMPAVA la tabella e
    basta. Una rotta dichiarata in ATTESI ma mai esercitata compariva come «NON ESERCITATA»
    e il modulo restava VERDE lo stesso; idem per una rotta che rispondeva con uno stato
    DIFFORME da quello dichiarato. `TestCoperturaRotteHost` non copriva il buco: confronta i
    NOMI delle rotte col sorgente del router, non le esecuzioni. Provato: eseguendo una sola
    classe il riepilogo diceva «coperte 12/49» e unittest diceva OK.
    Ora, quando il modulo gira INTERO, «NON ESERCITATA» e «DIFFORME» fanno fallire.
    Su esecuzione PARZIALE (una sola classe) la copertura non si giudica: si stampa e basta.
    """
    import sys
    righe = ["", "TABELLA DI COPERTURA — fetta host (%d rotte)" % len(ATTESI),
             "%-6s %-34s %8s %8s  %s" % ("METODO", "ROTTA", "ATTESO", "OTTENUTO", "ESITO")]
    ok = 0
    guasti = []
    for chiave in sorted(ATTESI):
        atteso = ATTESI[chiave]
        ottenuto = OTTENUTI.get(chiave)
        esito = "OK" if ottenuto == atteso else ("NON ESERCITATA" if ottenuto is None
                                                 else "DIFFORME")
        ok += 1 if esito == "OK" else 0
        if esito != "OK":
            guasti.append("%s %s: %s (atteso %d, ottenuto %s)"
                          % (chiave[0], chiave[1], esito, atteso,
                             "-" if ottenuto is None else ottenuto))
        righe.append("%-6s %-34s %8d %8s  %s"
                     % (chiave[0], chiave[1], atteso,
                        "-" if ottenuto is None else ottenuto, esito))
    righe.append("coperte %d/%d — escluse %d" % (ok, len(ATTESI), len(ESCLUSE)))
    print("\n".join(righe), file=sys.stderr)
    totale = _prove_del_modulo()
    if PROVE_ESEGUITE[0] < totale:
        print("[happy_host] modulo parziale (%d/%d prove): copertura non giudicata"
              % (PROVE_ESEGUITE[0], totale), file=sys.stderr)
        return
    assert not guasti, "rotte host senza copertura reale: " + " | ".join(guasti)


if __name__ == "__main__":
    unittest.main(verbosity=2)
