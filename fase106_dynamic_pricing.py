"""
CORE_AUTO - Fase 106: Dynamic pricing (motore prezzi domanda + stagionalità).

Calcola un prezzo/notte a partire dal prezzo base (cents) applicando coefficienti interi
deterministici: occupazione (demand spike), stagione (mese), weekend, last-minute/anticipo.
Tutto in basis-point e CENTESIMI interi (mai float). BLINDATO: input invalido → prezzo base.
Floor/cap configurabili → niente prezzi assurdi. PURO: nessun I/O, nessuna dipendenza.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


def _bps(v: Any, default: int) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else default


@dataclass(frozen=True)
class PoliticaPrezzo:
    # moltiplicatori in basis-point (10000 = ×1.0)
    occ_alta_bps: int = 13000        # occupazione >= soglia_alta → +30%
    occ_bassa_bps: int = 9000        # occupazione <= soglia_bassa → -10%
    soglia_alta: int = 8000          # 80% occupazione (bps)
    soglia_bassa: int = 3000         # 30%
    weekend_bps: int = 11500         # ven/sab → +15%
    last_minute_bps: int = 8500      # <=2 giorni → -15% (riempi i buchi)
    anticipo_bps: int = 10500        # >=60 giorni → +5%
    floor_bps: int = 6000            # mai sotto 60% del base
    cap_bps: int = 25000             # mai oltre 250% del base
    # coefficiente stagionale per mese 1..12 (bps); default neutro 10000
    stagione_bps: Dict[int, int] = field(default_factory=lambda: {
        1: 9000, 2: 9000, 3: 9500, 4: 10000, 5: 10500, 6: 12000,
        7: 13000, 8: 13000, 9: 11000, 10: 10000, 11: 9000, 12: 11000})


def _mese(data: Any) -> int:
    try:
        return int(str(data).split("-")[1])
    except Exception:
        return 0


def _giorno_settimana(data: Any) -> int:
    # 0=lun..6=dom via Zeller-free: usa datetime solo per parsing locale, no dipendenze
    try:
        from datetime import date
        a, m, g = (int(x) for x in str(data).split("-"))
        return date(a, m, g).weekday()
    except Exception:
        return -1


def calcola_prezzo(prezzo_base_cents: int, *, occupazione_bps: int = 5000,
                   data: str = "", giorni_all_arrivo: int = 30,
                   pol: PoliticaPrezzo = PoliticaPrezzo()) -> Dict[str, Any]:
    """Prezzo/notte dinamico. Ritorna prezzo finale (cents) + i fattori applicati (audit)."""
    base = prezzo_base_cents if isinstance(prezzo_base_cents, int) and \
        not isinstance(prezzo_base_cents, bool) and prezzo_base_cents > 0 else 0
    if base == 0:
        return {"prezzo_cents": 0, "base_cents": 0, "fattori": {}}
    occ = _bps(occupazione_bps, 5000)
    fattori: Dict[str, int] = {}
    m = _bps(10000, 10000)  # accumulatore moltiplicatore totale (bps)

    if occ >= pol.soglia_alta:
        fattori["occupazione"] = pol.occ_alta_bps
    elif occ <= pol.soglia_bassa:
        fattori["occupazione"] = pol.occ_bassa_bps
    else:
        fattori["occupazione"] = 10000

    fattori["stagione"] = pol.stagione_bps.get(_mese(data), 10000)

    gs = _giorno_settimana(data)
    fattori["weekend"] = pol.weekend_bps if gs in (4, 5) else 10000

    g = giorni_all_arrivo if isinstance(giorni_all_arrivo, int) and \
        not isinstance(giorni_all_arrivo, bool) else 30
    if g <= 2:
        fattori["anticipo"] = pol.last_minute_bps
    elif g >= 60:
        fattori["anticipo"] = pol.anticipo_bps
    else:
        fattori["anticipo"] = 10000

    for v in fattori.values():
        m = m * v // 10000
    m = max(pol.floor_bps, min(pol.cap_bps, m))
    prezzo = max(1, base * m // 10000)
    return {"prezzo_cents": prezzo, "base_cents": base,
            "moltiplicatore_bps": m, "fattori": fattori}


def crea_politica_prezzo(**kw: Any) -> PoliticaPrezzo:
    return PoliticaPrezzo(**kw)
