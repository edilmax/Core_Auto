"""Collaudo BUG #32 (2026-07-17, ragionamento "che test mancano" -> gap crash-recovery):
il webhook di pagamento NON si auto-riparava dopo un CRASH a meta'.

BUG PROVATO: `_conferma_pagamento` fa un CAS `conferma` (scrive 'pagato') e POI i passi
derivati (tassa nel ledger citta' + payout 'maturato'). Se il PRIMO handler muore DOPO il
CAS ma PRIMA dei passi derivati, lo stato 'pagato' e' committato ma tassa/payout no. Stripe
ritenta il webhook per giorni, MA `_conferma_pagamento` usciva subito su stato=='pagato'
('webhook duplicato: idempotente') -> i passi derivati NON venivano mai eseguiti:
  - tassa MAI registrata nel ledger -> sotto-versamento al Comune (pass-through perso);
  - payout bloccato 'in_attesa' invece di 'maturato' -> incasso host mai maturato,
    referral che non conta la prenotazione.
Incoerenza PERMANENTE, nessun auto-riparo nonostante i retry di Stripe.

Fix: `_riasserisci_incasso` (tassa + payout maturato, IDEMPOTENTI) chiamato sia sulla
prima conferma sia sul webhook di RETRY (ramo stato=='pagato'). Credito/referral (NON
idempotenti: usa_credito decrementa un saldo) restano solo sulla prima conferma, best-effort.
"""
import datetime
import json
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_cx"


class TestCrashRecoveryWebhook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(
            lambda u, b, h: {"url": "https://x/cs", "id": "cs_" + str(time.time_ns())})

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db",
            commissione_bps=1500, psp_bps=300, stripe_secret_key="sk",
            stripe_webhook_secret=WH, stripe_success_url="https://x/ok",
            stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sis, host_key="hk", base_url="https://b.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@cx.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.hid, self.tok = c["host_id"], c["token"]
        oggi = datetime.date.today()
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa", "titolo": "C", "citta": "Roma", "prezzo_notte_cents": 20000,
                "capacita": 4, "tassa_pp_notte_cents": 200}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa", "da": oggi.isoformat(),
                "a": (oggi + datetime.timedelta(days=30)).isoformat(),
                "unita_totali": 1, "prezzo_netto_cents": 20000}, {"X-Host-Token": self.tok})
        ci = (oggi + datetime.timedelta(days=5)).isoformat()
        co = (oggi + datetime.timedelta(days=7)).isoformat()
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@cx.it"})
        self.rif = b["riferimento"]
        self.tassa = q.get("tassa_soggiorno_cents")
        self.assertGreater(self.tassa, 0)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _webhook(self, rif):
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": rif}}}})
        return self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                               {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})

    def test_retry_sana_tassa_e_payout_dopo_crash(self):
        # SIMULA CRASH: il primo handler fa solo il CAS 'pagato' e muore
        self.sis.pagamenti_pendenti.conferma(self.rif)
        self.assertEqual(self.sis.pagamenti_pendenti.info(self.rif)["stato"], "pagato")
        # stato incoerente: tassa non registrata, payout ancora in_attesa
        self.assertEqual(self.sis.tassa_comunale.totale_riscosso("Roma"), 0)
        self.assertEqual(self.sis.payout.riepilogo(self.hid).get("EUR", {}).get("maturato", 0), 0)
        # RETRY di Stripe -> deve SANARE
        s, _ = self._webhook(self.rif)
        self.assertEqual(s, 200)
        self.assertEqual(self.sis.tassa_comunale.totale_riscosso("Roma"), self.tassa,
                         "tassa non sanata dal retry")
        self.assertEqual(self.sis.payout.riepilogo(self.hid)["EUR"]["maturato"], 32776,
                         "payout non maturato dal retry")

    def test_webhook_normale_piu_retry_non_raddoppia(self):
        # conferma normale (tutti i passi) + N retry -> tassa e payout stabili (idempotenti)
        self._webhook(self.rif)
        self._webhook(self.rif)
        self._webhook(self.rif)
        self.assertEqual(self.sis.tassa_comunale.totale_riscosso("Roma"), self.tassa,
                         "retry ha raddoppiato la tassa")
        self.assertEqual(self.sis.payout.riepilogo(self.hid)["EUR"]["maturato"], 32776,
                         "retry ha alterato il payout")

    def test_retry_non_risuscita_una_cancellata(self):
        # crash 'pagato', poi la prenotazione viene CANCELLATA, poi il retry: il retry NON
        # deve registrare la tassa (tombstone) ne' maturare il payout (trattenuto)
        _, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "casa",
                      "check_in": (datetime.date.today() + datetime.timedelta(days=9)).isoformat(),
                      "check_out": (datetime.date.today() + datetime.timedelta(days=11)).isoformat(),
                      "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli2@cx.it"})
        rif2, vt2 = b["riferimento"], b["voucher_token"]
        self._webhook(rif2)                                   # pagato normale
        tassa_prima = self.sis.tassa_comunale.totale_riscosso("Roma")
        self.g("POST", "/api/concierge/cancella", {"voucher_token": vt2})   # cancellata
        self._webhook(rif2)                                   # retry tardivo
        # la tassa della cancellata non deve essere nel totale (tombstone)
        self.assertEqual(self.sis.tassa_comunale.totale_riscosso("Roma"),
                         tassa_prima - q.get("tassa_soggiorno_cents"),
                         "retry ha ri-registrato la tassa di una cancellata")


if __name__ == "__main__":
    unittest.main(verbosity=2)
