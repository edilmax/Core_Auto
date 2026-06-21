"""
CORE_AUTO - Fase 80: Sentinel (FIM + canary + catena integrita') - difende la cartella.

Il sogno dell'utente: "un sistema che guarda la cartella e la difende, gratis e autonomo".
La verita': OSSEC/Wazuh/ClamAV/Fail2ban/Suricata sono lo standard, ma sono strumenti a
livello di SISTEMA OPERATIVO (si installano sul server Linux al deploy, via cron/script;
non sono un modulo Python). Il CUORE del sogno, pero', e' buildabile ORA in Python puro,
deterministico e a costo zero - ed e' esattamente cio' che fa OSSEC con la FIM:

  1. FILE INTEGRITY MONITORING: si fa un'ISTANTANEA (hash SHA-256 di ogni file tracciato)
     e a ogni VERIFICA si rileva qualunque MODIFICA / AGGIUNTA / CANCELLAZIONE. Un hacker
     che tocca il codice e' scoperto al confronto degli hash (anche zero-day: non serve
     una firma di virus, basta che il byte cambi).
  2. CANARY TOKEN: file-esca che nessun processo legittimo modifica mai. Se il suo hash
     cambia o sparisce -> intrusione CERTA (near-zero falsi positivi).
  3. CATENA D'INTEGRITA' append-only: ogni evento e' concatenato all'hash del precedente
     (hash-chain). Manomettere un record del log rompe la catena -> tamper-evident,
     come un registro notarile inalterabile.

VINCITRICE DEL BENCHMARK (4 modi di proteggere la cartella):
  V3 'FIM hash-baseline + canary + catena hash append-only'. Rileva QUALSIASI modifica
  (anche zero-day), il canary canta su accesso illegittimo, il log e' inalterabile;
  deterministico, zero costo, zero dipendenze. Le altre perdono: V1 'nessun monitoraggio'
  = non sai nulla; V2 'antivirus a firme' = cieco sullo zero-day e sui file leciti
  modificati; V4 'SIEM cloud' = costo + dipendenza + latenza.

NB confine onesto: rilevazione di ACCESSO in lettura (access-time) e il blocco IP/Active
Response sono a livello OS (auditd/Fail2ban, gated al server). Qui c'e' la rilevazione di
MODIFICA/INTEGRITA', pura e testabile, che gira accanto al codice. SOPRAVVIVENZA TOTALE:
funzioni blindate (file illeggibile -> None, mai eccezione); notificatore isolato;
catena verificabile deterministicamente. Zero dipendenze (hashlib/os da stdlib).
"""
from __future__ import annotations

import datetime
import hashlib
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger("core_auto.sentinel")

GENESI = "0" * 64


def hash_file(percorso: str) -> Optional[str]:
    """SHA-256 di un file (a blocchi). None se mancante/illeggibile (fail-safe)."""
    try:
        h = hashlib.sha256()
        with open(percorso, "rb") as f:
            for blocco in iter(lambda: f.read(65536), b""):
                h.update(blocco)
        return h.hexdigest()
    except (OSError, IOError, TypeError):
        return None


@dataclass
class ReportIntegrita:
    modificati: List[str] = field(default_factory=list)
    aggiunti: List[str] = field(default_factory=list)
    rimossi: List[str] = field(default_factory=list)
    canary_violati: List[str] = field(default_factory=list)

    @property
    def integro(self) -> bool:
        return not (self.modificati or self.aggiunti or self.rimossi
                    or self.canary_violati)

    @property
    def critico(self) -> bool:
        return bool(self.canary_violati)

    def as_dict(self) -> Dict[str, Any]:
        return {"integro": self.integro, "critico": self.critico,
                "modificati": self.modificati, "aggiunti": self.aggiunti,
                "rimossi": self.rimossi, "canary_violati": self.canary_violati}


# ─────────────────────────────────────────────────────────────────────────────
# Sentinel FIM
# ─────────────────────────────────────────────────────────────────────────────
class Sentinel:
    """Monitor d'integrita' di un insieme di file (o di una cartella) + canary."""

    def __init__(self, *, cartella: Optional[str] = None,
                 percorsi: Optional[Sequence[str]] = None,
                 canary: Optional[Sequence[str]] = None,
                 estensioni: Optional[Sequence[str]] = None,
                 notificatore: Optional[Callable[[Dict[str, Any]], None]] = None) -> None:
        self._cartella = cartella
        self._percorsi = list(percorsi) if percorsi else None
        self._canary = [str(c) for c in (canary or [])]
        self._estensioni = tuple(estensioni) if estensioni else None
        self._notifica = notificatore
        self._baseline: Dict[str, str] = {}
        self._baseline_canary: Dict[str, Optional[str]] = {}

    def _scan(self) -> List[str]:
        """Insieme corrente di file tracciati (esclusi i canary)."""
        files: List[str] = []
        if self._percorsi is not None:
            files = [p for p in self._percorsi]
        elif self._cartella and os.path.isdir(self._cartella):
            for radice, _dirs, nomi in os.walk(self._cartella):
                for n in nomi:
                    if self._estensioni and not n.endswith(self._estensioni):
                        continue
                    files.append(os.path.join(radice, n))
        canary_set = set(self._canary)
        return [f for f in files if f not in canary_set]

    def istantanea(self) -> int:
        """Cattura la baseline (hash di ogni file + canary). Ritorna quanti file."""
        self._baseline = {}
        for p in self._scan():
            h = hash_file(p)
            if h is not None:
                self._baseline[p] = h
        self._baseline_canary = {c: hash_file(c) for c in self._canary}
        return len(self._baseline)

    def verifica(self) -> ReportIntegrita:
        """Confronta lo stato corrente con la baseline. Notifica (isolato) se non integro."""
        rep = ReportIntegrita()
        corrente: Dict[str, str] = {}
        for p in self._scan():
            h = hash_file(p)
            if h is not None:
                corrente[p] = h
        for p, h in corrente.items():
            if p not in self._baseline:
                rep.aggiunti.append(p)
            elif self._baseline[p] != h:
                rep.modificati.append(p)
        for p in self._baseline:
            if p not in corrente:
                rep.rimossi.append(p)
        # canary: qualunque variazione/sparizione = intrusione
        for c, h0 in self._baseline_canary.items():
            if hash_file(c) != h0:
                rep.canary_violati.append(c)
        rep.modificati.sort()
        rep.aggiunti.sort()
        rep.rimossi.sort()
        rep.canary_violati.sort()
        if not rep.integro:
            self._allerta(rep)
        return rep

    def aggiorna_baseline(self) -> int:
        """Riallinea la baseline (dopo una modifica LEGITTIMA)."""
        return self.istantanea()

    def _allerta(self, rep: ReportIntegrita) -> None:
        if self._notifica is None:
            return
        try:
            self._notifica({"tipo": "integrita_violata", **rep.as_dict()})
        except Exception:
            logger.warning("Sentinel: notifica fallita (ignorata)", exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# Catena d'integrita' append-only (hash-chain, tamper-evident) - durevole
# ─────────────────────────────────────────────────────────────────────────────
class CatenaIntegrita:
    def __init__(self, conn_factory: Callable[[], sqlite3.Connection]) -> None:
        self._conn_factory = conn_factory
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
                    CREATE TABLE IF NOT EXISTS catena (
                        seq INTEGER PRIMARY KEY AUTOINCREMENT,
                        evento TEXT NOT NULL,
                        prev_hash TEXT NOT NULL,
                        entry_hash TEXT NOT NULL,
                        ts TEXT NOT NULL)""")
        finally:
            con.close()

    @staticmethod
    def _hash(prev: str, evento: str) -> str:
        return hashlib.sha256((prev + "|" + evento).encode("utf-8")).hexdigest()

    def append(self, evento: str) -> str:
        """Aggiunge un evento concatenato all'hash del precedente. Ritorna l'entry_hash."""
        evento = str(evento)
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            ultimo = con.execute("SELECT entry_hash FROM catena ORDER BY seq DESC "
                                 "LIMIT 1").fetchone()
            prev = ultimo["entry_hash"] if ultimo else GENESI
            entry = self._hash(prev, evento)
            con.execute("INSERT INTO catena (evento, prev_hash, entry_hash, ts) "
                        "VALUES (?,?,?,?)", (evento, prev, entry, ts))
            con.execute("COMMIT")
            return entry
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    def verifica_catena(self) -> Dict[str, Any]:
        """Ricalcola la catena dall'inizio. {'integro':bool, 'rotta_a':seq|None}."""
        con = self._apri()
        try:
            righe = con.execute("SELECT seq, evento, prev_hash, entry_hash FROM catena "
                                "ORDER BY seq ASC").fetchall()
        finally:
            con.close()
        prev = GENESI
        for r in righe:
            atteso = self._hash(prev, r["evento"])
            if r["prev_hash"] != prev or r["entry_hash"] != atteso:
                return {"integro": False, "rotta_a": int(r["seq"])}
            prev = r["entry_hash"]
        return {"integro": True, "rotta_a": None}

    def conteggio(self) -> int:
        con = self._apri()
        try:
            return con.execute("SELECT COUNT(*) FROM catena").fetchone()[0]
        finally:
            con.close()


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


def crea_catena(percorso: str = ":memory:") -> CatenaIntegrita:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return CatenaIntegrita(lambda: _ConnCondivisa(con))
    return CatenaIntegrita(lambda: sqlite3.connect(percorso))
