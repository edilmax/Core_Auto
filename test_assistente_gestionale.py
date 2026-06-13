#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Suite di test per assistente_gestionale.py (unittest, nessuna dipendenza extra).

Esecuzione:  python -m unittest test_assistente_gestionale -v

Garanzie dei test:
  - Lavorano SOLO in cartelle temporanee: non toccano TavolaVIP_Bozze,
    config_assistente.json ne' l'audit log reale.
  - Nessuna azione esterna reale: il prompt del gate e' iniettato
    (ApprovalGate accetta prompt= proprio per questo; patchare builtins.input
    NON basta, il default e' catturato alla definizione della classe)
    e gli esecutori sono funzioni finte.
"""

import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

import assistente_gestionale as ag


def config_di_prova(tmp: str) -> dict:
    """Config minima con percorsi ASSOLUTI dentro una cartella temporanea
    (os.path.join(BASE_DIR, percorso_assoluto) restituisce il percorso assoluto,
    quindi l'orchestratore non scrive mai dentro la cartella del progetto)."""
    bozze = os.path.join(tmp, "bozze")
    return {
        "progetto": "TavolaVIP-test",
        "sicurezza": {
            "autonomia_completa": False,
            "azioni_esterne_consentite": ["invio_email", "pubblicazione_social",
                                          "richiesta_web", "campagna_ricerca_web"],
            "azioni_sempre_vietate": ["tracciamento_persone"],
        },
        "percorsi": {
            "cartella_bozze": bozze,
            "file_log_audit": os.path.join(bozze, "audit.jsonl"),
            "file_candidati": os.path.join(bozze, "candidati.json"),
        },
    }


class BaseTemp(unittest.TestCase):
    """Base: cartella temporanea + audit + factory per gate con prompt iniettato."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = self._tmpdir.name
        self.config = config_di_prova(self.tmp)
        self.audit = ag.AuditLog(self.config["percorsi"]["file_log_audit"])

    def tearDown(self):
        self._tmpdir.cleanup()

    def gate_con_risposte(self, *risposte: str) -> ag.ApprovalGate:
        """Gate il cui prompt restituisce le risposte indicate, in ordine."""
        sequenza = iter(risposte)
        return ag.ApprovalGate(self.config, self.audit,
                               prompt=lambda msg: next(sequenza))

    def eventi_audit(self) -> list:
        with open(self.audit.percorso, "r", encoding="utf-8") as f:
            return [json.loads(r) for r in f if r.strip()]


class TestAuditLog(BaseTemp):

    def test_registra_appende_righe_jsonl_valide(self):
        self.audit.registra("evento_a", {"k": 1})
        self.audit.registra("evento_b", {"k": 2})
        eventi = self.eventi_audit()
        self.assertEqual([e["evento"] for e in eventi], ["evento_a", "evento_b"])
        self.assertEqual(eventi[1]["dettagli"], {"k": 2})
        for e in eventi:
            self.assertIn("timestamp", e)


class TestApprovalGate(BaseTemp):

    def test_approva_solo_con_la_parola_esatta(self):
        with redirect_stdout(io.StringIO()):
            # 'APPROVO' esatto e con spazi attorno (il gate fa .strip()): accettati
            for risposta in ("APPROVO", "APPROVO ", "  APPROVO"):
                gate = self.gate_con_risposte(risposta)
                self.assertTrue(gate.richiedi_approvazione("invio_email", "x"))
            # 'si', 'approvo' minuscolo, vuoto: tutti rifiutati
            for risposta in ("si", "approvo", ""):
                gate = self.gate_con_risposte(risposta)
                self.assertFalse(gate.richiedi_approvazione("invio_email", "x"))

    def test_azione_vietata_bloccata_senza_chiedere(self):
        gate = ag.ApprovalGate(self.config, self.audit,
                               prompt=lambda msg: self.fail("prompt non doveva essere chiamato"))
        with redirect_stdout(io.StringIO()):
            self.assertFalse(gate.richiedi_approvazione("tracciamento_persone", "x"))
        self.assertEqual(self.eventi_audit()[-1]["evento"], "azione_vietata_bloccata")

    def test_azione_fuori_ambito_bloccata(self):
        gate = ag.ApprovalGate(self.config, self.audit,
                               prompt=lambda msg: self.fail("prompt non doveva essere chiamato"))
        with redirect_stdout(io.StringIO()):
            self.assertFalse(gate.richiedi_approvazione("azione_inventata", "x"))
        self.assertEqual(self.eventi_audit()[-1]["evento"], "azione_fuori_ambito")

    def test_autonomia_completa_rifiutata(self):
        self.config["sicurezza"]["autonomia_completa"] = True
        gate = ag.ApprovalGate(self.config, self.audit, prompt=lambda msg: "APPROVO")
        with self.assertRaises(RuntimeError):
            gate.richiedi_approvazione("invio_email", "x")

    def test_decisioni_registrate_in_audit(self):
        with redirect_stdout(io.StringIO()):
            self.gate_con_risposte("no").richiedi_approvazione("invio_email", "x")
        ultimo = self.eventi_audit()[-1]
        self.assertEqual(ultimo["evento"], "decisione_approvazione")
        self.assertFalse(ultimo["dettagli"]["approvato"])


class TestGestoreBozze(BaseTemp):

    def setUp(self):
        super().setUp()
        self.cartella = self.config["percorsi"]["cartella_bozze"]

    def gestore(self, *risposte_gate: str) -> ag.GestoreBozze:
        return ag.GestoreBozze(self.cartella, self.gate_con_risposte(*risposte_gate),
                               self.audit)

    def test_crea_email_salva_file_json(self):
        with redirect_stdout(io.StringIO()):
            bozza = self.gestore().crea_email("a@b.it", "Oggetto", "Corpo")
        file_salvati = [n for n in os.listdir(self.cartella)
                        if n.startswith("bozza_email_")]
        self.assertEqual(len(file_salvati), 1)
        with open(os.path.join(self.cartella, file_salvati[0]), encoding="utf-8") as f:
            dati = json.load(f)
        self.assertEqual(dati["destinatario"], "a@b.it")
        self.assertEqual(bozza.tipo, "email")

    def test_elenca_salvate_ordina_e_salta_corrotti(self):
        gestore = self.gestore()
        # File scritti a mano per controllare nomi (= ordinamento) e corruzione.
        contenuti = {
            "bozza_email_20260101_000000.json":
                {"tipo": "email", "destinatario": "vecchia@x.it",
                 "oggetto": "vecchia", "corpo": "c", "creata_il": "2026-01-01T00:00:00"},
            "bozza_email_20260601_000000.json":
                {"tipo": "email", "destinatario": "nuova@x.it",
                 "oggetto": "nuova", "corpo": "c", "creata_il": "2026-06-01T00:00:00"},
        }
        for nome, dati in contenuti.items():
            with open(os.path.join(self.cartella, nome), "w", encoding="utf-8") as f:
                json.dump(dati, f)
        with open(os.path.join(self.cartella, "bozza_email_99990101_000000.json"),
                  "w", encoding="utf-8") as f:
            f.write("{ json rotto")
        with open(os.path.join(self.cartella, "non_una_bozza.json"),
                  "w", encoding="utf-8") as f:
            f.write("{}")

        with redirect_stdout(io.StringIO()):
            salvate = gestore.elenca_salvate()
        # Il file corrotto e quello estraneo sono esclusi; la piu' recente e' prima.
        self.assertEqual([b.destinatario for _, b in salvate],
                         ["nuova@x.it", "vecchia@x.it"])

    def test_invia_negato_dal_gate_non_chiama_esecutore(self):
        gestore = self.gestore("no")
        bozza = ag.Bozza("email", "a@b.it", "O", "C")
        esecutore = mock.Mock()
        with redirect_stdout(io.StringIO()):
            self.assertFalse(gestore.invia(bozza, esecutore=esecutore))
        esecutore.assert_not_called()

    def test_invia_approvato_senza_esecutore_resta_simulato(self):
        gestore = self.gestore("APPROVO")
        bozza = ag.Bozza("email", "a@b.it", "O", "C")
        with redirect_stdout(io.StringIO()):
            self.assertFalse(gestore.invia(bozza, esecutore=None))
        self.assertNotIn("azione_eseguita", [e["evento"] for e in self.eventi_audit()])

    def test_invia_approvato_con_esecutore_esegue_e_registra(self):
        gestore = self.gestore("APPROVO")
        bozza = ag.Bozza("social", "instagram", "(post social)", "testo")
        esecutore = mock.Mock()
        with redirect_stdout(io.StringIO()):
            self.assertTrue(gestore.invia(bozza, esecutore=esecutore))
        esecutore.assert_called_once_with(bozza)
        ultimo = self.eventi_audit()[-1]
        self.assertEqual(ultimo["evento"], "azione_eseguita")
        self.assertEqual(ultimo["dettagli"]["tipo"], "pubblicazione_social")


class TestRicercaAlloggi(BaseTemp):

    def setUp(self):
        super().setUp()
        self.file_candidati = self.config["percorsi"]["file_candidati"]

    def ricerca(self, *risposte_gate: str, percorso=None) -> ag.RicercaAlloggi:
        return ag.RicercaAlloggi(self.gate_con_risposte(*risposte_gate), self.audit,
                                 percorso_file=percorso)

    def test_costruisci_query_salta_campi_vuoti(self):
        criteri = ag.CriteriRicerca(citta="Roma", check_in="2026-07-01",
                                    check_out="", ospiti=2, budget_max_notte=80)
        query = self.ricerca().costruisci_query(criteri)
        self.assertEqual(query, "Roma | 2026-07-01 | 2 ospiti | max 80/notte")

    def test_classifica_mette_fuori_budget_in_fondo(self):
        r = self.ricerca()
        with redirect_stdout(io.StringIO()):
            r.aggiungi_candidato(ag.Alloggio("Caro", 95.0))
            r.aggiungi_candidato(ag.Alloggio("Economico", 70.0))
            r.aggiungi_candidato(ag.Alloggio("Medio", 75.0))
        self.assertEqual([a.titolo for a in r.classifica(budget_max=80)],
                         ["Economico", "Medio", "Caro"])

    def test_persistenza_salva_e_ricarica(self):
        with redirect_stdout(io.StringIO()):
            r1 = self.ricerca(percorso=self.file_candidati)
            r1.aggiungi_candidato(ag.Alloggio("Apt. Centro", 95.0, "http://es.it/1"))
            r1.aggiungi_candidato(ag.Alloggio("B&B Mare", 70.0))
            r2 = self.ricerca(percorso=self.file_candidati)  # "riavvio"
        self.assertEqual([c.titolo for c in r2.candidati],
                         ["Apt. Centro", "B&B Mare"])
        self.assertEqual(r2.candidati[0].url, "http://es.it/1")

    def test_persistenza_file_corrotto_riparte_da_zero(self):
        os.makedirs(os.path.dirname(self.file_candidati), exist_ok=True)
        with open(self.file_candidati, "w", encoding="utf-8") as f:
            f.write("{ json rotto")
        with redirect_stdout(io.StringIO()):
            r = self.ricerca(percorso=self.file_candidati)
        self.assertEqual(r.candidati, [])

    def test_senza_percorso_non_scrive_nulla(self):
        with redirect_stdout(io.StringIO()):
            r = self.ricerca(percorso=None)
            r.aggiungi_candidato(ag.Alloggio("Solo memoria", 50.0))
        self.assertFalse(os.path.exists(self.file_candidati))

    def test_cerca_online_negato_o_senza_esecutore(self):
        with redirect_stdout(io.StringIO()):
            self.assertIsNone(self.ricerca("no").cerca_online("q", lambda q: "ris"))
            self.assertIsNone(self.ricerca("APPROVO").cerca_online("q", esecutore=None))

    def test_cerca_online_approvato_con_esecutore(self):
        with redirect_stdout(io.StringIO()):
            risultato = self.ricerca("APPROVO").cerca_online("q", lambda q: f"ris:{q}")
        self.assertEqual(risultato, "ris:q")


class TestInputNumerici(unittest.TestCase):
    """chiedi_int/chiedi_float cercano input nel modulo, quindi qui basta
    patchare builtins.input (a differenza del prompt del gate)."""

    def test_chiedi_int_riprova_su_lettere_e_usa_default(self):
        with mock.patch("builtins.input", side_effect=["abc", "3"]), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(ag.chiedi_int("n: "), 3)
        with mock.patch("builtins.input", side_effect=[""]):
            self.assertEqual(ag.chiedi_int("n: ", default=7), 7)

    def test_chiedi_float_accetta_virgola(self):
        with mock.patch("builtins.input", side_effect=["x,y", "85,5"]), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(ag.chiedi_float("f: "), 85.5)


class TestSMTP(unittest.TestCase):

    def test_repr_credenziali_non_espone_password(self):
        cred = ag.CredenzialiSMTP(utente="u@x.it", password="segretissima")
        self.assertNotIn("segretissima", repr(cred))

    def test_credenziali_da_variabili_ambiente(self):
        env = {"GMAIL_USER": "u@x.it", "GMAIL_APP_PASSWORD": "p" * 16}
        with mock.patch.dict(os.environ, env):
            cred = ag.carica_credenziali_smtp({})
        self.assertEqual(cred.utente, "u@x.it")
        self.assertEqual(cred.porta, 465)

    def test_credenziali_mancanti_errore_senza_segreti(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                ag.carica_credenziali_smtp({})

    def test_esecutore_smtp_rifiuta_bozze_non_email(self):
        esecutore = ag.crea_esecutore_smtp(
            ag.CredenzialiSMTP(utente="u@x.it", password="x"))
        with self.assertRaises(ValueError):
            esecutore(ag.Bozza("social", "instagram", "o", "c"))
        # ValueError scatta PRIMA di qualsiasi connessione: nessuna rete usata.


class FonteFinta(ag.IFonteRicerca):
    """Fonte senza rete per i test del motore globale."""
    intervallo_minimo = 0.0

    def __init__(self, nome, risultati_per_citta):
        self.nome = nome
        self.risultati_per_citta = risultati_per_citta

    def cerca(self, query, mercato=None, lingua=""):
        return self.risultati_per_citta.get(mercato.citta, [])


class TestQueryExpander(unittest.TestCase):

    def test_cinque_varianti_localizzate_con_keyword_locale(self):
        expander = ag.QueryExpander()
        varianti_mi = expander.espandi(ag.mercato_da_catalogo("Milano"))
        varianti_ny = expander.espandi(ag.mercato_da_catalogo("New York"))
        self.assertEqual(len(varianti_mi), 5)
        self.assertEqual(len(varianti_ny), 5)
        self.assertTrue(all("Milano" in v for v in varianti_mi))
        self.assertTrue(any("affitto breve" in v for v in varianti_mi))
        self.assertTrue(any("short term rental" in v for v in varianti_ny))
        self.assertIn("Airbnb alternative New York", varianti_ny)

    def test_lingua_sconosciuta_usa_inglese_e_budget_in_valuta(self):
        mercato = ag.MercatoTarget(citta="Tokyo", lingua="ja", paese="JP",
                                   valuta="JPY", budget_max_notte=9000)
        varianti = ag.QueryExpander().espandi(mercato)
        self.assertTrue(any("short term rental" in v for v in varianti))
        self.assertTrue(all("max 9000 JPY" in v for v in varianti))

    def test_catalogo_assegna_paese_lingua_valuta(self):
        parigi = ag.mercato_da_catalogo("Parigi", budget_max_notte=100)
        self.assertEqual((parigi.paese, parigi.lingua, parigi.valuta),
                         ("FR", "fr", "EUR"))
        ignota = ag.mercato_da_catalogo("Paperopoli")
        self.assertEqual(ignota.lingua, "it")  # default generici


class TestMotoreGlobale(BaseTemp):
    """Flusso multi-mercato/multi-fonte completo, senza rete."""

    def setUp(self):
        super().setUp()
        self.db = ag.DatabaseCandidati(os.path.join(self.tmp, "db.sqlite3"))
        self.gestore = ag.GestoreCampagne(
            self.db.db_path, os.path.join(self.tmp, "campagne.json"),
            self.gate_con_risposte("APPROVO"), self.audit)
        mercati = [ag.mercato_da_catalogo("Milano", budget_max_notte=100),
                   ag.mercato_da_catalogo("Parigi"),
                   ag.mercato_da_catalogo("New York")]
        campagna = ag.CampagnaRicerca(nome="GlobalTest", mercati=mercati,
                                      max_richieste_giorno=100,
                                      pausa_secondi=0.0)
        with redirect_stdout(io.StringIO()):
            self.assertTrue(self.gestore.crea_campagna(campagna))

    def motore(self, fonti):
        return ag.MotoreRicerca(self.gestore, self.db, fonti, self.audit,
                                sleep=lambda s: None)

    def test_ciclo_globale_paesi_diversi_e_punteggio_combinato(self):
        risultati = {
            "Milano": [{"titolo": "Apt Milano 75 €", "url": "http://x/mi1",
                        "descrizione": "bilocale centro Milano"}],
            "Parigi": [{"titolo": "Appartement 90 EUR", "url": "http://x/pa1",
                        "descrizione": "Paris Marais"}],
            "New York": [{"titolo": "$120 apartment", "url": "http://x/ny1",
                          "descrizione": "Manhattan studio"}],
        }
        alpha = FonteFinta("alpha", risultati)
        beta = FonteFinta("beta", {"Milano": risultati["Milano"]})
        riepilogo = self.motore([alpha, beta]).esegui("GlobalTest")

        self.assertTrue(riepilogo["eseguito"])
        self.assertEqual(riepilogo["archiviati"], 3)
        # Candidati da almeno 2 paesi diversi (qui 3: IT, FR, US)
        self.assertGreaterEqual(len(riepilogo["archiviati_per_paese"]), 2)
        self.assertEqual(riepilogo["archiviati_per_paese"],
                         {"IT": 1, "FR": 1, "US": 1})
        # Punteggio combinato: mi1 visto da entrambe le fonti
        top = self.db.top_opportunita(5)
        milano = next(c for c in top if c["url"] == "http://x/mi1")
        self.assertEqual(milano["fonte"], "alpha+beta")
        self.assertAlmostEqual(milano["punteggio"], 1.0)  # 0.4+0.3+0.3 -> +0.1, tetto 1.0
        self.assertEqual(milano["prezzo"], 75.0)

    def test_report_globale_e_csv(self):
        fonte = FonteFinta("alpha", {
            "Milano": [{"titolo": "Apt 75 €", "url": "http://x/mi1",
                        "descrizione": "Milano centro"}],
            "New York": [{"titolo": "$120 apt", "url": "http://x/ny1",
                          "descrizione": "New York studio"}],
        })
        self.motore([fonte]).esegui("GlobalTest")
        report = self.db.report_globale()
        self.assertEqual(report["totale_candidati"], 2)
        self.assertEqual(report["paesi"]["IT"]["candidati"], 1)
        self.assertIn("Milano", report["paesi"]["IT"]["mercati"])
        percorso_csv = os.path.join(self.tmp, "export.csv")
        self.assertEqual(self.db.esporta_csv(percorso_csv), 2)
        with open(percorso_csv, encoding="utf-8-sig") as f:
            righe = f.read().splitlines()
        self.assertEqual(len(righe), 3)  # intestazione + 2 candidati
        self.assertTrue(righe[0].startswith("url;titolo;"))

    def test_limite_richieste_vale_anche_in_parallelo(self):
        fonte = FonteFinta("alpha", {})
        con_limite = ag.CampagnaRicerca(
            nome="Limitata", mercati=[ag.mercato_da_catalogo("Milano"),
                                      ag.mercato_da_catalogo("Parigi")],
            max_richieste_giorno=3, pausa_secondi=0.0)
        gestore = ag.GestoreCampagne(
            self.db.db_path, os.path.join(self.tmp, "x.json"),
            self.gate_con_risposte("APPROVO"), self.audit)
        with redirect_stdout(io.StringIO()):
            gestore.crea_campagna(con_limite)
        motore = ag.MotoreRicerca(gestore, self.db, [fonte], self.audit,
                                  sleep=lambda s: None)
        riepilogo = motore.esegui("Limitata")
        # 2 mercati x 5 varianti = 10 potenziali, ma il tetto e' 3
        self.assertEqual(riepilogo["richieste"], 3)
        self.assertIn("limite giornaliero", riepilogo["motivo"])

    def test_errore_di_rete_su_una_fonte_non_blocca_le_altre(self):
        class FonteRotta(ag.IFonteRicerca):
            nome = "rotta"
            intervallo_minimo = 0.0
            def cerca(self, query, mercato=None, lingua=""):
                raise OSError("rete giu'")
        sana = FonteFinta("sana", {"Milano": [
            {"titolo": "Apt 75 €", "url": "http://x/mi1",
             "descrizione": "Milano"}]})
        riepilogo = self.motore([FonteRotta(), sana]).esegui("GlobalTest")
        self.assertTrue(riepilogo["eseguito"])
        self.assertEqual(riepilogo["archiviati"], 1)
        self.assertGreater(riepilogo["errori_fonti"], 0)


class TestOrchestratore(BaseTemp):

    def test_avvio_crea_componenti_e_audit_in_cartella_temporanea(self):
        with redirect_stdout(io.StringIO()):
            assistente = ag.AssistenteGestionale(config=self.config)
        self.assertTrue(os.path.exists(self.config["percorsi"]["file_log_audit"]))
        eventi = self.eventi_audit()
        self.assertEqual(eventi[-1]["evento"], "avvio")
        self.assertEqual(assistente.ricerca.percorso_file,
                         self.config["percorsi"]["file_candidati"])


class TestMotorePacchetti(unittest.TestCase):
    """Motore di composizione 'Pacchetto Pronto' (V5): DB pacchetti separato,
    4 DB verticali in sola lettura, tutto in cartelle temporanee."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = self._tmp.name
        self.audit = ag.AuditLog(os.path.join(tmp, "audit.jsonl"))
        self.gestori = {
            cat: ag.GestoreRisorseVerticali(
                os.path.join(tmp, f"db_{cat}.sqlite3"), self.audit)
            for cat in ag.RISORSA_VERTICALI}
        self.motore = ag.MotoreComposizionePacchetti(
            self.audit, os.path.join(tmp, "pacchetti.sqlite3"), self.gestori)

    def tearDown(self):
        self._tmp.cleanup()

    def _risorsa(self, categoria, nome, area, prezzo, extra=None):
        meta = {"prezzo_giorno": prezzo}
        if extra:
            meta.update(extra)
        with redirect_stdout(io.StringIO()):
            rid = self.gestori[categoria].inserisci(nome, "contatto", area, meta)
            self.gestori[categoria].approva(rid, "test")
        return rid

    def _scadi(self, pacchetto_id):
        """Forza la scadenza nel passato (simula trascorrere delle 24h)."""
        con = sqlite3.connect(self.motore.db_path)
        with con:
            con.execute("UPDATE pacchetti SET data_scadenza='2000-01-01T00:00:00' "
                        "WHERE id=?", (pacchetto_id,))
        con.close()

    def _pacchetto_completo(self, area="Como", prezzo=100):
        for cat in ag.RISORSA_VERTICALI:
            self._risorsa(cat, f"{cat}-1", area, prezzo)

    def test_composizione_pacchetto_ok(self):
        self._pacchetto_completo()
        res = self.motore.componi("Como", 2000, "2026-07-01", "2026-07-05")
        self.assertEqual(res["esito"], "ok")
        self.assertTrue(res["codice"].startswith("PAC-"))
        self.assertEqual(res["stato"], "in_attesa")
        self.assertEqual(len(res["risorse"]), 4)
        self.assertEqual(res["mancanti"], [])

    def test_composizione_budget_insufficiente(self):
        for cat in ag.RISORSA_VERTICALI:
            self._risorsa(cat, f"{cat}-1", "Como", 1000)
        # tetto = 400/4 = 100 < 1000 -> tutte le categorie mancanti
        res = self.motore.componi("Como", 400, "2026-07-01", "2026-07-05")
        self.assertNotEqual(res["esito"], "ok")
        self.assertEqual(sorted(res["mancanti"]), sorted(ag.RISORSA_VERTICALI))
        self.assertEqual(res["stato"], "in_composizione")

    def test_fallback_scadenza_24h(self):
        self._risorsa("immobili", "imm-cheap", "Como", 100)   # id 1 (scelto)
        self._risorsa("immobili", "imm-alt", "Como", 150)     # id 2 (alternativa)
        for cat in ("mezzi", "talento", "esperienze"):
            self._risorsa(cat, f"{cat}-1", "Como", 100)
        res = self.motore.componi("Como", 2000, "2026-07-01", "2026-07-05")
        self.assertEqual(res["risorse"]["immobili"], 1)
        pid = res["id"]
        self.motore.invia_richieste_partner(pid)
        self._scadi(pid)
        self.motore.verifica_scadenze()
        risorse = json.loads(self.motore.get_pacchetto(pid)["risorse_json"])
        self.assertEqual(risorse["immobili"], 2)  # passato all'alternativa

    def test_fallback_max_tentativi(self):
        # Una sola risorsa per categoria: nessuna alternativa possibile.
        self._pacchetto_completo()
        res = self.motore.componi("Como", 2000, "2026-07-01", "2026-07-05")
        pid = res["id"]
        self.motore.invia_richieste_partner(pid)
        for _ in range(3):
            self._scadi(pid)
            self.motore.verifica_scadenze()
        self.assertEqual(self.motore.get_pacchetto(pid)["stato"], "scaduto")

    def test_registra_risposta_confermata(self):
        self._pacchetto_completo()
        res = self.motore.componi("Como", 2000, "2026-07-01", "2026-07-05")
        pid = res["id"]
        self.motore.invia_richieste_partner(pid)
        for req in self.motore.get_richieste(pid):
            self.motore.registra_risposta_partner(req["id"], "confermata", "ok")
        self.assertEqual(self.motore.get_pacchetto(pid)["stato"], "confermato")

    def test_registra_risposta_rifiutata(self):
        self._risorsa("immobili", "imm-cheap", "Como", 100)   # id 1
        self._risorsa("immobili", "imm-alt", "Como", 150)     # id 2 (alternativa)
        for cat in ("mezzi", "talento", "esperienze"):
            self._risorsa(cat, f"{cat}-1", "Como", 100)
        res = self.motore.componi("Como", 2000, "2026-07-01", "2026-07-05")
        pid = res["id"]
        self.motore.invia_richieste_partner(pid)
        imm = next(r for r in self.motore.get_richieste(pid)
                   if r["risorsa_db"] == "immobili")
        self.assertTrue(self.motore.registra_risposta_partner(
            imm["id"], "rifiutata", "non disponibile"))
        risorse = json.loads(self.motore.get_pacchetto(pid)["risorse_json"])
        self.assertEqual(risorse["immobili"], 2)  # fallback all'alternativa
        nuove = [r for r in self.motore.get_richieste(pid)
                 if r["risorsa_db"] == "immobili" and r["risorsa_id"] == 2
                 and r["stato"] == "inviata"]
        self.assertEqual(len(nuove), 1)


class TestGeneratoreProposta(unittest.TestCase):
    """Generatore di proposte commerciali (V6): scrive .md sotto una BASE_DIR
    temporanea, legge pacchetti e DB verticali in sola lettura."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.audit = ag.AuditLog(os.path.join(self.tmp, "audit.jsonl"))
        self.gestori = {
            cat: ag.GestoreRisorseVerticali(
                os.path.join(self.tmp, f"db_{cat}.sqlite3"), self.audit)
            for cat in ag.RISORSA_VERTICALI}
        self.motore = ag.MotoreComposizionePacchetti(
            self.audit, os.path.join(self.tmp, "pacchetti.sqlite3"), self.gestori)
        self.gen = ag.GeneratorePropostaCommerciale(
            self.audit, self.tmp, self.motore, self.gestori)

    def tearDown(self):
        self._tmp.cleanup()

    def _pacchetto_confermato(self, destinazione="Como", prezzo=100):
        with redirect_stdout(io.StringIO()):
            for cat in ag.RISORSA_VERTICALI:
                rid = self.gestori[cat].inserisci(
                    f"{cat}-{destinazione}", "contatto", destinazione,
                    {"prezzo_giorno": prezzo, "tipo": "premium"})
                self.gestori[cat].approva(rid, "test")
        res = self.motore.componi(destinazione, 4000, "2026-07-01", "2026-07-05")
        pid = res["id"]
        self.motore.invia_richieste_partner(pid)
        for req in self.motore.get_richieste(pid):
            self.motore.registra_risposta_partner(req["id"], "confermata", "ok")
        return pid

    def test_genera_proposta_ok(self):
        pid = self._pacchetto_confermato()
        esito = self.gen.genera(pid)
        self.assertTrue(os.path.exists(esito["percorso"]))
        self.assertEqual(esito["totale"], 400.0)
        self.assertEqual(esito["commissione"], 40.0)
        self.assertEqual(esito["totale_cliente"], 440.0)
        # Salvata sotto Proposte_Clienti/2026/07/
        self.assertIn(os.path.join("Proposte_Clienti", "2026", "07"),
                      esito["percorso"])

    def test_genera_proposta_non_confermato(self):
        # Pacchetto non confermato (solo composto)
        with redirect_stdout(io.StringIO()):
            for cat in ag.RISORSA_VERTICALI:
                rid = self.gestori[cat].inserisci(f"{cat}-1", "c", "Como",
                                                  {"prezzo_giorno": 100})
                self.gestori[cat].approva(rid, "test")
        res = self.motore.componi("Como", 4000, "2026-07-01", "2026-07-05")
        with self.assertRaises(ValueError):
            self.gen.genera(res["id"])

    def test_lista_proposte(self):
        p1 = self._pacchetto_confermato("Como")
        p2 = self._pacchetto_confermato("Roma")
        self.gen.genera(p1)
        self.gen.genera(p2)
        lista = self.gen.lista_proposte()
        self.assertEqual(len(lista), 2)
        # Ordine per data decrescente: la piu' recente (Roma) per prima.
        self.assertGreaterEqual(lista[0]["data"], lista[1]["data"])

    def test_lista_proposte_filtro(self):
        self.gen.genera(self._pacchetto_confermato("Como"))
        self.gen.genera(self._pacchetto_confermato("Roma"))
        solo_como = self.gen.lista_proposte("Como")
        self.assertEqual(len(solo_como), 1)
        self.assertEqual(solo_como[0]["destinazione"], "Como")

    def test_leggi_proposta(self):
        pid = self._pacchetto_confermato("Como")
        percorso = self.gen.genera(pid)["percorso"]
        contenuto = self.gen.leggi_proposta(percorso)
        self.assertIn("Proposta Commerciale Tavola Privé", contenuto)
        self.assertIn("Destinazione: Como", contenuto)
        self.assertIn("Totale Cliente", contenuto)


if __name__ == "__main__":
    unittest.main(verbosity=2)
