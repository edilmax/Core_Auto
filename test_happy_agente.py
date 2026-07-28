# -*- coding: utf-8 -*-
"""HAPPY PATH — fetta «AGENTE»: la superficie PUBBLICA e machine-readable (13 rotte).

Mandato del fondatore (livello 1): per OGNI rotta, una richiesta VALIDA e ben formata, con
l'autenticazione giusta e i dati corretti, deve rispondere con lo stato ATTESO **e** con una
struttura coerente. Qui non basta «non e' 500»: ogni prova assicura (a) lo stato ESATTO,
(b) chiavi e TIPI del corpo, (c) un VALORE VERO (un id, un totale, un conteggio).

TABELLA DI COPERTURA (13/13 rotte della fetta, 0 escluse):

  #   rotta                                atteso  come e' verificata
  1   GET  /api/catalogo                    200    router (annuncio vero pubblicato)
  2   GET  /api/catalogo/<slug>             200    router (scheda dell'annuncio vero)
  3   GET  /api/mappa                       200    router (GeoJSON, coordinate reali)
  4   POST /api/domanda                     201    router (credito FIRMATO decodificato)
  5   GET  /api/domanda/conta               200    router (conteggio vero: 2 iscritti)
  6   GET  /api/domanda/citta               200    router (aggregato + soglia)
  7   POST /api/partner                     201    router (+ candidatura davvero archiviata)
  8   POST /api/preventivo/email            200    router (+ email davvero partita)
  9   POST /api/contratto                   200    router (PDF vero + dati dal voucher firmato)
  10  GET  /api/legale/contratto-host       200    router (versione + impronta = fase163)
  11  GET  /api/trasparenza                 200    router (matematica esatta, legata alla config)
  12  POST /api/mcp                         200    router (JSON-RPC: initialize/tools/list/call)
  13  GET  /blog · /llms.txt · /openapi.json · /.well-known/ai-plugin.json
                                            200    NON passano dal router: vivono nel livello
                                                   HTTP (`servi`), che non e' istanziabile in
                                                   isolamento (avvia thread + serve_forever).
                                                   Coperte come il livello HTTP le usa: le
                                                   funzioni PURE che producono il corpo +
                                                   la GUARDIA DI CABLAGGIO che dimostra che
                                                   quei quattro percorsi sono davvero cablati
                                                   a quelle funzioni dentro `servi`.

NESSUNA PROMESSA VUOTA: ogni percorso dichiarato in /openapi.json, in
/.well-known/ai-plugin.json e in /llms.txt viene RICHIAMATO sul router vero e deve rispondere
(mai «rotta_non_trovata»), e il flusso in 3 passi promesso agli agenti (cerca -> preventivo
firmato -> prenota) viene percorso leggendo SOLO lo spec OpenAPI.

DIFETTO VERO TROVATO E CORRETTO QUI (guardia vista ROSSA):
  POST /api/contratto scriveva «Numero ospiti: 1» su OGNI contratto, anche quando la
  prenotazione era per 3 persone. Il numero di ospiti viveva solo nel preventivo firmato e
  non veniva portato nel voucher, quindi il contratto lo ignorava e stampava il default.
  Un dato FALSO su un documento che le parti firmano (e che l'host usa per la comunicazione
  agli alloggiati). Corretto alla radice: il numero ospiti viene FIRMATO nel voucher al
  momento della conferma e il contratto lo legge da li'. Guardia:
  `test_contratto_numero_ospiti_e_quello_vero` (rossa sul codice vecchio: 1 invece di 3).
"""
import datetime
import inspect
import json
import os
import re
import shutil
import tempfile
import unittest
from html.parser import HTMLParser

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import (ai_plugin_manifest, crea_router, openapi_agent_spec, servi)

BASE = "https://bookinvip.com"
RADICE = os.path.dirname(os.path.abspath(__file__))

# Elementi HTML senza tag di chiusura: non entrano nel bilanciamento.
_VUOTI = {"meta", "link", "br", "img", "hr", "input", "source", "col", "area",
          "base", "embed", "param", "track", "wbr"}


class _Bilanciatore(HTMLParser):
    """Controllo di buona formazione: ogni tag aperto viene chiuso, nell'ordine giusto."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pila = []
        self.errori = []
        self.tag = set()

    def handle_starttag(self, tag, attrs):
        self.tag.add(tag)
        if tag not in _VUOTI:
            self.pila.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.tag.add(tag)

    def handle_endtag(self, tag):
        if tag in _VUOTI:
            return
        if not self.pila:
            self.errori.append("</%s> senza apertura" % tag)
        elif self.pila[-1] != tag:
            self.errori.append("</%s> mentre era aperto <%s>" % (tag, self.pila[-1]))
        else:
            self.pila.pop()


def _controlla_html(testo):
    """Ritorna (errori, tag_visti). Errori vuoti + pila vuota = HTML ben formato."""
    p = _Bilanciatore()
    p.feed(testo)
    p.close()
    err = list(p.errori)
    if p.pila:
        err.append("tag mai chiusi: %r" % (p.pila,))
    return err, p.tag


class _Posta:
    """Provider email finto: registra e non tocca la rete."""

    def __init__(self):
        self.inviate = []

    def invia(self, dest, oggetto, html):
        self.inviate.append((dest, oggetto, html))
        return True


class _Ambiente(unittest.TestCase):
    """Sistema vero su file temporanei + router vero. Nessuna rete, nessun Stripe."""

    COMMISSIONE_BPS = 1000

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="happy_agente_")
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"A" * 32, con_registrazione_host=True,
            db_catalogo=self.d + "/c.db", db_inventario=self.d + "/i.db",
            db_registro_host=self.d + "/r.db", db_accettazioni=self.d + "/a.db",
            db_pendenti=self.d + "/p.db", db_domanda=self.d + "/dom.db",
            db_partner=self.d + "/par.db", db_payout=self.d + "/po.db",
            db_garanzia=self.d + "/g.db",
            commissione_bps=self.COMMISSIONE_BPS, psp_bps=300))
        self.posta = _Posta()
        self.sis.email_provider = self.posta
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak", base_url=BASE)
        oggi = datetime.date.today()
        self.oggi = oggi
        self.ci = (oggi + datetime.timedelta(days=5)).isoformat()
        self.co = (oggi + datetime.timedelta(days=7)).isoformat()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def g(self, metodo, path, query=None, body=None, headers=None):
        return self.r.gestisci(metodo, path, query or {},
                               json.dumps(body) if body is not None else None,
                               headers or {})

    def pubblica(self, slug="casa-agente", citta="Roma", prezzo=20000, unita=2):
        """Un annuncio VERO, pubblicato e con le date aperte (come lo farebbe un host)."""
        st, corpo = self.g("POST", "/api/host/pubblica", None, {
            "host_id": "host-agente", "slug": slug, "titolo": "Attico Agente",
            "citta": citta, "paese": "IT", "cin": "IT058091C2X5V0ABCD",
            "descrizione": "Attico con vista, due camere.",
            "prezzo_notte_cents": prezzo, "capacita": 4,
            "lat_micro": 41902782, "lon_micro": 12496366,
            "servizi": ["wifi"], "immagini": []}, {"X-Host-Key": "hk"})
        self.assertEqual(st, 201, corpo)
        st, corpo = self.g("POST", "/api/host/disponibilita_range", None, {
            "alloggio_id": slug, "da": self.oggi.isoformat(),
            "a": (self.oggi + datetime.timedelta(days=30)).isoformat(),
            "unita_totali": unita, "prezzo_netto_cents": prezzo}, {"X-Host-Key": "hk"})
        self.assertEqual(st, 200, corpo)
        return slug

    def prenota(self, slug="casa-agente", party=3):
        """Percorso ospite completo -> voucher FIRMATO (serve al contratto)."""
        st, q = self.g("POST", "/api/concierge/quote", None,
                       {"alloggio_id": slug, "check_in": self.ci,
                        "check_out": self.co, "party": party})
        self.assertEqual(st, 200, q)
        st, b = self.g("POST", "/api/concierge/book", None,
                       {"quote_token": q["quote_token"], "email": "ospite@example.com",
                        "lang": "it"})
        self.assertEqual(st, 201, b)
        return b


# ═══════════════════════════════════════════════════════════════════════════════
# 1-3 · VETRINA PUBBLICA: catalogo, dettaglio, mappa
# ═══════════════════════════════════════════════════════════════════════════════
class TestVetrinaPubblica(_Ambiente):

    def test_catalogo_elenca_lannuncio_vero(self):
        self.pubblica()
        st, c = self.g("GET", "/api/catalogo", {"lang": "it"})
        self.assertEqual(st, 200)
        self.assertEqual(sorted(k for k in ("totale", "risultati", "lingua", "ordine")
                                if k in c),
                         ["lingua", "ordine", "risultati", "totale"], c)
        self.assertIsInstance(c["totale"], int)
        self.assertIsInstance(c["risultati"], list)
        self.assertEqual(c["totale"], 1)
        self.assertEqual(c["lingua"], "it")
        scheda = c["risultati"][0]
        self.assertEqual(scheda["slug"], "casa-agente")
        self.assertEqual(scheda["titolo"], "Attico Agente")
        self.assertEqual(scheda["citta"], "Roma")
        self.assertEqual(scheda["prezzo_notte_cents"], 20000)     # valore VERO, intero
        self.assertIsInstance(scheda["prezzo_notte_cents"], int)
        self.assertEqual(scheda["valuta"], "EUR")
        self.assertEqual(scheda["capacita"], 4)
        self.assertIsInstance(scheda["cancellazione_gratuita"], bool)

    def test_catalogo_filtro_citta_vero(self):
        self.pubblica()
        st, dentro = self.g("GET", "/api/catalogo", {"citta": "Roma"})
        self.assertEqual((st, dentro["totale"]), (200, 1))
        st, fuori = self.g("GET", "/api/catalogo", {"citta": "Oslo"})
        self.assertEqual(st, 200)
        self.assertEqual(fuori["totale"], 0)
        self.assertEqual(fuori["risultati"], [])

    def test_dettaglio_slug(self):
        slug = self.pubblica()
        st, d = self.g("GET", "/api/catalogo/" + slug, {"lang": "it"})
        self.assertEqual(st, 200)
        for k in ("slug", "titolo", "citta", "prezzo_notte_cents", "valuta",
                  "capacita", "servizi", "descrizione"):
            self.assertIn(k, d, k)
        self.assertEqual(d["slug"], slug)
        self.assertEqual(d["prezzo_notte_cents"], 20000)
        self.assertEqual(d["descrizione"], "Attico con vista, due camere.")
        self.assertEqual(d["servizi"], ["wifi"])

    def test_mappa_geojson_con_coordinate_vere(self):
        self.pubblica()
        st, m = self.g("GET", "/api/mappa")
        self.assertEqual(st, 200)
        self.assertEqual(m["type"], "FeatureCollection")
        self.assertEqual(m["con_coordinate"], 1)
        self.assertEqual(len(m["features"]), 1)
        f = m["features"][0]
        self.assertEqual(f["type"], "Feature")
        self.assertEqual(f["geometry"]["type"], "Point")
        # GeoJSON = [longitudine, latitudine], dai microgradi INTERI dell'annuncio
        self.assertEqual(f["geometry"]["coordinates"], [12.496366, 41.902782])
        p = f["properties"]
        self.assertEqual(p["slug"], "casa-agente")
        self.assertEqual(p["titolo"], "Attico Agente")
        self.assertEqual(p["prezzo_cents"], 20000)
        self.assertEqual(p["valuta"], "EUR")

    def test_mappa_scarta_annunci_senza_coordinate(self):
        # annuncio SENZA lat/lon: resta nel catalogo ma non puo' avere un pin
        st, corpo = self.g("POST", "/api/host/pubblica", None, {
            "host_id": "host-agente", "slug": "senza-geo", "titolo": "Senza geo",
            "citta": "Roma", "paese": "IT", "cin": "IT058091C2X5V0ABCD",
            "prezzo_notte_cents": 9000, "capacita": 2}, {"X-Host-Key": "hk"})
        self.assertEqual(st, 201, corpo)
        st, m = self.g("GET", "/api/mappa")
        self.assertEqual(st, 200)
        self.assertEqual(m["con_coordinate"], 0)
        self.assertEqual(m["features"], [])


# ═══════════════════════════════════════════════════════════════════════════════
# 4-6 · DOMANDA (lista d'attesa anti-vuoto)
# ═══════════════════════════════════════════════════════════════════════════════
class TestDomanda(_Ambiente):

    def test_post_domanda_emette_credito_firmato(self):
        from fase158_domanda import CREDITO_FONDATORE_CENTS
        st, c = self.g("POST", "/api/domanda", None,
                       {"email": "ospite@example.com", "citta": "Roma", "lang": "it"})
        self.assertEqual(st, 201)
        self.assertIs(c["ok"], True)
        self.assertEqual(c["credito_cents"], CREDITO_FONDATORE_CENTS)
        self.assertIsInstance(c["credito_cents"], int)
        self.assertIn("Roma", c["messaggio"])
        # il credito non e' una stringa qualsiasi: e' FIRMATO e si decodifica
        dati = self.sis.firma.decodifica(c["credito_token"])
        self.assertIsInstance(dati, dict)
        self.assertEqual(dati["tipo"], "credito_fondatore")
        self.assertEqual(dati["email"], "ospite@example.com")
        self.assertEqual(dati["citta"], "roma")
        self.assertEqual(dati["credito_cents"], CREDITO_FONDATORE_CENTS)
        self.assertEqual(dati["valuta"], "EUR")

    def test_conta_e_il_numero_vero(self):
        for em in ("uno@example.com", "due@example.com"):
            st, _ = self.g("POST", "/api/domanda", None, {"email": em, "citta": "Roma"})
            self.assertEqual(st, 201)
        self.g("POST", "/api/domanda", None, {"email": "tre@example.com", "citta": "Milano"})
        st, tot = self.g("GET", "/api/domanda/conta")
        self.assertEqual(st, 200)
        self.assertEqual(tot, {"citta": "", "richieste": 3})
        st, roma = self.g("GET", "/api/domanda/conta", {"citta": "Roma"})
        self.assertEqual(st, 200)
        self.assertEqual(roma, {"citta": "Roma", "richieste": 2})

    def test_domanda_per_citta_aggregata(self):
        for em in ("uno@example.com", "due@example.com"):
            self.g("POST", "/api/domanda", None, {"email": em, "citta": "Roma"})
        self.g("POST", "/api/domanda", None, {"email": "tre@example.com", "citta": "Milano"})
        st, m = self.g("GET", "/api/domanda/citta", {"limit": "10"})
        self.assertEqual(st, 200)
        self.assertIsInstance(m["soglia"], int)
        self.assertGreater(m["soglia"], 0)
        self.assertIsInstance(m["citta"], list)
        per_citta = {r["citta"]: r for r in m["citta"]}
        self.assertEqual(per_citta["roma"]["richieste"], 2)       # la piu' richiesta, in cima
        self.assertEqual(m["citta"][0]["citta"], "roma")
        self.assertEqual(per_citta["milano"]["richieste"], 1)
        self.assertIs(per_citta["roma"]["oltre_soglia"], False)   # 2 < soglia(5)
        # nessun dato personale nell'aggregato pubblico
        self.assertNotIn("email", json.dumps(m))


# ═══════════════════════════════════════════════════════════════════════════════
# 7 · PARTNER
# ═══════════════════════════════════════════════════════════════════════════════
class TestPartner(_Ambiente):

    def test_candidatura_valida_archiviata(self):
        st, c = self.g("POST", "/api/partner", None,
                       {"nome": "Anna Creator", "email": "anna@example.com",
                        "tipo": "creator", "citta": "Roma",
                        "messaggio": "Blog di viaggi", "consenso": True})
        self.assertEqual((st, c), (201, {"ok": True}))
        # effetto VERO: la candidatura e' davvero negli archivi, coi campi giusti
        self.assertEqual(self.sis.partner.conta(), 1)
        riga = self.sis.partner.candidati()[0]
        self.assertEqual(riga["email"], "anna@example.com")
        self.assertEqual(riga["tipo"], "creator")
        self.assertEqual(riga["citta"], "Roma")


# ═══════════════════════════════════════════════════════════════════════════════
# 8 · PREVENTIVO VIA EMAIL
# ═══════════════════════════════════════════════════════════════════════════════
class TestPreventivoEmail(_Ambiente):

    def test_preventivo_email_parte_davvero(self):
        self.pubblica()
        st, c = self.g("POST", "/api/preventivo/email", None,
                       {"email": "ospite@example.com", "alloggio_id": "casa-agente",
                        "check_in": self.ci, "check_out": self.co, "party": 2,
                        "lang": "it"})
        self.assertEqual((st, c), (200, {"stato": "inviata"}))
        # effetto VERO: UNA email, al destinatario giusto, col totale ricalcolato dal server
        self.assertEqual(len(self.posta.inviate), 1)
        dest, oggetto, html = self.posta.inviate[0]
        self.assertEqual(dest, "ospite@example.com")
        self.assertIn("Attico Agente", oggetto + html)
        self.assertIn("400.00", html)          # 2 notti x 200.00 EUR, dal motore
        self.assertIn(self.ci, html)
        self.assertIn(self.co, html)


# ═══════════════════════════════════════════════════════════════════════════════
# 9 · CONTRATTO DI LOCAZIONE (dal voucher FIRMATO)
# ═══════════════════════════════════════════════════════════════════════════════
class TestContratto(_Ambiente):

    def test_contratto_pdf_dal_voucher(self):
        self.pubblica()
        pren = self.prenota(party=3)
        st, c = self.g("POST", "/api/contratto", None,
                       {"voucher_token": pren["voucher_token"], "lingua": "it"})
        self.assertEqual(st, 200)
        self.assertIsInstance(c["righe"], list)
        self.assertIsInstance(c["pdf_base64"], str)
        self.assertEqual(c["filename"], "contratto_%s.pdf" % pren["riferimento"])
        import base64
        pdf = base64.b64decode(c["pdf_base64"])
        self.assertTrue(pdf.startswith(b"%PDF-"), "non e' un PDF vero")
        self.assertGreater(len(pdf), 400)
        testo = "\n".join(c["righe"])
        # i dati vengono dal preventivo FIRMATO: prezzo e date non sono manomettibili
        self.assertIn("Attico Agente", testo)
        self.assertIn("400.00 EUR", testo)
        self.assertIn(self.ci, testo)
        self.assertIn(self.co, testo)
        self.assertIn(pren["riferimento"], testo)

    def test_contratto_numero_ospiti_e_quello_vero(self):
        """GUARDIA (vista ROSSA): il contratto scriveva sempre «Numero ospiti: 1», anche per
        una prenotazione da 3 persone — un dato falso su un documento che le parti firmano."""
        self.pubblica()
        pren = self.prenota(party=3)
        st, c = self.g("POST", "/api/contratto", None,
                       {"voucher_token": pren["voucher_token"], "lingua": "it"})
        self.assertEqual(st, 200)
        righe = [r for r in c["righe"] if "ospiti" in r.lower()]
        self.assertEqual(righe, ["Numero ospiti: 3"],
                         "il contratto deve dichiarare gli ospiti VERI del preventivo firmato")

    def test_contratto_inglese_numero_ospiti(self):
        self.pubblica()
        pren = self.prenota(party=2)
        st, c = self.g("POST", "/api/contratto", None,
                       {"voucher_token": pren["voucher_token"], "lingua": "en"})
        self.assertEqual(st, 200)
        self.assertIn("Number of guests: 2", "\n".join(c["righe"]))


# ═══════════════════════════════════════════════════════════════════════════════
# 10-11 · CONTRATTO HOST (testo vivo) e TRASPARENZA
# ═══════════════════════════════════════════════════════════════════════════════
class TestLegaleETrasparenza(_Ambiente):

    def test_contratto_host_versione_e_impronta(self):
        from fase163_accettazioni import (CONTRATTO_HOST_VERSIONE, DOCUMENTO_HOST,
                                          doc_sha256)
        st, c = self.g("GET", "/api/legale/contratto-host", {"lang": "en"})
        self.assertEqual(st, 200)
        self.assertEqual(c["documento"], DOCUMENTO_HOST)
        self.assertEqual(c["versione"], CONTRATTO_HOST_VERSIONE)
        self.assertEqual(c["doc_sha256"], doc_sha256())          # l'impronta che si firma
        self.assertEqual(c["lang"], "en")
        self.assertEqual(c["lingua_che_fa_fede"], "it")
        self.assertIsInstance(c["lingue"], list)
        self.assertIn("it", c["lingue"])
        self.assertGreater(len(c["testo"]), 500)

    def test_trasparenza_matematica_esatta(self):
        st, t = self.g("GET", "/api/trasparenza",
                       {"prezzo_cents": "100000", "ota": "booking"})
        self.assertEqual(st, 200)
        self.assertEqual(t["money_unit"], "cents_integer")
        self.assertEqual(t["prezzo_riferimento_cents"], 100000)
        nostro, ota = t["scenario_nostro"], t["scenario_ota"]
        # la NOSTRA commissione mostrata e' quella VERA della config, non un 10% scritto a mano
        self.assertEqual(nostro["commissione_cents"],
                         100000 * self.sis.config.commissione_bps // 10000)
        self.assertEqual(nostro["host_netto_cents"],
                         nostro["imponibile_cents"] - nostro["commissione_cents"]
                         - nostro["psp_cents"])
        self.assertEqual(ota["host_netto_cents"], 100000 - ota["commissione_cents"])
        self.assertGreater(ota["commissione_cents"], nostro["commissione_cents"])
        self.assertEqual(t["guadagno_extra_host_cents"],
                         nostro["host_netto_cents"] - ota["host_netto_cents"])
        for v in (nostro["commissione_cents"], ota["commissione_cents"],
                  t["guadagno_extra_host_cents"]):
            self.assertIsInstance(v, int)

    def test_trasparenza_segue_la_commissione_configurata(self):
        """Il numero mostrato all'host DEVE seguire il motore che addebita: con l'8% deve
        dire 8%, non il 10% del caso tipico."""
        d2 = tempfile.mkdtemp(prefix="happy_agente_bps_")
        try:
            sis2 = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=b"B" * 32,
                                              db_payout=d2 + "/po.db", commissione_bps=800))
            r2 = crea_router(sis2, host_key="hk", admin_key="ak", base_url=BASE)
            st, t = r2.gestisci("GET", "/api/trasparenza",
                                {"prezzo_cents": "100000", "ota": "booking"}, None, {})
            self.assertEqual(st, 200)
            self.assertEqual(t["scenario_nostro"]["commissione_cents"], 8000)
        finally:
            shutil.rmtree(d2, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 12 · MCP (JSON-RPC 2.0 per gli agenti IA)
# ═══════════════════════════════════════════════════════════════════════════════
class TestMCP(_Ambiente):

    def rpc(self, metodo, params=None, mid=1):
        corpo = {"jsonrpc": "2.0", "id": mid, "method": metodo}
        if params is not None:
            corpo["params"] = params
        return self.g("POST", "/api/mcp", None, corpo)

    def test_initialize(self):
        from fase60_mcp_server import MCP_PROTOCOL_VERSION, SERVER_NAME
        st, c = self.rpc("initialize")
        self.assertEqual(st, 200)
        self.assertEqual(c["jsonrpc"], "2.0")
        self.assertEqual(c["id"], 1)
        res = c["result"]
        self.assertEqual(res["protocolVersion"], MCP_PROTOCOL_VERSION)
        self.assertEqual(res["serverInfo"]["name"], SERVER_NAME)
        self.assertIn("tools", res["capabilities"])
        self.assertEqual(res["_concierge"]["money_unit"], "cents_integer")

    def test_tools_list_auto_descritti(self):
        st, c = self.rpc("tools/list", mid=2)
        self.assertEqual(st, 200)
        strumenti = c["result"]["tools"]
        nomi = [t["name"] for t in strumenti]
        for atteso in ("cerca_alloggi", "ottieni_preventivo", "prenota",
                       "dettaglio_alloggio", "lingue", "confronto_ota"):
            self.assertIn(atteso, nomi)
        for t in strumenti:                       # ogni tool si auto-descrive per l'agente
            self.assertTrue(t["description"].strip())
            self.assertEqual(t["inputSchema"]["type"], "object")

    def test_tools_call_cerca_alloggi_vede_lannuncio(self):
        self.pubblica()
        st, c = self.rpc("tools/call", {"name": "cerca_alloggi",
                                        "arguments": {"citta": "Roma"}}, mid=3)
        self.assertEqual(st, 200)
        res = c["result"]
        self.assertIs(res["isError"], False)
        dati = res["structuredContent"]
        self.assertEqual(dati["money_unit"], "cents_integer")
        self.assertEqual(dati["totale"], 1)
        self.assertEqual(dati["risultati"][0]["slug"], "casa-agente")
        # `content` testuale e `structuredContent` devono dire la STESSA cosa
        self.assertEqual(json.loads(res["content"][0]["text"]), dati)

    def test_tools_call_preventivo_firmato(self):
        self.pubblica()
        st, c = self.rpc("tools/call", {"name": "ottieni_preventivo",
                                        "arguments": {"alloggio_id": "casa-agente",
                                                      "check_in": self.ci,
                                                      "check_out": self.co,
                                                      "party": 2}}, mid=4)
        self.assertEqual(st, 200)
        q = c["result"]["structuredContent"]
        self.assertIs(c["result"]["isError"], False)
        self.assertEqual(q["prezzo_guest_cents"], 40000)
        self.assertEqual(q["party"], 2)
        # il prezzo e' FIRMATO dal core: il token si verifica e contiene lo stesso importo
        firmato = self.sis.firma.decodifica(q["quote_token"])
        self.assertEqual(firmato["prezzo_guest_cents"], 40000)


# ═══════════════════════════════════════════════════════════════════════════════
# 13 · SUPERFICIE DI SCOPERTA: openapi.json · ai-plugin.json · llms.txt
#      (+ NESSUNA PROMESSA VUOTA: cio' che e' dichiarato deve rispondere davvero)
# ═══════════════════════════════════════════════════════════════════════════════
class TestSuperficieAgente(_Ambiente):

    def _risponde(self, metodo, path, body=None):
        st, corpo = self.g(metodo, path, None, body)
        return st, corpo

    def test_openapi_ogni_percorso_dichiarato_risponde(self):
        spec = openapi_agent_spec(BASE)
        self.assertTrue(str(spec["openapi"]).startswith("3.0"))
        self.assertEqual(spec["servers"][0]["url"], BASE)
        self.assertTrue(spec["paths"], "spec senza rotte")
        for path, per_metodo in spec["paths"].items():
            for metodo in per_metodo:
                st, corpo = self._risponde(metodo.upper(), path, {} if metodo == "post" else None)
                self.assertNotEqual(
                    corpo.get("errore"), "rotta_non_trovata",
                    "PROMESSA VUOTA: openapi dichiara %s %s ma il router non la conosce"
                    % (metodo.upper(), path))
                self.assertLess(st, 500, "%s %s -> %s" % (metodo.upper(), path, st))

    def test_openapi_flusso_agente_percorso_davvero(self):
        """Un agente che legge SOLO lo spec deve arrivare in fondo: cerca -> quote -> prenota."""
        self.pubblica()
        spec = openapi_agent_spec(BASE)
        per_operazione = {}
        for path, per_metodo in spec["paths"].items():
            for metodo, op in per_metodo.items():
                per_operazione[op["operationId"]] = (metodo.upper(), path)

        m, p = per_operazione["cercaAlloggi"]
        st, cat = self._risponde(m, p)
        self.assertEqual((m, st), ("GET", 200))
        slug = cat["risultati"][0]["slug"]

        m, p = per_operazione["preventivo"]
        st, q = self._risponde(m, p, {"alloggio_id": slug, "check_in": self.ci,
                                      "check_out": self.co, "party": 2})
        self.assertEqual((m, st), ("POST", 200), q)
        self.assertTrue(q["quote_token"])
        self.assertEqual(q["prezzo_guest_cents"], 40000)

        m, p = per_operazione["prenota"]
        st, b = self._risponde(m, p, {"quote_token": q["quote_token"],
                                      "email": "agente@example.com"})
        self.assertEqual((m, st), ("POST", 201), b)
        self.assertEqual(b["stato"], "confermata")
        self.assertTrue(b["riferimento"])
        self.assertEqual(b["prezzo_guest_cents"], 40000)   # il prezzo firmato non e' cambiato

    def test_openapi_parametri_dichiarati_sono_veri(self):
        """I filtri promessi su /api/catalogo devono davvero filtrare (non decorazione)."""
        self.pubblica()
        spec = openapi_agent_spec(BASE)
        nomi = {p["name"] for p in spec["paths"]["/api/catalogo"]["get"]["parameters"]}
        for atteso in ("citta", "check_in", "check_out", "prezzo_max_cents", "lang"):
            self.assertIn(atteso, nomi)
        st, sotto = self.g("GET", "/api/catalogo", {"prezzo_max_cents": "10000"})
        self.assertEqual((st, sotto["totale"]), (200, 0))     # 200.00 > 100.00 -> escluso
        st, sopra = self.g("GET", "/api/catalogo", {"prezzo_max_cents": "30000"})
        self.assertEqual((st, sopra["totale"]), (200, 1))

    def test_ai_plugin_manifest_punta_a_cose_vive(self):
        m = ai_plugin_manifest(BASE)
        self.assertEqual(m["schema_version"], "v1")
        self.assertEqual(m["name_for_model"], "bookinvip")
        self.assertEqual(m["auth"]["type"], "none")
        self.assertEqual(m["api"], {"type": "openapi", "url": BASE + "/openapi.json"})
        self.assertEqual(m["mcp"], {"type": "jsonrpc", "url": BASE + "/api/mcp"})
        json.dumps(m)
        # l'endpoint MCP promesso risponde JSON-RPC per davvero
        st, c = self.g("POST", "/api/mcp", None,
                       {"jsonrpc": "2.0", "id": 9, "method": "ping"})
        self.assertEqual((st, c), (200, {"jsonrpc": "2.0", "id": 9, "result": {}}))
        # e /openapi.json e' servito dal livello HTTP (guardia di cablaggio piu' sotto)
        self.assertIn("/openapi.json", inspect.getsource(servi))

    def test_llms_txt_non_promette_rotte_inesistenti(self):
        from fase97_inbound_seo import llms_txt
        testo = llms_txt(BASE, commissione_bps=1000)
        self.assertTrue(testo.startswith("# BookinVIP"))
        self.assertIn("10%", testo)                       # la commissione VERA che passiamo
        sorgente_http = inspect.getsource(servi)
        percorsi = set()
        for u in re.findall(r"https://bookinvip\.com[^\s]*", testo):
            p = u[len(BASE):].rstrip(".,;:)") or "/"
            percorsi.add(p)
        self.assertIn("/api/catalogo", percorsi)
        self.assertIn("/api/concierge/quote", percorsi)
        self.assertIn("/api/concierge/book", percorsi)
        self.assertIn("/api/mcp", percorsi)
        for p in sorted(percorsi):
            if p.startswith("/api/"):
                stg, cg = self.g("GET", p)
                stp, cp = self.g("POST", p, None, {})
                ignota = (cg.get("errore") == "rotta_non_trovata"
                          and cp.get("errore") == "rotta_non_trovata")
                self.assertFalse(ignota, "PROMESSA VUOTA in llms.txt: %s (GET %s, POST %s)"
                                 % (p, stg, stp))
            elif p.endswith(".html"):
                self.assertTrue(os.path.isfile(os.path.join(RADICE, "deploy", p.lstrip("/"))),
                                "llms.txt promette la pagina %s che non esiste" % p)
            elif p == "/":
                self.assertTrue(os.path.isfile(os.path.join(RADICE, "deploy", "index.html")))
            else:
                self.assertIn('"%s"' % p, sorgente_http,
                              "llms.txt promette %s ma il livello HTTP non lo serve" % p)

    def test_cablaggio_livello_http_seo_agente(self):
        """CABLAGGIO (modo di rompersi n.2): le funzioni pure esistono — ma sono davvero
        appese ai quattro percorsi che gli agenti e i crawler chiamano?"""
        sorgente = inspect.getsource(servi)
        for percorso, funzione in (('"/blog"', "genera_indice_blog"),
                                   ('"/llms.txt"', "llms_txt"),
                                   ('"/openapi.json"', "openapi_agent_spec"),
                                   ('"/.well-known/ai-plugin.json"', "ai_plugin_manifest")):
            self.assertIn(percorso, sorgente, "percorso %s non cablato" % percorso)
            self.assertIn(funzione, sorgente, "funzione %s non cablata" % funzione)
        self.assertIn("genera_articolo_html", sorgente)


# ═══════════════════════════════════════════════════════════════════════════════
# 13-bis · BLOG: le pagine SEO devono rendere HTML VALIDO (non solo "rispondere")
# ═══════════════════════════════════════════════════════════════════════════════
class TestBlogHTML(unittest.TestCase):

    def test_indice_blog_html_valido(self):
        from fase198_blog import ARTICOLI, genera_indice_blog
        pagina = genera_indice_blog(lingua="it", base_url=BASE)
        errori, tag = _controlla_html(pagina)
        self.assertEqual(errori, [], "HTML dell'indice blog malformato")
        self.assertTrue(pagina.lower().startswith("<!doctype html>"))
        for t in ("html", "head", "title", "body", "main"):
            self.assertIn(t, tag, "manca <%s>" % t)
        self.assertIn('<link rel="canonical" href="%s/blog">' % BASE, pagina)
        self.assertIn('<meta name="description"', pagina)
        # ogni articolo e' linkato dall'indice (hub crawlabile)
        for a in ARTICOLI:
            self.assertIn('href="%s/blog/%s"' % (BASE, a["slug"]), pagina)
        self.assertIn("/diventa-host.html", pagina)

    def test_articoli_html_validi_in_tutte_le_lingue(self):
        from fase198_blog import ARTICOLI, BLOG_LINGUE, genera_articolo_html
        for a in ARTICOLI:
            for lng in BLOG_LINGUE:
                pagina = genera_articolo_html(str(a["slug"]), lingua=lng, base_url=BASE)
                self.assertIsNotNone(pagina, "articolo %s/%s assente" % (a["slug"], lng))
                errori, tag = _controlla_html(pagina)
                self.assertEqual(errori, [], "HTML malformato: %s/%s -> %s"
                                 % (a["slug"], lng, errori))
                self.assertIn('<html lang="%s"' % lng, pagina)
                self.assertIn("h1", tag)
                self.assertIn("article", tag)
                atteso = BASE + "/blog/" + str(a["slug"]) + ("" if lng == "it"
                                                             else "?lang=" + lng)
                self.assertIn('<link rel="canonical" href="%s">' % atteso, pagina)

    def test_jsonld_degli_articoli_e_json_valido(self):
        from fase198_blog import genera_articolo_html
        pagina = genera_articolo_html("prenotazioni-dirette", lingua="it", base_url=BASE)
        blocchi = re.findall(r'<script type="application/ld\+json">(.*?)</script>',
                             pagina, re.S)
        self.assertEqual(len(blocchi), 2, "attesi Article + BreadcrumbList")
        tipi = []
        for b in blocchi:
            dati = json.loads(b)                       # deve essere JSON VERO
            self.assertEqual(dati["@context"], "https://schema.org")
            tipi.append(dati["@type"])
        self.assertEqual(sorted(tipi), ["Article", "BreadcrumbList"])

    def test_slug_inesistente_non_inventa_pagine(self):
        from fase198_blog import genera_articolo_html
        self.assertIsNone(genera_articolo_html("articolo-che-non-esiste",
                                               lingua="it", base_url=BASE))

    def test_sitemap_blog_elenca_solo_pagine_che_esistono(self):
        from fase198_blog import (ARTICOLI, BLOG_LINGUE, genera_articolo_html,
                                  sitemap_blog)
        xml = sitemap_blog(BASE)
        self.assertTrue(xml.startswith('<?xml version="1.0" encoding="UTF-8"?>'))
        loc = re.findall(r"<loc>(.*?)</loc>", xml)
        attesi = len(BLOG_LINGUE) * (1 + len(ARTICOLI))
        self.assertEqual(len(loc), attesi)
        for u in loc:
            self.assertTrue(u.startswith(BASE + "/blog"))
            resto = u[len(BASE + "/blog"):].split("?")[0].lstrip("/")
            if resto:                                   # e' un articolo: deve generarsi
                self.assertIsNotNone(genera_articolo_html(resto, base_url=BASE), u)


if __name__ == "__main__":
    unittest.main(verbosity=2)
