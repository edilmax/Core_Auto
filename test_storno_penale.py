"""Collaudo STORNO PENALE (5ª distruttiva, Bunker-gated).

Correzione = NOTA CONTRARIA, mai modifica: la NC storna la ND, il debito si azzera,
l'eventuale già-riscosso torna in da_pagare (bonifico MANUALE). Giornale immutabile.
Invarianti:
  1. storno di ND con debito APERTO -> NC emessa (storno_di=ND), ND 'stornata',
     debito 'stornato' (residuo 0), catena hash intatta;
  2. il debito stornato NON viene MAI più riscosso dai payout futuri;
  3. storno di ND GIÀ RISCOSSA (in parte) -> il riscosso torna come riga 'maturato'
     `stornoND-<ND>` (da_pagare, PK fissa = zero doppi accrediti);
  4. IDEMPOTENTE: secondo storno -> gia_stornata, nessuna seconda NC/restituzione;
  5. endpoint: 401 senza chiave admin; 403 senza sessione Bunker; 422 senza motivo;
     404 su nota inesistente; 200 con doppio cancello;
  6. NC/ND restano visibili nella scheda Audit (fase181) con gli stati giusti.
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
from fase181_audit_console import componi

AK = {"X-Admin-Key": "ak"}


class TestStornoPenale(unittest.TestCase):
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
            abilitato=True, segreto_hmac=b"P" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/acc.db",
            db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db", db_garanzia=f"{d}/g.db",
            db_finanza=f"{d}/fin.db", bunker_password="SuperPw@1",
            commissione_bps=1000, psp_bps=300,
            stripe_secret_key="sk_test_x", stripe_webhook_secret="whsec_x",
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/ko"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@storno.it", "password": "password1",
                       "accetta_termini": True, "accetta_clausole": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.hid, self.tok = c["host_id"], c["token"]
        self.fc = self.sis.finanza
        self.pd = self.sis.payout
        oggi = datetime.date.today()
        for slug in ("casa-s1", "casa-s2"):
            self.g("POST", "/api/host/pubblica",
                   {"slug": slug, "titolo": "Casa " + slug, "citta": "Roma",
                    "prezzo_notte_cents": 10000, "capacita": 2},
                   {"X-Host-Token": self.tok})
            self.g("POST", "/api/host/disponibilita_range",
                   {"alloggio_id": slug, "da": oggi.isoformat(),
                    "a": (oggi + datetime.timedelta(days=60)).isoformat(),
                    "unita_totali": 1, "prezzo_netto_cents": 10000},
                   {"X-Host-Token": self.tok})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None,
                               h or {})

    def _book_paga(self, slug, giorni=30):
        oggi = datetime.date.today()
        ci = (oggi + datetime.timedelta(days=giorni)).isoformat()
        co = (oggi + datetime.timedelta(days=giorni + 2)).isoformat()
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": slug, "check_in": ci, "check_out": co, "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@storno.it"})
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata":
                                                  {"riferimento": b["riferimento"]}}}})
        sig = firma_di_test(payload, "whsec_x", int(time.time()))
        self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                        {"Stripe-Signature": sig})
        return b["riferimento"]

    def _nd_con_debito(self):
        """ND con debito APERTO pieno (unica prenotazione cancellata: zero offset)."""
        rif = self._book_paga("casa-s2", giorni=40)
        s, _ = self.g("POST", "/api/host/cancella", {"riferimento": rif},
                      {"X-Host-Token": self.tok})
        self.assertEqual(s, 200)
        nd = self.fc.note_per_riferimento(rif)[0]
        self.assertEqual(nd["tipo"], "debito")
        return nd

    def _sessione_bunker(self):
        s, out = self.g("POST", "/api/bunker/login", {"codice": "SuperPw@1"},
                        {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9"})
        self.assertEqual(s, 200, out)
        return {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9",
                "X-Bunker-Session": out["sessione"]}

    # ── 1) storno con debito aperto: NC + ND stornata + debito azzerato ───────
    def test_storno_con_debito_aperto(self):
        nd = self._nd_con_debito()
        out = self.fc.storna_penale(nota_id=nd["nota_id"], motivo="errore operatore",
                                    payout=self.pd)
        self.assertIsNotNone(out)
        self.assertFalse(out["gia_stornata"])
        nc = self.fc.nota(out["nc_id"])
        self.assertEqual(nc["tipo"], "credito")
        self.assertEqual(nc["storno_di"], nd["nota_id"])          # legame contrario
        self.assertEqual(nc["importo_cents"], nd["importo_cents"])
        self.assertEqual(self.fc.nota(nd["nota_id"])["stato"], "stornata")
        deb = [d for d in self.fc.debiti_host(self.hid) if d["debito_id"] == nd["nota_id"]][0]
        self.assertEqual((deb["stato"], deb["residuo_cents"]), ("stornato", 0))
        self.assertEqual(out["riscosso_cents"], 0)                # nulla era stato preso
        self.assertTrue(self.fc.verifica_catena()["ok"])

    # ── 2) il debito stornato NON si riscuote mai piu' ────────────────────────
    def test_debito_stornato_mai_piu_riscosso(self):
        nd = self._nd_con_debito()
        self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
        self.pd.registra_maturato("NUOVO1", self.hid, 20000, "EUR")
        ris = self.fc.riscuoti_debiti(host_id=self.hid, payout=self.pd)
        self.assertEqual(ris["riscossi_cents"], 0)                # niente da riscuotere
        self.assertEqual(self.pd.info("NUOVO1")["minori"], 20000)  # payout INTATTO

    # ── 3) storno di penale GIA' riscossa: il riscosso torna in da_pagare ─────
    def test_storno_restituisce_il_riscosso(self):
        nd = self._nd_con_debito()
        # la riscossione consuma il debito da un payout nuovo
        self.pd.registra_maturato("ALTRA", self.hid, 50000, "EUR")
        ris = self.fc.riscuoti_debiti(host_id=self.hid, payout=self.pd)
        riscosso = ris["riscossi_cents"]
        self.assertEqual(riscosso, nd["importo_cents"])           # debito saldato per intero
        out = self.fc.storna_penale(nota_id=nd["nota_id"], motivo="penale ingiusta",
                                    payout=self.pd)
        self.assertEqual(out["riscosso_cents"], riscosso)
        self.assertEqual(out["restituito_in_da_pagare"], riscosso)
        riga = self.pd.info("stornoND-" + nd["nota_id"])
        self.assertEqual((riga["stato"], riga["minori"]), ("maturato", riscosso))
        self.assertTrue(self.fc.verifica_catena()["ok"])

    # ── 4) idempotente ────────────────────────────────────────────────────────
    def test_idempotente(self):
        nd = self._nd_con_debito()
        self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
        n_note = len(self.fc.note_per_riferimento(nd["riferimento"]))
        out2 = self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
        self.assertTrue(out2["gia_stornata"])
        self.assertEqual(len(self.fc.note_per_riferimento(nd["riferimento"])), n_note)

    # ── 5) endpoint: doppio cancello + validazioni ────────────────────────────
    def test_endpoint_doppio_cancello(self):
        nd = self._nd_con_debito()
        corpo = {"nota_id": nd["nota_id"], "motivo": "errore"}
        s, _ = self.g("POST", "/api/admin/storno_penale", corpo, {})
        self.assertEqual(s, 401)                                  # niente chiave admin
        s, c = self.g("POST", "/api/admin/storno_penale", corpo, AK)
        self.assertEqual(s, 403)                                  # niente Bunker
        self.assertEqual(c["errore"], "bunker_richiesto")
        hb = self._sessione_bunker()
        s, c = self.g("POST", "/api/admin/storno_penale",
                      {"nota_id": nd["nota_id"], "motivo": ""}, hb)
        self.assertEqual(s, 422)                                  # motivo OBBLIGATORIO
        s, c = self.g("POST", "/api/admin/storno_penale",
                      {"nota_id": "ND-2099-999999", "motivo": "x"}, hb)
        self.assertEqual(s, 404)
        s, c = self.g("POST", "/api/admin/storno_penale", corpo, hb)
        self.assertEqual(s, 200, c)
        self.assertTrue(c["nc_id"].startswith("NC-"))

    # ── 6) la scheda Audit mostra ND stornata + NC ────────────────────────────
    def test_audit_mostra_lo_storno(self):
        nd = self._nd_con_debito()
        self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
        sc = componi(self.sis, nd["riferimento"])
        stati = {n["nota_id"]: n["stato"] for n in sc["note"]}
        self.assertEqual(stati[nd["nota_id"]], "stornata")
        self.assertIn("emessa", [n["stato"] for n in sc["note"]
                                 if n["nota_id"].startswith("NC-")])


if __name__ == "__main__":
    unittest.main()
