"""
RBAC ISOLAMENTO IN SCRITTURA cross-host (gap del micro-stepping Flow 5).

L'isolamento host era provato SOLO in LETTURA (metriche/export/calendario, vedi
test_host_metriche_isolamento). Qui si prova che host A NON puo' MODIFICARE i dati di
host B: cambiare disponibilita'/prezzi (sabotaggio: prezzo a 1 cent) o — la piu' grave —
ELIMINARE l'annuncio altrui. La guardia `_verifica_proprieta` esiste su ogni scrittura:
questi test la difendono (rossi se qualcuno la togliesse). Controllo positivo incluso:
A scrive il PROPRIO annuncio -> 200 (la guardia non blocca tutto = non compiacente).
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256


class TestRBACScritturaCrossHost(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db"))
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        self.tokA = self._host("a@rbac.it", "casa-a")
        self.tokB = self._host("b@rbac.it", "casa-b")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _host(self, email, slug):
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": email, "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        tok = c["token"]
        self.g("POST", "/api/host/pubblica",
               {"slug": slug, "titolo": slug, "citta": "Roma", "prezzo_notte_cents": 50000,
                "capacita": 4, "politica_cancellazione": "flessibile"}, {"X-Host-Token": tok})
        return tok

    def _range(self, slug, prezzo):
        return {"alloggio_id": slug, "da": "2026-09-01", "a": "2026-09-10",
                "unita_totali": 1, "prezzo_netto_cents": prezzo}

    # --- SCRITTURA calendario/prezzi altrui: VIETATA ---
    def test_A_non_cambia_disponibilita_di_B(self):
        # A prova a sabotare il prezzo di B mettendolo a 1 cent
        s, m = self.g("POST", "/api/host/disponibilita_range", self._range("casa-b", 1),
                      {"X-Host-Token": self.tokA})
        self.assertEqual(s, 403, "IDOR SCRITTURA: A ha cambiato calendario/prezzo di B! %s" % m)

    # --- ELIMINAZIONE annuncio altrui: VIETATA (la piu' grave) ---
    def test_A_non_elimina_annuncio_di_B(self):
        s, m = self.g("POST", "/api/host/alloggio_elimina",
                      {"alloggio_id": "casa-b", "slug": "casa-b"}, {"X-Host-Token": self.tokA})
        self.assertEqual(s, 403, "IDOR: A ha ELIMINATO l'annuncio di B! %s" % m)
        # ...e l'annuncio di B deve esistere ancora
        self.assertIsNotNone(self.sys.catalogo.host_di_alloggio("casa-b"),
                             "l'annuncio di B e' sparito nonostante il 403")

    # --- CONTROLLO POSITIVO (non-compiacenza): A scrive il PROPRIO -> ok ---
    def test_A_cambia_il_PROPRIO_ok(self):
        s, m = self.g("POST", "/api/host/disponibilita_range", self._range("casa-a", 60000),
                      {"X-Host-Token": self.tokA})
        self.assertEqual(s, 200, m)


if __name__ == "__main__":
    unittest.main()
