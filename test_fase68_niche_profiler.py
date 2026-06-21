"""
Test Fase 68 - Niche Profiler (niche stacking).

Copre: maschera attributi, soddisfa/nicchie_soddisfatte (incl. STACKING multi-nicchia),
attributi ignoti ignorati, pricing (sconto settimanale/mensile per soglia, supplemento
pet, tariffa solo, combinazioni, conservazione), accessibilita' senza supplemento,
profilo_alloggio machine-clean, robustezza.
"""
import unittest

from fase68_niche_profiler import (
    ATTRIBUTI, PROFILI, PoliticaNicchia, ammette_supplemento,
    attributi_da_maschera, calcola_prezzo_nicchia, maschera_nicchia,
    nicchie_soddisfatte, profilo_alloggio, soddisfa,
)


class TestMaschera(unittest.TestCase):
    def test_round_trip(self):
        attrs = ["pet_friendly", "scrivania", "wifi_veloce"]
        m = maschera_nicchia(attrs)
        self.assertEqual(set(attributi_da_maschera(m)), set(attrs))

    def test_ignoti_ignorati(self):
        self.assertEqual(maschera_nicchia(["wifi_veloce", "teletrasporto"]),
                         ATTRIBUTI["wifi_veloce"])

    def test_maschera_invalida(self):
        self.assertEqual(attributi_da_maschera(-1), [])
        self.assertEqual(attributi_da_maschera(True), [])


class TestProfili(unittest.TestCase):
    def test_soddisfa(self):
        m = maschera_nicchia(["pet_friendly", "pet_cane_grande"])
        self.assertTrue(soddisfa(m, "pet_cane_grande"))
        self.assertFalse(soddisfa(m, "pet_gatto"))

    def test_profilo_parziale_non_soddisfa(self):
        m = maschera_nicchia(["nomad_friendly", "scrivania"])  # manca wifi_veloce
        self.assertFalse(soddisfa(m, "nomad"))

    def test_niche_stacking(self):
        # un alloggio che serve 3 nicchie con UNA maschera
        attrs = ["pet_friendly", "pet_cane_grande",
                 "nomad_friendly", "scrivania", "wifi_veloce",
                 "acc_allarme_visivo"]
        nicchie = nicchie_soddisfatte(maschera_nicchia(attrs))
        self.assertIn("pet_cane_grande", nicchie)
        self.assertIn("nomad", nicchie)
        self.assertIn("accessibile_ipovedenti", nicchie)
        self.assertGreaterEqual(len(nicchie), 3)

    def test_soddisfa_profilo_ignoto(self):
        self.assertFalse(soddisfa(maschera_nicchia(["wifi_veloce"]), "profilo_inventato"))


class TestPricing(unittest.TestCase):
    def test_nessuno_sconto_sotto_soglia(self):
        pol = PoliticaNicchia(sconto_settimanale_bps=2000, soglia_settimana=7)
        c = calcola_prezzo_nicchia(10000, 5, politica=pol)
        self.assertEqual(c.fascia, "notte")
        self.assertEqual(c.totale_cents, 50000)

    def test_sconto_settimanale(self):
        pol = PoliticaNicchia(sconto_settimanale_bps=2000, soglia_settimana=7,
                              sconto_mensile_bps=3000, soglia_mese=28)
        c = calcola_prezzo_nicchia(10000, 10, politica=pol)   # 10 notti -> settimana
        self.assertEqual(c.fascia, "settimana")
        self.assertEqual(c.sconto_lungo_cents, (100000 * 2000) // 10000)  # 20%
        self.assertEqual(c.totale_cents, 100000 - 20000)

    def test_sconto_mensile_nomad(self):
        pol = PoliticaNicchia(sconto_settimanale_bps=2000, sconto_mensile_bps=3000,
                              soglia_mese=28)
        c = calcola_prezzo_nicchia(10000, 30, politica=pol)   # 30 notti -> mese
        self.assertEqual(c.fascia, "mese")
        self.assertEqual(c.sconto_lungo_cents, (300000 * 3000) // 10000)  # 30%

    def test_supplemento_pet(self):
        pol = PoliticaNicchia(pet_notte_cents=1500)
        c = calcola_prezzo_nicchia(10000, 3, politica=pol, con_pet=True)
        self.assertEqual(c.supplemento_pet_cents, 1500 * 3)
        self.assertEqual(c.totale_cents, 30000 + 4500)

    def test_tariffa_solo(self):
        pol = PoliticaNicchia(sconto_solo_bps=1000)   # 10%
        c = calcola_prezzo_nicchia(10000, 2, politica=pol, solo=True)
        self.assertEqual(c.sconto_solo_cents, (20000 * 1000) // 10000)
        self.assertEqual(c.totale_cents, 20000 - 2000)

    def test_conservazione(self):
        pol = PoliticaNicchia(sconto_settimanale_bps=1500, pet_notte_cents=1000,
                              sconto_solo_bps=500)
        c = calcola_prezzo_nicchia(12000, 7, politica=pol, con_pet=True, solo=True)
        atteso = (c.base_cents - c.sconto_lungo_cents - c.sconto_solo_cents
                  + c.supplemento_pet_cents)
        self.assertEqual(c.totale_cents, atteso)
        self.assertIsInstance(c.totale_cents, int)

    def test_fail_closed(self):
        pol = PoliticaNicchia()
        self.assertEqual(calcola_prezzo_nicchia(0, 5, politica=pol).totale_cents, 0)
        self.assertEqual(calcola_prezzo_nicchia(10000, 0, politica=pol).totale_cents, 0)
        self.assertEqual(calcola_prezzo_nicchia(10.0, 5, politica=pol).totale_cents, 0)

    def test_mai_sotto_uno(self):
        pol = PoliticaNicchia(sconto_solo_bps=10000)   # 100% sconto -> clamp a 1
        c = calcola_prezzo_nicchia(10000, 1, politica=pol, solo=True)
        self.assertEqual(c.totale_cents, 1)


class TestAccessibilita(unittest.TestCase):
    def test_no_supplemento(self):
        self.assertFalse(ammette_supplemento(["accessibile_sedia_rotelle"]))
        self.assertTrue(ammette_supplemento(["pet_cane_grande", "nomad"]))


class TestProfiloAlloggio(unittest.TestCase):
    def test_riepilogo(self):
        p = profilo_alloggio(["pet_friendly", "pet_gatto", "solo_friendly",
                              "no_supplemento_singola"])
        self.assertIn("pet_gatto", p["nicchie"])
        self.assertIn("solo", p["nicchie"])
        self.assertEqual(p["n_nicchie"], 2)
        self.assertTrue(p["supplementi_ammessi"])

    def test_robustezza(self):
        for bad in (None, 123, "x"):
            try:
                profilo_alloggio(bad)
                maschera_nicchia(bad)
                nicchie_soddisfatte(bad if isinstance(bad, int) else 0)
            except Exception as e:  # pragma: no cover
                self.fail(f"sollevato su {bad!r}: {e}")


if __name__ == "__main__":
    unittest.main()
