"""Test Fase 98 - Policy commissione: primi-1000-host + split 3%/12%. Puro + integra fase88."""
import unittest

from fase88_registro_host import crea_registro_host
from fase98_policy_commissione import (commissione_bps_per_host, commissione_cents,
                                       e_fondatore, fattura_startup_cents,
                                       ripartisci_host_guest)

SEG = b"x" * 32


class TestPolicyPrimi1000(unittest.TestCase):
    def test_fondatore_15(self):
        self.assertEqual(commissione_bps_per_host(1), 1500)
        self.assertEqual(commissione_bps_per_host(1000), 1500)
        self.assertTrue(e_fondatore(1))
        self.assertTrue(e_fondatore(1000))

    def test_oltre_soglia_usa_post(self):
        self.assertEqual(commissione_bps_per_host(1001, bps_dopo=1800), 1800)
        self.assertFalse(e_fondatore(1001))

    def test_ordinale_ignoto_e_invalido_failsafe(self):
        # ignoto/non valido -> tariffa standard (post), MAI sconto fondatori, MAI 0
        self.assertEqual(commissione_bps_per_host(0, bps_dopo=1800), 1800)
        self.assertEqual(commissione_bps_per_host(-5, bps_dopo=1800), 1800)
        self.assertEqual(commissione_bps_per_host("x", bps_dopo=1800), 1800)
        self.assertEqual(commissione_bps_per_host(None), 1500)   # default post=1500

    def test_soglia_configurabile(self):
        self.assertEqual(commissione_bps_per_host(50, soglia=10, bps_dopo=2000), 2000)
        self.assertEqual(commissione_bps_per_host(5, soglia=10), 1500)


class TestSplitAsimmetrico(unittest.TestCase):
    def test_3_piu_12_uguale_15(self):
        r = ripartisci_host_guest(10000)               # €100
        self.assertEqual(r["host_fee"], 300)           # 3%
        self.assertEqual(r["guest_fee"], 1200)         # 12%
        self.assertEqual(r["nostra_commissione"], 1500)  # 15% totale
        self.assertEqual(r["netto_host"], 9700)        # incassa 100 - 3
        self.assertEqual(r["totale_ospite"], 11200)    # paga 100 + 12

    def test_conservazione_esatta_fuzz(self):
        for p in (1, 99, 100, 333, 10000, 12345, 999999):
            r = ripartisci_host_guest(p)
            # nostra commissione = quanto paga l'ospite - quanto incassa l'host
            self.assertEqual(r["nostra_commissione"],
                             r["totale_ospite"] - r["netto_host"])
            self.assertEqual(r["nostra_commissione"], r["host_fee"] + r["guest_fee"])
            self.assertGreaterEqual(r["netto_host"], 0)

    def test_cents_interi_no_float(self):
        r = ripartisci_host_guest(12345)
        for v in r.values():
            self.assertIsInstance(v, int)

    def test_commissione_cents_floor_e_clamp(self):
        self.assertEqual(commissione_cents(10000, 1500), 1500)
        self.assertEqual(commissione_cents(-5, 1500), 0)        # mai negativa
        self.assertEqual(commissione_cents(10000, 99999), 10000)  # clamp 100%

    def test_fattura_startup_solo_commissione(self):
        # tutela forfettario: solo il 15% è nostro fatturato, non i 100
        self.assertEqual(fattura_startup_cents(10000), 1500)


class TestIntegrazioneFase88Counter(unittest.TestCase):
    def test_numero_e_conta_host(self):
        reg = crea_registro_host(":memory:", SEG)
        reg.inizializza_schema()
        self.assertEqual(reg.conta_host(), 0)
        ids = []
        for i in range(3):
            e = reg.registra("host%d@x.it" % i, "passw0rd!", accetta_termini=True)
            self.assertTrue(e.ok, e.errore)
            ids.append(e.host_id)
        self.assertEqual(reg.conta_host(), 3)
        # ogni host ha un ordinale 1..3, unico, e i primi 1000 sono fondatori
        ordinali = sorted(reg.numero_host(h) for h in ids)
        self.assertEqual(ordinali, [1, 2, 3])
        for h in ids:
            self.assertTrue(e_fondatore(reg.numero_host(h)))
            self.assertEqual(commissione_bps_per_host(reg.numero_host(h)), 1500)

    def test_host_inesistente_ordinale_zero(self):
        reg = crea_registro_host(":memory:", SEG)
        reg.inizializza_schema()
        self.assertEqual(reg.numero_host("h_inesistente"), 0)
        # ordinale 0 -> non fondatore (fail-safe)
        self.assertFalse(e_fondatore(reg.numero_host("h_inesistente")))


if __name__ == "__main__":
    unittest.main()
