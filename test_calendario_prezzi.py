"""
Collaudo — attivazione fase119 (calendario prezzi host): per ogni giorno stato + prezzo base
+ prezzo dinamico suggerito (fase106). Endpoint host-auth con verifica proprietà.
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE


class TestCalendarioPrezzi(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{self.d}/c.db", db_inventario=f"{self.d}/i.db",
            db_registro_host=f"{self.d}/r.db", db_accettazioni=f"{self.d}/a.db"))
        self.r = crea_router(self.sys, host_key="hk")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@cp.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa", "titolo": "Casa", "citta": "Roma",
                "prezzo_notte_cents": 10000, "capacita": 2}, {"X-Host-Token": self.tok})
        for g in ("2026-09-01", "2026-09-02"):
            self.sys.inventario.imposta_disponibilita("casa", g, unita_totali=1,
                                                      prezzo_netto_cents=10000)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def test_calendario_prezzi(self):
        s, d = self.g("GET", "/api/host/calendario_prezzi", h={"X-Host-Token": self.tok},
                      q={"alloggio": "casa", "da": "2026-09-01", "a": "2026-09-04"})
        self.assertEqual(s, 200, d)
        celle = {c["giorno"]: c for c in d["celle"]}
        self.assertEqual(celle["2026-09-01"]["prezzo_cents"], 10000)
        self.assertIn("prezzo_dinamico_cents", celle["2026-09-01"])
        self.assertEqual(celle["2026-09-01"]["stato"], "libero")
        self.assertEqual(celle["2026-09-03"]["stato"], "non_aperto")   # non caricato

    def test_prenotato_e_chiuso_visibili(self):
        """Bug #33 (provato live): giorno PIENO appariva 'libero' (chiavi
        venduto/occupati inesistenti nella riga fase58) e CHIUSO era ignorato."""
        e = self.sys.inventario.blocca("casa", "2026-09-01", "2026-09-02",
                                       idem_key="t33")
        self.assertTrue(e.ok, e)
        self.sys.inventario.imposta_disponibilita(
            "casa", "2026-09-02", unita_totali=1, prezzo_netto_cents=10000,
            chiuso=True)
        s, d = self.g("GET", "/api/host/calendario_prezzi", h={"X-Host-Token": self.tok},
                      q={"alloggio": "casa", "da": "2026-09-01", "a": "2026-09-04"})
        self.assertEqual(s, 200, d)
        celle = {c["giorno"]: c for c in d["celle"]}
        self.assertEqual(celle["2026-09-01"]["stato"], "prenotato")
        self.assertEqual(celle["2026-09-02"]["stato"], "chiuso")

    def test_occupazione_reale_muove_il_dinamico(self):
        """Il fattore occupazione (fase106) ora usa l'occupazione REALE del range
        (prima era fisso a 5000 bps: non scattava mai)."""
        import fase106_dynamic_pricing as dyn
        e = self.sys.inventario.blocca("casa", "2026-09-01", "2026-09-03",
                                       idem_key="t-occ")           # 2/2 notti: 100%
        self.assertTrue(e.ok, e)
        s, d = self.g("GET", "/api/host/calendario_prezzi", h={"X-Host-Token": self.tok},
                      q={"alloggio": "casa", "da": "2026-09-01", "a": "2026-09-04"})
        self.assertEqual(s, 200, d)
        celle = {c["giorno"]: c for c in d["celle"]}
        atteso = dyn.calcola_prezzo(10000, occupazione_bps=10000,
                                    data="2026-09-01")["prezzo_cents"]
        self.assertEqual(celle["2026-09-01"]["prezzo_dinamico_cents"], atteso)

    def test_stato_range_equivale_a_stato_giorno(self):
        """La vincitrice del benchmark (query unica) deve restituire ESATTAMENTE
        le stesse righe del percorso per-giorno."""
        inv = self.sys.inventario
        per_range = inv.stato_range("casa", "2026-09-01", "2026-09-04")
        for g in ("2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"):
            self.assertEqual(per_range.get(g), inv.stato_giorno("casa", g))
        self.assertEqual(inv.stato_range("casa", "js;drop", "2026-09-04"), {})

    def test_auth_proprieta_date(self):
        s, _ = self.g("GET", "/api/host/calendario_prezzi",
                      q={"alloggio": "casa", "da": "2026-09-01", "a": "2026-09-04"})
        self.assertEqual(s, 401)                                        # senza auth
        s, _ = self.g("GET", "/api/host/calendario_prezzi", h={"X-Host-Token": self.tok},
                      q={"alloggio": "casa"})
        self.assertEqual(s, 422)                                        # date mancanti
        altro = self.g("POST", "/api/host/registrazione",
                       {"email": "h2@cp.it", "password": "password1", "accetta_termini": True,
                        "accetta_clausole": True, "doc_sha256": doc_sha256(),
                        "versione": CONTRATTO_HOST_VERSIONE})[1]["token"]
        s, _ = self.g("GET", "/api/host/calendario_prezzi", h={"X-Host-Token": altro},
                      q={"alloggio": "casa", "da": "2026-09-01", "a": "2026-09-04"})
        self.assertEqual(s, 403)                                        # non è tuo


if __name__ == "__main__":
    unittest.main(verbosity=2)
