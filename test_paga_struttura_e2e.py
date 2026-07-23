"""
PAGA IN STRUTTURA — FASE 2, flusso end-to-end sul router VERO (Stripe FINTO, mai rete).

Prova, dal book al webhook, che il ramo "in struttura" e' DIVERSO dall'online proprio dove
contano i soldi:
  1. il link creato addebita l'ANTICIPO (fase188), non il totale, e salva la carta;
  2. la prenotazione e' marcata `modo_pagamento=in_struttura` con anticipo/saldo coerenti;
  3. NIENTE escrow di garanzia e NIENTE payout maturato (il saldo lo incassa l'host in loco);
  4. il webhook di pagamento conferma SENZA aprire payout/garanzia;
  5. CONTROLLO online (stessa struttura, senza scelta): apre garanzia E paga il payout ->
     prova che il ramo differenzia davvero (non e' un no-op).
Il gate DARK e' acceso qui (PAGA_STRUTTURA_ATTIVO=1) per provare il comportamento reale.
"""
import json
import os
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
import fase188_paga_struttura as PS
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_ps"
_BODIES = []


def _fake_fetch(url, body, headers):
    import secrets
    _BODIES.append(body.decode() if isinstance(body, (bytes, bytearray)) else str(body))
    return {"url": "https://checkout.stripe.com/c/" + secrets.token_hex(4),
            "id": "cs_" + secrets.token_hex(4)}


class TestPagaStrutturaE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        self._flag = os.environ.get("PAGA_STRUTTURA_ATTIVO")
        os.environ["PAGA_STRUTTURA_ATTIVO"] = "1"
        del _BODIES[:]
        self.dir = tempfile.mkdtemp()
        d = self.dir
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db",
            db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db",
            commissione_bps=1000, psp_bps=0, stripe_secret_key="sk",
            stripe_webhook_secret=WH, stripe_success_url="https://x/ok",
            stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sys, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@ps.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        self.tok, self.hid = c["token"], c["host_id"]
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa", "titolo": "Casa", "citta": "Roma",
                "prezzo_notte_cents": 30000, "capacita": 4,
                "politica_cancellazione": "flessibile"}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa", "da": "2026-09-01", "a": "2026-09-30",
                "unita_totali": 5, "prezzo_netto_cents": 30000}, {"X-Host-Token": self.tok})

    def tearDown(self):
        if self._flag is None:
            os.environ.pop("PAGA_STRUTTURA_ATTIVO", None)
        else:
            os.environ["PAGA_STRUTTURA_ATTIVO"] = self._flag
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _prenota(self, ci, co, modo=None):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
        self.assertEqual(s, 200, q)
        payload = {"quote_token": q["quote_token"], "email": "cli@ps.it"}
        if modo:
            payload["modo_pagamento"] = modo
        s, b = self.g("POST", "/api/concierge/book", payload)
        self.assertEqual(s, 201, b)
        return q, b

    def _maturato(self):
        return self.sys.payout.riepilogo(self.hid).get("EUR", {}).get("maturato", 0)

    def _in_attesa_payout(self):
        return self.sys.payout.riepilogo(self.hid).get("EUR", {}).get("in_attesa", 0)

    def _webhook(self, rif):
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": rif}}}})
        return self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                               {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})

    # ── il ramo in struttura ────────────────────────────────────────────────
    def test_book_in_struttura_marca_e_calcola(self):
        q, b = self._prenota("2026-09-05", "2026-09-08", modo="in_struttura")
        self.assertEqual(b.get("modo_pagamento"), "in_struttura", b)
        atteso = PS.calcola(q["totale_cents"], q["notti"], q["commissione_cents"])
        self.assertEqual(b["anticipo_online_cents"], atteso["anticipo_online_cents"])
        self.assertEqual(b["saldo_in_loco_cents"], atteso["saldo_in_loco_cents"])
        self.assertTrue(b.get("payment_url"), "manca il link anticipo")

    def test_link_addebita_anticipo_e_salva_carta(self):
        q, b = self._prenota("2026-09-05", "2026-09-08", modo="in_struttura")
        atteso = PS.calcola(q["totale_cents"], q["notti"], q["commissione_cents"])
        # NB: prenota crea (e poi scarta) anche il link online full-total; _forse_paga_struttura
        # lo SOSTITUISCE con l'anticipo. Isolo il link ANTICIPO (quello che usa l'ospite) dal
        # marcatore in_struttura e verifico su QUELLO che addebita l'anticipo, non il totale.
        ant = [x for x in _BODIES if "in_struttura" in x]
        self.assertEqual(len(ant), 1, "atteso esattamente un link anticipo")
        ant = ant[0]
        self.assertIn(f"unit_amount%5D={atteso['anticipo_online_cents']}", ant)     # anticipo
        self.assertNotIn(f"unit_amount%5D={q['totale_cents']}", ant)                # non il totale
        self.assertIn("setup_future_usage%5D=off_session", ant)                     # carta salvata
        self.assertIn(f"saldo_cents%5D={atteso['saldo_in_loco_cents']}", ant)       # saldo nei metadata

    def test_in_struttura_NON_apre_escrow_ne_payout(self):
        q, b = self._prenota("2026-09-05", "2026-09-08", modo="in_struttura")
        rif = b["riferimento"]
        # nessun escrow di garanzia aperto (lo stato "aperto" reale e' 'in_garanzia')
        gz = self.sys.garanzia.stato(rif) or {}
        self.assertNotEqual(gz.get("stato"), "in_garanzia",
                            "REGRESSIONE: garanzia aperta su paga-in-struttura")
        # nessun payout (ne' maturato ne' in attesa): il saldo non passa da noi
        self.assertEqual(self._maturato(), 0, "REGRESSIONE: payout maturato su paga-in-struttura")
        self.assertEqual(self._in_attesa_payout(), 0, "REGRESSIONE: payout in attesa su in-struttura")
        # il webhook conferma SENZA aprire nulla
        s, _ = self._webhook(rif)
        self.assertEqual(s, 200)
        self.assertEqual(self._maturato(), 0, "REGRESSIONE: payout maturato dopo webhook in-struttura")
        gz2 = self.sys.garanzia.stato(rif) or {}
        self.assertNotEqual(gz2.get("stato"), "in_garanzia")

    # ── il CONTROLLO online (prova che il ramo differenzia) ──────────────────
    def test_online_apre_escrow_e_paga_payout(self):
        q, b = self._prenota("2026-09-10", "2026-09-13")   # niente modo -> ONLINE
        rif = b["riferimento"]
        self.assertNotEqual(b.get("modo_pagamento"), "in_struttura")
        s, _ = self._webhook(rif)
        self.assertEqual(s, 200)
        self.assertGreater(self._maturato(), 0,
                           "l'online DEVE maturare il payout (se no il test non differenzia)")
        self.assertEqual(self.sys.garanzia.stato(rif).get("stato"), "in_garanzia")

    def test_dark_off_ignora_la_scelta(self):
        # con la feature SPENTA, modo=in_struttura viene ignorato -> flusso online
        os.environ["PAGA_STRUTTURA_ATTIVO"] = "0"
        q, b = self._prenota("2026-09-20", "2026-09-23", modo="in_struttura")
        self.assertNotEqual(b.get("modo_pagamento"), "in_struttura",
                            "DARK ROTTO: in-struttura attivo con feature spenta")


if __name__ == "__main__":
    unittest.main(verbosity=2)
