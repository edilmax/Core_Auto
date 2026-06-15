"""
Suite di SOPRAVVIVENZA TOTALE per M2 (fase44) - Manifesto dell'Eternita'.
CHAOS (rete OTA morta, corruzione, inventario fantasma, Price Circuit Breaker),
FUZZING (contesti random estremi, anti-inflazione OTA), ISOLAMENTO FRATTALE
(policy-prezzo rotta che non contagia, iniezione), IDEMPOTENZA (purezza).
"""
import random
import unittest

from fase44_prezzo import (
    ContestoPrezzo, EsitoPrezzo, PoliticaPrezzo, PoliticaPrezzoHostAuthoritative,
    PoliticaPrezzoFisso, CircuitBreakerPrezzo)


# ───────────────────────────── CHAOS ────────────────────────────────────────
class TestChaosPrezzo(unittest.TestCase):
    def setUp(self):
        self.pol = PoliticaPrezzoHostAuthoritative()

    def test_rete_ota_morta_vende_lo_stesso(self):
        # nessun dato OTA disponibile (rete OTA giu') -> Mango vende a tariffa host
        e = self.pol.risolvi(ContestoPrezzo(15_000, floor_host_cents=8_000,
                                            ota_confronto_cents=None))
        self.assertEqual((e.stato, e.prezzo_cents), ("ok", 15_000))

    def test_contesto_corrotto_rifiutato(self):
        for kw in (dict(tariffa_host_cents=-1),
                   dict(tariffa_host_cents=150.0),
                   dict(tariffa_host_cents=True),
                   dict(tariffa_host_cents=10_000, floor_host_cents=-5),
                   dict(tariffa_host_cents=10_000, ota_confronto_cents=9.9)):
            with self.assertRaises(ValueError):
                ContestoPrezzo(**kw)

    def test_inventario_fantasma_nosale(self):
        e = self.pol.risolvi(ContestoPrezzo(99_999, inventario_disponibile=False))
        self.assertEqual(e.stato, "nosale")

    def test_price_circuit_breaker_blocca_prezzo_folle(self):
        # tariffa host assurda (corruzione) oltre la banda di sicurezza -> HALT
        with self.assertRaises(CircuitBreakerPrezzo):
            self.pol.risolvi(ContestoPrezzo(10**9, floor_host_cents=8_000,
                                            prezzo_massimo_cents=50_000))

    def test_price_circuit_breaker_entro_banda_passa(self):
        e = self.pol.risolvi(ContestoPrezzo(40_000, floor_host_cents=8_000,
                                            prezzo_massimo_cents=50_000))
        self.assertEqual(e.prezzo_cents, 40_000)

    def test_banda_incoerente_rifiutata(self):
        with self.assertRaises(ValueError):
            ContestoPrezzo(10_000, floor_host_cents=8_000, prezzo_massimo_cents=5_000)


# ───────────────────────────── FUZZING ──────────────────────────────────────
class TestFuzzingPrezzo(unittest.TestCase):
    def setUp(self):
        self.pol = PoliticaPrezzoHostAuthoritative()

    def test_fuzz_contesti_estremi_invarianti(self):
        rng = random.Random(2024)
        for _ in range(5000):
            rate = rng.randint(0, 10**12)
            floor = rng.randint(0, 30_000)
            ctx = ContestoPrezzo(
                rate, floor_host_cents=floor,
                inventario_disponibile=rng.random() > 0.15,
                ota_confronto_cents=rng.choice([None, rng.randint(0, 10**12)]),
                confronto_stantio=rng.random() < 0.2)
            e = self.pol.risolvi(ctx)
            if e.stato == "ok":
                self.assertIsInstance(e.prezzo_cents, int)
                self.assertGreaterEqual(e.prezzo_cents, floor)          # floor sempre
                self.assertEqual(e.prezzo_cents, max(rate, floor))      # mai inflazione OTA

    def test_fuzz_anti_inflazione_ota(self):
        # l'OTA, per quanto selvaggia, NON deve mai muovere il prezzo transazionale
        rng = random.Random(7)
        for _ in range(3000):
            rate = rng.randint(8_000, 26_000)
            base = self.pol.risolvi(ContestoPrezzo(rate, floor_host_cents=8_000))
            con_ota = self.pol.risolvi(ContestoPrezzo(
                rate, floor_host_cents=8_000, ota_confronto_cents=rng.randint(0, 10**9)))
            self.assertEqual(base.prezzo_cents, con_ota.prezzo_cents)


# ─────────────────── ISOLAMENTO FRATTALE / AUTOPRESERVAZIONE ─────────────────
class TestIsolamentoFrattalePrezzo(unittest.TestCase):
    def test_policy_prezzo_rotta_non_contagia(self):
        class PoliticaEsplosiva(PoliticaPrezzo):
            def risolvi(self, ctx):
                raise RuntimeError("policy prezzo difettosa")
            def descrizione(self):
                return "esplosiva"

        ctx = ContestoPrezzo(15_000, floor_host_cents=8_000)
        with self.assertRaises(RuntimeError):                  # la rotta fallisce...
            PoliticaEsplosiva().risolvi(ctx)
        # ...la sana accanto resta perfettamente operativa (isolamento per purezza)
        sana = PoliticaPrezzoHostAuthoritative().risolvi(ctx)
        self.assertEqual(sana.prezzo_cents, 15_000)

    def test_iniezione_host_vs_fisso(self):
        ctx = ContestoPrezzo(15_000, floor_host_cents=8_000)
        host = PoliticaPrezzoHostAuthoritative().risolvi(ctx).prezzo_cents
        fisso = PoliticaPrezzoFisso(prezzo_cents=5_000).risolvi(ctx).prezzo_cents
        self.assertNotEqual(host, fisso)


# ───────────────────────────── IDEMPOTENZA ──────────────────────────────────
class TestIdempotenzaPrezzo(unittest.TestCase):
    def test_risolvi_idempotente(self):
        pol = PoliticaPrezzoHostAuthoritative()
        rng = random.Random(11)
        for _ in range(2000):
            ctx = ContestoPrezzo(rng.randint(0, 10**9), floor_host_cents=rng.randint(0, 20_000),
                                 ota_confronto_cents=rng.choice([None, rng.randint(0, 10**9)]))
            self.assertEqual(pol.risolvi(ctx), pol.risolvi(ctx))     # stesso ctx -> stesso esito


if __name__ == "__main__":
    unittest.main()
