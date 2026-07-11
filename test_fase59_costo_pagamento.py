"""Costo servizio pagamenti (carta) a carico HOST: dedotto dal netto host, MAI aggiunto
all'ospite (che paga sempre il prezzo pulito). Copre la fee Stripe -> noi mai in perdita."""
import unittest

from fase59_concierge import ProtocolloConcierge, FirmaQuote

SEG = b"k" * 32


class InvFinto:
    def disponibile(self, a, ci, co):
        return True

    def stato_giorno(self, a, g):
        return {"prezzo_netto_cents": 10000}     # €100/notte


def proto(**kw):
    return ProtocolloConcierge(InvFinto(), FirmaQuote(SEG), **kw)


REQ = {"alloggio_id": "casa-1", "check_in": "2026-07-01",
       "check_out": "2026-07-02", "party": 1}


class TestCostoPagamento(unittest.TestCase):
    def test_3pct_dedotto_dall_host_ospite_invariato(self):
        # commissione 10% + costo carta 3%: host = 10000 -1000 -300 = 8700; ospite paga 10000
        p = proto(commissione=lambda n: n * 10 // 100, psp_bps=300)
        q = p.quota(REQ).corpo
        self.assertEqual(q["prezzo_guest_cents"], 10000)     # ospite: prezzo PULITO
        self.assertEqual(q["totale_cents"], 10000)           # ospite paga questo (0% guest fee)
        self.assertEqual(q["commissione_cents"], 1000)       # nostra 10%
        self.assertEqual(q["costo_pagamento_cents"], 300)    # carta 3% a carico host
        self.assertEqual(q["netto_host_cents"], 8700)        # host = listino -comm -carta

    def test_costo_carta_su_totale_include_tassa(self):
        # il costo carta si calcola sul TOTALE addebitato (soggiorno + tassa), come fa Stripe
        p = proto(commissione=lambda n: 0, psp_bps=300,
                  tassa_alloggio=lambda slug, notti, ospiti, imponibile: 500)
        q = p.quota(REQ).corpo
        self.assertEqual(q["totale_cents"], 10500)           # 10000 + 500 tassa
        self.assertEqual(q["costo_pagamento_cents"], 315)    # 3% di 10500
        self.assertEqual(q["netto_host_cents"], 10000 - 315)  # host: listino - carta (comm 0)

    def test_default_zero_nessun_costo(self):
        # senza psp_bps (default 0) il comportamento e' identico a prima: nessun costo carta
        q = proto(commissione=lambda n: 1000).quota(REQ).corpo
        self.assertEqual(q["costo_pagamento_cents"], 0)
        self.assertEqual(q["netto_host_cents"], 9000)        # solo commissione 10%

    def test_mai_in_perdita_copre_stripe(self):
        # su €100 il 3% = 300 cents; la fee Stripe peggiore (2.9% + 25) = 315 su carte UE...
        # ma sul TOTALE con carte europee ~1.5%+25 = ~175 -> il 3% copre e avanza margine.
        p = proto(commissione=lambda n: n * 10 // 100, psp_bps=300)
        q = p.quota(REQ).corpo
        stripe_ue = (10000 * 15 // 1000) + 25                # ~1.5% + 0.25 = 175
        self.assertGreater(q["costo_pagamento_cents"], stripe_ue)  # 300 > 175: mai in perdita

    def test_clamp_e_input_invalido(self):
        # psp_bps oltre il cap 20% viene limitato; input non-int -> 0 (fail-safe)
        self.assertEqual(proto(psp_bps=9999, commissione=lambda n: 0).quota(REQ)
                         .corpo["costo_pagamento_cents"], 2000)     # cap 20% di 10000
        self.assertEqual(proto(psp_bps="x", commissione=lambda n: 0).quota(REQ)
                         .corpo["costo_pagamento_cents"], 0)

    def test_netto_host_mai_negativo(self):
        # costo carta enorme + commissione: il netto host non va sotto zero (guardia)
        q = proto(commissione=lambda n: n, psp_bps=2000).quota(REQ).corpo
        self.assertGreaterEqual(q["netto_host_cents"], 0)


if __name__ == "__main__":
    unittest.main()
