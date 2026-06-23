"""
CORE_AUTO - Fase 129: Traduzione recensioni guest multilingua (gratis, coerente fase61/107).

Riusa l'infrastruttura di fase107 (default PASS-THROUGH; backend gratuito LibreTranslate
INIETTABILE; cache) per tradurre le recensioni nella lingua del lettore. Aggiunge: rilevazione
euristica della lingua origine (token frequenti), badge "tradotto automaticamente", e
conservazione dell'ORIGINALE (mai sovrascritto). PURO/deterministico, BLINDATO: errore →
testo originale + tradotto=False.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fase107_traduzione_annunci import TraduttoreAnnunci

# token-spia per la rilevazione lingua (euristica leggera, offline).
_SPIE = {
    "it": (" il ", " che ", " non ", " per ", " sono ", "ottimo", "bellissim", " molto "),
    "en": (" the ", " and ", " was ", " very ", " great ", " stay ", " nice ", " with "),
    "es": (" el ", " que ", " muy ", " gracias", " excelente", " todo ", " con "),
    "fr": (" le ", " très ", " bien ", " séjour", " avec ", " merci", " nous "),
    "de": (" und ", " sehr ", " war ", " mit ", " schön", " danke", " wir "),
}


def rileva_lingua(testo: Any, default: str = "en") -> str:
    if not isinstance(testo, str) or not testo.strip():
        return default
    t = (" " + testo.lower() + " ")
    punteggi = {lng: sum(t.count(s) for s in spie) for lng, spie in _SPIE.items()}
    best = max(punteggi, key=punteggi.get)
    return best if punteggi[best] > 0 else default


class TraduttoreRecensioni:
    def __init__(self, traduci: Any = None, *, cache: Any = None) -> None:
        self._t = TraduttoreAnnunci(traduci, cache=cache)

    def traduci_recensione(self, recensione: Dict[str, Any], lingua_lettore: str
                           ) -> Dict[str, Any]:
        out = dict(recensione) if isinstance(recensione, dict) else {}
        testo = out.get("testo", "")
        origine = out.get("lingua") or rileva_lingua(testo)
        out["lingua_origine"] = origine
        out["testo_originale"] = testo                     # mai sovrascritto
        r = self._t.traduci_testo(testo, origine, lingua_lettore)
        out["testo"] = r["testo"]
        out["lingua"] = r["lingua"]
        out["tradotto_auto"] = bool(r["tradotto"])
        return out


def crea_traduttore_recensioni(traduci: Any = None, *, cache: Any = None
                               ) -> TraduttoreRecensioni:
    return TraduttoreRecensioni(traduci, cache=cache)


def crea_traduttore_recensioni_da_env(env: Optional[Dict[str, str]] = None, *,
                                      fetch: Any = None) -> TraduttoreRecensioni:
    import os
    from fase107_traduzione_annunci import traduttore_libretranslate
    e = env if env is not None else os.environ
    t = traduttore_libretranslate(e.get("LIBRETRANSLATE_URL", ""),
                                  api_key=e.get("LIBRETRANSLATE_KEY", ""), fetch=fetch)
    return TraduttoreRecensioni(t)
