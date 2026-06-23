"""Test Fase 141 - Onboarding wizard. SQLite :memory:."""
import unittest

from fase141_onboarding_wizard import (MINIMI, crea_onboarding_wizard, stato_wizard)

PASSI_DATI = {
    "account": {"email": "h@x.it"},
    "struttura": {"titolo": "Casa", "citta": "Roma", "capacita": 4},
    "foto": {"foto": ["a.jpg"]},
    "prezzo": {"prezzo_cents": 9000},
    "disponibilita": {"giorni_aperti": 30},
}


def wz():
    w = crea_onboarding_wizard(":memory:")
    w.inizializza_schema()
    return w


class TestStatoPuro(unittest.TestCase):
    def test_vuoto(self):
        s = stato_wizard({})
        self.assertEqual(s["completati"], [])
        self.assertEqual(s["prossimo_passo"], "account")
        self.assertFalse(s["pubblicabile"])
        self.assertEqual(s["completamento_bps"], 0)

    def test_completo_minimi_pubblicabile(self):
        d = {}
        for v in PASSI_DATI.values():
            d.update(v)
        s = stato_wizard(d)
        self.assertTrue(s["pubblicabile"])
        self.assertEqual(s["prossimo_passo"], "pagamenti")    # opzionale


class TestWizard(unittest.TestCase):
    def test_salva_passi_e_avanza(self):
        w = wz()
        r = w.salva_passo("h1", "account", {"email": "h@x.it"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["prossimo_passo"], "struttura")
        self.assertEqual(r["completamento_bps"], 10000 // 6)

    def test_passo_incompleto_non_avanza(self):
        w = wz()
        r = w.salva_passo("h1", "struttura", {"titolo": "Casa"})   # mancano citta/capacita
        self.assertFalse(r["ok"])
        self.assertEqual(r["errore"], "passo_incompleto")

    def test_pubblica_gate_failclosed(self):
        w = wz()
        w.salva_passo("h1", "account", {"email": "h@x.it"})
        r = w.pubblica("h1")
        self.assertFalse(r["ok"])
        self.assertEqual(r["errore"], "requisiti_minimi_mancanti")

    def test_pubblica_dopo_minimi(self):
        w = wz()
        for passo in MINIMI:
            self.assertTrue(w.salva_passo("h1", passo, PASSI_DATI[passo])["ok"])
        self.assertTrue(w.stato("h1")["pubblicabile"])
        self.assertTrue(w.pubblica("h1")["ok"])
        self.assertTrue(w.stato("h1")["pubblicato"])

    def test_input_invalido(self):
        w = wz()
        self.assertFalse(w.salva_passo("", "account", {"email": "x@y.it"})["ok"])
        self.assertFalse(w.salva_passo("h1", "boh", {})["ok"])


if __name__ == "__main__":
    unittest.main()
