"""
Test funzionali dell'Esploratore del Core (fase46, M4). Pain-score multifattore
vincente, ordinamento lead, Escape Analysis (perdita annua), compliance, iniezione.
"""
import unittest

from fase46_esploratore import (
    Proprieta, PainScoreMultifattore, PoliticaPainScore, ScoredProprieta,
    StubFonteProprieta, MotoreEsploratore, crea_esploratore)


def _p(id, prezzo=20_000, pren=30, dip=50, lecita=True):
    return Proprieta(id, "Hotel " + id, prezzo, 1800, pren, dip, fonte_lecita=lecita)


class TestPainScore(unittest.TestCase):
    def test_perdita_annua_escape_analysis(self):
        # 20000 * 18% = 3600 ; * 30 pren * 12 mesi = 1.296.000 cent
        self.assertEqual(_p("a").perdita_annua_cents(), 3600 * 30 * 12)

    def test_score_multifattore(self):
        s = PainScoreMultifattore()
        self.assertEqual(s.score(_p("a", dip=50)), _p("a").perdita_annua_cents() * 50 // 100)

    def test_lead_caldo_prima(self):
        mot = crea_esploratore()
        caldo = _p("caldo", prezzo=200_000, pren=150, dip=95)
        freddo = _p("freddo", prezzo=6_000, pren=120, dip=10)
        out = mot.classifica([freddo, caldo])
        self.assertEqual(out[0].proprieta.id, "caldo")
        self.assertGreater(out[0].pain_score, out[1].pain_score)


class TestEsplorazione(unittest.TestCase):
    def test_aggrega_da_piu_fonti(self):
        mot = crea_esploratore()
        f1 = StubFonteProprieta("sito_host", [_p("a"), _p("b")])
        f2 = StubFonteProprieta("metasearch", [_p("c")])
        out = mot.esplora([f1, f2])
        self.assertEqual(len(out), 3)

    def test_fonte_non_lecita_ignorata(self):
        mot = crea_esploratore()
        lecita = StubFonteProprieta("ok", [_p("a")])
        illecita = StubFonteProprieta("scraping_booking", [_p("b")], _lecita=False)
        out = mot.esplora([lecita, illecita])
        self.assertEqual([s.proprieta.id for s in out], ["a"])

    def test_proprieta_non_lecita_scartata(self):
        mot = crea_esploratore()
        f = StubFonteProprieta("mista", [_p("buono"), _p("cattivo", lecita=False)])
        out = mot.esplora([f])
        self.assertEqual([s.proprieta.id for s in out], ["buono"])

    def test_iniezione_painscore_diverso(self):
        class PainVolume(PoliticaPainScore):
            def score(self, p): return p.prenotazioni_mese
            def descrizione(self): return "volume"
        povero_ma_pieno = _p("vol", prezzo=5_000, pren=200, dip=10)
        ricco = _p("ricco", prezzo=300_000, pren=20, dip=90)
        multi = MotoreEsploratore(PainScoreMultifattore()).classifica([povero_ma_pieno, ricco])
        vol = MotoreEsploratore(PainVolume()).classifica([povero_ma_pieno, ricco])
        self.assertEqual(multi[0].proprieta.id, "ricco")      # multifattore: il ricco
        self.assertEqual(vol[0].proprieta.id, "vol")          # volume: il pieno


if __name__ == "__main__":
    unittest.main()
