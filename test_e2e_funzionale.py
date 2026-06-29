"""
Test E2E FUNZIONALE: simula l'intero flusso reale sul sistema vero (crea_sistema + router),
date di luglio. Verifica che OGNI funzione chiave lavori end-to-end, non solo i moduli isolati.
Prova del "tutto funziona dal vivo" ripetibile: python -m unittest test_e2e_funzionale
"""
import json
import os
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, pagina_voucher_html

SEG = b"e" * 32
HK = {"X-Host-Key": "hk"}
AK = {"X-Admin-Key": "ak"}
PUB = {"host_id": "demo", "slug": "casa-roma", "titolo": "Casa Roma", "citta": "Roma",
       "descrizione": "Bilocale centro", "prezzo_notte_cents": 10000, "capacita": 4,
       "servizi": ["wifi"], "immagini": ["https://x/y.jpg"]}


class TestE2EFunzionale(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        d = cls.dir
        cfg = ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db",
            db_messaggi=f"{d}/m.db", file_referral=f"{d}/ref.json",
            commissione_bps=1500, con_mcp=True)
        cls.sis = crea_sistema(cfg)
        cls.r = crea_router(cls.sis, host_key="hk", admin_key="ak",
                            base_url="https://bookinvip.com")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def g(self, metodo, path, body=None, headers=None, query=None):
        return self.r.gestisci(metodo, path, query or {},
                               json.dumps(body) if body is not None else None,
                               headers or {})

    def test_01_pubblica_e_disponibilita(self):
        s, _ = self.g("POST", "/api/host/pubblica", PUB, HK)
        self.assertIn(s, (200, 201))
        s, _ = self.g("POST", "/api/host/disponibilita_range",
                      {"alloggio_id": "casa-roma", "da": "2026-07-01", "a": "2026-07-31",
                       "unita_totali": 1, "prezzo_netto_cents": 10000}, HK)
        self.assertEqual(s, 200)

    def test_02_catalogo_trova_alloggio(self):
        s, c = self.g("GET", "/api/catalogo", query={"citta": "Roma"})
        self.assertEqual(s, 200)
        self.assertIn("casa-roma", json.dumps(c))

    def test_03_quote_marketplace_0pct_ospite(self):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa-roma", "check_in": "2026-07-10",
                       "check_out": "2026-07-12", "party": 2})
        self.assertEqual(s, 200)
        self.assertEqual(q["commissione_cents"], 3000)        # 15% su 20000
        self.assertEqual(q["prezzo_guest_cents"], 20000)      # ospite paga pulito (0% fee)
        self.assertEqual(q["netto_host_cents"], 17000)        # host = listino - commissione

    def test_04_quote_diretto_5pct(self):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa-roma", "check_in": "2026-07-20",
                       "check_out": "2026-07-22", "party": 2, "fonte": "diretto"})
        self.assertEqual(s, 200)
        self.assertEqual(q["commissione_cents"], 1000)        # 5% su 20000
        self.assertEqual(q["netto_host_cents"], 19000)

    def test_05_book_conferma_voucher_smartpass_recensione(self):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa-roma", "check_in": "2026-07-14",
                       "check_out": "2026-07-16", "party": 2})
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "ospite@x.it"})
        self.assertEqual(s, 201)                              # CREATED
        self.assertEqual(b["stato"], "confermata")
        self.assertTrue(b["voucher_token"])
        self.assertTrue(b["smart_pass"])
        self.assertTrue(b["diritto_recensione"])
        # la pagina voucher si genera dal token
        self.assertIsNotNone(pagina_voucher_html(self.sis, b["voucher_token"], "it"))
        # recensione verificata col diritto emesso
        sr, br = self.g("POST", "/api/recensioni",
                        {"token": b["diritto_recensione"], "voto": 5, "testo": "Ottimo"})
        self.assertIn(sr, (200, 201))

    def test_06_host_pannello(self):
        for p, q in (("/api/host/metriche", {}), ("/api/host/alloggi", {"host_id": "demo"}),
                     ("/api/host/export", {}),
                     ("/api/host/calendario", {"alloggio": "casa-roma", "da": "2026-07-01",
                                               "a": "2026-07-05"})):
            self.assertEqual(self.g("GET", p, headers=HK, query=q)[0], 200, p)

    def test_07_referral_link_assoluto(self):
        s, c = self.g("GET", "/api/host/referral", headers=HK, query={"host_id": "demo"})
        self.assertEqual(s, 200)
        self.assertTrue(c["link"].startswith("https://bookinvip.com/diventa-host.html?ref="))

    def test_08_messaggi_e_prezzo_dinamico(self):
        self.assertIn(self.g("POST", "/api/messaggi",
                      {"prenotazione_id": "X1", "guest_id": "g@x.it", "testo": "ciao"},
                      HK)[0], (200, 201))
        self.assertEqual(self.g("GET", "/api/messaggi", headers=HK,
                                query={"prenotazione_id": "X1"})[0], 200)
        s, c = self.g("GET", "/api/host/prezzo_suggerito", headers=HK,
                      query={"prezzo_base_cents": "10000", "occupazione_bps": "9000",
                             "data": "2026-08-08"})
        self.assertEqual(s, 200)
        self.assertGreater(c["prezzo_cents"], 10000)

    def test_09_admin_e_servizi(self):
        self.assertEqual(self.g("GET", "/api/admin/prenotazioni", headers=AK)[0], 200)
        self.assertEqual(self.g("GET", "/api/trasparenza",
                                query={"prezzo_cents": "10000"})[0], 200)
        self.assertEqual(self.g("GET", "/api/tassa",
                                query={"citta": "Roma", "ospiti": "2", "notti": "2"})[0], 200)
        self.assertEqual(self.g("POST", "/api/mcp",
                         {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[0], 200)

    def test_10_link_diretto_host_5pct(self):
        s, c = self.g("GET", "/api/host/link_diretto", headers=HK, query={"host_id": "demo"})
        self.assertEqual(s, 200)
        self.assertIn("?fonte=diretto", c["link_generale"])     # link generale -> 5%
        self.assertTrue(c["alloggi"])
        link = c["alloggi"][0]["link"]
        self.assertIn("fonte=diretto", link)
        self.assertIn("apri=casa-roma", link)                   # apre l'alloggio specifico
        self.assertEqual(c["commissione_bps"], 500)


if __name__ == "__main__":
    unittest.main()
