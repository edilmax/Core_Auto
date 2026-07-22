"""
Collaudo BUG "su-richiesta + Stripe" (trovato in prod: la prenotazione APPROVATA spariva).

Catena rotta prima del fix: (1) il link Stripe nasceva alla RICHIESTA e durava 30 min, ma
l'host ha 24h per approvare -> link morto; (2) l'email post-approvazione non conteneva il
link di pagamento (il cliente non sapeva di dover pagare); (3) l'hold ri-registrato durava
120s -> lo sweeper liberava le date e la prenotazione approvata SPARIVA (stato 'scaduto').

Il fix: all'approvazione si rigenera un link FRESCO (scade_secondi=HOLD_APPROVAZIONE_SEC,
~24h, massimo Stripe) e l'hold dura ALTRETTANTO; l'email include il bottone di pagamento;
se il link non si crea -> 503 e la richiesta RESTA in_attesa_host (fail-safe, ricliccabile).
"""
import json
import os
import re
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import HOLD_APPROVAZIONE_SEC, crea_router
from fase86_email import corpo_voucher_html
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE

WHSEC = "whsec_sr"


class TestSuRichiestaStripe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        # Stripe FINTO che registra i body (per leggere expires_at) e conta le sessioni
        self.sessioni = []

        def fake_fetch(url, body, headers):
            corpo = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else str(body)
            self.sessioni.append(corpo)
            return {"url": "https://checkout.stripe.test/cs_%d" % len(self.sessioni),
                    "id": "cs_test_%d" % len(self.sessioni)}

        _stripe.ProviderStripe._fetch_reale = staticmethod(fake_fetch)
        self.dir = tempfile.mkdtemp()
        d = self.dir
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/acc.db",
            db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db", db_garanzia=f"{d}/g.db",
            commissione_bps=1000, psp_bps=300,
            stripe_secret_key="sk_test_sr", stripe_webhook_secret=WHSEC,
            stripe_success_url="https://bookinvip.com/grazie.html",
            stripe_cancel_url="https://bookinvip.com/annullato.html"))
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@sr.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.hid, self.tok = c["host_id"], c["token"]
        s, _ = self.g("POST", "/api/host/pubblica",
                      {"slug": "casa-sr", "titolo": "Casa SR", "citta": "Roma",
                       "prezzo_notte_cents": 10000, "capacita": 2,
                       "modalita_prenotazione": "su_richiesta"}, {"X-Host-Token": self.tok})
        self.assertEqual(s, 201)
        s, _ = self.g("POST", "/api/host/disponibilita_range",
                      {"alloggio_id": "casa-sr", "da": "2026-09-01", "a": "2026-10-31",
                       "unita_totali": 1, "prezzo_netto_cents": 10000}, {"X-Host-Token": self.tok})
        self.assertEqual(s, 200)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, metodo, path, body=None, headers=None, query=None):
        return self.r.gestisci(metodo, path, query or {},
                               json.dumps(body) if body is not None else None, headers or {})

    def _richiedi(self, ci, co):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa-sr", "check_in": ci, "check_out": co, "party": 2})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@sr.it"})
        self.assertEqual(s, 201, b)
        self.assertEqual(b["stato"], "in_attesa_host")
        self.assertNotIn("payment_url", b)          # il cliente NON riceve il link alla richiesta
        return b["riferimento"]

    def _webhook(self, rif):
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata": {"riferimento": rif}}}})
        sig = firma_di_test(payload, WHSEC, int(time.time()))
        return self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                               {"Stripe-Signature": sig})

    # ── IL FIX, pezzo per pezzo ───────────────────────────────────────────────
    def test_approva_rigenera_link_fresco_con_scadenza_24h(self):
        ref = self._richiedi("2026-09-10", "2026-09-12")
        n_prima = len(self.sessioni)                 # sessione della book (creata da fase59)
        s, esito = self.g("POST", "/api/host/richieste/approva", {"riferimento": ref},
                          {"X-Host-Token": self.tok})
        self.assertEqual(s, 200, esito)
        pren = esito["prenotazione"]
        self.assertTrue(pren.get("payment_url"))     # il cliente ORA ha un link
        self.assertEqual(len(self.sessioni), n_prima + 1, "doveva creare una sessione NUOVA")
        # la sessione nuova scade ~24h (non 30 min): expires_at nel body
        m = re.search(r"expires_at=(\d+)", self.sessioni[-1])
        self.assertTrue(m)
        delta = int(m.group(1)) - int(time.time())
        self.assertGreater(delta, HOLD_APPROVAZIONE_SEC - 120)
        self.assertLessEqual(delta, 86400)           # dentro il massimo Stripe

    def test_hold_dura_24h_non_2_minuti(self):
        ref = self._richiedi("2026-09-14", "2026-09-16")
        s, _ = self.g("POST", "/api/host/richieste/approva", {"riferimento": ref},
                      {"X-Host-Token": self.tok})
        self.assertEqual(s, 200)
        pp = self.sys.pagamenti_pendenti
        rec = pp.info(ref)
        self.assertEqual(rec["stato"], "in_attesa")
        # a +10 minuti l'hold NON è scaduto (prima del fix: 120s -> spariva)
        ora = int(time.time())
        scaduti = [x["riferimento"] for x in pp.scaduti(ora_ts=ora + 600)]
        self.assertNotIn(ref, scaduti, "REGRESSIONE: hold approvazione scade come instant (120s)")
        # e scade correttamente dopo le 24h (il cliente che non paga non tiene la stanza)
        scaduti_24h = [x["riferimento"] for x in pp.scaduti(ora_ts=ora + HOLD_APPROVAZIONE_SEC + 60)]
        self.assertIn(ref, scaduti_24h)

    def test_date_restano_bloccate_e_pagamento_conferma(self):
        ref = self._richiedi("2026-09-18", "2026-09-20")
        s, _ = self.g("POST", "/api/host/richieste/approva", {"riferimento": ref},
                      {"X-Host-Token": self.tok})
        self.assertEqual(s, 200)
        # date bloccate: nessun altro può prenotarle
        s, q2 = self.g("POST", "/api/concierge/quote",
                       {"alloggio_id": "casa-sr", "check_in": "2026-09-18",
                        "check_out": "2026-09-20", "party": 2})
        self.assertFalse(q2.get("quote_token"), "le date approvate dovevano essere bloccate")
        # payout in_attesa (non guadagno fantasma) finché il cliente non paga
        rie = self.sys.payout.riepilogo(self.hid).get("EUR", {})
        self.assertGreater(rie.get("in_attesa", 0), 0)
        self.assertEqual(rie.get("maturato", 0), 0)
        # il cliente paga dall'email -> webhook -> confermata + maturato
        s, _ = self._webhook(ref)
        self.assertEqual(s, 200)
        self.assertEqual(self.sys.pagamenti_pendenti.info(ref)["stato"], "pagato")
        rie2 = self.sys.payout.riepilogo(self.hid).get("EUR", {})
        self.assertGreater(rie2.get("maturato", 0), 0)
        # e appare in "Le mie prenotazioni"
        s, pr = self.g("GET", "/api/host/prenotazioni", headers={"X-Host-Token": self.tok})
        self.assertEqual(s, 200)
        date = [(p["check_in"], p["check_out"]) for p in pr["prenotazioni"]]
        self.assertIn(("2026-09-18", "2026-09-20"), date)

    def test_link_non_creabile_failsafe(self):
        ref = self._richiedi("2026-09-22", "2026-09-24")

        def fetch_rotto(url, body, headers):
            raise RuntimeError("stripe giu'")

        # il provider VIVO cattura il fetch in __init__: sostituisco direttamente il suo
        self.sys.stripe._fetch = fetch_rotto
        s, esito = self.g("POST", "/api/host/richieste/approva", {"riferimento": ref},
                          {"X-Host-Token": self.tok})
        self.assertEqual(s, 503, esito)              # niente conferma senza link
        rec = self.sys.pagamenti_pendenti.info(ref)
        self.assertEqual(rec["stato"], "in_attesa_host")   # la richiesta RESTA: ricliccabile

    def test_email_contiene_bottone_pagamento(self):
        html = corpo_voucher_html("Casa SR", "BVIP-XXXX-YYYY", "2026-09-10", "2026-09-12",
                                  "https://bookinvip.com/voucher/tok", pin="1234", lingua="it",
                                  payment_url="https://checkout.stripe.test/cs_9")
        self.assertIn("https://checkout.stripe.test/cs_9", html)
        self.assertIn("Completa il pagamento", html)
        self.assertIn("approvata e riservata", html)
        # senza payment_url: email classica, nessun bottone
        html2 = corpo_voucher_html("Casa SR", "BVIP-XXXX-YYYY", "2026-09-10", "2026-09-12",
                                   "https://bookinvip.com/voucher/tok", pin="1234", lingua="it")
        self.assertNotIn("Completa il pagamento", html2)
        self.assertIn("Prenotazione confermata", html2)

    def test_calendario_mostra_in_trattativa(self):
        # richiesta in attesa dell'host -> quei giorni sono ARANCIONI (in_trattativa),
        # non "pieno": l'host capisce che non è ancora una prenotazione confermata.
        ref = self._richiedi("2026-10-01", "2026-10-03")
        s, cal = self.g("GET", "/api/host/calendario", headers={"X-Host-Token": self.tok},
                        query={"alloggio": "casa-sr", "da": "2026-09-30", "a": "2026-10-05"})
        self.assertEqual(s, 200, cal)
        stati = {g["giorno"]: g["stato"] for g in cal["giorni"]}
        self.assertEqual(stati.get("2026-10-01"), "in_trattativa")
        self.assertEqual(stati.get("2026-10-02"), "in_trattativa")
        self.assertEqual(stati.get("2026-10-03"), "libero")     # check-out escluso
        self.assertEqual(stati.get("2026-09-30"), "libero")
        # approva + paga -> diventa OCCUPATO (pieno), non più in trattativa
        s, _ = self.g("POST", "/api/host/richieste/approva", {"riferimento": ref},
                      {"X-Host-Token": self.tok})
        self.assertEqual(s, 200)
        self._webhook(ref)
        s, cal2 = self.g("GET", "/api/host/calendario", headers={"X-Host-Token": self.tok},
                         query={"alloggio": "casa-sr", "da": "2026-09-30", "a": "2026-10-05"})
        stati2 = {g["giorno"]: g["stato"] for g in cal2["giorni"]}
        self.assertEqual(stati2.get("2026-10-01"), "pieno")
        self.assertEqual(stati2.get("2026-10-02"), "pieno")

    def test_scade_secondi_clamp_fase85(self):
        catture = []

        def fetch(url, body, headers):
            catture.append(body.decode("utf-8"))
            return {"url": "https://x/y", "id": "cs_1"}

        p = _stripe.ProviderStripe("sk_test", "https://ok", "https://ko", fetch=fetch)
        ora = int(time.time())
        for chiesto, atteso in ((None, 1800), (60, 1800), (86100, 86100), (999999, 86100)):
            dati = {"totale_cents": 1000, "riferimento": "r1"}
            if chiesto is not None:
                dati["scade_secondi"] = chiesto
            self.assertTrue(p.crea_link(dati))
            m = re.search(r"expires_at=(\d+)", catture[-1])
            delta = int(m.group(1)) - ora
            self.assertAlmostEqual(delta, atteso, delta=30,
                                   msg="scade_secondi=%r -> atteso ~%d, avuto %d"
                                       % (chiesto, atteso, delta))


if __name__ == "__main__":
    unittest.main(verbosity=2)
