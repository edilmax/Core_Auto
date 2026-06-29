"""Test endpoint cancellazione self-service ospite (fase111 cablata nel server): book ->
voucher -> cancella -> rimborso calcolato (cents) + date liberate -> riprenotabile. Edge:
voucher mancante/manomesso -> 400. Chiude un buco grave (prima solo l'admin rimborsava)."""
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
            "alloggio_id": "casa", "da": "2026-07-01", "a": "2026-07-31",
            "unita_totali": 1, "prezzo_netto_cents": 10000}, HK)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, body=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {},
                               json.dumps(body) if body is not None else None, h or {})

    def _book(self):
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": "2026-07-10",
                       "check_out": "2026-07-12", "party": 1})
        return self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "ospite@x.it"})

    def test_cancella_calcola_rimborso_e_libera(self):
        s, b = self._book()
        self.assertEqual(s, 201)
        sc, c = self.g("POST", "/api/concierge/cancella",
                       {"voucher_token": b["voucher_token"]})
        self.assertEqual(sc, 200)
        self.assertEqual(c["stato"], "cancellata")
        self.assertEqual(c["rimborso_cents"], 20000)        # >1 giorno -> flessibile 100%
        self.assertTrue(c["date_liberate"])
        # date liberate -> di nuovo prenotabili
        s2, q2 = self.g("POST", "/api/concierge/quote",
                        {"alloggio_id": "casa", "check_in": "2026-07-10",
                         "check_out": "2026-07-12", "party": 1})
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
        self.assertEqual(c["politica"], "flessibile")
        self.assertEqual(c["rimborso_cents"], 20000)        # piena, la richiesta non conta


if __name__ == "__main__":
    unittest.main()
