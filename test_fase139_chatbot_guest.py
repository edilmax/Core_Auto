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



class TestIlDeskDellaHome(unittest.TestCase):
    """LE TRE FAMIGLIE del desk della Home (La Suite): CERCA alloggi con la ricerca
    vera del catalogo, risponde sui GUADAGNI con i numeri veri di fase98, e sulla
    FIDUCIA citando le macchine reali. Senza slug: e' la Home."""

    @classmethod
    def setUpClass(cls):
        import datetime
        import json
        import tempfile
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        from fase83_server import crea_router
        from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256
        cls.d = tempfile.mkdtemp(prefix="desk_home_")
        cfg = ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"D" * 32, con_registrazione_host=True,
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
                 {"email": "host@desk.it", "password": "password1",
                  "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
                  "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        if s != 201:
            raise AssertionError("registrazione: %s %r" % (s, c))
        tok = c["token"]
        s, c = g("POST", "/api/host/pubblica",
                 {"slug": "loft-desk", "titolo": "Loft del Desk", "citta": "Roma",
                  "paese": "IT", "cin": "IT058091C2X5V0ABCD",
                  "prezzo_notte_cents": 9500, "capacita": 4},
                 {"X-Host-Token": tok})
        if s != 201:
            raise AssertionError("pubblica: %s %r" % (s, c))
        oggi = datetime.date.today()
        s, c = g("POST", "/api/host/disponibilita_range",
                 {"alloggio_id": "loft-desk", "da": oggi.isoformat(),
                  "a": (oggi + datetime.timedelta(days=120)).isoformat(),
                  "unita_totali": 2, "prezzo_netto_cents": 9500},
                 {"X-Host-Token": tok})
        if s != 200:
            raise AssertionError("disponibilita: %s %r" % (s, c))

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.d, ignore_errors=True)

    def test_il_desk_cerca_e_trova_con_prezzo(self):
        import datetime
        oggi = datetime.date.today()
        s, c = self.g("POST", "/api/chatbot",
                      {"testo": "trovami un alloggio", "citta": "Roma", "party": 2,
                       "check_in": (oggi + datetime.timedelta(days=7)).isoformat(),
                       "check_out": (oggi + datetime.timedelta(days=9)).isoformat(),
                       "lang": "it"})
        self.assertEqual(200, s, c)
        self.assertEqual("cerca", c.get("intento"))
        self.assertIn("Loft del Desk", str(c.get("risposta")),
                      "il desk non cita l'alloggio vero: %r" % (c,))
        lista = c.get("lista") or []
        self.assertTrue(any(e.get("slug") == "loft-desk" for e in lista),
                        "la lista cliccabile non contiene l'alloggio vero: %r" % (lista,))
        self.assertTrue(any("95" in str(e.get("prezzo")) for e in lista),
                        "manca il prezzo a notte: %r" % (lista,))

    def test_il_desk_risponde_all_host_con_i_numeri_veri(self):
        s, c = self.g("POST", "/api/chatbot",
                      {"testo": "sono un host, quante commissioni pago?", "lang": "it"})
        self.assertEqual(200, s, c)
        risposta = str(c.get("risposta"))
        self.assertIn("0%", risposta, "manca lo 0%% dei primi giorni: %r" % (risposta,))
        self.assertIn("94,75", risposta.replace(".", ",") if False else risposta.replace(".", ","),
                      "manca l'esempio vero su 100 EUR: %r" % (risposta,))

    def test_il_desk_risponde_sulla_fiducia_col_motore(self):
        s, c = self.g("POST", "/api/chatbot", {"testo": "posso fidarmi? e' sicuro?", "lang": "it"})
        self.assertEqual(200, s, c)
        risposta = str(c.get("risposta"))
        self.assertIn("GARANZIA", risposta, "manca l'escrow: %r" % (risposta,))
        self.assertIn("FIRMATO", risposta, "manca il prezzo firmato: %r" % (risposta,))
        self.assertIn("recensioni", risposta.lower(), "manca la promessa recensioni: %r" % (risposta,))

    def test_senza_citta_il_desk_chiede_e_non_inventa(self):
        s, c = self.g("POST", "/api/chatbot", {"testo": "trovami un alloggio", "lang": "it"})
        self.assertEqual(200, s, c)
        risposta = str(c.get("risposta"))
        self.assertIn("citta", risposta.lower(),
                      "il desk cerca senza citta' invece di chiederla: %r" % (risposta,))


    def test_il_desk_dice_chi_siamo(self):
        s, c = self.g("POST", "/api/chatbot",
                      {"testo": "chi siete? cosa e' Bookin VIP?", "lang": "it"})
        self.assertEqual(200, s, c)
        self.assertEqual("chisiamo", c.get("intento"), "intento sbagliato: %r" % (c,))
        self.assertIn("0%", str(c.get("risposta")),
                      "manca lo 0%% dell'ospite: %r" % (c,))

    def test_il_desk_spiega_come_funziona(self):
        s, c = self.g("POST", "/api/chatbot",
                      {"testo": "come funziona? come pago?", "lang": "it"})
        self.assertEqual(200, s, c)
        r = str(c.get("risposta"))
        self.assertIn("FIRMATO", r, "manca il prezzo firmato: %r" % (r,))
        self.assertIn("voucher", r.lower(), "manca il voucher col PIN: %r" % (r,))
        self.assertIn("GARANZIA", r, "manca l'escrow: %r" % (r,))

    def test_il_desk_contatto_non_inventa_email(self):
        s, c = self.g("POST", "/api/chatbot",
                      {"testo": "come vi contatto? mi serve assistenza", "lang": "it"})
        self.assertEqual(200, s, c)
        r = str(c.get("risposta"))
        self.assertEqual("contatto", c.get("intento"), "intento sbagliato: %r" % (c,))
        self.assertNotIn("@", r, "il desk ha inventato un indirizzo: %r" % (r,))

    def test_il_desk_spiega_la_tassa(self):
        s, c = self.g("POST", "/api/chatbot",
                      {"testo": "c'e' la tassa di soggiorno?", "lang": "it"})
        self.assertEqual(200, s, c)
        r = str(c.get("risposta"))
        self.assertEqual("tassa", c.get("intento"), "intento sbagliato: %r" % (c,))
        self.assertIn("totale", r.lower(), "la tassa non parla del totale vero: %r" % (r,))

    def test_il_desk_risponde_su_cancellazione_dalla_home(self):
        s, c = self.g("POST", "/api/chatbot",
                      {"testo": "se cancello, il rimborso?", "lang": "it"})
        self.assertEqual(200, s, c)
        r = str(c.get("risposta"))
        self.assertEqual("cancellazione", c.get("intento"), "intento sbagliato: %r" % (c,))
        self.assertIn("checkout", r.lower(),
                      "la cancellazione non rimanda al checkout vero: %r" % (r,))


class TestIlMicrofonoNelPannelloChat(unittest.TestCase):
    """Il dittamo vocale anche nel PANNELLO della chat (2026-09-22, ordine del
    fondatore: stile WhatsApp). Guardia di SORGENTE su deploy/index.html: il tasto
    sta nel form della chat (fra l'input e Invia), SPARISCE dove il browser non
    sa dettare (niente bottoni finti), cio' che dettato finisce nell'input della
    chat, e il suo titolo e' tradotto in 8 lingue come tutto il resto della chat."""

    @classmethod
    def setUpClass(cls):
        import os
        cls.src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "deploy", "index.html"), encoding="utf-8").read()

    def test_il_tasto_sta_nel_form_fra_input_e_invia(self):
        i_input = self.src.index('id="cbInput"')
        i_voce = self.src.index('id="cbVoce"')
        i_manda = self.src.index('id="cbManda"')
        self.assertLess(i_input, i_voce,
                        "il microfono non sta dopo l'input della chat")
        self.assertLess(i_voce, i_manda,
                        "il microfono non sta prima del tasto Invia")

    def test_senza_web_speech_il_tasto_non_esiste(self):
        self.assertIn("document.getElementById('cbVoce')", self.src,
                      "il tasto non e' cablato col gestore letterale")
        self.assertIn("bv.style.display='none'", self.src,
                      "senza Web Speech API il tasto resta visibile: bottone finto")

    def test_la_dettatura_riempie_linput_della_chat(self):
        self.assertIn("inp.value=(inp.value?inp.value.trim()+' ':'')+d", self.src,
                      "la dettatura non scrive nell'input della chat")

    def test_il_titolo_del_tasto_e_tradotto_in_otto_lingue(self):
        from fase83_server import ETICHETTE_UI
        voci = ETICHETTE_UI.get("chat_voce_title", {})
        mancanti = [l for l in ("it", "en", "es", "fr", "de", "pt", "ja", "zh")
                    if not str(voci.get(l, "")).strip()]
        self.assertEqual([], mancanti, "lingue senza titolo del microfono: %r" % (mancanti,))

    def test_la_dettatura_morta_si_fa_vedere_in_chat(self):
        # 2026-09-22, fondatore in produzione: «clicco sul microfono ma non funziona».
        # Il permesso negato (misurato: onerror not-allowed) veniva ingoiato in
        # silenzio da r.onerror=r.onend: zero feedback per l'ospite.
        self.assertIn("voceAvvisa(", self.src,
                      "manca l'avviso visibile quando la dettatura muore")
        self.assertIn("chat_voce_no_perm", self.src,
                      "manca il messaggio per il microfono bloccato")
        self.assertNotIn("r.onerror=r.onend", self.src,
                         "la dettatura torna a ingoiare gli errori in silenzio")

    def test_gli_avvisi_della_dettatura_sono_in_otto_lingue(self):
        from fase83_server import ETICHETTE_UI
        for chiave in ("chat_voce_no", "chat_voce_no_perm"):
            voci = ETICHETTE_UI.get(chiave, {})
            mancanti = [l for l in ("it", "en", "es", "fr", "de", "pt", "ja", "zh")
                        if not str(voci.get(l, "")).strip()]
            self.assertEqual([], mancanti,
                             "%s senza lingue: %r" % (chiave, mancanti))


if __name__ == "__main__":
    unittest.main()
