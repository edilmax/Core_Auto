"""
CORE_AUTO - Fase 94: Scheduler auto-pubblicazione campagna marketing.

Fa girare `MotoreMarketing.esegui_campagna` (fase90) DA SOLO a cadenza fissa (es. ogni
giorno), ricordando l'ultima esecuzione in modo DUREVOLE -> riparte senza ripubblicare
a raffica anche se il server si riavvia.

DESIGN (vincitrice del benchmark fra 3 varianti):
  - V1 stato-solo-in-RAM: persa al riavvio -> ripubblica ad ogni boot (SCARTATA: spam).
  - V2 sqlite conn-per-op: durevole ma pesante per UN solo timestamp (SCARTATA: overkill).
  - V3 stato-file-atomico + clock iniettato (VINCITRICE): durevole, scrittura atomica
    (temp+rename, niente file mezzo-scritto), clock iniettabile -> test deterministici
    senza dormire, no-burst garantito dal confronto con `cadenza`.

CONFINI: niente solleva (errore -> {"eseguito": False, "errore": True}); senza canali
configurati nel motore i post si generano ma non si pubblicano (gating di fase90/91).
`clock` e `store` iniettabili -> test senza rete, senza attese, deterministici.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional, Sequence

from fase90_marketing import LINGUE

logger = logging.getLogger("core_auto.scheduler_campagna")


# --------------------------------------------------------------------------- stato
class StatoMemoria:
    """Stato in RAM (per i test). Non durevole."""

    def __init__(self, iso: Optional[str] = None) -> None:
        self._iso = iso

    def leggi(self) -> Optional[str]:
        return self._iso

    def scrivi(self, iso: str) -> None:
        self._iso = iso


class StatoFile:
    """Stato durevole su file JSON. Scrittura ATOMICA (temp+rename): mai un file
    mezzo-scritto, anche se il processo muore a metà. Isolato: errore -> None/no-op."""

    def __init__(self, percorso: str) -> None:
        self._p = percorso

    def leggi(self) -> Optional[str]:
        try:
            with open(self._p, encoding="utf-8") as f:
                return (json.load(f) or {}).get("ultimo")
        except Exception:
            return None

    def scrivi(self, iso: str) -> None:
        try:
            d = os.path.dirname(self._p) or "."
            fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"ultimo": iso}, f)
                os.replace(tmp, self._p)            # atomico su POSIX e Windows
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
        except Exception:
            logger.warning("StatoFile.scrivi fallita (ISOLATA)", exc_info=True)


# ----------------------------------------------------------------------- scheduler
class SchedulerCampagna:
    """Tick idempotente per cadenza: pubblica solo se è passata `cadenza_giorni`
    dall'ultima volta. Niente burst, niente attese nei test (clock iniettato)."""

    def __init__(self, motore: Any, store: Any, *, cadenza_giorni: int = 1,
                 clock: Optional[Callable[[], datetime]] = None) -> None:
        self._m = motore
        self._store = store
        self._cad = max(1, int(cadenza_giorni))
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _deve_girare(self, ora: datetime) -> bool:
        ultimo = self._store.leggi()
        if not ultimo:
            return True
        try:
            prec = datetime.fromisoformat(ultimo)
        except Exception:
            return True                              # stato corrotto -> rigira
        return (ora - prec) >= timedelta(days=self._cad)

    def tick(self, lingue: Sequence[str] = LINGUE) -> Dict[str, Any]:
        """Esegue la campagna SE è ora; altrimenti no-op. Mai solleva."""
        ora = self._clock()
        if not self._deve_girare(ora):
            return {"eseguito": False, "motivo": "non e' ancora ora"}
        try:
            rep = self._m.esegui_campagna(lingue)
        except Exception:
            logger.warning("esegui_campagna fallita (ISOLATA)", exc_info=True)
            return {"eseguito": False, "errore": True}
        self._store.scrivi(ora.isoformat())          # consuma la finestra SOLO se ok
        rep["eseguito"] = True
        return rep

    def avvia_in_thread(self, *, intervallo_sec: float = 3600.0,
                        lingue: Sequence[str] = LINGUE) -> threading.Event:
        """Avvia un loop in un thread daemon che fa `tick()` ogni `intervallo_sec`.
        Ritorna un Event: settalo per fermare. Isolato: un tick fallito non ferma il loop."""
        stop = threading.Event()

        def _loop() -> None:
            while not stop.is_set():
                try:
                    self.tick(lingue)
                except Exception:
                    logger.warning("tick loop fallito (ISOLATO)", exc_info=True)
                stop.wait(max(1.0, intervallo_sec))

        threading.Thread(target=_loop, name="scheduler-campagna", daemon=True).start()
        return stop


def crea_scheduler_campagna(motore: Any, *, percorso: Optional[str] = None,
                            cadenza_giorni: int = 1,
                            clock: Optional[Callable[[], datetime]] = None,
                            ultimo: Optional[str] = None) -> SchedulerCampagna:
    """percorso -> stato DUREVOLE su file; altrimenti stato in RAM (`ultimo` opzionale)."""
    store = StatoFile(percorso) if percorso else StatoMemoria(ultimo)
    return SchedulerCampagna(motore, store, cadenza_giorni=cadenza_giorni, clock=clock)
