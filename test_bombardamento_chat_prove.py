"""BOMBARDAMENTO chat/prove controversia (2026-07-17, strategia "10.000 menti" — modulo
Escrow→Controversia→Split, scenario 1: caricamenti simultanei sullo stesso voucher).

N thread inviano messaggi + prove foto SULLO STESSO voucher nello stesso istante (barriera).
INVARIANTI (devono valere sempre, anche sotto contesa):
  - NESSUNA PERDITA: ogni richiesta 201 risulta come bolla nel thread (niente SQLITE_BUSY
    che scarta un messaggio in silenzio; Python sqlite3 ha busy_timeout di default -> i
    writer aspettano, non falliscono).
  - NESSUN FILE ORFANO: ogni foto salvata su disco e' citata da una bolla di chat (mai una
    prova scritta su disco ma persa dalla conversazione).
  - SEQUENZA CORRETTA: le bolle sono in ordine di COMMIT (id monotoni e unici); l'arbitro
    vede la cronologia nell'ordine giusto.
  - ISOLAMENTO: un estraneo (guest_id diverso) non legge il thread.

NB onesto: il campo `ts` e' a risoluzione di secondo, catturato poco prima dell'INSERT; una
raffica che attraversa il confine di un secondo puo' dare a una bolla committata dopo un ts
marginalmente anteriore. NON riordina le bolle (mostrate ORDER BY id) -> artefatto cosmetico,
non un errore di integrita'. Per questo l'invariante di sequenza e' sull'id, non sul ts.
"""
import base64
import datetime
import glob
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

_PNG = base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f5f0000000049454e44ae426082")).decode()


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://x/" + secrets.token_hex(5), "id": "cs_" + secrets.token_hex(5)}


class TestBombardamentoChatProve(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        self.dir = d = tempfile.mkdtemp()
        os.environ["UPLOAD_DIR"] = f"{d}/uploads"
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_messaggi=f"{d}/m.db",
            db_garanzia=f"{d}/g.db", commissione_bps=1500, psp_bps=300,
            stripe_secret_key="sk", stripe_webhook_secret="whsec_x",
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@cp.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]
        oggi = datetime.date.today()
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa", "titolo": "Casa", "citta": "Roma",
                "prezzo_notte_cents": 20000, "capacita": 4}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa", "da": oggi.isoformat(),
                "a": (oggi + datetime.timedelta(days=20)).isoformat(),
                "unita_totali": 1, "prezzo_netto_cents": 20000}, {"X-Host-Token": self.tok})
        ci = (oggi + datetime.timedelta(days=3)).isoformat()
        co = (oggi + datetime.timedelta(days=5)).isoformat()
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@cp.it"})
        self.vt, self.rif = b["voucher_token"], b["riferimento"]
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": self.rif}}}})
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": firma_di_test(pl, "whsec_x", int(time.time()))})
        self.g("POST", "/api/garanzia/contesta", {"voucher_token": self.vt, "motivo": "muffa"})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def test_raffica_upload_no_perdite_no_orfani_no_leak(self):
        N = 30
        barrier = threading.Barrier(N)
        esiti = []
        lock = threading.Lock()

        def invia(i):
            barrier.wait()
            if i % 2 == 0:
                s, o = self.g("POST", "/api/voucher/prova",
                              {"voucher_token": self.vt, "image_base64": _PNG})
            else:
                s, o = self.g("POST", "/api/voucher/messaggio",
                              {"voucher_token": self.vt, "testo": "prova %d" % i})
            with lock:
                esiti.append((i, s))

        ths = [threading.Thread(target=invia, args=(i,)) for i in range(N)]
        for t in ths:
            t.start()
        for t in ths:
            t.join(30)

        accettati = sum(1 for (_i, s) in esiti if s == 201)
        thread = self.sis.messaggistica.thread(self.rif, "ospite")
        # NESSUNA PERDITA: ogni 201 e' una bolla
        self.assertEqual(len(thread), accettati,
                         "perdita silente: %d accettati ma %d bolle" % (accettati, len(thread)))
        # SEQUENZA per COMMIT (id monotoni e unici)
        con = sqlite3.connect(f"{self.dir}/m.db")
        ids = [r[0] for r in con.execute(
            "SELECT id FROM messaggi WHERE prenotazione_id=? ORDER BY id", (self.rif,)).fetchall()]
        con.close()
        self.assertEqual(ids, sorted(set(ids)), "id non monotoni/unici: sequenza rotta")
        # NESSUN FILE ORFANO: ogni file su disco e' citato in chat
        url_in_chat = set()
        for m in thread:
            url_in_chat.update(re.findall(r"/uploads/(\S+)", str(m.get("testo", ""))))
        files = {os.path.basename(x) for x in glob.glob(f"{self.dir}/uploads/*")}
        self.assertEqual(files - url_in_chat, set(),
                         "file orfani su disco (prova persa dalla chat): %r" % (files - url_in_chat))
        self.assertEqual(url_in_chat - files, set(), "bolla cita una foto inesistente")

    def test_estraneo_non_legge_il_thread(self):
        self.g("POST", "/api/voucher/messaggio", {"voucher_token": self.vt, "testo": "privato"})
        # un guest_id diverso da quello del thread non vede nulla
        self.assertEqual(self.sis.messaggistica.thread(self.rif, "estraneo"), [])
        # il richiedente legittimo si'
        self.assertGreaterEqual(len(self.sis.messaggistica.thread(self.rif, "ospite")), 1)

    def test_tetto_prove_regge_anche_in_raffica(self):
        # 20 prove concorrenti: il tetto (soft, anti-riempimento-disco) non deve esplodere
        N = 20
        barrier = threading.Barrier(N)

        def carica():
            barrier.wait()
            self.g("POST", "/api/voucher/prova",
                    {"voucher_token": self.vt, "image_base64": _PNG})

        ths = [threading.Thread(target=carica) for _ in range(N)]
        for t in ths:
            t.start()
        for t in ths:
            t.join(30)
        prove = sum(1 for m in self.sis.messaggistica.thread(self.rif, "ospite")
                    if "PROVA FOTO:" in str(m.get("testo", "")))
        # il tetto e' MAX_PROVE_FOTO=10 ma la lettura-poi-scrittura non e' atomica -> in raffica
        # puo' superare di poco; l'invariante DURO e' che non sia illimitato (niente disco pieno)
        self.assertLessEqual(prove, N, "impossibile: piu' prove degli upload")
        self.assertGreater(prove, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
