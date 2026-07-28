# -*- coding: utf-8 -*-
"""HAPPY PATH DEI CONTI + CONTRATTO JSON (punto 3 del mandato collaudo).

Che cosa guarda che NON e' gia' guardato altrove:
  - test_conservazione_denaro.py verifica le identita' contabili su prezzi OSTILI (primi,
    1 cent, casi limite) con la commissione CONFIGURATA a mano;
  - test_property_soldi.py verifica i motori PURI (fase98/111/188) con Hypothesis;
  - test_stateful_api.py verifica gli invarianti lungo sequenze casuali di API.
Qui invece si guarda il conto COME LO VEDE L'UTENTE su casi NORMALI (1-14 notti, 1-6
ospiti, 30-500 EUR, EUR/USD/GBP/JPY) e la FORMA delle risposte (il contratto JSON che un
domani non deve rompersi).

Le cinque cose che questo file fissa:
  A) PREVENTIVO — un ORACOLO INDIPENDENTE (riscritto qui da zero, senza guardare il motore)
     ricalcola ogni voce del preventivo e la confronta al CENTESIMO; vale l'identita'
     che l'ospite legge sulla pagina:
         totale_ospite == netto_host + commissione + tariffa_tecnica + tassa - sconti
  B) SCONTI — settimana (>=7 notti), mese (>=28, prevale), non-rimborsabile (-12% sul netto
     gia' scontato): listino == pagato + tutti gli sconti, sempre.
  B-bis) PREZZI PER NOTTE DIVERSI (weekend/alta stagione): il conto SOMMA le notti del
     calendario una per una — non moltiplica il prezzo base — e lo sconto lungo e la
     commissione poggiano su quella somma vera.
  C) RAMPA COMMISSIONI — host nuovo 0% -> 8% (>=90gg) -> 10% (>=365gg); link diretto 5%
     sempre; tariffa tecnica 3% SEMPRE presente anche a commissione 0; e soprattutto
     l'OSPITE PAGA LO STESSO IMPORTO in tutti e tre gli scaglioni (0% a suo carico: la
     commissione la sente solo l'host sul suo netto).
  D) CONTRATTO JSON — chiavi obbligatorie, tipi, denaro in centesimi INTERI (mai float, mai
     bool, mai negativo) per catalogo, catalogo/<slug>, concierge/quote, concierge/book,
     host/prenotazioni, host/payout; piu' i campi che NON devono comparire (il dettaglio
     pubblico non espone host_id ne' indirizzo) e il blocco 'paga in struttura' (fase188)
     nei due stati legittimi: dormiente (accettato=False) e acceso (conti che tornano).

VISTE ROSSE (regola aurea: nessun verde vale finche' non e' stato visto rosso).
19 guasti iniettati A RUNTIME nel motore (nessun file di produzione toccato), uno per volta,
e ognuno ha fatto fallire il test indicato:
   1-2. fase98 `stato_scaglione` appiattito a regime -> test_tre_scaglioni_esatti_ai_bordi e
        test_ospite_paga_lo_stesso_in_tutti_gli_scaglioni ROSSI;
   3.   fase59 `_psp_bps=0` (tariffa tecnica regalata) -> test_tariffa_tecnica_tre_percento_sempre;
   4.   fase98 `commissione_bps_fonte` che ignora la fonte -> test_link_diretto_sempre_cinque_percento;
   5.   fase57 `sconto_lungo_di`->(0,0) -> test_soglie_settimana_e_mese,
        test_sconto_finanziato_dall_host_mai_da_noi e il caso JPY;
   6.   fase57 `politica_cancellazione_di`->"flessibile" -> test_non_rimborsabile_dodici_percento;
   7.   fase58 `stato_giorno` col prezzo BASE per tutte le notti (calendario ignorato) ->
        entrambi i test di TestPrezziPerNotte;
   8.   fase59 `_valuta_alloggio`->"EUR" (like-for-like rotto) -> test_valute_esponente_giusto
        e test_jpy_con_sconto_e_tassa_percentuale;
   9.   fase66 `calcola_tassa` senza cap notti -> test_tassa_percentuale_e_cap_notti;
  10-13. quote mutilata (chiave tolta / importo float / +1 cent / -1 cent sul netto host) ->
        test_quote_contratto_e_valori, test_book_contratto_e_valori, la griglia;
  14.   fase188 `calcola` con fee azzerata -> test_paga_in_struttura_dormiente_e_acceso;
  15.   fase131 `PayoutDashboard.riepilogo` gonfiato -> test_host_payout_contratto.
Nessun guasto e' sopravvissuto: 19 su 19 visti ROSSI.

Zero rete (Stripe finto, geocoder spento), DB su file temporanei, deterministico.
"""
import datetime
import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase98_policy_commissione import (BPS_DIRETTO, LANCIO_BPS_FASE1, LANCIO_BPS_REGIME,
                                       LANCIO_GIORNI_FASE1, LANCIO_GIORNI_GRATIS)
from fase99_multicurrency import esponente
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

PSP_BPS = 300          # tariffa tecnica: 3% SEMPRE dovuta dall'host (README regola 4)
COMM_BPS = 1000        # commissione marketplace a regime: 10%
SCONTO_NR_BPS = 1200   # non-rimborsabile: -12% sul netto (finanziato dall'host)


def _fetch_finto(url, body, headers):
    import secrets
    return {"url": "https://stripe.finto/" + secrets.token_hex(4),
            "id": "cs_" + secrets.token_hex(8)}


# ─────────────────────────────────────────────────────────────────────────────
# ORACOLO INDIPENDENTE: la regola riscritta da zero (se il motore cambia in
# silenzio, qui non cambia nulla -> il confronto diventa rosso).
# ─────────────────────────────────────────────────────────────────────────────
def oracolo_preventivo(*, prezzo_notte=None, notti=None, prezzi_notti=None, ospiti,
                       comm_bps, psp_bps=PSP_BPS, non_rimborsabile=False,
                       sconto_settimana_bps=0, sconto_mese_bps=0,
                       tassa_pp_notte_cents=0, tassa_max_notti=0, tassa_perc_bps=0):
    """`prezzi_notti` = il prezzo REALE di ogni singola notte come sta sul calendario
    dell'host (weekend/alta stagione). Il conto e' la SOMMA delle notti, non il prezzo
    base moltiplicato: chi moltiplica sbaglia appena una notte costa diverso."""
    if prezzi_notti is not None:
        notti = len(prezzi_notti)
        listino = sum(prezzi_notti)
    else:
        listino = prezzo_notte * notti
    bps_lungo = (sconto_mese_bps if (notti >= 28 and sconto_mese_bps > 0)
                 else (sconto_settimana_bps if (notti >= 7 and sconto_settimana_bps > 0) else 0))
    sconto_lungo = listino * bps_lungo // 10000
    netto = listino - sconto_lungo
    sconto_nr = (netto * SCONTO_NR_BPS // 10000) if non_rimborsabile else 0
    netto -= sconto_nr
    comm = netto * comm_bps // 10000
    guest = netto
    notti_tass = min(notti, tassa_max_notti) if tassa_max_notti > 0 else notti
    tassa = tassa_pp_notte_cents * notti_tass * ospiti + tassa_perc_bps * netto // 10000
    totale = guest + tassa
    tariffa_tecnica = totale * psp_bps // 10000
    return {"prezzo_listino_cents": listino,
            "sconto_soggiorno_lungo_cents": sconto_lungo,
            "sconto_non_rimborsabile_cents": sconto_nr,
            "prezzo_netto_cents": netto,
            "commissione_cents": comm,
            "prezzo_guest_cents": guest,
            "tassa_soggiorno_cents": tassa,
            "totale_cents": totale,
            "costo_pagamento_cents": tariffa_tecnica,
            "netto_host_cents": netto - comm - tariffa_tecnica}


class _Base(unittest.TestCase):
    """Sistema vero + router vero, con i parametri della PRODUZIONE (main_casavip.py):
    commissione 10% a regime, rampa di lancio ACCESA, tariffa tecnica 3%."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="happy_conti_")
        os.environ["UPLOAD_DIR"] = self.d + "/u"
        # "Paga in struttura" e' pilotato da una variabile d'ambiente: se restasse quella
        # dell'ambiente, il CONTRATTO della quote cambierebbe forma da una macchina
        # all'altra. Qui si dichiara (spento di default) e si ripristina alla fine.
        self.ambiente("PAGA_STRUTTURA_ATTIVO", "0")
        self._orig_fetch = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fetch_finto)
        self.db_reg = self.d + "/r.db"
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=self.d + "/c.db", db_inventario=self.d + "/i.db",
            db_registro_host=self.db_reg, db_accettazioni=self.d + "/a.db",
            db_pendenti=self.d + "/p.db", db_payout=self.d + "/po.db",
            db_garanzia=self.d + "/g.db", db_finanza=self.d + "/f.db",
            commissione_bps=COMM_BPS, psp_bps=PSP_BPS, promo_lancio_attiva=True,
            stripe_secret_key="sk", stripe_webhook_secret="whsec_happy",
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/ko"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "host@happy.local", "password": "password1",
                       "accetta_termini": True, "accetta_clausole": True,
                       "accetta_privacy": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = {"X-Host-Token": c["token"]}
        self.host_id = c["host_id"]
        self.oggi = datetime.date.today()

    def tearDown(self):
        _stripe.ProviderStripe._fetch_reale = self._orig_fetch
        shutil.rmtree(self.d, ignore_errors=True)

    # ── infrastruttura ────────────────────────────────────────────────────────
    def ambiente(self, nome, valore):
        """Imposta una variabile d'ambiente per QUESTO test e la rimette com'era dopo
        (assente resta assente): nessun test lascia sporco agli altri."""
        prima = os.environ.get(nome)

        def _ripristina():
            if prima is None:
                os.environ.pop(nome, None)
            else:
                os.environ[nome] = prima
        self.addCleanup(_ripristina)
        os.environ[nome] = valore

    def g(self, metodo, path, body=None, headers=None, query=None):
        return self.r.gestisci(metodo, path, query or {},
                               json.dumps(body) if body is not None else None,
                               headers or {})

    def giorno(self, n):
        return (self.oggi + datetime.timedelta(days=n)).isoformat()

    def pubblica(self, slug, prezzo, *, valuta="EUR", citta="Roma", paese="IT",
                 giorni=60, **extra):
        corpo = {"slug": slug, "titolo": "Casa " + slug, "citta": citta, "paese": paese,
                 "descrizione": "Alloggio di prova per il collaudo dei conti.",
                 "prezzo_notte_cents": prezzo, "capacita": 6, "valuta": valuta,
                 "lat_micro": 41902782, "lon_micro": 12496366}
        if paese.upper() == "IT":
            corpo["cin"] = "IT058091C2X5V0ABCD"
        corpo.update(extra)
        s, o = self.g("POST", "/api/host/pubblica", corpo, self.tok)
        self.assertEqual(s, 201, o)
        s, o = self.g("POST", "/api/host/disponibilita_range",
                      {"alloggio_id": slug, "da": self.giorno(0), "a": self.giorno(giorni),
                       "unita_totali": 2, "prezzo_netto_cents": prezzo}, self.tok)
        self.assertEqual(s, 200, o)
        return slug

    def prezzo_giorno(self, slug, indice, prezzo, unita=2):
        """Prezzo di UNA notte sul calendario (weekend/alta stagione)."""
        s, o = self.g("POST", "/api/host/disponibilita",
                      {"alloggio_id": slug, "giorno": self.giorno(indice),
                       "unita_totali": unita, "prezzo_netto_cents": prezzo}, self.tok)
        self.assertEqual(s, 200, o)

    def quota(self, slug, *, notti=1, ospiti=2, fonte="marketplace", da=2, atteso=200):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": slug, "check_in": self.giorno(da),
                       "check_out": self.giorno(da + notti), "party": ospiti,
                       "fonte": fonte})
        self.assertEqual(s, atteso, q)
        return q

    def invecchia(self, giorni):
        """Sposta indietro la data di registrazione dell'host: fa scattare la rampa."""
        con = sqlite3.connect(self.db_reg)
        try:
            con.execute("UPDATE host SET creato_ts=? WHERE host_id=?",
                        (int(time.time()) - int(giorni) * 86400 - 60, self.host_id))
            con.commit()
        finally:
            con.close()

    # ── verifiche riusabili ───────────────────────────────────────────────────
    def confronta_oracolo(self, q, atteso, ctx):
        for chiave, valore in atteso.items():
            self.assertIsInstance(q.get(chiave), int,
                                  "%s: %s non e' un intero (%r)" % (ctx, chiave, q.get(chiave)))
            self.assertNotIsInstance(q.get(chiave), bool,
                                     "%s: %s e' un bool" % (ctx, chiave))
            self.assertEqual(q[chiave], valore,
                             "%s: %s -> motore %d, oracolo %d" % (ctx, chiave, q[chiave], valore))

    def identita_conto(self, q, ctx):
        """L'identita' che l'ospite legge sulla pagina, al centesimo."""
        self.assertEqual(
            q["totale_cents"],
            q["netto_host_cents"] + q["commissione_cents"] + q["costo_pagamento_cents"]
            + q["tassa_soggiorno_cents"] - q["sconto_credito_cents"],
            "%s: totale != netto_host + commissione + tariffa_tecnica + tassa - sconto (%r)"
            % (ctx, q))
        self.assertEqual(q["totale_cents"], q["prezzo_guest_cents"] + q["tassa_soggiorno_cents"],
                         "%s: la tassa non e' pass-through (%r)" % (ctx, q))
        self.assertEqual(q["prezzo_listino_cents"],
                         q["prezzo_guest_cents"] + q["sconto_non_rimborsabile_cents"]
                         + q["sconto_soggiorno_lungo_cents"] + q["sconto_credito_cents"],
                         "%s: listino != pagato + sconti (%r)" % (ctx, q))

    def _importo(self, v, ctx, dove):
        self.assertIsInstance(v, int, "%s: %s non intero (%r)" % (ctx, dove, v))
        self.assertNotIsInstance(v, bool, "%s: %s e' un bool" % (ctx, dove))
        self.assertGreaterEqual(v, 0, "%s: %s negativo (%d)" % (ctx, dove, v))

    def soldi_interi(self, corpo, ctx):
        """Ogni campo *_cents, a qualsiasi profondita': intero (mai float/bool) e >= 0.
        Un *_cents che porta una MAPPA valuta->importo (es. debiti_aperti_cents) viene
        controllato voce per voce."""
        if isinstance(corpo, dict):
            for k, v in corpo.items():
                if isinstance(k, str) and k.endswith("_cents"):
                    if isinstance(v, dict):
                        for valuta, importo in v.items():
                            self.assertIsInstance(valuta, str, "%s: %s" % (ctx, k))
                            self._importo(importo, ctx, "%s[%s]" % (k, valuta))
                    else:
                        self._importo(v, ctx, k)
                self.soldi_interi(v, ctx)
        elif isinstance(corpo, list):
            for v in corpo:
                self.soldi_interi(v, ctx)

    def schema(self, corpo, atteso, ctx):
        """Chiavi OBBLIGATORIE + tipi. `atteso` = {chiave: tipo|tupla-di-tipi}."""
        self.assertIsInstance(corpo, dict, "%s: la risposta non e' un oggetto JSON" % ctx)
        for chiave, tipo in atteso.items():
            self.assertIn(chiave, corpo, "%s: manca la chiave obbligatoria '%s'" % (ctx, chiave))
            v = corpo[chiave]
            self.assertIsInstance(v, tipo, "%s: '%s' e' %s, atteso %s"
                                  % (ctx, chiave, type(v).__name__, tipo))
            if tipo is int:
                self.assertNotIsInstance(v, bool, "%s: '%s' e' un bool" % (ctx, chiave))
        self.soldi_interi(corpo, ctx)


# ═══════════════════════════════════════════════════════════════════════════════
# A) PREVENTIVO — griglia di casi NORMALI, confronto con l'oracolo indipendente
# ═══════════════════════════════════════════════════════════════════════════════
class TestPreventivoGriglia(_Base):

    def test_griglia_notti_ospiti_prezzi(self):
        """1-14 notti x 1-6 ospiti x prezzi tipici: ogni voce del preventivo esatta al
        centesimo e identita' del conto sempre valida. Host a REGIME (10%)."""
        self.invecchia(LANCIO_GIORNI_FASE1 + 30)          # oltre l'anno -> 10% a regime
        prezzi = (3000, 8900, 12000, 50000)               # 30, 89, 120, 500 EUR a notte
        for i, prezzo in enumerate(prezzi):
            slug = self.pubblica("griglia-%d" % i, prezzo,
                                 tassa_pp_notte_cents=200, tassa_max_notti=3)
            for notti in range(1, 15):
                for ospiti in range(1, 7):
                    q = self.quota(slug, notti=notti, ospiti=ospiti)
                    ctx = "prezzo=%d notti=%d ospiti=%d" % (prezzo, notti, ospiti)
                    atteso = oracolo_preventivo(
                        prezzo_notte=prezzo, notti=notti, ospiti=ospiti, comm_bps=COMM_BPS,
                        tassa_pp_notte_cents=200, tassa_max_notti=3)
                    self.confronta_oracolo(q, atteso, ctx)
                    self.identita_conto(q, ctx)
                    self.assertEqual(q["notti"], notti, ctx)
                    self.assertEqual(q["party"], ospiti, ctx)

    def test_valute_esponente_giusto(self):
        """EUR/USD/GBP a 2 decimali, JPY a 0: gli importi restano UNITA' MINORI intere,
        mai moltiplicati per 100 (modo di rompersi n.10: 'dato assurdo')."""
        self.invecchia(LANCIO_GIORNI_FASE1 + 30)
        casi = (("EUR", 2, 12000, "Roma", "IT"), ("USD", 2, 15000, "New York", "US"),
                ("GBP", 2, 9500, "London", "GB"), ("JPY", 0, 18000, "Tokyo", "JP"))
        for valuta, esp, prezzo, citta, paese in casi:
            self.assertEqual(esponente(valuta), esp,
                             "esponente sbagliato per %s (dato assurdo in arrivo)" % valuta)
            slug = self.pubblica("val-" + valuta.lower(), prezzo, valuta=valuta,
                                 citta=citta, paese=paese,
                                 tassa_pp_notte_cents=150, tassa_max_notti=2)
            for notti in (1, 3, 7, 14):
                for ospiti in (1, 4, 6):
                    q = self.quota(slug, notti=notti, ospiti=ospiti)
                    ctx = "%s notti=%d ospiti=%d" % (valuta, notti, ospiti)
                    self.assertEqual(q["valuta"], valuta, ctx)
                    atteso = oracolo_preventivo(
                        prezzo_notte=prezzo, notti=notti, ospiti=ospiti, comm_bps=COMM_BPS,
                        tassa_pp_notte_cents=150, tassa_max_notti=2)
                    self.confronta_oracolo(q, atteso, ctx)
                    self.identita_conto(q, ctx)
            # la cifra che l'ospite LEGGE: 1 notte in JPY = 18000 yen, non 180 yen ne' 1.800.000
            q1 = self.quota(slug, notti=1, ospiti=1)
            self.assertEqual(q1["prezzo_listino_cents"], prezzo, valuta)
            self.assertEqual(q1["totale_cents"], prezzo + 150 * 1 * 1, valuta)

    def test_tassa_percentuale_e_cap_notti(self):
        """Tassa a percentuale + cap sulle notti: pass-through esatto, mai inventata."""
        self.invecchia(LANCIO_GIORNI_FASE1 + 30)
        slug = self.pubblica("tassa-mista", 20000, tassa_pp_notte_cents=250,
                             tassa_max_notti=4, tassa_perc_bps=500)
        for notti in (1, 4, 5, 10):
            q = self.quota(slug, notti=notti, ospiti=3)
            ctx = "tassa mista notti=%d" % notti
            atteso = oracolo_preventivo(prezzo_notte=20000, notti=notti, ospiti=3,
                                        comm_bps=COMM_BPS, tassa_pp_notte_cents=250,
                                        tassa_max_notti=4, tassa_perc_bps=500)
            self.confronta_oracolo(q, atteso, ctx)
            self.identita_conto(q, ctx)
            self.assertGreater(q["tassa_soggiorno_cents"], 0, ctx)

    def test_jpy_con_sconto_e_tassa_percentuale(self):
        """Il caso che scopre i numeri assurdi: valuta SENZA decimali (JPY) + sconto
        settimana + tassa a percentuale, tutto a divisione intera. Numeri ASSOLUTI, e un
        controllo di PLAUSIBILITA' (una notte a Tokyo costa migliaia di yen, non milioni)."""
        self.invecchia(LANCIO_GIORNI_FASE1 + 30)
        slug = self.pubblica("tokyo-7", 18000, valuta="JPY", citta="Tokyo", paese="JP",
                             giorni=45, sconto_settimana_bps=1000, tassa_perc_bps=500)
        q = self.quota(slug, notti=7, ospiti=2, da=1)
        atteso = oracolo_preventivo(prezzo_notte=18000, notti=7, ospiti=2, comm_bps=COMM_BPS,
                                    sconto_settimana_bps=1000, tassa_perc_bps=500)
        self.confronta_oracolo(q, atteso, "JPY settimana + tassa %")
        self.identita_conto(q, "JPY settimana + tassa %")
        self.assertEqual(q["valuta"], "JPY", q)
        self.assertEqual(q["prezzo_listino_cents"], 126000, q)
        self.assertEqual(q["sconto_soggiorno_lungo_cents"], 12600, q)
        self.assertEqual(q["prezzo_guest_cents"], 113400, q)
        self.assertEqual(q["tassa_soggiorno_cents"], 5670, q)
        self.assertEqual(q["totale_cents"], 119070, q)
        # occhio del fondatore: la cifra a notte deve avere senso nel mondo vero
        a_notte = q["totale_cents"] // q["notti"]
        self.assertTrue(2000 <= a_notte <= 200000,
                        "yen a notte fuori dal mondo reale: %d (%r)" % (a_notte, q))

    def test_alloggio_senza_tassa_non_la_inventa(self):
        self.invecchia(LANCIO_GIORNI_FASE1 + 30)
        slug = self.pubblica("senza-tassa", 15000)
        q = self.quota(slug, notti=5, ospiti=4)
        self.assertEqual(q["tassa_soggiorno_cents"], 0, q)
        self.assertEqual(q["totale_cents"], q["prezzo_guest_cents"], q)
        self.identita_conto(q, "senza tassa")


# ═══════════════════════════════════════════════════════════════════════════════
# B) SCONTI — settimana / mese / non-rimborsabile
# ═══════════════════════════════════════════════════════════════════════════════
class TestSconti(_Base):

    def test_soglie_settimana_e_mese(self):
        """<7 notti nessuno sconto; >=7 settimana; >=28 il mese PREVALE sulla settimana."""
        self.invecchia(LANCIO_GIORNI_FASE1 + 30)
        slug = self.pubblica("sconti", 10000, giorni=45,
                             sconto_settimana_bps=1000, sconto_mese_bps=2500)
        for notti, bps_atteso in ((1, 0), (6, 0), (7, 1000), (27, 1000), (28, 2500),
                                  (35, 2500)):
            q = self.quota(slug, notti=notti, ospiti=2, da=1)
            ctx = "sconto lungo notti=%d" % notti
            self.assertEqual(q["sconto_soggiorno_lungo_cents"],
                             10000 * notti * bps_atteso // 10000, ctx)
            atteso = oracolo_preventivo(prezzo_notte=10000, notti=notti, ospiti=2,
                                        comm_bps=COMM_BPS, sconto_settimana_bps=1000,
                                        sconto_mese_bps=2500)
            self.confronta_oracolo(q, atteso, ctx)
            self.identita_conto(q, ctx)

    def test_non_rimborsabile_dodici_percento(self):
        """-12% sul netto (gia' scontato lungo), e il listino resta la somma trasparente."""
        self.invecchia(LANCIO_GIORNI_FASE1 + 30)
        piena = self.pubblica("nr-no", 12000, giorni=45, sconto_settimana_bps=1000)
        nr = self.pubblica("nr-si", 12000, giorni=45, sconto_settimana_bps=1000,
                           politica_cancellazione="non_rimborsabile")
        for notti in (2, 7, 10):
            qa = self.quota(piena, notti=notti, ospiti=2, da=1)
            qb = self.quota(nr, notti=notti, ospiti=2, da=1)
            ctx = "non rimborsabile notti=%d" % notti
            self.assertEqual(qa["sconto_non_rimborsabile_cents"], 0, ctx)
            atteso = oracolo_preventivo(prezzo_notte=12000, notti=notti, ospiti=2,
                                        comm_bps=COMM_BPS, non_rimborsabile=True,
                                        sconto_settimana_bps=1000)
            self.confronta_oracolo(qb, atteso, ctx)
            self.identita_conto(qb, ctx)
            self.assertEqual(qb["sconto_non_rimborsabile_cents"],
                             qa["prezzo_guest_cents"] * SCONTO_NR_BPS // 10000, ctx)
            self.assertLess(qb["totale_cents"], qa["totale_cents"],
                            "%s: il non-rimborsabile deve costare MENO" % ctx)

    def test_sconto_finanziato_dall_host_mai_da_noi(self):
        """Lo sconto lo paga l'host (netto piu' basso), non la piattaforma: la commissione
        resta il 10% del netto SCONTATO e la tariffa tecnica copre sempre il 3%."""
        self.invecchia(LANCIO_GIORNI_FASE1 + 30)
        slug = self.pubblica("chi-paga", 10000, giorni=45, sconto_settimana_bps=2000,
                             politica_cancellazione="non_rimborsabile")
        q = self.quota(slug, notti=7, ospiti=2, da=1)
        # numeri ASSOLUTI (non ricavati dalla risposta stessa: un confronto che si nutre
        # dei propri dati resta verde anche se gli sconti spariscono).
        atteso = oracolo_preventivo(prezzo_notte=10000, notti=7, ospiti=2, comm_bps=COMM_BPS,
                                    non_rimborsabile=True, sconto_settimana_bps=2000)
        self.confronta_oracolo(q, atteso, "chi paga lo sconto")
        self.assertEqual(q["sconto_soggiorno_lungo_cents"], 14000, q)   # 20% di 70000
        self.assertEqual(q["sconto_non_rimborsabile_cents"], 6720, q)   # 12% di 56000
        self.assertEqual(q["prezzo_guest_cents"], 49280, q)             # l'ospite paga QUESTO
        self.assertEqual(q["commissione_cents"], 4928, q)               # 10% del netto SCONTATO
        self.assertEqual(q["costo_pagamento_cents"], 1478, q)           # 3% del totale
        self.assertEqual(q["netto_host_cents"], 42874, q)               # lo sconto lo paga l'host
        self.assertEqual(q["commissione_cents"], q["prezzo_netto_cents"] * COMM_BPS // 10000, q)
        self.assertEqual(q["costo_pagamento_cents"], q["totale_cents"] * PSP_BPS // 10000, q)
        self.identita_conto(q, "chi paga lo sconto")


# ═══════════════════════════════════════════════════════════════════════════════
# B-bis) PREZZI PER NOTTE DIVERSI — il conto SOMMA le notti, non moltiplica
# ═══════════════════════════════════════════════════════════════════════════════
class TestPrezziPerNotte(_Base):
    """Il caso piu' NORMALE del mondo vero: il weekend costa piu' del lunedi'. Il
    preventivo deve sommare le notti UNA PER UNA leggendole dal calendario, e tutto il
    resto (sconto lungo, commissione, tariffa tecnica, tassa) deve poggiare su quella
    somma. Chi moltiplicasse il prezzo base per le notti sbaglierebbe il conto in silenzio
    proprio sui soggiorni che valgono di piu'."""

    def setUp(self):
        super().setUp()
        self.invecchia(LANCIO_GIORNI_FASE1 + 30)          # regime 10%

    def test_weekend_piu_caro_somma_esatta(self):
        slug = self.pubblica("weekend", 10000, tassa_pp_notte_cents=200, tassa_max_notti=5)
        self.prezzo_giorno(slug, 3, 17500)                # la 2a notte del soggiorno
        self.prezzo_giorno(slug, 4, 22000)                # la 3a notte del soggiorno
        prezzi = [10000, 17500, 22000]                    # notti 2,3,4 -> check_in=2
        q = self.quota(slug, notti=3, ospiti=4, da=2)
        atteso = oracolo_preventivo(prezzi_notti=prezzi, ospiti=4, comm_bps=COMM_BPS,
                                    tassa_pp_notte_cents=200, tassa_max_notti=5)
        self.confronta_oracolo(q, atteso, "weekend")
        self.identita_conto(q, "weekend")
        self.assertEqual(q["prezzo_listino_cents"], sum(prezzi),
                         "il preventivo NON somma le notti del calendario: %r" % (q,))
        self.assertNotEqual(q["prezzo_listino_cents"], 10000 * 3,
                            "il preventivo moltiplica il prezzo base e ignora il calendario")

    def test_sconto_settimana_sulla_somma_reale_non_sul_base(self):
        """7 notti a prezzi misti: lo sconto settimana e' il 10% della SOMMA VERA."""
        slug = self.pubblica("mista-7", 10000, giorni=45, sconto_settimana_bps=1000)
        for indice in (3, 4):
            self.prezzo_giorno(slug, indice, 15000)
        prezzi = [10000, 15000, 15000, 10000, 10000, 10000, 10000]   # notti 2..8
        q = self.quota(slug, notti=7, ospiti=2, da=2)
        atteso = oracolo_preventivo(prezzi_notti=prezzi, ospiti=2, comm_bps=COMM_BPS,
                                    sconto_settimana_bps=1000)
        self.confronta_oracolo(q, atteso, "settimana mista")
        self.identita_conto(q, "settimana mista")
        self.assertEqual(q["prezzo_listino_cents"], 80000, q)
        self.assertEqual(q["sconto_soggiorno_lungo_cents"], 8000,
                         "lo sconto settimana non e' il 10%% della somma vera: %r" % (q,))
        self.assertEqual(q["commissione_cents"], 72000 * COMM_BPS // 10000, q)


# ═══════════════════════════════════════════════════════════════════════════════
# C) RAMPA COMMISSIONI — 0% -> 8% -> 10%, diretto 5%, ospite SEMPRE 0%
# ═══════════════════════════════════════════════════════════════════════════════
class TestRampaEOspiteZero(_Base):

    def setUp(self):
        super().setUp()
        self.slug = self.pubblica("rampa", 20000, tassa_pp_notte_cents=200,
                                  tassa_max_notti=3)

    def test_tre_scaglioni_esatti_ai_bordi(self):
        """0% fino a 89 giorni, 8% da 90 a 364, 10% da 365 in poi: al giorno preciso."""
        for giorni, bps in ((0, 0), (1, 0), (LANCIO_GIORNI_GRATIS - 1, 0),
                            (LANCIO_GIORNI_GRATIS, LANCIO_BPS_FASE1),
                            (LANCIO_GIORNI_FASE1 - 1, LANCIO_BPS_FASE1),
                            (LANCIO_GIORNI_FASE1, LANCIO_BPS_REGIME),
                            (LANCIO_GIORNI_FASE1 + 500, LANCIO_BPS_REGIME)):
            self.invecchia(giorni)
            q = self.quota(self.slug, notti=3, ospiti=2)
            netto = 20000 * 3
            self.assertEqual(q["commissione_cents"], netto * bps // 10000,
                             "anzianita' %d giorni: scaglione sbagliato (%r)" % (giorni, q))
            self.identita_conto(q, "rampa %d giorni" % giorni)

    def test_ospite_paga_lo_stesso_in_tutti_gli_scaglioni(self):
        """0% a carico dell'OSPITE: cambiando scaglione cambia solo il netto dell'HOST.
        Il totale che l'ospite paga NON si muove di un centesimo."""
        totali, netti = [], []
        for giorni in (0, LANCIO_GIORNI_GRATIS, LANCIO_GIORNI_FASE1):
            self.invecchia(giorni)
            q = self.quota(self.slug, notti=4, ospiti=3)
            totali.append(q["totale_cents"])
            netti.append(q["netto_host_cents"])
            self.assertEqual(q["prezzo_guest_cents"], q["prezzo_listino_cents"],
                             "l'ospite non deve pagare alcuna fee sopra il listino (%r)" % q)
        self.assertEqual(len(set(totali)), 1,
                         "l'ospite paga importi DIVERSI al variare della commissione host: %r"
                         % (totali,))
        self.assertEqual(netti, sorted(netti, reverse=True),
                         "il netto host deve calare al salire della commissione: %r" % (netti,))
        self.assertLess(netti[-1], netti[0], "la rampa non incide sul netto host: %r" % (netti,))

    def test_link_diretto_sempre_cinque_percento(self):
        """Canale 'diretto' (cliente dell'host): 5% fisso, la rampa non lo tocca."""
        netto = 20000 * 3
        for giorni in (0, LANCIO_GIORNI_GRATIS, LANCIO_GIORNI_FASE1, 5000):
            self.invecchia(giorni)
            q = self.quota(self.slug, notti=3, ospiti=2, fonte="diretto")
            self.assertEqual(q["fonte"], "diretto", q)
            self.assertEqual(q["commissione_cents"], netto * BPS_DIRETTO // 10000,
                             "diretto a %d giorni: non e' il 5%% (%r)" % (giorni, q))
            self.identita_conto(q, "diretto %d giorni" % giorni)

    def test_tariffa_tecnica_tre_percento_sempre(self):
        """3% SEMPRE dovuto dall'host, anche quando la commissione e' 0% (README regola 4)."""
        for giorni in (0, LANCIO_GIORNI_GRATIS, LANCIO_GIORNI_FASE1):
            self.invecchia(giorni)
            for fonte in ("marketplace", "diretto"):
                q = self.quota(self.slug, notti=2, ospiti=2, fonte=fonte)
                ctx = "%d giorni, %s" % (giorni, fonte)
                self.assertEqual(q["costo_pagamento_cents"],
                                 q["totale_cents"] * PSP_BPS // 10000,
                                 "%s: tariffa tecnica != 3%% del totale (%r)" % (ctx, q))
                self.assertGreater(q["costo_pagamento_cents"], 0,
                                   "%s: tariffa tecnica ASSENTE (%r)" % (ctx, q))
        self.invecchia(0)
        q = self.quota(self.slug, notti=2, ospiti=2)
        self.assertEqual(q["commissione_cents"], 0, q)
        self.assertGreater(q["costo_pagamento_cents"], 0,
                           "a commissione 0% la tariffa tecnica sparisce: perdita nostra")


# ═══════════════════════════════════════════════════════════════════════════════
# D) CONTRATTO JSON — la forma delle risposte principali
# ═══════════════════════════════════════════════════════════════════════════════
SCHEMA_CATALOGO = {"totale": int, "limit": int, "offset": int, "risultati": list,
                   "ordine": str, "lingua": str}
SCHEMA_CARD = {"slug": str, "titolo": str, "citta": str, "paese": str,
               "prezzo_notte_cents": int, "valuta": str, "capacita": int, "camere": int,
               "bagni": int, "servizi": list, "servizi_label": list, "lat_micro": int,
               "lon_micro": int, "politica_cancellazione": str,
               "cancellazione_gratuita": bool, "recensioni": dict}
SCHEMA_DETTAGLIO = {"slug": str, "titolo": str, "descrizione": str, "citta": str,
                    "paese": str, "fuso": str, "cin": str, "prezzo_notte_cents": int,
                    "valuta": str, "capacita": int, "camere": int, "bagni": int,
                    "servizi": list, "servizi_label": list, "politica_cancellazione": str,
                    "tassa_pp_notte_cents": int, "tassa_max_notti": int,
                    "tassa_perc_bps": int, "modalita_prenotazione": str,
                    "paga_in_struttura": bool, "immagini": list, "tavolo_id": str,
                    "lat_micro": int, "lon_micro": int, "recensioni": dict}
SCHEMA_QUOTE = {"quote_token": str, "alloggio_id": str, "check_in": str, "check_out": str,
                "party": int, "notti": int, "prezzo_netto_cents": int,
                "commissione_cents": int, "prezzo_guest_cents": int, "netto_host_cents": int,
                "costo_pagamento_cents": int, "sconto_credito_cents": int,
                "sconto_non_rimborsabile_cents": int, "sconto_soggiorno_lungo_cents": int,
                "prezzo_listino_cents": int, "tassa_soggiorno_cents": int,
                "totale_cents": int, "fonte": str, "valuta": str, "scade_a": int,
                "money_unit": str, "valuta_indicativa": str,
                "totale_indicativo_cents": int, "paga_in_struttura": dict}
SCHEMA_BOOK = {"stato": str, "riferimento": str, "alloggio_id": str, "check_in": str,
               "check_out": str, "prezzo_guest_cents": int, "netto_host_cents": int,
               "commissione_cents": int, "tassa_soggiorno_cents": int, "totale_cents": int,
               "costo_pagamento_cents": int, "valuta": str, "sconto_credito_cents": int,
               "credito_id": str, "idempotente": bool, "money_unit": str,
               "payment_url": str, "voucher_token": str, "diritto_recensione": str}
SCHEMA_PRENOTAZIONI = {"prenotazioni": list, "vista": str, "page": int, "limit": int,
                       "totale": int, "pagine": int, "totale_attive": int,
                       "totale_archivio": int}
SCHEMA_RIGA_PRENOTAZIONE = {"alloggio": str, "slug": str, "check_in": str,
                            "check_out": str, "codice": str, "pin": str, "stato": str,
                            "archiviata": bool}
SCHEMA_PAYOUT = {"payout": dict, "debiti_aperti_cents": dict}


class TestContrattoJSON(_Base):
    """Il contratto che un domani non deve rompersi: chiavi, tipi, unita' (cents interi)
    e qualche VALORE vero (id, totali, conteggi), non solo 'non e' 500'."""

    def setUp(self):
        super().setUp()
        self.invecchia(LANCIO_GIORNI_FASE1 + 30)          # regime 10%: numeri non banali
        self.slug = self.pubblica("contratto", 25000, tassa_pp_notte_cents=200,
                                  tassa_max_notti=3, sconto_settimana_bps=500)

    def test_catalogo_lista(self):
        s, c = self.g("GET", "/api/catalogo", None, None, {"citta": "Roma", "lang": "it"})
        self.assertEqual(s, 200, c)
        self.schema(c, SCHEMA_CATALOGO, "GET /api/catalogo")
        self.assertEqual(c["totale"], 1, c)
        self.assertEqual(len(c["risultati"]), 1, c)
        self.assertEqual(c["lingua"], "it", c)
        card = c["risultati"][0]
        self.schema(card, SCHEMA_CARD, "card di /api/catalogo")
        self.assertEqual(card["slug"], self.slug, card)
        self.assertEqual(card["prezzo_notte_cents"], 25000, card)
        self.assertEqual(card["valuta"], "EUR", card)
        self.assertIs(card["cancellazione_gratuita"], True, card)
        self.assertNotIn("host_id", card, "il catalogo pubblico non espone l'host")
        self.assertNotIn("indirizzo", card, "il catalogo pubblico non espone l'indirizzo")

    def test_catalogo_dettaglio(self):
        s, d = self.g("GET", "/api/catalogo/" + self.slug, None, None, {"lang": "it"})
        self.assertEqual(s, 200, d)
        self.schema(d, SCHEMA_DETTAGLIO, "GET /api/catalogo/<slug>")
        self.assertEqual(d["slug"], self.slug, d)
        self.assertEqual(d["tavolo_id"], self.slug, "il tavolo_id deve essere lo slug")
        self.assertEqual(d["prezzo_notte_cents"], 25000, d)
        self.assertEqual(d["tassa_pp_notte_cents"], 200, d)
        self.assertEqual(d["tassa_max_notti"], 3, d)
        self.assertEqual(d["cin"], "IT058091C2X5V0ABCD", d)
        self.assertNotIn("host_id", d, "il dettaglio pubblico non espone l'host (dato privato)")
        self.assertNotIn("indirizzo", d, "il dettaglio pubblico non espone l'indirizzo")
        s, nd = self.g("GET", "/api/catalogo/non-esiste")
        self.assertEqual((s, nd), (404, {"errore": "not_found"}))

    def test_quote_contratto_e_valori(self):
        q = self.quota(self.slug, notti=7, ospiti=2)
        self.schema(q, SCHEMA_QUOTE, "POST /api/concierge/quote")
        self.assertEqual(q["money_unit"], "cents_integer", q)
        self.assertEqual(q["alloggio_id"], self.slug, q)
        self.assertEqual(q["notti"], 7, q)
        atteso = oracolo_preventivo(prezzo_notte=25000, notti=7, ospiti=2,
                                    comm_bps=COMM_BPS, sconto_settimana_bps=500,
                                    tassa_pp_notte_cents=200, tassa_max_notti=3)
        self.confronta_oracolo(q, atteso, "contratto quote")
        self.identita_conto(q, "contratto quote")
        self.assertGreater(q["scade_a"], int(time.time()), "il preventivo nasce gia' scaduto")
        self.assertIn(".", q["quote_token"], "il preventivo dev'essere FIRMATO")

    def test_paga_in_struttura_dormiente_e_acceso(self):
        """Blocco 'paga in struttura' (fase188) SEMPRE presente nel preventivo — e' contratto,
        non un extra opzionale. Spento (PAGA_STRUTTURA_ATTIVO!=1) dice onestamente
        accettato=False e non mostra cifre; acceso, i suoi conti tornano al centesimo:
        ospite_paga == totale + fee(1.50 a notte) e anticipo + saldo == ospite_paga."""
        q = self.quota(self.slug, notti=3, ospiti=2)
        self.assertEqual(q["paga_in_struttura"], {"accettato": False},
                         "spento deve dire solo accettato=False: %r" % (q["paga_in_struttura"],))
        self.ambiente("PAGA_STRUTTURA_ATTIVO", "1")
        q = self.quota(self.slug, notti=3, ospiti=2)
        pis = q["paga_in_struttura"]
        self.schema(pis, {"accettato": bool, "ospite_paga_totale_cents": int,
                          "anticipo_online_cents": int, "saldo_in_loco_cents": int,
                          "fee_cents": int}, "paga_in_struttura")
        self.assertIs(pis["accettato"], True, pis)
        self.assertEqual(pis["fee_cents"], 150 * 3, pis)
        self.assertEqual(pis["ospite_paga_totale_cents"], q["totale_cents"] + pis["fee_cents"],
                         "in struttura l'ospite paga il soggiorno + la fee: %r" % (pis,))
        self.assertEqual(pis["anticipo_online_cents"] + pis["saldo_in_loco_cents"],
                         pis["ospite_paga_totale_cents"],
                         "anticipo + saldo non fa il totale (un cent perso): %r" % (pis,))
        self.assertGreater(pis["anticipo_online_cents"], 0, pis)

    def test_paga_in_struttura_presente_anche_se_il_catalogo_salta(self):
        """CONTRATTO STABILE (difetto chiuso alla radice): il blocco 'paga in struttura' e'
        calcolato dentro un try/except fail-safe. Se qualcosa la' dentro solleva (catalogo
        giu', motore fase188 guasto), la chiave NON deve sparire dalla risposta: deve restare
        {"accettato": False}. Prima della correzione il default era scritto DENTRO il try,
        dopo il punto che puo' saltare, quindi un guasto la faceva evaporare e la FORMA del
        JSON cambiava a seconda del guasto.
        VISTA ROSSA: col codice vecchio -> KeyError / chiave assente."""
        import fase188_paga_struttura as ps
        self.ambiente("PAGA_STRUTTURA_ATTIVO", "1")   # cosi' il ramo di calcolo viene percorso
        vero = ps.calcola

        def rotto(*a, **k):
            raise RuntimeError("motore paga-in-struttura giu'")

        ps.calcola = rotto
        try:
            q = self.quota(self.slug, notti=3, ospiti=2)
        finally:
            ps.calcola = vero
        self.assertIn("paga_in_struttura", q,
                      "la chiave e' sparita per via del guasto: %r" % (sorted(q),))
        self.assertEqual(q["paga_in_struttura"], {"accettato": False}, q["paga_in_struttura"])
        # e il preventivo resta comunque valido e firmato (il blocco e' davvero isolato)
        self.assertIn(".", q["quote_token"], "il preventivo dev'essere FIRMATO")
        self.assertGreater(q["totale_cents"], 0, q)

    def test_book_contratto_e_valori(self):
        q = self.quota(self.slug, notti=3, ospiti=2)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "ospite@happy.local",
                       "lang": "it"})
        self.assertEqual(s, 201, b)
        self.schema(b, SCHEMA_BOOK, "POST /api/concierge/book")
        self.assertEqual(b["money_unit"], "cents_integer", b)
        self.assertEqual(b["stato"], "in_attesa_pagamento", b)
        self.assertEqual(len(b["riferimento"]), 24, b)
        self.assertTrue(b["payment_url"].startswith("https://"), b)
        # i numeri del book sono ESATTAMENTE quelli firmati nel preventivo
        for k in ("prezzo_guest_cents", "netto_host_cents", "commissione_cents",
                  "tassa_soggiorno_cents", "totale_cents", "costo_pagamento_cents",
                  "valuta", "alloggio_id", "check_in", "check_out"):
            self.assertEqual(b[k], q[k], "il book cambia '%s' rispetto al preventivo" % k)
        self.assertEqual(b["totale_cents"],
                         b["netto_host_cents"] + b["commissione_cents"]
                         + b["costo_pagamento_cents"] + b["tassa_soggiorno_cents"]
                         - b["sconto_credito_cents"],
                         "il RECORD della prenotazione non riconcilia: %r" % (b,))

    def test_host_prenotazioni_contratto(self):
        q = self.quota(self.slug, notti=2, ospiti=2)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "ospite@happy.local"})
        self.assertEqual(s, 201, b)
        s, p = self.g("GET", "/api/host/prenotazioni", None, self.tok)
        self.assertEqual(s, 200, p)
        self.schema(p, SCHEMA_PRENOTAZIONI, "GET /api/host/prenotazioni")
        self.assertEqual((p["vista"], p["page"], p["totale"], p["pagine"]), ("attive", 1, 1, 1), p)
        self.assertEqual(p["totale_attive"], 1, p)
        self.assertEqual(p["totale_archivio"], 0, p)
        self.assertEqual(len(p["prenotazioni"]), 1, p)
        riga = p["prenotazioni"][0]
        self.schema(riga, SCHEMA_RIGA_PRENOTAZIONE, "riga di /api/host/prenotazioni")
        from fase59_concierge import codice_prenotazione
        self.assertEqual(riga["slug"], self.slug, riga)
        self.assertEqual(riga["check_in"], b["check_in"], riga)
        self.assertEqual(riga["check_out"], b["check_out"], riga)
        self.assertEqual(riga["codice"], codice_prenotazione(b["riferimento"]), riga)
        self.assertEqual(riga["pin"], self.sis.firma.pin_checkin(b["riferimento"]), riga)
        self.assertEqual(riga["stato"], "futura", riga)
        self.assertIs(riga["archiviata"], False, riga)

    def test_host_payout_contratto(self):
        q = self.quota(self.slug, notti=2, ospiti=2)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "ospite@happy.local"})
        self.assertEqual(s, 201, b)
        s, p = self.g("GET", "/api/host/payout", None, self.tok)
        self.assertEqual(s, 200, p)
        self.schema(p, SCHEMA_PAYOUT, "GET /api/host/payout")
        self.assertIn("EUR", p["payout"], p)
        for stato, importo in p["payout"]["EUR"].items():
            self.assertIsInstance(stato, str, p)
            self.assertIsInstance(importo, int, p)
            self.assertNotIsInstance(importo, bool, p)
            self.assertGreaterEqual(importo, 0, p)
        self.assertEqual(p["payout"]["EUR"].get("in_attesa"), b["netto_host_cents"],
                         "il payout atteso dell'host != netto firmato nel preventivo: %r" % (p,))
        self.assertEqual(p["debiti_aperti_cents"], {}, p)

    def test_payout_richiede_autenticazione_host(self):
        """Il contratto vale per l'host AUTENTICATO: senza token nessun dato di cassa."""
        s, _ = self.g("GET", "/api/host/payout")
        self.assertEqual(s, 401)
        s, _ = self.g("GET", "/api/host/prenotazioni")
        self.assertEqual(s, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
