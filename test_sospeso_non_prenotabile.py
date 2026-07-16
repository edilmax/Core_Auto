"""
COERENZA: un annuncio SOSPESO non dev'essere vendibile (bug provato 2026-07-16).

La sospensione (admin, per frode/reclami/sicurezza) nascondeva l'annuncio dalla ricerca
(catalogo fase57) ma il percorso di prenotazione controllava solo l'INVENTARIO (fase58) ->
l'annuncio restava quotabile e prenotabile con lo slug diretto. Fix: quota (e prenota, difesa
in profondita') rifiutano un annuncio non 'pubblicato' -> 404 alloggio_non_disponibile.
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256


class TestSospesoNonPrenotabile(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        d = self.dir
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db"))
        self.r = crea_router(self.sys, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@s.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.tok = c["token"]
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa", "titolo": "Casa", "citta": "Roma", "prezzo_notte_cents": 50000,
                "capacita": 4, "politica_cancellazione": "flessibile"}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa", "da": "2026-09-01", "a": "2026-09-30",
                "unita_totali": 1, "prezzo_netto_cents": 50000}, {"X-Host-Token": self.tok})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _quota(self):
        return self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": "2026-09-05",
                       "check_out": "2026-09-08", "party": 2})

    def test_pubblicato_prenotabile(self):
        s, q = self._quota()
        self.assertEqual(s, 200, q)                          # pubblicato -> quotabile
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@s.it"})
        self.assertEqual(s, 201, b)

    def test_sospeso_non_quotabile(self):
        s, _ = self.g("POST", "/api/admin/alloggio_stato",
                      {"slug": "casa", "stato": "sospeso"}, {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200)
        s, q = self._quota()
        self.assertEqual(s, 404, "REGRESSIONE: annuncio sospeso ancora quotabile")
        self.assertEqual(q.get("errore"), "alloggio_non_disponibile")

    def test_sospeso_dopo_quote_non_prenotabile(self):
        # difesa in profondita': quote ottenuto PRIMA della sospensione, book DOPO -> rifiutato
        s, q = self._quota()
        self.assertEqual(s, 200)
        self.g("POST", "/api/admin/alloggio_stato",
               {"slug": "casa", "stato": "sospeso"}, {"X-Admin-Key": "ak"})
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@s.it"})
        self.assertEqual(s, 404, "REGRESSIONE: book su annuncio sospeso (quote pre-sospensione)")

    def test_ripubblicato_torna_prenotabile(self):
        self.g("POST", "/api/admin/alloggio_stato",
               {"slug": "casa", "stato": "sospeso"}, {"X-Admin-Key": "ak"})
        self.g("POST", "/api/admin/alloggio_stato",
               {"slug": "casa", "stato": "pubblicato"}, {"X-Admin-Key": "ak"})
        s, q = self._quota()
        self.assertEqual(s, 200, "ripubblicato -> di nuovo quotabile")


if __name__ == "__main__":
    unittest.main(verbosity=2)
