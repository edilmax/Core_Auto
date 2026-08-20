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
        from fase59_concierge import codice_prenotazione
        from fase83_server import pagina_voucher_html
        _, corpo = self._prenota()
        rif = corpo["riferimento"]
        pin = self.sys.firma.pin_checkin(rif)
        h = pagina_voucher_html(self.sys, corpo["voucher_token"], "it")
        self.assertIn("Prenotazione confermata", h)
        self.assertIn(codice_prenotazione(rif), h)         # codice leggibile BVIP-XXXX-XXXX
        self.assertIn("PIN check-in", h)                   # l'etichetta c'è...
        self.assertNotIn(pin, h)                           # ...ma il PIN REALE no (bloccato pre-pagamento)
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

    def test_LA_CATENA_DEI_PROXY_PRENDE_IL_PRIMO_E_LO_CONVALIDA(self):
        """`X-Forwarded-For` puo' contenere piu' indirizzi separati da virgola: si continua a
        prendere il primo (comportamento invariato), ma passa dalla stessa convalida."""
        self.assertEqual("203.0.113.9", self._ip("203.0.113.9, 10.0.0.1, 172.16.0.1"))
        self.assertNotIn("cattivo", self._ip("cattivo, 10.0.0.1"))


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


if __name__ == "__main__":
    unittest.main()
