"""
CORE_AUTO - Fase 135: Sincronizzazione iCal BIDIREZIONALE.

fase82 importa (.ics esterno → blocca inventario). Qui si chiude il cerchio con l'EXPORT:
genera un feed .ics delle NOSTRE date occupate, pubblicabile come URL, così Airbnb/Booking
lo importano e bloccano da soli → anti-overbooking cross-canale in ENTRAMBE le direzioni.
RFC5545: VEVENT con VALUE=DATE, DTEND ESCLUSIVO (semi-aperto, coerente fase82), UID stabile,
righe CRLF, testo escapato. PURO/deterministico. BLINDATO: record invalido → saltato.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Sequence

PRODID = "-//BookinVIP//iCalBidirezionale//IT"


def _data_compatta(d: Any) -> Optional[str]:
    """'2026-08-01' -> '20260801'. None se invalida."""
    try:
        a, m, g = str(d).split("-")
        if len(a) == 4 and 1 <= int(m) <= 12 and 1 <= int(g) <= 31:
            return "%04d%02d%02d" % (int(a), int(m), int(g))
    except Exception:
        return None
    return None


def _escape(t: str) -> str:
    return (str(t).replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def _uid(slug: str, ci: str, co: str, dato: Optional[str]) -> str:
    if dato:
        return "%s@bookinvip.com" % dato
    h = hashlib.sha256(("%s|%s|%s" % (slug, ci, co)).encode("utf-8")).hexdigest()[:16]
    return "%s@bookinvip.com" % h


def genera_ical(prenotazioni: Sequence[Dict[str, Any]], *, prodid: str = PRODID,
                dtstamp: str = "20260101T000000Z") -> str:
    """Feed .ics delle date occupate. Ogni prenotazione: check_in, check_out (+slug, uid)."""
    righe = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:" + prodid, "CALSCALE:GREGORIAN"]
    for p in prenotazioni if isinstance(prenotazioni, (list, tuple)) else []:
        if not isinstance(p, dict):
            continue
        ci = _data_compatta(p.get("check_in"))
        co = _data_compatta(p.get("check_out"))
        if not (ci and co and ci < co):
            continue
        righe += [
            "BEGIN:VEVENT",
            "UID:" + _uid(str(p.get("slug", "")), ci, co, p.get("uid")),
            "DTSTAMP:" + dtstamp,
            "DTSTART;VALUE=DATE:" + ci,
            "DTEND;VALUE=DATE:" + co,                      # esclusivo (semi-aperto)
            "SUMMARY:" + _escape(p.get("summary", "Occupato - BookinVIP")),
            "TRANSP:OPAQUE",
            "END:VEVENT",
        ]
    righe.append("END:VCALENDAR")
    return "\r\n".join(righe) + "\r\n"


class SyncBidirezionale:
    """Import (fase82) + export (qui), stessa convenzione semi-aperta DTEND-esclusivo."""

    def esporta(self, prenotazioni: Sequence[Dict[str, Any]]) -> str:
        return genera_ical(prenotazioni)

    def importa(self, testo_ics: str, inventario: Any, slug: str) -> Dict[str, Any]:
        try:
            from fase82_ical_sync import sincronizza
            return sincronizza(inventario, slug, testo_ics)
        except Exception:
            return {}


def crea_sync_bidirezionale() -> SyncBidirezionale:
    return SyncBidirezionale()
