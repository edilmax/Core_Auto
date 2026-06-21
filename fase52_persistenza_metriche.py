"""
CORE_AUTO - Fase 52: Persistenza durevole + metriche del funnel Mango.

Lo Scheduler (fase51) persisteva i ReportCiclo solo in-memory: a un riavvio, l'intera
storia del funnel evaporava. Questo modulo fornisce uno `StoreCicli` DUREVOLE su
SQLite (drop-in per fase51, stessa interfaccia append/conteggio) + un aggregatore di
METRICHE per l'osservabilita' (conversion rate, guasti per stadio, cicli ok).

Schema IBRIDO (vincitore del benchmark, 3 varianti x 10 stress):
  - tabella `cicli`: una riga per ciclo con contatori PRECALCOLATI in scrittura
    (ok_totale, n_stadi, n_falliti, conversione_riuscita) -> metriche di ciclo come
    aggregati SQL O(1), nessun re-parsing;
  - tabella `stadi`: una riga per stadio (nome, ok, errore) -> breakdown per-stadio
    via GROUP BY, dettaglio diagnostico completo.
Le altre 2 (JSON-blob = metriche lente, parsing Python per ogni read; counters-only
= niente breakdown per-stadio, cieco sulla diagnosi) perdono velocita' o dettaglio.

DUREVOLEZZA/CONCORRENZA come fase34: connessione-per-operazione (`conn_factory`),
WAL, append atomico in `BEGIN IMMEDIATE`. Idempotenza dello schema (CREATE IF NOT
EXISTS). Fail-safe: un report malformato non corrompe lo store (estrazione difensiva).
"""
from __future__ import annotations

import datetime
import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("core_auto.persistenza_metriche")


# ─────────────────────────────────────────────────────────────────────────────
# Estrazione DIFENSIVA del riepilogo da un ReportCiclo (duck-typed, fase50)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class _RiepilogoStadio:
    nome: str
    ok: bool
    errore: str


@dataclass(frozen=True)
class _RiepilogoCiclo:
    abilitato: bool
    ok_totale: bool
    stadi: List[_RiepilogoStadio]
    conversione_riuscita: Optional[bool]   # None se lo stadio non c'e'

    @property
    def n_stadi(self) -> int:
        return len(self.stadi)

    @property
    def n_falliti(self) -> int:
        return sum(1 for s in self.stadi if not s.ok)


def riepiloga(report: Any) -> _RiepilogoCiclo:
    """Estrae un riepilogo serializzabile da un ReportCiclo qualunque, senza fidarsi
    della forma (i `risultato` degli stadi sono Any e possono non essere serializzabili)."""
    abilitato = bool(getattr(report, "abilitato", True))
    stadi_raw = getattr(report, "stadi", ()) or ()
    stadi: List[_RiepilogoStadio] = []
    conv: Optional[bool] = None
    for s in stadi_raw:
        nome = str(getattr(s, "nome", "?"))
        ok = bool(getattr(s, "ok", False))
        errore = str(getattr(s, "errore", "") or "")
        stadi.append(_RiepilogoStadio(nome, ok, errore))
        if nome == "conversione":
            # conversione "riuscita" = stadio non esploso E esito interno ok (se esposto)
            ris = getattr(s, "risultato", None)
            interno = getattr(ris, "ok", True)   # EsitoConversione.ok, o True se assente
            conv = bool(ok and interno)
    ok_totale = bool(getattr(report, "ok_totale", abilitato and all(s.ok for s in stadi)))
    return _RiepilogoCiclo(abilitato, ok_totale, stadi, conv)


# ─────────────────────────────────────────────────────────────────────────────
# Metriche aggregate
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class MetricheStadio:
    nome: str
    eseguiti: int
    falliti: int

    @property
    def ok(self) -> int:
        return self.eseguiti - self.falliti


@dataclass(frozen=True)
class MetricheFunnel:
    cicli_totali: int = 0
    cicli_ok: int = 0                      # ok_totale=True
    conversioni_tentate: int = 0
    conversioni_riuscite: int = 0
    per_stadio: Dict[str, MetricheStadio] = field(default_factory=dict)

    @property
    def conversion_rate(self) -> float:
        return (self.conversioni_riuscite / self.conversioni_tentate
                if self.conversioni_tentate else 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Store durevole SQLite (drop-in per l'interfaccia StoreCicli di fase51)
# ─────────────────────────────────────────────────────────────────────────────
class StoreCicliSQLite:
    """Persiste i ReportCiclo su SQLite e calcola le metriche del funnel. Stessa
    interfaccia append/conteggio dello StoreCicliMemoria di fase51 -> drop-in."""

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
                    CREATE TABLE IF NOT EXISTS cicli (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        abilitato INTEGER NOT NULL,
                        ok_totale INTEGER NOT NULL,
                        n_stadi INTEGER NOT NULL,
                        n_falliti INTEGER NOT NULL,
                        conversione_riuscita INTEGER,   -- NULL se stadio assente
                        ts TEXT NOT NULL)""")
                con.execute("""
                    CREATE TABLE IF NOT EXISTS stadi (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ciclo_id INTEGER NOT NULL,
                        nome TEXT NOT NULL,
                        ok INTEGER NOT NULL,
                        errore TEXT DEFAULT '',
                        FOREIGN KEY (ciclo_id) REFERENCES cicli(id) ON DELETE CASCADE)""")
                con.execute("CREATE INDEX IF NOT EXISTS idx_stadi_nome ON stadi(nome)")
        finally:
            con.close()

    def append(self, report: Any) -> None:
        """Persiste un ciclo + i suoi stadi in un'unica transazione atomica."""
        r = riepiloga(report)
        conv = None if r.conversione_riuscita is None else int(r.conversione_riuscita)
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            cur = con.execute(
                "INSERT INTO cicli (abilitato, ok_totale, n_stadi, n_falliti, "
                "conversione_riuscita, ts) VALUES (?,?,?,?,?,?)",
                (int(r.abilitato), int(r.ok_totale), r.n_stadi, r.n_falliti, conv, ts))
            ciclo_id = cur.lastrowid
            if r.stadi:
                con.executemany(
                    "INSERT INTO stadi (ciclo_id, nome, ok, errore) VALUES (?,?,?,?)",
                    [(ciclo_id, s.nome, int(s.ok), s.errore) for s in r.stadi])
            con.execute("COMMIT")
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    def conteggio(self) -> int:
        con = self._apri()
        try:
            return con.execute("SELECT COUNT(*) FROM cicli").fetchone()[0]
        finally:
            con.close()

    def metriche(self) -> MetricheFunnel:
        """Aggrega le metriche del funnel: contatori di ciclo (SQL O(1)) + breakdown
        per-stadio (GROUP BY)."""
        con = self._apri()
        try:
            row = con.execute(
                "SELECT COUNT(*) AS tot, "
                "COALESCE(SUM(ok_totale),0) AS ok, "
                "COALESCE(SUM(conversione_riuscita IS NOT NULL),0) AS conv_tent, "
                "COALESCE(SUM(CASE WHEN conversione_riuscita=1 THEN 1 ELSE 0 END),0) "
                "  AS conv_ok "
                "FROM cicli").fetchone()
            per_stadio: Dict[str, MetricheStadio] = {}
            for s in con.execute(
                    "SELECT nome, COUNT(*) AS eseguiti, "
                    "SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END) AS falliti "
                    "FROM stadi GROUP BY nome"):
                per_stadio[s["nome"]] = MetricheStadio(
                    s["nome"], s["eseguiti"], s["falliti"])
            return MetricheFunnel(
                cicli_totali=row["tot"], cicli_ok=row["ok"],
                conversioni_tentate=row["conv_tent"],
                conversioni_riuscite=row["conv_ok"], per_stadio=per_stadio)
        finally:
            con.close()


class _ConnCondivisa:
    """Proxy su una connessione condivisa con `close()` NEUTRALIZZATO: lo store
    chiude la connessione a ogni operazione (idioma conn-per-operazione, fase34), ma
    un DB :memory: vive solo finche' la sua connessione e' aperta -> qui close e'
    no-op e la connessione reale sopravvive tra le operazioni."""

    def __init__(self, con: sqlite3.Connection) -> None:
        object.__setattr__(self, "_con", con)

    def close(self) -> None:                     # no-op: la connessione resta viva
        pass

    def __enter__(self):
        return self._con.__enter__()

    def __exit__(self, *a):
        return self._con.__exit__(*a)

    def __getattr__(self, name):
        return getattr(self._con, name)

    def __setattr__(self, name, value):
        setattr(self._con, name, value)


def crea_store_sqlite(percorso: str = ":memory:") -> StoreCicliSQLite:
    """Factory: store durevole su file (o :memory:). Per :memory: usa una connessione
    persistente condivisa (altrimenti ogni connect creerebbe un DB vuoto distinto)."""
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return StoreCicliSQLite(lambda: _ConnCondivisa(con))
    return StoreCicliSQLite(lambda: sqlite3.connect(percorso))
