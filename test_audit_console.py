"""Collaudo FINANCIAL AUDIT CONSOLE (fase181): lo Spotlight contabile.

Invarianti:
  1. RISOLUZIONE: riferimento pieno, codice BVIP-XXXX-XXXX, nota ND/NC (anche
     minuscola), host h_...; spazzatura -> id_non_riconosciuto;
  2. SEMAFORO: pagata coerente -> VERDE (stripe grigio senza cs_/check: il grigio
     NON degrada); mismatch libri -> ROSSO col perche'; Stripe non raggiungibile ->
     GIALLO; Stripe che contraddice lo stato -> ROSSO;
  3. cs_ del webhook SALVATO (prerequisito shadow-check) e usato dalla scheda;
  4. READ-ONLY PROVATO: N consultazioni -> il giornale ha le stesse righe di prima;
  5. endpoint /api/admin/audit: 401 senza chiave; whitelist (mai corpo_json/idem_key
     ne' dati fiscali nel JSON).
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
from fase181_audit_console import componi, risolvi_id

AK = {"X-Admin-Key": "ak"}


class TestAuditConsole(unittest.TestCase):
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
            abilitato=True, segreto_hmac=b"A" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/acc.db",
            db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db", db_garanzia=f"{d}/g.db",
            db_finanza=f"{d}/fin.db",
            commissione_bps=1000, psp_bps=300,
            stripe_secret_key="sk_test_x", stripe_webhook_secret="whsec_x",
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/ko"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@audit.it", "password": "password1",
                       "accetta_termini": True, "accetta_clausole": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.hid, self.tok = c["host_id"], c["token"]
        oggi = datetime.date.today()
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa-au", "titolo": "Casa Audit", "citta": "Roma",
                "prezzo_notte_cents": 10000, "capacita": 2}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa-au", "da": oggi.isoformat(),
                "a": (oggi + datetime.timedelta(days=60)).isoformat(),
                "unita_totali": 3, "prezzo_netto_cents": 10000}, {"X-Host-Token": self.tok})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None,
                               h or {})

    def _book_paga(self, giorni=30):
        oggi = datetime.date.today()
        ci = (oggi + datetime.timedelta(days=giorni)).isoformat()
        co = (oggi + datetime.timedelta(days=giorni + 2)).isoformat()
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa-au", "check_in": ci, "check_out": co,
                       "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@audit.it"})
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"id": "cs_test_777",
                                                  "metadata": {"riferimento":
                                                               b["riferimento"]}}}})
        sig = firma_di_test(payload, "whsec_x", int(time.time()))
        self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                        {"Stripe-Signature": sig})
        self.assertEqual(self.sis.pagamenti_pendenti.info(b["riferimento"])["stato"],
                         "pagato")
        return b["riferimento"]

    # ── 1) risoluzione di ogni tipo di ID ─────────────────────────────────────
    def test_risoluzione_tutti_gli_id(self):
        rif = self._book_paga()
        self.assertEqual(risolvi_id(self.sis, rif)["riferimento"], rif)
        bvip = "BVIP-%s-%s" % (rif[:4].upper(), rif[4:8].upper())
        self.assertEqual(risolvi_id(self.sis, bvip)["riferimento"], rif)
        self.assertEqual(risolvi_id(self.sis, self.hid)["tipo"], "host")
        self.assertIsNone(risolvi_id(self.sis, "robaccia!!")["tipo"])
        # nota ND (da una penale) risolta anche in minuscolo
        s, _ = self.g("POST", "/api/host/cancella", {"riferimento": rif},
                      {"X-Host-Token": self.tok})
        self.assertEqual(s, 200)
        nd = self.sis.finanza.note_per_riferimento(rif)[0]["nota_id"]
        ris = risolvi_id(self.sis, nd.lower())
        self.assertEqual(ris["tipo"], "nota")
        self.assertEqual(ris["riferimento"], rif)

    # ── 2) semaforo VERDE su pagata coerente (grigio Stripe non degrada) ──────
    def test_verde_pagata_coerente(self):
        rif = self._book_paga()
        sc = componi(self.sis, rif)                     # nessun check Stripe -> grigio
        self.assertEqual(sc["semaforo"]["complessivo"], "verde")
        self.assertEqual(sc["semaforo"]["coerenza"]["colore"], "verde")
        self.assertEqual(sc["prenotazione"]["stato"], "pagato")
        self.assertIn("incasso", [m["tipo"] for m in sc["movimenti"]])

    # ── 3) cs_ salvato dal webhook + Stripe mock 'paid' -> stripe VERDE ───────
    def test_cs_salvato_e_stripe_verde(self):
        rif = self._book_paga()
        dj = json.loads(self.sis.pagamenti_pendenti.info(rif)["corpo_json"])
        self.assertEqual(dj["stripe_cs"], "cs_test_777")       # prerequisito SALVATO
        visti = []
        sc = componi(self.sis, rif, stripe_check=lambda cs: (visti.append(cs) or
                     {"ok": True, "payment_status": "paid"}))
        self.assertEqual(visti, ["cs_test_777"])               # usa PROPRIO quel cs_
        self.assertEqual(sc["semaforo"]["stripe"]["colore"], "verde")
        self.assertEqual(sc["semaforo"]["complessivo"], "verde")

    # ── 4) Stripe irraggiungibile -> GIALLO; Stripe che contraddice -> ROSSO ──
    def test_giallo_e_rosso_stripe(self):
        rif = self._book_paga()
        sc = componi(self.sis, rif, stripe_check=lambda cs: {"ok": False,
                                                             "motivo": "timeout"})
        self.assertEqual(sc["semaforo"]["stripe"]["colore"], "giallo")
        self.assertEqual(sc["semaforo"]["complessivo"], "giallo")
        sc = componi(self.sis, rif, stripe_check=lambda cs: {"ok": True,
                                                             "payment_status": "unpaid"})
        self.assertEqual(sc["semaforo"]["stripe"]["colore"], "rosso")
        self.assertEqual(sc["semaforo"]["complessivo"], "rosso")

    # ── 5) mismatch fra i libri -> ROSSO col perche' ──────────────────────────
    def test_rosso_mismatch_libri(self):
        rif = self._book_paga()
        # simulo il guasto: ledger dice "bonifico partito" ma nel giornale non c'e'
        self.sis.payout.aggiorna_stato(rif, "in_transito")
        sc = componi(self.sis, rif)
        self.assertEqual(sc["semaforo"]["coerenza"]["colore"], "rosso")
        self.assertEqual(sc["semaforo"]["complessivo"], "rosso")
        self.assertTrue(any("giornale" in p for p in
                            sc["semaforo"]["coerenza"]["problemi"]))

    # ── 6) READ-ONLY provato: N consultazioni, zero righe nuove ──────────────
    def test_read_only_provato(self):
        rif = self._book_paga()
        prima = self.sis.finanza.conta_movimenti()
        for _ in range(5):
            componi(self.sis, rif)
            componi(self.sis, self.hid)
            componi(self.sis, "robaccia")
        self.assertEqual(self.sis.finanza.conta_movimenti(), prima)

    # ── 7) endpoint: auth + whitelist ─────────────────────────────────────────
    def test_endpoint_auth_e_whitelist(self):
        rif = self._book_paga()
        s, _ = self.g("GET", "/api/admin/audit", None, {}, {"id": rif})
        self.assertEqual(s, 401)
        s, d = self.g("GET", "/api/admin/audit", None, AK, {"id": rif})
        self.assertEqual(s, 200, d)
        blob = json.dumps(d)
        for vietato in ("corpo_json", "idem_key", "iban", "codice_fiscale",
                        "partita_iva", "stripe_cs"):
            self.assertNotIn(vietato, blob, "campo VIETATO nella scheda: " + vietato)
        # scheda host dall'endpoint
        s, d = self.g("GET", "/api/admin/audit", None, AK, {"id": self.hid})
        self.assertEqual(d["tipo"], "host")
        self.assertIn("EUR", json.dumps(d["payout"]))


if __name__ == "__main__":
    unittest.main()
