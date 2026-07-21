"""GUARDIA — la valuta di un annuncio non si azzera e non cambia sotto le prenotazioni.

DUE DIFETTI dell'audit del 2026-07-22 sull'integrita' fra archivi.

1) AZZERAMENTO SILENZIOSO A EUR.
   La pubblicazione e' un upsert: modificare un annuncio senza rimandare il campo valuta
   faceva scattare il default `"EUR"` di `da_dict`. Un annuncio in **yen** che l'host
   ritoccava (una foto, il prezzo) **tornava in euro di nascosto** — e siccome lo yen non
   ha decimali, il prezzo cambiava anche di scala. La famiglia del difetto dello yen.

2) CAMBIO VALUTA CON PRENOTAZIONI GIA' FATTE.
   Cambiare la valuta di un annuncio dopo che qualcuno ha prenotato renderebbe l'annuncio
   (es. JPY) diverso dal **voucher**, dal **contratto** e dal **registro incassi** di
   quella prenotazione (EUR): lo stesso soggiorno raccontato in due monete. Le prove sono
   firmate nella valuta di allora e non si riscrivono: quindi e' la valuta dell'annuncio
   che non deve cambiare.

COSA SI PRETENDE
  1. modificare un annuncio SENZA mandare la valuta ne conserva la valuta (mai reset a EUR);
  2. cambiare valuta si puo' finche' NON ci sono prenotazioni;
  3. cambiare valuta con una prenotazione gia' fatta -> 409 'valuta_bloccata';
  4. su un annuncio NUOVO la valuta scelta e' libera.
"""

import json
import shutil
import tempfile
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://t/" + secrets.token_hex(4), "id": "cs_" + secrets.token_hex(4)}


class TestValutaAnnuncioBloccata(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"V" * 32, con_registrazione_host=True,
            db_catalogo="%s/c.db" % d, db_inventario="%s/i.db" % d,
            db_registro_host="%s/r.db" % d, db_accettazioni="%s/a.db" % d,
            db_pendenti="%s/p.db" % d, db_payout="%s/y.db" % d,
            db_garanzia="%s/g.db" % d, db_tassa_comunale="%s/t.db" % d,
            commissione_bps=1000, psp_bps=300, stripe_secret_key="sk"))
        self.r = crea_router(self.sys, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        st, c = self.g("POST", "/api/host/registrazione",
                       {"email": "h@v.it", "password": "password1",
                        "accetta_termini": True, "accetta_clausole": True,
                        "accetta_privacy": True, "doc_sha256": doc_sha256(),
                        "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(st, 201, c)
        self.tok = c["token"]

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _pubblica(self, **extra):
        base = {"slug": "zen", "titolo": "Zen House", "citta": "Tokyo",
                "prezzo_notte_cents": 18000, "capacita": 2,
                "politica_cancellazione": "flessibile"}
        base.update(extra)
        return self.g("POST", "/api/host/pubblica", base, {"X-Host-Token": self.tok})

    def _valuta_attuale(self):
        d = self.sys.catalogo.dettaglio("zen")
        return d.get("valuta") if isinstance(d, dict) else None

    def _prenota(self):
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "zen", "da": "2026-08-01", "a": "2026-12-31",
                "unita_totali": 1, "prezzo_netto_cents": 18000}, {"X-Host-Token": self.tok})
        st, q = self.g("POST", "/api/concierge/quote",
                       {"alloggio_id": "zen", "check_in": "2026-09-05",
                        "check_out": "2026-09-08", "party": 2})
        self.assertEqual(st, 200, q)
        st, b = self.g("POST", "/api/concierge/book",
                       {"quote_token": q["quote_token"], "email": "o@v.it"})
        self.assertIn(st, (200, 201), b)

    # ─────────────────────────────────────────────────────────────────────────
    def test_annuncio_nuovo_la_valuta_e_libera(self):
        st, c = self._pubblica(valuta="JPY")
        self.assertIn(st, (200, 201), c)
        self.assertEqual(self._valuta_attuale(), "JPY")

    def test_modifica_senza_valuta_NON_azzera_a_EUR(self):
        self._pubblica(valuta="JPY")
        # ritocco il prezzo, NON mando la valuta
        st, c = self._pubblica(prezzo_notte_cents=19000)
        self.assertIn(st, (200, 201), c)
        self.assertEqual(self._valuta_attuale(), "JPY",
                         "modificando senza mandare la valuta e' tornata EUR in silenzio")

    def test_cambio_valuta_consentito_SENZA_prenotazioni(self):
        self._pubblica(valuta="JPY")
        st, c = self._pubblica(valuta="USD")
        self.assertIn(st, (200, 201), c)
        self.assertEqual(self._valuta_attuale(), "USD")

    def test_cambio_valuta_BLOCCATO_con_prenotazioni(self):
        self._pubblica(valuta="JPY")
        self._prenota()
        st, c = self._pubblica(valuta="EUR")
        self.assertEqual(st, 409,
                         "valuta cambiata mentre esistono prenotazioni in JPY: %s" % c)
        self.assertEqual(c.get("errore"), "valuta_bloccata")
        self.assertEqual(self._valuta_attuale(), "JPY", "la valuta e' cambiata lo stesso")

    def test_ripubblicare_la_STESSA_valuta_con_prenotazioni_e_ok(self):
        self._pubblica(valuta="JPY")
        self._prenota()
        st, c = self._pubblica(valuta="JPY", prezzo_notte_cents=20000)
        self.assertIn(st, (200, 201),
                      "ripubblicare con la stessa valuta viene rifiutato: %s" % c)


if __name__ == "__main__":
    unittest.main(verbosity=2)
