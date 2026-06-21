"""
CORE_AUTO - Fase 50: Orchestratore Mango (capstone end-to-end).

Cabla in UNA pipeline i 7 mattoni Mango gia' costruiti e blindati:
  esplora (fase46) -> outreach (fase47) -> advertising (fase48) -> conversione/ponte
  (fase49, che a sua volta riusa proposte fase45 + booking fase34/40).

L'orchestratore non ricalcola nulla e non tocca il denaro DIRETTAMENTE: ogni stadio
e' delegato al suo motore (duck-typed/iniettabile) e l'UNICO touchpoint col denaro
resta il Ponte (fase49), gia' fail-closed e idempotente. Mango propone; il nucleo
booking decide e incassa.

Vincitrice del benchmark (3 varianti x 10 stress test, fallimenti casuali iniettati):
V3 'isolata-con-report'. Ogni stadio gira in un compartimento stagno: se un motore
solleva, l'errore viene CATTURATO nel report e gli altri stadi proseguono; il loop
non si schianta MAI e l'esito dello stadio-denaro non va perso. Le altre 2 (fail-fast
= un singolo errore abbatte l'intero ciclo; swallow-silent = nasconde i guasti e
rende il sistema cieco) perdono o lavoro o osservabilita'.

SOPRAVVIVENZA TOTALE: default-OFF (env MANGO_ORCHESTRATORE); spento, NON tocca alcun
motore (nemmeno il ponte). Stadi opzionali: gira solo cio' che ha sia il motore sia
l'input. Nessuna eccezione propaga dal ciclo (tranne configurazione errata).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("core_auto.orchestratore_mango")

_ENV_FLAG = "MANGO_ORCHESTRATORE"


class OrchestratoreError(Exception):
    """Errore di configurazione dell'orchestratore."""


@dataclass(frozen=True)
class EsitoStadio:
    nome: str
    ok: bool
    risultato: Any = None
    errore: str = ""


@dataclass(frozen=True)
class ReportCiclo:
    """Esito completo e osservabile di un ciclo del funnel."""
    abilitato: bool
    stadi: Tuple[EsitoStadio, ...] = ()

    def stadio(self, nome: str) -> Optional[EsitoStadio]:
        return next((s for s in self.stadi if s.nome == nome), None)

    @property
    def ok_totale(self) -> bool:
        return self.abilitato and all(s.ok for s in self.stadi)

    @property
    def errori(self) -> List[EsitoStadio]:
        return [s for s in self.stadi if not s.ok]

    @property
    def conversione(self) -> Any:
        s = self.stadio("conversione")
        return s.risultato if s is not None else None


class OrchestratoreMango:
    """Coordina il funnel Mango. Default-OFF; ogni stadio e' isolato (V3): un guasto
    di un motore non abbatte il ciclo ne' contamina lo stadio-denaro."""

    def __init__(self, *, esploratore: Any = None, venditore: Any = None,
                 advertising: Any = None, ponte: Any = None,
                 abilitato: Optional[bool] = None) -> None:
        self._esploratore = esploratore
        self._venditore = venditore
        self._advertising = advertising
        self._ponte = ponte
        self._abilitato = (os.environ.get(_ENV_FLAG) == "1"
                           if abilitato is None else bool(abilitato))

    @property
    def abilitato(self) -> bool:
        return self._abilitato

    @staticmethod
    def _isola(nome: str, fn: Callable[[], Any]) -> EsitoStadio:
        try:
            return EsitoStadio(nome, True, risultato=fn())
        except Exception as exc:                       # compartimento stagno
            logger.warning("Stadio '%s' fallito (isolato): %s", nome, exc)
            return EsitoStadio(nome, False, errore=f"{type(exc).__name__}: {exc}")

    def esegui_ciclo(self, *, fonti: Optional[List[Any]] = None,
                     leads: Optional[List[Any]] = None,
                     stato_per_lead: Optional[Dict[str, Any]] = None,
                     giorno: int = 0, capacita: int = 0,
                     budget_cents: Optional[int] = None,
                     campagne: Optional[List[Any]] = None,
                     conversione: Any = None) -> ReportCiclo:
        """Esegue gli stadi per cui esistono SIA il motore SIA l'input. Lo stadio
        'conversione' (denaro) e' l'ultimo e l'unico a toccare il booking, via Ponte."""
        if not self._abilitato:
            return ReportCiclo(False)                  # inerte: nessun motore toccato

        stadi: List[EsitoStadio] = []
        if self._esploratore is not None and fonti is not None:
            stadi.append(self._isola(
                "esplora", lambda: self._esploratore.esplora(fonti)))
        if self._venditore is not None and leads is not None:
            stadi.append(self._isola(
                "outreach", lambda: self._venditore.pianifica(
                    leads, stato_per_lead or {}, giorno, capacita)))
        if (self._advertising is not None and campagne is not None
                and budget_cents is not None):
            stadi.append(self._isola(
                "advertising", lambda: self._advertising.pianifica(
                    budget_cents, campagne)))
        if self._ponte is not None and conversione is not None:
            # UNICO touchpoint col denaro: il Ponte e' gia' fail-closed e idempotente.
            stadi.append(self._isola(
                "conversione", lambda: self._ponte.aggancia(conversione)))
        return ReportCiclo(True, tuple(stadi))


def crea_orchestratore(*, esploratore: Any = None, venditore: Any = None,
                       advertising: Any = None, ponte: Any = None,
                       abilitato: Optional[bool] = None) -> OrchestratoreMango:
    """Factory. `abilitato=None` -> legge l'env MANGO_ORCHESTRATORE (default-off):
    il funnel resta spento finche' non lo accendi esplicitamente."""
    return OrchestratoreMango(esploratore=esploratore, venditore=venditore,
                              advertising=advertising, ponte=ponte,
                              abilitato=abilitato)
