"""
CORE_AUTO - Fase 29: Backpressure & Code di Priorita' (potenziamento motore interno).

Sotto picchi di traffico estremi ("centinaia di chat" -> migliaia di task), il
motore deve SOPRAVVIVERE: memoria limitata, lavoro critico protetto, nessuno
stallo del produttore. Questo modulo fornisce `MotoreBackpressure`: una coda di
lavoro a PRIORITA' con AMMISSIONE A SOGLIE per-priorita' (load shedding).

Politica = **Variante C**, vincitrice di un benchmark a 3 (illimitata / bounded
cieca / bounded+priorita') sotto picco avverso: unica con picco coda LIMITATO
(sopravvive) E 100% dei task critici ammessi (la bassa priorita' e' scartata per
prima), mentre la coda illimitata esplode in memoria e quella cieca perde i
critici.

Backpressure: `submit` e' NON bloccante e ritorna se il task e' stato ammesso o
SCARTATO -> il produttore ha feedback immediato, mai uno stallo. Isolamento: un
handler che solleva non ferma MAI il motore (conteggiato come fallito).
"""
from __future__ import annotations

import heapq
import logging
import threading
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Callable, Dict, List

logger = logging.getLogger("core_auto.backpressure")


class Priorita(IntEnum):
    """Numero piu' basso = priorita' piu' alta (ordine naturale dell'heap)."""
    ALTA = 0
    NORMALE = 1
    BASSA = 2


@dataclass(frozen=True)
class EsitoSubmit:
    ammesso: bool
    motivo: str  # "ammesso" | "scartato_backpressure"


class MotoreBackpressure:
    """Coda di lavoro a priorita' con backpressure a soglie per-priorita'.

    Soglie (frazione della capacita'): oltre la soglia di una priorita', i task
    di quella priorita' (o inferiore) vengono scartati -> il picco resta limitato
    e la priorita' ALTA ha sempre headroom fino alla capacita' piena."""

    def __init__(self, handler: Callable[[Any], None], *, capacita: int = 1000,
                 workers: int = 4, soglia_bassa: float = 0.7,
                 soglia_normale: float = 0.9) -> None:
        if capacita <= 0:
            raise ValueError("capacita deve essere > 0")
        self._handler = handler
        self._capacita = capacita
        self._workers = max(1, workers)
        self._soglie = {
            Priorita.BASSA: max(1, int(capacita * soglia_bassa)),
            Priorita.NORMALE: max(1, int(capacita * soglia_normale)),
            Priorita.ALTA: capacita,
        }
        self._heap: List = []
        self._seq = 0
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._running = False
        self._threads: List[threading.Thread] = []
        # metriche
        self._ammessi = 0
        self._scartati = 0
        self._processati = 0
        self._falliti = 0
        self._picco = 0

    def submit(self, payload: Any, priorita: Priorita = Priorita.NORMALE) -> EsitoSubmit:
        """Ammette o scarta il task secondo la soglia della sua priorita'.
        Non blocca MAI: ritorna subito l'esito (backpressure esplicita)."""
        with self._lock:
            if len(self._heap) >= self._soglie[priorita]:
                self._scartati += 1
                return EsitoSubmit(False, "scartato_backpressure")
            self._seq += 1
            heapq.heappush(self._heap, (int(priorita), self._seq, payload))
            self._ammessi += 1
            if len(self._heap) > self._picco:
                self._picco = len(self._heap)
            self._cond.notify()
            return EsitoSubmit(True, "ammesso")

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._threads = [threading.Thread(target=self._worker, daemon=True,
                                              name=f"bp-worker-{i}")
                             for i in range(self._workers)]
            for t in self._threads:
                t.start()
        logger.info("MotoreBackpressure avviato (cap=%s, workers=%s)",
                    self._capacita, self._workers)

    def _worker(self) -> None:
        while True:
            with self._cond:
                while self._running and not self._heap:
                    self._cond.wait(timeout=0.1)
                if not self._heap:
                    if not self._running:
                        return            # stop + coda vuota -> esci
                    continue
                _, _, payload = heapq.heappop(self._heap)
            # Esecuzione FUORI dal lock, isolata: un handler che solleva non
            # ferma il motore.
            try:
                self._handler(payload)
                with self._lock:
                    self._processati += 1
            except Exception:
                with self._lock:
                    self._falliti += 1
                logger.error("Backpressure: handler ha sollevato (task scartato)",
                             exc_info=True)

    def stop(self, drain: bool = True, timeout: float = 5.0) -> None:
        """Ferma il motore. drain=True: termina i task in coda; drain=False:
        scarta la coda residua e si ferma subito."""
        with self._cond:
            if not drain:
                self._scartati += len(self._heap)
                self._heap.clear()
            self._running = False
            self._cond.notify_all()
            threads = list(self._threads)
        for t in threads:
            t.join(timeout=timeout)
        logger.info("MotoreBackpressure fermato (stats=%s)", self.stats())

    def in_coda(self) -> int:
        with self._lock:
            return len(self._heap)

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {"ammessi": self._ammessi, "scartati": self._scartati,
                    "processati": self._processati, "falliti": self._falliti,
                    "picco": self._picco, "in_coda": len(self._heap)}
