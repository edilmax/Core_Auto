"""
Collaudo fix — il campo "Ospiti" filtra la ricerca (capacita_min). Prima il frontend non lo
inviava: un ospite che cercava per 4 vedeva anche alloggi per 2. Il backend già filtrava.
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase57_vetrina import SchedaAlloggio


class TestFiltroOspiti(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32,
            db_catalogo=f"{self.d}/c.db", db_inventario=f"{self.d}/i.db"))
        self.r = crea_router(self.sys)
        for slug, cap in (("piccolo", 2), ("grande", 6)):
            self.sys.catalogo.pubblica(SchedaAlloggio(
                host_id="h1", slug=slug, titolo=slug, citta="Roma",
                prezzo_notte_cents=10000, capacita=cap))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _slugs(self, **q):
        s, res = self.r.gestisci("GET", "/api/catalogo", q, None, {})
        self.assertEqual(s, 200, res)
        return {c["slug"] for c in res["risultati"]}

    def test_capacita_min_filtra(self):
        self.assertEqual(self._slugs(citta="Roma"), {"piccolo", "grande"})    # senza filtro
        self.assertEqual(self._slugs(citta="Roma", capacita_min="4"), {"grande"})  # 4 ospiti
        self.assertEqual(self._slugs(citta="Roma", capacita_min="2"), {"piccolo", "grande"})
        self.assertEqual(self._slugs(citta="Roma", capacita_min="8"), set())  # nessuno abbastanza grande


if __name__ == "__main__":
    unittest.main(verbosity=2)
