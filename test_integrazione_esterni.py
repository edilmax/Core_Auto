# -*- coding: utf-8 -*-
"""
INTEGRAZIONE SERVIZI TERZI — SECONDA META' (mandato punto 1).

`test_integrazione_servizi.py` copre il money-path e i servizi cablati nel giro
prenotazione (Stripe, SMTP, Telegram/Meta, OXR, Nominatim, Overpass, AI). Restavano
SCOPERTI i canali di crescita e di indicizzazione, cioe' proprio quelli che oggi sono
DORMIENTI e che verranno accesi mettendo un token nel `.env`: il giorno in cui il
fondatore incolla quel token, la prima richiesta che parte deve essere GIA' quella
giusta — non c'e' un ambiente di prova dove sbagliarla.

  BLUESKY   fase194  (AT Protocol: createSession -> createRecord, 300 caratteri)
  REDDIT    fase195  (Basic auth -> access_token -> /api/submit, User-Agent obbligatorio)
  NOSTR     fase197  (evento kind=1 FIRMATO Schnorr BIP340, frame ["EVENT", ev] sui relay)
  INDEXNOW  fase169  (lotti, stesso host, dedup, User-Agent) + la CHIAVE servita dal server
  CABLAGGIO fase91   (i canali nuovi esistono ma sono davvero collegati al giro?)
  DISPATCH  fase90   (un canale che esplode non deve fermare la campagna)

STESSA REGOLA DELL'ALTRO FILE: le controfigure sono SEVERE. Il finto relay Nostr, per
dire, fa quello che fa un relay vero: ricalcola l'id come sha256 della serializzazione
canonica e VERIFICA LA FIRMA Schnorr — se il nostro evento fosse firmato male, il test
diventa rosso qui invece che in silenzio in produzione (una nota non firmata bene i relay
la buttano senza dire niente).

Il vaglio dei contratti e il registro delle violazioni sono condivisi con
`test_integrazione_servizi` (una sola severita', non due che divergono).
"""
import base64
import hashlib
import http.client
import json
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
from urllib.parse import urlsplit

import fase83_server
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase90_marketing import GeneratoreContenuti, MotoreMarketing, Post
from fase91_canali_social import crea_canali_da_env
from fase169_indexnow import (IndexNow, MAX_URL_BATCH, key_file_body, payload_indexnow,
                              urls_valide)
from fase194_canale_bluesky import CanaleBluesky, crea_canale_bluesky_da_env
from fase195_canale_reddit import CanaleReddit, crea_canale_reddit_da_env
from fase197_canale_nostr import (CanaleNostr, crea_canale_nostr_da_env, pubkey_xonly,
                                  schnorr_verify, serializza_evento)
from test_integrazione_servizi import (_CatturaLog, _ContrattiPuliti, _FintoSevero,
                                       azzera_finti)

# chiave privata di prova (32 byte, deterministica): NON e' un segreto, serve solo qui
SK_HEX = "1" * 63 + "2"
RELAYS = ("wss://relay.damus.io", "wss://nos.lol", "wss://relay.snort.social")


def _post(testo="Nuova casa a Roma", link="https://bookinvip.com/alloggio/casa-1"):
    return Post(tema="host", lingua="it", testo=testo, hashtag=("#BookinVIP",), link=link)


def _id_nostr_atteso(ev):
    """ORACOLO INDIPENDENTE dell'id di un evento Nostr, riscritto qui dalla specifica
    NIP-01 invece di richiamare `serializza_evento` del prodotto: se il prodotto cambiasse
    la sua serializzazione (spazi, ordine, escaping unicode) il suo id resterebbe coerente
    con se stesso e nessuno se ne accorgerebbe — mentre i relay veri lo scarterebbero.
    L'id e' sha256 del JSON COMPATTO di [0, pubkey, created_at, kind, tags, content]."""
    canonico = json.dumps([0, ev["pubkey"], int(ev["created_at"]), int(ev["kind"]),
                           [list(t) for t in ev["tags"]], ev["content"]],
                          separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def _porta_libera():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ══════════════════════════════════════════════════════════════════════════════
#  FINTI SEVERI dei servizi ancora scoperti
# ══════════════════════════════════════════════════════════════════════════════
class FintoBluesky(_FintoSevero):
    """PDS Bluesky severo: due endpoint XRPC, il secondo ESIGE il Bearer di sessione e un
    record `app.bsky.feed.post` completo (senza $type/createdAt il PDS risponde 400)."""

    servizio = "bsky.social"

    def __init__(self, risposte=None, guasto=None):
        super().__init__()
        self._risposte = list(risposte or [])
        self._guasto = guasto

    def __call__(self, url, data=None, headers=None):
        d = dict(data or {})
        h = dict(headers or {})
        self.richieste.append({"url": url, "data": d, "headers": h})
        e = self._esigi
        e(isinstance(url, str) and url.startswith("https://") and "/xrpc/" in url,
          "URL non e' un endpoint XRPC https: %r" % (url,))
        metodo_xrpc = url.rsplit("/xrpc/", 1)[-1]
        if metodo_xrpc == "com.atproto.server.createSession":
            e(d.get("identifier", "") != "", "createSession senza identifier (handle)")
            e(d.get("password", "") != "", "createSession senza password")
            e("Authorization" not in h,
              "createSession con un Authorization: non esiste ancora un token")
        elif metodo_xrpc == "com.atproto.repo.createRecord":
            auth = str(h.get("Authorization", ""))
            e(auth.startswith("Bearer ") and auth[7:].strip() != "",
              "createRecord senza il Bearer della sessione")
            e(str(d.get("repo", "")).startswith("did:"),
              "repo non e' un DID: %r" % (d.get("repo"),))
            e(d.get("collection") == "app.bsky.feed.post",
              "collection sbagliata: %r" % (d.get("collection"),))
            rec = d.get("record")
            e(isinstance(rec, dict), "record assente")
            e(rec.get("$type") == "app.bsky.feed.post",
              "record senza $type app.bsky.feed.post")
            testo = rec.get("text")
            e(isinstance(testo, str) and testo.strip() != "", "nota vuota")
            e(len(testo) <= 300, "nota di %d caratteri: Bluesky ne accetta 300" % len(testo))
            creato = str(rec.get("createdAt", ""))
            e(len(creato) >= 20 and creato.endswith("Z") and creato[4] == "-"
              and creato[10] == "T",
              "createdAt non e' ISO-8601 UTC: %r" % (creato,))
        else:
            e(False, "endpoint XRPC sconosciuto: %r" % (metodo_xrpc,))
        if self._guasto is not None:
            raise self._guasto
        return self._risposte.pop(0) if self._risposte else {}


class FintoReddit(_FintoSevero):
    """Reddit severo: SENZA User-Agent descrittivo Reddit risponde 429 a tutti (e' scritto
    nelle sue API rules); il token vuole Basic auth, il submit vuole Bearer."""

    servizio = "reddit"

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
        ua = str(h.get("User-Agent", ""))
        e(ua.strip() != "", "richiesta Reddit senza User-Agent: 429 garantito")
        e(len(ua) >= 10 and "bookinvip" in ua.lower(),
          "User-Agent non identificativo: %r" % (ua,))
        if url.endswith("/api/v1/access_token"):
            auth = str(h.get("Authorization", ""))
            e(auth.startswith("Basic "), "token endpoint senza Basic auth")
            try:
                coppia = base64.b64decode(auth[6:]).decode("utf-8")
                ok = ":" in coppia and all(coppia.split(":", 1))
            except Exception:
                ok = False
            e(ok, "Basic auth non e' base64(client_id:client_secret)")
            e(d.get("grant_type") == "password",
              "grant_type sbagliato: %r" % (d.get("grant_type"),))
            e(d.get("username", "") != "" and d.get("password", "") != "",
              "credenziali script-app incomplete")
        elif url.endswith("/api/submit"):
            e(str(h.get("Authorization", "")).startswith("Bearer "),
              "submit senza Bearer token")
            e(d.get("kind") in ("link", "self"), "kind sbagliato: %r" % (d.get("kind"),))
            e(str(d.get("sr", "")).strip() != "", "submit senza subreddit")
            e(str(d.get("sr", "")).lstrip("/").startswith("r/") is False,
              "il subreddit va senza prefisso 'r/': %r" % (d.get("sr"),))
            titolo = str(d.get("title", ""))
            e(titolo.strip() != "", "titolo vuoto")
            e(len(titolo) <= 300, "titolo di %d caratteri (max 300)" % len(titolo))
            e("\n" not in titolo, "titolo su piu' righe")
            e(str(d.get("url", "")).startswith("https://"),
              "kind=link senza URL https: %r" % (d.get("url"),))
        else:
            e(False, "endpoint Reddit sconosciuto: %r" % (url,))
        if self._guasto is not None:
            raise self._guasto
        return self._risposte.pop(0) if self._risposte else {}


class FintoRelayNostr(_FintoSevero):
    """Relay Nostr severo: fa ESATTAMENTE quello che fa un relay vero prima di accettare
    una nota — ricalcola l'id come sha256 della serializzazione canonica e VERIFICA la
    firma Schnorr BIP340. Un evento firmato male, un id sbagliato o un campo mancante
    verrebbero buttati dal relay IN SILENZIO: qui invece diventano rossi."""

    servizio = "relay-nostr"

    def __init__(self, accetta=True, guasto=None):
        super().__init__()
        self._accetta = accetta
        self._guasto = guasto
        self.eventi = []

    def __call__(self, relay_url, messaggio):
        self.richieste.append({"relay": relay_url, "messaggio": messaggio})
        e = self._esigi
        u = urlsplit(str(relay_url))
        e(u.scheme in ("ws", "wss") and bool(u.hostname),
          "relay non e' un URL WebSocket: %r" % (relay_url,))
        try:
            msg = json.loads(messaggio)
            leggibile = True
        except Exception:
            leggibile = False
        e(leggibile, "messaggio non JSON")
        e(isinstance(msg, list) and len(msg) == 2 and msg[0] == "EVENT",
          "non e' un frame [\"EVENT\", evento]")
        ev = msg[1]
        e(isinstance(ev, dict), "evento non e' un oggetto")
        for campo in ("id", "pubkey", "created_at", "kind", "tags", "content", "sig"):
            e(campo in ev, "evento senza campo %r" % (campo,))
        e(ev["kind"] == 1, "kind %r: una nota di testo e' kind=1" % (ev["kind"],))
        e(isinstance(ev["created_at"], int) and ev["created_at"] > 0,
          "created_at non e' un intero unix: %r" % (ev["created_at"],))
        e(str(ev["content"]).strip() != "", "nota vuota")
        e(_id_nostr_atteso(ev) == ev["id"],
          "id != sha256 della serializzazione canonica: il relay lo scarta")
        try:
            firma_ok = schnorr_verify(bytes.fromhex(ev["id"]), bytes.fromhex(ev["pubkey"]),
                                      bytes.fromhex(ev["sig"]))
        except Exception:
            firma_ok = False
        e(firma_ok, "FIRMA SCHNORR NON VALIDA: la nota verrebbe buttata senza un errore")
        self.eventi.append(ev)
        if self._guasto is not None:
            raise self._guasto
        return self._accetta


class FintoIndexNow(_FintoSevero):
    """api.indexnow.org severo: JSON, User-Agent (senza, risponde 403 — provato in prod),
    un solo host per lotto, massimo 10.000 URL, nessun duplicato."""

    servizio = "api.indexnow.org"

    def __init__(self, stato=200, guasto=None):
        super().__init__()
        self._stato = stato
        self._guasto = guasto

    def __call__(self, url, body, headers):
        h = dict(headers or {})
        self.richieste.append({"url": url, "body": body, "headers": h})
        e = self._esigi
        e(url == "https://api.indexnow.org/indexnow", "endpoint sbagliato: %r" % (url,))
        e(str(h.get("Content-Type", "")).startswith("application/json"),
          "Content-Type non JSON: %r" % (h.get("Content-Type"),))
        e(str(h.get("User-Agent", "")).strip() != "",
          "senza User-Agent api.indexnow.org risponde 403")
        e(isinstance(body, (bytes, bytearray)), "corpo non bytes")
        try:
            corpo = json.loads(bytes(body).decode("utf-8"))
            leggibile = True
        except Exception:
            corpo, leggibile = None, False
        e(leggibile and isinstance(corpo, dict), "corpo non e' un oggetto JSON")
        for campo in ("host", "key", "urlList"):
            e(campo in corpo, "corpo senza %r" % (campo,))
        e(str(corpo["key"]).strip() != "", "chiave vuota")
        lista = corpo["urlList"]
        e(isinstance(lista, list) and lista, "urlList vuota: invio inutile")
        e(len(lista) <= MAX_URL_BATCH,
          "lotto di %d URL: il massimo IndexNow e' %d" % (len(lista), MAX_URL_BATCH))
        e(len(set(lista)) == len(lista), "urlList con duplicati")
        for u in lista:
            e(isinstance(u, str) and u.startswith(("http://", "https://")),
              "URL non assoluto: %r" % (u,))
            e(urlsplit(u).netloc.lower() == str(corpo["host"]).lower(),
              "URL di un altro host (%r) nel lotto di %r" % (u, corpo["host"]))
        if "keyLocation" in corpo:
            e(str(corpo["keyLocation"]).startswith("https://"),
              "keyLocation non https: %r" % (corpo["keyLocation"],))
        if self._guasto is not None:
            raise self._guasto
        return self._stato


# ══════════════════════════════════════════════════════════════════════════════
#  1) BLUESKY (fase194)
# ══════════════════════════════════════════════════════════════════════════════
class TestBlueskyContratto(_ContrattiPuliti):
    PW = "abcd-efgh-ijkl-mnop"          # app password (segreto)

    def _canale(self, finto):
        return CanaleBluesky("bookinvip.bsky.social", self.PW, fetch=finto,
                             orologio=lambda: "2026-07-29T10:00:00.000Z")

    def test_due_passi_in_ordine_con_il_token_di_sessione(self):
        f = FintoBluesky([{"accessJwt": "jwt-sessione", "did": "did:plc:abc123"},
                          {"uri": "at://did:plc:abc123/app.bsky.feed.post/1", "cid": "bafy"}])
        self.assertTrue(self._canale(f).pubblica(_post()))
        self.assertEqual(len(f.richieste), 2)
        sess, rec = f.richieste
        self.assertEqual(sess["url"],
                         "https://bsky.social/xrpc/com.atproto.server.createSession")
        self.assertEqual(sess["data"], {"identifier": "bookinvip.bsky.social",
                                        "password": self.PW})
        self.assertEqual(rec["url"],
                         "https://bsky.social/xrpc/com.atproto.repo.createRecord")
        self.assertEqual(rec["headers"]["Authorization"], "Bearer jwt-sessione")
        self.assertEqual(rec["data"]["repo"], "did:plc:abc123")
        self.assertEqual(rec["data"]["collection"], "app.bsky.feed.post")
        self.assertEqual(rec["data"]["record"]["createdAt"], "2026-07-29T10:00:00.000Z")
        testo = rec["data"]["record"]["text"]
        self.assertIn("Nuova casa a Roma", testo)
        self.assertIn("#BookinVIP", testo)
        self.assertIn("https://bookinvip.com/alloggio/casa-1", testo)

    def test_sessione_fallita_nessun_secondo_passo(self):
        """Senza jwt+did non si puo' scrivere: tentarlo comunque brucia quota e finisce 401."""
        for sessione in ({"error": "AuthenticationRequired"}, {"accessJwt": "j"},
                         {"did": "did:plc:x"}, {}, None):
            f = FintoBluesky([sessione])
            self.assertFalse(self._canale(f).pubblica(_post()), repr(sessione))
            self.assertEqual(len(f.richieste), 1, "secondo passo senza sessione: %r"
                             % (sessione,))
            azzera_finti()

    def test_nota_lunga_tagliata_a_300_caratteri(self):
        f = FintoBluesky([{"accessJwt": "j", "did": "did:plc:x"}, {"uri": "at://x"}])
        self.assertTrue(self._canale(f).pubblica(_post("A" * 900)))
        self.assertEqual(len(f.richieste[1]["data"]["record"]["text"]), 300)

    def test_risposta_senza_uri_ne_cid_non_e_pubblicata(self):
        for risposta in ({}, {"error": "RateLimitExceeded"}, "non-dict", None):
            f = FintoBluesky([{"accessJwt": "j", "did": "did:plc:x"}, risposta])
            self.assertFalse(self._canale(f).pubblica(_post()), repr(risposta))
            azzera_finti()

    def test_rete_giu_nessuna_eccezione_e_password_mai_nei_log(self):
        f = FintoBluesky(guasto=urllib.error.HTTPError(
            "https://bsky.social/xrpc/com.atproto.server.createSession", 401,
            "Unauthorized", {}, None))
        with _CatturaLog("core_auto.canale_bluesky") as log:
            self.assertFalse(self._canale(f).pubblica(_post()))
        self.assertNotIn(self.PW, log.come_testo(), "APP PASSWORD BLUESKY NEI LOG")
        azzera_finti()

    def test_app_password_non_viaggia_nel_record_pubblico(self):
        """La password apre la sessione e basta: dentro il post (che finisce pubblico) non
        deve comparire neanche di striscio."""
        f = FintoBluesky([{"accessJwt": "j", "did": "did:plc:x"}, {"uri": "at://x"}])
        self._canale(f).pubblica(_post())
        self.assertNotIn(self.PW, json.dumps(f.richieste[1]))

    def test_gated_da_env(self):
        self.assertIsNone(crea_canale_bluesky_da_env({}))
        self.assertIsNone(crea_canale_bluesky_da_env({"BLUESKY_HANDLE": "x.bsky.social"}))
        self.assertIsNone(crea_canale_bluesky_da_env({"BLUESKY_APP_PASSWORD": "p"}))
        self.assertIsNotNone(crea_canale_bluesky_da_env(
            {"BLUESKY_HANDLE": "x.bsky.social", "BLUESKY_APP_PASSWORD": "p"}))

    def test_spento_senza_credenziali_nessuna_rete(self):
        f = FintoBluesky()
        self.assertFalse(CanaleBluesky("", "pw", fetch=f).pubblica(_post()))
        self.assertFalse(CanaleBluesky("h", "", fetch=f).pubblica(_post()))
        self.assertFalse(CanaleBluesky("h", "pw", fetch=f).pubblica("non-un-post"))
        self.assertEqual(f.richieste, [])


# ══════════════════════════════════════════════════════════════════════════════
#  2) REDDIT (fase195)
# ══════════════════════════════════════════════════════════════════════════════
class TestRedditContratto(_ContrattiPuliti):
    SEGRETO = "csec-superspeciale"
    PW = "password-di-reddit"

    def _canale(self, finto, sub="viaggi"):
        return CanaleReddit("cid1", self.SEGRETO, "bookinvip", self.PW, sub, fetch=finto)

    def test_token_poi_submit_con_le_intestazioni_giuste(self):
        f = FintoReddit([{"access_token": "tok-abc", "expires_in": 3600},
                         {"json": {"errors": [], "data": {"url": "https://reddit/x"}}}])
        self.assertTrue(self._canale(f).pubblica(_post()))
        self.assertEqual(len(f.richieste), 2)
        tok, sub = f.richieste
        self.assertEqual(tok["url"], "https://www.reddit.com/api/v1/access_token")
        self.assertEqual(base64.b64decode(tok["headers"]["Authorization"][6:]).decode(),
                         "cid1:" + self.SEGRETO)
        self.assertEqual(tok["data"]["grant_type"], "password")
        self.assertEqual(sub["url"], "https://oauth.reddit.com/api/submit")
        self.assertEqual(sub["headers"]["Authorization"], "Bearer tok-abc")
        self.assertEqual(sub["data"]["sr"], "viaggi")
        self.assertEqual(sub["data"]["kind"], "link")
        self.assertEqual(sub["data"]["url"], "https://bookinvip.com/alloggio/casa-1")
        self.assertEqual(sub["data"]["api_type"], "json")

    def test_prefisso_r_tolto_dal_subreddit(self):
        """'r/viaggi' come `sr` fa fallire il submit: il campo vuole il nome nudo."""
        f = FintoReddit([{"access_token": "t"}, {"json": {"errors": []}}])
        self.assertTrue(self._canale(f, sub="r/viaggi").pubblica(_post()))
        self.assertEqual(f.richieste[1]["data"]["sr"], "viaggi")

    def test_titolo_una_riga_e_al_massimo_300(self):
        f = FintoReddit([{"access_token": "t"}, {"json": {"errors": []}}])
        self.assertTrue(self._canale(f).pubblica(
            _post("Titolo lungo " * 40 + "\nseconda riga che non deve finire nel titolo")))
        titolo = f.richieste[1]["data"]["title"]
        self.assertLessEqual(len(titolo), 300)
        self.assertNotIn("\n", titolo)
        self.assertNotIn("seconda riga", titolo)

    def test_senza_token_nessun_submit(self):
        for risposta in ({"error": "invalid_grant"}, {"access_token": ""}, {}, None):
            f = FintoReddit([risposta])
            self.assertFalse(self._canale(f).pubblica(_post()), repr(risposta))
            self.assertEqual(len(f.richieste), 1, "submit tentato senza token")
            azzera_finti()

    def test_errori_nella_risposta_non_sono_una_pubblicazione(self):
        f = FintoReddit([{"access_token": "t"},
                         {"json": {"errors": [["SUBREDDIT_NOTALLOWED", "no", None]]}}])
        self.assertFalse(self._canale(f).pubblica(_post()))

    def test_post_senza_link_non_parte(self):
        """kind=link senza url = 400: meglio non partire (e non bruciare il rate-limit)."""
        f = FintoReddit()
        self.assertFalse(self._canale(f).pubblica(_post(link="")))
        self.assertEqual(f.richieste, [])

    def test_rete_giu_e_segreti_mai_nei_log(self):
        f = FintoReddit(guasto=urllib.error.HTTPError("https://www.reddit.com", 429,
                                                      "Too Many Requests", {}, None))
        with _CatturaLog("core_auto.canale_reddit") as log:
            self.assertFalse(self._canale(f).pubblica(_post()))
        testo = log.come_testo()
        self.assertNotIn(self.SEGRETO, testo, "CLIENT SECRET REDDIT NEI LOG")
        self.assertNotIn(self.PW, testo, "PASSWORD REDDIT NEI LOG")
        azzera_finti()

    def test_gated_da_env_servono_tutte_e_cinque(self):
        completo = {"REDDIT_CLIENT_ID": "a", "REDDIT_CLIENT_SECRET": "b",
                    "REDDIT_USERNAME": "c", "REDDIT_PASSWORD": "d",
                    "REDDIT_SUBREDDIT": "e"}
        self.assertIsNotNone(crea_canale_reddit_da_env(completo))
        for mancante in completo:
            parziale = {k: v for k, v in completo.items() if k != mancante}
            self.assertIsNone(crea_canale_reddit_da_env(parziale),
                              "canale acceso senza %s" % mancante)


# ══════════════════════════════════════════════════════════════════════════════
#  3) NOSTR (fase197) — il relay finto verifica la firma come quello vero
# ══════════════════════════════════════════════════════════════════════════════
class TestNostrContratto(_ContrattiPuliti):
    def _canale(self, sender, relays=RELAYS):
        return CanaleNostr(SK_HEX, relays, sender=sender, clock=lambda: 1785300000)

    def test_evento_firmato_accettato_da_tutti_i_relay(self):
        f = FintoRelayNostr()
        self.assertTrue(self._canale(f, RELAYS[:2]).pubblica(_post()))
        self.assertEqual([r["relay"] for r in f.richieste], list(RELAYS[:2]))
        ev = f.eventi[0]
        self.assertEqual(ev["kind"], 1)
        self.assertEqual(ev["created_at"], 1785300000)
        self.assertEqual(ev["pubkey"], pubkey_xonly(bytes.fromhex(SK_HEX)).hex())
        self.assertIn("Nuova casa a Roma", ev["content"])
        self.assertIn("https://bookinvip.com/alloggio/casa-1", ev["content"])
        # lo stesso evento va a TUTTI i relay: non se ne firma uno diverso per ciascuno
        self.assertEqual(len({r["messaggio"] for r in f.richieste}), 1)

    def test_id_e_firma_reggono_la_verifica_indipendente(self):
        """Oracolo indipendente: l'id viene ricalcolato qui dalla serializzazione canonica
        e la firma verificata con la funzione BIP340, senza fidarsi del produttore."""
        f = FintoRelayNostr()
        self._canale(f, RELAYS[:1]).pubblica(_post("Ciao da Roma"))
        ev = f.eventi[0]
        self.assertEqual(ev["id"], _id_nostr_atteso(ev))
        # e la serializzazione del prodotto deve coincidere con quella riscritta a mano
        self.assertEqual(serializza_evento(ev["pubkey"], ev["created_at"], 1, ev["tags"],
                                           ev["content"]),
                         json.dumps([0, ev["pubkey"], ev["created_at"], 1, ev["tags"],
                                     ev["content"]], separators=(",", ":"),
                                    ensure_ascii=False))
        self.assertTrue(schnorr_verify(bytes.fromhex(ev["id"]),
                                       bytes.fromhex(ev["pubkey"]),
                                       bytes.fromhex(ev["sig"])))
        # e la verifica SA dire di no: un id diverso non passa
        falso = bytes.fromhex(ev["id"])
        falso = bytes([falso[0] ^ 1]) + falso[1:]
        self.assertFalse(schnorr_verify(falso, bytes.fromhex(ev["pubkey"]),
                                        bytes.fromhex(ev["sig"])))

    def test_un_relay_solo_che_accetta_basta_a_pubblicare(self):
        """I relay sono tanti e cadono spesso: la pubblicazione riesce se ne accetta uno."""
        esiti = {RELAYS[0]: False, RELAYS[1]: False, RELAYS[2]: True}

        class _Misto(FintoRelayNostr):
            def __call__(_s, relay, messaggio):
                super().__call__(relay, messaggio)
                return esiti[relay]

        f = _Misto()
        self.assertTrue(self._canale(f).pubblica(_post()))
        self.assertEqual(len(f.richieste), 3, "un relay che rifiuta non ferma gli altri")

    def test_nessun_relay_accetta_nessuna_pubblicazione(self):
        f = FintoRelayNostr(accetta=False)
        self.assertFalse(self._canale(f).pubblica(_post()))
        self.assertEqual(len(f.richieste), 3)

    def test_relay_che_esplode_isolato_dagli_altri(self):
        esplosi = []

        class _UnoRotto(FintoRelayNostr):
            def __call__(_s, relay, messaggio):
                super().__call__(relay, messaggio)
                if relay == RELAYS[0]:
                    esplosi.append(relay)
                    raise urllib.error.URLError("relay morto")
                return True

        f = _UnoRotto()
        with _CatturaLog("core_auto.canale_nostr"):
            self.assertTrue(self._canale(f).pubblica(_post()))
        self.assertEqual(esplosi, [RELAYS[0]])
        self.assertEqual(len(f.richieste), 3)

    def test_chiave_privata_mai_nel_messaggio_ne_nei_log(self):
        """La chiave privata E' l'identita': se finisse in un frame o in un log, chiunque
        potrebbe pubblicare a nome nostro per sempre (non si puo' revocare)."""
        f = FintoRelayNostr()
        with _CatturaLog("core_auto.canale_nostr") as log:
            self._canale(f, RELAYS[:1]).pubblica(_post())
        self.assertNotIn(SK_HEX, f.richieste[0]["messaggio"], "CHIAVE PRIVATA NEL FRAME")
        self.assertNotIn(SK_HEX, log.come_testo(), "CHIAVE PRIVATA NEI LOG")
        self.assertNotEqual(f.eventi[0]["pubkey"], SK_HEX)

    def test_chiave_o_relay_non_validi_nessun_invio(self):
        f = FintoRelayNostr()
        for sk, relays in (("", RELAYS), ("nonesadecimale", RELAYS), ("ab" * 16, RELAYS),
                           (SK_HEX, ()), (SK_HEX, ("", "   "))):
            self.assertFalse(CanaleNostr(sk, relays, sender=f,
                                         clock=lambda: 1).pubblica(_post()),
                             "sk=%r relays=%r" % (sk[:8], relays))
        self.assertEqual(f.richieste, [], "invio con configurazione non valida")

    def test_gated_da_env(self):
        self.assertIsNone(crea_canale_nostr_da_env({}))
        self.assertIsNone(crea_canale_nostr_da_env({"NOSTR_PRIVATE_KEY": SK_HEX}))
        self.assertIsNone(crea_canale_nostr_da_env({"NOSTR_RELAYS": "wss://a"}))
        self.assertIsNone(crea_canale_nostr_da_env({"NOSTR_PRIVATE_KEY": SK_HEX,
                                                    "NOSTR_RELAYS": " , "}))
        c = crea_canale_nostr_da_env({"NOSTR_PRIVATE_KEY": SK_HEX,
                                      "NOSTR_RELAYS": "wss://a, wss://b"})
        self.assertIsNotNone(c)


# ══════════════════════════════════════════════════════════════════════════════
#  4) INDEXNOW (fase169): lotti + chiave servita dal server vero
# ══════════════════════════════════════════════════════════════════════════════
class TestIndexNowContratto(_ContrattiPuliti):
    HOST = "bookinvip.com"
    KEY = "chiavecollaudoesterni0123456789a"

    def _adapter(self, finto):
        return IndexNow(self.KEY, self.HOST, fetch=finto)

    def test_forma_della_richiesta_e_keylocation(self):
        f = FintoIndexNow()
        out = self._adapter(f).submit(["https://bookinvip.com/a", "https://bookinvip.com/b"])
        self.assertEqual(out, {"inviato": True, "url": 2, "stato": 200})
        corpo = json.loads(f.richieste[0]["body"].decode("utf-8"))
        self.assertEqual(corpo["host"], self.HOST)
        self.assertEqual(corpo["key"], self.KEY)
        self.assertEqual(corpo["keyLocation"],
                         "https://%s/%s.txt" % (self.HOST, self.KEY))
        self.assertEqual(corpo["urlList"], ["https://bookinvip.com/a",
                                            "https://bookinvip.com/b"])

    def test_lotto_cappato_a_diecimila_e_senza_duplicati(self):
        f = FintoIndexNow()
        urls = ["https://bookinvip.com/p/%d" % i for i in range(MAX_URL_BATCH + 500)]
        urls += urls[:10]                                  # duplicati in coda
        out = self._adapter(f).submit(urls)
        self.assertEqual(out["url"], MAX_URL_BATCH)
        corpo = json.loads(f.richieste[0]["body"].decode("utf-8"))
        self.assertEqual(len(corpo["urlList"]), MAX_URL_BATCH)
        self.assertEqual(len(set(corpo["urlList"])), MAX_URL_BATCH)

    def test_url_di_altri_host_scartati_prima_di_partire(self):
        """Regola IndexNow: un solo host per invio. Un URL estraneo fa rifiutare TUTTO
        il lotto — quindi va filtrato da noi, non dal motore di ricerca.

        NB misurato, non supposto: il confronto e' sull'HOST, quindi `http://` dello stesso
        host PASSA (per IndexNow e' lo stesso sito). Non e' un difetto — e' la regola — ma
        va scritto qui nero su bianco, altrimenti domani sembra una svista."""
        f = FintoIndexNow()
        out = self._adapter(f).submit(["https://bookinvip.com/ok",
                                       "https://esempio.it/altro",
                                       "https://www.bookinvip.com/sottodominio",
                                       "http://bookinvip.com/stesso-host-altro-schema",
                                       "ftp://bookinvip.com/x", "non-un-url", None, 42])
        self.assertEqual(out["url"], 2)
        corpo = json.loads(f.richieste[0]["body"].decode("utf-8"))
        self.assertEqual(corpo["urlList"],
                         ["https://bookinvip.com/ok",
                          "http://bookinvip.com/stesso-host-altro-schema"])

    def test_nessun_url_valido_nessuna_chiamata(self):
        f = FintoIndexNow()
        out = self._adapter(f).submit(["https://esempio.it/a"])
        self.assertEqual(out, {"inviato": False, "motivo": "nessun_url_valido"})
        self.assertEqual(f.richieste, [], "invio a vuoto: quota bruciata per niente")

    def test_senza_chiave_dormiente(self):
        f = FintoIndexNow()
        for chiave, host in ((None, self.HOST), ("", self.HOST), (self.KEY, None),
                             (self.KEY, "")):
            i = IndexNow(chiave, host, fetch=f)
            self.assertFalse(i.attivo)
            self.assertEqual(i.submit(["https://bookinvip.com/a"]),
                             {"inviato": False, "motivo": "disattivo"})
        self.assertEqual(f.richieste, [])

    def test_errore_di_rete_isolato(self):
        for guasto in (urllib.error.HTTPError("https://api.indexnow.org", 403, "Forbidden",
                                              {}, None),
                       urllib.error.URLError("dns"), RuntimeError("timeout")):
            f = FintoIndexNow(guasto=guasto)
            self.assertEqual(self._adapter(f).submit(["https://bookinvip.com/a"]),
                             {"inviato": False, "motivo": "errore_rete"}, repr(guasto))
            azzera_finti()

    def test_builder_puri_coerenti_con_l_adapter(self):
        """Oracolo indipendente: il corpo spedito e' esattamente quello del builder puro."""
        f = FintoIndexNow()
        urls = ["https://bookinvip.com/a", "https://bookinvip.com/a",
                "https://altro.it/b"]
        self._adapter(f).submit(urls)
        atteso = payload_indexnow(self.HOST, self.KEY, urls,
                                  key_location="https://%s/%s.txt" % (self.HOST, self.KEY))
        self.assertEqual(json.loads(f.richieste[0]["body"].decode("utf-8")), atteso)
        self.assertEqual(urls_valide(urls, self.HOST), ["https://bookinvip.com/a"])


class TestIndexNowChiaveServita(unittest.TestCase):
    """La chiave IndexNow non serve a niente se il motore non la trova sul sito: Bing scarica
    https://HOST/CHIAVE.txt e pretende dentro la chiave. Qui gira un SERVER VERO."""

    KEY = "chiavecollaudoesterni0123456789a"

    # Il server VERO accende anche i suoi servizi di fondo: senza queste tre variabili
    # andrebbe in RETE a chiedere una marca temporale a una TSA vera e passerebbe la
    # ramazza sulla `data/uploads` DELLO SVILUPPATORE. Un test non tocca ne' la rete ne'
    # i file di chi lo esegue.
    ENV = {"INDEXNOW_KEY": KEY, "MARCA_TEMPORALE": "0", "PULIZIA_UPLOADS": "0"}

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="indexnow_")
        d = cls.dir
        cls.ENV = dict(cls.ENV, UPLOAD_DIR=d + "/uploads",
                       OUTREACH_OPTOUT_FILE=d + "/optout.json")
        cls._env_prec = {k: os.environ.get(k) for k in cls.ENV}
        os.environ.update(cls.ENV)
        cls.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"k" * 32,
            db_catalogo=d + "/c.db", db_inventario=d + "/i.db",
            db_registro_host=d + "/r.db", db_finanza=d + "/fin.db"))
        cls.porta = _porta_libera()
        cls.t = threading.Thread(
            target=fase83_server.servi,
            kwargs=dict(sistema=cls.sis, host="127.0.0.1", porta=cls.porta,
                        cartella_statica="deploy", host_key="hk", admin_key="ak"),
            daemon=True)
        cls.t.start()
        for _ in range(300):
            try:
                if cls._req("GET", "/robots.txt")[0] == 200:
                    break
            except Exception:
                pass
            time.sleep(0.02)

    @classmethod
    def tearDownClass(cls):
        for chiave, valore in cls._env_prec.items():
            if valore is None:
                os.environ.pop(chiave, None)
            else:
                os.environ[chiave] = valore
        shutil.rmtree(cls.dir, ignore_errors=True)

    @classmethod
    def _req(cls, metodo, path):
        c = http.client.HTTPConnection("127.0.0.1", cls.porta, timeout=6)
        c.request(metodo, path)
        r = c.getresponse()
        corpo = r.read().decode("utf-8", "replace")
        intestazioni = {k.lower(): v for k, v in r.getheaders()}
        c.close()
        return r.status, intestazioni, corpo

    def test_il_file_di_verifica_contiene_esattamente_la_chiave(self):
        stato, hd, corpo = self._req("GET", "/%s.txt" % self.KEY)
        self.assertEqual(stato, 200)
        self.assertIn("text/plain", hd.get("content-type", ""))
        self.assertEqual(corpo.strip(), self.KEY)
        self.assertEqual(corpo.strip(), key_file_body(self.KEY))

    def test_solo_la_chiave_configurata_e_servita(self):
        """Non e' un endpoint che stampa qualunque nome gli si chieda: solo LA chiave."""
        for path in ("/chiave-inventata.txt", "/%s.txt" % self.KEY.upper(),
                     "/%sx.txt" % self.KEY, "/x%s.txt" % self.KEY):
            stato, _hd, corpo = self._req("GET", path)
            self.assertNotEqual(stato, 200, path)
            self.assertNotIn(self.KEY, corpo, "chiave trapelata su %s" % path)

    def test_senza_chiave_in_ambiente_nessun_file(self):
        os.environ.pop("INDEXNOW_KEY", None)
        try:
            stato, _hd, corpo = self._req("GET", "/%s.txt" % self.KEY)
            self.assertNotEqual(stato, 200)
            self.assertNotIn(self.KEY, corpo)
        finally:
            os.environ["INDEXNOW_KEY"] = self.KEY


# ══════════════════════════════════════════════════════════════════════════════
#  5) CABLAGGIO (fase91) e DISPATCH (fase90)
# ══════════════════════════════════════════════════════════════════════════════
class TestCablaggioCanaliNuovi(_ContrattiPuliti):
    """Il modo di rompersi n.2 del progetto: «il pezzo e' perfetto e non e' collegato».
    Qui si prova che i canali nuovi entrano DAVVERO nel giro comune di fase91."""

    ENV_COMPLETO = {"MASTODON_INSTANCE": "mastodon.social", "MASTODON_TOKEN": "t",
                    "BLUESKY_HANDLE": "x.bsky.social", "BLUESKY_APP_PASSWORD": "p",
                    "REDDIT_CLIENT_ID": "a", "REDDIT_CLIENT_SECRET": "b",
                    "REDDIT_USERNAME": "c", "REDDIT_PASSWORD": "d",
                    "REDDIT_SUBREDDIT": "viaggi",
                    "NOSTR_PRIVATE_KEY": SK_HEX, "NOSTR_RELAYS": "wss://relay.damus.io"}

    def test_ambiente_vuoto_nessun_canale(self):
        self.assertEqual(crea_canali_da_env({}), {})

    def test_ogni_canale_si_accende_dal_suo_token(self):
        canali = crea_canali_da_env(dict(self.ENV_COMPLETO))
        for nome in ("mastodon", "bluesky", "reddit", "nostr"):
            self.assertIn(nome, canali, "canale %s costruito ma NON cablato in fase91" % nome)
            self.assertEqual(canali[nome].nome, nome)
        self.assertNotIn("telegram", canali, "telegram acceso senza il suo token")

    def test_un_canale_alla_volta(self):
        """Accendere Bluesky non deve accendere anche gli altri (e viceversa)."""
        soli = {"bluesky": ("BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD"),
                "mastodon": ("MASTODON_INSTANCE", "MASTODON_TOKEN"),
                "nostr": ("NOSTR_PRIVATE_KEY", "NOSTR_RELAYS")}
        for nome, chiavi in soli.items():
            env = {k: self.ENV_COMPLETO[k] for k in chiavi}
            canali = crea_canali_da_env(env)
            self.assertEqual(sorted(canali), [nome], "env di %s ha acceso %s"
                             % (nome, sorted(canali)))


class TestCampagnaIsolata(_ContrattiPuliti):
    """Un canale che esplode non deve fermare la campagna sugli altri: il conteggio finale
    deve dire la verita' su chi ha pubblicato e chi no."""

    def test_canale_rotto_non_ferma_gli_altri_e_il_conteggio_e_onesto(self):
        class _Esplode:
            nome = "rotto"

            def pubblica(self, post):
                raise RuntimeError("canale morto")

        class _Rifiuta:
            nome = "rifiuta"

            def pubblica(self, post):
                return False

        class _Buono:
            nome = "buono"

            def __init__(self):
                self.visti = []

            def pubblica(self, post):
                self.visti.append(post.testo)
                return True

        buono = _Buono()
        motore = MotoreMarketing(GeneratoreContenuti(),
                                 {"rotto": _Esplode(), "rifiuta": _Rifiuta(),
                                  "buono": buono})
        piano = [{"canale": c, "post": _post()} for c in ("rotto", "rifiuta", "buono")]
        piano.append({"canale": "inesistente", "post": _post()})
        piano.append({"canale": "buono", "post": "non-un-post"})
        rep = motore.pubblica_piano(piano)
        self.assertEqual(rep["totale"], 5)
        self.assertEqual(rep["pubblicati"], 1)
        self.assertEqual(rep["saltati"], 4)
        self.assertEqual(rep["per_canale"], {"buono": 1})
        self.assertEqual(len(buono.visti), 1, "il post non valido e' arrivato al canale")


if __name__ == "__main__":
    unittest.main(verbosity=2)
