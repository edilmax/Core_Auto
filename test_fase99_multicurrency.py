"""Test Fase 99 - Multi-Currency Ledger. Puro; tasso iniettato (no rete)."""
import unittest
from decimal import Decimal

from fase99_multicurrency import (Denaro, ProviderTassi, converti,
                                  crea_provider_tassi, denaro_da_maggiore,
                                  esponente, ripartisci_pagamento)


class TestDenaro(unittest.TestCase):
    def test_costruzione_e_normalizza_valuta(self):
        d = Denaro(10000, "usd")
        self.assertEqual(d.valuta, "USD")
        self.assertEqual(d.minori, 10000)

    def test_float_rifiutato(self):
        with self.assertRaises(TypeError):
            Denaro(100.0, "EUR")

    def test_valuta_invalida(self):
        with self.assertRaises(ValueError):
            Denaro(100, "EURO")

    def test_mix_valute_vietato(self):
        with self.assertRaises(ValueError):
            Denaro(100, "USD").somma(Denaro(100, "EUR"))
        with self.assertRaises(ValueError):
            Denaro(100, "USD").sottrai(Denaro(50, "JPY"))

    def test_somma_sottrai_stessa_valuta(self):
        self.assertEqual(Denaro(100, "USD").somma(Denaro(50, "USD")).minori, 150)
        self.assertEqual(Denaro(100, "USD").sottrai(Denaro(30, "USD")).minori, 70)

    def test_esponente_per_valuta(self):
        self.assertEqual(esponente("JPY"), 0)
        self.assertEqual(esponente("BHD"), 3)
        self.assertEqual(esponente("USD"), 2)

    def test_formatta(self):
        self.assertEqual(Denaro(10000, "USD").formatta(), "100.00 USD")
        self.assertEqual(Denaro(1000, "JPY").formatta(), "1000 JPY")
        self.assertEqual(Denaro(1234, "BHD").formatta(), "1.234 BHD")
        self.assertEqual(Denaro(5, "USD").formatta(), "0.05 USD")

    def test_da_maggiore_half_up(self):
        self.assertEqual(denaro_da_maggiore("100.00", "USD").minori, 10000)
        self.assertEqual(denaro_da_maggiore("100.005", "USD").minori, 10001)   # HALF_UP
        self.assertEqual(denaro_da_maggiore("1000", "JPY").minori, 1000)
        with self.assertRaises(TypeError):
            denaro_da_maggiore(100.0, "USD")                                   # no float


class TestLikeForLike(unittest.TestCase):
    def test_split_nella_valuta_annuncio(self):
        r = ripartisci_pagamento(Denaro(10000, "USD"))     # $100, no conversione
        self.assertEqual(r["host_fee"].formatta(), "2.00 USD")
        self.assertEqual(r["guest_fee"].formatta(), "8.00 USD")
        self.assertEqual(r["nostra_commissione"].minori, 1000)
        self.assertEqual(r["netto_host"].minori, 9800)
        self.assertEqual(r["totale_ospite"].minori, 10800)
        for v in r.values():
            self.assertEqual(v.valuta, "USD")              # tutto USD, like-for-like

    def test_conservazione_esatta_multivaluta(self):
        for val in ("USD", "EUR", "JPY", "BHD"):
            r = ripartisci_pagamento(Denaro(12345, val))
            # nostra commissione = totale ospite - netto host (stessa valuta)
            diff = r["totale_ospite"].sottrai(r["netto_host"])
            self.assertEqual(diff.minori, r["nostra_commissione"].minori)


class TestConversioneTrasparente(unittest.TestCase):
    def test_markup_esplicito(self):
        # 100 USD -> EUR, mid 0.90, markup 1%
        r = converti(Denaro(10000, "USD"), "EUR", "0.90", markup_bps=100)
        self.assertEqual(r["destinazione_mid"].minori, 9000)        # 90.00 mid
        self.assertEqual(r["destinazione_cliente"].minori, 9090)    # +1% markup
        self.assertEqual(r["nostro_markup"].minori, 90)             # 0.90 EUR esplicito
        self.assertEqual(r["nostro_markup"].valuta, "EUR")

    def test_tasso_invalido(self):
        with self.assertRaises(ValueError):
            converti(Denaro(100, "USD"), "EUR", "0")
        with self.assertRaises(ValueError):
            converti(Denaro(100, "USD"), "EUR", "abc")

    def test_zero_markup(self):
        r = converti(Denaro(10000, "USD"), "EUR", "1.0", markup_bps=0)
        self.assertEqual(r["destinazione_cliente"].minori, r["destinazione_mid"].minori)
        self.assertEqual(r["nostro_markup"].minori, 0)

    def test_converti_verso_valuta_0_decimali(self):
        """MICRO-STEPPING Flow 2: convertire VERSO lo yen (0 decimali). `converti` usa
        l'esponente della DESTINAZIONE per scalare: qui dev'essere 1 (non 100). Se qualcuno
        inchiodasse il fattore a `Decimal(100)` come per l'euro, l'importo mandato a Stripe
        sarebbe ¥ x100 e nessun test (tutti su destinazioni a 2 decimali) se ne accorgerebbe.
        VISTO ROSSO col mutante `fattore = Decimal(100)`."""
        r = converti(Denaro(10000, "USD"), "JPY", "150.0", markup_bps=100)  # $100 -> yen
        self.assertEqual(r["destinazione_mid"].minori, 15000)               # 100*150, esp 0
        self.assertEqual(r["destinazione_mid"].formatta(), "15000 JPY")     # niente decimali
        self.assertEqual(r["destinazione_cliente"].minori, 15150)           # +1%
        self.assertEqual(r["nostro_markup"].minori, 150)
        self.assertEqual(r["nostro_markup"].valuta, "JPY")

    def test_converti_verso_valuta_3_decimali(self):
        """MICRO-STEPPING Flow 2: convertire VERSO il dinaro kuwaitiano/bahreinita (3 decimali).
        Il fattore dev'essere 1000: col mutante `Decimal(100)` l'importo uscirebbe /10 (mid
        3000 invece di 30000). VISTO ROSSO col mutante."""
        r = converti(Denaro(10000, "USD"), "KWD", "0.30", markup_bps=100)   # $100 -> KWD
        self.assertEqual(r["destinazione_mid"].minori, 30000)               # 30.000 KWD (esp 3)
        self.assertEqual(r["destinazione_mid"].formatta(), "30.000 KWD")
        self.assertEqual(r["destinazione_cliente"].minori, 30300)           # 30.300 KWD (+1%)
        self.assertEqual(r["nostro_markup"].minori, 300)                    # 0.300 KWD
        b = converti(Denaro(10000, "USD"), "BHD", "0.376", markup_bps=100)  # anche BHD
        self.assertEqual(b["destinazione_mid"].formatta(), "37.600 BHD")

    def test_converti_3_decimali_half_up_e_mai_in_perdita(self):
        """MICRO-STEPPING Flow 2: la DIREZIONE dell'arrotondamento dentro `converti` a 3
        decimali (HALF_UP, non troncamento) + l'invariante-soldi: il cliente non paga MAI
        meno del mid (markup >= 0), altrimenti ci rimetteremmo noi sul cambio.
        1.2345 KWD -> 1234.5 millesimi -> HALF_UP -> 1235 (col troncamento sarebbe 1234)."""
        r = converti(Denaro(100, "USD"), "KWD", "1.2345", markup_bps=100)   # $1.00 -> KWD
        self.assertEqual(r["destinazione_mid"].minori, 1235)               # HALF_UP, non 1234
        self.assertGreaterEqual(r["nostro_markup"].minori, 0)              # mai in perdita
        self.assertEqual(r["destinazione_cliente"].minori,
                         r["destinazione_mid"].minori + r["nostro_markup"].minori)


class TestProviderTassi(unittest.TestCase):
    def test_gated_senza_app_id(self):
        self.assertIsNone(ProviderTassi("").tasso("USD", "EUR"))

    def test_cross_rate_via_usd(self):
        p = crea_provider_tassi("KEY", fetch=lambda url: {"base": "USD",
                                "rates": {"EUR": "0.90", "GBP": "0.80"}})
        # EUR per 1 GBP = rate[EUR]/rate[GBP] = 0.90/0.80 = 1.125
        self.assertEqual(p.tasso("GBP", "EUR"), Decimal("1.125"))
        self.assertEqual(p.tasso("USD", "EUR"), Decimal("0.90"))

    def test_isolato_su_errore(self):
        def boom(url):
            raise RuntimeError("oxr giu")
        self.assertIsNone(crea_provider_tassi("KEY", fetch=boom).tasso("USD", "EUR"))


if __name__ == "__main__":
    unittest.main()
