"""
Test Fase 85 - Provider Pagamento Stripe.

Copre: creazione link (con fetch STUB, niente chiamata reale), request ben formata
(unit_amount in cents, auth Bearer, mode payment, metadata), no-url -> None, fetch che
solleva -> None (isolato), cents invalidi -> None, factory gated (no chiave -> None).
"""
import unittest

from fase85_pagamenti_stripe import ProviderStripe, crea_provider_stripe


class FetchSpy:
    """Cattura la richiesta e ritorna una risposta finta (no Stripe reale)."""
    def __init__(self, risposta=None, solleva=False):
        self.url = None
        self.body = None
        self.headers = None
        self._risp = risposta if risposta is not None else {"url": "https://checkout.stripe.com/c/sess_123"}
        self._solleva = solleva

    def __call__(self, url, body, headers):
        if self._solleva:
            raise RuntimeError("stripe giu'")
        self.url, self.body, self.headers = url, body.decode(), headers
        return self._risp


DATI = {"prezzo_guest_cents": 9500, "riferimento": "ABC123", "email": "g@x.it"}


class TestProvider(unittest.TestCase):
    def test_crea_link(self):
        spy = FetchSpy()
        p = ProviderStripe("sk_test_x", "https://ok", "https://ko", fetch=spy)
        url = p.crea_link(DATI)
        self.assertEqual(url, "https://checkout.stripe.com/c/sess_123")

    def test_request_ben_formata(self):
        spy = FetchSpy()
        ProviderStripe("sk_test_xyz", "https://ok", "https://ko", fetch=spy).crea_link(DATI)
        self.assertIn("api.stripe.com", spy.url)
        self.assertEqual(spy.headers["Authorization"], "Bearer sk_test_xyz")
        self.assertIn("unit_amount%5D=9500", spy.body)       # cents interi (chiave Stripe)
        self.assertIn("mode=payment", spy.body)
        self.assertIn("ABC123", spy.body)                    # riferimento nei metadata
        self.assertIn("customer_email", spy.body)

    def test_no_url_in_risposta(self):
        p = ProviderStripe("sk", "o", "k", fetch=FetchSpy(risposta={"error": "x"}))
        self.assertIsNone(p.crea_link(DATI))

    def test_fetch_solleva_isolato(self):
        p = ProviderStripe("sk", "o", "k", fetch=FetchSpy(solleva=True))
        self.assertIsNone(p.crea_link(DATI))                 # None, non crash

    def test_cents_invalidi(self):
        spy = FetchSpy()
        p = ProviderStripe("sk", "o", "k", fetch=spy)
        for bad in ({"prezzo_guest_cents": 0}, {"prezzo_guest_cents": -5},
                    {"prezzo_guest_cents": 95.0}, {}, None):
            self.assertIsNone(p.crea_link(bad))

    def test_valuta(self):
        spy = FetchSpy()
        ProviderStripe("sk", "o", "k", valuta="USD", fetch=spy).crea_link(DATI)
        self.assertIn("currency%5D=usd", spy.body)


ANT = {"anticipo_cents": 3312, "saldo_cents": 26838, "totale_cents": 30000,
       "riferimento": "PS777", "email": "g@x.it", "valuta": "EUR"}


class TestAnticipoPagaStruttura(unittest.TestCase):
    """PAGA IN STRUTTURA: la Checkout Session addebita SOLO l'anticipo e salva la carta."""

    def test_ritorna_url(self):
        spy = FetchSpy()
        p = ProviderStripe("sk_test_x", "https://ok", "https://ko", fetch=spy)
        self.assertEqual(p.crea_link_anticipo(ANT), "https://checkout.stripe.com/c/sess_123")

    def test_addebita_ANTICIPO_non_il_totale(self):
        # il difetto da temere: addebitare il totale (300) invece dell'anticipo (33,12).
        spy = FetchSpy()
        ProviderStripe("sk", "o", "k", fetch=spy).crea_link_anticipo(ANT)
        self.assertIn("unit_amount%5D=3312", spy.body)          # anticipo, in cents
        self.assertNotIn("unit_amount%5D=30000", spy.body)      # MAI il totale
        self.assertNotIn("26838", spy.body.split("metadata")[0]) # il saldo non e' un line item

    def test_salva_la_carta_e_marca_in_struttura(self):
        spy = FetchSpy()
        ProviderStripe("sk", "o", "k", fetch=spy).crea_link_anticipo(ANT)
        self.assertIn("setup_future_usage%5D=off_session", spy.body)  # carta salvata
        self.assertIn("customer_creation=always", spy.body)
        self.assertIn("mode=payment", spy.body)
        self.assertIn("in_struttura", spy.body)                 # metadata[modo]
        self.assertIn("saldo_cents%5D=26838", spy.body)         # saldo nei metadata (per il webhook)
        self.assertIn("PS777", spy.body)                        # riferimento

    def test_anticipo_invalido_none(self):
        spy = FetchSpy()
        p = ProviderStripe("sk", "o", "k", fetch=spy)
        for bad in ({"anticipo_cents": 0}, {"anticipo_cents": -5},
                    {"anticipo_cents": 33.1}, {"anticipo_cents": True}, {}, None):
            self.assertIsNone(p.crea_link_anticipo(bad))

    def test_fetch_solleva_isolato(self):
        p = ProviderStripe("sk", "o", "k", fetch=FetchSpy(solleva=True))
        self.assertIsNone(p.crea_link_anticipo(ANT))            # None, non crash

    def test_saldo_zero_ok(self):
        # prezzo minuscolo: anticipo == totale, saldo 0 -> paga tutto online, valido
        spy = FetchSpy()
        u = ProviderStripe("sk", "o", "k", fetch=spy).crea_link_anticipo(
            {"anticipo_cents": 500, "saldo_cents": 0, "riferimento": "R", "valuta": "EUR"})
        self.assertEqual(u, "https://checkout.stripe.com/c/sess_123")
        self.assertIn("saldo_cents%5D=0", spy.body)


class TestFactoryGated(unittest.TestCase):
    def test_senza_chiave_none(self):
        self.assertIsNone(crea_provider_stripe(None))
        self.assertIsNone(crea_provider_stripe(""))
        self.assertIsNone(crea_provider_stripe("   "))

    def test_con_chiave(self):
        spy = FetchSpy()
        p = crea_provider_stripe("sk_live_x", "https://ok", "https://ko", fetch=spy)
        self.assertIsNotNone(p)
        self.assertEqual(p.crea_link(DATI), "https://checkout.stripe.com/c/sess_123")


if __name__ == "__main__":
    unittest.main()
