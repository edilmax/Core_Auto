"""
Test collegamento Telegram per-host + canale notifica.
L'host genera un link (/api/host/telegram_link), lo apre e preme Start -> il webhook Telegram
salva il suo chat_id -> gli avvisi di prenotazione (coi tasti Approva/Rifiuta) arrivano su
Telegram. Copre: link+webhook, codice scaduto/ignoto, segreto webhook, canale CanaleTelegram.
"""
import json
import os
import shutil
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase152_notifiche_prenotazione import CanaleTelegram, crea_notificatore_prenotazione
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE

SEG = b"S" * 32


class TestTelegramHost(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        d = self.dir
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/acc.db"))
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@sim.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.hid, self.tok = c["host_id"], c["token"]

    def tearDown(self):
        os.environ.pop("TELEGRAM_WEBHOOK_SECRET", None)
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, metodo, path, body=None, headers=None, query=None):
        return self.r.gestisci(metodo, path, query or {},
                               json.dumps(body) if body is not None else None, headers or {})

    def _codice_link(self):
        s, d = self.g("GET", "/api/host/telegram_link", headers={"X-Host-Token": self.tok})
        self.assertEqual(s, 200, d)
        self.assertIn("t.me/", d["link"])
        return parse_qs(urlparse(d["link"]).query)["start"][0]

    def _update_start(self, code, chat_id=999001):
        return {"message": {"chat": {"id": chat_id}, "text": "/start " + code}}

    def test_link_e_webhook_salva_chat_id(self):
        code = self._codice_link()
        s, _ = self.g("POST", "/api/telegram/webhook", self._update_start(code, 555))
        self.assertEqual(s, 200)
        info = self.sys.registro_host.info_host(self.hid)
        self.assertEqual(info["telegram_chat_id"], "555")   # collegato

    def test_codice_ignoto_non_collega(self):
        s, _ = self.g("POST", "/api/telegram/webhook", self._update_start("codicefinto", 777))
        self.assertEqual(s, 200)
        self.assertEqual(self.sys.registro_host.info_host(self.hid)["telegram_chat_id"], "")

    def test_codice_usa_e_getta(self):
        code = self._codice_link()
        self.g("POST", "/api/telegram/webhook", self._update_start(code, 111))
        # riusare lo stesso codice non ricollega (è stato consumato)
        self.g("POST", "/api/telegram/webhook", self._update_start(code, 222))
        self.assertEqual(self.sys.registro_host.info_host(self.hid)["telegram_chat_id"], "111")

    def test_webhook_segreto(self):
        os.environ["TELEGRAM_WEBHOOK_SECRET"] = "s3cr3t"
        code = self._codice_link()
        s, _ = self.g("POST", "/api/telegram/webhook", self._update_start(code, 333))
        self.assertEqual(s, 403)                            # senza header segreto -> vietato
        s, _ = self.g("POST", "/api/telegram/webhook", self._update_start(code, 333),
                      {"X-Telegram-Bot-Api-Secret-Token": "s3cr3t"})
        self.assertEqual(s, 200)
        self.assertEqual(self.sys.registro_host.info_host(self.hid)["telegram_chat_id"], "333")

    def test_link_richiede_auth(self):
        s, _ = self.g("GET", "/api/host/telegram_link")
        self.assertEqual(s, 401)


class TestCanaleTelegram(unittest.TestCase):
    def test_invia_ok(self):
        chiamate = []
        def fake(url, headers, body):
            chiamate.append((url, body)); return 200, "ok"
        c = CanaleTelegram("BOTTOK", fetch=fake)
        self.assertTrue(c.attivo())
        self.assertTrue(c.invia("12345", "Nuova richiesta", "Approva: http://x"))
        self.assertIn("/botBOTTOK/sendMessage", chiamate[0][0])
        self.assertEqual(chiamate[0][1]["chat_id"], "12345")

    def test_gated_senza_token(self):
        self.assertFalse(CanaleTelegram("").attivo())
        self.assertFalse(CanaleTelegram("").invia("1", "x", "y"))

    def test_notificatore_include_telegram(self):
        def fake(url, headers, body):
            return 200, "ok"
        notif = crea_notificatore_prenotazione(telegram_bot_token="TOK", fetch=fake)
        # dispatch: l'host con telegram_chat_id riceve su Telegram
        rep = notif.avvisa({"telegram_chat_id": "42"}, "ogg", "testo con Approva/Rifiuta")
        self.assertGreaterEqual(rep.get("inviati", 0), 1)


if __name__ == "__main__":
    unittest.main()
