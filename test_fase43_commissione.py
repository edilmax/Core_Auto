"""
Test del motore commissionale del Core (fase43) - prima pietra del Fractal Bridge.

Copre: impossibilita' matematica della risalita del cricchetto (carico estremo),
floor >= break-even (vincolo strutturale), Credito Pioniere a tempo, centesimi
esatti, PSP pass-through, jurisdiction-agnostic (default tassa 0 + shift), e i due
test d'architettura richiesti: INIEZIONE di policy diverse sullo stesso Core e
ISOLAMENTO del namespace datastore via Registry.
"""
import random
import unittest

from fase43_commissione import (
    BPS_DENOM, commissione_cents, Giurisdizione, MetricheHost, StatoCommissione,
    PSPStandard, PoliticaRanaInversa, PoliticaQuotaFissa, Ripartizione, ConfigMotore,
    ripartisci, RegistroMotori, giurisdizione_da_env, politica_da_config)


class TestCommissioneCents(unittest.TestCase):
    def test_esatta_half_up_no_float(self):
        # 12345 * 3% = 370.35 -> 370 ; 12345 * 5% = 617.25 -> 617
        self.assertEqual(commissione_cents(12_345, 300), 370)
        self.assertEqual(commissione_cents(12_345, 500), 617)
        self.assertEqual(commissione_cents(0, 700), 0)

    def test_rifiuta_bool_e_negativi(self):
        for bad in (True, 1.5, "100"):
            with self.assertRaises((ValueError, TypeError)):
                commissione_cents(bad, 300)
        with self.assertRaises(ValueError):
            commissione_cents(1000, -1)


class TestCricchetto(unittest.TestCase):
    """La garanzia suprema: il tasso di lealta' NON risale MAI, sotto carico estremo."""

    def _serie(self, seed, mesi=48):
        rng = random.Random(seed)
        pren = repeat = 0
        out = []
        for mese in range(1, mesi + 1):
            pren = max(0, pren + rng.randint(-9, 12))   # volume su E giu' (avverso)
            repeat += 1 if rng.random() < 0.3 else 0
            out.append(MetricheHost(mese, pren, repeat))
        return out

    def test_non_sale_mai_500_host(self):
        pol = PoliticaRanaInversa()
        for h in range(500):
            st = pol.stato_iniziale()
            prec = st.bps_lealta
            for m in self._serie(h):
                st = pol.evolvi(st, m)
                self.assertLessEqual(st.bps_lealta, prec, f"risalita host {h}")
                prec = st.bps_lealta

    def test_floor_mai_sotto_break_even(self):
        pol = PoliticaRanaInversa()
        for h in range(300):
            st = pol.stato_iniziale()
            for m in self._serie(h):
                st = pol.evolvi(st, m)
                self.assertGreaterEqual(st.bps_lealta, pol.break_even_minimo_bps)

    def test_costruzione_rifiuta_floor_sotto_break_even(self):
        with self.assertRaises(ValueError):
            PoliticaRanaInversa(floor_bps=200, break_even_minimo_bps=400)

    def test_costruzione_rifiuta_scaglioni_non_discendenti(self):
        with self.assertRaises(ValueError):
            PoliticaRanaInversa(cap_bps=300, mid_bps=500, floor_bps=400)


class TestCreditoPioniere(unittest.TestCase):
    def test_pioniere_3pct_in_finestra(self):
        pol = PoliticaRanaInversa()
        st = pol.evolvi(pol.stato_iniziale(), MetricheHost(1, 0, 0))
        self.assertEqual(pol.bps_effettivo(st, MetricheHost(1, 0, 0)), 300)

    def test_credito_a_tempo_poi_tasso_lealta(self):
        pol = PoliticaRanaInversa()
        st = pol.stato_iniziale()
        for mese in range(1, 14):
            st = pol.evolvi(st, MetricheHost(mese, 60, 8))
        dentro = pol.bps_effettivo(st, MetricheHost(12, 60, 8))
        fuori = pol.bps_effettivo(st, MetricheHost(13, 60, 8))
        self.assertEqual(dentro, 300)                    # 3% nella finestra
        self.assertGreaterEqual(fuori, pol.break_even_minimo_bps)  # poi >= break-even
        self.assertGreaterEqual(fuori, dentro)           # la lealta' non e' < pioniere

    def test_lealta_strutturale_resta_monotona_oltre_la_finestra(self):
        # il credito che scade NON e' una risalita del cricchetto: la lealta' e' ferma
        pol = PoliticaRanaInversa()
        st = pol.evolvi(pol.stato_iniziale(), MetricheHost(20, 200, 20))
        self.assertEqual(st.bps_lealta, pol.floor_bps)


class TestRipartizione(unittest.TestCase):
    def test_split_quadra_fuzz(self):
        pol = PoliticaRanaInversa()
        cfg = ConfigMotore("mango", pol, Giurisdizione("KH"), PSPStandard(150, 25))
        st = pol.evolvi(pol.stato_iniziale(), MetricheHost(30, 40, 5))
        m = MetricheHost(30, 40, 5)
        rng = random.Random(7)
        for _ in range(5000):
            imp = rng.randint(0, 5_000_000)
            r = ripartisci(cfg, imp, st, m)
            self.assertEqual(r.commissione_cents + r.netto_host_cents, imp)
            self.assertGreaterEqual(r.commissione_cents, 0)

    def test_psp_passthrough_esplicito_e_margine_visibile(self):
        pol = PoliticaRanaInversa()
        cfg = ConfigMotore("mango", pol, Giurisdizione(), PSPStandard(150, 25))
        st = pol.evolvi(pol.stato_iniziale(), MetricheHost(60, 100, 9))
        r = ripartisci(cfg, 100_000, st, MetricheHost(60, 100, 9))
        self.assertEqual(r.costo_psp_cents, commissione_cents(100_000, 150) + 25)
        self.assertEqual(r.netto_piattaforma_cents,
                         r.commissione_cents - r.costo_psp_cents - r.tassa_commissione_cents)

    def test_pioniere_puo_essere_in_perdita_bounded(self):
        # 3% commissione - PSP 1.5%+25c puo' dare margine negativo (CAC voluto, segnalato)
        pol = PoliticaRanaInversa()
        cfg = ConfigMotore("mango", pol, Giurisdizione(), PSPStandard(150, 25))
        st = pol.evolvi(pol.stato_iniziale(), MetricheHost(1, 0, 0))
        # incasso piccolo: comm 3%=30c, PSP 1.5%+25c=40c -> margine -10c (CAC voluto)
        r = ripartisci(cfg, 1_000, st, MetricheHost(1, 0, 0))
        self.assertTrue(r.in_perdita)


class TestJurisdictionAgnostic(unittest.TestCase):
    def test_default_tassa_zero_nessun_valore_eu(self):
        self.assertEqual(Giurisdizione().tassa_commissione_bps, 0)

    def test_da_env_default_zero(self):
        self.assertEqual(giurisdizione_da_env({}).tassa_commissione_bps, 0)

    def test_da_env_shift_via_config(self):
        g = giurisdizione_da_env({"JURISDICTION_CODE": "IT", "COMMISSION_TAX_BPS": "2200"})
        self.assertEqual((g.codice, g.tassa_commissione_bps), ("IT", 2200))

    def test_shift_non_tocca_split_host(self):
        pol = PoliticaRanaInversa()
        st = pol.evolvi(pol.stato_iniziale(), MetricheHost(30, 40, 5))
        m = MetricheHost(30, 40, 5)
        it = ripartisci(ConfigMotore("m", pol, Giurisdizione("IT", "EUR", 2200)), 250_000, st, m)
        kh = ripartisci(ConfigMotore("m", pol, Giurisdizione("KH", "USD", 0)), 250_000, st, m)
        self.assertEqual(it.commissione_cents, kh.commissione_cents)
        self.assertEqual(it.netto_host_cents, kh.netto_host_cents)
        self.assertGreater(it.tassa_commissione_cents, 0)
        self.assertEqual(kh.tassa_commissione_cents, 0)
        self.assertGreater(kh.netto_piattaforma_cents, it.netto_piattaforma_cents)


class TestIniezionePolicy(unittest.TestCase):
    """RICHIESTO: lo STESSO Core, due policy iniettate diverse, regole-denaro diverse."""

    def test_mango_vs_tavolaprive_stesso_core(self):
        reg = RegistroMotori()
        reg.registra(ConfigMotore("mango", PoliticaRanaInversa(), datastore_namespace="db_mango"))
        reg.registra(ConfigMotore("tavolaprive", PoliticaQuotaFissa(quota_bps=0, quota_fissa_cents=500),
                                  datastore_namespace="db_tavolaprive"))
        m = MetricheHost(1, 0, 0)
        mango = reg.ottieni("mango")
        tp = reg.ottieni("tavolaprive")
        c_mango = mango.politica.commissione_cents(100_000, mango.politica.stato_iniziale(), m)
        # Mango pioniere: 3% di 100000 = 3000 ; Tavola Prive: fee fissa 500
        st_mango = mango.politica.evolvi(mango.politica.stato_iniziale(), m)
        c_mango = mango.politica.commissione_cents(100_000, st_mango, m)
        c_tp = tp.politica.commissione_cents(100_000, tp.politica.stato_iniziale(), m)
        self.assertEqual(c_mango, 3000)
        self.assertEqual(c_tp, 500)
        self.assertNotEqual(c_mango, c_tp)

    def test_factory_da_config(self):
        p = politica_da_config({"tipo": "rana_inversa", "tasso_pioniere_bps": 300})
        self.assertIsInstance(p, PoliticaRanaInversa)
        q = politica_da_config({"tipo": "quota_fissa", "quota_fissa_cents": 500})
        self.assertIsInstance(q, PoliticaQuotaFissa)
        with self.assertRaises(ValueError):
            politica_da_config({"tipo": "inesistente"})


class TestIsolamentoCredenziali(unittest.TestCase):
    """RICHIESTO: il Registry isola i namespace datastore tra motori."""

    def test_namespace_distinti_e_isolati(self):
        reg = RegistroMotori()
        reg.registra(ConfigMotore("mango", PoliticaRanaInversa(), datastore_namespace="db_mango"))
        reg.registra(ConfigMotore("tavolaprive", PoliticaQuotaFissa(), datastore_namespace="db_tavolaprive"))
        self.assertNotEqual(reg.ottieni("mango").datastore_namespace,
                            reg.ottieni("tavolaprive").datastore_namespace)

    def test_namespace_in_conflitto_rifiutato(self):
        reg = RegistroMotori()
        reg.registra(ConfigMotore("mango", PoliticaRanaInversa(), datastore_namespace="condiviso"))
        with self.assertRaises(ValueError):
            reg.registra(ConfigMotore("altro", PoliticaQuotaFissa(), datastore_namespace="condiviso"))

    def test_motore_id_duplicato_rifiutato(self):
        reg = RegistroMotori()
        reg.registra(ConfigMotore("mango", PoliticaRanaInversa(), datastore_namespace="a"))
        with self.assertRaises(ValueError):
            reg.registra(ConfigMotore("mango", PoliticaRanaInversa(), datastore_namespace="b"))

    def test_motore_non_registrato_solleva(self):
        reg = RegistroMotori()
        with self.assertRaises(KeyError):
            reg.ottieni("fantasma")


if __name__ == "__main__":
    unittest.main()
