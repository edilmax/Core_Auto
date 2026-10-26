"""
Test Fase 83 - Server HTTP (RouterHTTP puro).

Copre: health/lingue/i18n, catalogo (vuoto/popolato/traduzione servizi per lingua),
dettaglio/404, flusso concierge quote->book via HTTP, MCP JSON-RPC, host pubblica +
disponibilita' (auth X-Host-Key), errori (json invalido/rotta ignota/sistema spento),
mai solleva. Usa un SistemaCasaVIP reale (fase81).
"""
import datetime
import http.client
import io
import json
import os
import re
import shutil
import socket
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.error
from unittest import mock
from urllib.parse import parse_qs, quote, urlencode, urlparse

import fase83_server
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256
from test_blocco_carta import StripeColBlocco
from test_fase203_ical_orologio import _PostoInterno
from test_rimborso_torna_da_ogni_strada import _BancoDelleStrade
from test_fase160_escrow_garanzia import nella_finestra
from test_movimenti_giornale import _BancoDeiBonifici, _StripeDeiBonifici
from test_ritenuta import _Base as _BancoDellaRitenuta
from test_financial_controller import _BancoOffset, HK as _HK_FC, CI as _CI_FC, CO as _CO_FC
from fase83_server import (
    RouterHTTP, crea_router, percorso_statico_sicuro,
    jsonld_alloggio, pagina_alloggio_html, sitemap_xml, robots_txt, _importo,
    _testo_per_registro,
)
import fase59_concierge

# IL PREVENTIVO SI CHIEDE PRIMA DEL SOGGIORNO (lotto D, 2026-10-10): il passato non si vende piu',
# e le date fisse di questo file si quotano con l'orologio del preventivo fermo al 1 gennaio 2026,
# prima di tutte; il resto del sistema resta sull'ora vera.
_PREVENTIVO_PRIMA = mock.patch.object(fase59_concierge, "time",
                                      mock.Mock(time=lambda: 1767225600))


def setUpModule():
    _PREVENTIVO_PRIMA.start()


def tearDownModule():
    _PREVENTIVO_PRIMA.stop()

SEG = b"0123456789abcdef0123456789abcdef"


def _sistema():
    return crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=SEG))


def _fra(giorni):
    """Una data NEL FUTURO scritta come INTENZIONE, non come cifra sul calendario.

    ⛔ Serve dove il test ha bisogno che il soggiorno debba ANCORA ARRIVARE. Le date
    cablate del resto di questo file vanno benissimo dove l'esito non dipende da «e'
    futuro o passato?»; qui invece dipende, e una cifra sul calendario prima o poi passa.
    Misurato il 2026-08-13: `TestRecensioni.test_flusso_completo` sarebbe diventato rosso
    DA SOLO il **2026-09-02**, il giorno in cui il suo check-out ha smesso di essere futuro.
    L'intenzione non scade; una cifra sul calendario si'."""
    import datetime
    return (datetime.date.today() + datetime.timedelta(days=giorni)).isoformat()


def _popola(sys):
    from fase57_vetrina import SchedaAlloggio
    sys.catalogo.pubblica(SchedaAlloggio(host_id="h", slug="casa", titolo="Casa",
                                         citta="Roma", prezzo_notte_cents=10000,
                                         capacita=4, servizi=("wifi", "piscina")))
    for g in ("2026-09-01", "2026-09-02"):
        sys.inventario.imposta_disponibilita("casa", g, unita_totali=1,
                                             prezzo_netto_cents=10000)


class TestBase(unittest.TestCase):
    def setUp(self):
        self.r = crea_router(_sistema())

    def test_health(self):
        s, c = self.r.gestisci("GET", "/api/health")
        self.assertEqual(s, 200)
        self.assertEqual(c["status"], "ok")

    def test_lingue(self):
        s, c = self.r.gestisci("GET", "/api/lingue")
        self.assertIn("it", c["lingue"])
        self.assertIn("en", c["lingue"])

    def test_i18n(self):
        s, c = self.r.gestisci("GET", "/api/i18n", {"lang": "en"})
        self.assertEqual(c["lingua"], "en")
        self.assertEqual(c["ui"]["cerca"], "Search")
        self.assertEqual(c["servizi"]["piscina"], "Pool")

    def test_rotta_ignota(self):
        s, _ = self.r.gestisci("GET", "/api/boh")
        self.assertEqual(s, 404)

    def test_sistema_spento(self):
        r = crea_router(crea_sistema(ConfigCasaVIP(abilitato=False)))
        s, _ = r.gestisci("GET", "/api/health")
        self.assertEqual(s, 503)


class TestIlPulsanteDellaControversia(_BancoDelleStrade):
    """⛔ LE GUARDIE DEL FRENO «ARBITRATO» STANNO QUI, NEL TEST DEDICATO DEL SERVER, perche' e'
    il primo occhio che il Giudice della mutazione accende su `fase83_server.py`: il giro
    `--diff HEAD` del 2026-09-04 ha lasciato 10 mutanti vivi su 16 nelle righe nuove di
    `_rimborso_dovuto_scheda` non perche' fossero scoperte, ma perche' le guardie della catena
    (`test_rimborso_torna_da_ogni_strada`) stanno in fondo all'alfabeto e fuori dagli 8 occhi.
    Una guardia per sopravvissuto, nel file che il Giudice guarda per primo (metodo della
    casella 5). Il banco e' quello delle catene (importato): un solo banco, non due copie.

    Riga per riga (numeri del giro del 4 settembre, invecchiano): `gz is not None`/`stato ==
    "risolto"`/`ospite_rimborso == dovuto`/`arbitrato is None` nel freno delle date/`arbitrato
    is not None` nella riga -> `test_..._HA_il_pulsante`; `and`/`or` nel riconoscimento ->
    `..._cifra_diversa`; `or 0` sulla quota host -> `..._quota_host`; `<=` -> `..._al_centesimo`.
    """

    def _controversia_risolta(self, giorno, email, pi, frazione=3, resto=7):
        ci, co = self.date(giorno)
        b, totale = self.prenota(ci, co, email)
        rif = b["riferimento"]
        self.paga(rif, pi)
        s, _c = self.segnala(b)
        self.assertEqual(s, 200, "PREMESSA NON VALIDA: la contestazione non riesce: %r" % (_c,))
        in_garanzia = int((self.sis.garanzia.stato(rif) or {}).get("importo_host_cents") or 0)
        self.assertGreater(in_garanzia, 0, "PREMESSA NON VALIDA: niente in garanzia")
        deciso = in_garanzia // frazione + resto
        s, out = self.g("POST", "/api/admin/controversia/risolvi",
                        {"riferimento": rif, "rimborso_ospite_cents": deciso},
                        {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, "PREMESSA NON VALIDA: l'arbitrato non riesce: %r" % (out,))
        return rif, pi, deciso, totale, in_garanzia

    def test_la_riga_della_controversia_risolta_HA_il_pulsante_e_manda_la_cifra_esatta(self):
        rif, pi, deciso, _t, _g = self._controversia_risolta(30, "c1@fase83.it", "pi_c1")
        riga = self.riga(rif)
        self.assertIsNotNone(riga)
        self.assertTrue(riga.get("arbitrato"), "la riga non dice di nascere da un arbitrato: %r" % (riga,))
        self.assertTrue(riga.get("bottone"), "manca il pulsante (manca: %r)" % (riga.get("manca"),))
        self.assertNotIn("date_liberate", riga.get("manca") or [])
        s, o = self.premi(rif)
        self.assertEqual((s, o.get("stato"), o.get("importo_cents")), (200, "rimborsato", deciso), o)
        self.assertEqual([(c["payment_intent"], c["importo_cents"]) for c in self.stripe.creazioni],
                         [(pi, deciso)], "il gateway non ha ricevuto ESATTAMENTE la cifra dell'arbitro")

    def test_senza_pulsante_se_la_garanzia_dice_una_cifra_diversa(self):
        rif, _pi, _d, _t, _g = self._controversia_risolta(32, "c2@fase83.it", "pi_c2")
        vero = self.sis.garanzia.stato

        def diversa(pid):
            st = vero(pid)
            return dict(st, ospite_rimborso_cents=int(st["ospite_rimborso_cents"]) + 1) \
                if (st and pid == rif) else st
        self.sis.garanzia.stato = diversa
        try:
            riga = self.riga(rif)
            self.assertFalse(riga.get("arbitrato"))
            self.assertFalse(riga.get("bottone"), "pulsante con una cifra diversa in garanzia: %r" % (riga,))
            self.assertIn("date_liberate", riga.get("manca") or [])
            self.assertEqual(self.premi(rif)[0], 409)
            self.assertEqual(self.stripe.creazioni, [])
        finally:
            self.sis.garanzia.stato = vero

    def test_senza_pulsante_se_quota_host_piu_rimborso_superano_il_pagato(self):
        rif, _pi, _d, _t, _g = self._controversia_risolta(34, "c3@fase83.it", "pi_c3")
        vero = self.sis.garanzia.stato

        def gonfiata(pid):
            st = vero(pid)
            return dict(st, host_riceve_cents=10 ** 9) if (st and pid == rif) else st
        self.sis.garanzia.stato = gonfiata
        try:
            riga = self.riga(rif)
            self.assertTrue(riga.get("arbitrato"))
            self.assertFalse(riga.get("bottone"), "pulsante oltre il pagato: %r" % (riga,))
            self.assertIn("arbitrato_supera_il_pagato", riga.get("manca") or [])
            self.assertEqual(self.premi(rif)[0], 409)
            self.assertEqual(self.stripe.creazioni, [])
        finally:
            self.sis.garanzia.stato = vero

    def test_al_centesimo_quota_host_piu_rimborso_UGUALE_al_pagato_NON_e_una_perdita(self):
        """D16 al confine: uguale al pagato non e' «di piu'». Un `<` al posto di `<=` toglierebbe
        il pulsante proprio al rimborso pieno con host a zero."""
        rif, pi, deciso, _t, _g = self._controversia_risolta(36, "c4@fase83.it", "pi_c4")
        vero = self.sis.garanzia.stato
        riga0 = self.riga(rif)
        pagato = int(riga0.get("pagato_cents") or 0)
        self.assertGreater(pagato, deciso, "PREMESSA NON VALIDA: il pagato deve superare il deciso")

        def al_confine(pid):
            st = vero(pid)
            return dict(st, host_riceve_cents=pagato - deciso) if (st and pid == rif) else st
        self.sis.garanzia.stato = al_confine
        try:
            riga = self.riga(rif)
            self.assertTrue(riga.get("bottone"),
                            "quota host + rimborso == pagato e il pulsante manca: il confine e' "
                            "stato escluso (manca: %r)" % (riga.get("manca"),))
            s, o = self.premi(rif)
            self.assertEqual((s, o.get("importo_cents")), (200, deciso), o)
            self.assertEqual([(c["payment_intent"], c["importo_cents"]) for c in self.stripe.creazioni],
                             [(pi, deciso)])
        finally:
            self.sis.garanzia.stato = vero


class TestCatalogo(unittest.TestCase):
    def setUp(self):
        self.sys = _sistema()
        self.r = crea_router(self.sys)

    def test_vuoto(self):
        s, c = self.r.gestisci("GET", "/api/catalogo", {"citta": "Roma"})
        self.assertEqual(s, 200)
        self.assertEqual(c["totale"], 0)

    def test_popolato_e_traduzione(self):
        _popola(self.sys)
        s, c = self.r.gestisci("GET", "/api/catalogo",
                               {"citta": "Roma", "lang": "en"})
        self.assertEqual(c["totale"], 1)
        card = c["risultati"][0]
        self.assertEqual(card["slug"], "casa")
        self.assertIn("Pool", card["servizi_label"])    # servizi tradotti in EN

    def test_disponibilita_reale(self):
        _popola(self.sys)
        s, c = self.r.gestisci("GET", "/api/catalogo",
                               {"citta": "Roma", "check_in": "2026-09-01",
                                "check_out": "2026-09-02"})
        self.assertTrue(c["risultati"][0]["disponibile"])

    def test_dettaglio(self):
        _popola(self.sys)
        s, c = self.r.gestisci("GET", "/api/catalogo/casa", {"lang": "it"})
        self.assertEqual(s, 200)
        self.assertEqual(c["slug"], "casa")
        self.assertIn("Wi-Fi", c["servizi_label"])

    def test_dettaglio_404(self):
        s, _ = self.r.gestisci("GET", "/api/catalogo/mai-vista")
        self.assertEqual(s, 404)


def _popola_geo(sys):
    """3 alloggi a Roma: uno vicino (~0.7km), uno lontano (~33km), uno senza coordinate."""
    from fase57_vetrina import SchedaAlloggio
    sys.catalogo.pubblica(SchedaAlloggio(host_id="h", slug="vicino", titolo="Vicino",
        citta="Roma", prezzo_notte_cents=10000, capacita=2,
        lat_micro=41905000, lon_micro=12505000))
    sys.catalogo.pubblica(SchedaAlloggio(host_id="h", slug="lontano", titolo="Lontano",
        citta="Roma", prezzo_notte_cents=10000, capacita=2,
        lat_micro=42200000, lon_micro=12500000))
    sys.catalogo.pubblica(SchedaAlloggio(host_id="h", slug="senzageo", titolo="SenzaGeo",
        citta="Roma", prezzo_notte_cents=10000, capacita=2))


class TestGeoVicino(unittest.TestCase):
    """'Vicino a me': centro ~Piazza (41.90, 12.50), ordina per distanza, taglia al raggio."""
    def setUp(self):
        self.sys = _sistema()
        _popola_geo(self.sys)
        self.r = crea_router(self.sys)

    def _q(self, **kw):
        base = {"lat_micro": "41900000", "lon_micro": "12500000"}
        base.update({k: str(v) for k, v in kw.items()})
        return self.r.gestisci("GET", "/api/catalogo", base)

    def test_vicino_entro_raggio(self):
        s, c = self._q(raggio_km="5")
        self.assertEqual(s, 200)
        self.assertEqual(c["ordine"], "vicinanza")
        self.assertEqual([x["slug"] for x in c["risultati"]], ["vicino"])
        self.assertGreater(c["risultati"][0]["distanza_m"], 0)

    def test_raggio_ampio_ordina_per_distanza(self):
        s, c = self._q(raggio_km="60")
        slugs = [x["slug"] for x in c["risultati"]]
        self.assertEqual(slugs[0], "vicino")             # il piu' vicino in cima
        self.assertIn("lontano", slugs)
        self.assertNotIn("senzageo", slugs)              # senza coordinate -> escluso
        d = [x["distanza_m"] for x in c["risultati"]]
        self.assertEqual(d, sorted(d))                   # distanze crescenti
        self.assertEqual(c["totale"], 2)

    def test_senza_geo_ricerca_normale(self):
        s, c = self.r.gestisci("GET", "/api/catalogo", {"citta": "Roma"})
        self.assertEqual(c["totale"], 3)
        self.assertEqual(c.get("ordine"), "consigliati")   # default: i migliori in cima
        for x in c["risultati"]:
            self.assertNotIn("distanza_m", x)

    def test_coord_invalide_ignorate(self):
        s, c = self.r.gestisci("GET", "/api/catalogo",
                               {"lat_micro": "999999999", "lon_micro": "12500000"})
        self.assertEqual(s, 200)
        self.assertEqual(c["totale"], 3)                 # geo fuori Terra -> ricerca normale
        for x in c["risultati"]:
            self.assertNotIn("distanza_m", x)


class TestPayout(unittest.TestCase):
    """Dashboard payout host (fase131 cablato): un book registra il maturato per l'host."""
    def setUp(self):
        self.sys = _sistema()
        _popola(self.sys)
        # FAIL-CLOSED (ordine del fondatore 2026-09-18): il router senza HOST_KEY non apre
        # piu' l'API host. Questi test guardano la LOGICA del payout, non l'accesso:
        # entrano con la chiave condivisa dell'operatore.
        self.r = crea_router(self.sys, host_key="hk")

    def _book(self):
        s, c = self.r.gestisci("POST", "/api/concierge/quote", body=json.dumps(
            {"alloggio_id": "casa", "check_in": "2026-09-01", "check_out": "2026-09-02"}))
        s2, c2 = self.r.gestisci("POST", "/api/concierge/book", body=json.dumps(
            {"quote_token": c["quote_token"], "email": "g@x.it"}))
        self.assertEqual(s2, 201)

    def test_payout_dopo_book(self):
        self._book()
        s, c = self.r.gestisci("GET", "/api/host/payout", {"host_id": "h"},
                               headers={"X-Host-Key": "hk"})
        self.assertEqual(s, 200)
        self.assertIn("EUR", c["payout"])
        self.assertGreater(c["payout"]["EUR"].get("maturato", 0), 0)   # netto host atteso

    def test_payout_host_id_mancante(self):
        s, c = self.r.gestisci("GET", "/api/host/payout", {},
                               headers={"X-Host-Key": "hk"})
        self.assertEqual(s, 422)


class TestSplitPreview(unittest.TestCase):
    """Dividi tra amici (fase133): quote uguali a conservazione esatta."""
    def setUp(self):
        self.r = crea_router(_sistema())

    def test_split_conservazione(self):
        s, c = self.r.gestisci("POST", "/api/split/preview",
                               body=json.dumps({"totale_cents": 10000, "n": 3}))
        self.assertEqual(s, 200)
        self.assertEqual(sum(c["quote"]), 10000)        # conservazione esatta
        self.assertEqual(c["quote"], [3334, 3333, 3333])

    def test_split_invalido(self):
        s, c = self.r.gestisci("POST", "/api/split/preview",
                               body=json.dumps({"totale_cents": 100, "n": 0}))
        self.assertEqual(s, 400)


class TestContratto(unittest.TestCase):
    """Contratto PDF (fase145) precompilato dal voucher firmato."""
    def setUp(self):
        self.sys = _sistema()
        _popola(self.sys)
        self.r = crea_router(self.sys)

    def test_contratto_da_voucher(self):
        s, c = self.r.gestisci("POST", "/api/concierge/quote", body=json.dumps(
            {"alloggio_id": "casa", "check_in": "2026-09-01", "check_out": "2026-09-02"}))
        s2, c2 = self.r.gestisci("POST", "/api/concierge/book", body=json.dumps(
            {"quote_token": c["quote_token"], "email": "g@x.it"}))
        self.assertEqual(s2, 201)
        vt = c2.get("voucher_token")
        self.assertTrue(vt)
        s3, c3 = self.r.gestisci("POST", "/api/contratto", body=json.dumps({"voucher_token": vt}))
        self.assertEqual(s3, 200)
        self.assertTrue(c3["pdf_base64"].startswith("JVBER"))   # '%PDF' in base64
        self.assertTrue(any("BookinVIP" in r for r in c3["righe"]))

    def test_contratto_voucher_invalido(self):
        s, c = self.r.gestisci("POST", "/api/contratto",
                               body=json.dumps({"voucher_token": "x.y"}))
        self.assertEqual(s, 400)


class TestDomandaWaitlist(unittest.TestCase):
    """Cold-start: una email valida si registra SEMPRE; città vuota non blocca; errore onesto."""
    def setUp(self):
        self.r = crea_router(_sistema())

    def test_email_valida_citta_vuota_ok(self):       # regressione del bug live
        s, c = self.r.gestisci("POST", "/api/domanda",
                               body=json.dumps({"email": "roxincubo@gmail.com", "citta": ""}))
        self.assertEqual(s, 201)
        self.assertTrue(c["ok"])

    def test_email_valida_con_citta_ok(self):
        s, c = self.r.gestisci("POST", "/api/domanda",
                               body=json.dumps({"email": "a@b.com", "citta": "Torino"}))
        self.assertEqual(s, 201)

    def test_email_invalida_422(self):
        s, c = self.r.gestisci("POST", "/api/domanda",
                               body=json.dumps({"email": "nonvalida", "citta": "Torino"}))
        self.assertEqual(s, 422)
        self.assertEqual(c["errore"], "email_non_valida")


class TestConcierge(unittest.TestCase):
    def setUp(self):
        self.sys = _sistema()
        _popola(self.sys)
        self.r = crea_router(self.sys)

    def test_quote_e_book(self):
        s, c = self.r.gestisci("POST", "/api/concierge/quote", body=json.dumps(
            {"alloggio_id": "casa", "check_in": "2026-09-01", "check_out": "2026-09-02"}))
        self.assertEqual(s, 200)
        token = c["quote_token"]
        s2, c2 = self.r.gestisci("POST", "/api/concierge/book", body=json.dumps(
            {"quote_token": token, "email": "g@x.it"}))
        self.assertEqual(s2, 201)
        self.assertEqual(c2["stato"], "confermata")

    def test_quote_confronto_ota(self):
        s, c = self.r.gestisci("POST", "/api/concierge/quote", body=json.dumps(
            {"alloggio_id": "casa", "check_in": "2026-09-01", "check_out": "2026-09-02"}))
        self.assertEqual(s, 200)
        co = c.get("confronto_ota")
        self.assertIsNotNone(co)                                  # confronto presente
        self.assertEqual(co["nostro_totale_cents"], c["prezzo_guest_cents"])
        self.assertGreater(co["ota_totale_cents"], co["nostro_totale_cents"])
        self.assertGreater(co["risparmio_guest_cents"], 0)

    def test_json_invalido(self):
        s, c = self.r.gestisci("POST", "/api/concierge/quote", body="{rotto")
        self.assertEqual(s, 400)


class TestMarketing(unittest.TestCase):
    def setUp(self):
        self.sys = _sistema()
        self.r = crea_router(self.sys, admin_key="adm")

    def test_campagna_admin(self):
        # senza canali env -> genera ma salta (niente rete); con stub -> pubblica
        from fase90_marketing import CanaleStub
        self.sys.marketing._canali = {"telegram": CanaleStub(), "instagram": CanaleStub()}
        s, c = self.r.gestisci("POST", "/api/marketing/campagna",
                               headers={"X-Admin-Key": "adm"},
                               body=json.dumps({"lingue": ["it", "en"]}))
        self.assertEqual(s, 200)
        self.assertEqual(c["post_generati"], 6)        # 3 temi x 2 lingue
        self.assertEqual(c["pubblicati"], 6)

    def test_campagna_auth(self):
        s, _ = self.r.gestisci("POST", "/api/marketing/campagna", body="{}")
        self.assertEqual(s, 401)


class TestMotori(unittest.TestCase):
    def setUp(self):
        # il sistema si TIENE: serve `firma` per coniare il voucher che le rotte dello
        # split ora pretendono (vedi la nota sopra i due collaudi dello split)
        self.sis = _sistema()
        self.r = crea_router(self.sis)

    def test_tassa_zero_default(self):
        s, c = self.r.gestisci("GET", "/api/tassa",
                               {"citta": "roma", "notti": "3", "ospiti": "2"})
        self.assertEqual(s, 200)
        self.assertEqual(c["tassa_cents"], 0)          # nessuna regola env -> 0
        self.assertEqual(c["money_unit"], "cents_integer")

    # ⛔ AGGIORNATI IL 2026-08-20 PERCHE' E' CAMBIATO IL REQUISITO, NON PERCHE' ERANO SBAGLIATI.
    # `/api/split/crea` e `/api/split/paga` erano rotte pubbliche che SCRIVEVANO senza chiedere
    # chi fosse chi chiama (pezzo B del piano). Ora vogliono il voucher firmato, e la
    # prenotazione la prendono DA LI'. Questi collaudi provano il motore attraverso le rotte:
    # quello che cambia e' che ora si presentano con l'identita', come fara' l'ospite vero.
    # La serratura in se' la sorveglia `TestLoSPLITNONSIMUOVESENZAIDENTITA`, in fondo al file.
    def _voucher(self, rif="p1", allog="casa"):
        return self.sis.firma.codifica({"tipo": "voucher", "riferimento": rif,
                                        "alloggio_id": allog})

    def test_split_crea_paga_completa(self):
        # conto da 9000 diviso fra 3 -> 3000 ciascuno
        tk = self._voucher()
        s, c = self.r.gestisci("POST", "/api/split/crea", body=json.dumps(
            {"voucher_token": tk, "totale_cents": 9000,
             "partecipanti": ["a", "b", "c"]}))
        self.assertEqual(s, 201)
        cid = c["conto_id"]
        # a e b pagano
        for p in ("a", "b"):
            sp, cp = self.r.gestisci("POST", "/api/split/paga", body=json.dumps(
                {"conto_id": cid, "partecipante_id": p, "voucher_token": tk}))
            self.assertEqual(sp, 200)
            self.assertFalse(cp["completato"])
        # c paga -> completato
        sp, cp = self.r.gestisci("POST", "/api/split/paga", body=json.dumps(
            {"conto_id": cid, "partecipante_id": "c", "voucher_token": tk}))
        self.assertTrue(cp["completato"])
        # replay idempotente
        sp2, cp2 = self.r.gestisci("POST", "/api/split/paga", body=json.dumps(
            {"conto_id": cid, "partecipante_id": "c", "voucher_token": tk}))
        self.assertTrue(cp2["idempotente"])
        # stato
        ss, st = self.r.gestisci("GET", "/api/split/stato", {"conto_id": cid})
        self.assertEqual(st["totale_cents"], 9000)

    def test_split_conto_invalido(self):
        """Con l'identita' AL POSTO GIUSTO: il 422 deve arrivare per il conto senza
        partecipanti, non per il voucher mancante — altrimenti questo collaudo direbbe verde
        per il motivo sbagliato."""
        s, _ = self.r.gestisci("POST", "/api/split/crea", body=json.dumps(
            {"voucher_token": self._voucher(), "totale_cents": 1000,
             "partecipanti": []}))
        self.assertEqual(s, 422)


class TestWebhookStripe(unittest.TestCase):
    def test_webhook_valido(self):
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        from fase87_stripe_webhook import firma_di_test
        sys = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=SEG,
                                         stripe_webhook_secret="whsec_x"))
        r = crea_router(sys)
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata": {"riferimento": "R1"}}}})
        import time
        h = {"Stripe-Signature": firma_di_test(payload, "whsec_x", int(time.time()))}
        s, c = r.gestisci("POST", "/api/payments/webhook", body=payload, headers=h)
        self.assertEqual(s, 200)
        self.assertEqual(c["tipo"], "checkout.session.completed")

    def test_webhook_firma_invalida(self):
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        sys = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=SEG,
                                         stripe_webhook_secret="whsec_x"))
        r = crea_router(sys)
        s, _ = r.gestisci("POST", "/api/payments/webhook", body="{}",
                          headers={"Stripe-Signature": "t=1,v1=falso"})
        self.assertEqual(s, 400)

    def test_webhook_non_configurato(self):
        r = crea_router(_sistema())     # nessun webhook secret
        s, _ = r.gestisci("POST", "/api/payments/webhook", body="{}")
        self.assertEqual(s, 503)


class TestMCP(unittest.TestCase):
    def test_jsonrpc(self):
        r = crea_router(_sistema())
        s, c = r.gestisci("POST", "/api/mcp", body=json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))
        self.assertEqual(s, 200)
        self.assertEqual(len(c["result"]["tools"]), 6)


class TestTrasparenza(unittest.TestCase):
    def test_confronto(self):
        r = crea_router(_sistema())
        s, c = r.gestisci("GET", "/api/trasparenza",
                          {"prezzo_cents": "10000", "ota": "booking"})
        self.assertEqual(s, 200)
        self.assertEqual(c["money_unit"], "cents_integer")
        # con Booking l'host netta meno che con noi -> guadagno extra positivo
        self.assertGreater(c["guadagno_extra_host_cents"], 0)

    def test_prezzo_invalido(self):
        r = crea_router(_sistema())
        s, c = r.gestisci("GET", "/api/trasparenza", {"prezzo_cents": "abc"})
        self.assertEqual(s, 200)
        self.assertEqual(c["guadagno_extra_host_cents"], 0)


class TestHost(unittest.TestCase):
    def setUp(self):
        self.sys = _sistema()
        self.r = crea_router(self.sys, host_key="segreto-host")

    def test_pubblica_e_disponibilita(self):
        h = {"X-Host-Key": "segreto-host"}
        s, c = self.r.gestisci("POST", "/api/host/pubblica", body=json.dumps(
            {"host_id": "h1", "slug": "nuovo", "titolo": "Nuovo", "citta": "Milano",
             "prezzo_notte_cents": 12000, "capacita": 2}), headers=h)
        self.assertEqual(s, 201)
        s2, c2 = self.r.gestisci("POST", "/api/host/disponibilita", body=json.dumps(
            {"alloggio_id": "nuovo", "giorno": "2026-10-01", "unita_totali": 1,
             "prezzo_netto_cents": 12000}), headers=h)
        self.assertEqual(s2, 200)
        self.assertTrue(self.sys.inventario.disponibile("nuovo", "2026-10-01",
                                                        "2026-10-02"))

    def test_auth_mancante(self):
        s, _ = self.r.gestisci("POST", "/api/host/disponibilita",
                               body=json.dumps({"alloggio_id": "x", "giorno": "2026-10-01",
                                                "unita_totali": 1,
                                                "prezzo_netto_cents": 100}))
        self.assertEqual(s, 401)

    def test_scheda_invalida(self):
        h = {"X-Host-Key": "segreto-host"}
        s, c = self.r.gestisci("POST", "/api/host/pubblica",
                               body=json.dumps({"slug": "x"}), headers=h)
        self.assertEqual(s, 422)


class TestDashboardHost(unittest.TestCase):
    def setUp(self):
        self.sys = _sistema()
        _popola(self.sys)
        self.r = crea_router(self.sys, host_key="hk")
        self.h = {"X-Host-Key": "hk"}

    def test_metriche(self):
        # prenota 1 notte
        q = self.r.gestisci("POST", "/api/concierge/quote", body=json.dumps(
            {"alloggio_id": "casa", "check_in": "2026-09-01", "check_out": "2026-09-02"}))
        self.r.gestisci("POST", "/api/concierge/book", body=json.dumps(
            {"quote_token": q[1]["quote_token"], "email": "g@x.it"}))
        s, c = self.r.gestisci("GET", "/api/host/metriche", {"alloggio": "casa"},
                               headers=self.h)
        self.assertEqual(s, 200)
        self.assertEqual(c["revenue_cents"], 10000)        # 1 notte x 10000
        self.assertEqual(c["prenotazioni_attive"], 1)
        self.assertEqual(c["money_unit"], "cents_integer")
        self.assertGreater(c["occupazione_bps"], 0)

    def test_auth(self):
        s, _ = self.r.gestisci("GET", "/api/host/metriche")
        self.assertEqual(s, 401)

    def test_calendario(self):
        q = self.r.gestisci("POST", "/api/concierge/quote", body=json.dumps(
            {"alloggio_id": "casa", "check_in": "2026-09-01", "check_out": "2026-09-02"}))
        self.r.gestisci("POST", "/api/concierge/book", body=json.dumps(
            {"quote_token": q[1]["quote_token"], "email": "g@x.it"}))
        s, c = self.r.gestisci("GET", "/api/host/calendario",
                               {"alloggio": "casa", "da": "2026-09-01", "a": "2026-09-03"},
                               headers=self.h)
        self.assertEqual(s, 200)
        stati = {g["giorno"]: g["stato"] for g in c["giorni"]}
        self.assertEqual(stati["2026-09-01"], "pieno")        # prenotato
        self.assertEqual(stati["2026-09-02"], "libero")       # caricato da _popola

    def test_calendario_campi(self):
        s, _ = self.r.gestisci("GET", "/api/host/calendario", {"alloggio": "casa"},
                               headers=self.h)
        self.assertEqual(s, 422)

    def test_export_csv(self):
        q = self.r.gestisci("POST", "/api/concierge/quote", body=json.dumps(
            {"alloggio_id": "casa", "check_in": "2026-09-01", "check_out": "2026-09-02"}))
        self.r.gestisci("POST", "/api/concierge/book", body=json.dumps(
            {"quote_token": q[1]["quote_token"], "email": "g@x.it"}))
        s, c = self.r.gestisci("GET", "/api/host/export", {"alloggio": "casa"},
                               headers=self.h)
        self.assertEqual(s, 200)
        csv = c["csv"]
        self.assertIn("alloggio,check_in,check_out,notti", csv)   # header
        self.assertIn("casa,2026-09-01,2026-09-02,1", csv)        # riga
        self.assertIn("100.00", csv)                              # revenue (1 notte x 10000)
        self.assertIn("attiva", csv)

    def test_export_auth(self):
        s, _ = self.r.gestisci("GET", "/api/host/export")
        self.assertEqual(s, 401)

    def test_alloggi_host_e_stato(self):
        # _popola pubblica slug 'casa' con host_id 'h'
        s, c = self.r.gestisci("GET", "/api/host/alloggi", {"host_id": "h"},
                               headers=self.h)
        self.assertEqual(s, 200)
        self.assertEqual({a["slug"] for a in c["alloggi"]}, {"casa"})
        self.assertEqual(c["alloggi"][0]["stato"], "pubblicato")
        # sospendi
        s2, _ = self.r.gestisci("POST", "/api/host/stato", headers=self.h,
                                body=json.dumps({"slug": "casa", "stato": "sospeso"}))
        self.assertEqual(s2, 200)
        # ora non e' piu' in vetrina
        cat = self.r.gestisci("GET", "/api/catalogo", {"citta": "Roma"})
        self.assertEqual(cat[1]["totale"], 0)
        # ma resta tra i miei alloggi
        _, c3 = self.r.gestisci("GET", "/api/host/alloggi", {"host_id": "h"},
                                headers=self.h)
        self.assertEqual(c3["alloggi"][0]["stato"], "sospeso")

    def test_stato_invalido(self):
        s, _ = self.r.gestisci("POST", "/api/host/stato", headers=self.h,
                               body=json.dumps({"slug": "casa", "stato": "online"}))
        self.assertEqual(s, 422)


class TestSelfServiceHost(unittest.TestCase):
    def setUp(self):
        self.sys = _sistema()
        self.r = crea_router(self.sys, host_key="operatore")

    def test_registra_login_pubblica_solo_miei(self):
        s, c = self.r.gestisci("POST", "/api/host/registrazione", body=json.dumps(
            {"email": "mario@bnb.it", "password": "passwordlunga",
             "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True, "ragione_sociale": "B&B Mario"}))
        self.assertEqual(s, 201)
        token, hid = c["token"], c["host_id"]
        h = {"X-Host-Token": token}
        # col token pubblica: host_id forzato al suo anche se ne passa un altro
        s2, _ = self.r.gestisci("POST", "/api/host/pubblica", headers=h, body=json.dumps(
            {"host_id": "IMPOSTORE", "slug": "casa-mario", "titolo": "Casa Mario",
             "citta": "Bari", "prezzo_notte_cents": 8000, "capacita": 2}))
        self.assertEqual(s2, 201)
        _, miei = self.r.gestisci("GET", "/api/host/alloggi", {"host_id": hid}, headers=h)
        self.assertEqual({a["slug"] for a in miei["alloggi"]}, {"casa-mario"})
        # col token il parametro host_id è IGNORATO (il token vince): non puoi vedere gli
        # alloggi di un ALTRO host passando il suo id -> vedi sempre e solo i TUOI.
        _, imp = self.r.gestisci("GET", "/api/host/alloggi", {"host_id": "IMPOSTORE"},
                                 headers=h)
        self.assertEqual({a["slug"] for a in imp["alloggi"]}, {"casa-mario"})

    def test_token_invalido_bloccato(self):
        s, _ = self.r.gestisci("POST", "/api/host/pubblica",
                               headers={"X-Host-Token": "falso.token"},
                               body=json.dumps({"slug": "x", "titolo": "x", "citta": "x",
                                                "prezzo_notte_cents": 1000, "capacita": 1,
                                                "host_id": "h"}))
        self.assertEqual(s, 401)

    def test_login(self):
        self.r.gestisci("POST", "/api/host/registrazione", body=json.dumps(
            {"email": "l@b.it", "password": "passwordlunga", "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True}))
        s, c = self.r.gestisci("POST", "/api/host/login", body=json.dumps(
            {"email": "l@b.it", "password": "passwordlunga"}))
        self.assertEqual(s, 200)
        self.assertTrue(c["token"])
        s2, _ = self.r.gestisci("POST", "/api/host/login", body=json.dumps(
            {"email": "l@b.it", "password": "sbagliata"}))
        self.assertEqual(s2, 401)

    def test_viral_referral(self):
        # host A si registra e prende il suo link
        a = self.r.gestisci("POST", "/api/host/registrazione", body=json.dumps(
            {"email": "a@b.it", "password": "passwordlunga", "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True}))[1]
        ha = {"X-Host-Token": a["token"]}
        s, ref = self.r.gestisci("GET", "/api/host/referral", headers=ha)
        self.assertEqual(s, 200)
        self.assertIn("ref=", ref["link"])
        self.assertEqual(ref["credito_cents"], 0)
        codice = ref["codice"]
        # host B si registra COL codice di A -> entrambi accreditati
        b = self.r.gestisci("POST", "/api/host/registrazione", body=json.dumps(
            {"email": "b@b.it", "password": "passwordlunga", "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
             "codice_referral": codice}))[1]
        self.assertTrue(b["referral"]["ok"])
        self.assertGreater(b["referral"]["credito_cents"], 0)   # B: credito di benvenuto al signup
        # A NON prende credito al signup di B: lo riceve solo quando B si QUALIFICA (3 prenotazioni).
        # Mai in perdita: prima l'invitato produce, poi il referente viene premiato.
        _, ref2 = self.r.gestisci("GET", "/api/host/referral", headers=ha)
        self.assertEqual(ref2["credito_cents"], 0)

    def test_registrazione_termini(self):
        """Da 2026-07-20 il rifiuto avviene A MONTE sui 3 consensi obbligatori (contratto,
        clausole vessatorie ex artt. 1341-1342 c.c., privacy GDPR): l'errore ora e'
        `consensi_mancanti` e dice QUALI mancano."""
        s, c = self.r.gestisci("POST", "/api/host/registrazione", body=json.dumps(
            {"email": "x@b.it", "password": "passwordlunga", "accetta_termini": False}))
        self.assertEqual(s, 422)
        self.assertEqual(c["errore"], "consensi_mancanti")
        self.assertIn("accetta_termini", c["mancanti"])

    def test_un_consenso_NEGATO_come_stringa_non_e_un_consenso(self):
        """Trovato dalla chat A il 2026-09-07 (`collaudi/esame_legale.py`): le spunte erano
        giudicate con `bool(v)`, e per Python `bool("false")` e `bool("0")` sono VERI. Un
        client che manda `"accetta_clausole": "false"` otteneva 201, l'account nasceva e la
        prova firmata archiviava `vessatorie: True`: un consenso NEGATO registrato come dato.
        Il browser nostro manda booleani veri: la porta la apriva solo chi chiama l'API a mano,
        ma la prova firmata e' quella che si porta davanti a un giudice. Vale solo `True`."""
        for falso in ("false", "0", "no", 1, "true"):
            s, c = self.r.gestisci("POST", "/api/host/registrazione", body=json.dumps(
                {"email": "falso@b.it", "password": "passwordlunga", "accetta_termini": True,
                 "accetta_clausole": falso, "accetta_privacy": True}))
            self.assertEqual(s, 422, "accetta_clausole=%r ha risposto %s %s" % (falso, s, c))
            self.assertEqual(c["errore"], "consensi_mancanti")
            self.assertIn("accetta_clausole", c["mancanti"])
        # e nessun account e' nato da quei tentativi
        s, c = self.r.gestisci("POST", "/api/host/login", body=json.dumps(
            {"email": "falso@b.it", "password": "passwordlunga"}))
        self.assertNotEqual(s, 200, c)
        # stessa regola alla ri-accettazione
        s, c = self.r.gestisci("POST", "/api/host/registrazione", body=json.dumps(
            {"email": "vero@b.it", "password": "passwordlunga", "accetta_termini": True,
             "accetta_clausole": True, "accetta_privacy": True}))
        self.assertEqual(s, 201, c)
        h = {"X-Host-Token": c["token"]}
        s, c = self.r.gestisci("POST", "/api/host/riaccetta", headers=h, body=json.dumps(
            {"accetta_termini": True, "accetta_clausole": "false", "accetta_privacy": True}))
        self.assertEqual(s, 422, c)
        self.assertIn("accetta_clausole", c.get("mancanti", []))


class TestOnboarding(unittest.TestCase):
    def setUp(self):
        self.sys = _sistema()
        self.r = crea_router(self.sys, host_key="hk")
        self.h = {"X-Host-Key": "hk"}
        # ⛔ 2026-09-15: l'annuncio ORA deve ESISTERE prima che gli si apra il calendario.
        # Fino a quel giorno queste prove scrivevano giorni sotto un nome mai pubblicato —
        # cioe' proprio il difetto che il fondatore ha trovato dal pannello: il sistema
        # rispondeva «✅» e i giorni finivano sotto un nome che nessuno possiede
        # (`fase83_server._alloggio_in_catalogo`). Con l'annuncio pubblicato,
        # `test_range_invalido` torna a misurare il RANGE, non l'assenza dell'annuncio.
        # ⛔ L'host_id va nel CORPO: con la sola chiave da operatore non c'e' un token da cui
        # ricavarlo (`_host_pubblica`: `hid = self._host_id_da_token(headers)`, e senza token
        # resta quello del corpo). Misurato il 2026-09-16: senza, la rotta risponde
        # `422 scheda_non_valida / host_id_non_valido` e l'annuncio non nasce.
        st, _c = self.r.gestisci("POST", "/api/host/pubblica", headers=self.h, body=json.dumps(
            {"slug": "casa", "titolo": "Casa", "citta": "Roma", "host_id": "h_onboarding0001",
             "prezzo_notte_cents": 9000, "capacita": 2}))
        self.assertIn(st, (200, 201), _c)   # premessa del banco: senza annuncio non si misura

    def test_apri_periodo(self):
        s, c = self.r.gestisci("POST", "/api/host/disponibilita_range", headers=self.h,
                               body=json.dumps({"alloggio_id": "casa", "da": "2026-09-01",
                                                "a": "2026-09-05", "unita_totali": 1,
                                                "prezzo_netto_cents": 9000}))
        self.assertEqual(s, 200)
        self.assertEqual(c["giorni_impostati"], 4)        # 01..04 (05 escluso)
        self.assertTrue(self.sys.inventario.disponibile("casa", "2026-09-01",
                                                        "2026-09-03"))

    def test_range_invalido(self):
        s, _ = self.r.gestisci("POST", "/api/host/disponibilita_range", headers=self.h,
                               body=json.dumps({"alloggio_id": "casa", "da": "2026-09-05",
                                                "a": "2026-09-01", "unita_totali": 1,
                                                "prezzo_netto_cents": 9000}))
        self.assertEqual(s, 422)

    def test_ical_blocca_dopo_apertura(self):
        # 1) apri il periodo
        self.r.gestisci("POST", "/api/host/disponibilita_range", headers=self.h,
                        body=json.dumps({"alloggio_id": "casa", "da": "2026-09-01",
                                         "a": "2026-09-05", "unita_totali": 1,
                                         "prezzo_netto_cents": 9000}))
        # 2) importa iCal: il 02-03 e' occupato su Airbnb
        ics = ("BEGIN:VEVENT\nDTSTART;VALUE=DATE:20260902\nDTEND;VALUE=DATE:20260903\n"
               "END:VEVENT")
        s, c = self.r.gestisci("POST", "/api/host/ical", headers=self.h,
                               body=json.dumps({"alloggio_id": "casa", "ical": ics}))
        self.assertEqual(s, 200)
        self.assertEqual(c["giorni_bloccati"], 1)
        # il 02 ora NON e' disponibile; il 01 si'
        self.assertFalse(self.sys.inventario.disponibile("casa", "2026-09-02", "2026-09-03"))
        self.assertTrue(self.sys.inventario.disponibile("casa", "2026-09-01", "2026-09-02"))

    def test_ical_auth(self):
        s, _ = self.r.gestisci("POST", "/api/host/ical",
                               body=json.dumps({"alloggio_id": "casa", "ical": "x"}))
        self.assertEqual(s, 401)


class TestPathStatico(unittest.TestCase):
    def test_normali(self):
        import os
        for p, atteso in (("/", "index.html"), ("", "index.html"),
                          ("/host.html", "host.html"), ("/sw.js", "sw.js"),
                          ("/manifest.json", "manifest.json")):
            r = percorso_statico_sicuro(p, "deploy")
            self.assertIsNotNone(r)
            self.assertEqual(os.path.basename(r), atteso)

    def test_traversal_neutralizzato(self):
        import os
        # qualunque '../' o path assoluto -> resta DENTRO la cartella (mai /etc/passwd)
        for bad in ("/../../etc/passwd", "/../../../secret", "/..\\..\\windows"):
            r = percorso_statico_sicuro(bad, "deploy")
            if r is not None:
                self.assertTrue(os.path.realpath(r).startswith(
                    os.path.realpath("deploy")))
                self.assertNotIn("etc", os.path.dirname(r))

    def test_dotfile_e_nul_negati(self):
        import os
        # un basename che inizia con '.' (dotfile) e' negato
        self.assertIsNone(percorso_statico_sicuro("/.env", "deploy"))
        self.assertIsNone(percorso_statico_sicuro("/.htaccess", "deploy"))
        self.assertIsNone(percorso_statico_sicuro("/x\x00.html", "deploy"))
        self.assertIsNone(percorso_statico_sicuro(123, "deploy"))
        # '/.git/config' -> basename 'config' (benigno): resta DENTRO deploy/ (poi 404)
        r = percorso_statico_sicuro("/.git/config", "deploy")
        self.assertTrue(os.path.realpath(r).startswith(os.path.realpath("deploy")))

    # ------------------------------------------------------------------------------
    # IL BOMBARDAMENTO, e perche' e' diventato una guardia permanente
    # ------------------------------------------------------------------------------
    ATTACCHI = (
        "../fase83_server.py", "../../etc/passwd", "....//....//etc/passwd",
        "..\\..\\windows\\win.ini", "/etc/passwd", "C:\\Windows\\win.ini",
        "%2e%2e%2f%2e%2e%2fetc%2fpasswd", "..%2f..%2fetc%2fpasswd",
        "deploy/../../.env", "index.html/../../../.env.casavip", ".env",
        "\x00../../.env", "sub/../../../.env", "..%00/../.env",
        "/proc/self/environ", "..;/..;/etc/passwd", "./../.env",
        "uploads/../../../../../../etc/shadow",
    )

    def test_DICIOTTO_ATTACCHI_E_NESSUNO_ESCE_DALLA_CARTELLA(self):
        """⛔ NASCE DA SEI ALLARMI GRAVI, il 2026-08-18.

        CodeQL segnalava **6 `py/path-injection` gravi** nei due punti che servono i file.
        Prima di dichiararli falsi ho bombardato la funzione con i modi noti di uscire da una
        cartella: nessuno esce. Ma una prova fatta **a mano una volta** non protegge niente --
        domani qualcuno «semplifica» questa funzione e la prova non c'e' piu'. Quindi il
        bombardamento diventa una guardia che gira a ogni commit.

        💡 E c'e' un motivo in piu' per cui deve stare qui: la via facile per far tacere
        quell'allarme sarebbe **sostituire `commonpath` con `startswith`**, che CodeQL
        riconosce ma e' PIU' DEBOLE (`/base` e `/basement` cominciano uguali). Sarebbe
        appagare l'analizzatore peggiorando la difesa. Questa guardia rende quella scorciatoia
        impossibile da prendere in silenzio.
        """
        import os
        base = os.path.realpath("deploy")
        fughe = []
        for attacco in self.ATTACCHI:
            esito = percorso_statico_sicuro(attacco, "deploy")
            if esito is None:
                continue                      # rifiutato: va benissimo
            reale = os.path.realpath(esito)
            if not (reale == base or reale.startswith(base + os.sep)):
                fughe.append((attacco, reale))
        self.assertEqual(
            [], fughe,
            "QUESTI PERCORSI ESCONO DALLA CARTELLA CONSENTITA: %r.\n        E' un "
            "path-traversal vero: da li' si leggono file che non devono essere leggibili "
            "(.env, chiavi, database)." % (fughe,))

    def test_I_FILE_LEGITTIMI_CONTINUANO_A_FUNZIONARE(self):
        """L'altra meta': una difesa che rifiuta tutto sarebbe verde qui sopra e romperebbe
        il sito. Senza questa, `return None` sempre passerebbe il bombardamento a pieni voti."""
        import os
        for buono in ("/", "", "/index.html", "/app.js", "/host.html", "/manifest.json"):
            with self.subTest(percorso=buono):
                esito = percorso_statico_sicuro(buono, "deploy")
                self.assertIsNotNone(
                    esito, "%r e' un file legittimo del sito e viene rifiutato: la difesa "
                           "ha rotto il prodotto" % buono)
                self.assertTrue(os.path.realpath(esito).startswith(os.path.realpath("deploy")))


class TestAdmin(unittest.TestCase):
    def setUp(self):
        self.sys = _sistema()
        _popola(self.sys)
        self.r = crea_router(self.sys, admin_key="adm")
        self.h = {"X-Admin-Key": "adm"}

    def _prenota(self):
        q = self.r.gestisci("POST", "/api/concierge/quote", body=json.dumps(
            {"alloggio_id": "casa", "check_in": "2026-09-01", "check_out": "2026-09-02"}))
        b = self.r.gestisci("POST", "/api/concierge/book", body=json.dumps(
            {"quote_token": q[1]["quote_token"], "email": "g@x.it"}))
        return b[1]

    def test_elenco_e_rimborso(self):
        self._prenota()
        s, c = self.r.gestisci("GET", "/api/admin/prenotazioni", headers=self.h)
        self.assertEqual(s, 200)
        self.assertEqual(len(c["prenotazioni"]), 1)
        pren = c["prenotazioni"][0]
        self.assertFalse(pren["rimborsato"])
        # rimborsa (libera le date)
        s2, c2 = self.r.gestisci("POST", "/api/admin/rimborso", headers=self.h,
            body=json.dumps({"alloggio_id": pren["alloggio_id"],
                             "check_in": pren["check_in"], "check_out": pren["check_out"],
                             "idem_key": pren["idem_key"]}))
        self.assertEqual(s2, 200)
        self.assertEqual(c2["stato"], "rimborsato")
        # le date sono di nuovo disponibili
        self.assertTrue(self.sys.inventario.disponibile("casa", "2026-09-01",
                                                        "2026-09-02"))
        # ora risulta rimborsato nell'elenco
        _, c3 = self.r.gestisci("GET", "/api/admin/prenotazioni", headers=self.h)
        self.assertTrue(c3["prenotazioni"][0]["rimborsato"])

    def test_LA_LISTA_ADMIN_PORTA_IL_VOUCHER_DI_OGNI_PRENOTAZIONE(self):
        """D12 della prova vera (29/9, bbb00577): l'email di conferma non e' arrivata (casella
        dell'ospite piena) e l'ospite non aveva NESSUNA strada per cancellare, fare il check-in
        o scrivere all'host: il collegamento esisteva solo dentro il record. L'admin lo deve
        vedere, per mandarglielo da un altro canale. Senza pagamento con noi, niente."""
        pp, inv = self.sys.pagamenti_pendenti, self.sys.inventario
        giorni = [_fra(60 + i) for i in range(3)]
        for g in giorni:
            inv.imposta_disponibilita("casa", g, unita_totali=1, prezzo_netto_cents=10000)
        idem = "v" * 30
        self.assertTrue(inv.blocca("casa", giorni[0], giorni[1], idem_key=idem,
                                   origine="concierge").ok)
        self.assertTrue(pp.registra(idem[:24], alloggio_id="casa", check_in=giorni[0],
                                    check_out=giorni[1], idem_key=idem,
                                    corpo_json=json.dumps({"voucher_token": "tok.firmato-1"})))
        self.assertTrue(inv.blocca("casa", giorni[1], giorni[2], idem_key="w" * 30,
                                   origine="ical").ok)           # nessun pagamento con noi
        s, c = self.r.gestisci("GET", "/api/admin/prenotazioni", headers=self.h)
        self.assertEqual(s, 200, c)
        per_chiave = {p["idem_key"]: p for p in c["prenotazioni"]}
        self.assertEqual(per_chiave[idem].get("voucher_url"),
                         "https://bookinvip.com/voucher/tok.firmato-1")
        self.assertEqual(per_chiave["w" * 30].get("voucher_url"), "")

    def test_LA_LISTA_ADMIN_VA_A_PAGINE_E_DICE_LO_STATO_VERO(self):
        """D15 e D16 della prova vera del 29/9. La lista conosceva due stati soli, letti dal
        calendario: «rimborsato» se c'era il rilascio, «attiva» altrimenti. Cosi' una
        prenotazione MAI pagata e in attesa usciva «attiva» col pulsante Rimborsa, e una
        scaduta senza pagamento usciva «rimborsato». E arrivava tutta in una volta (limit
        100 fisso): «diventa un pannello lungo chilometri». Qui ogni stato vero del
        pagamento, le pagine, il totale, e il pulsante SOLO dove ci sono soldi da rendere."""
        import time as _t
        pp, inv = self.sys.pagamenti_pendenti, self.sys.inventario
        self.assertIsNotNone(pp)
        giorni = [_fra(40 + i) for i in range(11)]
        for g in giorni:
            inv.imposta_disponibilita("casa", g, unita_totali=1, prezzo_netto_cents=10000)
        attesi = {}

        def prenota(i, lettera, stato_atteso, pendente=True):
            idem = lettera * 30
            self.assertTrue(inv.blocca("casa", giorni[i], giorni[i + 1], idem_key=idem,
                                       origine="concierge").ok)
            if pendente:
                self.assertTrue(pp.registra(idem[:24], alloggio_id="casa",
                                            check_in=giorni[i], check_out=giorni[i + 1],
                                            idem_key=idem))
            attesi[idem] = stato_atteso
            return idem[:24]

        prenota(0, "a", "in_attesa")
        self.assertTrue(pp.scadi(prenota(1, "b", "scaduto")))
        pp.conferma(prenota(2, "c", "pagata"))
        rif = prenota(3, "d", "bloccata_sulla_carta")
        pp.conferma(rif)
        self.assertTrue(pp.segna_blocco(rif, blocco_pi="pi_prova_d",
                                        blocco_incassa_dal_ts=int(_t.time()) + 172800))
        rif = prenota(4, "e", "annullata")
        pp.conferma(rif)
        self.assertTrue(pp.segna_blocco(rif, blocco_pi="pi_prova_e",
                                        blocco_annullato_ts=int(_t.time())))
        self.assertTrue(pp.marca_da_rimborsare(rif))
        rif = prenota(5, "f", "rimborsata")
        pp.conferma(rif)
        self.assertTrue(pp.marca_da_rimborsare(rif))
        prenota(6, "g", "attiva", pendente=False)            # nessun pagamento con noi
        prenota(7, "h", "chiusa", pendente=False)
        inv.rilascia("casa", giorni[7], giorni[8], idem_key="h" * 30)
        # PAGATA DOPO UN RI-BLOCCO (pagamento tardivo): la chiave del calendario diventa
        # «reblock:<riferimento>», e il riferimento NON sono i suoi primi 24 caratteri. La
        # suite intera del 29/9 sera l'ha preso (test_host_metriche_isolamento) prima di me.
        rif_r, idem_r = "i" * 24, "reblock:" + "i" * 24
        self.assertTrue(inv.blocca("casa", giorni[9], giorni[10], idem_key=idem_r,
                                   origine="concierge").ok)
        self.assertTrue(pp.registra(rif_r, alloggio_id="casa", check_in=giorni[9],
                                    check_out=giorni[10], idem_key=idem_r))
        pp.conferma(rif_r)
        attesi[idem_r] = "pagata"

        s, c = self.r.gestisci("GET", "/api/admin/prenotazioni", headers=self.h)
        self.assertEqual(s, 200)
        visti = {p["idem_key"]: p for p in c["prenotazioni"]}
        self.assertEqual({k: p["stato"] for k, p in visti.items()}, attesi)
        rimborsabili = {k for k, p in visti.items() if p["rimborsabile"] is True}
        self.assertEqual(rimborsabili, {"c" * 30, "d" * 30, "g" * 30, idem_r},
                         "il pulsante Rimborsa va SOLO dove i soldi ci sono (o non passano "
                         "da noi): mai su una in attesa, scaduta, annullata o gia' chiusa")
        self.assertIn("rimborsato", visti["a" * 30])         # il campo di prima resta
        self.assertEqual(c["totale"], 9)

        pagine = []
        for n in (1, 2, 3):
            s, c = self.r.gestisci("GET", "/api/admin/prenotazioni",
                                   {"page": str(n), "limit": "4"}, headers=self.h)
            self.assertEqual(s, 200)
            self.assertEqual((c["pagina"], c["per_pagina"], c["totale"]), (n, 4, 9))
            pagine.append([p["idem_key"] for p in c["prenotazioni"]])
        self.assertEqual([len(p) for p in pagine], [4, 4, 1])
        self.assertEqual(sorted(sum(pagine, [])), sorted(attesi))
        _, c = self.r.gestisci("GET", "/api/admin/prenotazioni", {"limit": "100000"},
                               headers=self.h)
        self.assertEqual(c["per_pagina"], 100, "una pagina non puo' scaricare il mondo")

    def test_auth_mancante(self):
        s, _ = self.r.gestisci("GET", "/api/admin/prenotazioni")
        self.assertEqual(s, 401)
        s2, _ = self.r.gestisci("POST", "/api/admin/rimborso",
                                body=json.dumps({"alloggio_id": "x", "check_in": "a",
                                                 "check_out": "b", "idem_key": "k"}))
        self.assertEqual(s2, 401)

    def test_rimborso_campi_invalidi(self):
        s, _ = self.r.gestisci("POST", "/api/admin/rimborso", headers=self.h,
                               body=json.dumps({"alloggio_id": "x"}))
        self.assertEqual(s, 422)


class TestRecensioni(unittest.TestCase):
    def setUp(self):
        self.sys = _sistema()
        _popola(self.sys)
        # ⛔ QUI IL SOGGIORNO DEVE ESSERE NEL FUTURO, e non e' un dettaglio: il diritto di
        # recensione nasce con `nbf = check-out`, quindi `test_flusso_completo` pretende
        # `troppo_presto`. Con le date cablate (2026-09-01/02) quel «troppo presto» sarebbe
        # diventato falso da solo il 2026-09-02. La disponibilita' si carica sugli stessi
        # giorni relativi: se no il soggiorno cade fuori dal periodo aperto e il test
        # diventerebbe rosso per un motivo nuovo, inventato dalla riparazione.
        self.ci, self.co = _fra(20), _fra(21)
        for g in (self.ci, self.co):
            self.sys.inventario.imposta_disponibilita("casa", g, unita_totali=1,
                                                      prezzo_netto_cents=10000)
        self.r = crea_router(self.sys)

    def _prenota(self):
        q = self.r.gestisci("POST", "/api/concierge/quote", body=json.dumps(
            {"alloggio_id": "casa", "check_in": self.ci, "check_out": self.co}))
        b = self.r.gestisci("POST", "/api/concierge/book", body=json.dumps(
            {"quote_token": q[1]["quote_token"], "email": "g@x.it"}))
        return b

    def test_book_emette_diritto(self):
        _, corpo = self._prenota()
        self.assertIn("diritto_recensione", corpo)

    def test_book_invia_email_voucher(self):
        # inietto un provider email con send-stub e una base_url
        from fase86_email import ProviderEmail
        inviate = []
        self.sys.email_provider = ProviderEmail(
            "smtp.x", 587, "u", "pw", "no-reply@bookinvip.com",
            send=lambda dest, ogg, html: (inviate.append((dest, ogg, html)) or True))
        r = crea_router(self.sys, base_url="https://bookinvip.com")
        q = r.gestisci("POST", "/api/concierge/quote", body=json.dumps(
            {"alloggio_id": "casa", "check_in": "2026-09-01", "check_out": "2026-09-02"}))
        r.gestisci("POST", "/api/concierge/book", body=json.dumps(
            {"quote_token": q[1]["quote_token"], "email": "g@x.it"}))
        self.assertEqual(len(inviate), 1)
        self.assertEqual(inviate[0][0], "g@x.it")
        self.assertIn("https://bookinvip.com/voucher/", inviate[0][2])  # link nel corpo

    def test_book_senza_email_provider_non_crasha(self):
        # nessun provider email -> book funziona uguale (default)
        self.sys.email_provider = None
        _, corpo = self._prenota()
        self.assertEqual(corpo["stato"], "confermata")

    def test_book_emette_voucher_e_pass(self):
        _, corpo = self._prenota()
        self.assertIn("voucher_token", corpo)
        self.assertIn("smart_pass", corpo)
        # lo smart-pass e' un vero pass d'ingresso verificabile (fase64)
        from fase64_smartpass import VerificatorePass
        from fase83_server import _importo  # noqa
        # l'orologio finto del verificatore deve stare sul giorno del CHECK-IN vero di
        # questa classe: prima era la stessa cifra cablata, adesso e' la stessa intenzione
        ver = VerificatorePass(self.sys.firma, orologio=lambda: __import__(
            "fase64_smartpass")._epoch_da_data_ora(self.ci, 16))
        self.assertTrue(ver.verifica(corpo["smart_pass"], "casa").consentito)

    def test_pagina_voucher(self):
        # GATE STATO-PAGAMENTO (fondatore): senza pagamento CONFERMATO, il voucher NON espone il PIN
        # reale né i tasti di controversia — solo riepilogo + invito a pagare. (Il caso PAGATO->PIN
        # sbloccato è provato in test_email_ciclo con setup di pagamento completo.)
        # ⛔ IL PIN SI CERCA COME *RIGA DEL PIN*, NON COME QUATTRO CIFRE NUDE (2026-09-15).
        # Quel giorno la CI e' andata ROSSA su questo test: il PIN casuale del giro era
        # «1967» e coincideva con l'ultimo gruppo del codice prenotazione «BVIP-F279-1967»
        # — il sito non esponeva niente. Una pagina e' piena di cifre e un PIN di quattro ci
        # finisce dentro per caso (~1 su 1500, misurato il 2026-08-15): il prodotto lo sa
        # gia' e la sua rete difensiva cerca `riga_pin_voucher`, che esiste apposta. Questo
        # test era l'ultimo pezzo rimasto col confronto ingenuo. Un falso allarme e' un
        # difetto quanto un allarme mancato (regola ferrea 10).
        from fase59_concierge import codice_prenotazione
        from fase83_server import pagina_voucher_html, riga_pin_voucher
        _, corpo = self._prenota()
        rif = corpo["riferimento"]
        pin = self.sys.firma.pin_checkin(rif)
        h = pagina_voucher_html(self.sys, corpo["voucher_token"], "it")
        self.assertIn("Prenotazione confermata", h)
        self.assertIn(codice_prenotazione(rif), h)         # codice leggibile BVIP-XXXX-XXXX
        self.assertIn("PIN check-in", h)                   # l'etichetta c'è...
        # PREMESSA: la forma cercata deve contenere davvero il PIN, se no «non lo trovo»
        # sarebbe vero per il motivo sbagliato (una guardia che cerca una forma vuota).
        self.assertIn(pin, riga_pin_voucher(pin))
        self.assertNotIn(riga_pin_voucher(pin), h)         # ...ma il PIN REALE no (bloccato pre-pagamento)
        self.assertIn(riga_pin_voucher("\U0001F512"), h)   # al suo posto c'è il lucchetto
        self.assertNotIn("/api/garanzia/", h)              # nessun tasto controversia pre-pagamento
        self.assertIn("Completa il pagamento", h)
        self.assertIn("BookinVIP", h)

    def test_voucher_manomesso_404(self):
        from fase83_server import pagina_voucher_html
        self.assertIsNone(pagina_voucher_html(self.sys, "falso.token"))
        self.assertIsNone(pagina_voucher_html(self.sys, "non-token"))

    def test_flusso_completo(self):
        _, corpo = self._prenota()
        # NBF (2026-07-20, stile Booking/Agoda): il diritto emesso al book porta
        # nbf=check-out -> recensire PRIMA del soggiorno e' troppo_presto
        s0, c0 = self.r.gestisci("POST", "/api/recensioni", body=json.dumps(
            {"token": corpo["diritto_recensione"], "voto": 5}))
        self.assertEqual(s0, 400)
        self.assertEqual(c0.get("motivo"), "troppo_presto")
        # DOPO il check-out (diritto maturo, stessa firma di sistema): ammessa
        import time as _t
        from fase63_recensioni import EmettitoreDiritto
        diritto = EmettitoreDiritto(self.sys.firma).emetti(
            corpo["riferimento"], "casa", non_prima_ts=int(_t.time()) - 60)
        s, c = self.r.gestisci("POST", "/api/recensioni", body=json.dumps(
            {"token": diritto, "voto": 5, "testo": "Ottimo", "lingua": "it"}))
        self.assertEqual(s, 201)
        self.assertTrue(c["verificata"])
        # riepilogo + elenco
        s2, c2 = self.r.gestisci("GET", "/api/recensioni/casa")
        self.assertEqual(c2["riepilogo"]["conteggio"], 1)
        self.assertEqual(c2["riepilogo"]["media_centesimi"], 500)
        self.assertEqual(len(c2["recensioni"]), 1)
        # la scheda in vetrina ora porta il riepilogo
        s3, c3 = self.r.gestisci("GET", "/api/catalogo", {"citta": "Roma"})
        self.assertEqual(c3["risultati"][0]["recensioni"]["conteggio"], 1)

    def test_recensione_senza_diritto(self):
        s, c = self.r.gestisci("POST", "/api/recensioni", body=json.dumps(
            {"token": "falso.token", "voto": 5}))
        self.assertEqual(s, 400)
        self.assertFalse(c["ok"])

    def test_jsonld_aggregate_rating(self):
        _, corpo = self._prenota()
        # diritto MATURO (nbf passato): la recensione entra solo post-soggiorno
        import time as _t
        from fase63_recensioni import EmettitoreDiritto
        maturo = EmettitoreDiritto(self.sys.firma).emetti(
            corpo["riferimento"], "casa", non_prima_ts=int(_t.time()) - 60)
        self.r.gestisci("POST", "/api/recensioni", body=json.dumps(
            {"token": maturo, "voto": 4}))
        from fase83_server import pagina_alloggio_html
        h = pagina_alloggio_html(self.sys, "casa")
        self.assertIn("aggregateRating", h)
        self.assertIn("4.00", h)

    def test_disattivate(self):
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        sys = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=SEG,
                                         con_recensioni=False))
        r = crea_router(sys)
        s, _ = r.gestisci("GET", "/api/recensioni/casa")
        self.assertEqual(s, 503)


class TestSEO(unittest.TestCase):
    def setUp(self):
        self.sys = _sistema()
        _popola(self.sys)

    def test_euro_no_float(self):
        """Si chiamava `_euro` e non sapeva in che valuta stesse scrivendo: su un
        annuncio in yen produceva "540.00" per Y54.000, anche dentro il JSON-LD che
        finisce nei risultati di Google. Ora vuole la valuta, e la rispetta."""
        self.assertEqual(_importo(9500, "EUR"), "95.00")
        self.assertEqual(_importo(9999, "EUR"), "99.99")
        self.assertEqual(_importo(5, "EUR"), "0.05")
        self.assertEqual(_importo(54000, "JPY"), "54000")   # niente decimali
        self.assertEqual(_importo(25500, "KWD"), "25.500")  # tre decimali
        # importo negativo: si azzera invece di stampare un meno su una pagina pubblica
        self.assertEqual(_importo(-1, "EUR"), "0.00")
        self.assertEqual(_importo(-1, "JPY"), "0")

    def test_jsonld(self):
        d = self.sys.catalogo.dettaglio("casa")
        ld = jsonld_alloggio(d, "https://x.it")
        self.assertEqual(ld["@type"], "Apartment")
        self.assertEqual(ld["name"], "Casa")
        self.assertEqual(ld["offers"]["price"], "100.00")     # 10000 cents
        self.assertEqual(ld["url"], "https://x.it/alloggio/casa")
        self.assertTrue(any(a["name"] == "piscina" for a in ld["amenityFeature"]))

    def test_pagina_html(self):
        h = pagina_alloggio_html(self.sys, "casa", "https://x.it")
        self.assertIn("<title>Casa - BookinVIP</title>", h)
        self.assertIn("application/ld+json", h)
        self.assertIn("100.00", h)
        self.assertIn('rel="canonical"', h)

    def test_pagina_html_404(self):
        self.assertIsNone(pagina_alloggio_html(self.sys, "mai-vista"))

    def test_html_escaping(self):
        from fase57_vetrina import SchedaAlloggio
        self.sys.catalogo.pubblica(SchedaAlloggio(host_id="h", slug="xss",
            titolo="<script>alert(1)</script>", citta="Roma",
            prezzo_notte_cents=5000, capacita=2))
        h = pagina_alloggio_html(self.sys, "xss")
        self.assertNotIn("<script>alert(1)</script>", h)      # iniezione neutralizzata
        self.assertIn("&lt;script&gt;", h)

    def test_sitemap(self):
        import re
        xml = sitemap_xml(self.sys, "https://x.it")
        self.assertIn("https://x.it/alloggio/casa", xml)
        self.assertIn("urlset", xml)
        # <lastmod> reale per scheda (data di aggiornamento) → budget di scansione
        self.assertRegex(xml, r"<lastmod>\d{4}-\d{2}-\d{2}</lastmod>")

    def test_robots(self):
        r = robots_txt("https://x.it")
        self.assertIn("Sitemap: https://x.it/sitemap.xml", r)

    def test_registro_inventario_guida_sitemap_host(self):
        from fase83_server import _citta_inventario
        from fase97_inbound_seo import registro_citta, sitemap_inbound
        inv = _citta_inventario(self.sys)               # self.sys ha "casa" a Roma
        self.assertIn("Roma", inv)
        reg = registro_citta(inv)
        xml = sitemap_inbound("https://x.it", citta=reg)
        self.assertIn("/affitta/roma", xml)             # città con inventario nella sitemap
        # helper blindato: un sistema senza catalogo valido → [] (mai eccezione)
        self.assertEqual(_citta_inventario(object()), [])

    def test_etag_conditional_get(self):
        from fase83_server import etag_di, etag_combacia
        a = etag_di(b"ciao")
        self.assertEqual(a, etag_di(b"ciao"))                 # deterministico sul contenuto
        self.assertNotEqual(a, etag_di(b"ciaoo"))             # cambia col contenuto
        self.assertTrue(a.startswith('"') and a.endswith('"'))
        self.assertTrue(etag_combacia(a, a))                  # match esatto
        self.assertTrue(etag_combacia(a, '"x", %s , "y"' % a))  # dentro una lista
        self.assertTrue(etag_combacia(a, "*"))                # wildcard
        self.assertFalse(etag_combacia(a, ""))                # nessun If-None-Match
        self.assertFalse(etag_combacia(a, '"altro"'))         # non combacia


class TestRobustezza(unittest.TestCase):
    def test_mai_solleva(self):
        r = crea_router(_sistema())
        for m, p, b in (("GET", "/api/catalogo", None), ("POST", "/api/mcp", None),
                        ("POST", "/api/concierge/quote", None), ("GET", None, None)):
            try:
                r.gestisci(m, p or "/api/x", {}, b)
            except Exception as e:  # pragma: no cover
                self.fail(f"sollevato su {m} {p}: {e}")


class TestLIndirizzoDiChiChiamaEUnaFORMANonTestoLibero(unittest.TestCase):
    """🕵️ CHI CHIAMA SCEGLIE IL PROPRIO INDIRIZZO, E QUEL VALORE FINISCE NEI DOCUMENTI FISCALI.

    **Il fatto, misurato il 2026-08-18.** `RouterHTTP._client_ip` prende il primo elemento
    di `X-Forwarded-For` e lo restituisce **cosi' com'e'**, troncato a 64 caratteri. Nessun
    controllo di forma. Ma nginx **aggiunge in coda** il proprio valore a quello che arriva
    dal client (`proxy_add_x_forwarded_for`), quindi il PRIMO elemento -- proprio quello che
    prendiamo noi -- lo scrive **chi chiama**.

    ⛔ E non e' un problema di registro soltanto. Quel valore, misurato sui 31 usi nel file:
      1. **il registro** (una trentina di righe) -- si fabbricano righe di allarme false
         proprio dove il Guardiano (fase186) cerca i guasti sui soldi;
      2. **il conteggio dei limiti di frequenza** (`ip = self._client_ip(headers)`) -- e
         questo e' il peggiore: cambiando intestazione a ogni richiesta si finisce in un
         secchiello nuovo ogni volta, cioe' **il limite si aggira**;
      3. **gli estratti fiscali e legali** (`genera_estratto_csv(ip=...)`, il report DAC7) --
         testo scelto da un estraneo dentro un documento che ha valore legale.

    💡 **La riparazione giusta e' una sola per tutt'e tre: un indirizzo IP e' una FORMA, non
    testo libero.** Si convalida con `ipaddress` della libreria standard; se non e' un
    indirizzo, si restituisce un **marcatore fisso** invece delle parole dell'estraneo. Per
    ogni indirizzo legittimo il comportamento resta identico: cambia solo sul percorso
    d'attacco, e nel verso giusto.

    ⛔ E il marcatore dev'essere **UNO SOLO** per tutti i valori inventati: e' quello che
    chiude il buco n.2. Se due spazzature diverse producessero due chiavi diverse, il limite
    di frequenza resterebbe aggirabile esattamente come prima.
    """

    def _ip(self, valore):
        return RouterHTTP._client_ip({"X-Forwarded-For": valore})

    VERI = ("203.0.113.9", "8.8.8.8", "127.0.0.1", "2001:db8::1", "::1",
            "::ffff:203.0.113.9", "fe80::1")

    INVENTATI = ("unknown", "203.0.113.9 FALSO", "'; DROP TABLE prenotazioni; --",
                 "<script>alert(1)</script>", "999.999.999.999", "A" * 300,
                 "203.0.113.9\nERROR:core_auto.server:RIMBORSO MAI PARTITO",
                 "203.0.113.9\r\nCRITICAL: cassa a zero", "%s%r{}", "../../etc/passwd")

    def test_UN_INDIRIZZO_VERO_PASSA_INTATTO(self):
        """Il metro prima del muro: se la convalida storpiasse gli indirizzi buoni, il
        rimedio sarebbe peggio del male (i registri e i limiti perderebbero senso)."""
        for buono in self.VERI:
            with self.subTest(ip=buono):
                self.assertEqual(
                    buono, self._ip(buono),
                    "un indirizzo legittimo non deve cambiare: la convalida serve a togliere "
                    "il testo inventato, non a riscrivere i dati veri")

    def test_UN_VALORE_INVENTATO_NON_ARRIVA_MAI_INTATTO(self):
        for finto in self.INVENTATI:
            with self.subTest(valore=finto[:40]):
                uscita = self._ip(finto)
                self.assertNotIn(
                    finto.strip()[:20], uscita,
                    "il testo scelto da chi chiama e' arrivato fino in fondo: da li' si "
                    "fabbricano righe di registro false e si scrive dentro gli estratti "
                    "fiscali (uscita: %r)" % (uscita,))

    def test_NESSUN_A_CAPO_PUO_USCIRE_DA_QUI(self):
        """L'invariante che chiude il log-injection alla sorgente, per tutte e trenta le
        righe di registro in un colpo solo."""
        for finto in self.INVENTATI + self.VERI:
            with self.subTest(valore=finto[:40]):
                uscita = self._ip(finto)
                self.assertEqual(
                    len(uscita.splitlines()), 1,
                    "da un solo indirizzo sono uscite %d righe (%r): il registro si puo' "
                    "ancora falsificare" % (len(uscita.splitlines()), uscita))

    def test_DUE_SPAZZATURE_DIVERSE_FINISCONO_NELLO_STESSO_SECCHIELLO(self):
        """⛔ LA GUARDIA DEL BUCO PIU' GRAVE. Il limite di frequenza conta per chiave: se
        ogni valore inventato producesse una chiave diversa, basterebbe cambiare
        intestazione a ogni richiesta per non essere mai contati."""
        chiavi = {self._ip(v) for v in self.INVENTATI}
        self.assertEqual(
            1, len(chiavi),
            "valori inventati diversi producono %d chiavi diverse (%r): il limite di "
            "frequenza si aggira cambiando intestazione a ogni richiesta"
            % (len(chiavi), sorted(chiavi)[:5]))

    def test_SENZA_INTESTAZIONE_NON_SI_INVENTA_NIENTE(self):
        """Nessuna intestazione non e' un attacco: e' assenza di informazione, e va detta
        com'e'. Cambiare anche questo comportamento allargherebbe la riparazione oltre il
        difetto (regola ferrea 15)."""
        self.assertEqual("", RouterHTTP._client_ip({}))
        self.assertEqual("", RouterHTTP._client_ip(None))

    def test_LA_CATENA_DEI_PROXY_PRENDE_L_ULTIMO_E_LO_CONVALIDA(self):
        """⛔ CAMBIATA DICHIARANDOLO il 2026-10-08 (V2 della busta 6, confermato da GML nel
        Compito 52). Fino a quel giorno questa prova si chiamava «PRENDE_IL_PRIMO» e
        pretendeva proprio il difetto: il primo elemento lo scrive chi chiama, e nginx mette
        il NOSTRO in coda (`proxy_add_x_forwarded_for`). Adesso pretende l'ultimo, che e'
        l'unico scritto da un proxy nostro (MDN, «X-Forwarded-For», trusted proxy count),
        e la stessa convalida di forma."""
        self.assertEqual("172.16.0.1", self._ip("203.0.113.9, 10.0.0.1, 172.16.0.1"))
        self.assertNotIn("cattivo", self._ip("10.0.0.1, cattivo"))


class TestLIndirizzoELUltimoQuelloCheScriveIlNostroNginx(unittest.TestCase):
    """🌐 V2 (busta 6, 2026-10-05; MEDIA, confermato da GML nel Compito 52): CHI CHIAMA
    SCEGLIEVA IL PROPRIO INDIRIZZO.

    **Il fatto, misurato sul server vivo il 2026-10-08.** Davanti all'app c'e' UN solo proxy,
    il contenitore `casavip_nginx` con `deploy/nginx.casavip.ssl.conf`, che fa
    `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for`: prende cio' che il client
    ha mandato e ci AGGIUNGE IN CODA l'indirizzo vero da cui e' arrivata la connessione. Il
    DNS punta dritto al server (niente Cloudflare) e nginx vede indirizzi pubblici (400
    righe del suo registro: 0 privati). Quindi l'ULTIMO elemento e' il solo che non sceglie
    chi chiama; `_client_ip` prendeva il PRIMO.

    ⛔ Cosa si poteva fare: cambiare il primo elemento a ogni tentativo e non finire MAI nel
    buttafuori (chiave admin, accessi host e operatori, bunker); mettere un indirizzo
    inventato nelle prove legali dei consensi; ingannare il legame della sessione bunker
    all'indirizzo. La convalida di forma del 2026-08-18 non bastava: un indirizzo FINTO ma
    ben formato la passa.

    Fonti (D25): MDN «X-Forwarded-For» («Any security-related use of X-Forwarded-For (such
    as for rate limiting or IP-based access control) must only use IP addresses added by a
    trusted proxy»; con N proxy fidati si conta da DESTRA); Adam Pritchard, «The perils of
    the "real" client IP», 2022 («Danger on the left, trust on the right»).
    """

    def setUp(self):
        self.r = crea_router(_sistema(), host_key="hk", admin_key="ak")

    def _admin(self, chiave, xff):
        s, _ = self.r.gestisci("GET", "/api/admin/alloggi", {}, None,
                               {"X-Admin-Key": chiave, "X-Forwarded-For": xff})
        return s

    def test_IL_PRIMO_ELEMENTO_INVENTATO_NON_DIVENTA_L_INDIRIZZO(self):
        self.assertEqual("198.51.100.7",
                         RouterHTTP._client_ip({"X-Forwarded-For": "1.2.3.4, 198.51.100.7"}))

    def test_CAMBIARE_IL_PRIMO_ELEMENTO_NON_CAMBIA_LA_CHIAVE_DEL_BUTTAFUORI(self):
        chiavi = {RouterHTTP._client_ip({"X-Forwarded-For": "10.9.%d.%d, 198.51.100.7"
                                         % (i // 250, i % 250)}) for i in range(300)}
        self.assertEqual({"198.51.100.7"}, chiavi,
                         "trecento prefissi inventati hanno prodotto %d chiavi diverse: il "
                         "limite di frequenza si aggira cambiando intestazione" % len(chiavi))

    def test_LA_CHIAVE_ADMIN_A_RAFFICA_NON_SI_AGGIRA_CAMBIANDO_IL_PRIMO_ELEMENTO(self):
        """Il danno vero, sul router vero: otto chiavi sbagliate dallo STESSO indirizzo,
        ognuna con un primo elemento diverso, devono chiudere fuori quell'indirizzo -- anche
        quando al nono colpo arriva la chiave giusta (come `test_rate_limit_login`)."""
        vero = "198.51.100.7"
        self.assertNotEqual(401, self._admin("ak", "203.0.113.50"),
                            "premessa: la chiave giusta da un indirizzo pulito deve entrare")
        for i in range(8):
            self.assertEqual(401, self._admin("chiave-sbagliata", "10.0.0.%d, %s" % (i, vero)))
        self.assertEqual(401, self._admin("ak", "10.0.0.99, %s" % vero),
                         "otto chiavi sbagliate dallo stesso indirizzo vero e quello non e' "
                         "chiuso fuori: il buttafuori conta il primo elemento, che sceglie "
                         "chi chiama")


def _deve(condizione, *dettaglio):
    """Premessa della preparazione (S7): un'eccezione esplicita, non `assert`."""
    if not condizione:
        raise AssertionError("premessa non valida: %r" % (dettaglio,))


def _porta_libera():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class TestAprireIlLinkNonDecideNiente(unittest.TestCase):
    """📬 V4 (busta 6, 2026-10-05; MEDIA, confermato da GML nel Compito 52): UNA GET DECIDEVA.

    **Il fatto.** `GET /host/azione?t=...` -- il link «Approva»/«Rifiuta» che arriva all'host
    per email, Telegram o WhatsApp -- ESEGUIVA la decisione nel momento stesso in cui veniva
    aperto. Ma un link in un messaggio lo aprono anche le MACCHINE: i filtri antispam e
    antivirus delle caselle aziendali, le anteprime dei link nelle chat. Il primo che lo
    apriva decideva al posto dell'host: una prenotazione approvata (date bloccate, ospite
    avvisato) o rifiutata (cliente perso) senza che nessuno avesse toccato niente.

    **Il contratto.** Aprire il link (GET, e HEAD che passa da `do_GET`) MOSTRA soltanto la
    domanda con un pulsante; decide solo il pulsante, con un POST che porta lo stesso
    gettone firmato. Fonti (D25): MDN, «Safe (HTTP Methods)» («an application should not
    allow GET requests to alter its state»; «Browsers can call safe methods [...] pre-fetching
    [...] Web crawlers also rely on calling safe methods»); RFC 8058 (2017), perche' la
    disiscrizione in un clic e' un POST: «anti-spam software often fetches all resources in
    mail header fields automatically, without any action by the user».

    ⛔ Sta QUI, nel test dedicato di fase83, e non in `test_azione_richiesta.py`: il Giudice
    della mutazione accende per primo `test_fase83_server` e poi i primi in ordine alfabetico
    fra chi importa il modulo -- li', in CI, nessun guasto di queste righe sarebbe stato visto.
    """

    @classmethod
    def setUpClass(cls):
        cls._env_prec = {k: os.environ.get(k) for k in ("MARCA_TEMPORALE", "UPLOAD_DIR",
                                                         "PAGE_GATE")}
        cls.dir = d = tempfile.mkdtemp()
        os.environ["MARCA_TEMPORALE"] = "0"
        os.environ["UPLOAD_DIR"] = d + "/uploads"
        os.environ.pop("PAGE_GATE", None)
        cls.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, con_registrazione_host=True,
            db_catalogo=d + "/c.db", db_inventario=d + "/i.db", db_registro_host=d + "/r.db",
            db_accettazioni=d + "/acc.db", db_pendenti=d + "/p.db"))
        cls.r = crea_router(cls.sis, host_key="hk", base_url="https://bookinvip.com")
        s, c = cls._g("POST", "/api/host/registrazione",
                      {"email": "h@sim.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        _deve(s == 201, s, c)
        cls.hid, tok = c["host_id"], c["token"]
        s, p = cls._g("POST", "/api/host/pubblica",
                      {"slug": "casa-get", "titolo": "Casa GET", "citta": "Roma",
                       "prezzo_notte_cents": 10000, "capacita": 2,
                       "modalita_prenotazione": "su_richiesta"}, {"X-Host-Token": tok})
        _deve(s == 201, s, p)
        oggi = datetime.date.today()
        s, _ = cls._g("POST", "/api/host/disponibilita_range",
                      {"alloggio_id": "casa-get",
                       "da": (oggi + datetime.timedelta(days=10)).isoformat(),
                       "a": (oggi + datetime.timedelta(days=80)).isoformat(),
                       "unita_totali": 1, "prezzo_netto_cents": 10000}, {"X-Host-Token": tok})
        _deve(s == 200, s)
        cls.porta = _porta_libera()
        threading.Thread(
            target=fase83_server.servi,
            kwargs=dict(sistema=cls.sis, host="127.0.0.1", porta=cls.porta,
                        cartella_statica=os.path.join(os.path.dirname(os.path.abspath(
                            __file__)), "deploy"),
                        host_key="hk", admin_key="ak", base_url="https://bookinvip.com"),
            daemon=True).start()
        for _ in range(300):
            try:
                if cls._http("GET", "/api/health/live")[0] == 200:
                    break
            except OSError:                              # il server non ascolta ancora
                time.sleep(0.02)

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._env_prec.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.dir, ignore_errors=True)

    @classmethod
    def _g(cls, metodo, path, body=None, headers=None):
        return cls.r.gestisci(metodo, path, {},
                              json.dumps(body) if body is not None else None, headers or {})

    @classmethod
    def _http(cls, metodo, path, corpo=None):
        c = http.client.HTTPConnection("127.0.0.1", cls.porta, timeout=10)
        try:
            h = {"Content-Type": "application/x-www-form-urlencoded"} if corpo else {}
            c.request(metodo, path, body=corpo, headers=h)
            r = c.getresponse()
            return r.status, (r.getheader("Content-Type") or ""), r.read().decode("utf-8")
        finally:
            c.close()

    _giorno = [12]

    def _richiesta(self):
        """Una richiesta VERA in attesa dell'host, su date tutte sue (una per prova)."""
        oggi = datetime.date.today()
        g = self._giorno[0]
        self._giorno[0] += 3
        s, q = self._g("POST", "/api/concierge/quote",
                       {"alloggio_id": "casa-get",
                        "check_in": (oggi + datetime.timedelta(days=g)).isoformat(),
                        "check_out": (oggi + datetime.timedelta(days=g + 2)).isoformat(),
                        "party": 2})
        _deve(s == 200 and q.get("quote_token"), s, q)
        s, b = self._g("POST", "/api/concierge/book",
                       {"quote_token": q["quote_token"], "email": "cliente@sim.it"})
        _deve(s == 201 and b.get("stato") == "in_attesa_host", s, b)
        return b["riferimento"]

    def _gettone(self, rif, azione):
        link = self.r._link_azione(rif, self.hid, azione)
        _deve("/host/azione?t=" in link, link)
        return parse_qs(urlparse(link).query)["t"][0]

    def _stato(self, rif):
        return (self.sis.pagamenti_pendenti.info(rif) or {}).get("stato")

    def _date_di(self, rif):
        info = self.sis.pagamenti_pendenti.info(rif) or {}
        _deve(info.get("check_in") and info.get("check_out"), info)   # senza date, verde finto
        return info.get("check_in"), info.get("check_out")

    def test_APRIRE_IL_LINK_NON_APPROVA(self):
        rif = self._richiesta()
        tok = self._gettone(rif, "approva")
        s, _, pagina = self._http("GET", "/host/azione?t=" + quote(tok))
        self.assertEqual("in_attesa_host", self._stato(rif),
                         "aprire il link ha gia' deciso: chi apre i link al posto dell'host "
                         "(antispam, anteprime) approva le prenotazioni")
        self.assertEqual(200, s)
        self.assertIn('method="post"', pagina, "la pagina deve chiedere la conferma con un "
                      "pulsante che fa un POST")
        self.assertIn('value="%s"' % tok, pagina, "il pulsante deve portare il gettone")
        self.assertIn("Approvare la prenotazione?", pagina)
        self.assertIn("Sì, approva", pagina)

    def test_APRIRE_IL_LINK_NON_RIFIUTA(self):
        rif = self._richiesta()
        s, _, pagina = self._http("GET", "/host/azione?t=" + quote(self._gettone(rif, "rifiuta")))
        self.assertEqual("in_attesa_host", self._stato(rif))
        self.assertEqual(200, s)
        self.assertIn('method="post"', pagina)
        self.assertIn("Rifiutare la prenotazione?", pagina)
        self.assertIn("Sì, rifiuta", pagina)

    def test_UNA_HEAD_NON_DECIDE(self):
        """HEAD passa da `do_GET` (do_HEAD lo riusa): e' cio' che usano i controllori di link."""
        rif = self._richiesta()
        self._http("HEAD", "/host/azione?t=" + quote(self._gettone(rif, "approva")))
        self.assertEqual("in_attesa_host", self._stato(rif))

    def test_IL_PULSANTE_APPROVA(self):
        rif = self._richiesta()
        ci, co = self._date_di(rif)          # PRIMA: dopo la decisione la richiesta non c'e' piu'
        tok = self._gettone(rif, "approva")
        s, tipo, pagina = self._http("POST", "/host/azione", urlencode({"t": tok}))
        self.assertEqual(200, s, pagina[:300])
        self.assertIn("text/html", tipo)
        self.assertIn("Prenotazione approvata", pagina)
        self.assertNotEqual("in_attesa_host", self._stato(rif))
        s, q2 = self._g("POST", "/api/concierge/quote",
                        {"alloggio_id": "casa-get", "check_in": ci, "check_out": co,
                         "party": 2})
        self.assertFalse(q2.get("quote_token"), "approvata: le date dovevano bloccarsi")

    def test_IL_PULSANTE_RIFIUTA(self):
        rif = self._richiesta()
        ci, co = self._date_di(rif)
        s, _, pagina = self._http("POST", "/host/azione",
                                  urlencode({"t": self._gettone(rif, "rifiuta")}))
        self.assertEqual(200, s, pagina[:300])
        self.assertIn("Prenotazione rifiutata", pagina)
        self.assertNotEqual("in_attesa_host", self._stato(rif))
        s, q2 = self._g("POST", "/api/concierge/quote",
                        {"alloggio_id": "casa-get", "check_in": ci, "check_out": co,
                         "party": 2})
        self.assertTrue(q2.get("quote_token"), "rifiutata: le date dovevano tornare libere")

    def test_UN_POST_CON_GETTONE_FALSO_NON_DECIDE(self):
        rif = self._richiesta()
        tok = self._gettone(rif, "approva")
        s, _, pagina = self._http("POST", "/host/azione", urlencode({"t": tok[:-3] + "AAA"}))
        self.assertEqual(400, s)
        self.assertIn("Link non valido", pagina)
        self.assertEqual("in_attesa_host", self._stato(rif))

    def test_UN_LINK_FALSO_NON_MOSTRA_IL_PULSANTE(self):
        s, _, pagina = self._http("GET", "/host/azione?t=spazzatura.non.firmata")
        self.assertEqual(400, s)
        self.assertNotIn("<form", pagina)

    def test_UN_LINK_SCADUTO_NON_MOSTRA_IL_PULSANTE(self):
        """La domanda si mostra solo dopo TUTTI i controlli del link, scadenza compresa."""
        rif = self._richiesta()
        tok = self.sis.firma.codifica({"k": "az_richiesta", "rif": rif, "hid": self.hid,
                                       "az": "approva", "exp": int(time.time()) - 10})
        s, _, pagina = self._http("GET", "/host/azione?t=" + quote(tok))
        self.assertEqual(400, s)
        self.assertIn("Link scaduto", pagina)
        self.assertNotIn("<form", pagina)

    def test_LE_DUE_PAGINE_DEL_LINK_NON_SI_CONSERVANO(self):
        """La domanda porta il gettone nel modulo, l'esito dice cosa e' stato deciso: nessuna
        memoria intermedia (browser, proxy aziendale) le deve tenere. Chiusi cosi' i due
        sopravvissuti della mutazione sul diff (`no_store=True` -> False, 2026-10-08)."""
        rif = self._richiesta()
        tok = self._gettone(rif, "rifiuta")
        for metodo, path, corpo in (("GET", "/host/azione?t=" + quote(tok), None),
                                    ("POST", "/host/azione", urlencode({"t": tok}))):
            with self.subTest(metodo=metodo):
                c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=10)
                try:
                    h = {"Content-Type": "application/x-www-form-urlencoded"} if corpo else {}
                    c.request(metodo, path, body=corpo, headers=h)
                    r = c.getresponse()
                    r.read()
                    self.assertEqual(200, r.status)
                    self.assertIn("no-store", r.getheader("Cache-Control") or "")
                finally:
                    c.close()

    def test_UN_AZIONE_INVENTATA_NON_MOSTRA_IL_PULSANTE(self):
        rif = self._richiesta()
        tok = self.sis.firma.codifica({"k": "az_richiesta", "rif": rif, "hid": self.hid,
                                       "az": "cancella", "exp": int(time.time()) + 3600})
        s, _, pagina = self._http("GET", "/host/azione?t=" + quote(tok))
        self.assertEqual(400, s)
        self.assertNotIn("<form", pagina)

    def test_LA_PAGINA_DEL_LINK_SCADUTO_NON_PROMETTE_UNA_DURATA_DIVERSA(self):
        """Trovato per strada (b) della sessione B: la pagina «Link scaduto» diceva «oltre le
        24h» mentre `_link_azione` firma il link per una durata diversa. Una durata scritta
        nella pagina deve essere quella del link; una pagina che non ne scrive nessuna non
        puo' diventare falsa."""
        tok = parse_qs(urlparse(self.r._link_azione("rif-durata", self.hid, "approva")).query)
        vita_ore = (self.sis.firma.decodifica(tok["t"][0])["exp"] - time.time()) / 3600
        pagina = fase83_server.pagina_azione_html({"ok": False, "motivo": "link_scaduto"})
        _deve("Link scaduto" in pagina, pagina)
        for n, unita in re.findall(r"(\d+)\s*(h|ore|ora|giorni|giorno|gg)\b", pagina):
            ore = int(n) * (24 if unita.startswith("g") else 1)
            self.assertAlmostEqual(vita_ore, ore, delta=1,
                                   msg="la pagina dice %s%s, il link vale %.0f ore"
                                       % (n, unita, vita_ore))


class TestLImportDelleFotoNonPortaIlServerDentroCasa(unittest.TestCase):
    """🏠 Trovato per strada (a) della sessione B: LO STESSO DNS REBINDING DI V3, NELL'IMPORT
    DELLE FOTO.

    **Il fatto.** `_scarica_immagine` (le foto prese da un indirizzo web quando l'host importa
    un annuncio) controllava il NOME (`_ip_host_pubblico`, tolta) e poi si collegava al NOME: fra
    le due risoluzioni un DNS ostile poteva cambiare risposta, e il server bussava dentro casa.

    **Il contratto.** Come per il feed iCal (V3): il collegamento va all'indirizzo controllato,
    mai a una seconda risposta del nome. Fonte (D25): OWASP, «Server-Side Request Forgery
    Prevention Cheat Sheet» («A second, unchecked DNS lookup between validation and connection
    can bypass these checks»).
    """

    def setUp(self):
        self.posto = _PostoInterno()
        self.addCleanup(self.posto.chiudi)
        self.r = crea_router(_sistema())

    def test_UN_INDIRIZZO_INTERNO_NON_SI_TOCCA_NE_IN_HTTP_NE_IN_HTTPS(self):
        """Il collegamento controllato vale per TUTTI e due gli schemi: senza il gestore http
        controllato, o senza quello https, il server busserebbe davvero alla porta interna."""
        for url in ("http://127.0.0.1:%d/x.jpg", "https://127.0.0.1:%d/x.jpg",
                    "http://localhost:%d/x.jpg", "https://localhost:%d/x.jpg"):
            with self.subTest(url=url):
                self.posto.entrati = 0
                self.assertIsNone(self.r._scarica_immagine(url % self.posto.porta))
                self.assertEqual(0, self.posto.entrati,
                                 "il server ha bussato a un servizio interno: e' l'SSRF")

    def test_SI_COLLEGA_ALL_INDIRIZZO_CONTROLLATO_NON_AL_NOME(self):
        porta, domande, tentati = self.posto.porta, [], []
        vera_connessione = socket.create_connection

        def risolvi(host, *_a, **_k):
            if host in ("8.8.8.8", "127.0.0.1"):
                ip = host
            else:
                domande.append(host)
                ip = "8.8.8.8" if len(domande) == 1 else "127.0.0.1"
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, porta))]

        def collega(indirizzo, *a, **k):
            ip = risolvi(indirizzo[0])[0][4][0]          # un nome si risolve ADESSO
            if ip != "127.0.0.1":
                tentati.append(ip)
                raise OSError("fermato dal banco: nessuna rete vera")
            return vera_connessione((ip, indirizzo[1]), *a, **k)

        for schema in ("http", "https"):
            with self.subTest(schema=schema):
                domande.clear()
                del tentati[:]
                self.posto.entrati = 0
                with mock.patch.object(socket, "getaddrinfo", risolvi), \
                        mock.patch.object(socket, "create_connection", collega):
                    esito = self.r._scarica_immagine(
                        "%s://foto.esempio.it:%d/x.jpg" % (schema, porta))
                self.assertIsNone(esito)
                self.assertEqual(0, self.posto.entrati,
                                 "il server ha bussato a un servizio interno con la seconda "
                                 "risposta del nome: e' l'SSRF")
                if schema == "https":
                    self.assertEqual(["8.8.8.8"], tentati,
                                     "il collegamento doveva andare all'indirizzo controllato")
                else:                                     # http si puo' anche rifiutare
                    self.assertLessEqual(set(tentati), {"8.8.8.8"}, tentati)


class TestIlTestoLiberoRESTALEGGIBILEMaNonPuoFabbricareRIGHE(unittest.TestCase):
    """✍️ IL SECONDO RIMEDIO, E PERCHE' NON BASTAVA IL PRIMO.

    `_rif_per_registro` tiene **solo** lettere, cifre e quattro segni: perfetto per un
    identificativo, disastroso per una frase. Il motivo scritto a mano in un kill-switch, o
    il messaggio che torna da Stripe quando un rimborso fallisce, diventerebbero una parola
    unica e illeggibile **proprio nel momento in cui li si va a leggere** -- cioe' quando i
    soldi si sono fermati. Una difesa che rende inutile il registro non e' una difesa.

    Quindi `_testo_per_registro`: il testo resta leggibile, gli a-capo diventano **visibili**
    (`\\n` scritto come due caratteri). Chi legge vede che c'era un a-capo; quell'a-capo non
    puo' piu' aprire una riga nuova.

    ⛔ Le due guardie sono complementari e servono tutt'e due: una pretende che il veleno non
    passi, l'altra che il messaggio resti leggibile. Con la sola prima, il modo piu' semplice
    di passarla sarebbe restituire sempre stringa vuota.
    """

    VELENI = ("motivo\nERROR:core_auto.server:RIMBORSO MAI PARTITO",
              "motivo\r\nCRITICAL: cassa a zero",
              "riga1\rriga2", "a\n" * 50)

    def test_NESSUN_A_CAPO_SOPRAVVIVE(self):
        for veleno in self.VELENI:
            with self.subTest(valore=veleno[:30]):
                uscita = _testo_per_registro(veleno)
                self.assertEqual(
                    1, len(uscita.splitlines()),
                    "da un solo motivo sono uscite %d righe: il registro si puo' ancora "
                    "falsificare (%r)" % (len(uscita.splitlines()), uscita))

    def test_IL_MESSAGGIO_RESTA_LEGGIBILE(self):
        """⛔ La meta' che si dimentica sempre. Senza questa, «restituisci stringa vuota»
        passerebbe la guardia qui sopra a pieni voti."""
        vero = "carta rifiutata dall'emittente (insufficient_funds), riprovare piu' tardi"
        self.assertEqual(
            vero, _testo_per_registro(vero),
            "un messaggio innocuo e' stato storpiato: chi legge il registro dopo un guasto "
            "sui soldi deve poterlo capire")
        misto = "rimborso fallito\nmotivo: fondi insufficienti"
        uscita = _testo_per_registro(misto)
        self.assertIn("fondi insufficienti", uscita,
                      "il testo dopo l'a-capo e' sparito: si e' persa l'informazione, non "
                      "solo l'a-capo")
        self.assertIn("\\n", uscita,
                      "l'a-capo dev'essere VISIBILE, non cancellato in silenzio: chi legge "
                      "deve sapere che qualcuno ci aveva messo un a-capo")

    def test_IL_TESTO_LUNGO_VIENE_TRONCATO(self):
        self.assertEqual(200, len(_testo_per_registro("A" * 5000)))
        self.assertEqual(20, len(_testo_per_registro("A" * 5000, tetto=20)))

    def test_UN_MOTIVO_VUOTO_NON_PRODUCE_UNA_RIGA_MUTA(self):
        for vuoto in ("", None):
            with self.subTest(valore=vuoto):
                self.assertTrue(
                    _testo_per_registro(vuoto).strip(),
                    "da %r e' uscita una riga di registro senza motivo: illeggibile quanto "
                    "una falsa" % (vuoto,))


class TestLoSPLITNONSIMUOVESENZAIDENTITA(unittest.TestCase):
    """🔓 DUE ROTTE PUBBLICHE SCRIVEVANO SENZA CHIEDERE CHI FOSSE CHI CHIAMA.

    **Il fatto, misurato il 2026-08-20 sul sito VERO.** `POST /api/split/crea` e
    `POST /api/split/paga` erano cablate cosi': `self._split_crea(body)` — **ricevono solo il
    corpo, nemmeno le intestazioni**, quindi non potevano controllare l'identita' neanche
    volendo. E il motore era ACCESO in produzione (`GET /api/split/stato?conto_id=prova`
    rispondeva `404 conto_inesistente`, non `503`). Chiunque su internet poteva:
      · creare conti di gruppo sulla prenotazione di un altro;
      · e, la parte che conta, chiamare `/api/split/paga` per segnare **«pagata»** la quota
        di un partecipante **senza che fosse passato un centesimo**.
    ⚠️ Onesta' sulla portata: oggi nessuno a valle consuma `pronto_per_escrow`, quindi il buco
    non regalava ancora stanze. Ma era una scrittura pubblica su un motore dei soldi, ed e' il
    pezzo **B** del piano — quello che il piano stesso segnava «tocca produzione: serve
    autorizzato».

    L'identita' e' quella che il resto del prodotto usa gia' per l'ospite: il **voucher
    firmato**. ⛔ E non basta chiederlo: la prenotazione su cui si opera si prende **DAL
    VOUCHER**, non dal corpo — altrimenti chi ha un voucher qualunque potrebbe intestarsi il
    conto di un altro semplicemente dichiarandolo.
    """

    def setUp(self):
        self.sis = _sistema()
        self.r = crea_router(self.sis)
        self.tk = self.sis.firma.codifica({"tipo": "voucher", "riferimento": "pren-mia",
                                           "alloggio_id": "casa"})
        self.tk_altrui = self.sis.firma.codifica({"tipo": "voucher",
                                                  "riferimento": "pren-di-un-altro",
                                                  "alloggio_id": "casa"})

    def _post(self, path, corpo):
        return self.r.gestisci("POST", path, body=json.dumps(corpo))

    def test_creare_un_conto_SENZA_voucher_non_si_puo(self):
        s, c = self._post("/api/split/crea",
                          {"prenotazione_id": "pren-mia", "alloggio_id": "casa",
                           "totale_cents": 9000, "partecipanti": ["a", "b", "c"]})
        self.assertEqual(s, 401, "una rotta che SCRIVE non puo' accettare un anonimo: %s" % c)
        self.assertNotIn("conto_id", c or {}, "non deve essere nato nessun conto")

    def test_pagare_una_quota_SENZA_voucher_non_si_puo(self):
        """La piu' grave delle due: questa chiamata scrive «ha pagato» nel motore dei soldi."""
        s, c = self._post("/api/split/crea",
                          {"voucher_token": self.tk, "totale_cents": 9000,
                           "partecipanti": ["a", "b", "c"]})
        self.assertEqual(s, 201, c)
        s2, c2 = self._post("/api/split/paga",
                            {"conto_id": c["conto_id"], "partecipante_id": "a"})
        self.assertEqual(s2, 401,
                         "un anonimo ha appena dichiarato pagata una quota: %s" % c2)
        ss, st = self.r.gestisci("GET", "/api/split/stato", {"conto_id": c["conto_id"]})
        self.assertEqual(st["raccolto_cents"], 0,
                         "il rifiuto deve valere anche nei FATTI: non un centesimo raccolto")

    def test_col_voucher_di_un_ALTRA_prenotazione_non_si_paga(self):
        s, c = self._post("/api/split/crea",
                          {"voucher_token": self.tk, "totale_cents": 9000,
                           "partecipanti": ["a", "b", "c"]})
        self.assertEqual(s, 201, c)
        s2, c2 = self._post("/api/split/paga",
                            {"conto_id": c["conto_id"], "partecipante_id": "a",
                             "voucher_token": self.tk_altrui})
        self.assertEqual(s2, 403, "un voucher valido ma di un'ALTRA prenotazione: %s" % c2)

    def test_il_conto_nasce_sulla_prenotazione_DEL_VOUCHER_non_su_quella_dichiarata(self):
        """⛔ La parte che rende inutile mentire: chi chiama puo' scrivere quello che vuole nel
        corpo, ma il conto nasce sulla prenotazione che il voucher FIRMATO dichiara."""
        s, c = self._post("/api/split/crea",
                          {"voucher_token": self.tk,
                           "prenotazione_id": "pren-di-un-altro",   # <- bugia
                           "alloggio_id": "villa-altrui",           # <- bugia
                           "totale_cents": 9000, "partecipanti": ["a", "b", "c"]})
        self.assertEqual(s, 201, c)
        ss, st = self.r.gestisci("GET", "/api/split/stato", {"conto_id": c["conto_id"]})
        self.assertEqual(st["prenotazione_id"], "pren-mia",
                         "il conto si e' intestato alla prenotazione DICHIARATA invece che a "
                         "quella del voucher: cosi' chiunque puo' operare su chiunque")
        self.assertEqual(st["alloggio_id"], "casa")

    def test_e_col_voucher_GIUSTO_tutto_funziona_come_prima(self):
        """L'altra direzione (regola ferrea 10): la serratura non deve chiudere fuori chi ha
        la chiave. Il giro completo — crea, tre quote, completato — con l'identita' al posto."""
        s, c = self._post("/api/split/crea",
                          {"voucher_token": self.tk, "totale_cents": 9000,
                           "partecipanti": ["a", "b", "c"]})
        self.assertEqual(s, 201, c)
        cid = c["conto_id"]
        for chi in ("a", "b", "c"):
            sp, cp = self._post("/api/split/paga",
                                {"conto_id": cid, "partecipante_id": chi,
                                 "voucher_token": self.tk})
            self.assertEqual(sp, 200, cp)
        self.assertTrue(cp["completato"], "col voucher giusto il conto deve completarsi")


# ─────────────────────────────────────────────────────────────────────────────
# ⛔ L'ETICHETTA CHE LEGGE CHI STA PER PAGARE — e che diceva il falso in 8 lingue
# ─────────────────────────────────────────────────────────────────────────────
_LINGUE_ETICHETTE = ("it", "en", "es", "fr", "de", "pt", "ja", "zh")

# LO STESSO FATTO SCRITTO A MANO IN DUE POSTI: l'etichetta che vede l'OSPITE
# (`ETICHETTE_UI`, servita da /api/i18n e mostrata da deploy/index.html accanto al
# prezzo) e quella che vede l'HOST mentre SCEGLIE la politica (la tendina di
# deploy/host.html). Il motore che poi paga, invece, e' uno solo: fase111.POLITICHE.
_POL_OSPITE = (("flessibile", "pol_flessibile"), ("moderata", "pol_moderata"),
               ("rigida", "pol_rigida"), ("non_rimborsabile", "pol_non_rimborsabile"))
_POL_HOST = {"flessibile": "pol_fles", "moderata": "pol_mod",
             "rigida": "pol_rig", "non_rimborsabile": "pol_nr"}


def _soglia_rimborso_pieno(scaglioni):
    """I GIORNI da cui il motore rende il 100%, RICAVATI dagli scaglioni veri.

    None quando quella politica non ha nessuno scaglione al 100% (`non_rimborsabile`):
    li' non c'e' nessuna soglia da promettere, e la guardia lo dichiara invece di
    inventarsene una."""
    pieni = [giorni for giorni, bps in scaglioni if bps == 10000]
    return min(pieni) if pieni else None


def _cifre(testo):
    """Le cifre scritte nell'etichetta, come insieme.

    Funziona in tutte e 8 le lingue perche' il numero resta in cifre arabe anche in
    giapponese e in cinese (`14日前まで`, `入住前14天`): misurato, non supposto."""
    import re
    return set(int(x) for x in re.findall(r"\d+", testo))


def _percentuali(testo):
    """Le PERCENTUALI scritte nell'etichetta: un numero attaccato al segno di percento.

    ⛔ Serve perche' le sole cifre non bastano a distinguerle: in «fino a 14 giorni (poi
    50%)» sia 14 sia 50 sono numeri, ma uno e' un GIORNO e l'altro una QUOTA, e confonderli
    farebbe gridare la guardia a vuoto. Tutte e 8 le lingue usano il segno `%` (`％` e'
    la sua forma larga, quella che si scrive in giapponese e in cinese)."""
    import re
    return set(int(x) for x in re.findall(r"(\d+)\s*[%％]", testo))


def _etichette_host():
    """Le etichette della tendina dell'host, lette DAL FILE che va in produzione.

    ⛔ Se il file non c'e' o le etichette non si trovano, chi chiama deve diventare
    ROSSO e non saltare: un controllo che non riesce a misurare non e' un successo
    (sbaglio S7, e D18 punto 1)."""
    import io
    import os
    import re
    percorso = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "deploy", "host.html")
    with io.open(percorso, encoding="utf-8") as f:
        html_host = f.read()
    return dict((chiave, re.findall(chiave + r':"([^"]*)"', html_host))
                for chiave in _POL_HOST.values())


class TestLEtichettaDellaCancellazioneNONPuoSmentireIlMotore(unittest.TestCase):
    """⛔ E' LA RIGA CHE LEGGE CHI STA PER PAGARE, ED E' IN OTTO LINGUE.

    Trovato sul sito VIVO il 2026-08-21: `pol_rigida` prometteva «Cancellazione gratuita
    fino a 14 giorni prima (poi 50%)» mentre `fase111.POLITICHE["rigida"]` rende il 100%
    solo da **30** giorni. Chi cancellava a 20 giorni dall'arrivo leggeva 100% e riceveva
    50%: su una prenotazione da 400 EUR sono 200 EUR di differenza, promessi nell'istante
    del pagamento e in tutte e otto le lingue.

    💡 E lo stesso numero era scritto GIUSTO nella tendina dell'host (`deploy/host.html`:
    «30 giorni»). Due copie a mano dello stesso fatto, e a essere sbagliata era quella
    lontana dal motore -- la malattia di sempre. Percio' le guardie sono due: una confronta
    la pagina col MOTORE, l'altra confronta le DUE COPIE fra loro.

    ⛔ I giorni non si ricopiano: si RICAVANO dagli scaglioni, come gia' fa la guardia
    della FAQ in `test_fase173_motore_seo.py`. Sposta uno scaglione e questa diventa rossa
    lo stesso giorno.

    ⚠️ LIMITE DICHIARATO (D18 punto 3): si guardano i NUMERI, non il senso della frase.
    «niente sotto i 7 giorni» e «tutto sotto i 7 giorni» contengono lo stesso 7, e da qui
    sono indistinguibili: questa guardia impedisce che la pagina TACCIA una soglia o ne
    dica una sbagliata, non che qualcuno scriva una frase rovesciata.
    """

    def test_la_soglia_promessa_all_OSPITE_e_QUELLA_CHE_IL_MOTORE_APPLICA(self):
        from fase111_cancellazione import POLITICHE
        from fase83_server import ETICHETTE_UI
        bugie = []
        provate = 0
        for politica, chiave in _POL_OSPITE:
            self.assertIn(chiave, ETICHETTE_UI,
                          "l'etichetta '%s' non esiste piu': la pagina tacerebbe su una "
                          "politica che il motore tratta" % chiave)
            soglia = _soglia_rimborso_pieno(POLITICHE[politica].scaglioni)
            if soglia is None:
                continue        # non_rimborsabile: nessuno scaglione al 100%, niente da promettere
            for lingua in _LINGUE_ETICHETTE:
                testo = ETICHETTE_UI[chiave][lingua]
                provate += 1
                # Una soglia si puo' scrivere in GIORNI o in ORE: «1 giorno» e «24h» sono
                # lo stesso fatto, ed e' cosi' che e' scritta oggi la politica flessibile.
                if not ({soglia, soglia * 24} & _cifre(testo)):
                    bugie.append(
                        "%s/%s: il motore rende il 100%% da %d giorni dall'arrivo, "
                        "la pagina promette %r" % (chiave, lingua, soglia, testo))
        self.assertGreater(provate, 0,
                           "nessuna etichetta esaminata: questa guardia non sta provando "
                           "niente, e un denominatore zero non e' un verde")
        self.assertEqual([], bugie,
                         "LA PAGINA DOVE SI PAGA PROMETTE UN RIMBORSO CHE IL MOTORE NON DA':"
                         "\n" + "\n".join(bugie))

    def test_HOST_e_OSPITE_non_possono_leggere_DUE_NUMERI_DIVERSI(self):
        """L'altra faccia, e si vede anche SENZA il motore: l'host firma per una regola e
        l'ospite ne legge un'altra. Nessuno confrontava le due copie."""
        from fase83_server import ETICHETTE_UI
        host = _etichette_host()
        scarti = []
        for politica, chiave_ospite in _POL_OSPITE:
            chiave_host = _POL_HOST[politica]
            trovate = host.get(chiave_host) or []
            self.assertEqual(len(trovate), len(_LINGUE_ETICHETTE),
                             "in deploy/host.html l'etichetta '%s' compare %d volte invece "
                             "di %d: il confronto non si puo' fare, e un controllo che non "
                             "riesce a misurare non e' un successo"
                             % (chiave_host, len(trovate), len(_LINGUE_ETICHETTE)))
            per_lingua = set(frozenset(_cifre(t)) for t in trovate)
            self.assertEqual(len(per_lingua), 1,
                             "le 8 lingue di '%s' non dicono gli stessi numeri: %s"
                             % (chiave_host, sorted(sorted(x) for x in per_lingua)))
            numeri_host = set().union(*[_cifre(t) for t in trovate])
            numeri_ospite = set().union(
                *[_cifre(ETICHETTE_UI[chiave_ospite][l]) for l in _LINGUE_ETICHETTE])
            if numeri_host != numeri_ospite:
                scarti.append("%s: l'host legge %s, l'ospite legge %s"
                              % (politica, sorted(numeri_host), sorted(numeri_ospite)))
        self.assertEqual([], scarti,
                         "LO STESSO FATTO SCRITTO IN DUE POSTI, E I DUE NON CONCORDANO:\n"
                         + "\n".join(scarti))

    def test_una_QUOTA_PARZIALE_non_si_promette_SENZA_DIRE_DA_QUANDO_VALE(self):
        """La seconda faccia del difetto, e viveva nella stessa riga.

        «(poi 50%)» dice il vero fra 7 e 29 giorni e il FALSO sotto i 7, dove il motore
        rende ZERO -- ed e' proprio la finestra in cui la gente cancella. Una quota scritta
        senza il giorno da cui vale e' una promessa a tempo indeterminato: sotto quella
        soglia l'ospite legge «meta'» e riceve niente."""
        from fase111_cancellazione import POLITICHE
        from fase83_server import ETICHETTE_UI
        muti = []
        for politica, chiave in _POL_OSPITE:
            # gli scaglioni che rendono una quota PARZIALE: ne' tutto ne' niente
            parziali = sorted((giorni, bps) for giorni, bps
                              in POLITICHE[politica].scaglioni if 0 < bps < 10000)
            for lingua in _LINGUE_ETICHETTE:
                testo = ETICHETTE_UI[chiave][lingua]
                promesse = _percentuali(testo)
                if not promesse:
                    continue    # la pagina non promette nessuna quota parziale: niente da dire
                self.assertTrue(parziali,
                                "%s/%s: la pagina promette %s%% ma il motore non ha nessuno "
                                "scaglione parziale su questa politica: %r"
                                % (chiave, lingua, sorted(promesse), testo))
                da_quando, bps = parziali[0]
                if bps // 100 not in promesse:
                    muti.append("%s/%s: la pagina promette %s%%, il motore rende %d%%: %r"
                                % (chiave, lingua, sorted(promesse), bps // 100, testo))
                elif da_quando not in _cifre(testo):
                    muti.append("%s/%s: la pagina promette %d%% senza dire che vale solo da "
                                "%d giorni -- sotto quella soglia il motore rende ZERO: %r"
                                % (chiave, lingua, bps // 100, da_quando, testo))
        self.assertEqual([], muti,
                         "UNA QUOTA PROMESSA SENZA IL GIORNO DA CUI VALE E' UNA PROMESSA CHE "
                         "SOTTO QUELLA SOGLIA NON VIENE MANTENUTA:\n" + "\n".join(muti))


class TestIlBloccoVuotoDellaHomePrometteIlCreditoVERO(unittest.TestCase):
    """2026-09-23, ordine del fondatore: frase di tutela "fase di test per un servizio
    migliore e risparmio" + sconto 5 EUR al posto del vecchio blocco waitlist. La cifra
    nel testo DEVE valere quanto il credito che il motore emette davvero (fase158,
    CREDITO_FONDATORE_CENTS): un testo che promette un numero diverso e' una bugia sui
    soldi (regola zero 4)."""

    def test_lo_sconto_promesso_e_il_credito_del_motore_sono_la_STESSA_cifra(self):
        from fase158_domanda import CREDITO_FONDATORE_CENTS
        self.assertEqual(500, CREDITO_FONDATORE_CENTS,
                         "il credito e' cambiato? allora cambia ANCHE il testo della home")
        from fase83_server import ETICHETTE_UI
        for lingua in ("it", "en"):
            testo = ETICHETTE_UI["empty_lascia"][lingua]
            self.assertIn("5", testo,
                          "%s: il blocco vuoto non promette piu' lo sconto a 5 EUR: %r"
                          % (lingua, testo))

    def test_la_frase_di_tutela_e_le_cta_sono_in_otto_lingue(self):
        from fase83_server import ETICHETTE_UI
        for chiave in ("empty_titolo", "empty_lascia", "sei_host"):
            voci = ETICHETTE_UI[chiave]
            mancanti = [l for l in ("it", "en", "es", "fr", "de", "pt", "ja", "zh")
                        if not str(voci.get(l, "")).strip()]
            self.assertEqual([], mancanti, "%s senza lingue: %r" % (chiave, mancanti))

    def test_la_trasparenza_delle_recensioni_e_vera_e_mostrata(self):
        """2026-09-23, fondatore: 'chi prenota puo' fare recensioni, solo loro!!!' --
        la frase 'verificato dal sistema' e' VERA solo se l'enforcer esiste (la
        recensione senza pagamento e' rifiutata) e la pagina la mostra davvero."""
        import inspect
        import fase83_server
        from fase83_server import ETICHETTE_UI
        src_f83 = inspect.getsource(fase83_server)
        self.assertIn("def _recensione_ammessa", src_f83,
                      "l'enforcer anti-recensioni-finte non esiste piu': la frase "
                      "'verificato dal sistema' sarebbe una bugia (regola zero 4)")
        self.assertIn("prenotazione_non_pagata", src_f83,
                      "la regola 'solo chi ha pagato' non e' piu' applicata")
        voci = ETICHETTE_UI.get("recensioni_verifica", {})
        mancanti = [l for l in ("it", "en", "es", "fr", "de", "pt", "ja", "zh")
                    if not str(voci.get(l, "")).strip()]
        self.assertEqual([], mancanti, "recensioni_verifica senza lingue: %r" % (mancanti,))
        import os
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "deploy", "index.html"), encoding="utf-8").read()
        self.assertIn("recensioni_verifica", src,
                      "la scheda alloggio non mostra la riga di trasparenza")

    def test_il_sito_dichiara_i_fatti_al_le_macchine_json_ld(self):
        """2026-09-23, blocco AI Discovery: la home porta JSON-LD (schema.org) coi
        FATTI veri del motore. L'audit ha misurato: MCP vivo (6 tool provati dal
        vivo), llms.txt, ai-plugin.json, openapi.json — ma 0 pagine con JSON-LD:
        e' il formato che Google AI Search e Perplexity leggono. La guardia valida
        il JSON e pretende i campi che dicono la verita' del progetto."""
        import json as _json
        import os
        import re
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "deploy", "index.html"), encoding="utf-8").read()
        m = re.search(r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>',
                      src, re.S)
        self.assertIsNotNone(m, "la home non porta JSON-LD: invisibile alle AI search")
        d = _json.loads(m.group(1))                 # JSON rotto = rosso subito
        self.assertEqual(d.get("@type"), "TravelAgency")
        self.assertIn("https://schema.org", str(d.get("@context")))
        self.assertIn("SearchAction", str(d))
        self.assertIn("bookinvip.com", str(d.get("url")))
        lingue = d.get("availableLanguage") or []
        self.assertEqual(len(lingue), 8, "le lingue dichiarate alle macchine devono "
                                          "essere le 8 vere del sito")


class _ConnectCheRicorda:
    """Il bonifico Connect, finto al bordo: ricorda cosa gli e' stato chiesto di pagare."""

    def __init__(self):
        self.bonifici = []

    def trasferisci(self, acct, importo, valuta, rif):
        self.bonifici.append((acct, importo, valuta, rif))
        return "tr_%d" % len(self.bonifici)


class _BancoDeiSoldiDelServer(unittest.TestCase):
    """Sistema VERO su file (pendenti, bonifici, garanzia, giornale), webhook firmato,
    Stripe finto solo nella rete e Connect finto al bordo. Le guardie dei soldi che toccano
    righe di `fase83_server` stanno in QUESTO file: e' quello che il Giudice accende per
    fase83 (misurato l'8/10 con `scegli_sorveglianti`), altrove i mutanti sopravviverebbero."""

    WH = "whsec_banco_server"
    # in una costante: passata come stringa a un argomento `*_key` conta per bandit come
    # segreto cablato (B106). La rete e' finta, la chiave non conta.
    CHIAVE = "sk_test_x"

    @classmethod
    def setUpClass(cls):
        import fase85_pagamenti_stripe as _stripe
        cls._stripe = _stripe
        cls._orig_fetch = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(
            lambda u, b, h: {"id": u.rstrip("/").rsplit("/", 1)[-1], "payment_status": "paid"}
            if not b and "/checkout/sessions/" in u
            else {"url": "https://checkout.stripe.test/cs", "id": "cs_1"})

    @classmethod
    def tearDownClass(cls):
        cls._stripe.ProviderStripe._fetch_reale = cls._orig_fetch

    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/acc.db",
            db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db", db_garanzia=f"{d}/g.db",
            db_tassa_comunale=f"{d}/t.db", db_finanza=f"{d}/fin.db",
            commissione_bps=1000, psp_bps=300,
            stripe_secret_key=self.CHIAVE, stripe_webhook_secret=self.WH,
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/ko"))
        self.connect = _ConnectCheRicorda()
        self.sis.connect = self.connect
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@banco.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        _deve(s == 201, s, c)
        self.hid, self.tok = c["host_id"], c["token"]
        self.sis.registro_host.imposta_stripe_account(self.hid, "acct_banco")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def pubblica(self, slug, politica="flessibile", **altro):
        annuncio = {"slug": slug, "titolo": "Casa", "citta": "Roma", "prezzo_notte_cents": 10000,
                    "capacita": 2, "politica_cancellazione": politica}
        annuncio.update(altro)
        self.g("POST", "/api/host/pubblica", annuncio, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": slug, "da": _fra(0), "a": _fra(60), "unita_totali": 1,
                "prezzo_netto_cents": 10000}, {"X-Host-Token": self.tok})

    def prenota(self, slug, giorni_all_arrivo):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": slug, "check_in": _fra(giorni_all_arrivo),
                       "check_out": _fra(giorni_all_arrivo + 2), "party": 2})
        _deve(s == 200, s, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@banco.it"})
        _deve(s == 201, s, b)
        return b

    def evento(self, tipo, oggetto, evt_id=None):
        corpo = {"type": tipo, "data": {"object": oggetto}}
        if evt_id:
            corpo["id"] = evt_id
        payload = json.dumps(corpo)
        from fase87_stripe_webhook import firma_di_test
        return self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                               {"Stripe-Signature": firma_di_test(payload, self.WH,
                                                                  int(time.time()))})

    def paga(self, rif, pi):
        return self.evento("checkout.session.completed",
                           {"id": "cs_" + pi, "payment_intent": pi,
                            "metadata": {"riferimento": rif}})

    def contestazione(self, pi, dp="dp_banco1", importo=20000):
        return self.evento("charge.dispute.created",
                           {"id": dp, "object": "dispute", "payment_intent": pi,
                            "charge": "ch_banco", "amount": importo, "currency": "eur",
                            "reason": "fraudulent", "status": "needs_response"},
                           evt_id="evt_" + dp)

    def incassi(self, rif):
        return [m for m in self.sis.finanza.movimenti(rif) if m.get("tipo") == "incasso"]

    def ascolta(self):
        """Raccoglie TUTTO cio' che il server scrive nel registro, senza pretendere niente:
        cosi' la prova guarda prima i soldi e poi l'allarme, e il rosso dice il motivo vero
        (con `assertLogs` un allarme mancante nasconderebbe il bonifico sbagliato)."""
        import contextlib
        import logging

        @contextlib.contextmanager
        def _ascolto():
            righe = []

            class _Orecchio(logging.Handler):
                def emit(self, rec):
                    # anche la traccia: «c'e' LA COSA, del tipo giusto?», non «non e' nulla»
                    tipo = (rec.exc_info[0].__name__ if isinstance(rec.exc_info, tuple)
                            and rec.exc_info[0] is not None else "-")
                    righe.append("%s:%s |exc_info:%s" % (rec.levelname, rec.getMessage(), tipo))
            orecchio = _Orecchio(level=logging.DEBUG)
            lg = logging.getLogger("core_auto.server")
            prima = lg.level
            lg.addHandler(orecchio)
            lg.setLevel(logging.DEBUG)
            try:
                yield righe
            finally:
                lg.removeHandler(orecchio)
                lg.setLevel(prima)
        return _ascolto()

    @staticmethod
    def errori_con(righe, *parole):
        return [r for r in righe if r.startswith("ERROR:") and all(p in r for p in parole)]

    @staticmethod
    def avvisi_con(righe, *parole):
        return [r for r in righe if r.startswith("WARNING:") and all(p in r for p in parole)]


class TestLaPenaleNonDiventaUnBonificoPieno(_BancoDeiSoldiDelServer):
    """C53-B1-9 (busta 8): nella cancellazione con penale il registro dei bonifici si
    riallinea alla quota dell'host (`imposta_importo`) e poi parte il bonifico, che per
    regola paga l'importo SCRITTO NEL REGISTRO. Il ritorno del riallineo non si guardava: se
    la scrittura falliva (archivio bloccato) il registro restava all'importo PIENO e partiva
    quello -- l'ospite riceveva indietro la sua parte E l'host riceveva tutto."""

    def _cancella_con_penale(self, **annuncio):
        self.pubblica("casa-pen", "moderata", **annuncio)
        b = self.prenota("casa-pen", 2)                 # moderata a 2 giorni: meta' e meta'
        rif = b["riferimento"]
        s, c = self.paga(rif, "pi_pen")
        _deve(s == 200, s, c)
        pieno = self.sis.payout.info(rif)["minori"]
        _deve(self.sis.payout.stato_di(rif) == "maturato", self.sis.payout.stato_di(rif))
        s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        self.assertEqual(200, s, c)
        quota = self.sis.garanzia.stato(rif)["host_riceve_cents"]
        _deve(0 < quota < pieno, "PREMESSA: serve una penale PARZIALE", quota, pieno, c)
        return rif, quota, pieno

    def test_se_il_registro_NON_si_riallinea_il_bonifico_pieno_NON_parte(self):
        self.sis.payout.imposta_importo = lambda *a, **k: False
        with self.ascolta() as righe:
            rif, quota, pieno = self._cancella_con_penale()
        self.assertEqual([], self.connect.bonifici,
                         "BONIFICO PIENO SU UNA PENALE: la quota dell'host era %d, il registro "
                         "non si e' riallineato e sono partiti %r (pieno %d)"
                         % (quota, self.connect.bonifici, pieno))
        self.assertTrue(self.errori_con(righe, "importo_non_riallineato",
                                        "SOTTOCODICE: trattenuto |"),
                        "nessun ERROR col codice e col bonifico trattenuto: %r" % (righe,))
        self.assertEqual("trattenuto", self.sis.payout.stato_di(rif))

    def test_se_ANCHE_il_trattenere_esplode_il_registro_lo_dice(self):
        import sqlite3

        def esplode(*a, **k):
            raise sqlite3.OperationalError("database is locked")
        self.sis.payout.imposta_importo = lambda *a, **k: False
        vero = self.sis.payout.aggiorna_stato
        self.sis.payout.aggiorna_stato = (
            lambda pid, nuovo: esplode() if nuovo == "trattenuto" else vero(pid, nuovo))
        with self.ascolta() as righe:
            rif, quota, pieno = self._cancella_con_penale()
        self.assertEqual([], self.connect.bonifici, "%r" % (self.connect.bonifici,))
        self.assertTrue(self.errori_con(righe, "importo_non_riallineato",
                                        "SOTTOCODICE: TRATTENUTA_FALLITA"), "%r" % (righe,))
        self.assertTrue(self.avvisi_con(righe, "payout trattenuto su penale esploso",
                                        "|exc_info:OperationalError"), "%r" % (righe,))

    def test_con_DUE_archivi_fermi_il_bonifico_pieno_non_parte_nemmeno_dopo(self):
        # D19, lo stato si costruisce a mano: insieme al registro dei bonifici non risponde
        # nemmeno quello dei pagamenti, quindi il pagamento resta 'pagato'. La garanzia e' gia'
        # 'risolto': il giro che ritenta i bonifici fermi quando l'host completa i dati
        # fiscali pagherebbe il registro PIENO. A fermarlo resta solo il 'trattenuto'.
        import sqlite3

        def bloccato(*a, **k):
            raise sqlite3.OperationalError("database is locked")
        self.sis.payout.imposta_importo = lambda *a, **k: False
        self.sis.pagamenti_pendenti.marca_da_rimborsare = bloccato
        rif, quota, pieno = self._cancella_con_penale()
        _deve(self.sis.pagamenti_pendenti.info(rif)["stato"] == "pagato",
              "PREMESSA: il pagamento doveva restare 'pagato'",
              self.sis.pagamenti_pendenti.info(rif))
        s, c = self.g("POST", "/api/host/dati_fiscali",
                      {"codice_fiscale": "RSSMRA80A01H501U", "indirizzo_fiscale": "Via Roma 1",
                       "paese": "IT", "iban": "IT60X0542811101000000123456",
                       "tipo_soggetto": "individuo"}, {"X-Host-Token": self.tok})
        self.assertEqual(200, s, c)
        self.assertEqual([], self.connect.bonifici,
                         "BONIFICO PIENO DAL GIRO DEI BONIFICI FERMI: quota %d, partiti %r"
                         % (quota, self.connect.bonifici))
        self.assertEqual("trattenuto", self.sis.payout.stato_di(rif))

    def test_se_il_riallineo_ESPLODE_il_bonifico_pieno_NON_parte(self):
        import sqlite3

        def esplode(*a, **k):
            raise sqlite3.OperationalError("database is locked")
        self.sis.payout.imposta_importo = esplode
        with self.ascolta() as righe:
            rif, quota, pieno = self._cancella_con_penale()
        self.assertEqual([], self.connect.bonifici,
                         "BONIFICO PIENO SU UNA PENALE (riallineo esploso): quota %d, partiti %r"
                         % (quota, self.connect.bonifici))
        self.assertTrue(self.errori_con(righe, "importo_non_riallineato"), "%r" % (righe,))
        self.assertTrue(self.avvisi_con(righe, "riallineo payout su penale esploso",
                                        "|exc_info:OperationalError"), "%r" % (righe,))

    def test_col_registro_sano_parte_ESATTAMENTE_la_quota_dell_host(self):
        rif, quota, pieno = self._cancella_con_penale()
        self.assertEqual([("acct_banco", quota, "EUR", rif)], self.connect.bonifici)
        self.assertEqual(quota, self.sis.payout.info(rif)["minori"])

    def test_la_penale_arriva_INTERA_anche_con_la_ritenuta_accesa(self):
        # `penale=True` dal percorso VERO: una penale non e' canone e la ritenuta non si opera
        # (la guida AdE esclude le penali). C'e' gia' in test_ritenuta, ma il Giudice per
        # fase83 accende QUESTO file: la' il guasto sulla riga del bonifico non lo vedrebbe.
        _deve(self.sis.ritenuta.imposta(True, motivo="collaudo", chi="test"),
              "PREMESSA: la ritenuta non si accende")
        rif, quota, pieno = self._cancella_con_penale(paese="IT", cin="IT058091C2ABCDEF12")
        self.assertEqual([("acct_banco", quota, "EUR", rif)], self.connect.bonifici,
                         "la penale e' stata trattata come un canone")
        self.assertEqual([], [m for m in self.sis.finanza.movimenti(rif)
                              if m.get("tipo") == "ritenuta"])


class TestDopoUnaPenaleLaParteDellOspiteSiRimborsaAncora(_BancoDeiSoldiDelServer):
    """REGRESSIONE del pacco 1 (#279, gia' in produzione), trovata da PROTON il 26/10 rileggendo il
    freno 3 dei rimborsi dovuti (Kimi K12): 'in_transito' ferma il pulsante perche' «l'host e'
    gia' stato pagato». Ma nella cancellazione dell'ospite con PENALE l'host riceve SUBITO la sua
    quota (bonifico Connect riuscito -> 'in_transito') e all'ospite spetta il resto: quel bonifico
    e' legittimo, non un doppio. Il ramo dell'arbitro non scattava perche' la garanzia ragiona su
    netto + tassa e la riga del rimborso su prezzo + tassa: le due cifre non coincidono."""

    def test_la_quota_dell_host_pagata_non_blocca_il_rimborso_della_parte_dell_ospite(self):
        self.pubblica("casa-pq", "moderata")
        b = self.prenota("casa-pq", 2)                 # moderata a 2 giorni: meta' e meta'
        rif = b["riferimento"]
        s, c = self.paga(rif, "pi_pq")
        _deve(s == 200, s, c)
        s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        _deve(s == 200, s, c)
        _deve(int(c.get("rimborso_cents", 0)) > 0, "PREMESSA: all'ospite spetta una parte", c)
        quota = int(self.sis.garanzia.stato(rif)["host_riceve_cents"])
        _deve([("acct_banco", quota, "EUR", rif)] == self.connect.bonifici,
              "PREMESSA: la quota-penale dell'host e' partita", self.connect.bonifici)
        _deve(self.sis.payout.stato_di(rif) == "in_transito", self.sis.payout.stato_di(rif))
        s, lista = self.g("GET", "/api/admin/rimborsi_dovuti", None, {"X-Admin-Key": "ak"})
        _deve(s == 200, s, lista)
        riga = next((r for r in lista.get("rimborsi", []) if r.get("riferimento") == rif), None)
        _deve(riga is not None, "PREMESSA: la parte dell'ospite e' fra i rimborsi dovuti", lista)
        self.assertNotIn("payout_gia_pagato", riga.get("manca") or [],
                         "IL RIMBORSO DELL'OSPITE E' BLOCCATO dalla quota-penale dell'host, che era "
                         "sua: all'ospite spettano %d e il pulsante non c'e' (%r)"
                         % (int(riga.get("dovuto_cents", 0)), riga.get("manca")))
        self.assertNotIn("arbitrato_supera_il_pagato", riga.get("manca") or [],
                         "quota dell'host + parte dell'ospite superano il pagato: %r" % (riga,))
        # PROTON sul diff finale (26/10): il pulsante qui e' spento anche per un altro motivo (lo
        # Stripe finto del banco non risponde a `rimborsi_di`/`contestazione_di`), quindi guardare
        # solo due motivi non basta: l'uscita del freno 3 si legge per intero.
        self.assertIs(True, riga.get("passi_sicurezza_ok"),
                      "il freno 3 ferma la parte dell'ospite: %r" % (riga,))


class TestLaCancellazioneDellHostArrivaSempreInFondo(_BancoOffset):
    """VOCE 137 (piano di GML 35, busta di Claude, Kimi K14, PROTON P1-SEXIES): dopo il CAS
    'cancellata_host' la rotta tornava 503 se la nota di debito non si scriveva, PRIMA di liberare
    le date, togliere il bonifico all'host e scrivere il rimborso dell'ospite; e lo sweeper rifaceva
    SOLO la nota, e solo se la riga `penale:<rif>` mancava. G1-G7 viste ROSSE su e6ed3c2 (D20).
    Stanno QUI, nel test DEDICATO di fase83: il Giudice accende per primo questo file, e in
    test_financial_controller.py 47 righe nuove su 60 passavano senza occhi (giro del 26/10).
    G8-G13 e la classe sotto sono nate da quel giro: una per ogni gruppo di righe non viste."""

    def _sweep(self):
        fase83_server.sweep_hold_una_passata(self.sis, self.r)

    def _cancella(self, rif, **altro):
        corpo = {"riferimento": rif, "host_id": "demo"}
        corpo.update(altro)
        return self.g("POST", "/api/host/cancella", corpo, _HK_FC)

    def _solo_il_cas(self, rif):
        # il CAS di `_host_cancella` e niente altro: il processo e' morto alla riga dopo
        from fase98_policy_commissione import commissione_cents
        dj = json.loads(self.sis.pagamenti_pendenti.info(rif).get("corpo_json") or "{}")
        guest = int(dj.get("totale_cents", 0)) or int(dj.get("prezzo_guest_cents", 0))
        self.assertTrue(self.sis.pagamenti_pendenti.marca_cancellata_host(
            rif, commissione_cents(guest, fase83_server.PENALE_HOST_BPS)))
        return guest

    def _corpo(self, rif, **campi):
        # D19: lo stato che il flusso di oggi non produce si scrive a mano nel corpo del pendente
        pp = self.sis.pagamenti_pendenti
        dj = json.loads(pp.info(rif).get("corpo_json") or "{}")
        for k, v in campi.items():
            if v is None:
                dj.pop(k, None)
            else:
                dj[k] = v
        con = pp._apri()
        try:
            with con:
                con.execute("UPDATE pendenti SET corpo_json=? WHERE riferimento=?",
                            (json.dumps(dj), rif))
        finally:
            con.close()

    def _rimborsi(self, rif):
        return [m for m in self.sis.finanza.movimenti(rif) if m.get("tipo") == "rimborso"]

    def _con_gli_errori(self, fai):
        # gli ERROR «nota_debito_rinviata» scritti mentre gira `fai`
        with mock.patch.object(fase83_server.logger, "error",
                               wraps=fase83_server.logger.error) as err:
            esito = fai()
        return esito, [c for c in err.call_args_list if "nota_debito_rinviata" in str(c)]

    def test_137_G1_la_cancellazione_arriva_in_fondo_anche_se_la_penale_non_si_scrive(self):
        rif = self._prenota_paga()
        self.assertEqual("maturato", self.sis.payout.stato_di(rif),
                         "PREMESSA: il bonifico all'host e' maturato")
        with mock.patch.object(self.sis.finanza, "processa_penale", return_value=None):
            (s, c), rinviate = self._con_gli_errori(lambda: self._cancella(rif))
        # (1) l'host sa che la cancellazione e' FATTA (prima: 503 e «Riprova», con il CAS gia' vinto)
        self.assertEqual(200, s, c)
        self.assertEqual("cancellata_host", c.get("stato"), c)
        self.assertIs(True, c.get("nota_debito_in_attesa"), c)
        self.assertNotIn("nota_debito", c, c)
        self.assertEqual(1, len(rinviate), "la nota rinviata non grida col suo codice")
        # (2) i soldi sono a posto SUBITO: niente bonifico all'host, rimborso dell'ospite a giornale
        self.assertIsNone(self.sis.payout.info(rif), "l'host resta pagabile su una cancellata")
        self.assertEqual([int(c["rimborso_cliente_cents"])],
                         [int(m["importo_cents"]) for m in self._rimborsi(rif)],
                         "l'ospite non ha la riga del rimborso")
        # (3) la nota di debito la scrive lo sweeper, UNA volta sola
        self._sweep()
        self._sweep()
        self.assertEqual(1, len(self._note_debito(rif)), self._note_debito(rif))
        # (4) ripetere dice la verita': la cancellazione c'e' gia'
        s2, c2 = self._cancella(rif)
        self.assertEqual((409, "gia_cancellata"), (s2, c2.get("errore")), c2)

    def test_137_G2_col_giornale_giu_lo_sweeper_scrive_poi_rimborso_e_nota_una_volta(self):
        rif = self._prenota_paga()
        self.assertEqual("maturato", self.sis.payout.stato_di(rif), "PREMESSA: bonifico maturato")
        self.assertIn("incasso", self._tipi(rif), "PREMESSA: l'incasso e' nel giornale")
        with mock.patch.object(self.sis.finanza, "registra", return_value=None):
            s, c = self._cancella(rif)
        self.assertEqual(200, s, c)
        self.assertIsNone(self.sis.payout.info(rif), "host ancora pagabile su una cancellata")
        self.assertNotIn("rimborso", self._tipi(rif), "PREMESSA: col giornale giu' la riga manca")
        self._sweep()
        self._sweep()
        self.assertEqual(1, self._tipi(rif).count("rimborso"),
                         "l'ospite resta senza riga di rimborso: %r" % self._tipi(rif))
        self.assertEqual(1, len(self._note_debito(rif)), self._note_debito(rif))
        self.assertTrue(self.sis.finanza.verifica_catena()["ok"])

    def test_137_G3_il_processo_muore_dopo_il_CAS_e_lo_sweeper_finisce_il_lavoro(self):
        rif = self._prenota_paga()
        guest = self._solo_il_cas(rif)
        inv = self.sis.inventario
        with mock.patch.object(inv, "rilascia", wraps=inv.rilascia) as ril:
            self._sweep()
        self.assertGreaterEqual(ril.call_count, 1, "le date della cancellata restano bloccate")
        self.assertIsNone(self.sis.payout.info(rif), "host ancora pagabile su una cancellata")
        st = (self.sis.garanzia.stato(rif) or {}).get("stato")
        self.assertNotEqual("in_garanzia", st, "garanzia ancora aperta: %r" % st)
        self.assertEqual([(guest, "EUR")], [(int(m["importo_cents"]), m.get("valuta"))
                                            for m in self._rimborsi(rif)],
                         "l'ospite resta senza la riga del rimborso intero")
        note = self._note_debito(rif)
        self.assertEqual(["host:demo"], [n.get("soggetto") for n in note], note)
        tipi = self._tipi(rif)
        with mock.patch.object(inv, "rilascia", wraps=inv.rilascia) as ril2:
            self._sweep()
        self.assertEqual(0, ril2.call_count, "lo sweeper riapre il lucchetto dell'inventario a ogni giro")
        self.assertEqual(tipi, self._tipi(rif), "il secondo giro ha scritto ancora nel giornale")

    def test_137_G4_una_cancellazione_riuscita_lo_sweeper_non_la_ritocca(self):
        # il silenzio a macchina sana (ferrea 10): verde anche PRIMA della riparazione, e deve restarlo
        rif = self._prenota_paga()
        (s, c), rinviate = self._con_gli_errori(lambda: self._cancella(rif))
        self.assertEqual(200, s, c)
        self.assertTrue(str(c.get("nota_debito") or "").startswith("ND-"), c)
        self.assertNotIn("nota_debito_in_attesa", c, c)
        self.assertEqual([], rinviate, "una nota scritta grida «rinviata»")
        prima = self._tipi(rif)
        inv, pd = self.sis.inventario, self.sis.payout
        with mock.patch.object(inv, "rilascia", wraps=inv.rilascia) as ril, \
                mock.patch.object(pd, "rimuovi", wraps=pd.rimuovi) as rim, \
                mock.patch.object(self.sis.finanza, "processa_penale",
                                  wraps=self.sis.finanza.processa_penale) as pen:
            self._sweep()
        self.assertEqual((0, 0, 0), (ril.call_count, rim.call_count, pen.call_count),
                         "lo sweeper ritocca una cancellazione gia' finita")
        self.assertEqual(prima, self._tipi(rif))

    def test_137_G5_la_penale_scritta_solo_nel_giornale_lo_sweeper_la_finisce(self):
        # Kimi K14: `emetti_nota` scrive PRIMA la riga `penale:<rif>` del giornale e POI la nota;
        # se la nota non entra nella sua tabella, `esiste_evento("penale:")` dice «iniziata» e lo
        # sweeper non ci tornava piu'. D19: il guasto vero, l'INSERT della nota che fallisce.
        rif = self._prenota_paga()
        fc = self.sis.finanza
        with mock.patch.object(fc, "_prossimo_nota_id", side_effect=RuntimeError("nota giu'")):
            self._cancella(rif)
        self.assertTrue(fc.esiste_evento("penale:" + rif), "PREMESSA: la riga del giornale c'e'")
        self.assertEqual([], self._note_debito(rif), "PREMESSA: la nota NON e' nella sua tabella")
        self._sweep()
        self._sweep()
        note = self._note_debito(rif)
        self.assertEqual(1, len(note), "la nota della penale non nasce piu': %r" % note)
        deb = [d for d in fc.debiti_host("demo") if d.get("debito_id") == note[0]["nota_id"]]
        self.assertEqual(1, len(deb), "il debito della penale non e' scritto: %r" % deb)
        self.assertEqual(1, self._tipi(rif).count("nota_debito"), self._tipi(rif))

    def test_137_G6_la_penale_si_scrive_sotto_il_lucchetto_dei_bonifici(self):
        # Proton P1-SEXIES (a): due `processa_penale` in gara sullo stesso riferimento (la rotta e
        # lo sweeper che la riprende) fanno DUE note per una riga di giornale (nessun UNIQUE su
        # note.giornale_seq) e riscuotono la penale due volte (lo storico degli offset si legge una
        # volta sola). Una alla volta, sotto la stessa chiave dei bonifici che la penale consuma.
        fc = self.sis.finanza
        vera = fc.processa_penale
        sotto = []

        def _spia(**kw):
            sotto.append(fase83_server._BONIFICI_LOCK._is_owned())
            return vera(**kw)
        rif = self._prenota_paga()
        with mock.patch.object(fc, "processa_penale", side_effect=_spia):
            s, c = self._cancella(rif)
        self.assertEqual(200, s, c)
        rif2 = self._prenota_paga()
        self.assertTrue(self.sis.pagamenti_pendenti.marca_cancellata_host(rif2, 3000))
        with mock.patch.object(fc, "processa_penale", side_effect=_spia):
            self._sweep()
        self.assertEqual([True, True], sotto,
                         "la penale si scrive FUORI dal lucchetto (rotta, sweeper): %r" % sotto)

    def test_137_G7_la_ripresa_vede_una_prenotazione_vecchia_cancellata_adesso(self):
        # PROTON P1-SEXIES (b): `cancellate_host` prendeva le 50 piu' recenti per data di
        # PRENOTAZIONE, e 'cancellata_host' non si purga mai: dopo 50 cancellazioni dell'host una
        # prenotazione di un mese fa cancellata OGGI, col processo morto dopo il CAS, restava fuori
        # dall'elenco per sempre (ospite senza rimborso, host pagabile, in silenzio).
        pp = self.sis.pagamenti_pendenti
        rif = self._prenota_paga()
        con = pp._apri()
        try:
            with con:
                con.execute("UPDATE pendenti SET creato_ts = creato_ts - 2592000 WHERE riferimento=?",
                            (rif,))
        finally:
            con.close()
        ora = int(time.time())
        with mock.patch.object(pp, "_now", return_value=ora - 3600):
            for i in range(51):
                self.assertTrue(pp.registra("ALTRA%02d" % i, alloggio_id="hotel", check_in=_CI_FC,
                                            check_out=_CO_FC, host_id="demo"))
                self.assertTrue(pp.marca_cancellata_host("ALTRA%02d" % i, 0))
        self._solo_il_cas(rif)
        self.assertEqual("maturato", self.sis.payout.stato_di(rif), "PREMESSA: bonifico ancora li'")
        self._sweep()
        self.assertIsNone(self.sis.payout.info(rif),
                          "la cancellazione di una prenotazione vecchia non viene ripresa: host "
                          "ancora pagabile")
        self.assertEqual(1, self._tipi(rif).count("rimborso"), self._tipi(rif))

    def test_137_G8_una_prenotazione_NON_pagata_si_cancella_senza_penale_ne_rimborso(self):
        _s, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "hotel", "check_in": _CI_FC,
                       "check_out": _CO_FC, "party": 2})
        _s, b = self.g("POST", "/api/concierge/book", {"quote_token": q["quote_token"],
                       "email": "np@collaudo.invalid"})
        rif = b["riferimento"]
        self.assertEqual("in_attesa", self.sis.pagamenti_pendenti.info(rif)["stato"],
                         "PREMESSA: non pagata")
        (s, c), rinviate = self._con_gli_errori(lambda: self._cancella(rif))
        self.assertEqual(200, s, c)
        self.assertEqual((0, 0), (c.get("penale_host_cents"), c.get("rimborso_cliente_cents")), c)
        self.assertNotIn("nota_debito_in_attesa", c, c)
        self.assertEqual([], rinviate, "una cancellazione senza penale grida «nota rinviata»")
        self.assertEqual([], self._rimborsi(rif), "rimborso per soldi mai entrati")
        fc = self.sis.finanza
        with mock.patch.object(fc, "processa_penale", wraps=fc.processa_penale) as pen:
            self._sweep()
        self.assertEqual(0, pen.call_count, "lo sweeper cerca una penale che non c'e'")
        self.assertEqual([], self._rimborsi(rif), "lo sweeper rimborsa soldi mai entrati")
        self.assertEqual([], self._note_debito(rif))

    def test_137_G9_senza_giornale_la_cancellazione_va_in_fondo_e_lo_sweeper_non_si_ferma(self):
        # D19: il componente del giornale ASSENTE (un avvio senza db_finanza)
        rif = self._prenota_paga()
        meta = [self._prenota_paga(), self._prenota_paga()]
        for r in meta:
            self._solo_il_cas(r)
        self.sis.finanza = None
        s, c = self._cancella(rif)
        self.assertEqual(200, s, c)
        self.assertEqual(set(), {"nota_debito", "nota_debito_in_attesa"} & set(c), c)
        self.assertIsNone(self.sis.payout.info(rif), "host ancora pagabile su una cancellata")
        self._sweep()
        self.assertEqual([None, None], [self.sis.payout.info(r) for r in meta],
                         "senza giornale la ripresa si ferma alla prima cancellazione")

    def test_137_G10_senza_host_nel_corpo_la_penale_va_all_host_della_prenotazione(self):
        rif = self._prenota_paga()
        s, c = self.g("POST", "/api/host/cancella", {"riferimento": rif}, _HK_FC)
        self.assertEqual(200, s, c)
        self.assertTrue(str(c.get("nota_debito") or "").startswith("ND-"), c)
        self.assertEqual(["host:demo"], [n.get("soggetto") for n in self._note_debito(rif)])

    def test_137_G11_il_blocco_sulla_carta_lo_annulla_la_rotta_non_lo_sweeper(self):
        pp = self.sis.pagamenti_pendenti
        rif, rif2 = self._prenota_paga(), self._prenota_paga()
        dopo = int(time.time()) + 86400
        # D19: due pagamenti BLOCCATI sulla carta (soldi autorizzati, non incassati)
        self.assertTrue(pp.segna_blocco(rif, blocco_pi="pi_g11", blocco_incassa_dal_ts=dopo))
        self.assertTrue(pp.segna_blocco(rif2, blocco_pi="pi_g11b", blocco_incassa_dal_ts=dopo))
        self._solo_il_cas(rif2)
        stripe = mock.Mock()
        stripe.annulla.return_value = {"ok": True, "id": "pi_g11"}
        self.sis.stripe = stripe
        self._sweep()
        self.assertEqual([], stripe.annulla.call_args_list, "lo sweeper ha chiamato Stripe")
        self.assertIsNone(self.sis.payout.info(rif2), "PREMESSA: la ripresa e' passata")
        self.assertEqual([], self._rimborsi(rif2), "blocco aperto: soldi mai entrati, niente riga")
        s, c = self._cancella(rif)
        self.assertEqual(200, s, c)
        self.assertEqual([mock.call("pi_g11", "annullo:" + rif)], stripe.annulla.call_args_list,
                         "la rotta non annulla il blocco sulla carta")
        self.assertEqual([], self._rimborsi(rif), "blocco annullato: niente riga di rimborso")

    def test_137_G12_lo_sweeper_scrive_il_rimborso_del_TOTALE_nella_sua_valuta(self):
        rif, rif2 = self._prenota_paga(), self._prenota_paga()
        g1, g2 = self._solo_il_cas(rif), self._solo_il_cas(rif2)
        # D19: un totale diverso dal prezzo (tassa, costi), una valuta che non e' l'euro, e una
        # riga vecchia senza `totale_cents`
        self._corpo(rif, prezzo_guest_cents=g1 - 1000, valuta="USD")
        self._corpo(rif2, totale_cents=None)
        self._sweep()
        self.assertEqual([(g1, "USD")], [(int(m["importo_cents"]), m.get("valuta"))
                                         for m in self._rimborsi(rif)])
        self.assertEqual([g2], [int(m["importo_cents"]) for m in self._rimborsi(rif2)])

    def test_137_G13_una_ripresa_che_esplode_lascia_la_traccia_e_non_ferma_le_altre(self):
        rif, rif2 = self._prenota_paga(), self._prenota_paga()
        self._solo_il_cas(rif)
        self._solo_il_cas(rif2)
        vera = self.r._completa_cancellazione_host

        def _esplode_su_rif(ref, *a, **k):
            if ref == rif:
                raise RuntimeError("archivio giu'")
            return vera(ref, *a, **k)
        with mock.patch.object(self.r, "_completa_cancellazione_host", side_effect=_esplode_su_rif), \
                self.assertLogs("core_auto.server", level="WARNING") as registro:
            self._sweep()
        tracce = [r for r in registro.records if "ripresa cancellazione host fallita" in r.getMessage()]
        self.assertEqual(1, len(tracce), [r.getMessage() for r in registro.records])
        # Giudice del 26/10 (contenitore): con `exc_info=False` la prova restava verde, perche'
        # False «non e' None». La traccia e' la tupla dell'eccezione vera.
        ei = tracce[0].exc_info
        self.assertTrue(isinstance(ei, tuple) and ei[0] is RuntimeError,
                        "il guasto della ripresa non lascia la sua traccia: %r" % (ei,))
        self.assertIsNone(self.sis.payout.info(rif2), "un guasto su una ferma le altre")
        self.assertEqual(1, len(self._note_debito(rif)), "la penale non si riprende dopo il guasto")

    def test_137_G14_lo_sweeper_non_rimborsa_un_blocco_gia_ANNULLATO(self):
        # PROTON sul diff finale (26/10): con `("aperto",)` al posto di `("aperto", "annullato")`
        # nel ramo dello sweeper nessuna prova diventava rossa. La strada vera: il processo muore
        # dopo il CAS col blocco aperto, il giro orario lo annulla, lo sweeper riprende. D19: il
        # blocco annullato si scrive a mano, come in G11.
        pp = self.sis.pagamenti_pendenti
        rif = self._prenota_paga()
        dopo = int(time.time()) + 86400
        self.assertTrue(pp.segna_blocco(rif, blocco_pi="pi_g14", blocco_incassa_dal_ts=dopo))
        self._solo_il_cas(rif)
        self.assertTrue(pp.segna_blocco(rif, blocco_annullato_ts=int(time.time())))
        self.assertEqual("annullato", fase83_server._blocco(pp.info(rif))["stato"], "PREMESSA")
        self._sweep()
        self.assertIsNone(self.sis.payout.info(rif), "PREMESSA: la ripresa e' passata")
        self.assertEqual([], self._rimborsi(rif),
                         "blocco annullato = soldi mai entrati, e lo sweeper scrive la riga del "
                         "rimborso: finisce nella lista dei rimborsi dovuti")

    def test_137_G15_lo_sweeper_non_dice_fatto_quello_che_non_ha_fatto(self):
        # PROTON sul diff finale (26/10), misurato: col giornale giu' anche durante lo sweeper il
        # registro diceva «passi ripresi» e «ND emessa» (WARNING, a ogni giro) senza una nota ne'
        # una riga di rimborso. Il Guardiano legge gli ERROR: si grida, col suo codice.
        rif = self._prenota_paga()
        self._solo_il_cas(rif)
        with mock.patch.object(self.sis.finanza, "registra", return_value=None), \
                self.assertLogs("core_auto.server", level="WARNING") as registro:
            self._sweep()
        msg = [r.getMessage() for r in registro.records]
        self.assertEqual([], self._rimborsi(rif), "PREMESSA: col giornale giu' la riga non c'e'")
        self.assertEqual([], self._note_debito(rif), "PREMESSA: col giornale giu' la nota non c'e'")
        self.assertEqual([], [m for m in msg if "ND emessa" in m or "passi ripresi" in m],
                         "il registro dice fatto quello che non e' stato fatto")
        errori = [r.getMessage() for r in registro.records if r.levelname == "ERROR"]
        self.assertEqual(1, len([m for m in errori if "codice: ripresa_incompleta" in m]), msg)
        self.assertEqual(1, len([m for m in errori if "codice: nota_debito_rinviata" in m]), msg)

    def test_137_G16_col_totale_a_zero_non_si_chiede_una_riga_di_rimborso(self):
        # PROTON sul diff finale (26/10): il `guest > 0` tolto in `_completa_cancellazione_host`
        # faceva chiedere una riga di rimborso da zero euro, e test_blocco_carta lo vieta gia' (D19:
        # la prima difesa e' chi chiama, `_giornale` e' la seconda). Quel file il Giudice non lo
        # accende: la stessa regola sta anche qui.
        rif = self._prenota_paga()
        self._corpo(rif, totale_cents=0, prezzo_guest_cents=0)
        with mock.patch.object(self.r, "_giornale", wraps=self.r._giornale) as gio:
            s, c = self._cancella(rif)
        self.assertEqual(200, s, c)
        self.assertEqual([], [k for k in gio.call_args_list if k.kwargs.get("tipo") == "rimborso"],
                         "chiesta una riga di rimborso da zero euro")

    def test_137_G17_una_ripresa_riuscita_non_grida(self):
        # PROTON (26/10, N9 e N10): G15 pretende l'ERROR col giornale giu', ma nessuna prova
        # pretendeva il SILENZIO quando la ripresa riesce. Un allarme che grida sempre passava, e
        # un allarme che grida sempre si spegne (ferrea 10).
        rif = self._prenota_paga()
        self._solo_il_cas(rif)
        with self.assertLogs("core_auto.server", level="WARNING") as registro:
            self._sweep()
        msg = [r.getMessage() for r in registro.records]
        self.assertEqual(1, len(self._note_debito(rif)), "PREMESSA: la ripresa e' riuscita")
        self.assertEqual([], [r.getMessage() for r in registro.records if r.levelname == "ERROR"
                              and "codice: " in r.getMessage()],
                         "una ripresa riuscita grida come una fallita: %r" % msg)
        self.assertEqual(1, len([m for m in msg if "passi ripresi" in m]), msg)
        self.assertEqual(1, len([m for m in msg if "ND emessa" in m]), msg)

    def test_137_G18_la_penale_che_ESPLODE_non_ferma_la_cancellazione(self):
        # Kimi K18 punto 4 (26/10): `processa_penale` puo' anche SOLLEVARE (l'UPDATE della nota e
        # il debito, fase177, non hanno try: database bloccato), non solo tornare None. Dopo il
        # CAS la rotta non lo prendeva: l'host vedeva un errore con la cancellazione gia' fatta.
        # PROTON (26/10): il guasto e' quello VERO di SQLite, `OperationalError`, che non e' un
        # RuntimeError: un `except RuntimeError` restava verde con una prova che esplodeva cosi'.
        rif = self._prenota_paga()
        with mock.patch.object(self.sis.finanza, "processa_penale",
                               side_effect=sqlite3.OperationalError("database is locked")):
            (s, c), rinviate = self._con_gli_errori(lambda: self._cancella(rif))
        self.assertEqual(200, s, c)
        self.assertEqual("cancellata_host", c.get("stato"), c)
        self.assertIs(True, c.get("nota_debito_in_attesa"), c)
        self.assertEqual(1, len(rinviate), "la penale esplosa non grida col suo codice")
        self.assertIs(True, rinviate[0].kwargs.get("exc_info"), "il guasto non lascia la traccia")
        self.assertIn(fase83_server._rif_per_registro(rif), rinviate[0].args,
                      "l'allarme non dice QUALE prenotazione (ferrea 9)")
        self.assertIsNone(self.sis.payout.info(rif), "host ancora pagabile su una cancellata")
        self.assertEqual(1, len(self._rimborsi(rif)), "l'ospite resta senza la riga del rimborso")
        self._sweep()
        self.assertEqual(1, len(self._note_debito(rif)), "la nota non la riprende lo sweeper")

    def test_137_G19_una_penale_che_esplode_nello_sweeper_non_ferma_le_altre(self):
        # Kimi K18 su G13 (26/10): `_riprendi_cancellazione_host` proteggeva solo i passi; un guasto
        # nella penale (`_penale_finita`, `processa_penale`) usciva dal giro, e le cancellazioni
        # dietro restavano a meta'. Esplode la PRIMA ripresa, qualunque sia l'ordine.
        rif, rif2 = self._prenota_paga(), self._prenota_paga()
        self._solo_il_cas(rif)
        self._solo_il_cas(rif2)
        fc = self.sis.finanza
        vera, chiamate = fc.processa_penale, []

        def _la_prima_esplode(**kw):
            chiamate.append(kw.get("riferimento"))
            if len(chiamate) == 1:
                raise sqlite3.OperationalError("database is locked")    # il guasto vero (G18)
            return vera(**kw)
        with mock.patch.object(fc, "processa_penale", side_effect=_la_prima_esplode), \
                self.assertLogs("core_auto.server", level="WARNING") as registro:
            self._sweep()
        self.assertEqual(2, len(chiamate), "il guasto della prima ferma la ripresa delle altre")
        self.assertEqual({rif, rif2}, set(chiamate))
        self.assertEqual(1, len(self._note_debito(chiamate[1])), "la seconda nota non e' nata")
        tracce = [r for r in registro.records
                  if r.levelname == "ERROR" and "codice: ripresa_fallita" in r.getMessage()]
        self.assertEqual(1, len(tracce), [r.getMessage() for r in registro.records])
        ei = tracce[0].exc_info
        self.assertTrue(isinstance(ei, tuple) and ei[0] is sqlite3.OperationalError,
                        "il guasto della ripresa non lascia la sua traccia: %r" % (ei,))
        self.assertIn(fase83_server._rif_per_registro(chiamate[0]), tracce[0].getMessage(),
                      "l'allarme non dice QUALE prenotazione e' rimasta indietro (ferrea 9)")


class TestLeLettureDellaRipresaDellaCancellazione(unittest.TestCase):
    """VOCE 137: le due letture con cui lo sweeper decide se toccare una 'cancellata_host', ogni
    ramo da solo, con componenti finti -- anche gli stati che il flusso non produce (D19)."""

    class _Giornale:
        def __init__(self, note=(), debiti=None, eventi=()):
            self._note, self._debiti, self._eventi = list(note), dict(debiti or {}), set(eventi)
            self.chiesti = []

        def note_per_riferimento(self, rif):
            return list(self._note)

        def debiti_host(self, host):
            self.chiesti.append(host)
            return list(self._debiti.get(host, []))

        def esiste_evento(self, ev):
            return ev in self._eventi

    def test_la_penale_e_finita_solo_con_la_riga_del_debito_della_sua_nota(self):
        G, finita = self._Giornale, fase83_server._penale_finita
        nd = {"tipo": "debito", "nota_id": "ND-1", "soggetto": "host:demo", "storno_di": None}
        g = G([nd], {"demo": [{"debito_id": "ND-1"}]})
        self.assertIs(True, finita(g, "R"))
        self.assertEqual(["demo"], g.chiesti, "il debito si cerca fra quelli dell'host della nota")
        self.assertIs(False, finita(G([nd], {"demo": [{"debito_id": "ND-9"}]}), "R"))
        self.assertIs(False, finita(G([], {"demo": [{"debito_id": "ND-1"}]}), "R"))
        nc = {"tipo": "credito", "nota_id": "NC-1", "soggetto": "host:demo", "storno_di": None}
        self.assertIs(False, finita(G([nc], {"demo": [{"debito_id": "NC-1"}]}), "R"))
        storno = dict(nd, storno_di="NC-0")
        self.assertIs(False, finita(G([storno], {"demo": [{"debito_id": "ND-1"}]}), "R"))

    def test_una_cancellazione_e_a_meta_solo_se_si_vede_un_effetto_mancante(self):
        import types
        a_meta = fase83_server._cancellazione_host_a_meta

        def sis(payout, garanzia, finanza):
            return types.SimpleNamespace(payout=payout, garanzia=garanzia, finanza=finanza)

        def componente(metodo, valore):
            m = mock.Mock()
            getattr(m, metodo).return_value = valore
            return m
        pd_c, pd_v = componente("info", {"stato": "maturato"}), componente("info", None)
        gz_a = componente("stato", {"stato": "in_garanzia"})
        gz_c = componente("stato", {"stato": "annullato"})
        gz_n = componente("stato", None)
        g_si, g_no = self._Giornale(eventi={"rimborso:R"}), self._Giornale()
        nessuno = {"corpo_json": "{}"}
        aperto = {"corpo_json": json.dumps({"blocco_pi": "pi_x"})}
        incassato = {"corpo_json": json.dumps({"blocco_pi": "pi_x", "blocco_incassato_ts": 5})}
        casi = [
            ("tutto finito", sis(pd_v, gz_c, g_si), nessuno, True, 100, False),
            ("bonifico ancora li'", sis(pd_c, gz_c, g_si), nessuno, True, 100, True),
            ("garanzia aperta", sis(pd_v, gz_a, g_si), nessuno, True, 100, True),
            ("soldi entrati senza riga", sis(pd_v, gz_c, g_no), nessuno, True, 100, True),
            ("non pagata", sis(pd_v, gz_c, g_no), nessuno, False, 100, False),
            ("pagata a zero", sis(pd_v, gz_c, g_no), nessuno, True, 0, False),
            ("senza giornale", sis(pd_v, gz_c, None), nessuno, True, 100, False),
            ("blocco aperto", sis(pd_v, gz_c, g_no), aperto, True, 100, False),
            ("blocco incassato", sis(pd_v, gz_c, g_no), incassato, True, 100, True),
            ("componenti assenti", sis(None, None, g_si), nessuno, True, 100, False),
            ("garanzia illeggibile", sis(pd_v, gz_n, g_si), nessuno, True, 100, False),
        ]
        for nome, s, rec, pagata, guest, atteso in casi:
            with self.subTest(nome):
                self.assertIs(atteso, a_meta(s, rec, "R", pagata=pagata, guest=guest))


class TestUnPagamentoConfermatoNonLasciaIlBonificoFermo(_BancoDeiSoldiDelServer):
    """C53-B1-5 (busta 8): dopo la conferma il bonifico dell'host passa da 'in_attesa' a
    'maturato'. Se quel passo falliva (archivio bloccato: `aggiorna_stato` risponde False) il
    ritorno non si guardava, il webhook rispondeva 200 e Stripe non ritentava MAI: il
    bonifico restava 'in_attesa' per sempre, l'host non veniva pagato, e nessun allarme
    (il Guardiano cerca i bonifici fermi solo fra i 'maturato')."""

    def test_se_il_bonifico_non_matura_Stripe_deve_RITENTARE_e_il_ritentativo_sana(self):
        self.pubblica("casa-mat")
        b = self.prenota("casa-mat", 10)
        rif = b["riferimento"]
        _deve(self.sis.payout.stato_di(rif) == "in_attesa", self.sis.payout.stato_di(rif))
        vero = self.sis.payout.aggiorna_stato

        def bloccato(prenotazione_id, nuovo):
            return False if nuovo == "maturato" else vero(prenotazione_id, nuovo)
        self.sis.payout.aggiorna_stato = bloccato
        s, c = self.paga(rif, "pi_mat")
        self.assertEqual(503, s, "IL BONIFICO E' RIMASTO FERMO E STRIPE NON RITENTERA': il "
                                 "webhook ha risposto %s %r" % (s, c))
        self.assertEqual("in_attesa", self.sis.payout.stato_di(rif))
        self.assertEqual("pagato", self.sis.pagamenti_pendenti.info(rif)["stato"])
        self.sis.payout.aggiorna_stato = vero            # l'archivio torna libero
        s, c = self.paga(rif, "pi_mat")                  # Stripe ritenta
        self.assertEqual(200, s, c)
        self.assertEqual("maturato", self.sis.payout.stato_di(rif),
                         "il ritentativo non ha sanato il bonifico fermo")
        s, c = self.paga(rif, "pi_mat")                  # e una riconsegna in piu' non e' un 503
        self.assertEqual(200, s, "un bonifico GIA' maturato fa ritentare Stripe all'infinito: "
                                 "%r" % (c,))
        self.assertEqual(1, len(self.incassi(rif)), "%r" % (self.incassi(rif),))

    def test_finche_il_bonifico_resta_fermo_ANCHE_il_ritentativo_risponde_503(self):
        # il ritentativo passa da un'altra strada (il pagamento e' gia' 'pagato'): anche li'
        # un bonifico fermo non puo' diventare «gestito»
        self.pubblica("casa-mat2")
        b = self.prenota("casa-mat2", 10)
        rif = b["riferimento"]
        vero = self.sis.payout.aggiorna_stato
        self.sis.payout.aggiorna_stato = (
            lambda pid, nuovo: False if nuovo == "maturato" else vero(pid, nuovo))
        s1, c1 = self.paga(rif, "pi_mat2")
        _deve(s1 == 503, "PREMESSA: la prima consegna deve fallire", s1, c1)
        s2, c2 = self.paga(rif, "pi_mat2")               # ritenta con l'archivio ancora bloccato
        self.assertEqual(503, s2, "il ritentativo ha detto «gestito» con il bonifico ancora "
                                  "fermo: %r" % (c2,))
        self.assertEqual("in_attesa", self.sis.payout.stato_di(rif))


class TestUnaContestazioneDiCartaFermaIlBonifico(_BancoDeiSoldiDelServer):
    """C53-B1-4 (busta 8): nessuno gestiva `charge.dispute.created`. L'ospite contesta
    l'addebito con la sua banca, Stripe toglie importo e commissione dal NOSTRO saldo, e il
    bonifico all'host partiva lo stesso allo scadere della garanzia; nel registro niente.
    Stripe: «Non puoi emettere un rimborso al di fuori della procedura di contestazione quando
    ce n'e' una» -- decide una persona, quindi la garanzia si ferma come per un reclamo
    dell'ospite e lo dice un ERROR (che il Guardiano manda per email)."""

    def _pagata(self, slug, pi):
        self.pubblica(slug)
        b = self.prenota(slug, 10)
        rif = b["riferimento"]
        s, c = self.paga(rif, pi)
        _deve(s == 200, s, c)
        _deve(self.sis.garanzia.stato(rif)["stato"] == "in_garanzia",
              self.sis.garanzia.stato(rif))
        _deve(self.sis.payout.stato_di(rif) == "maturato", self.sis.payout.stato_di(rif))
        return rif

    def test_la_contestazione_FERMA_la_garanzia_e_il_bonifico_e_grida(self):
        rif = self._pagata("casa-dsp", "pi_dsp")
        with self.ascolta() as righe:
            s, c = self.contestazione("pi_dsp")
        self.assertEqual(200, s, c)
        self.assertEqual("contestato", self.sis.garanzia.stato(rif)["stato"],
                         "UNA CONTESTAZIONE DI CARTA NON FERMA LA GARANZIA: allo scadere il "
                         "bonifico all'host parte con i soldi che Stripe ci ha gia' tolto")
        self.assertEqual("trattenuto", self.sis.payout.stato_di(rif))
        self.assertTrue(self.errori_con(righe, "chargeback", "dp_banco1"),
                        "nessun ERROR che dica la contestazione: %r" % (righe,))
        # il giro orario di produzione: rilascio delle garanzie scadute + bonifico
        for r in self.sis.garanzia.auto_rilascia(ora_ts=int(time.time()) + 40 * 86400,
                                                 dettagli=True) or []:
            self.r._trasferisci_all_host(r["prenotazione_id"], r["host_riceve_cents"])
        self.assertEqual([], self.connect.bonifici,
                         "dopo la contestazione il bonifico all'host e' partito: %r"
                         % (self.connect.bonifici,))

    def test_la_contestazione_su_un_bonifico_GIA_PARTITO_lo_dice(self):
        rif = self._pagata("casa-dsp2", "pi_dsp2")
        for r in self.sis.garanzia.auto_rilascia(ora_ts=int(time.time()) + 40 * 86400,
                                                 dettagli=True) or []:
            self.r._trasferisci_all_host(r["prenotazione_id"], r["host_riceve_cents"])
        _deve(self.sis.payout.stato_di(rif) == "in_transito", self.sis.payout.stato_di(rif))
        with self.ascolta() as righe:
            s, c = self.contestazione("pi_dsp2", dp="dp_banco2")
        self.assertEqual(200, s, c)
        self.assertTrue(self.errori_con(righe, "bonifico_gia_partito", "dp_banco2"),
                        "una contestazione su un bonifico gia' partito non grida: %r" % (righe,))

    def test_la_contestazione_su_un_pagamento_SCONOSCIUTO_grida_e_non_fa_ritentare(self):
        with self.ascolta() as righe:
            s, c = self.contestazione("pi_mai_visto", dp="dp_banco3")
        self.assertEqual(200, s, c)
        self.assertTrue(self.errori_con(righe, "pagamento_sconosciuto", "dp_banco3"),
                        "una contestazione che non sappiamo a chi appartiene tace: %r" % (righe,))

    def test_se_la_garanzia_non_si_ferma_Stripe_deve_RITENTARE(self):
        self._pagata("casa-dsp4", "pi_dsp4")
        self.sis.garanzia.contesta = lambda *a, **k: {"ok": False, "motivo": "archivio"}
        with self.ascolta() as righe:
            s, c = self.contestazione("pi_dsp4", dp="dp_banco4")
        self.assertEqual(503, s, "la garanzia non si e' fermata e il webhook dice «gestito»: "
                                 "%r" % (c,))
        self.assertTrue(self.errori_con(righe, "dp_banco4"), "%r" % (righe,))

    def test_se_il_bonifico_non_si_trattiene_Stripe_deve_RITENTARE(self):
        rif = self._pagata("casa-dsp5", "pi_dsp5")
        self.sis.payout.aggiorna_stato = lambda *a, **k: False
        with self.ascolta() as righe:
            s, c = self.contestazione("pi_dsp5", dp="dp_banco5")
        self.assertEqual(503, s, "il bonifico e' rimasto pagabile e il webhook dice «gestito»: "
                                 "%r" % (c,))
        self.assertEqual("maturato", self.sis.payout.stato_di(rif))
        self.assertTrue(self.errori_con(righe, "bonifico_non_trattenuto", "dp_banco5"),
                        "%r" % (righe,))

    def test_una_garanzia_MAI_APERTA_non_fa_ritentare_ma_il_bonifico_si_ferma(self):
        # senza garanzia il bonifico e' l'UNICA protezione: i giri dei bonifici fermi pagano
        # chi non ha una garanzia aperta
        rif = self._pagata("casa-dsp6", "pi_dsp6")
        self.sis.garanzia.contesta = lambda *a, **k: {"ok": False, "motivo": "non_trovata"}
        with self.ascolta() as righe:
            s, c = self.contestazione("pi_dsp6", dp="dp_banco6")
        self.assertEqual(200, s, "ritentare non fa nascere una garanzia: %r" % (c,))
        self.assertEqual("trattenuto", self.sis.payout.stato_di(rif))
        self.assertTrue(self.errori_con(righe, "chargeback", "dp_banco6"), "%r" % (righe,))

    def test_se_la_ricerca_ESPLODE_Stripe_ritenta_e_il_registro_lo_dice(self):
        # D19: l'archivio illeggibile si costruisce a mano
        import sqlite3

        def esplode(*a, **k):
            raise sqlite3.OperationalError("database is locked")
        self.sis.pagamenti_pendenti.per_payment_intent = esplode
        with self.ascolta() as righe:
            s, c = self.contestazione("pi_dsp7", dp="dp_banco7")
        self.assertEqual(503, s, "%r" % (c,))
        self.assertTrue(self.errori_con(righe, "contestazione_esplosa", "dp_banco7",
                                        "|exc_info:OperationalError"), "%r" % (righe,))


class TestUnSoggiornoGiaIniziatoNonSiCancellaDalVoucher(_BancoDeiSoldiDelServer):
    """(m) in RIPRENDI_QUI, misurato l'11/10 sul prodotto (banco vero, Stripe e Connect finti
    al bordo). Delle tre strade verso un rimborso, la cancellazione dell'ospite dal voucher era
    l'unica senza il freno delle altre due (host: `escrow_gia_liquidato`; admin:
    `_garanzia_gia_divisa`). Due danni:
    (1) un soggiorno GIA' FINITO si cancellava: 200, meta' dei soldi indietro con la politica
        flessibile e il Credito Viaggio coniato, perche' «giorno d'arrivo passato» contava come
        «giorno d'arrivo» (la politica promette i rimborsi PRIMA dell'arrivo);
    (2) con la garanzia gia' chiusa a favore dell'host la riga del suo bonifico veniva TOLTA:
        un host senza Stripe collegato (bonifico a mano) non veniva pagato MAI, e i suoi soldi
        restavano a noi. Misurato su quattro politiche su quattro."""

    def _casa(self, slug, politica="flessibile"):
        self.pubblica(slug, politica)
        s, c = self.g("POST", "/api/host/disponibilita_range",
                      {"alloggio_id": slug, "da": _fra(-8), "a": _fra(0), "unita_totali": 1,
                       "prezzo_netto_cents": 10000}, {"X-Host-Token": self.tok})
        _deve(s == 200, s, c)

    def _pagata(self, slug, giorni_all_arrivo, pi):
        b = self.prenota(slug, giorni_all_arrivo)
        s, c = self.paga(b["riferimento"], pi)
        _deve(s == 200, s, c)
        return b

    def _giro_orario(self):
        # il giro di produzione (avvia_server): rilascio delle garanzie scadute + bonifico
        for r in self.sis.garanzia.auto_rilascia(dettagli=True) or []:
            self.r._trasferisci_all_host(r["prenotazione_id"], r["host_riceve_cents"])

    def _cancella(self, b):
        # «adesso» e' l'ora VERA anche per il preventivo: la prenotazione e' stata fatta prima
        # (orologio del preventivo fermo, come in tutto il file), la cancellazione arriva oggi
        with mock.patch.object(fase59_concierge, "time", time):
            return self.g("POST", "/api/concierge/cancella",
                          {"voucher_token": b["voucher_token"]})

    def _rimborsi_nel_giornale(self, rif):
        return [m for m in self.sis.finanza.movimenti(rif) if m.get("tipo") == "rimborso"]

    def test_un_soggiorno_GIA_FINITO_non_si_cancella_dal_voucher(self):
        self._casa("casa-fin")
        b = self._pagata("casa-fin", -4, "pi_fin")       # arrivato 4 giorni fa, partito 2 giorni fa
        rif = b["riferimento"]
        pieno = self.sis.payout.info(rif)["minori"]
        _deve(self.sis.garanzia.stato(rif)["stato"] == "in_garanzia",
              "PREMESSA: il giro orario non e' ancora passato", self.sis.garanzia.stato(rif))
        s, c = self._cancella(b)
        self.assertEqual((409, "soggiorno_iniziato"), (s, (c or {}).get("errore")),
                         "UN SOGGIORNO FINITO SI E' CANCELLATO DAL VOUCHER: %s %r" % (s, c))
        # e NIENTE effetti: pagamento, garanzia, bonifico e giornale come prima
        self.assertEqual("pagato", self.sis.pagamenti_pendenti.info(rif)["stato"])
        self.assertEqual("in_garanzia", self.sis.garanzia.stato(rif)["stato"])
        self.assertEqual(("maturato", pieno), (self.sis.payout.stato_di(rif),
                                               self.sis.payout.info(rif)["minori"]))
        self.assertEqual([], self.connect.bonifici)
        self.assertEqual([], self._rimborsi_nel_giornale(rif))

    def test_dopo_che_la_garanzia_ha_pagato_l_host_il_suo_bonifico_a_mano_RESTA(self):
        _deve(self.sis.registro_host.imposta_stripe_account(self.hid, ""),
              "PREMESSA: l'host deve restare senza Stripe (bonifico a mano)")
        self._casa("casa-man")
        b = self._pagata("casa-man", -4, "pi_man")
        rif = b["riferimento"]
        self._giro_orario()
        st = self.sis.garanzia.stato(rif)
        _deve(st["stato"] == "rilasciato" and self.sis.payout.stato_di(rif) == "maturato"
              and self.connect.bonifici == [],
              "PREMESSA: garanzia rilasciata, bonifico a mano ancora da fare", st,
              self.sis.payout.stato_di(rif), self.connect.bonifici)
        dovuto = int(st["host_riceve_cents"])
        s, c = self._cancella(b)
        self.assertEqual(409, s, "cancellato un soggiorno gia' pagato all'host: %r" % (c,))
        self.assertEqual(("maturato", dovuto),
                         (self.sis.payout.stato_di(rif),
                          (self.sis.payout.info(rif) or {}).get("minori")),
                         "L'HOST HA OSPITATO E NON SARA' MAI PAGATO: la riga del suo bonifico "
                         "a mano e' sparita")
        self.assertEqual(dovuto, self.sis.payout.da_pagare(self.hid, "EUR"))

    def test_con_la_garanzia_chiusa_PRIMA_dell_arrivo_la_cancellazione_non_tocca_i_soldi(self):
        # la garanzia e' gia' dell'host prima dell'arrivo, e la strada e' quella delle altre
        # due -- l'assistenza. Fino al 14/10 ci si arrivava premendo «tutto ok» in anticipo;
        # dalla riparazione (ad) la rotta lo rifiuta (`non_ancora_arrivato`, guardia
        # `test_ad_PRIMA_dell_arrivo_i_due_pulsanti_non_valgono`). Il freno della cancellazione
        # resta la seconda difesa (D19): lo stato si costruisce a mano, con la stessa scrittura
        # della rotta (host senza Stripe: nessun bonifico da far partire).
        _deve(self.sis.registro_host.imposta_stripe_account(self.hid, ""),
              "PREMESSA: l'host deve restare senza Stripe (bonifico a mano)")
        self._casa("casa-ok")
        b = self._pagata("casa-ok", 20, "pi_ok")
        rif = b["riferimento"]
        c = self.sis.garanzia.conferma_ospite(rif)
        _deve(c.get("ok"), "PREMESSA: la garanzia doveva passare all'host", c)
        dovuto = int(self.sis.garanzia.stato(rif)["host_riceve_cents"])
        s, c = self._cancella(b)
        self.assertEqual((409, "escrow_gia_liquidato"), (s, (c or {}).get("errore")),
                         "la cancellazione e' passata con la garanzia gia' dell'host: %s %r"
                         % (s, c))
        self.assertEqual("pagato", self.sis.pagamenti_pendenti.info(rif)["stato"])
        self.assertEqual(("maturato", dovuto),
                         (self.sis.payout.stato_di(rif),
                          (self.sis.payout.info(rif) or {}).get("minori")))
        self.assertEqual([], self._rimborsi_nel_giornale(rif))

    def test_il_GIORNO_D_ARRIVO_si_cancella_ancora_con_la_politica(self):
        # l'altra direzione (ferrea 10): il freno e' sul giorno DOPO l'arrivo, non sul giorno
        # stesso, dove la flessibile promette la meta'. «Oggi» si conta come il server, nel
        # fuso dell'alloggio: a cavallo della mezzanotte puo' essere ieri o domani per il PC.
        self._casa("casa-oggi")
        fuso = self.r._fuso_alloggio("casa-oggi")
        oggi = datetime.date.today()
        if fuso:
            from zoneinfo import ZoneInfo
            oggi = datetime.datetime.now(ZoneInfo(fuso)).date()
        b = self._pagata("casa-oggi", (oggi - datetime.date.today()).days, "pi_oggi")
        s, c = self._cancella(b)
        self.assertEqual(200, s, "il giorno d'arrivo non si cancella piu': %r" % (c,))
        self.assertEqual(int(b["prezzo_guest_cents"]) // 2, int(c["rimborso_cents"]), c)

    def test_ripetere_la_cancellazione_risponde_ancora_gia_cancellata(self):
        # i freni guardano SOLO una prenotazione pagata e viva: un replay (il pagamento e' gia'
        # 'rimborsato') resta quello di sempre, anche con la garanzia chiusa dalla penale
        self._casa("casa-rip", "moderata")
        b = self._pagata("casa-rip", 2, "pi_rip")          # moderata a 2 giorni: meta' e meta'
        rif = b["riferimento"]
        s, c = self._cancella(b)
        _deve(s == 200 and self.sis.garanzia.stato(rif)["stato"] == "risolto",
              "PREMESSA: prima cancellazione con penale", s, c, self.sis.garanzia.stato(rif))
        s, c = self._cancella(b)
        self.assertEqual((200, "gia_cancellata"), (s, (c or {}).get("stato")),
                         "il replay di una cancellazione non risponde piu' «gia' cancellata»: %r"
                         % (c,))
        self.assertEqual(0, c["credito_viaggio_cents"])

    def test_il_freno_scatta_ALLA_MEZZANOTTE_che_chiude_il_giorno_d_arrivo(self):
        # lo stesso confine del preventivo (fase59: `self._now() >= fine`): alla mezzanotte che
        # chiude il giorno d'arrivo il soggiorno e' iniziato; un secondo prima no
        self._casa("casa-mez")
        b1 = self._pagata("casa-mez", -4, "pi_mez1")
        b2 = self._pagata("casa-mez", -7, "pi_mez2")
        conc = self.sis.concierge
        fine1 = conc._fine_giorno_arrivo("casa-mez", _fra(-4))
        fine2 = conc._fine_giorno_arrivo("casa-mez", _fra(-7))
        with mock.patch.object(fase59_concierge, "time", mock.Mock(time=lambda: fine1)):
            s, c = self.g("POST", "/api/concierge/cancella",
                          {"voucher_token": b1["voucher_token"]})
        self.assertEqual((409, "soggiorno_iniziato"), (s, (c or {}).get("errore")),
                         "alla mezzanotte il giorno d'arrivo e' finito: %s %r" % (s, c))
        with mock.patch.object(fase59_concierge, "time", mock.Mock(time=lambda: fine2 - 1)):
            s, c = self.g("POST", "/api/concierge/cancella",
                          {"voucher_token": b2["voucher_token"]})
        self.assertEqual(200, s, "un secondo prima della mezzanotte e' ancora il giorno "
                                 "d'arrivo: %r" % (c,))


class TestUnaControversiaApertaFermaISoldi(_BancoDeiSoldiDelServer):
    """F1, F2 e (ad) in RIPRENDI_QUI. F1 e F2 li ha trovati la macchina delle combinazioni il
    13/10 (campione da 3 a 6 gesti); (ad) e' uscito il 14/10 rileggendo il libro col fondatore.

    F1: «segnala un problema» -> l'ospite cancella -> l'arbitro divide. La cancellazione
        toglieva la riga del bonifico e lasciava la controversia aperta; poi l'arbitro decideva
        la quota dell'host, ma senza quella riga il bonifico usciva muto: l'host collegato non
        era pagato MAI e i suoi soldi restavano alla piattaforma.
    F2: con la contestazione della BANCA aperta, cancellare e arbitrare scrivevano numeri su
        soldi che la banca aveva gia' ripreso, e il pulsante del rimborso rispondeva 502.
        Stripe: «Non puoi emettere un rimborso al di fuori della procedura di contestazione
        quando ce n'e' una» (docs.stripe.com/disputes/how-disputes-work, letto il 13/10).
    (ad): la regola del fondatore (D-10 nel libro) e' «da quando arriva [...] 24 ore per dire
        se va bene o se ci sono problemi. Dopo le 24 ore non puo' fare piu' niente». Il codice
        accettava i due pulsanti in qualunque momento dopo il pagamento.

    Il comportamento che queste prove pretendono (progetto del 13/10, una regola sola come i
    freni dell'11/10): finche' una controversia e' aperta, cancellare (ospite e host) non
    muove soldi -> 409 `controversia_aperta`; con la contestazione della banca anche l'arbitro
    -> 409 `decide_la_banca`. I due pulsanti valgono solo fra l'arrivo e lo sblocco della
    garanzia: prima `non_ancora_arrivato`, dopo `finestra_chiusa`.

    ⚠️ COSA NON GUARDANO (D18 punto 3): i rimborsi dell'admin dal pannello durante una
    controversia; la cancellazione dell'host DOPO l'arrivo; il giro orario che rilascia."""

    def _pagata(self, slug, giorni_all_arrivo, pi, politica="moderata"):
        self.pubblica(slug, politica)
        b = self.prenota(slug, giorni_all_arrivo)
        s, c = self.paga(b["riferimento"], pi)
        _deve(s == 200, s, c)
        return b

    def _segnalata(self, rif):
        """La controversia dell'ospite costruita A MANO con gli stessi due effetti della rotta
        (garanzia contestata, bonifico trattenuto): cosi' la prova di F1 non dipende dalla
        regola dell'arrivo, che e' un'altra riparazione (D19: lo stato si costruisce)."""
        _deve(self.sis.garanzia.contesta(rif, "non corrisponde").get("ok"),
              "PREMESSA: la garanzia doveva poter diventare contestata")
        _deve(self.sis.payout.aggiorna_stato(rif, "trattenuto") is True,
              "PREMESSA: il bonifico doveva fermarsi")

    def _fotografia(self, rif):
        return {"pagamento": self.sis.pagamenti_pendenti.info(rif)["stato"],
                "garanzia": (self.sis.garanzia.stato(rif) or {}).get("stato"),
                "bonifico": self.sis.payout.stato_di(rif),
                "quota": (self.sis.payout.info(rif) or {}).get("minori"),
                "rimborsi": [m.get("importo_cents") for m in self.sis.finanza.movimenti(rif)
                             if m.get("tipo") == "rimborso"],
                "bonificati": list(self.connect.bonifici)}

    def _cancella_ospite(self, b):
        with mock.patch.object(fase59_concierge, "time", time):
            return self.g("POST", "/api/concierge/cancella",
                          {"voucher_token": b["voucher_token"]})

    def _cancella_host(self, rif):
        return self.g("POST", "/api/host/cancella", {"riferimento": rif},
                      {"X-Host-Token": self.tok})

    def _arbitro(self, rif, percentuale_ospite):
        return self.g("POST", "/api/admin/controversia/risolvi",
                      {"riferimento": rif, "percentuale_ospite": percentuale_ospite},
                      {"X-Admin-Key": "ak"})

    def test_F1_con_la_controversia_aperta_l_ospite_NON_cancella(self):
        b = self._pagata("casa-f1a", 2, "pi_f1a")
        rif = b["riferimento"]
        self._segnalata(rif)
        prima = self._fotografia(rif)
        s, c = self._cancella_ospite(b)
        self.assertEqual((409, "controversia_aperta"), (s, (c or {}).get("errore")),
                         "CANCELLATA CON LA CONTROVERSIA APERTA: %s %r" % (s, c))
        self.assertEqual(prima, self._fotografia(rif), "la cancellazione rifiutata ha mosso soldi")

    def test_F1_con_la_controversia_aperta_l_host_NON_cancella(self):
        b = self._pagata("casa-f1b", 2, "pi_f1b")
        rif = b["riferimento"]
        self._segnalata(rif)
        prima = self._fotografia(rif)
        s, c = self._cancella_host(rif)
        self.assertEqual((409, "controversia_aperta"), (s, (c or {}).get("errore")),
                         "L'HOST HA CANCELLATO CON LA CONTROVERSIA APERTA: %s %r" % (s, c))
        self.assertEqual(prima, self._fotografia(rif), "la cancellazione rifiutata ha mosso soldi")

    def test_F1_segnala_cancella_arbitro_e_l_host_collegato_RICEVE_la_sua_quota(self):
        """Il danno vero di F1, guardato alla fine e non a meta': chi tenta di cancellare in
        mezzo non deve far sparire il bonifico che l'arbitro poi decide."""
        b = self._pagata("casa-f1c", 2, "pi_f1c")
        rif = b["riferimento"]
        self._segnalata(rif)
        self._cancella_ospite(b)                 # qualunque cosa risponda, non deve rompere
        s, c = self._arbitro(rif, 50)
        _deve(s == 200, "PREMESSA: l'arbitro doveva decidere", s, c)
        st = self.sis.garanzia.stato(rif)
        quota = int(st["host_riceve_cents"])
        _deve(quota > 0, "PREMESSA: meta' all'host", st)
        self.assertEqual([("acct_banco", quota, "EUR", rif)], self.connect.bonifici,
                         "L'HOST COLLEGATO NON E' STATO PAGATO: garanzia %r, bonifici %r"
                         % (st, self.connect.bonifici))

    def test_F2_con_la_contestazione_della_BANCA_niente_cancellazioni_e_niente_arbitro(self):
        b = self._pagata("casa-f2", 2, "pi_f2")
        rif = b["riferimento"]
        s, c = self.contestazione("pi_f2")
        _deve(s == 200 and self.sis.garanzia.stato(rif)["stato"] == "contestato",
              "PREMESSA: la contestazione della banca doveva fermare la garanzia", s, c,
              self.sis.garanzia.stato(rif))
        prima = self._fotografia(rif)
        esiti = {"ospite": self._cancella_ospite(b), "host": self._cancella_host(rif),
                 "arbitro": self._arbitro(rif, 50)}
        visti = {k: (s, (c or {}).get("errore")) for k, (s, c) in esiti.items()}
        self.assertEqual({"ospite": (409, "controversia_aperta"),
                          "host": (409, "controversia_aperta"),
                          "arbitro": (409, "decide_la_banca")}, visti,
                         "CON LA BANCA CHE CONTESTA QUALCUNO HA MOSSO I SOLDI: %r" % (esiti,))
        self.assertEqual(prima, self._fotografia(rif), "un rifiuto ha mosso soldi")

    def test_F2_quando_la_banca_ha_DECISO_l_arbitro_puo_chiudere(self):
        # l'altro verso (D18 punto 2): il freno non deve lasciare i soldi fermi per sempre
        b = self._pagata("casa-f2-chiusa", 2, "pi_f2c")
        rif = b["riferimento"]
        s, c = self.contestazione("pi_f2c", dp="dp_banco_chiusa")
        _deve(s == 200, "PREMESSA: contestazione della banca registrata", s, c)
        s, c = self.g("POST", "/api/admin/controversia/risolvi",
                      {"riferimento": rif, "percentuale_ospite": 100, "la_banca_ha_deciso": True},
                      {"X-Admin-Key": "ak"})
        self.assertEqual(200, s, "con la banca che ha deciso l'arbitro deve poter chiudere: %r"
                         % (c,))
        self.assertEqual("risolto", self.sis.garanzia.stato(rif)["stato"])

    def _all_istante(self, b, secondi_dallo_sblocco, rotta):
        rif = b["riferimento"]
        sblocco = int(self.sis.garanzia.stato(rif)["sblocco_auto_ts"])
        with mock.patch("time.time", return_value=float(sblocco + secondi_dallo_sblocco)):
            return self.g("POST", rotta, {"voucher_token": b["voucher_token"],
                                          "motivo": "non corrisponde"})

    def test_ad_PRIMA_dell_arrivo_i_due_pulsanti_non_valgono(self):
        from fase160_escrow_garanzia import FINESTRA_ORE_DEFAULT
        prima_dell_arrivo = -(FINESTRA_ORE_DEFAULT + 1) * 3600
        for rotta in ("/api/garanzia/contesta", "/api/garanzia/conferma"):
            with self.subTest(rotta=rotta):
                b = self._pagata("casa-ad" + rotta[-4:], 2, "pi_ad" + rotta[-4:])
                rif = b["riferimento"]
                prima = self._fotografia(rif)
                s, c = self._all_istante(b, prima_dell_arrivo, rotta)
                self.assertEqual((409, "non_ancora_arrivato"), (s, (c or {}).get("errore")),
                                 "%s ACCETTATO PRIMA DELL'ARRIVO: %s %r" % (rotta, s, c))
                self.assertEqual(prima, self._fotografia(rif), "un rifiuto ha mosso soldi")

    def test_ad_DOPO_le_24_ore_l_ospite_non_blocca_piu_i_soldi(self):
        # un minuto dopo lo sblocco, prima che passi il giro orario: la garanzia e' ancora
        # «in_garanzia» nel registro, ma la finestra dell'ospite e' chiusa
        b = self._pagata("casa-ad-dopo", 2, "pi_ad_dopo")
        rif = b["riferimento"]
        prima = self._fotografia(rif)
        s, c = self._all_istante(b, 60, "/api/garanzia/contesta")
        self.assertEqual((409, "finestra_chiusa"), (s, (c or {}).get("errore")),
                         "SEGNALAZIONE ACCETTATA DOPO LE 24 ORE: %s %r" % (s, c))
        self.assertEqual(prima, self._fotografia(rif), "un rifiuto ha mosso soldi")

    def test_ad_SENZA_FUSO_la_segnalazione_vale_dall_arrivo_VERO(self):
        """Trovato il 14/10 rendendo realistiche le prove. Un alloggio senza fuso (citta' e paese
        fuori tabella: Cebu, nelle Filippine) ha la garanzia ancorata all'ULTIMO arrivo possibile
        al mondo (`_istante_checkin_prudente`, le 15:00 a UTC-12): giusto per la chiusura, che
        cosi' non arriva mai prima del giusto. Ma l'arrivo vero a Cebu (UTC+8, nessuna ora legale)
        cade 20 ore prima, e la regola dell'arrivo non deve togliere all'ospite quelle ore. Le
        due direzioni: prima del PRIMO arrivo possibile al mondo (le 15:00 a UTC+14) no; un'ora
        dopo il check-in vero di Cebu si'."""
        self.pubblica("casa-cebu", "moderata", citta="Cebu", paese="PH")
        _deve(self.r._fuso_alloggio("casa-cebu") == "", "PREMESSA: l'alloggio non deve avere un "
              "fuso", self.r._fuso_alloggio("casa-cebu"))
        b = self.prenota("casa-cebu", 2)
        s, c = self.paga(b["riferimento"], "pi_cebu")
        _deve(s == 200, s, c)
        giorno = datetime.date.fromisoformat(_fra(2))

        def alle_15(ore_utc):
            fuso = datetime.timezone(datetime.timedelta(hours=ore_utc))
            return datetime.datetime(giorno.year, giorno.month, giorno.day, 15,
                                     tzinfo=fuso).timestamp()

        def segnala(istante):
            with mock.patch("time.time", return_value=float(istante)):
                return self.g("POST", "/api/garanzia/contesta",
                              {"voucher_token": b["voucher_token"], "motivo": "non corrisponde"})
        s, c = segnala(alle_15(14) - 3600)
        self.assertEqual((409, "non_ancora_arrivato"), (s, (c or {}).get("errore")),
                         "PRIMA del primo arrivo possibile al mondo: %s %r" % (s, c))
        s, c = segnala(alle_15(8) + 3600)
        self.assertEqual(200, s, "UN'ORA DOPO IL CHECK-IN VERO DI CEBU L'OSPITE NON PUO' "
                                 "SEGNALARE: %r" % (c,))

    def test_ad_DENTRO_le_24_ore_la_segnalazione_vale(self):
        # l'altro verso (D18 punto 2): la regola nuova non deve togliere il diritto vero
        b = self._pagata("casa-ad-dentro", 2, "pi_ad_dentro")
        rif = b["riferimento"]
        s, c = self._all_istante(b, -3600, "/api/garanzia/contesta")
        self.assertEqual(200, s, "un'ora prima dello sblocco l'ospite deve poter segnalare: %r"
                         % (c,))
        self.assertEqual("contestato", self.sis.garanzia.stato(rif)["stato"])

    # ⛔ LE QUATTRO PROVE QUI SOTTO LE HA CHIESTE LA MUTAZIONE SUL DIFF DELLA CI (commit a8a2e28,
    # job `caselle`, 14/10): quattro punti di `_controversia_aperta` e `_fuori_dalla_finestra`
    # si potevano rompere senza che nessuna prova se ne accorgesse.

    def test_ad_al_SECONDO_dell_arrivo_si_puo_gia_premere(self):
        """Il confine dell'arrivo (`<` -> `<=` sopravvissuto). Le due direzioni: un secondo
        prima no, al secondo dell'arrivo si'. Cosi' la prova fissa il confine DOVE sta, non
        solo da che parte."""
        from fase160_escrow_garanzia import FINESTRA_ORE_DEFAULT
        arrivo = -FINESTRA_ORE_DEFAULT * 3600
        for rotta in ("/api/garanzia/contesta", "/api/garanzia/conferma"):
            with self.subTest(rotta=rotta):
                b = self._pagata("casa-arr" + rotta[-4:], 2, "pi_arr" + rotta[-4:])
                s, c = self._all_istante(b, arrivo - 1, rotta)
                self.assertEqual((409, "non_ancora_arrivato"), (s, (c or {}).get("errore")),
                                 "%s UN SECONDO PRIMA DELL'ARRIVO: %s %r" % (rotta, s, c))
                s, c = self._all_istante(b, arrivo, rotta)
                self.assertEqual(200, s, "%s AL SECONDO DELL'ARRIVO L'OSPITE NON PUO' PREMERE: %r"
                                 % (rotta, c))

    def test_ad_al_SECONDO_dello_sblocco_la_finestra_e_gia_chiusa(self):
        """Il confine dello sblocco (`>=` -> `>` sopravvissuto): allo sblocco i soldi sono
        dell'host e l'ospite non li ferma piu'; un secondo prima si'. Il rifiuto viene PRIMA,
        cosi' la garanzia e' ancora aperta quando si prova il secondo prima."""
        for rotta in ("/api/garanzia/contesta", "/api/garanzia/conferma"):
            with self.subTest(rotta=rotta):
                b = self._pagata("casa-sbl" + rotta[-4:], 2, "pi_sbl" + rotta[-4:])
                rif = b["riferimento"]
                prima = self._fotografia(rif)
                s, c = self._all_istante(b, 0, rotta)
                self.assertEqual((409, "finestra_chiusa"), (s, (c or {}).get("errore")),
                                 "%s ACCETTATO AL SECONDO DELLO SBLOCCO: %s %r" % (rotta, s, c))
                self.assertEqual(prima, self._fotografia(rif), "un rifiuto ha mosso soldi")
                s, c = self._all_istante(b, -1, rotta)
                self.assertEqual(200, s, "%s UN SECONDO PRIMA DELLO SBLOCCO L'OSPITE NON PUO' "
                                         "PREMERE: %r" % (rotta, c))

    def _garanzia_illeggibile(self):
        import sqlite3

        def esplode(*a, **k):
            raise sqlite3.OperationalError("database is locked")
        self.sis.garanzia.stato = esplode

    def test_garanzia_ILLEGGIBILE_la_cancellazione_dell_host_PROSEGUE(self):
        """Il freno di F1 legge la garanzia; se non si legge (un guasto nostro) la cancellazione
        va avanti, come gli altri freni: mai bloccare una cancellazione legittima per un guasto
        nostro (`return False` -> `True` sopravvissuto). Dall'HOST perche' la cancellazione
        dell'ospite legge la garanzia gia' prima (`_garanzia_gia_divisa`, che su un guasto
        solleva apposta) e non arriverebbe mai a questo freno."""
        b = self._pagata("casa-gz-rotta", 2, "pi_gz_rotta")
        self._garanzia_illeggibile()
        s, c = self._cancella_host(b["riferimento"])
        self.assertEqual((200, "cancellata_host"), (s, (c or {}).get("stato")),
                         "UNA GARANZIA ILLEGGIBILE HA FERMATO LA CANCELLAZIONE: %s %r" % (s, c))

    def test_garanzia_ILLEGGIBILE_il_registro_porta_l_ERRORE_vero(self):
        """L'altra meta' dello stesso guasto (`exc_info=True` -> `False` sopravvissuto): chi
        legge il registro deve trovare l'errore vero, del tipo giusto, non solo la frase."""
        b = self._pagata("casa-gz-registro", 2, "pi_gz_registro")
        self._garanzia_illeggibile()
        with self.ascolta() as righe:
            self._cancella_host(b["riferimento"])
        self.assertTrue(self.errori_con(righe, "CONTROVERSIA NON LETTA",
                                        "|exc_info:OperationalError"), "%r" % (righe,))


class _StripeCheConosceLAddebito(StripeColBlocco):
    """Il fornitore finto del blocco sulla carta (`test_blocco_carta`), piu' la lettura
    dell'addebito per il bonifico legato (Compito 41): un pagamento incassato ha l'addebito
    `ch_<pi senza pi_>`, uno solo autorizzato non ce l'ha ancora."""

    def __init__(self):
        super().__init__()
        self.addebiti_letti = []

    def addebito_di(self, pi):
        self.addebiti_letti.append(pi)
        return "ch_" + pi[3:] if self.pagamenti.get(pi) == "succeeded" else ""


class _ConnectCheRicordaIlLegame:
    """Il bonifico Connect, finto al bordo: ricorda anche A QUALE ADDEBITO e' stato legato."""

    def __init__(self):
        self.bonifici = []

    def trasferisci(self, acct, importo, valuta, rif, source_transaction=""):
        self.bonifici.append((acct, importo, valuta, rif, source_transaction))
        return "tr_%d" % len(self.bonifici)


class _BancoDelBonificoLegato(_BancoDeiSoldiDelServer):
    """Il banco dei soldi, con il blocco sulla carta e l'addebito leggibile."""

    def setUp(self):
        super().setUp()
        self.stripe = _StripeCheConosceLAddebito()
        self.connect = _ConnectCheRicordaIlLegame()
        self.sis.connect = self.connect

    def pagata(self, slug, pi, bloccata, giorni=20, politica="flessibile", **annuncio):
        """Prenotata e pagata: `bloccata` = arrivo lontano, soldi solo AUTORIZZATI sulla carta."""
        self.pubblica(slug, politica, **annuncio)
        b = self.prenota(slug, giorni)
        rif = b["riferimento"]
        self.sis.stripe = self.stripe        # dopo il preventivo: il link lo fa il fornitore vero
        self.stripe.sessioni["cs_" + pi] = ("unpaid" if bloccata else "paid", pi)
        self.stripe.pagamenti[pi] = "requires_capture" if bloccata else "succeeded"
        s, c = self.paga(rif, pi)
        _deve(s == 200 and self.sis.pagamenti_pendenti.info(rif)["stato"] == "pagato", s, c)
        return b

    @staticmethod
    def dopo_la_finestra():
        return int(time.time()) + fase83_server.SECONDI_RIPENSAMENTO + 60

    def tutto_ok(self, b):
        with nella_finestra(self.sis, b["voucher_token"]):
            s, c = self.g("POST", "/api/garanzia/conferma", {"voucher_token": b["voucher_token"]})
        _deve(s == 200 and self.sis.garanzia.stato(b["riferimento"])["stato"] == "rilasciato",
              s, c)

    def giro_orario(self):
        # il giro di produzione (avvia_server): rilascio delle garanzie scadute + bonifico
        for r in self.sis.garanzia.auto_rilascia(ora_ts=int(time.time()) + 40 * 86400,
                                                 dettagli=True) or []:
            self.r._trasferisci_all_host(r["prenotazione_id"], r["host_riceve_cents"])


class TestIlBonificoFermatoDalBloccoRiparteAllIncasso(_BancoDelBonificoLegato):
    """DIFETTO A, trovato dalla macchina delle combinazioni dei soldi l'11/10 sera
    (`test_macchina_dei_soldi.py --una "lontano,flessibile,si,piccolo" "subito:tutto_ok"`).
    Arrivo lontano: i soldi dell'ospite sono solo AUTORIZZATI sulla carta e si incassano dopo
    48 ore. Se in quelle 48 ore l'ospite preme «tutto ok» (il pulsante e' sempre nel voucher) o
    l'arbitro decide, la garanzia passa all'host e il bonifico si FERMA, giustamente (non si
    anticipano soldi nostri). Ma dopo l'incasso nessuno lo ritentava: l'auto-rilascio guarda
    solo le garanzie ancora aperte e i giri dei bonifici fermi partono solo dai dati fiscali o
    dalla verifica dell'host. L'host collegato a Stripe restava senza i suoi soldi per sempre.

    Dal 14/10 (riparazione (ad)) i due pulsanti valgono solo dall'arrivo: qui si premono dentro
    la finestra (`nella_finestra`). Con l'incasso puntuale a 48 ore i soldi a quel punto sono
    gia' incassati; restano solo bloccati se l'incasso fallisce fino all'arrivo (il blocco
    dura 7 giorni, l'arrivo e' ad almeno `GIORNI_MINIMI_BLOCCO`): e' il caso che resta, e
    queste prove lo guardano."""

    def test_TUTTO_OK_prima_dell_incasso_il_bonifico_parte_ALL_INCASSO(self):
        b = self.pagata("casa-a1", "pi_a1", bloccata=True)
        rif = b["riferimento"]
        self.tutto_ok(b)
        _deve(self.connect.bonifici == [], "PREMESSA: soldi solo autorizzati, il bonifico si "
                                           "ferma", self.connect.bonifici)
        dovuto = int(self.sis.garanzia.stato(rif)["host_riceve_cents"])
        with self.ascolta() as righe:
            conta = self.r._incassa_blocchi(ora_ts=self.dopo_la_finestra())
        _deve(conta["incassati"] == 1, "PREMESSA: il giro doveva incassare", conta)
        self.assertEqual([("acct_banco", dovuto, "EUR", rif, "ch_a1")], self.connect.bonifici,
                         "IL BONIFICO FERMATO DAL BLOCCO NON RIPARTE ALL'INCASSO: la garanzia "
                         "da' all'host %d e i soldi ora ci sono, ma partiti %r"
                         % (dovuto, self.connect.bonifici))
        self.assertEqual("in_transito", self.sis.payout.stato_di(rif))
        self.assertEqual([], self.avvisi_con(righe, "IMPORTO RIALLINEATO"),
                         "l'importo chiesto non e' quello della garanzia")

    def test_un_secondo_incasso_dello_stesso_pagamento_non_paga_due_volte(self):
        b = self.pagata("casa-a2", "pi_a2", bloccata=True)
        rif = b["riferimento"]
        self.tutto_ok(b)
        self.r._incassa_blocchi(ora_ts=self.dopo_la_finestra())
        _deve(len(self.connect.bonifici) == 1, "PREMESSA: il primo incasso paga",
              self.connect.bonifici)
        self.r._incassa_blocchi(ora_ts=self.dopo_la_finestra())
        # un giro morto dopo l'incasso: Stripe rifiuta il secondo, si rilegge «succeeded»
        self.assertEqual("incassato", self.r._incassa_blocco(rif, "pi_a2"))
        self.giro_orario()
        self.assertEqual(1, len(self.connect.bonifici),
                         "LO STESSO BONIFICO E' PARTITO PIU' VOLTE: %r" % (self.connect.bonifici,))

    def test_senza_TUTTO_OK_l_incasso_non_paga_l_host_prima_del_soggiorno(self):
        # l'altra direzione (ferrea 10): i soldi incassati non sono ancora dell'host
        b = self.pagata("casa-a3", "pi_a3", bloccata=True)
        rif = b["riferimento"]
        conta = self.r._incassa_blocchi(ora_ts=self.dopo_la_finestra())
        _deve(conta["incassati"] == 1, "PREMESSA: il giro doveva incassare", conta)
        self.assertEqual([], self.connect.bonifici,
                         "BONIFICO PRIMA DEL SOGGIORNO: la garanzia era ancora aperta e sono "
                         "partiti %r" % (self.connect.bonifici,))
        self.assertEqual(("in_garanzia", "maturato"),
                         (self.sis.garanzia.stato(rif)["stato"], self.sis.payout.stato_di(rif)))

    def test_una_garanzia_NON_decisa_non_paga_anche_se_porta_gia_una_quota(self):
        # D19, lo stato si costruisce a mano: oggi la garanzia scrive la quota dell'host solo
        # quando decide (fase160 `_muta`), quindi aperta vale 0 e il bonifico non partirebbe
        # comunque (guasto a mano dell'11/10 rimasto VERDE). La difesa qui non deve dipendere
        # da quel modulo: conta lo STATO, non la cifra.
        b = self.pagata("casa-a6", "pi_a6", bloccata=True)
        rif = b["riferimento"]
        vera = self.sis.garanzia.stato
        for stato in ("in_garanzia", "contestato", "annullato"):
            with self.subTest(stato=stato):
                self.sis.garanzia.stato = (lambda r, stato=stato:
                                           dict(vera(r), stato=stato, host_riceve_cents=17400))
                self.assertEqual("incassato", self.r._incassa_blocco(rif, "pi_a6"))
                self.assertEqual([], self.connect.bonifici,
                                 "BONIFICO SU UNA GARANZIA '%s' (non decisa): %r"
                                 % (stato, self.connect.bonifici))

    def test_l_ARBITRO_prima_dell_incasso_la_quota_dell_host_parte_all_incasso(self):
        b = self.pagata("casa-a4", "pi_a4", bloccata=True)
        rif = b["riferimento"]
        with nella_finestra(self.sis, b["voucher_token"]):
            s, c = self.g("POST", "/api/garanzia/contesta",
                          {"voucher_token": b["voucher_token"], "motivo": "non corrisponde"})
        _deve(s == 200, s, c)
        s, c = self.g("POST", "/api/admin/controversia/risolvi",
                      {"riferimento": rif, "percentuale_ospite": 0}, {"X-Admin-Key": "ak"})
        st = self.sis.garanzia.stato(rif)
        _deve(s == 200 and st["stato"] == "risolto" and self.connect.bonifici == [],
              "PREMESSA: l'arbitro da' tutto all'host, il bonifico si ferma sul blocco", s, c,
              st, self.connect.bonifici)
        conta = self.r._incassa_blocchi(ora_ts=self.dopo_la_finestra())
        _deve(conta["incassati"] == 1, "PREMESSA: il giro doveva incassare", conta)
        self.assertEqual([("acct_banco", int(st["host_riceve_cents"]), "EUR", rif, "ch_a4")],
                         self.connect.bonifici,
                         "LA DECISIONE DELL'ARBITRO NON PAGA L'HOST DOPO L'INCASSO: %r"
                         % (self.connect.bonifici,))

    def test_se_la_garanzia_non_si_legge_l_incasso_RESTA_e_il_registro_lo_dice(self):
        import sqlite3
        b = self.pagata("casa-a5", "pi_a5", bloccata=True)
        rif = b["riferimento"]
        self.tutto_ok(b)

        def esplode(*a, **k):
            raise sqlite3.OperationalError("database is locked")
        self.sis.garanzia.stato = esplode
        with self.ascolta() as righe:
            conta = self.r._incassa_blocchi(ora_ts=self.dopo_la_finestra())
        self.assertEqual(1, conta["incassati"], "un guasto della garanzia ha fermato l'incasso")
        self.assertEqual([], self.connect.bonifici)
        self.assertEqual("maturato", self.sis.payout.stato_di(rif),
                         "il bonifico deve restare da pagare, non sparire")
        self.assertTrue(self.avvisi_con(righe, "bonifico dopo l'incasso non ripartito",
                                        "|exc_info:OperationalError"), "%r" % (righe,))


class TestIlBonificoParteDaiSoldiDellOspite(_BancoDelBonificoLegato):
    """COMPITO 41 (busta 4 di GML, 4/10). Il bonifico all'host usciva dal saldo DISPONIBILE della
    piattaforma: il 4/10 era -0,27 EUR, i soldi appena incassati ci entrano solo dopo giorni e
    i bonifici automatici del conto lo svuotano ogni giorno («Automatic payouts can interfere
    with transfers that don't have a defined source_transaction»). Allora il bonifico falliva,
    Stripe non lo ritenta e l'host aspettava un bonifico a mano. Legato all'ADDEBITO
    dell'ospite (`source_transaction`) Stripe lo accetta e lo esegue quando quei soldi sono
    disponibili (docs.stripe.com/connect/separate-charges-and-transfers, letto l'11/10/2026).
    L'addebito si legge dal pagamento salvato sulla prenotazione (`stripe_pi`)."""

    def test_il_bonifico_e_LEGATO_all_addebito_dell_ospite(self):
        b = self.pagata("casa-c1", "pi_c1", bloccata=False)
        rif = b["riferimento"]
        self.giro_orario()
        dovuto = int(self.sis.garanzia.stato(rif)["host_riceve_cents"])
        self.assertEqual([("acct_banco", dovuto, "EUR", rif, "ch_c1")], self.connect.bonifici,
                         "IL BONIFICO NON E' LEGATO AL PAGAMENTO DELL'OSPITE: esce dal saldo "
                         "disponibile e fallisce se non basta: %r" % (self.connect.bonifici,))
        self.assertEqual(["pi_c1"], self.stripe.addebiti_letti,
                         "l'addebito si legge dal pagamento di QUESTA prenotazione")

    def test_se_l_addebito_non_si_sa_il_bonifico_parte_come_prima_e_lo_dice(self):
        b = self.pagata("casa-c2", "pi_c2", bloccata=False)
        rif = b["riferimento"]
        self.stripe.addebito_di = lambda pi: ""
        with self.ascolta() as righe:
            self.giro_orario()
        dovuto = int(self.sis.garanzia.stato(rif)["host_riceve_cents"])
        self.assertEqual([("acct_banco", dovuto, "EUR", rif, "")], self.connect.bonifici,
                         "senza addebito il bonifico deve partire come prima: %r"
                         % (self.connect.bonifici,))
        self.assertTrue(self.avvisi_con(righe, "BONIFICO NON LEGATO AL PAGAMENTO"),
                        "un bonifico non legato parte in silenzio: %r" % (righe,))

    def test_se_la_lettura_dell_addebito_ESPLODE_il_bonifico_parte_e_il_registro_lo_dice(self):
        b = self.pagata("casa-c3", "pi_c3", bloccata=False)

        def esplode(pi):
            raise RuntimeError("stripe giu")
        self.stripe.addebito_di = esplode
        with self.ascolta() as righe:
            self.giro_orario()
        self.assertEqual([""], [x[4] for x in self.connect.bonifici], "%r" % (self.connect.bonifici,))
        self.assertTrue(self.avvisi_con(righe, "addebito dell'ospite non letto",
                                        "|exc_info:RuntimeError"), "%r" % (righe,))
        self.assertTrue(self.avvisi_con(righe, "BONIFICO NON LEGATO AL PAGAMENTO",
                                        b["riferimento"]), "%r" % (righe,))

    def test_un_legame_con_cio_che_non_e_un_addebito_non_si_manda(self):
        for i, risposta in enumerate(("pi_c4", "re_1", mock.Mock(), b"ch_1", None)):
            with self.subTest(risposta=risposta):
                self.stripe = _StripeCheConosceLAddebito()
                self.pagata("casa-c4-%d" % i, "pi_c4%d" % i, bloccata=False)
                self.connect.bonifici.clear()
                self.stripe.addebito_di = lambda pi, risposta=risposta: risposta
                self.giro_orario()
                self.assertEqual([""], [x[4] for x in self.connect.bonifici],
                                 "legame con %r: %r" % (risposta, self.connect.bonifici))

    def test_senza_un_fornitore_che_legge_l_addebito_il_bonifico_parte_come_prima(self):
        for i, fornitore in enumerate((None, object())):
            with self.subTest(fornitore=fornitore):
                self.pagata("casa-c5-%d" % i, "pi_c5%d" % i, bloccata=False)
                self.connect.bonifici.clear()
                self.sis.stripe = fornitore
                self.giro_orario()
                self.assertEqual([""], [x[4] for x in self.connect.bonifici],
                                 "%r" % (self.connect.bonifici,))


class TestDopoUnaContestazioneDiCartaLaCancellazioneNonLasciaUnBonificoFantasma(
        _BancoDelBonificoLegato):
    """D1, trovato dal giro lungo della macchina il 12/10 (chargeback -> ospite_cancella, e
    chargeback -> admin_rimborso). La contestazione della carta mette il bonifico dell'host a
    'trattenuto'; se poi l'ospite cancella o l'admin rimborsa (host a zero),
    `_payout_trattieni` toglieva la riga solo se 'in_attesa' o 'maturato': la riga restava
    'trattenuto' all'importo PIENO su una prenotazione rimborsata, per sempre (lo stesso D13
    della prova vera: soldi «Fermi» mai dovuti), e chi un giorno sbloccasse i trattenuti
    pagherebbe l'host di una prenotazione cancellata. Quando cancella l'host la riga si toglie
    gia'. Resta 'trattenuto' solo un bonifico GIA' PARTITO (riga `payout_host` nel giornale)."""

    def _contestata(self, slug, pi):
        b = self.pagata(slug, pi, bloccata=False)
        s, c = self.contestazione(pi, dp="dp_" + pi)
        _deve(s == 200 and self.sis.payout.stato_di(b["riferimento"]) == "trattenuto",
              "PREMESSA: la contestazione trattiene il bonifico", s, c,
              self.sis.payout.stato_di(b["riferimento"]))
        return b

    def test_contestazione_poi_l_OSPITE_non_cancella_e_la_riga_del_bonifico_RESTA_trattenuta(self):
        # RISCRITTA il 14/10. Prima l'ospite cancellava con la contestazione della banca aperta
        # e questa prova guardava che la riga del bonifico sparisse col rimborso pieno (D1). Da
        # F2 («autorizzato» del 14/10) con la banca che contesta decide la banca: cancellare
        # risponde `controversia_aperta` e non muove niente, quindi la riga resta 'trattenuto'
        # all'importo pieno, e non e' un fantasma: la prenotazione non e' rimborsata. Il D1 vivo
        # resta sulla strada dell'admin (la prova qui sotto).
        b = self._contestata("casa-d1a", "pi_d1a")
        rif = b["riferimento"]
        riga = self.sis.payout.info(rif)
        s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        self.assertEqual((409, "controversia_aperta"), (s, (c or {}).get("errore")),
                         "CANCELLATA CON LA BANCA CHE CONTESTA: %s %r" % (s, c))
        self.assertEqual(("pagato", "contestato", "trattenuto", riga),
                         (self.sis.pagamenti_pendenti.info(rif)["stato"],
                          self.sis.garanzia.stato(rif)["stato"], self.sis.payout.stato_di(rif),
                          self.sis.payout.info(rif)),
                         "la cancellazione rifiutata ha mosso pagamento, garanzia o bonifico")

    def test_contestazione_poi_l_ADMIN_rimborso_e_rifiutato_e_non_muove_niente(self):
        # RISCRITTA il 25/10 (pacco 1, voce 2, «autorizzato»; Kimi K10). Prima questa prova
        # pretendeva che l'admin rimborsasse con la banca che contesta (garanzia 'annullato',
        # riga del bonifico tolta): l'ospite riceveva i soldi da noi E dalla sua banca. Ora
        # decide la banca, come per la cancellazione dell'ospite qui sopra.
        b = self._contestata("casa-d1b", "pi_d1b")
        rif = b["riferimento"]
        riga = self.sis.payout.info(rif)
        idem = self.sis.firma.decodifica(b["voucher_token"]).get("idem_key", "")
        s, c = self.g("POST", "/api/admin/rimborso",
                      {"alloggio_id": "casa-d1b", "check_in": _fra(20), "check_out": _fra(22),
                       "idem_key": idem}, {"X-Admin-Key": "ak"})
        self.assertEqual((409, "controversia_aperta"), (s, (c or {}).get("errore")),
                         "RIMBORSATO CON LA BANCA CHE CONTESTA: %s %r" % (s, c))
        self.assertEqual(("pagato", "contestato", "trattenuto", riga),
                         (self.sis.pagamenti_pendenti.info(rif)["stato"],
                          self.sis.garanzia.stato(rif)["stato"], self.sis.payout.stato_di(rif),
                          self.sis.payout.info(rif)),
                         "il rimborso rifiutato ha mosso pagamento, garanzia o bonifico")

    def test_contestazione_poi_il_pannello_admin_NON_offre_Rimborsa(self):
        # pacco 1, voce 2 (25/10): lo stesso freno nell'elenco dell'admin (mutante della #279,
        # fase83 `_admin_prenotazioni`: la chiave del calendario resa vuota sopravviveva)
        self._contestata("casa-d1d", "pi_d1d")
        s, adm = self.g("GET", "/api/admin/prenotazioni", None, {"X-Admin-Key": "ak"})
        self.assertEqual(200, s, adm)
        riga = [p for p in adm["prenotazioni"] if p.get("alloggio_id") == "casa-d1d"]
        _deve(len(riga) == 1 and riga[0]["stato"] in ("pagata", "bloccata_sulla_carta", "attiva"),
              "PREMESSA: la prenotazione contestata e' in elenco e pagata", riga)
        self.assertIs(riga[0]["rimborsabile"], False,
                      "«Rimborsa» offerto con la banca che contesta: %r" % (riga[0],))

    def test_un_bonifico_GIA_PARTITO_resta_trattenuto_e_visibile(self):
        # D19, lo stato si costruisce a mano: i soldi sono usciti (riga `payout_host`)
        b = self.pagata("casa-d1c", "pi_d1c", bloccata=False)
        rif = b["riferimento"]
        _deve(self.sis.payout.aggiorna_stato(rif, "trattenuto"), "PREMESSA: trattenuto")
        self.r._giornale(tipo="payout_host", riferimento=rif, soggetto="host:" + self.hid,
                         importo_cents=self.sis.payout.info(rif)["minori"], valuta="EUR",
                         causale="bonifico Connect tr_banco all'host")
        self.assertIs(True, self.r._payout_trattieni(rif))
        self.assertEqual("trattenuto", self.sis.payout.stato_di(rif),
                         "un bonifico gia' partito e' sparito dal registro: nessuno lo vede piu'")

    def test_se_il_giornale_non_si_legge_la_riga_RESTA(self):
        import sqlite3
        b = self.pagata("casa-d1d", "pi_d1d", bloccata=False)
        rif = b["riferimento"]
        _deve(self.sis.payout.aggiorna_stato(rif, "trattenuto"), "PREMESSA: trattenuto")

        def esplode(*a, **k):
            raise sqlite3.OperationalError("database is locked")
        self.sis.finanza.movimenti = esplode
        with self.ascolta() as righe:
            self.assertIs(True, self.r._payout_trattieni(rif))
        self.assertEqual("trattenuto", self.sis.payout.stato_di(rif),
                         "nel dubbio la riga si toglie: un bonifico partito potrebbe sparire")
        self.assertTrue(self.avvisi_con(righe, "giornale illeggibile",
                                        "|exc_info:OperationalError"), "%r" % (righe,))

    def test_senza_giornale_la_riga_RESTA(self):
        # mutante sopravvissuto del 12/10 (riga del `return True` senza giornale)
        b = self.pagata("casa-d1e", "pi_d1e", bloccata=False)
        rif = b["riferimento"]
        _deve(self.sis.payout.aggiorna_stato(rif, "trattenuto"), "PREMESSA: trattenuto")
        self.sis.finanza = None
        self.assertIs(True, self.r._payout_trattieni(rif))
        self.assertEqual("trattenuto", self.sis.payout.stato_di(rif),
                         "senza giornale non si sa se il bonifico e' partito: la riga resta")


class TestLaPenaleFermataPartePoiQuandoLHostSiSblocca(_BancoDelBonificoLegato):
    """D2, trovato dal giro lungo della macchina il 12/10 (host collegato sopra la soglia DAC7:
    l'ospite cancella con penale, poi l'host completa i dati fiscali). La quota-penale
    dell'host parte solo DENTRO la cancellazione, finche' la prenotazione e' ancora 'pagato';
    se in quell'istante il bonifico era fermo (dati fiscali, verifica revocata, interruttore),
    i giri che lo ritentano trovavano 'rimborsato' e `_trasferisci_all_host` usciva muto: la
    quota restava 'maturato' per sempre. Su 'rimborsato' si paga SOLO con la garanzia divisa
    dalla penale ('risolto'), mai oltre la quota che la garanzia assegna, e come penale (niente
    ritenuta: non e' un canone)."""

    def _penale_ferma(self, slug, pi, **annuncio):
        b = self.pagata(slug, pi, bloccata=False, giorni=2, politica="moderata", **annuncio)
        rif = b["riferimento"]
        self.r._dac7_payout_bloccato = lambda hid: (True, ["iban"])
        s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        del self.r._dac7_payout_bloccato
        st = self.sis.garanzia.stato(rif)
        _deve(s == 200 and st["stato"] == "risolto" and 0 < int(st["host_riceve_cents"])
              and self.connect.bonifici == []
              and self.sis.payout.stato_di(rif) == "maturato"
              and self.sis.pagamenti_pendenti.info(rif)["stato"] == "rimborsato",
              "PREMESSA: penale all'host, bonifico fermo, prenotazione rimborsata", s, c, st,
              self.connect.bonifici, self.sis.payout.stato_di(rif))
        return rif, int(st["host_riceve_cents"])

    def _dati_fiscali(self):
        s, c = self.g("POST", "/api/host/dati_fiscali",
                      {"codice_fiscale": "RSSMRA80A01H501U", "indirizzo_fiscale": "Via Roma 1",
                       "paese": "IT", "iban": "IT60X0542811101000000123456",
                       "tipo_soggetto": "individuo"}, {"X-Host-Token": self.tok})
        _deve(s == 200, s, c)

    def test_la_quota_penale_ferma_parte_quando_l_host_completa_i_dati(self):
        rif, quota = self._penale_ferma("casa-d2a", "pi_d2a")
        self._dati_fiscali()
        self.assertEqual([("acct_banco", quota, "EUR", rif, "ch_d2a")], self.connect.bonifici,
                         "LA QUOTA DELLA PENALE NON PARTE MAI: l'host ha completato i dati e "
                         "il bonifico fermo e' rimasto 'maturato' (%r)" % (self.connect.bonifici,))
        self.assertEqual("in_transito", self.sis.payout.stato_di(rif))

    def test_ripartita_dopo_e_ancora_una_PENALE_niente_ritenuta(self):
        _deve(self.sis.ritenuta.imposta(True, motivo="collaudo", chi="test"),
              "PREMESSA: la ritenuta non si accende")
        rif, quota = self._penale_ferma("casa-d2b", "pi_d2b", paese="IT", cin="IT058091C2ABCDEF12")
        self._dati_fiscali()
        self.assertEqual([quota], [x[1] for x in self.connect.bonifici],
                         "la penale ripartita dopo e' stata trattata come un canone: %r"
                         % (self.connect.bonifici,))
        self.assertEqual([], [m for m in self.sis.finanza.movimenti(rif)
                              if m.get("tipo") == "ritenuta"])

    def test_un_rimborso_PIENO_con_la_riga_rimasta_non_paga_l_host(self):
        # l'altra direzione (D19): la riga del bonifico non si e' tolta (archivio bloccato) su
        # una prenotazione rimborsata per intero; la garanzia dice 0 all'host
        b = self.pagata("casa-d2c", "pi_d2c", bloccata=False)
        rif = b["riferimento"]
        vera = self.sis.payout.rimuovi
        self.sis.payout.rimuovi = lambda *a, **k: False
        s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        self.sis.payout.rimuovi = vera
        _deve(s == 200 and self.sis.garanzia.stato(rif)["stato"] == "annullato"
              and self.sis.payout.stato_di(rif) == "maturato",
              "PREMESSA: rimborso pieno con la riga rimasta", s, c,
              self.sis.garanzia.stato(rif), self.sis.payout.stato_di(rif))
        self.r._trasferisci_all_host(rif, self.sis.payout.info(rif)["minori"])
        self.assertEqual([], self.connect.bonifici,
                         "PAGATO L'HOST DI UNA PRENOTAZIONE RIMBORSATA PER INTERO: %r"
                         % (self.connect.bonifici,))

    def test_su_una_prenotazione_rimborsata_conta_SOLO_la_garanzia_risolto(self):
        # D19 (mutante sopravvissuto del 12/10): una garanzia 'rilasciato' che porta la quota
        # piena su una prenotazione rimborsata e' il caso «rimborso all'ospite E bonifico
        # all'host»; il tetto della quota non lo ferma, deve fermarlo lo stato
        rif, quota = self._penale_ferma("casa-d2e", "pi_d2e")
        vera = self.sis.garanzia.stato
        self.sis.garanzia.stato = lambda r: dict(vera(r), stato="rilasciato",
                                                 host_riceve_cents=10 ** 9)
        self.r._trasferisci_all_host(rif, quota)
        self.assertEqual([], self.connect.bonifici,
                         "BONIFICO SU UNA PRENOTAZIONE RIMBORSATA con la garanzia 'rilasciato': %r"
                         % (self.connect.bonifici,))

    def test_una_prenotazione_NON_pagata_non_si_bonifica(self):
        # mutante sopravvissuto del 12/10: il bonifico parte solo da 'pagato' (o dalla penale)
        self.pubblica("casa-d2f")
        b = self.prenota("casa-d2f", 20)
        rif = b["riferimento"]
        _deve(self.sis.pagamenti_pendenti.info(rif)["stato"] == "in_attesa"
              and (self.sis.payout.info(rif) or {}).get("minori"),
              "PREMESSA: prenotazione non pagata con la riga del bonifico",
              self.sis.pagamenti_pendenti.info(rif), self.sis.payout.info(rif))
        self.r._trasferisci_all_host(rif, self.sis.payout.info(rif)["minori"])
        self.assertEqual([], self.connect.bonifici,
                         "BONIFICO SU UNA PRENOTAZIONE NON PAGATA: %r" % (self.connect.bonifici,))

    def test_mai_oltre_la_quota_che_la_garanzia_assegna(self):
        rif, quota = self._penale_ferma("casa-d2d", "pi_d2d")
        _deve(self.sis.payout.imposta_importo(rif, quota + 500), "PREMESSA: registro gonfiato")
        with self.ascolta() as righe:
            self.r._trasferisci_all_host(rif, quota + 500)
        self.assertEqual([], self.connect.bonifici,
                         "BONIFICO OLTRE LA PENALE: garanzia %d, partiti %r"
                         % (quota, self.connect.bonifici))
        self.assertTrue(self.errori_con(righe, "BONIFICO FERMATO", "oltre la quota"),
                        "%r" % (righe,))
        # r2-bis (23/10/2026): le due cifre in euro, non in centesimi
        chiesto = quota + 500
        self.assertTrue(self.errori_con(
            righe, "chiede %d.%02d EUR," % (chiesto // 100, chiesto % 100),
            "(%d.%02d EUR)" % (quota // 100, quota % 100)), "%r" % (righe,))


class TestLeRiparazioniDel16OttobreSottoGliOcchiDelGiudice(_BancoDeiSoldiDelServer):
    """(aq), S4 e (al), riparati il 16/10: le loro guardie stanno in `test_macchina_dei_soldi`,
    `test_admin_rimborso_money` e `test_escrow_gia_liquidato`, fuori dagli occhi che il Giudice
    accende per fase83 nel giro `--diff` (`scegli_sorveglianti`). Il job `caselle` della PR #263
    ha lasciato vivi 9 mutanti su quelle righe: qui una prova per ciascuno, nel file che il
    Giudice guarda per primo (metodo della casella 5).

    Riga per riga: il debito dell'admin solo se l'ospite ha pagato, e mai da zero euro -> le due
    `test_aq_...`; la domanda
    sulla contestazione solo con un pagamento da chiedere -> `test_S4_...`; il freno della
    cancellazione dell'host e la sua nota -> le tre `test_al_...`."""

    def _pagata(self, slug, pi, giorni=20):
        self.pubblica(slug, "moderata")
        b = self.prenota(slug, giorni)
        s, c = self.paga(b["riferimento"], pi)
        _deve(s == 200 and self.sis.pagamenti_pendenti.info(b["riferimento"])["stato"] == "pagato",
              "PREMESSA: la prenotazione doveva risultare pagata", s, c)
        return b

    def _rimborsi_nel_giornale(self, rif):
        return [m.get("importo_cents") for m in self.sis.finanza.movimenti(rif)
                if m.get("tipo") == "rimborso"]

    def _riga_dovuta(self, rif):
        s, lista = self.g("GET", "/api/admin/rimborsi_dovuti", None, {"X-Admin-Key": "ak"})
        _deve(s == 200, "PREMESSA: la lista dei rimborsi dovuti risponde", s, lista)
        return [r for r in (lista.get("rimborsi") or []) if r.get("riferimento") == rif]

    def _cancella_host(self, rif):
        return self.g("POST", "/api/host/cancella", {"riferimento": rif},
                      {"X-Host-Token": self.tok})

    def _fotografia(self, rif):
        return {"pagamento": self.sis.pagamenti_pendenti.info(rif)["stato"],
                "garanzia": self.sis.garanzia.stato(rif),
                "bonifico": self.sis.payout.info(rif),
                "rimborsi": self._rimborsi_nel_giornale(rif),
                "bonificati": list(self.connect.bonifici)}

    def test_aq_il_rimborso_dell_admin_su_una_prenotazione_NON_pagata_non_scrive_un_debito(self):
        self.pubblica("casa-aq")
        b = self.prenota("casa-aq", 20)
        rif = b["riferimento"]
        rec = self.sis.pagamenti_pendenti.info(rif)
        _deve(rec["stato"] == "in_attesa"
              and int(json.loads(rec.get("corpo_json") or "{}").get("totale_cents") or 0) > 0,
              "PREMESSA: prenotazione NON pagata, con un prezzo nel record", rec)
        idem = self.sis.firma.decodifica(b["voucher_token"]).get("idem_key", "")
        s, c = self.g("POST", "/api/admin/rimborso",
                      {"alloggio_id": "casa-aq", "check_in": _fra(20), "check_out": _fra(22),
                       "idem_key": idem}, {"X-Admin-Key": "ak"})
        _deve(s == 200, "PREMESSA: il rimborso dell'admin risponde", s, c)
        self.assertEqual(([], []), (self._rimborsi_nel_giornale(rif), self._riga_dovuta(rif)),
                         "(aq) DEBITO FINTO: l'ospite non ha pagato niente e il giornale dice che "
                         "gli dobbiamo dei soldi (risposta: %r)" % (c,))

    def test_aq_un_totale_a_zero_non_chiede_una_riga_di_rimborso(self):
        """Gemella di `test_blocco_carta.test_un_totale_a_zero_non_chiede_una_riga_di_rimborso`,
        qui sotto gli occhi di fase83. Il chiamante non chiede una riga da zero euro: che
        `_giornale` la scarti da se' e' la seconda difesa, non la prima (D19). Il 16/10 `tot > 0`
        era stato tolto come «ridondante» e quella guardia e' caduta."""
        import sqlite3
        b = self._pagata("casa-aq0", "pi_aq0")
        rif = b["riferimento"]
        rec = self.sis.pagamenti_pendenti.info(rif)
        corpo = dict(json.loads(rec.get("corpo_json") or "{}"), totale_cents=0,
                     prezzo_guest_cents=0)
        con = sqlite3.connect(self.dir + "/p.db")
        with con:
            con.execute("UPDATE pendenti SET corpo_json=? WHERE riferimento=?",
                        (json.dumps(corpo), rif))
        con.close()
        chieste, vero = [], self.r._giornale
        self.r._giornale = lambda *a, **k: (chieste.append(k), vero(*a, **k))[1]
        idem = self.sis.firma.decodifica(b["voucher_token"]).get("idem_key", "")
        s, c = self.g("POST", "/api/admin/rimborso",
                      {"alloggio_id": "casa-aq0", "check_in": _fra(20), "check_out": _fra(22),
                       "idem_key": idem}, {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, "%r" % (c,))
        self.assertEqual([k for k in chieste if k.get("tipo") == "rimborso"], [],
                         "chiesta una riga di rimborso da zero euro")
        self.assertIn("non determinabile", c.get("rimborso_stripe", ""))

    def test_S4_senza_un_pagamento_da_chiedere_la_riga_non_inventa_la_contestazione(self):
        """Il pagamento e' arrivato senza `payment_intent` (fuori da Stripe, o un webhook senza
        `pi_`): la riga dice che manca quello, e basta. Chiedere a Stripe «c'e' una contestazione?»
        senza un pagamento da nominare da' «non lo so» (`payment_intent_assente`), e un
        «verifica_contestazione» in piu' sarebbe un falso allarme (regola ferrea 10)."""
        b = self._pagata("casa-s4", "")
        rif = b["riferimento"]
        s, c = self._cancella_host(rif)
        _deve(s == 200, "PREMESSA: l'host cancella e l'ospite e' da rimborsare", s, c)
        righe = self._riga_dovuta(rif)
        _deve(len(righe) == 1, "PREMESSA: la riga del rimborso dovuto c'e'", righe)
        self.assertEqual((["payment_intent"], False), (righe[0].get("manca"), righe[0].get("bottone")),
                         "la riga senza pagamento da chiedere dice cose diverse da «manca il "
                         "payment_intent»: %r" % (righe[0],))

    def test_al_dopo_la_decisione_dell_arbitro_con_zero_all_host_l_host_NON_cancella(self):
        b = self._pagata("casa-al1", "pi_al1")
        rif = b["riferimento"]
        _deve(self.sis.garanzia.contesta(rif, "non corrisponde").get("ok"),
              "PREMESSA: la garanzia doveva poter diventare contestata")
        tutto = int(self.sis.garanzia.stato(rif)["importo_host_cents"])
        _deve(self.sis.garanzia.risolvi(rif, rimborso_ospite_cents=tutto).get("ok"),
              "PREMESSA: l'arbitro decide")
        st = self.sis.garanzia.stato(rif)
        _deve((st["stato"], int(st["host_riceve_cents"])) == ("risolto", 0),
              "PREMESSA: arbitro al 100% per l'ospite, zero all'host", st)
        prima = self._fotografia(rif)
        s, c = self._cancella_host(rif)
        self.assertEqual((409, "escrow_gia_liquidato"), (s, (c or {}).get("errore")),
                         "(al) L'HOST HA CANCELLATO DOPO LA DECISIONE DELL'ARBITRO: %s %r" % (s, c))
        self.assertIn("arbitro", str((c or {}).get("nota")), c)
        self.assertEqual(prima, self._fotografia(rif), "la cancellazione rifiutata ha mosso soldi")

    def test_al_col_soggiorno_confermato_l_host_NON_cancella(self):
        b = self._pagata("casa-al2", "pi_al2")
        rif = b["riferimento"]
        _deve(self.sis.garanzia.conferma_ospite(rif).get("ok"),
              "PREMESSA: l'ospite conferma «tutto ok»")
        st = self.sis.garanzia.stato(rif)
        _deve(st["stato"] == "rilasciato" and int(st["host_riceve_cents"]) > 0,
              "PREMESSA: garanzia sbloccata all'host", st)
        prima = self._fotografia(rif)
        s, c = self._cancella_host(rif)
        self.assertEqual((409, "escrow_gia_liquidato", int(st["host_riceve_cents"])),
                         (s, (c or {}).get("errore"), (c or {}).get("gia_liquidato_cents")),
                         "L'HOST HA CANCELLATO UN SOGGIORNO GIA' SBLOCCATO: %s %r" % (s, c))
        self.assertIn("soggiorno", str((c or {}).get("nota")), c)
        self.assertEqual(prima, self._fotografia(rif), "la cancellazione rifiutata ha mosso soldi")

    def test_al_con_la_garanzia_ancora_aperta_l_host_cancella(self):
        # l'altra direzione (regola ferrea 10): il freno non scatta prima del tempo
        b = self._pagata("casa-al3", "pi_al3")
        rif = b["riferimento"]
        _deve(self.sis.garanzia.stato(rif)["stato"] == "in_garanzia",
              "PREMESSA: garanzia aperta", self.sis.garanzia.stato(rif))
        s, c = self._cancella_host(rif)
        self.assertEqual((200, "cancellata_host"), (s, (c or {}).get("stato")),
                         "il freno ha fermato una cancellazione legittima: %s %r" % (s, c))


class TestR2bisIRegistriDeiRimborsiScrivonoInValuta(_BancoDeiSoldiDelServer):
    """r2-bis (23/10/2026, «autorizzato»), stessa malattia di r1 e r2: le righe dei rimborsi
    stampavano le UNITA' MINORI accanto alla valuta («importo=20000 EUR»): chi legge il registro
    crede 20000 euro. Trovate da GML (compito 19, punto d); l'oracolo qui sotto e' scritto a
    parte, senza chiamare il formattatore del server."""

    _pagata = TestLeRiparazioniDel16OttobreSottoGliOcchiDelGiudice._pagata

    @staticmethod
    def _eur(c):
        return "%d.%02d EUR" % (c // 100, c % 100)

    def _rimborso_admin(self, slug, pi, esito):
        b = self._pagata(slug, pi)
        chiesti = []
        idem = self.sis.firma.decodifica(b["voucher_token"]).get("idem_key", "")
        with mock.patch.object(self.sis.stripe, "rimborsa",
                               lambda p, imp, chiave=None: (chiesti.append(imp), esito)[1]), \
                self.ascolta() as righe:
            s, c = self.g("POST", "/api/admin/rimborso",
                          {"alloggio_id": slug, "check_in": _fra(20), "check_out": _fra(22),
                           "idem_key": idem}, {"X-Admin-Key": "ak"})
        _deve(len(chiesti) == 1, "PREMESSA: il rimborso doveva arrivare a Stripe", s, c, chiesti)
        return righe, chiesti[0]

    def test_il_rimborso_ESEGUITO_scrive_euro(self):
        righe, imp = self._rimborso_admin("casa-r2b1", "pi_r2b1", {"ok": True, "id": "re_r2b"})
        trovate = [r for r in righe if "RIMBORSO ESEGUITO" in r]
        self.assertEqual(len(trovate), 1, "%r" % (righe,))
        self.assertIn("importo=%s stripe=" % self._eur(imp), trovate[0])

    def test_il_rimborso_FALLITO_scrive_euro(self):
        righe, imp = self._rimborso_admin("casa-r2b2", "pi_r2b2",
                                          {"ok": False, "id": "", "motivo": "carta_chiusa"})
        trovate = self.errori_con(righe, "RIMBORSO FALLITO")
        self.assertEqual(len(trovate), 1, "%r" % (righe,))
        self.assertIn("importo=%s ->" % self._eur(imp), trovate[0])

    def test_la_cancellazione_dell_host_scrive_euro(self):
        b = self._pagata("casa-r2b3", "pi_r2b3")
        with self.ascolta() as righe:
            s, c = self.g("POST", "/api/host/cancella", {"riferimento": b["riferimento"]},
                          {"X-Host-Token": self.tok})
        _deve(s == 200 and c.get("rimborso_cliente_cents", 0) > 0,
              "PREMESSA: cancellazione dell'host con rimborso all'ospite", s, c)
        trovate = [r for r in righe if "HOST ha cancellato" in r]
        self.assertEqual(len(trovate), 1, "%r" % (righe,))
        # la penale dipende dalla politica (qui moderata): basta che sia scritta in euro
        self.assertRegex(trovate[0], r"cliente rimborso %s, penale host \d+\.\d\d EUR \|"
                         % re.escape(self._eur(c["rimborso_cliente_cents"])))

    def test_il_formattatore_conosce_yen_dinari_e_il_segno(self):
        """GML compito 19 (e): «sempre /100» in `_fmt_importo` passava tutte le prove (lo yen
        sulla riga del bonifico a mano diventava 870.00 JPY); compito 22 (e): coi negativi la
        divisione intera dava -11.50 per -1050."""
        f = self.r._fmt_importo
        self.assertEqual(f(8700, "JPY"), "8700 JPY")
        self.assertEqual(f(8700, "KWD"), "8.700 KWD")
        self.assertEqual(f(5, "KWD"), "0.005 KWD")
        self.assertEqual(f(8700, "EUR"), "87.00 EUR")
        self.assertEqual(f(-1050, "EUR"), "-10.50 EUR")
        self.assertEqual(f(-5, "EUR"), "-0.05 EUR")
        # il confine: zero non ha segno (mutante `< 0` -> `<= 0` del giro --diff della PR #274)
        self.assertEqual(f(0, "EUR"), "0.00 EUR")


class TestLaDataDelCheckInSiLeggeUgualeSuOgniPython(unittest.TestCase):
    """DATE-311 (19/10): dal Python 3.11 `date.fromisoformat` accetta anche '20260905' e
    '2026-W36-6'. Le due funzioni del check-in accettano solo AAAA-MM-GG, su ogni versione.
    Gemella di `test_fusi_orari.test_non_si_rompe_su_una_data_assurda`, qui perche' il
    Giudice `--diff` guarda questo file: li' il mutante su `_istante_fine_tutela` passava."""

    def test_una_data_giusta_da_l_istante_e_la_fine_tutela(self):
        inizio = fase83_server._istante_checkin_prudente("2026-09-05")
        self.assertIsNotNone(inizio)
        self.assertEqual(fase83_server._istante_fine_tutela("2026-09-05", 24),
                         inizio + 24 * 3600)

    def test_le_forme_compatte_e_a_settimane_sono_rifiutate(self):
        for cattiva in ("20260905", "2026-W36-6", "2026W366", "2026-13-45", ""):
            with self.subTest(data=cattiva):
                self.assertIsNone(fase83_server._istante_checkin_prudente(cattiva))
                self.assertIsNone(fase83_server._istante_fine_tutela(cattiva, 24))


class TestIlPagamentoAMano(_BancoDeiBonifici):
    """⛔ R1 e R3 (revisione Trail of Bits della #268, 20/10; «autorizzato» del fondatore il
    21/10). LE GUARDIE STANNO QUI, NEL TEST DEDICATO DEL SERVER, come
    `TestIlPulsanteDellaControversia`: il giro `--diff master` del 21/10 (16:41-18:02) ha
    lasciato 33 mutanti vivi su 37 non perche' le righe fossero scoperte, ma perche' le guardie
    stavano in `test_movimenti_giornale`, fuori dagli 8 occhi che il Giudice accende. Il banco e'
    quello dei bonifici (importato): un solo banco, non due copie.
    R1: dopo un rifiuto di Stripe (o con l'host senza Stripe) il prodotto chiedeva il bonifico
    A MANO ma lasciava il payout 'maturato', e nessuna azione registrava il pagamento fatto a
    mano: il primo sblocco (verifica dell'host, dati fiscali) lo ripagava con Stripe. Modern
    Treasury, «Edge cases in complex payment operations»: un pagamento rimandato dopo un
    fallimento e' riuscito due volte -> «block redrafts after success».
    R3: Stripe non ritenta da solo un bonifico fallito, «You must explicitly attempt the
    transfer again» (docs.stripe.com/connect/account-balances, letta il 21/10/2026)."""

    def _rifiuto_di_stripe(self):
        corpo = json.dumps({"error": {"type": "invalid_request_error",
                                      "code": "balance_insufficient",
                                      "message": "Insufficient funds"}}).encode("utf-8")
        return urllib.error.HTTPError("https://api.stripe.com/v1/transfers", 400,
                                      "Bad Request", {}, io.BytesIO(corpo))

    def _soggiorno_confermato(self, rif):
        """«Tutto ok» dell'ospite: la garanzia e' dell'host (il bonifico lo si chiama a parte)."""
        self.assertTrue(self.sis.garanzia.conferma_ospite(rif).get("ok"))

    def _lo_pago_io_a_mano(self, rif):
        return self.g("POST", "/api/admin/payout/pagato_a_mano", {"riferimento": rif},
                      {"X-Admin-Key": "ak"})

    def _sblocco_della_verifica(self):
        codice, risposta = self.g("POST", "/api/admin/verifica_stato",
                                  {"host_id": self.hid, "stato": "verificato"},
                                  {"X-Admin-Key": "ak"})
        self.assertEqual(codice, 200, risposta)

    def test_R1_un_bonifico_preso_in_carico_A_MANO_non_lo_ripaga_Stripe(self):
        """Il fondatore paga a mano il bonifico che il prodotto gli ha chiesto. Prima lo dice al
        prodotto («Lo pago io a mano»), poi un giro automatico ritenta i payout 'maturato': quel
        payout non deve ripartire con Stripe. Due strade portano al «a mano»: Stripe rifiuta il
        bonifico, o l'host non ha collegato Stripe (e lo collega dopo)."""
        for caso in ("Stripe rifiuta", "host senza Stripe"):
            with self.subTest(caso):
                stripe = _StripeDeiBonifici(self._rifiuto_di_stripe(), ricorda_chiavi=False,
                                            eseguito_prima=False)
                rif, netto = self._bonifico_con(stripe)
                if caso == "host senza Stripe":
                    self.sis.registro_host.imposta_stripe_account(self.hid, "")
                    stripe.guasto = None                  # quando lo collega, Stripe accetta
                self._soggiorno_confermato(rif)
                self.r._trasferisci_all_host(rif, netto)  # il bonifico non parte
                self.assertEqual(stripe.bonifici, [], "premessa: nessun bonifico e' partito")
                self.assertEqual(self.sis.payout.stato_di(rif), "maturato")
                codice, risposta = self._lo_pago_io_a_mano(rif)
                self.sis.registro_host.imposta_stripe_account(self.hid, "acct_TEST")
                self._sblocco_della_verifica()            # il giro che ritenta i 'maturato'
                self.assertEqual(stripe.bonifici, [],
                                 "%s: l'host e' stato pagato DUE volte, a mano dal fondatore e poi "
                                 "da Stripe allo sblocco della verifica (risposta al «lo pago io a "
                                 "mano»: %r %r)" % (caso, codice, risposta))
                self.assertEqual(codice, 200, risposta)
                self.assertEqual(risposta.get("stato"), "preso_in_carico")
                self.assertEqual(risposta.get("importo_cents"), netto)
                # 'in_transito', come un bonifico Connect partito: il bonifico dalla banca e'
                # in viaggio, e ogni guardia anti-doppio che c'e' gia' lo riconosce
                self.assertEqual(self.sis.payout.stato_di(rif), "in_transito")
                self.assertEqual(self._tipi(rif).count("payout_host"), 1,
                                 "il pagamento a mano non e' nel giornale, o c'e' due volte")
                self.assertTrue(self.sis.finanza.verifica_catena()["ok"])
                self.assertEqual(stripe.inattesi, [])

    def test_R1_il_lo_pago_io_a_mano_rilegge_Stripe_e_si_ferma_se_non_e_sicuro(self):
        """Il pulsante non si fida del registro: chiede a Stripe se il bonifico c'e' gia'. Se c'e'
        (un esito sconosciuto che era partito davvero) o se Stripe non risponde, NON prende in
        carico niente: pagare a mano li' e' esattamente il doppio pagamento. E non paga una
        garanzia ancora aperta: quei soldi non sono ancora dell'host."""
        # il bonifico parte, la risposta no, e nemmeno la rilettura subito dopo: esito sconosciuto
        stripe = _StripeDeiBonifici(TimeoutError("The read operation timed out"),
                                    ricorda_chiavi=True, letture_rotte=(2,))
        rif, netto = self._bonifico_con(stripe)
        self._soggiorno_confermato(rif)
        self.r._trasferisci_all_host(rif, netto)
        self.assertEqual(len(stripe.bonifici), 1, "premessa: il bonifico e' su Stripe")
        self.assertEqual(self.sis.payout.stato_di(rif), "maturato", "premessa")
        codice, risposta = self._lo_pago_io_a_mano(rif)
        self.assertEqual(codice, 409, risposta)
        self.assertEqual(risposta.get("errore"), "gia_su_stripe")
        self.assertEqual(self.sis.payout.stato_di(rif), "maturato")
        self.assertNotIn("payout_host", self._tipi(rif))

        stripe2 = _StripeDeiBonifici(None, ricorda_chiavi=True, letture_rotte=(1,))
        rif2, _ = self._bonifico_con(stripe2)
        self._soggiorno_confermato(rif2)
        codice, risposta = self._lo_pago_io_a_mano(rif2)
        self.assertEqual(codice, 409, risposta)
        self.assertEqual(risposta.get("errore"), "stripe_non_risponde")
        self.assertEqual(self.sis.payout.stato_di(rif2), "maturato")

        stripe3 = _StripeDeiBonifici(None, ricorda_chiavi=True)
        rif3, _ = self._bonifico_con(stripe3)                # garanzia ancora aperta
        codice, risposta = self._lo_pago_io_a_mano(rif3)
        self.assertEqual(codice, 409, risposta)
        self.assertEqual(risposta.get("errore"), "garanzia_aperta")
        self.assertEqual(self.sis.payout.stato_di(rif3), "maturato")
        self.assertEqual(stripe2.bonifici + stripe3.bonifici, [])
        with mock.patch.object(self.r, "_puo_azione", return_value=False):
            codice, _ = self._lo_pago_io_a_mano(rif3)
        self.assertEqual(codice, 403, "il ruolo 'supporto' non muove soldi")

    def test_R1_con_Stripe_collegato_a_mano_solo_dopo_un_RIFIUTO_certo(self):
        """Revisione differenziale del 21/10 (RV1): un esito sconosciuto non scrive righe nel
        giornale e lascia il payout 'maturato'. Se il bonifico e' partito ma la lista di Stripe
        non lo mostra ancora, la rilettura del pulsante non lo vede: pagato a mano, l'host e'
        pagato due volte. Il bonifico a mano non ha la chiave anti-doppio di Stripe, il
        ritentativo automatico si' (docs.stripe.com/api/idempotent_requests, letta il 21/10):
        con un conto Stripe si prende in carico a mano solo dopo un rifiuto CERTO (la riga
        `payout_manuale`), e un esito sconosciuto lo chiude il giro orario."""
        stripe = _StripeDeiBonifici(TimeoutError("The read operation timed out"),
                                    ricorda_chiavi=True, eseguito_prima=False)
        rif, netto = self._bonifico_con(stripe)
        self._soggiorno_confermato(rif)
        self.r._trasferisci_all_host(rif, netto)          # nessuna risposta: esito sconosciuto
        self.assertEqual(stripe.bonifici, [], "premessa: su Stripe non c'e' (ancora) niente")
        self.assertEqual(self.sis.payout.stato_di(rif), "maturato", "premessa")
        self.assertNotIn("payout_manuale", self._tipi(rif), "premessa: nessun rifiuto certo")
        codice, risposta = self._lo_pago_io_a_mano(rif)
        self.assertEqual(codice, 409, "preso in carico a mano dopo un esito SCONOSCIUTO: se il "
                                      "bonifico era partito l'host e' pagato due volte (%r)"
                                      % (risposta,))
        self.assertEqual(risposta.get("errore"), "nessun_rifiuto_certo")
        self.assertEqual(self.sis.payout.stato_di(rif), "maturato")
        self.assertNotIn("payout_host", self._tipi(rif))
        self.r._ritenta_bonifici_fermi()                  # lo chiude il giro orario
        self.assertEqual(len(stripe.bonifici), 1)
        self.assertEqual(self.sis.payout.stato_di(rif), "in_transito")
        self.assertEqual(stripe.inattesi, [])

    def test_R1_il_pulsante_aspetta_il_bonifico_automatico_in_viaggio(self):
        """La gara: un giro automatico ha spedito il bonifico a Stripe e aspetta la risposta, e
        proprio allora si preme «Lo pago io a mano». Senza `_BONIFICI_LOCK` la rilettura di Stripe
        non vede ancora niente, il pulsante prende in carico, poi Stripe esegue: l'host e' pagato
        due volte. Col lucchetto il pulsante aspetta, e trova il bonifico gia' partito."""
        from fase101_stripe_connect import ProviderConnect
        stripe = _StripeDeiBonifici(None, ricorda_chiavi=True)
        rif, netto = self._bonifico_con(stripe)
        self._soggiorno_confermato(rif)
        in_viaggio, arriva = threading.Event(), threading.Event()

        def post_lento(url, body, headers):
            if body is not None:                      # il POST del bonifico, non le letture
                in_viaggio.set()
                arriva.wait(10)
            return stripe.post(url, body, headers)
        self.sis.connect = ProviderConnect("sk_test_x", fetch=post_lento, fetch_get=stripe.get)
        automatico = threading.Thread(target=self.r._trasferisci_all_host, args=(rif, netto))
        automatico.start()
        self.assertTrue(in_viaggio.wait(10), "premessa: il bonifico automatico e' in viaggio")
        esito = {}
        pulsante = threading.Thread(target=lambda: esito.update(r=self._lo_pago_io_a_mano(rif)))
        pulsante.start()
        pulsante.join(0.5)                            # senza lucchetto qui ha gia' risposto
        arriva.set()
        automatico.join(10)
        pulsante.join(10)
        self.assertFalse(automatico.is_alive() or pulsante.is_alive(), "un filo e' rimasto appeso")
        self.assertEqual(len(stripe.bonifici), 1, "premessa: Stripe ha eseguito il bonifico")
        codice, risposta = esito["r"]
        self.assertEqual(codice, 409, "il pulsante ha preso in carico un bonifico che Stripe stava "
                                      "gia' eseguendo: l'host viene pagato due volte (%r)"
                                      % (risposta,))
        self.assertEqual(risposta.get("errore"), "non_da_pagare")
        self.assertEqual(self.sis.payout.stato_di(rif), "in_transito")
        self.assertEqual(self._tipi(rif).count("payout_host"), 1)
        self.assertEqual(stripe.inattesi, [])

    def test_R3_un_bonifico_rifiutato_lo_ritenta_il_giro_orario(self):
        """Stripe rifiuta (saldo insufficiente), anche al primo giro orario; poi il saldo torna.
        Nessuno sblocco arriva: deve ripartire da solo al giro orario, una volta sola.
        `ricorda_chiavi=False`: Stripe ripete per 24 ore il rifiuto salvato sulla chiave, e qui
        si guarda il giro dopo. Le due direzioni: con la garanzia ancora aperta, o senza
        garanzia, il giro orario non paga niente."""
        stripe = _StripeDeiBonifici(self._rifiuto_di_stripe(), ricorda_chiavi=False,
                                    eseguito_prima=False)
        rif, netto = self._bonifico_con(stripe)
        self._soggiorno_confermato(rif)
        self.r._trasferisci_all_host(rif, netto)
        self.assertEqual(stripe.bonifici, [], "premessa: rifiutato")
        ritenta = getattr(self.r, "_ritenta_bonifici_fermi", None)
        self.assertIsNotNone(ritenta, "nessun giro orario ritenta i bonifici rifiutati: Stripe "
                                      "non lo fa da solo, e il payout resta 'maturato' finche' "
                                      "non capita uno sblocco")
        stripe._post_ricevuti, stripe.guasto = 0, self._rifiuto_di_stripe()
        ritenta()                                         # il saldo non e' ancora tornato
        self.assertEqual(stripe.bonifici, [], "premessa: rifiutato anche al giro orario")
        ritenta()                                         # il saldo e' tornato
        ritenta()
        self.assertEqual(len(stripe.bonifici), 1, "il giro orario non ha pagato, o due volte")
        self.assertEqual(self.sis.payout.stato_di(rif), "in_transito")
        self.assertEqual(self._tipi(rif).count("payout_host"), 1)
        self.assertEqual(self._tipi(rif).count("payout_manuale"), 1,
                         "il giornale scrive un promemoria a ogni tentativo rifiutato")

        stripe2 = _StripeDeiBonifici(None, ricorda_chiavi=True)
        rif2, _ = self._bonifico_con(stripe2)                # garanzia aperta
        ritenta()
        with mock.patch.object(self.sis.garanzia, "stato", return_value=None):
            ritenta()                                         # garanzia che non si trova
        self.assertEqual(stripe2.bonifici, [], "il giro orario paga soldi non ancora dell'host")
        self.assertEqual(self.sis.payout.stato_di(rif2), "maturato")
        self.assertEqual(stripe.inattesi + stripe2.inattesi, [])

    # ── i sopravvissuti del giro del 21/10 che nessuna guardia guardava, uno per uno ─────────
    def test_R1_un_riferimento_storto_non_entra(self):
        """Il riferimento finisce nel registro che legge il Guardiano: si controlla la FORMA, come
        `_admin_rimborsa_dovuto` (sopravviveva `and` -> `or`: una stringa qualunque passava)."""
        for storto in ("../payout", "a b", "", 123):
            with self.subTest(storto=storto):
                codice, risposta = self._lo_pago_io_a_mano(storto)
                self.assertEqual((codice, risposta.get("errore")), (422, "campi_non_validi"))

    def test_R1_una_garanzia_illeggibile_ferma_il_pulsante_e_lo_scrive_intero(self):
        """Non si sa se il soggiorno e' confermato: niente pagamento a mano (503), e la riga
        ERROR porta l'eccezione intera (sopravviveva `exc_info=True` -> `False`)."""
        stripe = _StripeDeiBonifici(None, ricorda_chiavi=True)
        rif, _ = self._bonifico_con(stripe)
        with mock.patch.object(self.sis.garanzia, "stato",
                               side_effect=RuntimeError("archivio della garanzia illeggibile")), \
                self.assertLogs("core_auto", level="ERROR") as cattura:
            codice, risposta = self._lo_pago_io_a_mano(rif)
        self.assertEqual((codice, risposta.get("errore")), (503, "garanzia_illeggibile"))
        self.assertEqual(self.sis.payout.stato_di(rif), "maturato")
        righe = [r for r in cattura.records if "BONIFICO A MANO NON PRESO IN CARICO" in r.getMessage()]
        self.assertEqual(len(righe), 1, cattura.output)
        # il TIPO, non «non e' nullo»: `exc_info=False` scrive False, che non e' None
        self.assertIsInstance(righe[0].exc_info, tuple, "la riga ERROR non porta l'eccezione: il "
                                                        "perche' della garanzia illeggibile si perde")

    def test_R1_l_host_senza_Stripe_lo_dice_col_suo_importo(self):
        """Il registro dice QUANTO va pagato a mano e COME (prima il pulsante): sopravviveva
        `(pd.info(rif) or {})` -> `and`, cioe' «IMPORTO: None» nella riga PAYOUT_HOLD."""
        stripe = _StripeDeiBonifici(None, ricorda_chiavi=True)
        rif, netto = self._bonifico_con(stripe)
        self.sis.registro_host.imposta_stripe_account(self.hid, "")
        with self.assertLogs("core_auto", level="WARNING") as cattura:
            self.r._trasferisci_all_host(rif, netto)
        righe = [r.getMessage() for r in cattura.records
                 if "PAYOUT_HOLD_TRIGGERED" in r.getMessage()]
        self.assertEqual(len(righe), 1, cattura.output)
        # r2-bis (23/10/2026): in euro, non in centesimi («IMPORTO: 8700» si leggeva 8700 euro)
        self.assertIn("IMPORTO: %d.%02d EUR |" % (netto // 100, netto % 100), righe[0])
        self.assertIn("«Lo pago io a mano»", righe[0])
        self.assertEqual(stripe.bonifici, [])
        self.assertEqual(self.sis.payout.stato_di(rif), "maturato")

    def _hold_scritto(self, motivo):
        stripe = _StripeDeiBonifici(None, ricorda_chiavi=True)
        rif, netto = self._bonifico_con(stripe)
        with self.assertLogs("core_auto", level="WARNING") as cattura:
            self.r._trasferisci_all_host(rif, netto)
        righe = [r.getMessage() for r in cattura.records
                 if "PAYOUT_HOLD_TRIGGERED" in r.getMessage() and motivo in r.getMessage()]
        self.assertEqual(len(righe), 1, cattura.output)
        self.assertEqual(stripe.bonifici, [], "premessa: il bonifico doveva restare fermo")
        return righe[0], netto

    def test_r2bis_la_verifica_revocata_scrive_l_importo_in_euro(self):
        """r2-bis: «PAYOUT_HOLD_TRIGGERED ... IMPORTO: 8700 | MOTIVO: VERIFICA_REVOCATA» si
        leggeva 8700 euro fermi. E' la riga che dice a una persona quanti soldi aspettano."""
        self.r._verifica_payout_bloccato = lambda hid: True
        riga, netto = self._hold_scritto("VERIFICA_REVOCATA")
        self.assertIn("IMPORTO: %d.%02d EUR |" % (netto // 100, netto % 100), riga)

    def test_r2bis_i_dati_fiscali_mancanti_scrivono_l_importo_in_euro(self):
        self.r._dac7_payout_bloccato = lambda hid: (True, ["iban"])
        riga, netto = self._hold_scritto("MANCANZA_DATI_FISCALI")
        self.assertIn("IMPORTO: %d.%02d EUR |" % (netto // 100, netto % 100), riga)

    def test_R3_un_bonifico_che_esplode_non_ferma_gli_altri(self):
        """Il giro orario passa i bonifici uno per uno: un errore su uno lo scrive per intero
        (sopravviveva `exc_info=True` -> `False`) e gli altri partono lo stesso."""
        stripe = _StripeDeiBonifici(None, ricorda_chiavi=True)
        rif, _ = self._bonifico_con(stripe)
        rif2, _ = self._bonifico_con(stripe)
        self._soggiorno_confermato(rif)
        self._soggiorno_confermato(rif2)
        vera, visti = self.r._garanzia_chiusa, []

        def la_prima_esplode(r):
            visti.append(r)
            if len(visti) == 1:
                raise RuntimeError("archivio della garanzia illeggibile")
            return vera(r)
        with mock.patch.object(self.r, "_garanzia_chiusa", side_effect=la_prima_esplode), \
                self.assertLogs("core_auto", level="WARNING") as cattura:
            self.r._ritenta_bonifici_fermi()
        self.assertEqual(sorted(visti), sorted([rif, rif2]), "il giro non ha visto i due bonifici")
        primo, altro = visti[0], visti[1]
        self.assertEqual(self.sis.payout.stato_di(altro), "in_transito",
                         "un bonifico che esplode ha fermato gli altri")
        self.assertEqual(self.sis.payout.stato_di(primo), "maturato")
        righe = [r for r in cattura.records if "BONIFICO FERMO NON RITENTATO" in r.getMessage()]
        self.assertEqual(len(righe), 1, cattura.output)
        self.assertIsInstance(righe[0].exc_info, tuple, "la riga non porta l'eccezione")
        self.assertEqual(len(stripe.bonifici), 1)


class TestIlGiroDeiBonificiFermiLasciaLaTraccia(unittest.TestCase):
    """R3 (21/10): il giro dei bonifici fermi e' il PRIMO passo di `_tick_garanzia`, una
    chiusura dentro `servi()`: si legge l'albero sintattico, come
    `test_blocco_carta.TestIlGiroOrarioLasciaLaTraccia`. Se esplode, il thread resta vivo e la
    riga ERROR porta l'eccezione intera (sopravviveva `exc_info=True` -> `False`)."""

    def test_il_giro_dei_bonifici_fermi_fallito_scrive_l_eccezione(self):
        import ast
        with open(fase83_server.__file__, encoding="utf-8") as f:
            albero = ast.parse(f.read())
        tick = [n for n in ast.walk(albero)
                if isinstance(n, ast.FunctionDef) and n.name == "_tick_garanzia"]
        self.assertEqual(len(tick), 1, "il tick della garanzia non si trova piu'")
        prove = [t for t in ast.walk(tick[0]) if isinstance(t, ast.Try)
                 and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                         and c.func.attr == "_ritenta_bonifici_fermi"
                         for s in t.body for c in ast.walk(s))]
        self.assertEqual(len(prove), 1, "il giro dei bonifici fermi non e' dentro il suo try")
        chiamate = [c for h in prove[0].handlers for c in ast.walk(h)
                    if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                    and c.func.attr == "error"]
        self.assertEqual(len(chiamate), 1)
        exc = [k.value for k in chiamate[0].keywords if k.arg == "exc_info"]
        self.assertTrue(len(exc) == 1 and isinstance(exc[0], ast.Constant) and exc[0].value is True,
                        "la riga ERROR del giro dei bonifici fermi non porta l'eccezione")


class TestIlGiroOrarioOperaLaRitenuta(_BancoDellaRitenuta):
    """R3 (21/10): il giro orario chiama `_trasferisci_all_host` senza `penale`, quindi a
    interruttore acceso la ritenuta si opera come al primo tentativo. Sopravviveva il default
    `penale=False` -> `True` sulla firma: l'host avrebbe incassato anche la parte dovuta allo
    Stato. Il banco e' quello della ritenuta (importato): casa in Italia, col CIN."""

    def test_R3_il_giro_orario_opera_la_ritenuta(self):
        self._accendi()
        rif, _q = self._prenota_paga()
        pieno = self._maturato(rif)
        self.assertTrue(self.sis.garanzia.conferma_ospite(rif).get("ok"))
        self.assertEqual(self._righe(rif, "ritenuta"), [], "premessa")
        self.assertEqual(self.r._ritenta_bonifici_fermi(), 1)
        ritenute = self._righe(rif, "ritenuta")
        self.assertEqual(len(ritenute), 1, "il giro orario ha pagato l'host senza la ritenuta")
        self.assertEqual(self.connect.chiamate,
                         [("acct_TEST", pieno - ritenute[0]["importo_cents"], "EUR", rif)])


class TestIlPagamentoAManoInDollari(_BancoDellaRitenuta):
    """R1 (21/10): la risposta del pulsante porta la valuta del bonifico, che la pagina mostra
    accanto all'importo. Sopravviveva `riga.get("valuta") or "EUR"` -> `and`: con un annuncio in
    euro le due scritture danno lo stesso, in dollari no."""
    VALUTA = "USD"

    def test_R1_la_risposta_dice_la_valuta_del_bonifico(self):
        rif, _q = self._prenota_paga()
        self.assertTrue(self.sis.garanzia.conferma_ospite(rif).get("ok"))
        self.sis.registro_host.imposta_stripe_account(self.hid, "")      # niente Stripe: a mano
        s, out = self.g("POST", "/api/admin/payout/pagato_a_mano", {"riferimento": rif},
                        self._bunker())
        self.assertEqual(s, 200, out)
        self.assertEqual((out.get("valuta"), out.get("importo_cents")),
                         ("USD", self._maturato(rif)))
        self.assertEqual(self.connect.chiamate, [], "un bonifico a mano e' partito con Stripe")

    def test_r2_la_riga_del_bonifico_a_mano_scrive_dollari_e_non_centesimi(self):
        # r2 (23/10/2026): «IMPORTO: %d %s» stampava i centesimi accanto alla valuta.
        rif, _q = self._prenota_paga()
        self.assertTrue(self.sis.garanzia.conferma_ospite(rif).get("ok"))
        self.sis.registro_host.imposta_stripe_account(self.hid, "")
        minori = self._maturato(rif)
        with self.assertLogs("core_auto.server", level="WARNING") as reg:
            s, out = self.g("POST", "/api/admin/payout/pagato_a_mano", {"riferimento": rif},
                            self._bunker())
        self.assertEqual(s, 200, out)
        riga = [r for r in reg.output if "BONIFICO A MANO PRESO IN CARICO" in r]
        self.assertEqual(len(riga), 1, reg.output)
        self.assertIn("IMPORTO: %d.%02d USD |" % (minori // 100, minori % 100), riga[0])


if __name__ == "__main__":
    unittest.main()
