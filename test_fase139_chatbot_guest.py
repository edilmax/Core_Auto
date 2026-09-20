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


class TestLaRottaPubblicaDelConcierge(unittest.TestCase):
    """/api/chatbot (La Suite, 2026-09-19): il desk dell'albergo esposto ALLA PAGINA.
    Costruzione per-richiesta (it/en) sul SISTEMA VERO: catalogo e concierge di fase81,
    niente finti -- perche' la guardia deve vedere il cablaggio che usa l'ospite."""

    @classmethod
    def setUpClass(cls):
        import datetime
        import json
        import tempfile
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        from fase83_server import crea_router
        from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256
        cls.d = tempfile.mkdtemp(prefix="chatbot_rotta_")
        cfg = ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"C" * 32, con_registrazione_host=True,
            db_catalogo=cls.d + "/c.db", db_inventario=cls.d + "/i.db",
            db_registro_host=cls.d + "/r.db", db_accettazioni=cls.d + "/a.db",
            db_pendenti=cls.d + "/p.db", db_payout=cls.d + "/po.db",
            db_finanza=cls.d + "/f.db", db_garanzia=cls.d + "/g.db",
            db_tassa_comunale=cls.d + "/t.db", valuta="EUR")
        sistema = crea_sistema(cfg)
        cls.r = crea_router(sistema, host_key="hk", admin_key="ak")
        j = json.dumps

        def g(m, p, b=None, h=None):
            return cls.r.gestisci(m, p, {}, j(b) if b is not None else None, h or {})

        cls.g = staticmethod(g)
        s, c = g("POST", "/api/host/registrazione",
                 {"email": "host@chatrotta.it", "password": "password1",
                  "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
                  "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        if s != 201:
            raise AssertionError("registrazione: %s %r" % (s, c))
        tok = c["token"]
        s, c = g("POST", "/api/host/pubblica",
                 {"slug": "casa-chat", "titolo": "Casa Chat", "citta": "Roma", "paese": "IT",
                  "cin": "IT058091C2X5V0ABCD", "prezzo_notte_cents": 12000, "capacita": 3},
                 {"X-Host-Token": tok})
        if s != 201:
            raise AssertionError("pubblica: %s %r" % (s, c))
        oggi = datetime.date.today()
        s, c = g("POST", "/api/host/disponibilita_range",
                 {"alloggio_id": "casa-chat", "da": oggi.isoformat(),
                  "a": (oggi + datetime.timedelta(days=90)).isoformat(),
                  "unita_totali": 2, "prezzo_netto_cents": 12000},
                 {"X-Host-Token": tok})
        if s != 200:
            raise AssertionError("disponibilita: %s %r" % (s, c))

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.d, ignore_errors=True)

    def test_il_saluto_arriva_dalla_rotta(self):
        s, c = self.g("POST", "/api/chatbot", {"testo": "ciao!", "lang": "it"})
        self.assertEqual(200, s, c)
        self.assertTrue(c.get("risposta"), "concierge muto sul saluto: %r" % (c,))
        self.assertEqual("saluto", c.get("intento"))

    def test_senza_testo_la_reception_dice_422(self):
        s, c = self.g("POST", "/api/chatbot", {"testo": "   "})
        self.assertEqual(422, s)
        self.assertEqual("testo_mancante", c.get("errore"))

    def test_il_monologo_viene_cappato_non_rifiutato(self):
        s, c = self.g("POST", "/api/chatbot", {"testo": "a" * 5000 + " quanto costa?"})
        self.assertEqual(200, s, "un ospite prolisso si legge, non si manda via: %r" % (c,))
        self.assertTrue(c.get("risposta"))

    def test_lo_slug_contesto_porta_la_risposta_giusta(self):
        import datetime
        oggi = datetime.date.today()
        ci = (oggi + datetime.timedelta(days=7)).isoformat()
        co = (oggi + datetime.timedelta(days=9)).isoformat()
        s, c = self.g("POST", "/api/chatbot",
                      {"testo": "quanto costa?", "slug": "casa-chat", "lang": "it",
                       "check_in": ci, "check_out": co})
        self.assertEqual(200, s, c)
        self.assertEqual("prezzo", c.get("intento"))
        # 2 notti x 120,00 = totale 240,00: il numero VERO dell'annuncio, e la frase
        # di fiducia ("preventivo firmato") che la Home promette nel badge
        self.assertIn("240", str(c.get("risposta")),
                      "il concierge non dice il totale vero (2 notti x 120): %r" % (c,))
        self.assertIn("firmato", str(c.get("risposta")),
                      "manca la promessa di fiducia del badge: %r" % (c,))

    def test_la_reception_non_si_lascia_intasare(self):
        # il buttafuori per IP (fase179): dopo la soglia, 429 -- lo stesso trattamento
        # delle chiavi, perche' anche il desk e' una porta
        s, c = 0, {}
        for _ in range(10):
            s, c = self.g("POST", "/api/chatbot", {"testo": "ciao"},
                          h={"X-Forwarded-For": "203.0.113.77"})
        self.assertEqual(429, s,
                         "il concierge e' rimasto aperto a raffica: %r" % (c,))


if __name__ == "__main__":
    unittest.main()
