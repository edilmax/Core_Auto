"""
Test FASE 28 / BLOCCO 2 - API Gateway.

Copre: validatore BLINDATO (batteria ostile -> 0 eccezioni, oversize/DoS
rifiutato), autenticazione per-cliente (timing-safe), orchestrazione
auth/validazione/evento (401/400/200), ISOLAMENTO TOTALE (publisher che esplode
-> 503, mai leak) e la route Flask end-to-end (estensione /api/v1).
"""
import unittest

from fase28_gateway import (ClientRegistry, GatewayAgente, valida_messaggio,
                            registra_gateway, RichiestaMessaggio)
from fase25_brain import AgenteIA, StubLLMProvider
from fase26_ricerca import Proposta, RicercaStub, MotoreRicercaProtetto
from fase27_proposte import GeneratoreProposte


_OSTILI = [None, [], "x", 42, {}, {"channel": "wa"},
           {"channel": "wa", "recipient": "r"},
           {"channel": 123, "recipient": "r", "text": "hi"},
           {"channel": "wa", "recipient": "r", "text": ""},
           {"channel": "wa", "recipient": "r", "text": "x" * 99999},
           {"channel": "wa", "recipient": None, "text": "hi"},
           {"channel": "wa", "recipient": "r", "text": ["nested"]}]


class TestValidatore(unittest.TestCase):

    def test_batteria_ostile_zero_eccezioni(self):
        for data in _OSTILI:
            ok, codice, ric = valida_messaggio(data)   # non deve MAI sollevare
            self.assertFalse(ok)
            self.assertTrue(codice)
            self.assertIsNone(ric)

    def test_payload_valido(self):
        ok, codice, ric = valida_messaggio(
            {"channel": "wa", "recipient": "+39", "text": "ciao",
             "localita": "Roma", "budget_max": 100})
        self.assertTrue(ok)
        self.assertIsInstance(ric, RichiestaMessaggio)
        self.assertEqual((ric.channel, ric.localita, ric.budget_max),
                         ("wa", "Roma", 100.0))

    def test_oversize_rifiutato(self):
        ok, codice, _ = valida_messaggio(
            {"channel": "wa", "recipient": "r", "text": "x" * 99999})
        self.assertFalse(ok)
        self.assertTrue(codice.startswith("campo_troppo_lungo"))

    def test_budget_negativo_e_non_numerico(self):
        self.assertFalse(valida_messaggio(
            {"channel": "wa", "recipient": "r", "text": "t", "budget_max": -1})[0])
        self.assertFalse(valida_messaggio(
            {"channel": "wa", "recipient": "r", "text": "t", "budget_max": "x"})[0])


class TestAuthPerCliente(unittest.TestCase):

    def test_autentica(self):
        reg = ClientRegistry({"k1": "c1", "k2": "c2"})
        self.assertEqual(reg.autentica("k1"), "c1")
        self.assertEqual(reg.autentica("k2"), "c2")
        self.assertIsNone(reg.autentica("x"))
        self.assertIsNone(reg.autentica(None))

    def test_from_env(self):
        import os
        os.environ["GATEWAY_CLIENTS"] = "abc:cliente_a, def:cliente_b"
        try:
            reg = ClientRegistry.from_env()
            self.assertEqual(reg.autentica("abc"), "cliente_a")
            self.assertEqual(reg.autentica("def"), "cliente_b")
        finally:
            os.environ.pop("GATEWAY_CLIENTS", None)


class TestProcessa(unittest.TestCase):

    def setUp(self):
        self.reg = ClientRegistry({"k-abc": "cliente1"})
        self.ag = AgenteIA(StubLLMProvider(risposta="Ciao!"))
        self.addCleanup(self.ag.stop)

    def test_401_chiave_errata(self):
        gw = GatewayAgente(self.reg, self.ag)
        self.assertEqual(gw.processa("nope", {}).status, 401)

    def test_400_payload_invalido(self):
        gw = GatewayAgente(self.reg, self.ag)
        self.assertEqual(gw.processa("k-abc", {"channel": "wa"}).status, 400)

    def test_200_risposta_agente(self):
        gw = GatewayAgente(self.reg, self.ag)
        r = gw.processa("k-abc", {"channel": "wa", "recipient": "+39", "text": "ciao"})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.corpo["client"], "cliente1")
        self.assertEqual(r.corpo["risposta"], "Ciao!")

    def test_intento_ricerca_genera_offerta(self):
        def fn(prompt):
            return "ricerca_alloggio" if "casa" in prompt.split("Messaggio:")[-1].lower() else "saluto"
        ag = AgenteIA(StubLLMProvider(fn))
        self.addCleanup(ag.stop)
        motore = MotoreRicercaProtetto(RicercaStub([Proposta("Trullo", "Roma", 80.0, "u", 9.0)]))
        gw = GatewayAgente(self.reg, ag, motore=motore, generatore=GeneratoreProposte())
        r = gw.processa("k-abc", {"channel": "wa", "recipient": "+39",
                                  "text": "cerco casa", "localita": "Roma"})
        self.assertEqual(r.status, 200)
        self.assertIn("88.00 EUR", r.corpo["risposta"])   # offerta con numeri esatti

    def test_503_isolamento_publisher_rotto(self):
        class _PubBoom:
            def publish_standalone(self, msg):
                raise RuntimeError("DB giu'")
        gw = GatewayAgente(self.reg, self.ag, publisher=_PubBoom())
        r = gw.processa("k-abc", {"channel": "wa", "recipient": "+39", "text": "ciao"})
        self.assertEqual(r.status, 503)
        self.assertEqual(r.corpo["error"], "service_unavailable")


class TestRouteFlask(unittest.TestCase):

    def setUp(self):
        from flask import Flask
        self.reg = ClientRegistry({"k-abc": "cliente1"})
        self.ag = AgenteIA(StubLLMProvider(risposta="Ciao!"))
        self.addCleanup(self.ag.stop)
        app = Flask(__name__)
        registra_gateway(app, GatewayAgente(self.reg, self.ag),
                         path="/api/v1/agent/message")
        self.client = app.test_client()

    def test_401_senza_chiave(self):
        r = self.client.post("/api/v1/agent/message",
                             json={"channel": "wa", "recipient": "r", "text": "ciao"})
        self.assertEqual(r.status_code, 401)

    def test_400_non_json(self):
        r = self.client.post("/api/v1/agent/message", data=b"non-json",
                             headers={"X-Client-Key": "k-abc",
                                      "Content-Type": "application/json"})
        self.assertEqual(r.status_code, 400)

    def test_200_valido(self):
        r = self.client.post("/api/v1/agent/message",
                             json={"channel": "wa", "recipient": "+39", "text": "ciao"},
                             headers={"X-Client-Key": "k-abc"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["risposta"], "Ciao!")


if __name__ == "__main__":
    unittest.main()
