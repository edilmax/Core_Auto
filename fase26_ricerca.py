"""
CORE_AUTO - Fase 26 / BLOCCO 3.1: Motore di ricerca alloggi PROTETTO.

Aggancia il Cervello (Fase 25) al motore TavolaVIP del core: l'agente non si
limita a parlare, interroga il DB e tira fuori proposte REALI. L'accesso al
motore passa SEMPRE per `MotoreRicercaProtetto`, un'interfaccia che NON propaga
mai errori (isolamento totale: un DB giu' o una query difettosa diventano una
lista vuota + esito di fallback, mai un crash dell'agente).

`MotoreRicercaProtetto` = **Variante C**, vincitrice di un benchmark a 3
varianti (protetta / +cache / +cache+circuit-breaker): unica a vincere su
ENTRAMBI gli assi -> CARICO (cache: 1 query DB su 50 ripetute) e GUASTO
(circuit breaker: 5 query su 50 con DB giu'), con 0 eccezioni trapelate.

Isola: il provider reale fa solo SELECT READ-ONLY su `candidati` (riusa l'engine
TavolaVIP esistente, non lo modifica). L'orchestrazione con l'agente usa import lazy.

NB: `prezzo` qui e' la tariffa informativa del listing (float, da scraping), NON
un importo transazionale: resta fuori dal dominio "denaro in centesimi" (Fase 17).
"""
from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

logger = logging.getLogger("core_auto.ricerca")


@dataclass(frozen=True)
class CriteriRicerca:
    """Criteri di ricerca (hashable -> usabile come chiave di cache)."""
    localita: str = ""
    budget_max: float = 0.0   # 0 = nessun limite
    limite: int = 5


@dataclass(frozen=True)
class Proposta:
    titolo: str
    localita: str
    prezzo: float
    url: str
    punteggio: float


@dataclass
class RisultatoRicerca:
    proposte: List[Proposta]
    ok: bool
    esito: str  # "db" | "cache" | "fallback_errore" | "fallback_circuito"


class RicercaProvider(ABC):
    """Contratto del motore di ricerca alloggi."""

    @abstractmethod
    def cerca(self, criteri: CriteriRicerca) -> List[Proposta]: ...


class RicercaStub(RicercaProvider):
    """Provider deterministico per test: filtra un dataset in memoria."""

    def __init__(self, dati: Optional[List[Proposta]] = None, fail: bool = False) -> None:
        self._dati = dati or []
        self.fail = fail

    def cerca(self, criteri: CriteriRicerca) -> List[Proposta]:
        if self.fail:
            raise RuntimeError("motore di ricerca giu'")
        out = []
        for p in self._dati:
            if criteri.localita and criteri.localita.lower() not in p.localita.lower():
                continue
            if criteri.budget_max and p.prezzo > 0 and p.prezzo > criteri.budget_max:
                continue
            out.append(p)
        out.sort(key=lambda p: (-p.punteggio, p.prezzo if p.prezzo > 0 else 1e12))
        return out[:criteri.limite]


class RicercaTavolaVIP(RicercaProvider):
    """Provider REALE: SELECT read-only su `candidati` (engine TavolaVIP)."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def cerca(self, criteri: CriteriRicerca) -> List[Proposta]:
        conn = self._db.connessione()  # connessione-per-operazione (read-only)
        try:
            sql = ("SELECT titolo, localita, prezzo, url_candidato, punteggio "
                   "FROM candidati WHERE 1=1")
            params: List[Any] = []
            if criteri.localita:
                sql += " AND localita LIKE ?"
                params.append(f"%{criteri.localita}%")
            if criteri.budget_max and criteri.budget_max > 0:
                sql += " AND prezzo > 0 AND prezzo <= ?"
                params.append(criteri.budget_max)
            sql += (" ORDER BY punteggio DESC, "
                    "CASE WHEN prezzo > 0 THEN prezzo ELSE 999999 END LIMIT ?")
            params.append(criteri.limite)
            righe = conn.execute(sql, tuple(params)).fetchall()
        finally:
            conn.close()
        return [Proposta(titolo=r[0] or "", localita=r[1] or "",
                         prezzo=float(r[2] or 0.0), url=r[3] or "",
                         punteggio=float(r[4] or 0.0)) for r in righe]


class MotoreRicercaProtetto:
    """Interfaccia protetta al motore (Variante C): cache LRU+TTL + circuit
    breaker + isolamento totale. `cerca` ritorna SEMPRE un RisultatoRicerca."""

    def __init__(self, provider: RicercaProvider, *, cache_size: int = 128,
                 cache_ttl: float = 30.0, cb_threshold: int = 5,
                 cb_cooldown: float = 10.0) -> None:
        self._provider = provider
        self._cache_size = cache_size
        self._cache_ttl = cache_ttl
        self._cb_threshold = cb_threshold
        self._cb_cooldown = cb_cooldown
        self._fails = 0
        self._open_until = 0.0
        self._cache: "OrderedDict[CriteriRicerca, Tuple[List[Proposta], float]]" = OrderedDict()
        self._lock = threading.Lock()

    def cerca(self, criteri: CriteriRicerca) -> RisultatoRicerca:
        now = time.time()
        with self._lock:
            if self._fails >= self._cb_threshold and now < self._open_until:
                return RisultatoRicerca([], False, "fallback_circuito")
            voce = self._cache.get(criteri)
            if voce is not None and now < voce[1]:
                self._cache.move_to_end(criteri)
                return RisultatoRicerca(list(voce[0]), True, "cache")

        try:
            proposte = self._provider.cerca(criteri)
        except Exception:
            with self._lock:
                self._fails += 1
                if self._fails >= self._cb_threshold:
                    self._open_until = now + self._cb_cooldown
            logger.error("Ricerca: provider ha sollevato (-> [] fallback)", exc_info=True)
            return RisultatoRicerca([], False, "fallback_errore")

        with self._lock:
            self._fails = 0  # successo: chiude il circuito
            self._cache[criteri] = (list(proposte), now + self._cache_ttl)
            self._cache.move_to_end(criteri)
            if len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return RisultatoRicerca(proposte, True, "db")

    def stato_circuito(self) -> str:
        with self._lock:
            aperto = self._fails >= self._cb_threshold and time.time() < self._open_until
        return "open" if aperto else "closed"


def formatta_proposte(proposte: List[Proposta]) -> str:
    """Rende le proposte in testo deterministico (no LLM)."""
    if not proposte:
        return "Al momento non ho trovato alloggi adatti ai tuoi criteri."
    righe = ["Ecco alcune proposte:"]
    for i, p in enumerate(proposte, 1):
        prezzo = f" - {p.prezzo:.2f} EUR" if p.prezzo > 0 else ""
        righe.append(f"{i}. {p.titolo} ({p.localita}){prezzo}")
    return "\n".join(righe)


@dataclass
class EsitoRichiesta:
    intento: Any            # fase25_brain.Intento
    proposte: List[Proposta]
    risposta: str
    ok: bool


def gestisci_richiesta_alloggio(agente: Any, motore: MotoreRicercaProtetto,
                                testo: str, criteri: CriteriRicerca) -> EsitoRichiesta:
    """Orchestrazione: classifica l'intento e, se e' RICERCA_ALLOGGIO, interroga
    il motore protetto e propone alloggi reali; altrimenti risponde col Cervello.
    Tutto isolato: un guasto del motore -> proposte vuote + messaggio di cortesia."""
    from fase25_brain import Intento  # import lazy (isolamento tra moduli)
    intento = agente.analizza_intento(testo)
    if intento == Intento.RICERCA_ALLOGGIO:
        ris = motore.cerca(criteri)
        return EsitoRichiesta(intento, ris.proposte,
                              formatta_proposte(ris.proposte), ris.ok)
    risposta = agente.genera_risposta(testo)
    return EsitoRichiesta(intento, [], risposta.testo, risposta.ok)
