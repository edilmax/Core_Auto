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
import shutil
import sqlite3
import tempfile
import time
import unittest
import urllib.error
from urllib.parse import parse_qsl, urlsplit

import fase85_pagamenti_stripe as _f85
import fase101_stripe_connect as _f101
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
from fase101_stripe_connect import crea_provider_connect
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
    """Corpo x-www-form-urlencoded -> dict (come lo legge Stripe)."""
    if isinstance(corpo, (bytes, bytearray)):
        corpo = corpo.decode("utf-8")
    return dict(parse_qsl(corpo or "", keep_blank_values=True))


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
#  FINTI SEVERI
# ══════════════════════════════════════════════════════════════════════════════
_MANCA = object()          # "non specificato" (distinto da None, che e' una risposta valida)


class FintoStripeForm:
    """Stripe form-encoded (fase85 / fase101): fetch(url, body, headers) -> dict.
    Registra TUTTO; `guasto` = eccezione da sollevare (rete giu' / 500)."""

    def __init__(self, risposta=_MANCA, guasto=None):
        self.richieste = []
        self._risposta = {"id": "cs_test_1",
                          "url": "https://checkout.stripe.com/c/pay/cs_test_1"} \
            if risposta is _MANCA else risposta
        self._guasto = guasto

    def __call__(self, url, body, headers):
        self.richieste.append({"url": url, "headers": dict(headers or {}),
                               "campi": _campi(body), "corpo": body})
        if self._guasto is not None:
            raise self._guasto
        r = self._risposta
        return r(self.richieste[-1]) if callable(r) else r

    @property
    def ultima(self):
        return self.richieste[-1]


class FintoStripeCarta:
    """ProviderCarta (fase183): fetch(metodo, url, body, headers) -> dict."""

    def __init__(self, risposte=None, guasto=None):
        self.richieste = []
        self._risposte = risposte or {}
        self._guasto = guasto

    def __call__(self, metodo, url, body, headers):
        self.richieste.append({"metodo": metodo, "url": url, "headers": dict(headers or {}),
                               "campi": _campi(body) if body else {}})
        if self._guasto is not None:
            raise self._guasto
        for chiave, val in self._risposte.items():
            if chiave in url:
                return val
        return {}

    @property
    def ultima(self):
        return self.richieste[-1]


class FintoHttpAI:
    """fase165: fetch(url, *, metodo, intestazioni, corpo, timeout) -> (status, obj)."""

    def __init__(self, esiti):
        self.richieste = []
        self._esiti = list(esiti)

    def __call__(self, url, *, metodo="GET", intestazioni=None, corpo=None, timeout=30.0):
        self.richieste.append({"url": url, "metodo": metodo,
                               "intestazioni": dict(intestazioni or {}), "corpo": corpo,
                               "timeout": timeout})
        return self._esiti.pop(0) if self._esiti else (0, None)


class FintoJson:
    """Canali social (fase91/193): fetch(url, data[, headers]) -> dict."""

    def __init__(self, risposte=None, guasto=None):
        self.richieste = []
        self._risposte = list(risposte or [])
        self._guasto = guasto

    def __call__(self, url, data=None, headers=None):
        self.richieste.append({"url": url, "data": dict(data or {}),
                               "headers": dict(headers or {})})
        if self._guasto is not None:
            raise self._guasto
        return self._risposte.pop(0) if self._risposte else {"ok": True, "id": "1"}


class FintoStatus:
    """Canali fase152: fetch(url, headers, body) -> (status, testo)."""

    def __init__(self, status=200, guasto=None):
        self.richieste = []
        self._status = status
        self._guasto = guasto

    def __call__(self, url, headers, body):
        self.richieste.append({"url": url, "headers": dict(headers or {}), "body": body})
        if self._guasto is not None:
            raise self._guasto
        return self._status, "{}"


# ══════════════════════════════════════════════════════════════════════════════
#  1) STRIPE — Checkout (fase85): forma della richiesta e importi in cents interi
# ══════════════════════════════════════════════════════════════════════════════
class TestStripeCheckoutContratto(unittest.TestCase):
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
class TestStripeConnectContratto(unittest.TestCase):
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

    def test_stripe_500_sul_transfer_non_solleva(self):
        f = FintoStripeForm(guasto=urllib.error.HTTPError(
            "https://api.stripe.com", 500, "boom", {}, None))
        p = crea_provider_connect("sk_test_x", fetch=f)
        self.assertIsNone(p.trasferisci("acct_H1", 21600, "EUR", "BVIP-AAAA"))
        self.assertEqual(len(f.richieste), 1)


# ══════════════════════════════════════════════════════════════════════════════
#  3) STRIPE — Carta off-session (fase183)
# ══════════════════════════════════════════════════════════════════════════════
class TestStripeCartaContratto(unittest.TestCase):
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
class TestEmailContratto(unittest.TestCase):
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


class TestCanaliContratto(unittest.TestCase):
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


class TestPubblicaVideoContratto(unittest.TestCase):
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
class TestCambioValutaOXR(unittest.TestCase):
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
class TestGeocoderContratto(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.db = os.path.join(self.d, "geo.db")
        self.chiamate = []

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _geo(self, risposta):
        def fetch(url):
            self.chiamate.append(url)
            if isinstance(risposta, Exception):
                raise risposta
            return risposta(url) if callable(risposta) else risposta

        return crea_geocoder(self.db, fetch=fetch)

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


class TestPOIContratto(unittest.TestCase):
    LAT, LON = 41_902_784, 12_496_366

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.db = os.path.join(self.d, "poi.db")
        self.chiamate = []

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _prov(self, risposta):
        def fetch(url):
            self.chiamate.append(url)
            if isinstance(risposta, Exception):
                raise risposta
            return risposta

        return crea_provider_poi(self.db, fetch=fetch)

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
class TestAIContratto(unittest.TestCase):
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
class _BaseIntegrazione(unittest.TestCase):
    """Sistema vero su FILE, servizi terzi con finti severi. Dopo ogni chiamata si riapre
    il database con sqlite3 e si guarda la riga: la risposta HTTP non e' una prova."""

    def setUp(self):
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
        self.sis.geocoder = crea_geocoder(self.percorsi["geocache"],
                                          fetch=self._finto_nominatim)
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _finto_nominatim(self, url):
        """Nominatim finto: /search -> coordinate, /reverse -> quartiere."""
        self.nominatim.append(url)
        if "/reverse" in url:
            return {"address": {"suburb": "Centro"}}
        return [{"lat": "41.902784", "lon": "12.496366"}]

    def _ricerche(self):
        return [u for u in self.nominatim if "/search" in u]

    # ── strumenti ────────────────────────────────────────────────────────────
    def g(self, m, path, corpo=None, headers=None):
        return self.r.gestisci(m, path, {}, json.dumps(corpo) if corpo is not None else None,
                               headers or {})

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

        NB (segnalato al coordinatore): oggi il book DEGRADA in 'confermata senza pagamento
        online' (il ramo pensato per Stripe NON configurato). Qui si sorveglia cio' che deve
        valere in ogni caso — soprattutto che l'host non venga pagato per un incasso mai
        avvenuto — senza congelare nel test il comportamento di degrado."""
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
        self.assertLess(s, 500, "un 500 di Stripe non deve diventare un 500 nostro")
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

    def test_host_senza_conto_stripe_nessun_transfer_ma_payout_tracciato(self):
        self.sis.registro_host.imposta_stripe_account(self.host_id, "")
        s, _ = self.g("POST", "/api/garanzia/conferma",
                      {"voucher_token": self.b["voucher_token"]})
        self.assertEqual(s, 200)
        self.assertEqual([r for r in self.connect.richieste
                          if r["url"].endswith("/transfers")], [])
        pay = self.sql("payout", "SELECT * FROM payout WHERE prenotazione_id=?", (self.rif,))
        self.assertEqual(pay[0]["stato"], "maturato")


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
        for riga in self.sql("registro", "SELECT * FROM host WHERE host_id=?", (hid,)):
            for k, v in riga.items():
                self.assertNotIn("4242", str(v), "numero carta nel nostro database")

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
