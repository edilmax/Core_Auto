"""
Test Fase 71 - Commitment Engine.

Copre: commitment a scaglioni (lontano/medio/vicino), deposito+voucher+saldo esatti,
fail-closed; cleaning fee trasparente (costo+buffer), sconto soggiorno lungo, breakdown;
chargeback shield (protetto/a rischio/chiavi custom/non-dict); purezza interi.
"""
import unittest

from fase71_commitment import (
    CalcoloCleaning, CalcoloCommitment, EsitoChargeback, PoliticaCommitment,
    calcola_cleaning_fee, calcola_commitment, valuta_chargeback,
)


class TestCommitment(unittest.TestCase):
    def test_lontano(self):
        c = calcola_commitment(100000, 60)        # >30 giorni -> 10% deposito
        self.assertEqual(c.tipo, "deposito_convertibile")
        self.assertEqual(c.deposito_cents, 10000)         # 10%
        self.assertEqual(c.voucher_se_cancella_cents, 12000)  # 120% del deposito
        self.assertEqual(c.saldo_a_checkin_cents, 90000)

    def test_medio(self):
        c = calcola_commitment(100000, 14)        # >7 giorni -> 20% deposito
        self.assertEqual(c.deposito_cents, 20000)
        self.assertEqual(c.voucher_se_cancella_cents, 23000)  # 115%
        self.assertEqual(c.saldo_a_checkin_cents, 80000)

    def test_vicino_pagamento_totale(self):
        c = calcola_commitment(100000, 3)         # <=7 giorni -> pieno
        self.assertEqual(c.tipo, "pagamento_totale")
        self.assertEqual(c.deposito_cents, 100000)
        self.assertEqual(c.voucher_se_cancella_cents, 0)

    def test_conservazione(self):
        c = calcola_commitment(99999, 40)
        self.assertEqual(c.deposito_cents + c.saldo_a_checkin_cents,
                         c.prezzo_totale_cents)

    def test_fail_closed(self):
        for p in (0, -1, 10.0, None):
            c = calcola_commitment(p, 60)
            self.assertEqual(c.tipo, "pagamento_totale")
            self.assertEqual(c.deposito_cents, 0)

    def test_giorni_invalidi_pieno(self):
        c = calcola_commitment(100000, -5)        # giorni invalidi -> 0 -> pieno
        self.assertEqual(c.tipo, "pagamento_totale")

    def test_interi(self):
        c = calcola_commitment(100000, 60)
        self.assertIsInstance(c.deposito_cents, int)


class TestCleaning(unittest.TestCase):
    def test_costo_piu_buffer(self):
        c = calcola_cleaning_fee(3300, 3)         # buffer 120% -> 3960
        self.assertEqual(c.fee_cents, 3960)
        self.assertEqual(c.costo_reale_cents, 3300)
        self.assertEqual(c.buffer_cents, 660)
        self.assertEqual(c.sconto_lungo_cents, 0)

    def test_sconto_soggiorno_lungo(self):
        pol = PoliticaCommitment(buffer_cleaning_bps=12000, soglia_soggiorno_lungo=7,
                                 sconto_cleaning_lungo_bps=2000)
        c = calcola_cleaning_fee(3300, 10, politica=pol)
        fee_base = (3300 * 12000) // 10000        # 3960
        sconto = (fee_base * 2000) // 10000       # 792
        self.assertEqual(c.sconto_lungo_cents, sconto)
        self.assertEqual(c.fee_cents, fee_base - sconto)

    def test_fail_closed(self):
        self.assertEqual(calcola_cleaning_fee(0, 3).fee_cents, 0)
        self.assertEqual(calcola_cleaning_fee(10.0, 3).fee_cents, 0)

    def test_as_dict(self):
        d = calcola_cleaning_fee(3300, 3).as_dict()
        self.assertEqual(d["money_unit"], "cents_integer")
        self.assertIsInstance(d["fee_cents"], int)


class TestChargeback(unittest.TestCase):
    def test_protetto(self):
        e = valuta_chargeback({"smart_pass_usato": True, "recensione_lasciata": True})
        self.assertTrue(e.protetto)
        self.assertEqual(e.mancanti, [])
        self.assertIn("smart_pass_usato", e.evidenze)

    def test_a_rischio(self):
        e = valuta_chargeback({"smart_pass_usato": True})   # manca recensione
        self.assertFalse(e.protetto)
        self.assertIn("recensione_lasciata", e.mancanti)

    def test_chiavi_custom(self):
        e = valuta_chargeback({"selfie": True, "wifi": True},
                              richieste=("selfie", "wifi"))
        self.assertTrue(e.protetto)

    def test_valore_non_true_conta_mancante(self):
        e = valuta_chargeback({"smart_pass_usato": "si", "recensione_lasciata": 1})
        self.assertFalse(e.protetto)              # solo True esatto conta
        self.assertEqual(set(e.mancanti), {"smart_pass_usato", "recensione_lasciata"})

    def test_non_dict(self):
        e = valuta_chargeback("non dict")
        self.assertFalse(e.protetto)
        self.assertTrue(e.mancanti)

    def test_mai_solleva(self):
        for bad in (None, 123, [], {}):
            try:
                valuta_chargeback(bad)
                calcola_commitment(bad, bad)
                calcola_cleaning_fee(bad, bad)
            except Exception as e:  # pragma: no cover
                self.fail(f"sollevato su {bad!r}: {e}")


if __name__ == "__main__":
    unittest.main()
