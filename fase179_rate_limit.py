"""
CORE_AUTO - Fase 179: RATE LIMIT autenticazione (anti brute-force / spray).

Chiude il fantasma del pre-mortem: nginx frena 20 req/s per IP, ma ZERO limite
applicativo sui TENTATIVI di password -> un brute-force LENTO e distribuito passava.
Con account che muovono denaro va chiuso.

Modello: finestra scorrevole dei FALLIMENTI per chiave + LOCKOUT esponenziale.
  - `consenti(chiave)` -> (ok, attesa_sec): False se la chiave e' in lockout;
  - `fallito(chiave)`: registra un fallimento; superata la soglia nella finestra ->
    blocco per base*2^(lockout-1), fino a un tetto (il brute-force diventa inutile);
  - `riuscito(chiave)`: azzera tutto per quella chiave (il legittimo non e' penalizzato).

Le chiavi sono DUE per il login (email E ip): distribuito su tanti IP non sfonda UN
account (chiave email), e un IP solo non spruzza tanti account (chiave ip).

PURO e testabile (orologio iniettabile). MEMORIA LIMITATA: un attaccante che ruota
chiavi all'infinito non gonfia la RAM (tetto + sfratto del piu' vecchio). Thread-safe
(un lucchetto: gli accessi sono brevi). Nessuna dipendenza, nessun I/O.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Dict, List, Optional, Tuple


class RateLimiter:
    def __init__(self, *, soglia: int = 8, finestra_sec: int = 900,
                 base_blocco_sec: int = 60, max_blocco_sec: int = 3600,
                 max_chiavi: int = 20000,
                 orologio: Optional[Callable[[], float]] = None) -> None:
        # oltre `soglia` fallimenti in `finestra_sec` -> lockout; il blocco raddoppia a
        # ogni lockout successivo (base -> 2x -> 4x ...) fino a `max_blocco_sec`.
        self._soglia = max(1, int(soglia))
        self._finestra = max(1, int(finestra_sec))
        self._base = max(1, int(base_blocco_sec))
        self._max = max(self._base, int(max_blocco_sec))
        self._max_chiavi = max(100, int(max_chiavi))
        self._now = orologio or time.time
        self._lock = threading.Lock()
        # chiave -> {"fail":[ts...], "blocco_fino":ts, "lockout":n, "visto":ts}
        self._m: Dict[str, Dict] = {}

    def _rec(self, chiave: str, ora: float) -> Dict:
        r = self._m.get(chiave)
        if r is None:
            r = {"fail": [], "blocco_fino": 0.0, "lockout": 0, "visto": ora}
            self._m[chiave] = r
            self._sfratta_se_serve(ora)
        r["visto"] = ora
        return r

    def _sfratta_se_serve(self, ora: float) -> None:
        # tetto anti-DoS di memoria: se troppe chiavi, butta le meno recenti (LRU).
        if len(self._m) <= self._max_chiavi:
            return
        n_da_togliere = len(self._m) - self._max_chiavi
        piu_vecchie = sorted(self._m.items(), key=lambda kv: kv[1]["visto"])[:n_da_togliere]
        for k, _ in piu_vecchie:
            self._m.pop(k, None)

    def consenti(self, chiave: str) -> Tuple[bool, int]:
        """(ok, attesa_sec). ok=False se la chiave e' in lockout adesso."""
        if not (isinstance(chiave, str) and chiave):
            return True, 0
        with self._lock:
            ora = self._now()
            r = self._m.get(chiave)
            if r is None:
                return True, 0
            r["visto"] = ora
            if r["blocco_fino"] > ora:
                return False, int(r["blocco_fino"] - ora) + 1
            return True, 0

    def fallito(self, chiave: str) -> Tuple[bool, int]:
        """Registra un tentativo fallito. Ritorna (bloccato_ora, attesa_sec)."""
        if not (isinstance(chiave, str) and chiave):
            return False, 0
        with self._lock:
            ora = self._now()
            r = self._rec(chiave, ora)
            taglio = ora - self._finestra
            r["fail"] = [t for t in r["fail"] if t >= taglio]
            r["fail"].append(ora)
            if len(r["fail"]) >= self._soglia:
                r["lockout"] += 1
                dur = min(self._max, self._base * (2 ** (r["lockout"] - 1)))
                r["blocco_fino"] = ora + dur
                r["fail"] = []                    # riparte il conteggio dopo il blocco
                return True, int(dur)
            return False, 0

    def riuscito(self, chiave: str) -> None:
        """Successo: azzera lo stato della chiave (il legittimo non e' mai penalizzato)."""
        if isinstance(chiave, str) and chiave:
            with self._lock:
                self._m.pop(chiave, None)

    def stato(self, chiave: str) -> Dict:
        with self._lock:
            r = self._m.get(chiave)
            return dict(r) if r else {"fail": [], "blocco_fino": 0.0, "lockout": 0}


def crea_rate_limiter(**kw) -> RateLimiter:
    return RateLimiter(**kw)
