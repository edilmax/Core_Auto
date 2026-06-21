"""
CORE_AUTO - Fase 66: Tassa di soggiorno automatica (jurisdiction-agnostic).

Gli alloggi nel mondo devono riscuotere una tassa di soggiorno (city tax / tourist tax)
che varia per ogni citta': importo per-persona-per-notte, percentuale, tetto notti,
esenzioni (bambini). Un sistema GLOBALE non puo' hardcodare le regole italiane/UE: la
direttiva del progetto e' esplicita -> mai IVA/regole EU hardcoded, tassa via parametro
con default ZERO. Una giurisdizione sconosciuta NON paga una tassa inventata da noi.

La tassa e' una VOCE SEPARATA e VISIBILE (come la PSP-fee in fase43): pass-through verso
l'autorita', NON margine dell'host, NON nostra commissione. Cosi' il prezzo netto host e
il nostro incasso restano misurabili, e il guest vede chiaramente cosa paga e a chi.

Modello (copre i casi reali nel mondo), tutto in CENTESIMI INTERI:
  tassa = componente_fissa + componente_percentuale
    componente_fissa = ospiti_tassabili * min(per_persona_notte*notti_tassabili, tetto)
    componente_percentuale = percentuale_bps * imponibile_cents // 10000
  con notti_tassabili = min(notti, max_notti_tassabili) [cap notti, comune: es. 7]
       ospiti_tassabili = max(0, ospiti - esenti) [esenzioni: bambini, ecc.]
       tetto = tetto_per_persona_soggiorno_cents (alcune citta' cappano per persona).

VINCITRICE DEL BENCHMARK (4 modelli):
  V3 'regola INIETTABILE (per-persona-notte + % + cap-notti + esenti + tetto), default
  ZERO per giurisdizione ignota, interi'. Copre i modelli reali, e' configurabile per
  citta' senza toccare il codice, e non inventa MAI una tassa dove non la conosce. Le
  altre perdono: V1 'hardcode IT/EU' viola jurisdiction-agnostic ed e' errato altrove;
  V2 'solo percentuale' non modella la per-persona-per-notte (la forma piu' comune);
  V4 'percentuali float' introduce drift sui centesimi.

SOPRAVVIVENZA TOTALE: calcolo PURO e deterministico; validazione fail-closed (input non
interi/negativi -> tassa 0, mai un'eccezione); zero dipendenze; zero float.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("core_auto.tassa_soggiorno")

MAX_CENTS = 1_000_000_00


def _intero_nn(v: Any) -> bool:
    """Intero non-negativo (no bool, no float)."""
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


@dataclass(frozen=True)
class RegolaTassa:
    """Regola di una giurisdizione. Default = tutto 0 -> tassa 0 (jurisdiction-agnostic)."""
    per_persona_notte_cents: int = 0
    percentuale_bps: int = 0                       # su imponibile (prezzo)
    max_notti_tassabili: Optional[int] = None      # None = nessun cap
    tetto_per_persona_soggiorno_cents: Optional[int] = None
    valuta: str = "EUR"                            # solo etichetta


REGOLA_ZERO = RegolaTassa()


@dataclass(frozen=True)
class CalcoloTassa:
    tassa_cents: int
    componente_fissa_cents: int
    componente_percentuale_cents: int
    notti_tassabili: int
    ospiti_tassabili: int
    valuta: str = "EUR"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tassa_cents": self.tassa_cents,
            "componente_fissa_cents": self.componente_fissa_cents,
            "componente_percentuale_cents": self.componente_percentuale_cents,
            "notti_tassabili": self.notti_tassabili,
            "ospiti_tassabili": self.ospiti_tassabili,
            "valuta": self.valuta,
            "money_unit": "cents_integer",
        }


def calcola_tassa(regola: RegolaTassa, *, notti: int, ospiti: int,
                  imponibile_cents: int = 0, esenti: int = 0) -> CalcoloTassa:
    """Calcola la tassa di soggiorno. BLINDATO: input invalidi -> tassa 0 (fail-closed)."""
    if not isinstance(regola, RegolaTassa):
        regola = REGOLA_ZERO
    if not (_intero_nn(notti) and _intero_nn(ospiti)):
        return CalcoloTassa(0, 0, 0, 0, 0, getattr(regola, "valuta", "EUR"))
    imponibile = imponibile_cents if _intero_nn(imponibile_cents) else 0
    esenti = esenti if _intero_nn(esenti) else 0

    if regola.max_notti_tassabili is not None and _intero_nn(regola.max_notti_tassabili):
        notti_tass = min(notti, regola.max_notti_tassabili)
    else:
        notti_tass = notti
    ospiti_tass = max(0, ospiti - esenti)

    fissa = 0
    if _intero_nn(regola.per_persona_notte_cents) and regola.per_persona_notte_cents > 0 \
            and ospiti_tass > 0 and notti_tass > 0:
        per_persona = regola.per_persona_notte_cents * notti_tass
        tetto = regola.tetto_per_persona_soggiorno_cents
        if tetto is not None and _intero_nn(tetto):
            per_persona = min(per_persona, tetto)
        fissa = per_persona * ospiti_tass

    perc = 0
    if _intero_nn(regola.percentuale_bps) and regola.percentuale_bps > 0 and imponibile > 0:
        perc = (regola.percentuale_bps * imponibile) // 10000   # intero, no float

    tassa = fissa + perc
    if tassa > MAX_CENTS:                            # cintura anti-overflow/abuso
        tassa = MAX_CENTS
    return CalcoloTassa(tassa, fissa, perc, notti_tass, ospiti_tass, regola.valuta)


# ─────────────────────────────────────────────────────────────────────────────
# Registro delle regole per giurisdizione (citta'/locale)
# ─────────────────────────────────────────────────────────────────────────────
class RegistroTasse:
    """giurisdizione -> RegolaTassa. Giurisdizione ignota -> REGOLA_ZERO (tassa 0)."""

    def __init__(self, regole: Optional[Dict[str, RegolaTassa]] = None, *,
                 default: RegolaTassa = REGOLA_ZERO) -> None:
        self._regole = dict(regole or {})
        self._default = default

    def regola(self, giurisdizione: Any) -> RegolaTassa:
        if not isinstance(giurisdizione, str):
            return self._default
        return self._regole.get(giurisdizione.strip().lower(), self._default)

    def calcola(self, giurisdizione: Any, *, notti: int, ospiti: int,
                imponibile_cents: int = 0, esenti: int = 0) -> CalcoloTassa:
        return calcola_tassa(self.regola(giurisdizione), notti=notti, ospiti=ospiti,
                             imponibile_cents=imponibile_cents, esenti=esenti)

    @classmethod
    def da_env(cls, var: str = "TASSE_SOGGIORNO") -> "RegistroTasse":
        """Carica 'citta=ppn:maxnotti:percbps,...' (ppn = per-persona-notte cents;
        maxnotti vuoto = nessun cap). Es: 'roma=350:10:0,amsterdam=0::700'."""
        import os
        regole: Dict[str, RegolaTassa] = {}
        for riga in os.environ.get(var, "").split(","):
            riga = riga.strip()
            if "=" not in riga:
                continue
            citta, spec = riga.split("=", 1)
            parti = (spec.split(":") + ["", "", ""])[:3]
            try:
                ppn = int(parti[0]) if parti[0].strip() else 0
                maxn = int(parti[1]) if parti[1].strip() else None
                perc = int(parti[2]) if parti[2].strip() else 0
            except (ValueError, TypeError):
                continue
            if citta.strip():
                regole[citta.strip().lower()] = RegolaTassa(
                    per_persona_notte_cents=max(0, ppn),
                    max_notti_tassabili=(maxn if (maxn is None or maxn >= 0) else None),
                    percentuale_bps=max(0, perc))
        return cls(regole)


def crea_registro_tasse(regole: Optional[Dict[str, RegolaTassa]] = None) -> RegistroTasse:
    return RegistroTasse(regole)
