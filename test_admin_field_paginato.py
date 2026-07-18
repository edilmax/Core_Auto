"""Collaudo FIELD ADMIN PAGINATO (Incremento 2 "Bunker & Field").

Il pannello operativo non carica piu' liste infinite: il DATABASE filtra, conta e taglia
(WHERE + COUNT + LIMIT/OFFSET). Invarianti:
  1. 30 annunci, limit 20 -> pagina 1 ha ESATTAMENTE 20, pagine=2, totale=30; pagina 2 = 10;
  2. filtro host_id -> solo quell'host; filtro stato -> solo quello stato; filtro id -> 1;
  3. limit e' CAPPATO a 20 (un client che chiede 1000 non scarica la piattaforma);
  4. nessuna colonna di troppo (niente SELECT *): la riga porta SOLO i campi mostrati;
  5. auth: senza chiave admin -> 401.
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

HK = {"X-Host-Key": "hk"}
AK = {"X-Admin-Key": "ak"}
CAMPI = {"id", "host_id", "slug", "titolo", "citta", "prezzo_notte_cents", "valuta", "stato"}


class TestFieldPaginato(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"h" * 32, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak")
        # 25 annunci di hostA + 5 di hostB = 30
        for i in range(25):
            self._pub("hostA", "a%02d" % i, "Roma")
        for i in range(5):
            self._pub("hostB", "b%02d" % i, "Milano")
        # sospendi 3 di hostA
        for i in range(3):
            self.g("POST", "/api/admin/alloggio_stato", {"slug": "a%02d" % i,
                   "stato": "sospeso"}, AK)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _pub(self, host, slug, citta):
        self.g("POST", "/api/host/pubblica", {"host_id": host, "slug": slug, "titolo": slug.upper(),
               "citta": citta, "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
               "servizi": [], "immagini": [], "tassa_pp_notte_cents": 0}, HK)

    def _lista(self, **q):
        qq = {k: str(v) for k, v in q.items()}
        s, d = self.g("GET", "/api/admin/alloggi", None, AK, qq)
        self.assertEqual(s, 200, d)
        return d

    def test_paginazione_20(self):
        d = self._lista(page=1, limit=20)
        self.assertEqual(len(d["alloggi"]), 20, "pagina 1 = 20 record esatti")
        self.assertEqual(d["totale"], 30)
        self.assertEqual(d["pagine"], 2)
        self.assertEqual(d["page"], 1)
        d2 = self._lista(page=2, limit=20)
        self.assertEqual(len(d2["alloggi"]), 10, "pagina 2 = resto (10)")
        # nessun doppione tra le pagine
        ids = [a["id"] for a in d["alloggi"]] + [a["id"] for a in d2["alloggi"]]
        self.assertEqual(len(ids), len(set(ids)), "doppioni tra le pagine")

    def test_filtri(self):
        self.assertEqual(self._lista(host_id="hostB")["totale"], 5)
        self.assertTrue(all(a["host_id"] == "hostB"
                            for a in self._lista(host_id="hostB")["alloggi"]))
        self.assertEqual(self._lista(stato="sospeso")["totale"], 3)
        self.assertTrue(all(a["stato"] == "sospeso"
                            for a in self._lista(stato="sospeso")["alloggi"]))
        self.assertEqual(self._lista(stato="pubblicato")["totale"], 27)
        # filtro id -> 1 solo
        uno = self._lista(host_id="hostB")["alloggi"][0]
        d = self._lista(id=uno["id"])
        self.assertEqual(d["totale"], 1)
        self.assertEqual(d["alloggi"][0]["id"], uno["id"])
        # combinato host+stato
        self.assertEqual(self._lista(host_id="hostA", stato="sospeso")["totale"], 3)

    def test_limit_cappato_a_20(self):
        d = self._lista(page=1, limit=1000)
        self.assertLessEqual(len(d["alloggi"]), 20, "limit ostile -> max 20")
        self.assertEqual(d["limit"], 20)

    def test_niente_select_star(self):
        a = self._lista(page=1)["alloggi"][0]
        self.assertEqual(set(a.keys()), CAMPI, "colonne extra = SELECT * (vietato)")

    def test_auth(self):
        s, _ = self.g("GET", "/api/admin/alloggi", None, {})
        self.assertEqual(s, 401)


if __name__ == "__main__":
    unittest.main()
