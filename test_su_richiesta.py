"""Test prenotazione SU RICHIESTA (host approva): book->in_attesa_host (niente voucher/escrow),
host vede la richiesta, approva->finalizzata (voucher+escrow), rifiuta->stanza liberata.
Modalita 'immediata' (default) resta instant-book invariata. Cliente e host rispettati."""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

SEG = b"s" * 32
HK = {"X-Host-Key": "hk"}


class TestSuRichiesta(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db", db_messaggi=f"{d}/m.db",
            db_domanda=f"{d}/dom.db", db_garanzia=f"{d}/g.db", db_pendenti=f"{d}/p.db",
            db_tassa_comunale=f"{d}/tc.db", file_referral=f"{d}/ref.json", commissione_bps=1500))
        self.r = crea_router(self.sis, host_key="hk", base_url="https://bookinvip.com")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _pubblica(self, slug, modalita):
        self.g("POST", "/api/host/pubblica", {"host_id": "demo", "slug": slug, "titolo": "C",
               "citta": "Roma", "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
               "servizi": [], "immagini": [], "modalita_prenotazione": modalita}, HK)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": slug, "da": "2027-03-01",
               "a": "2027-03-31", "unita_totali": 1, "prezzo_netto_cents": 10000}, HK)

    def _book(self, slug):
        _, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": slug,
                      "check_in": "2027-03-10", "check_out": "2027-03-12", "party": 1})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "o@x.it"})
        return b

    def test_immediata_resta_instant_book(self):
        self._pubblica("casa", "immediata")
        b = self._book("casa")
        self.assertEqual(b["stato"], "confermata")
        self.assertTrue(b.get("voucher_token"))                # finalizzata subito

    def test_su_richiesta_va_in_attesa_host(self):
        self._pubblica("casa", "su_richiesta")
        b = self._book("casa")
        self.assertEqual(b["stato"], "in_attesa_host")         # NON confermata
        self.assertIsNone(b.get("voucher_token"))              # niente voucher finche' non approva
        self.assertEqual(self.sis.garanzia.stato(b["riferimento"]), None)  # niente escrow ancora
        # l'host la vede tra le richieste
        _, ric = self.g("GET", "/api/host/richieste", q={"host_id": "demo"}, h=HK)
        self.assertEqual(len(ric["richieste"]), 1)

    def test_host_approva_finalizza(self):
        self._pubblica("casa", "su_richiesta")
        b = self._book("casa")
        s, c = self.g("POST", "/api/host/richieste/approva", {"riferimento": b["riferimento"]}, HK)
        self.assertEqual(s, 200)
        self.assertEqual(c["stato"], "approvata")
        self.assertTrue(c["prenotazione"]["voucher_token"])    # ORA c'e' il voucher
        self.assertIsNotNone(self.sis.garanzia.stato(b["riferimento"]))   # escrow aperto ora

    def test_host_rifiuta_libera_la_stanza(self):
        self._pubblica("casa", "su_richiesta")
        b = self._book("casa")
        s, c = self.g("POST", "/api/host/richieste/rifiuta", {"riferimento": b["riferimento"]}, HK)
        self.assertEqual(s, 200)
        self.assertEqual(c["stato"], "rifiutata")
        # stanza di nuovo prenotabile
        _, q2 = self.g("POST", "/api/concierge/quote", {"alloggio_id": "casa",
                       "check_in": "2027-03-10", "check_out": "2027-03-12", "party": 1})
        _, b2 = self.g("POST", "/api/concierge/book",
                       {"quote_token": q2["quote_token"], "email": "due@x.it"})
        self.assertIn(b2["stato"], ("in_attesa_host", "confermata"))


if __name__ == "__main__":
    unittest.main()
