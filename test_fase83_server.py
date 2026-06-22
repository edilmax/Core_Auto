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
from fase83_server import RouterHTTP, crea_router, percorso_statico_sicuro

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
