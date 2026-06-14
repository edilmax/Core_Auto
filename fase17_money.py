"""
CORE_AUTO - Fase 17: Money (importi in centesimi interi, zero float).

Regola d'oro: il denaro NON viaggia mai in virgola mobile. Tutti gli importi
transazionali (pagamenti split, escrow, commissioni) sono **centesimi interi**
(modello Stripe). I float sono vietati: introducono errori di arrotondamento
(0.1 + 0.2 != 0.3) che, accumulati su ripartizioni e somme, fanno divergere i
conti. Le conversioni per la presentazione usano Decimal (esatto), mai float.
"""
from __future__ import annotations

import re
from decimal import Decimal

_SOLO_CIFRE = re.compile(r"^-?\d+$")


def parse_cent(value, campo: str = "importo") -> int:
    """Normalizza un importo monetario in CENTESIMI interi senza usare float.

    Contratto API: gli importi sono centesimi interi. Accetta `int` (gia'
    centesimi) o una stringa di sole cifre (con eventuale segno). Rifiuta
    esplicitamente float, bool e stringhe decimali, per impedire a monte
    qualunque imprecisione in virgola mobile.

    Args:
        value: valore in ingresso (int o str di cifre).
        campo: nome del campo, per messaggi d'errore chiari.

    Returns:
        L'importo in centesimi (int).

    Raises:
        ValueError: tipo non ammesso o formato non intero.
    """
    if isinstance(value, bool):
        raise ValueError(f"{campo}: atteso intero (centesimi), ricevuto bool")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and _SOLO_CIFRE.match(value.strip()):
        return int(value.strip())
    raise ValueError(
        f"{campo}: gli importi devono essere centesimi interi (int o stringa di "
        f"cifre), ricevuto {type(value).__name__}: {value!r}")


def cents_to_str(cents: int) -> str:
    """Centesimi interi -> stringa euro a 2 decimali, esatta (Decimal, no float).

    Es.: 123456 -> '1234.56', -5 -> '-0.05', 0 -> '0.00'.
    """
    if not isinstance(cents, int) or isinstance(cents, bool):
        raise ValueError(f"cents deve essere int, ricevuto {type(cents).__name__}")
    return str((Decimal(cents) / Decimal(100)).quantize(Decimal("0.01")))


def valida_split(importo_totale: int, commissione_tavola: int,
                 quota_partner: int) -> None:
    """Verifica gli invarianti di una ripartizione (tutti in centesimi interi).

    Raises:
        ValueError: importi non interi/negativi o split che non quadra
            (commissione + quota != totale).
    """
    for nome, v in (("importo_totale", importo_totale),
                    ("commissione_tavola", commissione_tavola),
                    ("quota_partner", quota_partner)):
        if not isinstance(v, int) or isinstance(v, bool):
            raise ValueError(f"{nome}: atteso int (centesimi)")
        if v < 0:
            raise ValueError(f"{nome}: importo negativo non ammesso")
    if commissione_tavola + quota_partner != importo_totale:
        raise ValueError(
            "split non quadra: commissione_tavola + quota_partner "
            f"({commissione_tavola} + {quota_partner}) != importo_totale "
            f"({importo_totale}) [centesimi]")
