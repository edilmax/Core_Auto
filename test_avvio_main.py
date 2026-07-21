"""GUARDIA — `main_casavip.py` viene ESEGUITO, non solo letto.

PERCHE' ESISTE (2026-07-21). `main_casavip.py` e' l'unico file del prodotto che nessun
test eseguiva: e' marcato `# pragma: no cover` e la suite costruisce il sistema da
`crea_sistema()` in giu', saltando l'entrypoint. Risultato: tutto cio' che vive SOLO li'
— quali database vengono passati, con quali percorsi, quali cartelle vengono create —
non era coperto da nulla.

Avviandolo per davvero, il 2026-07-21, sono emersi in un colpo solo:
  · `DB_RECENSIONI` e `DB_CREDITO_USATI` non venivano passati -> restavano `:memory:`
    anche in produzione (recensioni perse a ogni riavvio; credito rispendibile);
  · il giro della marca temporale partiva solo con SMTP configurato.

Qui `main()` viene eseguito PER INTERO con `servi()` intercettato al posto del suo ciclo
infinito: si verifica cosa ha davvero composto, senza aprire nessuna porta di rete.
"""

import os
import shutil
import tempfile
import unittest


class TestAvvioReale(unittest.TestCase):

    def setUp(self):
        # `main()` chiama _configura_logging(), che AGGIUNGE gestori alla radice: senza
        # ripristino, nella suite intera se ne accumulerebbero decine, puntati a cartelle
        # temporanee poi cancellate (log rumorosi e scritture verso file inesistenti).
        import logging
        radice = logging.getLogger()
        precedenti, livello = list(radice.handlers), radice.level

        def _ripristina():
            for h in list(radice.handlers):
                if h not in precedenti:
                    try:
                        h.close()
                    except Exception:
                        pass
                    radice.removeHandler(h)
            radice.setLevel(livello)

        self.addCleanup(_ripristina)
        self.dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))
        self._env = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self._env)))
        os.environ.update({
            "CASAVIP_SEGRETO": "5a" * 32,
            "HOST_KEY": "hk-prova", "ADMIN_KEY": "ak-prova",
            "DATA_DIR": os.path.join(self.dir, "data"),
            "MARCA_TEMPORALE": "0",          # niente rete nella suite
            "GEOCODING": "false", "POI_OSM": "false",
        })
        for nome in list(os.environ):
            if nome.startswith("DB_") or nome in ("FILE_REFERRAL", "UPLOAD_DIR"):
                del os.environ[nome]
        # ogni database su file, dentro la cartella temporanea
        from fase81_bootstrap_casavip import ConfigCasaVIP
        for campo in vars(ConfigCasaVIP()):
            if campo.startswith("db_"):
                os.environ[campo.upper()] = os.path.join(
                    self.dir, "data", campo[3:] + ".db")

    def _avvia(self):
        """Esegue main() intero, sostituendo solo il server che non ritorna mai."""
        import main_casavip
        catturato = {}

        def finto_servi(sistema, **kw):
            catturato["sistema"] = sistema
            catturato["kw"] = kw

        vero = main_casavip.servi
        main_casavip.servi = finto_servi
        try:
            main_casavip.main()
        finally:
            main_casavip.servi = vero
        self.assertIn("sistema", catturato, "main() non ha mai avviato il server")
        return catturato["sistema"]

    def test_il_programma_si_avvia(self):
        sistema = self._avvia()
        self.assertTrue(sistema.report.get("abilitato"))
        self.assertTrue(sistema.report.get("money_path_pronto"))

    def test_NESSUN_database_resta_in_memoria(self):
        """IL CUORE. Un `:memory:` sfuggito qui significa dati che spariscono al riavvio
        senza che nulla se ne accorga: e' esattamente cio' che accadeva a recensioni e
        crediti gia' spesi fino al 2026-07-21."""
        sistema = self._avvia()
        in_ram = [c for c in vars(sistema.config)
                  if c.startswith("db_") and getattr(sistema.config, c) == ":memory:"]
        self.assertEqual(in_ram, [],
                         "database ancora IN MEMORIA all'avvio reale: %s — i loro dati "
                         "spariranno a ogni riavvio" % ", ".join(in_ram))

    def test_i_database_delicati_sono_passati_esplicitamente(self):
        """Quelli che, se persi, costano soldi o prove."""
        sistema = self._avvia()
        for campo in ("db_accettazioni", "db_marche", "db_finanza", "db_recensioni",
                      "db_credito_usati", "db_payout", "db_pendenti"):
            valore = getattr(sistema.config, campo, ":memory:")
            self.assertNotEqual(valore, ":memory:", "%s non e' persistente!" % campo)
            self.assertTrue(str(valore).endswith(".db"), "%s: %s" % (campo, valore))

    def test_le_cartelle_vengono_create_per_ogni_percorso(self):
        """La creazione non deve dipendere da una lista scritta a mano."""
        sistema = self._avvia()
        for campo in vars(sistema.config):
            if not campo.startswith("db_"):
                continue
            percorso = getattr(sistema.config, campo)
            if percorso == ":memory:":
                continue
            cartella = os.path.dirname(percorso)
            self.assertTrue(os.path.isdir(cartella),
                            "cartella non creata per %s: %s" % (campo, cartella))

    def test_i_file_nascono_davvero_su_disco(self):
        """Non basta il percorso: il database dev'essere stato aperto e creato."""
        self._avvia()
        cartella = os.path.join(self.dir, "data")
        creati = {f for f in os.listdir(cartella) if f.endswith(".db")}
        for atteso in ("accettazioni.db", "recensioni.db", "credito_usati.db",
                       "finanza.db", "registro_host.db"):
            self.assertIn(atteso, creati,
                          "%s non e' stato creato all'avvio: %s" % (atteso, sorted(creati)))

    def test_i_componenti_attesi_sono_accesi(self):
        sistema = self._avvia()
        componenti = " ".join(sistema.report.get("componenti", []))
        for atteso in ("recensioni(63)", "accettazioni(163)", "credito_single_use(167)",
                       "financial_controller(177)", "registro_host(88)"):
            self.assertIn(atteso, componenti, "componente spento: %s" % atteso)

    def test_la_marca_si_accende_e_si_spegne_dalla_variabile(self):
        os.environ["MARCA_TEMPORALE"] = "0"
        self.assertIsNone(self._avvia().marche, "spenta ma presente")
        os.environ["MARCA_TEMPORALE"] = "1"
        sistema = self._avvia()
        self.assertIsNotNone(sistema.marche, "accesa ma assente")
        self.assertIn("marca_temporale(184)", sistema.report.get("componenti", []))

    def test_senza_le_chiavi_daccesso_NON_parte(self):
        """Fail-closed: meglio non partire che partire con le API host spalancate."""
        for mancante in ("HOST_KEY", "ADMIN_KEY"):
            salvata = os.environ.pop(mancante)
            try:
                with self.assertRaises(SystemExit):
                    self._avvia()
            finally:
                os.environ[mancante] = salvata

    def test_nessun_avviso_inatteso_a_configurazione_completa(self):
        """Con Stripe e SMTP assenti gli avvisi sono DUE e noti: se ne compaiono altri,
        qualcosa si e' spento senza che nessuno lo sappia."""
        sistema = self._avvia()
        avvisi = sistema.report.get("avvisi", [])
        for a in avvisi:
            self.assertTrue("Stripe" in a or "SMTP" in a or "avviso host" in a,
                            "avviso inatteso all'avvio: %s" % a)


if __name__ == "__main__":
    unittest.main(verbosity=2)
