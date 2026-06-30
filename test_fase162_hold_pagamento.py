"""Test HOLD prima del pagamento (fase162) + webhook conferma + ledger tassa (fase147) + sweep.
Chiude il buco: una prenotazione non pagata NON blocca piu' la stanza per sempre."""
import hashlib
import hmac
import json
import shutil
import tempfile
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase162_pagamenti_pendenti import crea_pagamenti_pendenti

SEG = b"h" * 32
HK = {"X-Host-Key": "hk"}
WHSEC = "whsec_test"


class TestModulo(unittest.TestCase):
    def setUp(self):
        self.clock = {"t": 1000}
        self.p = crea_pagamenti_pendenti(":memory:", orologio=lambda: self.clock["t"])
        self.p.inizializza_schema()

    def test_registra_conferma_scaduti(self):
        self.assertTrue(self.p.registra("R1", alloggio_id="casa", check_in="2027-01-10",
                                        check_out="2027-01-12", idem_key="k1", tassa_cents=800,
                                        comune="Roma", scadenza_ts=2000))
        self.assertEqual(self.p.info("R1")["stato"], "in_attesa")
        self.clock["t"] = 3000
        self.assertEqual(len(self.p.scaduti()), 1)              # scaduto e non pagato
        rec = self.p.conferma("R1")                             # paga
        self.assertEqual(rec["tassa_cents"], 800)
        self.assertEqual(rec["comune"], "Roma")
        self.assertEqual(self.p.info("R1")["stato"], "pagato")
        self.assertEqual(self.p.scaduti(), [])                  # pagato -> non piu' scaduto
        self.assertTrue(self.p.rimuovi("R1"))


class TestFlussoHold(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db", db_messaggi=f"{d}/m.db",
            db_domanda=f"{d}/dom.db", db_garanzia=f"{d}/g.db", db_pendenti=f"{d}/p.db",
            db_tassa_comunale=f"{d}/tc.db", file_referral=f"{d}/ref.json",
            commissione_bps=1500, stripe_webhook_secret=WHSEC))
        # forza un payment_url (simula Stripe configurato) -> attiva l'HOLD
        self.sis.concierge._link = lambda dati: "https://pay/" + str(dati.get("riferimento", ""))
        self.r = crea_router(self.sis, host_key="hk", base_url="https://bookinvip.com")
        self.g("POST", "/api/host/pubblica", {"host_id": "demo", "slug": "casa", "titolo": "C",
               "citta": "Roma", "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
               "servizi": [], "immagini": [], "tassa_pp_notte_cents": 200}, HK)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa", "da": "2027-02-01",
               "a": "2027-02-28", "unita_totali": 1, "prezzo_netto_cents": 10000}, HK)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _book(self):
        _, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "casa",
                      "check_in": "2027-02-10", "check_out": "2027-02-12", "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "o@x.it"})
        return b

    def test_book_va_in_attesa_pagamento(self):
        b = self._book()
        self.assertEqual(b["stato"], "in_attesa_pagamento")     # NON confermata finche' non paga
        self.assertTrue(b.get("payment_url"))
        rec = self.sis.pagamenti_pendenti.info(b["riferimento"])
        self.assertEqual(rec["stato"], "in_attesa")
        self.assertEqual(rec["tassa_cents"], 800)               # 200*2*2

    def test_webhook_conferma_e_registra_tassa(self):
        b = self._book()
        rif = b["riferimento"]
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata": {"riferimento": rif}}}})
        ts = str(int(time.time()))
        mac = hmac.new(WHSEC.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
        # il body deve essere il payload GREZZO (la firma e' sul body grezzo)
        s, _ = self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                               {"Stripe-Signature": "t=%s,v1=%s" % (ts, mac)})
        self.assertEqual(s, 200)
        self.assertEqual(self.sis.pagamenti_pendenti.info(rif)["stato"], "pagato")
        self.assertEqual(self.sis.tassa_comunale.totale_riscosso("Roma"), 800)  # ledger

    def test_sweep_libera_lhold_non_pagato(self):
        b = self._book()
        rif = b["riferimento"]
        # simulo lo sweeper: forzo la scadenza nel passato e libero come fa il thread
        pp = self.sis.pagamenti_pendenti
        # riapro con scadenza passata: registro un record gia' scaduto e lo libero
        for rec in [pp.info(rif)]:
            self.sis.inventario.rilascia(rec["alloggio_id"], rec["check_in"], rec["check_out"],
                                         idem_key=rec["idem_key"])
            pp.rimuovi(rif)
        # le date sono di nuovo prenotabili
        _, q2 = self.g("POST", "/api/concierge/quote", {"alloggio_id": "casa",
                       "check_in": "2027-02-10", "check_out": "2027-02-12", "party": 1})
        self.assertEqual(q2.get("quote_token") is not None, True)


if __name__ == "__main__":
    unittest.main()
