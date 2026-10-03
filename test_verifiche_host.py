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
            lambda u, b, h: {"id": u.rsplit("/", 1)[-1], "payment_status": "paid"}
            if not b and "/checkout/sessions/" in u
            else {"url": "https://checkout.stripe.test/cs", "id": "cs_1"})

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
                              "data": {"object": {"id": "cs_" + b["riferimento"], "metadata":
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
        # il bonifico nasce allo sblocco della garanzia (consegne 35): prima, niente da ritentare
        self.assertTrue(self.sis.garanzia.conferma_ospite(rif).get("ok"), "setup: sblocco")
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

    def test_LA_VERIFICA_NON_PAGA_IN_ANTICIPO_UN_SOGGIORNO_NON_FATTO(self):
        """Consegne 35 (trovato dalla suite il 3/10): rimettere l'host «verificato» ritentava
        TUTTI i suoi bonifici 'maturato', anche quelli con la garanzia ancora aperta -> l'host
        incassava prima del soggiorno, e una cancellazione dopo ci faceva pagare due volte.
        Si ritenta solo cio' che la garanzia ha gia' sbloccato."""
        rif = self._book_paga()
        self.assertEqual((self.sis.garanzia.stato(rif) or {}).get("stato"), "in_garanzia",
                         "setup: soggiorno non ancora confermato")
        hb = self._hb()
        self.g("POST", "/api/admin/verifica_stato",
               {"host_id": self.hid, "stato": "revocato", "motivo": "controllo in corso"}, hb)
        s, c = self.g("POST", "/api/admin/verifica_stato",
                      {"host_id": self.hid, "stato": "verificato", "motivo": "ok"}, hb)
        self.assertEqual(s, 200, c)
        self.assertEqual(self.connect.chiamate, [],
                         "la verifica ha pagato l'host prima del soggiorno (garanzia aperta)")
        self.assertEqual(self.sis.payout.stato_di(rif), "maturato")

    def test_LA_VERIFICA_PAGA_SOLO_CON_LA_GARANZIA_CHIUSA(self):
        """Compito 29 di GML: un rimborso con DUE passi di sicurezza falliti lascia la garanzia
        «annullato», il bonifico «maturato» e la prenotazione «pagato». Un elenco degli stati che
        bloccano non conteneva «annullato»: il giro della verifica avrebbe pagato l'host di una
        prenotazione annullata. Si paga SOLO con la garanzia chiusa (rilasciata o risolta)."""
        rif = self._book_paga()
        self.assertTrue(self.sis.garanzia.annulla(rif).get("ok"), "setup: annullata")
        self.assertEqual(self.sis.payout.stato_di(rif), "maturato", "setup: payout rimasto")
        hb = self._hb()
        self.g("POST", "/api/admin/verifica_stato",
               {"host_id": self.hid, "stato": "revocato", "motivo": "controllo in corso"}, hb)
        s, c = self.g("POST", "/api/admin/verifica_stato",
                      {"host_id": self.hid, "stato": "verificato", "motivo": "ok"}, hb)
        self.assertEqual(s, 200, c)
        self.assertEqual(self.connect.chiamate, [],
                         "la verifica ha pagato l'host di una prenotazione con la garanzia annullata")

    def test_LA_VERIFICA_PAGA_LA_QUOTA_DECISA_DALL_ARBITRO(self):
        """L'altro verso: garanzia 'risolto' (l'arbitro ha deciso) e bonifico fermo per la
        verifica revocata -> rimesso «verificato», la quota dell'host PARTE."""
        rif = self._book_paga()
        self.assertTrue(self.sis.garanzia.contesta(rif, "prova").get("ok"), "setup: contestata")
        self.assertTrue(self.sis.garanzia.risolvi(rif, rimborso_ospite_cents=0).get("ok"),
                        "setup: risolta tutta all'host")
        hb = self._hb()
        self.g("POST", "/api/admin/verifica_stato",
               {"host_id": self.hid, "stato": "revocato", "motivo": "controllo in corso"}, hb)
        s, c = self.g("POST", "/api/admin/verifica_stato",
                      {"host_id": self.hid, "stato": "verificato", "motivo": "ok"}, hb)
        self.assertEqual(s, 200, c)
        self.assertEqual(len(self.connect.chiamate), 1,
                         "la quota decisa dall'arbitro non e' partita alla nuova verifica")

    def test_LA_VERIFICA_NON_PAGA_UN_SOGGIORNO_CONTESTATO(self):
        """Gemella: con la controversia aperta i soldi aspettano l'arbitro, non la verifica."""
        rif = self._book_paga()
        self.assertTrue(self.sis.garanzia.contesta(rif, "prova").get("ok"), "setup: contestata")
        hb = self._hb()
        self.g("POST", "/api/admin/verifica_stato",
               {"host_id": self.hid, "stato": "revocato", "motivo": "controllo in corso"}, hb)
        s, c = self.g("POST", "/api/admin/verifica_stato",
                      {"host_id": self.hid, "stato": "verificato", "motivo": "ok"}, hb)
        self.assertEqual(s, 200, c)
        self.assertEqual(self.connect.chiamate, [],
                         "la verifica ha pagato l'host con la controversia ancora aperta")

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
