"""Test Fase 101 - Stripe Connect split-all'origine. fetch STUB: nessuna rete."""
import unittest

from fase101_stripe_connect import (ProviderStripeConnect, costruisci_params,
                                    crea_provider_stripe_connect)

DATI = {"prezzo_guest_cents": 11200, "commissione_cents": 1500,
        "host_account": "acct_123", "riferimento": "REF1", "valuta": "usd"}


class TestParams(unittest.TestCase):
    def test_destination_e_fee(self):
        p = costruisci_params(11200, 1500, "acct_123", valuta="usd")
        self.assertEqual(p["payment_intent_data[transfer_data][destination]"], "acct_123")
        self.assertEqual(p["payment_intent_data[application_fee_amount]"], "1500")
        self.assertEqual(p["line_items[0][price_data][unit_amount]"], "11200")
        self.assertEqual(p["line_items[0][price_data][currency]"], "usd")

    def test_invalidi(self):
        self.assertIsNone(costruisci_params(0, 100, "acct_1"))
        self.assertIsNone(costruisci_params(1000, 100, ""))         # no host
        self.assertIsNone(costruisci_params(1000, 1000, "acct_1"))  # fee >= lordo
        self.assertIsNone(costruisci_params(1000, -1, "acct_1"))


class TestProvider(unittest.TestCase):
    def test_crea_link_ok(self):
        visti = {}
        p = ProviderStripeConnect("sk_test", fetch=lambda u, b, h:
                                  visti.update(body=b, head=h) or {"url": "https://pay/x"})
        self.assertEqual(p.crea_link(DATI), "https://pay/x")
        self.assertIn(b"acct_123", visti["body"])
        self.assertEqual(visti["head"]["Authorization"], "Bearer sk_test")

    def test_gated_senza_key(self):
        self.assertIsNone(crea_provider_stripe_connect(None))
        self.assertIsNone(ProviderStripeConnect("").crea_link(DATI))

    def test_isolato(self):
        def boom(*a):
            raise RuntimeError("stripe giu")
        self.assertIsNone(ProviderStripeConnect("sk", fetch=boom).crea_link(DATI))

    def test_factory(self):
        self.assertIsNotNone(crea_provider_stripe_connect("sk", fetch=lambda *a: {}))


if __name__ == "__main__":
    unittest.main()
