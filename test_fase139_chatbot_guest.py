"""Test Fase 139 - Chatbot guest. Provider e LLM iniettati: nessuna rete."""
import unittest

from fase139_chatbot_guest import classifica_intento, crea_chatbot_guest


class CatFinto:
    def dettaglio(self, slug):
        return {"citta": "Roma", "servizi": ["wifi", "pet"], "capacita": 4}


class Resp:
    def __init__(self, status, corpo):
        self.status = status
        self.corpo = corpo


class ConFinto:
    def quota(self, r):
        if r["check_in"] == "2026-08-01":
            return Resp(200, {"prezzo_guest_cents": 11200, "valuta": "EUR",
                              "quote_token": "tok.a.b"})
        return Resp(409, {"errore": "non_disponibile"})


class TestIntento(unittest.TestCase):
    def test_classifica(self):
        self.assertEqual(classifica_intento("quanto costa?"), "prezzo")
        self.assertEqual(classifica_intento("c'è il wifi?"), "servizi")
        self.assertEqual(classifica_intento("dove si trova"), "posizione")
        self.assertEqual(classifica_intento("blabla random"), "fallback")
        self.assertEqual(classifica_intento(""), "fallback")


class TestChatbot(unittest.TestCase):
    def setUp(self):
        self.b = crea_chatbot_guest(CatFinto(), ConFinto())

    def test_prezzo_dal_core(self):
        r = self.b.rispondi("casa-1", "quanto costa?",
                            contesto={"check_in": "2026-08-01", "check_out": "2026-08-03"})
        self.assertEqual(r["fonte"], "concierge")
        self.assertEqual(r["prezzo_guest_cents"], 11200)
        self.assertIn("112.00", r["risposta"])
        self.assertEqual(r["quote_token"], "tok.a.b")

    def test_prezzo_senza_date_chiede(self):
        r = self.b.rispondi("casa-1", "prezzo?")
        self.assertEqual(r["fonte"], "richiesta_dati")

    def test_disponibilita(self):
        ok = self.b.rispondi("casa-1", "è disponibile?",
                             contesto={"check_in": "2026-08-01", "check_out": "2026-08-03"})
        self.assertIn("Disponibile", ok["risposta"])
        ko = self.b.rispondi("casa-1", "disponibile?",
                             contesto={"check_in": "2026-12-01", "check_out": "2026-12-03"})
        self.assertIn("Non disponibile", ko["risposta"])

    def test_servizi_e_posizione_dal_catalogo(self):
        self.assertIn("wifi", self.b.rispondi("casa-1", "che servizi?")["risposta"])
        self.assertIn("Roma", self.b.rispondi("casa-1", "dove si trova?")["risposta"])

    def test_animali_da_servizi(self):
        self.assertIn("ammessi", self.b.rispondi("casa-1", "posso portare il cane?")["risposta"])

    def test_fallback_usa_llm_se_presente(self):
        b = crea_chatbot_guest(CatFinto(), ConFinto(), llm=lambda t: "Risposta LLM")
        self.assertEqual(b.rispondi("c", "domanda strana xyz")["fonte"], "llm")

    def test_fallback_canned_senza_llm(self):
        self.assertEqual(self.b.rispondi("c", "domanda strana xyz")["fonte"], "canned")

    def test_money_guard_llm_non_tocca_prezzo(self):
        # anche con LLM, il prezzo resta dal concierge (fonte=concierge), non dall'LLM
        b = crea_chatbot_guest(CatFinto(), ConFinto(), llm=lambda t: "€9999 inventato")
        r = b.rispondi("casa-1", "quanto costa?",
                       contesto={"check_in": "2026-08-01", "check_out": "2026-08-03"})
        self.assertEqual(r["fonte"], "concierge")
        self.assertEqual(r["prezzo_guest_cents"], 11200)


if __name__ == "__main__":
    unittest.main()
