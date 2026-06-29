"""
CORE_AUTO - Fase 158: DOMANDA / lista d'attesa + Credito Fondatore (cold-start).

Sito online ma vuoto = sembra morto. Quando un ospite cerca e NON trova nulla, invece della
pagina vuota: catturiamo email+citta ("ti avvisiamo appena apriamo") e gli diamo un CREDITO
FONDATORE (non-cashabile, floor-guarded) valido sulla prima prenotazione -> torna e prenota.
La domanda raccolta diventa l'ARMA per gli host: "N persone cercano gia' a <citta>".

Logica denaro coerente: il credito e' un TOKEN FIRMATO (non falsificabile), non-cashabile; la
riduzione al checkout viene finanziata SOLO dalla nostra commissione con guardia floor
(mai sotto i costi) -> ZERO perdita. Qui niente movimento denaro: solo domanda + emissione
credito firmato. Durevole SQLite (conn-per-op, dedup email+citta).
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional

CREDITO_FONDATORE_CENTS = 500          # 5,00 EUR di benvenuto (configurabile)
GIORNI_VALIDITA = 180


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


def _email_ok(e: Any) -> bool:
    return isinstance(e, str) and 3 <= len(e) <= 254 and "@" in e and "." in e.split("@")[-1]


class GestoreDomanda:
    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], *,
                 firma: Any = None, orologio: Optional[Callable[[], int]] = None) -> None:
        self._cf = conn_factory
        self._firma = firma
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
                con.execute("""CREATE TABLE IF NOT EXISTS domanda (
                    email TEXT NOT NULL, citta TEXT NOT NULL,
                    check_in TEXT DEFAULT '', check_out TEXT DEFAULT '',
                    party INTEGER DEFAULT 1, ts INTEGER NOT NULL,
                    PRIMARY KEY (email, citta))""")
        finally:
            con.close()

    def registra(self, email: Any, citta: Any, *, check_in: str = "", check_out: str = "",
                 party: Any = 1) -> bool:
        """Registra una richiesta (dedup per email+citta). False se email/citta non validi."""
        if not _email_ok(email) or not (isinstance(citta, str) and citta.strip()):
            return False
        em = email.strip().lower()
        ci = citta.strip().lower()
        p = party if isinstance(party, int) and not isinstance(party, bool) and party > 0 else 1
        con = self._apri()
        try:
            with con:
                con.execute("INSERT INTO domanda (email, citta, check_in, check_out, party, ts) "
                            "VALUES (?,?,?,?,?,?) ON CONFLICT(email, citta) DO UPDATE SET "
                            "check_in=excluded.check_in, check_out=excluded.check_out, "
                            "party=excluded.party, ts=excluded.ts",
                            (em, ci, str(check_in or ""), str(check_out or ""), p, self._now()))
            return True
        finally:
            con.close()

    def conta(self, citta: Any = None) -> int:
        """Quante persone cercano (totale o per citta). Prova sociale per gli host."""
        con = self._apri()
        try:
            if isinstance(citta, str) and citta.strip():
                r = con.execute("SELECT COUNT(*) FROM domanda WHERE citta=?",
                                (citta.strip().lower(),)).fetchone()
            else:
                r = con.execute("SELECT COUNT(*) FROM domanda").fetchone()
            return int(r[0]) if r else 0
        finally:
            con.close()

    def per_citta(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        lim = limit if isinstance(limit, int) and 0 < limit <= 500 else 50
        con = self._apri()
        try:
            righe = con.execute("SELECT citta, COUNT(*) c FROM domanda GROUP BY citta "
                                "ORDER BY c DESC LIMIT ?", (lim,)).fetchall()
            return [{"citta": r[0], "richieste": int(r[1])} for r in righe]
        finally:
            con.close()

    def email_citta(self, citta: Any, *, limit: int = 1000) -> List[str]:
        """Email da avvisare quando un host pubblica in quella citta'."""
        if not (isinstance(citta, str) and citta.strip()):
            return []
        lim = limit if isinstance(limit, int) and 0 < limit <= 5000 else 1000
        con = self._apri()
        try:
            righe = con.execute("SELECT email FROM domanda WHERE citta=? LIMIT ?",
                                (citta.strip().lower(), lim)).fetchall()
            return [r[0] for r in righe]
        finally:
            con.close()

    def emette_credito_fondatore(self, email: Any, citta: Any, *,
                                 credito_cents: int = CREDITO_FONDATORE_CENTS,
                                 giorni: int = GIORNI_VALIDITA) -> Optional[str]:
        """Token FIRMATO del Credito Fondatore (non falsificabile). None se non c'e' firma."""
        if self._firma is None or not _email_ok(email):
            return None
        c = credito_cents if isinstance(credito_cents, int) and 0 < credito_cents <= 5000 else \
            CREDITO_FONDATORE_CENTS
        return self._firma.codifica({
            "tipo": "credito_fondatore", "email": email.strip().lower(),
            "citta": (str(citta).strip().lower() if isinstance(citta, str) else ""),
            "credito_cents": c, "exp": self._now() + max(1, int(giorni)) * 86400})


def crea_gestore_domanda(percorso: str, *, firma: Any = None, orologio: Any = None
                         ) -> GestoreDomanda:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return GestoreDomanda(lambda: _ConnCondivisa(con), firma=firma, orologio=orologio)
    return GestoreDomanda(lambda: sqlite3.connect(percorso), firma=firma, orologio=orologio)
