"""
Test Fase 75 - Guardian Engine.

Copre: water leak (critico, stato manutenzione), fuoco/CO (emergenza, evacuazione),
muffa (richiede durata sostenuta: scatta solo oltre 48h, non sul transitorio), nessun
pericolo (ok), letture non-intere ignorate, pericoli multipli (union azioni, severita'
max), esecuzione attuatori isolata, regole custom, robustezza.
"""
import unittest

from fase75_guardian_engine import (
    GuardianEngine, Pericolo, RegolaPericolo, ReportGuardian, crea_guardian,
)

H48 = 172800


class TestRilevamento(unittest.TestCase):
    def setUp(self):
        self.g = crea_guardian()

    def test_water_leak(self):
        r = self.g.valuta("casa", {"water": 1})
        self.assertTrue(r.critico)
        self.assertEqual(r.pericoli[0].tipo, "water_leak")
        self.assertIn("chiudi_acqua", r.azioni_consigliate)
        self.assertIn("genera_claim", r.azioni_consigliate)
        self.assertEqual(r.stato_consigliato, "manutenzione")

    def test_fuoco_emergenza(self):
        r = self.g.valuta("casa", {"fumo": 1})
        self.assertEqual(r.stato_consigliato, "emergenza")
        self.assertIn("evacua_ospite", r.azioni_consigliate)
        self.assertIn("chiama_emergenza", r.azioni_consigliate)

    def test_co(self):
        r = self.g.valuta("casa", {"co": 80})       # >50 ppm
        self.assertTrue(r.critico)
        self.assertEqual(r.stato_consigliato, "emergenza")

    def test_co_sotto_soglia_no(self):
        r = self.g.valuta("casa", {"co": 20})
        self.assertEqual(r.pericoli, [])

    def test_nessun_pericolo(self):
        r = self.g.valuta("casa", {"water": 0, "fumo": 0, "co": 10, "umidita": 450})
        self.assertEqual(r.pericoli, [])
        self.assertEqual(r.stato_consigliato, "ok")


class TestMuffaDurata(unittest.TestCase):
    def setUp(self):
        self.g = crea_guardian()

    def test_muffa_sostenuta(self):
        r = self.g.valuta("casa", {"umidita": 650},
                          durate_sostenute={"umidita": H48})
        self.assertEqual(len(r.pericoli), 1)
        self.assertEqual(r.pericoli[0].tipo, "mold_risk")
        self.assertIn("pulizia_prioritaria", r.azioni_consigliate)

    def test_umidita_alta_ma_transitoria_no(self):
        # umidita' oltre soglia ma solo per 1h (doccia) -> nessun falso positivo
        r = self.g.valuta("casa", {"umidita": 700}, durate_sostenute={"umidita": 3600})
        self.assertEqual(r.pericoli, [])

    def test_umidita_alta_senza_durata_no(self):
        r = self.g.valuta("casa", {"umidita": 700})   # nessuna durata fornita -> 0
        self.assertEqual(r.pericoli, [])


class TestMultiplo(unittest.TestCase):
    def test_water_piu_fuoco(self):
        g = crea_guardian()
        r = g.valuta("casa", {"water": 1, "fumo": 1})
        self.assertEqual(len(r.pericoli), 2)
        self.assertEqual(r.stato_consigliato, "emergenza")   # emergenza prevale
        # azioni unite senza duplicati
        self.assertEqual(len(r.azioni_consigliate), len(set(r.azioni_consigliate)))


class TestEsecuzione(unittest.TestCase):
    def test_attuatori_isolati(self):
        g = crea_guardian()
        r = g.valuta("casa", {"water": 1})
        eseguite = []

        def ok_fn(rep):
            eseguite.append(rep.alloggio_id)

        def boom(rep):
            raise RuntimeError("valvola bloccata")

        attuatori = {"chiudi_acqua": boom, "notifica_urgente": ok_fn,
                     "blocca_manutenzione": ok_fn, "genera_claim": ok_fn}
        esiti = g.esegui(r, attuatori)
        self.assertFalse(esiti["chiudi_acqua"])     # isolato, non crasha
        self.assertTrue(esiti["notifica_urgente"])
        self.assertEqual(len(eseguite), 3)

    def test_azione_senza_attuatore(self):
        g = crea_guardian()
        r = g.valuta("casa", {"fumo": 1})
        esiti = g.esegui(r, {})                      # nessun attuatore
        self.assertTrue(all(v is False for v in esiti.values()))


class TestCustom(unittest.TestCase):
    def test_regola_custom_giu(self):
        # es. temperatura troppo bassa (gelo): valore <= soglia
        regole = (RegolaPericolo("gelo", "temp", 0, "avviso", ("riscalda",),
                                 direzione="giu"),)
        g = crea_guardian(regole)
        self.assertEqual(len(g.valuta("casa", {"temp": -50}).pericoli), 1)
        self.assertEqual(g.valuta("casa", {"temp": 200}).pericoli, [])


class TestRobustezza(unittest.TestCase):
    def test_letture_non_intere_ignorate(self):
        g = crea_guardian()
        r = g.valuta("casa", {"water": 1.0, "fumo": True, "co": "80"})
        self.assertEqual(r.pericoli, [])            # nessuna lettura intera valida

    def test_mai_solleva(self):
        g = crea_guardian()
        for bad in (None, 123, "x", []):
            try:
                rep = g.valuta("casa", bad)
                g.esegui(rep, bad)
            except Exception as e:  # pragma: no cover
                self.fail(f"sollevato su {bad!r}: {e}")


if __name__ == "__main__":
    unittest.main()
