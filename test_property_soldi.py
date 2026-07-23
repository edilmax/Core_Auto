"""
PROPERTY-BASED TESTING (Hypothesis) sui MOTORI DEI SOLDI.

Invece di scegliere noi i casi, Hypothesis GENERA centinaia di input (anche cattivi/estremi) e
verifica che gli INVARIANTI reggano SEMPRE. Se trova un controesempio, lo restringe al piu'
piccolo e lo mostra. Copre: motore "paga in struttura" (fase188), rampa commissioni (fase98),
rimborso cancellazione (fase111). Zero rete, deterministico (seed fisso via profilo).
"""
import unittest

from hypothesis import given, settings, strategies as st, HealthCheck

import fase188_paga_struttura as PS
import fase98_policy_commissione as POL
import fase111_cancellazione as CANC

_S = settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def _stripe_peggiore(x):
    return 25 + x * 325 // 10000


class TestMotorePagaStruttura(unittest.TestCase):
    @_S
    @given(prezzo=st.integers(min_value=0, max_value=5_000_000),
           notti=st.integers(min_value=1, max_value=90),
           comm=st.integers(min_value=0, max_value=6_000_000),
           psp=st.integers(min_value=0, max_value=1000))
    def test_invarianti_sempre(self, prezzo, notti, comm, psp):
        r = PS.calcola(prezzo, notti, comm, psp_bps=psp)
        A, S = r["anticipo_online_cents"], r["saldo_in_loco_cents"]
        # niente negativi, mai
        for k, v in r.items():
            self.assertGreaterEqual(v, 0, "%s negativo: %s" % (k, r))
        # conservazione + totale ospite = prezzo + fee
        self.assertEqual(r["ospite_paga_totale_cents"], max(0, prezzo) + r["fee_cents"])
        self.assertEqual(A + S, r["ospite_paga_totale_cents"])
        # host prende TUTTO dal saldo (no giro storto)
        self.assertEqual(r["host_incassa_cents"], S)
        # NON SI PERDE MAI: quello che incassiamo online copre il costo Stripe peggiore
        if A > 0:
            self.assertGreater(A - _stripe_peggiore(A), 0, "PERDITA su %s" % r)
        # margine PIENO quando l'anticipo non e' tosato (saldo > 0)
        if S > 0 and A > 0:
            self.assertGreaterEqual(r["gateway_cents"], _stripe_peggiore(A))

    @_S
    @given(prezzo=st.integers(min_value=1, max_value=5_000_000),
           notti=st.integers(min_value=1, max_value=60))
    def test_fee_sempre_150_per_notte(self, prezzo, notti):
        r = PS.calcola(prezzo, notti, 0)
        self.assertEqual(r["fee_cents"], 150 * notti)


class TestRampaCommissioni(unittest.TestCase):
    @_S
    @given(giorni=st.integers(min_value=-1000, max_value=100000))
    def test_scaglioni_0_8_10(self, giorni):
        bps = POL.commissione_bps_lancio(giorni)
        # sempre uno dei tre scaglioni ufficiali
        self.assertIn(bps, (0, POL.LANCIO_BPS_FASE1, POL.LANCIO_BPS_REGIME),
                      "bps fuori scaglione: %d (giorni %d)" % (bps, giorni))
        if giorni < 0:
            # FAIL-SAFE del fondatore: giorni non validi -> tariffa a regime (non si regala lo 0%)
            self.assertEqual(bps, POL.LANCIO_BPS_REGIME, "giorni negativi devono dare la tariffa a regime (fail-safe)")
        elif giorni < POL.LANCIO_GIORNI_GRATIS:
            self.assertEqual(bps, 0)
        elif giorni < POL.LANCIO_GIORNI_FASE1:
            self.assertEqual(bps, POL.LANCIO_BPS_FASE1)
        else:
            self.assertEqual(bps, POL.LANCIO_BPS_REGIME)

    @_S
    @given(g1=st.integers(min_value=0, max_value=100000),
           g2=st.integers(min_value=0, max_value=100000))
    def test_monotona(self, g1, g2):
        # su giorni VALIDI (>=0): piu' anzianita' -> commissione mai minore (la rampa non torna
        # indietro). Sui giorni negativi vale il fail-safe (regime), fuori dalla monotonia.
        if g1 <= g2:
            self.assertLessEqual(POL.commissione_bps_lancio(g1), POL.commissione_bps_lancio(g2))


class TestRimborsoCancellazione(unittest.TestCase):
    @_S
    @given(pagato=st.integers(min_value=0, max_value=5_000_000),
           giorni=st.integers(min_value=-30, max_value=400),
           politica=st.sampled_from(["flessibile", "moderata", "rigida", "non_rimborsabile"]),
           ripens=st.booleans())
    def test_rimborso_mai_oltre_il_pagato(self, pagato, giorni, politica, ripens):
        r = CANC.calcola_rimborso(pagato, giorni, politica=politica, entro_ripensamento=ripens)
        rimb = r.get("rimborso_cents", 0)
        tratt = r.get("trattenuto_cents", 0)
        # niente negativi
        self.assertGreaterEqual(rimb, 0, f"rimborso negativo: {r}")
        self.assertGreaterEqual(tratt, 0, f"trattenuto negativo: {r}")
        # MAI rimborsare piu' di quanto pagato (regalo di soldi)
        self.assertLessEqual(rimb, max(0, pagato), f"rimborso > pagato: {r}")
        # conservazione: rimborso + trattenuto == pagato
        self.assertEqual(rimb + tratt, max(0, pagato), f"rimborso+trattenuto != pagato: {r}")

    @_S
    @given(pagato=st.integers(min_value=1, max_value=1_000_000),
           giorni=st.integers(min_value=3, max_value=400))
    def test_ripensamento_rende_tutto(self, pagato, giorni):
        # dentro il ripensamento 48h (arrivo >= 3 giorni) si rende il 100% (diritto legale)
        r = CANC.calcola_rimborso(pagato, giorni, politica="non_rimborsabile", entro_ripensamento=True)
        self.assertEqual(r.get("rimborso_cents", 0), pagato, f"ripensamento non rende tutto: {r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
