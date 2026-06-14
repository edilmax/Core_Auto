"""
CORE_AUTO - Fase 15: Idempotency Manager (Production Ready).

Garantisce l'esecuzione "exactly-once" delle operazioni mutanti (escrow, split,
rimborsi) tramite Idempotency-Key, con locking pessimistico su SQLite.

Modello di stato di una chiave:
  1. ACQUISITO   -> il chiamante ha il lock, deve eseguire l'operazione e poi
                    chiamare store(token=...) (o release in caso di errore).
  2. IN_CORSO    -> un altro worker la sta eseguendo (lock fresco) -> 409 + Retry-After.
  3. IN_CACHE    -> risposta gia' prodotta e non scaduta -> replay deterministico.
  4. CONFLITTO   -> stessa key, fingerprint del body diverso -> 422 (difesa anti-abuso).

Garanzie di concorrenza:
  - acquire() gira in un'unica transazione `BEGIN IMMEDIATE` (un solo writer in WAL),
    quindi la sequenza leggi-decidi-scrivi e' atomica tra i worker.
  - Lo "steal" di un lock scaduto e tutte le ri-acquisizioni usano UPDATE
    condizionali (compare-and-swap su rowcount): difesa ridondante contro doppia
    esecuzione anche con piu' handle/processi.
  - store()/release() sono scoped per token: un worker il cui lock e' stato rubato
    (timeout) NON puo' sovrascrivere la risposta del worker subentrato.

NOTA DI ADATTAMENTO: il modulo e' autosufficiente (crea il proprio schema +
indici), allineato ai PRAGMA di resilienza H4 del progetto (WAL, busy_timeout,
synchronous=NORMAL). Si integra come singleton thread-safe.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger("core_auto.idempotency")


class EsitoAcquisizione(Enum):
    """Esito di una acquire(): determina la risposta HTTP del chiamante."""
    ACQUISITO = "acquired"        # esegui l'operazione, poi store()/release()
    IN_CORSO = "in_progress"      # un altro worker la sta eseguendo -> 409
    IN_CACHE = "cached"           # risposta gia' disponibile -> replay
    CONFLITTO = "conflict"        # stessa key, body diverso -> 422


@dataclass(frozen=True)  # NB: niente slots= (Python 3.9 non lo supporta)
class RisultatoIdempotenza:
    """Risultato immutabile di acquire().

    Attributes:
        esito: stato della chiave (vedi EsitoAcquisizione).
        token: token di lock da passare a store()/release() (solo se ACQUISITO).
        risposta: dict {status, body, headers} (solo se IN_CACHE).
        retry_after: secondi suggeriti per il retry (solo se IN_CORSO).
    """
    esito: EsitoAcquisizione
    token: Optional[str] = None
    risposta: Optional[Dict[str, Any]] = None
    retry_after: Optional[int] = None


class IdempotencyManager:
    """Singleton thread-safe per la gestione dell'idempotenza su SQLite."""

    _instance: Optional["IdempotencyManager"] = None
    _singleton_lock = threading.Lock()

    def __new__(cls, db_path: Optional[str] = None) -> "IdempotencyManager":
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._initialized = False
                    cls._instance = inst
        return cls._instance

    def __init__(self, db_path: Optional[str] = None) -> None:
        # L'init completo gira una sola volta, protetto dal lock del singleton
        # (evita doppia inizializzazione in race tra thread).
        if self._initialized:
            if db_path and db_path != self._db_path:
                logger.warning(
                    "IdempotencyManager gia' inizializzato su db=%s: il nuovo "
                    "db_path=%s viene IGNORATO (singleton).", self._db_path, db_path)
            return
        with self._singleton_lock:
            if self._initialized:
                return
            self._db_path = db_path or os.environ.get("CORE_AUTO_DB", "core_auto.db")
            self._ttl_hours = int(os.environ.get("IDEMPOTENCY_TTL_HOURS", "24"))
            # Soglia oltre la quale un lock e' considerato "morto" (worker crashato).
            self._lock_timeout_min = int(
                os.environ.get("IDEMPOTENCY_LOCK_TIMEOUT_MIN", "5"))
            # Retry difensivo su SQLITE_BUSY residuo (oltre busy_timeout/BEGIN
            # IMMEDIATE): tentativi e backoff lineare base (secondi).
            self._acquire_retries = int(
                os.environ.get("IDEMPOTENCY_ACQUIRE_RETRIES", "3"))
            self._acquire_backoff = float(
                os.environ.get("IDEMPOTENCY_ACQUIRE_BACKOFF", "0.05"))
            self._init_schema()
            self._initialized = True
            logger.info("IdempotencyManager inizializzato (db=%s, ttl=%sh, "
                        "lock_timeout=%smin)", self._db_path, self._ttl_hours,
                        self._lock_timeout_min)

    # ─────────────────────────────────────────────────────────────────────────
    # Connessione / schema
    # ─────────────────────────────────────────────────────────────────────────
    def _conn(self) -> sqlite3.Connection:
        """Connessione resiliente (H4) in autocommit per gestire le transazioni
        manualmente (BEGIN IMMEDIATE in acquire)."""
        conn = sqlite3.connect(self._db_path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        """Crea (idempotente) tabella e indici per chiavi/lock/scadenze."""
        cartella = os.path.dirname(self._db_path)
        if cartella:
            os.makedirs(cartella, exist_ok=True)
        conn = self._conn()
        try:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS idempotency_keys (
                       idempotency_key      TEXT PRIMARY KEY,
                       request_fingerprint  TEXT NOT NULL,
                       locked_by            TEXT,
                       locked_at            TEXT,
                       expires_at           TEXT NOT NULL,
                       correlation_id       TEXT,
                       response_status      INTEGER,
                       response_body        TEXT,
                       response_headers     TEXT,
                       created_at           TEXT NOT NULL DEFAULT (datetime('now'))
                   )""")
            # Sweep dei lock morti: indice parziale sui soli record bloccati.
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_idem_locked "
                "ON idempotency_keys(locked_at) WHERE locked_by IS NOT NULL")
            # Purge delle cache scadute.
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_idem_expires "
                "ON idempotency_keys(expires_at)")
        finally:
            conn.close()

    # ─────────────────────────────────────────────────────────────────────────
    # Helper
    # ─────────────────────────────────────────────────────────────────────────
    def fingerprint(self, method: str, path: str, body: bytes) -> str:
        """Hash SHA-256 della richiesta (metodo+path+body), hashing incrementale
        per non materializzare body grandi in memoria. Separatori NUL per evitare
        ambiguita' di concatenazione."""
        h = hashlib.sha256()
        h.update(method.upper().encode("utf-8"))
        h.update(b"\x00")
        h.update(path.encode("utf-8"))
        h.update(b"\x00")
        h.update(body or b"")
        return h.hexdigest()

    @staticmethod
    def _nuovo_token() -> str:
        """Token di lock univoco per (processo, thread, richiesta)."""
        return f"{os.getpid()}_{threading.get_ident()}_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _parse_dt(value: Optional[str]) -> Optional[datetime]:
        """Parsing difensivo di un timestamp ISO; normalizza a UTC-aware."""
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    # ─────────────────────────────────────────────────────────────────────────
    # API principale
    # ─────────────────────────────────────────────────────────────────────────
    def acquire(
        self,
        key: str,
        fingerprint: str,
        correlation_id: Optional[str] = None,
    ) -> RisultatoIdempotenza:
        """Acquisisce il lock per `key` o restituisce lo stato corrente.

        Wrapper difensivo: `busy_timeout` + `BEGIN IMMEDIATE` gia' serializzano i
        writer, ma su `SQLITE_BUSY` residuo (es. snapshot WAL) ritenta con backoff
        lineare prima di propagare l'errore. La logica resta in `_acquire_once`.

        Args:
            key: Idempotency-Key fornita dal client.
            fingerprint: impronta del corpo richiesta (vedi self.fingerprint).
            correlation_id: id di tracciamento opzionale.

        Returns:
            RisultatoIdempotenza con l'esito (ACQUISITO/IN_CORSO/IN_CACHE/CONFLITTO).
        """
        for tentativo in range(1, self._acquire_retries + 1):
            try:
                return self._acquire_once(key, fingerprint, correlation_id)
            except sqlite3.OperationalError as exc:
                if not _is_locked_error(exc) or tentativo == self._acquire_retries:
                    raise
                attesa = self._acquire_backoff * tentativo
                logger.warning("Idempotency acquire: DB occupato key=%s, retry "
                               "%s/%s tra %.3fs", key, tentativo,
                               self._acquire_retries, attesa)
                time.sleep(attesa)
        # irraggiungibile: l'ultimo tentativo o ritorna o rilancia.
        raise RuntimeError("acquire: stato irraggiungibile")  # pragma: no cover

    def _acquire_once(
        self,
        key: str,
        fingerprint: str,
        correlation_id: Optional[str] = None,
    ) -> RisultatoIdempotenza:
        """Singolo tentativo di acquisizione (RMW atomico in BEGIN IMMEDIATE)."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        exp_iso = (now + timedelta(hours=self._ttl_hours)).isoformat()
        lock_timeout = timedelta(minutes=self._lock_timeout_min)
        token = self._nuovo_token()
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")  # un solo writer: RMW atomico

            # 1) Fast path: prima volta che vediamo la chiave.
            cur = conn.execute(
                """INSERT OR IGNORE INTO idempotency_keys
                       (idempotency_key, request_fingerprint, locked_by, locked_at,
                        expires_at, correlation_id)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                (key, fingerprint, token, now_iso, exp_iso, correlation_id))
            if cur.rowcount == 1:
                conn.execute("COMMIT")
                return RisultatoIdempotenza(EsitoAcquisizione.ACQUISITO, token=token)

            # 2) La chiave esiste: ne ispezioniamo lo stato.
            row = conn.execute(
                "SELECT * FROM idempotency_keys WHERE idempotency_key = ?",
                (key,)).fetchone()
            if row is None:  # difensivo: eliminata tra INSERT e SELECT
                conn.execute("COMMIT")
                return RisultatoIdempotenza(EsitoAcquisizione.IN_CORSO, retry_after=1)

            # 2a) Stessa key, body diverso -> conflitto (anti-abuso).
            if not _eq_const(row["request_fingerprint"], fingerprint):
                conn.execute("COMMIT")
                logger.warning("Idempotency CONFLITTO key=%s (fingerprint diverso)", key)
                return RisultatoIdempotenza(EsitoAcquisizione.CONFLITTO)

            # 2b) Lock attivo.
            if row["locked_by"] is not None:
                locked_at = self._parse_dt(row["locked_at"])
                if locked_at is not None and (now - locked_at) < lock_timeout:
                    retry = int((lock_timeout - (now - locked_at)).total_seconds()) + 1
                    conn.execute("COMMIT")
                    return RisultatoIdempotenza(
                        EsitoAcquisizione.IN_CORSO, retry_after=retry)
                # Lock morto -> steal via compare-and-swap.
                steal = conn.execute(
                    "UPDATE idempotency_keys SET locked_by=?, locked_at=?, "
                    "expires_at=? WHERE idempotency_key=? AND locked_by=? "
                    "AND locked_at IS ?",
                    (token, now_iso, exp_iso, key, row["locked_by"],
                     row["locked_at"]))
                conn.execute("COMMIT")
                if steal.rowcount == 1:
                    logger.info("Idempotency lock morto recuperato key=%s", key)
                    return RisultatoIdempotenza(
                        EsitoAcquisizione.ACQUISITO, token=token)
                return RisultatoIdempotenza(EsitoAcquisizione.IN_CORSO, retry_after=1)

            # 2c) Nessun lock ma nessuna risposta (release senza store) -> ri-acquisisci.
            if row["response_status"] is None:
                reacq = conn.execute(
                    "UPDATE idempotency_keys SET locked_by=?, locked_at=?, "
                    "expires_at=? WHERE idempotency_key=? AND locked_by IS NULL "
                    "AND response_status IS NULL",
                    (token, now_iso, exp_iso, key))
                conn.execute("COMMIT")
                if reacq.rowcount == 1:
                    return RisultatoIdempotenza(
                        EsitoAcquisizione.ACQUISITO, token=token)
                return RisultatoIdempotenza(EsitoAcquisizione.IN_CORSO, retry_after=1)

            # 2d) Risposta presente: valida solo se non scaduta (TTL).
            expires_at = self._parse_dt(row["expires_at"])
            if expires_at is not None and now > expires_at:
                reacq = conn.execute(
                    "UPDATE idempotency_keys SET request_fingerprint=?, "
                    "locked_by=?, locked_at=?, expires_at=?, response_status=NULL, "
                    "response_body=NULL, response_headers=NULL "
                    "WHERE idempotency_key=? AND expires_at=?",
                    (fingerprint, token, now_iso, exp_iso, key, row["expires_at"]))
                conn.execute("COMMIT")
                if reacq.rowcount == 1:
                    return RisultatoIdempotenza(
                        EsitoAcquisizione.ACQUISITO, token=token)
                return RisultatoIdempotenza(EsitoAcquisizione.IN_CORSO, retry_after=1)

            # 2e) Cache hit valida -> replay.
            conn.execute("COMMIT")
            return RisultatoIdempotenza(
                EsitoAcquisizione.IN_CACHE,
                risposta={
                    "status": row["response_status"],
                    "body": row["response_body"],
                    "headers": _json_loads_safe(row["response_headers"]),
                })
        except sqlite3.Error as exc:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:  # pragma: no cover - difensivo
                pass
            # I busy transitori sono gestiti (con retry) dal wrapper acquire():
            # qui niente ERROR per non sporcare i log dei casi recuperabili.
            if _is_locked_error(exc):
                logger.debug("Idempotency acquire: DB occupato key=%s (%s)", key, exc)
            else:
                logger.error("Idempotency acquire fallita key=%s", key, exc_info=True)
            raise
        finally:
            conn.close()

    def store(
        self,
        key: str,
        token: str,
        status: int,
        body: Optional[str],
        headers: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Salva la risposta e rilascia il lock, SOLO se `token` possiede il lock.

        Returns:
            True se la risposta e' stata persistita; False se il lock non era
            piu' posseduto (es. rubato per timeout) -> il chiamante sappia che
            il suo risultato e' un duplicato da scartare.
        """
        conn = self._conn()
        try:
            cur = conn.execute(
                """UPDATE idempotency_keys
                       SET response_status=?, response_body=?, response_headers=?,
                           locked_by=NULL, locked_at=NULL
                       WHERE idempotency_key=? AND locked_by=?""",
                (status, body, json.dumps(headers) if headers else None,
                 key, token))
            if cur.rowcount == 0:
                logger.warning("Idempotency store ignorato key=%s: lock non "
                               "posseduto (scaduto/rubato).", key)
                return False
            return True
        finally:
            conn.close()

    def release(self, key: str, token: str) -> bool:
        """Rilascio del lock senza salvare (errore business logic), token-scoped.

        Returns:
            True se il lock era posseduto da `token` ed e' stato rilasciato.
        """
        conn = self._conn()
        try:
            cur = conn.execute(
                "UPDATE idempotency_keys SET locked_by=NULL, locked_at=NULL "
                "WHERE idempotency_key=? AND locked_by=?", (key, token))
            return cur.rowcount > 0
        finally:
            conn.close()

    # ─────────────────────────────────────────────────────────────────────────
    # Manutenzione
    # ─────────────────────────────────────────────────────────────────────────
    def sweep(self, timeout_minutes: Optional[int] = None) -> int:
        """Sblocca in batch i lock morti (worker crashati). Restituisce il numero
        di lock liberati."""
        minuti = self._lock_timeout_min if timeout_minutes is None else timeout_minutes
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minuti)).isoformat()
        conn = self._conn()
        try:
            cur = conn.execute(
                "UPDATE idempotency_keys SET locked_by=NULL, locked_at=NULL "
                "WHERE locked_by IS NOT NULL AND locked_at < ?", (cutoff,))
            if cur.rowcount:
                logger.info("Idempotency sweep: %s lock morti liberati", cur.rowcount)
            return cur.rowcount
        finally:
            conn.close()

    def purge_expired(self) -> int:
        """Elimina le chiavi con cache scaduta e non in elaborazione. Restituisce
        il numero di righe rimosse."""
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = self._conn()
        try:
            cur = conn.execute(
                "DELETE FROM idempotency_keys "
                "WHERE expires_at < ? AND locked_by IS NULL", (now_iso,))
            if cur.rowcount:
                logger.info("Idempotency purge: %s chiavi scadute rimosse", cur.rowcount)
            return cur.rowcount
        finally:
            conn.close()

    # ─────────────────────────────────────────────────────────────────────────
    # Test support
    # ─────────────────────────────────────────────────────────────────────────
    @classmethod
    def _reset_instance(cls) -> None:
        """Azzera il singleton (solo per i test)."""
        with cls._singleton_lock:
            cls._instance = None


def _json_loads_safe(value: Optional[str]) -> Dict[str, Any]:
    """json.loads difensivo: restituisce {} su None o JSON non valido."""
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _eq_const(a: Optional[str], b: Optional[str]) -> bool:
    """Confronto timing-safe dei fingerprint (entrambi gia' hash esadecimali)."""
    import hmac
    return hmac.compare_digest(str(a or ""), str(b or ""))


def _is_locked_error(exc: BaseException) -> bool:
    """True se l'errore SQLite e' un SQLITE_BUSY/locked transitorio (retriabile)."""
    return (isinstance(exc, sqlite3.OperationalError)
            and any(k in str(exc).lower() for k in ("locked", "busy")))
