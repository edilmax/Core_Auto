"""Test Fase 143 - KYC host. SQLite :memory:, provider iniettato: nessuna rete."""
import unittest

from fase143_kyc_host import crea_kyc_host


def kyc(provider=lambda h: "sess_" + h):
    k = crea_kyc_host(":memory:", avvia_sessione=provider)
    k.inizializza_schema()
    return k


class TestKYC(unittest.TestCase):
    def test_flusso_verificato(self):
        k = kyc()
        self.assertEqual(k.stato("h1"), "non_avviata")
        r = k.avvia("h1")
        self.assertTrue(r["ok"])
        self.assertEqual(r["session_ref"], "sess_h1")
        self.assertEqual(k.stato("h1"), "in_corso")
        self.assertFalse(k.verificato("h1"))
        self.assertTrue(k.conferma("h1", "verificato"))
        self.assertTrue(k.verificato("h1"))

    def test_respinto_e_ritenta(self):
        k = kyc()
        k.avvia("h1")
        self.assertTrue(k.conferma("h1", "respinto"))
        self.assertEqual(k.stato("h1"), "respinto")
        self.assertTrue(k.avvia("h1"))                     # respinto -> in_corso di nuovo

    def test_gated_senza_provider(self):
        k = crea_kyc_host(":memory:")
        k.inizializza_schema()
        self.assertFalse(k.avvia("h1")["ok"])

    def test_transizione_illegale(self):
        k = kyc()
        self.assertFalse(k.conferma("h1", "verificato"))   # non_avviata->verificato no
        self.assertFalse(k.conferma("h1", "boh"))

    def test_verificato_terminale(self):
        k = kyc()
        k.avvia("h1")
        k.conferma("h1", "verificato")
        self.assertFalse(k.conferma("h1", "respinto"))     # verificato è terminale

    def test_provider_solleva_isolato(self):
        def boom(h):
            raise RuntimeError("stripe giu")
        k = crea_kyc_host(":memory:", avvia_sessione=boom)
        k.inizializza_schema()
        self.assertFalse(k.avvia("h1")["ok"])

    def test_provider_ref_vuoto(self):
        k = crea_kyc_host(":memory:", avvia_sessione=lambda h: None)
        k.inizializza_schema()
        self.assertFalse(k.avvia("h1")["ok"])


if __name__ == "__main__":
    unittest.main()
