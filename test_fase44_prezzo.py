"""
Test funzionali del motore del prezzo del Core (fase44, M2) - vincitrice
Host-Authoritative. Prezzo = tariffa host + floor, verita' d'inventario,
dinamismo, centesimi esatti, OTA solo informativo, iniezione policy.
"""
import unittest

from fase44_prezzo import (
    ContestoPrezzo, PoliticaPrezzoHostAuthoritative, PoliticaPrezzoFisso,
    politica_prezzo_da_config)


class TestHostAuthoritative(unittest.TestCase):
    def setUp(self):
        self.pol = PoliticaPrezzoHostAuthoritative()

    def test_prezzo_uguale_alla_tariffa_host(self):
        e = self.pol.risolvi(ContestoPrezzo(15_000, floor_host_cents=8_000))
        self.assertEqual((e.stato, e.prezzo_cents), ("ok", 15_000))

    def test_floor_imposto(self):
        e = self.pol.risolvi(ContestoPrezzo(5_000, floor_host_cents=8_000))
        self.assertEqual(e.prezzo_cents, 8_000)

    def test_inventario_esaurito_nosale(self):
        e = self.pol.risolvi(ContestoPrezzo(15_000, inventario_disponibile=False))
        self.assertEqual(e.stato, "nosale")
        self.assertIsNone(e.prezzo_cents)

    def test_dinamismo_passa_attraverso(self):
        feriale = self.pol.risolvi(ContestoPrezzo(10_000)).prezzo_cents
        weekend = self.pol.risolvi(ContestoPrezzo(13_000)).prezzo_cents
        self.assertGreater(weekend, feriale)

    def test_centesimi_interi(self):
        e = self.pol.risolvi(ContestoPrezzo(15_001, floor_host_cents=8_000))
        self.assertIsInstance(e.prezzo_cents, int)

    def test_ota_solo_informativo_non_muove_il_prezzo(self):
        senza = self.pol.risolvi(ContestoPrezzo(15_000)).prezzo_cents
        con = self.pol.risolvi(ContestoPrezzo(15_000, ota_confronto_cents=20_000)).prezzo_cents
        self.assertEqual(senza, con)

    def test_risparmio_calcolato_se_confronto_fresco(self):
        e = self.pol.risolvi(ContestoPrezzo(15_000, ota_confronto_cents=18_300))
        self.assertTrue(e.confronto_affidabile)
        self.assertEqual(e.risparmio_vs_ota_cents, 3_300)

    def test_degrado_grazioso_confronto_stantio(self):
        e = self.pol.risolvi(ContestoPrezzo(15_000, ota_confronto_cents=18_300,
                                            confronto_stantio=True))
        self.assertEqual(e.prezzo_cents, 15_000)
        self.assertFalse(e.confronto_affidabile)
        self.assertIsNone(e.risparmio_vs_ota_cents)


class TestIniezionePolicyPrezzo(unittest.TestCase):
    def test_host_vs_fisso_stesso_core(self):
        ctx = ContestoPrezzo(15_000, floor_host_cents=8_000)
        host = PoliticaPrezzoHostAuthoritative().risolvi(ctx).prezzo_cents
        fisso = PoliticaPrezzoFisso(prezzo_cents=5_000).risolvi(ctx).prezzo_cents
        self.assertEqual((host, fisso), (15_000, 5_000))
        self.assertNotEqual(host, fisso)

    def test_fisso_rispetta_inventario(self):
        e = PoliticaPrezzoFisso(prezzo_cents=5_000).risolvi(
            ContestoPrezzo(0, inventario_disponibile=False))
        self.assertEqual(e.stato, "nosale")

    def test_factory_da_config(self):
        self.assertIsInstance(politica_prezzo_da_config({"tipo": "host_authoritative"}),
                              PoliticaPrezzoHostAuthoritative)
        self.assertIsInstance(
            politica_prezzo_da_config({"tipo": "fisso", "prezzo_cents": 5_000}),
            PoliticaPrezzoFisso)
        with self.assertRaises(ValueError):
            politica_prezzo_da_config({"tipo": "mirror_ota"})    # la variante scartata


if __name__ == "__main__":
    unittest.main()
