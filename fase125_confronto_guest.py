"""
CORE_AUTO - Fase 125: Confronto OTA risparmio GUEST (prezzo finale lato ospite).

Complementare a fase69 (che confronta il NETTO HOST): qui si mostra all'OSPITE quanto
pagherebbe sull'OTA vs su BookinVIP per lo STESSO alloggio, evidenziando il risparmio. Le
OTA caricano: markup sul prezzo host + guest service fee + (spesso) markup valutario DCC
occulto (fase99). Tutto in CENTESIMI interi e bps; INVARIANTE verificabile. BLINDATO.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class PoliticaConfrontoGuest:
    ota_markup_host_bps: int = 1500   # quanto l'OTA carica sopra il netto host
    ota_guest_fee_bps: int = 1400     # guest service fee dell'OTA (su netto+markup)
    ota_dcc_bps: int = 400            # markup valutario occulto (se cambio valuta)
    nostra_guest_fee_bps: int = 0     # 0% OSPITE: l'ospite paga il prezzo PULITO (strategia BookinVIP)


def _i(v: Any) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def confronta_guest(netto_host_cents: Any, *, valuta_diversa: bool = False,
                    pol: PoliticaConfrontoGuest = PoliticaConfrontoGuest()) -> Dict[str, Any]:
    """Prezzo finale ospite OTA vs noi, su uno stesso netto host. cents interi, fail-closed."""
    netto = _i(netto_host_cents)
    if netto == 0:
        return {"netto_host_cents": 0, "ota_totale_cents": 0, "nostro_totale_cents": 0,
                "risparmio_guest_cents": 0, "risparmio_bps": 0}
    # OTA: netto + markup -> base; + guest fee; + DCC se cambio valuta
    base_ota = netto + (netto * _i(pol.ota_markup_host_bps) // 10000)
    ota_fee = base_ota * _i(pol.ota_guest_fee_bps) // 10000
    ota_dcc = (base_ota + ota_fee) * _i(pol.ota_dcc_bps) // 10000 if valuta_diversa else 0
    ota_tot = base_ota + ota_fee + ota_dcc
    # Noi: netto host + nostra guest fee (no markup nascosto, no DCC occulto)
    # Noi: prezzo PULITO (0% ospite di default); no markup nascosto, no DCC occulto
    nostra_fee = netto * _i(pol.nostra_guest_fee_bps) // 10000
    nostro_tot = netto + nostra_fee
    risparmio = max(0, ota_tot - nostro_tot)
    return {"netto_host_cents": netto,
            "ota_base_cents": base_ota, "ota_guest_fee_cents": ota_fee,
            "ota_dcc_cents": ota_dcc, "ota_totale_cents": ota_tot,
            "nostra_guest_fee_cents": nostra_fee, "nostro_totale_cents": nostro_tot,
            "risparmio_guest_cents": risparmio,
            "risparmio_bps": (risparmio * 10000 // ota_tot) if ota_tot else 0}
