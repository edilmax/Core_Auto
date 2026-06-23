"""
CORE_AUTO - Fase 121: Mappa interattiva alloggi + geo-ricerca.

Coordinate in MICROGRADI interi (coerente con fase57; mai float per la geo). Bounding-box
da centro+raggio (km), filtro punti dentro box, distanza haversine (metri interi), ordina per
vicinanza, clustering a griglia per la mappa, GeoJSON FeatureCollection per il frontend.
PURO/deterministico. BLINDATO: input invalido → escluso/[].
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

MICRO = 1_000_000
_R_TERRA_M = 6_371_000


def _i(v: Any) -> Optional[int]:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def bbox(lat_u: int, lon_u: int, raggio_km: float) -> Optional[Dict[str, int]]:
    """Bounding-box (microgradi) attorno a un centro per un raggio in km."""
    la, lo = _i(lat_u), _i(lon_u)
    if la is None or lo is None or not raggio_km or raggio_km <= 0:
        return None
    dlat = raggio_km / 111.0
    coslat = max(0.01, math.cos(math.radians(la / MICRO)))
    dlon = raggio_km / (111.0 * coslat)
    return {"lat_min": int(la - dlat * MICRO), "lat_max": int(la + dlat * MICRO),
            "lon_min": int(lo - dlon * MICRO), "lon_max": int(lo + dlon * MICRO)}


def dentro_bbox(lat_u: int, lon_u: int, box: Dict[str, int]) -> bool:
    la, lo = _i(lat_u), _i(lon_u)
    if la is None or lo is None or not isinstance(box, dict):
        return False
    return (box["lat_min"] <= la <= box["lat_max"]
            and box["lon_min"] <= lo <= box["lon_max"])


def distanza_m(lat1_u: int, lon1_u: int, lat2_u: int, lon2_u: int) -> int:
    """Haversine, metri interi. -1 se input invalido."""
    a1, o1, a2, o2 = _i(lat1_u), _i(lon1_u), _i(lat2_u), _i(lon2_u)
    if None in (a1, o1, a2, o2):
        return -1
    la1, lo1, la2, lo2 = (math.radians(x / MICRO) for x in (a1, o1, a2, o2))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return int(2 * _R_TERRA_M * math.asin(min(1.0, math.sqrt(h))))


def cerca_vicini(alloggi: Sequence[Dict[str, Any]], lat_u: int, lon_u: int,
                 raggio_km: float, *, limit: int = 50) -> List[Dict[str, Any]]:
    """Alloggi (con lat_u/lon_u) dentro il raggio, ordinati per distanza crescente."""
    box = bbox(lat_u, lon_u, raggio_km)
    if box is None or not isinstance(alloggi, (list, tuple)):
        return []
    raggio_m = raggio_km * 1000
    out = []
    for a in alloggi:
        if not isinstance(a, dict):
            continue
        la, lo = _i(a.get("lat_u")), _i(a.get("lon_u"))
        if la is None or lo is None or not dentro_bbox(la, lo, box):
            continue
        d = distanza_m(lat_u, lon_u, la, lo)
        if 0 <= d <= raggio_m:
            out.append({**a, "distanza_m": d})
    out.sort(key=lambda x: x["distanza_m"])
    return out[:max(0, _i(limit) or 0)]


def cluster_griglia(alloggi: Sequence[Dict[str, Any]], *,
                    passo_micro: int = 50000) -> List[Dict[str, Any]]:
    """Raggruppa per cella di griglia (per la mappa a bassi zoom). Centroide intero + count."""
    p = max(1, _i(passo_micro) or 50000)
    celle: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    for a in alloggi if isinstance(alloggi, (list, tuple)) else []:
        if not isinstance(a, dict):
            continue
        la, lo = _i(a.get("lat_u")), _i(a.get("lon_u"))
        if la is None or lo is None:
            continue
        celle.setdefault((la // p, lo // p), []).append((la, lo))
    out = []
    for (cy, cx), pts in sorted(celle.items()):
        out.append({"lat_u": sum(x for x, _ in pts) // len(pts),
                    "lon_u": sum(y for _, y in pts) // len(pts), "count": len(pts)})
    return out


def geojson(alloggi: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """FeatureCollection per la mappa (coordinate in gradi float SOLO in output GeoJSON)."""
    feats = []
    for a in alloggi if isinstance(alloggi, (list, tuple)) else []:
        if not isinstance(a, dict):
            continue
        la, lo = _i(a.get("lat_u")), _i(a.get("lon_u"))
        if la is None or lo is None:
            continue
        feats.append({"type": "Feature",
                      "geometry": {"type": "Point", "coordinates": [lo / MICRO, la / MICRO]},
                      "properties": {"slug": a.get("slug", ""),
                                     "prezzo_cents": a.get("prezzo_cents")}})
    return {"type": "FeatureCollection", "features": feats}
