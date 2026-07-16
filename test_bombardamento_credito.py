"""BOMBARDAMENTO referral/credito multi-valuta (2026-07-17, strategia "10.000 menti",
modulo Referral→Qualifica→Credito — scenari #1 double-spend e #2 qualifica multipla).

A) DOUBLE-SPEND: un SOLO credito, N book+pay CONCORRENTI su N alloggi diversi (le "due
   schede" del briefing). Il consumo single-use (fase167.consuma, BEGIN IMMEDIATE + PK sul
   credito_id) fa vincere UNA sola finalizzazione: le altre ottengono 'diverso' -> 409 e la
   stanza si libera. INVARIANTE: somma sconti sui PAGATI <= nominale; credito consumato 1 volta.

B) QUALIFICA MULTIPLA: N invitati dello STESSO referrer qualificano nello stesso istante.
   Ogni qualifica (fase76.qualifica_referee) e' atomica su una riga distinta -> INVARIANTE:
   saldo referrer == N * premio (nessun lost-update, nessun deadlock).

NB VALUTA (fix #29): il credito e' like-for-like, NON si converte -> l'invariante
`nominale == speso + residuo` vale PER VALUTA banalmente (cross-valuta = sconto 0, mai FX).
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

WH = "whsec_cr"


def _fake_fetch(url, body, headers):
    return {"url": "https://x/cs", "id": "cs_" + str(time.time_ns())}


class TestBombardamentoCredito(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def _sistema(self, d):
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_garanzia=f"{d}/g.db", db_domanda=f"{d}/dom.db", db_credito_usati=f"{d}/cu.db",
            db_viral=f"{d}/v.db", commissione_bps=1500, psp_bps=300,
            stripe_secret_key="sk", stripe_webhook_secret=WH,
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
        r = crea_router(sis, host_key="hk", admin_key="ak", base_url="https://b.com")
        return sis, r

    def test_double_spend_credito_impossibile(self):
        d = tempfile.mkdtemp()
        try:
            sis, r = self._sistema(d)

            def g(m, p, b=None, h=None):
                return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

            def paga(rif):
                pl = json.dumps({"type": "checkout.session.completed",
                                 "data": {"object": {"metadata": {"riferimento": rif}}}})
                r.gestisci("POST", "/api/payments/webhook", {}, pl,
                           {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})

            _, c = g("POST", "/api/host/registrazione",
                     {"email": "h@c.it", "password": "password1", "accetta_termini": True,
                      "accetta_clausole": True, "doc_sha256": doc_sha256(),
                      "versione": CONTRATTO_HOST_VERSIONE})
            H = {"X-Host-Token": c["token"]}
            oggi = datetime.date.today()
            N = 10
            for i in range(N):
                g("POST", "/api/host/pubblica",
                  {"slug": "casa%d" % i, "titolo": "C%d" % i, "citta": "Roma",
                   "prezzo_notte_cents": 20000, "capacita": 4}, H)
                g("POST", "/api/host/disponibilita_range",
                  {"alloggio_id": "casa%d" % i, "da": oggi.isoformat(),
                   "a": (oggi + datetime.timedelta(days=60)).isoformat(),
                   "unita_totali": 1, "prezzo_netto_cents": 20000}, H)
            _, dom = g("POST", "/api/domanda", {"email": "cli@c.it", "citta": "roma"})
            cred = dom["credito_token"]
            ci = (oggi + datetime.timedelta(days=3)).isoformat()
            co = (oggi + datetime.timedelta(days=5)).isoformat()
            barrier = threading.Barrier(N)

            def compra(i):
                barrier.wait()
                _, q = g("POST", "/api/concierge/quote",
                         {"alloggio_id": "casa%d" % i, "check_in": ci, "check_out": co,
                          "party": 2, "credito_token": cred})
                if not q.get("quote_token"):
                    return
                _, b = g("POST", "/api/concierge/book",
                         {"quote_token": q["quote_token"], "email": "cli@c.it"})
                if b.get("riferimento") and b.get("stato") in ("confermata", "in_attesa_pagamento"):
                    paga(b["riferimento"])

            ths = [threading.Thread(target=compra, args=(i,)) for i in range(N)]
            for t in ths:
                t.start()
            for t in ths:
                t.join(30)

            conp = sqlite3.connect(f"{d}/p.db")
            conp.row_factory = sqlite3.Row
            tot_sconto, n_con_sconto = 0, 0
            for row in conp.execute("SELECT stato, corpo_json FROM pendenti"):
                if row["stato"] != "pagato":
                    continue
                try:
                    dj = json.loads(row["corpo_json"] or "{}")
                except Exception:
                    dj = {}
                sc = dj.get("sconto_credito_cents", 0)
                if sc > 0:
                    tot_sconto += sc
                    n_con_sconto += 1
            conp.close()
            conu = sqlite3.connect(f"{d}/cu.db")
            n_usati = conu.execute("SELECT COUNT(*) FROM crediti_usati").fetchone()[0]
            conu.close()
            self.assertLessEqual(tot_sconto, 500,
                                 "DOUBLE-SPEND: sconto totale %d > nominale 500" % tot_sconto)
            self.assertLessEqual(n_con_sconto, 1, "piu' di un pagato con lo stesso credito")
            self.assertLessEqual(n_usati, 1, "credito consumato piu' di una volta")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_qualifica_multipla_no_lost_update(self):
        d = tempfile.mkdtemp()
        try:
            sis, _ = self._sistema(d)
            viral = sis.viral
            cod = viral.genera_codice("REFERR")
            N, premio = 10, 4000
            for k in range(N):
                self.assertTrue(viral.registra_referee(cod, "inv%d" % k).ok)
            base = viral.credito_disponibile("REFERR")
            barrier = threading.Barrier(N)

            def qualifica(k):
                barrier.wait()
                viral.qualifica_referee("inv%d" % k, premio_cents=premio)

            ths = [threading.Thread(target=qualifica, args=(k,)) for k in range(N)]
            for t in ths:
                t.start()
            for t in ths:
                t.join(30)
            delta = viral.credito_disponibile("REFERR") - base
            self.assertEqual(delta, N * premio,
                             "LOST UPDATE: referrer +%d, atteso +%d" % (delta, N * premio))
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
