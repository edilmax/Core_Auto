"""
CORE_AUTO - Fase 25 / BLOCCO 3: Il Cervello (Agente IA).

Architettura per un agente conversazionale autonomo: un `LLMProvider` astratto
(sostituibile: stub deterministico in test, modello reale in prod) avvolto da un
`ResilientBrain` che lo rende a prova di guasto e leggero sotto carico.

`ResilientBrain` = **Variante C**, vincitrice di un benchmark a 3 varianti
(diretta / retry / circuit-breaker+cache): sotto guasto sostenuto fa il minimo di
chiamate al provider (5 vs 50 vs 150), su prompt ripetuti usa la cache (1 vs 50),
e in TUTTI i casi non fa MAI trapelare un'eccezione. Questo realizza il vincolo
North Star: **se l'IA fallisce o risponde male, il sistema gestisce l'errore in
isolamento totale** (fallback sicuro, mai un crash propagato al core/ai canali).

Isola: modulo a sé; l'eventuale aggancio a canali/outbox usa import lazy.
"""
from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("core_auto.brain")


# ─────────────────────────────────────────────────────────────────────────────
# Provider LLM (astratto + stub deterministici)
# ─────────────────────────────────────────────────────────────────────────────
class LLMProvider(ABC):
    """Contratto minimo di un modello: da prompt a testo. Le implementazioni
    reali (OpenAI/Claude/locali) e gli stub di test condividono questa interfaccia."""

    @abstractmethod
    def genera(self, prompt: str) -> str: ...


class StubLLMProvider(LLMProvider):
    """Provider deterministico per test/sviluppo: una funzione prompt->testo
    (default: eco fissa). Nessun I/O, riproducibile al 100%."""

    def __init__(self, fn: Optional[Callable[[str], str]] = None,
                 risposta: str = "ok") -> None:
        self._fn = fn
        self._risposta = risposta

    def genera(self, prompt: str) -> str:
        return self._fn(prompt) if self._fn else self._risposta


@dataclass
class RisultatoLLM:
    """Esito di una chiamata al cervello. `ok=False` => testo di fallback sicuro."""
    testo: str
    ok: bool
    esito: str  # "llm" | "cache" | "fallback_errore" | "fallback_timeout" | "fallback_circuito"


class ResilientBrain:
    """Wrapper resiliente attorno a un LLMProvider (Variante C).

    Garanzie: (1) non solleva MAI -> isolamento totale; (2) circuit breaker che,
    dopo `cb_threshold` guasti, smette di martellare un provider giu' per
    `cb_cooldown` secondi; (3) cache LRU sui prompt identici; (4) timeout duro
    per chiamata (via thread) cosi' un modello lento non blocca il sistema.
    """

    def __init__(self, provider: LLMProvider, *,
                 fallback: str = "Spiacenti, il servizio non e' al momento disponibile.",
                 timeout: float = 2.0, cache_size: int = 256,
                 cb_threshold: int = 5, cb_cooldown: float = 10.0,
                 max_workers: int = 4) -> None:
        self._provider = provider
        self._fallback = fallback
        self._timeout = timeout
        self._cache_size = cache_size
        self._cb_threshold = cb_threshold
        self._cb_cooldown = cb_cooldown
        self._fails = 0
        self._open_until = 0.0
        self._cache: "OrderedDict[str, str]" = OrderedDict()
        self._lock = threading.Lock()
        self._pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="brain")

    def genera(self, prompt: str) -> RisultatoLLM:
        """Chiama il provider in modo resiliente. Ritorna SEMPRE un RisultatoLLM."""
        now = time.time()
        with self._lock:
            if self._fails >= self._cb_threshold and now < self._open_until:
                return RisultatoLLM(self._fallback, False, "fallback_circuito")
            cached = self._cache.get(prompt)
            if cached is not None:
                self._cache.move_to_end(prompt)
                return RisultatoLLM(cached, True, "cache")

        # Chiamata con timeout duro: il provider gira in un worker, noi non ci
        # blocchiamo oltre `timeout` (un modello lento non impicca il sistema).
        try:
            fut = self._pool.submit(self._provider.genera, prompt)
            testo = fut.result(timeout=self._timeout)
        except concurrent.futures.TimeoutError:
            self._registra_guasto(now)
            logger.warning("Brain: timeout del provider (-> fallback)")
            return RisultatoLLM(self._fallback, False, "fallback_timeout")
        except Exception:
            self._registra_guasto(now)
            logger.error("Brain: provider ha sollevato (-> fallback)", exc_info=True)
            return RisultatoLLM(self._fallback, False, "fallback_errore")

        if not isinstance(testo, str):
            testo = str(testo)
        with self._lock:
            self._fails = 0  # successo: chiude il circuito
            self._cache[prompt] = testo
            if len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return RisultatoLLM(testo, True, "llm")

    def _registra_guasto(self, now: float) -> None:
        with self._lock:
            self._fails += 1
            if self._fails >= self._cb_threshold:
                self._open_until = now + self._cb_cooldown

    def stato_circuito(self) -> str:
        with self._lock:
            aperto = self._fails >= self._cb_threshold and time.time() < self._open_until
        return "open" if aperto else "closed"

    def stop(self) -> None:
        self._pool.shutdown(wait=False)


# ─────────────────────────────────────────────────────────────────────────────
# Agente IA: analisi intento + generazione risposta (sopra il ResilientBrain)
# ─────────────────────────────────────────────────────────────────────────────
class Intento(Enum):
    SALUTO = "saluto"
    RICERCA_ALLOGGIO = "ricerca_alloggio"
    PRENOTAZIONE = "prenotazione"
    RECLAMO = "reclamo"
    DOMANDA_GENERICA = "domanda_generica"
    SCONOSCIUTO = "sconosciuto"


@dataclass
class RispostaAgente:
    testo: str
    ok: bool
    esito: str


class AgenteIA:
    """Agente conversazionale: classifica l'intento e genera la risposta, sempre
    in isolamento totale (LLM giu' -> intento SCONOSCIUTO + risposta di fallback,
    mai un crash). Costruito sopra il ResilientBrain (Variante C)."""

    def __init__(self, provider: LLMProvider, *, client: Optional[Any] = None,
                 **brain_kw: Any) -> None:
        self._brain = ResilientBrain(provider, **brain_kw)
        # Opzionale (default None => comportamento identico): un ClientLLM (FASE 30)
        # che impone Token Budget + compressione sulla risposta. Duck-typed
        # (.chat(msgs)->RispostaChat) per non creare un ciclo di import con fase30.
        self._client = client

    def analizza_intento(self, testo: str) -> Intento:
        """Ritorna l'intento; se il cervello non e' affidabile -> SCONOSCIUTO."""
        r = self._brain.genera(self._prompt_intento(testo))
        if not r.ok:
            return Intento.SCONOSCIUTO  # isolamento: nessuna decisione su dato inaffidabile
        return self._parse_intento(r.testo)

    def genera_risposta(self, testo: str,
                        contesto: Optional[str] = None) -> RispostaAgente:
        """Genera la risposta; `ok=False` => e' il fallback sicuro (LLM giu').
        Se e' stato iniettato un ClientLLM, la risposta passa per il suo Token
        Budget spietato + compressione del contesto (il contesto diventa un
        messaggio `system`)."""
        if self._client is not None:
            from fase30_llm import Messaggio  # import lazy (evita ciclo con fase30)
            msgs = []
            if contesto:
                msgs.append(Messaggio("system", contesto))
            msgs.append(Messaggio("user", testo))
            rc = self._client.chat(msgs)
            return RispostaAgente(testo=rc.testo, ok=rc.ok, esito=rc.esito)
        r = self._brain.genera(self._prompt_risposta(testo, contesto))
        return RispostaAgente(testo=r.testo, ok=r.ok, esito=r.esito)

    def stop(self) -> None:
        self._brain.stop()
        if self._client is not None:  # ferma anche il client iniettato (idempotente)
            try:
                self._client.stop()
            except Exception:
                logger.warning("AgenteIA: stop del client fallito (ignorato)",
                               exc_info=True)

    # --- prompt e parsing (deterministici) ---
    @staticmethod
    def _prompt_intento(testo: str) -> str:
        return ("Classifica l'intento del messaggio tra: " +
                ", ".join(i.value for i in Intento) + f"\nMessaggio: {testo}")

    @staticmethod
    def _prompt_risposta(testo: str, contesto: Optional[str]) -> str:
        base = f"Rispondi in modo professionale al messaggio: {testo}"
        return base + (f"\nContesto: {contesto}" if contesto else "")

    @staticmethod
    def _parse_intento(risposta: str) -> Intento:
        s = (risposta or "").strip().lower()
        for it in Intento:
            if it.value in s:
                return it
        return Intento.SCONOSCIUTO


def rispondi_su_canale(agente: AgenteIA, publisher: Any, channel: str,
                       recipient: str, testo: str) -> RispostaAgente:
    """Loop agente minimale: genera la risposta e la ACCODA sul canale via Outbox
    (consegna at-least-once). Import lazy per non accoppiare i moduli."""
    risposta = agente.genera_risposta(testo)
    from fase24_channels import pubblica_messaggio  # isolamento
    pubblica_messaggio(publisher, channel, recipient, risposta.testo)
    return risposta
