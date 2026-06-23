"""Test Fase 103 - Reverse charge. Puro + durevole; nessuna rete."""
import os
import tempfile
import unittest

from fase103_reverse_charge import (ConfigReverseCharge, RegistroReverseCharge,
                                    calcola_autofattura, crea_registro_reverse_charge,
                                    scadenza_f24)

ON = ConfigReverseCharge(attivo=True)


class TestCalcolo(unittest.TestCase):
    def test_gated_off_none(self):
        self.assertIsNone(calcola_autofattura(10000, "2026-03-10"))   # default off

    def test_iva_22_e_td17(self):
        af = calcola_autofattura(10000, "2026-03-10", cfg=ON)
        self.assertEqual(af["iva_cents"], 2200)
        self.assertEqual(af["tipo_documento"], "TD17")
        self.assertEqual(af["scadenza_f24"], "2026-04-16")

    def test_td18_beni(self):
        af = calcola_autofattura(5000, "2026-12-01", servizio=False, cfg=ON)
        self.assertEqual(af["tipo_documento"], "TD18")
        self.assertEqual(af["scadenza_f24"], "2027-01-16")    # rollover anno

    def test_imponibile_invalido(self):
        self.assertIsNone(calcola_autofattura(0, "2026-03-10", cfg=ON))
        self.assertIsNone(calcola_autofattura(-5, "2026-03-10", cfg=ON))

    def test_aliquota_configurabile(self):
        af = calcola_autofattura(10000, "2026-03-10", cfg=ConfigReverseCharge(True, 1000))
        self.assertEqual(af["iva_cents"], 1000)

    def test_scadenza_f24(self):
        self.assertEqual(scadenza_f24("2026-06-30"), "2026-07-16")
        self.assertEqual(scadenza_f24("2026-12-15"), "2027-01-16")
        self.assertIsNone(scadenza_f24("non-data"))


class TestRegistro(unittest.TestCase):
    def test_totale_iva_per_scadenza(self):
        reg = crea_registro_reverse_charge(cfg=ON)
        reg.registra("Stripe IE", 10000, "2026-03-10")    # iva 2200 -> 2026-04-16
        reg.registra("AWS", 5000, "2026-03-20")           # iva 1100 -> 2026-04-16
        self.assertEqual(reg.iva_da_versare_cents("2026-04-16"), 3300)
        self.assertEqual(reg.iva_da_versare_cents("2026-05-16"), 0)

    def test_durevole(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "rc.json")
        RegistroReverseCharge(p, ON).registra("Stripe", 10000, "2026-03-10")
        self.assertEqual(RegistroReverseCharge(p, ON).iva_da_versare_cents("2026-04-16"), 2200)
        os.remove(p)
        os.rmdir(d)


if __name__ == "__main__":
    unittest.main()
