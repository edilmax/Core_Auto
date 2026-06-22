"""
Test Fase 87 - Webhook Stripe.

Copre: firma valida -> verificata, payload manomesso -> rifiutato, secret errato ->
rifiutato, timestamp scaduto (anti-replay) -> rifiutato, header malformato -> rifiutato,
gestisci_webhook (parse evento), robustezza (mai solleva).
"""
import json
import unittest

from fase87_stripe_webhook import (
    firma_di_test, gestisci_webhook, verifica_firma_stripe,
)

SECRET = "whsec_testsegreto"
PAYLOAD = json.dumps({"type": "checkout.session.completed",
                      "data": {"object": {"metadata": {"riferimento": "ABC123"}}}})


class TestFirma(unittest.TestCase):
    def test_valida(self):
        h = firma_di_test(PAYLOAD, SECRET, 1000)
        self.assertTrue(verifica_firma_stripe(PAYLOAD, h, SECRET, ora=1000))

    def test_payload_manomesso(self):
        h = firma_di_test(PAYLOAD, SECRET, 1000)
        self.assertFalse(verifica_firma_stripe(PAYLOAD + "x", h, SECRET, ora=1000))

    def test_secret_errato(self):
        h = firma_di_test(PAYLOAD, SECRET, 1000)
        self.assertFalse(verifica_firma_stripe(PAYLOAD, h, "whsec_altro", ora=1000))

    def test_replay_timestamp_vecchio(self):
        h = firma_di_test(PAYLOAD, SECRET, 1000)
        # ora molto dopo -> oltre la tolleranza -> rifiutato
        self.assertFalse(verifica_firma_stripe(PAYLOAD, h, SECRET, ora=1000 + 10000))

    def test_header_malformato(self):
        for bad in ("", "spazzatura", "t=abc,v1=x", "v1=soloquesto", None, 123):
            self.assertFalse(verifica_firma_stripe(PAYLOAD, bad, SECRET, ora=1000))

    def test_secret_vuoto(self):
        h = firma_di_test(PAYLOAD, SECRET, 1000)
        self.assertFalse(verifica_firma_stripe(PAYLOAD, h, "", ora=1000))


class TestGestisci(unittest.TestCase):
    def test_evento_valido(self):
        h = firma_di_test(PAYLOAD, SECRET, 1000)
        ok, tipo, dati = gestisci_webhook(PAYLOAD, h, SECRET, ora=1000)
        self.assertTrue(ok)
        self.assertEqual(tipo, "checkout.session.completed")
        self.assertEqual(dati["object"]["metadata"]["riferimento"], "ABC123")

    def test_firma_invalida_niente_evento(self):
        ok, tipo, dati = gestisci_webhook(PAYLOAD, "t=1000,v1=falso", SECRET, ora=1000)
        self.assertFalse(ok)
        self.assertEqual(tipo, "")
        self.assertIsNone(dati)

    def test_payload_non_json(self):
        h = firma_di_test("non-json", SECRET, 1000)
        ok, _, _ = gestisci_webhook("non-json", h, SECRET, ora=1000)
        self.assertFalse(ok)

    def test_mai_solleva(self):
        for bad in (None, 123, [], {}):
            try:
                verifica_firma_stripe(bad, bad, bad)
                gestisci_webhook(bad, bad, bad)
            except Exception as e:  # pragma: no cover
                self.fail(f"sollevato su {bad!r}: {e}")


if __name__ == "__main__":
    unittest.main()
