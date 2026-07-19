# -*- coding: utf-8 -*-
"""FANTASMI TERMINALI — guardia permanente (metodo deep-seek, 2026-07-19).

I test per-movimento non guardano lo STATO DI RIPOSO FINALE: qui ogni prenotazione viene
guidata fino in fondo al suo ramo (A ospite-conferma, B auto-rilascio 24h, C arbitro 100%
ospite, D arbitro parziale, E cancellazione ospite, F hold mai pagato scaduto) facendo
scattare tutti gli orologi (auto_rilascia nel futuro, sweep hold), e a fine corsa l'oracolo
verifica che NESSUN libro abbia fantasmi:
  - escrow ancora 'in_garanzia' (host mai pagato per sempre)
  - payout ancora 'in_attesa' (guadagno fantasma)
  - doppia riga 'incasso' a giornale
  - commissione a giornale != comm+costo-credito del record
  - quadratura incassi==totali PER VALUTA (EUR/USD/JPY mai mescolate)
  - catena hash del giornale rotta
Distillato dal cacciatore di sessione (8 seed x 180 pren = 0 fantasmi). Il primo giro
dell'harness ha insegnato a VALIDARE l'oracolo: l'orizzonte dell'orologio deve superare
l'ultimo check-in + 24h, o l'auto-rilascio legittimamente non scatta (falso fantasma).
"""
import datetime
import json
import os
import random
import sqlite3
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, sweep_hold_una_passata
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_ghost"
VAL_CITTA = [("EUR", "Roma"), ("USD", "New York"), ("JPY", "Tokyo")]


def _fake(url, body, headers):
    return {"url": "https://x/cs", "id": "cs_" + os.urandom(5).hex()}


class TestFantasmiTerminali(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def test_ogni_ramo_a_riposo_senza_fantasmi(self):
        rnd = random.Random(20260720)
        d = tempfile.mkdtemp()
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_garanzia=f"{d}/g.db", db_finanza=f"{d}/f.db", db_tassa_comunale=f"{d}/t.db",
            commissione_bps=1000, psp_bps=300, stripe_secret_key="sk",
            stripe_webhook_secret=WH, stripe_success_url="x", stripe_cancel_url="x"))
        r = crea_router(sis, host_key="hk", admin_key="ak", base_url="https://b.com")
        sis.connect.trasferisci = lambda a, m, c, rf: "tr_" + os.urandom(3).hex()
        AK = {"X-Admin-Key": "ak"}

        def g(m, p, b=None, h=None):
            return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

        oggi = datetime.date.today()
        slugs = []
        for k in range(3):
            val, citta = VAL_CITTA[k]
            _, c = g("POST", "/api/host/registrazione",
                     {"email": "h%d@gt.it" % k, "password": "password1",
                      "accetta_termini": True, "accetta_clausole": True,
                      "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
            tok = c["token"]
            sl = "gt-%d" % k
            g("POST", "/api/host/pubblica",
              {"slug": sl, "titolo": "Casa %d" % k, "citta": citta, "valuta": val,
               "prezzo_notte_cents": 20000 + k * 1111, "capacita": 4}, {"X-Host-Token": tok})
            g("POST", "/api/host/disponibilita_range",
              {"alloggio_id": sl, "da": oggi.isoformat(),
               "a": (oggi + datetime.timedelta(days=120)).isoformat(),
               "unita_totali": 6, "prezzo_netto_cents": 20000 + k * 1111},
              {"X-Host-Token": tok})
            slugs.append((sl, val))

        def paga(rif):
            pl = json.dumps({"type": "checkout.session.completed",
                             "data": {"object": {"metadata": {"riferimento": rif}}}})
            r.gestisci("POST", "/api/payments/webhook", {}, pl,
                       {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})

        prenote = {}
        giorno = 0
        for i in range(100):
            sl, val = rnd.choice(slugs)
            giorno = (giorno + rnd.randint(1, 3)) % 100
            ci = (oggi + datetime.timedelta(days=giorno + 2)).isoformat()
            co = (oggi + datetime.timedelta(days=giorno + 2 + rnd.randint(1, 3))).isoformat()
            st, q = g("POST", "/api/concierge/quote",
                      {"alloggio_id": sl, "check_in": ci, "check_out": co, "party": 2})
            if st != 200 or not q.get("quote_token"):
                continue
            st, b = g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "c%d@gt.it" % i})
            if st not in (200, 201) or not b.get("riferimento"):
                continue
            rif, vt = b["riferimento"], b.get("voucher_token", "")
            ramo = rnd.choice(["A", "B", "C", "D", "E", "F"])
            info = {"ramo": ramo, "val": val}
            if ramo == "F":
                prenote[rif] = info
                continue
            paga(rif)
            rec = sis.pagamenti_pendenti.info(rif)
            if not (rec and rec.get("stato") == "pagato"):
                continue
            info["dj"] = json.loads(rec.get("corpo_json") or "{}")
            if ramo == "A":
                g("POST", "/api/garanzia/conferma", {"voucher_token": vt})
            elif ramo == "C":
                g("POST", "/api/garanzia/contesta", {"voucher_token": vt})
                g("POST", "/api/admin/controversia/risolvi",
                  {"riferimento": rif, "percentuale_ospite": 100}, AK)
            elif ramo == "D":
                g("POST", "/api/garanzia/contesta", {"voucher_token": vt})
                g("POST", "/api/admin/controversia/risolvi",
                  {"riferimento": rif, "percentuale_ospite": 40}, AK)
            elif ramo == "E":
                g("POST", "/api/concierge/cancella", {"voucher_token": vt})
            prenote[rif] = info

        self.assertGreater(len(prenote), 40, "sim troppo piccola")
        # tutti gli orologi: auto-rilascio OLTRE l'ultimo check-in (+120gg) + finestra 24h
        futuro = int(time.time()) + 200 * 86400
        for rr in (sis.garanzia.auto_rilascia(ora_ts=futuro, dettagli=True) or []):
            try:
                r._trasferisci_all_host(rr["prenotazione_id"], rr["host_riceve_cents"])
            except Exception:
                pass
        con = sqlite3.connect(f"{d}/p.db")
        con.execute("UPDATE pendenti SET scadenza_ts=? WHERE stato='in_attesa'",
                    (int(time.time()) - 10,))
        con.commit(); con.close()
        for _ in range(2):
            sweep_hold_una_passata(sis, r)

        fant = []
        fc, pd, gz = sis.finanza, sis.payout, sis.garanzia
        tot_val, inc_val = {}, {}
        for rif, info in prenote.items():
            ramo = info["ramo"]
            se = gz.stato(rif)
            stato_e = se.get("stato") if isinstance(se, dict) else None
            stato_pay = pd.stato_di(rif)
            movs = fc.movimenti(rif)
            if stato_e == "in_garanzia":
                fant.append("ESCROW-LIMBO %s ramo %s" % (rif[:8], ramo))
            if stato_pay == "in_attesa":
                fant.append("PAYOUT-LIMBO %s ramo %s" % (rif[:8], ramo))
            n_inc = sum(1 for m in movs if m["tipo"] == "incasso")
            if n_inc > 1:
                fant.append("DOPPIO-INCASSO %s" % rif[:8])
            if ramo in ("A", "B") and stato_e != "rilasciato":
                fant.append("RAMO %s %s: escrow=%s" % (ramo, rif[:8], stato_e))
            if "dj" in info:
                dj, val = info["dj"], info["val"]
                totale = int(dj.get("totale_cents", 0) or 0)
                inc = sum(int(m["importo_cents"] or 0) for m in movs if m["tipo"] == "incasso")
                tot_val[val] = tot_val.get(val, 0) + totale
                inc_val[val] = inc_val.get(val, 0) + inc
                comm_att = (int(dj.get("commissione_cents", 0) or 0)
                            + int(dj.get("costo_pagamento_cents", 0) or 0)
                            - int(dj.get("sconto_credito_cents", 0) or 0))
                comm_gio = sum(int(m["importo_cents"] or 0) for m in movs
                               if m["tipo"] == "commissione")
                if comm_att > 0 and comm_gio != comm_att:
                    fant.append("COMMISSIONE %s: %d != %d" % (rif[:8], comm_gio, comm_att))
        for val in set(list(tot_val) + list(inc_val)):
            if tot_val.get(val, 0) != inc_val.get(val, 0):
                fant.append("QUADRATURA [%s]: %d != %d"
                            % (val, tot_val.get(val, 0), inc_val.get(val, 0)))
        if not fc.verifica_catena().get("ok"):
            fant.append("CATENA ROTTA")
        self.assertEqual(fant, [], "fantasmi allo stato terminale: %r" % fant[:15])


if __name__ == "__main__":
    unittest.main(verbosity=2)
