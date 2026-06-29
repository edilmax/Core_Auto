"""
Test E2E VARIANTI: il sistema vero sotto scenari avversariali e limite (come un cliente reale
che prenota, sbaglia, ritenta, manomette). Anti-overbooking atomico, token manomessi, date non
disponibili, prezzo per-fonte, recensioni false, cancellazione+riprenotazione, split di gruppo.
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

SEG = b"v" * 32
HK = {"X-Host-Key": "hk"}
AK = {"X-Admin-Key": "ak"}


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        d = cls.dir
        cls.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db",
            db_messaggi=f"{d}/m.db", file_referral=f"{d}/ref.json", commissione_bps=1500))
        cls.r = crea_router(cls.sis, host_key="hk", admin_key="ak",
                            base_url="https://bookinvip.com")
        cls.r.gestisci("POST", "/api/host/pubblica", {}, json.dumps({
            "host_id": "demo", "slug": "casa", "titolo": "Casa", "citta": "Roma",
            "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 4,
            "servizi": ["wifi"], "immagini": ["https://x/y.jpg"]}), HK)
        cls.r.gestisci("POST", "/api/host/disponibilita_range", {}, json.dumps({
            "alloggio_id": "casa", "da": "2026-07-01", "a": "2026-07-31",
            "unita_totali": 1, "prezzo_netto_cents": 10000}), HK)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def g(self, m, p, body=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {},
                               json.dumps(body) if body is not None else None, h or {})

    def quote(self, ci, co, fonte=None):
        b = {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2}
        if fonte:
            b["fonte"] = fonte
        s, c = self.g("POST", "/api/concierge/quote", b)
        return s, c

    def book(self, token, email="ospite@x.it"):
        return self.g("POST", "/api/concierge/book",
                      {"quote_token": token, "email": email})


class TestVarianti(_Base):
    def test_anti_overbooking_atomico(self):
        # due ospiti quotano le STESSE date (1 sola unità); solo uno può prenotare
        _, qa = self.quote("2026-07-10", "2026-07-12")
        _, qb = self.quote("2026-07-10", "2026-07-12")
        sa, _ = self.book(qa["quote_token"], "a@x.it")
        sb, cb = self.book(qb["quote_token"], "b@x.it")
        self.assertEqual(sa, 201)                      # primo ospite: prenotato
        self.assertEqual(sb, 409)                      # secondo: notte già venduta (no overbooking)

    def test_token_manomesso_rifiutato(self):
        _, q = self.quote("2026-07-13", "2026-07-14")
        s, c = self.book(q["quote_token"][:-3] + "abc")   # firma alterata
        self.assertEqual(s, 400)

    def test_data_non_disponibile(self):
        s, c = self.quote("2026-12-10", "2026-12-12")     # fuori dal periodo aperto
        self.assertIn(s, (409, 422))

    def test_prezzo_per_fonte_diretto_vs_marketplace(self):
        _, dm = self.quote("2026-07-15", "2026-07-17", fonte="marketplace")
        _, dd = self.quote("2026-07-15", "2026-07-17", fonte="diretto")
        self.assertEqual(dm["commissione_cents"], 3000)   # 15%
        self.assertEqual(dd["commissione_cents"], 1000)   # 5%
        self.assertEqual(dm["prezzo_guest_cents"], dd["prezzo_guest_cents"])  # ospite uguale (0% fee)

    def test_recensione_falsa_rifiutata(self):
        s, c = self.g("POST", "/api/recensioni",
                      {"token": "token.falso.xxx", "voto": 5, "testo": "fake"})
        self.assertNotIn(s, (200, 201))                   # senza diritto valido -> no

    def test_cancellazione_libera_e_riprenotabile(self):
        _, q = self.quote("2026-07-22", "2026-07-24")
        idem = q["quote_token"].split(".")[-1]
        sb, _ = self.book(q["quote_token"], "c@x.it")
        self.assertEqual(sb, 201)
        # admin rimborsa -> libera le date
        sr, _ = self.g("POST", "/api/admin/rimborso",
                       {"alloggio_id": "casa", "check_in": "2026-07-22",
                        "check_out": "2026-07-24", "idem_key": idem}, AK)
        self.assertEqual(sr, 200)
        # ora le date sono di nuovo prenotabili
        s2, q2 = self.quote("2026-07-22", "2026-07-24")
        self.assertEqual(s2, 200)
        self.assertEqual(self.book(q2["quote_token"], "d@x.it")[0], 201)

    def test_split_gruppo_conservazione(self):
        s, _ = self.g("POST", "/api/split/crea",
                      {"prenotazione_id": "P9", "alloggio_id": "casa",
                       "totale_cents": 10000, "partecipanti": ["a", "b", "c"]})
        self.assertIn(s, (200, 201))
        ss, cs = self.g("GET", "/api/split/stato", q={"conto_id": "P9"})
        if ss == 200 and isinstance(cs.get("quote"), dict):
            self.assertEqual(sum(cs["quote"].values()), 10000)   # conservazione esatta


if __name__ == "__main__":
    unittest.main()
