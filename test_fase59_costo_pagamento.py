"""Costo servizio pagamenti (carta) a carico HOST: dedotto dal netto host, MAI aggiunto
all'ospite (che paga sempre il prezzo pulito). Copre la fee Stripe -> noi mai in perdita."""
import io
import os
import re
import unittest

from fase59_concierge import ProtocolloConcierge, FirmaQuote

SEG = b"k" * 32


def default_di_produzione(nome):
    """Legge il valore PREDEFINITO che usa la produzione da `main_casavip.py`, invece di
    riscriverlo qui. Cosi' la prova non misura un numero inventato dal test: misura QUELLO
    CHE GIRA. Se domani qualcuno lo abbassa sotto il costo Stripe, questa prova diventa
    rossa da sola -- e' il punto di D22 (dove una macchina puo' ricontrollare, si mette una
    guardia, perche' un obbligo affidato alla buona volonta' si rompe di nuovo).

    Se il valore non si trova, la prova NON e' verde: e' NON ESEGUITA e si ferma (D18
    punto 1 -- uno strumento misura prima se stesso; sbaglio S7 -- premessa mancante non
    vale OK)."""
    percorso = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main_casavip.py")
    with io.open(percorso, encoding="utf-8", errors="replace") as f:
        src = f.read()
    m = re.search(nome + r'["\']\s*,\s*["\'](\d+)["\']', src)
    if not m:
        raise AssertionError(
            "non trovo %s in main_casavip.py: questa prova non e' in condizione di "
            "misurare niente, quindi si ferma invece di dare verde" % nome)
    return int(m.group(1))


class CatFinto:
    """Catalogo minimo: serve solo a dire in che VALUTA e' prezzato l'annuncio."""

    def __init__(self, valuta="EUR"):
        self._v = valuta

    def dettaglio(self, slug):
        return {"slug": slug, "valuta": self._v}


class InvFinto:
    def __init__(self, notte_cents=10000):
        # il prezzo a notte e' un PARAMETRO: la tariffa tecnica va provata anche sulle
        # prenotazioni piccole, dove la quota fissa di Stripe pesa di piu' (13 EUR per
        # una notte -- il caso vero portato dal fondatore il 2026-08-09).
        self._notte = notte_cents

    def disponibile(self, a, ci, co):
        return True

    def stato_giorno(self, a, g):
        return {"prezzo_netto_cents": self._notte}     # default: €100/notte


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

    def test_la_tariffa_tecnica_copre_la_carta_PEGGIORE_a_OGNI_importo(self):
        """La tariffa tecnica deve coprire il costo Stripe della carta PEGGIORE che ci
        puo' arrivare, a QUALUNQUE importo -- non della carta migliore su un importo
        comodo.

        QUESTA PROVA SOSTITUISCE `test_mai_in_perdita_copre_stripe`, CHE ERA UN
        ORNAMENTO. Quella confrontava il 3% con la carta europea standard (1,5% + 0,25)
        su 100 EUR: 300 > 175, verde per sempre. Il suo stesso commento dichiarava di
        sapere che il caso peggiore valeva 315 -- cioe' PIU' dei nostri 300 -- e poi
        misurava l'altro. Una prova che non puo' fallire non e' una guardia.

        I DUE MODI IN CUI IL 3% SECCO NON BASTA (misurati il 2026-08-09,
        `collaudi/conti_stripe.py`):
          1. manca la QUOTA FISSA: Stripe prende 0,25 EUR a transazione e noi no, quindi
             sotto i 16,66 EUR siamo sotto costo anche con la carta migliore;
          2. la PERCENTUALE e' troppo bassa: una carta non europea costa 3,15%, cioe' piu'
             del nostro 3%, a QUALUNQUE importo.

        Fonte del costo: https://stripe.com/it/pricing (listino Italia, letto 2026-08-09).
        Non e' stato possibile leggerlo dalle transazioni vere: `balance_transactions`
        sul conto live risponde `"data": []` -- zero pagamenti reali finora.
        """
        # Costo Stripe della carta PEGGIORE che ci puo' arrivare -- listino Italia,
        # https://stripe.com/it/pricing letto il 2026-08-09. Non e' stato possibile leggerlo
        # dalle transazioni vere: `GET /v1/balance_transactions` sul conto live risponde
        # `"data": []` (zero pagamenti reali). Il giorno che ce ne saranno, si rilegge di li'.
        #   annuncio in EURO   -> carta internazionale 3,15% + 0,25
        #   annuncio in ALTRA VALUTA -> + 2% di conversione, perche' il conto e' italiano e
        #   tiene SOLO euro (misurato: country IT, default_currency eur, nessun altro saldo)
        casi = (("EUR", 315, 25), ("USD", 515, 25))
        bps_eur = default_di_produzione("PAGAMENTO_BPS")
        bps_estera = default_di_produzione("PAGAMENTO_BPS_ESTERA")
        fisso = default_di_produzione("PAGAMENTO_FISSO_CENTS")
        for valuta, peggiore_bps, peggiore_fissa in casi:
            for notte_cents in (1300, 2500, 5000, 10000, 20000, 50000):
                with self.subTest(valuta=valuta, importo=notte_cents):
                    p = ProtocolloConcierge(
                        InvFinto(notte_cents), FirmaQuote(SEG), catalogo=CatFinto(valuta),
                        commissione=lambda n: n * 10 // 100,
                        psp_bps=bps_eur, psp_bps_valuta_estera=bps_estera,
                        psp_fisso_cents=fisso)
                    q = p.quota(REQ).corpo
                    totale = q["totale_cents"]
                    costo_stripe = (totale * peggiore_bps) // 10000 + peggiore_fissa
                    self.assertGreaterEqual(
                        q["costo_pagamento_cents"], costo_stripe,
                        "SOTTO COSTO su %d cents (annuncio in %s): la tariffa tecnica rende "
                        "%d ma la carta peggiore costa %d -> ci rimettiamo %d cents, e nei "
                        "primi 90 giorni (commissione 0%%) quella perdita non la copre nessuno."
                        % (totale, valuta, q["costo_pagamento_cents"], costo_stripe,
                           costo_stripe - q["costo_pagamento_cents"]))

    def test_la_quota_fissa_rifiuta_un_BOOLEANO(self):
        """`True` non e' una quota fissa: e' un valore sbagliato travestito da numero.

        ⛔ BUCO TROVATO DAL GIUDICE DELLA MUTAZIONE il 2026-08-10 (`fase59:182`, mutante
        `and -> or` SOPRAVVISSUTO): in Python `isinstance(True, int)` e' VERO, quindi senza
        il secondo controllo un `True` passerebbe per intero e diventerebbe **1 centesimo**
        di quota fissa. Nessun test passava un booleano, quindi quel controllo poteva
        sparire e nessuno se ne sarebbe accorto -- e' codice difensivo mai eseguito (D19).
        Il danno e' piccolo (1 cent invece di 25), ma la forma e' la stessa dei difetti
        grossi: un validatore che si puo' togliere senza far gridare niente."""
        for falso in (True, False):
            with self.subTest(valore=falso):
                p = ProtocolloConcierge(InvFinto(), FirmaQuote(SEG),
                                        commissione=lambda n: 0, psp_bps=0,
                                        psp_fisso_cents=falso)
                q = p.quota(REQ).corpo
                self.assertEqual(q["costo_pagamento_cents"], 0,
                                 "un %r e' stato accettato come quota fissa: con psp_bps=0 "
                                 "il costo doveva essere 0, invece e' %d"
                                 % (falso, q["costo_pagamento_cents"]))

    def test_clamp_e_input_invalido(self):
        # psp_bps oltre il cap 20% viene limitato; input non-int -> 0 (fail-safe)
        self.assertEqual(proto(psp_bps=9999, commissione=lambda n: 0).quota(REQ)
                         .corpo["costo_pagamento_cents"], 2000)     # cap 20% di 10000
        self.assertEqual(proto(psp_bps="x", commissione=lambda n: 0).quota(REQ)
                         .corpo["costo_pagamento_cents"], 0)

    def test_netto_host_mai_negativo(self):
        # commissione che assorbe tutto + costo carta: il preventivo viene RIFIUTATO
        # onestamente (422 prezzo_non_sostenibile) invece di far sparire la differenza
        # a nostro carico ("mai in perdita"). Con prezzi/fee reali non scatta mai.
        r = proto(commissione=lambda n: n, psp_bps=2000).quota(REQ)
        self.assertEqual(r.status, 422)
        self.assertEqual(r.corpo["errore"], "prezzo_non_sostenibile")


class TestPavimentoDelCredito(unittest.TestCase):
    """Il credito si finanzia dalla NOSTRA commissione, e `_sconto_credito` tiene un
    pavimento: si regala al massimo cio' che resta sopra il costo Stripe.

    TROVATO IL 2026-08-10 partendo dai mutanti sopravvissuti su quella funzione: il
    pavimento e' scritto a mano come `netto * 290 // 10000 + 25 + 200` (fase59:495),
    cioe' **2,9%**, mentre il costo MISURATO sull'API vera il 2026-08-09 e' 3,25% +
    0,25 EUR, e **5,25%** quando Stripe deve convertire la valuta. Il commento tre
    righe sopra la dice gia' giusta: e' il conto sotto che e' rimasto indietro. E' la
    stessa malattia della tariffa tecnica -- lo stesso numero in un secondo posto.

    Non e' «perdiamo soldi su ogni prenotazione»: la tariffa tecnica pagata dall'host
    copre Stripe a parte. E' che **il paracadute e' piu' lasco di quanto dichiara**, e
    di quanto lo sia si misura: su 1000 EUR in valuta estera lascia passare 21,50 EUR
    in piu' del suo stesso limite.
    """

    # Costo Stripe MISURATO il 2026-08-09 sull'API vera (chiave di prova, 120 addebiti):
    # carta peggiore 3,25% + 0,25 EUR; +2% quando il conto deve convertire la valuta.
    STRIPE_BPS = 325
    STRIPE_BPS_CAMBIO = 525
    STRIPE_FISSO = 25

    def _token(self, cents, valuta="EUR", *, firma):
        import secrets
        import time as _t
        return firma.codifica({"tipo": "credito_fondatore", "email": "x@x.it",
                               "citta": "roma", "credito_cents": cents,
                               "valuta": valuta, "exp": int(_t.time()) + 86400,
                               "nonce": secrets.token_hex(8)})

    def _scoperto(self, netto, valuta):
        """Quanto resta della nostra commissione dopo lo sconto, meno il costo Stripe
        vero. Negativo = il pavimento ha lasciato passare piu' di quanto dichiara."""
        firma = FirmaQuote(SEG)
        p = ProtocolloConcierge(InvFinto(), firma, catalogo=CatFinto(valuta),
                                valuta=("EUR" if valuta == "EUR" else "EUR"))
        comm = netto * 1000 // 10000                      # 10% a regime
        # credito enorme: si vuole vedere il PAVIMENTO, non il credito
        tok = self._token(netto, valuta, firma=firma)
        sconto, _ = p._sconto_credito(tok, netto, comm, valuta)
        bps = self.STRIPE_BPS if valuta == "EUR" else self.STRIPE_BPS_CAMBIO
        costo_vero = netto * bps // 10000 + self.STRIPE_FISSO
        return (comm - sconto) - costo_vero

    def test_il_pavimento_del_credito_copre_il_costo_STRIPE_MISURATO(self):
        casi = []
        for valuta in ("EUR", "GBP"):
            for eur in (13, 50, 100, 200, 500, 1000):
                d = self._scoperto(eur * 100, valuta)
                if d < 0:
                    casi.append("%s %d EUR -> scoperto di %.2f EUR"
                                % (valuta, eur, -d / 100.0))
        self.assertEqual(
            casi, [],
            "il pavimento del credito (fase59:495) regala piu' di quanto la sua stessa "
            "spiegazione permette, perche' stima Stripe al 2,9%% mentre il costo "
            "MISURATO e' 3,25%% (5,25%% col cambio valuta):\n  " + "\n  ".join(casi))


if __name__ == "__main__":
    unittest.main()
