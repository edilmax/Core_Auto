"""Test endpoint cancellazione self-service ospite (fase111 cablata nel server): book ->
voucher -> cancella -> rimborso calcolato (cents) + date liberate -> riprenotabile. Edge:
voucher mancante/manomesso -> 400. Chiude un buco grave (prima solo l'admin rimborsava).

Date RELATIVE a oggi (niente 'bombe a tempo'): l'arrivo è a +5 giorni, quindi l'annullamento
immediato ricade nel RIPENSAMENTO 48h -> rimborso 100% (copre California SB 644 e simili)."""
import datetime
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

SEG = b"q" * 32
HK = {"X-Host-Key": "hk"}


class TestCancellazioneGuest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        d = self.dir
        oggi = datetime.date.today()
        self.ci = (oggi + datetime.timedelta(days=5)).isoformat()    # arrivo +5gg -> ripensamento
        self.co = (oggi + datetime.timedelta(days=7)).isoformat()    # 2 notti
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db",
            db_messaggi=f"{d}/m.db", file_referral=f"{d}/ref.json", commissione_bps=1500))
        self.r = crea_router(self.sis, host_key="hk", base_url="https://bookinvip.com")
        self.g("POST", "/api/host/pubblica", {
            "host_id": "demo", "slug": "casa", "titolo": "Casa", "citta": "Roma",
            "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
            "servizi": [], "immagini": []}, HK)
        self.g("POST", "/api/host/disponibilita_range", {
            "alloggio_id": "casa", "da": oggi.isoformat(),
            "a": (oggi + datetime.timedelta(days=40)).isoformat(),
            "unita_totali": 1, "prezzo_netto_cents": 10000}, HK)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, body=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {},
                               json.dumps(body) if body is not None else None, h or {})

    def _book(self):
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": self.ci,
                       "check_out": self.co, "party": 1})
        return self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "ospite@x.it"})

    def test_cancella_ripensamento_100_e_libera(self):
        s, b = self._book()
        self.assertEqual(s, 201)
        sc, c = self.g("POST", "/api/concierge/cancella",
                       {"voucher_token": b["voucher_token"]})
        self.assertEqual(sc, 200)
        self.assertEqual(c["stato"], "cancellata")
        self.assertTrue(c["ripensamento"])                  # entro 48h dall'acquisto -> 100%
        self.assertEqual(c["rimborso_cents"], 20000)        # rimborso PIENO (2 notti x 10000)
        self.assertEqual(c["trattenuto_cents"], 0)
        self.assertTrue(c["date_liberate"])
        # date liberate -> di nuovo prenotabili
        s2, q2 = self.g("POST", "/api/concierge/quote",
                        {"alloggio_id": "casa", "check_in": self.ci,
                         "check_out": self.co, "party": 1})
        self.assertEqual(s2, 200)
        self.assertEqual(self.g("POST", "/api/concierge/book",
                                {"quote_token": q2["quote_token"], "email": "due@x.it"})[0], 201)

    def test_voucher_mancante_o_manomesso(self):
        self.assertEqual(self.g("POST", "/api/concierge/cancella", {})[0], 400)
        s, b = self._book()
        self.assertEqual(self.g("POST", "/api/concierge/cancella",
                                {"voucher_token": b["voucher_token"][:-3] + "xxx"})[0], 400)

    def test_politica_dal_voucher_non_dalla_richiesta(self):
        # ANTI-FURBATA: l'alloggio e' flessibile (default); l'ospite passa 'rigida' nella
        # richiesta -> IGNORATA, vince la politica dell'host bloccata nel voucher.
        s, b = self._book()
        sc, c = self.g("POST", "/api/concierge/cancella",
                       {"voucher_token": b["voucher_token"], "politica": "rigida"})
        self.assertEqual(sc, 200)
        self.assertEqual(c["politica"], "flessibile")       # NON la 'rigida' passata dall'ospite
        self.assertEqual(c["rimborso_cents"], 20000)        # ripensamento 48h -> pieno


if __name__ == "__main__":
    unittest.main()
