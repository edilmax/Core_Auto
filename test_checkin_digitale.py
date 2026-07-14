"""
Collaudo — attivazione fase127 (check-in digitale). L'ospite pre-registra gli ospiti dal suo
voucher PRIMA dell'arrivo; verifica capacità/formato; completato -> sblocco abilitato.
Endpoint POST /api/checkin/pre_registra + GET /api/checkin/stato (via voucher firmato).
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router


class TestCheckinDigitale(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32,
            db_catalogo=f"{self.d}/c.db", db_inventario=f"{self.d}/i.db",
            db_checkin=f"{self.d}/ck.db"))
        self.assertIsNotNone(self.sys.checkin, "checkin deve essere attivo (smartpass on)")
        self.r = crea_router(self.sys)
        from fase57_vetrina import SchedaAlloggio
        self.sys.catalogo.pubblica(SchedaAlloggio(
            host_id="h1", slug="casa", titolo="Casa", citta="Roma",
            prezzo_notte_cents=10000, capacita=4))
        for g in ("2026-09-01", "2026-09-02"):
            self.sys.inventario.imposta_disponibilita("casa", g, unita_totali=1,
                                                      prezzo_netto_cents=10000)
        self.voucher = self._prenota()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def g(self, m, p, b=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, {})

    def _prenota(self):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": "2026-09-01",
                       "check_out": "2026-09-02", "party": 2})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "g@x.it"})
        self.assertEqual(s, 201, b)
        self.assertTrue(b.get("voucher_token"), "serve il voucher per il check-in")
        return b["voucher_token"]

    def test_pre_registra_e_stato(self):
        s, st = self.g("GET", "/api/checkin/stato", q={"voucher_token": self.voucher})
        self.assertEqual(s, 200, st)
        self.assertFalse(st["completato"])                  # prima: non completato
        s, out = self.g("POST", "/api/checkin/pre_registra",
                        {"voucher_token": self.voucher,
                         "ospiti": [{"nome": "Mario Rossi", "documento": "AB1234567"},
                                    {"nome": "Lucia Bianchi", "documento": "CD7654321"}]})
        self.assertEqual(s, 200, out)
        self.assertTrue(out.get("ok"))
        s, st2 = self.g("GET", "/api/checkin/stato", q={"voucher_token": self.voucher})
        self.assertTrue(st2["completato"])                  # dopo: completato -> sblocco abilitato

    def test_troppi_ospiti_rifiutati(self):
        s, out = self.g("POST", "/api/checkin/pre_registra",
                        {"voucher_token": self.voucher,
                         "ospiti": [{"nome": "A B", "documento": "X1"},
                                    {"nome": "C D", "documento": "X2"},
                                    {"nome": "E F", "documento": "X3"},
                                    {"nome": "G H", "documento": "X4"},
                                    {"nome": "I J", "documento": "X5"}]})  # 5 > capacità 4
        self.assertEqual(s, 422, out)
        self.assertFalse(out.get("ok"))

    def test_voucher_non_valido(self):
        s, _ = self.g("POST", "/api/checkin/pre_registra",
                      {"voucher_token": "falso.non.firmato",
                       "ospiti": [{"nome": "A B", "documento": "X1"}]})
        self.assertEqual(s, 400)
        s, _ = self.g("GET", "/api/checkin/stato", q={"voucher_token": "falso"})
        self.assertEqual(s, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
