"""GUARDIA — Paga in Struttura (fase188): i conti dell'anticipo/saldo/fee, blindati.

Nasce dall'obiezione (sacrosanta) del fondatore: su 1 sola notte, o con carta extra-UE, il
costo FISSO di Stripe puo' far PERDERE soldi. La regola decisa: online = prezzo pulito; paga in
struttura = l'ospite paga una fee (1.50/notte) + l'host assorbe la copertura carta (~3%+30c) ->
cosi' NON perdiamo mai, anzi guadagniamo le briciole anche a commissione 0%.

Questa guardia prova, su ogni scenario:
  1. TOTALE OSPITE: ospite_paga_totale == prezzo + fee (l'ospite paga un po' di piu' in struttura).
  2. CONSERVAZIONE: anticipo_online + saldo_in_loco == ospite_paga_totale.
  3. NIENTE GIRO STORTO: host_incassa == saldo_in_loco (l'host prende il suo netto TUTTO dal
     saldo diretto in loco; noi non gli restituiamo NULLA) == prezzo - commissione - gateway.
  4. BOOKINVIP NON CI PERDE MAI, nemmeno 1 notte extra-UE: il gateway copre il costo Stripe
     peggiore (0.25 fisso + 3.25%), e col la fee ci guadagniamo pure.
  5. Non negativi; input assurdi ok; commissione clampata al prezzo.
"""

import unittest

import fase188_paga_struttura as PS


def _stripe_peggiore(importo_cents):
    """Costo Stripe caso PEGGIORE (carta extra-UE/commerciale): 0.25 fisso + 3.25%.
    CONFERMATO sull'API vera il 2026-08-09 (modalita' prova): 67 cents su 1300 e 675 su
    20000 sono esattamente 3,25% + 25."""
    return 25 + importo_cents * 325 // 10000


def _stripe_peggiore_valuta_estera(importo_cents):
    """Come sopra, MA quando l'annuncio non e' nella valuta in cui incassiamo: Stripe deve
    CONVERTIRE e aggiunge il 2%. Il conto e' italiano e tiene solo euro (misurato:
    `country: IT`, `default_currency: eur`, nessun altro saldo), quindi su un annuncio in
    altra valuta la conversione non e' evitabile.
    MISURATO sull'API vera: la commissione torna in DUE voci separate -- carta e
    conversione (es. `stripe_fee=346` + `stripe_fee=587` su un addebito da 200 USD)."""
    return 25 + importo_cents * 525 // 10000


class TestConti(unittest.TestCase):

    def _controlla(self, prezzo, notti, comm, **kw):
        r = PS.calcola(prezzo, notti, comm, **kw)
        # 1. totale ospite = prezzo + fee
        self.assertEqual(r["ospite_paga_totale_cents"], prezzo + r["fee_cents"])
        # 2. conservazione
        self.assertEqual(r["anticipo_online_cents"] + r["saldo_in_loco_cents"],
                         r["ospite_paga_totale_cents"], "anticipo+saldo != totale: %s" % r)
        # 3. NIENTE GIRO STORTO: l'host prende tutto dal saldo diretto, noi non restituiamo nulla
        self.assertEqual(r["host_incassa_cents"], r["saldo_in_loco_cents"],
                         "host_incassa != saldo -> ci sarebbe un giro di soldi all'host: %s" % r)
        self.assertEqual(r["host_incassa_cents"],
                         prezzo - r["commissione_cents"] - r["gateway_cents"])
        self.assertEqual(r["noi_incassiamo_cents"], r["commissione_cents"] + r["fee_cents"])
        # niente negativi
        for k, v in r.items():
            self.assertGreaterEqual(v, 0, "%s negativo: %s" % (k, r))
        # 4. BOOKINVIP NON CI PERDE: gateway trattenuto >= costo Stripe peggiore sull'anticipo
        if r["anticipo_online_cents"] > 0:
            self.assertGreaterEqual(
                r["gateway_cents"], _stripe_peggiore(r["anticipo_online_cents"]),
                "il gateway NON copre Stripe peggiore -> BookinVIP ci perde: %s" % r)
        return r

    def test_UNA_NOTTE_non_si_perde_MAI(self):
        # il caso che preoccupa il fondatore: 1 notte, host nuovo 0%, carta extra-UE (peggiore)
        r = self._controlla(2000, 1, 0)
        # noi incassiamo la fee, e il gateway copre Stripe col margine -> GUADAGNO, mai perdita
        guadagno_reale = r["noi_incassiamo_cents"] + (r["gateway_cents"]
                                                      - _stripe_peggiore(r["anticipo_online_cents"]))
        self.assertGreater(guadagno_reale, 0,
                           "su 1 notte 0%% NON dobbiamo perdere: guadagno=%d" % guadagno_reale)
        self.assertEqual(r["fee_cents"], 150, "la fee 1 notte deve essere 1.50")

    def test_valuta_estera_il_gateway_deve_coprire_ANCHE_la_conversione(self):
        """Se l'annuncio non e' nella valuta in cui incassiamo, Stripe CONVERTE e aggiunge
        il 2%: la copertura carta deve tenerne conto, altrimenti «paga in struttura» va
        sotto costo esattamente come ci andava il vecchio 3% secco.

        MISURATO il 2026-08-10 prima della riparazione (`fase188.calcola` senza saperlo):
            prezzo  50 EUR -> gateway  83, costo estera  71  -> coperto (il margine regge)
            prezzo 200 EUR -> gateway 134, costo estera 152  -> SCOPERTO di 18
            prezzo 500 EUR -> gateway 234, costo estera 315  -> SCOPERTO di 81
        Sotto i ~150 EUR i 30 centesimi di sicurezza voluti dal fondatore bastano da soli;
        sopra, il buco CRESCE con l'importo -- la stessa forma del difetto principale.

        ⛔ E' un difetto VIVO, non teorico: `PAGA_STRUTTURA_ATTIVO=1` e' acceso in
        produzione (misurato sul contenitore vero il 2026-08-09)."""
        for prezzo in (5000, 10000, 20000, 50000, 100000):
            with self.subTest(prezzo=prezzo):
                r = PS.calcola(prezzo, 2, prezzo * 10 // 100, valuta_estera=True)
                anticipo = r["anticipo_online_cents"]
                atteso = _stripe_peggiore_valuta_estera(anticipo)
                self.assertGreaterEqual(
                    r["gateway_cents"], atteso,
                    "annuncio in valuta estera su %d cents: la copertura carta rende %d "
                    "ma Stripe (carta + conversione) costa %d sull'anticipo di %d -> "
                    "ci rimettiamo %d cents"
                    % (prezzo, r["gateway_cents"], atteso, anticipo,
                       atteso - r["gateway_cents"]))

    def test_host_prende_uguale_online_o_struttura(self):
        # l'host incassa prezzo - commissione - gateway: la fee NON lo tocca (la paga l'ospite)
        r = self._controlla(30000, 1, 3000)
        self.assertEqual(r["host_incassa_cents"], 30000 - 3000 - r["gateway_cents"])
        self.assertEqual(r["fee_cents"], 150)   # +1.50 lo paga l'OSPITE, non l'host

    def test_scaglioni_e_notti(self):
        for comm in (0, 960, 2400, 3000):
            for prezzo, notti in ((2000, 1), (12000, 3), (30000, 1), (200000, 14)):
                if comm <= prezzo:
                    r = self._controlla(prezzo, notti, comm)
                    self.assertEqual(r["fee_cents"], 150 * notti)

    def test_prezzo_minuscolo_non_solleva_e_host_non_negativo(self):
        r = self._controlla(300, 1, 0)
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
        r = PS.calcola(1000, 1, 999999)
        self.assertLessEqual(r["commissione_cents"], 1000)
        self.assertGreaterEqual(r["host_incassa_cents"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
