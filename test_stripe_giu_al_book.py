# -*- coding: utf-8 -*-
"""Guardia «STRIPE GIÙ AL BOOK = SOGGIORNO GRATIS» — difetto ALTO trovato il 2026-07-29
dalla campagna di LIVELLO 2 (integrazione severa) e corretto alla radice dal coordinatore.

IL CAMMINO (misurato sul disco prima della correzione): prenotazione istantanea mentre
`api.stripe.com` risponde 500. `fase59_concierge.prenota` isolava l'errore del link di pagamento
e scriveva comunque `stato='confermata'`. Conseguenze REALI, tutte verificate:
  · HTTP 201 con `voucher_token` VALIDO e `smart_pass` (il PIN di check-in) consegnati all'ospite;
  · NESSUN `payment_url`: non gli viene mai chiesto di pagare;
  · date BLOCCATE (una seconda prenotazione sulle stesse notti riceve 409);
  · tabella `pendenti` VUOTA → nessuno sweeper libererà mai la stanza, e la riconciliazione
    non ha nemmeno un appiglio per accorgersene.
Risultato: camera fuori mercato, ospite con voucher valido, incasso zero, traccia zero.

NON era una scelta consapevole: lo STESSO caso sul ramo su-richiesta (approvazione host in
fase83) ha già il fail-safe corretto → 503 `pagamento_non_disponibile`. Il codice non
distingueva «gateway non configurato» (modo diretto, legittimo) da «gateway configurato ma
irraggiungibile» (incidente).

LA CORREZIONE (fase59_concierge.prenota): se il pagamento è configurato e il link non nasce →
si RILASCIA il blocco appena preso e si risponde 503. Il modo diretto senza gateway resta
invariato, e il caso normale (gateway sano) è intoccato.

⚠️ NOTA STORICA: il vecchio `test_link_pagamento_che_solleva_non_rompe` asseriva
`status == 201` «prenotazione valida nonostante PSP giu'» — cioè **codificava il difetto come
comportamento atteso**. È stato aggiornato: un test che benedice una perdita di denaro è più
pericoloso di nessun test.

VISTO ROSSO: togliendo da fase59_concierge il blocco `if self._link is not None and not
payment_url:` questi test tornano rossi (201 con voucher e stanza bloccata).
"""
import unittest

from fase57_vetrina import SchedaAlloggio, crea_catalogo
from fase58_channel_manager import crea_channel_manager
from fase59_concierge import FirmaQuote, ProtocolloConcierge

SEGRETO = b"0123456789abcdef0123456789abcdef"
GIORNI = ("2027-03-01", "2027-03-02", "2027-03-03")


def _mondo(unita=1, prezzo=10000):
    """Inventario + catalogo veri, una casa con `unita` unità disponibili."""
    inv = crea_channel_manager()
    for g in GIORNI:
        inv.imposta_disponibilita("casa", g, unita_totali=unita, prezzo_netto_cents=prezzo)
    cat = crea_catalogo(disponibilita=inv.disponibile)
    cat.pubblica(SchedaAlloggio(host_id="h", slug="casa", titolo="Casa",
                                citta="Roma", prezzo_notte_cents=prezzo, capacita=4))
    return inv, cat


def _prenota(proto, email="ospite@prova.it"):
    q = proto.quota({"alloggio_id": "casa", "check_in": GIORNI[0], "check_out": GIORNI[2]})
    assert q.status == 200, q.corpo
    return proto.prenota({"quote_token": q.corpo["quote_token"], "email": email})


def _gateway_rotto(_dati):
    raise RuntimeError("api.stripe.com 500")


class TestStripeGiuAlBook(unittest.TestCase):

    def test_gateway_in_avaria_NON_conferma(self):
        """Il cuore: niente conferma, niente voucher, niente PIN — 503 pulito e onesto."""
        inv, cat = _mondo()
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat,
                                    link_pagamento=_gateway_rotto)
        r = _prenota(proto)
        self.assertEqual(r.status, 503,
                         "confermata senza pagamento = soggiorno gratis: %s" % r.corpo)
        self.assertEqual(r.corpo.get("errore"), "pagamento_non_disponibile")
        self.assertNotEqual(r.corpo.get("stato"), "confermata")
        for chiave in ("voucher_token", "smart_pass", "riferimento"):
            self.assertNotIn(chiave, r.corpo,
                             "consegnato '%s' senza aver incassato un centesimo" % chiave)

    def test_la_stanza_torna_subito_vendibile(self):
        """La camera non deve restare fuori mercato per una prenotazione mai nata."""
        inv, cat = _mondo(unita=1)
        rotto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat,
                                    link_pagamento=_gateway_rotto)
        self.assertEqual(_prenota(rotto).status, 503)
        # un secondo ospite deve poter prendere le STESSE notti (l'unica unità è di nuovo libera)
        sano = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat,
                                   link_pagamento=lambda d: "https://pay.stripe/ok")
        r2 = _prenota(sano, email="secondo@prova.it")
        self.assertEqual(r2.status, 201, "stanza rimasta bloccata: %s" % r2.corpo)
        self.assertEqual(r2.corpo["stato"], "confermata")

    def test_link_che_torna_vuoto_vale_come_avaria(self):
        """Non solo l'eccezione: anche un link vuoto/None è un gateway che non funziona."""
        inv, cat = _mondo()
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat,
                                    link_pagamento=lambda d: "")
        self.assertEqual(_prenota(proto).status, 503)

    # ── I DUE CASI LEGITTIMI, CHE NON DEVONO CAMBIARE ───────────────────────
    def test_modo_diretto_senza_gateway_resta_legittimo(self):
        """Host che incassa per conto suo: nessun gateway configurato → si conferma, come prima."""
        inv, cat = _mondo()
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat)
        r = _prenota(proto)
        self.assertEqual(r.status, 201, r.corpo)
        self.assertEqual(r.corpo["stato"], "confermata")
        self.assertNotIn("payment_url", r.corpo)

    def test_gateway_sano_conferma_col_link(self):
        """Il caso normale è intoccato: conferma + link di pagamento."""
        inv, cat = _mondo()
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat,
                                    link_pagamento=lambda d: "https://pay.stripe/sessione")
        r = _prenota(proto)
        self.assertEqual(r.status, 201, r.corpo)
        self.assertEqual(r.corpo["stato"], "confermata")
        self.assertEqual(r.corpo["payment_url"], "https://pay.stripe/sessione")


if __name__ == "__main__":
    unittest.main()
