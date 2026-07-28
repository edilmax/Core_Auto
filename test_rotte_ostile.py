# -*- coding: utf-8 -*-
"""GIRO OSTILE SU TUTTE E 134 LE ROTTE — verifica INDIPENDENTE (revisore avverso).

Tesi da REFUTARE: «ogni rotta risponde correttamente a una richiesta valida».
Questo file NON riusa nulla dei collaudi happy-path per fetta: costruisce un mondo suo
(host veri, annunci veri, prenotazioni pagate col webhook FIRMATO, sessione Bunker) e poi
chiama **una per una tutte le rotte del router**, con l'autenticazione giusta e i dati
giusti, registrando lo stato ottenuto.

Cosa fa fallire questo file (i quattro difetti che cerca):
  1. una rotta che risponde 4xx/5xx a una richiesta LEGITTIMA;
  2. una rotta FANTASMA: dichiarata nel codice ma irraggiungibile ('rotta_non_trovata');
  3. una rotta che risponde 200 ma con corpo VUOTO o senza le chiavi promesse;
  4. una rotta NUOVA aggiunta al router e mai messa in questa tabella (guardia
     auto-applicante: la tabella si confronta con il sorgente di `_instrada`).

COME SI LEGGE: ogni riga del giro e' una chiamata `self.chiama(metodo, path, stato_atteso,
[(chiave, tipo), ...], valore={...})` — lo stato e' ESATTO (mai «< 500»), le chiavi e i tipi
del corpo sono verificati, e dove ha senso si controlla un VALORE VERO (un id, un totale,
un conteggio). `DORMIENTI` elenca le DUE sole rotte che rispondono 503 per progetto
(connettore spento senza chiave): sono dichiarate qui, non nascoste.

ROTTE ESCLUSE: nessuna. Tutte e 134 sono esercitate sul router vero; l'ultimo blocco del
test lo DIMOSTRA confrontando le rotte visitate con quelle estratte dal sorgente di
`_instrada` (se non coincidono, il test fallisce dicendo quali mancano).

Nessuna rete: Stripe, Stripe Connect, la carta off-session, il geocoder, la TSA (marca
temporale RFC 3161) e la riconciliazione Stripe sono sostituiti da finti deterministici.

VISTA ROSSA (provata): togliendo dal router una qualsiasi riga di `_instrada` la rotta
diventa 'rotta_non_trovata' e il giro fallisce nominandola; cambiando lo stato di ritorno
di un handler (es. 201 -> 200 su /api/host/pubblica) il giro fallisce sulla riga giusta.
"""
import datetime
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest

import fase182_riconciliazione as _ric
import fase184_marca_temporale as _marca
import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_ostile"
BASE = datetime.date.today() + datetime.timedelta(days=30)
PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8"
       "BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

# ── Rotte che rispondono 503 PER PROGETTO (connettore dormiente senza chiave) ──────────
DORMIENTI = {
    ("POST", "/api/host/kyc_avvia"):
        "Stripe Identity dormiente: si accende con STRIPE_IDENTITY_KEY nell'ambiente",
    ("POST", "/api/bunker/cambio_valuta/aggiorna"):
        "convertitore valuta dormiente: si accende con OXR_APP_ID nel .env",
}


def _g(i):
    return (BASE + datetime.timedelta(days=i)).isoformat()


def _fake_stripe(url, body, headers):
    import secrets
    return {"url": "https://stripe.finto/x", "id": "cs_" + secrets.token_hex(8)}


class _Email:
    def __init__(self):
        self.inviate = []

    def invia(self, dest, oggetto, html):
        self.inviate.append((dest, oggetto, html))
        return True


class _Geo:
    def geocodifica(self, citta, indirizzo="", paese=""):
        return (41902782, 12496366)


def rotte_del_router():
    """Le rotte DICHIARATE nel sorgente di `_instrada` (fonte di verita' del router).
    Serve alla guardia auto-applicante: una rotta nuova non puo' restare senza copertura."""
    perc = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fase83_server.py")
    with io.open(perc, encoding="utf-8") as f:
        src = f.read()
    i = src.index("def _instrada(")
    f = src.index('return 404, {"errore": "rotta_non_trovata"}', i)
    fuori = set()
    for m in re.finditer(r'metodo == "(\w+)" and path\s*(==|\.startswith\()\s*"([^"]+)"',
                         src[i:f]):
        fuori.add((m.group(1), m.group(3)))
    return fuori


class TestGiroOstileTutteLeRotte(unittest.TestCase):
    """Un solo mondo, un solo giro: l'ordine conta (le distruttive stanno in fondo)."""

    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls._orig_stripe = _stripe.ProviderStripe._fetch_reale
        cls._orig_marca = _marca.chiedi_marca
        cls._orig_ric = _ric._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_stripe)
        _marca.chiedi_marca = lambda impronta, url=None, trasporto=None, **k: {
            "ok": True, "tsa": "https://tsa.finta/ts", "policy": "1.2.3",
            "seriale": "1", "gen_time": 1785250000, "qualificata": True,
            "token": b"\x30\x03\x02\x01\x00"}
        _ric._fetch_reale = lambda percorso, params, chiave: {"data": [],
                                                             "has_more": False}

        cls.dir = tempfile.mkdtemp(prefix="rotte_ostile_")
        cls._env = {k: os.environ.get(k) for k in ("DATA_DIR", "UPLOAD_DIR")}
        os.environ["DATA_DIR"] = cls.dir
        os.environ["UPLOAD_DIR"] = os.path.join(cls.dir, "uploads")
        with io.open(os.path.join(cls.dir, "app.log"), "w", encoding="utf-8") as f:
            f.write("2026-07-28 10:00:00 INFO core_auto.server avvio\n")

        kw = dict(abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
                  commissione_bps=1000, psp_bps=300, stripe_secret_key="sk_test_ostile",
                  stripe_webhook_secret=WH, stripe_success_url="https://x/ok",
                  stripe_cancel_url="https://x/ko", bunker_password="SuperPw@1")
        # SMTP volutamente NON configurato: l'unico provider email e' lo stub qui sotto
        # (zero rete, e le email restano ispezionabili una per una).
        for campo in ConfigCasaVIP.__dataclass_fields__:
            if campo.startswith("db_"):
                kw[campo] = os.path.join(cls.dir, campo + ".db")
        cls.sis = crea_sistema(ConfigCasaVIP(**kw))
        cls.mail = _Email()
        cls.sis.email_provider = cls.mail
        cls.sis.geocoder = _Geo()
        if getattr(cls.sis, "connect", None) is not None:
            cls.sis.connect.trasferisci = lambda *a, **k: "tr_finto"
            cls.sis.connect.crea_account = lambda email="": "acct_finto"
            cls.sis.connect.link_onboarding = lambda a, ritorno: "https://connect.finto/onb"
            cls.sis.connect.stato_account = lambda a: {"pronto": True}
        if getattr(cls.sis, "carta", None) is not None:
            cls.sis.carta.crea_link_carta = \
                lambda host_id="", email="": "https://carta.finta/setup"
        cls.r = crea_router(cls.sis, host_key="hk", admin_key="ak",
                            base_url="https://bookinvip.com")

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig_stripe
        _marca.chiedi_marca = cls._orig_marca
        _ric._fetch_reale = cls._orig_ric
        for k, v in cls._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.dir, ignore_errors=True)

    # ── infrastruttura del giro ────────────────────────────────────────────────────────
    def setUp(self):
        self.visitate = {}          # (metodo, path_dichiarato) -> (stato, corpo)
        self.IP = {"X-Forwarded-For": "203.0.113.9"}
        self.ADM = dict(self.IP, **{"X-Admin-Key": "ak"})

    def chiama(self, metodo, path, atteso, chiavi=(), *, body=None, headers=None,
               query=None, raw=None, dichiarata=None, valore=None):
        """UNA rotta: stato ESATTO + corpo dict NON vuoto + chiavi/tipi + (opz.) un valore."""
        corpo_txt = raw if raw is not None else (json.dumps(body) if body is not None
                                                 else None)
        stato, out = self.r.gestisci(metodo, path, query or {}, corpo_txt, headers or {})
        chiave = (metodo, dichiarata or path)
        self.visitate[chiave] = (stato, out)
        self.assertNotEqual(
            (out or {}).get("errore") if isinstance(out, dict) else None,
            "rotta_non_trovata",
            "ROTTA FANTASMA: %s %s e' nel codice ma il router non la instrada" % chiave)
        self.assertEqual(stato, atteso,
                         "%s %s: atteso %d, ottenuto %d -> %r" % (metodo, path, atteso,
                                                                  stato, out))
        self.assertIsInstance(out, dict, "%s %s: corpo non e' un oggetto JSON" % chiave)
        self.assertTrue(out, "%s %s: risponde %d ma con CORPO VUOTO" % (metodo, path,
                                                                        stato))
        for nome, tipo in chiavi:
            self.assertIn(nome, out, "%s %s: manca la chiave '%s' nel corpo (%r)"
                          % (metodo, path, nome, out))
            self.assertIsInstance(out[nome], tipo,
                                  "%s %s: '%s' e' %r, atteso %s"
                                  % (metodo, path, nome, out[nome], tipo))
        if valore is not None:
            for nome, atteso_v in valore.items():
                self.assertEqual(out.get(nome), atteso_v,
                                 "%s %s: '%s' vale %r, atteso %r"
                                 % (metodo, path, nome, out.get(nome), atteso_v))
        return out

    # ── mattoni del mondo (usano rotte VERE: contano gia' come copertura) ─────────────
    def registra_host(self, email, atteso=201):
        out = self.chiama("POST", "/api/host/registrazione", atteso,
                          [("host_id", str), ("token", str)],
                          body={"email": email, "password": "password1",
                                "accetta_termini": True, "accetta_clausole": True,
                                "accetta_privacy": True, "doc_sha256": doc_sha256(),
                                "versione": CONTRATTO_HOST_VERSIONE}, headers=self.IP)
        return out["host_id"], dict(self.IP, **{"X-Host-Token": out["token"]})

    def pubblica(self, slug, tok, atteso=201, **extra):
        corpo = {"slug": slug, "titolo": "Casa " + slug, "citta": "Roma", "paese": "IT",
                 "cin": "IT058091C2X5V0ABCD", "descrizione": "Casa vera del giro ostile",
                 "prezzo_notte_cents": 30000, "capacita": 4,
                 "politica_cancellazione": "flessibile", "tassa_pp_notte_cents": 150,
                 "lat_micro": 41902782, "lon_micro": 12496366,
                 "servizi": ["wifi"], "immagini": []}
        corpo.update(extra)
        self.chiama("POST", "/api/host/pubblica", atteso,
                    [("slug", str), ("stato", str)], body=corpo, headers=tok,
                    valore={"slug": slug, "stato": "pubblicato"})
        self.chiama("POST", "/api/host/disponibilita_range", 200,
                    [("giorni_impostati", int)],
                    body={"alloggio_id": slug, "da": _g(0), "a": _g(25),
                          "unita_totali": 3, "prezzo_netto_cents": 30000}, headers=tok)
        return slug

    def prenota(self, slug, ci, co, email, atteso_book=201):
        q = self.chiama("POST", "/api/concierge/quote", 200,
                        [("quote_token", str), ("totale_cents", int),
                         ("netto_host_cents", int), ("commissione_cents", int)],
                        body={"alloggio_id": slug, "check_in": ci, "check_out": co,
                              "party": 2}, headers=self.IP)
        self.assertGreater(q["totale_cents"], 0, "preventivo a zero: prezzo perso")
        b = self.chiama("POST", "/api/concierge/book", atteso_book,
                        [("riferimento", str), ("totale_cents", int)],
                        body={"quote_token": q["quote_token"], "email": email,
                              "lang": "it"}, headers=self.IP)
        self.assertEqual(b["totale_cents"], q["totale_cents"],
                         "il totale cambia tra preventivo e prenotazione")
        return b

    def paga(self, rif):
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"id": "cs_" + rif[:10],
                                             "metadata": {"riferimento": rif}}}})
        self.chiama("POST", "/api/payments/webhook", 200, [("ricevuto", bool)],
                    raw=pl,
                    headers={"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))},
                    valore={"ricevuto": True})
        self.assertEqual((self.sis.pagamenti_pendenti.info(rif) or {}).get("stato"),
                         "pagato", "il webhook firmato non ha confermato il pagamento")

    # ══════════════════════════════════════════════════════════════════════════════════
    def test_giro_completo_tutte_le_rotte(self):
        IP, ADM = self.IP, self.ADM

        # ── MONDO ────────────────────────────────────────────────────────────────────
        host_id, TOK = self.registra_host("host@ostile.it")
        host_pulito, _TOK2 = self.registra_host("pulito@ostile.it")
        slug = self.pubblica("casa-ostile", TOK)
        slug_vuoto = self.pubblica("casa-vuota", TOK)
        slug_ric = self.pubblica("casa-richiesta", TOK,
                                 modalita_prenotazione="su_richiesta")
        b_rec = self.prenota(slug, _g(1), _g(3), "rec@ostile.it")
        self.paga(b_rec["riferimento"])
        b_conf = self.prenota(slug, _g(5), _g(7), "conf@ostile.it")
        self.paga(b_conf["riferimento"])
        b_cont = self.prenota(slug, _g(9), _g(10), "cont@ostile.it")
        self.paga(b_cont["riferimento"])
        b_rimb = self.prenota(slug, _g(13), _g(14), "rimb@ostile.it")
        self.paga(b_rimb["riferimento"])
        b_hcanc = self.prenota(slug, _g(17), _g(18), "hcanc@ostile.it")
        self.paga(b_hcanc["riferimento"])
        b_gcanc = self.prenota(slug, _g(21), _g(22), "gcanc@ostile.it")
        self.paga(b_gcanc["riferimento"])
        rq1 = self.prenota(slug_ric, _g(1), _g(2), "req1@ostile.it")
        rq2 = self.prenota(slug_ric, _g(4), _g(5), "req2@ostile.it")
        self.assertEqual(rq1.get("stato"), "in_attesa_host",
                         "annuncio 'su richiesta': la prenotazione deve attendere l'host")
        rif = b_rec["riferimento"]
        vt = b_rec["voucher_token"]

        # ── PUBBLICHE: salute, i18n, documenti ───────────────────────────────────────
        self.chiama("GET", "/api/health", 200, [("status", str)], valore={"status": "ok"})
        self.chiama("GET", "/api/health/live", 200, [("status", str)],
                    valore={"status": "live"})
        self.chiama("GET", "/api/health/ready", 200, [("status", str)],
                    valore={"status": "ready"})
        salute = self.chiama("GET", "/api/health/db", 200, [("db", dict)],
                             valore={"status": "ok"})
        self.assertTrue(salute["db"], "sonda DB: nessun archivio censito")
        self.assertTrue(all(v == "ok" for v in salute["db"].values()), salute["db"])
        ling = self.chiama("GET", "/api/lingue", 200, [("lingue", list)])
        self.assertIn("it", ling["lingue"])
        self.chiama("GET", "/api/i18n", 200, [("lingua", str), ("ui", dict)],
                    query={"lang": "it"}, valore={"lingua": "it"})
        self.chiama("GET", "/api/legale/documento", 200,
                    [("documento", str), ("versione", str), ("testo", str)],
                    query={"tipo": "privacy", "lang": "it"})
        self.chiama("GET", "/api/legale/contratto-host", 200,
                    [("doc_sha256", str), ("versione", str), ("testo", str)],
                    query={"lang": "it"},
                    valore={"doc_sha256": doc_sha256(),
                            "versione": CONTRATTO_HOST_VERSIONE})
        tr = self.chiama("GET", "/api/trasparenza", 200,
                         [("scenario_nostro", dict), ("scenario_ota", dict)],
                         query={"prezzo_cents": "10000", "ota": "booking"},
                         valore={"prezzo_riferimento_cents": 10000})
        self.assertGreater(tr["scenario_nostro"]["host_netto_cents"],
                           tr["scenario_ota"]["host_netto_cents"],
                           "la trasparenza dice che con noi l'host guadagna MENO")

        # ── PUBBLICHE: vetrina ───────────────────────────────────────────────────────
        cat = self.chiama("GET", "/api/catalogo", 200,
                          [("totale", int), ("risultati", list)], query={"citta": "Roma"})
        self.assertEqual(cat["totale"], 3, "il catalogo non mostra i 3 annunci veri")
        self.chiama("GET", "/api/catalogo/" + slug, 200,
                    [("slug", str), ("titolo", str), ("prezzo_notte_cents", int)],
                    dichiarata="/api/catalogo/*",
                    valore={"slug": slug, "prezzo_notte_cents": 30000})
        mappa = self.chiama("GET", "/api/mappa", 200, [("features", list)],
                            query={"citta": "Roma"}, valore={"type": "FeatureCollection"})
        self.assertTrue(mappa["features"], "mappa senza punti pur avendo annunci geolocalizzati")
        self.chiama("GET", "/api/tassa", 200,
                    [("tassa_cents", int), ("notti_tassabili", int)],
                    query={"citta": "Roma", "paese": "IT", "notti": "2", "ospiti": "2",
                           "alloggio_id": slug}, valore={"notti_tassabili": 2})
        man = self.chiama("GET", "/api/concierge/manifest", 200,
                          [("nome", str), ("flusso", list), ("mcp", str)])
        self.assertEqual(len(man["flusso"]), 3, "il manifest promette un flusso diverso da 3 passi")
        self.chiama("POST", "/api/mcp", 200, [("result", dict)],
                    body={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

        # ── PUBBLICHE: domanda, partner, documenti dell'ospite ───────────────────────
        dom = self.chiama("POST", "/api/domanda", 201, [("credito_token", str)],
                          body={"email": "lead@ostile.it", "citta": "Milano"},
                          valore={"ok": True})
        self.assertTrue(self.sis.firma.decodifica(dom["credito_token"]),
                        "il credito fondatore non e' un token firmato valido")
        self.chiama("GET", "/api/domanda/conta", 200, [("richieste", int)],
                    query={"citta": "Milano"}, valore={"citta": "Milano", "richieste": 1})
        self.chiama("GET", "/api/domanda/citta", 200, [("citta", list), ("soglia", int)])
        self.chiama("POST", "/api/partner", 201, [("ok", bool)],
                    body={"nome": "Partner Ostile", "email": "p@ostile.it",
                          "tipo": "agenzia", "citta": "Roma", "consenso": True},
                    valore={"ok": True})
        contr = self.chiama("POST", "/api/contratto", 200, [("righe", list)],
                            body={"voucher_token": vt, "lang": "it"})
        self.assertTrue(any("Casa casa-ostile" in x or "casa-ostile" in x or "Roma" in x
                            for x in contr["righe"]),
                        "il contratto non nomina l'alloggio vero")
        self.chiama("POST", "/api/preventivo/email", 200, [("stato", str)],
                    body={"alloggio_id": slug, "check_in": _g(1), "check_out": _g(3),
                          "party": 2, "email": "prev@ostile.it", "lang": "it"},
                    valore={"stato": "inviata"})

        # ── SPLIT DI GRUPPO ──────────────────────────────────────────────────────────
        self.chiama("POST", "/api/split/preview", 200,
                    [("quote", list), ("totale_cents", int)],
                    body={"totale_cents": 30000, "n": 3},
                    valore={"n": 3, "totale_cents": 30000})
        sc = self.chiama("POST", "/api/split/crea", 201, [("conto_id", str), ("stato", dict)],
                         body={"prenotazione_id": rif, "alloggio_id": slug,
                               "totale_cents": 30000,
                               "partecipanti": ["anna", "bruno", "carla"]})
        conto = sc["conto_id"]
        st = self.chiama("GET", "/api/split/stato", 200,
                         [("totale_cents", int), ("mancante_cents", int), ("quote", list)],
                         query={"conto_id": conto},
                         valore={"totale_cents": 30000, "raccolto_cents": 0})
        self.assertEqual(st["mancante_cents"], 30000, st)
        self.assertEqual(sum(q["dovuto_cents"] for q in st["quote"]), 30000,
                         "le quote non sommano al totale: centesimi persi")
        self.chiama("POST", "/api/split/paga", 200, [("stato", str), ("completato", bool)],
                    body={"conto_id": conto, "partecipante_id": "anna"},
                    valore={"stato": "pagato", "completato": False})

        # ── CHAT, PROVE, CHECK-IN, GARANZIA ──────────────────────────────────────────
        self.chiama("POST", "/api/voucher/messaggio", 201, [("stato", str)],
                    body={"voucher_token": vt, "testo": "Ciao host, a che ora il check-in?"},
                    valore={"stato": "inviato"})
        thr = self.chiama("GET", "/api/voucher/messaggi", 200, [("messaggi", list)],
                          query={"voucher_token": vt})
        self.assertEqual(len(thr["messaggi"]), 1, thr)
        self.chiama("POST", "/api/voucher/prova", 201, [("url", str)],
                    body={"voucher_token": vt, "image_base64": PNG})
        self.chiama("POST", "/api/messaggi", 201, [("stato", str)],
                    body={"prenotazione_id": rif, "guest_id": "ospite",
                          "testo": "Benvenuto!"}, headers=TOK, valore={"stato": "inviato"})
        thr2 = self.chiama("GET", "/api/messaggi", 200, [("messaggi", list)],
                           query={"prenotazione_id": rif}, headers=TOK)
        self.assertEqual(len(thr2["messaggi"]), 3, thr2)
        self.chiama("POST", "/api/checkin/pre_registra", 200, [("ospiti", int)],
                    body={"voucher_token": vt, "ospiti": [
                        {"nome": "Mario", "cognome": "Rossi",
                         "data_nascita": "1980-01-01", "documento": "AB123",
                         "tipo_documento": "carta_identita", "cittadinanza": "IT"}]},
                    valore={"ok": True, "ospiti": 1})
        self.chiama("GET", "/api/checkin/stato", 200, [("completato", bool)],
                    query={"voucher_token": vt}, valore={"completato": True})
        gs = self.chiama("GET", "/api/garanzia/stato", 200,
                         [("stato", str), ("importo_host_cents", int)],
                         query={"ref": rif}, headers=ADM, valore={"stato": "in_garanzia"})
        self.assertGreater(gs["importo_host_cents"], 0, "escrow aperto a zero")
        self.chiama("POST", "/api/garanzia/conferma", 200,
                    [("host_riceve_cents", int)],
                    body={"voucher_token": b_conf["voucher_token"]},
                    valore={"ok": True, "stato": "rilasciato"})
        self.chiama("POST", "/api/garanzia/contesta", 200, [("stato", str)],
                    body={"voucher_token": b_cont["voucher_token"],
                          "motivo": "riscaldamento non funzionante"},
                    valore={"ok": True, "stato": "contestato"})

        # ── RECENSIONI (il diritto si spende DOPO il check-out) ──────────────────────
        co = datetime.date.fromisoformat(b_rec["check_out"])
        dopo = int(time.mktime(datetime.datetime(co.year, co.month, co.day,
                                                 12, 0, 0).timetuple())) + 86400
        self.sis.recensioni._now = lambda: dopo
        self.chiama("POST", "/api/recensioni", 201, [("ok", bool), ("verificata", bool)],
                    body={"token": b_rec["diritto_recensione"], "voto": 5, "lingua": "it",
                          "testo": "Casa pulita, host presente, tornerei.",
                          "categorie": {"pulizia": 5}},
                    valore={"ok": True, "verificata": True})
        vet = self.chiama("GET", "/api/recensioni/" + slug, 200,
                          [("riepilogo", dict), ("recensioni", list)],
                          dichiarata="/api/recensioni/*")
        self.assertEqual(vet["riepilogo"]["conteggio"], 1, vet)
        self.assertEqual(vet["riepilogo"]["media_centesimi"], 500, vet)

        # ── CANALI E WEBHOOK ESTERNI ─────────────────────────────────────────────────
        camp = self.chiama("POST", "/api/marketing/campagna", 200,
                           [("totale", int), ("post_generati", int)],
                           body={"citta": "Roma", "lingua": "it"}, headers=ADM)
        self.assertGreater(camp["post_generati"], 0, "campagna senza nemmeno un post")
        self.chiama("POST", "/api/telegram/webhook", 200, [("ok", bool)],
                    body={"message": {"chat": {"id": 1}, "text": "/start"}}, headers=IP,
                    valore={"ok": True})
        gl = self.chiama("POST", "/api/gate/logout", 200, [("_cookie", list)],
                         body={}, headers=IP, valore={"ok": True})
        self.assertTrue(all(c[1] == "" and c[2] == 0 for c in gl["_cookie"]),
                        "il logout non cancella i cookie")

        # ── HOST: letture ────────────────────────────────────────────────────────────
        al = self.chiama("GET", "/api/host/alloggi", 200, [("alloggi", list)], headers=TOK)
        self.assertEqual(len(al["alloggi"]), 3, al)
        self.chiama("GET", "/api/host/alloggio", 200, [("slug", str), ("titolo", str)],
                    query={"slug": slug}, headers=TOK, valore={"slug": slug})
        cal = self.chiama("GET", "/api/host/calendario", 200, [("giorni", list)],
                          query={"alloggio": slug, "da": _g(0), "a": _g(10)}, headers=TOK)
        self.assertEqual(len(cal["giorni"]), 10, cal)          # range [da, a)
        cp = self.chiama("GET", "/api/host/calendario_prezzi", 200, [("celle", list)],
                         query={"alloggio": slug, "da": _g(0), "a": _g(10)}, headers=TOK)
        self.assertTrue(all(c["prezzo_cents"] == 30000 for c in cp["celle"]), cp)
        ct = self.chiama("GET", "/api/host/calendario_tutti", 200, [("alloggi", list)],
                         query={"da": _g(0), "a": _g(5)}, headers=TOK)
        self.assertEqual(len(ct["alloggi"]), 3, ct)
        pr = self.chiama("GET", "/api/host/prenotazioni", 200, [("prenotazioni", list)],
                         headers=TOK)
        # 6 prenotazioni CONFERMATE (le 2 'su richiesta' non sono ancora prenotazioni)
        self.assertEqual(len(pr["prenotazioni"]), 6, pr)
        me = self.chiama("GET", "/api/host/metriche", 200,
                         [("revenue_cents", int), ("notti_occupate", int)], headers=TOK)
        self.assertGreater(me["revenue_cents"], 0, "metriche host a zero con 8 prenotazioni")
        self.chiama("GET", "/api/host/metriche_avanzate", 200,
                    [("metriche", dict), ("prenotazioni", int)], headers=TOK)
        ex = self.chiama("GET", "/api/host/export", 200, [("csv", str)],
                         query={"formato": "csv"}, headers=TOK)
        self.assertIn(slug, ex["csv"])
        pay = self.chiama("GET", "/api/host/payout", 200, [("payout", dict)], headers=TOK)
        self.assertGreater(pay["payout"]["EUR"]["maturato"], 0, pay)
        self.chiama("GET", "/api/host/referral", 200, [("codice", str), ("link", str)],
                    headers=TOK)
        ld = self.chiama("GET", "/api/host/link_diretto", 200,
                         [("alloggi", list), ("commissione_bps", int)], headers=TOK)
        self.assertEqual(ld["commissione_bps"], 500, "link diretto: non e' il 5%")
        self.chiama("GET", "/api/host/telegram_link", 200, [("link", str)], headers=TOK)
        il = self.chiama("GET", "/api/host/ical_link", 200, [("url", str)],
                         query={"alloggio": slug}, headers=TOK)
        self.assertTrue(il["url"].endswith(".ics"), il)
        inv = self.chiama("GET", "/api/host/invito", 200, [("codice", str), ("link", str)],
                          headers=TOK)
        self.chiama("GET", "/api/host/geocode", 200, [("lat_micro", int), ("lon_micro", int)],
                    query={"citta": "Roma"}, headers=TOK)
        self.chiama("GET", "/api/host/prezzo_suggerito", 200,
                    [("prezzo_cents", int), ("fattori", dict)],
                    query={"prezzo_base_cents": "30000", "occupazione_bps": "5000",
                           "giorni": "30"}, headers=TOK, valore={"base_cents": 30000})
        acc = self.chiama("GET", "/api/host/accettazioni", 200, [("accettazioni", list)],
                          headers=TOK)
        self.assertTrue(acc["accettazioni"], "nessuna prova firmata del contratto host")
        self.chiama("GET", "/api/host/contratto_stato", 200,
                    [("contratto_corrente", bool), ("versione_corrente", str)],
                    headers=TOK, valore={"contratto_corrente": True,
                                         "versione_corrente": CONTRATTO_HOST_VERSIONE})
        self.chiama("GET", "/api/host/dac7_stato", 200, [("mancanti", list)], headers=TOK)
        self.chiama("GET", "/api/host/kyc_stato", 200, [("stato", str)], headers=TOK)
        self.chiama("GET", "/api/host/carta_stato", 200, [("carta_collegata", bool)],
                    headers=TOK)
        self.chiama("GET", "/api/host/stripe_link", 200,
                    [("account_id", str), ("pronto", bool)], headers=TOK,
                    valore={"account_id": "acct_finto", "pronto": True})
        cv = self.chiama("GET", "/api/host/conversazioni", 200, [("conversazioni", list)],
                         headers=TOK)
        self.assertTrue(cv["conversazioni"], cv)
        rq = self.chiama("GET", "/api/host/richieste", 200, [("richieste", list)],
                         headers=TOK)
        self.assertEqual(len(rq["richieste"]), 2, rq)
        seo = self.chiama("GET", "/api/host/seo_report", 200,
                          [("punteggio", int), ("query_vincibili", list)],
                          query={"alloggio_id": slug}, headers=TOK)
        self.assertGreater(seo["punteggio"], 0, seo)

        # ── HOST: scritture ──────────────────────────────────────────────────────────
        self.chiama("POST", "/api/host/disponibilita", 200, [("stato", str)],
                    body={"alloggio_id": slug, "giorno": _g(24), "unita_totali": 2,
                          "prezzo_netto_cents": 30000}, headers=TOK,
                    valore={"stato": "ok"})
        self.chiama("POST", "/api/host/dati_fiscali", 200,
                    [("salvato", bool), ("mancanti", list)],
                    body={"codice_fiscale": "RSSMRA80A01H501U",
                          "indirizzo_fiscale": "Via Roma 1", "paese": "IT",
                          "iban": "IT60X0542811101000000123456"}, headers=TOK,
                    valore={"salvato": True, "mancanti": []})
        ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
               "DTSTART;VALUE=DATE:%s\r\nDTEND;VALUE=DATE:%s\r\nSUMMARY:Occupato\r\n"
               "END:VEVENT\r\nEND:VCALENDAR\r\n"
               % (_g(24).replace("-", ""), _g(25).replace("-", "")))
        self.chiama("POST", "/api/host/ical", 200,
                    [("eventi", int), ("giorni_bloccati", int)],
                    body={"alloggio_id": slug, "ical": ics}, headers=TOK,
                    valore={"eventi": 1, "giorni_bloccati": 1})
        imp = self.chiama("POST", "/api/host/importa", 200,
                          [("importati", int), ("risultati", list)],
                          body={"sorgente": "canonico", "dati": [
                              {"titolo": "Portata da Booking", "citta": "Roma",
                               "paese": "IT", "prezzo_notte": "180.00", "capacita": 2,
                               "descrizione": "Annuncio portato via export GDPR"}]},
                          headers=TOK, valore={"importati": 1})
        self.assertTrue(imp["risultati"][0]["ok"], imp)
        self.chiama("POST", "/api/host/kyc_avvia",
                    503, [("errore", str)], body={}, headers=TOK,
                    valore={"errore": "identity_non_configurato"})
        self.chiama("POST", "/api/host/carta_link", 200, [("url", str), ("mandato", str)],
                    body={}, headers=TOK, valore={"url": "https://carta.finta/setup"})
        self.chiama("POST", "/api/host/stato", 200, [("stato", str)],
                    body={"slug": slug, "stato": "pubblicato"}, headers=TOK,
                    valore={"stato": "pubblicato"})
        self.chiama("POST", "/api/host/riaccetta", 200, [("accettazione", dict)],
                    body={"accetta_termini": True, "accetta_clausole": True,
                          "accetta_privacy": True, "doc_sha256": doc_sha256(),
                          "versione": CONTRATTO_HOST_VERSIONE}, headers=TOK,
                    valore={"ok": True})
        up = self.chiama("POST", "/api/host/upload_foto", 201, [("url", str)],
                         body={"image_base64": PNG}, headers=TOK)
        self.assertTrue(up["url"].startswith("/uploads/"), up)
        self.chiama("POST", "/api/host/foto_elimina", 200, [("eliminata", bool)],
                    body={"slug": slug, "url": up["url"]}, headers=TOK,
                    valore={"eliminata": True})
        h3, _t3 = self.registra_host("invitato@ostile.it")
        self.chiama("POST", "/api/host/invito/registra", 201, [("stato", str)],
                    body={"codice": inv["codice"], "nuovo_host_id": h3}, headers=IP,
                    valore={"stato": "registrato"})
        qual = self.chiama("POST", "/api/host/invito/qualifica", 200, [("bonus_cents", int)],
                           body={"nuovo_host_id": h3}, headers=ADM)
        self.assertGreater(qual["bonus_cents"], 0, "referral qualificato senza premio")
        ap = self.chiama("POST", "/api/host/richieste/approva", 200,
                         [("stato", str), ("prenotazione", dict)],
                         body={"riferimento": rq1["riferimento"]}, headers=TOK,
                         valore={"stato": "approvata"})
        self.assertEqual(ap["prenotazione"]["stato"], "in_attesa_pagamento", ap)
        self.chiama("POST", "/api/host/richieste/rifiuta", 200, [("stato", str)],
                    body={"riferimento": rq2["riferimento"]}, headers=TOK,
                    valore={"stato": "rifiutata"})
        self.chiama("POST", "/api/host/login", 200, [("token", str), ("host_id", str)],
                    body={"email": "host@ostile.it", "password": "password1"},
                    headers=IP, valore={"ok": True, "host_id": host_id})
        self.chiama("POST", "/api/host/password_dimenticata", 200, [("ok", bool)],
                    body={"email": "host@ostile.it", "lang": "it"}, headers=IP,
                    valore={"ok": True})
        tok_reset = ""
        for _dest, _ogg, html in self.mail.inviate:
            if "#reset=" in (html or ""):
                tok_reset = html.split("#reset=")[1].split('"')[0].split("<")[0].strip()
        self.assertTrue(tok_reset, "password dimenticata: nessun magic-link nell'email")
        self.chiama("POST", "/api/host/password_reset", 200, [("token", str)],
                    body={"token": tok_reset, "password": "password3A"}, headers=IP,
                    valore={"ok": True, "host_id": host_id})
        self.chiama("POST", "/api/host/cambia_password", 200, [("token", str)],
                    body={"attuale": "password3A", "vecchia": "password3A",
                          "nuova": "password4A"}, headers=TOK, valore={"ok": True})

        # ── ADMIN: letture ───────────────────────────────────────────────────────────
        aa = self.chiama("GET", "/api/admin/alloggi", 200, [("alloggi", list)], headers=ADM)
        self.assertEqual(len(aa["alloggi"]), 4, aa)
        ap2 = self.chiama("GET", "/api/admin/prenotazioni", 200, [("prenotazioni", list)],
                          headers=ADM)
        self.assertTrue(ap2["prenotazioni"], ap2)
        sr = self.chiama("GET", "/api/admin/search", 200,
                         [("prenotazioni", list), ("host", list), ("annunci", list)],
                         query={"q": "rec@ostile.it"}, headers=ADM)
        self.assertTrue(sr["prenotazioni"], "la ricerca operativa non trova l'ospite vero")
        au = self.chiama("GET", "/api/admin/audit", 200,
                         [("tipo", str), ("prenotazione", dict), ("semaforo", dict)],
                         query={"id": rif}, headers=ADM, valore={"riferimento": rif})
        self.assertIn("complessivo", au["semaforo"], au)
        am = self.chiama("GET", "/api/admin/messaggi", 200, [("messaggi", list)],
                         query={"riferimento": rif}, headers=ADM)
        self.assertEqual(len(am["messaggi"]), 3, am)
        self.chiama("GET", "/api/admin/partner", 200,
                    [("totale", int), ("candidati", list)], headers=ADM,
                    valore={"totale": 1})
        ac = self.chiama("GET", "/api/admin/controversie", 200, [("controversie", list)],
                         headers=ADM)
        self.assertEqual(len(ac["controversie"]), 1, ac)
        self.chiama("GET", "/api/admin/diagnosi", 200, [("allarmi", list), ("misure", dict)],
                    headers=ADM)
        av = self.chiama("GET", "/api/admin/verifiche", 200, [("host", list)], headers=ADM)
        self.assertTrue(av["host"], av)
        self.chiama("GET", "/api/admin/verifiche/dettaglio", 200,
                    [("host_id", str), ("documenti", dict)],
                    query={"host_id": host_id}, headers=ADM, valore={"host_id": host_id})

        # ── BUNKER: ingresso a doppia chiave ─────────────────────────────────────────
        bl = self.chiama("POST", "/api/bunker/login", 200,
                         [("sessione", str), ("scade_tra_sec", int)],
                         body={"codice": "SuperPw@1"}, headers=ADM, valore={"ok": True})
        BK = dict(ADM, **{"X-Bunker-Session": bl["sessione"]})

        self.chiama("GET", "/api/admin/verifiche/fascicolo", 200, [("fascicolo", dict)],
                    query={"host_id": host_id}, headers=BK)
        self.chiama("POST", "/api/admin/verifica_stato", 200, [("stato", str)],
                    body={"host_id": host_id, "stato": "verificato", "nota": "ok"},
                    headers=BK, valore={"ok": True, "stato": "verificato"})
        self.chiama("POST", "/api/admin/alloggio_stato", 200, [("stato", str)],
                    body={"slug": slug_ric, "stato": "sospeso"}, headers=BK,
                    valore={"stato": "sospeso"})
        self.chiama("POST", "/api/admin/login", 200, [("_cookie", list)], body={},
                    headers=ADM, valore={"ok": True, "ruolo": "admin"})
        cr = self.chiama("POST", "/api/admin/controversia/risolvi", 200,
                         [("rimborso_cliente_cents", int), ("va_all_host_cents", int)],
                         body={"riferimento": b_cont["riferimento"],
                               "percentuale_ospite": 50, "nota": "meta' e meta'"},
                         headers=BK, valore={"stato": "risolta"})
        # CONSERVAZIONE: quel che esce dall'escrow e' ESATTAMENTE quel che c'era dentro
        in_garanzia = int(ac["controversie"][0]["importo_host_cents"])
        self.assertEqual(cr["rimborso_cliente_cents"] + cr["va_all_host_cents"],
                         in_garanzia,
                         "arbitrato: la somma spartita (%d+%d) non e' quella in garanzia (%d)"
                         % (cr["rimborso_cliente_cents"], cr["va_all_host_cents"],
                            in_garanzia))
        rec_rimb = self.sis.pagamenti_pendenti.info(b_rimb["riferimento"]) or {}
        self.chiama("POST", "/api/admin/rimborso", 200, [("stato", str)],
                    body={"alloggio_id": slug, "check_in": _g(13), "check_out": _g(14),
                          "idem_key": rec_rimb.get("idem_key")}, headers=BK,
                    valore={"stato": "rimborsato", "date_liberate": True})

        # ── BUNKER: sala di controllo ────────────────────────────────────────────────
        self.chiama("GET", "/api/bunker/stato", 200, [("bunker", bool), ("diagnosi", dict)],
                    headers=BK, valore={"bunker": True})
        el = self.chiama("GET", "/api/bunker/export_legale", 200, [("contenuto", str)],
                         headers=BK)
        self.assertIn("BookinVIP", el["contenuto"])
        sg = self.chiama("GET", "/api/bunker/scaglioni_host", 200, [("host", list)],
                         headers=BK)
        self.assertTrue(sg["host"], sg)
        pl_ = self.chiama("GET", "/api/bunker/prove_legali", 200, [("prove", list)],
                          headers=BK)
        self.assertTrue(pl_["prove"], "nessuna prova firmata nel bunker")
        self.chiama("GET", "/api/bunker/costi_tecnici", 200,
                    [("incassate", dict), ("perdite", dict)], headers=BK)
        ma = self.chiama("POST", "/api/bunker/marca_ora", 200,
                         [("impronta", str), ("giorno", str)], body={}, headers=BK,
                         valore={"ok": True, "qualificata": True})
        self.assertEqual(len(ma["impronta"]), 64, ma)
        mt = self.chiama("GET", "/api/bunker/marche_temporali", 200,
                         [("marche", list), ("totale", int)], headers=BK)
        self.assertEqual(mt["totale"], 1, "la marca appena presa non e' archiviata")
        ig = self.chiama("GET", "/api/bunker/integrita", 200,
                         [("catena", dict), ("diagnosi", dict)], headers=BK)
        self.assertTrue(ig["catena"]["ok"], "catena del giornale ROTTA")
        lg = self.chiama("GET", "/api/bunker/log", 200, [("righe", list)],
                         query={"n": "50"}, headers=BK)
        self.assertTrue(lg["righe"], lg)
        ec = self.chiama("GET", "/api/bunker/export_contabile", 200, [("csv", str)],
                         query={"anno": "2026"}, headers=BK)
        self.assertIn("importo_cents", ec["csv"])
        self.chiama("GET", "/api/bunker/riconciliazione", 200,
                    [("giorni", int), ("solo_stripe", list), ("solo_giornale", list)],
                    query={"giorni": "30"}, headers=BK, valore={"giorni": 30})
        iv = self.chiama("GET", "/api/bunker/invarianti", 200,
                         [("ok", bool), ("violazioni", dict)], headers=BK)
        self.assertTrue(iv["ok"], "l'auditor invarianti trova violazioni sul giro pulito: %r"
                        % (iv["violazioni"],))
        self.chiama("GET", "/api/bunker/guardiano", 200, [("anomalie", dict), ("conta", int)],
                    headers=BK)
        dc = self.chiama("GET", "/api/bunker/dac7_conformita", 200,
                         [("anno", int), ("host", list)], headers=BK,
                         query={"anno": "2026"}, valore={"anno": 2026})
        self.assertTrue(dc["host"], dc)
        self.chiama("GET", "/api/bunker/dac7_report", 200, [("csv", str)],
                    query={"anno": "2026"}, headers=BK)
        self.chiama("GET", "/api/bunker/blocco_globale", 200, [("attivo", bool)],
                    headers=BK, valore={"attivo": False})
        self.chiama("POST", "/api/bunker/blocco_globale", 200, [("impostato", bool)],
                    body={"attivo": False}, headers=BK,
                    valore={"attivo": False, "impostato": True})
        self.chiama("GET", "/api/bunker/cambio_valuta", 200, [("configurato", bool)],
                    headers=BK, valore={"configurato": False})
        self.chiama("POST", "/api/bunker/cambio_valuta/aggiorna", 503, [("errore", str)],
                    body=None, headers=BK, valore={"errore": "convertitore_spento"})
        self.chiama("GET", "/api/bunker/admin_accounts", 200,
                    [("account", list), ("ruoli", list)], headers=BK)
        self.chiama("POST", "/api/bunker/admin_accounts", 200, [("email", str)],
                    body={"azione": "crea", "email": "op1@bookinvip.com",
                          "password": "OpPassword@1", "ruolo": "supporto"}, headers=BK,
                    valore={"ok": True, "ruolo": "supporto"})

        # ── DISTRUTTIVE, per ultime ──────────────────────────────────────────────────
        hc = self.chiama("POST", "/api/host/cancella", 200,
                         [("rimborso_cliente_cents", int), ("penale_host_cents", int)],
                         body={"riferimento": b_hcanc["riferimento"]}, headers=TOK,
                         valore={"stato": "cancellata_host"})
        self.assertGreater(hc["penale_host_cents"], 0,
                           "l'host cancella e non paga penale")
        note = self.sis.finanza.note_per_riferimento(b_hcanc["riferimento"]) or []
        nd = next((n for n in note if n.get("tipo") == "debito"), None)
        self.assertIsNotNone(nd, "cancellazione host senza nota di debito a giornale")
        sp = self.chiama("POST", "/api/admin/storno_penale", 200,
                         [("nota_id", str), ("nc_id", str)],
                         body={"nota_id": nd["nota_id"], "motivo": "ND emessa per errore"},
                         headers=BK, valore={"nota_id": nd["nota_id"]})
        self.assertTrue(sp["nc_id"].startswith("NC-"), sp)
        gc = self.chiama("POST", "/api/concierge/cancella", 200,
                         [("rimborso_cents", int)],
                         body={"voucher_token": b_gcanc["voucher_token"]}, headers=IP,
                         valore={"stato": "cancellata", "date_liberate": True})
        self.assertGreater(gc["rimborso_cents"], 0,
                           "cancellazione flessibile 21 giorni prima senza rimborso")
        self.chiama("POST", "/api/host/alloggio_elimina", 200, [("stato", str)],
                    body={"slug": slug_vuoto}, headers=TOK,
                    valore={"stato": "eliminato", "slug": slug_vuoto})
        ca = self.chiama("POST", "/api/admin/cancella_attivita", 200,
                         [("cancellati", dict), ("residui", dict)],
                         body={"host_id": host_pulito}, headers=BK,
                         valore={"host_id": host_pulito})
        self.assertTrue(all(v == 0 for v in ca["residui"].values()), ca)
        self.chiama("POST", "/api/bunker/logout", 200, [("_cookie", list)], body={},
                    headers=BK, valore={"ok": True})

        # ── VERDETTO: la tabella copre TUTTO il router? ──────────────────────────────
        dichiarate = rotte_del_router()
        # le due wildcard vivono nel router come prefissi: le ho chiamate su slug veri
        provate = set(self.visitate)
        provate = {(m, p) for m, p in provate}
        provate |= {("GET", "/api/catalogo/"), ("GET", "/api/recensioni/")}
        provate -= {("GET", "/api/catalogo/*"), ("GET", "/api/recensioni/*")}
        mancanti = dichiarate - provate
        self.assertEqual(mancanti, set(),
                         "ROTTE DEL ROUTER MAI PROVATE DA QUESTO GIRO (copertura bucata): %s"
                         % sorted(mancanti))
        inesistenti = provate - dichiarate
        self.assertEqual(inesistenti, set(),
                         "provate rotte che il router non dichiara: %s" % sorted(inesistenti))
        self.assertEqual(len(dichiarate), 134,
                         "il router ha %d rotte: la mappa del collaudo va aggiornata"
                         % len(dichiarate))
        # nessuna 5xx inattesa: solo le due dormienti dichiarate
        brutte = {k: v for k, v in self.visitate.items()
                  if v[0] >= 400 and k not in DORMIENTI}
        self.assertEqual(brutte, {},
                         "rotte che rifiutano una richiesta LEGITTIMA: %r" % (brutte,))
        for k in DORMIENTI:
            self.assertEqual(self.visitate[k][0], 503,
                             "%s doveva essere dormiente (503): %r" % (k, self.visitate[k]))
        print("\n[rotte_ostile] provate %d rotte su %d dichiarate dal router "
              "(%d dormienti dichiarate)"
              % (len(provate), len(dichiarate), len(DORMIENTI)), file=sys.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
