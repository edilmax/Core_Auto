"""
Test Fase 37 / Tavola VIP - Notifiche (consegna voucher, Variante D).

Copre: lo Stub, il RouterNotifiche resiliente (retry sul transitorio, FALLBACK
multi-canale, isolamento da notificatori che sollevano, tutti_falliti),
EmailNotificatore non configurato (degrada), e l'integrazione con ServizioPagamenti
(il voucher parte al confirm; un guasto della notifica NON rompe il pagamento).
"""
import os
import sqlite3
import tempfile
import unittest

from fase37_notifiche import (EsitoNotifica, Notifica, Notificatore,
                              StubNotificatore, EmailNotificatore, RouterNotifiche,
                              ServizioNotifiche, componi_voucher)
from fase34_prenotazioni import MotorePrenotazioni, RichiestaPrenotazione
from fase35_pagamenti import StubPagamentoProvider, ServizioPagamenti


class _Esplosivo(Notificatore):
    canale = "email"
    def invia(self, destinatario, oggetto, corpo):
        raise RuntimeError("boom")  # un notificatore difettoso NON deve far crashare


class TestStub(unittest.TestCase):
    def test_successo_e_destinatario_mancante(self):
        s = StubNotificatore()
        self.assertTrue(s.invia("a@b.it", "o", "c").ok)
        self.assertEqual(s.invia("", "o", "c").motivo, "destinatario_mancante")

    def test_transitorio_poi_ok(self):
        s = StubNotificatore(fallisci_volte=2)
        self.assertFalse(s.invia("a@b.it", "o", "c").ok)
        self.assertFalse(s.invia("a@b.it", "o", "c").ok)
        self.assertTrue(s.invia("a@b.it", "o", "c").ok)


class TestRouter(unittest.TestCase):
    def test_consegna_primaria(self):
        s = StubNotificatore("email")
        r = RouterNotifiche().registra(s)
        es = r.invia(Notifica("o", "c", {"email": "a@b.it"}))
        self.assertTrue(es.ok)
        self.assertEqual(len(s.inviate), 1)

    def test_retry_recupera_transitorio(self):
        s = StubNotificatore("email", fallisci_volte=2)   # 2 ko, poi ok (tentativi=3)
        r = RouterNotifiche(tentativi=3).registra(s)
        self.assertTrue(r.invia(Notifica("o", "c", {"email": "a@b.it"})).ok)

    def test_fallback_su_secondo_canale(self):
        email = StubNotificatore("email", sempre_giu=True)
        whats = StubNotificatore("whatsapp")
        r = RouterNotifiche().registra(email).registra(whats)
        es = r.invia(Notifica("o", "c", {"email": "a@b.it", "whatsapp": "+39"}),
                     priorita=("email", "whatsapp"))
        self.assertTrue(es.ok)
        self.assertEqual(es.canale, "whatsapp")            # ripiegato sul fallback
        self.assertEqual(len(whats.inviate), 1)

    def test_tutti_falliti(self):
        r = RouterNotifiche().registra(StubNotificatore("email", sempre_giu=True))
        self.assertEqual(r.invia(Notifica("o", "c", {"email": "a@b.it"})).motivo,
                         "tutti_falliti")

    def test_isolato_da_notificatore_che_solleva(self):
        r = RouterNotifiche().registra(_Esplosivo())
        es = r.invia(Notifica("o", "c", {"email": "a@b.it"}))   # NON deve sollevare
        self.assertFalse(es.ok)


class TestEmailEComponi(unittest.TestCase):
    def test_email_non_configurato_degrada(self):
        e = EmailNotificatore(host="", mittente="")
        self.assertEqual(e.invia("a@b.it", "o", "c").motivo, "non_configurato")

    def test_componi_voucher(self):
        ogg, corpo = componi_voucher(codice_voucher="VIP-X", alloggio="t1",
                                     check_in="2026-08-01", check_out="2026-08-03")
        self.assertIn("VIP-X", corpo)
        self.assertIn("2026-08-03", corpo)
        self.assertIn("t1", ogg)


class TestIntegrazionePagamento(unittest.TestCase):
    """Il voucher parte al confirm; un guasto notifica NON rompe il pagamento."""
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

    def _prenota_e_paga(self, servizio):
        e = self.motore.crea(RichiestaPrenotazione(
            "t1", "Mario", "cliente@x.it", "2026-08-01", "2026-08-03", 10000, 1000))
        payload, firma = self.provider.firma_evento(e.pagamento_id, pagato=True)
        return servizio.gestisci_webhook(payload, firma)

    def test_voucher_consegnato_al_cliente(self):
        stub = StubNotificatore("email")
        notifiche = ServizioNotifiche(RouterNotifiche().registra(stub))
        servizio = ServizioPagamenti(self.motore, self.provider, notifiche=notifiche)
        esito = self._prenota_e_paga(servizio)
        self.assertEqual(esito.esito, "confermato")
        self.assertEqual(len(stub.inviate), 1)
        dest, oggetto, corpo = stub.inviate[0]
        self.assertEqual(dest, "cliente@x.it")
        self.assertIn(esito.voucher, corpo)               # il codice voucher nel messaggio

    def test_notifica_giu_non_rompe_il_pagamento(self):
        notifiche = ServizioNotifiche(RouterNotifiche().registra(_Esplosivo()))
        servizio = ServizioPagamenti(self.motore, self.provider, notifiche=notifiche)
        esito = self._prenota_e_paga(servizio)
        self.assertEqual(esito.esito, "confermato")        # confermato malgrado la notifica giu'
        self.assertTrue(esito.voucher)

    def test_senza_notifiche_invariato(self):
        servizio = ServizioPagamenti(self.motore, self.provider)  # notifiche=None
        self.assertEqual(self._prenota_e_paga(servizio).esito, "confermato")


if __name__ == "__main__":
    unittest.main()
