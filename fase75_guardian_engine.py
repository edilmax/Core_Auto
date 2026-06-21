"""
CORE_AUTO - Fase 75: Guardian Engine (rilevamento pericoli + risposta automatica).

Non e' una feature, e' un sistema di SOPRAVVIVENZA dell'alloggio. I danni invisibili
uccidono il business prima delle recensioni:
  - WATER LEAK: ~$130.000 di danno medio per incidente; rilevazione IoT in ~8 secondi vs
    2-4 ore manuali, -85% di danno;
  - FUOCO / CO: minaccia diretta alla vita -> evacuazione + emergenza;
  - MUFFA: umidita' >60% per >48h -> crescita; quando e' visibile e' troppo tardi
    ($50K+ di bonifica).
Nessuna piattaforma di prenotazione include tutto questo: lo scaricano sull'host. Ma
l'host che perde l'alloggio = buco = cancellazione = penale = recensione distrutta.

Il Guardian non MISURA (i sensori sono gated/hardware) e non ESEGUE da solo i comandi
fisici: RILEVA dai dati (letture dal Digital Twin fase72 / report host) e produce un
PIANO D'AZIONE strutturato e deterministico (chiudi acqua, notifica urgente, blocca
l'inventario in 'manutenzione'/'emergenza', genera claim assicurativo, evacua, chiama
emergenza). L'esecuzione e' delegata ad attuatori INIETTATI e ISOLATI (un attuatore che
esplode non abbatte il resto). Compone con fase58 (stato inventario), fase37/39
(notifiche), fase52 (metriche).

VINCITRICE DEL BENCHMARK (4 modi di gestire i pericoli):
  V3 'soglia immediata per i critici (acqua/fuoco) + soglia-SOSTENUTA per i lenti (muffa)
  + piano d'azione strutturato + esecuzione isolata'. Proattivo, pochi falsi positivi
  (la muffa richiede durata -> non scatta sul vapore della doccia), azioni automatiche.
  Le altre perdono: V1 'reattivo (allarme a disastro avvenuto)' = $130K di danno; V2
  'soglia istantanea senza durata' = allarmi continui sui transitori; V4 'anomaly ML' =
  non-deterministico, scatola nera (inaccettabile per la sicurezza).

SOPRAVVIVENZA TOTALE: valutazione PURA e deterministica; letture non-intere ignorate
(fail-safe); pericoli a durata non scattano senza durata sufficiente (no falsi positivi);
attuatori isolati; severita' -> stato (emergenza>manutenzione>ok). Zero dipendenze.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("core_auto.guardian")


def _intero(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


@dataclass(frozen=True)
class RegolaPericolo:
    tipo: str                       # 'water_leak' | 'fire' | 'co' | 'mold_risk' ...
    sensore: str
    soglia: int
    severita: str                   # 'critico' | 'avviso'
    azioni: Tuple[str, ...]
    durata_min_sec: int = 0         # 0 = immediato; >0 = soglia SOSTENUTA
    direzione: str = "su"           # 'su' = valore>=soglia e' pericolo; 'giu' = <=soglia


# Regole di default (sovrascrivibili). Unita': water/fumo presenza (1=rilevato),
# co in ppm, umidita' in per-mille (600=60%).
REGOLE_DEFAULT: Tuple[RegolaPericolo, ...] = (
    RegolaPericolo("water_leak", "water", 1, "critico",
                   ("chiudi_acqua", "notifica_urgente", "blocca_manutenzione",
                    "genera_claim")),
    RegolaPericolo("fire", "fumo", 1, "critico",
                   ("allarme", "evacua_ospite", "chiama_emergenza", "blocca_emergenza")),
    RegolaPericolo("co", "co", 50, "critico",
                   ("allarme", "evacua_ospite", "chiama_emergenza", "blocca_emergenza")),
    RegolaPericolo("mold_risk", "umidita", 600, "avviso",
                   ("ventilazione_max", "pulizia_prioritaria", "notifica_host"),
                   durata_min_sec=172800),     # 48h
)

_AZIONI_EMERGENZA = ("blocca_emergenza",)
_AZIONI_MANUTENZIONE = ("blocca_manutenzione",)


@dataclass(frozen=True)
class Pericolo:
    tipo: str
    sensore: str
    valore: int
    severita: str
    azioni: Tuple[str, ...]


@dataclass
class ReportGuardian:
    alloggio_id: str
    pericoli: List[Pericolo] = field(default_factory=list)
    azioni_consigliate: List[str] = field(default_factory=list)
    stato_consigliato: str = "ok"      # 'emergenza' | 'manutenzione' | 'ok'

    @property
    def critico(self) -> bool:
        return any(p.severita == "critico" for p in self.pericoli)


class GuardianEngine:
    def __init__(self, regole: Optional[Tuple[RegolaPericolo, ...]] = None) -> None:
        self._regole = tuple(regole) if regole is not None else REGOLE_DEFAULT

    def valuta(self, alloggio_id: str, letture: Any, *,
               durate_sostenute: Optional[Dict[str, int]] = None) -> ReportGuardian:
        """Rileva i pericoli dalle letture correnti. `durate_sostenute`: secondi per cui
        ogni sensore e' oltre la sua soglia (per i pericoli a durata, es. muffa)."""
        report = ReportGuardian(alloggio_id=str(alloggio_id))
        if not isinstance(letture, dict):
            return report
        durate = durate_sostenute if isinstance(durate_sostenute, dict) else {}
        azioni: List[str] = []
        for r in self._regole:
            v = letture.get(r.sensore)
            if not _intero(v):
                continue
            oltre = (v >= r.soglia) if r.direzione == "su" else (v <= r.soglia)
            if not oltre:
                continue
            if r.durata_min_sec > 0:
                d = durate.get(r.sensore, 0)
                if not _intero(d) or d < r.durata_min_sec:
                    continue                    # non sostenuto abbastanza -> no falso positivo
            report.pericoli.append(Pericolo(r.tipo, r.sensore, v, r.severita, r.azioni))
            for a in r.azioni:
                if a not in azioni:
                    azioni.append(a)
        report.azioni_consigliate = azioni
        report.stato_consigliato = self._stato(azioni)
        return report

    @staticmethod
    def _stato(azioni: List[str]) -> str:
        if any(a in _AZIONI_EMERGENZA for a in azioni):
            return "emergenza"
        if any(a in _AZIONI_MANUTENZIONE for a in azioni):
            return "manutenzione"
        return "ok"

    def esegui(self, report: ReportGuardian,
               attuatori: Dict[str, Callable[[ReportGuardian], Any]]
               ) -> Dict[str, bool]:
        """Esegue le azioni consigliate via attuatori INIETTATI e ISOLATI. Ritorna
        {azione: ok}. Azione senza attuatore -> False (saltata)."""
        esiti: Dict[str, bool] = {}
        if not isinstance(attuatori, dict):
            return esiti
        for azione in report.azioni_consigliate:
            fn = attuatori.get(azione)
            if fn is None:
                esiti[azione] = False
                continue
            try:
                fn(report)
                esiti[azione] = True
            except Exception:
                logger.error("Guardian: attuatore '%s' ha sollevato (ISOLATO)", azione,
                             exc_info=True)
                esiti[azione] = False
        return esiti


def crea_guardian(regole: Optional[Tuple[RegolaPericolo, ...]] = None) -> GuardianEngine:
    return GuardianEngine(regole)
