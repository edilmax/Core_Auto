"""
CORE_AUTO - Fase 166: Geocoder (indirizzo/città -> coordinate) per la mappa nella ricerca.

L'host inserisce solo la CITTÀ (e opzionalmente un indirizzo); la mappa ha bisogno di
coordinate. Questo modulo le ricava GRATIS da OpenStreetMap/Nominatim (nessuna chiave),
le salva in CACHE durevole (SQLite) — così non si ri-geocodifica e si rispetta il limite
di Nominatim (1 richiesta/sec, niente uso massivo) — e le restituisce in MICROGRADI INTERI
(coerente con fase57/fase121: mai float per la geo).

BLINDATO: non solleva MAI (errore/rete giù -> None); coordinate fuori range -> None;
`fetch` iniettabile (test deterministici senza rete); GATED implicito dalla cache (una
città geocodificata una volta resta). ISOLATO: usato best-effort alla pubblicazione, un
fallimento non blocca MAI la pubblicazione dell'annuncio.

VINCITRICE DEL BENCHMARK (4 modi di ottenere le coordinate):
  V3 'Nominatim gratis + cache SQLite + fetch iniettabile isolato'. Zero chiavi, zero costo,
  rispetta i limiti, testabile senza rete. Perdono: V1 'Google Geocoding' = chiave + costo;
  V2 'coordinate a mano dall'host' = errori/attrito (host non tecnico); V4 'geocodifica
  sincrona ad ogni ricerca' = rate-limit di Nominatim sfondato + lentezza.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional, Tuple

logger = logging.getLogger("core_auto.geocoder")

NOMINATIM = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"
# campi address di Nominatim che valgono come "quartiere", dal piu' specifico
_CAMPI_QUARTIERE = ("suburb", "neighbourhood", "quarter", "city_district", "borough", "village")
_QUARTIERE_MAX = 80
# Nominatim ESIGE un User-Agent identificativo con contatto (policy d'uso).
_UA = "BookinVIP/1.0 (+https://bookinvip.com; info@bookinvip.com)"
_LAT_MAX, _LON_MAX = 90_000_000, 180_000_000     # microgradi


def _conn_condivisa(con: sqlite3.Connection):
    class _C:
        def close(self):
            pass

        def __enter__(self):
            return con.__enter__()

        def __exit__(self, *a):
            return con.__exit__(*a)

        def __getattr__(self, n):
            return getattr(con, n)
    return _C()


class Geocoder:
    """`geocodifica(citta, indirizzo, paese) -> (lat_micro, lon_micro) | None`. Cache-first."""

    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], *,
                 fetch: Optional[Callable[[str], Any]] = None,
                 orologio: Optional[Callable[[], int]] = None) -> None:
        self._cf = conn_factory
        self._fetch = fetch or self._fetch_reale
        self._now = orologio or (lambda: int(time.time()))

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
                con.execute("""CREATE TABLE IF NOT EXISTS geocache (
                    chiave TEXT PRIMARY KEY,
                    lat_micro INTEGER, lon_micro INTEGER,
                    trovato INTEGER NOT NULL DEFAULT 0, ts INTEGER NOT NULL)""")
                # reverse-geocode: cella ~100m -> nome quartiere (vuoto = "non trovato" cache-ato)
                con.execute("""CREATE TABLE IF NOT EXISTS quartiere_cache (
                    chiave TEXT PRIMARY KEY,
                    quartiere TEXT NOT NULL DEFAULT '', ts INTEGER NOT NULL)""")
        finally:
            con.close()

    @staticmethod
    def _chiave(citta: str, indirizzo: str, paese: str) -> str:
        parti = [p.strip().lower() for p in (indirizzo, citta, paese) if p and p.strip()]
        return "|".join(" ".join(p.split()) for p in parti)

    def geocodifica(self, citta: Any, indirizzo: str = "",
                    paese: str = "") -> Optional[Tuple[int, int]]:
        """Coordinate (lat_micro, lon_micro) o None. Cache-first; negativo cache-ato per non
        ripetere chiamate inutili. Non solleva mai."""
        if not (isinstance(citta, str) and citta.strip()) and not (indirizzo and indirizzo.strip()):
            return None
        chiave = self._chiave(str(citta or ""), str(indirizzo or ""), str(paese or ""))
        if not chiave:
            return None
        # 1) cache (inclusi i "non trovato", per non martellare Nominatim)
        cache = self._da_cache(chiave)
        if cache is not None:
            trovato, lat, lon = cache
            return (lat, lon) if trovato else None
        # 2) rete (isolata)
        coord = self._interroga(chiave)
        self._salva_cache(chiave, coord)
        return coord

    def _da_cache(self, chiave: str) -> Optional[Tuple[int, Optional[int], Optional[int]]]:
        con = self._apri()
        try:
            r = con.execute("SELECT trovato, lat_micro, lon_micro FROM geocache WHERE chiave=?",
                            (chiave,)).fetchone()
            if r is None:
                return None
            return (int(r[0]), r[1], r[2])
        except Exception:
            return None
        finally:
            con.close()

    def _salva_cache(self, chiave: str, coord: Optional[Tuple[int, int]]) -> None:
        con = self._apri()
        try:
            with con:
                con.execute(
                    "INSERT OR REPLACE INTO geocache (chiave, lat_micro, lon_micro, trovato, ts) "
                    "VALUES (?,?,?,?,?)",
                    (chiave, coord[0] if coord else None, coord[1] if coord else None,
                     1 if coord else 0, self._now()))
        except Exception:
            logger.warning("geocoder: salvataggio cache fallito (ISOLATO)", exc_info=True)
        finally:
            con.close()

    def _interroga(self, chiave: str) -> Optional[Tuple[int, int]]:
        try:
            q = chiave.replace("|", ", ")
            url = NOMINATIM + "?" + urllib.parse.urlencode(
                {"q": q, "format": "json", "limit": "1"})
            dati = self._fetch(url)
            if not (isinstance(dati, list) and dati):
                return None
            primo = dati[0]
            lat = float(primo.get("lat"))
            lon = float(primo.get("lon"))
            lat_u = int(round(lat * 1_000_000))
            lon_u = int(round(lon * 1_000_000))
            if abs(lat_u) > _LAT_MAX or abs(lon_u) > _LON_MAX:
                return None
            return (lat_u, lon_u)
        except Exception:
            logger.warning("geocoder: interrogazione fallita (ISOLATA -> None)", exc_info=True)
            return None

    # ── QUARTIERE (reverse-geocode): coordinate -> nome del quartiere, cache-first ──

    def quartiere(self, lat_micro: Any, lon_micro: Any) -> Optional[str]:
        """Nome del quartiere dalle coordinate (microgradi interi), o None.
        Cache per cella ~100m (vale per tutti gli annunci dello stesso isolato,
        negativi inclusi: una zona senza quartiere non ri-martella Nominatim).
        Non solleva mai."""
        if not (isinstance(lat_micro, int) and isinstance(lon_micro, int)):
            return None
        if (lat_micro, lon_micro) == (0, 0):                 # "null island" = niente pin
            return None
        if abs(lat_micro) > _LAT_MAX or abs(lon_micro) > _LON_MAX:
            return None
        chiave = "%d|%d" % (lat_micro // 1000, lon_micro // 1000)
        cache = self._quartiere_da_cache(chiave)
        if cache is not None:
            return cache or None                             # '' cache-ato = non trovato
        nome = self._interroga_quartiere(lat_micro, lon_micro)
        self._salva_quartiere(chiave, nome)
        return nome

    def _quartiere_da_cache(self, chiave: str) -> Optional[str]:
        con = self._apri()
        try:
            r = con.execute("SELECT quartiere FROM quartiere_cache WHERE chiave=?",
                            (chiave,)).fetchone()
            return None if r is None else str(r[0])
        except Exception:
            return None
        finally:
            con.close()

    def _salva_quartiere(self, chiave: str, nome: Optional[str]) -> None:
        con = self._apri()
        try:
            with con:
                con.execute("INSERT OR REPLACE INTO quartiere_cache (chiave, quartiere, ts) "
                            "VALUES (?,?,?)", (chiave, nome or "", self._now()))
        except Exception:
            logger.warning("geocoder: salvataggio cache quartiere fallito (ISOLATO)",
                           exc_info=True)
        finally:
            con.close()

    @staticmethod
    def _gradi_str(micro: int) -> str:
        """Microgradi interi -> stringa decimale SENZA float (es. -1234567 -> '-1.234567')."""
        segno = "-" if micro < 0 else ""
        intero, resto = divmod(abs(micro), 1_000_000)
        return "%s%d.%06d" % (segno, intero, resto)

    def _interroga_quartiere(self, lat_micro: int, lon_micro: int) -> Optional[str]:
        try:
            url = NOMINATIM_REVERSE + "?" + urllib.parse.urlencode(
                {"lat": self._gradi_str(lat_micro), "lon": self._gradi_str(lon_micro),
                 "format": "jsonv2", "zoom": "14", "addressdetails": "1"})
            dati = self._fetch(url)
            addr = dati.get("address") if isinstance(dati, dict) else None
            if not isinstance(addr, dict):
                return None
            for campo in _CAMPI_QUARTIERE:
                v = addr.get(campo)
                if isinstance(v, str) and v.strip():
                    return " ".join(v.split())[:_QUARTIERE_MAX]
            return None
        except Exception:
            logger.warning("geocoder: reverse quartiere fallito (ISOLATO -> None)",
                           exc_info=True)
            return None

    @staticmethod
    def _fetch_reale(url: str) -> Any:  # pragma: no cover (rete)
        req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                                   "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=12) as r:
            return json.loads(r.read().decode("utf-8", "replace"))


def crea_geocoder(percorso: str, *, fetch: Any = None,
                  orologio: Any = None) -> Geocoder:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        g = Geocoder(lambda: _conn_condivisa(con), fetch=fetch, orologio=orologio)
    else:
        g = Geocoder(lambda: sqlite3.connect(percorso), fetch=fetch, orologio=orologio)
    g.inizializza_schema()
    return g
