"""
Collaudo BUG "pagamento su prenotazione cancellata" (denaro — trovato al collaudo finale).

Prima del fix:
  (1) `_conferma_pagamento` confermava QUALSIASI stato non-pagato/non-scaduto: un pagamento
      tardivo su prenotazione CANCELLATA (dal cliente o dall'host) diventava 'pagato' ->
      soldi senza stanza + payout indebito all'host + tassa registrata.
  (2) `_cancella_prenotazione` non guardava se il cliente avesse DAVVERO pagato: dichiarava
      "rimborso €X" (e regalava Credito Viaggio) su soldi MAI incassati, e non invalidava il
      record -> il link di pagamento (vivo fino a 24h) poteva "resuscitare" la prenotazione.

Il fix: whitelist in _conferma_pagamento (solo 'in_attesa'/'scaduto' confermabili; il resto
-> log RIMBORSARE, nessuna conferma); cancellazione consapevole del pagamento (non pagata ->
rimborso 0, tassa 0, niente credito, "nessun addebito") + record invalidato ('rimborsato');
ritenzione pendenti 26h (> vita massima del link Stripe).
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
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE

WHSEC = "whsec_cm"


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://checkout.stripe.test/" + secrets.token_hex(6),
            "id": "cs_test_" + secrets.token_hex(6)}


class TestCancellazioneMoney(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

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
            db_tassa_comunale=f"{d}/t.db",
            commissione_bps=1000, psp_bps=300,
            stripe_secret_key="sk_test_cm", stripe_webhook_secret=WHSEC,
            stripe_success_url="https://bookinvip.com/grazie.html",
            stripe_cancel_url="https://bookinvip.com/annullato.html"))
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@cm.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.hid, self.tok = c["host_id"], c["token"]
        s, _ = self.g("POST", "/api/host/pubblica",
                      {"slug": "casa-cm", "titolo": "Casa CM", "citta": "Roma",
                       "prezzo_notte_cents": 10000, "capacita": 2,
                       "politica_cancellazione": "flessibile"}, {"X-Host-Token": self.tok})
        self.assertEqual(s, 201)
        s, _ = self.g("POST", "/api/host/disponibilita_range",
                      {"alloggio_id": "casa-cm", "da": "2026-09-01", "a": "2026-12-31",
                       "unita_totali": 1, "prezzo_netto_cents": 10000}, {"X-Host-Token": self.tok})
        self.assertEqual(s, 200)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, metodo, path, body=None, headers=None, query=None):
        return self.r.gestisci(metodo, path, query or {},
                               json.dumps(body) if body is not None else None, headers or {})

    def _prenota(self, ci, co):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa-cm", "check_in": ci, "check_out": co, "party": 2})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@cm.it"})
        self.assertEqual(s, 201, b)
        return b

    def _webhook(self, rif):
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata": {"riferimento": rif}}}})
        sig = firma_di_test(payload, WHSEC, int(time.time()))
        return self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                               {"Stripe-Signature": sig})

    def _maturato(self):
        return self.sys.payout.riepilogo(self.hid).get("EUR", {}).get("maturato", 0)

    # ── (2) cancellazione consapevole del pagamento ───────────────────────────
    def test_cancella_non_pagata_rimborso_zero(self):
        b = self._prenota("2026-09-05", "2026-09-07")
        s, canc = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200, canc)
        self.assertEqual(canc["rimborso_cents"], 0, "rimborso su soldi MAI incassati")
        self.assertEqual(canc["credito_viaggio_cents"], 0, "credito regalato senza pagamento")
        self.assertTrue(canc["pagamento_mai_effettuato"])
        self.assertIn("nessun addebito", canc["nota"])
        # il record è invalidato: un pagamento tardivo NON conferma
        self.assertEqual(self.sys.pagamenti_pendenti.info(b["riferimento"])["stato"], "rimborsato")

    def test_cancella_pagata_rimborso_reale_invariato(self):
        b = self._prenota("2026-09-10", "2026-09-12")
        self._webhook(b["riferimento"])              # il cliente HA pagato
        s, canc = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200, canc)
        self.assertFalse(canc["pagamento_mai_effettuato"])
        self.assertGreater(canc["rimborso_cents"], 0)      # politica flessibile: rimborso vero

    # ── (1) whitelist in _conferma_pagamento ──────────────────────────────────
    def test_pagamento_dopo_cancellazione_cliente_non_conferma(self):
        b = self._prenota("2026-09-15", "2026-09-17")
        rif = b["riferimento"]
        self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        prima = self._maturato()
        s, _ = self._webhook(rif)                    # link ancora vivo: il cliente paga DOPO
        self.assertEqual(s, 200)                     # webhook accettato (200 a Stripe)...
        rec = self.sys.pagamenti_pendenti.info(rif)
        self.assertNotEqual(rec["stato"], "pagato",  # ...ma NIENTE conferma
                            "REGRESSIONE: pagamento su prenotazione cancellata CONFERMATO")
        self.assertEqual(self._maturato(), prima, "payout indebito all'host")
        # le date sono rimaste libere (nessuna resurrezione)
        s, q2 = self.g("POST", "/api/concierge/quote",
                       {"alloggio_id": "casa-cm", "check_in": "2026-09-15",
                        "check_out": "2026-09-17", "party": 2})
        self.assertTrue(q2.get("quote_token"))

    def test_pagamento_dopo_cancellazione_host_non_conferma(self):
        b = self._prenota("2026-09-20", "2026-09-22")
        rif = b["riferimento"]
        self._webhook(rif)                           # pagata
        s, canc = self.g("POST", "/api/host/cancella", {"riferimento": rif},
                         {"X-Host-Token": self.tok})
        self.assertEqual(s, 200, canc)
        self.assertEqual(self.sys.pagamenti_pendenti.info(rif)["stato"], "cancellata_host")
        s, _ = self._webhook(rif)                    # webhook duplicato/tardivo
        self.assertEqual(s, 200)
        self.assertEqual(self.sys.pagamenti_pendenti.info(rif)["stato"], "cancellata_host",
                         "REGRESSIONE: la cancellazione host è stata sovrascritta da 'pagato'")

    def test_pagamento_su_richiesta_non_approvata_non_conferma(self):
        # difesa in profondità: un pagamento mentre lo stato è in_attesa_host NON conferma
        pp = self.sys.pagamenti_pendenti
        pp.registra("REF_NA", alloggio_id="casa-cm", check_in="2026-10-01",
                    check_out="2026-10-03", stato="in_attesa_host",
                    scadenza_ts=int(time.time()) + 86400)
        s, _ = self._webhook("REF_NA")
        self.assertEqual(s, 200)
        self.assertEqual(pp.info("REF_NA")["stato"], "in_attesa_host",
                         "pagamento senza approvazione dell'host CONFERMATO")

    # ── ritenzione: il record vive più del link Stripe ────────────────────────
    def test_ritenzione_26h(self):
        pp = self.sys.pagamenti_pendenti
        ora = int(time.time())
        pp.registra("REF_OLD", alloggio_id="casa-cm", check_in="2026-10-05",
                    check_out="2026-10-06", stato="in_attesa")
        pp.marca_da_rimborsare("REF_OLD")
        # a +25h (link Stripe max 24h APPENA morto) il record c'è ancora
        pp.pulisci_vecchi(ora_ts=ora + 25 * 3600)
        self.assertIsNotNone(pp.info("REF_OLD"))
        # a +27h è housekeeping legittimo
        pp.pulisci_vecchi(ora_ts=ora + 27 * 3600)
        self.assertIsNone(pp.info("REF_OLD"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
