"""
CORE_AUTO - Fase 78: Sleep-as-a-Service (garanzia di sonno money-back).

Il mercato del sonno vale ~$136B e cresce; il wellness tourism ~$1.7T. Eppure nessuna
piattaforma di prenotazione VENDE il sonno: Booking vende camere. L'ospite non cerca
"camera a Roma", cerca "dormire 8 ore senza svegliarmi". La nostra mossa: una camera
"Sleep Optimized" con GARANZIA verificabile -> "dormi bene o ti rimborso".

Il meccanismo (deterministico, a costo zero di software):
  1. SLEEP SCORE misurato dai dati del soggiorno (durata, efficienza dal materasso
     smart se presente; silenzio, aria, temperatura dall'ambiente - riusa il Sensory
     Engine fase74 e il Digital Twin fase72);
  2. GARANZIA money-back: se lo sleep score e' sotto la soglia promessa, il CORE calcola
     un RIMBORSO (in centesimi, % configurabile) -> eseguito via fase35. Se la soglia e'
     rispettata, nessun rimborso. Se non ci sono dati, NON si paga (fail-closed: non si
     rimborsa senza prova).

Cosi' il premium della camera "Sleep Optimized" e' GIUSTIFICATO (e' garantito), e la
fiducia e' totale (la garanzia e' verificabile, non uno slogan).

VINCITRICE DEL BENCHMARK (4 modi di vendere il sonno):
  V3 'sleep score MISURATO + garanzia money-back deterministica'. Verificabile, giusta,
  giustifica il premium. Le altre perdono: V1 'vendere la camera' = nessuna garanzia,
  nessuna fiducia; V2 'garanzia soggettiva ("comfort garantito") senza misura' = non
  verificabile, dispute infinite; V4 'predizione ML del sonno' = scatola nera non-
  deterministica per decidere un rimborso (inaccettabile).

SOPRAVVIVENZA TOTALE: score PURO e deterministico (riusa fase74); garanzia fail-closed
(niente dati -> niente rimborso, non si paga senza prova); rimborso in CENTESIMI interi
dal CORE (mai dall'IA); validatori blindati. Zero dipendenze nuove.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from fase74_sensory_engine import MetricaSensoriale, SensoryEngine

logger = logging.getLogger("core_auto.sleep_guarantee")

MAX_CENTS = 1_000_000_00

# Dimensioni del sonno (valori interi). Durata in minuti, efficienza in per-mille,
# silenzio in dB, aria in CO2 ppm, temp_dev = deviazione centi-gradi dall'ottimale.
METRICHE_SONNO: Dict[str, MetricaSensoriale] = {
    "durata": MetricaSensoriale(480, 300, peso=35),       # 8h ideale, 5h peggiore
    "efficienza": MetricaSensoriale(900, 600, peso=25),   # 90% ideale, 60% peggiore
    "silenzio": MetricaSensoriale(30, 55, peso=20),       # dB
    "aria": MetricaSensoriale(500, 1200, peso=10),        # CO2 ppm
    "temp_dev": MetricaSensoriale(0, 400, peso=10),       # deviazione centi-gradi
}


def _intero_pos(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


@dataclass(frozen=True)
class PoliticaSonno:
    soglia_score: int = 80        # score promesso per soddisfare la garanzia
    rimborso_bps: int = 5000      # 50% rimborso se non rispettata


@dataclass(frozen=True)
class GaranziaSonno:
    stato: str                    # 'soddisfatta' | 'rimborso' | 'non_valutabile'
    score: Optional[int]
    rimborso_cents: int
    dettaglio: Dict[str, int]

    def as_dict(self) -> Dict[str, Any]:
        return {"stato": self.stato, "score": self.score,
                "rimborso_cents": self.rimborso_cents, "dettaglio": self.dettaglio,
                "money_unit": "cents_integer"}


class SleepGuaranteeEngine:
    def __init__(self, politica: Optional[PoliticaSonno] = None,
                 metriche: Optional[Dict[str, MetricaSensoriale]] = None) -> None:
        self._pol = politica or PoliticaSonno()
        self._engine = SensoryEngine(metriche if metriche is not None else METRICHE_SONNO)

    def sleep_score(self, metriche_soggiorno: Any) -> Optional[Dict[str, Any]]:
        """Composito 0..100 dalle metriche del soggiorno (None se nessun dato)."""
        return self._engine.punteggio_composito(metriche_soggiorno)

    def valuta_garanzia(self, prezzo_cents: int, metriche_soggiorno: Any
                        ) -> GaranziaSonno:
        """Decide la garanzia. BLINDATO: niente dati -> 'non_valutabile' (no rimborso);
        prezzo invalido -> nessun rimborso."""
        res = self.sleep_score(metriche_soggiorno)
        if res is None:
            return GaranziaSonno("non_valutabile", None, 0, {})
        score = res["composito"]
        dettaglio = res["dettaglio"]
        if score >= self._pol.soglia_score:
            return GaranziaSonno("soddisfatta", score, 0, dettaglio)
        # sotto soglia -> rimborso calcolato dal CORE
        if not (_intero_pos(prezzo_cents) and prezzo_cents <= MAX_CENTS):
            return GaranziaSonno("rimborso", score, 0, dettaglio)
        rimborso = (prezzo_cents * max(0, min(10000, self._pol.rimborso_bps))) // 10000
        return GaranziaSonno("rimborso", score, rimborso, dettaglio)


def crea_sleep_guarantee(politica: Optional[PoliticaSonno] = None,
                         metriche: Optional[Dict[str, MetricaSensoriale]] = None
                         ) -> SleepGuaranteeEngine:
    return SleepGuaranteeEngine(politica, metriche)
