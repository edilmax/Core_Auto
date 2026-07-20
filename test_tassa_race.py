"""Collaudo BUG #31 (2026-07-17, bombardamento concorrente ledger tassa di soggiorno):
la TASSA restava contata per prenotazioni RIMBORSATE sotto la race webhook-pay ∥ cancel.

BUG PROVATO (107 violazioni in concorrenza): la tassa di soggiorno (pass-through alla
citta') e' registrata nel ledger al pagamento (`_conferma_pagamento`) e stornata alla
cancellazione. Due difetti sotto concorrenza:
  (1) il guest-cancel chiamava `_storna_tassa` SOLO `if pagato_davvero` -> se leggeva la
      prenotazione ancora 'in_attesa' un istante prima del webhook, non stornava mai, e un
      webhook concorrente registrava la tassa DOPO -> tassa su prenotazione rimborsata;
  (2) anche stornando, se lo `storna` (DELETE) precedeva la `registra_riscossione` (INSERT)
      la tassa risorgeva.
Effetto: `totale_riscosso` sovra-contava i rimborsati -> rischio di versare alla citta' una
tassa gia' restituita all'ospite = NOSTRA PERDITA (stessa classe del fix #5, finestra concorrente).

Fix: (a) `fase147.storna` = TOMBSTONE permanente (importo=0 + stornato=1, in BEGIN IMMEDIATE);
`registra_riscossione` in BEGIN IMMEDIATE rifiuta se gia' presente/stornato -> chiude la race
in entrambi gli ordini; `totale_riscosso` filtra `stornato=0`. (b) il guest-cancel chiama
`_storna_tassa` SEMPRE (non solo se pagato) -> il tombstone e' posato anche se il pagamento
non risulta ancora incassato, bloccando una riscossione tardiva/concorrente.
"""
import datetime
import json
import random
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
from fase147_tassa_comunale import crea_tassa_comunale

WH = "whsec_tx"


class TestTassaTombstone(unittest.TestCase):
    """Unit: il tombstone dello store chiude la race in ENTRAMBI gli ordini."""

    def test_storna_prima_di_registra_non_riattiva(self):
        d = tempfile.mkdtemp()
        try:
            led = crea_tassa_comunale(f"{d}/t.db")
            led.inizializza_schema()
            led.storna("R1")                                  # tombstone PRIMA
            led.registra_riscossione("R1", "Roma", 800)       # tardiva -> deve essere respinta
            self.assertEqual(led.totale_riscosso("Roma"), 0)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_registra_poi_storna_azzera(self):
        d = tempfile.mkdtemp()
        try:
            led = crea_tassa_comunale(f"{d}/t.db")
            led.inizializza_schema()
            led.registra_riscossione("R2", "Roma", 800)
            self.assertEqual(led.totale_riscosso("Roma"), 800)
            led.storna("R2")
            self.assertEqual(led.totale_riscosso("Roma"), 0)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_registra_normale_non_stornata_conta(self):
        d = tempfile.mkdtemp()
        try:
            led = crea_tassa_comunale(f"{d}/t.db")
            led.inizializza_schema()
            led.registra_riscossione("R3", "Roma", 500)
            led.registra_riscossione("R3", "Roma", 999)       # idempotente: non raddoppia
            self.assertEqual(led.totale_riscosso("Roma"), 500)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestTassaRaceEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(
            lambda u, b, h: {"url": "https://x/cs", "id": "cs_" + str(time.time_ns())})

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def _tempesta(self, seed, n_pren):
        rnd = random.Random(seed)
        d = tempfile.mkdtemp()
        try:
            sis = crea_sistema(ConfigCasaVIP(
                abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
                db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
                db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
                db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db",
                commissione_bps=1500, psp_bps=300, stripe_secret_key="sk",
                stripe_webhook_secret=WH, stripe_success_url="https://x/ok",
                stripe_cancel_url="https://x/no"))
            r = crea_router(sis, host_key="hk", base_url="https://b.com")

            def g(m, p, b=None, h=None):
                return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

            def paga(rif):
                pl = json.dumps({"type": "checkout.session.completed",
                                 "data": {"object": {"metadata": {"riferimento": rif}}}})
                r.gestisci("POST", "/api/payments/webhook", {}, pl,
                           {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})

            _, c = g("POST", "/api/host/registrazione",
                     {"email": "h@tx.it", "password": "password1", "accetta_termini": True,
                      "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                      "versione": CONTRATTO_HOST_VERSIONE})
            H = {"X-Host-Token": c["token"]}
            oggi = datetime.date.today()
            g("POST", "/api/host/pubblica",
              {"slug": "casa", "titolo": "C", "citta": "Roma", "prezzo_notte_cents": 20000,
               "capacita": 4, "tassa_pp_notte_cents": 200,
               "politica_cancellazione": "flessibile"}, H)
            g("POST", "/api/host/disponibilita_range",
              {"alloggio_id": "casa", "da": oggi.isoformat(),
               "a": (oggi + datetime.timedelta(days=90)).isoformat(),
               "unita_totali": n_pren + 2, "prezzo_netto_cents": 20000}, H)
            vouchers = []
            for i in range(n_pren):
                ci = (oggi + datetime.timedelta(days=3 + i)).isoformat()
                co = (oggi + datetime.timedelta(days=5 + i)).isoformat()
                _, q = g("POST", "/api/concierge/quote",
                         {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
                if not q.get("quote_token"):
                    continue
                _, b = g("POST", "/api/concierge/book",
                         {"quote_token": q["quote_token"], "email": "c%d@tx.it" % i})
                if b.get("riferimento"):
                    vouchers.append((b["riferimento"], b["voucher_token"],
                                     q.get("tassa_soggiorno_cents", 0)))
            self.assertGreater(len(vouchers), 0)
            barrier = threading.Barrier(len(vouchers) + len(vouchers) // 2)

            def do_pay(rif):
                barrier.wait()
                paga(rif)

            def do_cancel(vt):
                barrier.wait()
                g("POST", "/api/concierge/cancella", {"voucher_token": vt})

            ths = []
            for idx, (rif, vt, tassa) in enumerate(vouchers):
                ths.append(threading.Thread(target=do_pay, args=(rif,)))
                if idx % 2 == 0:                              # meta' viene cancellata in gara
                    ths.append(threading.Thread(target=do_cancel, args=(vt,)))
            rnd.shuffle(ths)
            for t in ths:
                t.start()
            for t in ths:
                t.join(60)

            cont = sqlite3.connect(f"{d}/t.db")
            conp = sqlite3.connect(f"{d}/p.db")
            conp.row_factory = sqlite3.Row
            atteso = 0
            for (rif, vt, tassa) in vouchers:
                row = cont.execute("SELECT importo, stornato FROM tassa_riscossione "
                                   "WHERE prenotazione_id=?", (rif,)).fetchone()
                rec = conp.execute("SELECT stato FROM pendenti WHERE riferimento=?",
                                   (rif,)).fetchone()
                stato = rec["stato"] if rec else None
                contato = row[0] if (row and not row[1]) else 0
                if stato in ("rimborsato", "cancellata_host"):
                    self.assertEqual(contato, 0,
                                     "tassa contata su rimborsato %s: %d" % (rif, contato))
                if stato == "pagato":
                    atteso += tassa
            cont.close()
            conp.close()
            self.assertEqual(sis.tassa_comunale.totale_riscosso("Roma"), atteso,
                             "totale_riscosso != somma tasse dei pagati vivi")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_pay_vs_cancel_tassa_non_sovraconta(self):
        for seed in range(4):
            self._tempesta(seed, 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
