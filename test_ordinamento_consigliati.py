"""
Collaudo LOOP 4 — ordinamento "consigliati" (i migliori annunci in cima, come i colossi).
Default quando l'ospite non chiede un ordine esplicito. Punteggio PURO/deterministico su
segnali già disponibili (foto, recensioni, cancellazione gratuita, servizi). Ordine esplicito
(recente/prezzo) NON viene riordinato.
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, _punteggio_consigliato
from fase57_vetrina import Immagine, SchedaAlloggio


class TestPunteggio(unittest.TestCase):
    def test_foto_e_recensioni_pesano(self):
        ricco = {"thumbnail": "x.jpg", "cancellazione_gratuita": True,
                 "servizi": ["wifi", "aria"], "recensioni": {"conteggio": 8, "media_centesimi": 460}}
        povero = {"thumbnail": None, "cancellazione_gratuita": False, "servizi": []}
        self.assertGreater(_punteggio_consigliato(ricco), _punteggio_consigliato(povero))
        self.assertEqual(_punteggio_consigliato(povero), 0)
        self.assertEqual(_punteggio_consigliato({}), 0)     # robusto
        self.assertEqual(_punteggio_consigliato("x"), 0)

    def test_cap_e_monotonia(self):
        molte = {"recensioni": {"conteggio": 100, "media_centesimi": 500}}
        self.assertEqual(_punteggio_consigliato(molte), 30 + 25)   # cap 30 + voto 25
        solo_foto = {"thumbnail": "a"}
        self.assertEqual(_punteggio_consigliato(solo_foto), 40)


class TestOrdinamentoEndpoint(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32,
            db_catalogo=f"{self.d}/c.db", db_inventario=f"{self.d}/i.db"))
        self.r = crea_router(self.sys)
        # 3 annunci a QUALITÀ diversa nella stessa città (pubblicati in quest'ordine)
        self._pub("povero", pol="rigida")                                   # niente foto/servizi
        self._pub("medio", pol="flessibile", serv=("wifi",))                # gratuita
        self._pub("ricco", pol="flessibile", serv=("wifi", "aria", "tv"),
                  img=["http://x/foto.jpg"])                                  # foto+servizi+gratuita

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _pub(self, slug, pol="flessibile", serv=(), img=None):
        self.sys.catalogo.pubblica(
            SchedaAlloggio(host_id="h1", slug=slug, titolo=slug, citta="Roma",
                           prezzo_notte_cents=10000, capacita=2,
                           politica_cancellazione=pol, servizi=tuple(serv)),
            [Immagine(u, i) for i, u in enumerate(img or [])])

    def _cerca(self, **q):
        s, res = self.r.gestisci("GET", "/api/catalogo", q, None, {})
        self.assertEqual(s, 200, res)
        return res

    def test_default_e_consigliati_il_migliore_in_cima(self):
        res = self._cerca(citta="Roma")
        self.assertEqual(res.get("ordine"), "consigliati")
        slugs = [c["slug"] for c in res["risultati"]]
        self.assertEqual(slugs[0], "ricco", "il migliore deve essere primo")
        self.assertLess(slugs.index("ricco"), slugs.index("povero"))
        self.assertLess(slugs.index("medio"), slugs.index("povero"))
        self.assertEqual(res["totale"], 3)

    def test_ordine_esplicito_non_riordinato(self):
        res = self._cerca(citta="Roma", ordine="recente")
        self.assertNotEqual(res.get("ordine"), "consigliati")
        # 'recente' = pubblicati per ultimi prima -> ricco (ultimo) primo, povero (primo) ultimo
        slugs = [c["slug"] for c in res["risultati"]]
        self.assertEqual(slugs[0], "ricco")
        self.assertEqual(slugs[-1], "povero")


if __name__ == "__main__":
    unittest.main(verbosity=2)
