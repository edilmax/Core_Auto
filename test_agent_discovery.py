"""Superficie AI-agent: manifest di scoperta /.well-known/ai-plugin.json + /openapi.json.
Puri e testabili: qualsiasi agente (Claude/Gemini/ChatGPT) scopre il flusso cerca->quote->prenota."""
import json
import unittest

from fase83_server import ai_plugin_manifest, openapi_agent_spec


class TestAgentDiscovery(unittest.TestCase):
    def test_ai_plugin_manifest(self):
        m = ai_plugin_manifest("https://bookinvip.com")
        self.assertEqual(m["schema_version"], "v1")
        self.assertEqual(m["name_for_model"], "bookinvip")
        self.assertEqual(m["auth"]["type"], "none")
        self.assertEqual(m["api"]["url"], "https://bookinvip.com/openapi.json")
        self.assertEqual(m["mcp"]["url"], "https://bookinvip.com/api/mcp")
        json.dumps(m)   # serializzabile

    def test_manifest_base_url_default(self):
        m = ai_plugin_manifest("")
        self.assertTrue(m["api"]["url"].startswith("https://bookinvip.com"))

    def test_openapi_flusso_prenotazione(self):
        s = openapi_agent_spec("https://bookinvip.com")
        self.assertTrue(str(s["openapi"]).startswith("3.0"))
        self.assertEqual(s["servers"][0]["url"], "https://bookinvip.com")
        for p in ("/api/catalogo", "/api/concierge/quote", "/api/concierge/book",
                  "/api/i18n", "/api/domanda/citta", "/api/mcp"):
            self.assertIn(p, s["paths"], p)
        # il preventivo richiede alloggio_id/check_in/check_out; il book richiede quote_token+email
        req_book = s["paths"]["/api/concierge/book"]["post"]["requestBody"]["content"][
            "application/json"]["schema"]["required"]
        self.assertIn("quote_token", req_book)
        self.assertIn("email", req_book)
        json.dumps(s)   # serializzabile


if __name__ == "__main__":
    unittest.main()
