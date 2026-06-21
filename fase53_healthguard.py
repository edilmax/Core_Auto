"""
CORE_AUTO - Fase 53: Health-guard / Circuit del funnel Mango (self-governance).

Il funnel ora si auto-osserva (MetricheFunnel, fase52). Questo modulo chiude l'anello
di controllo: legge le metriche, ne valuta la SALUTE e — se il funnel degenera —
apre un CIRCUITO che lo mette in PAUSA (fail-closed, auto-preservazione), poi lo
riapre da solo quando la salute torna stabile. Mango impara a fermarsi quando si
rompe, senza un umano nel loop.

Due pezzi:
  - `valuta_salute(metriche, politica)` -> Diagnosi PURA (sano|degradato|critico):
    failure-rate per stadio oltre soglia o conversion-rate sotto il floor = critico;
    sotto `min_campione` cicli NON si giudica (niente trip su rumore statistico).
  - `CircuitoFunnel`: macchina a stati chiuso->aperto->semiaperto con cooldown e
    recovery (clock iniettabile). `consenti()` dice se il funnel puo' girare.

Vincitrice del benchmark (3 varianti x 10 stress, stream con outage + rumore):
V3 'cooldown + semiaperto con isteresi'. Blocca durante l'outage, recupera quando
la salute si stabilizza, e NON sfarfalla sul rumore. Le altre 2 (istantanea =
flapping a ogni blip; latch = non recupera mai, uccide il funnel su un guasto
transitorio) sono instabili o troppo conservative.

SOPRAVVIVENZA TOTALE: default-OFF (env MANGO_HEALTHGUARD); spento = pura osservabilita'
(`consenti()` sempre True, lo stato non si muove). Soglie validate; metriche
duck-typed (qualsiasi oggetto MetricheFunnel-like, anche parziale).
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple

logger = logging.getLogger("core_auto.healthguard")

_ENV_FLAG = "MANGO_HEALTHGUARD"

CHIUSO = "chiuso"          # funnel attivo
APERTO = "aperto"          # funnel in pausa (circuito scattato)
SEMIAPERTO = "semiaperto"  # periodo di prova dopo il cooldown

SANO = "sano"
DEGRADATO = "degradato"
CRITICO = "critico"


def _frazione(v, nome):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not (0.0 <= v <= 1.0):
        raise ValueError(f"{nome} deve essere in [0,1]")
    return float(v)


@dataclass(frozen=True)
class PoliticaSalute:
    max_failure_rate_stadio: float = 0.5   # oltre questa frazione di guasti -> critico
    soglia_degrado: float = 0.8            # quota di max_* oltre cui = degradato (warning)
    min_conversion_rate: float = 0.1       # sotto questo conversion-rate -> critico
    min_campione: int = 20                 # cicli minimi prima di giudicare
    min_campione_conversioni: int = 20     # tentativi minimi prima di giudicare il CR
    cooldown_s: float = 60.0               # pausa prima di tentare il recupero

    def __post_init__(self):
        _frazione(self.max_failure_rate_stadio, "max_failure_rate_stadio")
        _frazione(self.soglia_degrado, "soglia_degrado")
        _frazione(self.min_conversion_rate, "min_conversion_rate")
        for nome in ("min_campione", "min_campione_conversioni"):
            v = getattr(self, nome)
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise ValueError(f"{nome} deve essere int >= 0")
        if not isinstance(self.cooldown_s, (int, float)) or self.cooldown_s < 0:
            raise ValueError("cooldown_s deve essere >= 0")


@dataclass(frozen=True)
class Diagnosi:
    stato: str                  # SANO | DEGRADATO | CRITICO
    motivi: Tuple[str, ...] = ()

    @property
    def sano(self) -> bool:
        return self.stato == SANO

    @property
    def critico(self) -> bool:
        return self.stato == CRITICO


def valuta_salute(metriche: Any, politica: Optional[PoliticaSalute] = None) -> Diagnosi:
    """Funzione PURA: da un MetricheFunnel-like a una Diagnosi. Non tocca stato."""
    pol = politica or PoliticaSalute()
    tot = int(getattr(metriche, "cicli_totali", 0) or 0)
    if tot < pol.min_campione:
        return Diagnosi(SANO, ("campione insufficiente",))   # non si giudica sul rumore

    motivi = []
    livello = SANO

    def _peggiora(nuovo):
        nonlocal livello
        ordine = {SANO: 0, DEGRADATO: 1, CRITICO: 2}
        if ordine[nuovo] > ordine[livello]:
            livello = nuovo

    per = getattr(metriche, "per_stadio", {}) or {}
    for nome, ms in per.items():
        eseguiti = int(getattr(ms, "eseguiti", 0) or 0)
        falliti = int(getattr(ms, "falliti", 0) or 0)
        if eseguiti <= 0:
            continue
        fr = falliti / eseguiti
        if fr > pol.max_failure_rate_stadio:
            motivi.append(f"stadio '{nome}': failure-rate {fr:.0%} > "
                          f"{pol.max_failure_rate_stadio:.0%}")
            _peggiora(CRITICO)
        elif fr >= pol.max_failure_rate_stadio * pol.soglia_degrado:
            motivi.append(f"stadio '{nome}': failure-rate {fr:.0%} in avvicinamento")
            _peggiora(DEGRADATO)

    conv_tent = int(getattr(metriche, "conversioni_tentate", 0) or 0)
    if conv_tent >= pol.min_campione_conversioni:
        cr = float(getattr(metriche, "conversion_rate", 0.0) or 0.0)
        if cr < pol.min_conversion_rate:
            motivi.append(f"conversion-rate {cr:.0%} < {pol.min_conversion_rate:.0%}")
            _peggiora(CRITICO)

    return Diagnosi(livello, tuple(motivi))


class CircuitoFunnel:
    """Macchina a stati che mette in pausa il funnel quando la salute e' critica e lo
    riapre dopo un cooldown se la salute si stabilizza (V3, isteresi)."""

    def __init__(self, politica: Optional[PoliticaSalute] = None, *,
                 clock: Callable[[], float] = time.monotonic,
                 abilitato: Optional[bool] = None) -> None:
        self._pol = politica or PoliticaSalute()
        self._clock = clock
        self._abilitato = (os.environ.get(_ENV_FLAG) == "1"
                           if abilitato is None else bool(abilitato))
        self._stato = CHIUSO
        self._aperto_a = 0.0
        self._ultima: Optional[Diagnosi] = None

    @property
    def abilitato(self) -> bool:
        return self._abilitato

    @property
    def stato(self) -> str:
        return self._stato

    @property
    def ultima_diagnosi(self) -> Optional[Diagnosi]:
        return self._ultima

    def _forse_semiaperto(self) -> None:
        if (self._stato == APERTO
                and (self._clock() - self._aperto_a) >= self._pol.cooldown_s):
            self._stato = SEMIAPERTO

    def osserva(self, metriche: Any) -> Diagnosi:
        """Valuta le metriche e aggiorna lo stato del circuito. Ritorna la Diagnosi."""
        d = valuta_salute(metriche, self._pol)
        self._ultima = d
        if not self._abilitato:
            return d                              # pura osservabilita', stato fermo
        self._forse_semiaperto()
        if d.critico:
            self._apri()
        elif self._stato == SEMIAPERTO and d.sano:
            self._stato = CHIUSO                  # recupero confermato
        return d

    def consenti(self) -> bool:
        """True se il funnel puo' girare (chiuso o in prova). Spento -> sempre True."""
        if not self._abilitato:
            return True
        self._forse_semiaperto()
        return self._stato in (CHIUSO, SEMIAPERTO)

    def _apri(self) -> None:
        if self._stato != APERTO:
            logger.warning("CircuitoFunnel APERTO: %s",
                           ", ".join(self._ultima.motivi) if self._ultima else "critico")
        self._stato = APERTO
        self._aperto_a = self._clock()

    def forza_apertura(self) -> None:
        """Pausa manuale (kill-switch operativo)."""
        if self._abilitato:
            self._apri()


def crea_circuito_funnel(politica: Optional[PoliticaSalute] = None, *,
                         clock: Callable[[], float] = time.monotonic,
                         abilitato: Optional[bool] = None) -> CircuitoFunnel:
    """Factory. `abilitato=None` -> legge l'env MANGO_HEALTHGUARD (default-off):
    spento e' pura osservabilita', non mette mai in pausa il funnel."""
    return CircuitoFunnel(politica, clock=clock, abilitato=abilitato)
