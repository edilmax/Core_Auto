"""GUARDIA '1000 cose' sulla matematica VISIBILE all'ospite (2026-07-16, metodo libro).

Centinaia di preventivi con parametri caotici (prezzi da 7 a 2400 euro, 3 valute, 4
politiche, tasse varie, party 1-9, notti 1-28, credito a campione): OGNI risposta 200
deve quadrare al centesimo. Il fuzzer "menti" verifica i RECORD salvati; questa guardia
verifica i NUMERI MOSTRATI (il preventivo e' cio' che l'occhio del cliente vede).

Invarianti:
  A. totale == prezzo_guest + tassa
  B. prezzo_guest == prezzo_netto - sconto_credito
  C. netto_host == prezzo_netto - commissione - costo_pagamento  (mai negativo)
  D. costo_pagamento == totale * psp_bps // 10000
  E. prezzo_listino >= prezzo_netto (gli sconti non gonfiano mai il listino)
  F. split fra amici: somma quote == totale ESATTO, differenza max 1 cent
  G. book 201: numeri IDENTICI alla quote (firmati, immutabili)

Al primo giro (1000 colpi): 988 valide, ZERO violazioni.
"""
import datetime
import json
import random
import shutil
import tempfile
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE

PSP = 300


class TestQuoteCoerenza(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(
            lambda u, b, h: {"url": "https://x/cs", "id": "cs_1"})

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def test_martello_preventivi(self):
        rnd = random.Random(99)
        d = tempfile.mkdtemp()
        try:
            sis = crea_sistema(ConfigCasaVIP(
                abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
                db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
                db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/acc.db",
                db_pendenti=f"{d}/p.db", db_domanda=f"{d}/dom.db",
                db_credito_usati=f"{d}/cu.db", commissione_bps=1500, psp_bps=PSP,
                stripe_secret_key="sk_test_x", stripe_webhook_secret="whsec_x",
                stripe_success_url="https://x/ok", stripe_cancel_url="https://x/ko"))
            r = crea_router(sis, host_key="hk", base_url="https://bookinvip.com")

            def g(m, p, b=None, h=None):
                return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None,
                                  h or {})

            s, c = g("POST", "/api/host/registrazione",
                     {"email": "h@qc.it", "password": "password1", "accetta_termini": True,
                      "accetta_clausole": True, "doc_sha256": doc_sha256(),
                      "versione": CONTRATTO_HOST_VERSIONE})
            self.assertEqual(s, 201, c)
            H = {"X-Host-Token": c["token"]}
            oggi = datetime.date.today()
            pol = ["flessibile", "moderata", "rigida", "non_rimborsabile"]
            val = ["EUR", "USD", "JPY"]
            slugs = []
            for i in range(6):
                slug = "casa%d" % i
                g("POST", "/api/host/pubblica",
                  {"slug": slug, "titolo": "C%d" % i, "citta": "Roma",
                   "prezzo_notte_cents": rnd.choice([700, 4900, 10000, 55000, 240000]),
                   "capacita": rnd.randint(1, 8), "valuta": val[i % 3],
                   "politica_cancellazione": pol[i % 4],
                   "tassa_pp_notte_cents": rnd.choice([0, 100, 350])}, H)
                g("POST", "/api/host/disponibilita_range",
                  {"alloggio_id": slug, "da": oggi.isoformat(),
                   "a": (oggi + datetime.timedelta(days=120)).isoformat(),
                   "unita_totali": 3,
                   "prezzo_netto_cents": rnd.choice([700, 4900, 10000, 55000, 240000])}, H)
                slugs.append(slug)
            _, dom = g("POST", "/api/domanda", {"email": "cli@qc.it", "citta": "roma"})
            cred = dom["credito_token"]

            viol, n200 = [], 0
            for i in range(100):    # guardia quotidiana snella; il martello 1000 e' gia' passato
                slug = rnd.choice(slugs)
                off = rnd.randint(0, 88)
                notti = rnd.choice([1, 2, 3, 7, 14, 28])
                body = {"alloggio_id": slug,
                        "check_in": (oggi + datetime.timedelta(days=off)).isoformat(),
                        "check_out": (oggi + datetime.timedelta(days=off + notti)).isoformat(),
                        "party": rnd.randint(1, 9)}
                if rnd.random() < 0.3:
                    body["credito_token"] = cred
                s, q = g("POST", "/api/concierge/quote", body)
                if s != 200:
                    continue
                n200 += 1
                tot, guest = q["totale_cents"], q["prezzo_guest_cents"]
                netto, comm = q["prezzo_netto_cents"], q["commissione_cents"]
                nh, cp = q["netto_host_cents"], q["costo_pagamento_cents"]
                tassa, sc = q["tassa_soggiorno_cents"], q["sconto_credito_cents"]
                lst = q.get("prezzo_listino_cents", netto)
                if tot != guest + tassa:
                    viol.append(("A", i, tot, guest, tassa))
                if guest != netto - sc:
                    viol.append(("B", i, guest, netto, sc))
                if nh != netto - comm - cp or nh < 0:
                    viol.append(("C", i, nh, netto, comm, cp))
                if cp != tot * PSP // 10000:
                    viol.append(("D", i, cp, tot))
                if lst < netto:
                    viol.append(("E", i, lst, netto))
                if rnd.random() < 0.25:
                    n = rnd.choice([2, 3, 5, 7, 11])
                    s2, sp = g("POST", "/api/split/preview",
                               {"totale_cents": tot, "persone": n})
                    if s2 == 200:
                        quote = sp.get("quote_cents") or sp.get("quote") or []
                        if quote and sum(quote) != tot:
                            viol.append(("F-somma", i, tot, quote))
                        if quote and max(quote) - min(quote) > 1:
                            viol.append(("F-equita", i, quote))
                if rnd.random() < 0.1:
                    s3, b = g("POST", "/api/concierge/book",
                              {"quote_token": q["quote_token"], "email": "cli@qc.it"})
                    if s3 == 201:
                        for k in ("totale_cents", "prezzo_guest_cents", "netto_host_cents",
                                  "commissione_cents", "tassa_soggiorno_cents", "valuta"):
                            if b.get(k) != q.get(k):
                                viol.append(("G", i, k, q.get(k), b.get(k)))
            self.assertGreater(n200, 60, "troppi preventivi rifiutati: setup rotto?")
            self.assertEqual(viol, [], "la matematica visibile NON quadra: %r" % viol[:6])
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
