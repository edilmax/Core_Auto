"""
CORE_AUTO - Fase 82: iCal Sync (la portabilita' REALE, non quella gonfiata).

Verita' onesta (validata da una critica di mercato): NON esiste un'API pubblica per
esportare l'inventario host da Booking/Airbnb. Il "bottone Importa da Booking in 10
secondi" e' un'illusione. Ma esiste un canale di portabilita' REALE, legale e
UNIVERSALE che ogni OTA offre davvero all'host: il calendario iCal (.ics). Airbnb,
Booking, Vrbo esportano tutti un link iCal con le date gia' occupate/bloccate.

Questo modulo fa la cosa vera: parser iCal PURO (zero dipendenze - la libreria
`icalendar` non e' installata e non serve), estrae i periodi occupati dai VEVENT, e li
sincronizza nell'inventario (fase58) marcandoli NON disponibili. E' il vero anti-
overbooking cross-canale: una prenotazione presa su Airbnb blocca quelle date anche da
noi, automaticamente, senza scraping ne' API proprietarie.

Semantica corretta: in iCal con VALUE=DATE, DTEND e' ESCLUSIVO -> coincide con il nostro
intervallo semi-aperto [check_in, check_out) (fase34/58). Niente off-by-one.

VINCITRICE DEL BENCHMARK (4 modi di sincronizzare i canali):
  V3 'parser iCal puro + blocco idempotente per-giorno su fase58'. Reale (iCal e' lo
  standard universale), legale (link fornito dall'host), zero dipendenze, idempotente
  (ri-sincronizzare non rompe nulla). Le altre perdono: V1 'API inventario Booking' =
  NON ESISTE; V2 'scraping' = illegale (ToS) e fragile; V4 'import CSV manuale' =
  attrito, si fa una volta sola, non si sincronizza.

SOPRAVVIVENZA TOTALE: parser blindato (righe/eventi malformati IGNORATI, mai
un'eccezione); date invalide scartate; sync isolato (un giorno che fallisce non abbatte
il resto); blocco via imposta_disponibilita (unita_totali=0) che NON scende mai sotto
l'occupato reale (fail-safe). Zero dipendenze esterne.
"""
from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("core_auto.ical_sync")

MAX_GIORNI_EVENTO = 366    # tetto anti-abuso su un singolo VEVENT


def _srotola(testo: str) -> List[str]:
    """RFC5545 line unfolding: una riga che inizia con spazio/tab continua la precedente."""
    righe: List[str] = []
    for riga in testo.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if riga[:1] in (" ", "\t") and righe:
            righe[-1] += riga[1:]
        else:
            righe.append(riga)
    return righe


def _data_da_valore(valore: str) -> Optional[datetime.date]:
    """Estrae la data da un valore DTSTART/DTEND ('20260701' o '20260701T140000Z')."""
    cifre = ""
    for ch in valore.strip():
        if ch.isdigit():
            cifre += ch
            if len(cifre) == 8:
                break
        else:
            if cifre:
                break
    if len(cifre) != 8:
        return None
    try:
        return datetime.date(int(cifre[:4]), int(cifre[4:6]), int(cifre[6:8]))
    except ValueError:
        return None


def analizza_ical(testo: Any) -> List[Tuple[str, str]]:
    """Estrae i periodi occupati (check_in, check_out) ISO da un .ics. BLINDATO."""
    if not isinstance(testo, str):
        return []
    eventi: List[Tuple[str, str]] = []
    dentro = False
    dtstart: Optional[datetime.date] = None
    dtend: Optional[datetime.date] = None
    for riga in _srotola(testo):
        u = riga.strip().upper()
        if u == "BEGIN:VEVENT":
            dentro, dtstart, dtend = True, None, None
            continue
        if u == "END:VEVENT":
            if dtstart and dtend and dtstart < dtend \
                    and (dtend - dtstart).days <= MAX_GIORNI_EVENTO:
                eventi.append((dtstart.isoformat(), dtend.isoformat()))
            dentro = False
            continue
        if not dentro or ":" not in riga:
            continue
        chiave, _, valore = riga.partition(":")
        nome = chiave.split(";")[0].strip().upper()
        if nome == "DTSTART":
            dtstart = _data_da_valore(valore)
        elif nome == "DTEND":
            dtend = _data_da_valore(valore)
    return eventi


def _giorni(check_in: str, check_out: str) -> List[str]:
    ci = datetime.date.fromisoformat(check_in)
    co = datetime.date.fromisoformat(check_out)
    return [(ci + datetime.timedelta(days=i)).isoformat()
            for i in range((co - ci).days)]


def sincronizza(inventario: Any, alloggio_id: str, ical_testo: Any) -> Dict[str, int]:
    """Blocca nell'inventario (fase58) tutti i giorni occupati dell'iCal (unita_totali=0
    -> non disponibile). Idempotente. Ritorna {eventi, giorni_bloccati}."""
    eventi = analizza_ical(ical_testo)
    giorni_bloccati = 0
    giorni_visti = set()
    for ci, co in eventi:
        try:
            giorni = _giorni(ci, co)
        except (ValueError, TypeError):
            continue
        for g in giorni:
            if g in giorni_visti:
                continue
            giorni_visti.add(g)
            try:
                # unita_totali=0 -> giorno non disponibile; non scende mai sotto
                # l'occupato reale (fase58 fail-safe)
                if inventario.imposta_disponibilita(str(alloggio_id), g,
                                                    unita_totali=0,
                                                    prezzo_netto_cents=0):
                    giorni_bloccati += 1
            except Exception:
                logger.warning("ical_sync: blocco giorno %s fallito (isolato)", g,
                               exc_info=True)
    return {"eventi": len(eventi), "giorni_bloccati": giorni_bloccati}
