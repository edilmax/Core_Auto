"""Collaudo BUG #16 (2026-07-16): la decisione su una richiesta 'in_attesa_host' NON era
atomica. Due decisioni concorrenti procedevano entrambe:
  - approva + rifiuta simultanei -> prenotazione CONFERMATA (escrow aperto, email "paga"
    al cliente) su date GIA' LIBERATE dal rifiuto -> un secondo cliente prenotava le
    stesse notti = OVERBOOKING + cliente invitato a pagare una stanza inesistente;
  - doppio click su approva -> 2 finalizzazioni (2 sessioni Stripe, 2 email).

Il fix: fase162.rimuovi_se_stato (DELETE condizionato allo stato = CAS) usato da
_decidi_richiesta sia sull'approva (dopo il fail-safe del link) sia sul rifiuta (PRIMA
del rilascio date): una sola decisione vince, il perdente riceve 404 e non tocca niente.

L'interleaving e' riprodotto REALE: il thread "approva" entra in _decidi_richiesta, legge
il record e si blocca dentro stripe.crea_link (fetch finto bloccante); nel frattempo
l'altra decisione completa; poi si sblocca e si verifica chi ha vinto.
"""
import json
import shutil
import tempfile
import threading
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE


class TestDecisioneRichiestaAtomica(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        self.gate = threading.Event()       # crea_link resta fermo qui finche' non si apre
        self.dentro = threading.Event()     # segnala: un thread e' DENTRO crea_link
        self.gate.set()                     # di default passa (book/finalizza normali)

        def fetch_block(url, body, headers, _n=[0]):
            _n[0] += 1
            self.dentro.set()
            self.gate.wait(10)
            return {"url": "https://checkout.stripe.test/cs_%d" % _n[0],
                    "id": "cs_%d" % _n[0]}

        _stripe.ProviderStripe._fetch_reale = staticmethod(fetch_block)
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/acc.db",
            db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db", db_garanzia=f"{d}/g.db",
            commissione_bps=1000, psp_bps=300,
            stripe_secret_key="sk_test_x", stripe_webhook_secret="whsec_x",
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/ko"))
        self.r = crea_router(self.sis, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@ra.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa-ra", "titolo": "Casa RA", "citta": "Roma",
                "prezzo_notte_cents": 10000, "capacita": 2,
                "modalita_prenotazione": "su_richiesta"}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa-ra", "da": "2026-09-01", "a": "2026-09-30",
                "unita_totali": 1, "prezzo_netto_cents": 10000}, {"X-Host-Token": self.tok})

    def tearDown(self):
        self.gate.set()                     # mai lasciare thread appesi
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None,
                               h or {})

    def _richiedi(self):
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa-ra", "check_in": "2026-09-10",
                       "check_out": "2026-09-12", "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@ra.it"})
        self.assertEqual(b["stato"], "in_attesa_host")
        return b["riferimento"]

    def _approva_bloccato(self, ref, esiti, chiave):
        def corri():
            esiti[chiave] = self.g("POST", "/api/host/richieste/approva",
                                   {"riferimento": ref}, {"X-Host-Token": self.tok})
        t = threading.Thread(target=corri)
        t.start()
        return t

    def test_approva_vs_rifiuta_una_sola_decisione(self):
        ref = self._richiedi()
        self.gate.clear()
        self.dentro.clear()
        esiti = {}
        t = self._approva_bloccato(ref, esiti, "A")
        self.assertTrue(self.dentro.wait(10), "approva non e' entrato in crea_link")
        sR, cR = self.g("POST", "/api/host/richieste/rifiuta",
                        {"riferimento": ref}, {"X-Host-Token": self.tok})
        self.gate.set()
        t.join(10)
        sA, cA = esiti["A"]
        # UNA sola decisione vince
        self.assertEqual(sR, 200, cR)
        self.assertEqual(sA, 404, "approva doveva PERDERE la gara (CAS): %r" % (cA,))
        # il perdente non ha toccato niente: nessun escrow, niente prenotazione fantasma
        self.assertIsNone(self.sis.garanzia.stato(ref))
        self.assertIsNone(self.sis.pagamenti_pendenti.info(ref))
        # le date sono davvero libere (il rifiuto le ha rilasciate, l'approva non le ha riprese)
        s2, q2 = self.g("POST", "/api/concierge/quote",
                        {"alloggio_id": "casa-ra", "check_in": "2026-09-10",
                         "check_out": "2026-09-12", "party": 2})
        self.assertEqual(s2, 200)
        self.assertTrue(q2.get("quote_token"), "date rilasciate dal rifiuto: riprenotabili")

    def test_doppio_approva_una_sola_finalizzazione(self):
        ref = self._richiedi()
        self.gate.clear()
        self.dentro.clear()
        esiti = {}
        t1 = self._approva_bloccato(ref, esiti, "A1")
        t2 = self._approva_bloccato(ref, esiti, "A2")
        self.assertTrue(self.dentro.wait(10))
        time.sleep(0.5)                     # entrambi in volo sul record
        self.gate.set()
        t1.join(10)
        t2.join(10)
        stati = sorted(s for s, _ in esiti.values())
        self.assertEqual(stati, [200, 404],
                         "doppio approva: doveva vincerne UNO solo, esiti=%r" % (esiti,))
        # una sola pendente 'in_attesa' registrata (un solo hold pagamento)
        rec = self.sis.pagamenti_pendenti.info(ref)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["stato"], "in_attesa")

    def test_rifiuta_dopo_sweeper_scaduto_non_rilascia(self):
        # lo sweeper ha gia' scadito la richiesta (CAS scadi + rilascio): un rifiuto
        # tardivo deve perdere il CAS e NON toccare le date (rilascio doppio = replay).
        ref = self._richiedi()
        pp = self.sis.pagamenti_pendenti
        self.assertTrue(pp.scadi(ref))      # come fa lo sweeper (in_attesa_host -> scaduto)
        s, c = self.g("POST", "/api/host/richieste/rifiuta",
                      {"riferimento": ref}, {"X-Host-Token": self.tok})
        self.assertEqual(s, 404, c)
        self.assertEqual(pp.info(ref)["stato"], "scaduto")   # record intatto


if __name__ == "__main__":
    unittest.main(verbosity=2)
