"""
CORE_AUTO - Fase 32 / BLOCCO 3: Governatore globale dei token (quota/costo LLM).

Chiude un'asimmetria pericolosa: il `ClientLLM` (FASE 30) e' spietato sul budget
PER-RICHIESTA ma cieco sul TOTALE. Sotto "centinaia di chat" concorrenti, N
richieste ognuna entro la sua finestra possono comunque far ESPLODERE la quota
tokens-per-minute del provider (= bolletta + 429). Il `GovernatoreToken` impone
un tetto GLOBALE condiviso, thread-safe, su tutte le chat.

Algoritmo = **Variante D**, vincitrice di un benchmark a 4 (finestra-fissa /
token-bucket / sliding-log / sliding-log+priorita') su DUE assi avversi:
- GARANZIA DURA: il totale concesso in QUALSIASI finestra mobile non supera MAI
  il limite. Finestra-fissa (burst ai bordi -> 2x) e token-bucket (capacita' +
  rate*W -> ~2x) LO VIOLANO; lo sliding-window log NO (precisione esatta).
- PRIORITA': sotto diluvio a bassa priorita', i task CRITICI devono comunque
  ottenere token. Lo sliding-log cieco li AFFAMA; le RISERVE per-priorita' (come
  fase29) tengono headroom per i critici fino al limite pieno.

Struttura interna = **V2 bucket-conservativo**, vincitrice di un SECONDO benchmark
sotto carico ESTREMO (120k req/iter x 10 iter): il log esatto a `deque` tiene un
evento per richiesta -> memoria O(eventi-in-finestra) che cresce col throughput
(picco ~68 nel test). I bucket per-secondo coalescono gli eventi -> memoria O(W)
LIMITATA (picco 2, ~34x meno) SENZA perdere la garanzia dura: il purge e'
CONSERVATIVO (scarta un bucket solo quando e' INTERAMENTE oltre la finestra), quindi
la somma e' sempre >= alla finestra reale -> non si concede MAI oltre il limite (la
variante con purge non-conservativo, testata, SFORA: scartata).

Backpressure esplicita: `acquisisci` NON blocca e ritorna se il token e' concesso
o NEGATO (quota/shed) -> il chiamante DIFFERISCE, mai uno stallo. Isola: dipende
solo da `Priorita` (fase29, solo-stdlib) -> nessun ciclo.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Dict

from fase29_backpressure import Priorita

logger = logging.getLogger("core_auto.governatore")


@dataclass(frozen=True)
class EsitoGovernatore:
    """Esito di una richiesta di token. `concesso=False` => il chiamante DIFFERISCE
    (non chiama l'LLM): cosi' la quota globale non viene MAI sforata."""
    concesso: bool
    motivo: str  # "concesso" | "quota_superata" | "shed_priorita"
    token_in_finestra: int


class GovernatoreToken:
    """Tetto GLOBALE tokens-per-finestra con sliding-window log + riserve per
    priorita' (Variante D). Garanzia: il totale concesso in QUALSIASI finestra
    mobile di `finestra_s` secondi e' <= `limite`. Thread-safe.

    Riserve: oltre la soglia di una priorita' i suoi token sono negati (shed) ->
    la priorita' ALTA conserva headroom fino al limite pieno mentre la bassa viene
    differita per prima. `clock` iniettabile per test deterministici."""

    def __init__(self, limite: int, *, finestra_s: float = 60.0,
                 soglia_bassa: float = 0.7, soglia_normale: float = 0.9,
                 bucket_s: float = 1.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if limite <= 0:
            raise ValueError("limite deve essere > 0")
        if finestra_s <= 0:
            raise ValueError("finestra_s deve essere > 0")
        if bucket_s <= 0:
            raise ValueError("bucket_s deve essere > 0")
        self._limite = limite
        self._finestra = finestra_s
        self._bucket_s = bucket_s
        self._soglie: Dict[Priorita, int] = {
            Priorita.BASSA: max(1, int(limite * soglia_bassa)),
            Priorita.NORMALE: max(1, int(limite * soglia_normale)),
            Priorita.ALTA: limite,
        }
        # Bucket per-finestra-temporale: chiave=int(t/bucket_s) -> token coalescati.
        # Memoria O(finestra/bucket) anche sotto throughput estremo (vs 1 evento/req).
        self._bucket: "OrderedDict[int, int]" = OrderedDict()
        self._somma = 0
        self._clock = clock
        self._lock = threading.Lock()
        # metriche
        self._concessi_tok = 0
        self._negati = 0
        self._warned_oversize = False  # diagnostica one-shot (vedi acquisisci)

    def _purge(self, now: float) -> None:
        """Scarta i bucket INTERAMENTE oltre la finestra (purge CONSERVATIVO: un
        bucket resta finche' anche la sua coda e' dentro W -> `_somma` sovrastima
        la finestra reale, quindi non si concede MAI oltre il limite)."""
        limite_t = now - self._finestra
        for k in list(self._bucket):
            if (k + 1) * self._bucket_s <= limite_t:
                self._somma -= self._bucket.pop(k)
            else:
                break  # chiavi crescenti (clock monotono): il primo vivo ferma il purge

    def acquisisci(self, token: int, priorita: Priorita = Priorita.NORMALE) -> EsitoGovernatore:
        """Concede `token` solo se restano sotto la soglia della priorita' nella
        finestra mobile. Non blocca MAI. Una richiesta piu' grande del limite e'
        sempre negata (va compressa prima: il ClientLLM lo fa)."""
        token = max(0, int(token))
        with self._lock:
            # Misconfigurazione: una richiesta piu' grande dell'intera quota non
            # potra' MAI essere concessa (starvation) -> diagnostica one-shot.
            if token > self._limite and not self._warned_oversize:
                self._warned_oversize = True
                logger.warning("Governatore: richiesta di %d token > limite %d: "
                               "sara' sempre negata (comprimere o alzare il limite)",
                               token, self._limite)
            now = self._clock()
            self._purge(now)
            if self._somma + token <= self._soglie[priorita]:
                k = int(now / self._bucket_s)
                self._bucket[k] = self._bucket.get(k, 0) + token
                self._somma += token
                self._concessi_tok += token
                return EsitoGovernatore(True, "concesso", self._somma)
            self._negati += 1
            motivo = "quota_superata" if self._somma + token > self._limite else "shed_priorita"
            return EsitoGovernatore(False, motivo, self._somma)

    def token_in_finestra(self) -> int:
        with self._lock:
            self._purge(self._clock())
            return self._somma

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {"concessi_tok": self._concessi_tok, "negati": self._negati,
                    "in_finestra": self._somma, "limite": self._limite,
                    "bucket_attivi": len(self._bucket)}
