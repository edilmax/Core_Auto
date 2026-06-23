"""Test Fase 100 - DAC7 gate. Puro + durevole; nessuna rete."""
import os
import tempfile
import unittest

from fase100_dac7 import (ConfigDAC7, RegistroDAC7, ReportDAC7, crea_registro_dac7,
                          valuta_dac7)

ON = ConfigDAC7(attivo=True)


class TestValuta(unittest.TestCase):
    def test_gated_off_nessuna_azione(self):
        r = valuta_dac7(100, 999999, False)            # default attivo=False
        self.assertFalse(r.sospendi_annuncio)
        self.assertFalse(r.blocca_payout)

    def test_sotto_soglia_ok(self):
        r = valuta_dac7(5, 50000, False, ON)
        self.assertFalse(r.gate_attivo)
        self.assertFalse(r.deve_segnalare)

    def test_gate_sicurezza_prenotazioni(self):
        r = valuta_dac7(28, 0, False, ON)
        self.assertTrue(r.gate_attivo)
        self.assertTrue(r.sospendi_annuncio)
        self.assertTrue(r.blocca_payout)

    def test_gate_sicurezza_ricavi(self):
        self.assertTrue(valuta_dac7(1, 180000, False, ON).blocca_payout)

    def test_dati_forniti_sblocca(self):
        r = valuta_dac7(40, 300000, True, ON)
        self.assertFalse(r.sospendi_annuncio)
        self.assertTrue(r.deve_segnalare)              # obbligo di report resta

    def test_soglia_legale_segnalazione(self):
        self.assertTrue(valuta_dac7(30, 0, True, ON).deve_segnalare)
        self.assertTrue(valuta_dac7(0, 200000, True, ON).deve_segnalare)

    def test_input_invalido_failsafe(self):
        r = valuta_dac7("x", None, "y", ON)
        self.assertEqual(r.prenotazioni, 0)
        self.assertEqual(r.ricavi_cents, 0)


class TestRegistro(unittest.TestCase):
    def test_conteggio_e_gate_memoria(self):
        reg = crea_registro_dac7(cfg=ON)
        for _ in range(28):
            reg.registra_prenotazione("h1", 1000)
        self.assertFalse(reg.visibile("h1"))
        self.assertFalse(reg.payout_consentito("h1"))
        reg.imposta_dati_fiscali("h1")
        self.assertTrue(reg.visibile("h1"))
        self.assertTrue(reg.payout_consentito("h1"))

    def test_durevole_file_atomico(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "dac7.json")
        r1 = RegistroDAC7(p, ON)
        for _ in range(28):
            r1.registra_prenotazione("h2", 1000)
        self.assertFalse(RegistroDAC7(p, ON).visibile("h2"))   # ricaricato
        os.remove(p)
        os.rmdir(d)

    def test_host_sconosciuto_ok(self):
        self.assertTrue(crea_registro_dac7(cfg=ON).visibile("ignoto"))


if __name__ == "__main__":
    unittest.main()
