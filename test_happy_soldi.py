# -*- coding: utf-8 -*-
"""HAPPY PATH — FETTA «SOLDI»: le 20 rotte del percorso ospite/denaro camminate come le
cammina un ospite VERO, con asserzioni sui VALORI (non solo «non e' 500»).

Il cammino reale, un anello per volta, con l'effetto verificato a ogni passo:

    host pubblica + apre le date
      -> POST /api/concierge/quote      preventivo FIRMATO, totale al centesimo
      -> POST /api/concierge/book       riferimento + voucher + payment_url
      -> (voucher PRE-pagamento: NIENTE PIN)
      -> POST /api/payments/webhook     firma Stripe valida -> pendente 'pagato'
      -> (voucher POST-pagamento: PIN presente)
      -> POST /api/checkin/pre_registra + GET /api/checkin/stato
      -> GET  /api/garanzia/stato       escrow 'in_garanzia' = netto host esatto
      -> POST /api/garanzia/conferma    escrow 'rilasciato' col netto host esatto

Rotte coperte (20) e stato atteso:
  POST /api/concierge/quote        200 | POST /api/concierge/book        201
  POST /api/concierge/cancella     200 | GET  /api/concierge/manifest    200
  GET  /api/garanzia/stato         200 | POST /api/garanzia/conferma     200
  POST /api/garanzia/contesta      200 | POST /api/voucher/messaggio     201
  GET  /api/voucher/messaggi       200 | POST /api/voucher/prova         201
  POST /api/checkin/pre_registra   200 | GET  /api/checkin/stato         200
  GET  /api/tassa                  200 | POST /api/split/preview         200
  POST /api/split/crea             201 | POST /api/split/paga            200
  GET  /api/split/stato            200 | POST /api/payments/webhook      200
  POST /api/host/carta_link        200 | GET  /api/host/carta_stato      200

CONTI ATTESI (annuncio 200,00 EUR/notte, 2 notti, 2 ospiti, tassa 3,00 pp/notte;
commissione marketplace 10%, tariffa tecnica a carico HOST letta dal motore):
    soggiorno  40000  |  tassa 1200  |  TOTALE OSPITE 41200
    commissione 4000  |  tariffa tecnica = percentuale del totale + quota fissa
    invariante: totale == netto_host + commissione + costo_carta + tassa

Coperto anche il CREDITO (token firmato, non e' una rotta a se': viaggia dentro
quote/book): sconta la NOSTRA commissione, mai il netto host, ed e' single-use.

VISTE ROSSE (regola aurea: nessun verde vale finche' non e' stato visto rosso).
Guasti iniettati nel motore, uno per volta, e test che li hanno visti fallire:
  1. fase83 `_checkin_pre_registra`: guardia pagamento neutralizzata (`if False and ...`)
     -> test_checkin_bloccato_prima_del_pagamento ROSSO (200 invece di 409).
  2. fase83 `pagina_voucher_html`: `_pagato = True` forzato
     -> test_pin_solo_dopo_il_pagamento ROSSO (PIN visibile pre-pagamento).
  3. fase83 `_conferma_pagamento`: CAS `pp.conferma(rif)` degradato a `pp.info(rif)`
     -> test_webhook_firmato_porta_a_pagato ROSSO (stato resta 'in_attesa').
  4. fase160 `EscrowGaranzia.conferma_ospite` che non muta lo stato
     -> test_garanzia_conferma_rilascia_il_netto_host ROSSO (nessun rilascio).
  5. fase65 `riparti_equo` con `base+1` a TUTTI
     -> test_split_crea_quote_esatte ROSSO (le quote non sommano piu' al totale).
(1-3 iniettati nel sorgente e subito ripristinati; 4-5 iniettati a runtime.)

Stdlib pura, zero rete (Stripe e email finti), DB su file temporanei, deterministico.
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
from fase83_server import crea_router, pagina_voucher_html
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WHSEC = "whsec_happy_soldi"
SLUG = "casa-soldi"
CIN_IT = "IT058091C2X5V0ABCD"

# PNG 1x1 valido (prova fotografica in chat)
PNG1 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA"
        "60e6kgAAAABJRU5ErkJggg==")

# ── i conti attesi, al centesimo (interi, mai float) ────────────────────────────
PREZZO_NOTTE = 20000
NOTTI = 2
PARTY = 2
TASSA_PP_NOTTE = 300
NETTO = PREZZO_NOTTE * NOTTI                 # 40000  soggiorno di listino
TASSA = TASSA_PP_NOTTE * NOTTI * PARTY       #  1200  tassa di soggiorno (pass-through)
TOTALE = NETTO + TASSA                       # 41200  quello che l'ospite paga DAVVERO
COMMISSIONE = 4000                           # 10% di 40000 (marketplace, a carico host)


def _dal_motore(chiave):
    """La tariffa tecnica VERA, letta dai default di `main_casavip.py`.

    Qui c'era `COSTO_CARTA = 1236  # 3% di 41200`, e il 2026-08-10 e' diventato falso:
    la produzione prende percentuale PIU' 0,25 EUR fissi. Una cifra copiata a mano in un
    file che si chiama «happy soldi» e' la piu' pericolosa di tutte, perche' e' quella
    che si guarda per sapere «quanto entra davvero». Ora viene dal motore.
    """
    import io as _io
    import re as _re
    _qui = os.path.dirname(os.path.abspath(__file__))
    with _io.open(os.path.join(_qui, "main_casavip.py"), encoding="utf-8") as f:
        _src = f.read()
    _m = _re.search(chiave + r'["\']\s*,\s*["\'](\d+)["\']', _src)
    assert _m, "main_casavip.py non dichiara piu' il default %s" % chiave
    return int(_m.group(1))


PSP_BPS = _dal_motore("PAGAMENTO_BPS")
PSP_FISSO = _dal_motore("PAGAMENTO_FISSO_CENTS")


def _tecnica(importo):
    """La tariffa tecnica su `importo`: percentuale PIU' quota fissa."""
    return (importo * PSP_BPS) // 10000 + PSP_FISSO


COSTO_CARTA = _tecnica(TOTALE)               # tariffa tecnica sul totale (a carico host)
NETTO_HOST = NETTO - COMMISSIONE - COSTO_CARTA
# ⛔ DUE FATTI DIVERSI, E VANNO TENUTI DIVERSI (decisione del fondatore, 2026-08-19:
# «la tassa passa all'host»). `NETTO_HOST` e' quello che l'host GUADAGNA dal soggiorno --
# la cifra su cui si calcolano commissione e report DAC7. `VERSATO_HOST` e' quello che gli
# BONIFICHIAMO: il suo guadagno piu' la tassa di soggiorno, che e' denaro in transito da
# girare al suo Comune. Sommarle in una voce sola dichiarerebbe al Fisco un reddito che
# l'host non ha; tenerle separate e' la ragione per cui esistono due nomi.
VERSATO_HOST = NETTO_HOST + TASSA


def _fake_stripe_fetch(url, body, headers):
    """Checkout Session finta: nessuna rete, id/url deterministici per chiamata."""
    import secrets
    return {"url": "https://stripe.finto/" + secrets.token_hex(4),
            "id": "cs_" + secrets.token_hex(8)}


def _fake_carta_fetch(metodo, url, body, headers):
    """Provider carta (fase183) finto: crea_link_carta + dettagli_da_sessione."""
    if "/checkout/sessions/" in url:
        return {"customer": "cus_finto", "setup_intent": "seti_finto"}
    if "/setup_intents/" in url:
        return {"payment_method": "pm_finto"}
    if url.endswith("/checkout/sessions"):
        return {"url": "https://stripe.finto/salva-carta", "id": "cs_setup_finto"}
    return {}


class _Posta:
    """Provider email finto: registra, non spedisce."""

    def __init__(self):
        self.inviate = []

    def invia(self, dest, oggetto, html):
        self.inviate.append((dest, oggetto, html))
        return True

    def oggetti(self):
        return [o for _d, o, _h in self.inviate]


class _BaseSoldi(unittest.TestCase):
    """Sistema vero + router vero + un annuncio pubblicato con le date aperte."""

    def setUp(self):
        self._env0 = {k: os.environ.get(k) for k in
                      ("UPLOAD_DIR", "TASSE_SOGGIORNO", "PAGA_STRUTTURA_ATTIVO")}
        self.d = tempfile.mkdtemp(prefix="happy_soldi_")
        os.environ["UPLOAD_DIR"] = self.d + "/uploads"
        os.environ["TASSE_SOGGIORNO"] = "roma=350:10:0,amsterdam=0::700"
        os.environ["PAGA_STRUTTURA_ATTIVO"] = "0"   # deterministico: vetrina in-struttura OFF
        self._fetch0 = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_stripe_fetch)

        d = self.d
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=d + "/c.db", db_inventario=d + "/i.db", db_registro_host=d + "/r.db",
            db_accettazioni=d + "/a.db", db_pendenti=d + "/p.db", db_payout=d + "/po.db",
            db_garanzia=d + "/g.db", db_finanza=d + "/f.db", db_messaggi=d + "/m.db",
            db_checkin=d + "/ck.db", db_split=d + "/sp.db", db_tassa_comunale=d + "/t.db",
            db_recensioni=d + "/rec.db", db_viral=d + "/v.db", db_domanda=d + "/dom.db",
            commissione_bps=1000, psp_bps=PSP_BPS, psp_fisso_cents=PSP_FISSO,
            stripe_secret_key="sk",
            stripe_webhook_secret=WHSEC, stripe_success_url="https://x/ok",
            stripe_cancel_url="https://x/ko"))
        self.posta = _Posta()
        self.sis.email_provider = self.posta
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        if getattr(self.sis, "connect", None) is not None:
            self.sis.connect.trasferisci = lambda *a, **k: "tr_finto"   # mai rete
        if getattr(self.sis, "carta", None) is not None:
            self.sis.carta._fetch = _fake_carta_fetch                    # mai rete

        s, c = self.g("POST", "/api/host/registrazione", {
            "email": "host@soldi.it", "password": "password1", "accetta_termini": True,
            "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
            "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.host_id = c["host_id"]
        self.tk = {"X-Host-Token": c["token"]}
        self.admin = {"X-Admin-Key": "ak"}

        s, p = self.g("POST", "/api/host/pubblica", {
            "slug": SLUG, "titolo": "Attico Soldi", "citta": "Roma", "paese": "IT",
            "cin": CIN_IT, "descrizione": "Attico con terrazza",
            "prezzo_notte_cents": PREZZO_NOTTE, "capacita": 4,
            "tassa_pp_notte_cents": TASSA_PP_NOTTE, "servizi": [], "immagini": []}, self.tk)
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

    def book(self, email="ospite@soldi.it", **extra):
        s, q = self.quote()
        self.assertEqual(s, 200, q)
        corpo = {"quote_token": q["quote_token"], "email": email, "lang": "it"}
        corpo.update(extra)
        return self.g("POST", "/api/concierge/book", corpo)

    def paga(self, riferimento, sessione="cs_pagamento"):
        """Webhook Stripe FIRMATO sul corpo grezzo (come lo manda Stripe)."""
        grezzo = json.dumps({"type": "checkout.session.completed",
                             "data": {"object": {"id": sessione,
                                                 "metadata": {"riferimento": riferimento}}}})
        firma = firma_di_test(grezzo, WHSEC, int(time.time()))
        return self.r.gestisci("POST", "/api/payments/webhook", {}, grezzo,
                               {"Stripe-Signature": firma})

    def prenotazione_pagata(self, email="ospite@soldi.it"):
        """(riferimento, voucher_token) di una prenotazione VERAMENTE pagata."""
        s, b = self.book(email=email)
        self.assertEqual(s, 201, b)
        s, w = self.paga(b["riferimento"])
        self.assertEqual(s, 200, w)
        return b["riferimento"], b["voucher_token"]

    def stato_pendente(self, rif):
        rec = self.sis.pagamenti_pendenti.info(rif)
        return (rec or {}).get("stato")

    def assertInteri(self, corpo, chiavi):
        for k in chiavi:
            self.assertIn(k, corpo, "manca la chiave '%s'" % k)
            self.assertIsInstance(corpo[k], int, "'%s' non e' un intero" % k)
            self.assertNotIsInstance(corpo[k], bool, "'%s' e' un bool" % k)


# ══════════════════════════════════════════════════════════════════════════════
# 1) IL CAMMINO: preventivo -> prenotazione -> pagamento -> voucher -> check-in -> garanzia
# ══════════════════════════════════════════════════════════════════════════════
class TestCamminoSoldi(_BaseSoldi):

    def test_quote_totale_al_centesimo(self):
        """POST /api/concierge/quote -> 200 e il conto torna, cifra per cifra."""
        s, q = self.quote()
        self.assertEqual(s, 200, q)
        self.assertInteri(q, ("prezzo_netto_cents", "commissione_cents", "prezzo_guest_cents",
                              "netto_host_cents", "costo_pagamento_cents",
                              "tassa_soggiorno_cents", "totale_cents", "notti", "party"))
        self.assertIsInstance(q["quote_token"], str)
        self.assertIn(".", q["quote_token"])            # payload.firma HMAC
        self.assertEqual(q["notti"], NOTTI)
        self.assertEqual(q["prezzo_netto_cents"], NETTO)
        self.assertEqual(q["prezzo_guest_cents"], NETTO)
        self.assertEqual(q["commissione_cents"], COMMISSIONE)
        self.assertEqual(q["costo_pagamento_cents"], COSTO_CARTA)
        self.assertEqual(q["netto_host_cents"], NETTO_HOST)
        self.assertEqual(q["tassa_soggiorno_cents"], TASSA)
        self.assertEqual(q["totale_cents"], TOTALE)
        self.assertEqual(q["valuta"], "EUR")
        self.assertEqual(q["money_unit"], "cents_integer")
        # conservazione esatta del denaro: niente si perde e niente si crea
        self.assertEqual(q["totale_cents"],
                         q["netto_host_cents"] + q["commissione_cents"]
                         + q["costo_pagamento_cents"] + q["tassa_soggiorno_cents"])

    def test_credito_fondatore_sconta_e_si_consuma(self):
        """Il CREDITO (token firmato) sconta il preventivo dalla NOSTRA commissione, mai
        dal netto dell'host, ed e' SINGLE-USE: speso una volta, non sconta piu'."""
        tok = self.sis.domanda.emette_credito_fondatore("ospite@soldi.it", "Roma")
        self.assertIsInstance(tok, str)
        s, q = self.quote(credito_token=tok)
        self.assertEqual(s, 200, q)
        self.assertEqual(q["sconto_credito_cents"], 500)
        self.assertEqual(q["prezzo_guest_cents"], NETTO - 500)      # 39500
        self.assertEqual(q["tassa_soggiorno_cents"], TASSA)
        self.assertEqual(q["totale_cents"], NETTO - 500 + TASSA)    # 40700
        self.assertEqual(q["commissione_cents"], COMMISSIONE)       # lo sconto esce da QUI
        _tec = _tecnica(NETTO - 500 + TASSA)     # tariffa tecnica sul nuovo totale
        self.assertEqual(q["costo_pagamento_cents"], _tec)
        self.assertEqual(q["netto_host_cents"], NETTO - COMMISSIONE - _tec)
        # conservazione col credito: totale == netto + comm + carta + tassa - sconto
        self.assertEqual(q["totale_cents"],
                         q["netto_host_cents"] + q["commissione_cents"]
                         + q["costo_pagamento_cents"] + q["tassa_soggiorno_cents"]
                         - q["sconto_credito_cents"])
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "ospite@soldi.it"})
        self.assertEqual(s, 201, b)
        self.assertEqual(b["totale_cents"], NETTO - 500 + TASSA)
        # SINGLE-USE: lo stesso credito su un nuovo preventivo non sconta piu' nulla
        s, q2 = self.quote(credito_token=tok)
        self.assertEqual(s, 200, q2)
        self.assertEqual(q2["sconto_credito_cents"], 0)
        self.assertEqual(q2["totale_cents"], TOTALE)

    def test_book_riferimento_e_voucher(self):
        """POST /api/concierge/book -> 201 col riferimento, il voucher firmato e il link."""
        s, b = self.book()
        self.assertEqual(s, 201, b)
        self.assertEqual(b["stato"], "in_attesa_pagamento")
        self.assertIsInstance(b["riferimento"], str)
        self.assertEqual(len(b["riferimento"]), 24)          # idem-key troncata, stabile
        self.assertIsInstance(b["voucher_token"], str)
        self.assertIn(".", b["voucher_token"])
        self.assertTrue(b["payment_url"].startswith("https://"))
        # il prezzo del book e' quello FIRMATO nel preventivo, identico al centesimo
        self.assertEqual(b["totale_cents"], TOTALE)
        self.assertEqual(b["prezzo_guest_cents"], NETTO)
        self.assertEqual(b["tassa_soggiorno_cents"], TASSA)
        self.assertEqual(b["netto_host_cents"], NETTO_HOST)
        self.assertEqual(b["commissione_cents"], COMMISSIONE)
        self.assertEqual(b["money_unit"], "cents_integer")
        # EFFETTO: nasce un pagamento pendente, ancora NON pagato
        self.assertEqual(self.stato_pendente(b["riferimento"]), "in_attesa")
        # il voucher firmato contiene il riferimento e le date vere
        v = self.sis.firma.decodifica(b["voucher_token"])
        self.assertEqual(v["tipo"], "voucher")
        self.assertEqual(v["riferimento"], b["riferimento"])
        self.assertEqual((v["check_in"], v["check_out"]), (self.ci, self.co))

    def test_webhook_firmato_porta_a_pagato(self):
        """POST /api/payments/webhook -> 200 e la prenotazione diventa 'pagato'."""
        s, b = self.book()
        self.assertEqual(s, 201, b)
        rif = b["riferimento"]
        self.assertEqual(self.stato_pendente(rif), "in_attesa")
        s, w = self.paga(rif)
        self.assertEqual(s, 200, w)
        self.assertEqual(w, {"ricevuto": True, "tipo": "checkout.session.completed"})
        self.assertEqual(self.stato_pendente(rif), "pagato")   # EFFETTO, non solo 200
        # l'ospite riceve la conferma di pagamento
        self.assertTrue(any("Pagamento" in o for o in self.posta.oggetti()),
                        "nessuna email di conferma pagamento: %r" % (self.posta.oggetti(),))

    def test_pin_solo_dopo_il_pagamento(self):
        """Il PIN di check-in (smart-pass) NON esiste sul voucher finche' non si e' pagato."""
        s, b = self.book()
        self.assertEqual(s, 201, b)
        rif, vt = b["riferimento"], b["voucher_token"]
        pin = self.sis.firma.pin_checkin(rif)
        self.assertTrue(pin)
        prima = pagina_voucher_html(self.sis, vt, "it") or ""
        self.assertNotIn(pin, prima, "PIN visibile PRIMA del pagamento")
        self.assertEqual(self.paga(rif)[0], 200)
        dopo = pagina_voucher_html(self.sis, vt, "it") or ""
        self.assertIn(pin, dopo, "PIN assente DOPO il pagamento")

    def test_checkin_bloccato_prima_del_pagamento(self):
        """POST /api/checkin/pre_registra -> 409 finche' il pagamento non e' confermato."""
        s, b = self.book()
        self.assertEqual(s, 201, b)
        s, out = self.g("POST", "/api/checkin/pre_registra", {
            "voucher_token": b["voucher_token"],
            "ospiti": [{"nome": "Mario Rossi", "documento": "AB12345"}]})
        self.assertEqual(s, 409, out)
        self.assertEqual(out, {"errore": "pagamento_non_confermato", "stato": "in_attesa"})
        self.assertFalse(self.sis.checkin.completato(b["riferimento"]))

    def test_checkin_pre_registra_e_stato(self):
        """POST /api/checkin/pre_registra -> 200 · GET /api/checkin/stato -> 200 completato."""
        rif, vt = self.prenotazione_pagata()
        s, prima = self.g("GET", "/api/checkin/stato", None, None, {"voucher_token": vt})
        self.assertEqual((s, prima), (200, {"completato": False}))
        s, out = self.g("POST", "/api/checkin/pre_registra", {
            "voucher_token": vt,
            "ospiti": [{"nome": "Mario Rossi", "documento": "AB12345"},
                       {"nome": "Lucia Bianchi", "documento": "CD67890"}]})
        self.assertEqual((s, out), (200, {"ok": True, "ospiti": 2}))
        s, dopo = self.g("GET", "/api/checkin/stato", None, None, {"voucher_token": vt})
        self.assertEqual((s, dopo), (200, {"completato": True}))

    def test_garanzia_stato_tiene_il_netto_host(self):
        """GET /api/garanzia/stato (admin) -> 200: l'escrow nasce con l'importo ESATTO da
        versare all'host -- il suo netto PIU' la tassa di soggiorno (2026-08-19)."""
        rif, _vt = self.prenotazione_pagata()
        s, st = self.g("GET", "/api/garanzia/stato", None, self.admin, {"ref": rif})
        self.assertEqual(s, 200, st)
        self.assertEqual(st["prenotazione_id"], rif)
        self.assertEqual(st["stato"], "in_garanzia")
        self.assertEqual(st["importo_host_cents"], VERSATO_HOST)
        self.assertEqual(st["host_riceve_cents"], 0)          # ancora in garanzia
        self.assertEqual(st["ospite_rimborso_cents"], 0)
        self.assertEqual(st["money_unit"], "cents_integer")
        self.assertInteri(st, ("aperto_ts", "sblocco_auto_ts"))
        self.assertGreater(st["sblocco_auto_ts"], st["aperto_ts"])

    def test_garanzia_conferma_rilascia_il_netto_host(self):
        """POST /api/garanzia/conferma -> 200: l'escrow passa a 'rilasciato', importo esatto.

        ⛔ L'importo atteso e' `VERSATO_HOST`, non `NETTO_HOST`: dal 2026-08-19 la cassaforte
        trattiene anche la **tassa di soggiorno**, perche' e' denaro dell'host in transito che
        lui deve girare al suo Comune (decisione del fondatore). Prima restava a noi, e il
        libro contabile dichiarava un debito verso il Comune che non ci compete."""
        rif, vt = self.prenotazione_pagata()
        s, out = self.g("POST", "/api/garanzia/conferma", {"voucher_token": vt})
        self.assertEqual(s, 200, out)
        self.assertEqual(out, {"ok": True, "stato": "rilasciato",
                               "host_riceve_cents": VERSATO_HOST, "ospite_rimborso_cents": 0})
        s, st = self.g("GET", "/api/garanzia/stato", None, self.admin, {"ref": rif})
        self.assertEqual((s, st["stato"]), (200, "rilasciato"))
        self.assertEqual(st["host_riceve_cents"], VERSATO_HOST)

    def test_garanzia_contesta_blocca_il_payout(self):
        """POST /api/garanzia/contesta -> 200 e il payout dell'host va 'trattenuto'."""
        rif, vt = self.prenotazione_pagata()
        self.assertEqual(self.sis.payout.stato_di(rif), "maturato")
        s, out = self.g("POST", "/api/garanzia/contesta",
                        {"voucher_token": vt, "motivo": "muffa in bagno"})
        self.assertEqual(s, 200, out)
        self.assertEqual(out, {"ok": True, "stato": "contestato",
                               "host_riceve_cents": 0, "ospite_rimborso_cents": 0})
        # EFFETTO: i soldi escono dal giro bonifici finche' l'arbitro non decide
        self.assertEqual(self.sis.payout.stato_di(rif), "trattenuto")
        s, st = self.g("GET", "/api/garanzia/stato", None, self.admin, {"ref": rif})
        self.assertEqual((s, st["stato"]), (200, "contestato"))

    def test_cancella_rimborsa_soggiorno_e_tassa(self):
        """POST /api/concierge/cancella -> 200: rimborso al centesimo e date liberate."""
        rif, vt = self.prenotazione_pagata()
        s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": vt})
        self.assertEqual(s, 200, c)
        self.assertEqual(c["stato"], "cancellata")
        self.assertEqual(c["riferimento"], rif)
        self.assertIs(c["date_liberate"], True)
        self.assertIs(c["ripensamento"], True)                 # 48h dall'acquisto, arrivo >=3gg
        self.assertEqual(c["rimborso_soggiorno_cents"], NETTO)
        self.assertEqual(c["tassa_rimborsata_cents"], TASSA)
        self.assertEqual(c["rimborso_cents"], TOTALE)          # soggiorno + tassa, tutto reso
        self.assertEqual(c["trattenuto_cents"], 0)
        self.assertEqual(c["politica"], "flessibile")
        self.assertIs(c["pagamento_mai_effettuato"], False)
        self.assertEqual(c["money_unit"], "cents_integer")
        # EFFETTO: il pendente e' invalidato e l'escrow non paga piu' l'host
        self.assertEqual(self.stato_pendente(rif), "rimborsato")
        s, st = self.g("GET", "/api/garanzia/stato", None, self.admin, {"ref": rif})
        self.assertEqual((s, st["stato"]), (200, "annullato"))
        self.assertEqual(st["host_riceve_cents"], 0)


# ══════════════════════════════════════════════════════════════════════════════
# 2) LE ALTRE ROTTE DELLA FETTA: manifest, voucher-chat, tassa, split, carta
# ══════════════════════════════════════════════════════════════════════════════
class TestRotteSoldi(_BaseSoldi):

    def test_manifest_descrive_il_flusso_vero(self):
        """GET /api/concierge/manifest -> 200: i 3 passi puntano a rotte che ESISTONO."""
        s, m = self.g("GET", "/api/concierge/manifest")
        self.assertEqual(s, 200, m)
        self.assertEqual(m["nome"], "BookinVIP Concierge")
        self.assertEqual(m["versione"], 1)
        self.assertEqual(m["mcp"], "https://bookinvip.com/api/mcp")
        # NB: la 'nota' si confronta col TIPO e col contenuto minimo, mai con se stessa
        # (prima era `"nota": m["catalogo"]["nota"]`: per quel campo il test non poteva fallire).
        self.assertEqual({k: m["catalogo"][k] for k in ("metodo", "path")},
                         {"metodo": "GET", "path": "/api/catalogo"}, m["catalogo"])
        self.assertEqual(sorted(m["catalogo"]), ["metodo", "nota", "path"], m["catalogo"])
        self.assertIsInstance(m["catalogo"]["nota"], str)
        self.assertGreater(len(m["catalogo"]["nota"].strip()), 10,
                           "la nota all'agente non puo' essere vuota: %r" % (m["catalogo"],))
        self.assertIsInstance(m["flusso"], list)
        self.assertEqual([p["passo"] for p in m["flusso"]], [1, 2, 3])
        self.assertEqual([p["path"] for p in m["flusso"]],
                         ["/api/concierge/quote", "/api/concierge/book",
                          "/api/concierge/cancella"])
        # il manifest non mente: ogni passo promesso risponde davvero
        s, _ = self.g("GET", "/api/catalogo")
        self.assertEqual(s, 200)
        for passo in m["flusso"]:
            self.assertEqual(passo["metodo"], "POST")
            st, _c = self.g("POST", passo["path"], {})
            self.assertNotEqual(st, 404, "rotta promessa dal manifest assente: %s"
                                % passo["path"])

    def test_voucher_messaggio_e_thread(self):
        """POST /api/voucher/messaggio -> 201 · GET /api/voucher/messaggi -> 200 col testo."""
        _rif, vt = self.prenotazione_pagata()
        s, out = self.g("POST", "/api/voucher/messaggio",
                        {"voucher_token": vt, "testo": "A che ora posso entrare?"})
        self.assertEqual((s, out), (201, {"stato": "inviato"}))
        s, th = self.g("GET", "/api/voucher/messaggi", None, None, {"voucher_token": vt})
        self.assertEqual(s, 200, th)
        self.assertIsInstance(th["messaggi"], list)
        self.assertEqual(len(th["messaggi"]), 1)
        self.assertEqual(th["messaggi"][0]["mittente"], "ospite")
        self.assertEqual(th["messaggi"][0]["testo"], "A che ora posso entrare?")
        self.assertIsInstance(th["messaggi"][0]["ts"], int)

    def test_voucher_prova_foto_entra_in_chat(self):
        """POST /api/voucher/prova -> 201: la foto e' salvata E la bolla e' in chat."""
        _rif, vt = self.prenotazione_pagata()
        s, out = self.g("POST", "/api/voucher/prova",
                        {"voucher_token": vt, "image_base64": PNG1})
        self.assertEqual(s, 201, out)
        self.assertEqual(out["stato"], "caricata")
        self.assertTrue(out["url"].startswith("/uploads/"), out["url"])
        self.assertTrue(out["url"].endswith(".png"), out["url"])
        # il file c'e' davvero su disco (non solo una stringa in risposta)
        self.assertTrue(os.path.isfile(os.path.join(os.environ["UPLOAD_DIR"],
                                                    out["url"].split("/")[-1])))
        # e l'arbitro lo vedra': la prova e' una bolla del thread, col link dentro
        s, th = self.g("GET", "/api/voucher/messaggi", None, None, {"voucher_token": vt})
        self.assertEqual((s, len(th["messaggi"])), (200, 1))
        self.assertIn(out["url"], th["messaggi"][0]["testo"])

    def test_tassa_di_soggiorno_calcolata(self):
        """GET /api/tassa -> 200: fissa per-persona/notte, con esenti e cap notti."""
        s, t = self.g("GET", "/api/tassa", None, None,
                      {"citta": "Roma", "notti": "2", "ospiti": "3", "esenti": "1",
                       "imponibile_cents": "40000"})
        self.assertEqual(s, 200, t)
        self.assertEqual(t["tassa_cents"], 1400)          # 350 x 2 notti x (3-1) ospiti
        self.assertEqual(t["componente_fissa_cents"], 1400)
        self.assertEqual(t["componente_percentuale_cents"], 0)
        self.assertEqual(t["notti_tassabili"], 2)
        self.assertEqual(t["ospiti_tassabili"], 2)
        self.assertEqual(t["valuta"], "EUR")
        self.assertEqual(t["money_unit"], "cents_integer")

    def test_tassa_percentuale_e_citta_ignota(self):
        """GET /api/tassa -> 200 anche in percentuale; citta' senza regola -> 0 (mai inventare)."""
        s, t = self.g("GET", "/api/tassa", None, None,
                      {"giurisdizione": "amsterdam", "notti": "2", "ospiti": "2",
                       "imponibile_cents": "40000"})
        self.assertEqual(s, 200, t)
        self.assertEqual(t["tassa_cents"], 2800)          # 7% di 40000
        self.assertEqual(t["componente_percentuale_cents"], 2800)
        s, z = self.g("GET", "/api/tassa", None, None,
                      {"citta": "Narnia", "notti": "2", "ospiti": "2"})
        self.assertEqual((s, z["tassa_cents"]), (200, 0))

    def test_split_preview_conserva_il_totale(self):
        """POST /api/split/preview -> 200: N quote intere che sommano ESATTAMENTE al totale."""
        s, p = self.g("POST", "/api/split/preview", {"totale_cents": TOTALE, "n": 3})
        self.assertEqual(s, 200, p)
        self.assertEqual(p["quote"], [13734, 13733, 13733])
        self.assertEqual(sum(p["quote"]), TOTALE)
        self.assertEqual(p["n"], 3)
        self.assertEqual(p["totale_cents"], TOTALE)
        self.assertEqual(p["per_persona_min_cents"], 13733)
        self.assertEqual(p["per_persona_max_cents"], 13734)
        self.assertLessEqual(p["per_persona_max_cents"] - p["per_persona_min_cents"], 1)
        self.assertEqual(p["money_unit"], "cents_integer")

    def test_split_crea_quote_esatte(self):
        """POST /api/split/crea -> 201 col conto aperto e le quote che tornano al centesimo."""
        rif, _vt = self.prenotazione_pagata()
        s, c = self.g("POST", "/api/split/crea",
                      {"prenotazione_id": rif, "alloggio_id": SLUG,
                       "totale_cents": TOTALE,
                       "partecipanti": ["anna", "bruno", "carla"]})
        self.assertEqual(s, 201, c)
        self.assertIsInstance(c["conto_id"], str)
        self.assertTrue(c["conto_id"])
        st = c["stato"]
        self.assertEqual(st["prenotazione_id"], rif)
        self.assertEqual(st["alloggio_id"], SLUG)
        self.assertEqual(st["totale_cents"], TOTALE)
        self.assertEqual(st["raccolto_cents"], 0)
        self.assertEqual(st["mancante_cents"], TOTALE)
        self.assertEqual(st["stato"], "aperto")
        self.assertIs(st["completato"], False)
        self.assertEqual([q["dovuto_cents"] for q in st["quote"]], [13734, 13733, 13733])
        self.assertEqual(sum(q["dovuto_cents"] for q in st["quote"]), TOTALE)

    def test_split_paga_e_stato(self):
        """POST /api/split/paga -> 200 (idempotente) · GET /api/split/stato -> 200 col raccolto."""
        rif, _vt = self.prenotazione_pagata()
        s, c = self.g("POST", "/api/split/crea",
                      {"prenotazione_id": rif, "alloggio_id": SLUG, "totale_cents": TOTALE,
                       "metodo": "importi", "partecipanti": ["anna", "bruno"],
                       "importi": {"anna": 20000, "bruno": 21200}})
        self.assertEqual(s, 201, c)
        cid = c["conto_id"]
        s, p1 = self.g("POST", "/api/split/paga",
                       {"conto_id": cid, "partecipante_id": "anna"})
        self.assertEqual((s, p1), (200, {"stato": "pagato", "completato": False,
                                         "idempotente": False}))
        s, replay = self.g("POST", "/api/split/paga",
                           {"conto_id": cid, "partecipante_id": "anna"})
        self.assertEqual((s, replay), (200, {"stato": "pagato", "completato": False,
                                             "idempotente": True}))
        s, meta = self.g("GET", "/api/split/stato", None, None, {"conto_id": cid})
        self.assertEqual(s, 200, meta)
        self.assertEqual(meta["raccolto_cents"], 20000)     # il replay NON ha raccolto due volte
        self.assertEqual(meta["mancante_cents"], TOTALE - 20000)
        self.assertEqual(meta["stato"], "aperto")
        s, p2 = self.g("POST", "/api/split/paga",
                       {"conto_id": cid, "partecipante_id": "bruno"})
        self.assertEqual((s, p2), (200, {"stato": "pagato", "completato": True,
                                         "idempotente": False}))
        s, fine = self.g("GET", "/api/split/stato", None, None, {"conto_id": cid})
        self.assertEqual(s, 200, fine)
        self.assertEqual(fine["raccolto_cents"], TOTALE)
        self.assertEqual(fine["mancante_cents"], 0)
        self.assertEqual(fine["stato"], "completato")
        self.assertIs(fine["completato"], True)
        self.assertIs(fine["pronto_per_escrow"], True)

    def test_carta_link_e_stato(self):
        """POST /api/host/carta_link -> 200 col mandato · GET /api/host/carta_stato -> 200."""
        # ⛔ Dal 2026-08-08 «attivo» pretende anche SCATTO3_ATTIVO: non si offre una
        #    garanzia che non si puo' incassare. Qui si accende, perche' e' il mondo
        #    in cui la funzione deve funzionare.
        import os as _os
        _os.environ["SCATTO3_ATTIVO"] = "1"
        self.addCleanup(_os.environ.pop, "SCATTO3_ATTIVO", None)
        s, prima = self.g("GET", "/api/host/carta_stato", None, self.tk)
        self.assertEqual((s, prima), (200, {"carta_collegata": False, "attivo": True}))
        s, link = self.g("POST", "/api/host/carta_link", {}, self.tk)
        self.assertEqual(s, 200, link)
        self.assertEqual(link["url"], "https://stripe.finto/salva-carta")
        self.assertIn("Autorizzo BookinVIP", link["mandato"])   # mandato esplicito, non implicito
        # il webhook mode=setup salva gli id OPACHI (mai il numero della carta)
        grezzo = json.dumps({"type": "checkout.session.completed",
                             "data": {"object": {"id": "cs_setup_finto", "mode": "setup",
                                                 "metadata": {"host_id": self.host_id,
                                                              "scopo": "mandato_penale_offsession"}}}})
        s, w = self.r.gestisci("POST", "/api/payments/webhook", {}, grezzo,
                               {"Stripe-Signature": firma_di_test(grezzo, WHSEC,
                                                                  int(time.time()))})
        self.assertEqual(s, 200, w)
        self.assertEqual(w, {"ricevuto": True, "tipo": "checkout.session.completed",
                             "scopo": "carta"})
        info = self.sis.registro_host.info_host(self.host_id)
        self.assertEqual(info["stripe_customer_id"], "cus_finto")
        self.assertEqual(info["stripe_payment_method"], "pm_finto")
        s, dopo = self.g("GET", "/api/host/carta_stato", None, self.tk)
        self.assertEqual((s, dopo), (200, {"carta_collegata": True, "attivo": True}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
