"""
CORE_AUTO - Fase 187: IL FUSO ORARIO DELL'ALLOGGIO.

L'audit del 2026-07-22 ha trovato che ogni calcolo sul tempo (finestra di contestazione,
diritto di recensione, pass della serratura, finestra di cancellazione) usava il fuso del
SERVER, e l'alloggio NON aveva un fuso nel modello dati. Per chi vive lontano da Greenwich
questo tagliava la tutela: a Honolulu (UTC-10) le 24 ore di contestazione si chiudevano
quando l'ospite aveva passato in casa 12 ore. Come rimedio provvisorio si era ancorato
tutto a un fuso "prudente" (l'estremo del pianeta), largo ma non esatto.

Questo modulo da' all'alloggio il suo fuso VERO. Un check-in "il 5 settembre alle 15:00"
diventa un istante UTC preciso a seconda di DOVE sta l'alloggio: 15:00 a Tokyo, a Roma o
alle Hawaii sono tre momenti diversi, e ora il sistema lo sa.

ZERO DIPENDENZE: usa `zoneinfo` (stdlib da Python 3.9) col database IANA di sistema, che in
produzione c'e' (verificato). Se un giorno mancasse, le funzioni tornano None e i chiamanti
ricadono sull'approssimazione prudente: mai un errore, mai una tutela piu' stretta del giusto.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Optional

logger = logging.getLogger("core_auto.fuso")

# Convenzione: il check-in e' alle 15:00 ORA LOCALE dell'alloggio.
ORA_CHECKIN_LOCALE = 15

# Citta' -> fuso IANA. Le mete principali (il progetto e' globale, top destinations first).
# La citta' vince sul paese perche' un paese puo' avere piu' fusi (gli USA ne hanno sei:
# per quello NON si mette un default USA "a caso").
_CITTA_FUSO = {
    "tokyo": "Asia/Tokyo", "osaka": "Asia/Tokyo", "kyoto": "Asia/Tokyo",
    "roma": "Europe/Rome", "rome": "Europe/Rome", "milano": "Europe/Rome",
    "milan": "Europe/Rome", "venezia": "Europe/Rome", "venice": "Europe/Rome",
    "firenze": "Europe/Rome", "florence": "Europe/Rome", "napoli": "Europe/Rome",
    "honolulu": "Pacific/Honolulu", "maui": "Pacific/Honolulu", "kona": "Pacific/Honolulu",
    "new york": "America/New_York", "nyc": "America/New_York", "miami": "America/New_York",
    "boston": "America/New_York", "washington": "America/New_York",
    "los angeles": "America/Los_Angeles", "san francisco": "America/Los_Angeles",
    "las vegas": "America/Los_Angeles", "seattle": "America/Los_Angeles",
    "chicago": "America/Chicago", "austin": "America/Chicago", "houston": "America/Chicago",
    "london": "Europe/London", "londra": "Europe/London",
    "paris": "Europe/Paris", "parigi": "Europe/Paris",
    "barcelona": "Europe/Madrid", "barcellona": "Europe/Madrid", "madrid": "Europe/Madrid",
    "berlin": "Europe/Berlin", "berlino": "Europe/Berlin", "munich": "Europe/Berlin",
    "amsterdam": "Europe/Amsterdam", "lisbon": "Europe/Lisbon", "lisbona": "Europe/Lisbon",
    "dubai": "Asia/Dubai", "abu dhabi": "Asia/Dubai",
    "singapore": "Asia/Singapore", "hong kong": "Asia/Hong_Kong",
    "bangkok": "Asia/Bangkok", "seoul": "Asia/Seoul", "shanghai": "Asia/Shanghai",
    "beijing": "Asia/Shanghai", "pechino": "Asia/Shanghai",
    "sydney": "Australia/Sydney", "melbourne": "Australia/Melbourne",
    "mexico city": "America/Mexico_City", "citta del messico": "America/Mexico_City",
    "sao paulo": "America/Sao_Paulo", "san paolo": "America/Sao_Paulo",
    "rio de janeiro": "America/Sao_Paulo", "buenos aires": "America/Argentina/Buenos_Aires",
    "cape town": "Africa/Johannesburg", "citta del capo": "Africa/Johannesburg",
    "istanbul": "Europe/Istanbul", "cairo": "Africa/Cairo", "il cairo": "Africa/Cairo",
    "reykjavik": "Atlantic/Reykjavik", "moscow": "Europe/Moscow", "mosca": "Europe/Moscow",
    "toronto": "America/Toronto", "vancouver": "America/Vancouver",
}

# Paesi con un SOLO fuso pratico -> default affidabile quando la citta' non e' in tabella.
# Si escludono di proposito i paesi multi-fuso (US, CA, AU, BR, RU, MX, ...).
_PAESE_FUSO = {
    "it": "Europe/Rome", "ita": "Europe/Rome", "italia": "Europe/Rome",
    "italy": "Europe/Rome", "jp": "Asia/Tokyo", "jpn": "Asia/Tokyo",
    "japan": "Asia/Tokyo", "giappone": "Asia/Tokyo",
    "fr": "Europe/Paris", "france": "Europe/Paris", "francia": "Europe/Paris",
    "de": "Europe/Berlin", "germany": "Europe/Berlin", "germania": "Europe/Berlin",
    "es": "Europe/Madrid", "spain": "Europe/Madrid", "spagna": "Europe/Madrid",
    "gb": "Europe/London", "uk": "Europe/London", "united kingdom": "Europe/London",
    "nl": "Europe/Amsterdam", "pt": "Europe/Lisbon", "portugal": "Europe/Lisbon",
    "ae": "Asia/Dubai", "sg": "Asia/Singapore", "kr": "Asia/Seoul", "th": "Asia/Bangkok",
    "ch": "Europe/Zurich", "at": "Europe/Vienna", "gr": "Europe/Athens",
    "ie": "Europe/Dublin", "be": "Europe/Brussels", "tr": "Europe/Istanbul",
}


def _zi(nome: str):
    """ZoneInfo se il nome e' valido e il database c'e', altrimenti None (mai solleva)."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(nome)
    except Exception:
        return None


def fuso_valido(nome: object) -> bool:
    """Vero se `nome` e' un fuso IANA reale ('Asia/Tokyo', ...) e usabile qui."""
    return isinstance(nome, str) and bool(nome) and _zi(nome) is not None


def fuso_da_luogo(citta: object, paese: object = "") -> str:
    """Deduce il fuso IANA da citta'/paese, best-effort. '' se non si e' sicuri
    (meglio vuoto, e ripiego prudente a valle, che un fuso sbagliato)."""
    c = str(citta or "").strip().lower()
    if c in _CITTA_FUSO:
        return _CITTA_FUSO[c]
    p = str(paese or "").strip().lower()
    if p in _PAESE_FUSO:
        return _PAESE_FUSO[p]
    return ""


def normalizza(fuso: object, citta: object = "", paese: object = "") -> str:
    """Il fuso da salvare per un alloggio: quello dato (se valido), altrimenti dedotto da
    citta'/paese, altrimenti '' (i calcoli useranno il ripiego prudente)."""
    if fuso_valido(fuso):
        return str(fuso)
    return fuso_da_luogo(citta, paese)


def istante_locale(data_iso: object, ora_locale: int, fuso: object) -> Optional[int]:
    """Epoch UTC del momento 'data_iso alle ora_locale:00' NEL FUSO dell'alloggio.
    None se la data non e' valida o il fuso non e' utilizzabile (il chiamante ripiega)."""
    tz = _zi(fuso) if isinstance(fuso, str) else None
    if tz is None:
        return None
    try:
        g = _dt.date.fromisoformat(str(data_iso))
    except Exception:
        return None
    ora = ora_locale if isinstance(ora_locale, int) and 0 <= ora_locale <= 23 else \
        ORA_CHECKIN_LOCALE
    return int(_dt.datetime(g.year, g.month, g.day, ora, 0, 0, tzinfo=tz).timestamp())


def mezzanotte_locale(data_iso: object, fuso: object) -> Optional[int]:
    """Epoch UTC della MEZZANOTTE (00:00) di quel giorno nel fuso dell'alloggio.
    Serve al diritto di recensione (si recensisce dal giorno del check-out, ora locale)."""
    return istante_locale(data_iso, 0, fuso)
