"""
CORE_AUTO - Fase 175: PROVIDER POI (punti d'interesse) da OpenStreetMap/Overpass, per-annuncio.

Arricchisce il CERVELLO SEO (fase171) con i fatti pubblici piu' preziosi: i luoghi notevoli
VICINI a un alloggio (attrazioni, stazioni, parchi, spiagge...) con la loro DISTANZA in metri
— fatti verificabili che gli answer-engine amano citare ("a 6 minuti a piedi dalla Stazione").

Come fase96 (Overpass) + fase166 (geocoder): `fetch` INIETTABILE (test deterministici senza
rete), cache SQLite con i "vuoti" cache-ati (una zona senza POI non ri-martella Overpass),
tutto BLINDATO (errore -> [] , mai eccezione). GATED: usato solo se il sistema lo cabla
(con_poi, default OFF nei test). Ritorna ESATTAMENTE il contratto che il cervello si aspetta:
lista di {nome, cat, lat_micro, lon_micro} con `cat` fra le categorie notevoli di fase171.

Coordinate in microgradi interi (mai float nel dominio). Overpass `around:` in metri.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("core_auto.poi_osm")

OVERPASS = "https://overpass-api.de/api/interpreter"
_UA = "BookinVIP/1.0 (+https://bookinvip.com)"
_RAGGIO_M = 1500
_MAX_POI = 12
_LAT_MAX, _LON_MAX = 90_000_000, 180_000_000

# tag OSM -> categoria notevole del cervello (fase171._POI_NOTABILI). Solo cio' che vale citare.
_MAPPA_CAT: Dict[Tuple[str, str], str] = {
    ("tourism", "attraction"): "attraction",
    ("tourism", "museum"): "museum",
    ("historic", "monument"): "monument",
    ("historic", "memorial"): "monument",
    ("natural", "beach"): "beach",
    ("leisure", "beach_resort"): "beach",
    ("leisure", "park"): "park",
    ("railway", "station"): "station",
    ("railway", "subway_entrance"): "subway",
    ("station", "subway"): "subway",
    ("amenity", "university"): "university",
    ("amenity", "hospital"): "hospital",
    ("leisure", "stadium"): "stadium",
}


def _categoria(tags: Dict[str, Any]) -> Optional[str]:
    if not isinstance(tags, dict):
        return None
    for (k, v), cat in _MAPPA_CAT.items():
        if str(tags.get(k, "")) == v:
            return cat
    return None


class ProviderPOI:
    """POI notevoli vicini a un punto. `fetch(url)->dati` iniettabile; None = rete reale."""

    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], *,
                 endpoint: str = OVERPASS,
                 fetch: Optional[Callable[[str], Any]] = None,
                 orologio: Optional[Callable[[], int]] = None,
                 raggio_m: int = _RAGGIO_M) -> None:
        self._cf = conn_factory
        self._endpoint = endpoint or OVERPASS
        self._fetch = fetch or self._fetch_reale
        self._now = orologio or (lambda: int(time.time()))
        self._raggio = raggio_m if isinstance(raggio_m, int) and raggio_m > 0 else _RAGGIO_M

    def _apri(self) -> sqlite3.Connection:
        con = self._cf()
        try:
            con.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass
        return con

    def inizializza_schema(self) -> None:
        con = self._apri()
        try:
            with con:
                con.execute("""CREATE TABLE IF NOT EXISTS poicache (
                    chiave TEXT PRIMARY KEY, poi_json TEXT NOT NULL, ts INTEGER NOT NULL)""")
        finally:
            con.close()

    def _chiave(self, lat_micro: int, lon_micro: int) -> str:
        # arrotonda a ~100m (3 decimali) per riusare la cache tra annunci nello stesso isolato
        return "%d:%d:%d" % (round(lat_micro, -3), round(lon_micro, -3), self._raggio)

    def vicini(self, dettaglio: Dict[str, Any]) -> List[Dict[str, Any]]:
        """POI notevoli vicini all'annuncio (dal suo lat/lon micro). [] se coords assenti o
        errore. Cache-first (vuoti inclusi). Il cervello poi filtra/ordina per distanza."""
        if not isinstance(dettaglio, dict):
            return []
        lat, lon = dettaglio.get("lat_micro"), dettaglio.get("lon_micro")
        if not (isinstance(lat, int) and not isinstance(lat, bool)
                and isinstance(lon, int) and not isinstance(lon, bool)):
            return []
        if abs(lat) > _LAT_MAX or abs(lon) > _LON_MAX:
            return []
        chiave = self._chiave(lat, lon)
        cache = self._da_cache(chiave)
        if cache is not None:
            return cache
        poi = self._interroga(lat, lon)
        self._salva_cache(chiave, poi)
        return poi

    def _da_cache(self, chiave: str) -> Optional[List[Dict[str, Any]]]:
        con = self._apri()
        try:
            r = con.execute("SELECT poi_json FROM poicache WHERE chiave=?",
                            (chiave,)).fetchone()
            if r is None:
                return None
            dati = json.loads(r[0])
            return dati if isinstance(dati, list) else []
        except Exception:
            return None
        finally:
            con.close()

    def _salva_cache(self, chiave: str, poi: List[Dict[str, Any]]) -> None:
        con = self._apri()
        try:
            with con:
                con.execute("INSERT OR REPLACE INTO poicache (chiave, poi_json, ts) "
                            "VALUES (?,?,?)",
                            (chiave, json.dumps(poi, ensure_ascii=False), self._now()))
        except Exception:
            logger.warning("poi: salvataggio cache fallito (ISOLATO)", exc_info=True)
        finally:
            con.close()

    def _query(self, lat_micro: int, lon_micro: int) -> str:
        lat = "%d.%06d" % (lat_micro // 1_000_000, abs(lat_micro) % 1_000_000)
        lon = "%d.%06d" % (lon_micro // 1_000_000, abs(lon_micro) % 1_000_000)
        intorno = "around:%d,%s,%s" % (self._raggio, lat, lon)
        filtri = "".join(
            'node(%s)[%s=%s][name];' % (intorno, k, v) for (k, v) in _MAPPA_CAT)
        return "[out:json][timeout:15];(%s);out center %d;" % (filtri, _MAX_POI * 3)

    def _interroga(self, lat_micro: int, lon_micro: int) -> List[Dict[str, Any]]:
        try:
            url = self._endpoint + "?" + urllib.parse.urlencode(
                {"data": self._query(lat_micro, lon_micro)})
            dati = self._fetch(url)
            elementi = dati.get("elements") if isinstance(dati, dict) else None
            if not isinstance(elementi, list):
                return []
            out: List[Dict[str, Any]] = []
            visti = set()
            for el in elementi:
                if not isinstance(el, dict):
                    continue
                tags = el.get("tags") or {}
                nome = tags.get("name")
                cat = _categoria(tags)
                lat = el.get("lat", (el.get("center") or {}).get("lat"))
                lon = el.get("lon", (el.get("center") or {}).get("lon"))
                if not (isinstance(nome, str) and nome and cat is not None
                        and isinstance(lat, (int, float)) and isinstance(lon, (int, float))):
                    continue
                lat_u = int(round(float(lat) * 1_000_000))
                lon_u = int(round(float(lon) * 1_000_000))
                if abs(lat_u) > _LAT_MAX or abs(lon_u) > _LON_MAX:
                    continue
                chiave = (nome, cat)
                if chiave in visti:
                    continue
                visti.add(chiave)
                out.append({"nome": nome, "cat": cat,
                            "lat_micro": lat_u, "lon_micro": lon_u})
                if len(out) >= _MAX_POI:
                    break
            return out
        except Exception:
            logger.warning("poi: interrogazione Overpass fallita (ISOLATA -> [])",
                           exc_info=True)
            return []

    @staticmethod
    def _fetch_reale(url: str) -> Any:  # pragma: no cover (rete)
        req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                                   "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8", "replace"))


def crea_provider_poi(percorso: str, *, fetch: Any = None,
                      endpoint: str = OVERPASS, orologio: Any = None,
                      raggio_m: int = _RAGGIO_M) -> ProviderPOI:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        p = ProviderPOI(lambda: _ConnCondivisa(con), fetch=fetch, endpoint=endpoint,
                        orologio=orologio, raggio_m=raggio_m)
    else:
        p = ProviderPOI(lambda: sqlite3.connect(percorso, timeout=30), fetch=fetch, endpoint=endpoint,
                        orologio=orologio, raggio_m=raggio_m)
    p.inizializza_schema()
    return p


class _ConnCondivisa:
    def __init__(self, con: sqlite3.Connection) -> None:
        object.__setattr__(self, "_con", con)

    def close(self) -> None:
        pass

    def __enter__(self):
        return self._con.__enter__()

    def __exit__(self, *a):
        return self._con.__exit__(*a)

    def __getattr__(self, n):
        return getattr(self._con, n)
