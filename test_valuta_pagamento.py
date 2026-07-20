"""
COERENZA multi-valuta al PAGAMENTO (bug provato 2026-07-16).

Il provider Stripe usava una valuta FISSA (config, EUR) per OGNI addebito, ignorando la valuta
dell'annuncio: un annuncio in JPY/USD/GBP veniva addebitato in EUR (valuta sbagliata + importo
errato; e incassavamo EUR mentre dovevamo un'altra valuta all'host). Rompeva il "like-for-like".
Fix: crea_link usa la valuta della PRENOTAZIONE. Qui: la valuta inviata a Stripe == valuta annuncio.
"""
import json
import shutil
import tempfile
import unittest
from urllib.parse import parse_qs

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

_CAP = {}


def _fake_fetch(url, body, headers):
    import secrets
    _CAP["p"] = parse_qs(body.decode("utf-8"))
    return {"url": "https://c/" + secrets.token_hex(4), "id": "cs_" + secrets.token_hex(4)}


class TestValutaPagamento(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def _addebito(self, valuta_annuncio, prezzo):
        """Pubblica un annuncio nella valuta data, prenota, ritorna (currency, amount) verso Stripe."""
        d = tempfile.mkdtemp()
        try:
            sysx = crea_sistema(ConfigCasaVIP(
                abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
                db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
                db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db", valuta="EUR",
                stripe_secret_key="sk", stripe_webhook_secret="wh",
                stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
            r = crea_router(sysx, host_key="hk", base_url="https://bookinvip.com")

            def g(m, p, b=None, h=None):
                return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})
            s, c = g("POST", "/api/host/registrazione",
                     {"email": "h@v.it", "password": "password1", "accetta_termini": True,
                      "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                      "versione": CONTRATTO_HOST_VERSIONE})
            tok = c["token"]
            g("POST", "/api/host/pubblica",
              {"slug": "a", "titolo": "A", "citta": "X", "prezzo_notte_cents": prezzo,
               "capacita": 2, "politica_cancellazione": "flessibile",
               "valuta": valuta_annuncio}, {"X-Host-Token": tok})
            g("POST", "/api/host/disponibilita_range",
              {"alloggio_id": "a", "da": "2026-09-01", "a": "2026-09-30",
               "unita_totali": 1, "prezzo_netto_cents": prezzo, "valuta": valuta_annuncio},
              {"X-Host-Token": tok})
            s, q = g("POST", "/api/concierge/quote",
                     {"alloggio_id": "a", "check_in": "2026-09-05", "check_out": "2026-09-07",
                      "party": 2})
            self.assertEqual(q.get("valuta"), valuta_annuncio)
            _CAP.clear()
            s, b = g("POST", "/api/concierge/book",
                     {"quote_token": q["quote_token"], "email": "cli@v.it"})
            self.assertEqual(s, 201, b)
            p = _CAP.get("p", {})
            cur = (p.get("line_items[0][price_data][currency]") or [""])[0]
            amt = (p.get("line_items[0][price_data][unit_amount]") or [""])[0]
            return cur, amt, q.get("totale_cents")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_jpy_addebitato_in_jpy(self):
        cur, amt, tot = self._addebito("JPY", 10000)
        self.assertEqual(cur, "jpy", "REGRESSIONE: annuncio JPY addebitato in valuta sbagliata")
        self.assertEqual(int(amt), tot)

    def test_usd_addebitato_in_usd(self):
        cur, amt, tot = self._addebito("USD", 10000)
        self.assertEqual(cur, "usd")
        self.assertEqual(int(amt), tot)

    def test_eur_resta_eur(self):
        cur, amt, tot = self._addebito("EUR", 10000)
        self.assertEqual(cur, "eur", "nessuna regressione sulle prenotazioni in EUR")
        self.assertEqual(int(amt), tot)


if __name__ == "__main__":
    unittest.main(verbosity=2)
