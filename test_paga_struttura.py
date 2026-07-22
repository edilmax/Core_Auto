"""GUARDIA — Paga in Struttura (fase188): i conti dell'anticipo/saldo, blindati.

Nasce dall'obiezione (sacrosanta) del fondatore: su 1 sola notte, o con carta extra-UE, il
costo FISSO di Stripe puo' prosciugare il margine e far PERDERE soldi. Questa guardia prova
che non succede mai, e che i conti tornano al centesimo:

  1. CONSERVAZIONE: anticipo + saldo == prezzo (l'ospite paga il totale, prezzo pulito).
  2. NETTO HOST: host_incassa == prezzo - commissione - gateway; e la parte da anticipo +
     il saldo in loco == host_incassa (nulla si perde per strada).
  3. BOOKINVIP NON CI PERDE MAI: il gateway trattenuto copre SEMPRE il costo Stripe peggiore
     (fisso 0.25 + 3.25% extra-UE), anche a commissione 0% su 1 notte economica.
  4. L'ANTICIPO COPRE LA COMMISSIONE (BookinVIP la incassa subito), tranne su prezzi minuscoli.
  5. MINIMO 5.00 sui soggiorni brevi/economici; niente valori negativi; input assurdi ok.
"""

import unittest

import fase188_paga_struttura as PS


def _stripe_peggiore(importo_cents):
    """Modello del costo Stripe caso PEGGIORE (carta extra-UE/commerciale): 0.25 fisso + 3.25%."""
    return 25 + importo_cents * 325 // 10000


class TestConti(unittest.TestCase):

    def _controlla_invarianti(self, prezzo, notti, comm, **kw):
        r = PS.calcola(prezzo, notti, comm, **kw)
        # 1. conservazione: anticipo + saldo == prezzo
        self.assertEqual(r["anticipo_online_cents"] + r["saldo_in_loco_cents"], prezzo,
                         "anticipo + saldo != prezzo (%s)" % r)
        # 2. netto host coerente
        self.assertEqual(r["host_incassa_cents"],
                         prezzo - r["commissione_cents"] - r["gateway_cents"])
        self.assertEqual(r["di_cui_da_anticipo_cents"] + r["saldo_in_loco_cents"],
                         r["host_incassa_cents"], "i due pezzi del netto host non tornano")
        # niente negativi
        for k, v in r.items():
            self.assertGreaterEqual(v, 0, "%s negativo: %s" % (k, r))
        # la parte da anticipo non supera l'anticipo
        self.assertLessEqual(r["di_cui_da_anticipo_cents"], r["anticipo_online_cents"])
        # 3. BOOKINVIP NON CI PERDE: gateway trattenuto >= costo Stripe peggiore sull'anticipo
        if r["anticipo_online_cents"] > 0:
            self.assertGreaterEqual(
                r["gateway_cents"], _stripe_peggiore(r["anticipo_online_cents"]),
                "il gateway NON copre il costo Stripe peggiore -> BookinVIP ci perde: %s" % r)
        return r

    def test_una_notte_economica_0pct_non_si_perde(self):
        # 1 notte a 20.00, host nuovo (0% rampa): il caso che preoccupava il fondatore
        r = self._controlla_invarianti(2000, 1, 0)
        self.assertGreaterEqual(r["anticipo_online_cents"], 500, "sotto il minimo 5.00")
        # BookinVIP a 0% incassa almeno il gateway - Stripe (>0): non va sotto
        margine = r["gateway_cents"] - _stripe_peggiore(r["anticipo_online_cents"])
        self.assertGreaterEqual(margine, 0)

    def test_una_notte_cara_10pct_anticipo_copre_commissione(self):
        # 1 notte a 300.00, host a regime (10% = 3000): l'anticipo deve coprire la commissione
        r = self._controlla_invarianti(30000, 1, 3000)
        self.assertGreaterEqual(r["anticipo_online_cents"], r["commissione_cents"],
                                "l'anticipo non incassa tutta la commissione")

    def test_soggiorno_lungo_deposito_per_notte(self):
        # 10 notti: deposito per-notte 1.50*10 = 15.00 supera il minimo
        r = self._controlla_invarianti(50000, 10, 4000)
        self.assertGreaterEqual(r["anticipo_online_cents"], 1500)

    def test_scaglioni_rampa(self):
        for comm in (0, 800 * 100 // 100, 2400, 3000):   # 0% / 8% / 10% su vari prezzi
            for prezzo, notti in ((2000, 1), (12000, 3), (30000, 1), (200000, 14)):
                if comm <= prezzo:
                    self._controlla_invarianti(prezzo, notti, comm)

    def test_prezzo_minuscolo_anticipo_uguale_prezzo(self):
        # soggiorno da 3.00: l'anticipo non puo' superare il prezzo -> tutto online, saldo 0
        r = self._controlla_invarianti(300, 1, 0)
        self.assertEqual(r["saldo_in_loco_cents"], 0)
        self.assertEqual(r["anticipo_online_cents"], 300)
        self.assertGreaterEqual(r["host_incassa_cents"], 0)

    def test_input_assurdi_non_sollevano(self):
        for prezzo, notti, comm in ((None, None, None), (-5, 0, -9), ("x", "y", "z"),
                                    (0, 1, 0), (10 ** 9, 1, 10 ** 9), (True, False, True)):
            try:
                r = PS.calcola(prezzo, notti, comm)
            except Exception as e:
                self.fail("solleva su (%r,%r,%r): %s" % (prezzo, notti, comm, e))
            for v in r.values():
                self.assertGreaterEqual(v, 0)

    def test_commissione_maggiore_del_prezzo_clampata(self):
        # commissione assurda > prezzo: viene compressa, host mai negativo
        r = PS.calcola(1000, 1, 999999)
        self.assertLessEqual(r["commissione_cents"], 1000)
        self.assertGreaterEqual(r["host_incassa_cents"], 0)
        self.assertEqual(r["anticipo_online_cents"] + r["saldo_in_loco_cents"], 1000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
