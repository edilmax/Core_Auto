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

    def test_json_invalido(self):
        s, c = self.r.gestisci("POST", "/api/concierge/quote", body="{rotto")
        self.assertEqual(s, 400)


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
