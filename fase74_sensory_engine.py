"""
CORE_AUTO - Fase 74: Sensory Engine (Sensory Score) - un nuovo linguaggio per l'alloggio.

I colossi descrivono il DOVE (location), il QUANTO (prezzo), il QUANDO (disponibilita').
Nessuno descrive COME SI SENTE l'ospite. Eppure la motivazione #1 di viaggio e' "riposare
e ricaricarsi", e la causa #1 di recensioni negative e' dormire male (rumore, aria
viziata, doccia fredda). "Il suono del lusso nel 2026 e', sempre piu', il silenzio."

Il Sensory Engine traduce misure fisiche in un PUNTEGGIO SENSORIALE comprensibile:
  Booking dice "WiFi gratuito". Noi diciamo "Silenzio 92/100, Aria certificata CO2<600".
Le dimensioni (silenzio/aria/luce/doccia/ascensore/profumo) arrivano dal Digital Twin
(fase72), dai report dell'host o dalle metriche (fase52); qui NON si misura, si
PUNTEGGIA. Compone con la vetrina (fase57, badge), il niche profiler (fase68, filtro
"sensory premium") e le recensioni (fase63).

Mappatura deterministica: ogni dimensione ha un valore IDEALE (100 punti) e un valore
PEGGIORE (0 punti); il punteggio e' l'interpolazione lineare CLAMP 0..100. Una sola
formula copre sia "piu' basso e' meglio" (rumore, CO2, deviazione doccia) sia "piu' alto
e' meglio" (lux, ore di sonno): basta scegliere ideale/peggiore. Il composito e' la
media PESATA delle SOLE dimensioni presenti (dati assenti non penalizzano, non si inventa).

VINCITRICE DEL BENCHMARK (4 modi di valutare il comfort):
  V3 'score per-dimensione interpolato + composito pesato sui presenti + badge a soglia'.
  Deterministico, configurabile (nessuna costante magica imposta), onesto coi dati
  mancanti. Le altre perdono: V1 'checkbox sì/no' = nessuna gradazione, nessun confronto;
  V2 'media non pesata su tutte le dimensioni' = penalizza chi non ha un sensore (dato
  assente = 0); V4 'punteggio ML/sentiment' = non-deterministico, a costo.

SOPRAVVIVENZA TOTALE: calcoli PURI; valore non-intero -> dimensione ignorata (fail-safe);
nessun dato -> nessun punteggio (None, mai inventato); badge solo sopra soglia
(fail-closed, niente badge mediocri); zero float, zero dipendenze.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("core_auto.sensory_engine")


def _intero(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


@dataclass(frozen=True)
class MetricaSensoriale:
    valore_ideale: int      # mappa a 100 punti
    valore_peggiore: int    # mappa a 0 punti
    peso: int = 10          # peso nel composito


# Configurazione di default (sovrascrivibile). Unita' tra parentesi.
METRICHE_DEFAULT: Dict[str, MetricaSensoriale] = {
    "silenzio": MetricaSensoriale(30, 70, peso=30),          # dB notturni (basso meglio)
    "aria": MetricaSensoriale(400, 1400, peso=25),           # CO2 ppm (basso meglio)
    "luce": MetricaSensoriale(1000, 0, peso=15),             # lux (alto meglio)
    "doccia": MetricaSensoriale(0, 1200, peso=15),           # deviazione centi-gradi (basso)
    "ascensore": MetricaSensoriale(0, 90, peso=5),           # attesa sec (basso meglio)
    "profumo": MetricaSensoriale(100, 0, peso=10),           # score 0-100 host (alto)
}

SOGLIA_ECCELLENTE = 85
SOGLIA_BUONO = 65


def _clamp(v: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, v))


class SensoryEngine:
    def __init__(self, metriche: Optional[Dict[str, MetricaSensoriale]] = None) -> None:
        self._m = dict(metriche if metriche is not None else METRICHE_DEFAULT)

    def punteggio_dimensione(self, nome: str, valore: Any) -> Optional[int]:
        """Punteggio 0..100 di una dimensione. None se sconosciuta o valore non intero."""
        cfg = self._m.get(nome)
        if cfg is None or not _intero(valore):
            return None
        den = cfg.valore_ideale - cfg.valore_peggiore
        if den == 0:
            return None
        score = (100 * (valore - cfg.valore_peggiore)) // den
        return _clamp(score)

    def punteggio_composito(self, valori: Any) -> Optional[Dict[str, Any]]:
        """Media PESATA dei punteggi delle dimensioni presenti. None se nessun dato.
        {'composito': int, 'dettaglio': {nome: score}, 'livello': str}."""
        if not isinstance(valori, dict):
            return None
        dettaglio: Dict[str, int] = {}
        somma_pesata = 0
        somma_pesi = 0
        for nome, valore in valori.items():
            score = self.punteggio_dimensione(nome, valore)
            if score is None:
                continue
            peso = self._m[nome].peso
            if peso <= 0:
                continue
            dettaglio[nome] = score
            somma_pesata += score * peso
            somma_pesi += peso
        if somma_pesi == 0:
            return None                          # nessun dato valido -> nessun punteggio
        composito = somma_pesata // somma_pesi
        return {"composito": composito, "dettaglio": dettaglio,
                "livello": self.livello(composito), "money_unit": "n/a"}

    def badge(self, nome: str, valore: Any) -> Optional[Tuple[str, int]]:
        """(livello, score) se sopra soglia 'buono'; None altrimenti (fail-closed)."""
        score = self.punteggio_dimensione(nome, valore)
        if score is None or score < SOGLIA_BUONO:
            return None
        return (self.livello(score), score)

    @staticmethod
    def livello(score: int) -> str:
        if score >= SOGLIA_ECCELLENTE:
            return "eccellente"
        if score >= SOGLIA_BUONO:
            return "buono"
        return "base"


def crea_sensory_engine(metriche: Optional[Dict[str, MetricaSensoriale]] = None
                        ) -> SensoryEngine:
    return SensoryEngine(metriche)
