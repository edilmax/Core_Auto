# -*- coding: utf-8 -*-
"""HAPPY PATH — LE 4 ROTTE RIMASTE SCOPERTE dalle sette fette (admin/agente/altro/conti/
host/moduli/soldi). Trovate non a occhio ma STRUMENTANDO il router: `RouterHTTP.gestisci`
e' stato avvolto da una spia che ha registrato ogni (metodo, path, stato) toccato dai 229
test happy-path; il confronto con l'elenco ufficiale delle 134 rotte ha lasciato fuori
esattamente queste quattro:

    POST /api/recensioni        201   il diritto firmato al book, speso DOPO il soggiorno
    GET  /api/recensioni/<slug> 200   la vetrina pubblica che ne esce
    GET  /api/messaggi          200   il thread di una prenotazione, letto dall'host
    POST /api/marketing/campagna 200  la campagna admin-only, generata e pubblicata

Mandato (livello 1): richiesta VALIDA, autenticazione giusta, dati corretti -> stato ESATTO
atteso + chiavi/tipi coerenti + un VALORE VERO (un conteggio, una media, un testo, un id).

DETERMINISMO. Il diritto di recensione nasce col `nbf` = mezzanotte del CHECK-OUT (si
recensisce DOPO il soggiorno, mai prima). Invece di prenotare nel passato — cosa che il
motore giustamente rifiuta — si sposta l'OROLOGIO del registro recensioni oltre il
check-out: e' il parametro `orologio` che `RegistroRecensioni` espone apposta, non una
scorciatoia. Il resto e' vero: host vero, annuncio vero, preventivo vero, prenotazione
vera, webhook Stripe FIRMATO che porta il pendente a 'pagato'.

VISTE ROSSE (nessun verde vale finche' non e' stato visto rosso). Guasti iniettati a
runtime, uno per volta, e test che li hanno visti fallire:
  1. `RegistroRecensioni.invia` che ritorna sempre EsitoRecensione(False, "x")
     -> test_recensione_verificata_dopo_il_soggiorno ROSSO (400 invece di 201).
  2. `RegistroRecensioni.riepilogo` che ritorna conteggio 0
     -> test_vetrina_recensioni_pubblica ROSSO (media e conteggio a zero).
  3. `Messaggistica.thread` che ritorna [] a chiunque
     -> test_thread_messaggi_letto_dall_host ROSSO (thread vuoto).
  4. `MotoreMarketing.pubblica_piano` che salta tutto
     -> test_campagna_pubblica_sui_canali_configurati ROSSO (pubblicati 0).

Stdlib pura, zero rete (Stripe finto, email finta), archivi su file temporanei.
"""
import datetime
import json
import os
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase90_marketing import CanaleStub
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

# ORACOLO INDIPENDENTE della campagna: il contratto e' «un post per ogni TEMA in ogni
# LINGUA chiesta». I temi sono tre (host · guest · referral), quindi 3 x lingue.
# Numero scritto QUI a mano, non letto dal motore: un conteggio confrontato solo con se
# stesso (`totale == post_generati`) resta verde anche se la campagna si dimezza —
# difetto PROVATO in revisione ostile 2026-07-28 (mutante `campagna_completa()[:-1]`
# SOPRAVVISSUTO a tutte e tre le prove).
TEMI_CAMPAGNA = ("host", "guest", "referral")


def post_attesi(lingue):
    return len(TEMI_CAMPAGNA) * len(lingue)

WHSEC = "whsec_happy_lacune"
SLUG = "casa-lacune"
CIN_IT = "IT058091C2X5V0ABCD"
PREZZO_NOTTE = 12000
NOTTI = 2
PARTY = 2


def _fake_stripe_fetch(url, body, headers):
    """Checkout Session finta: nessuna rete, id deterministico per chiamata."""
    import secrets
    n = secrets.token_hex(6)
    return {"url": "https://stripe.finto/" + n, "id": "cs_" + n}


class _Posta:
    """Provider email finto: registra invece di spedire."""

    def __init__(self):
        self.inviate = []

    def invia(self, dest, oggetto, html):
        self.inviate.append((dest, oggetto, html))
        return True


class _BaseLacune(unittest.TestCase):
    """Sistema vero + router vero + host vero + annuncio pubblicato con le date aperte."""

    def setUp(self):
        self._env0 = {k: os.environ.get(k) for k in ("UPLOAD_DIR", "PAGA_STRUTTURA_ATTIVO")}
        self.d = tempfile.mkdtemp(prefix="happy_lacune_")
        os.environ["UPLOAD_DIR"] = self.d + "/uploads"
        os.environ["PAGA_STRUTTURA_ATTIVO"] = "0"
        self._fetch0 = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_stripe_fetch)

        d = self.d
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"L" * 32, con_registrazione_host=True,
            db_catalogo=d + "/c.db", db_inventario=d + "/i.db", db_registro_host=d + "/r.db",
            db_accettazioni=d + "/a.db", db_pendenti=d + "/p.db", db_payout=d + "/po.db",
            db_garanzia=d + "/g.db", db_finanza=d + "/f.db", db_messaggi=d + "/m.db",
            db_recensioni=d + "/rec.db", db_domanda=d + "/dom.db",
            commissione_bps=1000, psp_bps=300, stripe_secret_key="sk",
            stripe_webhook_secret=WHSEC, stripe_success_url="https://x/ok",
            stripe_cancel_url="https://x/ko"))
        self.posta = _Posta()
        self.sis.email_provider = self.posta
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        if getattr(self.sis, "connect", None) is not None:
            self.sis.connect.trasferisci = lambda *a, **k: "tr_finto"    # mai rete

        s, c = self.g("POST", "/api/host/registrazione", {
            "email": "host@lacune.it", "password": "password1", "accetta_termini": True,
            "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
            "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.host_id = c["host_id"]
        self.tk = {"X-Host-Token": c["token"]}
        self.admin = {"X-Admin-Key": "ak"}

        s, p = self.g("POST", "/api/host/pubblica", {
            "slug": SLUG, "titolo": "Loft delle Lacune", "citta": "Roma", "paese": "IT",
            "cin": CIN_IT, "descrizione": "Loft luminoso vicino al Colosseo",
            "prezzo_notte_cents": PREZZO_NOTTE, "capacita": 4,
            "servizi": [], "immagini": []}, self.tk)
        self.assertEqual(s, 201, p)

        oggi = datetime.date.today()
        self.ci = (oggi + datetime.timedelta(days=20)).isoformat()
        self.co = (oggi + datetime.timedelta(days=20 + NOTTI)).isoformat()
        s, disp = self.g("POST", "/api/host/disponibilita_range", {
            "alloggio_id": SLUG, "da": (oggi + datetime.timedelta(days=10)).isoformat(),
            "a": (oggi + datetime.timedelta(days=40)).isoformat(),
            "unita_totali": 3, "prezzo_netto_cents": PREZZO_NOTTE}, self.tk)
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

    def prenotazione_pagata(self, email="ospite@lacune.it"):
        """(riferimento, diritto_recensione) di una prenotazione DAVVERO pagata."""
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": SLUG, "check_in": self.ci, "check_out": self.co,
                       "party": PARTY})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": email, "lang": "it"})
        self.assertEqual(s, 201, b)
        grezzo = json.dumps({"type": "checkout.session.completed",
                             "data": {"object": {"id": "cs_lacune",
                                                 "metadata": {"riferimento":
                                                              b["riferimento"]}}}})
        firma = firma_di_test(grezzo, WHSEC, int(time.time()))
        s, w = self.r.gestisci("POST", "/api/payments/webhook", {}, grezzo,
                               {"Stripe-Signature": firma})
        self.assertEqual(s, 200, w)
        self.assertEqual(self.sis.pagamenti_pendenti.info(b["riferimento"])["stato"], "pagato")
        self.assertIsInstance(b.get("diritto_recensione"), str)
        return b["riferimento"], b["diritto_recensione"]

    def torna_a_casa(self):
        """L'ospite e' rientrato: sposta l'orologio del registro recensioni al giorno
        DOPO il check-out (il `nbf` firmato nel diritto e' la mezzanotte del check-out)."""
        co = datetime.date.fromisoformat(self.co)
        dopo = int(time.mktime(datetime.datetime(co.year, co.month, co.day,
                                                 12, 0, 0).timetuple())) + 86400
        self.sis.recensioni._now = lambda: dopo


# ══════════════════════════════════════════════════════════════════════════════
# 1) RECENSIONI — POST /api/recensioni (201) + GET /api/recensioni/<slug> (200)
# ══════════════════════════════════════════════════════════════════════════════
class TestRecensioni(_BaseLacune):

    def test_recensione_verificata_dopo_il_soggiorno(self):
        """POST /api/recensioni -> 201: il diritto firmato al book, speso dopo il
        check-out da una prenotazione PAGATA, produce una recensione VERIFICATA."""
        rif, diritto = self.prenotazione_pagata()
        self.torna_a_casa()
        s, out = self.g("POST", "/api/recensioni", {
            "token": diritto, "voto": 5, "lingua": "it",
            "testo": "Loft pulitissimo, host presente, rifarei.",
            "categorie": {"pulizia": 5, "posizione": 4}})
        self.assertEqual(s, 201, out)
        self.assertEqual(out, {"ok": True, "motivo": "", "verificata": True})
        # EFFETTO VERO sul dato durevole: la riga esiste, e' legata a QUESTA prenotazione
        self.assertTrue(self.sis.recensioni.gia_recensita(rif))
        elenco = self.sis.recensioni.elenco(SLUG, 10)
        self.assertEqual(len(elenco), 1)
        self.assertEqual(elenco[0]["prenotazione_id"], rif)
        self.assertEqual(elenco[0]["voto"], 5)

    def test_una_sola_recensione_per_soggiorno(self):
        """La seconda volta la stessa prenotazione non passa: 409 'gia_recensita'
        (non e' un happy-path in piu': e' la prova che il 201 ha SCRITTO davvero)."""
        _rif, diritto = self.prenotazione_pagata()
        self.torna_a_casa()
        s, _ = self.g("POST", "/api/recensioni",
                      {"token": diritto, "voto": 4, "testo": "bene", "lingua": "it"})
        self.assertEqual(s, 201)
        s, out = self.g("POST", "/api/recensioni",
                        {"token": diritto, "voto": 1, "testo": "ci ripenso", "lingua": "it"})
        self.assertEqual(s, 409, out)
        self.assertEqual(out["ok"], False)
        self.assertEqual(out["motivo"], "gia_recensita")

    def test_vetrina_recensioni_pubblica(self):
        """GET /api/recensioni/<slug> -> 200: riepilogo + elenco, con la MEDIA in
        centesimi di stella e il testo taggato con la lingua d'origine."""
        rif, diritto = self.prenotazione_pagata()
        self.torna_a_casa()
        s, _ = self.g("POST", "/api/recensioni", {
            "token": diritto, "voto": 4, "lingua": "it",
            "testo": "Ottima posizione, tornero'.", "categorie": {"posizione": 5}})
        self.assertEqual(s, 201)

        s, out = self.g("GET", "/api/recensioni/" + SLUG)
        self.assertEqual(s, 200, out)
        self.assertIsInstance(out.get("riepilogo"), dict)
        self.assertIsInstance(out.get("recensioni"), list)
        rie = out["riepilogo"]
        self.assertEqual(rie["conteggio"], 1)
        self.assertEqual(rie["media_centesimi"], 400)       # 4 stelle = 400 centesimi
        self.assertEqual(rie["distribuzione"]["4"] if "4" in rie["distribuzione"]
                         else rie["distribuzione"][4], 1)
        self.assertEqual(rie["categorie"]["posizione"],
                         {"conteggio": 1, "media_centesimi": 500})
        self.assertEqual(len(out["recensioni"]), 1)
        voce = out["recensioni"][0]
        self.assertEqual(voce["prenotazione_id"], rif)
        self.assertEqual(voce["voto"], 4)
        self.assertEqual(voce["testo"], {"text": "Ottima posizione, tornero'.", "lang": "it"})
        self.assertEqual(voce["categorie"], {"posizione": 5})

    def test_vetrina_vuota_di_un_annuncio_senza_recensioni(self):
        """GET /api/recensioni/<slug> -> 200 anche a zero: conteggio 0 e media 0,
        mai una media inventata (guardia contro la divisione su insieme vuoto)."""
        s, out = self.g("GET", "/api/recensioni/" + SLUG)
        self.assertEqual(s, 200, out)
        self.assertEqual(out["riepilogo"]["conteggio"], 0)
        self.assertEqual(out["riepilogo"]["media_centesimi"], 0)
        self.assertEqual(out["riepilogo"]["categorie"], {})
        self.assertEqual(out["recensioni"], [])


# ══════════════════════════════════════════════════════════════════════════════
# 2) MESSAGGI — GET /api/messaggi (200)
# ══════════════════════════════════════════════════════════════════════════════
class TestThreadMessaggi(_BaseLacune):

    def test_thread_messaggi_letto_dall_host(self):
        """GET /api/messaggi?prenotazione_id=... -> 200: l'host rilegge, in ordine, le
        bolle che ha scritto lui (mittente = il suo host_id vero)."""
        s, vuoto = self.g("GET", "/api/messaggi", None, self.tk,
                          {"prenotazione_id": "REF-LACUNE-1"})
        self.assertEqual(s, 200, vuoto)
        self.assertEqual(vuoto, {"messaggi": []})

        for testo in ("Benvenuto, il check-in e' dalle 15.",
                      "Le chiavi sono nella cassetta accanto al portone."):
            s, c = self.g("POST", "/api/messaggi",
                          {"prenotazione_id": "REF-LACUNE-1", "guest_id": "ospite-1",
                           "testo": testo}, self.tk)
            self.assertEqual(s, 201, c)

        s, out = self.g("GET", "/api/messaggi", None, self.tk,
                        {"prenotazione_id": "REF-LACUNE-1"})
        self.assertEqual(s, 200, out)
        msgs = out["messaggi"]
        self.assertIsInstance(msgs, list)
        self.assertEqual(len(msgs), 2)
        for m in msgs:
            self.assertEqual(set(m), {"mittente", "testo", "ts"})
            self.assertEqual(m["mittente"], self.host_id)
        self.assertEqual([m["testo"] for m in msgs],
                         ["Benvenuto, il check-in e' dalle 15.",
                          "Le chiavi sono nella cassetta accanto al portone."])

    def test_thread_di_un_altra_prenotazione_non_si_mescola(self):
        """Due prenotazioni, due thread: GET /api/messaggi ne torna UNO solo (la
        prova che il filtro per prenotazione_id esiste davvero)."""
        for rif, testo in (("REF-A", "messaggio della A"), ("REF-B", "messaggio della B")):
            s, c = self.g("POST", "/api/messaggi",
                          {"prenotazione_id": rif, "guest_id": "ospite-" + rif,
                           "testo": testo}, self.tk)
            self.assertEqual(s, 201, c)
        s, out = self.g("GET", "/api/messaggi", None, self.tk, {"prenotazione_id": "REF-A"})
        self.assertEqual(s, 200, out)
        self.assertEqual([m["testo"] for m in out["messaggi"]], ["messaggio della A"])


# ══════════════════════════════════════════════════════════════════════════════
# 3) MARKETING — POST /api/marketing/campagna (200)
# ══════════════════════════════════════════════════════════════════════════════
class TestCampagnaMarketing(_BaseLacune):

    def test_campagna_senza_canali_configurati(self):
        """POST /api/marketing/campagna -> 200: senza token social NESSUN canale e'
        configurato, quindi la campagna si genera ma NON tocca la rete: tutto saltato."""
        s, rep = self.g("POST", "/api/marketing/campagna", {"lingue": ["it", "en"]}, self.admin)
        self.assertEqual(s, 200, rep)
        for k in ("totale", "pubblicati", "saltati", "post_generati"):
            self.assertIsInstance(rep.get(k), int, k)
            self.assertNotIsInstance(rep.get(k), bool, k)
        self.assertIsInstance(rep.get("per_canale"), dict)
        self.assertIsInstance(rep.get("canali_configurati"), list)
        self.assertEqual(rep["canali_configurati"], [])      # nessun token -> nessun canale
        # NUMERO ASSOLUTO dall'oracolo (3 temi x 2 lingue = 6): un conteggio confrontato
        # solo con se stesso non vedrebbe una campagna dimezzata.
        self.assertEqual(rep["post_generati"], post_attesi(["it", "en"]))
        self.assertEqual(rep["totale"], post_attesi(["it", "en"]))
        self.assertEqual(rep["pubblicati"], 0)
        self.assertEqual(rep["saltati"], post_attesi(["it", "en"]))   # niente rete: tutto saltato
        self.assertEqual(rep["per_canale"], {})

    def test_campagna_pubblica_sui_canali_configurati(self):
        """POST /api/marketing/campagna -> 200 con un canale COLLEGATO: ogni post del
        piano arriva davvero al canale (l'anello 'motore -> canale' e' cablato)."""
        canale = CanaleStub()
        self.sis.marketing._canali = {canale.nome: canale}
        s, rep = self.g("POST", "/api/marketing/campagna", {"lingue": ["it"]}, self.admin)
        self.assertEqual(s, 200, rep)
        atteso = post_attesi(["it"])                          # 3 temi x 1 lingua = 3
        self.assertEqual(rep["canali_configurati"], ["stub"])
        self.assertEqual(rep["post_generati"], atteso)
        self.assertEqual(rep["totale"], atteso)
        self.assertEqual(rep["pubblicati"], atteso)
        self.assertEqual(rep["saltati"], 0)
        self.assertEqual(rep["per_canale"], {"stub": atteso})
        # EFFETTO VERO: i post sono nelle mani del canale, uno per TEMA, con testo e link nostri
        self.assertEqual(len(canale.pubblicati), atteso)
        self.assertEqual(sorted(p.tema for p in canale.pubblicati), sorted(TEMI_CAMPAGNA))
        for p in canale.pubblicati:
            self.assertEqual(p.lingua, "it")
            self.assertTrue(p.testo.strip())

    def test_lingue_omesse_usano_il_default(self):
        """Corpo senza 'lingue' -> 200 lo stesso: il motore usa it+en (nessun 400 su un
        campo facoltativo)."""
        canale = CanaleStub()
        self.sis.marketing._canali = {canale.nome: canale}
        s, rep = self.g("POST", "/api/marketing/campagna", {}, self.admin)
        self.assertEqual(s, 200, rep)
        atteso = post_attesi(["it", "en"])                    # 3 temi x 2 lingue = 6
        self.assertEqual(rep["totale"], atteso)
        self.assertEqual(rep["pubblicati"], atteso)
        self.assertEqual({p.lingua for p in canale.pubblicati}, {"it", "en"})
        # ogni lingua riceve TUTTI i temi: 3 e 3, non 3 e 2
        for lingua in ("it", "en"):
            self.assertEqual(sorted(p.tema for p in canale.pubblicati if p.lingua == lingua),
                             sorted(TEMI_CAMPAGNA), lingua)


if __name__ == "__main__":
    unittest.main(verbosity=2)
