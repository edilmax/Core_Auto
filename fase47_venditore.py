"""
CORE_AUTO - Fase 47: Venditore del Core (M5) - orchestratore di outreach.

Prende i lead ordinati dall'Esploratore (M4) e decide CHI contattare oggi,
producendo OutreachIntent che a valle verranno consegnati via ChannelAdapter(24)
+ Outbox(16) (astrazioni: qui NON si invia, si pianifica). Vincitrice del benchmark
(4 varianti x 10 stress test): V3 'cadenza-consensata'.

REGOLE FERREE (cablate, fail-closed):
  - GDPR: si contatta SOLO chi ha dato consenso e NON ha fatto opt-out. Stato
    mancante -> nessun consenso -> NON contattato (fail-closed).
  - Dedup: mai oltre max_tocchi contatti per lead.
  - Cadenza: rispetta un gap minimo di giorni tra due contatti (niente spam).
  - Backpressure: mai oltre la capacita' giornaliera.
  - Prioritizzazione: entro la capacita', i lead a pain-score piu' alto per primi.

SOPRAVVIVENZA TOTALE: input corrotti -> fail-closed; piano deterministico e
idempotente; nessun duplicato; fuzzing su migliaia di lead.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional


def _int_non_neg(v, nome):
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        raise ValueError(f"{nome} deve essere int >= 0")
    return v


@dataclass(frozen=True)
class Lead:
    proprieta_id: str
    pain_score: int
    canale: str
    contatto: str

    def __post_init__(self):
        if not self.proprieta_id:
            raise ValueError("proprieta_id obbligatorio")
        _int_non_neg(self.pain_score, "pain_score")
        if not self.canale or not self.contatto:
            raise ValueError("canale e contatto obbligatori")


@dataclass(frozen=True)
class StatoContatto:
    """Default = fail-closed: nessun consenso, mai contattato."""
    consenso: bool = False
    opt_out: bool = False
    tocchi: int = 0
    ultimo_giorno: Optional[int] = None

    def __post_init__(self):
        if not isinstance(self.consenso, bool) or not isinstance(self.opt_out, bool):
            raise ValueError("consenso/opt_out devono essere bool")
        _int_non_neg(self.tocchi, "tocchi")
        if self.ultimo_giorno is not None:
            _int_non_neg(self.ultimo_giorno, "ultimo_giorno")


@dataclass(frozen=True)
class OutreachIntent:
    proprieta_id: str
    canale: str
    contatto: str
    passo: int                     # numero del tocco (tocchi precedenti + 1)


class PoliticaOutreach(ABC):
    @abstractmethod
    def eleggibile(self, lead: Lead, stato: StatoContatto, giorno: int) -> bool: ...

    @abstractmethod
    def chiave_ordine(self, lead: Lead): ...

    @abstractmethod
    def descrizione(self) -> str: ...


@dataclass(frozen=True)
class PoliticaOutreachConsensata(PoliticaOutreach):
    """Vincitrice V3: GDPR + dedup + cadenza, prioritizzando il pain-score."""
    gap_giorni: int = 3
    max_tocchi: int = 4

    def __post_init__(self):
        _int_non_neg(self.gap_giorni, "gap_giorni")
        _int_non_neg(self.max_tocchi, "max_tocchi")

    def eleggibile(self, lead: Lead, stato: StatoContatto, giorno: int) -> bool:
        return (stato.consenso and not stato.opt_out
                and stato.tocchi < self.max_tocchi
                and (stato.ultimo_giorno is None
                     or giorno - stato.ultimo_giorno >= self.gap_giorni))

    def chiave_ordine(self, lead: Lead):
        return (-lead.pain_score, lead.proprieta_id)   # pain desc, poi id per spareggio

    def descrizione(self) -> str:
        return f"Consensata (gap={self.gap_giorni}g, max_tocchi={self.max_tocchi})"


class MotoreVenditore:
    """Pianifica l'outreach giornaliero in modo deterministico e fail-closed."""

    def __init__(self, politica: PoliticaOutreach):
        self.pol = politica

    def pianifica(self, leads: List[Lead], stato_per_lead: Dict[str, StatoContatto],
                  giorno: int, capacita: int) -> List[OutreachIntent]:
        _int_non_neg(giorno, "giorno")
        _int_non_neg(capacita, "capacita")
        # dedup per proprieta_id (tiene il pain piu' alto) -> mai due intent sullo stesso lead
        unici: Dict[str, Lead] = {}
        for l in leads:
            if l.proprieta_id not in unici or l.pain_score > unici[l.proprieta_id].pain_score:
                unici[l.proprieta_id] = l
        eleggibili = []
        for l in unici.values():
            st = stato_per_lead.get(l.proprieta_id, StatoContatto())   # manca -> fail-closed
            if self.pol.eleggibile(l, st, giorno):
                eleggibili.append((l, st))
        eleggibili.sort(key=lambda ls: self.pol.chiave_ordine(ls[0]))
        return [OutreachIntent(l.proprieta_id, l.canale, l.contatto, st.tocchi + 1)
                for (l, st) in eleggibili[:capacita]]


def crea_venditore(politica: Optional[PoliticaOutreach] = None) -> MotoreVenditore:
    return MotoreVenditore(politica or PoliticaOutreachConsensata())
