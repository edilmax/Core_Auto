"""
CORE_AUTO - Fase 107: i18n auto-traduzione annunci (GRATIS, coerente con fase61).

Direttiva fase61 [[core-auto-storefront]]: MAI traduzione live a pagamento → default
PASS-THROUGH (testo invariato, taggato lingua origine; l'agente del guest traduce gratis).
Qui si AGGIUNGE un backend di traduzione OPZIONALE e GRATUITO (LibreTranslate self-host),
INIETTABILE: senza backend → pass-through (costo zero); con backend → traduce e CACHA per
non ripagare/ricomputare. BLINDATO: traduttore che solleva → pass-through. PURO/deterministico
(traduci_fn e fetch iniettabili → test senza rete).
"""
from __future__ import annotations

import hashlib
import json
import logging
import urllib.parse
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("core_auto.traduzione_annunci")


class TraduttoreAnnunci:
    CAMPI = ("titolo", "descrizione")

    def __init__(self, traduci: Optional[Callable[[str, str, str], str]] = None, *,
                 cache: Optional[Dict[Any, str]] = None) -> None:
        self._t = traduci
        self._cache: Dict[Any, str] = {} if cache is None else cache

    def traduci_testo(self, testo: Any, da: str, a: str) -> Dict[str, Any]:
        if not isinstance(testo, str) or not testo.strip() or da == a or self._t is None:
            return {"testo": testo, "lingua": da, "tradotto": False}
        key = (a, hashlib.sha256(("%s|%s" % (da, testo)).encode("utf-8")).hexdigest())
        if key in self._cache:
            return {"testo": self._cache[key], "lingua": a, "tradotto": True, "cache": True}
        try:
            out = self._t(testo, da, a)
            if not isinstance(out, str) or not out.strip():
                raise ValueError("traduzione vuota")
        except Exception:
            logger.warning("traduzione fallita (ISOLATA -> pass-through)", exc_info=True)
            return {"testo": testo, "lingua": da, "tradotto": False}
        self._cache[key] = out
        return {"testo": out, "lingua": a, "tradotto": True}

    def traduci_annuncio(self, annuncio: Dict[str, Any], lingua_dest: str, *,
                         lingua_origine: str = "it") -> Dict[str, Any]:
        out = dict(annuncio) if isinstance(annuncio, dict) else {}
        meta: Dict[str, bool] = {}
        for c in self.CAMPI:
            if c in out:
                r = self.traduci_testo(out[c], lingua_origine, lingua_dest)
                out[c] = r["testo"]
                meta[c] = bool(r["tradotto"])
        out["_lingua"] = lingua_dest if any(meta.values()) else lingua_origine
        out["_tradotto"] = meta
        return out


def _fetch_reale(url: str, data: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover
    import urllib.request
    body = urllib.parse.urlencode(data).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=15) as r:
        return json.loads(r.read())


def traduttore_libretranslate(endpoint: str, *, api_key: str = "",
                              fetch: Optional[Callable[..., Dict[str, Any]]] = None
                              ) -> Optional[Callable[[str, str, str], str]]:
    """Backend GRATUITO LibreTranslate (self-host). Senza endpoint → None (pass-through)."""
    if not endpoint:
        return None
    f = fetch or _fetch_reale

    def traduci(testo: str, da: str, a: str) -> str:
        payload = {"q": testo, "source": da, "target": a, "format": "text"}
        if api_key:
            payload["api_key"] = api_key
        r = f(endpoint, payload)
        return r.get("translatedText", "") if isinstance(r, dict) else ""
    return traduci


def crea_traduttore(traduci: Any = None, *, cache: Any = None) -> TraduttoreAnnunci:
    return TraduttoreAnnunci(traduci, cache=cache)


def crea_traduttore_da_env(env: Optional[Dict[str, str]] = None, *,
                           fetch: Any = None) -> TraduttoreAnnunci:
    import os
    e = env if env is not None else os.environ
    t = traduttore_libretranslate(e.get("LIBRETRANSLATE_URL", ""),
                                  api_key=e.get("LIBRETRANSLATE_KEY", ""), fetch=fetch)
    return TraduttoreAnnunci(t)
