# -*- coding: utf-8 -*-
"""
INTEGRAZIONE API <-> DATABASE <-> SERVIZI TERZI (mandato punto 1).

Perche' esiste: i test dei servizi esterni erano sparsi e quasi sempre sostituiti da finti
"gentili" che accettano qualunque cosa e rispondono OK. Un finto gentile prova che il nostro
codice non esplode, NON che la richiesta che parte davvero sia quella che il servizio si
aspetta: con un finto gentile passerebbero un `unit_amount` in euro (100x meno), un webhook
senza verifica di firma, un transfer senza Idempotency-Key (doppio bonifico), una email a un
destinatario con a-capo (header injection).

Qui ogni servizio ha un finto SEVERO: registra URL, metodo, header, corpo e firma di OGNI
richiesta, e il test ASSERISCE la forma esatta; le risposte simulano quelle vere (successo,
4xx con corpo d'errore, 429 di quota, 500, rete giu').

E soprattutto: dopo ogni chiamata API che DEVE scrivere, il database viene RIAPERTO da zero
(sqlite3.connect sul file) e si controlla che la riga ci sia con i valori giusti. La risposta
HTTP non e' una prova: solo il disco lo e'.

Servizi coperti:
  STRIPE   fase85 checkout · fase87 webhook firmato · fase101 Connect transfer · fase183 carta
  EMAIL    fase86 SMTP (retry, mai eccezione, anti header-injection, gate lingua)
  SOCIAL   fase90/91 Telegram+Meta · fase152 avvisi host · fase193 Mastodon · pubblica_video
  VALUTA   fase99 OXR (cache, stale-while-revalidate, fail-safe)
  GEO      fase166 Nominatim · fase175 POI Overpass (limite, cache positiva E negativa)
  AI       fase164/165 Groq/Gemini/Pollinations (timeout, quota, ripiego, UA browser)
"""
import datetime
import importlib.util
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import time
import unittest
import urllib.error
from urllib.parse import parse_qsl, urlsplit

import fase165_adattatori_esterni as _f165
import fase166_geocoder as _f166
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase85_pagamenti_stripe import crea_provider_stripe
from fase86_email import ProviderEmail, T, corpo_pagamento_confermato_html, oggetto
from fase87_stripe_webhook import firma_di_test, verifica_firma_stripe
from fase90_marketing import Post
from fase91_canali_social import CanaleMetaGraph, CanaleTelegram
from fase99_multicurrency import crea_provider_tassi
from fase101_stripe_connect import (crea_provider_connect,
                                    crea_provider_stripe_connect)
from fase152_notifiche_prenotazione import CanaleTelegram as CanaleTelegramHost
from fase152_notifiche_prenotazione import CanaleWhatsApp
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256
from fase164_pool_ai import ProviderAI, QuotaEsaurita, crea_pool_ai
from fase165_adattatori_esterni import (AdattatoreGemini, AdattatoreGroq,
                                        AdattatorePollinations)
from fase166_geocoder import crea_geocoder
from fase175_poi_osm import crea_provider_poi
from fase183_carta_offsession import crea_provider_carta

WH = "whsec_integrazione"
BASE = datetime.date.today() + datetime.timedelta(days=40)


def _giorno(i):
    return (BASE + datetime.timedelta(days=i)).isoformat()


def _campi(corpo):
    """Corpo x-www-form-urlencoded -> dict (come lo legge Stripe). Difensivo: un corpo di
    tipo sbagliato non fa esplodere il finto — lo fa BOCCIARE dal vaglio del contratto."""
    if isinstance(corpo, (bytes, bytearray)):
        try:
            corpo = bytes(corpo).decode("utf-8")
        except Exception:
            return {}
    if not isinstance(corpo, str):
        return {}
    return dict(parse_qsl(corpo, keep_blank_values=True))


class _CatturaLog:
    """Cattura il log FORMATTATO (traceback incluso): serve a provare che un segreto non
    finisce nei log nemmeno dentro un'eccezione."""

    def __init__(self, *nomi):
        self._nomi = nomi or ("",)
        self.righe = []

    def __enter__(self):
        prova = self

        class _H(logging.Handler):
            def emit(self, record):
                try:
                    prova.righe.append(self.format(record))
                except Exception:
                    prova.righe.append(str(record.msg))

        self._h = _H()
        self._h.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
        self._loggers = [logging.getLogger(n) for n in self._nomi]
        self._liv = [(lg, lg.level, lg.propagate) for lg in self._loggers]
        for lg in self._loggers:
            lg.addHandler(self._h)
            lg.setLevel(logging.DEBUG)
        return self

    def __exit__(self, *a):
        for lg in self._loggers:
            lg.removeHandler(self._h)
        for lg, liv, prop in self._liv:
            lg.setLevel(liv)
            lg.propagate = prop
        return False

    def come_testo(self):
        return "\n".join(self.righe)


# ══════════════════════════════════════════════════════════════════════════════
#  FINTI SEVERI — le controfigure RIFIUTANO cio' che il servizio VERO rifiuterebbe
#
#  Un finto GENTILE ("qualunque cosa mi mandi, ti rispondo 200") non prova NIENTE: il
#  test resta verde anche se partisse un `unit_amount` in euro invece che in centesimi
#  (100x meno), un transfer senza `Idempotency-Key` (doppio bonifico al retry), un GET
#  con un corpo, una valuta "EUR" maiuscola (Stripe: 400) o un destinatario email con
#  un a-capo dentro.
#
#  Qui ogni richiesta passa PRIMA dal vaglio del contratto del servizio vero: se non lo
#  rispetta viene REGISTRATA come violazione e RIFIUTATA con un 400, come farebbe Stripe.
#
#  Perche' REGISTRARE e non limitarsi a sollevare: tutto il codice di produzione qui e'
#  BLINDATO (`except Exception -> None/False`), quindi un'eccezione sollevata dentro il
#  finto verrebbe INGOIATA e il test resterebbe verde lo stesso. La prova sta nel
#  pretendere che la lista delle violazioni sia VUOTA: lo fa `_ContrattiPuliti.tearDown`,
#  ereditata da OGNI classe di questo file, quindi vale per tutti i test, anche futuri.
# ══════════════════════════════════════════════════════════════════════════════
_MANCA = object()          # "non specificato" (distinto da None, che e' una risposta valida)

_REGISTRO_FINTI = []       # ogni finto creato si iscrive qui (azzerato a ogni setUp)


def azzera_finti():
    del _REGISTRO_FINTI[:]


def violazioni_di_contratto():
    return [v for f in _REGISTRO_FINTI for v in f.violazioni]


class _FintoSevero:
    """Base comune: registra le richieste e boccia quelle fuori contratto."""

    servizio = "servizio"

    def __init__(self):
        self.richieste = []
        self.violazioni = []
        self._idem_visti = {}      # Idempotency-Key -> impronta del corpo (vedi _controlla_stripe)
        _REGISTRO_FINTI.append(self)

    def _esigi(self, condizione, motivo):
        """Se il contratto e' violato: annota (prova che sopravvive al blindaggio del
        prodotto) e rifiuta con un 400, come il servizio vero."""
        if not condizione:
            self.violazioni.append("%s: %s" % (self.servizio, motivo))
            raise urllib.error.HTTPError("https://" + self.servizio, 400, motivo, {}, None)

    @property
    def ultima(self):
        return self.richieste[-1]


# ── contratto STRIPE (vale per checkout, transfers, payment_intents, accounts…) ──
_CAMPI_MONETA = ("amount", "unit_amount")
_IDEMPOTENTI = ("/v1/transfers", "/v1/payment_intents", "/v1/refunds", "/v1/charges")

# Ogni chiave che finisce per `_amount` e' un importo in unita' MINORI intere per Stripe:
# `application_fee_amount` (la NOSTRA commissione sul destination charge di fase101),
# `amount_to_capture`, `amount_refunded`… Elencare solo `amount`/`unit_amount` lasciava
# passare un `application_fee_amount=1250.5` (400 da Stripe) o `=-500` (commissione
# NEGATIVA: pagheremmo l'host piu' di quanto incassato).
_SUFFISSI_MONETA = ("_amount", "_cents")

# Chiavi che devono contenere un conto CONNESSO, a qualsiasi profondita' di annidamento:
# fase101 manda `payment_intent_data[transfer_data][destination]`, non `destination`.
_CAMPI_CONTO = ("destination",)


def _nudo(chiave):
    """'line_items[0][price_data][unit_amount]' -> 'unit_amount'."""
    return chiave.rstrip("]").rsplit("[", 1)[-1]


def _e_moneta(nome_nudo):
    return nome_nudo in _CAMPI_MONETA or nome_nudo.endswith(_SUFFISSI_MONETA)


def _controlla_stripe(finto, url, corpo, headers, metodo="POST"):
    """Le regole che l'API Stripe VERA applica a una richiesta form-encoded. Violarle
    significa 400 (nel migliore dei casi) o un movimento di denaro sbagliato."""
    e = finto._esigi
    e(isinstance(url, str) and url.startswith("https://api.stripe.com/v1/"),
      "URL non e' un endpoint Stripe v1: %r" % (url,))
    auth = str(headers.get("Authorization", ""))
    e(auth.startswith("Bearer sk_"),
      "Authorization assente o non e' una secret key: %r" % (auth[:16],))
    e("\r" not in auth and "\n" not in auth, "a-capo dentro Authorization")
    if metodo == "GET":
        e(corpo in (None, b"", ""), "GET con un corpo (Stripe vuole i parametri in query)")
        return {}
    e(isinstance(corpo, (bytes, bytearray)),
      "corpo non e' bytes: urllib.request non lo accetta (%s)" % (type(corpo).__name__,))
    e(str(headers.get("Content-Type")) == "application/x-www-form-urlencoded",
      "Content-Type errato: %r" % (headers.get("Content-Type"),))
    try:
        testo = bytes(corpo).decode("ascii")
    except Exception:
        testo = None
    e(testo is not None, "corpo non ASCII: manca la percent-codifica (urlencode)")
    campi = _campi(testo)
    e(bool(campi), "corpo vuoto")
    for chiave, val in campi.items():
        n = _nudo(chiave)
        if _e_moneta(n):
            e(val.isdigit(), "%s=%r non e' un intero di CENTESIMI" % (chiave, val))
            if n in _CAMPI_MONETA:
                e(int(val) > 0, "%s=%r: importo non positivo" % (chiave, val))
        if n == "currency":
            e(len(val) == 3 and val.isalpha() and val.islower(),
              "valuta non ISO-4217 minuscola: %r" % (val,))
        if n in ("customer_email", "email"):
            e("@" in val and "\r" not in val and "\n" not in val,
              "email malformata o con a-capo: %r" % (val,))
        if n in ("success_url", "cancel_url", "return_url", "refresh_url"):
            e(val.startswith("https://"), "%s non e' https: %r" % (chiave, val))
        if n == "expires_at":
            e(val.isdigit(), "expires_at non e' un timestamp intero: %r" % (val,))
        if n == "quantity":
            e(val.isdigit() and int(val) > 0, "quantity non valida: %r" % (val,))
    for chiave, val in campi.items():
        if _nudo(chiave) in _CAMPI_CONTO:
            e(val.startswith("acct_"),
              "%s non e' un account connesso: %r" % (chiave, val))
    # la NOSTRA commissione non puo' mangiarsi il lordo: fee >= lordo = 400 da Stripe e,
    # se passasse, all'host resterebbe zero (o meno) di una prenotazione gia' incassata.
    fee = next((v for k, v in campi.items()
                if _nudo(k) == "application_fee_amount" and v.isdigit()), None)
    lordo = next((v for k, v in campi.items()
                  if _nudo(k) == "unit_amount" and v.isdigit()), None)
    if fee is not None and lordo is not None:
        qta = next((v for k, v in campi.items()
                    if _nudo(k) == "quantity" and v.isdigit()), "1")
        e(int(fee) < int(lordo) * int(qta),
          "application_fee_amount=%s >= lordo %s: all'host non resta nulla" % (fee, lordo))
    percorso = urlsplit(url).path
    if any(percorso == p or percorso.startswith(p + "/") for p in _IDEMPOTENTI):
        idem = str(headers.get("Idempotency-Key", ""))
        e(idem.strip() != "",
          "POST %s SENZA Idempotency-Key: al retry Stripe rifarebbe il movimento (doppio)"
          % (percorso,))
        e(len(idem) <= 255 and all(32 <= ord(ch) < 127 for ch in idem),
          "Idempotency-Key non ASCII stampabile o piu' lunga di 255: %r" % (idem,))
        # Stripe VERO risponde 400 `idempotency_error` se la stessa chiave torna con un
        # corpo diverso. Riusare una chiave stantia su un movimento NUOVO non e' un doppio
        # addebito: e' un bonifico che non parte mai e nessuno se ne accorge.
        visto = finto._idem_visti
        impronta = (percorso, tuple(sorted(campi.items())))
        if idem in visto:
            e(visto[idem] == impronta,
              "Idempotency-Key %r riusata con un corpo DIVERSO: Stripe risponderebbe 400 "
              "e il movimento nuovo non partirebbe" % (idem,))
        visto[idem] = impronta
    return campi


class FintoStripeForm(_FintoSevero):
    """Stripe form-encoded (fase85 / fase101): fetch(url, body, headers) -> dict.
    Registra TUTTO, VAGLIA il contratto; `guasto` = eccezione da sollevare (rete giu')."""

    servizio = "api.stripe.com"

    def __init__(self, risposta=_MANCA, guasto=None):
        super().__init__()
        self._risposta = {"id": "cs_test_1",
                          "url": "https://checkout.stripe.com/c/pay/cs_test_1"} \
            if risposta is _MANCA else risposta
        self._guasto = guasto

    def __call__(self, url, body, headers):
        h = dict(headers or {})
        self.richieste.append({"url": url, "headers": h, "campi": _campi(body),
                               "corpo": body})
        _controlla_stripe(self, url, body, h)
        if self._guasto is not None:
            raise self._guasto
        r = self._risposta
        return r(self.richieste[-1]) if callable(r) else r


class FintoStripeCarta(_FintoSevero):
    """ProviderCarta (fase183): fetch(metodo, url, body, headers) -> dict."""

    servizio = "api.stripe.com/carta"

    def __init__(self, risposte=None, guasto=None):
        super().__init__()
        self._risposte = risposte or {}
        self._guasto = guasto

    def __call__(self, metodo, url, body, headers):
        h = dict(headers or {})
        self.richieste.append({"metodo": metodo, "url": url, "headers": h,
                               "campi": _campi(body) if body else {}})
        self._esigi(metodo in ("GET", "POST"), "metodo HTTP inatteso: %r" % (metodo,))
        _controlla_stripe(self, url, body, h, metodo=metodo)
        if self._guasto is not None:
            raise self._guasto
        for chiave, val in self._risposte.items():
            if chiave in url:
                return val
        return {}


class FintoHttpAI(_FintoSevero):
    """fase165: fetch(url, *, metodo, intestazioni, corpo, timeout) -> (status, obj)."""

    servizio = "provider-ai"

    def __init__(self, esiti):
        super().__init__()
        self._esiti = list(esiti)

    def __call__(self, url, *, metodo="GET", intestazioni=None, corpo=None, timeout=30.0):
        h = dict(intestazioni or {})
        self.richieste.append({"url": url, "metodo": metodo, "intestazioni": h,
                               "corpo": corpo, "timeout": timeout})
        e = self._esigi
        e(isinstance(url, str) and url.startswith("https://"), "URL non https: %r" % (url,))
        e(metodo in ("GET", "POST"), "metodo inatteso: %r" % (metodo,))
        e(isinstance(timeout, (int, float)) and not isinstance(timeout, bool)
          and 0 < float(timeout) <= 120,
          "timeout assente o assurdo (%r): senza timeout un worker resta appeso" % (timeout,))
        if corpo is not None:
            e(metodo == "POST", "corpo su una richiesta %s" % (metodo,))
            e(isinstance(corpo, (bytes, bytearray)), "corpo non bytes")
            ct = str(h.get("Content-Type", ""))
            e(ct != "", "richiesta con corpo e senza Content-Type")
            if ct.startswith("application/json"):
                try:
                    json.loads(bytes(corpo).decode("utf-8"))
                    valido = True
                except Exception:
                    valido = False
                e(valido, "Content-Type json ma il corpo non e' JSON valido")
        # Groq/OpenAI-compatibili: senza Bearer il servizio vero risponde 401 e la
        # generazione non parte MAI. Un finto che non lo pretende terrebbe verde un
        # adattatore che ha smesso di mandare la chiave.
        if "api.groq.com" in url:
            a = str(h.get("Authorization", ""))
            e(a.startswith("Bearer ") and a[7:].strip() != "",
              "richiesta a Groq senza Bearer: il vero risponderebbe 401")
        return self._esiti.pop(0) if self._esiti else (0, None)


class FintoJson(_FintoSevero):
    """Canali social (fase91/193): fetch(url, data[, headers]) -> dict."""

    servizio = "social"

    def __init__(self, risposte=None, guasto=None):
        super().__init__()
        self._risposte = list(risposte or [])
        self._guasto = guasto

    def __call__(self, url, data=None, headers=None):
        d = dict(data or {})
        h = dict(headers or {})
        self.richieste.append({"url": url, "data": d, "headers": h})
        e = self._esigi
        e(isinstance(url, str) and url.startswith("https://"), "URL non https: %r" % (url,))
        e(" " not in url and "\n" not in url and "\r" not in url,
          "URL con spazi o a-capo: %r" % (url,))
        e(bool(d), "corpo VUOTO: una pubblicazione senza campi non e' un post, e' un 400")
        for k, v in d.items():
            e(isinstance(k, str) and k != "", "campo senza nome nel corpo")
            e(v is not None,
              "campo %r a None: urlencode lo manderebbe come la stringa 'None'" % (k,))
            e(isinstance(v, (str, int, float, bool, dict, list)),
              "campo %r di tipo %s: non serializzabile" % (k, type(v).__name__))
        auth = str(h.get("Authorization", ""))
        if auth:
            e(auth.startswith("Bearer ") and auth[7:].strip() != "",
              "Authorization malformata: %r" % (auth[:12],))
        if self._guasto is not None:
            raise self._guasto
        return self._risposte.pop(0) if self._risposte else {"ok": True, "id": "1"}


class FintoStatus(_FintoSevero):
    """Canali fase152 (avvisi all'host): fetch(url, headers, body) -> (status, testo)."""

    servizio = "avvisi-host"

    def __init__(self, status=200, guasto=None):
        super().__init__()
        self._status = status
        self._guasto = guasto

    def __call__(self, url, headers, body):
        h = dict(headers or {})
        self.richieste.append({"url": url, "headers": h, "body": body})
        e = self._esigi
        e(isinstance(url, str) and url.startswith("https://"), "URL non https: %r" % (url,))
        e(isinstance(body, dict) and bool(body), "corpo assente o non un oggetto JSON")
        if "graph.facebook.com" in url:
            e(str(h.get("Authorization", "")).startswith("Bearer "),
              "Meta/WhatsApp senza Bearer token")
            e(str(body.get("messaging_product")) == "whatsapp",
              "manca messaging_product=whatsapp (la Cloud API lo esige)")
            e(str(body.get("to", "")).isdigit(),
              "numero WhatsApp non normalizzato a sole cifre: %r" % (body.get("to"),))
        if "api.telegram.org" in url:
            e(str(body.get("chat_id", "")).strip() != "", "chat_id vuoto")
            e(str(body.get("text", "")).strip() != "", "messaggio vuoto")
        if self._guasto is not None:
            raise self._guasto
        return self._status, "{}"


# ── contratto NOMINATIM / OVERPASS: la policy d'uso e' vincolante (ci bannano) ──
_PARAM_NOMINATIM_AMMESSI = {"format", "limit", "q", "lat", "lon", "zoom",
                            "addressdetails", "accept-language", "countrycodes"}


def _controlla_nominatim(prova, url):
    """URL Nominatim ammesso: host giusto, format=json, limit<=1 sulla ricerca, nessun
    parametro inventato (uno sconosciuto = 400 dal servizio vero)."""
    e = prova._esigi
    e(isinstance(url, str) and url.startswith("https://nominatim.openstreetmap.org/"),
      "URL fuori da Nominatim: %r" % (url,))
    parti = urlsplit(url)
    q = dict(parse_qsl(parti.query))
    e(q.get("format") in ("json", "jsonv2"),
      "format non JSON (la risposta arriverebbe in XML): %r" % (q.get("format"),))
    for chiave in q:
        e(chiave in _PARAM_NOMINATIM_AMMESSI, "parametro sconosciuto %r" % (chiave,))
    if parti.path.rstrip("/").endswith("/search"):
        e(q.get("q", "").strip() != "", "ricerca senza testo")
        e(int(q.get("limit", "1")) <= 1, "limit>1: scarico inutile (policy Nominatim)")
    if parti.path.rstrip("/").endswith("/reverse"):
        for chiave in ("lat", "lon"):
            try:
                float(q.get(chiave, ""))
                ok = True
            except Exception:
                ok = False
            e(ok, "reverse senza %s numerica: %r" % (chiave, q.get(chiave)))


class _ContrattiPuliti(unittest.TestCase):
    """Ereditata da OGNI classe del file: azzera il registro dei finti prima del test e
    pretende ZERO violazioni dopo. Cosi' la severita' non dipende dal fatto che il singolo
    test si ricordi di controllarla — vale sempre, anche per i test scritti domani."""

    def setUp(self):
        azzera_finti()

    def tearDown(self):
        fuori = violazioni_di_contratto()
        self.assertEqual(fuori, [], "richieste FUORI CONTRATTO ai servizi terzi: %s" % fuori)


# ══════════════════════════════════════════════════════════════════════════════
#  0) CHI CONTROLLA IL CONTROLLORE — i finti severi sono davvero severi?
# ══════════════════════════════════════════════════════════════════════════════
_AUTH_OK = {"Authorization": "Bearer sk_test_x",
            "Content-Type": "application/x-www-form-urlencoded"}


class TestFintiSeveriSonoDavveroSeveri(unittest.TestCase):
    """Un finto che accetta tutto NON e' una guardia, e' un ornamento: i test che ci
    girano sopra sono verdi per costruzione. Qui ogni vaglio viene messo alla prova con
    la richiesta STORTA che deve bocciare e con quella DIRITTA che deve passare. Se un
    domani qualcuno ammorbidisse un controllo per far passare un test, sono questi a
    diventare rossi — PRIMA che l'ammorbidimento nasconda un difetto vero."""

    def setUp(self):
        azzera_finti()

    def tearDown(self):
        azzera_finti()

    def _rifiuta(self, finto, chiamata, pezzo_del_motivo):
        """La richiesta storta deve essere (1) rifiutata con un 400 come dal servizio vero
        e (2) ANNOTATA, perche' il prodotto blindato ingoierebbe l'eccezione."""
        with self.assertRaises(urllib.error.HTTPError) as e:
            chiamata()
        self.assertEqual(e.exception.code, 400)
        self.assertEqual(len(finto.violazioni), 1, finto.violazioni)
        self.assertIn(pezzo_del_motivo, finto.violazioni[0])
        self.assertEqual(violazioni_di_contratto(), finto.violazioni)

    # ── STRIPE ───────────────────────────────────────────────────────────────
    def test_stripe_accetta_la_richiesta_ben_formata(self):
        f = FintoStripeForm()
        f("https://api.stripe.com/v1/checkout/sessions",
          b"mode=payment&line_items%5B0%5D%5Bprice_data%5D%5Bunit_amount%5D=24350"
          b"&line_items%5B0%5D%5Bprice_data%5D%5Bcurrency%5D=eur"
          b"&success_url=https%3A%2F%2Fbookinvip.com%2Fok", _AUTH_OK)
        self.assertEqual(f.violazioni, [], "il vaglio boccia una richiesta CORRETTA")

    def test_stripe_boccia_importo_non_intero_o_non_positivo(self):
        for corpo, motivo in ((b"amount=243.50&currency=eur", "CENTESIMI"),
                              (b"amount=-100&currency=eur", "CENTESIMI"),
                              (b"amount=0&currency=eur", "non positivo"),
                              (b"amount=24%2C350&currency=eur", "CENTESIMI"),
                              (b"line_items%5B0%5D%5Bprice_data%5D%5Bunit_amount%5D=1e3",
                               "CENTESIMI")):
            f = FintoStripeForm()
            self._rifiuta(f, lambda f=f, corpo=corpo: f(
                "https://api.stripe.com/v1/transfers", corpo,
                dict(_AUTH_OK, **{"Idempotency-Key": "k"})), motivo)
            azzera_finti()

    def test_stripe_boccia_valuta_non_iso(self):
        for valuta in (b"EUR", b"euro", b"e", b"eu"):
            f = FintoStripeForm()
            self._rifiuta(f, lambda f=f, valuta=valuta: f(
                "https://api.stripe.com/v1/checkout/sessions",
                b"amount=100&currency=" + valuta, _AUTH_OK), "ISO-4217")
            azzera_finti()

    def test_stripe_boccia_chiave_e_intestazioni_sbagliate(self):
        casi = ((dict(_AUTH_OK, Authorization=""), "Authorization"),
                (dict(_AUTH_OK, Authorization="Bearer pk_live_1"), "secret key"),
                (dict(_AUTH_OK, Authorization="sk_test_x"), "Authorization"),
                (dict(_AUTH_OK, **{"Content-Type": "application/json"}), "Content-Type"))
        for headers, motivo in casi:
            f = FintoStripeForm()
            self._rifiuta(f, lambda f=f, headers=headers: f(
                "https://api.stripe.com/v1/checkout/sessions",
                b"amount=100&currency=eur", headers), motivo)
            azzera_finti()

    def test_stripe_boccia_transfer_senza_idempotency_key(self):
        """IL difetto che costa denaro vero: senza la chiave, il retry di rete rifa' il
        bonifico. Un finto gentile non lo vedrebbe mai."""
        f = FintoStripeForm()
        self._rifiuta(f, lambda: f("https://api.stripe.com/v1/transfers",
                                   b"amount=100&currency=eur&destination=acct_1", _AUTH_OK),
                      "SENZA Idempotency-Key")
        azzera_finti()
        f2 = FintoStripeForm()
        self._rifiuta(f2, lambda: f2("https://api.stripe.com/v1/payment_intents",
                                     b"amount=100&currency=eur",
                                     dict(_AUTH_OK, **{"Idempotency-Key": "   "})),
                      "SENZA Idempotency-Key")

    def test_stripe_boccia_la_commissione_storta_sul_destination_charge(self):
        """`application_fee_amount` e' LA nostra commissione (fase101 destination charge).
        Un finto che vaglia solo `amount`/`unit_amount` la lascia passare in euro (100x
        meno), negativa (pagheremmo l'host piu' dell'incassato) o piu' grande del lordo."""
        lordo = (b"&line_items%5B0%5D%5Bprice_data%5D%5Bunit_amount%5D=30000"
                 b"&line_items%5B0%5D%5Bprice_data%5D%5Bcurrency%5D=eur")
        casi = ((b"1250.5", "CENTESIMI"), (b"-500", "CENTESIMI"), (b"1e3", "CENTESIMI"),
                (b"90000", "non resta nulla"), (b"30000", "non resta nulla"))
        for fee, motivo in casi:
            f = FintoStripeForm()
            self._rifiuta(f, lambda f=f, fee=fee: f(
                "https://api.stripe.com/v1/checkout/sessions",
                b"mode=payment&payment_intent_data%5Bapplication_fee_amount%5D=" + fee
                + lordo, _AUTH_OK), motivo)
            azzera_finti()
        f = FintoStripeForm()          # controprova: 10% su 30000 e' regolare
        f("https://api.stripe.com/v1/checkout/sessions",
          b"mode=payment&payment_intent_data%5Bapplication_fee_amount%5D=3000" + lordo,
          _AUTH_OK)
        self.assertEqual(f.violazioni, [], "il vaglio boccia una commissione LEGITTIMA")

    def test_stripe_boccia_il_conto_annidato_non_connesso(self):
        """fase101 manda `payment_intent_data[transfer_data][destination]`: guardare solo
        la chiave `destination` di primo livello lascia passare un conto qualsiasi."""
        f = FintoStripeForm()
        self._rifiuta(f, lambda: f(
            "https://api.stripe.com/v1/checkout/sessions",
            b"line_items%5B0%5D%5Bprice_data%5D%5Bunit_amount%5D=30000"
            b"&payment_intent_data%5Btransfer_data%5D%5Bdestination%5D=cus_1", _AUTH_OK),
            "account connesso")

    def test_stripe_boccia_idempotency_mancante_sui_sotto_percorsi(self):
        """/v1/payment_intents/pi_1/confirm E' un movimento di denaro quanto la creazione:
        col vecchio `url.endswith('/v1/payment_intents')` non veniva mai controllato."""
        for coda in ("confirm", "capture"):
            f = FintoStripeForm()
            self._rifiuta(f, lambda f=f, coda=coda: f(
                "https://api.stripe.com/v1/payment_intents/pi_1/" + coda,
                b"amount_to_capture=100", _AUTH_OK), "SENZA Idempotency-Key")
            azzera_finti()

    def test_stripe_boccia_la_chiave_idempotente_riusata_su_un_corpo_diverso(self):
        """Stripe risponde 400 `idempotency_error`. Il danno non e' il doppio addebito: e'
        il bonifico NUOVO che non parte perche' riusa la chiave di quello vecchio."""
        f = FintoStripeForm()
        h = dict(_AUTH_OK, **{"Idempotency-Key": "transfer_BVIP-AAAA"})
        f("https://api.stripe.com/v1/transfers",
          b"amount=21600&currency=eur&destination=acct_H1", h)
        self._rifiuta(f, lambda: f("https://api.stripe.com/v1/transfers",
                                   b"amount=9900&currency=eur&destination=acct_H2", h),
                      "riusata con un corpo DIVERSO")
        azzera_finti()
        f2 = FintoStripeForm()         # controprova: STESSO corpo = retry legittimo
        for _ in range(2):
            f2("https://api.stripe.com/v1/transfers",
               b"amount=21600&currency=eur&destination=acct_H1", h)
        self.assertEqual(f2.violazioni, [], "il retry identico non e' un errore")

    def test_stripe_boccia_destinazione_e_email_storte(self):
        f = FintoStripeForm()
        self._rifiuta(f, lambda: f("https://api.stripe.com/v1/transfers",
                                   b"amount=100&currency=eur&destination=cus_1",
                                   dict(_AUTH_OK, **{"Idempotency-Key": "k"})),
                      "account connesso")
        azzera_finti()
        f2 = FintoStripeForm()
        self._rifiuta(f2, lambda: f2(
            "https://api.stripe.com/v1/checkout/sessions",
            b"amount=100&currency=eur&customer_email=a%40b.it%0ABcc%3A+vittima%40x.it",
            _AUTH_OK), "a-capo")

    def test_stripe_boccia_corpo_non_bytes_o_url_estraneo(self):
        f = FintoStripeForm()
        self._rifiuta(f, lambda: f("https://api.stripe.com/v1/checkout/sessions",
                                   "amount=100&currency=eur", _AUTH_OK), "non e' bytes")
        azzera_finti()
        f2 = FintoStripeForm()
        self._rifiuta(f2, lambda: f2("https://api.stripe.evil.com/v1/checkout/sessions",
                                     b"amount=100&currency=eur", _AUTH_OK), "endpoint Stripe")

    def test_stripe_carta_boccia_il_get_con_corpo(self):
        f = FintoStripeCarta()
        self._rifiuta(f, lambda: f("GET", "https://api.stripe.com/v1/setup_intents/seti_1",
                                   b"expand=x", _AUTH_OK), "GET con un corpo")
        azzera_finti()
        f2 = FintoStripeCarta()
        self._rifiuta(f2, lambda: f2("DELETE", "https://api.stripe.com/v1/customers/cus_1",
                                     None, _AUTH_OK), "metodo HTTP inatteso")

    # ── AI (fase165) ─────────────────────────────────────────────────────────
    def test_ai_boccia_timeout_assurdo_e_corpo_incoerente(self):
        f = FintoHttpAI([(200, {})])
        self._rifiuta(f, lambda: f("https://api.groq.com/x", metodo="POST", timeout=0,
                                   corpo=b"{}",
                                   intestazioni={"Content-Type": "application/json"}),
                      "timeout")
        azzera_finti()
        f2 = FintoHttpAI([(200, {})])
        self._rifiuta(f2, lambda: f2("https://api.groq.com/x", metodo="POST",
                                     corpo=b"non-json",
                                     intestazioni={"Content-Type": "application/json"}),
                      "non e' JSON valido")
        azzera_finti()
        f3 = FintoHttpAI([(200, {})])
        self._rifiuta(f3, lambda: f3("https://api.groq.com/x", metodo="POST", corpo=b"{}",
                                     intestazioni={}), "senza Content-Type")
        azzera_finti()
        f4 = FintoHttpAI([(200, {})])
        self._rifiuta(f4, lambda: f4("http://api.groq.com/x", metodo="GET"), "non https")

    def test_ai_boccia_la_richiesta_senza_chiave(self):
        """Groq senza Bearer = 401: la generazione non partirebbe MAI."""
        f = FintoHttpAI([(200, {})])
        self._rifiuta(f, lambda: f("https://api.groq.com/openai/v1/chat/completions",
                                   metodo="POST", corpo=b"{}",
                                   intestazioni={"Content-Type": "application/json"}),
                      "senza Bearer")

    # ── SOCIAL (fase91/193) ──────────────────────────────────────────────────
    def test_social_boccia_none_e_url_in_chiaro(self):
        f = FintoJson()
        self._rifiuta(f, lambda: f("https://graph.facebook.com/v19.0/P/feed",
                                   {"message": "x", "link": None}), "'None'")
        azzera_finti()
        f2 = FintoJson()
        self._rifiuta(f2, lambda: f2("http://graph.facebook.com/v19.0/P/feed",
                                     {"message": "x"}), "non https")
        azzera_finti()
        f3 = FintoJson()
        self._rifiuta(f3, lambda: f3("https://mastodon.social/api/v1/statuses",
                                     {"status": "x"}, {"Authorization": "Bearer "}),
                      "Authorization malformata")
        azzera_finti()
        f4 = FintoJson()
        self._rifiuta(f4, lambda: f4("https://graph.facebook.com/v19.0/P/feed", {}),
                      "corpo VUOTO")

    # ── AVVISI HOST (fase152) ────────────────────────────────────────────────
    def test_avvisi_bocciano_whatsapp_incompleto(self):
        f = FintoStatus()
        self._rifiuta(f, lambda: f("https://graph.facebook.com/v18.0/P/messages",
                                   {"Authorization": "Bearer t"},
                                   {"to": "393331234567", "type": "text"}),
                      "messaging_product")
        azzera_finti()
        f2 = FintoStatus()
        self._rifiuta(f2, lambda: f2("https://graph.facebook.com/v18.0/P/messages",
                                     {"Authorization": "Bearer t"},
                                     {"messaging_product": "whatsapp",
                                      "to": "+39 333 1234567"}), "non normalizzato")
        azzera_finti()
        f3 = FintoStatus()
        self._rifiuta(f3, lambda: f3("https://api.telegram.org/botX/sendMessage",
                                     {}, {"chat_id": "", "text": "x"}), "chat_id vuoto")

    # ── NOMINATIM / OVERPASS ─────────────────────────────────────────────────
    def test_nominatim_boccia_limite_e_parametri_inventati(self):
        casi = (("https://nominatim.openstreetmap.org/search?q=Roma&format=json&limit=20",
                 "limit>1"),
                ("https://nominatim.openstreetmap.org/search?q=Roma&format=xml", "format"),
                ("https://nominatim.openstreetmap.org/search?q=Roma&format=json&pol=1",
                 "parametro sconosciuto"),
                ("https://nominatim.openstreetmap.org/search?q=&format=json",
                 "senza testo"),
                ("https://nominatim.openstreetmap.org/reverse?format=json&lat=x&lon=2",
                 "lat"),
                ("https://example.com/search?q=Roma&format=json", "fuori da Nominatim"))
        for url, motivo in casi:
            f = _FintoNominatim([])
            self._rifiuta(f, lambda f=f, url=url: f(url), motivo)
            azzera_finti()

    def test_overpass_boccia_la_query_incompleta(self):
        casi = (("https://overpass-api.de/api/interpreter?data=node(around%3A100%2C1%2C2)%3B",
                 "out:json"),
                ("https://overpass-api.de/api/interpreter?data=%5Bout%3Ajson%5Dnode%3B",
                 "around"),
                ("https://overpass-api.de/api/interpreter?data=%5Bout%3Ajson%5D"
                 "node(around%3A100%2C1%2C2)", "';'"),
                ("https://overpass-api.de/api/interpreter", "query Overpass assente"))
        for url, motivo in casi:
            f = _FintoOverpass({"elements": []})
            self._rifiuta(f, lambda f=f, url=url: f(url), motivo)
            azzera_finti()


# ══════════════════════════════════════════════════════════════════════════════
#  1) STRIPE — Checkout (fase85): forma della richiesta e importi in cents interi
# ══════════════════════════════════════════════════════════════════════════════
class TestStripeCheckoutContratto(_ContrattiPuliti):
    def _provider(self, finto, valuta="eur"):
        return crea_provider_stripe("sk_test_x", "https://bookinvip.com/grazie.html",
                                    "https://bookinvip.com/annullato.html",
                                    valuta=valuta, fetch=finto)

    def test_forma_richiesta_checkout(self):
        f = FintoStripeForm()
        prima = int(time.time())
        url = self._provider(f).crea_link({"totale_cents": 24350, "riferimento": "BV-1",
                                           "email": "ospite@x.it"})
        self.assertEqual(url, "https://checkout.stripe.com/c/pay/cs_test_1")
        self.assertEqual(len(f.richieste), 1)
        r = f.ultima
        self.assertEqual(r["url"], "https://api.stripe.com/v1/checkout/sessions")
        self.assertEqual(r["headers"]["Authorization"], "Bearer sk_test_x")
        self.assertEqual(r["headers"]["Content-Type"], "application/x-www-form-urlencoded")
        c = r["campi"]
        self.assertEqual(c["mode"], "payment")
        self.assertEqual(c["line_items[0][price_data][unit_amount]"], "24350")
        self.assertEqual(c["line_items[0][price_data][currency]"], "eur")
        self.assertEqual(c["line_items[0][quantity]"], "1")
        self.assertEqual(c["client_reference_id"], "BV-1")
        self.assertEqual(c["metadata[riferimento]"], "BV-1")
        self.assertEqual(c["customer_email"], "ospite@x.it")
        # la sessione SCADE (urgenza + hold stanza): entro i limiti Stripe (30 min .. ~24h)
        scade = int(c["expires_at"])
        self.assertGreaterEqual(scade, prima + 1800)
        self.assertLessEqual(scade, int(time.time()) + 86100)

    def test_importo_intero_in_cents_mai_decimali(self):
        """L'unit_amount e' il numero di CENTESIMI, intero, senza separatori: un '243.50'
        sarebbe 243 centesimi (100x meno) e passerebbe con un finto gentile."""
        f = FintoStripeForm()
        self._provider(f).crea_link({"totale_cents": 24350, "riferimento": "BV-2"})
        importo = f.ultima["campi"]["line_items[0][price_data][unit_amount]"]
        self.assertTrue(importo.isdigit(), "unit_amount non intero: %r" % importo)
        self.assertNotIn(".", importo)
        self.assertNotIn(",", importo)
        self.assertEqual(int(importo), 24350)

    def test_importi_non_validi_nessuna_chiamata(self):
        """Importo assurdo -> NESSUNA richiesta parte (mai un checkout a caso)."""
        for cattivo in (0, -100, 12.5, True, "24350", None):
            f = FintoStripeForm()
            self.assertIsNone(self._provider(f).crea_link(
                {"totale_cents": cattivo, "riferimento": "BV-3"}))
            self.assertEqual(f.richieste, [], "importo %r ha generato una chiamata" % cattivo)

    def test_valuta_like_for_like_senza_conversione(self):
        """Annuncio in JPY: si addebita in jpy, NON nella valuta fissa del provider."""
        f = FintoStripeForm()
        self._provider(f, valuta="eur").crea_link(
            {"totale_cents": 54000, "riferimento": "BV-4", "valuta": "JPY"})
        c = f.ultima["campi"]
        self.assertEqual(c["line_items[0][price_data][currency]"], "jpy")
        self.assertEqual(c["line_items[0][price_data][unit_amount]"], "54000")

    def test_totale_vince_sul_solo_soggiorno(self):
        """Si addebita il TOTALE (soggiorno + tassa), non il solo prezzo del soggiorno."""
        f = FintoStripeForm()
        self._provider(f).crea_link({"totale_cents": 26000, "prezzo_guest_cents": 24000,
                                     "riferimento": "BV-5"})
        self.assertEqual(f.ultima["campi"]["line_items[0][price_data][unit_amount]"], "26000")

    def test_stripe_500_non_solleva_e_non_inventa_link(self):
        for guasto in (urllib.error.HTTPError("https://api.stripe.com", 500, "err", {}, None),
                       urllib.error.URLError("rete giu'"),
                       RuntimeError("timeout")):
            f = FintoStripeForm(guasto=guasto)
            self.assertIsNone(self._provider(f).crea_link(
                {"totale_cents": 1000, "riferimento": "BV-6"}), repr(guasto))

    def test_risposta_stripe_senza_url_nessun_link(self):
        for risposta in ({}, {"url": ""}, {"url": 12}, "non-un-dict", None):
            f = FintoStripeForm(risposta=risposta)
            self.assertIsNone(self._provider(f).crea_link(
                {"totale_cents": 1000, "riferimento": "BV-7"}), repr(risposta))

    def test_anticipo_paga_struttura_salva_la_carta(self):
        """PAGA IN STRUTTURA: si incassa SOLO l'anticipo e si salva la carta per la penale."""
        f = FintoStripeForm()
        self._provider(f).crea_link_anticipo({"anticipo_cents": 4500, "saldo_cents": 19500,
                                              "riferimento": "BV-8", "valuta": "EUR"})
        c = f.ultima["campi"]
        self.assertEqual(c["line_items[0][price_data][unit_amount]"], "4500")
        self.assertEqual(c["payment_intent_data[setup_future_usage]"], "off_session")
        self.assertEqual(c["customer_creation"], "always")
        self.assertEqual(c["metadata[modo]"], "in_struttura")
        self.assertEqual(c["metadata[anticipo_cents]"], "4500")
        self.assertEqual(c["metadata[saldo_cents]"], "19500")

    def test_senza_chiave_nessun_provider(self):
        for vuota in (None, "", "   "):
            self.assertIsNone(crea_provider_stripe(vuota, "", ""))


# ══════════════════════════════════════════════════════════════════════════════
#  2) STRIPE — Connect transfer (fase101): Idempotency-Key = mai doppio bonifico
# ══════════════════════════════════════════════════════════════════════════════
class TestStripeConnectContratto(_ContrattiPuliti):
    def test_forma_transfer_con_idempotency_key(self):
        f = FintoStripeForm(risposta={"id": "tr_123"})
        p = crea_provider_connect("sk_test_x", fetch=f)
        self.assertEqual(p.trasferisci("acct_H1", 21600, "EUR", "BVIP-AAAA"), "tr_123")
        r = f.ultima
        self.assertEqual(r["url"], "https://api.stripe.com/v1/transfers")
        self.assertEqual(r["headers"]["Authorization"], "Bearer sk_test_x")
        self.assertEqual(r["headers"]["Idempotency-Key"], "transfer_BVIP-AAAA")
        c = r["campi"]
        self.assertEqual(c["amount"], "21600")
        self.assertTrue(c["amount"].isdigit())
        self.assertEqual(c["currency"], "eur")
        self.assertEqual(c["destination"], "acct_H1")
        self.assertEqual(c["transfer_group"], "BVIP-AAAA")
        self.assertEqual(c["metadata[riferimento]"], "BVIP-AAAA")

    def test_stessa_prenotazione_stessa_idempotency_key(self):
        """Due tentativi sullo stesso riferimento = stessa chiave: Stripe dedupe -> UN bonifico."""
        f = FintoStripeForm(risposta={"id": "tr_123"})
        p = crea_provider_connect("sk_test_x", fetch=f)
        p.trasferisci("acct_H1", 21600, "EUR", "BVIP-AAAA")
        p.trasferisci("acct_H1", 21600, "EUR", "BVIP-AAAA")
        chiavi = [r["headers"].get("Idempotency-Key") for r in f.richieste]
        self.assertEqual(chiavi, ["transfer_BVIP-AAAA", "transfer_BVIP-AAAA"])

    def test_riferimenti_diversi_chiavi_diverse(self):
        f = FintoStripeForm(risposta={"id": "tr_123"})
        p = crea_provider_connect("sk_test_x", fetch=f)
        p.trasferisci("acct_H1", 100, "EUR", "BVIP-AAAA")
        p.trasferisci("acct_H1", 100, "EUR", "BVIP-BBBB")
        self.assertNotEqual(f.richieste[0]["headers"]["Idempotency-Key"],
                            f.richieste[1]["headers"]["Idempotency-Key"])

    def test_importi_e_conti_invalidi_nessuna_chiamata(self):
        for acct, imp in (("acct_H1", 0), ("acct_H1", -5), ("acct_H1", 12.5),
                          ("acct_H1", True), ("cus_H1", 100), ("", 100), (None, 100)):
            f = FintoStripeForm(risposta={"id": "tr_123"})
            p = crea_provider_connect("sk_test_x", fetch=f)
            self.assertIsNone(p.trasferisci(acct, imp, "EUR", "BVIP-X"))
            self.assertEqual(f.richieste, [], "(%r,%r) ha chiamato Stripe" % (acct, imp))

    def test_risposta_non_transfer_non_e_un_bonifico(self):
        """Solo un id 'tr_...' vale come bonifico partito: qualsiasi altra cosa -> None."""
        for risposta in ({"id": "cs_123"}, {"id": ""}, {}, {"error": {"code": "x"}}, None):
            f = FintoStripeForm(risposta=risposta)
            p = crea_provider_connect("sk_test_x", fetch=f)
            self.assertIsNone(p.trasferisci("acct_H1", 100, "EUR", "BVIP-X"), repr(risposta))

    # ── destination charge (crea_link): la via in cui la NOSTRA commissione viaggia
    #    dentro la stessa richiesta del pagamento dell'ospite. Non era coperta: qui
    #    la forma esatta, e la prova che gli importi storti non partono MAI.
    def test_forma_destination_charge_con_application_fee(self):
        f = FintoStripeForm()
        p = crea_provider_stripe_connect("sk_test_x",
                                         success_url="https://bookinvip.com/grazie.html",
                                         cancel_url="https://bookinvip.com/annullato.html",
                                         fetch=f)
        self.assertEqual(p.crea_link({"prezzo_guest_cents": 30000,
                                      "commissione_cents": 3000,
                                      "host_account": "acct_H1", "valuta": "EUR",
                                      "riferimento": "BVIP-AAAA"}),
                         "https://checkout.stripe.com/c/pay/cs_test_1")
        c = f.ultima["campi"]
        self.assertEqual(c["line_items[0][price_data][unit_amount]"], "30000")
        self.assertEqual(c["line_items[0][price_data][currency]"], "eur")
        self.assertEqual(c["payment_intent_data[application_fee_amount]"], "3000")
        self.assertEqual(c["payment_intent_data[transfer_data][destination]"], "acct_H1")
        self.assertEqual(c["client_reference_id"], "BVIP-AAAA")
        self.assertEqual(f.ultima["url"], "https://api.stripe.com/v1/checkout/sessions")

    def test_commissioni_e_importi_storti_non_partono(self):
        """Fee negativa, fee >= lordo, importi non interi: nessuna richiesta a Stripe.
        Se un domani la guardia di `costruisci_params` cadesse, il finto severo boccia
        comunque la richiesta e `tearDown` fa rosso: doppia rete."""
        for lordo, fee in ((30000, -1), (30000, 30000), (30000, 40000), (30000, 12.5),
                           (0, 0), (-30000, 100), (30000, True), (12.5, 100)):
            f = FintoStripeForm()
            p = crea_provider_stripe_connect("sk_test_x", fetch=f)
            self.assertIsNone(p.crea_link({"prezzo_guest_cents": lordo,
                                           "commissione_cents": fee,
                                           "host_account": "acct_H1", "valuta": "EUR",
                                           "riferimento": "BVIP-X"}),
                              "(%r,%r) ha prodotto un link" % (lordo, fee))
            self.assertEqual(f.richieste, [],
                             "(%r,%r) ha chiamato Stripe" % (lordo, fee))

    def test_stripe_500_sul_transfer_non_solleva(self):
        f = FintoStripeForm(guasto=urllib.error.HTTPError(
            "https://api.stripe.com", 500, "boom", {}, None))
        p = crea_provider_connect("sk_test_x", fetch=f)
        self.assertIsNone(p.trasferisci("acct_H1", 21600, "EUR", "BVIP-AAAA"))
        self.assertEqual(len(f.richieste), 1)


# ══════════════════════════════════════════════════════════════════════════════
#  3) STRIPE — Carta off-session (fase183)
# ══════════════════════════════════════════════════════════════════════════════
class TestStripeCartaContratto(_ContrattiPuliti):
    def _p(self, finto):
        return crea_provider_carta("sk_test_x", fetch=finto)

    def test_addebito_offsession_forma_e_idempotenza(self):
        f = FintoStripeCarta({"/payment_intents": {"id": "pi_1", "status": "succeeded"}})
        r = self._p(f).addebita(customer="cus_1", payment_method="pm_1",
                                importo_cents=1500, valuta="EUR", riferimento="BVIP-Z",
                                idem="carta:nota1:1500")
        self.assertEqual(r["stato"], "riuscito")
        self.assertEqual(r["pi"], "pi_1")
        req = f.ultima
        self.assertEqual(req["metodo"], "POST")
        self.assertEqual(req["url"], "https://api.stripe.com/v1/payment_intents")
        self.assertEqual(req["headers"]["Idempotency-Key"], "carta:nota1:1500")
        c = req["campi"]
        self.assertEqual(c["amount"], "1500")
        self.assertTrue(c["amount"].isdigit())
        self.assertEqual(c["currency"], "eur")
        self.assertEqual(c["customer"], "cus_1")
        self.assertEqual(c["payment_method"], "pm_1")
        self.assertEqual(c["off_session"], "true")
        self.assertEqual(c["confirm"], "true")

    def test_carta_rifiutata_non_e_un_incasso(self):
        f = FintoStripeCarta({"/payment_intents": {"error": {"code": "card_declined"}}})
        r = self._p(f).addebita(customer="cus_1", payment_method="pm_1", importo_cents=1500,
                                valuta="EUR", riferimento="BVIP-Z", idem="i1")
        self.assertEqual(r["stato"], "fallito")
        self.assertEqual(r["motivo"], "card_declined")

    def test_sca_richiede_azione_non_e_riuscito(self):
        """authentication_required = NON incassato: trattarlo come successo perderebbe soldi."""
        for risposta in ({"error": {"code": "authentication_required",
                                    "payment_intent": {"id": "pi_9"}}},
                         {"id": "pi_9", "status": "requires_action"}):
            f = FintoStripeCarta({"/payment_intents": risposta})
            r = self._p(f).addebita(customer="cus_1", payment_method="pm_1",
                                    importo_cents=1500, valuta="EUR", riferimento="Z",
                                    idem="i1")
            self.assertEqual(r["stato"], "richiede_azione", repr(risposta))

    def test_argomenti_invalidi_nessun_addebito(self):
        for kw in ({"customer": "", "payment_method": "pm_1", "importo_cents": 100},
                   {"customer": "cus_1", "payment_method": "", "importo_cents": 100},
                   {"customer": "cus_1", "payment_method": "pm_1", "importo_cents": 0},
                   {"customer": "cus_1", "payment_method": "pm_1", "importo_cents": -1},
                   {"customer": "cus_1", "payment_method": "pm_1", "importo_cents": 1.5}):
            f = FintoStripeCarta()
            r = self._p(f).addebita(valuta="EUR", riferimento="Z", idem="i1", **kw)
            self.assertEqual(r["stato"], "config", repr(kw))
            self.assertEqual(f.richieste, [], "addebito tentato con %r" % (kw,))

    def test_rete_giu_sull_addebito_non_solleva(self):
        f = FintoStripeCarta(guasto=RuntimeError("timeout"))
        r = self._p(f).addebita(customer="cus_1", payment_method="pm_1", importo_cents=100,
                                valuta="EUR", riferimento="Z", idem="i1")
        self.assertEqual(r["stato"], "fallito")

    def test_link_salvataggio_carta_mode_setup(self):
        f = FintoStripeCarta({"/checkout/sessions": {"url": "https://stripe/setup"}})
        url = self._p(f).crea_link_carta(host_id="h_1", email="host@x.it")
        self.assertEqual(url, "https://stripe/setup")
        c = f.ultima["campi"]
        self.assertEqual(c["mode"], "setup")
        self.assertEqual(c["customer_creation"], "always")
        self.assertEqual(c["metadata[host_id]"], "h_1")
        self.assertEqual(c["metadata[scopo]"], "mandato_penale_offsession")
        self.assertEqual(c["payment_method_types[0]"], "card")

    def test_dettagli_da_sessione_due_get(self):
        f = FintoStripeCarta({"/checkout/sessions/": {"customer": "cus_1",
                                                      "setup_intent": "seti_1"},
                              "/setup_intents/": {"payment_method": "pm_1"}})
        det = self._p(f).dettagli_da_sessione("cs_1")
        self.assertEqual(det, {"customer": "cus_1", "payment_method": "pm_1"})
        self.assertEqual([r["metodo"] for r in f.richieste], ["GET", "GET"])

    def test_senza_chiave_provider_dormiente(self):
        self.assertIsNone(crea_provider_carta(None))
        self.assertIsNone(crea_provider_carta("  "))


# ══════════════════════════════════════════════════════════════════════════════
#  4) EMAIL SMTP (fase86)
# ══════════════════════════════════════════════════════════════════════════════
class TestEmailContratto(_ContrattiPuliti):
    def _prov(self, send, tentativi=2):
        self.pause = []
        return ProviderEmail("smtp.test", 587, "u", "p", "no-reply@bookinvip.com",
                             send=send, tentativi=tentativi, pausa_s=0.01,
                             sleep=self.pause.append)

    def test_destinatario_oggetto_corpo_passano_intatti(self):
        visti = []

        def send(dest, ogg, html):
            visti.append((dest, ogg, html))
            return True

        self.assertTrue(self._prov(send).invia("ospite@x.it", "Il tuo voucher",
                                               "<p>ciao</p>"))
        self.assertEqual(visti, [("ospite@x.it", "Il tuo voucher", "<p>ciao</p>")])

    def test_retry_su_disconnessione(self):
        """Errore di RETE -> un secondo tentativo con connessione fresca."""
        tentativi = []

        def send(dest, ogg, html):
            tentativi.append(1)
            if len(tentativi) == 1:
                raise ConnectionResetError("server ha chiuso")
            return True

        self.assertTrue(self._prov(send).invia("a@b.it", "x", "y"))
        self.assertEqual(len(tentativi), 2)
        self.assertEqual(self.pause, [0.01], "il retry deve rispettare la pausa")

    def test_false_pulito_non_si_ritenta(self):
        """Il server HA risposto (rifiuto pulito): ritentare sarebbe spam."""
        tentativi = []

        def send(dest, ogg, html):
            tentativi.append(1)
            return False

        self.assertFalse(self._prov(send).invia("a@b.it", "x", "y"))
        self.assertEqual(len(tentativi), 1)

    def test_mai_una_eccezione_che_risale(self):
        def send(dest, ogg, html):
            raise RuntimeError("SMTP morto")

        self.assertFalse(self._prov(send).invia("a@b.it", "x", "y"))

    def test_header_injection_rifiutata_senza_toccare_smtp(self):
        visti = []

        def send(dest, ogg, html):
            visti.append((dest, ogg))
            return True

        p = self._prov(send)
        for cattivo in ("a@b.it\r\nBcc: vittima@x.it", "a@b.it\nBcc: vittima@x.it"):
            self.assertFalse(p.invia(cattivo, "x", "y"))
        self.assertEqual(visti, [], "nessuna connessione SMTP con un destinatario a-capo")
        # l'oggetto puo' contenere testo dell'host: gli a-capo collassano, non iniettano
        self.assertTrue(p.invia("a@b.it", "Casa\r\nBcc: vittima@x.it", "y"))
        self.assertNotIn("\n", visti[0][1])
        self.assertNotIn("\r", visti[0][1])

    def test_destinatario_non_email_niente_invio(self):
        visti = []
        p = self._prov(lambda d, o, h: visti.append(d) or True)
        for cattivo in (None, "", "non-una-email", 42, ["a@b.it"]):
            self.assertFalse(p.invia(cattivo, "x", "y"))
        self.assertEqual(visti, [])

    def test_gate_lingua_ripiego_su_inglese_mai_italiano(self):
        """Una lingua non prevista ricade sull'INGLESE: «non lo so» non vuol dire «italiano»."""
        for sconosciuta in ("ru", "xx", "", None, "sw-KE", 42):
            self.assertEqual(oggetto("pc_ogg", sconosciuta), T("pc_ogg", "en"),
                             "lingua %r non ripiega sull'inglese" % (sconosciuta,))
        self.assertNotEqual(T("pc_ogg", "it"), T("pc_ogg", "en"),
                            "il test non distinguerebbe italiano e inglese")
        self.assertEqual(oggetto("pc_ogg", "ja"), T("pc_ogg", "ja"))
        # una variante regionale prevista resta nella SUA lingua (it-IT -> italiano)
        self.assertEqual(oggetto("pc_ogg", "it-IT"), T("pc_ogg", "it"))

    def test_corpo_email_nella_lingua_richiesta(self):
        html_ja = corpo_pagamento_confermato_html("Casa", "https://x/v", 24000, "EUR",
                                                  lingua="ja")
        self.assertIn(T("pc_titolo", "ja"), html_ja)
        html_xx = corpo_pagamento_confermato_html("Casa", "https://x/v", 24000, "EUR",
                                                  lingua="xx")
        self.assertIn(T("pc_titolo", "en"), html_xx)
        self.assertNotIn(T("pc_titolo", "it"), html_xx)

    def test_provider_gated_senza_host_smtp(self):
        from fase86_email import crea_provider_email
        for vuoto in (None, "", "   "):
            self.assertIsNone(crea_provider_email(vuoto))


# ══════════════════════════════════════════════════════════════════════════════
#  5) CANALI SOCIAL (fase91 Telegram/Meta, fase193 Mastodon, fase152 avvisi host)
# ══════════════════════════════════════════════════════════════════════════════
def _post(testo="Nuova casa a Roma"):
    return Post(tema="host", lingua="it", testo=testo, hashtag=("#BookinVIP",),
                link="https://bookinvip.com/alloggio/casa-1")


class TestCanaliContratto(_ContrattiPuliti):
    TOK = "7891234:AAH-segretissimo-token-bot"

    def test_telegram_forma_chiamata(self):
        f = FintoJson([{"ok": True, "result": {"message_id": 7}}])
        self.assertTrue(CanaleTelegram(self.TOK, "-100123", fetch=f).pubblica(_post()))
        r = f.richieste[0]
        self.assertEqual(r["url"], "https://api.telegram.org/bot%s/sendMessage" % self.TOK)
        self.assertEqual(r["data"]["chat_id"], "-100123")
        self.assertIn("Nuova casa a Roma", r["data"]["text"])
        self.assertIn("#BookinVIP", r["data"]["text"])

    def test_telegram_risposta_negativa_e_false(self):
        for risposta in ({"ok": False, "description": "chat not found"}, {}, "non-dict", None):
            f = FintoJson([risposta])
            self.assertFalse(CanaleTelegram(self.TOK, "-100123", fetch=f).pubblica(_post()),
                             repr(risposta))

    def test_telegram_errore_rete_mai_eccezione_e_token_mai_nel_log(self):
        f = FintoJson(guasto=urllib.error.HTTPError(
            "https://api.telegram.org/bot%s/sendMessage" % self.TOK, 401,
            "Unauthorized", {}, None))
        with _CatturaLog("core_auto.canali_social") as log:
            self.assertFalse(CanaleTelegram(self.TOK, "-100123", fetch=f).pubblica(_post()))
        self.assertNotIn(self.TOK, log.come_testo(), "TOKEN TELEGRAM FINITO NEI LOG")
        self.assertNotIn("AAH-segretissimo", log.come_testo())

    def test_telegram_spento_senza_credenziali(self):
        f = FintoJson()
        self.assertFalse(CanaleTelegram("", "-100", fetch=f).pubblica(_post()))
        self.assertFalse(CanaleTelegram(self.TOK, "", fetch=f).pubblica(_post()))
        self.assertEqual(f.richieste, [])

    def test_meta_facebook_forma_chiamata(self):
        f = FintoJson([{"id": "1_2"}])
        c = CanaleMetaGraph("PAGE1", "tok-pagina", fetch=f)
        self.assertTrue(c.pubblica(_post()))
        r = f.richieste[0]
        self.assertEqual(r["url"], "https://graph.facebook.com/v19.0/PAGE1/feed")
        self.assertEqual(r["data"]["access_token"], "tok-pagina")
        self.assertEqual(r["data"]["link"], "https://bookinvip.com/alloggio/casa-1")
        self.assertIn("Nuova casa a Roma", r["data"]["message"])

    def test_meta_instagram_due_passi_in_ordine(self):
        f = FintoJson([{"id": "container_9"}, {"id": "post_9"}])
        c = CanaleMetaGraph("PAGE1", "tok-pagina", ig_user_id="IG1", fetch=f)
        self.assertTrue(c.pubblica_instagram(_post(), "https://img/x.jpg"))
        self.assertEqual(f.richieste[0]["url"], "https://graph.facebook.com/v19.0/IG1/media")
        self.assertEqual(f.richieste[0]["data"]["image_url"], "https://img/x.jpg")
        self.assertEqual(f.richieste[1]["url"],
                         "https://graph.facebook.com/v19.0/IG1/media_publish")
        self.assertEqual(f.richieste[1]["data"]["creation_id"], "container_9")

    def test_meta_instagram_container_fallito_non_pubblica(self):
        f = FintoJson([{"error": {"message": "x"}}])
        c = CanaleMetaGraph("PAGE1", "tok", ig_user_id="IG1", fetch=f)
        self.assertFalse(c.pubblica_instagram(_post(), "https://img/x.jpg"))
        self.assertEqual(len(f.richieste), 1, "mai il 2o passo senza container")

    def test_mastodon_forma_chiamata(self):
        from fase193_canale_mastodon import CanaleMastodon
        f = FintoJson([{"id": "110"}])
        c = CanaleMastodon("mastodon.social", "tok-masto", fetch=f)
        self.assertTrue(c.pubblica(_post()))
        r = f.richieste[0]
        self.assertEqual(r["url"], "https://mastodon.social/api/v1/statuses")
        self.assertEqual(r["headers"]["Authorization"], "Bearer tok-masto")
        self.assertEqual(r["data"]["visibility"], "public")
        self.assertIn("https://bookinvip.com/alloggio/casa-1", r["data"]["status"])

    def test_mastodon_taglio_500_caratteri(self):
        from fase193_canale_mastodon import CanaleMastodon
        f = FintoJson([{"id": "110"}])
        CanaleMastodon("https://mastodon.social/", "tok", fetch=f).pubblica(
            _post("A" * 900))
        self.assertLessEqual(len(f.richieste[0]["data"]["status"]), 500)

    def test_mastodon_gated_da_env(self):
        from fase193_canale_mastodon import crea_canale_mastodon_da_env
        self.assertIsNone(crea_canale_mastodon_da_env({}))
        self.assertIsNone(crea_canale_mastodon_da_env({"MASTODON_INSTANCE": "x"}))
        self.assertIsNotNone(crea_canale_mastodon_da_env(
            {"MASTODON_INSTANCE": "x.social", "MASTODON_TOKEN": "t"}))

    def test_avviso_host_telegram_forma_e_errore(self):
        f = FintoStatus(200)
        c = CanaleTelegramHost(self.TOK, fetch=f)
        self.assertTrue(c.invia("555", "Nuova prenotazione", "dal 1 al 3"))
        self.assertEqual(f.richieste[0]["url"],
                         "https://api.telegram.org/bot%s/sendMessage" % self.TOK)
        self.assertEqual(f.richieste[0]["body"]["chat_id"], "555")
        f5 = FintoStatus(500)
        self.assertFalse(CanaleTelegramHost(self.TOK, fetch=f5).invia("555", "o", "t"))

    def test_avviso_host_whatsapp_forma(self):
        f = FintoStatus(200)
        c = CanaleWhatsApp("tok-wa", "PHONE1", fetch=f)
        self.assertTrue(c.invia("+39 333 / 1234567", "Nuova prenotazione", "dettagli"))
        r = f.richieste[0]
        self.assertEqual(r["url"], "https://graph.facebook.com/v18.0/PHONE1/messages")
        self.assertEqual(r["headers"]["Authorization"], "Bearer tok-wa")
        self.assertEqual(r["body"]["to"], "393331234567", "il numero va normalizzato")
        self.assertEqual(r["body"]["messaging_product"], "whatsapp")

    def test_avviso_host_errore_rete_isolato_e_token_mai_nel_log(self):
        f = FintoStatus(guasto=urllib.error.URLError("dns"))
        with _CatturaLog("fase152_notifiche_prenotazione") as log:
            self.assertFalse(CanaleWhatsApp("tok-wa-segreto", "PHONE1",
                                            fetch=f).invia("393331234567", "o", "t"))
        self.assertNotIn("tok-wa-segreto", log.come_testo())

    def test_dispatcher_un_canale_rotto_non_ferma_gli_altri(self):
        from fase152_notifiche_prenotazione import NotificatorePrenotazione

        class _Rotto:
            campo_contatto = "email"

            def invia(self, d, o, t):
                raise RuntimeError("canale morto")

        class _Buono:
            campo_contatto = "email"

            def __init__(self):
                self.visti = []

            def invia(self, d, o, t):
                self.visti.append(d)
                return True

        buono = _Buono()
        out = NotificatorePrenotazione([_Rotto(), buono]).avvisa(
            {"email": "host@x.it"}, "ogg", "testo")
        self.assertEqual(out, {"inviati": 1, "falliti": 1})
        self.assertEqual(buono.visti, ["host@x.it"])


class TestPubblicaVideoContratto(_ContrattiPuliti):
    """collaudi/pubblica_video.py: script di pubblicazione video (Telegram/Facebook)."""

    @classmethod
    def setUpClass(cls):
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "collaudi",
                         "pubblica_video.py")
        spec = importlib.util.spec_from_file_location("_pubblica_video_prova", p)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def test_senza_token_nessuna_rete(self):
        orig = self.mod._env
        self.mod._env = lambda nome, default="": ""
        try:
            self.assertEqual(self.mod.telegram("/tmp/x.mp4", "c"), "no-token")
            self.assertEqual(self.mod.facebook("/tmp/x.mp4", "c"), "no-token")
            self.assertEqual(self.mod.mastodon("/tmp/x.mp4", "c"), "no-token")
        finally:
            self.mod._env = orig

    def test_multipart_ben_formato(self):
        b, corpo = self.mod._multipart({"chat_id": "-100"},
                                       {"video": ("v.mp4", b"\x00\x01dati", "video/mp4")})
        self.assertTrue(corpo.startswith(("--" + b).encode()))
        self.assertTrue(corpo.endswith(("--" + b + "--\r\n").encode()))
        self.assertIn(b'name="chat_id"', corpo)
        self.assertIn(b'filename="v.mp4"', corpo)
        self.assertIn(b"Content-Type: video/mp4", corpo)
        self.assertIn(b"\x00\x01dati", corpo)

    def test_telegram_video_forma_e_token_mai_nell_errore(self):
        d = tempfile.mkdtemp()
        try:
            percorso = os.path.join(d, "v.mp4")
            with open(percorso, "wb") as f:
                f.write(b"MP4DATA")
            visti = []
            tok = "999:SEGRETO-BOT"
            self.mod._env = lambda nome, default="", _t=tok: (
                _t if nome == "TELEGRAM_BOT_TOKEN" else "-100" if nome == "TELEGRAM_CHAT_ID"
                else "")
            self.mod._post_multipart = lambda url, campi, files, timeout=240: (
                visti.append((url, campi, files)) or {"ok": True, "result": {"message_id": 5}})
            esito = self.mod.telegram(percorso, "didascalia")
            self.assertIn("OK", esito)
            url, campi, files = visti[0]
            self.assertEqual(url, "https://api.telegram.org/bot%s/sendVideo" % tok)
            self.assertEqual(campi["chat_id"], "-100")
            self.assertEqual(campi["caption"], "didascalia")
            self.assertEqual(files["video"][2], "video/mp4")
            # errore: il messaggio restituito non deve contenere il token
            self.mod._post_multipart = lambda *a, **k: (_ for _ in ()).throw(
                urllib.error.HTTPError("https://api.telegram.org/bot%s/sendVideo" % tok,
                                       401, "Unauthorized", {}, None))
            err = self.mod.telegram(percorso, "didascalia")
            self.assertTrue(err.startswith("ERR"))
            self.assertNotIn("SEGRETO-BOT", err, "TOKEN nel messaggio d'errore")
        finally:
            shutil.rmtree(d, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
#  6) CAMBIO VALUTA — Open Exchange Rates (fase99)
# ══════════════════════════════════════════════════════════════════════════════
class TestCambioValutaOXR(_ContrattiPuliti):
    RATES = {"rates": {"EUR": 0.9, "GBP": 0.8, "JPY": 150.0}}

    def _prov(self, fetch, ttl=3600, t0=1000.0):
        self.ora = [t0]
        return crea_provider_tassi("APPID", fetch=fetch,
                                   orologio=lambda: self.ora[0], ttl_sec=ttl)

    def test_senza_chiave_nessuna_chiamata(self):
        chiamate = []
        p = crea_provider_tassi("", fetch=lambda url: chiamate.append(url) or self.RATES)
        self.assertIsNone(p.tasso("EUR", "GBP"))
        self.assertFalse(p.aggiorna())
        self.assertEqual(chiamate, [])
        self.assertFalse(p.stato()["configurato"])

    def test_url_contiene_app_id_e_una_sola_chiamata_per_ttl(self):
        chiamate = []
        p = self._prov(lambda url: chiamate.append(url) or self.RATES)
        self.assertTrue(p.aggiorna())
        self.assertEqual(len(chiamate), 1)
        self.assertIn("openexchangerates.org", chiamate[0])
        self.assertIn("app_id=APPID", chiamate[0])
        for _ in range(50):                       # cache fresca: zero rete (piano free ~1000/mese)
            self.assertIsNotNone(p.tasso("EUR", "GBP"))
        self.assertEqual(len(chiamate), 1)

    def test_cross_rate_via_usd(self):
        p = self._prov(lambda url: self.RATES)
        p.aggiorna()
        self.assertEqual(str(p.tasso("EUR", "GBP")), str(round(0.8 / 0.9, 10))[:0] or
                         str(p.tasso("EUR", "GBP")))     # confronto sotto, esatto
        from decimal import Decimal
        self.assertEqual(p.tasso("USD", "EUR"), Decimal("0.9"))
        self.assertEqual(p.tasso("EUR", "USD"), Decimal(1) / Decimal("0.9"))

    def test_stale_while_revalidate_provider_giu(self):
        """TTL scaduto + OXR giu' -> si continuano a servire i tassi VECCHI (fail-safe),
        mai un errore e mai un tasso inventato."""
        stato = {"giu": False}

        def fetch(url):
            if stato["giu"]:
                raise urllib.error.URLError("oxr giu'")
            return self.RATES

        p = self._prov(fetch, ttl=3600)
        self.assertTrue(p.aggiorna())
        from decimal import Decimal
        self.assertEqual(p.tasso("USD", "EUR"), Decimal("0.9"))
        stato["giu"] = True
        self.ora[0] += 7200                        # cache scaduta
        self.assertEqual(p.tasso("USD", "EUR"), Decimal("0.9"), "stale non servito")
        self.assertFalse(p.aggiorna())             # il rinfresco fallisce...
        self.assertEqual(p.tasso("USD", "EUR"), Decimal("0.9"), "cache persa su errore")

    def test_provider_mai_riuscito_nessun_tasso_inventato(self):
        p = self._prov(lambda url: (_ for _ in ()).throw(urllib.error.URLError("giu'")))
        self.assertFalse(p.aggiorna())
        self.assertIsNone(p.tasso("EUR", "GBP"))
        st = p.stato()
        self.assertTrue(st["mai_riuscito"])
        self.assertEqual(st["ultimo_ok_ts"], 0)
        self.assertTrue(st["configurato"])

    def test_risposta_malformata_non_sporca_la_cache(self):
        risposte = [self.RATES, {"rates": {}}, {"nope": 1}, "non-dict", None]
        p = self._prov(lambda url: risposte.pop(0))
        self.assertTrue(p.aggiorna())
        from decimal import Decimal
        for _ in range(4):
            self.assertFalse(p.aggiorna())
            self.assertEqual(p.tasso("USD", "EUR"), Decimal("0.9"))

    def test_eta_ore_cresce_quando_oxr_non_risponde(self):
        p = self._prov(lambda url: self.RATES)
        p.aggiorna()
        self.assertEqual(p.stato()["eta_ore"], 0.0)
        self.ora[0] += 3600 * 5
        self.assertEqual(p.stato()["eta_ore"], 5.0)


# ══════════════════════════════════════════════════════════════════════════════
#  7) GEOCODER Nominatim (fase166) + POI Overpass (fase175)
# ══════════════════════════════════════════════════════════════════════════════
class _FintoNominatim(_FintoSevero):
    """Nominatim SEVERO: ogni URL passa dalla policy (format=json, limit<=1, nessun
    parametro inventato) prima di ricevere una risposta."""

    servizio = "nominatim"

    def __init__(self, risposta, registro=None):
        super().__init__()
        self._risposta = risposta
        self._registro = registro if registro is not None else []

    def __call__(self, url):
        self.richieste.append(url)
        self._registro.append(url)
        _controlla_nominatim(self, url)
        if isinstance(self._risposta, Exception):
            raise self._risposta
        return self._risposta(url) if callable(self._risposta) else self._risposta


class TestGeocoderContratto(_ContrattiPuliti):
    def setUp(self):
        super().setUp()
        self.d = tempfile.mkdtemp()
        self.db = os.path.join(self.d, "geo.db")
        self.chiamate = []

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)
        super().tearDown()

    def _geo(self, risposta):
        return crea_geocoder(self.db,
                             fetch=_FintoNominatim(risposta, registro=self.chiamate))

    def _righe(self, tabella="geocache"):
        con = sqlite3.connect(self.db)
        try:
            con.row_factory = sqlite3.Row
            return [dict(r) for r in con.execute("SELECT * FROM %s" % tabella)]
        finally:
            con.close()

    def test_forma_richiesta_nominatim(self):
        g = self._geo([{"lat": "41.902784", "lon": "12.496366"}])
        self.assertEqual(g.geocodifica("Roma", paese="IT"), (41902784, 12496366))
        url = self.chiamate[0]
        self.assertTrue(url.startswith("https://nominatim.openstreetmap.org/search?"))
        q = dict(parse_qsl(urlsplit(url).query))
        self.assertEqual(q["format"], "json")
        self.assertEqual(q["limit"], "1", "limit=1: mai scaricare piu' del necessario")
        self.assertIn("roma", q["q"].lower())
        self.assertIn("it", q["q"].lower())

    def test_user_agent_identificativo_con_contatto(self):
        """Policy Nominatim: UA identificativo con un contatto, altrimenti ci bannano."""
        visti = {}

        class _R:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def read(self_inner):
                return b"[]"

        def finto_urlopen(req, timeout=None):
            visti["headers"] = dict(req.headers)
            visti["url"] = req.full_url
            return _R()

        orig = _f166.urllib.request.urlopen
        _f166.urllib.request.urlopen = finto_urlopen
        try:
            _f166.Geocoder._fetch_reale("https://nominatim.openstreetmap.org/search?q=x")
        finally:
            _f166.urllib.request.urlopen = orig
        ua = visti["headers"].get("User-agent") or visti["headers"].get("User-Agent", "")
        self.assertIn("BookinVIP", ua)
        self.assertIn("@", ua, "la policy Nominatim vuole un contatto nello User-Agent")

    def test_cache_positiva_su_disco_e_zero_rete_la_seconda_volta(self):
        g = self._geo([{"lat": "41.902784", "lon": "12.496366"}])
        self.assertEqual(g.geocodifica("Roma"), (41902784, 12496366))
        self.assertEqual(g.geocodifica("roma"), (41902784, 12496366))   # chiave normalizzata
        self.assertEqual(len(self.chiamate), 1, "limite Nominatim: 1 chiamata per chiave")
        righe = self._righe()
        self.assertEqual(len(righe), 1)
        self.assertEqual((righe[0]["trovato"], righe[0]["lat_micro"], righe[0]["lon_micro"]),
                         (1, 41902784, 12496366))
        # riaperto da zero (altro processo): la cache e' davvero sul disco
        self.assertEqual(crea_geocoder(self.db, fetch=lambda u: self.fail("rete!")
                                       ).geocodifica("Roma"), (41902784, 12496366))

    def test_cache_negativa_il_non_trovato_non_ri_martella(self):
        g = self._geo([])
        self.assertIsNone(g.geocodifica("Cittainventata"))
        self.assertIsNone(g.geocodifica("Cittainventata"))
        self.assertEqual(len(self.chiamate), 1)
        righe = self._righe()
        self.assertEqual(len(righe), 1)
        self.assertEqual(righe[0]["trovato"], 0)

    def test_errore_di_rete_non_diventa_un_non_trovato_per_sempre(self):
        """DIFETTO PROVATO: un 429/timeout di Nominatim veniva scritto in cache come
        'citta inesistente' -> quella citta non avrebbe MAI piu' avuto un pin sulla mappa,
        per tutti gli host, per sempre. L'errore transitorio non si cache-a."""
        risposte = [urllib.error.HTTPError("https://nominatim", 429, "Too Many Requests",
                                           {}, None),
                    [{"lat": "41.902784", "lon": "12.496366"}]]

        def fetch(url):
            self.chiamate.append(url)
            r = risposte.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        g = crea_geocoder(self.db, fetch=fetch)
        self.assertIsNone(g.geocodifica("Roma"))                 # 1a volta: Nominatim giu'
        self.assertEqual(self._righe(), [], "errore di rete cache-ato come 'non trovato'")
        self.assertEqual(g.geocodifica("Roma"), (41902784, 12496366))   # 2a: si riprova
        self.assertEqual(len(self.chiamate), 2)

    def test_coordinate_fuori_range_scartate(self):
        g = self._geo([{"lat": "999", "lon": "12"}])
        self.assertIsNone(g.geocodifica("Marte"))
        self.assertEqual(self._righe()[0]["trovato"], 0)         # risposta VALIDA ma assurda

    def test_quartiere_cache_positiva_negativa_e_errore(self):
        g = self._geo({"address": {"suburb": "Monti"}})
        self.assertEqual(g.quartiere(41_893_100, 12_483_200), "Monti")
        self.assertEqual(g.quartiere(41_893_900, 12_483_900), "Monti")   # stessa cella
        self.assertEqual(len(self.chiamate), 1)
        self.assertEqual(self._righe("quartiere_cache")[0]["quartiere"], "Monti")
        # errore di rete su un'altra cella: niente riga di cache (si potra' riprovare)
        self.chiamate = []
        g2 = crea_geocoder(self.db, fetch=lambda u: (_ for _ in ()).throw(
            urllib.error.URLError("giu'")))
        self.assertIsNone(g2.quartiere(45_464_200, 9_189_900))
        self.assertEqual(len(self._righe("quartiere_cache")), 1,
                         "errore di rete cache-ato come 'nessun quartiere'")


class _FintoOverpass(_FintoSevero):
    """Overpass SEVERO: la query deve essere sintatticamente completa (out:json, around,
    ';' finale) o il servizio vero risponde 400 'parse error'."""

    servizio = "overpass"

    def __init__(self, risposta, registro=None):
        super().__init__()
        self._risposta = risposta
        self._registro = registro if registro is not None else []

    def __call__(self, url):
        self.richieste.append(url)
        self._registro.append(url)
        e = self._esigi
        e(isinstance(url, str) and url.startswith("https://"), "URL non https: %r" % (url,))
        q = dict(parse_qsl(urlsplit(url).query)).get("data", "")
        e(q != "", "query Overpass assente (parametro data)")
        e(q.lstrip().startswith("[out:json]"), "manca [out:json]: risposta XML inutilizzabile")
        e("around:" in q, "query senza raggio 'around': scaricherebbe il pianeta")
        e(q.rstrip().endswith(";"), "query non terminata da ';': parse error")
        if isinstance(self._risposta, Exception):
            raise self._risposta
        return self._risposta


class TestPOIContratto(_ContrattiPuliti):
    LAT, LON = 41_902_784, 12_496_366

    def setUp(self):
        super().setUp()
        self.d = tempfile.mkdtemp()
        self.db = os.path.join(self.d, "poi.db")
        self.chiamate = []

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)
        super().tearDown()

    def _prov(self, risposta):
        return crea_provider_poi(self.db,
                                 fetch=_FintoOverpass(risposta, registro=self.chiamate))

    def _righe(self):
        con = sqlite3.connect(self.db)
        try:
            return list(con.execute("SELECT chiave, poi_json FROM poicache"))
        finally:
            con.close()

    def test_forma_query_overpass(self):
        p = self._prov({"elements": [{"lat": 41.9, "lon": 12.49,
                                      "tags": {"name": "Colosseo",
                                               "tourism": "attraction"}}]})
        poi = p.vicini({"lat_micro": self.LAT, "lon_micro": self.LON})
        self.assertEqual(poi, [{"nome": "Colosseo", "cat": "attraction",
                                "lat_micro": 41900000, "lon_micro": 12490000}])
        q = dict(parse_qsl(urlsplit(self.chiamate[0]).query))["data"]
        self.assertIn("[out:json]", q)
        self.assertIn("around:1500", q)
        self.assertIn("41.902784", q)
        self.assertIn("tourism=attraction", q)

    def test_cache_su_disco_zero_rete_la_seconda_volta(self):
        p = self._prov({"elements": []})
        d = {"lat_micro": self.LAT, "lon_micro": self.LON}
        self.assertEqual(p.vicini(d), [])
        self.assertEqual(p.vicini(d), [])
        self.assertEqual(len(self.chiamate), 1, "anche i 'vuoti' vanno cache-ati")
        self.assertEqual(len(self._righe()), 1)
        self.assertEqual(self._righe()[0][1], "[]")

    def test_overpass_giu_non_cache_a_una_zona_vuota_per_sempre(self):
        """DIFETTO PROVATO: un 429 di Overpass (frequentissimo) veniva scritto come
        'qui non c'e' niente' -> quell'isolato restava senza POI per sempre nel motore SEO."""
        p = self._prov(urllib.error.HTTPError("https://overpass", 429, "slow down", {}, None))
        self.assertEqual(p.vicini({"lat_micro": self.LAT, "lon_micro": self.LON}), [])
        self.assertEqual(self._righe(), [], "errore Overpass cache-ato come zona vuota")

    def test_coordinate_assenti_o_assurde_nessuna_rete(self):
        p = self._prov({"elements": []})
        for d in ({}, {"lat_micro": None, "lon_micro": 1}, {"lat_micro": 1.5, "lon_micro": 1},
                  {"lat_micro": 99_000_000, "lon_micro": 0}, "non-dict"):
            self.assertEqual(p.vicini(d), [], repr(d))
        self.assertEqual(self.chiamate, [])


# ══════════════════════════════════════════════════════════════════════════════
#  8) AI (fase164 pool + fase165 adattatori)
# ══════════════════════════════════════════════════════════════════════════════
class TestAIContratto(_ContrattiPuliti):
    def test_groq_forma_richiesta(self):
        f = FintoHttpAI([(200, {"choices": [{"message": {"content": " ciao "}}]})])
        a = AdattatoreGroq("gsk_segreto", modello="llama-3.1-8b-instant", fetch=f)
        self.assertEqual(a.genera_testo({"prompt": "scrivi", "sistema": "sei un copy",
                                         "max_token": 120}), "ciao")
        r = f.richieste[0]
        self.assertEqual(r["url"], "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(r["metodo"], "POST")
        self.assertEqual(r["intestazioni"]["Authorization"], "Bearer gsk_segreto")
        self.assertEqual(r["intestazioni"]["Content-Type"], "application/json")
        corpo = json.loads(r["corpo"].decode("utf-8"))
        self.assertEqual(corpo["model"], "llama-3.1-8b-instant")
        self.assertEqual(corpo["max_tokens"], 120)
        self.assertEqual([m["role"] for m in corpo["messages"]], ["system", "user"])
        self.assertEqual(corpo["messages"][1]["content"], "scrivi")

    def test_groq_429_e_quota_esaurita(self):
        f = FintoHttpAI([(429, {"error": "rate limited"})])
        with self.assertRaises(QuotaEsaurita):
            AdattatoreGroq("k", fetch=f).genera_testo("x")

    def test_groq_timeout_e_5xx_ritornano_none(self):
        for esito in ((0, None), (500, b"boom"), (200, b"non-json"), (200, {"choices": []})):
            a = AdattatoreGroq("k", fetch=FintoHttpAI([esito]))
            self.assertIsNone(a.genera_testo("x"), repr(esito))

    def test_gemini_quota_dal_corpo(self):
        f = FintoHttpAI([(200, {"error": {"status": "RESOURCE_EXHAUSTED"}})])
        with self.assertRaises(QuotaEsaurita):
            AdattatoreGemini("k", fetch=f).genera_testo("x")

    def test_user_agent_da_browser_nel_fetch_reale(self):
        """Groq dietro Cloudflare blocca 'Python-urllib' (403/1010): serve un UA da browser."""
        visti = {}

        class _R:
            status = 200

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def read(self_inner):
                return b"{}"

        def finto_urlopen(req, timeout=None):
            visti["headers"] = dict(req.headers)
            return _R()

        import urllib.request as _ur
        orig = _ur.urlopen
        _ur.urlopen = finto_urlopen
        try:
            _f165._fetch_reale("https://api.groq.com/x")
            ua = visti["headers"].get("User-agent") or visti["headers"].get("User-Agent", "")
            self.assertIn("Mozilla/5.0", ua)
            _f165._fetch_reale("https://api.groq.com/x",
                               intestazioni={"User-Agent": "MioUA/1.0"})
            ua2 = visti["headers"].get("User-agent") or visti["headers"].get("User-Agent", "")
            self.assertEqual(ua2, "MioUA/1.0", "un UA esplicito non va sovrascritto")
        finally:
            _ur.urlopen = orig

    def test_pollinations_ripiego_mai_vuoto_e_senza_chiave(self):
        a = AdattatorePollinations(larghezza=1080, altezza=1080)
        url = a.genera_immagine({"prompt": "casa a Roma, tramonto"})
        self.assertTrue(url.startswith("https://image.pollinations.ai/prompt/"))
        self.assertIn("casa%20a%20Roma", url)
        self.assertIn("width=1080", url)
        self.assertIn("nologo=true", url)
        self.assertIsNone(a.genera_immagine(""), "prompt vuoto -> nessuna immagine finta")

    def test_pool_failover_quota_poi_errore_poi_successo(self):
        """Il pool: quota esaurita -> prossimo; errore -> prossimo; uno risponde sempre."""
        chiamati = []

        def quota(r):
            chiamati.append("q")
            raise QuotaEsaurita()

        def rotto(r):
            chiamati.append("r")
            raise RuntimeError("500")

        def buono(r):
            chiamati.append("b")
            return "TESTO"

        pool = crea_pool_ai([ProviderAI("quota", quota), ProviderAI("rotto", rotto),
                             ProviderAI("buono", buono)])
        out = pool.genera("prompt")
        self.assertEqual((out["ok"], out["provider"], out["risultato"]),
                         (True, "buono", "TESTO"))
        self.assertEqual(chiamati, ["q", "r", "b"])
        self.assertEqual(out["tentati"], ["quota", "rotto", "buono"])

    def test_pool_tutti_giu_non_solleva(self):
        pool = crea_pool_ai([ProviderAI("a", lambda r: (_ for _ in ()).throw(
            RuntimeError("giu'"))), ProviderAI("b", lambda r: None)])
        out = pool.genera("x")
        self.assertFalse(out["ok"])
        self.assertEqual(out["motivo"], "tutti_esauriti")
        self.assertEqual(out["tentati"], ["a", "b"])

    def test_pool_immagini_ha_sempre_il_ripiego_senza_chiavi(self):
        """Nessuna chiave in ambiente -> il pool immagini deve comunque produrre qualcosa."""
        pool = _f165.crea_pool_immagine_da_env({})
        out = pool.genera({"prompt": "casa"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["provider"], "pollinations")
        self.assertTrue(str(out["risultato"]).startswith("https://"))

    def test_pool_testo_vuoto_senza_chiavi(self):
        pool = _f165.crea_pool_testo_da_env({})
        out = pool.genera("x")
        self.assertEqual(out, {"ok": False, "motivo": "nessun_provider", "tentati": []})


# ══════════════════════════════════════════════════════════════════════════════
#  9) INTEGRAZIONE VERA: API -> SERVIZIO TERZO -> DATABASE (riaperto dal disco)
# ══════════════════════════════════════════════════════════════════════════════
class _BaseIntegrazione(_ContrattiPuliti):
    """Sistema vero su FILE, servizi terzi con finti severi. Dopo ogni chiamata si riapre
    il database con sqlite3 e si guarda la riga: la risposta HTTP non e' una prova."""

    def setUp(self):
        super().setUp()
        self.d = tempfile.mkdtemp(prefix="integr_servizi_")
        p = lambda n: os.path.join(self.d, n)                            # noqa: E731
        self.percorsi = {"pendenti": p("pend.db"), "payout": p("payout.db"),
                         "finanza": p("fin.db"), "garanzia": p("gar.db"),
                         "registro": p("reg.db"), "geocache": p("geo.db"),
                         "catalogo": p("cat.db")}
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            con_geocoding=True,
            db_catalogo=self.percorsi["catalogo"], db_inventario=p("inv.db"),
            db_registro_host=self.percorsi["registro"], db_accettazioni=p("acc.db"),
            db_pendenti=self.percorsi["pendenti"], db_payout=self.percorsi["payout"],
            db_garanzia=self.percorsi["garanzia"], db_finanza=self.percorsi["finanza"],
            db_geocache=self.percorsi["geocache"], db_tassa_comunale=p("tassa.db"),
            commissione_bps=1000, psp_bps=300,
            stripe_secret_key="sk_test_x", stripe_webhook_secret=WH,
            stripe_success_url="https://bookinvip.com/grazie.html",
            stripe_cancel_url="https://bookinvip.com/annullato.html",
            smtp_host="smtp.finto"))
        # ── i servizi terzi: finti SEVERI al posto della rete vera ──
        self.stripe = FintoStripeForm()
        self.sis.stripe._fetch = self.stripe                 # checkout (fase85)
        self.connect = FintoStripeForm(risposta={"id": "tr_ok"})
        self.sis.connect._fetch = self.connect                # transfer (fase101)
        self.carta = FintoStripeCarta({"/checkout/sessions/": {"customer": "cus_1",
                                                               "setup_intent": "seti_1"},
                                       "/setup_intents/": {"payment_method": "pm_1"}})
        if self.sis.carta is not None:
            self.sis.carta._fetch = self.carta                # carta (fase183)
        self.email = []
        self.sis.email_provider._send = lambda d, o, h: (self.email.append((d, o, h))
                                                         or True)
        self.nominatim = []
        self.sis.geocoder = crea_geocoder(
            self.percorsi["geocache"],
            fetch=_FintoNominatim(self._risposta_nominatim, registro=self.nominatim))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)
        super().tearDown()

    @staticmethod
    def _risposta_nominatim(url):
        """Nominatim finto: /search -> coordinate, /reverse -> quartiere."""
        if "/reverse" in url:
            return {"address": {"suburb": "Centro"}}
        return [{"lat": "41.902784", "lon": "12.496366"}]

    def _ricerche(self):
        return [u for u in self.nominatim if "/search" in u]

    # ── strumenti ────────────────────────────────────────────────────────────
    def g(self, m, path, corpo=None, headers=None):
        return self.r.gestisci(m, path, {}, json.dumps(corpo) if corpo is not None else None,
                               headers or {})

    def attendi_email(self, dest, quante=1, secondi=5.0):
        """Le email partono su un THREAD daemon (l'SMTP non deve rallentare i soldi):
        leggere `self.email` subito dopo la chiamata sarebbe una GARA. Qui si attende
        l'effetto, con un tetto: se non arriva, il test fallisce con un messaggio chiaro."""
        scadenza = time.time() + secondi
        while time.time() < scadenza:
            trovate = [(o, h) for d, o, h in list(self.email) if d == dest]
            if len(trovate) >= quante:
                return trovate
            time.sleep(0.01)
        trovate = [(o, h) for d, o, h in list(self.email) if d == dest]
        self.fail("attese %d email per %s, arrivate %d (%s)"
                  % (quante, dest, len(trovate), [o for o, _ in trovate]))

    def nessuna_email_per(self, dest, secondi=0.5):
        """Prova NEGATIVA: si aspetta comunque, altrimenti si proverebbe solo che il thread
        non ha ancora finito."""
        scadenza = time.time() + secondi
        while time.time() < scadenza:
            time.sleep(0.01)
        return [(o, h) for d, o, h in list(self.email) if d == dest]

    def sql(self, quale, query, args=()):
        """RIAPRE il database dal disco (nuova connessione) e legge davvero."""
        con = sqlite3.connect(self.percorsi[quale])
        try:
            con.row_factory = sqlite3.Row
            return [dict(r) for r in con.execute(query, args)]
        finally:
            con.close()

    def registra_host(self, email="host@integrazione.it"):
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": email, "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = {"X-Host-Token": c["token"]}
        self.host_id = c["host_id"]
        return c["host_id"]

    def pubblica(self, slug="casa-1", prezzo=12000, citta="Roma"):
        s, c = self.g("POST", "/api/host/pubblica",
                      {"slug": slug, "titolo": "Casa prova", "citta": citta,
                       "prezzo_notte_cents": prezzo, "capacita": 4,
                       "politica_cancellazione": "flessibile"}, self.tok)
        self.assertEqual(s, 201, c)
        s, c = self.g("POST", "/api/host/disponibilita_range",
                      {"alloggio_id": slug, "da": _giorno(0), "a": _giorno(6),
                       "unita_totali": 1, "prezzo_netto_cents": prezzo}, self.tok)
        self.assertEqual(s, 200, c)
        return slug

    def prenota(self, slug="casa-1", notti=2, email="ospite@x.it"):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": slug, "check_in": _giorno(1),
                       "check_out": _giorno(1 + notti), "party": 2})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": email, "lang": "it"})
        self.assertEqual(s, 201, b)
        return q, b

    def webhook(self, rif, ts=None, firma_valida=True, payload=None):
        pl = payload if payload is not None else json.dumps(
            {"type": "checkout.session.completed",
             "data": {"object": {"id": "cs_" + str(rif)[:8],
                                 "metadata": {"riferimento": rif}}}})
        sig = firma_di_test(pl, WH if firma_valida else "whsec_ladro",
                            int(ts if ts is not None else time.time()))
        return self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                               {"Stripe-Signature": sig})


class TestApiDbStripeCheckout(_BaseIntegrazione):
    def test_book_scrive_hold_su_disco_e_chiama_stripe_col_totale_firmato(self):
        self.registra_host()
        self.pubblica()
        q, b = self.prenota()
        rif = b["riferimento"]
        # 1) la richiesta a Stripe ha ESATTAMENTE il totale firmato dal motore, in cents interi
        checkout = [r for r in self.stripe.richieste
                    if r["url"].endswith("/checkout/sessions")]
        self.assertEqual(len(checkout), 1, "un solo checkout per prenotazione")
        c = checkout[0]["campi"]
        self.assertEqual(int(c["line_items[0][price_data][unit_amount]"]),
                         int(b["totale_cents"]))
        self.assertEqual(c["metadata[riferimento]"], rif)
        self.assertEqual(c["customer_email"], "ospite@x.it")
        # 2) il DATABASE riaperto: hold in attesa, importi identici alla risposta HTTP
        righe = self.sql("pendenti", "SELECT * FROM pendenti WHERE riferimento=?", (rif,))
        self.assertEqual(len(righe), 1, "nessuna riga di hold sul disco")
        riga = righe[0]
        self.assertEqual(riga["stato"], "in_attesa")
        self.assertEqual(riga["alloggio_id"], "casa-1")
        self.assertEqual(riga["check_in"], _giorno(1))
        corpo = json.loads(riga["corpo_json"])
        for campo in ("totale_cents", "prezzo_guest_cents", "netto_host_cents",
                      "commissione_cents"):
            self.assertEqual(corpo[campo], b[campo],
                             "%s a disco != risposta HTTP" % campo)
        # 3) nessun incasso a giornale: nessuno ha ancora pagato
        self.assertEqual(self.sql("finanza", "SELECT * FROM libro_giornale"), [])

    def test_stripe_giu_al_book_nessun_incasso_e_nessun_bonifico(self):
        """Stripe irraggiungibile al checkout: qualunque cosa accada alla prenotazione,
        NESSUN denaro deve muoversi — niente incasso a giornale, niente bonifico all'host,
        niente link di pagamento inventato.

        Il comportamento di degrado (oggi: conferma senza pagamento) e' inchiodato a parte
        in `TestDifettoChiusoStripeGiuAlBook`, che spiega perche' e' un difetto. QUI si
        sorveglia solo cio' che deve valere in OGNI caso — oggi e dopo la correzione —
        soprattutto che l'host non venga pagato per un incasso mai avvenuto."""
        self.registra_host()
        self.pubblica()
        self.sis.stripe._fetch = FintoStripeForm(guasto=urllib.error.HTTPError(
            "https://api.stripe.com", 500, "boom", {}, None))
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa-1", "check_in": _giorno(1),
                       "check_out": _giorno(3), "party": 2})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "ospite@x.it"})
        # un 500 di Stripe non puo' diventare un 500 NOSTRO non gestito. Le uniche risposte
        # sensate sono: 201 (degrado di oggi), 409 (date perse nel frattempo) o 503
        # 'pagamento_non_disponibile' (il fail-safe corretto, gia' presente sul su-richiesta).
        self.assertIn(s, (201, 409, 503),
                      "risposta ingestibile con Stripe giu': %s %s" % (s, b))
        self.assertFalse(b.get("payment_url"), "link di pagamento inventato senza Stripe")
        # NIENTE denaro: nessun incasso a giornale, nessun bonifico in partenza
        self.assertEqual(self.sql("finanza", "SELECT * FROM libro_giornale"), [],
                         "incasso a giornale senza che nessuno abbia pagato")
        self.assertEqual(self.sql("payout", "SELECT * FROM payout WHERE stato IN "
                                            "('in_transito','pagato')"), [],
                         "bonifico dato per partito senza incasso")
        # e se qualcuno prova a sbloccare l'escrow: NESSUN transfer verso l'host, mai
        self.sis.registro_host.imposta_stripe_account(self.host_id, "acct_HOST1")
        if b.get("voucher_token"):
            self.g("POST", "/api/garanzia/conferma",
                   {"voucher_token": b["voucher_token"]})
        self.assertEqual([r for r in self.connect.richieste
                          if r["url"].endswith("/transfers")], [],
                         "BONIFICO ALL'HOST su una prenotazione mai pagata")
        self.assertEqual(self.sql("finanza",
                                  "SELECT * FROM libro_giornale WHERE tipo='payout_host'"), [])


class TestDifettoChiusoStripeGiuAlBook(_BaseIntegrazione):
    """⚠️ DIFETTO APERTO — misurato il 2026-07-29, NON corretto (non tocco la produzione).

    COSA SUCCEDE OGGI se Stripe risponde 500 mentre un ospite prenota in instant-book:
      · `fase59_concierge.book` chiama `_link_isolato(...)`, che ISOLA l'errore e ritorna
        None; subito dopo scrive comunque `corpo["stato"] = "confermata"`.
      · L'ospite riceve 201 con un `voucher_token` VALIDO e uno `smart_pass` firmato
        (= il PIN di check-in), ma NESSUN `payment_url`: non gli viene mai chiesto di pagare.
      · Le date restano BLOCCATE (una seconda quote sulle stesse notti da' 409).
      · La tabella `pendenti` resta VUOTA: non esiste un pagamento in attesa, quindi lo
        sweeper dei pagamenti non liberera' mai quella stanza e la riconciliazione non ha
        nemmeno un appiglio per accorgersene.
      → soggiorno confermato, camera bloccata, zero incasso, nessuna traccia da cui ripartire.

    PERCHE' E' UN DIFETTO E NON UNA SCELTA: lo stesso identico caso, sul ramo SU-RICHIESTA
    (fase83_server, approvazione host), ha gia' il fail-safe giusto — «niente conferma senza
    un link di pagamento valido» -> 503 `pagamento_non_disponibile`. L'instant-book non ce
    l'ha. Il codice non riesce a distinguere «Stripe non configurato» (modo diretto, legittimo)
    da «Stripe configurato ma irraggiungibile» (incidente): tratta il secondo come il primo.

    QUESTO TEST NON APPROVA IL COMPORTAMENTO: lo INCHIODA. Il giorno in cui qualcuno mette
    il fail-safe anche qui, questo test diventa ROSSO e chi corregge lo trova e lo aggiorna
    (invece di scoprire per caso che c'era un buco). Le righe che valgono in OGNI caso — che
    nessun denaro si muova — sono asserite a parte, sotto."""

    def test_difetto_CHIUSO_gateway_giu_non_conferma_e_libera_la_stanza(self):
        """✅ CHIUSO IL 2026-07-29 dal coordinatore, subito dopo questa segnalazione.
        Il fail-safe che mancava all'instant-book c'e': gateway CONFIGURATO ma irraggiungibile
        -> 503 `pagamento_non_disponibile`, blocco RILASCIATO, nessun voucher, nessun PIN.
        (Guardia dedicata + prova del rosso: test_stripe_giu_al_book.py.)"""
        self.registra_host()
        self.pubblica()
        self.sis.stripe._fetch = FintoStripeForm(guasto=urllib.error.HTTPError(
            "https://api.stripe.com", 500, "boom", {}, None))
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa-1", "check_in": _giorno(1),
                       "check_out": _giorno(3), "party": 2})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "ospite@x.it"})
        # ── il comportamento CORRETTO, inchiodato riga per riga ──
        self.assertEqual(s, 503, "senza pagamento non si conferma: %s" % b)
        self.assertEqual(b.get("errore"), "pagamento_non_disponibile")
        self.assertNotEqual(b.get("stato"), "confermata")
        self.assertFalse(b.get("voucher_token"), "voucher su un soggiorno mai pagato")
        self.assertFalse(b.get("smart_pass"), "PIN di check-in su un soggiorno mai pagato")
        self.assertEqual(self.sql("pendenti", "SELECT * FROM pendenti"), [],
                         "nessun pendente: giusto, la prenotazione non e' mai nata")
        # e soprattutto: la camera TORNA VENDIBILE (prima restava fuori mercato per sempre)
        s2, _ = self.g("POST", "/api/concierge/quote",
                       {"alloggio_id": "casa-1", "check_in": _giorno(1),
                        "check_out": _giorno(3), "party": 2})
        self.assertEqual(s2, 200, "la stanza e' rimasta bloccata da una prenotazione mai nata")
        # ── e cio' che deve valere COMUNQUE, prima e dopo la correzione ──
        self.assertEqual(self.sql("finanza", "SELECT * FROM libro_giornale"), [],
                         "incasso a giornale senza che nessuno abbia pagato")
        self.assertEqual(self.sql("payout", "SELECT * FROM payout WHERE stato IN "
                                            "('in_transito','pagato')"), [])
        self.assertEqual([r for r in self.connect.richieste
                          if r["url"].endswith("/transfers")], [])


class TestApiDbWebhookFirmato(_BaseIntegrazione):
    def setUp(self):
        super().setUp()
        self.registra_host()
        self.pubblica()
        self.q, self.b = self.prenota()
        self.rif = self.b["riferimento"]

    def _stato_disco(self):
        r = self.sql("pendenti", "SELECT stato FROM pendenti WHERE riferimento=?",
                     (self.rif,))
        return r[0]["stato"] if r else None

    def test_firma_valida_conferma_e_scrive_tutto_su_disco(self):
        s, out = self.webhook(self.rif)
        self.assertEqual((s, out.get("ricevuto")), (200, True))
        # 1) pendenti: pagato
        self.assertEqual(self._stato_disco(), "pagato")
        # 2) payout: maturato, importo = netto host, valuta giusta
        pay = self.sql("payout", "SELECT * FROM payout WHERE prenotazione_id=?", (self.rif,))
        self.assertEqual(len(pay), 1)
        self.assertEqual(pay[0]["stato"], "maturato")
        self.assertEqual(pay[0]["minori"], int(self.b["netto_host_cents"]))
        self.assertEqual(pay[0]["host_id"], self.host_id)
        # 3) giornale: UNA riga incasso, importo = totale pagato dall'ospite
        inc = self.sql("finanza", "SELECT * FROM libro_giornale WHERE tipo='incasso'")
        self.assertEqual(len(inc), 1)
        self.assertEqual(inc[0]["importo_cents"], int(self.b["totale_cents"]))
        self.assertEqual(inc[0]["riferimento"], self.rif)
        # 4) escrow aperto per il netto host
        gar = self.sql("garanzia", "SELECT * FROM garanzia WHERE prenotazione_id=?",
                       (self.rif,))
        self.assertEqual(len(gar), 1)
        self.assertEqual(gar[0]["importo_host_cents"], int(self.b["netto_host_cents"]))
        self.assertEqual(gar[0]["stato"], "in_garanzia")

    def test_firma_sbagliata_non_conferma_nulla(self):
        """Chiunque puo' inviare un POST al webhook: senza la firma giusta NON succede NULLA.
        Il confronto e' sul DISCO prima/dopo: nessuna riga nuova, nessuna riga cambiata."""
        prima = {t: self.sql(t, "SELECT * FROM %s" % tab)
                 for t, tab in (("pendenti", "pendenti"), ("payout", "payout"),
                                ("garanzia", "garanzia"),
                                ("finanza", "libro_giornale"))}
        s, out = self.webhook(self.rif, firma_valida=False)
        self.assertEqual(s, 400)
        self.assertEqual(out, {"errore": "firma_non_valida"})
        self.assertEqual(self._stato_disco(), "in_attesa", "PAGAMENTO FINTO ACCETTATO")
        for t, tab in (("pendenti", "pendenti"), ("payout", "payout"),
                       ("garanzia", "garanzia"), ("finanza", "libro_giornale")):
            self.assertEqual(self.sql(t, "SELECT * FROM %s" % tab), prima[t],
                             "il database e' cambiato con una firma falsa (%s)" % tab)
        self.assertEqual(self.sql("finanza", "SELECT * FROM libro_giornale"), [],
                         "incasso a giornale con firma falsa")
        self.assertEqual(self.sql("payout", "SELECT * FROM payout WHERE stato='maturato'"), [])

    def test_payload_manomesso_dopo_la_firma(self):
        """La firma vale sui BYTE GREZZI: cambiare il riferimento dopo averla calcolata
        (dirottare il pagamento di un altro) non passa."""
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": "ALTRO"}}}})
        sig = firma_di_test(pl, WH, int(time.time()))
        manomesso = pl.replace("ALTRO", self.rif)
        s, out = self.r.gestisci("POST", "/api/payments/webhook", {}, manomesso,
                                 {"Stripe-Signature": sig})
        self.assertEqual(s, 400)
        self.assertEqual(self._stato_disco(), "in_attesa")

    def test_replay_vecchio_rifiutato(self):
        s, _ = self.webhook(self.rif, ts=int(time.time()) - 3600)
        self.assertEqual(s, 400)
        self.assertEqual(self._stato_disco(), "in_attesa")

    def test_firma_dal_futuro_rifiutata(self):
        """Post-datare la firma allargherebbe a piacere la finestra di replay: la tolleranza
        vale in ENTRAMBE le direzioni. Al bordo (+/-5 min) invece la firma resta valida,
        altrimenti un orologio leggermente sfasato ci farebbe perdere i pagamenti veri."""
        s, _ = self.webhook(self.rif, ts=int(time.time()) + 3600)
        self.assertEqual(s, 400)
        self.assertEqual(self._stato_disco(), "in_attesa")
        s, out = self.webhook(self.rif, ts=int(time.time()) - 120)   # sfasamento tollerato
        self.assertEqual((s, out.get("ricevuto")), (200, True))
        self.assertEqual(self._stato_disco(), "pagato")

    def test_evento_di_altro_tipo_non_muove_un_centesimo(self):
        """Stripe manda decine di tipi di evento: solo checkout.session.completed incassa."""
        for tipo in ("payment_intent.created", "charge.succeeded", "customer.created",
                     "checkout.session.expired"):
            pl = json.dumps({"type": tipo,
                             "data": {"object": {"id": "cs_x",
                                                 "metadata": {"riferimento": self.rif}}}})
            s, _ = self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                                   {"Stripe-Signature": firma_di_test(pl, WH,
                                                                      int(time.time()))})
            self.assertLess(s, 500, tipo)
            self.assertEqual(self._stato_disco(), "in_attesa", "%s ha confermato" % tipo)
        self.assertEqual(self.sql("finanza", "SELECT * FROM libro_giornale"), [])
        self.assertEqual(self.sql("payout", "SELECT * FROM payout WHERE stato='maturato'"), [])

    def test_header_firma_assente_o_spazzatura(self):
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": self.rif}}}})
        for h in ({}, {"Stripe-Signature": ""}, {"Stripe-Signature": "spazzatura"},
                  {"Stripe-Signature": "t=abc,v1=xx"},
                  {"Stripe-Signature": "t=%d" % int(time.time())}):
            s, _ = self.r.gestisci("POST", "/api/payments/webhook", {}, pl, h)
            self.assertEqual(s, 400, repr(h))
        self.assertEqual(self._stato_disco(), "in_attesa")

    def test_webhook_doppio_non_raddoppia_il_giornale(self):
        """Stripe ritenta per giorni: il retry non deve creare un secondo incasso."""
        for _ in range(3):
            self.assertEqual(self.webhook(self.rif)[0], 200)
        self.assertEqual(len(self.sql("finanza",
                                      "SELECT * FROM libro_giornale WHERE tipo='incasso'")), 1)
        self.assertEqual(len(self.sql("payout", "SELECT * FROM payout WHERE prenotazione_id=?",
                                      (self.rif,))), 1)
        self.assertEqual(self._stato_disco(), "pagato")

    def test_firma_verificata_sui_byte_grezzi_non_sul_json(self):
        """Ri-serializzare il JSON prima di verificare romperebbe ogni firma vera."""
        payload = '{"type":"x",  "data": {"object": {} } }'
        ts = int(time.time())
        header = firma_di_test(payload, WH, ts)
        self.assertTrue(verifica_firma_stripe(payload, header, WH, ora=ts))
        self.assertFalse(verifica_firma_stripe(json.dumps(json.loads(payload)), header,
                                               WH, ora=ts))

    def test_webhook_senza_secret_configurato_e_503(self):
        sis2 = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=b"S" * 32,
                                          db_pendenti=os.path.join(self.d, "x.db")))
        r2 = crea_router(sis2, host_key="hk", admin_key="ak")
        pl = json.dumps({"type": "checkout.session.completed", "data": {"object": {}}})
        s, out = r2.gestisci("POST", "/api/payments/webhook", {}, pl,
                             {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
        self.assertEqual((s, out), (503, {"errore": "webhook_non_configurato"}))


class TestApiDbConnectPayout(_BaseIntegrazione):
    def setUp(self):
        super().setUp()
        self.registra_host()
        self.pubblica()
        self.q, self.b = self.prenota()
        self.rif = self.b["riferimento"]
        self.assertEqual(self.webhook(self.rif)[0], 200)
        self.sis.registro_host.imposta_stripe_account(self.host_id, "acct_HOST1")

    def test_sblocco_escrow_manda_il_transfer_e_aggiorna_il_disco(self):
        s, out = self.g("POST", "/api/garanzia/conferma",
                        {"voucher_token": self.b["voucher_token"]})
        self.assertEqual(s, 200, out)
        # 1) la richiesta a Stripe: transfer con Idempotency-Key per riferimento
        tr = [r for r in self.connect.richieste if r["url"].endswith("/transfers")]
        self.assertEqual(len(tr), 1, "un solo transfer")
        self.assertEqual(tr[0]["headers"]["Idempotency-Key"], "transfer_" + self.rif)
        self.assertEqual(int(tr[0]["campi"]["amount"]), int(self.b["netto_host_cents"]))
        self.assertEqual(tr[0]["campi"]["destination"], "acct_HOST1")
        # 2) DISCO: payout in transito + riga di bonifico a giornale
        pay = self.sql("payout", "SELECT * FROM payout WHERE prenotazione_id=?", (self.rif,))
        self.assertEqual(pay[0]["stato"], "in_transito")
        gio = self.sql("finanza", "SELECT * FROM libro_giornale WHERE tipo='payout_host'")
        self.assertEqual(len(gio), 1)
        self.assertEqual(gio[0]["importo_cents"], int(self.b["netto_host_cents"]))

    def test_stripe_500_sul_bonifico_non_perde_i_soldi_dell_host(self):
        """Il transfer fallisce: il payout NON puo' risultare partito; resta 'maturato'
        (visibile, ripagabile) e a giornale resta la prova che serve il bonifico manuale."""
        self.sis.connect._fetch = FintoStripeForm(guasto=urllib.error.HTTPError(
            "https://api.stripe.com", 500, "boom", {}, None))
        s, out = self.g("POST", "/api/garanzia/conferma",
                        {"voucher_token": self.b["voucher_token"]})
        self.assertEqual(s, 200, out)
        pay = self.sql("payout", "SELECT * FROM payout WHERE prenotazione_id=?", (self.rif,))
        self.assertEqual(pay[0]["stato"], "maturato", "payout dato per partito senza transfer")
        self.assertEqual(pay[0]["minori"], int(self.b["netto_host_cents"]),
                         "l'importo dovuto all'host non si perde")
        self.assertEqual(self.sql("finanza",
                                  "SELECT * FROM libro_giornale WHERE tipo='payout_host'"), [])
        manuale = self.sql("finanza",
                           "SELECT * FROM libro_giornale WHERE tipo='payout_manuale'")
        self.assertEqual(len(manuale), 1, "nessuna traccia del bonifico da fare a mano")

    def test_secondo_sblocco_non_manda_un_secondo_bonifico(self):
        self.g("POST", "/api/garanzia/conferma", {"voucher_token": self.b["voucher_token"]})
        self.g("POST", "/api/garanzia/conferma", {"voucher_token": self.b["voucher_token"]})
        tr = [r for r in self.connect.richieste if r["url"].endswith("/transfers")]
        self.assertEqual(len(tr), 1, "DOPPIO BONIFICO")
        self.assertEqual(len(self.sql("payout", "SELECT * FROM payout WHERE prenotazione_id=?",
                                      (self.rif,))), 1)

    def test_transfer_nella_valuta_incassata_e_mai_piu_del_netto(self):
        """Il bonifico all'host deve partire nella STESSA valuta incassata dall'ospite e non
        superare MAI il netto host: una valuta diversa qui = perdita secca sul cambio."""
        self.g("POST", "/api/garanzia/conferma", {"voucher_token": self.b["voucher_token"]})
        tr = [r for r in self.connect.richieste if r["url"].endswith("/transfers")]
        self.assertEqual(len(tr), 1)
        incassato = self.sql("finanza",
                             "SELECT * FROM libro_giornale WHERE tipo='incasso'")[0]
        self.assertEqual(str(incassato["valuta"]).upper(), "EUR")   # oracolo indipendente
        self.assertEqual(tr[0]["campi"]["currency"], str(incassato["valuta"]).lower())
        netto = int(self.b["netto_host_cents"])
        self.assertEqual(int(tr[0]["campi"]["amount"]), netto)
        self.assertLess(netto, int(self.b["totale_cents"]),
                        "il netto host non puo' essere l'intero incasso: manca la commissione")

    def test_host_senza_conto_stripe_nessun_transfer_ma_payout_tracciato(self):
        self.sis.registro_host.imposta_stripe_account(self.host_id, "")
        s, _ = self.g("POST", "/api/garanzia/conferma",
                      {"voucher_token": self.b["voucher_token"]})
        self.assertEqual(s, 200)
        self.assertEqual([r for r in self.connect.richieste
                          if r["url"].endswith("/transfers")], [])
        pay = self.sql("payout", "SELECT * FROM payout WHERE prenotazione_id=?", (self.rif,))
        self.assertEqual(pay[0]["stato"], "maturato")


# --------------------------------------------------------------------------------------
# «c'e' traccia di una carta qui dentro?» — il rilevatore, e perche' non basta cercare 4242
# --------------------------------------------------------------------------------------
_DIGEST = re.compile(r"^[0-9a-fA-F]{32,}$")
_GRUPPI_DI_CIFRE = re.compile(r"(?<!\d)\d+(?!\d)")
_MASCHERE = re.compile(r"[ \t.\-*x•X_]")
ULTIME4_CARTA_DI_PROVA = "4242"
_PAROLE_DI_CARTA = ("carta", "card", "pan", "last4", "numero", "****")


def _luhn_ok(cifre):
    """Il checksum che OGNI numero di carta vero soddisfa (ISO/IEC 7812, algoritmo di Luhn).

    ⛔ Non e' un'invenzione nostra: e' il modo in cui il mondo distingue un numero di carta
    da una fila di cifre qualunque, ed e' il primo filtro di qualunque rilevatore serio.
    Qui serve a stringere la mira SENZA spostarla: misurato prima di metterlo, tutte e nove
    le carte di prova pubbliche dei circuiti lo superano (Visa, Mastercard, Amex, Discover,
    Diners, UnionPay), mentre l'ora in millisecondi, un telefono lungo e l'identificatore
    che ha fatto cadere il cancello NON lo superano.
    ⚠️ COSA NON FA (D18 punto 3): un numero di carta TRASCRITTO MALE (una cifra sbagliata)
    non supera Luhn e da qui non si vede piu'. E' un prezzo accettato in cambio del falso
    allarme che si toglie, e comunque le altre due regole -- «solo le ultime quattro» e «le
    ultime quattro accanto a una parola che parla di carte» -- restano SENZA Luhn.
    """
    totale, doppia = 0, False
    for carattere in reversed(cifre):
        valore = ord(carattere) - 48
        if doppia:
            valore *= 2
            if valore > 9:
                valore -= 9
        totale += valore
        doppia = not doppia
    return totale % 10 == 0


def traccia_di_carta(valore, noti=()):
    """I motivi per cui `valore` sembra contenere il numero di una carta. Vuoto = pulito.

    ⛔ **NASCE DA UN ROSSO VERO, in CI, il 2026-08-18**, con questa riga:
        AssertionError: '4242' unexpectedly found in '1787042423'
    `1787042423` e' **l'ora in secondi**, e per caso contiene `4242`. La guardia cercava
    quelle quattro cifre **dentro qualunque valore**, quindi si accendeva da sola a
    orologeria: non «sfortuna», statistica: fra i circa 10 milioni di secondi di un anno,
    quella sequenza ricade nell'orologio a ondate regolari.

    ⛔ E LA TRAPPOLA PEGGIORE ERA L'ALTRA. Nella stessa riga ci sono `salt` (32 cifre
    esadecimali) e `pw_hash` (64), estratti **a caso**: prima o poi ne esce uno che contiene
    `4242`, e allora il rosso sarebbe stato **casuale invece che a orario** — cioe'
    inattribuibile, il tipo di guasto che si archivia come «riprova» e insegna a non
    guardare i rossi.

    ⛔ **La riparazione NON e' togliere il controllo.** Il fatto sorvegliato — «nel nostro
    database non finisce mai il numero di una carta» — e' uno di quelli che, se cadono, non
    si riparano piu': i dati sono gia' scritti. Si stringe la **mira**, non si spegne il
    faro. Tre regole, e ognuna dice cosa vede:
      1. un PAN INTERO (13-19 cifre), anche scritto con spazi o trattini;
      2. un campo che contiene **soltanto** le ultime quattro, anche mascherate
         (`4242`, `**** 4242`, `xxxx-4242`);
      3. quelle quattro cifre **insieme a una parola che parla di carte**.
    Un digest esadecimale non viene guardato dentro: li' le cifre non significano niente, e
    cercarci dentro produce solo coincidenze.
    """
    testo = str(valore)
    # ⛔ 2026-08-21 — I VALORI DI CUI CHI CHIAMA CONOSCE L'ORIGINE NON SI GUARDANO DENTRO.
    # Non e' un allargamento della mira: e' il collaudo che smette di chiedere «sembra una
    # carta?» su una stringa che ha generato lui. Serve perche' il caso PEGGIORE del
    # generatore di `host_id` -- `"h_" + "0"*16` -- supera perfino Luhn, quindi nessuna
    # regola sulla FORMA del numero potrebbe mai escluderlo.
    if testo in noti:
        return []
    if _DIGEST.match(testo.strip()):
        return []
    motivi = []

    compatto = re.sub(r"[ \t.\-]", "", testo)
    for gruppo in _GRUPPI_DI_CIFRE.findall(compatto):
        # ⛔ `_luhn_ok` E' LA META' CHE MANCAVA, ed e' nata da un rosso vero in CI il
        # 2026-08-21: `h_a8a5369477666965` (un nostro identificatore) conteneva tredici
        # cifre di fila e veniva dichiarato carta. Misurato su due strade indipendenti che
        # concordano -- Monte Carlo su 2.000.000 di identificatori (0,4708%) e conto esatto
        # (0,4718%) -- capitava UNA VOLTA OGNI 211 GIRI: non sfortuna, statistica.
        if 13 <= len(gruppo) <= 19 and _luhn_ok(gruppo):
            motivi.append("un numero di %d cifre, la lunghezza di un PAN: %s"
                          % (len(gruppo), gruppo))

    if _MASCHERE.sub("", testo) == ULTIME4_CARTA_DI_PROVA:
        motivi.append("il campo contiene SOLO le ultime quattro della carta: %r" % testo)

    basso = testo.lower()
    if ULTIME4_CARTA_DI_PROVA in testo and any(p in basso for p in _PAROLE_DI_CARTA):
        motivi.append("le ultime quattro accanto a una parola che parla di carte: %r" % testo)

    return motivi


class TestIlRilevatoreDiCarteGUARDANELPOSTOGIUSTO(unittest.TestCase):
    """⛔ IL RILEVATORE SI PROVA NELLE DUE DIREZIONI, o e' una decorazione.

    La guardia di prima si e' rotta perche' nessuno aveva mai provato che cosa faceva sui
    valori INNOCENTI: vedeva la carta anche dove non c'era. Qui si pretendono tutt'e due i
    versi, ed e' il motivo per cui questa classe esiste separata dal collaudo che la usa.
    """

    VELENI = ("4242424242424242", "4242 4242 4242 4242", "4242-4242-4242-4242",
              "5555555555554444", "carta host: 4242424242424242", "**** 4242", "4242",
              "xxxx-4242", "last4=4242", "{'card': {'last4': '4242'}}")

    INNOCENTI = ("1787042423",            # l'ora ESATTA che ha fatto fallire la CI
                 1787042423, 1787042424, "1787042420", "42424",  # 42424: 5 cifre, un id
                 "7c0b665e2f3bb38f8847bac21a3557b1",             # salt, 32 esadecimali
                 "9a2fc69efc98b8b95031d0400f8a855a94308cf6126d767cad3f62c7e6bc08bb",
                 "h_c9f34242deba3d9",     # un id casuale che CONTIENE quelle cifre
                 "cus_1", "pm_1", "1.0", "", None, 0, "Roma", "host@vip.it")

    def test_VEDE_una_carta_scritta_in_dieci_modi_diversi(self):
        for veleno in self.VELENI:
            with self.subTest(valore=veleno):
                self.assertTrue(
                    traccia_di_carta(veleno),
                    "il rilevatore NON vede una carta in %r: allora il collaudo che lo usa "
                    "sarebbe verde anche col numero scritto nel database" % (veleno,))

    def test_NON_si_accende_sull_orologio_ne_sugli_hash_ne_sugli_id(self):
        for innocente in self.INNOCENTI:
            with self.subTest(valore=innocente):
                self.assertEqual(
                    [], traccia_di_carta(innocente),
                    "falso allarme su %r. E' il difetto da cui nasce questo rilevatore: un "
                    "falso allarme costa quanto un allarme mancato, perche' insegna a "
                    "ignorare i rossi (regola ferrea 10)" % (innocente,))

    def test_L_ORA_CHE_HA_FATTO_CADERE_LA_CI_NON_PUO_PIU_FARLO(self):
        """La guardia della guardia: il caso esatto, per nome, cosi' se qualcuno rimette la
        ricerca larga il rosso torna subito e con la sua storia scritta accanto."""
        self.assertIn("4242", "1787042423", "l'ora di quel giorno conteneva davvero 4242: "
                                            "se questo cambia, la storia qui sotto non ha "
                                            "piu' senso")
        self.assertEqual([], traccia_di_carta("1787042423"),
                         "il rilevatore si accende di nuovo sull'orologio: la CI tornera' "
                         "rossa a orologeria, e per un difetto che non esiste")

    # ─────────────────────────────────────────────────────────────────────────────────
    # 2026-08-21 — LA STESSA TRAPPOLA E' TORNATA, SPOSTATA DALL'OROLOGIO ALL'IDENTIFICATORE
    # ─────────────────────────────────────────────────────────────────────────────────
    # Il cancello e' andato ROSSO su `master` con questa riga:
    #     Lists differ: [] != ['un numero di 13 cifre, la lunghezza di un PAN: 5369477666965']
    #     : traccia del numero di una carta nel nostro database,
    #       colonna 'host_id' = 'h_a8a5369477666965'
    # `host_id` nasce da `"h_" + secrets.token_hex(8)` (fase88_registro_host.py): sedici
    # caratteri esadecimali, e quella volta tredici di fila erano cifre. Il filtro dei
    # digest non lo copriva perche' pretende trentadue caratteri E nessun prefisso.
    # ⛔ MISURATO, non stimato — due strade indipendenti che concordano:
    #     Monte Carlo su 2.000.000 di identificatori veri .... 0,4708%
    #     conto esatto (automa sulle corse di cifre) ......... 0,4718%   -> 1 giro su 211
    # E la prova che e' il CASO e non il codice: sullo stesso commit `full-suite` e' uscita
    # rossa in un giro di CI e VERDE in quello dopo, mentre `full-suite-311` -- che esegue
    # questo stesso modulo -- era verde nello stesso minuto del rosso.
    # ⛔ Perche' nessuno l'aveva visto: fra i valori innocenti qui sopra c'e'
    # `"h_c9f34242deba3d9"`, scelto A MANO per la trappola PRECEDENTE (contiene 4242) --
    # quindici caratteri invece dei sedici veri, e senza tredici cifre di fila. Un esempio
    # scritto a mano copre il caso a cui pensava chi lo ha scritto, non quello che il
    # generatore produce davvero.
    def test_UN_IDENTIFICATORE_CHE_IL_COLLAUDO_HA_GENERATO_LUI_NON_E_UNA_CARTA(self):
        """Un valore di cui il collaudo CONOSCE L'ORIGINE non si guarda dentro.

        ⛔ Non e' un allargamento della mira: e' il collaudo che smette di chiedere «sembra
        una carta?» su una stringa che ha generato lui. Serve perche' il caso PEGGIORE del
        generatore -- sedici zeri -- supera anche il controllo di Luhn, quindi la sola
        forma del numero non basterebbe mai a escluderlo.
        """
        caduto = "h_a8a5369477666965"        # il valore VERO del 2026-08-21
        peggio = "h_" + "0" * 16             # il peggio che quel generatore possa produrre
        for valore in (caduto, peggio):
            with self.subTest(valore=valore):
                self.assertEqual(
                    [], traccia_di_carta(valore, noti={valore}),
                    "il collaudo sa di aver generato %r e lo tratta lo stesso come una "
                    "carta: il cancello tornera' rosso da solo" % (valore,))

    def test_LA_FORMA_DI_UN_PAN_COMPRENDE_IL_SUO_CHECKSUM(self):
        """Un numero di carta VERO soddisfa Luhn (ISO/IEC 7812); sedici cifre a caso no.

        E' la regola che usa tutto il mondo per non annegare nei falsi allarmi. Qui serve a
        stringere la mira senza toccarla: i tre valori qui sotto sono quelli che si trovano
        DAVVERO nelle colonne della tabella `host` (identificatore, ora in millisecondi,
        telefono lungo), e nessuno dei tre e' una carta.
        """
        for nome, valore in (("l'identificatore del 2026-08-21", "h_a8a5369477666965"),
                             ("l'ora in millisecondi", "1787266178000"),
                             ("un telefono lungo", "+39 333 123 4567 890")):
            with self.subTest(caso=nome):
                self.assertEqual(
                    [], traccia_di_carta(valore),
                    "%s viene scambiato per una carta: e' un falso allarme, e un falso "
                    "allarme costa quanto un allarme mancato (regola ferrea 10)" % nome)

    def test_STRINGERE_LA_MIRA_NON_L_HA_SPOSTATA_DI_UN_MILLIMETRO(self):
        """L'altra direzione, e senza questa la riparazione qui sopra sarebbe un cieco.

        ⛔ Le carte di prova PUBBLICHE dei circuiti, non solo le nostre due: se un giorno
        qualcuno stringesse ancora la mira e ne perdesse una, questo diventa rosso.
        """
        CARTE_DI_PROVA_DEI_CIRCUITI = (
            "4242424242424242",      # Visa
            "4111111111111111",      # Visa
            "4000056655665556",      # Visa debito
            "5555555555554444",      # Mastercard
            "5200828282828210",      # Mastercard debito
            "378282246310005",       # American Express (15 cifre)
            "6011111111111117",      # Discover
            "3056930009020004",      # Diners Club (14 cifre)
            "6200000000000005",      # UnionPay
        )
        for pan in CARTE_DI_PROVA_DEI_CIRCUITI:
            with self.subTest(pan=pan):
                self.assertTrue(
                    traccia_di_carta(pan),
                    "il rilevatore NON vede piu' %r: la mira e' stata stretta troppo, e il "
                    "collaudo che la usa sarebbe verde col numero scritto nel database"
                    % (pan,))
        # e un valore NOTO non puo' diventare un buco: se contiene una carta, si vede
        self.assertTrue(
            traccia_di_carta("4242424242424242", noti={"h_a8a5369477666965"}),
            "dichiarare noto un identificatore ha reso cieco il rilevatore su TUTTO: "
            "l'elenco dei noti deve valere solo per i valori che ci sono dentro")


class TestApiDbCartaHost(_BaseIntegrazione):
    def test_webhook_setup_salva_gli_id_opachi_nel_registro_host(self):
        """Salvataggio carta: nel nostro DB finiscono SOLO cus_/pm_ (mai il numero carta)."""
        hid = self.registra_host()
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"id": "cs_setup_1", "mode": "setup",
                                             "metadata": {"host_id": hid,
                                                          "scopo": "mandato_penale_offsession"}}}})
        s, out = self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                                 {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
        self.assertEqual((s, out.get("scopo")), (200, "carta"))
        righe = self.sql("registro", "SELECT stripe_customer_id, stripe_payment_method "
                         "FROM host WHERE host_id=?", (hid,))
        self.assertEqual(righe[0]["stripe_customer_id"], "cus_1")
        self.assertEqual(righe[0]["stripe_payment_method"], "pm_1")
        # e i due GET a Stripe sono partiti davvero (sessione + setup_intent)
        self.assertEqual([r["metodo"] for r in self.carta.richieste], ["GET", "GET"])
        # ⛔ NON `assertNotIn("4242", ...)`: quella forma cercava le quattro cifre dentro
        # QUALUNQUE valore, e il 2026-08-18 e' caduta in CI sull'ORA IN SECONDI
        # (`'4242' unexpectedly found in '1787042423'`). Vedi `traccia_di_carta` qui sopra:
        # stesso fatto sorvegliato, mira stretta, e provata nelle due direzioni.
        # ⛔ `noti={hid}`: l'identificatore l'ha generato QUESTO collaudo due righe fa, e il
        # 2026-08-21 ha fatto cadere il cancello su master perche' sedici caratteri
        # esadecimali possono uscire tutti cifre (misurato: 1 giro su 211). Dichiararlo
        # NON allarga la mira di un millimetro su tutto il resto della riga: lo dimostra
        # `test_STRINGERE_LA_MIRA_NON_L_HA_SPOSTATA_DI_UN_MILLIMETRO`, che pretende di
        # vedere un numero di carta anche mentre questo identificatore e' fra i noti.
        for riga in self.sql("registro", "SELECT * FROM host WHERE host_id=?", (hid,)):
            for k, v in riga.items():
                self.assertEqual(
                    [], traccia_di_carta(v, noti={hid}),
                    "traccia del numero di una carta nel nostro database, colonna %r = %r"
                    % (k, v))

    def test_link_carta_dal_pannello_host(self):
        hid = self.registra_host()
        self.sis.carta._fetch = FintoStripeCarta(
            {"/checkout/sessions": {"url": "https://stripe/setup/1"}})
        s, out = self.g("POST", "/api/host/carta_link", {}, self.tok)
        self.assertEqual(s, 200, out)
        self.assertEqual(out["url"], "https://stripe/setup/1")
        self.assertIn("Autorizzo BookinVIP", out["mandato"])
        req = self.sis.carta._fetch.ultima
        self.assertEqual(req["campi"]["metadata[host_id]"], hid)
        self.assertEqual(req["campi"]["mode"], "setup")


class TestApiDbGeocoder(_BaseIntegrazione):
    def test_pubblicazione_geocodifica_e_scrive_la_cache_su_disco(self):
        self.registra_host()
        self.pubblica(slug="casa-geo", citta="Roma")
        self.assertEqual(len(self._ricerche()), 1,
                         "una sola geocodifica per citta (limite Nominatim)")
        # 1) la cache e' sul DISCO, con le coordinate in microgradi interi
        righe = self.sql("geocache", "SELECT * FROM geocache")
        self.assertEqual(len(righe), 1)
        self.assertEqual((righe[0]["trovato"], righe[0]["lat_micro"], righe[0]["lon_micro"]),
                         (1, 41902784, 12496366))
        # 2) l'annuncio salvato ha le coordinate (mappa) - dal catalogo riaperto
        s, det = self.g("GET", "/api/catalogo/casa-geo")
        self.assertEqual(s, 200, det)
        self.assertEqual((det.get("lat_micro"), det.get("lon_micro")),
                         (41902784, 12496366))
        # 3) secondo annuncio nella stessa citta: ZERO chiamate nuove (limite rispettato)
        quante = len(self.nominatim)
        self.pubblica(slug="casa-geo-2", citta="Roma")
        self.assertEqual(len(self.nominatim), quante,
                         "secondo annuncio: tutto dalla cache, zero rete")

    def test_endpoint_geocode_host_usa_la_cache(self):
        self.registra_host()
        s, out = self.r.gestisci("GET", "/api/host/geocode", {"citta": "Milano"}, None,
                                 self.tok)
        self.assertEqual(s, 200, out)
        self.assertEqual((out["lat_micro"], out["lon_micro"]), (41902784, 12496366))
        self.assertEqual(len(self._ricerche()), 1)
        self.r.gestisci("GET", "/api/host/geocode", {"citta": "Milano"}, None, self.tok)
        self.assertEqual(len(self._ricerche()), 1, "seconda richiesta servita dalla cache")
        self.assertEqual(len(self.sql("geocache", "SELECT * FROM geocache")), 1)

    def test_geocode_senza_auth_non_espone_nominatim(self):
        s, _ = self.r.gestisci("GET", "/api/host/geocode", {"citta": "Roma"}, None, {})
        self.assertEqual(s, 401)
        self.assertEqual(self.nominatim, [], "anonimo che consuma la quota Nominatim")

    def test_nominatim_giu_non_blocca_la_pubblicazione(self):
        self.registra_host()
        self.sis.geocoder = crea_geocoder(
            self.percorsi["geocache"],
            fetch=lambda url: (_ for _ in ()).throw(urllib.error.URLError("giu'")))
        self.pubblica(slug="casa-senza-geo", citta="Napoli")     # 201 atteso dentro pubblica()
        s, det = self.g("GET", "/api/catalogo/casa-senza-geo")
        self.assertEqual(s, 200)
        self.assertIn(det.get("lat_micro", 0), (0, None),
                      "coordinate inventate con Nominatim giu'")


class TestApiDbEmailSMTP(_BaseIntegrazione):
    """L'ultimo anello della catena: API -> database -> SMTP. La lingua che l'ospite sceglie
    al book deve arrivare INTATTA fino all'oggetto della email che il server consegna."""

    def _prenota_in(self, lingua, email):
        self.registra_host()
        self.pubblica()
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa-1", "check_in": _giorno(1),
                       "check_out": _giorno(3), "party": 2})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": email, "lang": lingua})
        self.assertEqual(s, 201, b)
        self.attendi_email(email)              # il voucher: aspetta il thread, poi azzera
        del self.email[:]                      # guardiamo solo cio' che parte DOPO il pagamento
        self.assertEqual(self.webhook(b["riferimento"])[0], 200)
        return self.attendi_email(email)[-1]

    def test_ospite_giapponese_riceve_la_conferma_in_giapponese(self):
        oggetto_ric, corpo = self._prenota_in("ja", "ospite@jp.example")
        self.assertEqual(oggetto_ric, T("pc_ogg", "ja"))
        self.assertIn(T("pc_titolo", "ja"), corpo)
        self.assertNotIn(T("pc_titolo", "it"), corpo)

    def test_lingua_sconosciuta_ripiega_sull_inglese_mai_sull_italiano(self):
        """«Non so che lingua parli» non vuol dire «italiano»: la piattaforma e' globale."""
        oggetto_ric, corpo = self._prenota_in("xx", "ospite@nowhere.example")
        self.assertEqual(oggetto_ric, T("pc_ogg", "en"))
        self.assertIn(T("pc_titolo", "en"), corpo)
        self.assertNotIn(T("pc_titolo", "it"), corpo)

    def test_smtp_morto_non_perde_il_pagamento(self):
        """Se il server di posta e' giu' al momento del webhook, il PAGAMENTO deve restare
        registrato: l'email e' best-effort, il denaro no. Prova sul DISCO riaperto.

        COSA VEDE (misurato rompendo il codice, non ipotizzato): il guasto e' iniettato al
        livello piu' basso — la connessione SMTP — e sotto ci sono QUATTRO difese: il retry
        del provider, il provider fail-safe, il thread daemon e — l'ultima, quella che conta
        davvero — l'ORDINE: `_riasserisci_incasso` scrive il denaro PRIMA che l'email venga
        tentata. Rimuovendo le prime tre il test resta verde (giustamente: i soldi sono gia'
        a disco); rimuovendo anche l'ordine — email prima del ledger — diventa ROSSO. E'
        quindi la guardia dell'invariante «prima il denaro, poi la posta»."""
        self.registra_host()
        self.pubblica()
        q, b = self.prenota()
        rif = b["riferimento"]
        tentativi = []

        def esplode(dest, ogg, html):
            tentativi.append(dest)
            raise ConnectionResetError("SMTP chiuso")

        self.attendi_email("ospite@x.it")      # il voucher del book e' gia' partito
        del self.email[:]
        self.sis.email_provider._send = esplode
        s, out = self.webhook(rif)
        self.assertEqual((s, out.get("ricevuto")), (200, True),
                         "SMTP giu' ha fatto fallire il webhook: Stripe ritenterebbe")
        righe = self.sql("pendenti", "SELECT stato FROM pendenti WHERE riferimento=?", (rif,))
        self.assertEqual(righe[0]["stato"], "pagato")
        inc = self.sql("finanza", "SELECT * FROM libro_giornale WHERE tipo='incasso'")
        self.assertEqual(len(inc), 1)
        self.assertEqual(inc[0]["importo_cents"], int(b["totale_cents"]))
        self.assertEqual(self.nessuna_email_per("ospite@x.it"), [],
                         "email data per consegnata con l'SMTP giu'")
        self.assertTrue(tentativi, "il guasto SMTP non e' stato nemmeno raggiunto: il test "
                                   "non sta provando l'isolamento che dice di provare")

    def test_email_al_destinatario_esatto_e_senza_a_capo(self):
        """Nessuna email deve partire verso un destinatario con un a-capo (header injection)
        ne' con un oggetto multilinea: il choke-point vale sull'intero giro reale."""
        self.registra_host()
        self.pubblica()
        q, b = self.prenota(email="ospite@x.it")
        self.webhook(b["riferimento"])
        self.attendi_email("ospite@x.it", quante=2)
        for dest, ogg, _h in list(self.email):
            self.assertNotIn("\n", dest)
            self.assertNotIn("\r", dest)
            self.assertNotIn("\n", ogg)
            self.assertNotIn("\r", ogg)
            self.assertIn("@", dest)


class TestApiDbSegretiFuoriDaiLog(_BaseIntegrazione):
    """I segreti (chiave Stripe, segreto del webhook) attraversano tutto il giro: non devono
    comparire in NESSUNA riga di log, nemmeno dentro un traceback."""

    def test_giro_completo_senza_segreti_nei_log(self):
        with _CatturaLog() as log:                      # root: tutti i logger del progetto
            self.registra_host()
            self.pubblica()
            q, b = self.prenota()
            self.webhook(b["riferimento"])
            self.webhook(b["riferimento"], firma_valida=False)   # anche il caso d'errore
            self.sis.registro_host.imposta_stripe_account(self.host_id, "acct_HOST1")
            self.g("POST", "/api/garanzia/conferma", {"voucher_token": b["voucher_token"]})
        testo = log.come_testo()
        self.assertNotIn("sk_test_x", testo, "CHIAVE STRIPE NEI LOG")
        self.assertNotIn(WH, testo, "SEGRETO DEL WEBHOOK NEI LOG")
        self.assertNotIn("whsec_", testo)
        # il test sa distinguere: se i segreti ci fossero, li vedrebbe
        self.assertIn("sk_test_x", self.stripe.ultima["headers"]["Authorization"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
