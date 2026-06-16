"""
CORE_AUTO - Fase 48: Advertising del Core (M6) - campagne + allocazione budget.

Capacita' NUOVA: gestione campagne pubblicitarie. Due piani NETTAMENTE separati:
  - DENARO (budget) -> calcolato dal CORE in centesimi interi, MAI dall'IA.
  - CONTENUTO (testo annunci) -> generato via GeneratoreContenuti (astrazione LLM,
    stub nei test, adapter reale lazy/gated). Il generatore NON tocca il denaro.

Vincitrice del benchmark (4 varianti x 10 stress test): V3 'proporzionale-con-floor'
-> alloca il budget per priorita', garantisce no-starvation (1 cent minimo alle
campagne vive), esclude le campagne morte (priorita' 0), conserva ogni centesimo,
spende tutto il budget. Le altre 3 (equal/winner-take-all/unbounded) sprecano,
affamano o sforano.

SOPRAVVIVENZA TOTALE: input corrotti -> fail-closed; CircuitBreakerBudget se una
politica tentasse di sforare il budget (autopreservazione finanziaria); piano
deterministico/idempotente; fuzzing. Posting reale gated da ad-platform.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional


class CircuitBreakerBudget(Exception):
    """Autopreservazione finanziaria: una politica ha tentato di allocare PIU' del
    budget totale. Il motore BLOCCA (fail-closed) invece di sforare la spesa."""


def _int_non_neg(v, nome):
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        raise ValueError(f"{nome} deve essere int >= 0")
    return v


def ripartisci_proporzionale(totale: int, pesi: List[int]) -> List[int]:
    """Ripartizione proporzionale ai pesi, conservando OGNI centesimo (largest-
    remainder, mai float)."""
    _int_non_neg(totale, "totale")
    s = sum(pesi)
    if s == 0 or totale == 0:
        return [0] * len(pesi)
    raw = [Decimal(totale) * Decimal(p) / Decimal(s) for p in pesi]
    fl = [int(r) for r in raw]                       # int(Decimal>=0) = floor
    resto = totale - sum(fl)
    ordine = sorted(range(len(raw)), key=lambda i: raw[i] - fl[i], reverse=True)
    for k in range(resto):
        fl[ordine[k]] += 1
    return fl


@dataclass(frozen=True)
class Campagna:
    id: str
    canale: str
    priorita: int                  # 0 = campagna morta (esclusa); piu' alta = piu' budget
    richiesta_cents: int

    def __post_init__(self):
        if not self.id or not self.canale:
            raise ValueError("id e canale obbligatori")
        _int_non_neg(self.priorita, "priorita")
        _int_non_neg(self.richiesta_cents, "richiesta_cents")


@dataclass(frozen=True)
class AllocazioneCampagna:
    campagna_id: str
    importo_cents: int


class PoliticaBudget(ABC):
    @abstractmethod
    def alloca(self, budget_cents: int, campagne: List[Campagna]) -> List[int]:
        """Restituisce gli importi (centesimi) paralleli a 'campagne'. Somma <= budget."""

    @abstractmethod
    def descrizione(self) -> str: ...


@dataclass(frozen=True)
class PoliticaBudgetProporzionale(PoliticaBudget):
    """Vincitrice V3: proporzionale alla priorita', con floor anti-starvation."""

    def alloca(self, budget_cents: int, campagne: List[Campagna]) -> List[int]:
        a = [0] * len(campagne)
        elig = [i for i, c in enumerate(campagne) if c.priorita > 0]
        if budget_cents <= 0 or not elig:
            return a
        n = len(elig)
        if budget_cents < n:                         # budget scarso: 1 ai piu' prioritari
            for i in sorted(elig, key=lambda i: (-campagne[i].priorita, campagne[i].id))[:budget_cents]:
                a[i] = 1
            return a
        parti = ripartisci_proporzionale(budget_cents - n, [campagne[i].priorita for i in elig])
        for k, i in enumerate(elig):
            a[i] = 1 + parti[k]                      # floor 1 + quota proporzionale
        return a

    def descrizione(self) -> str:
        return "Proporzionale-con-floor (priorita' + no-starvation)"


class GeneratoreContenuti(ABC):
    @abstractmethod
    def genera(self, campagna: Campagna) -> str:
        """Testo dell'annuncio. NON tocca il denaro (separazione contenuto/budget)."""


@dataclass(frozen=True)
class StubGeneratoreContenuti(GeneratoreContenuti):
    """Stub deterministico per i test (e per girare senza LLM reale)."""
    def genera(self, campagna: Campagna) -> str:
        return f"[{campagna.canale}] Scopri {campagna.id}: prenota diretto, niente commissioni OTA."


class MotoreAdvertising:
    """Pianifica le campagne: alloca il budget (dal Core) e genera i contenuti
    (dal generatore). Fail-closed sullo sforamento del budget."""

    def __init__(self, politica: PoliticaBudget,
                 generatore: Optional[GeneratoreContenuti] = None):
        self.pol = politica
        self.gen = generatore or StubGeneratoreContenuti()

    def pianifica(self, budget_cents: int, campagne: List[Campagna]) -> List[AllocazioneCampagna]:
        _int_non_neg(budget_cents, "budget_cents")
        importi = self.pol.alloca(budget_cents, campagne)
        if len(importi) != len(campagne):
            raise CircuitBreakerBudget("la politica ha restituito un numero errato di importi")
        for x in importi:
            _int_non_neg(x, "importo_allocato")
        if sum(importi) > budget_cents:              # circuit breaker finanziario
            raise CircuitBreakerBudget(
                f"overspend: allocati {sum(importi)} > budget {budget_cents}")
        return [AllocazioneCampagna(c.id, x) for c, x in zip(campagne, importi)]

    def contenuto(self, campagna: Campagna) -> str:
        return self.gen.genera(campagna)             # testo, mai denaro


def crea_advertising(politica: Optional[PoliticaBudget] = None,
                     generatore: Optional[GeneratoreContenuti] = None) -> MotoreAdvertising:
    return MotoreAdvertising(politica or PoliticaBudgetProporzionale(), generatore)
