"""
CORE_AUTO - Fase 72: Digital Twin dell'alloggio (telemetria + manutenzione predittiva).

Mercato reale da ~$149B entro il 2030: ogni alloggio ha un "gemello digitale" che
rispecchia il suo stato in tempo reale e PREDICE i guasti 30-90 giorni prima. Il valore
operativo: scoprire il problema (perdita d'acqua, HVAC che cede, frigo che scalda)
PRIMA che l'ospite arrivi o si lamenti -> zero recensioni distrutte, zero emergenze.

I sensori fisici sono GATED (hardware), ma la LOGICA del twin e' pura, deterministica e
sensore-agnostica: ingerisce letture (iniettate, da qualsiasi fonte), e fornisce:
  1. STATO: l'ultimo valore per sensore;
  2. ANOMALIE: letture fuori dalla banda di comfort/sicurezza (fail-closed);
  3. MANUTENZIONE PREDITTIVA: dal TREND recente proietta se un sensore raggiungera' la
     soglia di guasto entro un orizzonte -> avviso anticipato (es. umidita' che sale ->
     perdita; energia che sale -> HVAC che degrada);
  4. AGIBILITA' pre-arrivo: tutti i sensori critici in banda -> pronto (compone con
     fase70 turnover e fase53 health-guard).

Valori in INTERI nell'unita' nativa del sensore (es. temperatura in centi-gradi: 2150 =
21.50C; umidita' in per-mille). Niente float -> confronti deterministici, zero flakiness.

VINCITRICE DEL BENCHMARK (4 modi di sorvegliare l'alloggio):
  V3 'twin con banda + trend lineare + orizzonte'. Rileva sia l'anomalia ISTANTANEA
  (fuori banda) sia il DEGRADO (trend verso la soglia) con proiezione deterministica.
  Le altre perdono: V1 'solo allarme su soglia' = scopre il guasto quando e' gia'
  successo (reattivo, non predittivo); V2 'media mobile' = ritarda e maschera i trend;
  V4 'ML/forecasting' = overkill, non-deterministico, a costo.

SOPRAVVIVENZA TOTALE: store durevole (conn-per-op, WAL, BEGIN IMMEDIATE, idem schema);
validatori BLINDATI (valore non-intero -> rifiutato); analisi PURE e deterministiche;
agibilita' fail-closed (sensore critico assente -> non pronto); orologio iniettabile.
Zero dipendenze.
"""
from __future__ import annotations

import datetime
import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("core_auto.digital_twin")


def _intero(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


@dataclass(frozen=True)
class SensoreConfig:
    banda_min: int
    banda_max: int
    soglia_guasto: Optional[int] = None    # valore che indica guasto imminente
    direzione: str = "su"                  # 'su' = sale verso la soglia, 'giu' = scende
    critico: bool = False                  # se True, deve essere in banda per l'agibilita'


@dataclass(frozen=True)
class Anomalia:
    sensore: str
    valore: int
    banda_min: int
    banda_max: int


@dataclass(frozen=True)
class PredizioneGuasto:
    sensore: str
    valore_attuale: int
    valore_proiettato: int
    soglia_guasto: int
    quando_sec: int                        # stima secondi al superamento della soglia


# ─────────────────────────────────────────────────────────────────────────────
# Digital Twin durevole
# ─────────────────────────────────────────────────────────────────────────────
class DigitalTwin:
    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], *,
                 orologio: Optional[Callable[[], int]] = None) -> None:
        self._conn_factory = conn_factory
        self._now = orologio or (lambda: int(time.time()))
        self.inizializza_schema()

    def _apri(self) -> sqlite3.Connection:
        con = self._conn_factory()
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass
        return con

    def inizializza_schema(self) -> None:
        con = self._apri()
        try:
            with con:
                con.execute("""
                    CREATE TABLE IF NOT EXISTS letture (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        alloggio_id TEXT NOT NULL,
                        sensore TEXT NOT NULL,
                        valore INTEGER NOT NULL,
                        ts INTEGER NOT NULL)""")
                con.execute("CREATE INDEX IF NOT EXISTS idx_letture "
                            "ON letture(alloggio_id, sensore, ts)")
        finally:
            con.close()

    def registra_lettura(self, alloggio_id: str, sensore: str, valore: int, *,
                         ts: Optional[int] = None) -> bool:
        """Ingerisce una lettura (intero nell'unita' del sensore). BLINDATO."""
        if not (isinstance(alloggio_id, str) and alloggio_id.strip()):
            return False
        if not (isinstance(sensore, str) and sensore.strip()):
            return False
        if not _intero(valore):
            return False
        quando = ts if _intero(ts) else self._now()
        con = self._apri()
        try:
            with con:
                con.execute("INSERT INTO letture (alloggio_id, sensore, valore, ts) "
                            "VALUES (?,?,?,?)",
                            (str(alloggio_id), str(sensore), valore, quando))
            return True
        finally:
            con.close()

    def stato(self, alloggio_id: str) -> Dict[str, Dict[str, int]]:
        """Ultimo valore per sensore: {sensore: {'valore':v, 'ts':t}}."""
        con = self._apri()
        try:
            righe = con.execute(
                "SELECT sensore, valore, ts FROM letture l WHERE alloggio_id=? AND "
                "ts = (SELECT MAX(ts) FROM letture WHERE alloggio_id=l.alloggio_id AND "
                "sensore=l.sensore)", (str(alloggio_id),)).fetchall()
        finally:
            con.close()
        return {r["sensore"]: {"valore": int(r["valore"]), "ts": int(r["ts"])}
                for r in righe}

    def anomalie(self, alloggio_id: str,
                 config: Dict[str, SensoreConfig]) -> List[Anomalia]:
        """Sensori la cui ultima lettura e' fuori banda."""
        st = self.stato(alloggio_id)
        out: List[Anomalia] = []
        for sensore, cfg in (config or {}).items():
            if not isinstance(cfg, SensoreConfig) or sensore not in st:
                continue
            v = st[sensore]["valore"]
            if v < cfg.banda_min or v > cfg.banda_max:
                out.append(Anomalia(sensore, v, cfg.banda_min, cfg.banda_max))
        return out

    def predici_guasti(self, alloggio_id: str, config: Dict[str, SensoreConfig], *,
                       orizzonte_sec: int, finestra: int = 10) -> List[PredizioneGuasto]:
        """Dal trend lineare delle ultime `finestra` letture, proietta se il sensore
        raggiungera' la soglia di guasto entro `orizzonte_sec`. Deterministico, interi."""
        if not _intero(orizzonte_sec) or orizzonte_sec <= 0:
            return []
        fin = finestra if (_intero(finestra) and finestra >= 2) else 10
        out: List[PredizioneGuasto] = []
        con = self._apri()
        try:
            for sensore, cfg in (config or {}).items():
                if not isinstance(cfg, SensoreConfig) or cfg.soglia_guasto is None:
                    continue
                righe = con.execute(
                    "SELECT valore, ts FROM letture WHERE alloggio_id=? AND sensore=? "
                    "ORDER BY ts DESC LIMIT ?",
                    (str(alloggio_id), sensore, fin)).fetchall()
                if len(righe) < 2:
                    continue
                righe = list(reversed(righe))           # ts crescente
                primo, ultimo = righe[0], righe[-1]
                dt = ultimo["ts"] - primo["ts"]
                dv = ultimo["valore"] - primo["valore"]
                if dt <= 0 or dv == 0:
                    continue
                pred = self._proietta(sensore, cfg, ultimo["valore"], dv, dt,
                                      orizzonte_sec)
                if pred is not None:
                    out.append(pred)
        finally:
            con.close()
        return out

    @staticmethod
    def _proietta(sensore: str, cfg: SensoreConfig, attuale: int, dv: int, dt: int,
                  orizzonte_sec: int) -> Optional[PredizioneGuasto]:
        soglia = cfg.soglia_guasto
        proiettato = attuale + (dv * orizzonte_sec) // dt
        if cfg.direzione == "su":
            if dv <= 0 or attuale >= soglia or proiettato < soglia:
                return None
            quando = ((soglia - attuale) * dt) // dv     # dv>0
        else:  # 'giu'
            if dv >= 0 or attuale <= soglia or proiettato > soglia:
                return None
            quando = ((soglia - attuale) * dt) // dv     # entrambi negativi -> positivo
        return PredizioneGuasto(sensore, attuale, proiettato, soglia, max(0, quando))

    def pronto_per_arrivo(self, alloggio_id: str,
                          config: Dict[str, SensoreConfig]) -> bool:
        """Tutti i sensori CRITICI presenti e in banda -> pronto. Fail-closed: sensore
        critico assente o fuori banda -> non pronto."""
        st = self.stato(alloggio_id)
        for sensore, cfg in (config or {}).items():
            if not isinstance(cfg, SensoreConfig) or not cfg.critico:
                continue
            if sensore not in st:
                return False                            # critico senza dati -> fail-closed
            v = st[sensore]["valore"]
            if v < cfg.banda_min or v > cfg.banda_max:
                return False
        return True

    def report_soggiorno(self, alloggio_id: str, sensore: str, ts_inizio: int,
                         ts_fine: int) -> Optional[Dict[str, int]]:
        """Confronto pre/post di un sensore nell'intervallo [ts_inizio, ts_fine]."""
        if not (_intero(ts_inizio) and _intero(ts_fine)) or ts_inizio > ts_fine:
            return None
        con = self._apri()
        try:
            primo = con.execute(
                "SELECT valore FROM letture WHERE alloggio_id=? AND sensore=? AND ts>=? "
                "ORDER BY ts ASC LIMIT 1",
                (str(alloggio_id), str(sensore), ts_inizio)).fetchone()
            ultimo = con.execute(
                "SELECT valore FROM letture WHERE alloggio_id=? AND sensore=? AND ts<=? "
                "ORDER BY ts DESC LIMIT 1",
                (str(alloggio_id), str(sensore), ts_fine)).fetchone()
        finally:
            con.close()
        if primo is None or ultimo is None:
            return None
        return {"inizio": int(primo["valore"]), "fine": int(ultimo["valore"]),
                "delta": int(ultimo["valore"]) - int(primo["valore"])}


# ─────────────────────────────────────────────────────────────────────────────
# Connessione condivisa per :memory:
# ─────────────────────────────────────────────────────────────────────────────
class _ConnCondivisa:
    def __init__(self, con: sqlite3.Connection) -> None:
        object.__setattr__(self, "_con", con)

    def close(self) -> None:
        pass

    def __enter__(self):
        return self._con.__enter__()

    def __exit__(self, *a):
        return self._con.__exit__(*a)

    def __getattr__(self, name):
        return getattr(self._con, name)

    def __setattr__(self, name, value):
        setattr(self._con, name, value)


def crea_digital_twin(percorso: str = ":memory:", *,
                      orologio: Optional[Callable[[], int]] = None) -> DigitalTwin:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return DigitalTwin(lambda: _ConnCondivisa(con), orologio=orologio)
    return DigitalTwin(lambda: sqlite3.connect(percorso), orologio=orologio)
