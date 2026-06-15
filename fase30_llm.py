"""
CORE_AUTO - Fase 30 / BLOCCO 4: Client LLM reale (Token Budget + Compressione).

Potenziamento del motore interno: un `ClientLLM` di livello enterprise che parla
con un modello reale ma resta governabile sotto ogni carico. Due garanzie dure:

1. TOKEN BUDGET SPIETATO: il contesto inviato NON supera MAI la finestra del
   modello, nemmeno con un singolo messaggio piu' grande dell'intera finestra
   (troncamento duro come ultima risorsa). Vincitore di un benchmark a 3 varianti
   (rifiuta-se-sfora / comprimi-senza-floor / comprimi+troncamento): solo la terza
   tiene il budget sul caso estremo (le altre o perdono tutto o sforano).

2. COMPRESSIONE INTELLIGENTE DEL CONTESTO (**Variante C**, vincitrice di un
   secondo benchmark a 3 - tronca-vecchi / ultimi-N / ancora+riassunto+coda):
   quando la chat supera la finestra, si PRESERVA l'intento iniziale (l'ancora) e
   la coda recente, RIASSUMENDO il mezzo - senza perdere l'intento principale.

Costruito SOPRA il `ResilientBrain` (FASE 25): eredita timeout duro, circuit
breaker, cache LRU e ISOLAMENTO TOTALE (l'IA giu'/lenta non crasha mai il core).
Lo `StimatoreToken` e' astratto: euristico/deterministico nei test, tokenizer
reale in prod. Isolamento: import dal solo `fase25_brain`.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence

from fase25_brain import LLMProvider, ResilientBrain

logger = logging.getLogger("core_auto.llm")

RUOLI_VALIDI = ("system", "user", "assistant")


# ─────────────────────────────────────────────────────────────────────────────
# Messaggio (unita' della conversazione)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Messaggio:
    """Un turno di conversazione. Immutabile: la compressione produce nuovi
    messaggi, non muta gli originali (riproducibilita')."""
    ruolo: str
    contenuto: str

    def __post_init__(self) -> None:
        if self.ruolo not in RUOLI_VALIDI:
            raise ValueError(f"ruolo non valido: {self.ruolo!r} (validi: {RUOLI_VALIDI})")


# ─────────────────────────────────────────────────────────────────────────────
# Stima dei token (astratta: euristica nei test, tokenizer reale in prod)
# ─────────────────────────────────────────────────────────────────────────────
class StimatoreToken(ABC):
    """Contratto: conta i token di un testo e sa troncarlo a un tetto di token.
    Possiede sia `conta` che `tronca` cosi' contare e troncare usano la STESSA
    metrica (coerenza: nessuna stima che diverge dal troncamento)."""

    overhead_msg: int = 3  # token di cornice per messaggio (ruolo/delimitatori)

    @abstractmethod
    def conta(self, testo: str) -> int: ...

    @abstractmethod
    def tronca(self, testo: str, max_token: int) -> str: ...

    def conta_messaggi(self, msgs: Sequence[Messaggio]) -> int:
        return sum(self.conta(m.contenuto) + self.overhead_msg for m in msgs)


class StimatoreEuristico(StimatoreToken):
    """~1 token ogni `char_per_token` caratteri. Deterministico, zero I/O,
    riproducibile al 100%. Sostituibile in prod con un tokenizer reale (tiktoken,
    SentencePiece) mantenendo lo stesso contratto."""

    def __init__(self, char_per_token: int = 4, overhead_msg: int = 3) -> None:
        if char_per_token <= 0:
            raise ValueError("char_per_token deve essere > 0")
        self._cpt = char_per_token
        self.overhead_msg = overhead_msg

    def conta(self, testo: str) -> int:
        return 0 if not testo else max(1, len(testo) // self._cpt)

    def tronca(self, testo: str, max_token: int) -> str:
        if max_token <= 0:
            return ""
        return testo[: self._cpt * max_token]


# ─────────────────────────────────────────────────────────────────────────────
# Budget dei token (finestra del modello - riserva per la risposta)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class BudgetToken:
    """Contabilita' della finestra del modello. `input_max` e' il tetto DURO per
    il contesto in ingresso: finestra totale meno i token riservati alla risposta
    (cosi' il modello ha sempre spazio per rispondere)."""
    finestra: int
    riserva_output: int

    def __post_init__(self) -> None:
        if self.finestra <= 0:
            raise ValueError("finestra deve essere > 0")
        if self.riserva_output < 0:
            raise ValueError("riserva_output non puo' essere negativa")
        if self.riserva_output >= self.finestra:
            raise ValueError("riserva_output deve essere < finestra")

    @property
    def input_max(self) -> int:
        return self.finestra - self.riserva_output


# ─────────────────────────────────────────────────────────────────────────────
# Compressore del contesto (Variante C + troncamento duro spietato)
# ─────────────────────────────────────────────────────────────────────────────
Riassuntore = Callable[[Sequence[Messaggio]], str]


class CompressoreContesto:
    """Riduce una conversazione entro un budget di token SENZA perdere l'intento.

    Variante C (vincitrice): preserva il/i `system`, l'ANCORA (primo messaggio
    non-system = l'intento iniziale) e la CODA recente che entra; il mezzo viene
    RIASSUNTO. Garanzia DURA: l'output sta SEMPRE entro `budget`, anche se l'unico
    messaggio e' piu' grande dell'intera finestra (troncamento a livello di
    carattere come ultima risorsa - 'spietato')."""

    def __init__(self, stimatore: StimatoreToken,
                 riassuntore: Optional[Riassuntore] = None) -> None:
        self._st = stimatore
        self._riassumi = riassuntore or self._riassunto_segnaposto

    def comprimi(self, messaggi: Sequence[Messaggio], budget: int) -> List[Messaggio]:
        msgs = list(messaggi)
        if self._st.conta_messaggi(msgs) <= budget:
            return msgs  # gia' dentro: nessuna perdita

        system = [m for m in msgs if m.ruolo == "system"][:1]
        nonsys = [m for m in msgs if m.ruolo != "system"]
        ancora = nonsys[:1]
        resto = nonsys[1:]

        candidato = list(system) + list(ancora)
        if resto:
            summary = Messaggio("system", self._riassumi(resto))
            candidato.append(summary)
            # Coda recente: aggiungi dal piu' nuovo finche' c'e' spazio.
            rem = budget - self._st.conta_messaggi(candidato)
            coda: List[Messaggio] = []
            for m in reversed(resto):
                costo = self._st.conta_messaggi([m])
                if costo <= rem:
                    coda.insert(0, m)
                    rem -= costo
                else:
                    break
            candidato.extend(coda)

        return self._forza_budget(candidato, budget)

    def _forza_budget(self, msgs: List[Messaggio], budget: int) -> List[Messaggio]:
        """Ultima risorsa SPIETATA: garantisce conta_messaggi(out) <= budget.
        Termina sempre (ogni passo riduce token verso 0 o rimuove un messaggio)."""
        out = list(msgs)
        # 1) rimuovi dal centro (preserva testa=ancora/system e coda=recente)
        while self._st.conta_messaggi(out) > budget and len(out) > 2:
            out.pop(len(out) // 2)
        # 2) tronca il contenuto piu' lungo finche' rientra
        while self._st.conta_messaggi(out) > budget and out:
            eccesso = self._st.conta_messaggi(out) - budget
            i = max(range(len(out)), key=lambda k: self._st.conta(out[k].contenuto))
            attuale = self._st.conta(out[i].contenuto)
            nuovo_testo = self._st.tronca(out[i].contenuto, max(0, attuale - eccesso))
            if nuovo_testo == out[i].contenuto:
                out.pop(i)  # non riducibile oltre (gia' vuoto) -> rimuovi
            else:
                out[i] = Messaggio(out[i].ruolo, nuovo_testo)
        return out

    @staticmethod
    def _riassunto_segnaposto(resto: Sequence[Messaggio]) -> str:
        return f"[riassunto di {len(resto)} messaggi precedenti]"


# ─────────────────────────────────────────────────────────────────────────────
# Client LLM (budget spietato + compressione, sopra il ResilientBrain)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class RispostaChat:
    """Esito di una chat. `ok=False` => testo di fallback sicuro (IA giu')."""
    testo: str
    ok: bool
    esito: str            # eredita gli esiti del ResilientBrain (llm/cache/fallback_*)
    token_input: int      # token effettivamente inviati (<= budget.input_max)
    token_originali: int  # token della conversazione prima della compressione
    compresso: bool


class ClientLLM:
    """Client LLM enterprise: impone il Token Budget in modo SPIETATO (non sfora
    MAI la finestra) e comprime il contesto in modo intelligente (Variante C)
    quando la chat eccede. Costruito SOPRA il `ResilientBrain` (FASE 25), da cui
    eredita timeout/circuit-breaker/cache/ISOLAMENTO TOTALE."""

    def __init__(self, provider: LLMProvider, budget: BudgetToken, *,
                 stimatore: Optional[StimatoreToken] = None,
                 riassuntore: Optional[Riassuntore] = None,
                 **brain_kw) -> None:
        self._brain = ResilientBrain(provider, **brain_kw)
        self._budget = budget
        self._st = stimatore or StimatoreEuristico()
        self._compressore = CompressoreContesto(self._st, riassuntore)

    def chat(self, messaggi: Sequence[Messaggio]) -> RispostaChat:
        """Assembla il contesto entro il budget (comprimendo se serve) e chiama
        l'IA in isolamento totale. Ritorna SEMPRE un RispostaChat."""
        originali = self._st.conta_messaggi(messaggi)
        compressi = self._compressore.comprimi(messaggi, self._budget.input_max)
        finale = self._st.conta_messaggi(compressi)

        # GUARDIA DURA (difesa in profondita', non un assert: regge anche con -O).
        if finale > self._budget.input_max:
            compressi = self._compressore._forza_budget(
                list(compressi), self._budget.input_max)
            finale = self._st.conta_messaggi(compressi)

        prompt = self._serializza(compressi)
        r = self._brain.genera(prompt)
        return RispostaChat(
            testo=r.testo, ok=r.ok, esito=r.esito,
            token_input=finale, token_originali=originali,
            compresso=finale < originali)

    def conta_token(self, messaggi: Sequence[Messaggio]) -> int:
        return self._st.conta_messaggi(messaggi)

    def stop(self) -> None:
        self._brain.stop()

    @staticmethod
    def _serializza(msgs: Sequence[Messaggio]) -> str:
        return "\n".join(f"{m.ruolo}: {m.contenuto}" for m in msgs)


def crea_riassuntore_llm(provider: LLMProvider, *, max_token_riassunto: int = 200,
                         **brain_kw) -> Riassuntore:
    """Factory: un riassuntore che usa un LLM (in isolamento) per riassumere il
    mezzo. Se l'IA fallisce, degrada al segnaposto deterministico (mai un crash)."""
    brain = ResilientBrain(provider, **brain_kw)

    def _riassumi(resto: Sequence[Messaggio]) -> str:
        testo = "\n".join(f"{m.ruolo}: {m.contenuto}" for m in resto)
        r = brain.genera(f"Riassumi in modo conciso, preservando l'intento:\n{testo}")
        if r.ok and r.testo:
            return f"[riassunto] {r.testo}"
        return f"[riassunto di {len(resto)} messaggi precedenti]"

    return _riassumi
