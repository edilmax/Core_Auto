"""
CORE_AUTO - Fase 115: Dashboard host metriche avanzate (KPI deterministici).

Calcola KPI dell'host da una lista di prenotazioni (dict): revenue, occupazione %, ADR
(average daily rate), RevPAR, notti vendute, lead-time medio, tasso cancellazione, rating
medio. Tutto in CENTESIMI interi e bps (mai float). PURO: nessun I/O. BLINDATO: liste
vuote/record invalidi → 0, mai eccezioni. Periodo (giorni) e unità configurabili.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence


def _i(v: Any, d: int = 0) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else d


def _notti(p: Dict[str, Any]) -> int:
    n = _i(p.get("notti"), 0)
    if n > 0:
        return n
    try:
        from fase58_channel_manager import notti
        el = notti(p.get("check_in"), p.get("check_out"))
        return len(el) if el else 0
    except Exception:
        return 0


def calcola_metriche(prenotazioni: Sequence[Dict[str, Any]], *,
                     giorni_periodo: int = 30, unita: int = 1) -> Dict[str, Any]:
    pren = [p for p in prenotazioni if isinstance(p, dict)] if \
        isinstance(prenotazioni, (list, tuple)) else []
    giorni = max(1, _i(giorni_periodo, 30))
    u = max(1, _i(unita, 1))
    attive = [p for p in pren if not p.get("rimborsato") and not p.get("cancellata")]
    tot = len(pren)
    cancellate = sum(1 for p in pren if p.get("rimborsato") or p.get("cancellata"))

    revenue = sum(max(0, _i(p.get("prezzo_guest_cents"))) for p in attive)
    notti_vendute = sum(_notti(p) for p in attive)
    notti_disponibili = giorni * u

    occ_bps = (notti_vendute * 10000 // notti_disponibili) if notti_disponibili else 0
    occ_bps = min(10000, occ_bps)
    adr = (revenue // notti_vendute) if notti_vendute else 0          # ricavo medio/notte
    revpar = (revenue // notti_disponibili) if notti_disponibili else 0
    canc_bps = (cancellate * 10000 // tot) if tot else 0

    lead = [d for d in (_i(p.get("lead_time_giorni"), -1) for p in attive) if d >= 0]
    lead_medio = (sum(lead) // len(lead)) if lead else 0
    voti = [v for v in (_i(p.get("voto"), 0) for p in pren) if 1 <= v <= 5]
    rating_centi = (sum(voti) * 100 // len(voti)) if voti else 0       # stelle ×100

    return {
        "prenotazioni_totali": tot,
        "prenotazioni_attive": len(attive),
        "cancellate": cancellate,
        "tasso_cancellazione_bps": canc_bps,
        "revenue_cents": revenue,
        "notti_vendute": notti_vendute,
        "notti_disponibili": notti_disponibili,
        "occupazione_bps": occ_bps,
        "adr_cents": adr,
        "revpar_cents": revpar,
        "lead_time_medio_giorni": lead_medio,
        "rating_medio_centi": rating_centi,
    }
