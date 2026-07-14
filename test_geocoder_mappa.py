"""
Collaudo LOOP 2 — mappa nella ricerca: geocoder (città->coordinate, gratis+cache) +
auto-geocodifica alla pubblicazione + endpoint /api/mappa (GeoJSON).

Blindato: geocoder non tocca la rete nei test (fetch iniettato); cache evita ri-chiamate
(anche i "non trovato"); rete giù -> None isolato; auto-geocode è best-effort (non blocca
mai la pubblicazione); /api/mappa mostra SOLO gli annunci con coordinate.
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE
from fase166_geocoder import crea_geocoder


class TestGeocoder(unittest.TestCase):
    def _gc(self, risposta, contatore=None):
        def fetch(url):
            if contatore is not None:
                contatore.append(url)
            if callable(risposta):
                return risposta(url)
            return risposta
        return crea_geocoder(":memory:", fetch=fetch)

    def test_geocodifica_ok_microgradi(self):
        g = self._gc([{"lat": "41.9027835", "lon": "12.4963655"}])
        self.assertEqual(g.geocodifica("Roma"), (41902784, 12496366))

    def test_cache_evita_seconda_chiamata(self):
        chiamate = []
        g = self._gc([{"lat": "48.8566", "lon": "2.3522"}], chiamate)
        a = g.geocodifica("Parigi")
        b = g.geocodifica("  parigi ")           # chiave normalizzata (case/spazi)
        self.assertEqual(a, b)
        self.assertEqual(len(chiamate), 1, "la cache doveva evitare la 2ª chiamata")

    def test_non_trovato_cache_ato(self):
        chiamate = []
        g = self._gc([], chiamate)               # Nominatim: nessun risultato
        self.assertIsNone(g.geocodifica("Cittainventata"))
        self.assertIsNone(g.geocodifica("Cittainventata"))
        self.assertEqual(len(chiamate), 1, "anche i 'non trovato' vanno cache-ati")

    def test_risposta_malformata_none(self):
        self.assertIsNone(self._gc([{"lat": "abc", "lon": "x"}]).geocodifica("X"))
        self.assertIsNone(self._gc("non-una-lista").geocodifica("Y"))
        self.assertIsNone(self._gc([{}]).geocodifica("Z"))

    def test_fuori_range_none(self):
        self.assertIsNone(self._gc([{"lat": "999", "lon": "12"}]).geocodifica("W"))

    def test_rete_giu_isolata(self):
        def esplode(url):
            raise RuntimeError("timeout")
        self.assertIsNone(self._gc(esplode).geocodifica("Roma"))

    def test_input_vuoto_none(self):
        self.assertIsNone(self._gc([{"lat": "1", "lon": "1"}]).geocodifica("", ""))


class _FakeGeocoder:
    def __init__(self, coord=(41902784, 12496366)):
        self.coord = coord
        self.chiamate = 0
        self.ultimo = None      # (citta, indirizzo, paese) dell'ultima chiamata

    def geocodifica(self, citta, indirizzo="", paese=""):
        self.chiamate += 1
        self.ultimo = (citta, indirizzo, paese)
        return self.coord


class TestAutoGeocodeEMappa(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        d = self.dir
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/a.db"))
        self.assertIsNone(self.sys.geocoder, "geocoder deve essere OFF di default (test)")
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@map.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, metodo, path, body=None, headers=None, query=None):
        return self.r.gestisci(metodo, path, query or {},
                               json.dumps(body) if body is not None else None, headers or {})

    def _pubblica(self, slug, titolo, citta="Roma", extra=None):
        b = {"slug": slug, "titolo": titolo, "citta": citta,
             "prezzo_notte_cents": 9000, "capacita": 2}
        if extra:
            b.update(extra)
        s, r = self.g("POST", "/api/host/pubblica", b, {"X-Host-Token": self.tok})
        self.assertEqual(s, 201, r)
        for gio in ("2026-09-01", "2026-09-02"):
            self.g("POST", "/api/host/disponibilita",
                   {"alloggio_id": slug, "giorno": gio, "unita_totali": 1,
                    "prezzo_netto_cents": 9000}, {"X-Host-Token": self.tok})

    def test_auto_geocode_alla_pubblicazione(self):
        fake = _FakeGeocoder((41902784, 12496366))
        self.sys.geocoder = fake                          # simulo il geocoder ON
        self._pubblica("casa-roma", "Casa Roma", "Roma")
        self.assertEqual(fake.chiamate, 1)
        d = self.sys.catalogo.dettaglio("casa-roma")
        self.assertEqual(d["lat_micro"], 41902784)
        self.assertEqual(d["lon_micro"], 12496366)

    def test_coordinate_esplicite_non_geocodifica(self):
        fake = _FakeGeocoder()
        self.sys.geocoder = fake
        self._pubblica("casa-gps", "Con GPS", "Roma",
                       extra={"lat_micro": 45464203, "lon_micro": 9189982})   # Milano
        self.assertEqual(fake.chiamate, 0, "coordinate già date -> niente geocoding")
        d = self.sys.catalogo.dettaglio("casa-gps")
        self.assertEqual(d["lat_micro"], 45464203)

    def test_senza_geocoder_pubblica_lo_stesso(self):
        self._pubblica("casa-nocoord", "Senza coord", "Roma")   # geocoder None
        d = self.sys.catalogo.dettaglio("casa-nocoord")
        self.assertIsNone(d["lat_micro"])                # pubblicato comunque, senza pin

    def test_mappa_geojson_solo_con_coordinate(self):
        self.sys.geocoder = _FakeGeocoder((41902784, 12496366))
        self._pubblica("con-1", "Con coord 1", "Roma")
        self._pubblica("con-2", "Con coord 2", "Roma")
        self.sys.geocoder = None                          # il terzo resta senza coordinate
        self._pubblica("senza", "Senza coord", "Roma")
        s, fc = self.g("GET", "/api/mappa", query={"citta": "Roma"})
        self.assertEqual(s, 200, fc)
        self.assertEqual(fc["type"], "FeatureCollection")
        self.assertEqual(fc["con_coordinate"], 2, "solo gli annunci geocodificati sulla mappa")
        slugs = {f["properties"]["slug"] for f in fc["features"]}
        self.assertEqual(slugs, {"con-1", "con-2"})
        f0 = fc["features"][0]
        self.assertEqual(f0["geometry"]["type"], "Point")
        lon, lat = f0["geometry"]["coordinates"]         # GeoJSON = [lon, lat]
        self.assertAlmostEqual(lat, 41.902784, places=5)
        self.assertAlmostEqual(lon, 12.496366, places=5)
        self.assertIn("titolo", f0["properties"])
        self.assertEqual(f0["properties"]["valuta"], "EUR")
        self.assertEqual(f0["properties"]["prezzo_cents"], 9000)

    def test_indirizzo_geocodifica_precisa(self):
        fake = _FakeGeocoder((41894560, 12482500))
        self.sys.geocoder = fake
        self._pubblica("con-via", "Con via", "Roma",
                       extra={"indirizzo": "Via del Corso 12"})
        self.assertEqual(fake.ultimo[1], "Via del Corso 12", "geocode deve usare l'indirizzo")
        d = self.sys.catalogo.dettaglio_owner("con-via")
        self.assertEqual(d["lat_micro"], 41894560)
        self.assertEqual(d["indirizzo"], "Via del Corso 12")   # privato, vista owner

    def test_indirizzo_e_privato(self):
        self.sys.geocoder = _FakeGeocoder((41894560, 12482500))
        self._pubblica("priv", "Privacy", "Roma", extra={"indirizzo": "Via Segreta 9"})
        # PUBBLICO (dettaglio + card di ricerca + mappa): niente indirizzo
        s, det = self.g("GET", "/api/catalogo/priv")
        self.assertEqual(s, 200, det)
        self.assertNotIn("indirizzo", det)
        s, cat = self.g("GET", "/api/catalogo", query={"citta": "Roma"})
        for c in cat.get("risultati", []):
            self.assertNotIn("indirizzo", c)
        s, fc = self.g("GET", "/api/mappa", query={"citta": "Roma"})
        for f in fc["features"]:
            self.assertNotIn("indirizzo", f["properties"])

    def test_modifica_senza_indirizzo_preserva_coordinate(self):
        # pubblico con coordinate esplicite (precise), poi "modifico" senza indirizzo ma
        # ripassando le coordinate -> NON deve degradare a centro-città (geocoder non chiamato)
        fake = _FakeGeocoder((45000000, 9000000))    # coord "sbagliate" se venisse chiamato
        self.sys.geocoder = fake
        self._pubblica("mod", "Mod", "Roma",
                       extra={"lat_micro": 41894560, "lon_micro": 12482500})
        self.assertEqual(fake.chiamate, 0)
        # ri-pubblico (edit) stesso slug con le coordinate, senza indirizzo
        s, _ = self.g("POST", "/api/host/pubblica",
                      {"slug": "mod", "titolo": "Mod 2", "citta": "Roma",
                       "prezzo_notte_cents": 9000, "capacita": 2,
                       "lat_micro": 41894560, "lon_micro": 12482500}, {"X-Host-Token": self.tok})
        self.assertEqual(s, 201)
        self.assertEqual(fake.chiamate, 0, "coord presenti + no indirizzo -> niente geocode")
        d = self.sys.catalogo.dettaglio_owner("mod")
        self.assertEqual(d["lat_micro"], 41894560)

    def test_mappa_filtra_per_citta(self):
        self.sys.geocoder = _FakeGeocoder((41902784, 12496366))
        self._pubblica("roma-1", "Roma 1", "Roma")
        self.sys.geocoder = _FakeGeocoder((45464203, 9189982))
        self._pubblica("milano-1", "Milano 1", "Milano")
        s, fc = self.g("GET", "/api/mappa", query={"citta": "Milano"})
        self.assertEqual(s, 200)
        slugs = {f["properties"]["slug"] for f in fc["features"]}
        self.assertEqual(slugs, {"milano-1"})


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestDistanzaCentro(unittest.TestCase):
    def test_distanza_centro_automatica(self):
        import json as _j
        d = tempfile.mkdtemp()
        sys_ = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=b"S" * 32,
                                          db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db"))
        r = crea_router(sys_)
        sys_.geocoder = _FakeGeocoder((41890000, 12490000))     # "centro Roma" finto
        from fase57_vetrina import SchedaAlloggio
        sys_.catalogo.pubblica(SchedaAlloggio(
            host_id="h1", slug="dist", titolo="Dist", citta="Roma",
            prezzo_notte_cents=9000, capacita=2,
            lat_micro=41900000, lon_micro=12490000))            # ~1.11 km a nord del centro
        s, det = r.gestisci("GET", "/api/catalogo/dist", {}, None, {})
        self.assertEqual(s, 200, det)
        self.assertAlmostEqual(det["centro_distanza_m"], 1113, delta=30)
        s, res = r.gestisci("GET", "/api/catalogo", {"citta": "Roma"}, None, {})
        card = res["risultati"][0]
        self.assertAlmostEqual(card["centro_distanza_m"], 1113, delta=30)
        # senza geocoder: campo assente, niente crash
        sys_.geocoder = None
        s, det2 = r.gestisci("GET", "/api/catalogo/dist", {}, None, {})
        self.assertNotIn("centro_distanza_m", det2)
        shutil.rmtree(d, ignore_errors=True)
