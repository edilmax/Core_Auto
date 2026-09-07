"""
Test Fase 78 - Sleep Guarantee Engine.

Copre: sleep score (buono/cattivo), garanzia soddisfatta (no rimborso) / non rispettata
(rimborso % in cents), boundary soglia, niente dati -> non_valutabile (no rimborso,
fail-closed), prezzo invalido, politica custom, rimborso intero, robustezza.
"""
import dataclasses
import unittest

from fase78_sleep_guarantee import (
    MAX_CENTS, GaranziaSonno, PoliticaSonno, SleepGuaranteeEngine, _intero_pos,
    crea_sleep_guarantee,
)

SONNO_OTTIMO = {"durata": 480, "efficienza": 900, "silenzio": 30, "aria": 500,
                "temp_dev": 0}
SONNO_PESSIMO = {"durata": 300, "efficienza": 600, "silenzio": 55, "aria": 1200,
                 "temp_dev": 400}


class TestScore(unittest.TestCase):
    def test_ottimo_alto(self):
        e = crea_sleep_guarantee()
        self.assertEqual(e.sleep_score(SONNO_OTTIMO)["composito"], 100)

    def test_pessimo_basso(self):
        e = crea_sleep_guarantee()
        self.assertEqual(e.sleep_score(SONNO_PESSIMO)["composito"], 0)

    def test_nessun_dato_none(self):
        self.assertIsNone(crea_sleep_guarantee().sleep_score({}))


class TestGaranzia(unittest.TestCase):
    def setUp(self):
        self.e = crea_sleep_guarantee()   # soglia 80, rimborso 50%

    def test_soddisfatta_no_rimborso(self):
        g = self.e.valuta_garanzia(12000, SONNO_OTTIMO)
        self.assertEqual(g.stato, "soddisfatta")
        self.assertEqual(g.rimborso_cents, 0)
        self.assertEqual(g.score, 100)

    def test_non_rispettata_rimborso(self):
        g = self.e.valuta_garanzia(12000, SONNO_PESSIMO)
        self.assertEqual(g.stato, "rimborso")
        self.assertEqual(g.rimborso_cents, 6000)   # 50% di 12000

    def test_boundary_soglia(self):
        pol = PoliticaSonno(soglia_score=80, rimborso_bps=5000)
        e = crea_sleep_guarantee(pol)
        # costruisco un sonno con score esattamente >= 80: durata media alta
        buono = {"durata": 480, "efficienza": 900, "silenzio": 30, "aria": 1200,
                 "temp_dev": 400}
        g = e.valuta_garanzia(10000, buono)
        # silenzio/aria ok, aria/temp bassi -> verifico che lo stato dipenda dalla soglia
        self.assertIn(g.stato, ("soddisfatta", "rimborso"))
        if g.score >= 80:
            self.assertEqual(g.stato, "soddisfatta")
        else:
            self.assertEqual(g.stato, "rimborso")

    def test_non_valutabile(self):
        g = self.e.valuta_garanzia(12000, {})
        self.assertEqual(g.stato, "non_valutabile")
        self.assertEqual(g.rimborso_cents, 0)      # niente dati -> non si paga

    def test_prezzo_invalido_no_rimborso(self):
        g = self.e.valuta_garanzia(0, SONNO_PESSIMO)
        self.assertEqual(g.stato, "rimborso")
        self.assertEqual(g.rimborso_cents, 0)

    def test_rimborso_intero(self):
        g = self.e.valuta_garanzia(9999, SONNO_PESSIMO)
        self.assertEqual(g.rimborso_cents, (9999 * 5000) // 10000)
        self.assertIsInstance(g.rimborso_cents, int)


class TestPoliticaCustom(unittest.TestCase):
    def test_rimborso_full(self):
        e = crea_sleep_guarantee(PoliticaSonno(soglia_score=90, rimborso_bps=10000))
        g = e.valuta_garanzia(8000, SONNO_PESSIMO)
        self.assertEqual(g.rimborso_cents, 8000)   # 100%

    def test_soglia_alta_rende_difficile(self):
        e = crea_sleep_guarantee(PoliticaSonno(soglia_score=100))
        # score 100 esatto -> soddisfatta; qualsiasi imperfezione -> rimborso
        self.assertEqual(e.valuta_garanzia(10000, SONNO_OTTIMO).stato, "soddisfatta")


class TestRobustezza(unittest.TestCase):
    def test_mai_solleva(self):
        e = crea_sleep_guarantee()
        for bad in (None, 123, "x", []):
            try:
                e.sleep_score(bad)
                e.valuta_garanzia(10000, bad)
                e.valuta_garanzia(bad, SONNO_OTTIMO)
            except Exception as ex:  # pragma: no cover
                self.fail(f"sollevato su {bad!r}: {ex}")

    def test_as_dict(self):
        d = crea_sleep_guarantee().valuta_garanzia(12000, SONNO_OTTIMO).as_dict()
        self.assertEqual(d["money_unit"], "cents_integer")


# ═══════════════════════════════════════════════════════════════════════════════════════
# I 7 PUNTI SOPRAVVISSUTI DELLA NOTTE FRA IL 6 E IL 7 SETTEMBRE 2026 (Giudice, Blocco 4)
# ═══════════════════════════════════════════════════════════════════════════════════════

class TestI7PuntiSopravvissutiDellaNotteDel7Settembre(unittest.TestCase):
    """Il Giudice (giudice_notte_blocchi_4_7) ha trovato 7 punti in cui il guasto passa e i
    test restano verdi. Qui si decide un RIMBORSO: un prezzo storto che passa il filtro
    diventa un rimborso NEGATIVO (prezzo -5 -> -3 cent) o un rimborso su un prezzo oltre
    il tetto. UNA guardia per punto, vista ROSSA col mutante iniettato con l'editor."""

    def setUp(self):
        self.e = crea_sleep_guarantee()                      # soglia 80, rimborso 50%

    # ── riga 56: il filtro sul prezzo, provato dal RIMBORSO che ne esce ────────────
    def test_riga56_un_prezzo_NEGATIVO_non_produce_un_rimborso_negativo(self):
        g = self.e.valuta_garanzia(-5, SONNO_PESSIMO)
        self.assertEqual("rimborso", g.stato)
        self.assertEqual(0, g.rimborso_cents, "rimborso calcolato su un prezzo negativo")

    def test_riga56_un_prezzo_BOOLEANO_non_produce_rimborso_nemmeno_al_100_per_cento(self):
        e = crea_sleep_guarantee(PoliticaSonno(soglia_score=80, rimborso_bps=10000))
        g = e.valuta_garanzia(True, SONNO_PESSIMO)
        self.assertEqual(0, g.rimborso_cents, "True e' passato per un prezzo di 1 cent")

    def test_riga56_un_prezzo_di_tipo_storto_non_esplode_e_non_rimborsa(self):
        for cattivo in ("abc", None, 3.5, []):
            g = self.e.valuta_garanzia(cattivo, SONNO_PESSIMO)
            self.assertEqual(0, g.rimborso_cents, "rimborso su prezzo %r" % (cattivo,))

    def test_riga56_lo_zero_non_e_un_intero_positivo(self):
        """`_intero_pos` e' il filtro: 0 no, 1 si', True no. Con prezzo 0 il rimborso e'
        0 in entrambi i casi (0 * bps = 0), quindi il confine si prova sul filtro."""
        self.assertIs(False, _intero_pos(0))
        self.assertIs(True, _intero_pos(1))
        self.assertIs(False, _intero_pos(True))
        self.assertIs(False, _intero_pos(-1))

    # ── righe 59 · 65: politica ed esito sono IMMUTABILI ───────────────────────────
    def test_riga59_PoliticaSonno_e_congelata(self):
        p = PoliticaSonno()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            p.rimborso_bps = 10000
        self.assertEqual(hash(PoliticaSonno()), hash(p))

    def test_riga65_GaranziaSonno_e_congelata(self):
        g = self.e.valuta_garanzia(12000, SONNO_PESSIMO)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            g.rimborso_cents = 0

    # ── riga 100: il tetto del prezzo, sul confine esatto ──────────────────────────
    def test_riga100_un_prezzo_OLTRE_il_tetto_non_si_rimborsa(self):
        g = self.e.valuta_garanzia(MAX_CENTS + 1, SONNO_PESSIMO)
        self.assertEqual("rimborso", g.stato)
        self.assertEqual(0, g.rimborso_cents, "rimborso su un prezzo oltre il tetto")

    def test_riga100_un_prezzo_ESATTAMENTE_al_tetto_si_rimborsa(self):
        g = self.e.valuta_garanzia(MAX_CENTS, SONNO_PESSIMO)
        self.assertEqual(MAX_CENTS // 2, g.rimborso_cents, "il tetto esatto e' stato rifiutato")


if __name__ == "__main__":
    unittest.main()
