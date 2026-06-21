"""
CORE_AUTO - Fase 54: Loop/Daemon runner del funnel Mango (il pezzo connettivo).

Mette in moto, da solo, l'intera macchina costruita finora:
  ad ogni TICK -> consulta il CircuitoFunnel (fase53) come GATE; se consente, fa
  girare lo Scheduler (fase51) sui lavori della sorgente, che persiste gli esiti
  nello store durevole (fase52); poi RI-ALIMENTA le metriche al circuito (osserva)
  cosi' la salute guida i tick successivi (apertura/recupero autonomi).

Senza questo loop il health-guard resterebbe inerte: qui il funnel diventa un daemon
autonomo che si ferma quando si rompe e riparte quando guarisce, senza umano nel loop.

Vincitrice del benchmark timing (3 varianti x 10 stress, run a durata variabile):
V3 'fixed-rate NO-burst'. La cadenza non deriva (come il fixed-delay, che somma il
tempo d'esecuzione) e non accumula raffiche di recupero (come il fixed-rate puro, che
dopo un tick lento spara tick a raffica): se e' in ritardo, riparte da ora + intervallo.
Cadenza stabile sotto carico.

SOPRAVVIVENZA TOTALE: default-OFF (env MANGO_LOOP); spento non gira. clock/sleep
iniettabili (test deterministici). Tick ISOLATO: un'eccezione nel tick non abbatte il
daemon. Shutdown pulito via stop()/Event. max_tick per esecuzioni finite.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Tuple

logger = logging.getLogger("core_auto.loop_mango")

_ENV_FLAG = "MANGO_LOOP"


class LoopError(Exception):
    """Errore di configurazione del loop."""


@dataclass(frozen=True)
class EsitoTick:
    eseguito: bool                 # lo scheduler ha girato in questo tick?
    in_pausa: bool = False         # saltato perche' il circuito e' aperto
    errore: str = ""               # tick isolato che ha sollevato
    esito_scheduler: Any = None
    diagnosi: Any = None


@dataclass(frozen=True)
class ReportLoop:
    abilitato: bool
    tick: Tuple[EsitoTick, ...] = field(default_factory=tuple)

    @property
    def tick_eseguiti(self) -> int:
        return sum(1 for t in self.tick if t.eseguito)

    @property
    def tick_in_pausa(self) -> int:
        return sum(1 for t in self.tick if t.in_pausa)

    @property
    def tick_errore(self) -> int:
        return sum(1 for t in self.tick if t.errore)


class LoopMango:
    """Daemon che fa girare lo scheduler a cadenza fissa sotto il gate del circuito."""

    def __init__(self, scheduler: Any, sorgente: Callable[[], Any], *,
                 circuito: Any = None, intervallo_s: float = 60.0,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 abilitato: Optional[bool] = None) -> None:
        if scheduler is None:
            raise LoopError("scheduler obbligatorio")
        if not callable(sorgente):
            raise LoopError("sorgente deve essere callable")
        if not isinstance(intervallo_s, (int, float)) or intervallo_s < 0:
            raise LoopError("intervallo_s deve essere >= 0")
        self._sched = scheduler
        self._sorgente = sorgente
        self._circ = circuito
        self._intervallo = float(intervallo_s)
        self._clock = clock
        self._sleep = sleep
        self._abilitato = (os.environ.get(_ENV_FLAG) == "1"
                           if abilitato is None else bool(abilitato))
        self._stop = threading.Event()

    @property
    def abilitato(self) -> bool:
        return self._abilitato

    def stop(self) -> None:
        """Richiede uno shutdown pulito (il loop esce al prossimo controllo)."""
        self._stop.set()

    def _consentito(self) -> bool:
        return self._circ is None or bool(self._circ.consenti())

    def tick(self) -> EsitoTick:
        """Un singolo giro: gate -> scheduler -> ri-alimenta la salute. Isolato."""
        if not self._consentito():
            return EsitoTick(eseguito=False, in_pausa=True)
        try:
            lavori = self._sorgente()
            esito = self._sched.esegui(lavori if lavori is not None else [])
            diagnosi = None
            if self._circ is not None and hasattr(self._sched, "store"):
                diagnosi = self._circ.osserva(self._sched.store.metriche())
            return EsitoTick(eseguito=True, esito_scheduler=esito, diagnosi=diagnosi)
        except Exception as exc:                       # compartimento stagno
            logger.warning("Tick fallito (isolato): %s", exc)
            return EsitoTick(eseguito=False, errore=f"{type(exc).__name__}: {exc}")

    def esegui(self, *, max_tick: Optional[int] = None) -> ReportLoop:
        """Avvia il loop. Cadenza fixed-rate no-burst. Si ferma a max_tick o su stop()."""
        if not self._abilitato:
            return ReportLoop(False)
        if max_tick is not None and (not isinstance(max_tick, int)
                                     or isinstance(max_tick, bool) or max_tick < 0):
            raise LoopError("max_tick deve essere int >= 0")
        self._stop.clear()
        esiti: List[EsitoTick] = []
        inizio = self._clock()
        k = 0
        while not self._stop.is_set():
            if max_tick is not None and k >= max_tick:
                break
            esiti.append(self.tick())
            k += 1
            if max_tick is not None and k >= max_tick:
                break
            if self._stop.is_set():
                break
            self._attendi(inizio, k)
            # ribasa la cadenza se siamo in ritardo (no-burst)
            if self._clock() - inizio > k * self._intervallo:
                inizio = self._clock() - k * self._intervallo
        return ReportLoop(True, tuple(esiti))

    def _attendi(self, inizio: float, k: int) -> None:
        if self._intervallo <= 0:
            return
        prossimo = inizio + k * self._intervallo
        ora = self._clock()
        if prossimo > ora:
            self._sleep(prossimo - ora)


def crea_loop(scheduler: Any, sorgente: Callable[[], Any], *, circuito: Any = None,
              intervallo_s: float = 60.0,
              clock: Callable[[], float] = time.monotonic,
              sleep: Callable[[float], None] = time.sleep,
              abilitato: Optional[bool] = None) -> LoopMango:
    """Factory. `abilitato=None` -> legge l'env MANGO_LOOP (default-off)."""
    return LoopMango(scheduler, sorgente, circuito=circuito, intervallo_s=intervallo_s,
                     clock=clock, sleep=sleep, abilitato=abilitato)
