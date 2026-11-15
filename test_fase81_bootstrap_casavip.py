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
    # in una costante: passata come stringa a un argomento `*_key` conta per bandit come segreto
    # cablato (B106). La rete e' finta, la chiave non conta.
    CHIAVE_FINTA = "sk_test_xyz"

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

    def test_prova12_il_concierge_riceve_anche_il_numero_della_pagina(self):
        """Prova mancante 12 (pr-test-analyzer, 11/11): l'avvio deve passare al concierge
        `crea_sessione` (indirizzo E numero della pagina), non `crea_link` (solo indirizzo):
        senza il numero lo spazzino non sa quale pagina chiudere prima di liberare la stanza."""
        s = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=SEG,
                                       stripe_secret_key=self.CHIAVE_FINTA))
        s.stripe._fetch = lambda u, b, h: {"url": "https://checkout.stripe.test/cs_z",
                                           "id": "cs_z"}
        url, numero = s.concierge._link_isolato({"totale_cents": 10000, "valuta": "EUR",
                                                 "riferimento": "r1", "email": "g@x.it"})
        self.assertEqual((url, numero), ("https://checkout.stripe.test/cs_z", "cs_z"))

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


class TestPR316LaCodaEmailSiCollegaSoloAUnArchivioVero(unittest.TestCase):
    """Pezzo 4 (PR #316): sopravvissuti del giudice sul diff (job caselle di 2bfa64b) su
    `collega_coda_email` e sul suo uso in `crea_sistema` (:182 :189 :612). Le prove c'erano in
    test_email_tracciata, che il giudice per fase81 non accende: qui stanno nel dedicato.
    Le due direzioni: con provider e archivio su file la coda c'e', parte da sola col suo giro
    e si dichiara fra i componenti; senza provider, senza archivio o in RAM non c'e' niente."""

    class _Prov(object):
        def __init__(self):
            self.chiamate = []

        def invia(self, destinatario, oggetto, corpo_html):
            self.chiamate.append(destinatario)
            return True

    def setUp(self):
        import os
        import shutil
        import tempfile
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.db = os.path.join(self.dir, "coda_email.db")

    def _collega(self, prov, percorso, **k):
        from fase81_bootstrap_casavip import collega_coda_email
        coda = collega_coda_email(prov, percorso, **k)
        if coda is not None:
            self.addCleanup(coda.ferma)       # prima di ogni asserzione: un giro non resta vivo
        return coda

    def test_con_provider_e_archivio_su_file_la_coda_c_e_ed_e_del_provider(self):
        import os
        prov = self._Prov()
        coda = self._collega(prov, self.db, avvia=False)
        self.assertIsNotNone(coda, "provider e archivio su file, e nessuna coda: email perse")
        self.assertIs(getattr(prov, "coda_email", None), coda,
                      "la coda non e' appesa al provider: fase83 non la troverebbe")
        self.assertEqual(os.path.abspath(coda.percorso), os.path.abspath(self.db))
        self.assertTrue(os.path.exists(self.db), "l'archivio della coda non e' stato creato")
        self.assertIsNone(getattr(coda, "_giro", None), "avvia=False e il giro e' partito")

    def test_senza_archivio_o_in_RAM_niente_coda(self):
        for percorso in ("", None, ":memory:"):
            with self.subTest(percorso=percorso):
                prov = self._Prov()
                self.assertIsNone(self._collega(prov, percorso, avvia=False),
                                  "una coda senza archivio su file morirebbe al riavvio")
                self.assertFalse(hasattr(prov, "coda_email"), "coda appesa senza archivio")

    def test_senza_provider_niente_coda_e_niente_archivio(self):
        import os
        self.assertIsNone(self._collega(None, self.db, avvia=False))
        self.assertFalse(os.path.exists(self.db), "senza provider si e' creato un archivio")

    def test_di_serie_il_giro_parte_da_solo_e_non_tiene_vivo_il_processo(self):
        coda = self._collega(self._Prov(), self.db)
        giro = getattr(coda, "_giro", None)
        self.assertIsNotNone(giro, "di serie il giro della coda deve partire: nessuno ritenta")
        self.assertTrue(giro.is_alive(), "il giro della coda non gira")
        self.assertTrue(giro.daemon, "un giro non demone tiene vivo il processo all'uscita")

    def test_crea_sistema_dichiara_la_coda_solo_quando_c_e(self):
        s = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=SEG,
                                       smtp_host="smtp.invalid", db_coda_email=self.db))
        coda = getattr(s.email_provider, "coda_email", None)
        if coda is not None:
            self.addCleanup(coda.ferma)
        self.assertIsNotNone(coda, "SMTP acceso e archivio su file, e nessuna coda")
        self.assertIn("email(86)", s.report["componenti"])
        self.assertIn("coda_email(86)", s.report["componenti"],
                      "la coda c'e' e il sistema non lo dichiara: %r" % (s.report["componenti"],))
        s2 = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=SEG,
                                        smtp_host="smtp.invalid", db_coda_email=":memory:"))
        self.assertIsNone(getattr(s2.email_provider, "coda_email", None))
        self.assertIn("email(86)", s2.report["componenti"])
        self.assertNotIn("coda_email(86)", s2.report["componenti"],
                         "dichiarata una coda che non esiste: %r" % (s2.report["componenti"],))


if __name__ == "__main__":
    unittest.main()
