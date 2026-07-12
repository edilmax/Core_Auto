"""
CORE_AUTO - Fase 162: Pagamenti PENDENTI (hold prima del pagamento) — chiude il buco logico
per cui una prenotazione non pagata bloccava la stanza per sempre.

Quando serve un pagamento (Stripe configurato), al book la stanza va in HOLD e qui si registra
la prenotazione 'in_attesa' con una SCADENZA. Il webhook Stripe (pagamento riuscito) la
'conferma'. Uno sweeper periodico LIBERA gli hold scaduti non pagati (fase58.rilascia +
garanzia.annulla). Conserva anche tassa+comune per registrarli nel ledger (fase147) al pagamento.

Durevole SQLite (conn-per-op, row_factory=Row), idempotente, denaro in cents interi.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional

HOLD_SECONDI_DEFAULT = 120           # 2 minuti per pagare, poi la stanza si libera (urgenza tipo Agoda: chi paga prima se la prende)


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


class PagamentiPendenti:
    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], *,
                 orologio: Optional[Callable[[], int]] = None) -> None:
        self._cf = conn_factory
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
                con.execute("""CREATE TABLE IF NOT EXISTS pendenti (
                    riferimento TEXT PRIMARY KEY,
                    alloggio_id TEXT NOT NULL, check_in TEXT NOT NULL, check_out TEXT NOT NULL,
                    idem_key TEXT NOT NULL DEFAULT '',
                    tassa_cents INTEGER NOT NULL DEFAULT 0, comune TEXT NOT NULL DEFAULT '',
                    host_id TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
                    quote_token TEXT NOT NULL DEFAULT '', corpo_json TEXT NOT NULL DEFAULT '',
                    scadenza_ts INTEGER NOT NULL, stato TEXT NOT NULL DEFAULT 'in_attesa',
                    creato_ts INTEGER NOT NULL)""")
                for _c in ("host_id", "email", "quote_token", "corpo_json"):
                    try:
                        con.execute("ALTER TABLE pendenti ADD COLUMN %s TEXT NOT NULL DEFAULT ''" % _c)
                    except sqlite3.OperationalError:
                        pass
        finally:
            con.close()

    def _riga(self, r: sqlite3.Row) -> Dict[str, Any]:
        k = r.keys()
        g = lambda n, d="": (r[n] if n in k else d)
        return {"riferimento": r["riferimento"], "alloggio_id": r["alloggio_id"],
                "check_in": r["check_in"], "check_out": r["check_out"],
                "idem_key": r["idem_key"], "tassa_cents": int(r["tassa_cents"]),
                "comune": r["comune"], "stato": r["stato"], "scadenza_ts": int(r["scadenza_ts"]),
                "host_id": g("host_id"), "email": g("email"),
                "quote_token": g("quote_token"), "corpo_json": g("corpo_json")}

    def registra(self, riferimento: Any, *, alloggio_id: str, check_in: str, check_out: str,
                 idem_key: str = "", tassa_cents: int = 0, comune: str = "",
                 host_id: str = "", email: str = "", quote_token: str = "",
                 corpo_json: str = "", stato: str = "in_attesa",
                 scadenza_ts: Optional[int] = None) -> bool:
        if not (isinstance(riferimento, str) and riferimento and alloggio_id):
            return False
        now = self._now()
        sca = scadenza_ts if isinstance(scadenza_ts, int) and not isinstance(scadenza_ts, bool) \
            else now + HOLD_SECONDI_DEFAULT
        t = tassa_cents if isinstance(tassa_cents, int) and not isinstance(tassa_cents, bool) \
            and tassa_cents > 0 else 0
        st = stato if stato in ("in_attesa", "in_attesa_host") else "in_attesa"
        con = self._apri()
        try:
            with con:
                con.execute(
                    "INSERT INTO pendenti (riferimento, alloggio_id, check_in, check_out, "
                    "idem_key, tassa_cents, comune, host_id, email, quote_token, corpo_json, "
                    "scadenza_ts, stato, creato_ts) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(riferimento) DO NOTHING",
                    (riferimento, alloggio_id, check_in, check_out, str(idem_key or ""),
                     t, str(comune or ""), str(host_id or ""), str(email or ""),
                     str(quote_token or ""), str(corpo_json or ""), sca, st, now))
            return True
        finally:
            con.close()

    def da_approvare(self, host_id: Any, *, limit: int = 100) -> List[Dict[str, Any]]:
        """Richieste 'in_attesa_host' per il pannello dell'host."""
        if not (isinstance(host_id, str) and host_id):
            return []
        lim = limit if isinstance(limit, int) and 0 < limit <= 500 else 100
        con = self._apri()
        try:
            righe = con.execute("SELECT * FROM pendenti WHERE stato='in_attesa_host' AND "
                                "host_id=? ORDER BY creato_ts LIMIT ?", (host_id, lim)).fetchall()
            return [self._riga(r) for r in righe]
        finally:
            con.close()

    def conferma(self, riferimento: Any) -> Optional[Dict[str, Any]]:
        """Pagamento riuscito -> 'pagato'. Ritorna il record (per il ledger tassa). None se assente."""
        if not (isinstance(riferimento, str) and riferimento):
            return None
        con = self._apri()
        try:
            with con:
                r = con.execute("SELECT * FROM pendenti WHERE riferimento=?",
                                (riferimento,)).fetchone()
                if r is None:
                    return None
                con.execute("UPDATE pendenti SET stato='pagato' WHERE riferimento=?",
                            (riferimento,))
            return self._riga(r)
        finally:
            con.close()

    def scaduti(self, *, ora_ts: Optional[int] = None) -> List[Dict[str, Any]]:
        ora = ora_ts if isinstance(ora_ts, int) and not isinstance(ora_ts, bool) else self._now()
        con = self._apri()
        try:
            righe = con.execute("SELECT * FROM pendenti WHERE stato IN "
                                "('in_attesa','in_attesa_host') AND scadenza_ts<=?",
                                (ora,)).fetchall()
            return [self._riga(r) for r in righe]
        finally:
            con.close()

    def rimuovi(self, riferimento: Any) -> bool:
        if not (isinstance(riferimento, str) and riferimento):
            return False
        con = self._apri()
        try:
            with con:
                cur = con.execute("DELETE FROM pendenti WHERE riferimento=?", (riferimento,))
            return bool(cur.rowcount)
        finally:
            con.close()

    def scadi(self, riferimento: Any) -> bool:
        """Hold scaduto (non pagato entro i 2 min): NON cancella il record, lo marca 'scaduto'
        conservando i dati. Serve a gestire un eventuale pagamento TARDIVO (link Stripe ancora
        vivo): al pagamento si ri-tenta il blocco stanza; se libera -> ancora sua, se presa da
        chi ha pagato prima -> rimborso. Evita 'soldi senza stanza'."""
        if not (isinstance(riferimento, str) and riferimento):
            return False
        con = self._apri()
        try:
            with con:
                cur = con.execute(
                    "UPDATE pendenti SET stato='scaduto' WHERE riferimento=? AND "
                    "stato IN ('in_attesa','in_attesa_host')", (riferimento,))
            return bool(cur.rowcount)
        finally:
            con.close()

    def marca_da_rimborsare(self, riferimento: Any) -> bool:
        """Pagamento tardivo su stanza già presa: marca 'rimborsato' (il cliente va rimborsato).
        Non riappare negli scaduti; verrà ripulito da pulisci_vecchi."""
        if not (isinstance(riferimento, str) and riferimento):
            return False
        con = self._apri()
        try:
            with con:
                cur = con.execute("UPDATE pendenti SET stato='rimborsato' WHERE riferimento=?",
                                  (riferimento,))
            return bool(cur.rowcount)
        finally:
            con.close()

    def pulisci_vecchi(self, *, eta_sec: int = 3600, ora_ts: Optional[int] = None) -> int:
        """Elimina i record 'scaduto'/'rimborsato' più vecchi di eta_sec (default 1h, ben oltre
        i 30 min di vita del link Stripe): housekeeping. Ritorna quanti rimossi."""
        ora = ora_ts if isinstance(ora_ts, int) and not isinstance(ora_ts, bool) else self._now()
        con = self._apri()
        try:
            with con:
                cur = con.execute(
                    "DELETE FROM pendenti WHERE stato IN ('scaduto','rimborsato') AND creato_ts<?",
                    (ora - max(60, int(eta_sec)),))
            return cur.rowcount
        finally:
            con.close()

    def info(self, riferimento: Any) -> Optional[Dict[str, Any]]:
        if not (isinstance(riferimento, str) and riferimento):
            return None
        con = self._apri()
        try:
            r = con.execute("SELECT * FROM pendenti WHERE riferimento=?", (riferimento,)).fetchone()
        finally:
            con.close()
        return self._riga(r) if r is not None else None


def crea_pagamenti_pendenti(percorso: str, *, orologio: Any = None) -> PagamentiPendenti:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        con.row_factory = sqlite3.Row
        return PagamentiPendenti(lambda: _ConnCondivisa(con), orologio=orologio)

    def cf() -> sqlite3.Connection:
        c = sqlite3.connect(percorso)
        c.row_factory = sqlite3.Row
        return c
    return PagamentiPendenti(cf, orologio=orologio)
