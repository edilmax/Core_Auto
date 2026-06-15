"""
CORE_AUTO - Fase 43: Motore commissionale del Core (prima pietra del Fractal Bridge).

Questo modulo NON e' "la commissione di Mango": e' una LIBRERIA del Core che
espone una POLITICA COMMERCIALE iniettabile via Registry. Lo stesso Core puo'
servire:
  - Motore B (Mango)        -> PoliticaRanaInversa (Pioniere a tempo, cricchetto)
  - Motore A (Tavola Prive) -> PoliticaQuotaFissa  (fee/quota per prenotazione)
  - Motori futuri (C, D...) -> qualunque PoliticaCommerciale registrata

Logica convergente (vincitrice del ragionamento d'ingegneria):
  1. CRICCHETTO STRUTTURALE "non sale MAI" -> il tasso di lealta' puo' solo
     scendere (per anzianita'+volume+repeat) e NON scende mai sotto il break-even
     (vincolo validato in costruzione: floor_bps >= break_even_minimo_bps).
  2. CREDITO PIONIERE A TEMPO -> sconto di penetrazione (es. 3%) applicato SOLO
     nella finestra iniziale; e' un costo di acquisizione (CAC) limitato e
     trasparente, separato dal tasso strutturale. Alla scadenza si paga il tasso
     di lealta' gia' sceso. NON e' una "promo nascosta che risale" (trucco OTA):
     il cricchetto strutturale resta monotono e la glide-path e' dichiarata.
  3. PSP PASS-THROUGH ESPLICITO -> la fee del payment provider (Stripe/PayPal) e'
     una voce SEPARATA e visibile, non sepolta nella commissione. Cosi' il margine
     reale e' misurabile e il floor e' validabile contro il break-even vero.

Jurisdiction-agnostic: nessuna regola fiscale/IVA EU cablata. La tassa sulla
commissione e' in basis-point da CONFIG (default 0 = offshore). La valuta e' solo
un'etichetta: la matematica e' sempre in minor-unit interi (centesimi, fase17).

Denaro: SEMPRE centesimi interi, mai float, mai delegato all'LLM (estende fase17).
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Optional

from fase17_money import valida_split

BPS_DENOM = 10000  # 100% = 10000 basis point


def _int_non_neg(valore, nome: str) -> int:
    if not isinstance(valore, int) or isinstance(valore, bool):
        raise ValueError(f"{nome} deve essere int (no bool/float)")
    if valore < 0:
        raise ValueError(f"{nome} negativo non ammesso")
    return valore


def commissione_cents(importo_cents: int, bps: int) -> int:
    """Applica un tasso in basis-point a un importo in centesimi, restituendo
    centesimi interi (Decimal HALF_UP, mai float). Aritmetica esatta stile fase17.
    """
    _int_non_neg(importo_cents, "importo_cents")
    _int_non_neg(bps, "bps")
    return int((Decimal(importo_cents) * Decimal(bps) / Decimal(BPS_DENOM)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


# ───────────────────────── Config di dominio ────────────────────────────────
@dataclass(frozen=True)
class Giurisdizione:
    """Config fiscale jurisdiction-agnostic. La tassa sulla commissione viene
    SOLO da qui (default 0 = nessun valore EU hardcoded). Cambiare giurisdizione
    (IT -> Cambogia/APAC) = cambiare questa config, zero modifiche al codice."""
    codice: str = "GLOBAL"
    valuta: str = ""                  # etichetta; la math resta in minor-unit interi
    tassa_commissione_bps: int = 0    # IVA/GST sulla commissione, in bps, da config

    def __post_init__(self):
        _int_non_neg(self.tassa_commissione_bps, "tassa_commissione_bps")
        if self.tassa_commissione_bps >= BPS_DENOM:
            raise ValueError("tassa_commissione_bps fuori range [0,10000)")


@dataclass(frozen=True)
class MetricheHost:
    """Segnali di fedelta' di un host (per il motore di discesa)."""
    mesi_attivo: int = 0
    prenotazioni: int = 0
    repeat_guest: int = 0

    def __post_init__(self):
        _int_non_neg(self.mesi_attivo, "mesi_attivo")
        _int_non_neg(self.prenotazioni, "prenotazioni")
        _int_non_neg(self.repeat_guest, "repeat_guest")


@dataclass(frozen=True)
class StatoCommissione:
    """Stato persistito del cricchetto: il miglior (piu' basso) tasso di lealta'
    mai raggiunto, in bps. E' il cuore della garanzia 'non sale mai'."""
    bps_lealta: int


# ───────────────────────── PSP pass-through ─────────────────────────────────
class PSP(ABC):
    @abstractmethod
    def costo_cents(self, importo_cents: int) -> int:
        """Fee del payment provider su un incasso (centesimi interi)."""


@dataclass(frozen=True)
class PSPStandard(PSP):
    """Fee a due componenti (variabile bps + fissa), modello Stripe/PayPal.
    Es. Stripe EU ~ bps=150 (1.5%) + 25 cent. Tutto da config, niente hardcode."""
    bps: int = 0
    fisso_cents: int = 0

    def __post_init__(self):
        _int_non_neg(self.bps, "psp.bps")
        _int_non_neg(self.fisso_cents, "psp.fisso_cents")

    def costo_cents(self, importo_cents: int) -> int:
        return commissione_cents(importo_cents, self.bps) + self.fisso_cents


# ───────────────────────── Politiche commerciali ────────────────────────────
class PoliticaCommerciale(ABC):
    """Contratto che ogni motore inietta. Separa il MECCANISMO (il Core) dalla
    POLITICA (regola commerciale del singolo verticale)."""

    @abstractmethod
    def stato_iniziale(self) -> StatoCommissione: ...

    @abstractmethod
    def evolvi(self, stato: StatoCommissione, metriche: MetricheHost) -> StatoCommissione:
        """Avanza lo stato del cricchetto (non puo' mai salire)."""

    @abstractmethod
    def commissione_cents(self, totale_cents: int, stato: StatoCommissione,
                          metriche: MetricheHost) -> int:
        """Commissione lorda in centesimi, secondo la regola del verticale."""

    @abstractmethod
    def descrizione(self) -> str: ...


@dataclass(frozen=True)
class PoliticaRanaInversa(PoliticaCommerciale):
    """Mango: scala discendente multifattore + cricchetto + Credito Pioniere a tempo.

    tasso_lealta: parte da cap_bps, scende per (mesi*peso + prenotazioni*peso +
    repeat*peso) verso floor_bps. Il floor e' il break-even strutturale e NON puo'
    essere impostato sotto break_even_minimo_bps (validato). Il cricchetto rende
    il tasso di lealta' monotono non-crescente.

    Credito Pioniere: nella finestra (mesi_attivo <= mesi_pioniere) il tasso
    EFFETTIVO scende a tasso_pioniere_bps (es. 3%), un CAC limitato e a tempo.
    Fuori finestra si paga il tasso di lealta' (>= break-even). Il tasso pioniere
    PUO' essere sotto il break-even di proposito (perdita di acquisizione bounded).
    """
    cap_bps: int = 700
    mid_bps: int = 500
    floor_bps: int = 400               # break-even strutturale (sostenibile per sempre)
    break_even_minimo_bps: int = 400
    soglia_mid: int = 40
    soglia_floor: int = 100
    peso_mesi: int = 5
    peso_prenotazioni: int = 1
    peso_repeat: int = 10
    tasso_pioniere_bps: int = 300      # 3% effettivo nella finestra di penetrazione
    mesi_pioniere: int = 12

    def __post_init__(self):
        for nome in ("cap_bps", "mid_bps", "floor_bps", "break_even_minimo_bps",
                     "soglia_mid", "soglia_floor", "peso_mesi", "peso_prenotazioni",
                     "peso_repeat", "tasso_pioniere_bps", "mesi_pioniere"):
            _int_non_neg(getattr(self, nome), nome)
        if not (self.cap_bps >= self.mid_bps >= self.floor_bps):
            raise ValueError("scaglioni non discendenti: serve cap >= mid >= floor")
        if self.floor_bps < self.break_even_minimo_bps:
            raise ValueError(
                "floor strutturale sotto il break-even: insostenibile "
                f"({self.floor_bps} < {self.break_even_minimo_bps})")
        if self.cap_bps >= BPS_DENOM:
            raise ValueError("cap_bps fuori range")
        if not (self.soglia_mid <= self.soglia_floor):
            raise ValueError("soglie non ordinate: soglia_mid <= soglia_floor")

    def _tier(self, m: MetricheHost) -> int:
        score = (m.mesi_attivo * self.peso_mesi + m.prenotazioni * self.peso_prenotazioni
                 + m.repeat_guest * self.peso_repeat)
        return self.cap_bps if score < self.soglia_mid else (
            self.mid_bps if score < self.soglia_floor else self.floor_bps)

    def stato_iniziale(self) -> StatoCommissione:
        return StatoCommissione(self.cap_bps)

    def evolvi(self, stato: StatoCommissione, metriche: MetricheHost) -> StatoCommissione:
        nuovo = min(self._tier(metriche), stato.bps_lealta)   # cricchetto: non sale
        nuovo = max(nuovo, self.floor_bps)                    # mai sotto break-even
        return StatoCommissione(nuovo)

    def in_finestra_pioniere(self, metriche: MetricheHost) -> bool:
        return metriche.mesi_attivo <= self.mesi_pioniere

    def bps_effettivo(self, stato: StatoCommissione, metriche: MetricheHost) -> int:
        if self.in_finestra_pioniere(metriche):
            return min(self.tasso_pioniere_bps, stato.bps_lealta)
        return stato.bps_lealta

    def commissione_cents(self, totale_cents, stato, metriche) -> int:
        return commissione_cents(totale_cents, self.bps_effettivo(stato, metriche))

    def descrizione(self) -> str:
        return (f"RanaInversa cap={self.cap_bps} floor={self.floor_bps} "
                f"pioniere={self.tasso_pioniere_bps}bps/{self.mesi_pioniere}m")


@dataclass(frozen=True)
class PoliticaQuotaFissa(PoliticaCommerciale):
    """Tavola Prive: fee fissa (centesimi) + eventuale quota percentuale (bps),
    senza cricchetto. Mostra che lo STESSO Core regge regole commerciali distanti."""
    quota_bps: int = 0
    quota_fissa_cents: int = 0

    def __post_init__(self):
        _int_non_neg(self.quota_bps, "quota_bps")
        _int_non_neg(self.quota_fissa_cents, "quota_fissa_cents")
        if self.quota_bps >= BPS_DENOM:
            raise ValueError("quota_bps fuori range")

    def stato_iniziale(self) -> StatoCommissione:
        return StatoCommissione(self.quota_bps)

    def evolvi(self, stato, metriche) -> StatoCommissione:
        return stato                      # fissa: non evolve

    def commissione_cents(self, totale_cents, stato, metriche) -> int:
        comm = commissione_cents(totale_cents, self.quota_bps) + self.quota_fissa_cents
        return min(comm, totale_cents)    # mai oltre l'incasso

    def descrizione(self) -> str:
        return f"QuotaFissa {self.quota_bps}bps+{self.quota_fissa_cents}c"


# ───────────────────────── Ripartizione (decomposizione) ────────────────────
@dataclass(frozen=True)
class Ripartizione:
    """Scomposizione trasparente di un incasso. Invariante: commissione + netto_host
    == totale (validato). netto_piattaforma puo' essere < 0 nella finestra Pioniere
    (CAC bounded e voluto): in_perdita lo segnala per il monitoraggio."""
    totale_cents: int
    commissione_cents: int            # quota lorda della piattaforma
    costo_psp_cents: int              # fee PSP pass-through (esplicita)
    tassa_commissione_cents: int      # tassa giurisdizione sulla commissione
    netto_host_cents: int             # totale - commissione
    netto_piattaforma_cents: int      # commissione - psp - tassa (margine reale)

    @property
    def in_perdita(self) -> bool:
        return self.netto_piattaforma_cents < 0


@dataclass(frozen=True)
class ConfigMotore:
    """Config iniettata per-istanza (il 'bundle' del Fractal Bridge). Ogni motore
    riceve la propria politica, giurisdizione, PSP e il PROPRIO namespace datastore
    (isolamento: un motore non puo' ottenere il namespace di un altro)."""
    motore_id: str
    politica: PoliticaCommerciale
    giurisdizione: Giurisdizione = Giurisdizione()
    psp: Optional[PSP] = None
    datastore_namespace: str = ""

    def __post_init__(self):
        if not self.motore_id:
            raise ValueError("motore_id obbligatorio")


def ripartisci(cfg: ConfigMotore, totale_cents: int, stato: StatoCommissione,
               metriche: MetricheHost) -> Ripartizione:
    """Calcola la ripartizione completa di un incasso per un motore iniettato."""
    _int_non_neg(totale_cents, "totale_cents")
    comm = cfg.politica.commissione_cents(totale_cents, stato, metriche)
    if not (0 <= comm <= totale_cents):
        raise ValueError(f"commissione fuori range [0,{totale_cents}]: {comm}")
    netto_host = totale_cents - comm
    costo_psp = cfg.psp.costo_cents(totale_cents) if cfg.psp else 0
    tassa = commissione_cents(comm, cfg.giurisdizione.tassa_commissione_bps)
    netto_piattaforma = comm - costo_psp - tassa
    valida_split(totale_cents, comm, netto_host)   # invariante duro: comm+netto==totale
    return Ripartizione(totale_cents, comm, costo_psp, tassa, netto_host, netto_piattaforma)


# ───────────────────────── Registry (plug-and-play) ─────────────────────────
class RegistroMotori:
    """Registry del Fractal Bridge: mappa motore_id -> ConfigMotore. Garantisce
    l'iniezione delle config per-istanza e l'ISOLAMENTO del namespace datastore:
    due motori non possono condividere lo stesso namespace, e un motore puo'
    ottenere SOLO la propria config (per id). E' la 'presa di corrente' in cui i
    motori presenti e futuri si innestano senza toccare l'infrastruttura base."""

    def __init__(self):
        self._motori: Dict[str, ConfigMotore] = {}

    def registra(self, cfg: ConfigMotore) -> None:
        if cfg.motore_id in self._motori:
            raise ValueError(f"motore gia' registrato: {cfg.motore_id}")
        if cfg.datastore_namespace:
            for altro in self._motori.values():
                if altro.datastore_namespace == cfg.datastore_namespace:
                    raise ValueError(
                        f"namespace datastore in conflitto: {cfg.datastore_namespace}")
        self._motori[cfg.motore_id] = cfg

    def ottieni(self, motore_id: str) -> ConfigMotore:
        if motore_id not in self._motori:
            raise KeyError(f"motore non registrato: {motore_id}")
        return self._motori[motore_id]

    def motori(self) -> tuple:
        return tuple(self._motori.keys())


# ───────────────────────── Factory da config/env ────────────────────────────
def giurisdizione_da_env(env: Optional[dict] = None) -> Giurisdizione:
    """Costruisce la giurisdizione da env (jurisdiction-agnostic). Default tassa 0:
    nessun valore EU hardcoded. IT -> COMMISSION_TAX_BPS=2200 nel .env, KH -> 0."""
    env = env if env is not None else os.environ
    return Giurisdizione(
        codice=env.get("JURISDICTION_CODE", "GLOBAL"),
        valuta=env.get("JURISDICTION_CURRENCY", ""),
        tassa_commissione_bps=int(env.get("COMMISSION_TAX_BPS", "0")),
    )


def politica_da_config(d: dict) -> PoliticaCommerciale:
    """Costruisce una PoliticaCommerciale da un dict di config (Registry-driven)."""
    tipo = d.get("tipo", "rana_inversa")
    if tipo == "rana_inversa":
        campi = ("cap_bps", "mid_bps", "floor_bps", "break_even_minimo_bps",
                 "soglia_mid", "soglia_floor", "peso_mesi", "peso_prenotazioni",
                 "peso_repeat", "tasso_pioniere_bps", "mesi_pioniere")
        return PoliticaRanaInversa(**{k: d[k] for k in campi if k in d})
    if tipo == "quota_fissa":
        campi = ("quota_bps", "quota_fissa_cents")
        return PoliticaQuotaFissa(**{k: d[k] for k in campi if k in d})
    raise ValueError(f"politica sconosciuta: {tipo!r}")
