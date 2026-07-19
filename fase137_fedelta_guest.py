"""
CORE_AUTO - Fase 137: Programma fedeltà guest (punti per soggiorni → sconti).

Il guest accumula PUNTI a ogni soggiorno completato (1 punto per ogni X cents spesi) e sale
di LIVELLO (bronze/silver/gold/platinum) con moltiplicatore punti crescente. I punti si
riscattano come sconto (non-cashabile, 1 punto = Y cents, con tetto). Store DUREVOLE SQLite.
Tutto in interi (cents/punti). Idempotente per prenotazione (no doppio accredito). BLINDATO.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("core_auto.fedelta_guest")

CENTS_PER_PUNTO = 100            # 1 punto ogni 1€ speso
PUNTO_VALE_CENTS = 1            # 1 punto = 0.01€ in sconto
# (soglia_punti_totali, livello, moltiplicatore_bps)
LIVELLI: Tuple[Tuple[int, str, int], ...] = (
    (0, "bronze", 10000), (500, "silver", 11000),
    (2000, "gold", 12500), (5000, "platinum", 15000))


def livello_per_punti(punti_totali: int) -> Tuple[str, int]:
    nome, molt = "bronze", 10000
    for soglia, n, m in LIVELLI:
        if punti_totali >= soglia:
            nome, molt = n, m
    return nome, molt


class _ConnCondivisa:
    def __init__(self, con: sqlite3.Connection) -> None:
        object.__setattr__(self, "_con", con)

    def close(self) -> None:
        pass

    def __enter__(self):
        return self._con.__enter__()

    def __exit__(self, *a):
        return self._con.__exit__(*a)

    def __getattr__(self, n):
        return getattr(self._con, n)


class FedeltaGuest:
    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], *,
                 cents_per_punto: int = CENTS_PER_PUNTO,
                 orologio: Optional[Callable[[], int]] = None) -> None:
        self._cf = conn_factory
        self._cpp = max(1, int(cents_per_punto))
        self._now = orologio or (lambda: int(time.time()))

    def _apri(self) -> sqlite3.Connection:
        con = self._cf()
        try:
            con.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass
        return con

    def inizializza_schema(self) -> None:
        con = self._apri()
        try:
            with con:
                con.execute("""CREATE TABLE IF NOT EXISTS fedelta_saldo (
                    guest_id TEXT PRIMARY KEY, punti INTEGER NOT NULL DEFAULT 0,
                    punti_totali INTEGER NOT NULL DEFAULT 0)""")
                con.execute("""CREATE TABLE IF NOT EXISTS fedelta_accredito (
                    prenotazione_id TEXT PRIMARY KEY, guest_id TEXT NOT NULL,
                    punti INTEGER NOT NULL, ts INTEGER NOT NULL)""")
        finally:
            con.close()

    def accredita(self, prenotazione_id: str, guest_id: str, speso_cents: int) -> int:
        """Punti accreditati per un soggiorno completato (idempotente). Applica il
        moltiplicatore del livello CORRENTE. Ritorna i punti accreditati (0 se duplicato)."""
        if not (prenotazione_id and guest_id) or not isinstance(speso_cents, int) \
                or isinstance(speso_cents, bool) or speso_cents <= 0:
            return 0
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            if con.execute("SELECT 1 FROM fedelta_accredito WHERE prenotazione_id=?",
                           (str(prenotazione_id),)).fetchone():
                con.execute("ROLLBACK")
                return 0
            row = con.execute("SELECT punti, punti_totali FROM fedelta_saldo "
                              "WHERE guest_id=?", (str(guest_id),)).fetchone()
            saldo, totali = (row[0], row[1]) if row else (0, 0)
            _, molt = livello_per_punti(totali)
            base = speso_cents // self._cpp
            punti = base * molt // 10000
            if punti <= 0:
                con.execute("ROLLBACK")
                return 0
            con.execute("INSERT OR REPLACE INTO fedelta_saldo (guest_id, punti, "
                        "punti_totali) VALUES (?,?,?)",
                        (str(guest_id), saldo + punti, totali + punti))
            con.execute("INSERT INTO fedelta_accredito (prenotazione_id, guest_id, punti, "
                        "ts) VALUES (?,?,?,?)",
                        (str(prenotazione_id), str(guest_id), punti, self._now()))
            con.execute("COMMIT")
            return punti
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            logger.warning("accredita fallita (ISOLATA)", exc_info=True)
            return 0
        finally:
            con.close()

    def saldo(self, guest_id: str) -> Dict[str, Any]:
        con = self._apri()
        try:
            row = con.execute("SELECT punti, punti_totali FROM fedelta_saldo "
                              "WHERE guest_id=?", (str(guest_id),)).fetchone()
            punti, totali = (row[0], row[1]) if row else (0, 0)
            liv, molt = livello_per_punti(totali)
            return {"punti": punti, "punti_totali": totali, "livello": liv,
                    "moltiplicatore_bps": molt, "valore_cents": punti * PUNTO_VALE_CENTS}
        finally:
            con.close()

    def riscatta(self, guest_id: str, punti: int, *, max_cents: int = 10 ** 9) -> int:
        """Converte punti in sconto (cents). Ritorna i cents di sconto applicati."""
        chiesti = punti if isinstance(punti, int) and not isinstance(punti, bool) \
            and punti > 0 else 0
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT punti FROM fedelta_saldo WHERE guest_id=?",
                              (str(guest_id),)).fetchone()
            disp = row[0] if row else 0
            usa = min(disp, chiesti)
            sconto = min(usa * PUNTO_VALE_CENTS, max(0, int(max_cents)))
            usa = sconto // PUNTO_VALE_CENTS               # riallinea ai cents effettivi
            if usa <= 0:
                con.execute("ROLLBACK")
                return 0
            con.execute("UPDATE fedelta_saldo SET punti=? WHERE guest_id=?",
                        (disp - usa, str(guest_id)))
            con.execute("COMMIT")
            return usa * PUNTO_VALE_CENTS
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            return 0
        finally:
            con.close()


def crea_fedelta_guest(percorso: str, *, cents_per_punto: int = CENTS_PER_PUNTO,
                       orologio: Any = None) -> FedeltaGuest:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return FedeltaGuest(lambda: _ConnCondivisa(con), cents_per_punto=cents_per_punto,
                            orologio=orologio)
    return FedeltaGuest(lambda: sqlite3.connect(percorso, timeout=30),
                        cents_per_punto=cents_per_punto, orologio=orologio)
