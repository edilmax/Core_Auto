"""Test Fase 121 - Geo-ricerca. Microgradi interi, deterministico."""
import unittest

from fase121_geo_ricerca import (MICRO, bbox, cerca_vicini, cluster_griglia, dentro_bbox,
                                 distanza_m, geojson)

ROMA = (41_902_782, 12_496_366)        # lat_u, lon_u
ALLOGGI = [
    {"slug": "centro", "lat_u": 41_900_000, "lon_u": 12_500_000, "prezzo_cents": 9000},
    {"slug": "vicino", "lat_u": 41_910_000, "lon_u": 12_490_000, "prezzo_cents": 8000},
    {"slug": "milano", "lat_u": 45_464_000, "lon_u": 9_190_000, "prezzo_cents": 7000},
]


class TestGeo(unittest.TestCase):
    def test_bbox_e_dentro(self):
        box = bbox(*ROMA, 5)
        self.assertTrue(dentro_bbox(41_900_000, 12_500_000, box))
        self.assertFalse(dentro_bbox(45_464_000, 9_190_000, box))   # Milano fuori

    def test_distanza(self):
        d = distanza_m(*ROMA, 41_910_000, 12_490_000)
        self.assertTrue(0 < d < 2000)                      # < 2 km
        self.assertEqual(distanza_m("x", 1, 2, 3), -1)

    def test_cerca_vicini_ordinato(self):
        r = cerca_vicini(ALLOGGI, *ROMA, 10)
        self.assertEqual([a["slug"] for a in r], ["centro", "vicino"])  # no milano
        self.assertLessEqual(r[0]["distanza_m"], r[1]["distanza_m"])

    def test_cerca_raggio_invalido(self):
        self.assertEqual(cerca_vicini(ALLOGGI, *ROMA, 0), [])

    def test_cluster(self):
        cl = cluster_griglia(ALLOGGI, passo_micro=1_000_000)
        # centro+vicino nella stessa cella (~41.9/12.5), milano in un'altra
        counts = sorted(c["count"] for c in cl)
        self.assertEqual(counts, [1, 2])

    def test_geojson(self):
        g = geojson(ALLOGGI[:1])
        self.assertEqual(g["type"], "FeatureCollection")
        lon, lat = g["features"][0]["geometry"]["coordinates"]
        self.assertAlmostEqual(lat, 41_900_000 / MICRO)
        self.assertAlmostEqual(lon, 12_500_000 / MICRO)

    def test_record_invalidi_ignorati(self):
        self.assertEqual(cerca_vicini([{"slug": "x"}, None], *ROMA, 10), [])
        self.assertEqual(geojson([{"slug": "x"}])["features"], [])


if __name__ == "__main__":
    unittest.main()
