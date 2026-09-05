"""
Test fase152 - notifiche prenotazione all'HOST. Modulo (compose localizzato, canali email +
WhatsApp gated, dispatcher isolato) + E2E reale: registro host -> pubblica -> ospite prenota
-> l'HOST riceve l'avviso (oltre all'email voucher dell'ospite). Test estremi: canale che
esplode NON blocca gli altri, contatto mancante saltato, gating, localizzazione.
"""
import json
import shutil
import tempfile
import unittest

from fase61_localizzazione import Localizzatore
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase152_notifiche_prenotazione import (CanaleLine, CanaleTelegram, CanaleWeChat,
                                            CanaleWhatsApp, NotificatorePrenotazione,
                                            componi_avviso_host,
                                            crea_notificatore_prenotazione)


class TestCanaliAsia(unittest.TestCase):
    def test_line_notify_invia(self):
        visti = {}
        def fake(url, headers, data):
            visti.update(url=url, headers=headers, data=data); return 200, "ok"
        c = CanaleLine(fetch=fake)
        self.assertEqual(c.campo_contatto, "line_token")
        self.assertTrue(c.invia("TOK123", "ogg", "ciao"))
        self.assertIn("Bearer TOK123", visti["headers"]["Authorization"])
        self.assertFalse(c.invia("", "o", "t"))                 # niente token -> no

    def test_wechat_webhook_invia(self):
        visti = {}
        c = CanaleWeChat(fetch=lambda u, h, b: visti.update(u=u, b=b) or (200, "ok"))
        self.assertEqual(c.campo_contatto, "wechat_webhook")
        self.assertTrue(c.invia("https://qyapi.weixin.qq.com/x", "ogg", "ciao"))
        self.assertEqual(visti["b"]["msgtype"], "text")
        self.assertFalse(c.invia("non-un-url", "o", "t"))       # non http -> no

    def test_dispatcher_instrada_su_line(self):
        inviati = []
        line = CanaleLine(fetch=lambda u, h, d: inviati.append(d) or (200, "ok"))
        n = NotificatorePrenotazione([line])
        rep = n.avvisa({"line_token": "TK", "email": "h@x.it"}, "o", "t")
        self.assertEqual(rep["inviati"], 1)                     # usa line_token, non email
        self.assertTrue(inviati)

    def test_factory_include_canali_asia(self):
        n = crea_notificatore_prenotazione(email_provider=None)
        self.assertTrue(n.attivo())                             # LINE+WeChat sempre presenti

SEG = b"n" * 32
HK = {"X-Host-Key": "hk"}


class CaptureEmail:
    def __init__(self):
        self.inviate = []

    def invia(self, dest, oggetto, corpo_html):
        self.inviate.append((dest, oggetto, corpo_html))
        return True


class CanaleEsplode:
    campo_contatto = "email"

    def invia(self, dest, oggetto, testo):
        raise RuntimeError("canale rotto")


# ───────────────────────────── modulo ─────────────────────────────
class TestComposizione(unittest.TestCase):
    def test_localizzato_it_en_con_conferma(self):
        loc = Localizzatore()
        og_it, c_it = componi_avviso_host(loc, alloggio="Casa", ci="2026-07-10",
                                          co="2026-07-12", riferimento="R1",
                                          link_pannello="https://bookinvip.com/host.html",
                                          lingua="it")
        self.assertIn("Casa", c_it)
        self.assertIn("CONFERMATA", c_it)                 # nessuna azione richiesta
        self.assertIn("R1", c_it)
        self.assertIn("host.html", c_it)
        _, c_en = componi_avviso_host(loc, alloggio="Casa", ci="2026-07-10",
                                      co="2026-07-12", lingua="en")
        self.assertNotEqual(c_it.split("\n")[0], c_en.split("\n")[0])   # testo diverso per lingua

    def test_con_un_calendario_esterno_collegato_l_avviso_chiede_di_bloccare_le_date(self):
        # fase203 (2026-09-05): il lato dell'OTA lo chiude la mano dell'host, e l'avviso
        # glielo dice chiaro; senza calendari esterni resta «nessuna azione richiesta».
        loc = Localizzatore()
        og, corpo = componi_avviso_host(loc, alloggio="Casa", ci="2026-07-10", co="2026-07-12",
                                        calendari_esterni=1)
        self.assertIn("BLOCCA ORA", corpo)
        self.assertIn("BLOCCA", og)
        self.assertNotIn("nessuna azione richiesta", corpo)
        og0, corpo0 = componi_avviso_host(loc, alloggio="Casa", ci="2026-07-10",
                                          co="2026-07-12", calendari_esterni=0)
        self.assertIn("nessuna azione richiesta", corpo0)
        self.assertNotIn("BLOCCA", og0)


class TestCanaleWhatsApp(unittest.TestCase):
    def test_gating_e_invio_con_fetch_finto(self):
        visti = {}
        def fake(url, headers, body):
            visti["url"] = url; visti["body"] = body
            return 200, "ok"
        wa = CanaleWhatsApp("tok", "PH1", fetch=fake)
        self.assertTrue(wa.attivo())
        self.assertTrue(wa.invia("+39 333 1234567", "ogg", "ciao"))
        self.assertEqual(visti["body"]["to"], "393331234567")     # solo cifre
        self.assertIn("PH1/messages", visti["url"])

    def test_non_attivo_senza_credenziali(self):
        self.assertFalse(CanaleWhatsApp("", "").attivo())
        self.assertFalse(CanaleWhatsApp("", "").invia("+39333", "o", "t"))

    def test_fetch_esplode_isolato(self):
        def boom(*a):
            raise TimeoutError("giu'")
        self.assertFalse(CanaleWhatsApp("t", "p", fetch=boom).invia("+39333", "o", "t"))


class TestDispatcher(unittest.TestCase):
    def test_email_e_whatsapp_contatto_giusto(self):
        cap = CaptureEmail()
        sent_wa = {}
        wa = CanaleWhatsApp("t", "p", fetch=lambda u, h, b: sent_wa.update(b) or (200, "ok"))
        n = crea_notificatore_prenotazione(email_provider=cap,
                                           whatsapp_token="t", whatsapp_phone_id="p")
        # forzo il fetch del canale wa creato dalla factory: ricreo con canali_extra
        n = NotificatorePrenotazione([n._canali[0], wa])
        rep = n.avvisa({"email": "h@x.it", "telefono": "+39333"}, "ogg", "testo")
        self.assertEqual(rep["inviati"], 2)               # email + whatsapp
        self.assertEqual(cap.inviate[0][0], "h@x.it")
        self.assertEqual(sent_wa["to"], "39333")

    def test_canale_esplode_non_blocca_gli_altri(self):
        cap = CaptureEmail()
        n = NotificatorePrenotazione([CanaleEsplode(),
                                      crea_notificatore_prenotazione(email_provider=cap)._canali[0]])
        rep = n.avvisa({"email": "h@x.it"}, "o", "t")
        self.assertEqual(rep["falliti"], 1)               # quello rotto
        self.assertEqual(rep["inviati"], 1)               # l'email passa lo stesso
        self.assertEqual(len(cap.inviate), 1)

    def test_contatto_mancante_saltato(self):
        cap = CaptureEmail()
        n = crea_notificatore_prenotazione(email_provider=cap)
        rep = n.avvisa({"telefono": "+39333"}, "o", "t")   # niente email
        self.assertEqual(rep, {"inviati": 0, "falliti": 0})
        self.assertEqual(cap.inviate, [])

    def test_factory_attivo(self):
        self.assertTrue(crea_notificatore_prenotazione(email_provider=CaptureEmail()).attivo())
        self.assertTrue(crea_notificatore_prenotazione().attivo())   # LINE+WeChat sempre presenti


# ───────────────────────────── E2E reale ─────────────────────────────
class TestE2EHostAvvisato(unittest.TestCase):
    def test_prenotazione_avvisa_host_e_ospite(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db",
            db_messaggi=f"{d}/m.db", file_referral=f"{d}/ref.json", commissione_bps=1500))
        cap = CaptureEmail()
        sis.email_provider = cap                                    # ospite (voucher)
        sis.notificatore_prenotazione = crea_notificatore_prenotazione(email_provider=cap)  # host
        r = crea_router(sis, host_key="hk", base_url="https://bookinvip.com")

        def g(m, p, body=None, h=None, q=None):
            return r.gestisci(m, p, q or {},
                              json.dumps(body) if body is not None else None, h or {})

        # host REGISTRATO (cosi' info_host(host_id) trova email+telefono)
        s, c = g("POST", "/api/host/registrazione",
                 {"email": "host@b.it", "password": "passw0rd!", "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True, "lang": "it",
                  "telefono": "+39 333 9999999"})
        self.assertEqual(s, 201)
        hid = c["host_id"]
        g("POST", "/api/host/pubblica",
          {"host_id": hid, "slug": "casa", "titolo": "Casa Mia", "citta": "Roma",
           "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
           "servizi": [], "immagini": []}, HK)
        g("POST", "/api/host/disponibilita_range",
          {"alloggio_id": "casa", "da": "2026-07-01", "a": "2026-07-31",
           "unita_totali": 1, "prezzo_netto_cents": 10000}, HK)
        _, q = g("POST", "/api/concierge/quote",
                 {"alloggio_id": "casa", "check_in": "2026-07-10", "check_out": "2026-07-12",
                  "party": 1})
        s, b = g("POST", "/api/concierge/book",
                 {"quote_token": q["quote_token"], "email": "ospite@x.it"})
        self.assertEqual(s, 201)
        dest = [e[0] for e in cap.inviate]
        self.assertIn("ospite@x.it", dest)                          # ospite avvisato (voucher)
        self.assertIn("host@b.it", dest)                            # HOST avvisato (nuovo!)
        # l'avviso host contiene i dati prenotazione. NB: da C2 (2026-07-20) alla
        # REGISTRAZIONE parte anche l'email di BENVENUTO -> l'avviso prenotazione
        # non e' piu' necessariamente la PRIMA email all'host: si cerca tra tutte.
        host_mails = [e for e in cap.inviate if e[0] == "host@b.it"]
        self.assertTrue(any("Casa Mia" in e[2] for e in host_mails),
                        "avviso prenotazione all'host mancante; oggetti: %r"
                        % [e[1] for e in host_mails])
        self.assertTrue(any("Benvenuto" in e[2] for e in host_mails),
                        "email di benvenuto (C2) mancante alla registrazione")


class TestLeGuardieDeiPuntiScoperti(unittest.TestCase):
    """Una guardia per ogni punto che il Giudice della mutazione ha trovato SCOPERTO col
    solo occhio dedicato (2026-09-05, Blocco 2 casella 4: 17 punti su 32)."""

    @staticmethod
    def _spia(esito=(200, "ok")):
        chiamate = []

        def fake(url, headers, body):
            chiamate.append((url, headers, body))
            return esito
        return chiamate, fake

    def test_whatsapp_e_attivo_solo_con_token_E_numero(self):
        # riga 55: `token AND phone_id`.
        self.assertFalse(CanaleWhatsApp("tok", "").attivo())
        self.assertFalse(CanaleWhatsApp("", "PH").attivo())
        self.assertTrue(CanaleWhatsApp("tok", "PH").attivo())

    def test_whatsapp_e_telegram_senza_destinatario_non_chiamano_la_rete(self):
        # righe 58 e 137-138: senza destinatario si dice no PRIMA di toccare la rete.
        chiamate, fake = self._spia()
        self.assertFalse(CanaleWhatsApp("tok", "PH", fetch=fake).invia("", "o", "t"))
        self.assertFalse(CanaleTelegram("tok", fetch=fake).invia("", "o", "t"))
        self.assertEqual(chiamate, [])

    def test_ogni_canale_che_esplode_dice_no_e_lascia_la_traccia(self):
        # righe 69, 99-100, 120-121, 147-148: la rete che esplode -> False, e l'avviso
        # porta LA COSA, del tipo giusto (una tupla con l'eccezione vera).
        def boom(*a):
            raise TimeoutError("giu'")
        casi = ((CanaleWhatsApp("t", "p", fetch=boom), "+39333"),
                (CanaleLine(fetch=boom), "TOK"),
                (CanaleWeChat(fetch=boom), "https://x"),
                (CanaleTelegram("t", fetch=boom), "123"))
        for canale, destinatario in casi:
            with self.subTest(canale=type(canale).__name__):
                with self.assertLogs("fase152_notifiche_prenotazione",
                                     level="WARNING") as registro:
                    self.assertFalse(canale.invia(destinatario, "o", "t"))
                traccia = registro.records[0].exc_info
                self.assertIsInstance(traccia, tuple)
                self.assertIs(traccia[0], TimeoutError)

    def test_telegram_tiene_il_token_usa_la_rete_iniettata_e_spegne_le_anteprime(self):
        # righe 130 (`bot_token or ""`), 131 (`fetch or _fetch_post`), 144 (anteprime spente).
        chiamate, fake = self._spia()
        tg = CanaleTelegram("tok", fetch=fake)
        self.assertTrue(tg.attivo())
        self.assertTrue(tg.invia("123", "o", "t"))
        self.assertEqual(len(chiamate), 1)
        self.assertIn("bottok/", chiamate[0][0])
        self.assertIs(chiamate[0][2]["disable_web_page_preview"], True)

    def test_un_canale_che_esplode_nel_dispatcher_lascia_la_traccia(self):
        # riga 174.
        n = NotificatorePrenotazione([CanaleEsplode()])
        with self.assertLogs("fase152_notifiche_prenotazione", level="WARNING") as registro:
            rep = n.avvisa({"email": "h@x.it"}, "o", "t")
        self.assertEqual(rep, {"inviati": 0, "falliti": 1})
        traccia = registro.records[0].exc_info
        self.assertIsInstance(traccia, tuple)
        self.assertIs(traccia[0], RuntimeError)

    def test_l_origine_vuota_diventa_un_trattino_e_quella_piena_resta(self):
        # riga 185: `origine or "—"`.
        visti = []

        class Loc:
            def notifica(self, chiave, lingua, **kw):
                visti.append(kw)
                return "testo"
        componi_avviso_host(Loc(), alloggio="Casa", ci="2026-07-10", co="2026-07-12",
                            origine="")
        componi_avviso_host(Loc(), alloggio="Casa", ci="2026-07-10", co="2026-07-12",
                            origine="web")
        self.assertEqual([v["origine"] for v in visti], ["—", "web"])

    def test_i_canali_extra_validi_entrano_e_i_None_no(self):
        # riga 220: `c is not None`.
        chiamate, fake = self._spia()
        extra = CanaleLine(fetch=fake)
        n = crea_notificatore_prenotazione(canali_extra=[None, extra])
        self.assertIn(extra, n._canali)
        self.assertNotIn(None, n._canali)


if __name__ == "__main__":
    unittest.main()
