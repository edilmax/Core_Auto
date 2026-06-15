"""
Suite di SOPRAVVIVENZA TOTALE per M3 (fase45) - Manifesto dell'Eternita'.
CHAOS (input corrotti, breaker Mango-non-competitivo, breaker host-sotto-floor),
FUZZING (conservazione + nessuno peggio dell'OTA su scenari estremi),
ISOLAMENTO FRATTALE (policy commerciale rotta non contagia), IDEMPOTENZA.
"""
import random
import unittest

from fase43_commissione import (ConfigMotore, PoliticaRanaInversa, PoliticaCommerciale,
                                MetricheHost, StatoCommissione, Giurisdizione)
from fase44_prezzo import PoliticaPrezzoHostAuthoritative, ContestoPrezzo
from fase45_pricing import (PoliticaSplit3Vie, ContestoProposta, MotoreProposte,
                            CircuitBreakerProposta, ripartisci_esatto)


def _motore(split=None, comm_pol=None):
    pol = comm_pol or PoliticaRanaInversa()
    cfg = ConfigMotore("mango", pol, Giurisdizione())
    return MotoreProposte(cfg, split or PoliticaSplit3Vie(),
                          PoliticaPrezzoHostAuthoritative()), pol


class TestChaosProposta(unittest.TestCase):
    def test_contesto_corrotto_rifiutato(self):
        for kw in (dict(prezzo_ota_cents=-1, comm_ota_bps=1800),
                   dict(prezzo_ota_cents=1.5, comm_ota_bps=1800),
                   dict(prezzo_ota_cents=10_000, comm_ota_bps=10_000),
                   dict(prezzo_ota_cents=10_000, comm_ota_bps=-1)):
            with self.assertRaises(ValueError):
                ContestoProposta(**kw)

    def test_breaker_mango_non_competitivo(self):
        mot, pol = _motore()
        st = pol.evolvi(pol.stato_iniziale(), MetricheHost(1, 0, 0))
        with self.assertRaises(CircuitBreakerProposta):
            mot.componi(ContestoProposta(100_000, 100), st, MetricheHost(1, 0, 0),
                        ContestoPrezzo(85_000, floor_host_cents=80_000))

    def test_breaker_host_sotto_floor(self):
        mot, pol = _motore()
        st = pol.evolvi(pol.stato_iniziale(), MetricheHost(1, 0, 0))
        with self.assertRaises(CircuitBreakerProposta):
            mot.componi(ContestoProposta(100_000, 1800), st, MetricheHost(1, 0, 0),
                        ContestoPrezzo(99_000, floor_host_cents=99_000))


class TestFuzzingProposta(unittest.TestCase):
    def test_fuzz_conservazione_e_nessuno_peggio(self):
        mot, pol = _motore()
        st = pol.evolvi(pol.stato_iniziale(), MetricheHost(60, 200, 20))   # host fedele
        rng = random.Random(45)
        casi = 0
        for _ in range(8000):
            P_o = rng.randint(5_000, 10**9)
            ctx_p = ContestoProposta(P_o, 1800)
            ctx_prezzo = ContestoPrezzo(P_o, floor_host_cents=0)   # floor 0: non blocca
            try:
                p = mot.componi(ctx_p, st, MetricheHost(60, 200, 20), ctx_prezzo)
            except CircuitBreakerProposta:
                continue
            # conservazione esatta
            self.assertEqual(p.prezzo_guest_cents, p.netto_host_cents + p.incasso_mango_cents)
            # nessuno peggio dell'OTA
            self.assertLessEqual(p.prezzo_guest_cents, p.prezzo_ota_cents)
            self.assertGreaterEqual(p.risparmio_guest_cents, 0)
            self.assertGreaterEqual(p.guadagno_host_cents, 0)
            self.assertGreaterEqual(p.incasso_mango_cents, 0)
            casi += 1
        self.assertGreater(casi, 0)

    def test_fuzz_split_esatto(self):
        rng = random.Random(7)
        for _ in range(20000):
            tot = rng.randint(0, 10**9)
            a = rng.randint(0, 10000)
            b = rng.randint(0, 10000 - a)
            c = 10000 - a - b
            parti = ripartisci_esatto(tot, (a, b, c))
            self.assertEqual(sum(parti), tot)              # conserva ogni centesimo


class TestIsolamentoIdempotenza(unittest.TestCase):
    def test_policy_commerciale_rotta_non_contagia(self):
        class PoliticaEsplosiva(PoliticaCommerciale):
            def stato_iniziale(self): return StatoCommissione(700)
            def evolvi(self, s, m): return s
            def commissione_cents(self, t, s, m): raise RuntimeError("rotta")
            def descrizione(self): return "x"

        cfg_rotto = ConfigMotore("rotto", PoliticaEsplosiva(), datastore_namespace="r")
        mot_rotto = MotoreProposte(cfg_rotto, PoliticaSplit3Vie(),
                                   PoliticaPrezzoHostAuthoritative())
        with self.assertRaises(RuntimeError):
            mot_rotto.componi(ContestoProposta(100_000, 1800), StatoCommissione(700),
                              MetricheHost(1, 0, 0), ContestoPrezzo(85_000, floor_host_cents=0))
        # il motore sano accanto resta operativo
        mot_sano, pol = _motore()
        st = pol.evolvi(pol.stato_iniziale(), MetricheHost(1, 0, 0))
        p = mot_sano.componi(ContestoProposta(100_000, 1800), st, MetricheHost(1, 0, 0),
                             ContestoPrezzo(85_000, floor_host_cents=0))
        self.assertEqual(p.surplus_cents, 15_000)

    def test_idempotenza(self):
        mot, pol = _motore()
        st = pol.evolvi(pol.stato_iniziale(), MetricheHost(30, 40, 5))
        args = (ContestoProposta(100_000, 1800), st, MetricheHost(30, 40, 5),
                ContestoPrezzo(85_000, floor_host_cents=70_000))
        self.assertEqual(mot.componi(*args), mot.componi(*args))


if __name__ == "__main__":
    unittest.main()
