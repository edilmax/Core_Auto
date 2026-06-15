"""
Test Fase 35 / Tavola VIP - Pagamenti (link + webhook firmato + E2E).

Copre: creazione link, verifica firma webhook (valida/contraffatta/non pagato),
e il FLUSSO COMPLETO prenotazione -> link -> webhook firmato -> conferma + voucher.
Sicurezza: un webhook con firma errata NON cambia lo stato. Idempotenza: ri-
consegnare il webhook NON emette un secondo voucher.
"""
import os
import sqlite3
import tempfile
import unittest

from fase34_prenotazioni import MotorePrenotazioni, RichiestaPrenotazione
from fase35_pagamenti import (StubPagamentoProvider, StripeProvider,
                              ServizioPagamenti, EventoPagamento, LinkPagamento,
                              EsitoRimborso, crea_provider_pagamenti)


class _SpyProvider(StubPagamentoProvider):
    """Stub che registra le chiamate di rimborso (e puo' farle fallire)."""
    def __init__(self, *a, fallisci=False, **k):
        super().__init__(*a, **k)
        self.fallisci = fallisci
        self.rimborsi = []
    def rimborsa(self, riferimento, importo_cents):
        self.rimborsi.append((riferimento, importo_cents))
        return EsitoRimborso(False) if self.fallisci else EsitoRimborso(True, "re_x")


def _richiesta(ci="2026-09-01", co="2026-09-05"):
    return RichiestaPrenotazione("tavolo-1", "Mario", "m@x.it", ci, co, 20000, 2000)


class _Base(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.motore = MotorePrenotazioni(lambda: sqlite3.connect(self.path, timeout=30))
        self.motore.inizializza_schema()
        self.provider = StubPagamentoProvider(segreto="s3gr3t0")
        self.servizio = ServizioPagamenti(self.motore, self.provider)
    def tearDown(self):
        for ext in ("", "-wal", "-shm", "-journal"):
            try:
                os.remove(self.path + ext)
            except OSError:
                pass


class TestProvider(_Base):
    def test_crea_link(self):
        link = self.provider.crea_link(pagamento_id=7, importo_cents=20000,
                                       descrizione="x", email="a@b.it")
        self.assertIsInstance(link, LinkPagamento)
        self.assertIn("stub_7", link.url)

    def test_webhook_firma_valida(self):
        payload, firma = self.provider.firma_evento(42, pagato=True)
        ev = self.provider.verifica_webhook(payload, firma)
        self.assertEqual(ev, EventoPagamento("pagato", 42, "pi_stub_42"))

    def test_webhook_firma_contraffatta(self):
        payload, _ = self.provider.firma_evento(42)
        self.assertEqual(self.provider.verifica_webhook(payload, "deadbeef").tipo,
                         "non_valido")

    def test_webhook_payload_manomesso(self):
        payload, firma = self.provider.firma_evento(42)
        manomesso = payload.replace(b"42", b"99")  # firma non combacia piu'
        self.assertEqual(self.provider.verifica_webhook(manomesso, firma).tipo,
                         "non_valido")

    def test_webhook_non_pagato(self):
        payload, firma = self.provider.firma_evento(42, pagato=False)
        self.assertEqual(self.provider.verifica_webhook(payload, firma).tipo, "ignorato")


class TestFlussoE2E(_Base):
    def test_prenotazione_link_webhook_voucher(self):
        e = self.motore.crea(_richiesta())
        self.assertTrue(e.ok)
        # link di pagamento
        link = self.servizio.crea_link_pagamento(
            pagamento_id=e.pagamento_id, importo_cents=20000, email="m@x.it")
        self.assertTrue(link.url)
        # il cliente paga -> il PSP manda il webhook firmato
        payload, firma = self.provider.firma_evento(e.pagamento_id, pagato=True)
        esito = self.servizio.gestisci_webhook(payload, firma)
        self.assertEqual(esito.esito, "confermato")
        self.assertEqual(esito.prenotazione_id, e.prenotazione_id)
        self.assertTrue(esito.voucher and esito.voucher.startswith("VIP-"))
        # stato finale: pagata
        self.assertEqual(self.motore.stato(e.prenotazione_id)["stato"], "pagata")

    def test_webhook_firma_errata_non_cambia_stato(self):
        e = self.motore.crea(_richiesta())
        payload, _ = self.provider.firma_evento(e.pagamento_id)
        esito = self.servizio.gestisci_webhook(payload, "00000000")
        self.assertEqual(esito.esito, "non_valido")
        # NESSUN cambio di stato: ancora in attesa, niente voucher
        self.assertEqual(self.motore.stato(e.prenotazione_id)["stato"],
                         "in_attesa_pagamento")
        self.assertIsNone(self.motore.emetti_voucher(e.prenotazione_id))  # non pagata

    def test_pagamento_sconosciuto(self):
        payload, firma = self.provider.firma_evento(99999, pagato=True)
        self.assertEqual(self.servizio.gestisci_webhook(payload, firma).esito,
                         "pagamento_sconosciuto")

    def test_webhook_idempotente_un_solo_voucher(self):
        e = self.motore.crea(_richiesta())
        payload, firma = self.provider.firma_evento(e.pagamento_id, pagato=True)
        v1 = self.servizio.gestisci_webhook(payload, firma).voucher
        v2 = self.servizio.gestisci_webhook(payload, firma).voucher  # ri-consegna
        self.assertEqual(v1, v2)  # stesso voucher, non un secondo
        c = sqlite3.connect(self.path)
        n = c.execute("SELECT COUNT(*) FROM voucher_prenotazioni").fetchone()[0]
        c.close()
        self.assertEqual(n, 1)


class TestFactory(unittest.TestCase):
    """La factory env-driven: Stripe se la chiave c'e', altrimenti stub."""
    def _set_env(self, **kw):
        for k, v in kw.items():
            vecchio = os.environ.get(k)
            self.addCleanup(lambda k=k, v=vecchio:
                            os.environ.__setitem__(k, v) if v is not None
                            else os.environ.pop(k, None))
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_senza_chiave_usa_stub(self):
        self._set_env(STRIPE_API_KEY=None)
        self.assertIsInstance(crea_provider_pagamenti(), StubPagamentoProvider)

    def test_con_chiave_usa_stripe(self):
        self._set_env(STRIPE_API_KEY="sk_test_xyz")
        p = crea_provider_pagamenti(success_url="https://ok", cancel_url="https://ko")
        self.assertIsInstance(p, StripeProvider)  # nessuna chiamata di rete qui


class TestRimborsoServizio(unittest.TestCase):
    """Approvazione admin: il denaro si muove SOLO da 'rimborso_richiesto'."""
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.motore = MotorePrenotazioni(lambda: sqlite3.connect(self.path, timeout=30))
        self.motore.inizializza_schema()
        self.provider = _SpyProvider(segreto="s")
        self.servizio = ServizioPagamenti(self.motore, self.provider)
    def tearDown(self):
        for ext in ("", "-wal", "-shm", "-journal"):
            try:
                os.remove(self.path + ext)
            except OSError:
                pass
    def _paga(self):
        e = self.motore.crea(_richiesta())
        payload, firma = self.provider.firma_evento(e.pagamento_id, pagato=True)
        self.servizio.gestisci_webhook(payload, firma)   # memorizza il riferimento PSP
        return e

    def test_approva_completa_e_chiama_refund(self):
        e = self._paga()
        self.assertTrue(self.servizio.richiedi_rimborso(e.prenotazione_id))
        r = self.servizio.approva_rimborso(e.prenotazione_id)
        self.assertEqual(r.esito, "rimborsata")
        self.assertEqual(self.provider.rimborsi,
                         [(f"pi_stub_{e.pagamento_id}", 20000)])   # ref + importo esatto
        self.assertEqual(self.motore.stato(e.prenotazione_id)["stato"], "rimborsata")

    def test_approva_senza_richiesta_non_muove_denaro(self):
        e = self._paga()                       # pagata ma NON richiesto rimborso
        r = self.servizio.approva_rimborso(e.prenotazione_id)
        self.assertEqual(r.esito, "stato_non_valido")
        self.assertEqual(self.provider.rimborsi, [])   # refund MAI chiamato

    def test_refund_psp_fallito_non_chiude(self):
        self.provider.fallisci = True
        e = self._paga()
        self.servizio.richiedi_rimborso(e.prenotazione_id)
        r = self.servizio.approva_rimborso(e.prenotazione_id)
        self.assertEqual(r.esito, "refund_psp_fallito")
        self.assertEqual(self.motore.stato(e.prenotazione_id)["stato"],
                         "rimborso_richiesto")   # stato invariato: niente chiusura

    def test_rifiuta_torna_pagata(self):
        e = self._paga()
        self.servizio.richiedi_rimborso(e.prenotazione_id)
        self.assertTrue(self.servizio.rifiuta_rimborso(e.prenotazione_id))
        self.assertEqual(self.motore.stato(e.prenotazione_id)["stato"], "pagata")


if __name__ == "__main__":
    unittest.main()
