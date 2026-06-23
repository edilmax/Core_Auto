"""Test Fase 107 - i18n auto-traduzione annunci. traduci_fn iniettato: nessuna rete."""
import unittest

from fase107_traduzione_annunci import (TraduttoreAnnunci, crea_traduttore,
                                        crea_traduttore_da_env,
                                        traduttore_libretranslate)

UP = lambda testo, da, a: ("[%s]" % a) + testo            # finto traduttore deterministico
ANN = {"titolo": "Casa a Roma", "descrizione": "Bellissima", "citta": "Roma"}


class TestPassThrough(unittest.TestCase):
    def test_default_pass_through(self):
        out = crea_traduttore().traduci_annuncio(ANN, "en", lingua_origine="it")
        self.assertEqual(out["titolo"], "Casa a Roma")     # invariato
        self.assertEqual(out["_lingua"], "it")
        self.assertFalse(any(out["_tradotto"].values()))

    def test_stessa_lingua_no_op(self):
        r = TraduttoreAnnunci(UP).traduci_testo("ciao", "it", "it")
        self.assertEqual(r["testo"], "ciao")
        self.assertFalse(r["tradotto"])


class TestTraduzione(unittest.TestCase):
    def test_traduce_campi(self):
        out = crea_traduttore(UP).traduci_annuncio(ANN, "en", lingua_origine="it")
        self.assertEqual(out["titolo"], "[en]Casa a Roma")
        self.assertEqual(out["descrizione"], "[en]Bellissima")
        self.assertEqual(out["citta"], "Roma")             # campo non tradotto
        self.assertEqual(out["_lingua"], "en")
        self.assertTrue(out["_tradotto"]["titolo"])

    def test_cache_evita_ricompute(self):
        chiamate = []
        t = TraduttoreAnnunci(lambda testo, da, a: chiamate.append(1) or "X")
        t.traduci_testo("ciao", "it", "en")
        r = t.traduci_testo("ciao", "it", "en")
        self.assertTrue(r.get("cache"))
        self.assertEqual(len(chiamate), 1)

    def test_isolato_pass_through(self):
        def boom(testo, da, a):
            raise RuntimeError("backend giu")
        r = TraduttoreAnnunci(boom).traduci_testo("ciao", "it", "en")
        self.assertEqual(r["testo"], "ciao")
        self.assertFalse(r["tradotto"])

    def test_traduzione_vuota_pass_through(self):
        r = TraduttoreAnnunci(lambda *a: "").traduci_testo("ciao", "it", "en")
        self.assertFalse(r["tradotto"])


class TestBackend(unittest.TestCase):
    def test_libretranslate_gated(self):
        self.assertIsNone(traduttore_libretranslate(""))
        self.assertIsNotNone(crea_traduttore_da_env({}))    # pass-through traduttore
        self.assertIsNone(crea_traduttore_da_env({})._t)

    def test_libretranslate_traduce(self):
        f = traduttore_libretranslate("http://lt", fetch=lambda u, d: {"translatedText": "Hello"})
        self.assertEqual(f("Ciao", "it", "en"), "Hello")


if __name__ == "__main__":
    unittest.main()
