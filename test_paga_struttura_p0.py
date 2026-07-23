"""
PAGA IN STRUTTURA — INVARIANTI P0 (Business & Stripe), a prova di ogni scenario/valuta/paese.

Richiesta del fondatore (regola Anti-Finti-Verdi): le regole economiche dell'anticipo devono
essere "matematicamente inattaccabili in qualsiasi scenario, valuta o paese", mai azzerate,
mai negative, e BookinVIP non deve MAI perdere denaro.

fase188 lavora in UNITA' MINORI INTERE della valuta dell'annuncio (cents EUR, yen, fils...): e'
per costruzione indipendente dalla valuta. Qui si martella una GRIGLIA larghissima + fuzzing
casuale (migliaia di combinazioni prezzo × notti × commissione × psp) e su OGNI risultato si
verificano gli invarianti P0. Un solo controesempio = rosso.

NOTA sul "deposito minimo 5€": e' del modello VECCHIO, SUPERATO. Oggi l'anticipo =
commissione + fee(1,50/notte) + copertura carta; la copertura carta garantisce da sola che non
si perde mai (fisso 0,55 > 0,25 di Stripe, + 3,25% del caso peggiore extra-UE). Questo test lo
DIMOSTRA numericamente, cosi' la scelta di modello resta blindata.
"""
import random
import unittest

import fase188_paga_struttura as PS

# soglie del modello (le rileggiamo dal modulo: se cambiano nel codice, il test le segue)
FEE = PS.FEE_PER_NOTTE_CENTS
GW_MIN = PS.GATEWAY_MINIMO_CENTS
GW_FIX = PS.GATEWAY_FISSO_CENTS
GW_BPS = PS.GATEWAY_BPS


def _stripe_peggiore(x):
    """Costo Stripe del CASO PEGGIORE su un addebito x: 0,25 fisso + 3,25%."""
    return 25 + x * 325 // 10000


class TestInvariantiP0(unittest.TestCase):

    def _p0(self, prezzo, notti, comm, psp=300):
        r = PS.calcola(prezzo, notti, comm, psp_bps=psp)
        ctx = f"(prezzo={prezzo}, notti={notti}, comm={comm}, psp={psp}) -> {r}"
        A = r["anticipo_online_cents"]
        S = r["saldo_in_loco_cents"]
        G = r["gateway_cents"]
        C = r["commissione_cents"]
        F = r["fee_cents"]
        H = r["host_incassa_cents"]
        N = r["noi_incassiamo_cents"]
        OT = r["ospite_paga_totale_cents"]
        P = max(0, int(prezzo)) if isinstance(prezzo, int) and not isinstance(prezzo, bool) else 0

        # 1) NIENTE NEGATIVI, mai (nessuna voce sotto zero, in nessuno scenario)
        for k, v in r.items():
            self.assertGreaterEqual(v, 0, "NEGATIVO %s %s" % (k, ctx))
        # 2) TOTALE OSPITE = prezzo + fee ; CONSERVAZIONE anticipo+saldo == totale
        self.assertEqual(OT, P + F, "totale ospite != prezzo+fee " + ctx)
        self.assertEqual(A + S, OT, "anticipo+saldo != totale " + ctx)
        # 3) NIENTE GIRO STORTO: host prende TUTTO dal saldo (== prezzo - comm - gateway)
        self.assertEqual(H, S, "host_incassa != saldo " + ctx)
        self.assertEqual(H, P - C - G, "host_incassa != prezzo-comm-gateway " + ctx)
        # 4) NOI = commissione + fee (il gateway copre Stripe, non e' ricavo)
        self.assertEqual(N, C + F, "noi != comm+fee " + ctx)
        # 5) la commissione non supera mai il prezzo (clamp)
        self.assertLessEqual(C, P, "commissione > prezzo " + ctx)
        # 6) l'anticipo non supera mai quello che paga l'ospite (prezzi minuscoli)
        self.assertLessEqual(A, OT, "anticipo > totale ospite " + ctx)
        # 7) P0 SOLDI — NON SI PERDE MAI, in NESSUNO scenario: quello che incassiamo online
        #    (l'anticipo, tutto nostro) copre SEMPRE il costo Stripe del caso peggiore, quindi
        #    cio' che ci RESTA e' strettamente positivo. Questo e' l'invariante vero e vale
        #    ovunque, anche nei prezzi assurdi (fee > prezzo: un host che mette 30 notti a 1€).
        if A > 0:
            netto_reale = A - _stripe_peggiore(A)
            self.assertGreater(netto_reale, 0, "netto reale <= 0 -> PERDITA " + ctx)
            # 7b) MARGINE PIENO (guadagno >= commissione+fee) quando l'anticipo NON e' stato
            #     tosato al tetto, cioe' quando resta un saldo > 0 (ogni annuncio con prezzi
            #     sensati: commissione 0/8/10% e fee piccola). Li' il gateway e' quello pieno
            #     `_gw(anticipo)` e supera sempre Stripe. Se invece comm+fee assurdi divorano
            #     tutto (saldo 0), non c'e' margine pieno ma NON si perde (garantito sopra).
            if S > 0:
                self.assertGreaterEqual(G, _stripe_peggiore(A),
                                        "gateway < Stripe peggiore con saldo>0 " + ctx)
                guadagno = N + (G - _stripe_peggiore(A))
                self.assertGreater(guadagno, 0, "guadagno non positivo " + ctx)
        return r

    def test_griglia_larga_tutte_le_valute(self):
        # prezzi che coprono cent EUR minuscoli, yen (nessun decimale), importi enormi
        prezzi = [0, 1, 50, 99, 100, 150, 199, 300, 1000, 1999, 2000, 5000, 12345,
                  30000, 100000, 500000, 1000000, 1800000, 10 ** 8, 10 ** 9]
        notti_l = [1, 2, 3, 7, 14, 28, 30, 60]
        for P in prezzi:
            for n in notti_l:
                # commissioni: 0%, 8%, 10%, e la commissione oltre il prezzo (clamp)
                for bps in (0, 800, 1000):
                    self._p0(P, n, P * bps // 10000)
                self._p0(P, n, P + 999)          # comm > prezzo -> clampata

    def test_psp_di_ogni_paese(self):
        # diverse tariffe PSP (paesi/carte): l'invariante "non si perde" deve reggere
        for psp in (0, 100, 250, 290, 300, 325, 400, 1000):
            for P in (100, 2000, 30000, 250000):
                for n in (1, 5, 30):
                    self._p0(P, n, P // 10, psp=psp)

    def test_fuzzing_casuale(self):
        rnd = random.Random(20260723)
        for _ in range(6000):
            P = rnd.randint(0, 5_000_000)
            n = rnd.randint(1, 90)
            comm = rnd.randint(0, P + 5000)          # a volte oltre il prezzo (clamp)
            psp = rnd.choice([0, 250, 300, 325, 500])
            self._p0(P, n, comm, psp=psp)

    def test_anticipo_mai_azzerato_su_prenotazione_reale(self):
        # su QUALSIASI prenotazione reale (prezzo>0, >=1 notte) l'anticipo e' > 0 e >= fee
        for P in (100, 300, 2000, 30000, 250000):
            for n in (1, 3, 14):
                for bps in (0, 800, 1000):
                    r = PS.calcola(P, n, P * bps // 10000)
                    self.assertGreater(r["anticipo_online_cents"], 0,
                                       "anticipo AZZERATO su prenotazione reale P=%d n=%d" % (P, n))
                    self.assertGreaterEqual(r["fee_cents"], FEE,   # almeno una notte di fee
                                            "fee sotto il minimo P=%d n=%d" % (P, n))

    def test_una_notte_zero_percento_non_si_perde(self):
        # il caso che preoccupava il fondatore, blindato: 1 notte, host nuovo 0%, carta peggiore
        r = self._p0(2000, 1, 0)
        self.assertEqual(r["fee_cents"], FEE)
        self.assertGreater(r["noi_incassiamo_cents"], 0)

    def test_soglie_coerenti_col_modello(self):
        # il gateway fisso DEVE superare il fisso di Stripe (0,25) -> margine di sicurezza > 0
        self.assertGreater(GW_FIX, 25, "il gateway fisso non copre il fisso Stripe: PERDITA possibile")
        self.assertGreaterEqual(GW_BPS, 325, "il gateway %% non copre il caso peggiore extra-UE")
        self.assertEqual(FEE, 150, "la fee 1,50/notte e' cambiata: aggiornare i testi pubblici")


if __name__ == "__main__":
    unittest.main(verbosity=2)
