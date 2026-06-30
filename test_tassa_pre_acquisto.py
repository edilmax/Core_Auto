"""Test tassa di soggiorno PRECISA e PRE-ACQUISTO: l'host la dichiara sull'annuncio (tutela),
il preventivo la calcola e la mostra separata + totale. Citta' senza regola -> 0 (mai inventare)."""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

SEG = b"t" * 32
HK = {"X-Host-Key": "hk"}


class TestTassaPreAcquisto(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db", db_messaggi=f"{d}/m.db",
            db_domanda=f"{d}/dom.db", db_garanzia=f"{d}/g.db", file_referral=f"{d}/ref.json",
            commissione_bps=1500))
        self.r = crea_router(self.sis, host_key="hk", base_url="https://bookinvip.com")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _pubblica(self, **tax):
        body = {"host_id": "demo", "slug": "casa", "titolo": "Casa", "citta": "Roma",
                "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 4,
                "servizi": [], "immagini": []}
        body.update(tax)
        self.g("POST", "/api/host/pubblica", body, HK)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa",
                "da": "2027-01-01", "a": "2027-01-31", "unita_totali": 1,
                "prezzo_netto_cents": 10000}, HK)

    def _quote(self, party=2):
        _, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "casa",
                      "check_in": "2027-01-10", "check_out": "2027-01-12", "party": party})
        return q

    def test_tassa_calcolata_e_mostrata_pre_acquisto(self):
        self._pubblica(tassa_pp_notte_cents=200)            # €2,00 per persona/notte
        q = self._quote(party=2)                            # 2 persone x 2 notti
        self.assertEqual(q["tassa_soggiorno_cents"], 800)   # 200*2*2
        self.assertEqual(q["prezzo_guest_cents"], 20000)    # soggiorno pulito
        self.assertEqual(q["totale_cents"], 20800)          # quello che paga DAVVERO l'ospite
        self.assertEqual(self.sis.catalogo.dettaglio("casa")["tassa_pp_notte_cents"], 200)

    def test_citta_senza_regola_tassa_zero(self):
        self._pubblica()                                    # nessuna tassa dichiarata
        q = self._quote()
        self.assertEqual(q["tassa_soggiorno_cents"], 0)     # mai inventare
        self.assertEqual(q["totale_cents"], q["prezzo_guest_cents"])

    def test_pagamento_addebita_il_totale_con_tassa(self):
        # il book riporta totale_cents (= soggiorno + tassa): e' quello che Stripe addebita
        self._pubblica(tassa_pp_notte_cents=200)
        _, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "casa",
                      "check_in": "2027-01-10", "check_out": "2027-01-12", "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "o@x.it"})
        self.assertEqual(b["totale_cents"], 20800)            # 20000 soggiorno + 800 tassa
        self.assertEqual(b["tassa_soggiorno_cents"], 800)

    def test_cancellazione_rimborsa_anche_la_tassa(self):
        self._pubblica(tassa_pp_notte_cents=200)              # flessibile (default) + tassa
        _, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "casa",
                      "check_in": "2027-01-10", "check_out": "2027-01-12", "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "o@x.it"})
        _, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        self.assertEqual(c["tassa_rimborsata_cents"], 800)    # tassa SEMPRE resa per intero
        self.assertEqual(c["rimborso_cents"], 20800)          # soggiorno pieno (flessibile) + tassa

    def test_cap_notti_tassabili(self):
        self._pubblica(tassa_pp_notte_cents=200, tassa_max_notti=1)   # max 1 notte
        q = self._quote(party=2)
        self.assertEqual(q["tassa_soggiorno_cents"], 400)   # 200*2persone*1notte (cap)

    def test_regola_tassa_di_default_zero(self):
        from fase66_tassa_soggiorno import REGOLA_ZERO
        self.assertIs(self.sis.catalogo.regola_tassa_di("inesistente"), REGOLA_ZERO)

    def test_like_for_like_valuta_dellannuncio(self):
        # l'host prezza in USD -> il preventivo (e l'addebito) e' in USD -> zero rischio cambio
        self._pubblica(valuta="USD")
        q = self._quote()
        self.assertEqual(q["valuta"], "USD")
        # annuncio EUR (default) -> preventivo EUR
        self.g("POST", "/api/host/pubblica", {"host_id": "demo", "slug": "casa2",
                "titolo": "C2", "citta": "Roma", "descrizione": "x", "prezzo_notte_cents": 9000,
                "capacita": 2, "servizi": [], "immagini": [], "valuta": "EUR"}, HK)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa2",
                "da": "2027-01-01", "a": "2027-01-31", "unita_totali": 1,
                "prezzo_netto_cents": 9000}, HK)
        _, q2 = self.g("POST", "/api/concierge/quote", {"alloggio_id": "casa2",
                       "check_in": "2027-01-10", "check_out": "2027-01-12", "party": 1})
        self.assertEqual(q2["valuta"], "EUR")


if __name__ == "__main__":
    unittest.main()
