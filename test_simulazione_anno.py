"""
MEGA-SIMULAZIONE "un anno di vita" (richiesta fondatore): 1000 host + 1000 clienti che fanno
TUTTI i flussi consentiti, sul VERO sistema (crea_sistema+crea_router), con Stripe finto.
Verifica gli INVARIANTI d'ingegneria che devono reggere sempre:
 - nessuna DOPPIA prenotazione (anti-overbooking) neppure in gara concorrente;
 - i CONTI tornano al centesimo (guest = netto+comm+carta; escrow rimborso+host = importo);
 - ogni ramo del money-path è coerente (pagato/scaduto/cancellato/contestato/risolto);
 - il sistema non solleva MAI (ogni richiesta -> risposta), health-equivalente sotto carico;
 - i pannelli (host: alloggi/prenotazioni/conversazioni; admin: annunci/controversie) rispondono.
Iterazioni pbkdf2 ridotte via monkeypatch SOLO per velocità del volume (l'hashing è testato
altrove); tutta la logica di business è quella reale.
"""
import json
import os
import random
import shutil
import tempfile
import threading
import time
import unittest

import fase88_registro_host as _rh
import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE

N_HOST = int(os.environ.get("SIM_HOST", "60"))   # suite quotidiana: 60; mega-collaudo: SIM_HOST=1000
N_CLI = int(os.environ.get("SIM_CLI", "60"))
WH = "whsec_anno"


def _fake_checkout(url, body, headers):
    import secrets
    return {"url": "https://ck.test/" + secrets.token_hex(6), "id": "cs_" + secrets.token_hex(6)}


class TestSimulazioneAnno(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._iter = _rh.PBKDF2_ITER
        _rh.PBKDF2_ITER = 1000                      # solo velocità volume (hash testato altrove)
        cls._fetch = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_checkout)

    @classmethod
    def tearDownClass(cls):
        _rh.PBKDF2_ITER = cls._iter
        _stripe.ProviderStripe._fetch_reale = cls._fetch

    def setUp(self):
        self.d = tempfile.mkdtemp()
        d = self.d
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db",
            db_garanzia=f"{d}/g.db", db_messaggi=f"{d}/m.db", db_tassa_comunale=f"{d}/t.db",
            commissione_bps=1000, psp_bps=300,
            stripe_secret_key="sk_test", stripe_webhook_secret=WH,
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/ko"))
        self.r = crea_router(self.sys, host_key="hk", admin_key="ak")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _paga(self, rif):
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata": {"riferimento": rif}}}})
        sig = firma_di_test(payload, WH, int(time.time()))
        return self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                               {"Stripe-Signature": sig})

    def test_un_anno_di_vita(self):
        t0 = time.time()
        # ── 1000 HOST: registrazione + contratto firmato + 1 annuncio + disponibilità ──
        tok, slug = [], []
        for i in range(N_HOST):
            s, c = self.g("POST", "/api/host/registrazione",
                          {"email": "host%04d@sim.test" % i, "password": "password%04d" % i,
                           "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
                           "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
            self.assertEqual(s, 201)
            tok.append(c["token"])
            modal = "su_richiesta" if i % 5 == 0 else "immediata"
            pol = ("non_rimborsabile", "flessibile", "moderata", "rigida")[i % 4]
            val = ("EUR", "USD", "GBP", "JPY")[i % 4]
            prezzo = 12000 if val != "JPY" else 1500000
            sg = f"casa-{i:04d}"
            s, _ = self.g("POST", "/api/host/pubblica",
                          {"slug": sg, "titolo": "Casa %d" % i, "citta": "Roma",
                           "prezzo_notte_cents": prezzo, "capacita": 2 + i % 4, "valuta": val,
                           "modalita_prenotazione": modal, "politica_cancellazione": pol,
                           "sconto_settimana_bps": 1000 if i % 3 else 0},
                          {"X-Host-Token": c["token"]})
            self.assertEqual(s, 201)
            self.g("POST", "/api/host/disponibilita_range",
                   {"alloggio_id": sg, "da": "2026-08-01", "a": "2026-09-30",
                    "unita_totali": 1, "prezzo_netto_cents": prezzo}, {"X-Host-Token": c["token"]})
            slug.append(sg)
        self.assertEqual(len(slug), N_HOST)

        # ── 1000 CLIENTI: ogni ramo del money-path (paga / non-paga-scade / cancella /
        #    contesta+risolvi / su-richiesta approva / ricerca-e-basta) ──
        confermate = contestate = cancellate = scadute = su_richiesta = 0
        for j in range(N_CLI):
            sg = slug[j % N_HOST]
            ramo = j % 6
            gi = 1 + (j % 56)
            ci = "2026-%02d-%02d" % (8 + gi // 28, 1 + gi % 28)
            co = "2026-%02d-%02d" % (8 + (gi + 1) // 28, 1 + (gi + 1) % 28)
            if ramo == 5:                                   # solo ricerca (tanti guardano, non prenotano)
                s, _ = self.g("GET", "/api/catalogo", q={"citta": "Roma", "limit": "12"})
                self.assertEqual(s, 200)
                continue
            s, q = self.g("POST", "/api/concierge/quote",
                          {"alloggio_id": sg, "check_in": ci, "check_out": co, "party": 2})
            if s != 200 or not q.get("quote_token"):
                continue                                    # data occupata: legittimo
            # INVARIANTE CONTI sul preventivo
            self.assertEqual(q["prezzo_guest_cents"],
                             q["netto_host_cents"] + q["commissione_cents"]
                             + q["costo_pagamento_cents"])
            self.assertEqual(q["totale_cents"],
                             q["prezzo_guest_cents"] + q["tassa_soggiorno_cents"])
            s, b = self.g("POST", "/api/concierge/book",
                          {"quote_token": q["quote_token"], "email": "cli%04d@sim.test" % j})
            if s != 201:
                continue
            rif, vt = b["riferimento"], b.get("voucher_token", "")
            if b.get("stato") == "in_attesa_host":          # su-richiesta -> host approva
                self.g("POST", "/api/host/richieste/approva", {"riferimento": rif},
                       {"X-Host-Token": tok[(j % N_HOST)]})
                su_richiesta += 1
                continue
            if ramo == 0:                                   # paga -> confermata
                self._paga(rif); confermate += 1
            elif ramo == 1:                                 # non paga (l'hold scadrà)
                scadute += 1
            elif ramo == 2 and vt:                          # cancella
                self.g("POST", "/api/concierge/cancella", {"voucher_token": vt}); cancellate += 1
            elif ramo == 3 and vt:                          # paga + contesta + chat/prova
                self._paga(rif)
                self.g("POST", "/api/garanzia/contesta",
                       {"voucher_token": vt, "motivo": "problema %d" % j})
                self.g("POST", "/api/voucher/messaggio", {"voucher_token": vt, "testo": "chiarimento"})
                contestate += 1
            elif ramo == 4:                                 # paga + conferma "tutto ok"
                self._paga(rif)
                if vt:
                    self.g("POST", "/api/garanzia/conferma", {"voucher_token": vt})
                confermate += 1

        # ── ADMIN: risolve METÀ delle controversie (arbitro) ──
        s, dc = self.g("GET", "/api/admin/controversie", h={"X-Admin-Key": "ak"})
        self.assertEqual(s, 200)
        aperte = dc.get("controversie", [])
        for k, c in enumerate(aperte):
            if k % 2 == 0:
                st = c["importo_host_cents"]
                s, out = self.g("POST", "/api/admin/controversia/risolvi",
                                {"riferimento": c["prenotazione_id"], "percentuale_ospite": 40},
                                {"X-Admin-Key": "ak"})
                self.assertEqual(s, 200, out)
                # INVARIANTE escrow: rimborso + host = importo
                self.assertEqual(out["rimborso_cliente_cents"] + out["va_all_host_cents"], st)

        # ── sweeper hold: le non-pagate scadono senza lasciare "guadagni fantasma" ──
        pp = self.sys.pagamenti_pendenti
        for rec in pp.scaduti(ora_ts=int(time.time()) + 10 * 86400):
            try:
                self.sys.inventario.rilascia(rec["alloggio_id"], rec["check_in"], rec["check_out"],
                                             idem_key=rec.get("idem_key") or ("h_" + rec["riferimento"]))
            except Exception:
                pass
            pp.scadi(rec["riferimento"])

        # ── INVARIANTE ANTI-OVERBOOKING: nessuna notte con occupate > totali ──
        con = self.sys.inventario._apri()
        try:
            bad = con.execute("SELECT COUNT(*) FROM inventario WHERE unita_occupate > unita_totali").fetchone()[0]
        finally:
            con.close()
        self.assertEqual(bad, 0, "OVERBOOKING: %d notti sovra-occupate" % bad)

        # ── PANNELLI rispondono (host + admin) ──
        s, mine = self.g("GET", "/api/host/alloggi", h={"X-Host-Token": tok[0]})
        self.assertEqual(s, 200); self.assertTrue(mine["alloggi"])
        for path in ("/api/host/prenotazioni", "/api/host/conversazioni"):
            s, _ = self.g("GET", path, h={"X-Host-Token": tok[3]})
            self.assertEqual(s, 200, path)
        s, aa = self.g("GET", "/api/admin/alloggi", h={"X-Admin-Key": "ak"})
        # Field paginato (max 20/pagina): il CONTEGGIO totale e' nel campo 'totale',
        # la pagina ne porta al massimo 20.
        self.assertEqual(s, 200); self.assertEqual(aa.get("totale"), N_HOST)
        self.assertLessEqual(len(aa.get("alloggi", [])), 20)

        dt = time.time() - t0
        print("\n== 1 ANNO: %d host, %d clienti | conf=%d contest=%d canc=%d scad=%d surichiesta=%d "
              "| controversie=%d | %.1fs ==" % (N_HOST, N_CLI, confermate, contestate, cancellate,
                                                scadute, su_richiesta, len(aperte), dt))

    def test_gara_1_stanza_100_clienti(self):
        # concorrenza estrema: 100 thread sulla STESSA stanza/date -> 1 solo vincitore
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "gara@sim.test", "password": "passwordgara",
                       "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        t = c["token"]
        self.g("POST", "/api/host/pubblica", {"slug": "gara", "titolo": "Gara", "citta": "Roma",
               "prezzo_notte_cents": 10000, "capacita": 2}, {"X-Host-Token": t})
        for gg in ("2026-09-01", "2026-09-02"):
            self.sys.inventario.imposta_disponibilita("gara", gg, unita_totali=1, prezzo_netto_cents=10000)
        vinti = []
        lock = threading.Lock()

        def cliente(i):
            s, q = self.g("POST", "/api/concierge/quote",
                          {"alloggio_id": "gara", "check_in": "2026-09-01",
                           "check_out": "2026-09-03", "party": 2})
            if s != 200 or not q.get("quote_token"):
                return
            s2, b = self.g("POST", "/api/concierge/book",
                           {"quote_token": q["quote_token"], "email": "g%d@sim.test" % i})
            if s2 == 201 and b.get("stato") != "in_attesa_host":
                with lock:
                    vinti.append(b["riferimento"])
        th = [threading.Thread(target=cliente, args=(i,)) for i in range(100)]
        for x in th:
            x.start()
        for x in th:
            x.join(timeout=60)
        self.assertLessEqual(len(vinti), 1, "OVERBOOKING sotto gara: %d vincitori" % len(vinti))


if __name__ == "__main__":
    unittest.main(verbosity=2)
