"""BOMBARDAMENTO CONCORRENTE della spina del denaro (2026-07-17, strategia "10.000 menti").

Differenza dai fuzzer "menti" (sequenziali, un'azione alla volta): qui piu' thread colpiscono
lo STESSO voucher NELLO STESSO ISTANTE (barriera) con TUTTI i ruoli intrecciati + webhook
duplicati + tick auto-rilascio. E' l'unione dei 3 scenari di concorrenza del briefing:
  1. accessi simultanei allo stesso record (100 agenti/record),
  2. azioni multi-ruolo sovrapposte (ospite annulla ∥ host annulla ∥ admin rimborsa/disputa),
  3. disallineamento webhook (Pagamento Riuscito duplicato/tardivo).

INVARIANTE ECONOMICA IMMUTABILE verificata per OGNI voucher dopo la tempesta:
  host_pagato XOR ospite_rimborsato (mai entrambi; unica eccezione lecita = quota-penale
  decisa dall'escrow su stato 'risolto'), transfer <= 1, escrow conserva
  (host_riceve + ospite_rimborso <= importo), zero overbooking.

Prova su vasta scala (in scratchpad, non nel giro quotidiano): 400 voucher, 10.000 thread
concorrenti, 10 seed -> 0 errori, 0 violazioni. Qui gira una versione veloce come GUARDIA.
"""
import datetime
import json
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_bomb"


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://x/" + secrets.token_hex(5), "id": "cs_" + secrets.token_hex(5)}


class _ConnectFinto:
    def __init__(self):
        self._lock = threading.Lock()
        self.transfers = []

    def trasferisci(self, acct, amount, currency, rif):
        with self._lock:
            self.transfers.append((str(acct), int(amount), str(currency), str(rif)))
            return "tr_%d" % len(self.transfers)


class TestBombardamentoConcorrente(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def _tempesta(self, seed, n_vouchers, agenti_per_voucher):
        import random
        rnd = random.Random(seed)
        d = tempfile.mkdtemp()
        try:
            sis = crea_sistema(ConfigCasaVIP(
                abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
                db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
                db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
                db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db",
                commissione_bps=1500, psp_bps=300,
                stripe_secret_key="sk", stripe_webhook_secret=WH,
                stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
            fc = _ConnectFinto()
            sis.connect = fc
            r = crea_router(sis, host_key="hk", admin_key="ak", base_url="https://b.com")

            def g(m, p, b=None, h=None):
                return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

            def paga(rif):
                pl = json.dumps({"type": "checkout.session.completed",
                                 "data": {"object": {"metadata": {"riferimento": rif}}}})
                r.gestisci("POST", "/api/payments/webhook", {}, pl,
                           {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})

            _, c = g("POST", "/api/host/registrazione",
                     {"email": "h@b.it", "password": "password1", "accetta_termini": True,
                      "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                      "versione": CONTRATTO_HOST_VERSIONE})
            hid, tok = c["host_id"], c["token"]
            sis.registro_host.imposta_stripe_account(hid, "acct_bomb")
            H = {"X-Host-Token": tok}
            AK = {"X-Admin-Key": "ak"}
            oggi = datetime.date.today()
            pol = ["flessibile", "moderata", "rigida", "non_rimborsabile"]
            vouchers = []
            for i in range(n_vouchers):
                slug = "casa%d" % i
                g("POST", "/api/host/pubblica",
                  {"slug": slug, "titolo": "C%d" % i, "citta": "Roma",
                   "prezzo_notte_cents": rnd.choice([5000, 20000, 90000]), "capacita": 4,
                   "politica_cancellazione": pol[i % 4]}, H)
                ci = (oggi + datetime.timedelta(days=2 + (i % 5))).isoformat()
                co = (oggi + datetime.timedelta(days=4 + (i % 5))).isoformat()
                g("POST", "/api/host/disponibilita_range",
                  {"alloggio_id": slug, "da": oggi.isoformat(),
                   "a": (oggi + datetime.timedelta(days=30)).isoformat(),
                   "unita_totali": 1, "prezzo_netto_cents": 20000}, H)
                _, q = g("POST", "/api/concierge/quote",
                         {"alloggio_id": slug, "check_in": ci, "check_out": co, "party": 2})
                if not q.get("quote_token"):
                    continue
                _, b = g("POST", "/api/concierge/book",
                         {"quote_token": q["quote_token"], "email": "cli@b.it"})
                if not (b.get("riferimento") and b.get("voucher_token")):
                    continue
                paga(b["riferimento"])
                if (sis.pagamenti_pendenti.info(b["riferimento"]) or {}).get("stato") != "pagato":
                    continue
                vouchers.append((slug, b["riferimento"], b["voucher_token"], ci, co))

            idem_by_rif = {}
            _, adm = g("GET", "/api/admin/prenotazioni", None, AK)
            for p in (adm.get("prenotazioni") or []):
                idem_by_rif[str(p.get("idem_key", ""))[:24]] = p.get("idem_key", "")

            KINDS = ["guest_cancel", "host_cancel", "admin_refund", "contesta", "risolvi",
                     "webhook_dup", "webhook_dup", "tick"]
            errs = []
            threads = []
            total = len(vouchers) * agenti_per_voucher
            self.assertGreater(total, 0, "setup: nessun voucher pagato")
            barrier = threading.Barrier(total)

            def make(kind, slug, rif, vt, ci, co, real_idem):
                def f():
                    barrier.wait()
                    try:
                        if kind == "guest_cancel":
                            g("POST", "/api/concierge/cancella", {"voucher_token": vt})
                        elif kind == "host_cancel":
                            g("POST", "/api/host/cancella", {"riferimento": rif}, H)
                        elif kind == "admin_refund":
                            g("POST", "/api/admin/rimborso",
                              {"alloggio_id": slug, "check_in": ci, "check_out": co,
                               "idem_key": real_idem}, AK)
                        elif kind == "contesta":
                            g("POST", "/api/garanzia/contesta",
                              {"voucher_token": vt, "motivo": "x"})
                        elif kind == "risolvi":
                            g("POST", "/api/admin/controversia/risolvi",
                              {"riferimento": rif,
                               "percentuale_ospite": rnd.choice([0, 50, 100])}, AK)
                        elif kind == "webhook_dup":
                            pl = json.dumps({"type": "checkout.session.completed",
                                             "data": {"object": {"metadata": {"riferimento": rif}}}})
                            r.gestisci("POST", "/api/payments/webhook", {}, pl,
                                       {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
                        elif kind == "tick":
                            sis.garanzia.auto_rilascia(ora_ts=int(time.time()) + 30 * 3600)
                    except Exception as e:  # un'eccezione qui e' un bug
                        errs.append((kind, rif, type(e).__name__, str(e)[:80]))
                return f

            for (slug, rif, vt, ci, co) in vouchers:
                real_idem = idem_by_rif.get(rif, rif)
                for _ in range(agenti_per_voucher):
                    kind = rnd.choice(KINDS)
                    threads.append(threading.Thread(
                        target=make(kind, slug, rif, vt, ci, co, real_idem)))
            for t in threads:
                t.start()
            for t in threads:
                t.join(60)
            sis.garanzia.auto_rilascia(ora_ts=int(time.time()) + 30 * 3600)

            # ---- INVARIANTE ECONOMICA per voucher ----
            viol = []
            tr_by_rif = {}
            for (_a, amt, _c, rif) in fc.transfers:
                tr_by_rif.setdefault(rif, []).append(amt)
            cong = sqlite3.connect(f"{d}/g.db")
            cong.row_factory = sqlite3.Row
            gar = {row["prenotazione_id"]: dict(row)
                   for row in cong.execute("SELECT * FROM garanzia")}
            cong.close()
            for (slug, rif, vt, ci, co) in vouchers:
                st = sis.pagamenti_pendenti.info(rif)
                gstato = (gar.get(rif) or {}).get("stato")
                trs = tr_by_rif.get(rif, [])
                rimborsato = (st and st.get("stato") in ("rimborsato", "cancellata_host")) \
                    or gstato == "annullato"
                if rimborsato and len(trs) > 0 and gstato != "risolto":
                    viol.append(("HOST_PAGATO_E_RIMBORSATO", rif, gstato, trs))
                if len(trs) > 1:
                    viol.append(("DOPPIO_TRANSFER", rif, trs))
                gq = gar.get(rif)
                if gq:
                    hr = gq["host_riceve_cents"] or 0
                    orr = gq["ospite_rimborso_cents"] or 0
                    if hr < 0 or orr < 0 or hr + orr > (gq["importo_host_cents"] or 0):
                        viol.append(("ESCROW_NON_CONSERVA", rif, dict(gq)))
            coni = sqlite3.connect(f"{d}/i.db")
            coni.row_factory = sqlite3.Row
            for row in coni.execute("SELECT alloggio_id,giorno,unita_totali,unita_occupate "
                                    "FROM inventario"):
                if row["unita_occupate"] > row["unita_totali"] or row["unita_occupate"] < 0:
                    viol.append(("OVERBOOKING", dict(row)))
            coni.close()
            self.assertEqual(errs, [], f"seed={seed}: il router ha SOLLEVATO: {errs[:3]}")
            self.assertEqual(viol, [], f"seed={seed}: invariante economica ROTTA: {viol[:5]}")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_tempesta_seed_1(self):
        self._tempesta(1, n_vouchers=10, agenti_per_voucher=12)

    def test_tempesta_seed_2(self):
        self._tempesta(2, n_vouchers=10, agenti_per_voucher=12)


if __name__ == "__main__":
    unittest.main(verbosity=2)
