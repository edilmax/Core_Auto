"""
Collaudo PIN TRASCINABILE — l'host fissa la posizione ESATTA trascinando il
segnaposto sulla mini-mappa del pannello (precisione al portone anche senza
scrivere l'indirizzo).

Regole blindate qui:
- pin_manuale + coordinate -> la scelta dell'host VINCE sulla geocodifica
  dell'indirizzo (anche alla ri-pubblicazione/modifica);
- guardia anti-disastro: pin a >100km dal centro della SUA città = errore
  (continente sbagliato/tocco involontario) -> pin scartato, geocodifica normale;
- pin senza coordinate = flag vuoto -> ignorato (geocodifica normale);
- senza geocoder il pin resta com'è (nessuna guardia possibile, parola all'host);
- migrazione: un DB vecchio SENZA la colonna pin_manuale la riceve da solo;
- endpoint /api/host/geocode: auth obbligatoria, centra la mini-mappa sui campi
  digitati PRIMA di salvare, isolato.
"""
import json
import shutil
import sqlite3
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE

CENTRO_ROMA = (41890000, 12490000)
GEO_INDIRIZZO = (41894560, 12482500)      # dove "cade" la geocodifica dell'indirizzo
PIN_BUONO = (41900000, 12490000)          # ~1.1 km dal centro: sensato
PIN_ASSURDO = (43000000, 12490000)        # ~123 km dal centro: errore evidente


class _GC:
    """Geocoder finto: centro-città fisso, indirizzo su un punto diverso."""
    def __init__(self):
        self.tutte = []

    def geocodifica(self, citta, indirizzo="", paese=""):
        self.tutte.append((citta, indirizzo, paese))
        return GEO_INDIRIZZO if indirizzo else CENTRO_ROMA


class TestPinManuale(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        d = self.dir
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/a.db"))
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@pin.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, metodo, path, body=None, headers=None, query=None):
        return self.r.gestisci(metodo, path, query or {},
                               json.dumps(body) if body is not None else None, headers or {})

    def _pubblica(self, slug, extra=None):
        b = {"slug": slug, "titolo": "Pin " + slug, "citta": "Roma",
             "prezzo_notte_cents": 9000, "capacita": 2}
        if extra:
            b.update(extra)
        return self.g("POST", "/api/host/pubblica", b, {"X-Host-Token": self.tok})

    def test_pin_vince_su_indirizzo(self):
        gc = _GC()
        self.sys.geocoder = gc
        s, r = self._pubblica("vince", {"indirizzo": "Via del Corso 12",
                                        "lat_micro": PIN_BUONO[0], "lon_micro": PIN_BUONO[1],
                                        "pin_manuale": True})
        self.assertEqual(s, 201, r)
        d = self.sys.catalogo.dettaglio_owner("vince")
        self.assertEqual((d["lat_micro"], d["lon_micro"]), PIN_BUONO,
                         "il pin dell'host deve vincere sulla geocodifica dell'indirizzo")
        self.assertTrue(d["pin_manuale"])
        self.assertNotIn("Via del Corso 12", [c[1] for c in gc.tutte],
                         "con pin valido l'indirizzo NON va geocodificato")

    def test_pin_sopravvive_alla_modifica(self):
        self.sys.geocoder = _GC()
        self._pubblica("mod", {"indirizzo": "Via del Corso 12",
                               "lat_micro": PIN_BUONO[0], "lon_micro": PIN_BUONO[1],
                               "pin_manuale": True})
        # modifica (il form rimanda pin_manuale + coordinate + indirizzo invariati)
        s, r = self._pubblica("mod", {"titolo": "Titolo nuovo",
                                      "indirizzo": "Via del Corso 12",
                                      "lat_micro": PIN_BUONO[0], "lon_micro": PIN_BUONO[1],
                                      "pin_manuale": True})
        self.assertEqual(s, 201, r)
        d = self.sys.catalogo.dettaglio_owner("mod")
        self.assertEqual((d["lat_micro"], d["lon_micro"]), PIN_BUONO,
                         "la modifica non deve degradare il pin all'indirizzo geocodificato")
        self.assertTrue(d["pin_manuale"])

    def test_pin_assurdo_ripiega_su_geocodifica(self):
        self.sys.geocoder = _GC()
        s, r = self._pubblica("assurdo", {"indirizzo": "Via del Corso 12",
                                          "lat_micro": PIN_ASSURDO[0],
                                          "lon_micro": PIN_ASSURDO[1],
                                          "pin_manuale": True})
        self.assertEqual(s, 201, r)
        d = self.sys.catalogo.dettaglio_owner("assurdo")
        self.assertEqual((d["lat_micro"], d["lon_micro"]), GEO_INDIRIZZO,
                         "pin a >100km dal centro = errore -> geocodifica dall'indirizzo")
        self.assertFalse(d["pin_manuale"])

    def test_pin_senza_coordinate_ignorato(self):
        self.sys.geocoder = _GC()
        s, r = self._pubblica("vuoto", {"indirizzo": "Via del Corso 12",
                                        "pin_manuale": True})
        self.assertEqual(s, 201, r)
        d = self.sys.catalogo.dettaglio_owner("vuoto")
        self.assertEqual((d["lat_micro"], d["lon_micro"]), GEO_INDIRIZZO)
        self.assertFalse(d["pin_manuale"], "flag senza coordinate non vale")

    def test_senza_geocoder_pin_resta(self):
        self.assertIsNone(self.sys.geocoder)
        s, r = self._pubblica("nogc", {"lat_micro": PIN_BUONO[0], "lon_micro": PIN_BUONO[1],
                                       "pin_manuale": True})
        self.assertEqual(s, 201, r)
        d = self.sys.catalogo.dettaglio_owner("nogc")
        self.assertEqual((d["lat_micro"], d["lon_micro"]), PIN_BUONO)
        self.assertTrue(d["pin_manuale"])

    def test_pin_e_privato_come_l_indirizzo(self):
        # il flag è un dettaglio del pannello host: MAI nelle viste pubbliche
        self.sys.geocoder = _GC()
        self._pubblica("priv", {"lat_micro": PIN_BUONO[0], "lon_micro": PIN_BUONO[1],
                                "pin_manuale": True})
        s, det = self.g("GET", "/api/catalogo/priv")
        self.assertEqual(s, 200, det)
        self.assertNotIn("pin_manuale", det)
        s, cat = self.g("GET", "/api/catalogo", query={"citta": "Roma"})
        for c in cat.get("risultati", []):
            self.assertNotIn("pin_manuale", c)

    # ── endpoint /api/host/geocode (centra la mini-mappa prima di salvare) ──
    def test_geocode_endpoint(self):
        self.sys.geocoder = _GC()
        s, r = self.g("GET", "/api/host/geocode", query={"citta": "Roma"})
        self.assertEqual(s, 401, "senza token: vietato")
        s, r = self.g("GET", "/api/host/geocode", headers={"X-Host-Token": self.tok},
                      query={})
        self.assertEqual(s, 422)
        s, r = self.g("GET", "/api/host/geocode", headers={"X-Host-Token": self.tok},
                      query={"citta": "Roma", "indirizzo": "Via del Corso 12"})
        self.assertEqual(s, 200, r)
        self.assertEqual((r["lat_micro"], r["lon_micro"]), GEO_INDIRIZZO)

    def test_geocode_endpoint_non_trovata_e_spento(self):
        class _Niente:
            def geocodifica(self, citta, indirizzo="", paese=""):
                return None
        self.sys.geocoder = _Niente()
        s, r = self.g("GET", "/api/host/geocode", headers={"X-Host-Token": self.tok},
                      query={"citta": "Cittainventata"})
        self.assertEqual(s, 404)
        self.sys.geocoder = None
        s, r = self.g("GET", "/api/host/geocode", headers={"X-Host-Token": self.tok},
                      query={"citta": "Roma"})
        self.assertEqual(s, 503)


class TestMigrazionePin(unittest.TestCase):
    def test_db_vecchio_riceve_la_colonna(self):
        # DB "di ieri": tabella alloggi SENZA pin_manuale -> inizializza_schema la aggiunge
        d = tempfile.mkdtemp()
        db = f"{d}/vecchio.db"
        con = sqlite3.connect(db)
        con.execute("""CREATE TABLE alloggi (
            id INTEGER PRIMARY KEY AUTOINCREMENT, host_id TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE, titolo TEXT NOT NULL,
            descrizione TEXT NOT NULL DEFAULT '', citta TEXT NOT NULL,
            paese TEXT NOT NULL DEFAULT '', indirizzo TEXT NOT NULL DEFAULT '',
            prezzo_notte_cents INTEGER NOT NULL, capacita INTEGER NOT NULL,
            camere INTEGER NOT NULL DEFAULT 1, bagni INTEGER NOT NULL DEFAULT 1,
            servizi_mask INTEGER NOT NULL DEFAULT 0, valuta TEXT NOT NULL DEFAULT 'EUR',
            stato TEXT NOT NULL DEFAULT 'pubblicato', lat_micro INTEGER, lon_micro INTEGER,
            politica_cancellazione TEXT NOT NULL DEFAULT 'flessibile',
            tassa_pp_notte_cents INTEGER NOT NULL DEFAULT 0,
            tassa_max_notti INTEGER NOT NULL DEFAULT 0,
            tassa_perc_bps INTEGER NOT NULL DEFAULT 0,
            sconto_settimana_bps INTEGER NOT NULL DEFAULT 0,
            sconto_mese_bps INTEGER NOT NULL DEFAULT 0,
            modalita_prenotazione TEXT NOT NULL DEFAULT 'immediata',
            creato_ts TEXT NOT NULL, aggiornato_ts TEXT NOT NULL)""")
        con.execute("INSERT INTO alloggi (host_id, slug, titolo, citta, "
                    "prezzo_notte_cents, capacita, creato_ts, aggiornato_ts) "
                    "VALUES ('h1','vecchio','Vecchio','Roma',9000,2,'2026-01-01','2026-01-01')")
        con.commit()
        con.close()
        from fase57_vetrina import crea_catalogo, SchedaAlloggio
        cat = crea_catalogo(db)
        dett = cat.dettaglio_owner("vecchio")
        self.assertFalse(dett["pin_manuale"], "annuncio pre-migrazione: pin False")
        cat.pubblica(SchedaAlloggio(host_id="h1", slug="vecchio", titolo="Vecchio",
                                    citta="Roma", prezzo_notte_cents=9000, capacita=2,
                                    lat_micro=PIN_BUONO[0], lon_micro=PIN_BUONO[1],
                                    pin_manuale=True))
        self.assertTrue(cat.dettaglio_owner("vecchio")["pin_manuale"])
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
