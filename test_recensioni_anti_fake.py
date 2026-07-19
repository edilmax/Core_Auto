"""
ANTI-FAKE recensioni (bug provato 2026-07-16).

Il diritto di recensione e' emesso al BOOK, PRIMA del pagamento. Senza controllo si poteva
recensire GRATIS creando un hold mai pagato -> recensioni "verificate" finte a costo zero
(gonfiare la propria vetrina / bombardare un rivale / manipolare il ranking 'consigliati').
Fix: /api/recensioni richiede una prenotazione PAGATA. Qui: (1) non pagata -> 402 bloccata;
(2) pagata -> ammessa (nessuna regressione sul flusso legittimo).
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
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_rec"


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://t/" + secrets.token_hex(4), "id": "cs_" + secrets.token_hex(4)}


class TestRecensioniAntiFake(unittest.TestCase):
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
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db", db_recensioni=f"{d}/rec.db",
            stripe_secret_key="sk", stripe_webhook_secret=WH,
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@rec.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.tok = c["token"]
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa", "titolo": "Casa", "citta": "Roma", "prezzo_notte_cents": 50000,
                "capacita": 4, "politica_cancellazione": "flessibile"}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa", "da": "2026-09-01", "a": "2026-09-30",
                "unita_totali": 2, "prezzo_netto_cents": 50000}, {"X-Host-Token": self.tok})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _book(self, ci, co):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@rec.it"})
        return b

    def _paga(self, rif):
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": rif}}}})
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})

    def test_recensione_senza_pagamento_bloccata(self):
        b = self._book("2026-09-05", "2026-09-08")           # hold NON pagato
        s, res = self.g("POST", "/api/recensioni",
                        {"token": b["diritto_recensione"], "voto": 5, "testo": "finta"})
        self.assertEqual(s, 402, res)
        self.assertEqual(res.get("motivo"), "prenotazione_non_pagata")
        self.assertEqual(self.sys.recensioni.riepilogo("casa")["conteggio"], 0,
                         "REGRESSIONE: recensione finta senza pagamento entrata")

    def test_recensione_pagata_ammessa(self):
        b = self._book("2026-09-15", "2026-09-18")
        self._paga(b["riferimento"])                         # ora e' pagata
        # NBF (2026-07-20, stile Booking/Agoda): pagata MA soggiorno non ancora fatto ->
        # il diritto emesso al book (nbf=check-out) rifiuta con troppo_presto
        s, res = self.g("POST", "/api/recensioni",
                        {"token": b["diritto_recensione"], "voto": 4, "testo": "soggiorno vero"})
        self.assertEqual(s, 400, res)
        self.assertEqual(res.get("motivo"), "troppo_presto")
        # DOPO il check-out (stessa firma di sistema, nbf passato): ammessa
        import time as _t
        from fase63_recensioni import EmettitoreDiritto
        maturo = EmettitoreDiritto(self.sys.firma).emetti(
            b["riferimento"], "casa", non_prima_ts=int(_t.time()) - 60)
        s, res = self.g("POST", "/api/recensioni",
                        {"token": maturo, "voto": 4, "testo": "soggiorno vero"})
        self.assertEqual(s, 201, res)
        self.assertTrue(res.get("ok") and res.get("verificata"))
        rie = self.sys.recensioni.riepilogo("casa")
        self.assertEqual(rie["conteggio"], 1)
        self.assertEqual(rie["media_centesimi"], 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
