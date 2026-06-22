"""
Test Fase 81 - Bootstrap Casa VIP (composition root).

Copre: default-off (niente componenti), accensione (catalogo/inventario/concierge/mcp
cablati), incoerenza attiva (segreto debole -> BootstrapError), MCP opzionale, e la
PROVA END-TO-END che i moduli lavorano INSIEME attraverso il sistema composto:
pubblica in vetrina -> inventario -> la vetrina mostra la disponibilita' reale ->
concierge quota+prenota -> MCP manifest/tools.
"""
import unittest

from fase81_bootstrap_casavip import (
    BootstrapError, ConfigCasaVIP, SistemaCasaVIP, crea_sistema,
)

SEG = b"0123456789abcdef0123456789abcdef"


class TestDefaultOff(unittest.TestCase):
    def test_spento(self):
        s = crea_sistema()
        self.assertFalse(s.attivo)
        self.assertIsNone(s.catalogo)
        self.assertIsNone(s.concierge)
        self.assertFalse(s.money_path_pronto)

    def test_spento_esplicito(self):
        s = crea_sistema(ConfigCasaVIP(abilitato=False, segreto_hmac=SEG))
        self.assertFalse(s.attivo)


class TestAccensione(unittest.TestCase):
    def setUp(self):
        self.s = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=SEG))

    def test_componenti_presenti(self):
        self.assertTrue(self.s.attivo)
        self.assertIsNotNone(self.s.catalogo)
        self.assertIsNotNone(self.s.inventario)
        self.assertIsNotNone(self.s.concierge)
        self.assertIsNotNone(self.s.mcp)
        self.assertTrue(self.s.money_path_pronto)
        self.assertIn("concierge(59)", self.s.report["componenti"])

    def test_segreto_debole_errore(self):
        with self.assertRaises(BootstrapError):
            crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=b"corto"))

    def test_mcp_opzionale(self):
        s = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=SEG, con_mcp=False))
        self.assertIsNone(s.mcp)
        self.assertIn("mcp disattivato (con_mcp=False)", s.report["avvisi"])


class TestEndToEnd(unittest.TestCase):
    def test_stack_lavora_insieme(self):
        s = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=SEG))
        from fase57_vetrina import CriteriRicerca, SchedaAlloggio

        # 1) host pubblica in vetrina
        s.catalogo.pubblica(SchedaAlloggio(host_id="h", slug="casa", titolo="Casa",
                                           citta="Roma", prezzo_notte_cents=10000,
                                           capacita=4))
        # 2) inventario realtime: carica 2 notti
        for g in ("2026-09-01", "2026-09-02"):
            s.inventario.imposta_disponibilita("casa", g, unita_totali=1,
                                               prezzo_netto_cents=10000)

        # 3) la vetrina mostra la disponibilita' REALE dell'inventario (cablaggio)
        res = s.catalogo.cerca(CriteriRicerca(citta="Roma", check_in="2026-09-01",
                                              check_out="2026-09-03"))
        self.assertEqual(res["totale"], 1)
        self.assertTrue(res["risultati"][0]["disponibile"])   # da fase58 via cablaggio

        # 4) concierge: preventivo firmato + prenotazione
        q = s.concierge.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                               "check_out": "2026-09-03"})
        self.assertEqual(q.status, 200)
        b = s.concierge.prenota({"quote_token": q.corpo["quote_token"],
                                 "email": "g@x.it"})
        self.assertEqual(b.status, 201)
        # inventario scalato dopo la prenotazione via concierge
        self.assertFalse(s.inventario.disponibile("casa", "2026-09-01", "2026-09-03"))

        # 5) MCP: manifest + tools list raggiungibili
        man = s.mcp.processa({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                              "params": {}})
        self.assertEqual(man["result"]["serverInfo"]["name"], "core_auto.hospitality")
        tl = s.mcp.processa({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(len(tl["result"]["tools"]), 6)

    def test_vetrina_non_disponibile_se_inventario_vuoto(self):
        s = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=SEG))
        from fase57_vetrina import CriteriRicerca, SchedaAlloggio
        s.catalogo.pubblica(SchedaAlloggio(host_id="h", slug="x", titolo="X",
                                           citta="Roma", prezzo_notte_cents=10000,
                                           capacita=2))
        res = s.catalogo.cerca(CriteriRicerca(citta="Roma", check_in="2026-09-01",
                                              check_out="2026-09-02"))
        # nessun inventario caricato -> non disponibile (fail-closed via fase58)
        self.assertFalse(res["risultati"][0]["disponibile"])


if __name__ == "__main__":
    unittest.main()
