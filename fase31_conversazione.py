"""
CORE_AUTO - Fase 31 / BLOCCO 3: Cablaggio del Cervello budget-aware (multi-turno).

Aggancia il `ClientLLM` (FASE 30, Token Budget + Compressione) al loop operativo
per gestire **centinaia di chat** in simultanea SENZA esplodere in memoria. Il
pezzo nuovo e' la `MemoriaConversazioni`: lo storico per-destinatario.

`MemoriaConversazioni` = **Variante D**, vincitrice di un benchmark a 4 varianti
(illimitata / ring-senza-cap-globale / ring+LRU-senza-ancora / ring+LRU+ancora)
sotto carico avverso (600 chat x 30 turni): l'unica LIMITATA su ENTRAMBE le
dimensioni (turni-per-chat via ring + numero-di-chat via LRU globale) E che
PRESERVA l'intento iniziale di una chat lunga e viva (l'ANCORA e' immune allo
scorrimento del ring). Le altre o esplodono in memoria o dimenticano l'intento.

`AgenteConversazionale` compone, senza modificarli, l'`AgenteIA` (intento, path
economico) e il `ClientLLM` (risposta, path con budget+compressione). Isolamento
totale ereditato: IA giu' -> fallback, mai un crash. La memoria limitata + la
compressione del ClientLLM = contesto SEMPRE entro il budget anche a regime.
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, List, Optional

from fase30_llm import Messaggio

logger = logging.getLogger("core_auto.conversazione")


# ─────────────────────────────────────────────────────────────────────────────
# Memoria conversazionale (Variante D: ancora-intento + ring recente + LRU)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class _Sessione:
    """Storico di UNA chat: l'ancora (primo turno utente = intento, immune allo
    scorrimento) + un ring buffer dei turni recenti (memoria per-chat limitata)."""
    ancora: Optional[Messaggio] = None
    recenti: Deque[Messaggio] = field(default_factory=deque)


class MemoriaConversazioni:
    """Storico per-destinatario LIMITATO su due dimensioni (Variante D):
    - `max_turni`: ring buffer dei turni recenti per chat;
    - `max_sessioni`: LRU globale sul numero di chat (le chat idle vengono
      sfrattate -> la memoria totale ha un tetto duro anche con infinite chat).
    L'ANCORA (primo turno utente) e' preservata oltre il ring: una chat lunga e
    viva non perde mai l'intento iniziale. Thread-safe."""

    def __init__(self, *, max_sessioni: int = 256, max_turni: int = 12) -> None:
        if max_sessioni <= 0 or max_turni <= 0:
            raise ValueError("max_sessioni e max_turni devono essere > 0")
        self._max_sessioni = max_sessioni
        self._max_turni = max_turni
        self._sessioni: "OrderedDict[str, _Sessione]" = OrderedDict()
        self._lock = threading.Lock()

    def registra(self, destinatario: str, ruolo: str, contenuto: str) -> None:
        """Aggiunge un turno (valida il ruolo via Messaggio). Aggiorna la LRU e
        sfratta la chat meno-recente se si supera `max_sessioni`."""
        msg = Messaggio(ruolo, contenuto)  # valida il ruolo
        with self._lock:
            s = self._sessioni.get(destinatario)
            if s is None:
                s = _Sessione(recenti=deque(maxlen=self._max_turni))
                self._sessioni[destinatario] = s
            self._sessioni.move_to_end(destinatario)
            if s.ancora is None and ruolo == "user":
                s.ancora = msg  # primo turno utente = intento (immune al ring)
            s.recenti.append(msg)
            while len(self._sessioni) > self._max_sessioni:
                self._sessioni.popitem(last=False)  # sfratta la chat piu' idle

    def cronologia(self, destinatario: str,
                   system: Optional[str] = None) -> List[Messaggio]:
        """Ricostruisce il contesto: [system] + [ancora-intento] + turni-recenti.
        L'ancora e' aggiunta solo se e' gia' uscita dal ring (niente duplicati)."""
        with self._lock:
            out: List[Messaggio] = []
            if system:
                out.append(Messaggio("system", system))
            s = self._sessioni.get(destinatario)
            if s is not None:
                self._sessioni.move_to_end(destinatario)
                if s.ancora is not None and all(m is not s.ancora for m in s.recenti):
                    out.append(s.ancora)
                out.extend(s.recenti)
            return out

    def dimentica(self, destinatario: str) -> None:
        with self._lock:
            self._sessioni.pop(destinatario, None)

    def num_sessioni(self) -> int:
        with self._lock:
            return len(self._sessioni)


# ─────────────────────────────────────────────────────────────────────────────
# Agente conversazionale (compone AgenteIA + ClientLLM + memoria)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class RispostaConversazione:
    """Esito di un turno: l'intento, la risposta budget-aware e le metriche."""
    intento: Any           # fase25_brain.Intento (duck-typed per isolamento)
    testo: str
    ok: bool
    esito: str
    token_input: int
    compresso: bool


class AgenteConversazionale:
    """Orchestratore multi-turno: tiene lo storico per-chat (limitato) e genera
    risposte ENTRO il budget. Non modifica i componenti: l'`AgenteIA` classifica
    l'intento (path economico, prompt corto), il `ClientLLM` genera la risposta
    (budget + compressione). Isolamento totale ereditato: nessun crash propagato."""

    def __init__(self, agente: Any, client: Any,
                 memoria: Optional[MemoriaConversazioni] = None, *,
                 system_prompt: Optional[str] = None) -> None:
        self._agente = agente            # duck-typed: .analizza_intento, .stop
        self._client = client            # duck-typed: .chat(msgs)->RispostaChat, .stop
        self._memoria = memoria or MemoriaConversazioni()
        self._system = system_prompt

    def rispondi(self, destinatario: str, testo: str,
                 intento: Any = None) -> RispostaConversazione:
        """Registra il turno utente, genera la risposta budget-aware sull'intero
        storico (compresso al volo) e memorizza la risposta SOLO se valida (un
        fallback non inquina il contesto futuro). `intento` puo' essere passato
        gia' calcolato (es. dal gateway) per non rianalizzare."""
        self._memoria.registra(destinatario, "user", testo)
        if intento is None:
            intento = self._agente.analizza_intento(testo)
        msgs = self._memoria.cronologia(destinatario, system=self._system)
        r = self._client.chat(msgs)
        if r.ok:
            self._memoria.registra(destinatario, "assistant", r.testo)
        return RispostaConversazione(
            intento=intento, testo=r.testo, ok=r.ok, esito=r.esito,
            token_input=r.token_input, compresso=r.compresso)

    def num_sessioni(self) -> int:
        return self._memoria.num_sessioni()

    def stop(self) -> None:
        """Ferma i componenti in isolamento (best-effort, mai un crash)."""
        for comp in (self._client, self._agente):
            try:
                comp.stop()
            except Exception:
                logger.warning("Conversazione: stop componente fallito (ignorato)",
                               exc_info=True)
