"""Collaudo KYC DASHBOARD "Verifiche & Legale" (Incremento 10).

DECISIONE LEGALE (DSA art.30 + GDPR): i documenti d'identità NON si conservano MAI
sui nostri server — l'identificazione elettronica via provider soddisfa la norma.
La dashboard governa ciò che DAVVERO custodiamo: contratto firmato (fase163),
dati fiscali DAC7, Stripe Connect, verifica manuale del super-admin.
Invarianti:
  1. lista con stato composito (contratto/fiscale/stripe/verifica) + contatori
     + filtri (q, stato); AUDIT ADMIN_ACTION su ogni consultazione;
  2. dettaglio: prove del contratto (ts/IP/hash/integra), IBAN e CF MASCHERATI;
  3. approva/revoca: BUNKER-gated (401/403), motivo OBBLIGATORIO per la revoca;
  4. REVOCA -> i bonifici vanno in HOLD (transfer MAI chiamato, payout resta
     'maturato'); RIPRISTINO -> ripartono da soli (payout_riprovati);
  5. fascicolo legale completo: BUNKER-gated, dati fiscali PIENI dentro;
  6. il dettaglio admin NON contiene mai IBAN/CF in chiaro.
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

AK = {"X-Admin-Key": "ak"}


class _ConnectContatore:
    def __init__(self):
        self.chiamate = []

    def trasferisci(self, acct, importo, valuta, rif):
        self.chiamate.append((acct, int(importo), valuta, str(rif)))
        return "tr_%d" % len(self.chiamate)


class TestVerificheHost(unittest.TestCase):
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
            abilitato=True, segreto_hmac=b"K" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/acc.db",
            db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db", db_garanzia=f"{d}/g.db",
            db_finanza=f"{d}/fin.db", bunker_password="SuperPw@1",
            commissione_bps=1000, psp_bps=300,
            stripe_secret_key="sk_test_x", stripe_webhook_secret="whsec_x",
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/ko"))
        self.connect = _ConnectContatore()
        self.sis.connect = self.connect
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak")
        # host COMPLETO: contratto firmato (registrazione con clausole) + fiscale + stripe
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "ok@ver.it", "password": "password1",
                       "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.hid, self.tok = c["host_id"], c["token"]
        self.sis.registro_host.imposta_stripe_account(self.hid, "acct_ok")
        self.sis.registro_host.imposta_dati_fiscali(self.hid, {
            "codice_fiscale": "RSSMRA80A01H501U", "indirizzo_fiscale": "Via Roma 1",
            "paese": "IT", "iban": "IT60X0542811101000000123456",
            "tipo_soggetto": "individuo"})
        # host INCOMPLETO (niente fiscale/stripe)
        e2 = self.sis.registro_host.registra("manca@ver.it", "password12",
                                             accetta_termini=True,
                                             ragione_sociale="Pensione Vuota")
        self.hid2 = e2.host_id
        oggi = datetime.date.today()
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa-v", "titolo": "Casa V", "citta": "Roma",
                "prezzo_notte_cents": 10000, "capacita": 2}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa-v", "da": oggi.isoformat(),
                "a": (oggi + datetime.timedelta(days=60)).isoformat(),
                "unita_totali": 2, "prezzo_netto_cents": 10000},
               {"X-Host-Token": self.tok})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None,
                               h or {})

    def _book_paga(self):
        oggi = datetime.date.today()
        ci = (oggi + datetime.timedelta(days=30)).isoformat()
        co = (oggi + datetime.timedelta(days=32)).isoformat()
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa-v", "check_in": ci, "check_out": co,
                       "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@ver.it"})
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata":
                                                  {"riferimento": b["riferimento"]}}}})
        sig = firma_di_test(payload, "whsec_x", int(time.time()))
        self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                        {"Stripe-Signature": sig})
        return b["riferimento"]

    def _hb(self):
        s, out = self.g("POST", "/api/bunker/login", {"codice": "SuperPw@1"},
                        {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9"})
        self.assertEqual(s, 200, out)
        return {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9",
                "X-Bunker-Session": out["sessione"]}

    # ── 1) lista, contatori e filtri ──────────────────────────────────────────
    def test_lista_contatori_filtri(self):
        s, d = self.g("GET", "/api/admin/verifiche", None, AK)
        self.assertEqual(s, 200, d)
        per_id = {h["host_id"]: h["documenti"] for h in d["host"]}
        ok = per_id[self.hid]
        self.assertTrue(ok["contratto"] and ok["fiscale"] and ok["stripe"])
        self.assertFalse(ok["in_regola"])          # manca la verifica manuale
        manca = per_id[self.hid2]
        self.assertFalse(manca["fiscale"] or manca["stripe"])
        self.assertEqual(d["contatori"]["incompleti"], 2)
        # filtro q per nome
        s, d = self.g("GET", "/api/admin/verifiche", None, AK, {"q": "Pensione"})
        self.assertEqual([h["host_id"] for h in d["host"]], [self.hid2])
        # filtro stato=incompleti
        s, d = self.g("GET", "/api/admin/verifiche", None, AK,
                      {"stato": "incompleti"})
        self.assertEqual(len(d["host"]), 2)

    # ── 2) dettaglio: prova contratto + MASCHERE ──────────────────────────────
    def test_dettaglio_prove_e_maschere(self):
        s, d = self.g("GET", "/api/admin/verifiche/dettaglio", None, AK,
                      {"host_id": self.hid})
        self.assertEqual(s, 200, d)
        # da 2026-07-20 le prove sono 2: contratto + privacy (consenso GDPR separato)
        self.assertEqual(len(d["contratto_prove"]), 2)
        p = [x for x in d["contratto_prove"] if x["documento"] == "contratto_host"][0]
        self.assertTrue(p["integra"])
        self.assertEqual(p["versione"], CONTRATTO_HOST_VERSIONE)
        self.assertTrue(any(x["documento"] == "privacy_gdpr" and x["integra"]
                            for x in d["contratto_prove"]))
        blob = json.dumps(d)
        self.assertNotIn("IT60X0542811101000000123456", blob)   # IBAN MAI in chiaro
        self.assertNotIn("RSSMRA80A01H501U", blob)              # CF MAI in chiaro
        self.assertTrue(d["fiscale"]["iban_maschera"].endswith("3456"))

    # ── 3) approva/revoca: doppio cancello + motivo ───────────────────────────
    def test_cancelli_verifica(self):
        corpo = {"host_id": self.hid, "stato": "revocato", "motivo": "doc sospetti"}
        s, _ = self.g("POST", "/api/admin/verifica_stato", corpo, {})
        self.assertEqual(s, 401)
        s, c = self.g("POST", "/api/admin/verifica_stato", corpo, AK)
        self.assertEqual(s, 403)                    # niente Bunker
        hb = self._hb()
        s, c = self.g("POST", "/api/admin/verifica_stato",
                      {"host_id": self.hid, "stato": "revocato", "motivo": ""}, hb)
        self.assertEqual(s, 422)                    # motivo OBBLIGATORIO per revoca
        s, c = self.g("POST", "/api/admin/verifica_stato", corpo, hb)
        self.assertEqual(s, 200, c)
        self.assertEqual(self.sis.registro_host.info_host(self.hid)["verifica_stato"],
                         "revocato")

    # ── 4) revoca FERMA i bonifici; ripristino li fa ripartire ────────────────
    def test_revoca_blocca_e_ripristino_sblocca(self):
        rif = self._book_paga()
        hb = self._hb()
        s, _ = self.g("POST", "/api/admin/verifica_stato",
                      {"host_id": self.hid, "stato": "revocato",
                       "motivo": "controllo in corso"}, hb)
        self.assertEqual(s, 200)
        netto = self.sis.payout.riepilogo(self.hid)["EUR"]["maturato"]
        self.r._trasferisci_all_host(rif, netto)
        self.assertEqual(self.connect.chiamate, [])              # HOLD: mai partito
        self.assertEqual(self.sis.payout.stato_di(rif), "maturato")   # mai perso
        # RIPRISTINO -> il bonifico riparte da solo
        s, c = self.g("POST", "/api/admin/verifica_stato",
                      {"host_id": self.hid, "stato": "verificato", "motivo": "ok"}, hb)
        self.assertEqual(s, 200, c)
        self.assertGreaterEqual(c["payout_riprovati"], 1)
        self.assertEqual(len(self.connect.chiamate), 1)          # PARTITO
        self.assertEqual(self.sis.payout.stato_di(rif), "in_transito")

    # ── 5) fascicolo legale: Bunker-gated, dati PIENI dentro ──────────────────
    def test_fascicolo_bunker_gated(self):
        s, _ = self.g("GET", "/api/admin/verifiche/fascicolo", None, AK,
                      {"host_id": self.hid})
        self.assertEqual(s, 403)                    # admin da solo NON basta
        s, d = self.g("GET", "/api/admin/verifiche/fascicolo", None, self._hb(),
                      {"host_id": self.hid})
        self.assertEqual(s, 200, d)
        f = d["fascicolo"]
        self.assertEqual(f["fiscale"]["iban"], "IT60X0542811101000000123456")  # PIENO
        self.assertEqual(len(f["contratto_prove"]), 2)   # contratto + privacy GDPR
        self.assertIn("identita", f)
        self.assertIn("MAI conservati", f["nota_legale"])


if __name__ == "__main__":
    unittest.main()
