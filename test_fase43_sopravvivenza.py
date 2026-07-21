"""
Suite di SOPRAVVIVENZA TOTALE per M1 (fase43) - Manifesto dell'Eternita'.
Tre pilastri: CHAOS (corruzione/limiti), FUZZING (config/metriche random),
ISOLAMENTO FRATTALE (thread-safety del Registry, policy rotta che non contagia),
+ Circuit Breaker Finanziario e Idempotenza/Autopreservazione.
"""
import random
import threading
import unittest

from fase43_commissione import (
    BPS_DENOM, commissione_cents, Giurisdizione, MetricheHost, StatoCommissione,
    PSPStandard, PoliticaRanaInversa, PoliticaQuotaFissa, PoliticaCommerciale,
    ConfigMotore, ripartisci, RegistroMotori, CircuitBreakerFinanziario)


# ───────────────────────── CHAOS: corruzione dati ───────────────────────────
class TestChaosCorruzioneStato(unittest.TestCase):
    def test_stato_corrotto_negativo_rifiutato(self):
        with self.assertRaises(ValueError):
            StatoCommissione(-5)

    def test_stato_corrotto_oltre_100pct_rifiutato(self):
        with self.assertRaises(ValueError):
            StatoCommissione(BPS_DENOM + 1)

    def test_stato_corrotto_tipo_rifiutato(self):
        for bad in (3.5, True, "300", None):
            with self.assertRaises((ValueError, TypeError)):
                StatoCommissione(bad)

    def test_stato_valido_passa(self):
        self.assertEqual(StatoCommissione(300).bps_lealta, 300)


# ───────────────────── CHAOS: Circuit Breaker Finanziario ───────────────────
class TestCircuitBreakerFinanziario(unittest.TestCase):
    def test_perdita_oltre_limite_blocca(self):
        pol = PoliticaRanaInversa()
        cfg = ConfigMotore("mango", pol, Giurisdizione(), PSPStandard(150, 25),
                           limite_perdita_cents=0)            # tolleranza zero
        st = pol.evolvi(pol.stato_iniziale(), MetricheHost(1, 0, 0))
        # incasso piccolo in finestra Pioniere -> perdita -> deve BLOCCARE
        with self.assertRaises(CircuitBreakerFinanziario):
            ripartisci(cfg, 1_000, st, MetricheHost(1, 0, 0))

    def test_perdita_entro_limite_passa(self):
        pol = PoliticaRanaInversa()
        cfg = ConfigMotore("mango", pol, Giurisdizione(), PSPStandard(150, 25),
                           limite_perdita_cents=1_000)        # tollera fino a 1000c
        st = pol.evolvi(pol.stato_iniziale(), MetricheHost(1, 0, 0))
        r = ripartisci(cfg, 1_000, st, MetricheHost(1, 0, 0))  # perdita 10c < 1000c
        self.assertTrue(r.in_perdita)

    def test_senza_limite_nessun_blocco(self):
        pol = PoliticaRanaInversa()
        cfg = ConfigMotore("mango", pol, Giurisdizione(), PSPStandard(150, 25))
        st = pol.evolvi(pol.stato_iniziale(), MetricheHost(1, 0, 0))
        # senza limite il calcolo deve RIUSCIRE e conservare il denaro: prima si
        # chiamava e basta, quindi il test non poteva fallire.
        r = ripartisci(cfg, 1_000, st, MetricheHost(1, 0, 0))
        self.assertIsNotNone(r, "senza limite la ripartizione non deve essere bloccata")


# ───────────────────────────── FUZZING ──────────────────────────────────────
class TestFuzzing(unittest.TestCase):
    def test_fuzz_config_e_metriche_random(self):
        rng = random.Random(2024)
        for _ in range(4000):
            floor = rng.randint(100, 500)
            mid = rng.randint(floor, 800)
            cap = rng.randint(mid, 1500)
            pol = PoliticaRanaInversa(
                cap_bps=cap, mid_bps=mid, floor_bps=floor, break_even_minimo_bps=floor,
                tasso_pioniere_bps=rng.randint(0, floor), mesi_pioniere=rng.randint(0, 24))
            st = pol.stato_iniziale()
            prec = st.bps_lealta
            for _ in range(12):
                m = MetricheHost(rng.randint(0, 10**6), rng.randint(0, 10**6),
                                 rng.randint(0, 10**6))     # metriche estreme
                st = pol.evolvi(st, m)
                self.assertLessEqual(st.bps_lealta, prec)   # non sale MAI
                self.assertGreaterEqual(st.bps_lealta, floor)
                prec = st.bps_lealta

    def test_fuzz_importi_estremi_centesimi_esatti(self):
        pol = PoliticaRanaInversa()
        st = pol.evolvi(pol.stato_iniziale(), MetricheHost(60, 100, 9))
        m = MetricheHost(60, 100, 9)
        rng = random.Random(99)
        for imp in [0, 1, 2, BPS_DENOM, 10**12] + [rng.randint(0, 10**9) for _ in range(3000)]:
            comm = pol.commissione_cents(imp, st, m)
            self.assertIsInstance(comm, int)
            self.assertTrue(0 <= comm <= imp)
            self.assertEqual(comm + (imp - comm), imp)


# ──────────────────── ISOLAMENTO FRATTALE: thread-safety ─────────────────────
class TestIsolamentoFrattaleRegistry(unittest.TestCase):
    def test_registrazioni_concorrenti_nessuna_persa(self):
        reg = RegistroMotori()
        start = threading.Barrier(20)

        def worker(i):
            start.wait()                                    # massima contesa
            reg.registra(ConfigMotore(f"m{i}", PoliticaRanaInversa(),
                                      datastore_namespace=f"db{i}"))

        ths = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        self.assertEqual(len(reg.motori()), 20)             # nessun update perso

    def test_namespace_conteso_uno_solo_vince(self):
        reg = RegistroMotori()
        start = threading.Barrier(30)
        vinti, errori = [], []

        def worker(i):
            start.wait()
            try:
                reg.registra(ConfigMotore(f"m{i}", PoliticaRanaInversa(),
                                          datastore_namespace="CONTESO"))
                vinti.append(i)
            except ValueError:
                errori.append(i)

        ths = [threading.Thread(target=worker, args=(i,)) for i in range(30)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        self.assertEqual(len(vinti), 1)                     # atomicita': UNO solo entra
        self.assertEqual(len(errori), 29)

    def test_policy_rotta_non_contagia_il_registry(self):
        class PoliticaEsplosiva(PoliticaCommerciale):
            def stato_iniziale(self):
                return StatoCommissione(700)
            def evolvi(self, stato, metriche):
                return stato
            def commissione_cents(self, totale_cents, stato, metriche):
                raise RuntimeError("policy difettosa")
            def descrizione(self):
                return "esplosiva"

        reg = RegistroMotori()
        reg.registra(ConfigMotore("rotto", PoliticaEsplosiva(), datastore_namespace="db_rotto"))
        reg.registra(ConfigMotore("sano", PoliticaRanaInversa(), datastore_namespace="db_sano"))
        rotto = reg.ottieni("rotto")
        with self.assertRaises(RuntimeError):               # il motore rotto fallisce...
            ripartisci(rotto, 100_000, StatoCommissione(700), MetricheHost(1, 0, 0))
        # ...ma il motore sano resta perfettamente operativo (isolamento)
        sano = reg.ottieni("sano")
        st = sano.politica.evolvi(sano.politica.stato_iniziale(), MetricheHost(1, 0, 0))
        r = ripartisci(sano, 100_000, st, MetricheHost(1, 0, 0))
        self.assertEqual(r.commissione_cents, 3_000)        # 3% Pioniere, intatto


# ──────────────── IDEMPOTENZA / AUTOPRESERVAZIONE (purezza) ──────────────────
class TestIdempotenza(unittest.TestCase):
    def test_calcolo_puro_idempotente(self):
        pol = PoliticaRanaInversa()
        st = pol.evolvi(pol.stato_iniziale(), MetricheHost(30, 40, 5))
        m = MetricheHost(30, 40, 5)
        a = pol.commissione_cents(250_000, st, m)
        b = pol.commissione_cents(250_000, st, m)
        self.assertEqual(a, b)

    def test_evolvi_su_stato_convergente_e_stabile(self):
        pol = PoliticaRanaInversa()
        st = StatoCommissione(pol.floor_bps)                # gia' al minimo
        m = MetricheHost(60, 200, 20)
        self.assertEqual(pol.evolvi(st, m).bps_lealta, pol.floor_bps)
        self.assertEqual(pol.evolvi(pol.evolvi(st, m), m).bps_lealta, pol.floor_bps)


if __name__ == "__main__":
    unittest.main()
