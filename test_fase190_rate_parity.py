"""
RATE PARITY (fase190) — store segnalazioni + segnale visibilita', regola Anti-Finti-Verdi.

Copre: rilevamento violazione (nostro > OTA oltre tolleranza), stato iniziale della segnalazione
(fondata->aperto / infondata->respinto), Badge VIP vs penalita', punteggio di visibilita' puro,
negative testing (numeri assurdi, valute, slug vuoto). Osservabili FORTI (lo stato reale nel DB
+ il numero di ranking).
"""
import sqlite3
import unittest

import fase190_rate_parity as RP


def _mem():
    con = sqlite3.connect(":memory:")
    return RP.GestoreRateParity(lambda: RP._ConnCondivisa(con))


class TestViolazionePura(unittest.TestCase):
    def test_nostro_piu_alto_e_violazione(self):
        # noi 120, OTA 100, tolleranza 2% -> soglia 102 -> 120 > 102 -> violazione
        self.assertTrue(RP.e_violazione(12000, 10000))

    def test_uguale_o_meno_non_e_violazione(self):
        self.assertFalse(RP.e_violazione(10000, 10000))   # uguale: ok
        self.assertFalse(RP.e_violazione(9000, 10000))    # meno: ok (e' quello che vogliamo)

    def test_dentro_tolleranza_non_e_violazione(self):
        # noi 101, OTA 100, soglia 102 -> non e' violazione (rumore/valute)
        self.assertFalse(RP.e_violazione(10100, 10000))

    def test_confine_esatto_tolleranza_off_by_one(self):
        # OTA 100.00, tolleranza 2% -> soglia ESATTA 102.00. Confine < vs <=:
        # a 102.00 NON e' violazione (siamo alla soglia), a 102.01 SI'.
        self.assertFalse(RP.e_violazione(10200, 10000), "alla soglia esatta non e' violazione")
        self.assertTrue(RP.e_violazione(10201, 10000), "un cent oltre la soglia E' violazione")

    def test_input_assurdi_non_sollevano(self):
        for n, o in ((None, None), ("x", 100), (100, 0), (-5, 100), (100, -1)):
            try:
                RP.e_violazione(n, o)
            except Exception as ex:
                self.fail("ha sollevato su (%r,%r): %s" % (n, o, ex))


class TestVisibilita(unittest.TestCase):
    def test_badge_vip_spinge_su(self):
        self.assertEqual(RP.punteggio_visibilita(100, {"badge_vip": True}), 115)

    def test_violazione_verificata_penalizza(self):
        self.assertEqual(RP.punteggio_visibilita(100, {"violazioni_verificate": 1}), 60)

    def test_mai_sotto_zero(self):
        self.assertEqual(RP.punteggio_visibilita(10, {"violazioni_verificate": 3}), 0)

    def test_stato_non_dict_non_solleva(self):
        self.assertEqual(RP.punteggio_visibilita(50, None), 50)


class TestStore(unittest.TestCase):
    def setUp(self):
        self.g = _mem()

    def test_segnalazione_fondata_nasce_aperta(self):
        rid = self.g.segnala(alloggio_slug="casa", ota_nome="Booking",
                             nostro_prezzo_cents=12000, ota_prezzo_cents=10000)
        self.assertTrue(rid)
        st = self.g.stato_parita("casa")
        self.assertEqual(st["violazioni_aperte"], 1)
        self.assertFalse(st["badge_vip"])

    def test_segnalazione_infondata_respinta_subito(self):
        # da noi costa MENO: la segnalazione e' infondata -> 'respinto', nessuna violazione aperta
        rid = self.g.segnala(alloggio_slug="casa", ota_nome="Booking",
                             nostro_prezzo_cents=9000, ota_prezzo_cents=10000)
        self.assertTrue(rid)
        st = self.g.stato_parita("casa")
        self.assertEqual(st["violazioni_aperte"], 0)
        self.assertTrue(st["badge_vip"], "senza violazioni l'annuncio merita il Badge VIP")

    def test_verifica_toglie_il_badge_e_penalizza(self):
        rid = self.g.segnala(alloggio_slug="casa", ota_nome="Booking",
                             nostro_prezzo_cents=12000, ota_prezzo_cents=10000)
        self.g.risolvi(rid, "verificato")
        st = self.g.stato_parita("casa")
        self.assertEqual(st["violazioni_verificate"], 1)
        self.assertTrue(st["penalita"])
        self.assertLess(RP.punteggio_visibilita(100, st), 100, "una violazione verificata DEVE penalizzare")

    def test_annuncio_pulito_ha_badge(self):
        st = self.g.stato_parita("mai-segnalato")
        self.assertTrue(st["badge_vip"])
        self.assertEqual(RP.punteggio_visibilita(100, st), 115)

    def test_slug_vuoto_o_ota_zero_rifiutati(self):
        self.assertIsNone(self.g.segnala(alloggio_slug="", ota_nome="B",
                                         nostro_prezzo_cents=100, ota_prezzo_cents=100))
        self.assertIsNone(self.g.segnala(alloggio_slug="casa", ota_nome="B",
                                         nostro_prezzo_cents=100, ota_prezzo_cents=0))

    def test_risolvi_esito_non_valido(self):
        rid = self.g.segnala(alloggio_slug="casa", ota_nome="B",
                             nostro_prezzo_cents=12000, ota_prezzo_cents=10000)
        self.assertFalse(self.g.risolvi(rid, "boh"))
        self.assertTrue(self.g.risolvi(rid, "respinto"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
