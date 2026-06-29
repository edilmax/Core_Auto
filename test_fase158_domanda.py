"""Test cold-start: domanda/waitlist (fase158) + Credito Fondatore riscattato nel concierge
con guardia floor (sconto finanziato dalla NOSTRA commissione, mai in perdita; host invariato).
"""
import json
import shutil
import tempfile
import unittest

from fase59_concierge import FirmaQuote
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase158_domanda import crea_gestore_domanda

SEG = b"d" * 32
HK = {"X-Host-Key": "hk"}


class TestDomandaModulo(unittest.TestCase):
    def setUp(self):
        self.d = crea_gestore_domanda(":memory:", firma=FirmaQuote(SEG))
        self.d.inizializza_schema()

    def test_registra_dedup_e_conta(self):
        self.assertTrue(self.d.registra("a@x.it", "Roma"))
        self.assertTrue(self.d.registra("a@x.it", "Roma"))      # dedup
        self.assertTrue(self.d.registra("b@x.it", "Roma"))
        self.assertTrue(self.d.registra("a@x.it", "Milano"))
        self.assertEqual(self.d.conta("Roma"), 2)
        self.assertEqual(self.d.conta(), 3)                     # 3 righe (a-Roma,b-Roma,a-Milano)
        self.assertEqual(self.d.per_citta()[0]["citta"], "roma")
        self.assertIn("a@x.it", self.d.email_citta("Roma"))

    def test_email_invalida_rifiutata(self):
        self.assertFalse(self.d.registra("non-email", "Roma"))
        self.assertFalse(self.d.registra("a@x.it", ""))

    def test_credito_token_firmato(self):
        tok = self.d.emette_credito_fondatore("a@x.it", "Roma")
        v = FirmaQuote(SEG).decodifica(tok)
        self.assertEqual(v["tipo"], "credito_fondatore")
        self.assertEqual(v["credito_cents"], 500)


class TestRiscattoNelConcierge(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db",
            db_messaggi=f"{d}/m.db", db_domanda=f"{d}/dom.db", file_referral=f"{d}/ref.json",
            commissione_bps=1500))
        self.r = crea_router(self.sis, host_key="hk", base_url="https://bookinvip.com")
        self.g("POST", "/api/host/pubblica", {
            "host_id": "demo", "slug": "casa", "titolo": "Casa", "citta": "Roma",
            "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
            "servizi": [], "immagini": []}, HK)
        self.g("POST", "/api/host/disponibilita_range", {
            "alloggio_id": "casa", "da": "2026-09-01", "a": "2026-09-30",
            "unita_totali": 1, "prezzo_netto_cents": 10000}, HK)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, body=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {},
                               json.dumps(body) if body is not None else None, h or {})

    def _credito(self):
        s, c = self.g("POST", "/api/domanda", {"email": "a@x.it", "citta": "Roma"})
        self.assertEqual(s, 201)
        return c["credito_token"]

    def test_credito_sconta_ospite_da_nostra_commissione(self):
        ct = self._credito()
        _, q = self.g("POST", "/api/concierge/quote", {
            "alloggio_id": "casa", "check_in": "2026-09-10", "check_out": "2026-09-12",
            "party": 1, "credito_token": ct})
        self.assertEqual(q["sconto_credito_cents"], 500)        # 5,00 applicati
        self.assertEqual(q["prezzo_guest_cents"], 19500)        # ospite paga -5
        self.assertEqual(q["netto_host_cents"], 17000)          # HOST INVARIATO (netto-15%)
        # la nostra presa = comm - sconto = 3000-500 = 2500 (> costi) -> nessuna perdita

    def test_floor_credito_non_applicato_se_niente_margine(self):
        # prenotazione piccola: la commissione non copre i costi -> sconto 0 (mai in perdita)
        self.g("POST", "/api/host/disponibilita_range", {
            "alloggio_id": "casa", "da": "2026-09-01", "a": "2026-09-30",
            "unita_totali": 1, "prezzo_netto_cents": 800})          # 8,00/notte
        ct = self._credito()
        _, q = self.g("POST", "/api/concierge/quote", {
            "alloggio_id": "casa", "check_in": "2026-09-20", "check_out": "2026-09-21",
            "party": 1, "fonte": "diretto", "credito_token": ct})
        self.assertEqual(q["sconto_credito_cents"], 0)          # protetti: niente sconto
        self.assertEqual(q["prezzo_guest_cents"], q["prezzo_netto_cents"])

    def test_conta_domanda_prova_sociale(self):
        self._credito()
        s, c = self.g("GET", "/api/domanda/conta", q={"citta": "Roma"})
        self.assertEqual(s, 200)
        self.assertEqual(c["richieste"], 1)


if __name__ == "__main__":
    unittest.main()
