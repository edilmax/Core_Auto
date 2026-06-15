"""
CORE_AUTO - Fase 44: Motore del PREZZO del Core (M2, gemello di fase43).

PoliticaPrezzo iniettabile (come PoliticaCommerciale). Vincitrice del benchmark
sotto carico (4 varianti x 10 stress test): UNICAMENTE V2 Host-Authoritative.

  PoliticaPrezzoHostAuthoritative (Mango) -> prezzo = tariffa DINAMICA dell'host
      (gia' yieldata dal suo PMS/channel-manager, letta dal NOSTRO datastore),
      inventario verificato, floor imposto, Price Circuit Breaker. L'OTA serve SOLO
      come confronto cached (informativo), MAI come input del prezzo transazionale.
  PoliticaPrezzoFisso (Tavola Prive) -> prezzo statico/menu.

Perche' NON il "Mirror-OTA": leggere il prezzo OTA live al checkout e' illegale
(diritto banche dati UE), bloccabile (bot-defense), non-deterministico (float che
varia), eredita l'inflazione commissionale OTA, ignora la verita' d'inventario e
richiede un dark-pattern (Labor Illusion). Il "Cecchino" giusto legge SOLO casa
nostra: locale, centesimi, deterministico, zero call esterne sul money-path.

SOPRAVVIVENZA TOTALE: input validati (fail-closed su corruzione/float), floor mai
violato (mai sotto-costo), Price Circuit Breaker (prezzo fuori banda -> HALT),
degrado grazioso su dati stantii, purezza -> idempotenza. Denaro: centesimi interi,
mai float (estende fase17).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

STATI_PREZZO = ("ok", "nosale")


class CircuitBreakerPrezzo(Exception):
    """Autopreservazione: prezzo fuori dalla banda di sicurezza (probabile corruzione
    dati a monte). Il motore si BLOCCA (fail-closed) invece di vendere a un prezzo
    folle al checkout."""


def _cent(valore, nome: str) -> int:
    if not isinstance(valore, int) or isinstance(valore, bool):
        raise ValueError(f"{nome} deve essere int (centesimi, no bool/float)")
    if valore < 0:
        raise ValueError(f"{nome} negativo non ammesso")
    return valore


@dataclass(frozen=True)
class ContestoPrezzo:
    """Input disponibili al checkout, TUTTI dal nostro datastore (niente terzi sul
    percorso). tariffa_host_cents = tariffa dinamica dell'host gia' ingerita.
    ota_confronto_cents = ultimo prezzo OTA visto (cached), SOLO informativo.
    prezzo_massimo_cents = banda di sicurezza (Price Circuit Breaker)."""
    tariffa_host_cents: int
    floor_host_cents: int = 0
    inventario_disponibile: bool = True
    ota_confronto_cents: Optional[int] = None
    confronto_stantio: bool = False
    prezzo_massimo_cents: Optional[int] = None

    def __post_init__(self):
        _cent(self.tariffa_host_cents, "tariffa_host_cents")
        _cent(self.floor_host_cents, "floor_host_cents")
        if self.ota_confronto_cents is not None:
            _cent(self.ota_confronto_cents, "ota_confronto_cents")
        if self.prezzo_massimo_cents is not None:
            _cent(self.prezzo_massimo_cents, "prezzo_massimo_cents")
            if self.prezzo_massimo_cents < self.floor_host_cents:
                raise ValueError("banda incoerente: prezzo_massimo < floor")
        if not isinstance(self.inventario_disponibile, bool):
            raise ValueError("inventario_disponibile deve essere bool")
        if not isinstance(self.confronto_stantio, bool):
            raise ValueError("confronto_stantio deve essere bool")


@dataclass(frozen=True)
class EsitoPrezzo:
    """Esito della risoluzione. risparmio_vs_ota_cents e confronto_affidabile sono
    SOLO informativi (etichetta 'risparmi X vs Booking'); il prezzo transazionale e'
    prezzo_cents, autoritativo e indipendente dall'OTA."""
    stato: str                                  # "ok" | "nosale"
    prezzo_cents: Optional[int] = None
    risparmio_vs_ota_cents: Optional[int] = None
    confronto_affidabile: bool = False


class PoliticaPrezzo(ABC):
    @abstractmethod
    def risolvi(self, ctx: ContestoPrezzo) -> EsitoPrezzo:
        """Risolve il prezzo al checkout da dati LOCALI (mai call esterne)."""

    @abstractmethod
    def descrizione(self) -> str: ...


@dataclass(frozen=True)
class PoliticaPrezzoHostAuthoritative(PoliticaPrezzo):
    """Mango (vincitrice benchmark): prezzo = tariffa dinamica dell'host, con floor
    imposto, inventario verificato e Price Circuit Breaker. OTA solo confronto."""

    def risolvi(self, ctx: ContestoPrezzo) -> EsitoPrezzo:
        if not ctx.inventario_disponibile:
            return EsitoPrezzo("nosale")                  # verita' d'inventario
        prezzo = max(ctx.tariffa_host_cents, ctx.floor_host_cents)  # dinamico + floor
        # Price Circuit Breaker: prezzo fuori banda -> autopreservazione (HALT)
        if ctx.prezzo_massimo_cents is not None and prezzo > ctx.prezzo_massimo_cents:
            raise CircuitBreakerPrezzo(
                f"prezzo {prezzo}c oltre il massimo {ctx.prezzo_massimo_cents}c: bloccato")
        # confronto OTA: solo se presente E non stantio -> altrimenti non affidabile
        risparmio = None
        affidabile = False
        if ctx.ota_confronto_cents is not None and not ctx.confronto_stantio:
            affidabile = True
            if ctx.ota_confronto_cents > prezzo:
                risparmio = ctx.ota_confronto_cents - prezzo
        return EsitoPrezzo("ok", prezzo, risparmio, affidabile)

    def descrizione(self) -> str:
        return "HostAuthoritative (tariffa dinamica host + floor + inventario + breaker)"


@dataclass(frozen=True)
class PoliticaPrezzoFisso(PoliticaPrezzo):
    """Tavola Prive: prezzo statico/menu. Stesso Core, regola diversa (iniezione)."""
    prezzo_cents: int = 0
    richiede_inventario: bool = True

    def __post_init__(self):
        _cent(self.prezzo_cents, "prezzo_cents")

    def risolvi(self, ctx: ContestoPrezzo) -> EsitoPrezzo:
        if self.richiede_inventario and not ctx.inventario_disponibile:
            return EsitoPrezzo("nosale")
        return EsitoPrezzo("ok", self.prezzo_cents)

    def descrizione(self) -> str:
        return f"Fisso {self.prezzo_cents}c"


def politica_prezzo_da_config(d: dict) -> PoliticaPrezzo:
    """Costruisce una PoliticaPrezzo da config (Registry-driven, plug-and-play)."""
    tipo = d.get("tipo", "host_authoritative")
    if tipo == "host_authoritative":
        return PoliticaPrezzoHostAuthoritative()
    if tipo == "fisso":
        campi = ("prezzo_cents", "richiede_inventario")
        return PoliticaPrezzoFisso(**{k: d[k] for k in campi if k in d})
    raise ValueError(f"politica prezzo sconosciuta: {tipo!r}")
