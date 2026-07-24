"""
COERENZA MIN-STAY ricerca↔book (gap micro-stepping Flow 1).

Prima: `disponibile()` (usato da ricerca/quote) IGNORAVA `min_notti`, mentre `blocca()` (il
book) lo imponeva -> un soggiorno sotto la soglia riceveva un PREVENTIVO, poi il book lo
rifiutava con 409 (preventivo fantasma). E per di piu' l'endpoint disponibilita_range NON
permetteva nemmeno di IMPOSTARE min_notti (restava sempre 1 = feature dormiente).

Ora: (1) l'host imposta `min_notti` col range; (2) `disponibile()` rispetta la stessa regola
di `blocca()` -> la quote rifiuta subito il soggiorno troppo corto. Rosso sul vecchio.
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256


class TestMinStayCoerente(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db"))
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@ms.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        self.tok = c["token"]
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa", "titolo": "Casa", "citta": "Roma", "prezzo_notte_cents": 10000,
                "capacita": 4, "politica_cancellazione": "flessibile"}, {"X-Host-Token": self.tok})
        s, m = self.g("POST", "/api/host/disponibilita_range",
                      {"alloggio_id": "casa", "da": "2026-09-01", "a": "2026-09-30",
                       "unita_totali": 1, "prezzo_netto_cents": 10000, "min_notti": 3},
                      {"X-Host-Token": self.tok})
        self.assertEqual(s, 200, ("range con min_notti=3 non accettato", m))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _quote(self, ci, co):
        return self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})

    # --- la QUOTE deve rifiutare il soggiorno troppo corto (coerente col book) ---
    def test_una_notte_sotto_il_minimo_NON_da_preventivo(self):
        s, q = self._quote("2026-09-05", "2026-09-06")     # 1 notte < min 3
        self.assertNotEqual(s, 200, ("preventivo FANTASMA: 1 notte con min_notti=3", q))

    def test_due_notti_sotto_il_minimo_NON_da_preventivo(self):
        s, q = self._quote("2026-09-05", "2026-09-07")     # 2 notti < min 3
        self.assertNotEqual(s, 200, ("preventivo FANTASMA: 2 notti con min_notti=3", q))

    def test_soggiorno_valido_ok(self):
        s, q = self._quote("2026-09-05", "2026-09-08")     # 3 notti == min
        self.assertEqual(s, 200, q)

    # --- disponibile() (motore ricerca) deve concordare con blocca() (book) ---
    def test_disponibile_concorda_col_book(self):
        inv = self.sys.inventario
        self.assertIsNot(inv.disponibile("casa", "2026-09-05", "2026-09-06"), True,
                         "disponibile() dice LIBERO su 1 notte < min: incoerente col book")
        self.assertIs(inv.disponibile("casa", "2026-09-05", "2026-09-08"), True,
                      "disponibile() nega un soggiorno valido di 3 notti")


if __name__ == "__main__":
    unittest.main()
