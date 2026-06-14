"""
CORE_AUTO - Fase 16: Outbox Publisher & Dispatcher (Production Ready).

Pattern Transactional Outbox con consegna **at-least-once**: i messaggi vengono
inseriti nella tabella `outbox` DENTRO la stessa transazione DB che produce
l'effetto di business (es. creazione escrow), garantendo che evento e stato
siano atomici. Un dispatcher in background li consegna ai sottoscrittori con
backoff, lease anti-blocco, DLQ e reclaim dei messaggi orfani.

Stati: pending -> processing -> completed | failed (retry) | dead_letter.

Garanzie:
  - Atomicità producer: publish() usa la connessione/transazione del chiamante.
  - Exactly-once NON garantito (i consumer DEVONO essere idempotenti): un crash
    tra l'esecuzione dell'handler e l'update finale ricausa la consegna.
  - Nessun messaggio resta bloccato: i lock 'processing' scaduti vengono
    recuperati (reclaim) a 'failed'.
  - Lock scoped per worker: un dispatcher il cui lease e' scaduto non puo'
    sovrascrivere l'esito di chi ha ripreso il messaggio.

NOTA DI ADATTAMENTO: il modulo originale importava `fase11_alerting` (inesistente
in questo progetto) e non creava lo schema. Qui lo schema e' autosufficiente e
l'handler Telegram usa `Config.TELEGRAM_*` via `requests` (come `fase13`).
"""
from __future__ import annotations

import concurrent.futures
import http.client
import ipaddress
import json
import logging
import os
import random
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger("core_auto.outbox")

Handler = Callable[[Dict[str, Any]], bool]

# Stati terminali/intermedi.
_STATI_DA_CONSEGNARE = ("pending", "failed")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def inizializza_schema(db_path: str) -> None:
    """Crea (idempotente) la tabella `outbox` e gli indici. Va chiamata prima di
    qualsiasi publish() poiche' l'insert avviene nella transazione del chiamante."""
    cartella = os.path.dirname(db_path)
    if cartella:
        os.makedirs(cartella, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS outbox (
                   id             INTEGER PRIMARY KEY AUTOINCREMENT,
                   topic          TEXT NOT NULL,
                   partition_key  TEXT,
                   payload        TEXT NOT NULL,
                   headers        TEXT,
                   status         TEXT NOT NULL DEFAULT 'pending',
                   retry_count    INTEGER NOT NULL DEFAULT 0,
                   max_retries    INTEGER NOT NULL DEFAULT 3,
                   next_retry_at  TEXT,
                   locked_by      TEXT,
                   locked_at      TEXT,
                   last_error     TEXT,
                   correlation_id TEXT,
                   causation_id   TEXT,
                   created_at     TEXT NOT NULL DEFAULT (datetime('now')),
                   processed_at   TEXT
               )""")
        # Fetch dei messaggi pronti (status + scadenza retry, ordine FIFO).
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_outbox_due "
            "ON outbox(status, next_retry_at, id)")
        # Reclaim dei lock morti: solo i record in lavorazione.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_outbox_processing "
            "ON outbox(locked_at) WHERE status='processing'")
        conn.commit()
    finally:
        conn.close()


@dataclass
class OutboxMessage:
    """Messaggio da pubblicare nell'outbox."""
    topic: str
    payload: Dict[str, Any]
    partition_key: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    max_retries: int = 3
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None


class OutboxPublisher:
    """Singleton thread-safe per l'inserimento dei messaggi nell'outbox."""

    _instance: Optional["OutboxPublisher"] = None
    _singleton_lock = threading.Lock()

    # Tetto dimensione payload serializzato (anti-abuso / righe enormi).
    _MAX_PAYLOAD_BYTES = int(os.environ.get("OUTBOX_MAX_PAYLOAD_BYTES", str(256 * 1024)))

    def __new__(cls, db_path: Optional[str] = None) -> "OutboxPublisher":
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._initialized = False
                    cls._instance = inst
        return cls._instance

    def __init__(self, db_path: Optional[str] = None) -> None:
        if self._initialized:
            if db_path and db_path != self._db_path:
                logger.warning("OutboxPublisher gia' inizializzato su db=%s: "
                               "db_path=%s ignorato (singleton).", self._db_path, db_path)
            return
        with self._singleton_lock:
            if self._initialized:
                return
            self._db_path = db_path or os.environ.get("CORE_AUTO_DB", "core_auto.db")
            inizializza_schema(self._db_path)
            self._initialized = True
            logger.info("OutboxPublisher inizializzato (db=%s)", self._db_path)

    def publish(self, conn: sqlite3.Connection, msg: OutboxMessage) -> int:
        """Inserisce un messaggio nella transazione ATTIVA del chiamante.

        Il chiamante deve aver gia' aperto la transazione (idealmente
        BEGIN IMMEDIATE) e committera' insieme all'effetto di business.

        Args:
            conn: connessione del chiamante con transazione in corso.
            msg: messaggio da pubblicare.

        Returns:
            L'id del messaggio inserito.

        Raises:
            ValueError: payload non serializzabile o oltre il limite di dimensione.
        """
        if not msg.topic:
            raise ValueError("OutboxMessage.topic obbligatorio")
        try:
            payload_txt = json.dumps(msg.payload)
        except (TypeError, ValueError) as exc:
            raise ValueError("payload non serializzabile in JSON: %s" % exc)
        if len(payload_txt.encode("utf-8")) > self._MAX_PAYLOAD_BYTES:
            raise ValueError("payload oltre il limite (%s byte)" % self._MAX_PAYLOAD_BYTES)
        cur = conn.execute(
            """INSERT INTO outbox
                   (topic, partition_key, payload, headers, status, max_retries,
                    created_at, correlation_id, causation_id)
               VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)""",
            (msg.topic, msg.partition_key, payload_txt,
             json.dumps(msg.headers) if msg.headers else None,
             max(0, int(msg.max_retries)), _now_iso(),
             msg.correlation_id, msg.causation_id))
        return cur.lastrowid

    def publish_standalone(self, msg: OutboxMessage) -> int:
        """Pubblica aprendo una transazione propria (quando non c'e' un effetto
        di business da accorpare)."""
        conn = _connessione(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            mid = self.publish(conn, msg)
            conn.execute("COMMIT")
            return mid
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:  # pragma: no cover - difensivo
                pass
            raise
        finally:
            conn.close()

    @classmethod
    def _reset_instance(cls) -> None:
        """Azzera il singleton (solo per i test)."""
        with cls._singleton_lock:
            cls._instance = None


def _connessione(db_path: str) -> sqlite3.Connection:
    """Connessione resiliente (H4) in autocommit (transazioni gestite a mano)."""
    conn = sqlite3.connect(db_path, timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    # journal_mode=WAL e' persistente (impostato in inizializza_schema): qui no.
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# Validazione anti-SSRF per gli URL dei webhook
# ─────────────────────────────────────────────────────────────────────────────
def _host_allowlist() -> Optional[set]:
    raw = os.environ.get("OUTBOX_WEBHOOK_ALLOWLIST", "").strip()
    if not raw:
        return None
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _url_sicuro(url: str) -> bool:
    """True se l'URL e' un endpoint esterno sicuro per un webhook.

    Difese anti-SSRF: solo http(s); host nell'eventuale allowlist; nessun IP
    risolto privato/loopback/link-local/riservato (blocca metadata cloud,
    localhost, reti interne).

    FASE 20: questo e' solo il pre-check; il DNS rebinding (risoluzione diversa
    tra check e connect) e' chiuso ri-validando l'IP REALE del peer al momento
    del connect (vedi _SafeHTTPConnection/_verifica_peer).
    """
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    allow = _host_allowlist()
    if allow is not None and p.hostname.lower() not in allow:
        logger.warning("Webhook host non in allowlist: %s", p.hostname)
        return False
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80))
    except socket.gaierror:
        return False
    for info in infos:
        if _ip_non_instradabile(info[4][0]):
            logger.warning("Webhook verso IP non instradabile/interno bloccato: %s",
                           info[4][0])
            return False
    return True


def _ip_non_instradabile(ip_str: str) -> bool:
    """True se l'IP non e' un indirizzo pubblico instradabile (privato, loopback,
    link-local, riservato, multicast, unspecified) -> da bloccare per anti-SSRF."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # non parsabile -> blocca per sicurezza
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def _verifica_peer(sock) -> None:
    """Valida l'IP REALE del peer connesso (chiusura DNS-rebinding, FASE 20).

    Chiamata subito dopo il connect: se il socket e' attestato verso un IP
    interno/non instradabile, lo chiude e solleva, indipendentemente da cosa
    aveva restituito la risoluzione DNS in fase di pre-check.
    """
    try:
        ip = sock.getpeername()[0]
    except OSError as exc:  # pragma: no cover - difensivo
        raise OSError("peer IP non determinabile") from exc
    if _ip_non_instradabile(ip):
        sock.close()
        raise OSError(f"connessione bloccata verso IP non instradabile: {ip}")


class _SafeHTTPConnection(http.client.HTTPConnection):
    """HTTPConnection che valida il peer IP al connect (anti DNS-rebinding)."""
    def connect(self) -> None:
        super().connect()
        _verifica_peer(self.sock)


class _SafeHTTPSConnection(http.client.HTTPSConnection):
    """HTTPSConnection che valida il peer IP al connect (anti DNS-rebinding)."""
    def connect(self) -> None:
        super().connect()
        _verifica_peer(self.sock)


class _SafeHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_SafeHTTPConnection, req)


class _SafeHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_SafeHTTPSConnection, req,
                            context=self._context,
                            check_hostname=self._check_hostname)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Blocca i redirect (un 3xx potrebbe puntare a un IP interno)."""
    def redirect_request(self, *args: Any, **kwargs: Any):  # noqa: D401
        return None


class OutboxDispatcher:
    """Dispatcher in background (un'istanza per master Gunicorn) con backoff,
    DLQ, lease anti-blocco e reclaim dei messaggi orfani."""

    def __init__(self, db_path: Optional[str] = None, poll: float = 1.0,
                 batch: int = 10) -> None:
        self._db_path = db_path or os.environ.get("CORE_AUTO_DB", "core_auto.db")
        self._poll = poll
        self._batch = batch
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._ctl_lock = threading.Lock()
        self._worker_id = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
        # Lease: un 'processing' piu' vecchio di questo va recuperato.
        self._lease_timeout_s = int(os.environ.get("OUTBOX_LEASE_TIMEOUT_S", "300"))
        self._reclaim_every_s = int(os.environ.get("OUTBOX_RECLAIM_INTERVAL_S", "60"))
        self._backoff_cap_s = int(os.environ.get("OUTBOX_BACKOFF_CAP_S", "300"))
        self._wh_timeout = int(os.environ.get("OUTBOX_WEBHOOK_TIMEOUT_S", "10"))
        # Alert su profondita' DLQ (audit): soglia + throttling dell'allarme.
        self._dlq_alert_threshold = int(
            os.environ.get("OUTBOX_DLQ_ALERT_THRESHOLD", "10"))
        self._dlq_alert_every_s = int(
            os.environ.get("OUTBOX_DLQ_ALERT_INTERVAL_S", "3600"))
        self._last_reclaim = 0.0
        self._last_dlq_alert = 0.0
        # FASE 22: dispatch concorrente. Ogni messaggio ha il suo lock CAS, quindi
        # il parallelismo e' sicuro; le scritture SQLite serializzano sul
        # write-lock (busy_timeout), ma l'I/O degli handler va in parallelo.
        self._concurrency = max(1, int(os.environ.get("OUTBOX_CONCURRENCY", "4")))
        self._pool: Optional[concurrent.futures.ThreadPoolExecutor] = None
        self._handlers: Dict[str, Handler] = {}
        inizializza_schema(self._db_path)
        self._register_defaults()

    # --- Registrazione handler ---
    def register(self, topic: str, handler: Handler) -> None:
        """Registra/sovrascrive l'handler per un topic. handler(payload)->bool."""
        self._handlers[topic] = handler

    def _register_defaults(self) -> None:
        self._handlers.setdefault("telegram_alert", self._h_telegram)
        self._handlers.setdefault("webhook_partner", self._h_webhook)
        self._handlers.setdefault("email_admin", self._h_email)
        self._handlers.setdefault("audit_external", self._h_audit)

    def _backoff(self, retry: int) -> int:
        """Backoff esponenziale con full jitter, cap configurabile."""
        base = min(2 ** max(0, retry), self._backoff_cap_s)
        return max(1, int(random.uniform(base * 0.5, base)))

    # --- Handlers di default ---
    def _h_telegram(self, payload: Dict[str, Any]) -> bool:
        try:
            import requests  # lazy
            from fase13_protocollo_finale import Config
            if not (Config.TELEGRAM_BOT_TOKEN and Config.TELEGRAM_CHAT_ID):
                logger.warning("Telegram non configurato: messaggio scartato come consegnato")
                return True
            url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"
            r = requests.post(url, json={
                "chat_id": Config.TELEGRAM_CHAT_ID,
                "text": payload.get("message", ""),
                "parse_mode": "HTML",
            }, timeout=self._wh_timeout)
            return r.status_code == 200
        except Exception:
            logger.error("Telegram dispatch fallito", exc_info=True)
            return False

    @staticmethod
    def _webhook_headers(payload: Dict[str, Any]) -> Dict[str, str]:
        """Header per la consegna webhook, con Idempotency-Key stabile in uscita
        (FASE 21) derivata dall'id outbox: il partner puo' deduplicare i retry."""
        headers = {"Content-Type": "application/json"}
        did = (payload.get("_outbox") or {}).get("message_id")
        if did is not None:
            headers["Idempotency-Key"] = f"outbox-{did}"
            headers["X-Outbox-Delivery-Id"] = str(did)
        return headers

    def _h_webhook(self, payload: Dict[str, Any]) -> bool:
        url = payload.get("url", "")
        if not _url_sicuro(url):
            logger.error("Webhook URL non sicuro/non valido, consegna rifiutata: %s", url)
            return False
        try:
            data = json.dumps(payload.get("body", {})).encode("utf-8")
            req = urllib.request.Request(
                url, data=data, method="POST",
                headers=self._webhook_headers(payload))
            # FASE 20: no-redirect + validazione del peer IP al connect.
            opener = urllib.request.build_opener(
                _NoRedirect(), _SafeHTTPHandler(), _SafeHTTPSHandler())
            with opener.open(req, timeout=self._wh_timeout) as r:
                r.read(1024)  # drena una quota limitata della risposta
                return 200 <= r.status < 300
        except Exception:
            logger.error("Webhook dispatch fallito url=%s", url, exc_info=True)
            return False

    def _h_email(self, payload: Dict[str, Any]) -> bool:
        logger.info("Email (stub) subject=%s", payload.get("subject"))
        return True

    def _h_audit(self, payload: Dict[str, Any]) -> bool:
        logger.info("Audit esterno (stub) event=%s", payload.get("event_type"))
        return True

    # --- Engine ---
    def _fetch(self) -> List[sqlite3.Row]:
        conn = _connessione(self._db_path)
        try:
            return conn.execute(
                """SELECT * FROM outbox
                       WHERE status IN ('pending','failed')
                         AND (next_retry_at IS NULL OR next_retry_at <= ?)
                       ORDER BY id ASC LIMIT ?""",
                (_now_iso(), self._batch)).fetchall()
        finally:
            conn.close()

    def _process(self, row: sqlite3.Row) -> None:
        mid, topic = row["id"], row["topic"]
        handler = self._handlers.get(topic)
        if handler is None:
            logger.critical("Nessun handler per il topic '%s' (id=%s)", topic, mid)
            return

        conn = _connessione(self._db_path)
        try:
            # Lock atomico (CAS): solo uno tra i dispatcher acquisisce il record.
            cur = conn.execute(
                "UPDATE outbox SET status='processing', locked_by=?, locked_at=? "
                "WHERE id=? AND status IN ('pending','failed')",
                (self._worker_id, _now_iso(), mid))
            if cur.rowcount == 0:
                return  # gia' preso da un altro worker

            # Esecuzione handler FUORI transazione; mai deve lasciare 'processing'.
            try:
                payload = json.loads(row["payload"])
                # FASE 21: meta per la consegna idempotente in uscita. La chiave
                # e' stabile su TUTTI i retry (deriva dall'id), cosi' il consumer
                # puo' deduplicare. Iniettata nel wrapper, NON nel body inviato.
                if isinstance(payload, dict):
                    payload["_outbox"] = {"message_id": mid,
                                          "retry_count": row["retry_count"]}
                ok = bool(handler(payload))
                errore = None if ok else "handler ha restituito False"
            except Exception as exc:  # handler difettoso -> trattato come fallimento
                ok = False
                errore = "eccezione handler: %s" % exc
                logger.error("Handler '%s' ha sollevato (id=%s)", topic, mid, exc_info=True)

            if ok:
                conn.execute(
                    "UPDATE outbox SET status='completed', processed_at=?, "
                    "locked_by=NULL, locked_at=NULL WHERE id=? AND locked_by=?",
                    (_now_iso(), mid, self._worker_id))
                return

            # Fallimento: incremento atomico + DLQ oltre max_retries.
            rc = row["retry_count"] + 1
            if rc >= row["max_retries"]:
                conn.execute(
                    "UPDATE outbox SET status='dead_letter', retry_count=?, "
                    "last_error=?, locked_by=NULL, locked_at=NULL "
                    "WHERE id=? AND locked_by=?",
                    (rc, errore, mid, self._worker_id))
                logger.critical("DLQ: id=%s topic=%s (%s tentativi)", mid, topic, rc)
            else:
                nxt = (datetime.now(timezone.utc)
                       + timedelta(seconds=self._backoff(rc))).isoformat()
                conn.execute(
                    "UPDATE outbox SET status='failed', retry_count=?, "
                    "next_retry_at=?, last_error=?, locked_by=NULL, locked_at=NULL "
                    "WHERE id=? AND locked_by=?",
                    (rc, nxt, errore, mid, self._worker_id))
        except sqlite3.Error:
            logger.exception("Errore DB nel processing id=%s", mid)
        finally:
            conn.close()

    # --- Manutenzione ---
    def reclaim_stuck(self) -> int:
        """Recupera i messaggi bloccati in 'processing' oltre il lease (dispatcher
        crashato) riportandoli a 'failed' (pronti per il retry). Ritorna il numero."""
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(seconds=self._lease_timeout_s)).isoformat()
        conn = _connessione(self._db_path)
        try:
            cur = conn.execute(
                "UPDATE outbox SET status='failed', locked_by=NULL, locked_at=NULL "
                "WHERE status='processing' AND locked_at < ?", (cutoff,))
            if cur.rowcount:
                logger.warning("Outbox reclaim: %s messaggi orfani recuperati", cur.rowcount)
            return cur.rowcount
        finally:
            conn.close()

    def requeue_dead_letter(self, message_id: Optional[int] = None) -> int:
        """Rimette in coda i messaggi in DLQ (tutti o uno specifico)."""
        conn = _connessione(self._db_path)
        try:
            if message_id is None:
                cur = conn.execute(
                    "UPDATE outbox SET status='pending', retry_count=0, "
                    "next_retry_at=NULL, last_error=NULL WHERE status='dead_letter'")
            else:
                cur = conn.execute(
                    "UPDATE outbox SET status='pending', retry_count=0, "
                    "next_retry_at=NULL, last_error=NULL "
                    "WHERE status='dead_letter' AND id=?", (message_id,))
            return cur.rowcount
        finally:
            conn.close()

    def purge_completed(self, retention_hours: int = 24) -> int:
        """Elimina i messaggi 'completed' piu' vecchi della retention."""
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(hours=retention_hours)).isoformat()
        conn = _connessione(self._db_path)
        try:
            cur = conn.execute(
                "DELETE FROM outbox WHERE status='completed' AND processed_at < ?",
                (cutoff,))
            if cur.rowcount:
                logger.info("Outbox purge: %s messaggi completati rimossi", cur.rowcount)
            return cur.rowcount
        finally:
            conn.close()

    def _invia_alert(self, message: str) -> None:
        """Alert best-effort via Config.TELEGRAM_*/WEBHOOK_URL (come fase13)."""
        try:
            import requests  # lazy
            from fase13_protocollo_finale import Config
            if Config.TELEGRAM_BOT_TOKEN and Config.TELEGRAM_CHAT_ID:
                requests.post(
                    f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={"chat_id": Config.TELEGRAM_CHAT_ID, "text": message},
                    timeout=self._wh_timeout)
            if Config.WEBHOOK_URL:
                requests.post(Config.WEBHOOK_URL,
                              json={"source": "core_auto_outbox", "message": message},
                              timeout=self._wh_timeout)
        except Exception:  # pragma: no cover - difensivo
            logger.error("Outbox: invio alert DLQ fallito", exc_info=True)

    def check_dlq_alert(self) -> int:
        """Se la profondita' DLQ supera la soglia, logga CRITICAL e invia un
        alert best-effort. Ritorna la profondita' corrente della DLQ."""
        depth = self.status().get("dead_letter", 0)
        if depth >= self._dlq_alert_threshold:
            logger.critical("Outbox DLQ depth=%s >= soglia=%s", depth,
                            self._dlq_alert_threshold)
            self._invia_alert(
                f"🚨 CORE_AUTO Outbox: {depth} messaggi in dead-letter "
                f"(soglia {self._dlq_alert_threshold})")
        return depth

    def status(self) -> Dict[str, int]:
        """Conteggio dei messaggi per stato (per health/monitoring)."""
        conn = _connessione(self._db_path)
        try:
            righe = conn.execute(
                "SELECT status, COUNT(*) c FROM outbox GROUP BY status").fetchall()
            return {r["status"]: r["c"] for r in righe}
        finally:
            conn.close()

    # --- Ciclo di vita ---
    def start(self) -> None:
        with self._ctl_lock:
            if self._running:
                return
            if self._concurrency > 1:
                self._pool = concurrent.futures.ThreadPoolExecutor(
                    max_workers=self._concurrency, thread_name_prefix="outbox-wk")
            self._running = True
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="outbox-dispatcher")
            self._thread.start()
            logger.info("Outbox Dispatcher avviato (worker=%s, concorrenza=%s)",
                        self._worker_id, self._concurrency)

    def stop(self, timeout: float = 5.0) -> None:
        with self._ctl_lock:
            self._running = False
            t, pool = self._thread, self._pool
            self._pool = None
        if t is not None:
            t.join(timeout=timeout)
        if pool is not None:
            pool.shutdown(wait=True)
        logger.info("Outbox Dispatcher fermato")

    def _dispatch_batch(self, righe: List[sqlite3.Row]) -> None:
        """Processa il batch in parallelo (pool) se concorrenza>1, sequenziale
        altrimenti. Sicuro: ogni riga ha il proprio lock CAS in _process."""
        if self._pool is not None and len(righe) > 1:
            futures = [self._pool.submit(self._process, row) for row in righe]
            concurrent.futures.wait(futures)  # _process non solleva (gestito dentro)
        else:
            for row in righe:
                if not self._running:
                    break
                self._process(row)

    def _run(self) -> None:
        while self._running:
            try:
                now = time.time()
                if now - self._last_reclaim >= self._reclaim_every_s:
                    self.reclaim_stuck()
                    self._last_reclaim = now
                if now - self._last_dlq_alert >= self._dlq_alert_every_s:
                    self.check_dlq_alert()
                    self._last_dlq_alert = now
                righe = self._fetch()
                self._dispatch_batch(righe)
                # Se il batch e' pieno c'e' probabilmente altro lavoro: non dormire.
                if len(righe) < self._batch:
                    time.sleep(self._poll)
            except Exception:
                logger.exception("Errore nel loop del dispatcher")
                time.sleep(5)
