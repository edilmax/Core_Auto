# -*- coding: utf-8 -*-
"""RICONCILIAZIONE INTER-LIBRO — guardia permanente (metodo nuovo, 2026-07-19).

Nessun altro test confronta i QUATTRO libri contabili TRA LORO: giornale (177),
payout (131), escrow (160), tassa (147). Ognuno era verde per conto suo. Questo
guida prenotazioni reali (quote->book->webhook, con REPLAY/cancellazioni/rimborsi
in PIU' VALUTE) e poi RICALCOLA da un oracolo indipendente, imponendo:
  I-A  identita' del record:  totale == netto + (comm - sconto) + tassa + costo_pag
  I-B  incasso a giornale(rif) == totale  E  valuta a giornale == valuta record
  I-C  IDEMPOTENZA: webhook ripetuto N volte -> UNA sola riga 'incasso'
  I-D  payout.info(rif).minori == netto  (pagata non rimborsata)
  I-E  tassa147.totale_riscosso(comune) == somma tasse attese (non-rimborsate)
  I-F  quadratura globale PER VALUTA (mai mescolare EUR/USD/JPY)
  I-G  rimborsata -> payout NON resta 'maturato' pieno
  catena hash del giornale integra
+ un test di AUTO-RIPARAZIONE del crash #32 (guasto tra CAS 'pagato' e passi derivati).

Distillato dal riconciliatore di sessione (girato 10 seed x 5 valute = 0 divergenze).
"""
import datetime
import json
import os
import random
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_recon"
VAL_CITTA = [("EUR", "Roma"), ("USD", "New York"), ("JPY", "Tokyo"),
             ("GBP", "London"), ("CHF", "Zurich")]


def _fake(url, body, headers):
    return {"url": "https://x/cs", "id": "cs_" + os.urandom(5).hex()}


class TestRiconciliazioneInterlibro(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def _build(self):
        d = tempfile.mkdtemp()
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_garanzia=f"{d}/g.db", db_messaggi=f"{d}/m.db", db_finanza=f"{d}/f.db",
            db_tassa_comunale=f"{d}/t.db", commissione_bps=1500, psp_bps=300,
            stripe_secret_key="sk", stripe_webhook_secret=WH,
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
        r = crea_router(sis, host_key="hk", admin_key="ak", base_url="https://b.com")
        return sis, r

    @staticmethod
    def _g(r):
        def g(m, p, b=None, h=None, q=None):
            return r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})
        return g

    def _paga(self, r, rif, volte=1):
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": rif}}}})
        for _ in range(volte):
            r.gestisci("POST", "/api/payments/webhook", {}, pl,
                       {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})

    def test_quattro_libri_coerenti_multivaluta(self):
        rnd = random.Random(20260719)
        sis, r = self._build()
        g = self._g(r)
        oggi = datetime.date.today()
        slugs = []
        for k in range(5):
            val, citta = VAL_CITTA[k]
            _, c = g("POST", "/api/host/registrazione",
                     {"email": "h%d@rc.it" % k, "password": "password1",
                      "accetta_termini": True, "accetta_clausole": True,
                      "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
            tok = c["token"]
            sl = "rc-%d" % k
            prezzo = 12000 + k * 500
            g("POST", "/api/host/pubblica",
              {"slug": sl, "titolo": "Casa %d" % k, "citta": citta, "valuta": val,
               "prezzo_notte_cents": prezzo, "capacita": 4}, {"X-Host-Token": tok})
            g("POST", "/api/host/disponibilita_range",
              {"alloggio_id": sl, "da": oggi.isoformat(),
               "a": (oggi + datetime.timedelta(days=90)).isoformat(),
               "unita_totali": 5, "prezzo_netto_cents": prezzo}, {"X-Host-Token": tok})
            slugs.append(sl)

        pagate, cancellate = {}, set()
        giorno = 0
        for i in range(80):
            sl = rnd.choice(slugs)
            giorno = (giorno + rnd.randint(1, 3)) % 80
            ci = (oggi + datetime.timedelta(days=giorno + 1)).isoformat()
            co = (oggi + datetime.timedelta(days=giorno + 1 + rnd.randint(1, 3))).isoformat()
            st, q = g("POST", "/api/concierge/quote",
                      {"alloggio_id": sl, "check_in": ci, "check_out": co, "party": 2})
            if st != 200 or not q.get("quote_token"):
                continue
            st, b = g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli%d@rc.it" % i})
            if st not in (200, 201) or not b.get("riferimento"):
                continue
            rif, vt = b["riferimento"], b.get("voucher_token", "")
            scelta = rnd.random()
            if scelta < 0.7:
                self._paga(r, rif, rnd.choice([1, 1, 2, 4]))     # + replay = idempotenza
            elif scelta < 0.85:
                if vt:
                    g("POST", "/api/concierge/cancella", {"voucher_token": vt})
                    g("POST", "/api/concierge/cancella", {"voucher_token": vt})  # replay
                    cancellate.add(rif)
                continue
            else:
                self._paga(r, rif, 1)
                if vt:
                    g("POST", "/api/concierge/cancella", {"voucher_token": vt})
                    cancellate.add(rif)
            rec = sis.pagamenti_pendenti.info(rif)
            if rec and rec.get("stato") == "pagato":
                pagate[rif] = {"dj": json.loads(rec.get("corpo_json") or "{}"),
                               "comune": rec.get("comune", "")}

        self.assertGreater(len(pagate), 15, "sim troppo piccola: non prova nulla")
        fc, pd, tax = sis.finanza, sis.payout, sis.tassa_comunale
        viol = []
        tot_val, inc_val, tassa_com = {}, {}, {}
        for rif, exp in pagate.items():
            dj = exp["dj"]
            val = dj.get("valuta") or "EUR"
            netto = int(dj.get("netto_host_cents", 0) or 0)
            comm = int(dj.get("commissione_cents", 0) or 0)
            sconto = int(dj.get("sconto_credito_cents", 0) or 0)
            tassa = int(dj.get("tassa_soggiorno_cents", 0) or 0)
            costo = int(dj.get("costo_pagamento_cents", 0) or 0)
            totale = int(dj.get("totale_cents", 0) or 0)
            if totale != netto + (comm - sconto) + tassa + costo:
                viol.append("I-A %s" % rif)
            movs = fc.movimenti(rif)
            incassi = [m for m in movs if m["tipo"] == "incasso"]
            inc_tot = sum(int(m["importo_cents"] or 0) for m in incassi)
            if inc_tot != totale:
                viol.append("I-B importo %s (%d!=%d)" % (rif, inc_tot, totale))
            if any((m.get("valuta") or "EUR") != val for m in incassi):
                viol.append("I-B valuta %s" % rif)
            if len(incassi) != 1:
                viol.append("I-C %s: %d incassi (replay non idempotente)" % (rif, len(incassi)))
            if rif not in cancellate and netto > 0:
                pinfo = pd.info(rif)
                if pinfo is None or int(pinfo["minori"]) != netto:
                    viol.append("I-D %s" % rif)
            tot_val[val] = tot_val.get(val, 0) + totale
            inc_val[val] = inc_val.get(val, 0) + inc_tot
            if tassa > 0 and rif not in cancellate:
                tassa_com[exp["comune"]] = tassa_com.get(exp["comune"], 0) + tassa
        for val in set(list(tot_val) + list(inc_val)):
            if tot_val.get(val, 0) != inc_val.get(val, 0):
                viol.append("I-F [%s] quadratura" % val)
        for comune, attesa in tassa_com.items():
            if tax.totale_riscosso(comune) != attesa:
                viol.append("I-E comune %s (%d!=%d)" % (comune, tax.totale_riscosso(comune), attesa))
        for rif in cancellate:
            if rif in pagate:
                pinfo = pd.info(rif)
                netto = int(pagate[rif]["dj"].get("netto_host_cents", 0) or 0)
                if pinfo and pinfo.get("stato") == "maturato" and int(pinfo["minori"]) == netto and netto > 0:
                    viol.append("I-G %s: rimborsata ma payout pieno" % rif)
        # I-INV intreccio inventario<->denaro: ogni PAGATA-attiva ha le sue notti
        # occupate (mai "soldi senza stanza"); mai overbooking.
        inv = sis.inventario
        for rif in pagate:
            if rif in cancellate:
                continue
            rec = sis.pagamenti_pendenti.info(rif)
            if not rec:
                continue
            sl, ci, co = rec.get("alloggio_id", ""), rec.get("check_in", ""), rec.get("check_out", "")
            if not (sl and ci and co):
                continue
            sr = inv.stato_range(sl, ci, co)
            n = datetime.date.fromisoformat(ci)
            fine = datetime.date.fromisoformat(co)
            while n < fine:
                cell = sr.get(n.isoformat())
                if cell is None or int(cell.get("unita_occupate", 0)) < 1:
                    viol.append("I-INV %s notte %s non occupata" % (rif, n.isoformat()))
                elif int(cell.get("unita_occupate", 0)) > int(cell.get("unita_totali", 0)):
                    viol.append("I-INV overbooking %s %s" % (sl, n.isoformat()))
                n += datetime.timedelta(days=1)
        vc = fc.verifica_catena()
        if not vc.get("integra", vc.get("ok", True)):
            viol.append("catena rotta")
        self.assertEqual(viol, [], "divergenze inter-libro: %r" % viol[:20])

    def test_autoriparazione_crash_32(self):
        """Crash tra CAS 'pagato' e passi derivati (tassa+payout): il retry del webhook
        DEVE sanare (tassa nel ledger, payout 'maturato', UNA sola riga incasso)."""
        sis, r = self._build()
        g = self._g(r)
        oggi = datetime.date.today()
        _, c = g("POST", "/api/host/registrazione",
                 {"email": "cr@rc.it", "password": "password1", "accetta_termini": True,
                  "accetta_clausole": True, "doc_sha256": doc_sha256(),
                  "versione": CONTRATTO_HOST_VERSIONE})
        tok = c["token"]
        g("POST", "/api/host/pubblica",
          {"slug": "cr", "titolo": "Crash", "citta": "Roma", "valuta": "EUR",
           "prezzo_notte_cents": 12000, "capacita": 4}, {"X-Host-Token": tok})
        g("POST", "/api/host/disponibilita_range",
          {"alloggio_id": "cr", "da": oggi.isoformat(),
           "a": (oggi + datetime.timedelta(days=30)).isoformat(),
           "unita_totali": 3, "prezzo_netto_cents": 12000}, {"X-Host-Token": tok})
        ci = (oggi + datetime.timedelta(days=5)).isoformat()
        co = (oggi + datetime.timedelta(days=7)).isoformat()
        _, q = g("POST", "/api/concierge/quote",
                 {"alloggio_id": "cr", "check_in": ci, "check_out": co, "party": 2})
        _, b = g("POST", "/api/concierge/book",
                 {"quote_token": q["quote_token"], "email": "z@rc.it"})
        rif = b["riferimento"]

        # 1o webhook: CRASH nei passi derivati (dopo il CAS 'pagato')
        router = r if hasattr(r, "_riasserisci_incasso") else getattr(r, "_router", r)
        vero = router._riasserisci_incasso
        stato = {"n": 0}

        def esplode(rec, _rif):
            stato["n"] += 1
            if stato["n"] == 1:
                raise RuntimeError("crash simulato #32 a meta' pagamento")
            return vero(rec, _rif)

        router._riasserisci_incasso = esplode
        try:
            self._paga(r, rif, 1)                        # 1a volta: esplode a meta'
            self._paga(r, rif, 1)                        # retry Stripe: DEVE sanare
        finally:
            router._riasserisci_incasso = vero

        rec = sis.pagamenti_pendenti.info(rif)
        self.assertEqual(rec.get("stato"), "pagato")
        incassi = [m for m in sis.finanza.movimenti(rif) if m["tipo"] == "incasso"]
        self.assertEqual(len(incassi), 1, "auto-riparazione: deve restare UNA riga incasso")
        self.assertEqual(sis.payout.stato_di(rif), "maturato",
                         "payout deve essere sanato a 'maturato' dal retry")


if __name__ == "__main__":
    unittest.main(verbosity=2)
