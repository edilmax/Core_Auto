# -*- coding: utf-8 -*-
"""COLLAUDO PROFONDO DEI MODULI DORMIENTI — il rischio «costruito e dimenticato».

Il REGISTRO_INGEGNERIA sez. 2 elenca i moduli 🟡 «costruito ma SPENTO». Un modulo spento
non e' testato da nessuno *sul serio*: i suoi test unitari girano contro FINTI (catalogo
finto, concierge finto) che parlano un vocabolario inventato dal test. Il giorno che lo si
accende, la macchina vera gli passa dati veri — e ci si accorge che il pezzo pagato non
combacia.

Questo collaudo fa una cosa sola, per ogni modulo dormiente: **lo accende sulla macchina
VERA** (sistema reale, host registrato davvero, annuncio pubblicato davvero, prenotazione
pagata davvero) e ne cammina l'happy path pretendendo VALORI esatti — stato, chiavi, cifre
al centesimo, effetti sul DB su FILE (mai `:memory:`, i dormienti custodiscono denaro e
consensi) e l'integrazione con il resto del sistema.

MODULI COPERTI (13)
  ACCESI (rotte vive, qui camminate per la prima volta end-to-end):
    143 KYC host (Stripe Identity)       -> /api/host/kyc_stato · /api/host/kyc_avvia
    135 iCal BIDIREZIONALE               -> /api/host/ical (import) · /ical/<tok>.ics (export)
    133 split quote uguali (meta' pura)  -> /api/split/preview
  SPENTI (nessuna rotta / nessun cablaggio: accesi qui a mano sui dati veri):
    149 deposito cauzionale · 117 wishlist · 137 fedelta' guest · 139 chatbot guest
    123 web push · 67 coda intelligente · 104 gateway Asia · 107 traduzione annunci
    129 traduzione recensioni · 105 identity gate (VC W3C)

DIFETTI VERI TROVATI ACCENDENDOLI (4, corretti in questo giro, guardie qui sotto):
  1. fase139 `_prezzo`: diceva «Totale <prezzo_guest_cents>» — cioe' il SOGGIORNO, senza la
     TASSA DI SOGGIORNO. Sull'annuncio vero (300,00 + 10,00 di tassa) il chatbot annunciava
     300,00 EUR a un ospite che ne pagava 310,00: un prezzo pubblico piu' BASSO del vero.
     Nessun test lo vedeva: il concierge finto di test_fase139 non ha `totale_cents`.
     FIX: si mostra `totale_cents` (quello che l'ospite paga DAVVERO) con ripiego su
     `prezzo_guest_cents`; entrambe le cifre restano nel dict di risposta.
  2. fase139 `rispondi`/animali: cercava il servizio `"pet"`, vocabolario che il catalogo
     VERO (fase57.SERVIZI) non ha mai usato — il codice reale e' `animali_ammessi`. Su un
     annuncio che AMMETTE gli animali il chatbot rispondeva «Animali non ammessi».
     Il test unitario passava perche' il suo catalogo finto restituiva `["wifi", "pet"]`.
     FIX: si riconoscono entrambi i codici.
  3. fase129 `traduci_recensione`: riceveva la recensione nella forma di fase63
     (`testo = {"text": ..., "lang": ...}`) e, non essendo una stringa, la lasciava passare
     INTATTA con `tradotto_auto=False` — muta per sempre, anche col traduttore configurato.
     FIX: si accetta anche la forma reale (testo+lingua estratti dal dizionario).
  4. fase83 (handler `/ical/<tok>.ics`): passava a `_testo` un content-type che gia'
     conteneva il charset, e `_testo` ne aggiunge un altro -> l'unica risposta che leggono
     i parser di Booking/Airbnb usciva con `text/calendar; charset=utf-8; charset=utf-8`,
     parametro DUPLICATO (malformato per RFC 9110). FIX: si passa `"text/calendar"`.

VISTE ROSSE (regola aurea: nessun verde vale finche' non e' stato visto rosso)
  - I quattro difetti sopra: le guardie sono nate ROSSE sul codice del prodotto PRIMA del
    fix (`TestChatbotGuestSpento.test_prezzo_e_quello_che_l_ospite_paga_davvero` e
     `...test_llm_non_puo_toccare_i_numeri` (KeyError 'totale_cents'),
     `...test_animali_dal_vocabolario_vero_del_catalogo` («Animali non ammessi» su una casa
     che li ammette), `TestTraduzioneRecensioniSpenta` (2 test: la recensione restava un
     dizionario intradotto), `TestIcalBidirezionaleAcceso.test_export_ics_...` (charset
     doppio nell'header)).
  - Ogni ALTRA guardia e' stata provata rompendo a RUNTIME il motore che sorveglia, una per
    volta e poi ripristinato: 27 mutazioni, 33 esecuzioni mirate, **33 ROSSE, 0 mutanti
    sopravvissuti**, suite di nuovo verde dopo il ripristino. In sintesi:
      fase143 `registra_avvio`/`conferma`/`_TRANS` · fase83 `_identity_key` (finta chiave)
      fase82  `sincronizza` · fase135 `genera_ical` · fase83 `_ical_export` (firma ignorata)
      fase133 `riparti_uguale` (`base+1` a tutti) · fase67 `libera` · fase58 `blocca`
      fase149 `cattura_danno` / tetto autorizzato / gate PSP
      fase117 `aggiungi` (no-op che dice True) · fase137 `accredita` + `livello_per_punti`
      fase139 `_prezzo` (senza tassa) + `quote_token` inventato + vocabolario 'pet'
      fase123 gate VAPID + `disiscrivi` · fase104 `costruisci_params_asia` + gate chiave
      fase107 cache + isolamento · fase129 forma-stringa · fase105 `_hash` costante

Stdlib pura, zero rete (Stripe/Identity/push/traduttore finti e INIETTATI), DB su file
temporanei, deterministico.
"""
import datetime
import http.client
import json
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest

import fase85_pagamenti_stripe as _stripe
import fase143_kyc_host as _kyc_mod
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WHSEC = "whsec_dormienti"
SLUG = "casa-dormiente"
CIN_IT = "IT058091C2X5V0ABCD"

# ── i conti attesi, al centesimo (interi, mai float) ────────────────────────────
PREZZO_NOTTE = 15000
NOTTI = 2
PARTY = 2
TASSA_PP_NOTTE = 250
NETTO = PREZZO_NOTTE * NOTTI                      # 30000  soggiorno
TASSA = TASSA_PP_NOTTE * NOTTI * PARTY            #  1000  tassa di soggiorno
TOTALE = NETTO + TASSA                            # 31000  quello che l'ospite paga DAVVERO
COMMISSIONE = 3000                                # 10% di 30000 (marketplace, a carico host)
COSTO_CARTA = 930                                 # 3% di 31000 (a carico host)
NETTO_HOST = NETTO - COMMISSIONE - COSTO_CARTA    # 26070


def _fake_stripe_fetch(url, body, headers):
    """Checkout Session finta: nessuna rete, id/url deterministici per chiamata."""
    import secrets
    return {"url": "https://stripe.finto/" + secrets.token_hex(4),
            "id": "cs_" + secrets.token_hex(8)}


def _porta_libera():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class _Posta:
    """Provider email finto: registra, non spedisce."""

    def __init__(self):
        self.inviate = []

    def invia(self, dest, oggetto, html):
        self.inviate.append((dest, oggetto, html))
        return True


class _BaseDormienti(unittest.TestCase):
    """Macchina VERA: sistema + router + host registrato + annuncio pubblicato + date aperte.
    Tutti i database su FILE (i dormienti custodiscono denaro, consensi e prove)."""

    def setUp(self):
        self._env0 = {k: os.environ.get(k) for k in
                      ("UPLOAD_DIR", "TASSE_SOGGIORNO", "PAGA_STRUTTURA_ATTIVO",
                       "STRIPE_IDENTITY_KEY")}
        self.d = tempfile.mkdtemp(prefix="dormienti_")
        os.environ["UPLOAD_DIR"] = self.d + "/uploads"
        os.environ["TASSE_SOGGIORNO"] = ""            # la regola la detta l'annuncio
        os.environ["PAGA_STRUTTURA_ATTIVO"] = "0"
        os.environ.pop("STRIPE_IDENTITY_KEY", None)   # KYC: spento finche' non lo accendo io
        self._fetch0 = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_stripe_fetch)

        d = self.d
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"D" * 32, con_registrazione_host=True,
            db_catalogo=d + "/c.db", db_inventario=d + "/i.db", db_registro_host=d + "/r.db",
            db_accettazioni=d + "/a.db", db_pendenti=d + "/p.db", db_payout=d + "/po.db",
            db_garanzia=d + "/g.db", db_finanza=d + "/f.db", db_messaggi=d + "/m.db",
            db_checkin=d + "/ck.db", db_split=d + "/sp.db", db_tassa_comunale=d + "/t.db",
            db_recensioni=d + "/rec.db", db_viral=d + "/v.db", db_domanda=d + "/dom.db",
            db_kyc=d + "/kyc.db", db_coda=d + "/coda.db",
            commissione_bps=1000, psp_bps=300, stripe_secret_key="sk",
            stripe_webhook_secret=WHSEC, stripe_success_url="https://x/ok",
            stripe_cancel_url="https://x/ko"))
        self.posta = _Posta()
        self.sis.email_provider = self.posta
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        if getattr(self.sis, "connect", None) is not None:
            self.sis.connect.trasferisci = lambda *a, **k: "tr_finto"     # mai rete

        s, c = self.g("POST", "/api/host/registrazione", {
            "email": "host@dormienti.it", "password": "password1", "accetta_termini": True,
            "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
            "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.host_id = c["host_id"]
        self.tk = {"X-Host-Token": c["token"]}
        self.admin = {"X-Admin-Key": "ak"}

        s, p = self.g("POST", "/api/host/pubblica", {
            "slug": SLUG, "titolo": "Casa Dormiente", "citta": "Roma", "paese": "IT",
            "cin": CIN_IT, "descrizione": "Casa con giardino e cane benvenuto",
            "prezzo_notte_cents": PREZZO_NOTTE, "capacita": 4,
            "tassa_pp_notte_cents": TASSA_PP_NOTTE,
            "servizi": ["wifi", "animali_ammessi"], "immagini": []}, self.tk)
        self.assertEqual(s, 201, p)

        oggi = datetime.date.today()
        self.ci = (oggi + datetime.timedelta(days=40)).isoformat()
        self.co = (oggi + datetime.timedelta(days=40 + NOTTI)).isoformat()
        s, disp = self.g("POST", "/api/host/disponibilita_range", {
            "alloggio_id": SLUG, "da": (oggi + datetime.timedelta(days=30)).isoformat(),
            "a": (oggi + datetime.timedelta(days=70)).isoformat(),
            "unita_totali": 5, "prezzo_netto_cents": PREZZO_NOTTE}, self.tk)
        self.assertEqual(s, 200, disp)

    def tearDown(self):
        _stripe.ProviderStripe._fetch_reale = self._fetch0
        for k, v in self._env0.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.d, ignore_errors=True)

    # ── utilita' ────────────────────────────────────────────────────────────────
    def g(self, metodo, path, body=None, headers=None, query=None):
        return self.r.gestisci(metodo, path, query or {},
                               json.dumps(body) if body is not None else None,
                               headers or {})

    def quote(self, **extra):
        corpo = {"alloggio_id": SLUG, "check_in": self.ci, "check_out": self.co,
                 "party": PARTY}
        corpo.update(extra)
        return self.g("POST", "/api/concierge/quote", corpo)

    def prenotazione_pagata(self, email="ospite@dormienti.it"):
        """(riferimento, voucher_token) di una prenotazione VERAMENTE pagata."""
        s, q = self.quote()
        self.assertEqual(s, 200, q)
        self.assertEqual(q["totale_cents"], TOTALE, "il conto atteso e' cambiato")
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": email, "lang": "it"})
        self.assertEqual(s, 201, b)
        grezzo = json.dumps({"type": "checkout.session.completed",
                             "data": {"object": {"id": "cs_dormienti",
                                                 "metadata": {"riferimento":
                                                              b["riferimento"]}}}})
        firma = firma_di_test(grezzo, WHSEC, int(time.time()))
        s, w = self.r.gestisci("POST", "/api/payments/webhook", {}, grezzo,
                               {"Stripe-Signature": firma})
        self.assertEqual(s, 200, w)
        self.assertEqual(self.sis.pagamenti_pendenti.info(b["riferimento"])["stato"],
                         "pagato")
        return b["riferimento"], b["voucher_token"]


# ══════════════════════════════════════════════════════════════════════════════
# 1) fase143 — KYC HOST: acceso dalla chiave, camminato dalle rotte vere
# ══════════════════════════════════════════════════════════════════════════════
class TestKycHostAcceso(_BaseDormienti):
    """Il modulo e' cablato (bootstrap + 2 rotte) ma GATED da STRIPE_IDENTITY_KEY.
    Qui la chiave si accende e il provider si INIETTA (nessuna rete)."""

    def setUp(self):
        super().setUp()
        self._crea0 = _kyc_mod.stripe_identity_crea
        self._stato0 = _kyc_mod.stripe_identity_stato
        self.chiamate = []
        self.risposta_provider = "processing"

        def _crea(chiave, host_id, return_url, **kw):
            self.chiamate.append((chiave, host_id, return_url))
            return {"id": "vs_finta_1", "url": "https://verify.stripe.finta/vs_finta_1"}

        _kyc_mod.stripe_identity_crea = _crea
        _kyc_mod.stripe_identity_stato = lambda chiave, sid, **kw: self.risposta_provider

    def tearDown(self):
        _kyc_mod.stripe_identity_crea = self._crea0
        _kyc_mod.stripe_identity_stato = self._stato0
        super().tearDown()

    def test_spento_senza_chiave_lo_dice_e_non_finge(self):
        """Senza la chiave: stato leggibile e onesto, avvio rifiutato con 503 (mai un finto ok)."""
        s, c = self.g("GET", "/api/host/kyc_stato", None, self.tk)
        self.assertEqual(s, 200, c)
        self.assertEqual(c, {"configurato": False, "stato": "non_avviata"})
        s, c = self.g("POST", "/api/host/kyc_avvia", {}, self.tk)
        self.assertEqual(s, 503)
        self.assertEqual(c, {"errore": "identity_non_configurato"})
        self.assertEqual(self.sis.kyc.stato(self.host_id), "non_avviata")

    def test_acceso_avvia_e_scrive_su_file(self):
        """Con la chiave: l'avvio crea la sessione hosted e il registro passa a 'in_corso'
        SU FILE (sopravvive al riavvio: e' una prova di conformita', non un dato volatile)."""
        os.environ["STRIPE_IDENTITY_KEY"] = "sk_identity_finta"
        s, c = self.g("POST", "/api/host/kyc_avvia", {}, self.tk)
        self.assertEqual(s, 200, c)
        self.assertEqual(c, {"ok": True, "stato": "in_corso",
                             "url": "https://verify.stripe.finta/vs_finta_1"})
        self.assertEqual(len(self.chiamate), 1)
        self.assertEqual(self.chiamate[0][0], "sk_identity_finta")
        self.assertEqual(self.chiamate[0][1], self.host_id)       # l'host VERO, non un id finto
        self.assertEqual(self.chiamate[0][2],
                         "https://bookinvip.com/host.html?identity=fatto")
        # effetto sul DB, riletto da una connessione NUOVA sul file
        self.assertEqual(self.sis.kyc.stato(self.host_id), "in_corso")
        self.assertEqual(self.sis.kyc.sessione(self.host_id), "vs_finta_1")
        riaperto = _kyc_mod.crea_kyc_host(self.d + "/kyc.db")
        self.assertEqual(riaperto.riferimento(self.host_id)["stato"], "in_corso")
        self.assertEqual(riaperto.riferimento(self.host_id)["session_ref"], "vs_finta_1")
        # ri-avviare mentre e' in corso non apre una seconda sessione
        s, c = self.g("POST", "/api/host/kyc_avvia", {}, self.tk)
        self.assertEqual(s, 409)
        self.assertEqual(c, {"errore": "gia_in_corso", "stato": "in_corso"})
        self.assertEqual(len(self.chiamate), 2)                   # chiamato, ma non registrato
        self.assertEqual(self.sis.kyc.sessione(self.host_id), "vs_finta_1")

    def test_sync_col_provider_porta_a_verificato_e_si_vede_in_admin(self):
        """Il provider dice 'verified' -> il registro transita e l'ADMIN lo vede: e' il pezzo
        che rende il modulo utile (la colonna 'identity' della dashboard Verifiche)."""
        os.environ["STRIPE_IDENTITY_KEY"] = "sk_identity_finta"
        s, _ = self.g("POST", "/api/host/kyc_avvia", {}, self.tk)
        self.assertEqual(s, 200)
        s, c = self.g("GET", "/api/host/kyc_stato", None, self.tk)
        self.assertEqual(c, {"configurato": True, "stato": "in_corso"})
        self.risposta_provider = "verified"
        s, c = self.g("GET", "/api/host/kyc_stato", None, self.tk)
        self.assertEqual(s, 200, c)
        self.assertEqual(c, {"configurato": True, "stato": "verificato"})
        self.assertTrue(self.sis.kyc.verificato(self.host_id))
        s, adm = self.g("GET", "/api/admin/verifiche", None, self.admin)
        self.assertEqual(s, 200, adm)
        voce = [h for h in adm["host"] if h["host_id"] == self.host_id]
        self.assertEqual(len(voce), 1, "l'host vero non compare nella dashboard verifiche")
        self.assertEqual(voce[0]["documenti"]["identity"], "verificato")

    def test_respinto_e_ritentabile(self):
        """'canceled' dal provider -> respinto, e l'host puo' RIPROVARE (non e' un vicolo cieco)."""
        os.environ["STRIPE_IDENTITY_KEY"] = "sk_identity_finta"
        self.g("POST", "/api/host/kyc_avvia", {}, self.tk)
        self.risposta_provider = "canceled"
        s, c = self.g("GET", "/api/host/kyc_stato", None, self.tk)
        self.assertEqual(c, {"configurato": True, "stato": "respinto"})
        self.risposta_provider = "processing"
        s, c = self.g("POST", "/api/host/kyc_avvia", {}, self.tk)
        self.assertEqual(s, 200, c)
        self.assertEqual(c["stato"], "in_corso")
        self.assertEqual(self.sis.kyc.stato(self.host_id), "in_corso")


# ══════════════════════════════════════════════════════════════════════════════
# 2) fase135 — iCal BIDIREZIONALE: import da un OTA -> export verso l'altro
#    (contro un server HTTP VERO: il feed .ics vive solo nell'handler, non nel router)
# ══════════════════════════════════════════════════════════════════════════════
_ICS_ESTERNO = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Airbnb//IT\r\n"
    "BEGIN:VEVENT\r\nUID:airbnb-1\r\nDTSTART;VALUE=DATE:%s\r\nDTEND;VALUE=DATE:%s\r\n"
    "SUMMARY:Reserved\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")


class TestIcalBidirezionaleAcceso(_BaseDormienti):
    """fase82 importa, fase135 esporta: il cerchio si chiude solo se una data presa su
    Airbnb esce nel NOSTRO feed .ics, quello che Booking legge."""

    def setUp(self):
        super().setUp()
        oggi = datetime.date.today()
        self.b_da = oggi + datetime.timedelta(days=45)
        self.b_a = oggi + datetime.timedelta(days=47)          # DTEND esclusivo: 2 notti
        self.ics = _ICS_ESTERNO % (self.b_da.strftime("%Y%m%d"), self.b_a.strftime("%Y%m%d"))
        # ZERO RETE: `servi` avvia i giri giornalieri veri (Guardiano -> Stripe, marca
        # temporale -> Autorita' RFC 3161). Un collaudo non deve toccare servizi esterni.
        import fase186_guardiano as _guard
        self._scan0 = _guard.scansiona
        _guard.scansiona = lambda *a, **k: {"pulito": True, "conta": 0, "anomalie": {}}
        self.sis.marche = None
        self.porta = _porta_libera()
        import fase83_server
        self.t = threading.Thread(
            target=fase83_server.servi,
            kwargs=dict(sistema=self.sis, host="127.0.0.1", porta=self.porta,
                        cartella_statica="deploy", host_key="hk", admin_key="ak",
                        base_url="http://127.0.0.1:%d" % self.porta),
            daemon=True)
        self.t.start()
        for _ in range(200):
            try:
                if self._grezzo("GET", "/robots.txt")[0] == 200:
                    break
            except Exception:
                pass
            time.sleep(0.03)

    def tearDown(self):
        import fase186_guardiano as _guard
        _guard.scansiona = self._scan0
        super().tearDown()

    def _grezzo(self, metodo, path):
        c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=6)
        c.request(metodo, path)
        r = c.getresponse()
        dati = r.read().decode("utf-8", "replace")
        hd = {k.lower(): v for k, v in r.getheaders()}
        c.close()
        return r.status, hd, dati

    def test_import_ota_blocca_davvero_le_date(self):
        """POST /api/host/ical -> le date dell'OTA diventano non prenotabili DA NOI."""
        s, e = self.g("POST", "/api/host/ical",
                      {"alloggio_id": SLUG, "ical": self.ics}, self.tk)
        self.assertEqual(s, 200, e)
        self.assertEqual(e, {"eventi": 1, "giorni_bloccati": 2})
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": SLUG, "check_in": self.b_da.isoformat(),
                       "check_out": self.b_a.isoformat(), "party": PARTY})
        self.assertEqual(s, 409, q)
        self.assertEqual(q, {"errore": "non_disponibile"})
        # il giorno DOPO la finestra importata resta vendibile (nessun off-by-one)
        s, q = self.quote()
        self.assertEqual(s, 200, q)
        self.assertEqual(q["totale_cents"], TOTALE)

    def test_export_ics_ripubblica_le_date_bloccate(self):
        """/api/host/ical_link -> GET /ical/<token>.ics sul server VERO: un solo VEVENT,
        con le date esatte importate dall'altro canale (DTEND esclusivo, semi-aperto)."""
        s, e = self.g("POST", "/api/host/ical",
                      {"alloggio_id": SLUG, "ical": self.ics}, self.tk)
        self.assertEqual(s, 200, e)
        s, link = self.g("GET", "/api/host/ical_link", None, self.tk,
                         query={"alloggio": SLUG})
        self.assertEqual(s, 200, link)
        self.assertIn("/ical/", link["url"])
        self.assertTrue(link["url"].endswith(".ics"), link["url"])
        percorso = "/ical/" + link["url"].split("/ical/", 1)[1]
        st, hd, corpo = self._grezzo("GET", percorso)
        self.assertEqual(st, 200)
        self.assertEqual(hd.get("content-type"), "text/calendar; charset=utf-8")
        self.assertTrue(corpo.startswith("BEGIN:VCALENDAR\r\n"), repr(corpo[:40]))
        self.assertEqual(corpo.count("BEGIN:VEVENT"), 1, corpo)
        self.assertIn("DTSTART;VALUE=DATE:" + self.b_da.strftime("%Y%m%d"), corpo)
        self.assertIn("DTEND;VALUE=DATE:" + self.b_a.strftime("%Y%m%d"), corpo)
        self.assertIn("TRANSP:OPAQUE", corpo)
        self.assertTrue(corpo.rstrip().endswith("END:VCALENDAR"))

    def test_feed_di_un_token_non_firmato_non_esiste(self):
        """Il feed e' pubblico: senza firma valida NON deve dire nulla dell'alloggio."""
        st, _hd, corpo = self._grezzo("GET", "/ical/token-inventato.ics")
        self.assertEqual(st, 404)
        self.assertNotIn("VCALENDAR", corpo)


# ══════════════════════════════════════════════════════════════════════════════
# 3) fase133 — SPLIT IN QUOTE UGUALI: meta' ACCESA (rotta) + meta' SPENTA (registro)
# ══════════════════════════════════════════════════════════════════════════════
class TestSplitQuoteUguali(_BaseDormienti):

    def test_rotta_preview_conserva_il_totale_vero(self):
        """POST /api/split/preview sul TOTALE vero della prenotazione: le quote sommano
        ESATTAMENTE (nessun centesimo creato o perso) e la differenza max e' 1 cent."""
        s, c = self.g("POST", "/api/split/preview", {"totale_cents": TOTALE, "n": 3})
        self.assertEqual(s, 200, c)
        self.assertEqual(c["quote"], [10334, 10333, 10333])
        self.assertEqual(sum(c["quote"]), TOTALE)
        self.assertEqual(c["totale_cents"], TOTALE)
        self.assertEqual(c["n"], 3)
        self.assertEqual(c["per_persona_min_cents"], 10333)
        self.assertEqual(c["per_persona_max_cents"], 10334)
        self.assertEqual(c["money_unit"], "cents_integer")
        s, c = self.g("POST", "/api/split/preview", {"totale_cents": TOTALE, "n": 0})
        self.assertEqual(s, 400)
        self.assertEqual(c, {"errore": "parametri_non_validi"})

    def test_registro_quote_spento_ma_funziona_su_file(self):
        """La meta' DUREVOLE di fase133 (crea_gruppo/paga/stato) non ha rotte: accesa a mano
        sul riferimento VERO della prenotazione, tiene il conto fino al saldo."""
        from fase133_split_quote_uguali import crea_split_quote
        rif, _v = self.prenotazione_pagata()
        reg = crea_split_quote(self.d + "/split133.db")
        reg.inizializza_schema()
        self.assertTrue(reg.crea_gruppo(rif, TOTALE, ["anna", "bruno", "carla"]))
        st = reg.stato(rif)
        self.assertEqual(st["quote"], {"anna": 10334, "bruno": 10333, "carla": 10333})
        self.assertEqual(st["totale_cents"], TOTALE)
        self.assertEqual(st["pagato_cents"], 0)
        self.assertFalse(st["completato"])
        self.assertEqual(st["mancanti"], ["anna", "bruno", "carla"])
        self.assertTrue(reg.paga(rif, "anna"))
        self.assertFalse(reg.paga(rif, "anna"))               # due volte non paga doppio
        self.assertEqual(reg.stato(rif)["pagato_cents"], 10334)
        self.assertTrue(reg.paga(rif, "bruno"))
        self.assertTrue(reg.paga(rif, "carla"))
        st = reg.stato(rif)
        self.assertEqual(st["pagato_cents"], TOTALE)
        self.assertTrue(st["completato"])
        self.assertEqual(st["mancanti"], [])
        riaperto = crea_split_quote(self.d + "/split133.db")   # sopravvive al riavvio
        self.assertEqual(riaperto.stato(rif)["pagato_cents"], TOTALE)


# ══════════════════════════════════════════════════════════════════════════════
# 4) fase67 — CODA INTELLIGENTE: motore in sistema, ZERO rotte
# ══════════════════════════════════════════════════════════════════════════════
class TestCodaIntelligenteSpenta(_BaseDormienti):

    def test_il_gestore_e_su_file_non_in_ram(self):
        """Custodisce DEPOSITI: il percorso deve essere un file (`:memory:` = soldi persi
        al riavvio). Il sistema lo costruisce gia' cosi'."""
        self.assertIsNotNone(self.sis.coda)
        self.assertTrue(os.path.isfile(self.d + "/coda.db"), "coda.db non esiste su disco")

    def test_ciclo_fifo_e_prenotazione_vera(self):
        """Iscrizione -> l'host libera -> il PRIMO riceve l'offerta -> accettando prenota
        DAVVERO sull'inventario reale (le date spariscono dalla vendita)."""
        coda = self.sis.coda
        e1 = coda.iscrivi(SLUG, self.ci, self.co, "ospite-1")
        e2 = coda.iscrivi(SLUG, self.ci, self.co, "ospite-2")
        self.assertTrue(e1.ok)
        self.assertEqual(e1.posizione, 1)
        self.assertEqual(e2.posizione, 2)
        self.assertTrue(coda.iscrivi(SLUG, self.ci, self.co, "ospite-1").idempotente)
        off = coda.libera(SLUG, self.ci, self.co)
        self.assertEqual(off.esito, "offerto")
        self.assertEqual(off.ospite_id, "ospite-1")            # FIFO, non a caso
        prenotati = []

        def _prenota(alloggio, ci, co, ospite):
            prenotati.append((alloggio, ci, co, ospite))
            return self.sis.inventario.blocca(alloggio, ci, co,
                                              idem_key="coda:" + ospite) is not None

        acc = coda.accetta(SLUG, self.ci, self.co, "ospite-1", prenota=_prenota)
        self.assertTrue(acc.ok, acc.motivo)
        self.assertEqual(prenotati, [(SLUG, self.ci, self.co, "ospite-1")])
        # effetto REALE: quelle notti non sono piu' vendibili (unita 5 -> il blocco e' 1 unita')
        st = coda.stato_coda(SLUG, self.ci, self.co)
        self.assertEqual([(r["ospite_id"], r["stato"]) for r in st],
                         [("ospite-1", "confermato"), ("ospite-2", "in_coda")])
        self.assertEqual(st[0]["deposito_cents"], 2000)
        self.assertEqual(st[0]["voucher_cents"], 2500)   # deposito + bonus anti-frustrazione
        cal = self.sis.inventario.calendario(SLUG, self.ci, self.co)
        self.assertEqual([g["unita_occupate"] for g in cal], [1] * NOTTI)


# ══════════════════════════════════════════════════════════════════════════════
# 5) fase149 — DEPOSITO CAUZIONALE: nessuna rotta, nessun campo di config
# ══════════════════════════════════════════════════════════════════════════════
class TestDepositoCauzionaleSpento(_BaseDormienti):

    def _acceso(self):
        from fase149_deposito_cauzionale import crea_deposito_cauzionale
        self.psp = []
        dep = crea_deposito_cauzionale(
            self.d + "/cauzione.db",
            capture=lambda ref, imp: (self.psp.append(("capture", ref, imp)), True)[1],
            release=lambda ref: (self.psp.append(("release", ref)), True)[1])
        dep.inizializza_schema()
        return dep

    def test_hold_su_prenotazione_vera_poi_danno_e_conservazione(self):
        """Pre-autorizzazione su una prenotazione VERAMENTE pagata, danno catturato dal PSP,
        resto rilasciato: catturato + rilasciato == autorizzato, sempre."""
        rif, _v = self.prenotazione_pagata()
        dep = self._acceso()
        self.assertTrue(dep.autorizza(rif, "pi_" + rif, 20000))
        st = dep.stato(rif)
        self.assertEqual(st, {"psp_ref": "pi_" + rif, "autorizzato_cents": 20000,
                              "catturato_cents": 0, "rilasciato_cents": 20000,
                              "stato": "autorizzato"})
        self.assertEqual(self.psp, [])                      # l'hold NON addebita nulla
        self.assertTrue(dep.cattura_danno(rif, 7500))
        self.assertEqual(self.psp, [("capture", "pi_" + rif, 7500)])
        st = dep.stato(rif)
        self.assertEqual(st["catturato_cents"], 7500)
        self.assertEqual(st["rilasciato_cents"], 12500)
        self.assertEqual(st["catturato_cents"] + st["rilasciato_cents"],
                         st["autorizzato_cents"])
        self.assertEqual(st["stato"], "catturato_parziale")
        self.assertTrue(dep.rilascia(rif))
        self.assertEqual(dep.stato(rif)["stato"], "rilasciato")
        self.assertEqual(self.psp[-1], ("release", "pi_" + rif))

    def test_mai_catturare_piu_dell_autorizzato_e_mai_due_volte(self):
        """Il tetto e' la garanzia dell'ospite: sopra l'autorizzato si rifiuta, senza toccare
        il PSP; e una cauzione gia' chiusa non si riapre."""
        rif, _v = self.prenotazione_pagata()
        dep = self._acceso()
        dep.autorizza(rif, "pi_x", 20000)
        self.assertFalse(dep.cattura_danno(rif, 20001))
        self.assertEqual(self.psp, [])
        self.assertEqual(dep.stato(rif)["stato"], "autorizzato")
        self.assertTrue(dep.cattura_danno(rif, 20000))       # il tetto esatto passa
        self.assertFalse(dep.cattura_danno(rif, 1))          # non si cattura due volte
        self.assertEqual(dep.stato(rif)["catturato_cents"], 20000)
        self.assertEqual(dep.stato(rif)["rilasciato_cents"], 0)

    def test_senza_psp_non_cattura_nulla(self):
        """GATED: senza provider carta configurato non si finge un incasso."""
        from fase149_deposito_cauzionale import crea_deposito_cauzionale
        dep = crea_deposito_cauzionale(self.d + "/cauzione2.db")
        dep.inizializza_schema()
        self.assertTrue(dep.autorizza("rif-1", "pi_y", 5000))
        self.assertFalse(dep.cattura_danno("rif-1", 100))
        self.assertEqual(dep.stato("rif-1")["stato"], "autorizzato")


# ══════════════════════════════════════════════════════════════════════════════
# 6) fase117 — WISHLIST: nessuna rotta (serve identita' ospite)
# ══════════════════════════════════════════════════════════════════════════════
class TestWishlistSpenta(_BaseDormienti):

    def test_preferiti_su_annunci_veri_e_persistenti(self):
        from fase117_wishlist import crea_wishlist
        w = crea_wishlist(self.d + "/wishlist.db")
        w.inizializza_schema()
        self.assertTrue(w.aggiungi("ospite@dormienti.it", SLUG))
        self.assertTrue(w.aggiungi("ospite@dormienti.it", SLUG))     # idempotente
        self.assertEqual(w.elenca("ospite@dormienti.it"), [SLUG])
        self.assertTrue(w.contiene("ospite@dormienti.it", SLUG))
        self.assertEqual(w.elenca("altro@x.it"), [])                 # niente lista altrui
        # integrazione: ogni slug salvato e' un annuncio VERO e mostrabile
        for slug in w.elenca("ospite@dormienti.it"):
            s, d = self.g("GET", "/api/catalogo/" + slug)
            self.assertEqual(s, 200, d)
            self.assertEqual(d["slug"], SLUG)
            self.assertEqual(d["prezzo_notte_cents"], PREZZO_NOTTE)
        riaperta = crea_wishlist(self.d + "/wishlist.db")
        self.assertEqual(riaperta.elenca("ospite@dormienti.it"), [SLUG])
        self.assertTrue(riaperta.rimuovi("ospite@dormienti.it", SLUG))
        self.assertFalse(riaperta.rimuovi("ospite@dormienti.it", SLUG))
        self.assertEqual(riaperta.elenca("ospite@dormienti.it"), [])

    def test_liste_nominate_separate(self):
        from fase117_wishlist import crea_wishlist
        w = crea_wishlist(self.d + "/wishlist2.db")
        w.inizializza_schema()
        w.aggiungi("g1", SLUG, lista="Estate")
        w.aggiungi("g1", SLUG, lista="Inverno")
        self.assertEqual(w.liste("g1"), ["Estate", "Inverno"])
        self.assertEqual(w.elenca("g1", lista="Estate"), [SLUG])
        self.assertEqual(w.elenca("g1"), [])                          # lista default vuota


# ══════════════════════════════════════════════════════════════════════════════
# 7) fase137 — FEDELTA' GUEST: nessuna rotta, nessun aggancio al soggiorno
# ══════════════════════════════════════════════════════════════════════════════
class TestFedeltaGuestSpenta(_BaseDormienti):

    def test_punti_dal_totale_vero_idempotenti_e_riscattabili(self):
        from fase137_fedelta_guest import crea_fedelta_guest
        rif, _v = self.prenotazione_pagata()
        f = crea_fedelta_guest(self.d + "/fedelta.db")
        f.inizializza_schema()
        punti = f.accredita(rif, "ospite@dormienti.it", TOTALE)
        self.assertEqual(punti, TOTALE // 100)                        # 310 punti su 310,00 EUR
        self.assertEqual(f.accredita(rif, "ospite@dormienti.it", TOTALE), 0,
                         "lo stesso soggiorno non puo' pagare due volte")
        saldo = f.saldo("ospite@dormienti.it")
        self.assertEqual(saldo, {"punti": 310, "punti_totali": 310, "livello": "bronze",
                                 "moltiplicatore_bps": 10000, "valore_cents": 310})
        self.assertEqual(f.riscatta("ospite@dormienti.it", 310), 310)
        self.assertEqual(f.saldo("ospite@dormienti.it")["punti"], 0)
        self.assertEqual(f.riscatta("ospite@dormienti.it", 1), 0)     # saldo vuoto: zero
        self.assertEqual(f.saldo("ospite@dormienti.it")["punti_totali"], 310)  # livello resta

    def test_livello_sale_e_moltiplica(self):
        """Il moltiplicatore e' quello del livello CORRENTE: silver (>=500 punti) da' +10%."""
        from fase137_fedelta_guest import crea_fedelta_guest
        f = crea_fedelta_guest(self.d + "/fedelta2.db")
        f.inizializza_schema()
        self.assertEqual(f.accredita("p1", "g", 60000), 600)          # bronze 1.00x
        self.assertEqual(f.saldo("g")["livello"], "silver")
        self.assertEqual(f.accredita("p2", "g", 10000), 110)          # silver 1.10x
        self.assertEqual(f.saldo("g")["punti_totali"], 710)


# ══════════════════════════════════════════════════════════════════════════════
# 8) fase139 — CHATBOT GUEST: nessuna rotta; qui parla col CATALOGO e col CONCIERGE veri
# ══════════════════════════════════════════════════════════════════════════════
class TestChatbotGuestSpento(_BaseDormienti):

    def _bot(self, llm=None):
        from fase139_chatbot_guest import crea_chatbot_guest
        return crea_chatbot_guest(self.sis.catalogo, self.sis.concierge, llm=llm)

    def test_prezzo_e_quello_che_l_ospite_paga_davvero(self):
        """DIFETTO TROVATO: diceva «Totale» mostrando il solo soggiorno, senza la tassa di
        soggiorno -> prezzo pubblico piu' BASSO del vero. Deve dire il TOTALE."""
        s, q = self.quote()
        self.assertEqual(s, 200, q)
        self.assertEqual(q["prezzo_guest_cents"], NETTO)
        self.assertEqual(q["totale_cents"], TOTALE)
        r = self._bot().rispondi(SLUG, "quanto costa?",
                                 contesto={"check_in": self.ci, "check_out": self.co,
                                           "party": PARTY})
        self.assertEqual(r["intento"], "prezzo")
        self.assertEqual(r["fonte"], "concierge")
        self.assertEqual(r["totale_cents"], TOTALE)
        self.assertEqual(r["prezzo_guest_cents"], NETTO)
        self.assertIn("310.00 EUR", r["risposta"])
        self.assertNotIn("300.00", r["risposta"])
        # il preventivo citato e' FIRMATO dal sistema vero (non un numero inventato)
        firmato = self.sis.firma.decodifica(r["quote_token"])
        self.assertIsInstance(firmato, dict)
        self.assertEqual(firmato["totale_cents"], TOTALE)
        self.assertEqual(firmato["alloggio_id"], SLUG)

    def test_animali_dal_vocabolario_vero_del_catalogo(self):
        """DIFETTO TROVATO: cercava il servizio 'pet', che il catalogo VERO non usa
        (fase57 lo chiama 'animali_ammessi') -> rispondeva 'non ammessi' su una casa che
        li ammette."""
        d = self.sis.catalogo.dettaglio(SLUG)
        self.assertIn("animali_ammessi", d["servizi"])
        self.assertNotIn("pet", d["servizi"])
        r = self._bot().rispondi(SLUG, "posso portare il cane?")
        self.assertEqual(r["intento"], "animali")
        self.assertEqual(r["risposta"], "Animali ammessi.")

    def test_disponibilita_e_servizi_dai_dati_veri(self):
        r = self._bot().rispondi(SLUG, "e' disponibile?",
                                 contesto={"check_in": self.ci, "check_out": self.co})
        self.assertEqual(r["intento"], "disponibilita")
        self.assertEqual(r["fonte"], "concierge")
        self.assertTrue(r["risposta"].startswith("Disponibile"), r["risposta"])
        r = self._bot().rispondi(SLUG, "che servizi ci sono?")
        self.assertEqual(r["fonte"], "catalogo")
        self.assertIn("wifi", r["risposta"])
        r = self._bot().rispondi(SLUG, "dove si trova?")
        self.assertEqual(r["risposta"], "Si trova a Roma")

    def test_llm_non_puo_toccare_i_numeri(self):
        """Regola d'oro: il denaro non si delega all'IA. Anche con un LLM bugiardo, il prezzo
        resta quello firmato dal concierge."""
        bot = self._bot(llm=lambda t: "Costa 1 EUR, fidati!")
        r = bot.rispondi(SLUG, "quanto costa?",
                         contesto={"check_in": self.ci, "check_out": self.co,
                                   "party": PARTY})
        self.assertEqual(r["fonte"], "concierge")
        self.assertEqual(r["totale_cents"], TOTALE)
        self.assertNotIn("1 EUR", r["risposta"])
        self.assertEqual(bot.rispondi(SLUG, "domanda strampalata xyz")["fonte"], "llm")

    def test_date_occupate_non_diventano_un_prezzo(self):
        """Se le notti sono gia' vendute il chatbot non inventa un preventivo."""
        self.assertIsNotNone(self.sis.inventario.blocca(SLUG, self.ci, self.co,
                                                        idem_key="k"))
        self.g("POST", "/api/host/disponibilita",
               {"alloggio_id": SLUG, "giorno": self.ci, "unita_totali": 1,
                "prezzo_netto_cents": PREZZO_NOTTE}, self.tk)
        r = self._bot().rispondi(SLUG, "quanto costa?",
                                 contesto={"check_in": self.ci, "check_out": self.co})
        self.assertEqual(r["fonte"], "concierge")
        self.assertEqual(r["risposta"], "Non disponibile per quelle date.")
        self.assertNotIn("totale_cents", r)


# ══════════════════════════════════════════════════════════════════════════════
# 9) fase123 — WEB PUSH: nessuna rotta, nessuna chiave VAPID
# ══════════════════════════════════════════════════════════════════════════════
class TestWebPushSpento(_BaseDormienti):

    SUB = {"endpoint": "https://push.finto/ep-1",
           "keys": {"p256dh": "chiave-pub", "auth": "segreto"}}

    def test_gate_vapid_e_invio_con_chiavi(self):
        from fase123_web_push import crea_web_push
        spedite = []

        def _fetch(url, body, headers):
            spedite.append((url, json.loads(body.decode("utf-8")), headers))
            return 201

        # GATE: senza chiave pubblica VAPID il servizio push del browser rifiuterebbe;
        # il modulo non deve nemmeno PROVARE a spedire (il fetch e' iniettato apposta:
        # se il gate cadesse, la chiamata comparirebbe qui).
        senza = crea_web_push(self.d + "/push.db", firma_vapid=lambda ep: "vapid t=finto",
                              fetch=_fetch)
        senza.inizializza_schema()
        self.assertTrue(senza.registra("ospite@dormienti.it", self.SUB))
        self.assertEqual(senza.invia("ospite@dormienti.it", "Ciao", "corpo"), 0,
                         "senza VAPID non si spedisce nulla")
        self.assertEqual(spedite, [], "gate VAPID caduto: notifica partita senza chiavi")

        acceso = crea_web_push(self.d + "/push.db", vapid_public="BKpub",
                               firma_vapid=lambda ep: "vapid t=finto",
                               fetch=_fetch)
        self.assertEqual(acceso.invia("ospite@dormienti.it", "La tua casa a Roma",
                                      "Le date sono libere", url="/alloggio/" + SLUG), 1)
        self.assertEqual(len(spedite), 1)
        url, payload, headers = spedite[0]
        self.assertEqual(url, "https://push.finto/ep-1")
        self.assertEqual(payload, {"title": "La tua casa a Roma",
                                   "body": "Le date sono libere",
                                   "url": "/alloggio/" + SLUG})
        self.assertEqual(headers["Authorization"], "vapid t=finto")
        self.assertEqual(headers["TTL"], "86400")

    def test_disiscrizione_ferma_le_notifiche(self):
        from fase123_web_push import crea_web_push
        n = crea_web_push(self.d + "/push2.db", vapid_public="BKpub",
                          firma_vapid=lambda ep: "vapid", fetch=lambda *a: 201)
        n.inizializza_schema()
        n.registra("g", self.SUB)
        self.assertEqual(n.invia("g", "t", "c"), 1)
        self.assertTrue(n.disiscrivi("g", self.SUB["endpoint"]))
        self.assertEqual(n.invia("g", "t", "c"), 0)
        self.assertFalse(n.registra("g", {"endpoint": "http://insicuro", "keys": {}}))


# ══════════════════════════════════════════════════════════════════════════════
# 10) fase104 — GATEWAY ASIA: nessuna credenziale PSP asiatica
# ══════════════════════════════════════════════════════════════════════════════
class TestGatewayAsiaSpento(_BaseDormienti):

    def test_link_alipay_con_lo_split_vero_del_preventivo(self):
        """Alipay/WeChat riusano lo split di Stripe Connect: la fee che resta a noi e la
        destinazione host devono essere quelle del preventivo VERO, non numeri di comodo."""
        from fase104_gateway_asia import ProviderAsia, costruisci_params_asia
        s, q = self.quote()
        self.assertEqual(s, 200, q)
        chiamate = []

        def _fetch(url, body, headers):
            chiamate.append((url, body.decode("utf-8"), headers))
            return {"url": "https://checkout.stripe.finto/alipay-1", "id": "cs_asia"}

        p = ProviderAsia("sk_live_finta", success_url="https://x/ok",
                         cancel_url="https://x/ko", fetch=_fetch)
        link = p.crea_link({"prezzo_guest_cents": q["totale_cents"],
                            "commissione_cents": q["commissione_cents"],
                            "host_account": "acct_host_vero", "metodo": "alipay",
                            "valuta": "cny", "riferimento": SLUG})
        self.assertEqual(link, "https://checkout.stripe.finto/alipay-1")
        self.assertEqual(len(chiamate), 1)
        url, corpo, headers = chiamate[0]
        self.assertEqual(url, "https://api.stripe.com/v1/checkout/sessions")
        self.assertEqual(headers["Authorization"], "Bearer sk_live_finta")
        self.assertIn("payment_method_types%5B0%5D=alipay", corpo)
        self.assertIn("%5Bunit_amount%5D=" + str(TOTALE), corpo)
        self.assertIn("%5Bapplication_fee_amount%5D=" + str(COMMISSIONE), corpo)
        self.assertIn("%5Bdestination%5D=acct_host_vero", corpo)
        self.assertIn("%5Bcurrency%5D=cny", corpo)
        # WeChat aggiunge il suo client; un metodo inventato non produce params
        w = costruisci_params_asia(TOTALE, COMMISSIONE, "acct_host_vero", "wechat_pay")
        self.assertEqual(w["payment_method_options[wechat_pay][client]"], "web")
        self.assertIsNone(costruisci_params_asia(TOTALE, COMMISSIONE, "acct_host_vero",
                                                 "bancomat"))

    def test_senza_chiave_nessun_link(self):
        """GATED: senza credenziali il PSP non va nemmeno CHIAMATO (il fetch e' iniettato
        apposta: se il gate cadesse, la chiamata comparirebbe qui)."""
        from fase104_gateway_asia import ProviderAsia, crea_provider_asia_da_env
        chiamate = []

        def _fetch(url, body, headers):
            chiamate.append(url)
            return {"url": "https://non-doveva-esistere"}

        self.assertIsNone(ProviderAsia("", fetch=_fetch).crea_link(
            {"prezzo_guest_cents": TOTALE, "commissione_cents": COMMISSIONE,
             "host_account": "acct_x", "metodo": "alipay"}))
        self.assertEqual(chiamate, [], "gate della chiave caduto: PSP chiamato senza credenziali")
        self.assertIsNone(crea_provider_asia_da_env({}))


# ══════════════════════════════════════════════════════════════════════════════
# 11) fase107 — TRADUZIONE ANNUNCI: nessun backend collegato
# ══════════════════════════════════════════════════════════════════════════════
class TestTraduzioneAnnunciSpenta(_BaseDormienti):

    def test_traduce_l_annuncio_vero_e_non_ripaga_due_volte(self):
        from fase107_traduzione_annunci import crea_traduttore
        s, ann = self.g("GET", "/api/catalogo/" + SLUG)
        self.assertEqual(s, 200, ann)
        chiamate = []

        def _traduci(testo, da, a):
            chiamate.append((testo, da, a))
            return "[%s] %s" % (a, testo)

        t = crea_traduttore(_traduci)
        out = t.traduci_annuncio(ann, "en", lingua_origine="it")
        self.assertEqual(out["titolo"], "[en] Casa Dormiente")
        self.assertEqual(out["descrizione"], "[en] Casa con giardino e cane benvenuto")
        self.assertEqual(out["_lingua"], "en")
        self.assertEqual(out["_tradotto"], {"titolo": True, "descrizione": True})
        self.assertEqual(out["prezzo_notte_cents"], PREZZO_NOTTE)   # i numeri non si toccano
        self.assertEqual(out["slug"], SLUG)
        self.assertEqual(len(chiamate), 2)
        t.traduci_annuncio(ann, "en", lingua_origine="it")          # cache: nessuna ri-chiamata
        self.assertEqual(len(chiamate), 2, "la cache non ha protetto dal ri-pagamento")

    def test_senza_backend_passa_intatto(self):
        """Default onesto (direttiva fase61): niente traduzione a pagamento -> testo invariato,
        taggato con la lingua d'origine; e un backend che esplode non rompe l'annuncio."""
        from fase107_traduzione_annunci import crea_traduttore
        s, ann = self.g("GET", "/api/catalogo/" + SLUG)
        out = crea_traduttore().traduci_annuncio(ann, "en", lingua_origine="it")
        self.assertEqual(out["titolo"], "Casa Dormiente")
        self.assertEqual(out["_lingua"], "it")
        self.assertEqual(out["_tradotto"], {"titolo": False, "descrizione": False})

        def _boom(*a):
            raise RuntimeError("backend giu'")

        rotto = crea_traduttore(_boom).traduci_annuncio(ann, "en", lingua_origine="it")
        self.assertEqual(rotto["titolo"], "Casa Dormiente")
        self.assertEqual(rotto["_lingua"], "it")


# ══════════════════════════════════════════════════════════════════════════════
# 12) fase129 — TRADUZIONE RECENSIONI: sulla recensione VERA di fase63
# ══════════════════════════════════════════════════════════════════════════════
class TestTraduzioneRecensioniSpenta(_BaseDormienti):

    def _recensione_vera(self):
        rif, _v = self.prenotazione_pagata()
        diritto = self.sis.emettitore_recensioni.emetti(rif, SLUG)
        s, e = self.g("POST", "/api/recensioni",
                      {"token": diritto, "voto": 5,
                       "testo": "Ottimo soggiorno, molto bello e pulito",
                       "lingua": "it"})
        self.assertEqual(s, 201, e)
        self.assertEqual(e, {"ok": True, "motivo": "", "verificata": True})
        s, pubbliche = self.g("GET", "/api/recensioni/" + SLUG)
        self.assertEqual(s, 200, pubbliche)
        self.assertEqual(len(pubbliche["recensioni"]), 1)
        return pubbliche["recensioni"][0]

    def test_traduce_la_recensione_nella_forma_vera_di_fase63(self):
        """DIFETTO TROVATO: fase63 consegna `testo = {"text": ..., "lang": ...}`; il
        traduttore pretendeva una stringa e lasciava passare tutto INTATTO (tradotto=False),
        anche col backend acceso. Con dati veri non traduceva mai nulla."""
        from fase129_traduzione_recensioni import crea_traduttore_recensioni
        rec = self._recensione_vera()
        self.assertEqual(rec["testo"], {"text": "Ottimo soggiorno, molto bello e pulito",
                                        "lang": "it"})
        out = crea_traduttore_recensioni(
            lambda testo, da, a: "Great stay" if (da, a) == ("it", "en") else "?"
        ).traduci_recensione(rec, "en")
        self.assertEqual(out["testo"], "Great stay")
        self.assertEqual(out["lingua"], "en")
        self.assertEqual(out["lingua_origine"], "it")
        self.assertTrue(out["tradotto_auto"])
        self.assertEqual(out["testo_originale"], "Ottimo soggiorno, molto bello e pulito")
        self.assertEqual(out["voto"], 5)                     # il voto non si traduce

    def test_senza_backend_la_recensione_resta_leggibile(self):
        from fase129_traduzione_recensioni import crea_traduttore_recensioni
        rec = self._recensione_vera()
        out = crea_traduttore_recensioni().traduci_recensione(rec, "en")
        self.assertEqual(out["testo"], "Ottimo soggiorno, molto bello e pulito")
        self.assertEqual(out["lingua_origine"], "it")
        self.assertFalse(out["tradotto_auto"])


# ══════════════════════════════════════════════════════════════════════════════
# 13) fase105 — IDENTITY GATE (Verifiable Credential W3C): nessun cablaggio
# ══════════════════════════════════════════════════════════════════════════════
class TestIdentityGateSpento(_BaseDormienti):

    def test_credenziale_sull_annuncio_vero_e_manomissione_scoperta(self):
        from fase105_identity_gate import crea_gate_identita
        gate = crea_gate_identita(self.sis.config.segreto_hmac)
        d = self.sis.catalogo.dettaglio(SLUG)
        vc = gate.emetti_annuncio(self.host_id, SLUG, d["titolo"], d["citta"])
        self.assertIsInstance(vc, str)
        self.assertTrue(gate.verifica_annuncio(vc, slug=SLUG, titolo=d["titolo"],
                                               citta=d["citta"]))
        # titolo cambiato (annuncio clonato/manomesso) -> credenziale non piu' valida
        self.assertFalse(gate.verifica_annuncio(vc, slug=SLUG, titolo=d["titolo"] + " LUSSO",
                                                citta=d["citta"]))
        self.assertFalse(gate.verifica_annuncio(vc, slug="altro-slug", titolo=d["titolo"],
                                                citta=d["citta"]))
        # firmata con un ALTRO segreto -> rifiutata (la firma e' la sostanza)
        altro = crea_gate_identita(b"X" * 32)
        self.assertFalse(altro.verifica_annuncio(vc, slug=SLUG, titolo=d["titolo"],
                                                 citta=d["citta"]))

    def test_credenziale_di_recensione_legata_al_soggiorno(self):
        from fase105_identity_gate import crea_gate_identita
        rif, _v = self.prenotazione_pagata()
        gate = crea_gate_identita(self.sis.config.segreto_hmac)
        vc = gate.emetti_recensione(rif, SLUG, 5, "Tutto perfetto")
        self.assertTrue(gate.verifica_recensione(vc, prenotazione_id=rif, alloggio_slug=SLUG,
                                                 voto=5, testo="Tutto perfetto"))
        self.assertFalse(gate.verifica_recensione(vc, prenotazione_id=rif,
                                                  alloggio_slug=SLUG, voto=1,
                                                  testo="Tutto perfetto"))
        self.assertFalse(gate.verifica_recensione(vc, prenotazione_id="altra-prenotazione",
                                                  alloggio_slug=SLUG, voto=5,
                                                  testo="Tutto perfetto"))
        self.assertIsNone(gate.emetti_recensione(rif, SLUG, 9, "voto fuori scala"))


# ══════════════════════════════════════════════════════════════════════════════
# 14) IL REGISTRO DEI BUCHI: cosa manca per usarli in produzione
# ══════════════════════════════════════════════════════════════════════════════
class TestGapDiCablaggio(_BaseDormienti):
    """Fotografia ONESTA dello stato attuale. Se un giorno uno di questi moduli viene
    cablato, questo test diventa rosso: e' il promemoria per aggiornare
    REGISTRO_INGEGNERIA sez.2 e per scrivere il collaudo della rotta nuova."""

    # ✅ 'deposito' TOLTO dalla lista il 2026-07-30: fase149 e' stato CABLATO (archivio durevole
    # DB_DEPOSITO, esposto come `sistema.deposito`) — vedi test_deposito_cablato.py. Resta senza
    # ROTTA, quindi continua a comparire nel test sulle rotte inesistenti qui sotto: mezzo
    # cablato, come coda e split.
    SPENTI = ("cauzione", "wishlist", "fedelta", "chatbot", "web_push",
              "push", "traduttore", "gate_identita", "asia")

    def test_i_moduli_spenti_non_sono_ancora_nel_sistema(self):
        for nome in self.SPENTI:
            self.assertIsNone(getattr(self.sis, nome, None),
                              "'%s' e' stato cablato: aggiorna REGISTRO sez.2 e i collaudi"
                              % nome)

    def test_il_deposito_e_cablato_ma_senza_rotta(self):
        """Il modulo che era «costruito e dimenticato» ora e' nel sistema (fase149), con
        archivio durevole. La porta d'ingresso per l'utente resta da decidere."""
        self.assertIsNotNone(self.sis.deposito, "il deposito e' tornato scollegato")

    def test_le_rotte_dei_moduli_spenti_non_esistono(self):
        """Nessuna rotta -> l'utente non puo' usarli. 404 e' la prova del buco."""
        for metodo, rotta, corpo in (
                ("POST", "/api/wishlist", {"slug": SLUG}),
                ("GET", "/api/wishlist", None),
                ("POST", "/api/fedelta/accredita", {"punti": 1}),
                ("POST", "/api/chatbot", {"slug": SLUG, "testo": "ciao"}),
                ("POST", "/api/push/registra", {"sub": {}}),
                ("POST", "/api/deposito/autorizza", {"importo_cents": 100}),
                ("POST", "/api/coda/iscrivi", {"alloggio_id": SLUG}),
                ("GET", "/api/coda/posizione", None)):
            s, _c = self.g(metodo, rotta, corpo, self.tk)
            self.assertEqual(s, 404, "%s %s ora esiste: cablato? aggiorna il registro"
                             % (metodo, rotta))

    def test_la_coda_e_lo_split_sono_nel_sistema_ma_senza_rotte(self):
        """Meta' cablati: il motore c'e' (e su file), la porta d'ingresso no."""
        self.assertIsNotNone(self.sis.coda)
        self.assertIsNotNone(self.sis.split)
        self.assertIsNotNone(self.sis.kyc)


if __name__ == "__main__":
    unittest.main()
