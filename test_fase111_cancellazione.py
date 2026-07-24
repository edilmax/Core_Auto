"""Test Fase 111 - Cancellazione flessibile + rimborso. Puro, cents interi.
Soglie allineate agli standard mondiali (Airbnb/Booking/Vrbo) + finestra di ripensamento 48h."""
import unittest

from fase111_cancellazione import (POLITICHE, PoliticaCancellazione, calcola_rimborso,
                                   crea_politica_cancellazione)


class TestRimborso(unittest.TestCase):
    def test_flessibile_pieno(self):
        r = calcola_rimborso(10000, 5, politica="flessibile")
        self.assertEqual(r["rimborso_cents"], 10000)        # >=1 giorno -> 100%
        self.assertEqual(r["trattenuto_cents"], 0)

    def test_flessibile_stesso_giorno_meta(self):
        r = calcola_rimborso(10000, 0, politica="flessibile")
        self.assertEqual(r["rimborso_cents"], 5000)         # 0 giorni -> 50%

    def test_moderata_scaglioni(self):
        self.assertEqual(calcola_rimborso(10000, 5, politica="moderata")["rimborso_cents"], 10000)
        self.assertEqual(calcola_rimborso(10000, 3, politica="moderata")["rimborso_cents"], 5000)
        self.assertEqual(calcola_rimborso(10000, 0, politica="moderata")["rimborso_cents"], 0)

    def test_rigida_soglie_stile_airbnb_firm(self):
        # rigida = Airbnb "Firm": 100% >=30gg, 50% 7-30gg, 0% <7gg
        self.assertEqual(calcola_rimborso(10000, 30, politica="rigida")["rimborso_cents"], 10000)
        self.assertEqual(calcola_rimborso(10000, 29, politica="rigida")["rimborso_cents"], 5000)
        self.assertEqual(calcola_rimborso(10000, 7, politica="rigida")["rimborso_cents"], 5000)
        self.assertEqual(calcola_rimborso(10000, 6, politica="rigida")["rimborso_cents"], 0)
        self.assertEqual(calcola_rimborso(10000, 0, politica="rigida")["rimborso_cents"], 0)

    def test_non_rimborsabile(self):
        # 0% sempre (ma vedi ripensamento: la finestra 48h vince comunque)
        self.assertEqual(calcola_rimborso(10000, 90, politica="non_rimborsabile")["rimborso_cents"], 0)
        self.assertEqual(calcola_rimborso(10000, 1, politica="non_rimborsabile")["trattenuto_cents"], 10000)

    def test_ripensamento_vince_su_ogni_politica(self):
        # finestra di ripensamento 48h -> 100% anche su rigida e non_rimborsabile
        for pol in ("flessibile", "moderata", "rigida", "non_rimborsabile"):
            r = calcola_rimborso(10000, 3, politica=pol, entro_ripensamento=True)
            self.assertEqual(r["rimborso_cents"], 10000, pol)
            self.assertEqual(r["trattenuto_cents"], 0, pol)
            self.assertTrue(r.get("ripensamento"))

    def test_ripensamento_non_crea_soldi_dal_nulla(self):
        # fail-closed: input invalido resta 0 anche con ripensamento
        self.assertEqual(calcola_rimborso(0, 3, entro_ripensamento=True)["rimborso_cents"], 0)
        self.assertEqual(calcola_rimborso(-5, 3, entro_ripensamento=True)["rimborso_cents"], 0)

    def test_fee_pulizia_sempre_resa(self):
        # rigida, 2 giorni -> soggiorno 0%, ma pulizia 2000 sempre rimborsata
        r = calcola_rimborso(12000, 2, politica="rigida", fee_pulizia_cents=2000)
        self.assertEqual(r["rimborso_cents"], 2000)
        self.assertEqual(r["trattenuto_cents"], 10000)

    def test_input_invalido_failclosed(self):
        self.assertEqual(calcola_rimborso(0, 5)["rimborso_cents"], 0)
        self.assertEqual(calcola_rimborso(-5, 5)["rimborso_cents"], 0)
        self.assertEqual(calcola_rimborso(10000, -3, politica="moderata")["rimborso_cents"], 0)

    def test_mai_piu_del_pagato(self):
        # invariante "noi mai in perdita": rimborso <= pagato, sempre
        for g in (-5, 0, 1, 7, 30, 100):
            for pol in POLITICHE:
                r = calcola_rimborso(10000, g, politica=pol)
                self.assertLessEqual(r["rimborso_cents"], 10000)
                self.assertEqual(r["rimborso_cents"] + r["trattenuto_cents"], 10000)

    def test_cents_interi_e_conservazione(self):
        r = calcola_rimborso(9999, 3, politica="moderata")
        self.assertIsInstance(r["rimborso_cents"], int)
        self.assertEqual(r["rimborso_cents"] + r["trattenuto_cents"], 9999)

    def test_politica_custom(self):
        pol = crea_politica_cancellazione("x", [(2, 10000), (0, 2000)])
        self.assertIsInstance(pol, PoliticaCancellazione)
        self.assertEqual(calcola_rimborso(10000, 0, politica=pol)["rimborso_cents"], 2000)

    def test_politica_sconosciuta_usa_flessibile(self):
        self.assertEqual(calcola_rimborso(10000, 5, politica="boh")["politica"], "flessibile")

    # --- FLOOR del rimborso parziale (Flow 4 micro-stepping): mai over-refund di 1 cent ---
    def test_rimborso_parziale_FLOOR_non_arrotonda_su(self):
        # 9999 * 50% = 4999.5 -> DEVE fare FLOOR (4999), non round (5000). Con round() si
        # rimborserebbe 1 cent di troppo (noi in perdita). Nessun test lo bloccava: la
        # conservazione (rimborso+trattenuto=pagato) resta vera anche arrotondando su.
        r = calcola_rimborso(9999, 3, politica="moderata")          # moderata@3gg -> bps 5000
        self.assertEqual(r["bps"], 5000)
        self.assertEqual(r["rimborso_cents"], 4999, "rimborso non FLOORato (over-refund di 1 cent)")
        self.assertEqual(r["trattenuto_cents"], 5000)
        self.assertEqual(round(9999 * 5000 / 10000), 5000)          # prova: round() darebbe 5000

    def test_rimborso_non_supera_mai_la_quota_esatta(self):
        # invariante FLOOR non-circolare: rimborso <= quota proporzionale ESATTA, sempre.
        # (rimborso*10000 <= soggiorno*bps) <=> il rimborso non eccede mai la frazione esatta.
        # Rosso se qualcuno passa a round()/ceil (over-refund su importi dispari).
        for pagato in (9999, 10001, 12345, 7777, 33333, 1, 3, 101):
            for pol_nome in POLITICHE:
                for g in (0, 1, 5, 7, 30):
                    r = calcola_rimborso(pagato, g, politica=pol_nome)   # fee=0 -> soggiorno=pagato
                    self.assertLessEqual(
                        r["rimborso_cents"] * 10000, pagato * r["bps"],
                        "OVER-REFUND: pagato=%d pol=%s g=%d -> rimborso %d supera la quota esatta"
                        % (pagato, pol_nome, g, r["rimborso_cents"]))


if __name__ == "__main__":
    unittest.main()
