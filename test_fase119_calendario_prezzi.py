"""Test Fase 119 - Calendario prezzi visuale. Provider iniettato: nessun DB."""
import unittest

from fase119_calendario_prezzi import (calendario_html, costruisci_calendario)


def stato_finto(slug, g):
    if g == "2026-08-08":                                  # sabato agosto, prenotato
        return {"prezzo_netto_cents": 10000, "unita": 1, "venduto": 1}
    if g == "2026-08-09":
        return {"prezzo_netto_cents": 10000, "unita": 2, "venduto": 0}
    return {}                                              # non aperto


def stato_reale(slug, g):
    """Chiavi ESATTE di fase58.stato_giorno (riga DB): unita_occupate/chiuso,
    MAI venduto/occupati. Il vecchio finto mascherava il bug #33."""
    righe = {
        "2026-08-08": {"prezzo_netto_cents": 10000, "unita_totali": 1,
                       "unita_occupate": 1, "chiuso": 0, "min_notti": 1},
        "2026-08-09": {"prezzo_netto_cents": 10000, "unita_totali": 2,
                       "unita_occupate": 0, "chiuso": 0, "min_notti": 1},
        "2026-08-10": {"prezzo_netto_cents": 10000, "unita_totali": 1,
                       "unita_occupate": 0, "chiuso": 1, "min_notti": 1},
        "2026-08-11": {"prezzo_netto_cents": 0, "unita_totali": 0,
                       "unita_occupate": 0, "chiuso": 1, "min_notti": 1},
        "2026-08-12": {"prezzo_netto_cents": 10000, "unita_totali": 1,
                       "unita_occupate": 1, "chiuso": 1, "min_notti": 1},
    }
    return righe.get(g)


class TestContrattoProviderReale(unittest.TestCase):
    """Bug #33 (provato live): col provider reale un giorno PIENO appariva
    'libero' e un giorno CHIUSO appariva 'libero' con prezzo suggerito."""

    def test_pieno_e_chiuso_col_provider_reale(self):
        c = costruisci_calendario("casa", "2026-08-08", "2026-08-12",
                                  stato_giorno=stato_reale)
        stati = {x["giorno"]: x["stato"] for x in c}
        self.assertEqual(stati["2026-08-08"], "prenotato")
        self.assertEqual(stati["2026-08-09"], "libero")
        self.assertEqual(stati["2026-08-10"], "chiuso")
        self.assertEqual(stati["2026-08-11"], "chiuso")   # chiuso senza prezzo
        # bug #35: VENDUTA vince su CHIUSA (mai nascondere una prenotazione viva)
        self.assertEqual(stati["2026-08-12"], "prenotato")

    def test_chiuso_senza_prezzo_niente_prezzi(self):
        c = costruisci_calendario("casa", "2026-08-11", "2026-08-11",
                                  stato_giorno=stato_reale)
        self.assertIsNone(c[0]["prezzo_cents"])
        self.assertIsNone(c[0]["prezzo_dinamico_cents"])

    def test_chiuso_con_prezzo_mantiene_il_prezzo(self):
        c = costruisci_calendario("casa", "2026-08-10", "2026-08-10",
                                  stato_giorno=stato_reale)
        self.assertEqual(c[0]["stato"], "chiuso")
        self.assertEqual(c[0]["prezzo_cents"], 10000)


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
