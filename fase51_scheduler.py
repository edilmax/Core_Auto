"""
CORE_AUTO - Fase 51: Scheduler/Runner del funnel Mango.

Guida l'Orchestratore (fase50) in modo RICORRENTE su una coda di lavori, sotto tre
protezioni gia' collaudate altrove:
  - QUOTA GLOBALE token (fase32 GovernatoreToken): prima di ogni ciclo chiede i
    token; se negati, il ciclo viene DIFFERITO (non eseguito) -> la spesa LLM globale
    non viene MAI sforata;
  - ISOLAMENTO per-ciclo: un ciclo che esplode non abbatte il run (compartimento
    stagno, come l'orchestratore fa con gli stadi);
  - PERSISTENZA: ogni ReportCiclo eseguito e' versato in uno store durevole
    (iniettabile; default in-memory) per osservabilita'/ripresa.

Vincitrice del benchmark (4 varianti x 10 stress test, quota sotto pressione):
V3 'differisci-e-continua'. Su quota negata salta il singolo ciclo e prosegue ->
zero sforamenti, throughput massimo ammissibile, nessun lavoro perso silenziosamente
(i differiti sono contati). Le altre 3 (greedy = sfora la quota; hard-stop = un
diniego transitorio uccide tutto il run; backoff-cieco = spreca cicli dormendo)
perdono o soldi o lavoro.

SOPRAVVIVENZA TOTALE: default-OFF (env MANGO_SCHEDULER); spento, non esegue nulla.
Nessuna eccezione propaga dal run. La quota e' opt-in (senza governatore = nessun
tetto, ma allora il chiamante se ne assume la responsabilita').
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("core_auto.scheduler_mango")

_ENV_FLAG = "MANGO_SCHEDULER"


class SchedulerError(Exception):
    """Errore di configurazione dello scheduler."""


def _int_non_neg(v, nome):
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        raise ValueError(f"{nome} deve essere int >= 0")
    return v


class StoreCicli:
    """Store durevole degli esiti-ciclo (duck-typed). Il default e' in-memory; un
    adapter SQLite/file puo' sostituirlo senza toccare lo scheduler."""

    def append(self, report: Any) -> None:               # pragma: no cover
        raise NotImplementedError

    def conteggio(self) -> int:                           # pragma: no cover
        raise NotImplementedError


class StoreCicliMemoria(StoreCicli):
    def __init__(self) -> None:
        self._cicli: List[Any] = []

    def append(self, report: Any) -> None:
        self._cicli.append(report)

    def conteggio(self) -> int:
        return len(self._cicli)

    def tutti(self) -> Tuple[Any, ...]:
        return tuple(self._cicli)


@dataclass(frozen=True)
class EsitoEsecuzione:
    abilitato: bool
    cicli_eseguiti: int = 0
    cicli_differiti: int = 0          # quota negata -> non eseguiti
    cicli_errore: int = 0             # il ciclo ha sollevato (isolato)
    report: Tuple[Any, ...] = field(default_factory=tuple)

    @property
    def cicli_totali(self) -> int:
        return self.cicli_eseguiti + self.cicli_differiti + self.cicli_errore


class SchedulerMango:
    """Esegue l'orchestratore su una coda di lavori, gated da quota e con persistenza.
    Default-OFF; isolamento per-ciclo; differisci-e-continua sulla quota (V3)."""

    def __init__(self, orchestratore: Any, *, governatore: Any = None,
                 store: Optional[StoreCicli] = None, costo_token_ciclo: int = 1000,
                 priorita: Any = None, abilitato: Optional[bool] = None) -> None:
        if orchestratore is None:
            raise SchedulerError("orchestratore obbligatorio")
        _int_non_neg(costo_token_ciclo, "costo_token_ciclo")
        self._orch = orchestratore
        self._gov = governatore
        self._store = store if store is not None else StoreCicliMemoria()
        self._costo = costo_token_ciclo
        self._priorita = priorita
        self._abilitato = (os.environ.get(_ENV_FLAG) == "1"
                           if abilitato is None else bool(abilitato))

    @property
    def abilitato(self) -> bool:
        return self._abilitato

    @property
    def store(self) -> StoreCicli:
        return self._store

    def _quota_concessa(self) -> bool:
        if self._gov is None:
            return True                                   # nessun tetto opt-in
        esito = (self._gov.acquisisci(self._costo, self._priorita)
                 if self._priorita is not None
                 else self._gov.acquisisci(self._costo))
        return bool(getattr(esito, "concesso", False))

    def esegui(self, lavori: Iterable[Dict[str, Any]], *,
               max_cicli: Optional[int] = None) -> EsitoEsecuzione:
        """Scorre `lavori` (kwargs per orchestratore.esegui_ciclo). Per ciascuno:
        chiede la quota (negata -> differito), poi esegue isolato e persiste."""
        if not self._abilitato:
            return EsitoEsecuzione(False)
        if max_cicli is not None:
            _int_non_neg(max_cicli, "max_cicli")

        eseguiti = differiti = errori = 0
        report: List[Any] = []
        for n, lavoro in enumerate(lavori):
            if max_cicli is not None and n >= max_cicli:
                break
            if not self._quota_concessa():
                differiti += 1                            # quota: differisci, continua
                continue
            try:
                r = self._orch.esegui_ciclo(**(lavoro or {}))
            except Exception as exc:                      # compartimento stagno
                logger.warning("Ciclo %d fallito (isolato): %s", n, exc)
                errori += 1
                continue
            self._store.append(r)
            report.append(r)
            eseguiti += 1
        return EsitoEsecuzione(True, eseguiti, differiti, errori, tuple(report))


def crea_scheduler(orchestratore: Any, *, governatore: Any = None,
                   store: Optional[StoreCicli] = None, costo_token_ciclo: int = 1000,
                   priorita: Any = None,
                   abilitato: Optional[bool] = None) -> SchedulerMango:
    """Factory. `abilitato=None` -> legge l'env MANGO_SCHEDULER (default-off)."""
    return SchedulerMango(orchestratore, governatore=governatore, store=store,
                          costo_token_ciclo=costo_token_ciclo, priorita=priorita,
                          abilitato=abilitato)
