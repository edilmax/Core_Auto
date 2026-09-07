"""Test Fase 125 - Confronto OTA risparmio guest. Puro, cents/bps interi."""
import dataclasses
import unittest

from fase125_confronto_guest import PoliticaConfrontoGuest, _i, confronta_guest


class TestConfrontoGuest(unittest.TestCase):
    def test_calcolo_base(self):
        c = confronta_guest(10000)                          # netto host 100
        # OTA: 100 +15% = 115 base; +14% fee = 16.10; tot 131.10
        self.assertEqual(c["ota_base_cents"], 11500)
        self.assertEqual(c["ota_guest_fee_cents"], 1610)
        self.assertEqual(c["ota_totale_cents"], 13110)
        # noi: 100 PULITO (0% ospite) -> l'ospite paga 10000
        self.assertEqual(c["nostro_totale_cents"], 10000)
        self.assertEqual(c["risparmio_guest_cents"], 3110)     # risparmio reale vs OTA

    def test_dcc_solo_se_valuta_diversa(self):
        senza = confronta_guest(10000, valuta_diversa=False)
        con = confronta_guest(10000, valuta_diversa=True)
        self.assertEqual(senza["ota_dcc_cents"], 0)
        self.assertGreater(con["ota_dcc_cents"], 0)
        self.assertGreater(con["risparmio_guest_cents"], senza["risparmio_guest_cents"])

    def test_risparmio_bps(self):
        c = confronta_guest(10000)
        self.assertEqual(c["risparmio_bps"], 3110 * 10000 // 13110)   # 0% ospite -> risparmio maggiore

    def test_zero_failclosed(self):
        c = confronta_guest(0)
        self.assertEqual(c["risparmio_guest_cents"], 0)
        c2 = confronta_guest("x")
        self.assertEqual(c2["ota_totale_cents"], 0)

    def test_politica_custom(self):
        pol = PoliticaConfrontoGuest(ota_markup_host_bps=2500, ota_guest_fee_bps=1500,
                                     nostra_guest_fee_bps=1000)
        c = confronta_guest(10000, pol=pol)
        self.assertGreater(c["risparmio_guest_cents"], 0)

    def test_cents_interi(self):
        c = confronta_guest(9999, valuta_diversa=True)
        for v in c.values():
            self.assertIsInstance(v, int)


# ═══════════════════════════════════════════════════════════════════════════════════════
# I 2 PUNTI SOPRAVVISSUTI DELLA NOTTE FRA IL 6 E IL 7 SETTEMBRE 2026 (Giudice, Blocco 4)
# ═══════════════════════════════════════════════════════════════════════════════════════

class TestI2PuntiSopravvissutiDellaNotteDel7Settembre(unittest.TestCase):
    """Il Giudice (giudice_notte_blocchi_4_7) ha trovato 2 punti: il `frozen` della
    politica e il filtro `_i` sullo zero. Il secondo (`v >= 0` -> `v > 0`) cambia SOLO
    l'ingresso 0, e per 0 entrambe le versioni rispondono 0: la guardia documenta il
    contratto ma non puo' ucciderlo (vedi consegna)."""

    def test_riga15_PoliticaConfrontoGuest_e_congelata(self):
        p = PoliticaConfrontoGuest()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            p.nostra_guest_fee_bps = 5000
        self.assertEqual(hash(PoliticaConfrontoGuest()), hash(p))

    def test_riga24_il_filtro_degli_interi_azzera_negativi_booleani_e_tipi_storti(self):
        self.assertEqual(0, _i(0))
        self.assertEqual(0, _i(-1))
        self.assertEqual(0, _i(True))
        self.assertEqual(0, _i("5"))
        self.assertEqual(5, _i(5))
        self.assertEqual(0, confronta_guest(-100)["ota_totale_cents"])
        self.assertEqual(0, confronta_guest(True)["ota_totale_cents"])


if __name__ == "__main__":
    unittest.main()
