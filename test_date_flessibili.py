"""
Collaudo LOOP 5 — date flessibili (± giorni, come i colossi). Se l'ospite attiva "date
flessibili", per ogni annuncio si cerca una finestra libera dello STESSO numero di notti
dentro [check_in-flex, check_out+flex] e si mostra quella. Backend puro/testabile.
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase57_vetrina import SchedaAlloggio


class TestDateFlessibili(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32,
            db_catalogo=f"{self.d}/c.db", db_inventario=f"{self.d}/i.db"))
        self.r = crea_router(self.sys)
        self.sys.catalogo.pubblica(SchedaAlloggio(
            host_id="h1", slug="casa", titolo="Casa", citta="Roma",
            prezzo_notte_cents=10000, capacita=2))
        # disponibile SOLO 5,6,7 settembre (non 3,4) -> finestra 2 notti = 5→7
        for g in ("2026-09-05", "2026-09-06", "2026-09-07"):
            self.sys.inventario.imposta_disponibilita("casa", g, unita_totali=1,
                                                      prezzo_netto_cents=10000)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _cerca(self, **q):
        s, res = self.r.gestisci("GET", "/api/catalogo", q, None, {})
        self.assertEqual(s, 200, res)
        return res

    def test_prima_finestra_unita(self):
        inv = self.sys.inventario
        self.assertEqual(inv.prima_finestra("casa", "2026-09-02", "2026-09-08", 2),
                         ("2026-09-05", "2026-09-07"))
        # nessuna finestra (giorni tutti chiusi)
        self.assertIsNone(inv.prima_finestra("casa", "2026-09-20", "2026-09-25", 2))
        # input blindato
        self.assertIsNone(inv.prima_finestra("casa", "x", "y", 2))
        self.assertIsNone(inv.prima_finestra("casa", "2026-09-02", "2026-09-08", 0))

    def test_flessibile_trova_finestra_vicina(self):
        # date esatte 3→5 NON disponibili; con flex ±3 trova 5→7
        res = self._cerca(citta="Roma", check_in="2026-09-03", check_out="2026-09-05",
                          flex_giorni="3")
        self.assertEqual(res.get("ordine"), "flessibile")
        self.assertEqual(res["totale"], 1)
        c = res["risultati"][0]
        self.assertEqual(c["finestra_ci"], "2026-09-05")
        self.assertEqual(c["finestra_co"], "2026-09-07")
        self.assertTrue(c["disponibile"])

    def test_senza_flex_date_esatte_non_disponibili(self):
        # stessa ricerca SENZA flex: 3→5 non disponibile -> l'annuncio risulta non prenotabile
        res = self._cerca(citta="Roma", check_in="2026-09-03", check_out="2026-09-05")
        self.assertNotEqual(res.get("ordine"), "flessibile")
        c = res["risultati"][0]
        self.assertFalse(c.get("disponibile"))
        self.assertNotIn("finestra_ci", c)

    def test_flex_ignorato_senza_date(self):
        # flex senza check_in/out -> ricerca normale (nessun crash, no finestra)
        res = self._cerca(citta="Roma", flex_giorni="3")
        self.assertNotEqual(res.get("ordine"), "flessibile")


if __name__ == "__main__":
    unittest.main(verbosity=2)
