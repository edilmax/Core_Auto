"""
Suite di SOPRAVVIVENZA TOTALE per M4 (fase46) - Manifesto dell'Eternita'.
CHAOS (proprieta' corrotta, fonte illecita, dati malformati), ISOLAMENTO FRATTALE
(una fonte che esplode non ferma le altre), FUZZING (score int>=0, ranking stabile),
IDEMPOTENZA.
"""
import random
import unittest

from fase46_esploratore import (
    Proprieta, PainScoreMultifattore, StubFonteProprieta, MotoreEsploratore,
    crea_esploratore)


def _p(id, prezzo=20_000, pren=30, dip=50, lecita=True):
    return Proprieta(id, "H" + id, prezzo, 1800, pren, dip, fonte_lecita=lecita)


class TestChaosEsploratore(unittest.TestCase):
    def test_proprieta_corrotta_rifiutata(self):
        for kw in (dict(id="", nome="x", prezzo_ota_cents=1, comm_ota_bps=1800,
                        prenotazioni_mese=1, dipendenza_ota=50),
                   dict(id="a", nome="x", prezzo_ota_cents=-1, comm_ota_bps=1800,
                        prenotazioni_mese=1, dipendenza_ota=50),
                   dict(id="a", nome="x", prezzo_ota_cents=1, comm_ota_bps=10_000,
                        prenotazioni_mese=1, dipendenza_ota=50),
                   dict(id="a", nome="x", prezzo_ota_cents=1, comm_ota_bps=1800,
                        prenotazioni_mese=1, dipendenza_ota=101),
                   dict(id="a", nome="x", prezzo_ota_cents=1.5, comm_ota_bps=1800,
                        prenotazioni_mese=1, dipendenza_ota=50)):
            with self.assertRaises(ValueError):
                Proprieta(**kw)

    def test_fonte_illecita_zero_dati(self):
        mot = crea_esploratore()
        out = mot.esplora([StubFonteProprieta("booking_scrape", [_p("x")], _lecita=False)])
        self.assertEqual(out, [])


class TestIsolamentoFrattaleEsploratore(unittest.TestCase):
    def test_fonte_che_esplode_non_ferma_le_altre(self):
        mot = crea_esploratore()
        buona = StubFonteProprieta("sito_host", [_p("a"), _p("b")])
        rotta = StubFonteProprieta("api_giu", _errore=TimeoutError("rete interrotta"))
        altra = StubFonteProprieta("ical", [_p("c")])
        out = mot.esplora([buona, rotta, altra])               # la rotta in mezzo
        self.assertEqual(sorted(s.proprieta.id for s in out), ["a", "b", "c"])  # le altre OK


class TestFuzzingEsploratore(unittest.TestCase):
    def test_fuzz_score_e_ranking(self):
        mot = crea_esploratore()
        rng = random.Random(46)
        props = []
        for i in range(5000):
            props.append(_p(str(i), rng.randint(0, 10**9), rng.randint(0, 10**5),
                            rng.randint(0, 100)))
        out = mot.classifica(props)
        for s in out:
            self.assertIsInstance(s.pain_score, int)
            self.assertGreaterEqual(s.pain_score, 0)
            self.assertGreaterEqual(s.perdita_annua_cents, 0)
        # ranking ordinato decrescente per pain
        self.assertEqual([s.pain_score for s in out],
                         sorted((s.pain_score for s in out), reverse=True))


class TestIdempotenzaEsploratore(unittest.TestCase):
    def test_classifica_idempotente(self):
        mot = crea_esploratore()
        props = [_p("a", 30_000, 40, 70), _p("b", 30_000, 40, 70), _p("c", 9_000, 10, 20)]
        a = [(s.proprieta.id, s.pain_score) for s in mot.classifica(props)]
        b = [(s.proprieta.id, s.pain_score) for s in mot.classifica(props)]
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
