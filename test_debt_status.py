"""Collaudo FINANCIAL CONTROLLER Scatto ② — DEBT STATUS (riscossione alla fonte).

Chiude la falda "noi in perdita": un debito 'aperto' (penale non coperta al momento
della cancellazione) si RISCUOTE DA SOLO sui payout futuri dell'host, PRIMA di ogni
bonifico. E il bonifico parte SEMPRE per la verità del ledger payout (fix overpay:
prima l'importo veniva dalla garanzia, che non sa delle compensazioni).
Invarianti:
  1. riscuoti_debiti: salda FIFO dai maturato, stessa valuta, giornale-prima,
     nota->'saldata', debito->'saldato', catena hash intatta;
  2. parziale: payout consumato, debito resta 'aperto' col residuo; il maturato
     successivo lo estingue;
  3. IDEMPOTENTE: ri-chiamare non riconta (evento_id nel giornale);
  4. valuta diversa MAI toccata; il payout della prenotazione del debito stesso escluso;
  5. FIX OVERPAY (integrazione): dopo l'offset di Scatto ① su un altro payout, la
     conferma ospite bonifica l'importo RIDOTTO dal ledger, non il pieno della garanzia;
  6. riscossione LIVE: debito aperto + nuova prenotazione pagata -> al rilascio parte
     netto-debito, debito saldato, DEBT_COLLECTED;
  7. trasparenza: l'host vede il debito in /api/host/payout; il Bunker in /integrita.
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
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE


class ConnectFinto:
    def __init__(self):
        self.transfers = []

    def trasferisci(self, acct, amount, currency, rif):
        self.transfers.append((acct, amount, currency, rif))
        return "tr_%d" % len(self.transfers)


class TestDebtStatus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(
            lambda u, b, h: {"url": "https://checkout.stripe.test/cs", "id": "cs_1"})

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/acc.db",
            db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db", db_garanzia=f"{d}/g.db",
            db_finanza=f"{d}/fin.db", bunker_password="SuperPw@1",
            commissione_bps=1000, psp_bps=300,
            stripe_secret_key="sk_test_x", stripe_webhook_secret="whsec_x",
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/ko"))
        self.fcn = ConnectFinto()
        self.sis.connect = self.fcn
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@debt.it", "password": "password1",
                       "accetta_termini": True, "accetta_clausole": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.hid, self.tok = c["host_id"], c["token"]
        self.sis.registro_host.imposta_stripe_account(self.hid, "acct_test")
        self.fc = self.sis.finanza
        self.pd = self.sis.payout

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None,
                               h or {})

    def _pubblica(self, slug):
        oggi = datetime.date.today()
        self.g("POST", "/api/host/pubblica",
               {"slug": slug, "titolo": "Casa D", "citta": "Roma",
                "prezzo_notte_cents": 10000, "capacita": 2}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": slug, "da": oggi.isoformat(),
                "a": (oggi + datetime.timedelta(days=60)).isoformat(),
                "unita_totali": 1, "prezzo_netto_cents": 10000}, {"X-Host-Token": self.tok})

    def _book_paga(self, slug, giorni=30):
        oggi = datetime.date.today()
        ci = (oggi + datetime.timedelta(days=giorni)).isoformat()
        co = (oggi + datetime.timedelta(days=giorni + 2)).isoformat()
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": slug, "check_in": ci, "check_out": co, "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@debt.it"})
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata":
                                                  {"riferimento": b["riferimento"]}}}})
        sig = firma_di_test(payload, "whsec_x", int(time.time()))
        self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                        {"Stripe-Signature": sig})
        self.assertEqual(self.sis.pagamenti_pendenti.info(b["riferimento"])["stato"],
                         "pagato")
        return b

    def _debito_diretto(self, rif="B-DEB", cents=2550):
        """Debito 'aperto' pieno: penale processata con ledger payout VUOTO."""

        class _PayVuoto:
            def elenca(self, *a, **k):
                return []
        out = self.fc.processa_penale(riferimento=rif, host_id=self.hid,
                                      penale_cents=cents, valuta="EUR",
                                      payout=_PayVuoto())
        self.assertEqual(out["residuo_cents"], cents)
        return out

    # ── 1) riscossione piena ───────────────────────────────────────────────────
    def test_riscossione_salda_e_riduce(self):
        self._debito_diretto(cents=2550)
        self.pd.registra_maturato("A2", self.hid, 17000, "EUR")
        ris = self.fc.riscuoti_debiti(host_id=self.hid, payout=self.pd)
        self.assertEqual(ris["riscossi_cents"], 2550)
        self.assertEqual(ris["debiti_saldati"], 1)
        self.assertEqual(ris["debiti_aperti"], 0)
        self.assertEqual(self.pd.info("A2")["minori"], 14450)      # 17000 - 2550
        self.assertEqual(self.fc.debiti_host(self.hid, stato="aperto"), [])
        tipi = [m["tipo"] for m in self.fc.movimenti("B-DEB")]
        self.assertIn("penale_offset", tipi)
        self.assertTrue(self.fc.verifica_catena()["ok"])

    # ── 2) parziale FIFO + estinzione col maturato successivo ──────────────────
    def test_riscossione_parziale_poi_estinta(self):
        self._debito_diretto(cents=5000)
        self.pd.registra_maturato("A2", self.hid, 3000, "EUR")
        ris = self.fc.riscuoti_debiti(host_id=self.hid, payout=self.pd)
        self.assertEqual(ris["riscossi_cents"], 3000)
        self.assertEqual(ris["debiti_aperti"], 1)                  # residuo 2000
        self.assertIsNone(self.pd.info("A2"))                      # consumato intero
        deb = self.fc.debiti_host(self.hid, stato="aperto")[0]
        self.assertEqual(deb["residuo_cents"], 2000)
        self.pd.registra_maturato("A3", self.hid, 10000, "EUR")
        ris = self.fc.riscuoti_debiti(host_id=self.hid, payout=self.pd)
        self.assertEqual(ris["riscossi_cents"], 2000)
        self.assertEqual(ris["debiti_saldati"], 1)
        self.assertEqual(self.pd.info("A3")["minori"], 8000)
        self.assertTrue(self.fc.verifica_catena()["ok"])

    # ── 3) idempotenza ─────────────────────────────────────────────────────────
    def test_riscuotere_di_nuovo_non_riconta(self):
        self._debito_diretto(cents=2000)
        self.pd.registra_maturato("A2", self.hid, 9000, "EUR")
        self.fc.riscuoti_debiti(host_id=self.hid, payout=self.pd)
        ris = self.fc.riscuoti_debiti(host_id=self.hid, payout=self.pd)
        self.assertEqual(ris["riscossi_cents"], 0)                 # niente doppioni
        self.assertEqual(self.pd.info("A2")["minori"], 7000)

    # ── 4) valuta diversa e prenotazione del debito: MAI toccate ───────────────
    def test_valuta_diversa_e_stessa_prenotazione_escluse(self):
        self._debito_diretto(rif="B-DEB", cents=5000)
        self.pd.registra_maturato("USD1", self.hid, 9000, "USD")   # valuta diversa
        self.pd.registra_maturato("B-DEB", self.hid, 9000, "EUR")  # la prenotazione stessa
        ris = self.fc.riscuoti_debiti(host_id=self.hid, payout=self.pd)
        self.assertEqual(ris["riscossi_cents"], 0)
        self.assertEqual(self.pd.info("USD1")["minori"], 9000)
        self.assertEqual(self.pd.info("B-DEB")["minori"], 9000)

    # ── 5) FIX OVERPAY: dopo l'offset ①, la conferma paga il RIDOTTO ───────────
    def test_conferma_paga_il_ledger_non_la_garanzia(self):
        self._pubblica("casa-a")
        self._pubblica("casa-b")
        a = self._book_paga("casa-a", giorni=30)
        b = self._book_paga("casa-b", giorni=40)
        netto_a = self.pd.info(a["riferimento"])["minori"]
        # host cancella B -> penale 15%: Scatto ① la compensa dal maturato di A
        s, out = self.g("POST", "/api/host/cancella",
                        {"riferimento": b["riferimento"]}, {"X-Host-Token": self.tok})
        self.assertEqual(s, 200, out)
        ridotto = self.pd.info(a["riferimento"])["minori"]
        self.assertLess(ridotto, netto_a)                          # offset avvenuto su A
        penale = netto_a - ridotto
        self.assertGreater(penale, 0)
        # ospite di A conferma il check-in: la garanzia passa l'importo PIENO,
        # ma il bonifico DEVE partire per il residuo del ledger (fix overpay)
        s, c = self.g("POST", "/api/garanzia/conferma",
                      {"voucher_token": a["voucher_token"]})
        self.assertEqual(s, 200, c)
        self.assertEqual(len(self.fcn.transfers), 1)
        self.assertEqual(self.fcn.transfers[-1][1], ridotto)       # MAI il pieno
        self.assertTrue(self.fc.verifica_catena()["ok"])

    # ── 6) riscossione LIVE sul payout nuovo (end-to-end) ──────────────────────
    def test_riscossione_live_alla_conferma(self):
        self._pubblica("casa-a")
        self._pubblica("casa-b")
        b = self._book_paga("casa-b", giorni=40)
        # unica prenotazione: la penale non ha maturato da compensare -> debito APERTO
        s, out = self.g("POST", "/api/host/cancella",
                        {"riferimento": b["riferimento"]}, {"X-Host-Token": self.tok})
        self.assertEqual(s, 200, out)
        aperti = self.fc.debiti_host(self.hid, stato="aperto")
        self.assertEqual(len(aperti), 1)
        debito = aperti[0]["residuo_cents"]
        self.assertGreater(debito, 0)
        # nuova prenotazione pagata -> alla conferma il debito si riscuote ALLA FONTE
        a = self._book_paga("casa-a", giorni=30)
        netto_a = self.pd.info(a["riferimento"])["minori"]
        s, c = self.g("POST", "/api/garanzia/conferma",
                      {"voucher_token": a["voucher_token"]})
        self.assertEqual(s, 200, c)
        self.assertEqual(self.fcn.transfers[-1][1], netto_a - debito)
        self.assertEqual(self.fc.debiti_host(self.hid, stato="aperto"), [])
        self.assertTrue(self.fc.verifica_catena()["ok"])

    # ── 7) trasparenza host + Bunker ───────────────────────────────────────────
    def test_host_e_bunker_vedono_il_debito(self):
        self._debito_diretto(cents=3000)
        s, d = self.g("GET", "/api/host/payout", None, {"X-Host-Token": self.tok})
        self.assertEqual(s, 200, d)
        self.assertEqual(d["debiti_aperti_cents"]["EUR"], 3000)
        s, out = self.g("POST", "/api/bunker/login", {"codice": "SuperPw@1"},
                        {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9"})
        self.assertEqual(s, 200, out)
        hb = {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9",
              "X-Bunker-Session": out["sessione"]}
        s, rep = self.g("GET", "/api/bunker/integrita", None, hb)
        self.assertEqual(s, 200, rep)
        self.assertEqual(rep["debiti"]["aperti"], 1)
        self.assertEqual(rep["debiti"]["totale_cents"], 3000)
        self.assertIn(self.hid, rep["debiti"]["host"])
        # dopo la riscossione, il debito sparisce da entrambe le viste
        self.pd.registra_maturato("A9", self.hid, 9000, "EUR")
        self.fc.riscuoti_debiti(host_id=self.hid, payout=self.pd)
        s, d = self.g("GET", "/api/host/payout", None, {"X-Host-Token": self.tok})
        self.assertEqual(d["debiti_aperti_cents"], {})


if __name__ == "__main__":
    unittest.main()
