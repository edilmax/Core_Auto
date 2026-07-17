"""Test Fase 175 - Provider POI OSM. fetch INIETTABILE (no rete), cache, blindatura,
contratto verso il cervello fase171 (categorie notevoli), integrazione col motore fase173."""
import json
import unittest

from fase171_cervello_seo import _POI_NOTABILI, valuta_annuncio
from fase175_poi_osm import ProviderPOI, crea_provider_poi

LAT, LON = 41_900_000, 12_500_000


def _overpass_finto(elements):
    return lambda url: {"elements": elements}


_EL = [
    {"lat": 41.9005, "lon": 12.5005, "tags": {"name": "Colosseo", "tourism": "attraction"}},
    {"lat": 41.8996, "lon": 12.4997, "tags": {"name": "Stazione Termini", "railway": "station"}},
    {"lat": 41.9010, "lon": 12.4990, "tags": {"name": "Villa Borghese", "leisure": "park"}},
    {"tags": {"name": "Senza coordinate", "tourism": "museum"}},              # scartato
    {"lat": 41.9, "lon": 12.5, "tags": {"amenity": "cafe", "name": "Bar"}},   # non notevole
    {"lat": 41.9, "lon": 12.5, "tags": {"tourism": "attraction"}},            # senza nome
]


class TestProviderPOI(unittest.TestCase):
    def _prov(self, elements):
        return crea_provider_poi(":memory:", fetch=_overpass_finto(elements))

    def test_estrae_solo_notevoli_con_nome_e_coord(self):
        poi = self._prov(_EL).vicini({"lat_micro": LAT, "lon_micro": LON})
        nomi = {p["nome"] for p in poi}
        self.assertEqual(nomi, {"Colosseo", "Stazione Termini", "Villa Borghese"})
        for p in poi:
            self.assertIn(p["cat"], _POI_NOTABILI)      # contratto col cervello
            self.assertIsInstance(p["lat_micro"], int)
            self.assertIsInstance(p["lon_micro"], int)

    def test_senza_coordinate_lista_vuota(self):
        self.assertEqual(self._prov(_EL).vicini({}), [])
        self.assertEqual(self._prov(_EL).vicini({"lat_micro": LAT}), [])
        self.assertEqual(self._prov(_EL).vicini({"lat_micro": 1.5, "lon_micro": LON}), [])

    def test_cache_evita_seconda_chiamata(self):
        chiamate = []

        def conta(url):
            chiamate.append(url)
            return {"elements": _EL}

        p = crea_provider_poi(":memory:", fetch=conta)
        d = {"lat_micro": LAT, "lon_micro": LON}
        p.vicini(d)
        p.vicini(d)
        self.assertEqual(len(chiamate), 1, "la cache deve evitare la seconda Overpass")

    def test_zona_vuota_cache_ata(self):
        chiamate = []

        def vuoto(url):
            chiamate.append(url)
            return {"elements": []}

        p = crea_provider_poi(":memory:", fetch=vuoto)
        d = {"lat_micro": 0, "lon_micro": 0}
        self.assertEqual(p.vicini(d), [])
        self.assertEqual(p.vicini(d), [])
        self.assertEqual(len(chiamate), 1, "anche i 'vuoti' vanno cache-ati")

    def test_blindato_fetch_esplode(self):
        def boom(url):
            raise RuntimeError("overpass giu'")

        p = crea_provider_poi(":memory:", fetch=boom)
        self.assertEqual(p.vicini({"lat_micro": LAT, "lon_micro": LON}), [])

    def test_blindato_risposta_malformata(self):
        for cattivo in (None, "x", {"elements": "no"}, {"nope": 1}, {"elements": [1, "x"]}):
            p = crea_provider_poi(":memory:", fetch=lambda url, c=cattivo: c)
            self.assertEqual(p.vicini({"lat_micro": LAT, "lon_micro": LON}), [])

    def test_dedup_e_tetto(self):
        molti = [{"lat": 41.9 + i * 0.0001, "lon": 12.5,
                  "tags": {"name": "Museo %d" % i, "tourism": "museum"}}
                 for i in range(30)]
        molti += [{"lat": 41.9, "lon": 12.5,
                   "tags": {"name": "Museo 0", "tourism": "museum"}}]  # duplicato
        poi = self._prov(molti).vicini({"lat_micro": LAT, "lon_micro": LON})
        self.assertLessEqual(len(poi), 12)
        nomi = [p["nome"] for p in poi]
        self.assertEqual(len(nomi), len(set(nomi)))     # nessun duplicato

    def test_query_contiene_around_e_raggio(self):
        p = ProviderPOI(lambda: __import__("sqlite3").connect(":memory:"), raggio_m=800)
        q = p._query(LAT, LON)
        self.assertIn("around:800,41.900000,12.500000", q)
        self.assertIn("[name]", q)


class TestIntegrazioneCervello(unittest.TestCase):
    def test_poi_alzano_il_punteggio_e_sbloccano_query(self):
        prov = crea_provider_poi(":memory:", fetch=_overpass_finto(_EL))
        scheda = {"citta": "Roma", "prezzo_notte_cents": 11000, "capacita": 4,
                  "camere": 2, "bagni": 1, "servizi": ("wifi", "cucina"),
                  "lat_micro": LAT, "lon_micro": LON, "foto": 5,
                  "descrizione": "x" * 320}
        poi = prov.vicini(scheda)
        senza = valuta_annuncio(scheda, {}, None, ())
        con = valuta_annuncio(scheda, {"poi": poi}, None, ())
        self.assertGreater(con["punteggio"], senza["punteggio"])
        testi = " ".join(q["testo"] for q in con["query"])
        self.assertIn("Colosseo", testi)


if __name__ == "__main__":
    unittest.main(verbosity=2)
