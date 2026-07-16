"""
ISOLAMENTO delle metriche host (bug provato 2026-07-16: data-leak/IDOR).

`/api/host/metriche` non verificava la proprieta' dello slug (un host leggeva le metriche di un
annuncio ALTRUI) e, senza slug, aggregava TUTTA la piattaforma (`inventario.metriche(None)` =
nessun WHERE -> ogni host vedeva l'incasso di tutti). Fix: slug specifico -> verifica proprieta'
(403 se non tuo); senza slug -> solo i PROPRI annunci.
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256


class TestHostMetricheIsolamento(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        d = self.dir
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db"))
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        self.tokA = self._host("a@iso.it", "casa-a")
        self.tokB = self._host("b@iso.it", "casa-b")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _host(self, email, slug):
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": email, "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        tok = c["token"]
        self.g("POST", "/api/host/pubblica",
               {"slug": slug, "titolo": slug, "citta": "Roma", "prezzo_notte_cents": 50000,
                "capacita": 4, "politica_cancellazione": "flessibile"}, {"X-Host-Token": tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": slug, "da": "2026-09-01", "a": "2026-09-30",
                "unita_totali": 1, "prezzo_netto_cents": 50000}, {"X-Host-Token": tok})
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": slug, "check_in": "2026-09-05", "check_out": "2026-09-08",
                       "party": 2})
        self.g("POST", "/api/concierge/book", {"quote_token": q["quote_token"], "email": "c@x.it"})
        return tok

    def _metriche(self, tok, slug=None):
        q = {"alloggio": slug} if slug else {}
        return self.g("GET", "/api/host/metriche", None, {"X-Host-Token": tok}, q=q)

    def test_proprio_annuncio_ok(self):
        s, m = self._metriche(self.tokA, "casa-a")
        self.assertEqual(s, 200, m)
        self.assertEqual(m["revenue_cents"], 150000)

    def test_annuncio_altrui_vietato(self):
        s, m = self._metriche(self.tokA, "casa-b")            # slug di B
        self.assertEqual(s, 403, "IDOR: un host non deve leggere le metriche di un annuncio altrui")
        self.assertEqual(m.get("errore"), "non_tuo")

    def test_senza_slug_solo_i_propri(self):
        s, m = self._metriche(self.tokA)                      # nessuno slug
        self.assertEqual(s, 200, m)
        self.assertEqual(m["revenue_cents"], 150000,
                         "LEAK: senza slug si vedeva l'incasso di TUTTA la piattaforma (300000)")

    # --- export CSV prenotazioni: stesso isolamento ---
    def test_export_annuncio_altrui_vietato(self):
        s, m = self.g("GET", "/api/host/export", None, {"X-Host-Token": self.tokA},
                      q={"alloggio": "casa-b"})
        self.assertEqual(s, 403, "IDOR: export delle prenotazioni di un annuncio altrui")

    def test_export_senza_slug_solo_i_propri(self):
        s, m = self.g("GET", "/api/host/export", None, {"X-Host-Token": self.tokA})
        self.assertEqual(s, 200, m)
        self.assertEqual(m["righe"], 1, "LEAK: senza slug si esportavano le prenotazioni di tutti")

    # --- calendario: stesso isolamento ---
    def test_calendario_annuncio_altrui_vietato(self):
        s, m = self.g("GET", "/api/host/calendario", None, {"X-Host-Token": self.tokA},
                      q={"alloggio": "casa-b", "da": "2026-09-01", "a": "2026-09-10"})
        self.assertEqual(s, 403, "IDOR: calendario di un annuncio altrui")

    def test_calendario_proprio_ok(self):
        s, m = self.g("GET", "/api/host/calendario", None, {"X-Host-Token": self.tokA},
                      q={"alloggio": "casa-a", "da": "2026-09-01", "a": "2026-09-10"})
        self.assertEqual(s, 200, m)


if __name__ == "__main__":
    unittest.main(verbosity=2)
