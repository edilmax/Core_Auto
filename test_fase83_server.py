"""
Test Fase 83 - Server HTTP (RouterHTTP puro).

Copre: health/lingue/i18n, catalogo (vuoto/popolato/traduzione servizi per lingua),
dettaglio/404, flusso concierge quote->book via HTTP, MCP JSON-RPC, host pubblica +
disponibilita' (auth X-Host-Key), errori (json invalido/rotta ignota/sistema spento),
mai solleva. Usa un SistemaCasaVIP reale (fase81).
"""
import json
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import (
    RouterHTTP, crea_router, percorso_statico_sicuro,
    jsonld_alloggio, pagina_alloggio_html, sitemap_xml, robots_txt, _euro,
)

SEG = b"0123456789abcdef0123456789abcdef"


def _sistema():
    return crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=SEG))


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
        self.assertNotIn("ordine", c)
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
        self.r = crea_router(self.sys)

    def _book(self):
        s, c = self.r.gestisci("POST", "/api/concierge/quote", body=json.dumps(
            {"alloggio_id": "casa", "check_in": "2026-09-01", "check_out": "2026-09-02"}))
        s2, c2 = self.r.gestisci("POST", "/api/concierge/book", body=json.dumps(
            {"quote_token": c["quote_token"], "email": "g@x.it"}))
        self.assertEqual(s2, 201)

    def test_payout_dopo_book(self):
        self._book()
        s, c = self.r.gestisci("GET", "/api/host/payout", {"host_id": "h"})
        self.assertEqual(s, 200)
        self.assertIn("EUR", c["payout"])
        self.assertGreater(c["payout"]["EUR"].get("maturato", 0), 0)   # netto host atteso

    def test_payout_host_id_mancante(self):
        s, c = self.r.gestisci("GET", "/api/host/payout", {})
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
        self.r = crea_router(_sistema())

    def test_tassa_zero_default(self):
        s, c = self.r.gestisci("GET", "/api/tassa",
                               {"citta": "roma", "notti": "3", "ospiti": "2"})
        self.assertEqual(s, 200)
        self.assertEqual(c["tassa_cents"], 0)          # nessuna regola env -> 0
        self.assertEqual(c["money_unit"], "cents_integer")

    def test_split_crea_paga_completa(self):
        # conto da 9000 diviso fra 3 -> 3000 ciascuno
        s, c = self.r.gestisci("POST", "/api/split/crea", body=json.dumps(
            {"prenotazione_id": "p1", "alloggio_id": "casa", "totale_cents": 9000,
             "partecipanti": ["a", "b", "c"]}))
        self.assertEqual(s, 201)
        cid = c["conto_id"]
        # a e b pagano
        for p in ("a", "b"):
            sp, cp = self.r.gestisci("POST", "/api/split/paga", body=json.dumps(
                {"conto_id": cid, "partecipante_id": p}))
            self.assertEqual(sp, 200)
            self.assertFalse(cp["completato"])
        # c paga -> completato
        sp, cp = self.r.gestisci("POST", "/api/split/paga", body=json.dumps(
            {"conto_id": cid, "partecipante_id": "c"}))
        self.assertTrue(cp["completato"])
        # replay idempotente
        sp2, cp2 = self.r.gestisci("POST", "/api/split/paga", body=json.dumps(
            {"conto_id": cid, "partecipante_id": "c"}))
        self.assertTrue(cp2["idempotente"])
        # stato
        ss, st = self.r.gestisci("GET", "/api/split/stato", {"conto_id": cid})
        self.assertEqual(st["totale_cents"], 9000)

    def test_split_conto_invalido(self):
        s, _ = self.r.gestisci("POST", "/api/split/crea", body=json.dumps(
            {"prenotazione_id": "p", "alloggio_id": "c", "totale_cents": 1000,
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
             "accetta_termini": True, "ragione_sociale": "B&B Mario"}))
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
        _, imp = self.r.gestisci("GET", "/api/host/alloggi", {"host_id": "IMPOSTORE"},
                                 headers=h)
        self.assertEqual(imp["alloggi"], [])      # NON pubblicato sotto l'impostore

    def test_token_invalido_bloccato(self):
        s, _ = self.r.gestisci("POST", "/api/host/pubblica",
                               headers={"X-Host-Token": "falso.token"},
                               body=json.dumps({"slug": "x", "titolo": "x", "citta": "x",
                                                "prezzo_notte_cents": 1000, "capacita": 1,
                                                "host_id": "h"}))
        self.assertEqual(s, 401)

    def test_login(self):
        self.r.gestisci("POST", "/api/host/registrazione", body=json.dumps(
            {"email": "l@b.it", "password": "passwordlunga", "accetta_termini": True}))
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
            {"email": "a@b.it", "password": "passwordlunga", "accetta_termini": True}))[1]
        ha = {"X-Host-Token": a["token"]}
        s, ref = self.r.gestisci("GET", "/api/host/referral", headers=ha)
        self.assertEqual(s, 200)
        self.assertIn("ref=", ref["link"])
        self.assertEqual(ref["credito_cents"], 0)
        codice = ref["codice"]
        # host B si registra COL codice di A -> entrambi accreditati
        b = self.r.gestisci("POST", "/api/host/registrazione", body=json.dumps(
            {"email": "b@b.it", "password": "passwordlunga", "accetta_termini": True,
             "codice_referral": codice}))[1]
        self.assertTrue(b["referral"]["ok"])
        self.assertGreater(b["referral"]["credito_cents"], 0)
        # ora A ha credito
        _, ref2 = self.r.gestisci("GET", "/api/host/referral", headers=ha)
        self.assertGreater(ref2["credito_cents"], 0)

    def test_registrazione_termini(self):
        s, c = self.r.gestisci("POST", "/api/host/registrazione", body=json.dumps(
            {"email": "x@b.it", "password": "passwordlunga", "accetta_termini": False}))
        self.assertEqual(s, 422)
        self.assertEqual(c["errore"], "termini_non_accettati")


class TestOnboarding(unittest.TestCase):
    def setUp(self):
        self.sys = _sistema()
        self.r = crea_router(self.sys, host_key="hk")
        self.h = {"X-Host-Key": "hk"}

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
        self.r = crea_router(self.sys)

    def _prenota(self):
        q = self.r.gestisci("POST", "/api/concierge/quote", body=json.dumps(
            {"alloggio_id": "casa", "check_in": "2026-09-01", "check_out": "2026-09-02"}))
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
        from fase83_server import _euro  # noqa
        ver = VerificatorePass(self.sys.firma, orologio=lambda: __import__(
            "fase64_smartpass")._epoch_da_data_ora("2026-09-01", 16))
        self.assertTrue(ver.verifica(corpo["smart_pass"], "casa").consentito)

    def test_pagina_voucher(self):
        from fase83_server import pagina_voucher_html
        _, corpo = self._prenota()
        h = pagina_voucher_html(self.sys, corpo["voucher_token"], "it")
        self.assertIn("Prenotazione confermata", h)
        self.assertIn(corpo["riferimento"], h)
        self.assertIn("BookinVIP", h)

    def test_voucher_manomesso_404(self):
        from fase83_server import pagina_voucher_html
        self.assertIsNone(pagina_voucher_html(self.sys, "falso.token"))
        self.assertIsNone(pagina_voucher_html(self.sys, "non-token"))

    def test_flusso_completo(self):
        _, corpo = self._prenota()
        diritto = corpo["diritto_recensione"]
        # invia recensione con il diritto firmato
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
        self.r.gestisci("POST", "/api/recensioni", body=json.dumps(
            {"token": corpo["diritto_recensione"], "voto": 4}))
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
        self.assertEqual(_euro(9500), "95.00")
        self.assertEqual(_euro(9999), "99.99")
        self.assertEqual(_euro(5), "0.05")
        self.assertEqual(_euro(-1), "0.00")

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
        xml = sitemap_xml(self.sys, "https://x.it")
        self.assertIn("https://x.it/alloggio/casa", xml)
        self.assertIn("urlset", xml)

    def test_robots(self):
        r = robots_txt("https://x.it")
        self.assertIn("Sitemap: https://x.it/sitemap.xml", r)


class TestRobustezza(unittest.TestCase):
    def test_mai_solleva(self):
        r = crea_router(_sistema())
        for m, p, b in (("GET", "/api/catalogo", None), ("POST", "/api/mcp", None),
                        ("POST", "/api/concierge/quote", None), ("GET", None, None)):
            try:
                r.gestisci(m, p or "/api/x", {}, b)
            except Exception as e:  # pragma: no cover
                self.fail(f"sollevato su {m} {p}: {e}")


if __name__ == "__main__":
    unittest.main()
