"""Test Fase 129 - Traduzione recensioni. traduci_fn iniettato: nessuna rete."""
import unittest

from fase129_traduzione_recensioni import (crea_traduttore_recensioni,
                                           crea_traduttore_recensioni_da_env,
                                           rileva_lingua)

TAG = lambda testo, da, a: ("[%s<-%s]" % (a, da)) + testo


class TestRilevaLingua(unittest.TestCase):
    def test_it_en_es(self):
        self.assertEqual(rileva_lingua("Ottimo soggiorno, molto bello e pulito"), "it")
        self.assertEqual(rileva_lingua("The stay was very great and nice"), "en")
        self.assertEqual(rileva_lingua("Todo excelente, muy gracias"), "es")

    def test_default_su_ignoto(self):
        self.assertEqual(rileva_lingua("xyz 123", default="en"), "en")
        self.assertEqual(rileva_lingua("", default="it"), "it")


class TestTraduzione(unittest.TestCase):
    def test_pass_through_default(self):
        out = crea_traduttore_recensioni().traduci_recensione(
            {"testo": "Ottimo soggiorno molto bello", "voto": 5}, "en")
        self.assertEqual(out["testo"], "Ottimo soggiorno molto bello")
        self.assertFalse(out["tradotto_auto"])
        self.assertEqual(out["lingua_origine"], "it")

    def test_traduce_conserva_originale(self):
        out = crea_traduttore_recensioni(TAG).traduci_recensione(
            {"testo": "Ottimo soggiorno molto bello", "lingua": "it"}, "en")
        self.assertEqual(out["testo"], "[en<-it]Ottimo soggiorno molto bello")
        self.assertEqual(out["testo_originale"], "Ottimo soggiorno molto bello")
        self.assertTrue(out["tradotto_auto"])
        self.assertEqual(out["lingua"], "en")

    def test_stessa_lingua_no_op(self):
        out = crea_traduttore_recensioni(TAG).traduci_recensione(
            {"testo": "The stay was very great", "lingua": "en"}, "en")
        self.assertFalse(out["tradotto_auto"])

    def test_isolato_pass_through(self):
        def boom(*a):
            raise RuntimeError("x")
        out = crea_traduttore_recensioni(boom).traduci_recensione(
            {"testo": "Ottimo molto bello", "lingua": "it"}, "en")
        self.assertFalse(out["tradotto_auto"])
        self.assertEqual(out["testo"], "Ottimo molto bello")

    def test_factory_env(self):
        self.assertIsNotNone(crea_traduttore_recensioni_da_env({}))


if __name__ == "__main__":
    unittest.main()
