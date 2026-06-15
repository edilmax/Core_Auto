"""
Test FASE 27 / BLOCCO 3.2 - Generatore di proposte commerciali.

Copre: commissione a precisione DECIMALE assoluta (centesimi esatti), rifinitura
IA opzionale che DEGRADA al template, ISOLAMENTO TOTALE (input invalido / IA
giu' -> nota di attesa, mai crash; numeri mai delegati all'IA) e la pipeline
ricerca-protetta -> offerta.
"""
import unittest
from decimal import Decimal

from fase27_proposte import (GeneratoreProposte, componi_offerta, NOTA_ATTESA,
                             COMMISSIONE_DEFAULT)
from fase26_ricerca import Proposta, RicercaStub, MotoreRicercaProtetto, CriteriRicerca
from fase25_brain import AgenteIA, StubLLMProvider


_PROP = [Proposta("Trullo", "Roma", 80.0, "u1", 9.0)]


class _AgenteFail(AgenteIA):
    def __init__(self):
        class _F(StubLLMProvider):
            def genera(self, p):
                raise RuntimeError("LLM down")
        super().__init__(_F())


class TestCommissioneEsatta(unittest.TestCase):

    def test_calcolo_centesimi(self):
        r = GeneratoreProposte().genera(_PROP)
        self.assertTrue(r.ok)
        v = r.voci[0]
        self.assertEqual((v.prezzo_cent, v.commissione_cent, v.totale_cliente_cent),
                         (8000, 800, 8800))

    def test_testo_contiene_importi(self):
        r = GeneratoreProposte().genera(_PROP)
        for s in ("80.00 EUR", "8.00 EUR", "88.00 EUR", "10%"):
            self.assertIn(s, r.testo)

    def test_commissione_personalizzata(self):
        r = GeneratoreProposte(commissione=Decimal("0.15")).genera(_PROP)
        self.assertEqual(r.voci[0].commissione_cent, 1200)   # 15% di 8000
        self.assertEqual(r.voci[0].totale_cliente_cent, 9200)

    def test_no_proposte(self):
        r = GeneratoreProposte().genera([])
        self.assertTrue(r.ok)
        self.assertIn("non ho proposte", r.testo.lower())


class TestRifinituraIA(unittest.TestCase):

    def test_intro_presente_se_ia_ok(self):
        ag = AgenteIA(StubLLMProvider(risposta="Gentile cliente,"))
        self.addCleanup(ag.stop)
        r = GeneratoreProposte(agente=ag).genera(_PROP)
        self.assertEqual(r.esito, "completa_ai")
        self.assertTrue(r.testo.startswith("Gentile cliente,"))
        self.assertIn("88.00 EUR", r.testo)  # numeri intatti

    def test_ia_giu_degrada_a_template(self):
        ag = _AgenteFail()
        self.addCleanup(ag.stop)
        r = GeneratoreProposte(agente=ag).genera(_PROP)
        self.assertTrue(r.ok)
        self.assertEqual(r.esito, "completa")   # niente intro, numeri esatti
        self.assertIn("88.00 EUR", r.testo)


class TestIsolamento(unittest.TestCase):

    def test_proposta_invalida_nota_attesa(self):
        class _Bad:
            titolo, localita, prezzo = "x", "y", "non-un-numero"
        r = GeneratoreProposte().genera([_Bad()])
        self.assertFalse(r.ok)
        self.assertEqual(r.esito, "fallback_attesa")
        self.assertEqual(r.testo, NOTA_ATTESA)
        self.assertEqual(r.voci, [])


class TestPipeline(unittest.TestCase):

    def test_ricerca_protetta_a_offerta(self):
        m = MotoreRicercaProtetto(RicercaStub(_PROP))
        r = componi_offerta(m, GeneratoreProposte(), CriteriRicerca("Roma"))
        self.assertTrue(r.ok)
        self.assertIn("Trullo", r.testo)
        self.assertIn("88.00 EUR", r.testo)

    def test_motore_giu_offerta_cortese(self):
        m = MotoreRicercaProtetto(RicercaStub(fail=True))
        r = componi_offerta(m, GeneratoreProposte(), CriteriRicerca("Roma"))
        self.assertTrue(r.ok)                       # nessun crash end-to-end
        self.assertIn("non ho proposte", r.testo.lower())


if __name__ == "__main__":
    unittest.main()
