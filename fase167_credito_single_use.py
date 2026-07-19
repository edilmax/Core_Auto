"""
CORE_AUTO - Fase 167: Registro SINGLE-USE dei crediti (Credito Fondatore / Credito Viaggio).

CHIUDE UN BUCO REALE (provato al collaudo 2026-07-16): il token `credito_fondatore` era un
BEARER riusabile all'INFINITO. `_sconto_credito` (fase59) verificava firma+tipo+scadenza+margine
ma NIENTE single-use -> lo STESSO credito da €50 scontava OGNI preventivo (3 prenotazioni ->
€150 regalati, senza limite). Chiunque ne ottiene uno iscrivendosi alla waitlist (fase158) e il
token e' condivisibile -> erosione sistematica del ricavo (mai perdita diretta grazie alla
guardia di margine, ma comunque un buco sfruttabile OGGI).

MODELLO: un credito e' identificato dalla FIRMA del suo token (`token.split('.')[-1]`, unica
perche' gli emittenti aggiungono un nonce). Il credito si CONSUMA alla FINALIZZAZIONE della
prenotazione (non al preventivo: cosi' il semplice browsing non brucia il credito, e per il
su-richiesta si consuma solo se APPROVATO, mai se rifiutato). Il preventivo CONTROLLA il registro
(`usato`) e non mostra lo sconto se il credito e' gia' speso.

`consuma(credito_id, riferimento)` e' ATOMICO (BEGIN IMMEDIATE) e idempotente sulla STESSA
prenotazione (un replay dello stesso book non ri-consuma): ritorna
  - "nuovo"  : prima volta (credito valido, sconto legittimo)
  - "stesso" : gia' consumato DA QUESTA prenotazione (replay idempotente -> ok)
  - "diverso": gia' speso su un'ALTRA prenotazione (riuso -> lo sconto non va onorato)

FAIL-OPEN (come il resto del codice "isolato"): i chiamanti trattano un errore dello store come
"non tracciato" -> una prenotazione legittima non viene MAI bloccata da un guasto del registro.

Durevole SQLite (conn-per-op, row_factory=Row).
Vincitrice benchmark: unica tabella con PK sul credito_id (dedup atomico), zero stato in RAM.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any, Callable, Optional


class _ConnCondivisa:
    """Wrapper per la connessione :memory: condivisa (i test): close() no-op."""
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


class RegistroCreditiUsati:
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
                con.execute("""CREATE TABLE IF NOT EXISTS crediti_usati (
                    credito_id TEXT PRIMARY KEY,
                    riferimento TEXT NOT NULL DEFAULT '',
                    ts INTEGER NOT NULL DEFAULT 0)""")
        finally:
            con.close()

    def usato(self, credito_id: Any) -> bool:
        """True se il credito e' gia' stato consumato. Input vuoto -> False (niente da tracciare)."""
        if not (isinstance(credito_id, str) and credito_id.strip()):
            return False
        con = self._apri()
        try:
            r = con.execute("SELECT 1 FROM crediti_usati WHERE credito_id=?",
                            (credito_id,)).fetchone()
            return r is not None
        finally:
            con.close()

    def consuma(self, credito_id: Any, riferimento: Any) -> str:
        """Consuma il credito per QUESTA prenotazione. ATOMICO. Ritorna nuovo|stesso|diverso.
        credito_id vuoto -> 'nuovo' (nessun credito da tracciare: non blocca nulla)."""
        if not (isinstance(credito_id, str) and credito_id.strip()):
            return "nuovo"
        rif = str(riferimento or "")
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            r = con.execute("SELECT riferimento FROM crediti_usati WHERE credito_id=?",
                            (credito_id,)).fetchone()
            if r is None:
                con.execute("INSERT INTO crediti_usati (credito_id, riferimento, ts) "
                            "VALUES (?,?,?)", (credito_id, rif, self._now()))
                con.execute("COMMIT")
                return "nuovo"
            con.execute("COMMIT")
            return "stesso" if r["riferimento"] == rif else "diverso"
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()


def crea_registro_crediti_usati(percorso: str, *, orologio: Any = None
                                ) -> RegistroCreditiUsati:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        con.row_factory = sqlite3.Row
        return RegistroCreditiUsati(lambda: _ConnCondivisa(con), orologio=orologio)

    def cf() -> sqlite3.Connection:
        c = sqlite3.connect(percorso, timeout=30)
        c.row_factory = sqlite3.Row
        return c
    return RegistroCreditiUsati(cf, orologio=orologio)
