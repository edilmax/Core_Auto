"""
Collaudo LOOP 1 — soldi all'host IN AUTOMATICO allo sblocco dell'escrow (strategia fondatore).

Il cliente paga -> i soldi restano in custodia -> al check-in ha 24h: "tutto ok" (o silenzio)
-> il NETTO parte DA SOLO verso il conto Stripe dell'host (Connect, transfer separato);
controversia -> bloccati finché l'admin decide (la parte host parte al verdetto).

Blindati: transfer IDEMPOTENTE (Idempotency-Key per riferimento + guardia stato payout),
GATED (host senza conto -> resta bonifico manuale, nessun transfer), ISOLATO (transfer
fallito -> payout resta 'maturato' tracciato, nessun crash), niente transfer su prenotazioni
non pagate online.
"""
import json
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase101_stripe_connect import ProviderConnect
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE

WHSEC = "whsec_cx"


def _fake_checkout(url, body, headers):
    import secrets
    return {"url": "https://checkout.stripe.test/" + secrets.token_hex(6),
            "id": "cs_test_" + secrets.token_hex(6)}


class _FakeConnectRete:
    """Registra le chiamate Connect (accounts/links/transfers) e risponde come Stripe."""

    def __init__(self):
        self.post = []          # (url, params_str, headers)
        self.fallisci_transfer = False

    def fetch(self, url, body, headers):
        corpo = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else str(body)
        self.post.append((url, corpo, dict(headers)))
        if url.endswith("/accounts"):
            return {"id": "acct_TEST123"}
        if url.endswith("/account_links"):
            return {"url": "https://connect.stripe.test/onboarding"}
        if url.endswith("/transfers"):
            if self.fallisci_transfer:
                return {"error": {"message": "insufficient funds"}}
            return {"id": "tr_TEST%d" % len(self.post)}
        return {}

    def fetch_get(self, url, headers):
        return {"payouts_enabled": True, "details_submitted": True}

    def transfers(self):
        return [(u, c, h) for (u, c, h) in self.post if u.endswith("/transfers")]


class TestConnectEscrow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_checkout)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        d = self.dir
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/acc.db",
            db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db", db_garanzia=f"{d}/g.db",
            commissione_bps=1000, psp_bps=300,
            stripe_secret_key="sk_test_cx", stripe_webhook_secret=WHSEC,
            stripe_success_url="https://bookinvip.com/grazie.html",
            stripe_cancel_url="https://bookinvip.com/annullato.html"))
        # rete Connect FINTA iniettata nel provider vivo
        self.rete = _FakeConnectRete()
        self.sys.connect._fetch = self.rete.fetch
        self.sys.connect._fetch_get = self.rete.fetch_get
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@cx.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.hid, self.tok = c["host_id"], c["token"]
        s, _ = self.g("POST", "/api/host/pubblica",
                      {"slug": "casa-cx", "titolo": "Casa CX", "citta": "Roma",
                       "prezzo_notte_cents": 10000, "capacita": 2}, {"X-Host-Token": self.tok})
        self.assertEqual(s, 201)
        s, _ = self.g("POST", "/api/host/disponibilita_range",
                      {"alloggio_id": "casa-cx", "da": "2026-09-01", "a": "2026-12-31",
                       "unita_totali": 1, "prezzo_netto_cents": 10000}, {"X-Host-Token": self.tok})
        self.assertEqual(s, 200)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, metodo, path, body=None, headers=None, query=None):
        return self.r.gestisci(metodo, path, query or {},
                               json.dumps(body) if body is not None else None, headers or {})

    def _collega_stripe(self):
        s, d = self.g("GET", "/api/host/stripe_link", headers={"X-Host-Token": self.tok})
        self.assertEqual(s, 200, d)
        return d

    def _prenota_e_paga(self, ci, co):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa-cx", "check_in": ci, "check_out": co, "party": 2})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@cx.it"})
        self.assertEqual(s, 201, b)
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata": {"riferimento": b["riferimento"]}}}})
        sig = firma_di_test(payload, WHSEC, int(time.time()))
        s, _ = self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                               {"Stripe-Signature": sig})
        self.assertEqual(s, 200)
        return b

    # ── onboarding host ───────────────────────────────────────────────────────
    def test_stripe_link_crea_account_e_lo_riusa(self):
        d = self._collega_stripe()
        self.assertEqual(d["account_id"], "acct_TEST123")
        self.assertTrue(d["link"].startswith("https://connect.stripe.test/"))
        self.assertTrue(d["pronto"])
        # l'account è salvato sull'host
        info = self.sys.registro_host.info_host(self.hid)
        self.assertEqual(info["stripe_account_id"], "acct_TEST123")
        # seconda chiamata: NON crea un secondo account (riusa)
        n_accounts = sum(1 for u, _, _ in self.rete.post if u.endswith("/accounts"))
        self._collega_stripe()
        n_accounts2 = sum(1 for u, _, _ in self.rete.post if u.endswith("/accounts"))
        self.assertEqual(n_accounts2, n_accounts)
        # gated: senza auth 401
        s, _ = self.g("GET", "/api/host/stripe_link")
        self.assertEqual(s, 401)

    # ── il cuore: sblocco escrow -> transfer automatico ───────────────────────
    def test_conferma_cliente_fa_partire_il_bonifico(self):
        self._collega_stripe()
        b = self._prenota_e_paga("2026-09-05", "2026-09-07")
        netto = self.sys.payout.riepilogo(self.hid)["EUR"]["maturato"]
        s, out = self.g("POST", "/api/garanzia/conferma", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200, out)
        trs = self.rete.transfers()
        self.assertEqual(len(trs), 1, "doveva partire UN transfer")
        url, corpo, headers = trs[0]
        self.assertIn("amount=%d" % netto, corpo)             # il NETTO esatto dell'host
        self.assertIn("destination=acct_TEST123", corpo)
        self.assertIn("currency=eur", corpo)
        self.assertEqual(headers.get("Idempotency-Key"),
                         "transfer_" + b["riferimento"])       # idempotente su Stripe
        # payout: maturato -> in_transito (soldi partiti)
        rie = self.sys.payout.riepilogo(self.hid)["EUR"]
        self.assertEqual(rie.get("maturato", 0), 0)
        self.assertEqual(rie.get("in_transito", 0), netto)

    def test_doppia_conferma_un_solo_transfer(self):
        self._collega_stripe()
        b = self._prenota_e_paga("2026-09-10", "2026-09-12")
        self.g("POST", "/api/garanzia/conferma", {"voucher_token": b["voucher_token"]})
        self.g("POST", "/api/garanzia/conferma", {"voucher_token": b["voucher_token"]})
        self.assertEqual(len(self.rete.transfers()), 1, "doppio bonifico!")

    def test_auto_rilascio_24h_fa_partire_il_bonifico(self):
        self._collega_stripe()
        b = self._prenota_e_paga("2026-09-15", "2026-09-17")
        gz = self.sys.garanzia
        # come farebbe lo sweeper DOPO la finestra: forzo lo sblocco nel passato
        con = gz._apri()
        with con:
            con.execute("UPDATE garanzia SET sblocco_auto_ts=? WHERE prenotazione_id=?",
                        (int(time.time()) - 10, b["riferimento"]))
        con.close()
        rilasciate = gz.auto_rilascia(dettagli=True)
        self.assertEqual(len(rilasciate), 1)
        for r_ in rilasciate:                                  # come fa _tick_garanzia
            self.r._trasferisci_all_host(r_["prenotazione_id"], r_["host_riceve_cents"])
        self.assertEqual(len(self.rete.transfers()), 1)
        self.assertIn("amount=%d" % rilasciate[0]["host_riceve_cents"],
                      self.rete.transfers()[0][1])

    def test_controversia_risolta_manda_la_parte_host(self):
        self._collega_stripe()
        b = self._prenota_e_paga("2026-09-20", "2026-09-22")
        s, _ = self.g("POST", "/api/garanzia/contesta", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200)
        self.assertEqual(len(self.rete.transfers()), 0)        # bloccati durante la disputa
        s, out = self.g("POST", "/api/admin/controversia/risolvi",
                        {"riferimento": b["riferimento"], "percentuale_ospite": 40},
                        {"X-Admin-Key": None} if False else {"X-Admin-Key": "ak"})
        # router creato senza admin_key -> _auth_admin passa (dev); verifico l'esito
        self.assertEqual(s, 200, out)
        trs = self.rete.transfers()
        self.assertEqual(len(trs), 1)
        self.assertIn("amount=%d" % out["va_all_host_cents"], trs[0][1])

    # ── guardie ───────────────────────────────────────────────────────────────
    def test_host_senza_stripe_resta_manuale(self):
        b = self._prenota_e_paga("2026-09-25", "2026-09-27")   # NESSUN collegamento Stripe
        netto = self.sys.payout.riepilogo(self.hid)["EUR"]["maturato"]
        s, _ = self.g("POST", "/api/garanzia/conferma", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200)
        self.assertEqual(len(self.rete.transfers()), 0, "transfer senza conto collegato!")
        rie = self.sys.payout.riepilogo(self.hid)["EUR"]
        self.assertEqual(rie.get("maturato", 0), netto)        # resta tracciato per il manuale

    def test_transfer_fallito_isolato_payout_resta(self):
        self._collega_stripe()
        b = self._prenota_e_paga("2026-10-01", "2026-10-03")
        netto = self.sys.payout.riepilogo(self.hid)["EUR"]["maturato"]
        self.rete.fallisci_transfer = True
        s, out = self.g("POST", "/api/garanzia/conferma", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200, out)                          # il rilascio NON si blocca
        rie = self.sys.payout.riepilogo(self.hid)["EUR"]
        self.assertEqual(rie.get("maturato", 0), netto)        # payout resta (bonifico manuale)
        self.assertEqual(rie.get("in_transito", 0), 0)

    def test_niente_transfer_su_prenotazione_non_pagata_online(self):
        self._collega_stripe()
        # transfer chiesto per un riferimento senza pendente 'pagato' -> nessuna chiamata
        self.r._trasferisci_all_host("REF_INESISTENTE", 5000)
        self.assertEqual(len(self.rete.transfers()), 0)

    # ── unit ProviderConnect ──────────────────────────────────────────────────
    def test_provider_gated_e_validazioni(self):
        p = ProviderConnect("", fetch=self.rete.fetch)          # senza chiave: tutto None
        self.assertIsNone(p.crea_account())
        self.assertIsNone(p.trasferisci("acct_X", 100, "eur", "r"))
        p2 = ProviderConnect("sk", fetch=self.rete.fetch)
        self.assertIsNone(p2.trasferisci("acct_X", 0, "eur", "r"))     # importo non valido
        self.assertIsNone(p2.trasferisci("non_acct", 100, "eur", "r"))  # account non valido


if __name__ == "__main__":
    unittest.main(verbosity=2)
