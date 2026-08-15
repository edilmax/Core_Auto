"""COLLAUDO HAPPY-PATH — fetta "ALTRO" (le rotte che non sono host/admin/bunker/ospite).

MANDATO (livello 1, fondatore): per OGNI rotta di questa fetta una richiesta VALIDA e ben
formata, con l'autenticazione giusta e i dati corretti, deve rispondere con lo stato ESATTO
atteso e con una struttura coerente. Non basta "non e' 500": ogni test asserisce
  (a) lo STATO esatto,
  (b) le CHIAVI e i TIPI del corpo,
  (c) dove ha senso un VALORE VERO (un id, un totale, un conteggio, un effetto sul dato).

DUE LIVELLI, perche' questa fetta vive in due posti diversi:
  · TestHappyAltroRouter  — le 12 rotte /api/* del ROUTER (health x4, lingue, i18n, legale x2,
    trasparenza, mappa, telegram/webhook, gate/logout);
  · TestHappyAltroHTTP    — le superfici che NON passano dal router e vivono solo
    nell'handler HTTP (robots/sitemap*/feed/rss/llms/blog/affitta/openapi/ai-plugin/
    ical pubblico/host-azione/indexnow key-file/stop/entra-*/grazie/annullato/HEAD/OPTIONS):
    girate contro un SERVER VERO avviato in un thread, come test_gatekeeper.

Deterministico e OFFLINE: niente Stripe (nessuna chiave -> provider None), email finta,
MARCA_TEMPORALE=0 (altrimenti il giro RFC 3161 chiamerebbe una TSA in rete),
TELEGRAM_BOT_TOKEN assente (la risposta al bot e' un no-op), archivi su file temporanei.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import http.client
import json
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
from urllib.parse import quote

import fase83_server
from fase61_localizzazione import LINGUE_SUPPORTATE
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

SEGRETO = b"A" * 32
RADICE = os.path.dirname(os.path.abspath(__file__))


class _Posta:
    """Provider email finto: registra invece di spedire."""

    def __init__(self):
        self.inviate = []

    def invia(self, dest, oggetto, html):
        self.inviate.append((dest, oggetto, html))
        return True


def _stripe_finto(_url, _body, _headers):
    """Sostituto in-house della chiamata HTTP a Stripe: nessuna rete, esito deterministico."""
    import secrets
    n = secrets.token_hex(6)
    return {"url": "https://checkout.finto/" + n, "id": "cs_" + n}


def _porta_libera():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _config(d, **extra):
    base = dict(
        abilitato=True, segreto_hmac=SEGRETO, con_registrazione_host=True,
        db_catalogo=d + "/c.db", db_inventario=d + "/i.db", db_registro_host=d + "/r.db",
        db_accettazioni=d + "/a.db", db_pendenti=d + "/p.db", db_payout=d + "/pay.db",
        db_garanzia=d + "/g.db", db_recensioni=d + "/rec.db", db_domanda=d + "/dom.db",
        db_messaggi=d + "/m.db", db_finanza=d + "/fin.db")
    base.update(extra)
    return ConfigCasaVIP(**base)


# ═══════════════════════════════════════════════════════════════════════════════════
#  LIVELLO 1 — le 12 rotte /api/* del ROUTER
# ═══════════════════════════════════════════════════════════════════════════════════
class TestHappyAltroRouter(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._marca_prec = os.environ.get("MARCA_TEMPORALE")
        os.environ["MARCA_TEMPORALE"] = "0"
        cls.dir = tempfile.mkdtemp()
        cls.sis = crea_sistema(_config(cls.dir))
        cls.posta = _Posta()
        cls.sis.email_provider = cls.posta
        cls.r = crea_router(cls.sis, host_key="hk", admin_key="ak",
                            base_url="https://bookinvip.com")
        # un host vero + un annuncio vero CON COORDINATE: senza dati la mappa
        # risponderebbe "0 pin" e il test non proverebbe nulla.
        s, c = cls._g("POST", "/api/host/registrazione", {
            "email": "altro@collaudo.it", "password": "password12",
            "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
            "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        assert s == 201, (s, c)
        cls.host_id, cls.token = c["host_id"], c["token"]
        cls.hk = {"X-Host-Token": cls.token}
        s, c = cls._g("POST", "/api/host/pubblica", {
            "slug": "casa-altro", "titolo": "Attico del collaudo", "citta": "Roma",
            "paese": "IT", "cin": "IT058091C2X5V0ABCD", "descrizione": "Vista Colosseo",
            "prezzo_notte_cents": 15000, "capacita": 3,
            "lat_micro": 41902782, "lon_micro": 12496365,
            "servizi": [], "immagini": []}, cls.hk)
        assert s == 201, (s, c)
        oggi = datetime.date.today()
        s, c = cls._g("POST", "/api/host/disponibilita_range", {
            "alloggio_id": "casa-altro", "da": oggi.isoformat(),
            "a": (oggi + datetime.timedelta(days=30)).isoformat(),
            "unita_totali": 2, "prezzo_netto_cents": 15000}, cls.hk)
        assert s == 200, (s, c)

    @classmethod
    def tearDownClass(cls):
        if cls._marca_prec is None:
            os.environ.pop("MARCA_TEMPORALE", None)
        else:
            os.environ["MARCA_TEMPORALE"] = cls._marca_prec
        shutil.rmtree(cls.dir, ignore_errors=True)

    @classmethod
    def _g(cls, metodo, path, body=None, headers=None, query=None):
        return cls.r.gestisci(metodo, path, query or {},
                              json.dumps(body) if body is not None else None,
                              headers or {})

    def g(self, metodo, path, body=None, headers=None, query=None):
        return self._g(metodo, path, body, headers, query)

    # ── 1) GET /api/health ────────────────────────────────────────────────────
    def test_health(self):
        s, c = self.g("GET", "/api/health")
        self.assertEqual(s, 200)
        # I campi stabili restano fissati esatti; `guardiano` (2026-08-15) varia col battito
        # del Guardiano dei soldi, quindi si fissa l'INSIEME dei valori ammessi -- contratto
        # piu' STRETTO, non piu' largo: un valore inventato fa rosso.
        self.assertEqual({k: v for k, v in c.items() if k != "guardiano"},
                         {"status": "ok", "money_unit": "cents_integer"})
        self.assertIn(c.get("guardiano"), ("ok", "muto", "sconosciuto"),
                      "stato del Guardiano non riconoscibile dalla salute: %r" % (c,))

    # ── 2) GET /api/health/live ───────────────────────────────────────────────
    def test_health_live(self):
        s, c = self.g("GET", "/api/health/live")
        self.assertEqual(s, 200)
        self.assertEqual(c, {"status": "live", "money_unit": "cents_integer"})

    # ── 3) GET /api/health/ready ──────────────────────────────────────────────
    def test_health_ready(self):
        s, c = self.g("GET", "/api/health/ready")
        self.assertEqual(s, 200)
        self.assertEqual(c, {"status": "ready"})

    # ── 4) GET /api/health/db ─────────────────────────────────────────────────
    def test_health_db(self):
        s, c = self.g("GET", "/api/health/db")
        self.assertEqual(s, 200, c)
        self.assertEqual(c.get("status"), "ok")
        db = c.get("db")
        self.assertIsInstance(db, dict)
        # VALORE VERO: gli archivi CONFIGURATI SU FILE sono nominati uno per uno e sono "ok".
        for nome in ("db_catalogo", "db_inventario", "db_registro_host", "db_pendenti"):
            self.assertEqual(db.get(nome), "ok", "%s non sano: %s" % (nome, db))
        # gli archivi lasciati a :memory: NON vengono sondati (nessun falso "ok")
        self.assertNotIn("db_viral", db)

    # ── 5) GET /api/lingue ────────────────────────────────────────────────────
    def test_lingue(self):
        s, c = self.g("GET", "/api/lingue")
        self.assertEqual(s, 200)
        self.assertIsInstance(c.get("lingue"), list)
        self.assertEqual(c["lingue"], list(LINGUE_SUPPORTATE))
        self.assertEqual(len(c["lingue"]), 8)
        for l in ("it", "en", "ja", "zh"):
            self.assertIn(l, c["lingue"])

    # ── 6) GET /api/i18n ──────────────────────────────────────────────────────
    def test_i18n(self):
        s, c = self.g("GET", "/api/i18n", query={"lang": "fr"})
        self.assertEqual(s, 200)
        self.assertEqual(c.get("lingua"), "fr")
        for k in ("ui", "servizi", "stati"):
            self.assertIsInstance(c.get(k), dict, k)
            self.assertTrue(c[k], "%s vuoto" % k)
        # VALORE VERO: il dizionario e' DAVVERO in francese, non l'italiano ricopiato.
        s_it, c_it = self.g("GET", "/api/i18n", query={"lang": "it"})
        self.assertEqual(s_it, 200)
        self.assertEqual(set(c["ui"]), set(c_it["ui"]))
        diverse = [k for k in c["ui"] if c["ui"][k] != c_it["ui"][k]]
        self.assertGreater(len(diverse), 10, "fr e it identici: traduzioni non servite")

    # ── 7) GET /api/legale/documento ──────────────────────────────────────────
    def test_legale_documento(self):
        for doc in ("termini", "privacy"):
            s, c = self.g("GET", "/api/legale/documento", query={"doc": doc, "lang": "de"})
            self.assertEqual(s, 200, c)
            self.assertEqual(c.get("documento"), doc)
            self.assertEqual(c.get("lang"), "de")
            self.assertEqual(c.get("lingua_che_fa_fede"), "it")
            self.assertTrue(c.get("tradotto"))
            self.assertIsInstance(c.get("lingue"), list)
            self.assertIn("it", c["lingue"])
            self.assertIsInstance(c.get("testo"), str)
            self.assertGreater(len(c["testo"]), 500, "testo legale troppo corto per essere vero")
            # VALORE VERO: l'impronta e' quella del testo servito (verificabile da chi firma)
            self.assertEqual(c.get("doc_sha256"),
                             hashlib.sha256(c["testo"].encode("utf-8")).hexdigest())
            self.assertIsInstance(c.get("versione"), str)
            self.assertTrue(c["versione"])
        # default senza parametro: i termini
        s, c = self.g("GET", "/api/legale/documento")
        self.assertEqual(s, 200)
        self.assertEqual(c.get("documento"), "termini")
        # ANTI-FINTO-VERDE: dichiarare `lang` non basta, il TESTO deve cambiare davvero
        # (modo di rompersi n.11: "la pagina ha 8 lingue ma il testo e' congelato").
        testi = {}
        for lang in ("it", "en", "de", "ja"):
            s, c = self.g("GET", "/api/legale/documento",
                          query={"doc": "privacy", "lang": lang})
            self.assertEqual(s, 200)
            testi[lang] = c["testo"]
        self.assertEqual(len(set(testi.values())), 4,
                         "privacy: due lingue servono lo STESSO testo")

    # ── 8) GET /api/legale/contratto-host ─────────────────────────────────────
    def test_legale_contratto_host(self):
        s, c = self.g("GET", "/api/legale/contratto-host", query={"lang": "it"})
        self.assertEqual(s, 200, c)
        self.assertEqual(c.get("lang"), "it")
        self.assertEqual(c.get("lingua_che_fa_fede"), "it")
        self.assertIsInstance(c.get("testo"), str)
        self.assertGreater(len(c["testo"]), 500)
        self.assertIsInstance(c.get("lingue"), list)
        # VALORE VERO: versione e impronta sono ESATTAMENTE quelle che la registrazione
        # pretende (se divergessero, nessun host potrebbe piu' accettare il contratto).
        self.assertEqual(c.get("versione"), CONTRATTO_HOST_VERSIONE)
        self.assertEqual(c.get("doc_sha256"), doc_sha256())
        # ANTI-FINTO-VERDE: la lingua dichiarata deve cambiare il TESTO servito
        s_en, c_en = self.g("GET", "/api/legale/contratto-host", query={"lang": "en"})
        self.assertEqual(s_en, 200)
        self.assertEqual(c_en.get("lang"), "en")
        self.assertNotEqual(c_en["testo"], c["testo"],
                            "contratto host: 'en' serve il testo italiano")

    # ── 9) GET /api/trasparenza ───────────────────────────────────────────────
    def test_trasparenza(self):
        s, c = self.g("GET", "/api/trasparenza",
                      query={"prezzo_cents": "100000", "ota": "booking"})
        self.assertEqual(s, 200, c)
        self.assertEqual(c.get("prezzo_riferimento_cents"), 100000)
        self.assertEqual(c.get("money_unit"), "cents_integer")
        for blocco in ("scenario_ota", "scenario_nostro"):
            self.assertIsInstance(c.get(blocco), dict, blocco)
        for k in ("commissione_cents", "host_netto_cents", "guest_paga_cents"):
            self.assertIsInstance(c["scenario_ota"][k], int, k)
        for k in ("imponibile_cents", "commissione_cents", "psp_cents",
                  "host_netto_cents", "guest_paga_cents"):
            self.assertIsInstance(c["scenario_nostro"][k], int, k)
        # VALORE VERO: la NOSTRA commissione e' quella REALE della config (10% di 100000),
        # e col nostro modello l'host tiene di piu' che con l'OTA.
        self.assertEqual(c["scenario_nostro"]["commissione_cents"], 10000)
        self.assertGreater(c["scenario_ota"]["commissione_cents"],
                           c["scenario_nostro"]["commissione_cents"])
        self.assertEqual(c.get("guadagno_extra_host_cents"),
                         c["scenario_nostro"]["host_netto_cents"]
                         - c["scenario_ota"]["host_netto_cents"])
        self.assertGreater(c["guadagno_extra_host_cents"], 0)

    # ── 10) GET /api/mappa ────────────────────────────────────────────────────
    def test_mappa(self):
        s, c = self.g("GET", "/api/mappa", query={"citta": "Roma"})
        self.assertEqual(s, 200, c)
        self.assertEqual(c.get("type"), "FeatureCollection")
        self.assertIsInstance(c.get("features"), list)
        self.assertEqual(c.get("con_coordinate"), 1)
        self.assertGreaterEqual(c.get("totale"), 1)
        f = c["features"][0]
        self.assertEqual(f["type"], "Feature")
        self.assertEqual(f["geometry"]["type"], "Point")
        # VALORE VERO: le coordinate GeoJSON sono [lon, lat] in GRADI, dai microgradi salvati
        lon, lat = f["geometry"]["coordinates"]
        self.assertAlmostEqual(lat, 41.902782, places=6)
        self.assertAlmostEqual(lon, 12.496365, places=6)
        p = f["properties"]
        self.assertEqual(p["slug"], "casa-altro")
        self.assertEqual(p["titolo"], "Attico del collaudo")
        self.assertEqual(p["citta"], "Roma")
        self.assertEqual(p["prezzo_cents"], 15000)
        self.assertEqual(p["valuta"], "EUR")

    # ── 11) POST /api/telegram/webhook ────────────────────────────────────────
    @staticmethod
    def _payload_telegram(host_id):
        sig = hmac.new(SEGRETO, host_id.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
        return "%s-%s" % (host_id, sig)

    def test_telegram_webhook(self):
        self.assertEqual(self.sis.registro_host.info_host(self.host_id)["telegram_chat_id"], "")
        s, c = self.g("POST", "/api/telegram/webhook", {
            "update_id": 1,
            "message": {"chat": {"id": 987654321},
                        "text": "/start " + self._payload_telegram(self.host_id)}})
        self.assertEqual(s, 200)
        self.assertEqual(c, {"ok": True})
        # EFFETTO VERO: il chat_id dell'host e' stato salvato (e' l'unico scopo della rotta)
        self.assertEqual(self.sis.registro_host.info_host(self.host_id)["telegram_chat_id"],
                         "987654321")

    def test_telegram_webhook_col_segreto_configurato(self):
        """Happy path CON autenticazione: header segreto giusto -> 200 e collegamento fatto."""
        prec = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
        os.environ["TELEGRAM_WEBHOOK_SECRET"] = "s3greto-di-collaudo"
        try:
            s, c = self.g("POST", "/api/telegram/webhook", {
                "message": {"chat": {"id": 111222333},
                            "text": "/start " + self._payload_telegram(self.host_id)}},
                {"X-Telegram-Bot-Api-Secret-Token": "s3greto-di-collaudo"})
            self.assertEqual(s, 200)
            self.assertEqual(c, {"ok": True})
            self.assertEqual(
                self.sis.registro_host.info_host(self.host_id)["telegram_chat_id"], "111222333")
        finally:
            if prec is None:
                os.environ.pop("TELEGRAM_WEBHOOK_SECRET", None)
            else:
                os.environ["TELEGRAM_WEBHOOK_SECRET"] = prec

    # ── 12) POST /api/gate/logout ─────────────────────────────────────────────
    def test_gate_logout(self):
        s, c = self.g("POST", "/api/gate/logout", {})
        self.assertEqual(s, 200)
        self.assertIs(c.get("ok"), True)
        cookie = c.get("_cookie")
        self.assertIsInstance(cookie, list)
        # VALORE VERO: i TRE cookie di sessione, tutti con Max-Age 0 (cancellazione)
        self.assertEqual({n for n, _v, _m in cookie}, {"bv_admin", "bv_host", "bv_bunker"})
        for _n, valore, maxage in cookie:
            self.assertEqual(valore, "")
            self.assertEqual(maxage, 0)


# ═══════════════════════════════════════════════════════════════════════════════════
#  LIVELLO 2 — le superfici che vivono SOLO nell'handler HTTP (server vero in thread)
# ═══════════════════════════════════════════════════════════════════════════════════
class TestHappyAltroHTTP(unittest.TestCase):

    BASE = "https://bookinvip.com"
    INDEXNOW_KEY = "chiavecollaudoaltro0123456789ab"

    @classmethod
    def setUpClass(cls):
        cls._env_prec = {k: os.environ.get(k) for k in
                         ("MARCA_TEMPORALE", "INDEXNOW_KEY", "OUTREACH_OPTOUT_FILE",
                          "UPLOAD_DIR", "PAGE_GATE")}
        cls.dir = tempfile.mkdtemp()
        # Il GUARDIANO (fase186) parte con il server e, avendo una chiave Stripe in config,
        # interrogherebbe api.stripe.com: qui la lista Stripe la serve una funzione locale
        # (vuota). Nessuna rete, nessun 401 nei log, esito deterministico.
        import fase182_riconciliazione as _ric
        cls._fetch_ric_prec = _ric._fetch_reale
        _ric._fetch_reale = lambda _p, _params, _k: {"data": [], "has_more": False}
        os.environ["MARCA_TEMPORALE"] = "0"      # niente giro RFC 3161 = niente rete
        os.environ["INDEXNOW_KEY"] = cls.INDEXNOW_KEY
        os.environ["OUTREACH_OPTOUT_FILE"] = cls.dir + "/optout.json"
        os.environ["UPLOAD_DIR"] = cls.dir + "/uploads"
        os.environ.pop("PAGE_GATE", None)
        cls.sis = crea_sistema(_config(
            cls.dir, stripe_secret_key="sk_collaudo", stripe_webhook_secret="whsec_collaudo",
            stripe_success_url=cls.BASE + "/grazie", stripe_cancel_url=cls.BASE + "/annullato"))
        # Stripe FINTO sulla SOLA istanza (niente monkeypatch di classe, niente rete):
        # serve ad avere un pagamento vero da cui nascono voucher, ricevuta e recensione.
        cls.sis.stripe._fetch = _stripe_finto
        cls.posta = _Posta()
        cls.sis.email_provider = cls.posta
        # router "di servizio" sullo STESSO sistema: serve solo a preparare i dati e a
        # coniare i link firmati (stesso segreto del server) — le rotte si chiamano via HTTP.
        cls.r = crea_router(cls.sis, host_key="hk", admin_key="ak", base_url=cls.BASE)
        cls._prepara_dati()
        cls.porta = _porta_libera()
        cls.t = threading.Thread(
            target=fase83_server.servi,
            kwargs=dict(sistema=cls.sis, host="127.0.0.1", porta=cls.porta,
                        cartella_statica=os.path.join(RADICE, "deploy"),
                        host_key="hk", admin_key="ak", base_url=cls.BASE),
            daemon=True)
        cls.t.start()
        for _ in range(300):                      # attesa attiva finche' risponde
            try:
                if cls._req("GET", "/api/health/live")[0] == 200:
                    break
            except Exception:
                pass
            time.sleep(0.02)

    @classmethod
    def tearDownClass(cls):
        import fase182_riconciliazione as _ric
        _ric._fetch_reale = cls._fetch_ric_prec
        for k, v in cls._env_prec.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.dir, ignore_errors=True)

    # ── dati veri: un annuncio pubblicato, un giorno chiuso (per l'iCal), e una
    #    richiesta 'su richiesta' in attesa (per il link Approva da messaggio) ──
    @classmethod
    def _prepara_dati(cls):
        def g(m, p, b=None, h=None, q=None):
            return cls.r.gestisci(m, p, q or {},
                                  json.dumps(b) if b is not None else None, h or {})

        s, c = g("POST", "/api/host/registrazione", {
            "email": "http@collaudo.it", "password": "password12",
            "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
            "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        assert s == 201, (s, c)
        cls.host_id, cls.token = c["host_id"], c["token"]
        hk = {"X-Host-Token": cls.token}
        oggi = datetime.date.today()
        for slug, titolo, modo in (("casa-http", "Loft del collaudo", "immediata"),
                                   ("casa-http-rq", "Villa su richiesta", "su_richiesta")):
            s, c = g("POST", "/api/host/pubblica", {
                "slug": slug, "titolo": titolo, "citta": "Roma", "paese": "IT",
                "cin": "IT058091C2X5V0ABCD", "descrizione": "Bella e vera",
                "prezzo_notte_cents": 18000, "capacita": 2, "modalita_prenotazione": modo,
                "lat_micro": 41902782, "lon_micro": 12496365,
                "servizi": [], "immagini": []}, hk)
            assert s == 201, (slug, s, c)
            s, c = g("POST", "/api/host/disponibilita_range", {
                "alloggio_id": slug, "da": oggi.isoformat(),
                "a": (oggi + datetime.timedelta(days=40)).isoformat(),
                "unita_totali": 1, "prezzo_netto_cents": 18000}, hk)
            assert s == 200, (slug, s, c)
        # un giorno CHIUSO dall'host -> deve comparire nel feed .ics pubblico
        cls.giorno_chiuso = (oggi + datetime.timedelta(days=3)).isoformat()
        s, c = g("POST", "/api/host/disponibilita", {
            "alloggio_id": "casa-http", "giorno": cls.giorno_chiuso,
            "unita_totali": 1, "prezzo_netto_cents": 18000, "chiuso": True}, hk)
        assert s == 200, (s, c)
        # URL firmato del calendario (rotta host, qui usata come fixture)
        s, c = g("GET", "/api/host/ical_link", None, hk, {"alloggio": "casa-http"})
        assert s == 200, (s, c)
        cls.ical_path = c["url"][len(cls.BASE):]
        assert cls.ical_path.startswith("/ical/") and cls.ical_path.endswith(".ics"), c
        # richiesta 'su richiesta' in attesa + link firmato Approva (quello delle email)
        ci = (oggi + datetime.timedelta(days=10)).isoformat()
        co = (oggi + datetime.timedelta(days=12)).isoformat()
        s, q = g("POST", "/api/concierge/quote", {
            "alloggio_id": "casa-http-rq", "check_in": ci, "check_out": co, "party": 2})
        assert s == 200, (s, q)
        s, b = g("POST", "/api/concierge/book",
                 {"quote_token": q["quote_token"], "email": "ospite@collaudo.it"})
        assert s == 201 and b.get("stato") == "in_attesa_host", (s, b)
        cls.riferimento = b["riferimento"]
        link = cls.r._link_azione(cls.riferimento, cls.host_id, "approva")
        assert link.startswith(cls.BASE + "/host/azione?t="), link
        cls.azione_path = link[len(cls.BASE):]
        # FOTO VERA caricata dall'host -> deve poi essere servita da /uploads/<nome>
        cls.png = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 40)
        s, c = g("POST", "/api/host/upload_foto",
                 {"image_base64": base64.b64encode(cls.png).decode("ascii")}, hk)
        assert s == 201, (s, c)
        cls.upload_path = c["url"]
        # PRENOTAZIONE VERA e PAGATA (instant-book) -> voucher, ricevuta, recensione
        ci2 = (oggi + datetime.timedelta(days=20)).isoformat()
        co2 = (oggi + datetime.timedelta(days=22)).isoformat()
        s, q = g("POST", "/api/concierge/quote", {
            "alloggio_id": "casa-http", "check_in": ci2, "check_out": co2, "party": 2})
        assert s == 200, (s, q)
        s, b = g("POST", "/api/concierge/book",
                 {"quote_token": q["quote_token"], "email": "pagante@collaudo.it",
                  "lang": "it"})
        assert s == 201 and b.get("voucher_token"), (s, b)
        cls.voucher = b["voucher_token"]
        cls.rif_pagato = b["riferimento"]
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata":
                                                  {"riferimento": cls.rif_pagato}}}})
        s, w = cls.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                              {"Stripe-Signature": firma_di_test(payload, "whsec_collaudo",
                                                                 int(time.time()))})
        assert s == 200, (s, w)
        assert cls.sis.pagamenti_pendenti.info(cls.rif_pagato).get("stato") == "pagato"
        # PRENOTAZIONE NON PAGATA (stesso annuncio, altre date): serve a dare senso al
        # verde di sopra — la ricevuta esiste SOLO dove i soldi sono arrivati davvero.
        ci3 = (oggi + datetime.timedelta(days=25)).isoformat()
        co3 = (oggi + datetime.timedelta(days=27)).isoformat()
        s, q3 = g("POST", "/api/concierge/quote", {
            "alloggio_id": "casa-http", "check_in": ci3, "check_out": co3, "party": 2})
        assert s == 200, (s, q3)
        s, b3 = g("POST", "/api/concierge/book",
                  {"quote_token": q3["quote_token"], "email": "nonpagante@collaudo.it",
                   "lang": "it"})
        assert s == 201 and b3.get("voucher_token"), (s, b3)
        cls.voucher_non_pagato = b3["voucher_token"]
        cls.rif_non_pagato = b3["riferimento"]
        assert cls.sis.pagamenti_pendenti.info(cls.rif_non_pagato).get("stato") != "pagato"

    # ── trasporto HTTP grezzo (redirect NON seguiti) ──────────────────────────
    @classmethod
    def _req(cls, metodo, path, headers=None, body=None):
        c = http.client.HTTPConnection("127.0.0.1", cls.porta, timeout=10)
        try:
            c.request(metodo, path, body=body, headers=headers or {})
            r = c.getresponse()
            dati = r.read()
            hd = {k.lower(): v for k, v in r.getheaders()}
            return r.status, hd, dati.decode("utf-8", "replace")
        finally:
            c.close()

    def req(self, metodo, path, headers=None, body=None):
        return self._req(metodo, path, headers, body)

    @classmethod
    def _grezzo(cls, metodo, path):
        """Richiesta a SOCKET NUDO: legge dal filo TUTTI i byte che il server manda.
        Indispensabile per HEAD: `http.client` SCARTA d'ufficio il corpo di una risposta
        HEAD, quindi un server che lo spedisse lo stesso passerebbe inosservato — la
        verifica non potrebbe fallire mai (guardia-ornamento). Qui invece si vede."""
        s = socket.create_connection(("127.0.0.1", cls.porta), timeout=10)
        try:
            s.sendall(("%s %s HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
                       % (metodo, path)).encode("ascii"))
            pezzi = []
            while True:
                b = s.recv(65536)
                if not b:
                    break
                pezzi.append(b)
        finally:
            s.close()
        grezzo = b"".join(pezzi)
        testa, _, corpo = grezzo.partition(b"\r\n\r\n")
        return testa.decode("latin-1"), corpo

    # ── A) /robots.txt ────────────────────────────────────────────────────────
    def test_robots_txt(self):
        s, hd, b = self.req("GET", "/robots.txt")
        self.assertEqual(s, 200)
        self.assertTrue(hd.get("content-type", "").startswith("text/plain"))
        self.assertTrue(hd.get("etag"))
        self.assertIn("User-agent: *", b)
        self.assertIn("Allow: /", b)
        # VALORE VERO: le 4 sitemap dichiarate sono URL ASSOLUTI del nostro dominio
        for sm in ("/sitemap-index.xml", "/sitemap.xml", "/sitemap-host.xml",
                   "/sitemap-blog.xml"):
            self.assertIn("Sitemap: " + self.BASE + sm, b)

    # ── B) /sitemap.xml ───────────────────────────────────────────────────────
    def test_sitemap_xml(self):
        s, hd, b = self.req("GET", "/sitemap.xml")
        self.assertEqual(s, 200)
        self.assertTrue(hd.get("content-type", "").startswith("application/xml"))
        self.assertTrue(b.startswith('<?xml version="1.0" encoding="UTF-8"?>'))
        self.assertIn('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">', b)
        # VALORE VERO: l'annuncio pubblicato davvero e' dentro, con lastmod di oggi
        self.assertIn("<loc>%s/alloggio/casa-http</loc>" % self.BASE, b)
        self.assertIn("<lastmod>%s</lastmod>" % datetime.date.today().isoformat(), b)
        self.assertEqual(b.count("<url>"), b.count("</url>"))

    def test_sitemap_etag_condizionale(self):
        """Crawl budget: stesso ETag rimandato -> 304 senza corpo."""
        s, hd, _b = self.req("GET", "/sitemap.xml")
        self.assertEqual(s, 200)
        etag = hd.get("etag")
        self.assertTrue(etag)
        s2, hd2, b2 = self.req("GET", "/sitemap.xml", {"If-None-Match": etag})
        self.assertEqual(s2, 304)
        self.assertEqual(b2, "")

    # ── C) /feed.xml (+ alias /rss, /rss.xml) ─────────────────────────────────
    def test_feed_rss(self):
        for path in ("/feed.xml", "/rss", "/rss.xml"):
            s, hd, b = self.req("GET", path)
            self.assertEqual(s, 200, path)
            self.assertTrue(hd.get("content-type", "").startswith("application/rss+xml"), path)
            self.assertIn('<rss version="2.0">', b)
            self.assertIn("<title>BookinVIP — nuovi alloggi</title>", b)
            # VALORE VERO: gli annunci pubblicati sono voci del feed, col link assoluto
            self.assertIn("<link>%s/alloggio/casa-http</link>" % self.BASE, b)
            self.assertEqual(b.count("<item>"), 2, "attese 2 voci (i 2 annunci pubblicati)")

    # ── D) sitemap-index / sitemap-host / shard / sitemap-blog ────────────────
    def test_sitemap_index(self):
        s, hd, b = self.req("GET", "/sitemap-index.xml")
        self.assertEqual(s, 200)
        self.assertTrue(hd.get("content-type", "").startswith("application/xml"))
        self.assertIn("<sitemapindex", b)
        self.assertIn("<loc>%s/sitemap.xml</loc>" % self.BASE, b)
        self.assertIn("<loc>%s/sitemap-host-0.xml</loc>" % self.BASE, b)

    def test_sitemap_host_e_shard(self):
        for path in ("/sitemap-host.xml", "/sitemap-host-0.xml"):
            s, hd, b = self.req("GET", path)
            self.assertEqual(s, 200, path)
            self.assertTrue(hd.get("content-type", "").startswith("application/xml"), path)
            self.assertIn("<urlset", b)
            self.assertIn("/affitta/roma", b)
            self.assertGreater(b.count("<loc>"), 10, path)

    def test_sitemap_blog(self):
        from fase198_blog import ARTICOLI
        s, hd, b = self.req("GET", "/sitemap-blog.xml")
        self.assertEqual(s, 200)
        self.assertTrue(hd.get("content-type", "").startswith("application/xml"))
        self.assertIn("<urlset", b)
        for a in ARTICOLI:
            self.assertIn("%s/blog/%s</loc>" % (self.BASE, a["slug"]), b)

    # ── E) /llms.txt (guida per gli agenti AI) ────────────────────────────────
    def test_llms_txt(self):
        s, hd, b = self.req("GET", "/llms.txt")
        self.assertEqual(s, 200)
        self.assertTrue(hd.get("content-type", "").startswith("text/plain"))
        self.assertIn("BookinVIP", b)
        self.assertIn(self.BASE, b)
        self.assertGreater(len(b), 200)

    # ── F) /blog e /blog/<slug> ───────────────────────────────────────────────
    def test_blog_indice_e_articolo(self):
        from fase198_blog import ARTICOLI
        s, hd, b = self.req("GET", "/blog")
        self.assertEqual(s, 200)
        self.assertTrue(hd.get("content-type", "").startswith("text/html"))
        self.assertIn("<html", b.lower())
        for a in ARTICOLI:
            self.assertIn("/blog/" + str(a["slug"]), b)
        slug = str(ARTICOLI[0]["slug"])
        s, hd, b = self.req("GET", "/blog/" + slug)
        self.assertEqual(s, 200)
        self.assertTrue(hd.get("content-type", "").startswith("text/html"))
        titolo_it = ARTICOLI[0]["T"]["it"]["titolo"]
        self.assertIn(titolo_it[:25], b)
        # stesso articolo in inglese: la pagina cambia davvero lingua
        s, _hd, b_en = self.req("GET", "/blog/%s?lang=en" % slug)
        self.assertEqual(s, 200)
        self.assertIn(str(ARTICOLI[0]["T"]["en"]["titolo"])[:25], b_en)
        self.assertNotEqual(b, b_en)

    # ── G) /affitta/<citta> (landing host SEO) ────────────────────────────────
    def test_landing_affitta_citta(self):
        s, hd, b = self.req("GET", "/affitta/roma")
        self.assertEqual(s, 200)
        self.assertTrue(hd.get("content-type", "").startswith("text/html"))
        self.assertIn("Roma", b)
        self.assertIn("<html", b.lower())
        self.assertIn("canonical", b)

    # ── H) /.well-known/ai-plugin.json e /openapi.json ────────────────────────
    def test_manifest_agenti_ai(self):
        s, hd, b = self.req("GET", "/.well-known/ai-plugin.json")
        self.assertEqual(s, 200)
        self.assertTrue(hd.get("content-type", "").startswith("application/json"))
        d = json.loads(b)
        self.assertIsInstance(d, dict)
        self.assertTrue(d.get("name_for_model") or d.get("name_for_human"))
        self.assertIn(self.BASE, json.dumps(d))

    def test_openapi_json(self):
        s, hd, b = self.req("GET", "/openapi.json")
        self.assertEqual(s, 200)
        self.assertTrue(hd.get("content-type", "").startswith("application/json"))
        d = json.loads(b)
        self.assertTrue(str(d.get("openapi", "")).startswith("3."))
        self.assertIsInstance(d.get("paths"), dict)
        self.assertIn("/api/catalogo", d["paths"])

    # ── I) /ical/<token>.ics — il feed PUBBLICO letto da Booking/Airbnb ───────
    def test_ical_pubblico(self):
        s, hd, b = self.req("GET", self.ical_path)
        self.assertEqual(s, 200, self.ical_path)
        self.assertTrue(hd.get("content-type", "").startswith("text/calendar"))
        self.assertTrue(b.startswith("BEGIN:VCALENDAR"))
        self.assertIn("VERSION:2.0", b)
        self.assertTrue(b.rstrip("\r\n").endswith("END:VCALENDAR"))
        # VALORE VERO: il giorno chiuso dall'host e' un evento, con DTEND esclusivo
        compatto = self.giorno_chiuso.replace("-", "")
        domani = (datetime.date.fromisoformat(self.giorno_chiuso)
                  + datetime.timedelta(days=1)).isoformat().replace("-", "")
        self.assertIn("BEGIN:VEVENT", b)
        self.assertIn("DTSTART;VALUE=DATE:" + compatto, b)
        self.assertIn("DTEND;VALUE=DATE:" + domani, b)

    # ── L) /host/azione?t=... — Approva da un messaggio, un tocco ─────────────
    def test_azione_da_messaggio(self):
        s, hd, b = self.req("GET", self.azione_path)
        self.assertEqual(s, 200, self.azione_path)
        self.assertTrue(hd.get("content-type", "").startswith("text/html"))
        self.assertIn("Prenotazione approvata", b)
        # EFFETTO VERO: la richiesta non e' piu' in attesa (e' stata evasa davvero)
        info = self.sis.pagamenti_pendenti.info(self.riferimento)
        self.assertTrue(info is None or info.get("stato") != "in_attesa_host",
                        "la richiesta e' rimasta in_attesa_host: il link non ha agito")

    # ── M) IndexNow: il file di verifica della proprieta' ─────────────────────
    def test_indexnow_key_file(self):
        s, hd, b = self.req("GET", "/" + self.INDEXNOW_KEY + ".txt")
        self.assertEqual(s, 200)
        self.assertTrue(hd.get("content-type", "").startswith("text/plain"))
        self.assertEqual(b.strip(), self.INDEXNOW_KEY)

    # ── N) /stop — disiscrizione pubblica (obbligo di legge) ──────────────────
    def test_stop_disiscrizione(self):
        s, hd, b = self.req("GET", "/stop?e=" + quote("via@collaudo.it"))
        self.assertEqual(s, 200)
        self.assertTrue(hd.get("content-type", "").startswith("text/html"))
        self.assertIn("Disiscritto", b)
        # EFFETTO VERO E DUREVOLE: l'indirizzo e' scritto nel file di opt-out
        with open(os.environ["OUTREACH_OPTOUT_FILE"], encoding="utf-8") as f:
            self.assertIn("via@collaudo.it", json.load(f)["optout"])

    # ── O) /alloggio/<slug> — la scheda pubblica crawlabile ───────────────────
    def test_pagina_alloggio(self):
        s, hd, b = self.req("GET", "/alloggio/casa-http")
        self.assertEqual(s, 200)
        self.assertTrue(hd.get("content-type", "").startswith("text/html"))
        self.assertIn("Loft del collaudo", b)
        self.assertIn('rel="canonical" href="%s/alloggio/casa-http"' % self.BASE, b)
        self.assertIn('property="og:title"', b)
        self.assertIn("application/ld+json", b)

    # ── P) pagine di login pubbliche e pagine post-pagamento ──────────────────
    def test_pagine_login_e_post_pagamento(self):
        for path, atteso in (("/entra-host", "/api/host/login"),
                             ("/entra-admin", "/api/admin/login"),
                             ("/entra-bunker", "/api/bunker/login")):
            s, hd, b = self.req("GET", path)
            self.assertEqual(s, 200, path)
            self.assertIn("no-store", hd.get("cache-control", ""), path)
            self.assertIn(atteso, b, path)
        for path in ("/grazie", "/annullato"):
            s, hd, b = self.req("GET", path)
            self.assertEqual(s, 200, path)
            self.assertTrue(hd.get("content-type", "").startswith("text/html"), path)
            self.assertIn("<html", b.lower(), path)

    # ── P-bis) / (radice) — la vetrina servita dai file statici ───────────────
    def test_radice_serve_index(self):
        s, hd, b = self.req("GET", "/")
        self.assertEqual(s, 200)
        self.assertTrue(hd.get("content-type", "").startswith("text/html"))
        self.assertIn("<html", b.lower())

    # ── P-ter) /uploads/<file> — le foto caricate dall'host ───────────────────
    def test_uploads_serve_la_foto(self):
        s, hd, _b = self.req("GET", self.upload_path)
        self.assertEqual(s, 200, self.upload_path)
        self.assertEqual(hd.get("content-type"), "image/png")
        self.assertIn("max-age=", hd.get("cache-control", ""))
        # VALORE VERO: i byte serviti sono ESATTAMENTE quelli caricati
        c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=10)
        try:
            c.request("GET", self.upload_path)
            self.assertEqual(c.getresponse().read(), self.png)
        finally:
            c.close()

    # ── P-quater) /voucher, /ricevuta, /recensione (pagine da token firmato) ──
    def test_pagina_voucher(self):
        from fase59_concierge import codice_prenotazione
        s, hd, b = self.req("GET", "/voucher/" + quote(self.voucher) + "?lang=it")
        self.assertEqual(s, 200)
        self.assertTrue(hd.get("content-type", "").startswith("text/html"))
        self.assertIn("Prenotazione confermata", b)
        self.assertIn(codice_prenotazione(self.rif_pagato), b)
        # VALORE VERO: pagata -> il PIN di check-in e' sbloccato sulla pagina
        self.assertIn(self.sis.firma.pin_checkin(self.rif_pagato), b)
        self.assertIn("/ricevuta/", b)          # e il link alla ricevuta compare solo se pagata

    def test_pagina_ricevuta(self):
        from fase59_concierge import codice_prenotazione
        s, hd, b = self.req("GET", "/ricevuta/" + quote(self.voucher))
        self.assertEqual(s, 200, "la ricevuta di una prenotazione PAGATA deve esistere")
        self.assertTrue(hd.get("content-type", "").startswith("text/html"))
        self.assertIn("Ricevuta di pagamento", b)
        self.assertIn(codice_prenotazione(self.rif_pagato), b)
        self.assertIn("Loft del collaudo", b)
        self.assertIn("360.00 EUR", b)          # 2 notti x 18000 cents, al centesimo

    def test_ricevuta_solo_se_pagata(self):
        """Il verde qui sopra vale solo se il NON pagato e' escluso: una ricevuta emessa
        per soldi mai incassati sarebbe un documento falso. Stesso annuncio, altre date."""
        s, _hd, _b = self.req("GET", "/ricevuta/" + quote(self.voucher_non_pagato))
        self.assertEqual(s, 404, "ricevuta emessa per una prenotazione NON pagata")
        # il voucher pre-pagamento invece esiste, ma senza PIN (non si entra senza pagare)
        s, _hd, bv = self.req("GET", "/voucher/" + quote(self.voucher_non_pagato) + "?lang=it")
        self.assertEqual(s, 200)
        self.assertNotIn(self.sis.firma.pin_checkin(self.rif_non_pagato), bv)

    def test_pagina_recensione_prima_del_soggiorno(self):
        """Soggiorno non ancora concluso: la pagina esiste (200) e dice la verita' —
        il modulo NON si apre prima del check-out (recensioni solo verificate)."""
        s, hd, b = self.req("GET", "/recensione/" + quote(self.voucher) + "?lang=it")
        self.assertEqual(s, 200)
        self.assertTrue(hd.get("content-type", "").startswith("text/html"))
        self.assertIn("Loft del collaudo", b)
        self.assertIn("noindex", b)
        self.assertNotIn("/api/recensioni", b)

    def test_pagina_recensione_dopo_il_soggiorno(self):
        """Soggiorno concluso: la pagina apre il modulo di valutazione vero.
        Il voucher e' firmato dal sistema stesso (stesso segreto, stessa struttura di
        quello emesso al book): l'unica differenza e' che il check-out e' passato."""
        ieri = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        tok = self.sis.firma.codifica({
            "tipo": "voucher", "riferimento": self.rif_pagato,
            "alloggio_id": "casa-http", "check_in": (
                datetime.date.today() - datetime.timedelta(days=3)).isoformat(),
            "check_out": ieri, "valuta": "EUR", "lang": "it"})
        s, hd, b = self.req("GET", "/recensione/" + quote(tok) + "?lang=it")
        self.assertEqual(s, 200)
        self.assertTrue(hd.get("content-type", "").startswith("text/html"))
        self.assertIn("/api/recensioni", b)      # il modulo punta al motore recensioni vero
        self.assertIn("Loft del collaudo", b)

    # ── Q) HEAD e OPTIONS (monitor di uptime e preflight CORS) ────────────────
    def test_head_come_get_senza_corpo(self):
        # UNA per ciascuno dei QUATTRO scrittori di corpo dell'handler: JSON (_scrivi),
        # SEO con ETag (_testo_seo), testo semplice (_testo), file statico (_statico) e
        # foto caricata (_serve_upload). Coprirne uno solo lascia gli altri senza guardia.
        for path in ("/api/health", "/robots.txt", "/feed.xml", "/entra-host",
                     self.ical_path, "/", self.upload_path):
            sg, _hg, bg = self.req("GET", path)
            self.assertEqual(sg, 200, path)
            self.assertTrue(bg, path)
            testa, corpo = self._grezzo("HEAD", path)     # socket nudo: il corpo si vede
            self.assertIn(" 200 ", testa.split("\r\n")[0], path)
            self.assertIn("Content-Type:", testa, path)
            self.assertEqual(corpo, b"", "HEAD %s ha spedito un corpo (%d byte)"
                             % (path, len(corpo)))

    def test_options_preflight(self):
        s, hd, b = self.req("OPTIONS", "/api/health")
        self.assertEqual(s, 204)
        self.assertEqual(hd.get("access-control-allow-origin"), "*")
        self.assertEqual(b, "")

    # ── R) la sonda di salute risponde anche via HTTP (cablaggio completo) ────
    def test_health_via_http(self):
        for path, atteso in (("/api/health", "ok"), ("/api/health/live", "live"),
                             ("/api/health/ready", "ready")):
            s, hd, b = self.req("GET", path)
            self.assertEqual(s, 200, path)
            self.assertTrue(hd.get("content-type", "").startswith("application/json"), path)
            self.assertEqual(json.loads(b).get("status"), atteso, path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
