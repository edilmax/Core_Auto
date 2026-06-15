"""
CORE_AUTO - Fase 46: Esploratore del Core (M4) - property intelligence + pain-score.

Primo mattone OLTRE il cuore economico: l'acquisizione dati per il Venditore
(reverse-lead). COMPLIANCE-FIRST: ingerisce solo da fonti LECITE (API partner
ufficiali, metasearch licenziato, sito DELL'host, iCal fornito) - mai scraping
evasivo di OTA. Per ogni proprieta' calcola la PERDITA ANNUA con l'OTA (l'Escape
Analysis: 'in 12 mesi con Booking hai perso X') e un PAIN-SCORE che prioritizza i
lead piu' caldi (vincitrice benchmark V3: perdita annua x dipendenza dall'OTA).

SOPRAVVIVENZA TOTALE: dati corrotti -> fail-closed (Proprieta valida in costruzione);
fonte non lecita -> IGNORATA (compliance fail-closed); guasto di una fonte ->
ISOLATO (le altre continuano, degrado grazioso); pain-score puro -> idempotente.
Denaro in centesimi (riusa fase43). FonteProprieta e' un'astrazione iniettabile:
stub nei test, adapter reali (lazy) in produzione gated da credenziali.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

from fase43_commissione import BPS_DENOM, commissione_cents

logger = logging.getLogger("core_auto.esploratore")


def _int_non_neg(v, nome):
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        raise ValueError(f"{nome} deve essere int >= 0")
    return v


@dataclass(frozen=True)
class Proprieta:
    """Property intelligence normalizzata. fonte_lecita=False -> scartata a monte."""
    id: str
    nome: str
    prezzo_ota_cents: int
    comm_ota_bps: int
    prenotazioni_mese: int
    dipendenza_ota: int                  # 0..100 (% prenotazioni via OTA)
    fonte_lecita: bool = True

    def __post_init__(self):
        if not self.id:
            raise ValueError("id obbligatorio")
        _int_non_neg(self.prezzo_ota_cents, "prezzo_ota_cents")
        _int_non_neg(self.prenotazioni_mese, "prenotazioni_mese")
        if (not isinstance(self.comm_ota_bps, int) or isinstance(self.comm_ota_bps, bool)
                or not (0 <= self.comm_ota_bps < BPS_DENOM)):
            raise ValueError("comm_ota_bps deve essere int in [0,10000)")
        if (not isinstance(self.dipendenza_ota, int) or isinstance(self.dipendenza_ota, bool)
                or not (0 <= self.dipendenza_ota <= 100)):
            raise ValueError("dipendenza_ota deve essere int in [0,100]")
        if not isinstance(self.fonte_lecita, bool):
            raise ValueError("fonte_lecita deve essere bool")

    def perdita_annua_cents(self) -> int:
        """Escape Analysis: commissione annua lasciata all'OTA (centesimi esatti)."""
        return commissione_cents(self.prezzo_ota_cents, self.comm_ota_bps) * self.prenotazioni_mese * 12


class PoliticaPainScore(ABC):
    @abstractmethod
    def score(self, p: Proprieta) -> int: ...

    @abstractmethod
    def descrizione(self) -> str: ...


@dataclass(frozen=True)
class PainScoreMultifattore(PoliticaPainScore):
    """Vincitrice V3: perdita annua pesata per la dipendenza dall'OTA. Chi sanguina
    di piu' ED e' piu' agganciato all'OTA = lead piu' caldo."""

    def score(self, p: Proprieta) -> int:
        return p.perdita_annua_cents() * p.dipendenza_ota // 100

    def descrizione(self) -> str:
        return "Multifattore (perdita annua x dipendenza OTA)"


@dataclass(frozen=True)
class ScoredProprieta:
    proprieta: Proprieta
    pain_score: int
    perdita_annua_cents: int


class FonteProprieta(ABC):
    @abstractmethod
    def lecita(self) -> bool: ...        # compliance: la fonte e' lecita?

    @abstractmethod
    def estrai(self) -> List[Proprieta]: ...

    @abstractmethod
    def nome(self) -> str: ...


@dataclass
class StubFonteProprieta(FonteProprieta):
    """Fonte stub per i test (e per simulare guasti/illeciti)."""
    _nome: str
    proprieta: List[Proprieta] = field(default_factory=list)
    _lecita: bool = True
    _errore: Optional[Exception] = None

    def lecita(self) -> bool:
        return self._lecita

    def nome(self) -> str:
        return self._nome

    def estrai(self) -> List[Proprieta]:
        if self._errore is not None:
            raise self._errore
        return list(self.proprieta)


class MotoreEsploratore:
    """Aggrega property intelligence da fonti LECITE, isola i guasti per-fonte e
    produce lead ordinati per pain-score (decrescente)."""

    def __init__(self, pain: PoliticaPainScore):
        self.pain = pain

    def esplora(self, fonti: List[FonteProprieta]) -> List[ScoredProprieta]:
        raccolte: List[Proprieta] = []
        for f in fonti:
            if not f.lecita():                       # compliance-first
                logger.warning("Esploratore: fonte '%s' NON lecita, ignorata", f.nome())
                continue
            try:
                for p in f.estrai():
                    if p.fonte_lecita:
                        raccolte.append(p)
                    else:
                        logger.warning("Esploratore: proprieta' '%s' non lecita, scartata", p.id)
            except Exception as e:                   # isolamento: un guasto non ferma le altre
                logger.error("Esploratore: fonte '%s' ha sollevato (isolata): %s", f.nome(), e)
        return self.classifica(raccolte)

    def classifica(self, proprieta: List[Proprieta]) -> List[ScoredProprieta]:
        scored = [ScoredProprieta(p, self.pain.score(p), p.perdita_annua_cents())
                  for p in proprieta]
        # ordine stabile e deterministico: pain desc, poi id per spareggio
        scored.sort(key=lambda s: (-s.pain_score, s.proprieta.id))
        return scored


def crea_esploratore(pain: Optional[PoliticaPainScore] = None) -> MotoreEsploratore:
    return MotoreEsploratore(pain or PainScoreMultifattore())
