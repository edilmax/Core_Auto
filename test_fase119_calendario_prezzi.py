"""Test Fase 119 - Calendario prezzi visuale. Provider iniettato: nessun DB."""
import unittest

from fase119_calendario_prezzi import (calendario_html, costruisci_calendario)


def stato_finto(slug, g):
    if g == "2026-08-08":                                  # sabato agosto, prenotato
        return {"prezzo_netto_cents": 10000, "unita": 1, "venduto": 1}
    if g == "2026-08-09":
        return {"prezzo_netto_cents": 10000, "unita": 2, "venduto": 0}
    return {}                                              # non aperto


class TestCalendario(unittest.TestCase):
    def test_celle_per_giorno(self):
        c = costruisci_calendario("casa", "2026-08-08", "2026-08-10",
                                  stato_giorno=stato_finto, occupazione_bps=5000)
        self.assertEqual(len(c), 3)
        self.assertEqual(c[0]["stato"], "prenotato")
        self.assertEqual(c[1]["stato"], "libero")
        self.assertEqual(c[2]["stato"], "non_aperto")

    def test_prezzo_dinamico_applicato(self):
        c = costruisci_calendario("casa", "2026-08-09", "2026-08-09",
                                  stato_giorno=stato_finto, occupazione_bps=5000)
        # 2026-08-09 domenica, agosto 13000 -> 10000*1.3 = 13000
        self.assertEqual(c[0]["prezzo_cents"], 10000)
        self.assertEqual(c[0]["prezzo_dinamico_cents"], 13000)

    def test_range_invalido_vuoto(self):
        self.assertEqual(costruisci_calendario("c", "2026-08-10", "2026-08-01",
                         stato_giorno=stato_finto), [])

    def test_provider_solleva_cella_errore(self):
        def boom(s, g):
            raise RuntimeError("db giu")
        c = costruisci_calendario("c", "2026-08-08", "2026-08-08", stato_giorno=boom)
        self.assertEqual(c[0]["stato"], "errore")

    def test_html_xss_safe(self):
        celle = [{"giorno": "2026-08-08", "stato": "libero",
                  "prezzo_dinamico_cents": 13000}]
        h = calendario_html(celle)
        self.assertIn("<table", h)
        self.assertIn("€130.00", h)

    def test_html_non_aperto(self):
        h = calendario_html([{"giorno": "2026-08-08", "stato": "non_aperto",
                              "prezzo_dinamico_cents": None}])
        self.assertIn("-", h)


if __name__ == "__main__":
    unittest.main()
