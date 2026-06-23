"""Test Fase 109 - Referral host-porta-host. Puro + durevole; nessuna rete."""
import os
import tempfile
import unittest

from fase109_referral_host import ReferralHost, crea_referral_host

SEG = b"r" * 32


class TestReferral(unittest.TestCase):
    def setUp(self):
        self.r = crea_referral_host(SEG)

    def test_flusso_bonus(self):
        cod = self.r.genera_codice("hostA")
        self.assertTrue(self.r.registra_referral(cod, "hostB"))
        self.assertEqual(self.r.crediti("hostA"), 0)        # non ancora qualificato
        bonus = self.r.conferma_qualifica("hostB")
        self.assertEqual(bonus, 1000)                       # 1° referral -> tier 1
        self.assertEqual(self.r.crediti("hostA"), 1000)

    def test_anti_auto_referral(self):
        cod = self.r.genera_codice("hostA")
        self.assertFalse(self.r.registra_referral(cod, "hostA"))

    def test_dedup_referee(self):
        cod = self.r.genera_codice("hostA")
        self.assertTrue(self.r.registra_referral(cod, "hostB"))
        self.assertFalse(self.r.registra_referral(cod, "hostB"))

    def test_codice_falso_rifiutato(self):
        self.assertFalse(self.r.registra_referral("token.finto.xxx", "hostB"))

    def test_qualifica_idempotente(self):
        cod = self.r.genera_codice("hostA")
        self.r.registra_referral(cod, "hostB")
        self.assertEqual(self.r.conferma_qualifica("hostB"), 1000)
        self.assertEqual(self.r.conferma_qualifica("hostB"), 0)   # già qualificato
        self.assertEqual(self.r.crediti("hostA"), 1000)

    def test_scaglioni_crescenti(self):
        cod = self.r.genera_codice("hostA")
        for i in range(4):                                  # 4 referee qualificati
            self.r.registra_referral(cod, "h%d" % i)
            self.r.conferma_qualifica("h%d" % i)
        # 1..3 -> 1000 ciascuno; 4° -> 1500
        self.assertEqual(self.r.crediti("hostA"), 1000 * 3 + 1500)

    def test_credito_non_cashabile_uso(self):
        cod = self.r.genera_codice("hostA")
        self.r.registra_referral(cod, "hostB")
        self.r.conferma_qualifica("hostB")
        self.assertEqual(self.r.usa_credito("hostA", 600), 600)
        self.assertEqual(self.r.crediti("hostA"), 400)
        self.assertEqual(self.r.usa_credito("hostA", 9999), 400)   # cap al disponibile
        self.assertEqual(self.r.crediti("hostA"), 0)

    def test_durevole(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "ref.json")
        r1 = ReferralHost(SEG, p)
        cod = r1.genera_codice("hostA")
        r1.registra_referral(cod, "hostB")
        r1.conferma_qualifica("hostB")
        self.assertEqual(ReferralHost(SEG, p).crediti("hostA"), 1000)
        os.remove(p)
        os.rmdir(d)


if __name__ == "__main__":
    unittest.main()
