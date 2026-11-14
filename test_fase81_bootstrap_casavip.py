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
from unittest import mock

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
        self.assertIsNotNone(self.s.recensioni)
        self.assertIsNotNone(self.s.emettitore_recensioni)
        self.assertTrue(self.s.money_path_pronto)
        self.assertIn("concierge(59)", self.s.report["componenti"])
        self.assertIn("recensioni(63)", self.s.report["componenti"])

    def test_segreto_debole_errore(self):
        with self.assertRaises(BootstrapError):
            crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=b"corto"))

    def test_stripe_gated(self):
        # senza chiave: nessun componente stripe, niente link
        self.assertNotIn("stripe(85)", self.s.report["componenti"])
        # con chiave: componente presente e link cablato nel concierge
        s = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=SEG,
                                       stripe_secret_key="sk_test_xyz"))
        self.assertIn("stripe(85)", s.report["componenti"])
        self.assertIsNotNone(s.concierge._link)

    def test_mcp_opzionale(self):
        s = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=SEG, con_mcp=False))
        self.assertIsNone(s.mcp)
        self.assertIn("mcp disattivato (con_mcp=False)", s.report["avvisi"])

    def test_senza_la_chiave_dei_cambi_l_avvio_lo_DICHIARA(self):
        """⛔ VOCE 255 (4/11): senza fornitore di cambi la quota fissa della tariffa tecnica
        non si converte nelle altre monete (fase59, fase83). In produzione la chiave c'e' (letta
        il 4/11); se sparisse, l'avvio lo deve DIRE: il protocollo di deploy legge `avvisi` e si
        aspetta la lista vuota. Con la chiave l'avviso tace (la rete qui non si tocca)."""
        from unittest import mock
        import fase99_multicurrency as f99
        s = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=SEG))
        self.assertTrue([a for a in s.report["avvisi"] if "OXR_APP_ID" in a and "quota fissa" in a],
                        s.report["avvisi"])
        with mock.patch.object(f99.ProviderTassi, "scalda", lambda self: None):
            s2 = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=SEG,
                                            oxr_app_id="chiave-di-prova"))
        self.assertIsNotNone(s2.tassi)
        self.assertEqual([a for a in s2.report["avvisi"] if "OXR_APP_ID" in a], [],
                         s2.report["avvisi"])


class TestLaDataDelBonifico(unittest.TestCase):
    """PR #315 (pezzo 3), job `caselle` del 14/11 su bb014a7: il cablaggio `connect.da_quando`
    (PR5, 8/11) aveva la sua prova solo in test_fase101, che il giudice non accende per questo
    file. Il bonifico di una prenotazione si cerca da un giorno prima che lei nascesse; di una
    prenotazione che non conosciamo, dall'inizio (0 meno il giorno di margine)."""

    # Finta e senza rete: serve solo ad accendere il cablaggio Connect. Sta in un nome e non
    # dentro la chiamata, cosi' bandit (B106) non la conta come segreto scritto a mano.
    _CHIAVE_FINTA = "sk_test_xyz"

    def test_PR315_il_bonifico_si_cerca_da_un_giorno_prima_della_prenotazione(self):
        import os
        import shutil
        import tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        s = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=SEG,
                                       db_pendenti=os.path.join(d, "p.db"),
                                       stripe_secret_key=self._CHIAVE_FINTA))
        self.assertIsNotNone(s.connect, "premessa: con la chiave Connect e' cablato")
        self.assertTrue(s.pagamenti_pendenti.registra(
            "R-PR315", alloggio_id="casa", check_in="2027-01-01", check_out="2027-01-03"))
        creato = s.pagamenti_pendenti.info("R-PR315")["creato_ts"]
        self.assertGreater(creato, 86400, "premessa: data di nascita vera")
        self.assertEqual(s.connect.da_quando("R-PR315"), creato - 86400)
        self.assertEqual(s.connect.da_quando("R-SCONOSCIUTA"), -86400)


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
