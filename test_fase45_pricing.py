"""
Test funzionali del motore delle proposte del Core (fase45, M3) - split a 3 vie
vincitore. Fonde M1 (commissione) + M2 (prezzo host). Verifica conservazione,
flywheel (guest risparmia + host guadagna + Mango quota), e i circuit breaker.
"""
import unittest

from fase43_commissione import (ConfigMotore, PoliticaRanaInversa, MetricheHost,
                                Giurisdizione)
from fase44_prezzo import PoliticaPrezzoHostAuthoritative, ContestoPrezzo
from fase45_pricing import (PoliticaSplit3Vie, ContestoProposta, MotoreProposte,
                            CircuitBreakerProposta, ripartisci_esatto,
                            politica_split_da_config)


def _motore(split=None, comm_pol=None):
    pol = comm_pol or PoliticaRanaInversa()
    cfg = ConfigMotore("mango", pol, Giurisdizione())
    return MotoreProposte(cfg, split or PoliticaSplit3Vie(),
                          PoliticaPrezzoHostAuthoritative()), pol


def _stato(pol):
    return pol.evolvi(pol.stato_iniziale(), MetricheHost(1, 0, 0))


class TestSplitEsatto(unittest.TestCase):
    def test_conserva_ogni_centesimo(self):
        for tot in (0, 1, 2, 3, 7, 999, 100_001):
            parti = ripartisci_esatto(tot, (4000, 4000, 2000))
            self.assertEqual(sum(parti), tot)
            self.assertTrue(all(p >= 0 for p in parti))

    def test_split_invalido_rifiutato(self):
        with self.assertRaises(ValueError):
            PoliticaSplit3Vie(5000, 4000, 2000)         # non somma 10000


class TestComposizione(unittest.TestCase):
    def test_conservazione_e_flywheel(self):
        mot, pol = _motore()
        ctx_p = ContestoProposta(100_000, 1800)
        ctx_prezzo = ContestoPrezzo(85_000, floor_host_cents=80_000)
        p = mot.componi(ctx_p, _stato(pol), MetricheHost(1, 0, 0), ctx_prezzo)
        # conservazione
        self.assertEqual(p.prezzo_guest_cents, p.netto_host_cents + p.incasso_mango_cents)
        # flywheel: tutti e tre vincono
        self.assertGreater(p.risparmio_guest_cents, 0)      # guest risparmia
        self.assertGreater(p.guadagno_host_cents, 0)        # host guadagna
        self.assertGreater(p.incasso_mango_cents, 0)        # Mango incassa
        # surplus = C_ota(18000) - C_mango(3% pioniere = 3000) = 15000
        self.assertEqual(p.surplus_cents, 15_000)
        self.assertLessEqual(p.prezzo_guest_cents, p.prezzo_ota_cents)

    def test_breaker_mango_non_competitivo(self):
        # OTA commissione 1% < Mango 3% pioniere -> S<0 -> BLOCCO
        mot, pol = _motore()
        ctx_p = ContestoProposta(100_000, 100)
        ctx_prezzo = ContestoPrezzo(85_000, floor_host_cents=80_000)
        with self.assertRaises(CircuitBreakerProposta):
            mot.componi(ctx_p, _stato(pol), MetricheHost(1, 0, 0), ctx_prezzo)

    def test_breaker_host_sotto_floor(self):
        mot, pol = _motore()
        ctx_p = ContestoProposta(100_000, 1800)
        ctx_prezzo = ContestoPrezzo(95_000, floor_host_cents=95_000)   # floor troppo alto
        with self.assertRaises(CircuitBreakerProposta):
            mot.componi(ctx_p, _stato(pol), MetricheHost(1, 0, 0), ctx_prezzo)

    def test_iniezione_split_diverso(self):
        ctx_p = ContestoProposta(100_000, 1800)
        ctx_prezzo = ContestoPrezzo(85_000, floor_host_cents=70_000)
        mot_a, pa = _motore(PoliticaSplit3Vie(8000, 1000, 1000))   # pro-guest
        mot_b, pb = _motore(PoliticaSplit3Vie(1000, 8000, 1000))   # pro-host
        pa_ = mot_a.componi(ctx_p, _stato(pa), MetricheHost(1, 0, 0), ctx_prezzo)
        pb_ = mot_b.componi(ctx_p, _stato(pb), MetricheHost(1, 0, 0), ctx_prezzo)
        self.assertGreater(pa_.risparmio_guest_cents, pb_.risparmio_guest_cents)
        self.assertGreater(pb_.guadagno_host_cents, pa_.guadagno_host_cents)

    def test_factory_split(self):
        s = politica_split_da_config({"quota_guest_bps": 5000, "quota_host_bps": 3000,
                                      "quota_mango_bps": 2000})
        self.assertEqual(s.quote(), (5000, 3000, 2000))


if __name__ == "__main__":
    unittest.main()
