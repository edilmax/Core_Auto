"""Test DB giurisdizioni marketing mondiale: USA cold-email lecito, UE bloccata, sconosciuto
fail-closed, per-canale, lista paesi consentiti ordinata per intensita'."""
import unittest

from fase154_giurisdizioni_marketing import (canali_permessi, giurisdizioni_consentite,
                                             puo_contattare_a_freddo, regole_paese)


class TestGiurisdizioni(unittest.TestCase):
    def test_usa_email_cold_lecito(self):
        ok, legge = puo_contattare_a_freddo("US", "email")
        self.assertTrue(ok)
        self.assertIn("CAN-SPAM", legge)

    def test_ue_bloccata(self):
        for p in ("IT", "FR", "DE", "ES"):
            self.assertFalse(puo_contattare_a_freddo(p, "email")[0], p)

    def test_canada_opt_in_bloccato(self):
        self.assertFalse(puo_contattare_a_freddo("CA", "email")[0])   # CASL

    def test_uk_b2b_email_lecito(self):
        self.assertTrue(puo_contattare_a_freddo("GB", "email")[0])

    def test_sconosciuto_fail_closed(self):
        self.assertFalse(puo_contattare_a_freddo("ZZ", "email")[0])
        self.assertFalse(puo_contattare_a_freddo("", "email")[0])
        self.assertFalse(puo_contattare_a_freddo(None, "email")[0])
        self.assertEqual(regole_paese("ZZ").intensita, 0)

    def test_per_canale_sms_whatsapp_piu_stretti(self):
        # in USA email e' opt-out ma SMS (TCPA) e WhatsApp restano opt-in
        self.assertEqual(canali_permessi("US"), ["email"])
        self.assertFalse(puo_contattare_a_freddo("US", "sms")[0])
        self.assertFalse(puo_contattare_a_freddo("US", "whatsapp")[0])

    def test_lista_consentiti_ordinata_per_intensita(self):
        lst = giurisdizioni_consentite("email")
        self.assertIn("US", lst)
        self.assertNotIn("IT", lst)                  # UE esclusa
        self.assertEqual(lst[0], "US")               # mercato piu' aggressivo per primo

    def test_nessun_paese_per_canale_inesistente(self):
        self.assertEqual(giurisdizioni_consentite("piccione"), [])

    def test_asia_est_opt_out_dove_lecito(self):
        # Hong Kong (UEMO) e Taiwan: opt-out -> cold email lecito
        for p in ("HK", "TW", "JP"):
            self.assertTrue(puo_contattare_a_freddo(p, "email")[0], p)

    def test_asia_est_opt_in_bloccata(self):
        # Cina, Corea, Thailandia, Indonesia, Vietnam, Malaysia: opt-in -> cold BLOCCATO
        for p in ("CN", "KR", "TH", "ID", "VN", "MY", "PH"):
            self.assertFalse(puo_contattare_a_freddo(p, "email")[0], p)

    def test_lista_include_asia_e_americhe_opt_out(self):
        lst = giurisdizioni_consentite("email")
        for p in ("US", "HK", "TW", "MX", "SG", "JP"):
            self.assertIn(p, lst)
        for p in ("CN", "KR", "IT"):
            self.assertNotIn(p, lst)


if __name__ == "__main__":
    unittest.main()
