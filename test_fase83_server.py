"""
Test Fase 83 - Server HTTP (RouterHTTP puro).

Copre: health/lingue/i18n, catalogo (vuoto/popolato/traduzione servizi per lingua),
dettaglio/404, flusso concierge quote->book via HTTP, MCP JSON-RPC, host pubblica +
disponibilita' (auth X-Host-Key), errori (json invalido/rotta ignota/sistema spento),
mai solleva. Usa un SistemaCasaVIP reale (fase81).
"""
import datetime
import http.client
import json
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
from urllib.parse import parse_qs, quote, urlencode, urlparse

import fase83_server
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256
from test_rimborso_torna_da_ogni_strada import _BancoDelleStrade
from fase83_server import (
    RouterHTTP, crea_router, percorso_statico_sicuro,
    jsonld_alloggio, pagina_alloggio_html, sitemap_xml, robots_txt, _importo,
    _testo_per_registro,
)

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
        s, _c = self.g("POST", "/api/garanzia/contesta", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200, "PREMESSA NON VALIDA: la contestazione non riesce")
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


if __name__ == "__main__":
    unittest.main()
