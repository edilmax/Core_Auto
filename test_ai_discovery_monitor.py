"""Guardie dell'AI DISCOVERY MONITOR (collaudi/ai_discovery_monitor.py).

Ordine del fondatore 2026-09-24 (coda punto 2). Le guardie girano SENZA rete:
il motore e' finto, la salute del sito e' finta. Due direzioni (regola ferrea 10):
la risposta che nomina bookinvip si vede, e quella che non lo nomina non viene
dichiarata trovata. La chiave finta non compare MAI nell'output ne' nel rapporto
(ferrea 14). Senza configurazione l'esame e' NON ESEGUITO e esce 1, mai un verde
silenzioso (sbaglio S7).
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collaudi import ai_discovery_monitor as ADM  # noqa: E402

CHIAVE_FINTA = "sk-finto-abc123def456"
ENV_COMPLETO = {"DISCOVERY_AI_URL": "https://motore.finto/v1",
                "DISCOVERY_AI_KEY": CHIAVE_FINTA,
                "DISCOVERY_AI_MODEL": "modello-finto"}

RISPOSTA_CON_NOI = ("Per le vacanze a Roma ti consiglio bookinvip.com, che non "
                    "applica commissioni all'ospite; in alternativa Airbnb.")
RISPOSTA_CON_CORRENTE = ("I siti piu' noti sono booking.com e airbnb per gli "
                         "appartamenti a Roma.")
RISPOSTA_NEUTRA = ("Le case vacanza si prenotano su molte piattaforme online.")


def _salute_ok():
    return True, "http=200 (finta)"


def _salute_giu():
    return False, "http=503 (finta)"


class TestGiudicaRispostaDueDirezioni(unittest.TestCase):
    def test_la_risposta_che_nomina_bookinvip_e_vista(self):
        esito = ADM.giudica_risposta(RISPOSTA_CON_NOI)
        self.assertTrue(esito["trovato"])
        self.assertIsInstance(esito["posizione"], int)
        self.assertIn("bookinvip", esito["frase"].lower())

    def test_la_risposta_che_non_lo_nomina_non_e_dichiarata_trovata(self):
        esito = ADM.giudica_risposta(RISPOSTA_CON_CORRENTE)
        self.assertFalse(esito["trovato"])
        self.assertIsNone(esito["posizione"])
        self.assertEqual(esito["frase"], "")
        self.assertIn("booking.com", esito["competitor"])
        self.assertIn("airbnb", esito["competitor"])

    def test_risposta_vuota_o_non_testo_non_esplode(self):
        for vuoto in ("", None):
            esito = ADM.giudica_risposta(vuoto)
            self.assertFalse(esito["trovato"])
            self.assertIsNone(esito["posizione"])


class TestConfigurazione(unittest.TestCase):
    def test_config_completa_ritorna_le_tre_voci(self):
        config, motivo = ADM._config_da_ambiente(ENV_COMPLETO)
        self.assertIsNone(motivo)
        self.assertEqual(config["modello"], "modello-finto")
        self.assertEqual(config["url"], "https://motore.finto/v1")

    def test_senza_variabili_NON_ESEGUITO_uscita_1_e_zero_chiamate(self):
        chiamate = []

        def posta_che_non_deve_esser_chiamata(*a):
            chiamate.append(a)
            raise AssertionError("il motore non va interrogato senza config")

        uscite = []
        codice = ADM.main(argv=[], env={}, stampa=uscite.append,
                          posta=posta_che_non_deve_esser_chiamata,
                          salute=_salute_ok)
        self.assertEqual(codice, 1)
        self.assertTrue(any("NON ESEGUITO" in u for u in uscite))
        self.assertTrue(any("DISCOVERY_AI_KEY" in u for u in uscite))
        self.assertEqual(chiamate, [])


class TestGiroCompletoMotoreFinto(unittest.TestCase):
    def _posta_finta(self, alza=False):
        def posta(config, domanda, timeout):
            if alza:
                raise OSError("connessione caduta (finta)")
            if "appartamento Roma centro" in domanda:
                return RISPOSTA_CON_CORRENTE
            return RISPOSTA_CON_NOI if "Roma?" in domanda else RISPOSTA_NEUTRA
        return posta

    def test_giro_completo_due_direzioni_e_chiave_mai_scritta(self):
        cartella = tempfile.mkdtemp(prefix="discovery_test_")
        percorso = os.path.join(cartella, "rapporto.json")
        uscite = []
        codice = ADM.main(argv=["--report", percorso], env=dict(ENV_COMPLETO),
                          stampa=uscite.append, posta=self._posta_finta(),
                          salute=_salute_ok)
        self.assertEqual(codice, 0)
        with open(percorso, encoding="utf-8") as f:
            rapporto = json.load(f)
        self.assertEqual(rapporto["presenza"]["domande_totali"], len(ADM.DOMANDE))
        self.assertEqual(rapporto["presenza"]["risposte_ottenute"], len(ADM.DOMANDE))
        self.assertGreaterEqual(rapporto["presenza"]["con_bookinvip"], 1)
        self.assertIn("airbnb", rapporto["presenza"]["competitor_visti"])
        self.assertIn("booking.com", rapporto["presenza"]["competitor_visti"])
        self.assertTrue(rapporto["limiti"])
        # ferrea 14: la chiave finta non finisce ne' nell'output ne' nel rapporto
        with open(percorso, encoding="utf-8") as f:
            testo_rapporto = f.read()
        tutto = "\n".join(uscite) + testo_rapporto
        self.assertNotIn(CHIAVE_FINTA, tutto)
        # il rapporto nomina il motore per host, non per chiave
        self.assertEqual(rapporto["motore"]["host"], "motore.finto")

    def test_motore_muto_esce_1_e_lo_dichiara(self):
        cartella = tempfile.mkdtemp(prefix="discovery_test_")
        percorso = os.path.join(cartella, "rapporto.json")
        uscite = []
        codice = ADM.main(argv=["--report", percorso], env=dict(ENV_COMPLETO),
                          stampa=uscite.append, posta=self._posta_finta(alza=True),
                          salute=_salute_ok)
        self.assertEqual(codice, 1)
        self.assertTrue(any("NON ESEGUITO" in u for u in uscite))
        with open(percorso, encoding="utf-8") as f:
            rapporto = json.load(f)
        self.assertEqual(rapporto["presenza"]["risposte_ottenute"], 0)
        for riga in rapporto["domande"]:
            self.assertTrue(riga["errore"])

    def test_sito_giu_esce_1_prima_di_interrogare_il_motore(self):
        chiamate = []

        def posta(*a):
            chiamate.append(a)
            raise AssertionError("sito giu': il motore non va interrogato")

        uscite = []
        codice = ADM.main(argv=[], env=dict(ENV_COMPLETO), stampa=uscite.append,
                          posta=posta, salute=_salute_giu)
        self.assertEqual(codice, 1)
        self.assertTrue(any("NON ESEGUITO" in u for u in uscite))
        self.assertEqual(chiamate, [])


class TestIlSetDiDomande(unittest.TestCase):
    def test_il_set_non_e_vuoto_e_ogni_domanda_neanche(self):
        # una misura su insieme vuoto non e' una misura (sbaglio S1)
        self.assertGreaterEqual(len(ADM.DOMANDE), 1)
        for domanda in ADM.DOMANDE:
            self.assertTrue(domanda.strip())
        self.assertTrue(ADM.COMPETITOR)


if __name__ == "__main__":
    unittest.main()
