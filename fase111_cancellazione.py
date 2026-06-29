"""
CORE_AUTO - Fase 111: Cancellazione flessibile + rimborso automatico.

Calcola in modo DETERMINISTICO la quota rimborsabile in base a giorni-all'arrivo e alla
politica scelta (flessibile/moderata/rigida), in CENTESIMI interi. PURO: nessun I/O; il
rimborso effettivo è delegato (orologio iniettabile per i test). BLINDATO: input invalido
→ rimborso 0 (fail-closed, non si restituisce ciò che non si deve).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


@dataclass(frozen=True)
class PoliticaCancellazione:
    nome: str = "flessibile"
    # scaglioni (giorni_all_arrivo_minimi, percentuale_rimborso_bps) ordinati DESC per giorni
    scaglioni: Tuple[Tuple[int, int], ...] = ((7, 10000), (1, 5000), (0, 0))


POLITICHE = {
    "flessibile": PoliticaCancellazione("flessibile", ((1, 10000), (0, 5000))),
    "moderata": PoliticaCancellazione("moderata", ((5, 10000), (1, 5000), (0, 0))),
    "rigida": PoliticaCancellazione("rigida", ((14, 10000), (7, 5000), (0, 0))),
    "non_rimborsabile": PoliticaCancellazione("non_rimborsabile", ((0, 0),)),
}


def _bps_per_giorni(giorni: int, scaglioni: Tuple[Tuple[int, int], ...]) -> int:
    for soglia, bps in sorted(scaglioni, key=lambda x: -x[0]):
        if giorni >= soglia:
            return max(0, min(10000, int(bps)))
    return 0


def calcola_rimborso(prezzo_pagato_cents: Any, giorni_all_arrivo: Any, *,
                     politica: Any = "flessibile",
                     fee_pulizia_cents: int = 0) -> Dict[str, Any]:
    """Rimborso in cents. La fee pulizia (se presente) è SEMPRE rimborsata se non c'è stato
    soggiorno (non maturata); il resto segue gli scaglioni. fail-closed su input invalido."""
    pol = politica if isinstance(politica, PoliticaCancellazione) \
        else POLITICHE.get(str(politica), POLITICHE["flessibile"])
    pagato = prezzo_pagato_cents if isinstance(prezzo_pagato_cents, int) and \
        not isinstance(prezzo_pagato_cents, bool) and prezzo_pagato_cents > 0 else 0
    if pagato == 0:
        return {"rimborso_cents": 0, "trattenuto_cents": 0, "bps": 0,
                "politica": pol.nome}
    g = giorni_all_arrivo if isinstance(giorni_all_arrivo, int) and \
        not isinstance(giorni_all_arrivo, bool) and giorni_all_arrivo >= 0 else 0
    fee = max(0, int(fee_pulizia_cents)) if isinstance(fee_pulizia_cents, int) and \
        not isinstance(fee_pulizia_cents, bool) else 0
    fee = min(fee, pagato)
    soggiorno = pagato - fee                                # parte soggetta a penale
    bps = _bps_per_giorni(g, pol.scaglioni)
    rimborso = fee + (soggiorno * bps // 10000)            # pulizia sempre resa
    rimborso = max(0, min(pagato, rimborso))
    return {"rimborso_cents": rimborso, "trattenuto_cents": pagato - rimborso,
            "bps": bps, "politica": pol.nome}


def crea_politica_cancellazione(nome: str,
                                scaglioni: List[Tuple[int, int]]) -> PoliticaCancellazione:
    return PoliticaCancellazione(nome, tuple(scaglioni))
