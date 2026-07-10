"""
CORE_AUTO - Allarme domanda: quando le persone in attesa in una città superano una SOGLIA,
si scatta un allarme UNA sola volta per città (anti-spam, durevole) -> notifica automatica agli
host ("N cercano casa a X, pubblica/aggiorna disponibilità") + evidenza in ricerca.

PURO e BLINDATO: stato durevole su file JSON (come il pattern opt-out); input non validi ->
nessun allarme (fail-closed, non si spamma). Nessuna dipendenza esterna, tutto testabile.
"""
from __future__ import annotations

import json
import logging
from typing import Any, List, Set

logger = logging.getLogger("core_auto.domanda_allarme")

SOGLIA_DEFAULT = 5


class AllarmeDomanda:
    def __init__(self, percorso: str = "", *, soglia: int = SOGLIA_DEFAULT) -> None:
        self._percorso = percorso or ""
        self._soglia = soglia if isinstance(soglia, int) and not isinstance(soglia, bool) \
            and soglia >= 1 else SOGLIA_DEFAULT
        self._segnalate: Set[str] = self._leggi()

    @property
    def soglia(self) -> int:
        return self._soglia

    def _leggi(self) -> Set[str]:
        if not self._percorso:
            return set()
        try:
            with open(self._percorso, encoding="utf-8") as f:
                d = json.load(f)
            return set(str(c) for c in d.get("citta", []))
        except Exception:
            return set()

    def _scrivi(self) -> None:
        if not self._percorso:
            return
        try:
            with open(self._percorso, "w", encoding="utf-8") as f:
                json.dump({"citta": sorted(self._segnalate)}, f, ensure_ascii=False)
        except Exception:
            logger.warning("AllarmeDomanda: scrittura stato fallita (ISOLATA)", exc_info=True)

    @staticmethod
    def _norm(citta: Any) -> str:
        return citta.strip().lower() if isinstance(citta, str) and citta.strip() else ""

    def controlla(self, citta: Any, conteggio: Any) -> bool:
        """True la PRIMA volta che 'citta' raggiunge la soglia (poi segnata -> mai due volte)."""
        c = self._norm(citta)
        n = conteggio if isinstance(conteggio, int) and not isinstance(conteggio, bool) else 0
        if not c or n < self._soglia or c in self._segnalate:
            return False
        self._segnalate.add(c)
        self._scrivi()
        return True

    def in_allarme(self, citta: Any) -> bool:
        return self._norm(citta) in self._segnalate

    def elenco(self) -> List[str]:
        return sorted(self._segnalate)
