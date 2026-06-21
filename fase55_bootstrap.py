"""
CORE_AUTO - Fase 55: Bootstrap / Composition-root del funnel Mango.

Finora accendere il sistema richiedeva cablare a mano 12 moduli. Questo e' il PUNTO
UNICO DI ACCENSIONE: da una ConfigMango assembla lo stack autonomo
  stadi (esplora/outreach/advertising/ponte) -> orchestratore(50) -> scheduler(51)
  + store SQLite(52) + health-guard(53) -> loop/daemon(54)
e restituisce un SistemaMango pronto a girare, con un report di composizione che dice
COSA e' attivo e COSA manca (e perche').

Vincitrice del benchmark (3 varianti x 10 stress, config casuali incoerenti/parziali):
V3 'validata-con-report'. Costruisce ogni configurazione COERENTE e degrada con
avvisi espliciti sui pezzi assenti; fa fail-closed (BootstrapError) SOLO sull'incoerenza
attiva (sistema acceso ma senza alcuno stadio = brucia risorse a vuoto). Le altre 2
(eager-fail-fast = esplode anche su componenti opzionali assenti a sistema SPENTO;
silent-partial = costruisce in silenzio un sistema rotto) o sono troppo rigide o
nascondono i guasti.

SOPRAVVIVENZA TOTALE: default-OFF (ConfigMango.abilitato=False -> nessun layer gira;
il money-path resta separato e opt-in). Config validata (fail-closed su tipi/valori).
Money: il Ponte (fase49) resta l'unico ingresso al denaro; se assente, il funnel
osserva e propone ma NON prenota (avviso esplicito).
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple

from fase50_orchestratore import crea_orchestratore
from fase51_scheduler import crea_scheduler
from fase52_persistenza_metriche import crea_store_sqlite
from fase53_healthguard import crea_circuito_funnel, PoliticaSalute
from fase54_loop import crea_loop

logger = logging.getLogger("core_auto.bootstrap_mango")

_ENV_FLAG = "MANGO_ATTIVO"


class BootstrapError(Exception):
    """Configurazione incoerente: il composition-root rifiuta di assemblare (fail-closed)."""


def _num_non_neg(v, nome):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
        raise ValueError(f"{nome} deve essere numero >= 0")
    return v


def _int_non_neg(v, nome):
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        raise ValueError(f"{nome} deve essere int >= 0")
    return v


@dataclass(frozen=True)
class ConfigMango:
    """Parametri di accensione. `abilitato` (master) governa orchestratore/scheduler/
    loop; `abilitato_healthguard` governa il circuito (default = master)."""
    abilitato: bool = False
    abilitato_healthguard: Optional[bool] = None   # None -> = abilitato
    db_path: str = ":memory:"
    intervallo_s: float = 60.0
    costo_token_ciclo: int = 1000
    cooldown_s: float = 60.0

    def __post_init__(self):
        if not isinstance(self.db_path, str) or not self.db_path:
            raise ValueError("db_path deve essere stringa non vuota")
        _num_non_neg(self.intervallo_s, "intervallo_s")
        _int_non_neg(self.costo_token_ciclo, "costo_token_ciclo")
        _num_non_neg(self.cooldown_s, "cooldown_s")

    @property
    def hg_attivo(self) -> bool:
        return self.abilitato if self.abilitato_healthguard is None else bool(self.abilitato_healthguard)

    @classmethod
    def da_env(cls, **override) -> "ConfigMango":
        """Config dall'ambiente (MANGO_ATTIVO=1 accende il master)."""
        base = dict(abilitato=os.environ.get(_ENV_FLAG) == "1")
        base.update(override)
        return cls(**base)


@dataclass(frozen=True)
class ReportComposizione:
    attivi: Dict[str, bool]
    avvisi: Tuple[str, ...] = ()
    coerente: bool = True


@dataclass(frozen=True)
class SistemaMango:
    config: ConfigMango
    store: Any
    orchestratore: Any
    scheduler: Any
    circuito: Any
    loop: Any
    report: ReportComposizione

    def avvia(self, *, max_tick: Optional[int] = None):
        """Accende il daemon (delega al loop). Spento -> ReportLoop inerte."""
        return self.loop.esegui(max_tick=max_tick)

    def metriche(self):
        return self.store.metriche()


def costruisci(config: ConfigMango, *, esploratore: Any = None, venditore: Any = None,
               advertising: Any = None, ponte: Any = None, governatore: Any = None,
               sorgente: Optional[Callable[[], Any]] = None,
               clock: Callable[[], float] = time.monotonic,
               sleep: Callable[[float], None] = time.sleep) -> SistemaMango:
    """Assembla lo stack (V3 validata-con-report). Fail-closed solo sull'incoerenza
    attiva; altrimenti degrada con avvisi."""
    if not isinstance(config, ConfigMango):
        raise BootstrapError("config deve essere una ConfigMango")

    stadi = {nome: obj for nome, obj in (
        ("esploratore", esploratore), ("venditore", venditore),
        ("advertising", advertising), ("ponte", ponte)) if obj is not None}

    # --- incoerenza ATTIVA = fail-closed ---
    if config.abilitato and not stadi:
        raise BootstrapError("sistema attivo ma nessuno stadio montato "
                             "(esploratore/venditore/advertising/ponte): brucerebbe a vuoto")

    # --- assemblaggio ---
    store = crea_store_sqlite(config.db_path)
    orchestratore = crea_orchestratore(
        esploratore=esploratore, venditore=venditore, advertising=advertising,
        ponte=ponte, abilitato=config.abilitato)
    scheduler = crea_scheduler(
        orchestratore, governatore=governatore, store=store,
        costo_token_ciclo=config.costo_token_ciclo, abilitato=config.abilitato)
    circuito = crea_circuito_funnel(
        PoliticaSalute(cooldown_s=config.cooldown_s), clock=clock,
        abilitato=config.hg_attivo)
    loop = crea_loop(
        scheduler, sorgente or (lambda: []), circuito=circuito,
        intervallo_s=config.intervallo_s, clock=clock, sleep=sleep,
        abilitato=config.abilitato)

    # --- avvisi (degrado grazioso, non fatali) ---
    avvisi = []
    if governatore is None:
        avvisi.append("nessun governatore token: spesa LLM globale NON limitata")
    if not config.hg_attivo:
        avvisi.append("health-guard spento: nessuna auto-pausa/recupero")
    if config.abilitato and ponte is None:
        avvisi.append("money-path OFF (ponte assente): il funnel osserva/propone ma NON prenota")
    if not config.abilitato:
        avvisi.append("sistema in DEFAULT-OFF: nessun layer gira finche' non lo accendi")

    report = ReportComposizione(
        attivi={
            "esploratore": esploratore is not None,
            "venditore": venditore is not None,
            "advertising": advertising is not None,
            "ponte": ponte is not None,
            "governatore": governatore is not None,
            "health_guard": config.hg_attivo,
            "loop": config.abilitato,
        },
        avvisi=tuple(avvisi), coerente=True)

    logger.info("SistemaMango assemblato: attivi=%s avvisi=%d",
                {k: v for k, v in report.attivi.items() if v}, len(avvisi))
    return SistemaMango(config, store, orchestratore, scheduler, circuito, loop, report)
