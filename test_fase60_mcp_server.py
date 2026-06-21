"""
Test Fase 60 - MCP Server (Model Context Protocol).

Copre: handshake initialize, tools/list (schemi), tools/call sui 3 tool sopra il vero
stack fase57/58/59, flusso completo preventivo->prenota, REGOLA D'ORO (manomissione
prezzo via MCP respinta), idempotenza, mappatura errori, robustezza JSON-RPC (metodo
ignoto, malformato, notifica senza risposta, parse error), e stress concorrente
anti-overbooking via MCP (10x).
"""
import base64
import json
import os
import shutil
import tempfile
import threading
import unittest

from fase57_vetrina import SchedaAlloggio, crea_catalogo
from fase58_channel_manager import crea_channel_manager
from fase59_concierge import FirmaQuote, ProtocolloConcierge
from fase60_mcp_server import (
    ERR_INVALID_REQUEST, ERR_METHOD_NOT_FOUND, ERR_PARSE, MCP_PROTOCOL_VERSION,
    ServerMCP, crea_server_mcp,
)

SEGRETO = b"0123456789abcdef0123456789abcdef"
GIORNI = ("2026-10-01", "2026-10-02", "2026-10-03")


def _stack(unita=1, prezzo=10000, path=None):
    inv = crea_channel_manager(path) if path else crea_channel_manager()
    for g in GIORNI:
        inv.imposta_disponibilita("casa", g, unita_totali=unita, prezzo_netto_cents=prezzo)
    cat = crea_catalogo(disponibilita=inv.disponibile)
    cat.pubblica(SchedaAlloggio(host_id="h", slug="casa", titolo="Casa",
                                citta="Roma", prezzo_notte_cents=prezzo, capacita=4))
    proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat)
    return inv, crea_server_mcp(proto)


def _call(srv, name, arguments, mid=1):
    return srv.processa({"jsonrpc": "2.0", "id": mid, "method": "tools/call",
                         "params": {"name": name, "arguments": arguments}})


class TestHandshake(unittest.TestCase):
    def test_initialize(self):
        _, srv = _stack()
        r = srv.processa({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {}})
        res = r["result"]
        self.assertEqual(res["protocolVersion"], MCP_PROTOCOL_VERSION)
        self.assertIn("tools", res["capabilities"])
        self.assertEqual(res["serverInfo"]["name"], "core_auto.hospitality")

    def test_initialized_notifica_nessuna_risposta(self):
        _, srv = _stack()
        self.assertIsNone(srv.processa({"jsonrpc": "2.0",
                                        "method": "notifications/initialized"}))

    def test_ping(self):
        _, srv = _stack()
        r = srv.processa({"jsonrpc": "2.0", "id": 9, "method": "ping"})
        self.assertEqual(r["result"], {})
        self.assertEqual(r["id"], 9)


class TestToolsList(unittest.TestCase):
    def test_elenco_tool_con_schema(self):
        _, srv = _stack()
        r = srv.processa({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        nomi = {t["name"] for t in r["result"]["tools"]}
        self.assertEqual(nomi, {"cerca_alloggi", "ottieni_preventivo", "prenota"})
        for t in r["result"]["tools"]:
            self.assertEqual(t["inputSchema"]["type"], "object")


class TestToolsCall(unittest.TestCase):
    def test_cerca(self):
        _, srv = _stack()
        r = _call(srv, "cerca_alloggi", {"citta": "Roma", "check_in": "2026-10-01",
                                         "check_out": "2026-10-03"})
        self.assertFalse(r["result"]["isError"])
        corpo = r["result"]["structuredContent"]
        self.assertEqual(corpo["totale"], 1)
        self.assertEqual(corpo["money_unit"], "cents_integer")

    def test_preventivo_e_prenota(self):
        inv, srv = _stack(unita=1)
        q = _call(srv, "ottieni_preventivo", {"alloggio_id": "casa",
                  "check_in": "2026-10-01", "check_out": "2026-10-03"})
        token = q["result"]["structuredContent"]["quote_token"]
        self.assertEqual(q["result"]["structuredContent"]["prezzo_guest_cents"], 20000)
        b = _call(srv, "prenota", {"quote_token": token, "email": "g@x.it"})
        self.assertFalse(b["result"]["isError"])
        self.assertEqual(b["result"]["structuredContent"]["stato"], "confermata")
        self.assertFalse(inv.disponibile("casa", "2026-10-01", "2026-10-03"))

    def test_prenota_idempotente(self):
        _, srv = _stack(unita=1)
        q = _call(srv, "ottieni_preventivo", {"alloggio_id": "casa",
                  "check_in": "2026-10-01", "check_out": "2026-10-03"})
        token = q["result"]["structuredContent"]["quote_token"]
        _call(srv, "prenota", {"quote_token": token, "email": "g@x.it"})
        b2 = _call(srv, "prenota", {"quote_token": token, "email": "g@x.it"})
        self.assertTrue(b2["result"]["structuredContent"]["idempotente"])

    def test_regola_oro_manomissione_prezzo(self):
        """L'agente prova ad abbassare il prezzo nel token via MCP -> firma rotta."""
        _, srv = _stack()
        q = _call(srv, "ottieni_preventivo", {"alloggio_id": "casa",
                  "check_in": "2026-10-01", "check_out": "2026-10-03"})
        token = q["result"]["structuredContent"]["quote_token"]
        b64, sig = token.split(".")
        payload = json.loads(base64.urlsafe_b64decode(b64))
        payload["prezzo_guest_cents"] = 1
        b64f = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).decode()
        b = _call(srv, "prenota", {"quote_token": b64f + "." + sig, "email": "g@x.it"})
        self.assertTrue(b["result"]["isError"])      # niente sconto pirata

    def test_errore_non_disponibile(self):
        inv, srv = _stack(unita=1)
        inv.blocca("casa", "2026-10-01", "2026-10-03", idem_key="x")
        q = _call(srv, "ottieni_preventivo", {"alloggio_id": "casa",
                  "check_in": "2026-10-01", "check_out": "2026-10-03"})
        self.assertTrue(q["result"]["isError"])

    def test_tool_ignoto(self):
        _, srv = _stack()
        r = _call(srv, "vola_sulla_luna", {})
        self.assertIn("error", r)

    def test_params_non_dict(self):
        _, srv = _stack()
        r = srv.processa({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": "stringa"})
        self.assertIn("error", r)


class TestRobustezzaJsonRpc(unittest.TestCase):
    def test_metodo_ignoto(self):
        _, srv = _stack()
        r = srv.processa({"jsonrpc": "2.0", "id": 5, "method": "pippo"})
        self.assertEqual(r["error"]["code"], ERR_METHOD_NOT_FOUND)

    def test_jsonrpc_mancante(self):
        _, srv = _stack()
        r = srv.processa({"id": 1, "method": "ping"})
        self.assertEqual(r["error"]["code"], ERR_INVALID_REQUEST)

    def test_notifica_metodo_ignoto_nessuna_risposta(self):
        _, srv = _stack()
        self.assertIsNone(srv.processa({"jsonrpc": "2.0", "method": "qualcosa"}))

    def test_gestisci_raw_parse_error(self):
        _, srv = _stack()
        out = srv.gestisci_raw("{non json")
        self.assertEqual(json.loads(out)["error"]["code"], ERR_PARSE)

    def test_gestisci_raw_flusso(self):
        _, srv = _stack()
        out = srv.gestisci_raw(json.dumps({"jsonrpc": "2.0", "id": 1,
                                           "method": "tools/list"}))
        self.assertEqual(len(json.loads(out)["result"]["tools"]), 3)

    def test_non_solleva_mai(self):
        _, srv = _stack()
        for bad in (None, 123, [], "", {"jsonrpc": "2.0"}, {"jsonrpc": "2.0", "id": 1,
                    "method": "tools/call", "params": {"name": 999}}):
            try:
                srv.processa(bad)
            except Exception as e:  # pragma: no cover
                self.fail(f"dispatcher ha sollevato su {bad!r}: {e}")


class TestStressMCP(unittest.TestCase):
    def test_anti_overbooking_via_mcp_10x(self):
        """10 ripetizioni: molti agenti MCP prenotano la stessa notte da 1 unita';
        esattamente 1 conferma."""
        for rip in range(10):
            d = tempfile.mkdtemp()
            try:
                inv, srv = _stack(unita=1, path=os.path.join(d, f"m{rip}.db"))
                esiti = []
                lock = threading.Lock()

                def agente(i):
                    q = _call(srv, "ottieni_preventivo", {"alloggio_id": "casa",
                              "check_in": "2026-10-01", "check_out": "2026-10-02"}, mid=i)
                    sc = q["result"]["structuredContent"]
                    if "quote_token" not in sc:
                        return
                    b = _call(srv, "prenota", {"quote_token": sc["quote_token"],
                              "email": f"a{i}@x.it"}, mid=i)
                    with lock:
                        esiti.append(not b["result"]["isError"])

                th = [threading.Thread(target=agente, args=(i,)) for i in range(16)]
                for t in th:
                    t.start()
                for t in th:
                    t.join()
                self.assertEqual(sum(1 for ok in esiti if ok), 1,
                                 f"rip {rip}: attesa 1 conferma")
                self.assertEqual(inv.stato_giorno("casa", "2026-10-01")["unita_occupate"], 1)
            finally:
                shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
