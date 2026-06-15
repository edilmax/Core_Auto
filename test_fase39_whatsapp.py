"""
Test Fase 39 / Tavola VIP - Canale WhatsApp (Cloud API) + innesto nel router.

Copre: WhatsAppNotificatore (config, invio ok/errore/isolamento, payload template),
la factory completa (WhatsApp default-off), il FALLBACK whatsapp->email del router,
e l'E2E: una prenotazione con telefono consegna il voucher su WhatsApp.
Trasporto iniettato: nessuna rete reale.
"""
import os
import sqlite3
import tempfile
import unittest

from fase39_whatsapp import WhatsAppNotificatore, crea_servizio_notifiche_completo
from fase37_notifiche import (RouterNotifiche, ServizioNotifiche, Notifica,
                              StubNotificatore)
from fase34_prenotazioni import MotorePrenotazioni, RichiestaPrenotazione
from fase35_pagamenti import StubPagamentoProvider, ServizioPagamenti


def _trasp_ok(reg):
    def t(url, headers, payload):
        reg.append((url, headers, payload))
        return 200, {"messages": [{"id": "wamid.X"}]}
    return t

def _trasp_400(url, headers, payload):
    return 400, {"error": {"message": "template non approvato"}}

def _trasp_boom(url, headers, payload):
    raise RuntimeError("rete giu'")


class TestWhatsAppNotificatore(unittest.TestCase):
    def test_non_configurato(self):
        w = WhatsAppNotificatore(access_token="", phone_number_id="")
        self.assertEqual(w.invia("+39", "o", "c").motivo, "non_configurato")

    def test_destinatario_mancante(self):
        w = WhatsAppNotificatore(access_token="t", phone_number_id="1")
        self.assertEqual(w.invia("", "o", "c").motivo, "destinatario_mancante")

    def test_invio_ok_e_payload(self):
        reg = []
        w = WhatsAppNotificatore(access_token="tok", phone_number_id="999",
                                 template="link_pagamento", transport=_trasp_ok(reg))
        es = w.invia("+39333", "oggetto", "VIP-123")
        self.assertTrue(es.ok)
        self.assertEqual(es.canale, "whatsapp")
        url, headers, payload = reg[0]
        self.assertIn("999/messages", url)
        self.assertEqual(payload["to"], "+39333")
        self.assertEqual(payload["template"]["name"], "link_pagamento")

    def test_status_errore(self):
        w = WhatsAppNotificatore(access_token="t", phone_number_id="1",
                                 transport=_trasp_400)
        self.assertEqual(w.invia("+39", "o", "c").motivo, "errore")

    def test_transport_solleva_isolato(self):
        w = WhatsAppNotificatore(access_token="t", phone_number_id="1",
                                 transport=_trasp_boom)
        es = w.invia("+39", "o", "c")   # NON deve sollevare
        self.assertFalse(es.ok)


class TestFactoryCompleta(unittest.TestCase):
    def _env(self, val):
        vecchio = os.environ.get("WHATSAPP_ENABLED")
        self.addCleanup(lambda: os.environ.__setitem__("WHATSAPP_ENABLED", vecchio)
                        if vecchio is not None else os.environ.pop("WHATSAPP_ENABLED", None))
        if val is None:
            os.environ.pop("WHATSAPP_ENABLED", None)
        else:
            os.environ["WHATSAPP_ENABLED"] = val

    def test_default_off_solo_email(self):
        self._env(None)
        s = crea_servizio_notifiche_completo()
        self.assertEqual(s._priorita, ("email",))
        self.assertNotIn("whatsapp", s._router.canali())

    def test_acceso_registra_whatsapp(self):
        self._env("true")
        s = crea_servizio_notifiche_completo()
        self.assertEqual(s._priorita, ("whatsapp", "email"))
        self.assertIn("whatsapp", s._router.canali())


class TestFallback(unittest.TestCase):
    def test_whatsapp_giu_ripiega_su_email(self):
        wa = WhatsAppNotificatore(access_token="t", phone_number_id="1",
                                  transport=_trasp_boom)   # WhatsApp giu'
        email = StubNotificatore("email")
        r = RouterNotifiche().registra(wa).registra(email)
        es = r.invia(Notifica("o", "c", {"whatsapp": "+39", "email": "a@b.it"}),
                     priorita=("whatsapp", "email"))
        self.assertTrue(es.ok)
        self.assertEqual(es.canale, "email")             # ripiegato
        self.assertEqual(len(email.inviate), 1)

    def test_whatsapp_ok_consegna_su_whatsapp(self):
        reg = []
        wa = WhatsAppNotificatore(access_token="t", phone_number_id="1",
                                  transport=_trasp_ok(reg))
        r = RouterNotifiche().registra(wa).registra(StubNotificatore("email"))
        es = r.invia(Notifica("o", "c", {"whatsapp": "+39", "email": "a@b.it"}),
                     priorita=("whatsapp", "email"))
        self.assertEqual(es.canale, "whatsapp")
        self.assertEqual(len(reg), 1)


class TestE2ETelefono(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.motore = MotorePrenotazioni(lambda: sqlite3.connect(self.path, timeout=30))
        self.motore.inizializza_schema()
        self.provider = StubPagamentoProvider(segreto="s")

    def tearDown(self):
        for ext in ("", "-wal", "-shm", "-journal"):
            try:
                os.remove(self.path + ext)
            except OSError:
                pass

    def test_voucher_via_whatsapp_se_c_e_il_telefono(self):
        reg = []
        wa = WhatsAppNotificatore(access_token="t", phone_number_id="1",
                                  transport=_trasp_ok(reg))
        notifiche = ServizioNotifiche(
            RouterNotifiche().registra(wa).registra(StubNotificatore("email")),
            priorita=("whatsapp", "email"))
        servizio = ServizioPagamenti(self.motore, self.provider, notifiche=notifiche)
        e = self.motore.crea(RichiestaPrenotazione(
            "t1", "Mario", "m@x.it", "2026-08-01", "2026-08-03", 10000, 1000,
            ospite_telefono="+39333111"))
        payload, firma = self.provider.firma_evento(e.pagamento_id, pagato=True)
        esito = servizio.gestisci_webhook(payload, firma)
        self.assertEqual(esito.esito, "confermato")
        self.assertEqual(len(reg), 1)                    # consegnato via WhatsApp
        self.assertEqual(reg[0][2]["to"], "+39333111")   # al telefono giusto


if __name__ == "__main__":
    unittest.main()
