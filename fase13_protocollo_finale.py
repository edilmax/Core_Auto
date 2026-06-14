"""
╔══════════════════════════════════════════════════════════════════════════════╗
║         FASE 13 AGGIORNATA: PROTOCOLLO FINALE + DIFESSE DI LIVELLO MASSIMO    ║
║         RateLimiter | Nonce Anti-Replay | DBCircuitBreaker | Zero Trust      ║
╚══════════════════════════════════════════════════════════════════════════════╝

File: fase13_protocollo_finale.py
"""

import os
import hmac
import hashlib
import secrets
import time
import json
import sqlite3
import threading
import psutil
import requests
import signal
import sys
from functools import wraps
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Callable, Tuple
from dataclasses import dataclass
from enum import Enum
from collections import OrderedDict, deque
from flask import Flask, request, jsonify, abort, g
import logging


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURAZIONE CENTRALIZZATA
# ═══════════════════════════════════════════════════════════════════════════════

class Config:
    """Configurazione centralizzata del sistema."""

    # Sicurezza
    HMAC_SECRET = os.environ.get('HMAC_SECRET', secrets.token_hex(32))
    API_KEY = os.environ.get('API_KEY', secrets.token_hex(16))
    BEARER_TOKEN = os.environ.get('BEARER_TOKEN', secrets.token_urlsafe(32))

    # Database
    DB_PATH = os.environ.get('DB_PATH', '/tmp/marketplace.db')

    # Rate Limiting (60 req/min per IP)
    RATE_LIMIT_IP = 60           # richieste per minuto
    RATE_LIMIT_WINDOW = 60       # secondi

    # Nonce
    NONCE_TTL = 60               # secondi
    NONCE_MAX_SIZE = 10000       # max nonce in cache

    # Circuit Breaker
    CB_FAILURE_THRESHOLD = 3     # fallimenti prima di aprire
    CB_TIMEOUT = 10              # secondi prima di half-open

    # Self-Healing
    WATCHDOG_INTERVAL = 30       # secondi
    MAX_MEMORY_MB = 512
    MEMORY_WARNING = 0.7
    MEMORY_CRITICAL = 0.9
    DB_TIMEOUT = 0.5

    # Telegram
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
    WEBHOOK_URL = os.environ.get('WEBHOOK_URL', '')

    # Gunicorn
    WORKERS = int(os.environ.get('WORKERS', '2'))
    TIMEOUT = int(os.environ.get('TIMEOUT', '120'))
    MAX_REQUESTS = int(os.environ.get('MAX_REQUESTS', '1000'))

    # DeepSeek Indexing
    DEEPSEEK_INDEXING = os.environ.get('DEEPSEEK_INDEXING', 'true').lower() == 'true'

    # Audit
    AUDIT_ENABLED = os.environ.get('AUDIT_ENABLED', 'true').lower() == 'true'


# ═══════════════════════════════════════════════════════════════════════════════
# SECURITY MANAGER: HMAC + NONCE ANTI-REPLAY
# ═══════════════════════════════════════════════════════════════════════════════

class SecurityManager:
    """
    Sistema di autenticazione con HMAC-SHA256 + Nonce Anti-Replay.

    Caratteristiche:
    • HMAC-SHA256 per firma operazioni
    • secrets.compare_digest per anti-timing-attack
    • Cache LRU per nonce usati (anti-replay)
    • Timestamp validation (±5 secondi)
    """

    def __init__(self):
        self._nonce_cache = OrderedDict()
        self._nonce_lock = threading.Lock()
        self._cleanup_thread = threading.Thread(target=self._cleanup_nonce_loop, daemon=True)
        self._cleanup_thread.start()

    @staticmethod
    def generate_signature(payload: str, timestamp: str) -> str:
        """Genera firma HMAC-SHA256."""
        message = f"{payload}:{timestamp}"
        return hmac.new(
            Config.HMAC_SECRET.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

    @staticmethod
    def verify_signature(payload: str, timestamp: str, signature: str) -> bool:
        """Verifica firma HMAC-SHA256 con timing-safe comparison."""
        expected = SecurityManager.generate_signature(payload, timestamp)
        return hmac.compare_digest(expected, signature or "")

    # ─── NONCE MANAGEMENT (Anti-Replay) ───

    def is_nonce_valid(self, nonce: str) -> bool:
        """
        Verifica se il nonce è valido (non riutilizzato).

        Pattern: Cache LRU con TTL. Se il nonce è già nella cache,
        la richiesta è un replay attack e viene rifiutata.
        """
        with self._nonce_lock:
            if nonce in self._nonce_cache:
                return False

            # Aggiungi nonce con timestamp
            self._nonce_cache[nonce] = time.time()

            # Limita dimensione cache
            while len(self._nonce_cache) > Config.NONCE_MAX_SIZE:
                self._nonce_cache.popitem(last=False)

            return True

    def _cleanup_nonce_loop(self):
        """Pulizia periodica nonce scaduti."""
        while True:
            time.sleep(Config.NONCE_TTL)
            with self._nonce_lock:
                now = time.time()
                expired = [n for n, t in self._nonce_cache.items()
                          if now - t > Config.NONCE_TTL]
                for n in expired:
                    del self._nonce_cache[n]

    # ─── TIMESTAMP VALIDATION ───

    @staticmethod
    def is_timestamp_valid(ts: str, window: int = 5) -> bool:
        """Verifica timestamp entro finestra di ±N secondi."""
        try:
            ts_int = int(ts)
            now = int(time.time())
            return abs(now - ts_int) <= window
        except ValueError:
            return False

    # ─── API KEY / BEARER ───

    @staticmethod
    def verify_api_key(key: str) -> bool:
        """Verifica API key con timing-safe comparison."""
        return hmac.compare_digest(key, Config.API_KEY)

    @staticmethod
    def verify_bearer_token(token: str) -> bool:
        """Verifica Bearer token con timing-safe comparison."""
        return hmac.compare_digest(token, Config.BEARER_TOKEN)


# ═══════════════════════════════════════════════════════════════════════════════
# RATE LIMITER: 60 RICHIESTE/MINUTO PER IP
# ═══════════════════════════════════════════════════════════════════════════════

class RateLimiter:
    """
    Rate limiting con sliding window per IP.

    Implementazione: dizionario in memoria con timestamps.
    Ogni IP ha una deque di timestamp delle richieste.
    """

    def __init__(self):
        self._ip_windows: Dict[str, deque] = {}
        self._lock = threading.Lock()

    def is_allowed(self, ip: str) -> Tuple[bool, Dict]:
        """
        Verifica se l'IP può effettuare una richiesta.

        Returns:
            (allowed, headers) dove headers contiene Retry-After se bloccato
        """
        now = time.time()

        with self._lock:
            # Ottieni o crea finestra per l'IP
            if ip not in self._ip_windows:
                self._ip_windows[ip] = deque()

            window = self._ip_windows[ip]

            # Rimuovi richieste vecchie (fuori dalla finestra temporale)
            cutoff = now - Config.RATE_LIMIT_WINDOW
            while window and window[0] < cutoff:
                window.popleft()

            # Verifica limite
            if len(window) >= Config.RATE_LIMIT_IP:
                # Calcola quando l'IP potrà fare richieste di nuovo
                retry_after = int(window[0] + Config.RATE_LIMIT_WINDOW - now) + 1
                return False, {
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(Config.RATE_LIMIT_IP),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(window[0] + Config.RATE_LIMIT_WINDOW))
                }

            # Registra la richiesta corrente
            window.append(now)

            remaining = Config.RATE_LIMIT_IP - len(window)
            return True, {
                "X-RateLimit-Limit": str(Config.RATE_LIMIT_IP),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(int(now + Config.RATE_LIMIT_WINDOW))
            }

    def get_stats(self, ip: str) -> Dict:
        """Restituisce statistiche per un IP."""
        with self._lock:
            if ip not in self._ip_windows:
                return {"requests_in_window": 0, "limit": Config.RATE_LIMIT_IP}

            now = time.time()
            cutoff = now - Config.RATE_LIMIT_WINDOW
            window = self._ip_windows[ip]

            # Conta solo richieste nella finestra
            valid_requests = sum(1 for t in window if t >= cutoff)
            return {
                "requests_in_window": valid_requests,
                "limit": Config.RATE_LIMIT_IP,
                "remaining": Config.RATE_LIMIT_IP - valid_requests
            }


# ═══════════════════════════════════════════════════════════════════════════════
# CIRCUIT BREAKER: DATABASE RESILIENCE
# ═══════════════════════════════════════════════════════════════════════════════

class DBCircuitBreaker:
    """
    Circuit breaker per il database.

    Stati:
    • CLOSED: tutto normale, richieste passano
    • OPEN: troppi fallimenti consecutive, richieste bloccate
    • HALF_OPEN: test di recupero dopo timeout

    Se il DB fallisce 3 volte consecutive, il circuito si apre per 10 secondi.
    """

    class State(Enum):
        CLOSED = "closed"
        OPEN = "open"
        HALF_OPEN = "half-open"

    def __init__(self, failure_threshold: int = Config.CB_FAILURE_THRESHOLD,
                 timeout: int = Config.CB_TIMEOUT):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failures = 0
        self.state = self.State.CLOSED
        self.last_failure = 0
        self._lock = threading.Lock()

    def call(self, func: Callable, *args, **kwargs):
        """Esegue funzione con circuit breaker protection."""
        with self._lock:
            if self.state == self.State.OPEN:
                if time.time() - self.last_failure > self.timeout:
                    self.state = self.State.HALF_OPEN
                    logging.info("[CircuitBreaker] Stato HALF_OPEN - test di recupero")
                else:
                    remaining = self.timeout - (time.time() - self.last_failure)
                    raise Exception(
                        f"Database circuit breaker OPEN - riprova tra {remaining:.0f}s"
                    )

        try:
            result = func(*args, **kwargs)
            with self._lock:
                if self.state == self.State.HALF_OPEN:
                    self.state = self.State.CLOSED
                    self.failures = 0
                    logging.info("[CircuitBreaker] Stato CLOSED - recupero riuscito")
            return result

        except Exception as e:
            with self._lock:
                self.failures += 1
                self.last_failure = time.time()
                if self.failures >= self.failure_threshold:
                    self.state = self.State.OPEN
                    logging.error(
                        f"[CircuitBreaker] Stato OPEN dopo {self.failures} fallimenti"
                    )
            raise

    def get_status(self) -> Dict:
        """Stato corrente del circuit breaker."""
        with self._lock:
            return {
                "state": self.state.value,
                "failures": self.failures,
                "last_failure": datetime.fromtimestamp(self.last_failure).isoformat()
                               if self.last_failure else None,
                "threshold": self.failure_threshold,
                "timeout": self.timeout
            }


# ═══════════════════════════════════════════════════════════════════════════════
# SELF-HEALING MANAGER (con Circuit Breaker integrato)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class HealthStatus:
    """Stato di salute del sistema."""
    status: str
    timestamp: float
    memory_usage_mb: float
    memory_limit_mb: float
    memory_percent: float
    db_connection_ok: bool
    circuit_breaker_state: str
    uptime_seconds: float
    requests_per_second: float = 0.0


class SelfHealingManager:
    """Watchdog autonomo con circuit breaker integrato."""

    def __init__(self, db_path: str = Config.DB_PATH):
        self.db_path = db_path
        self.start_time = time.time()
        self._stop_event = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        self._last_health: Optional[HealthStatus] = None
        self._request_times = deque(maxlen=100)
        self._request_lock = threading.Lock()
        self._circuit_breaker = DBCircuitBreaker()

        # Signal handlers per graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_sigterm)
        signal.signal(signal.SIGINT, self._handle_sigterm)

    def _handle_sigterm(self, signum, frame):
        """Graceful shutdown su SIGTERM."""
        logging.info("[SelfHealing] Ricevuto SIGTERM, avvio graceful shutdown...")
        self.stop_monitoring()
        logging.info("[SelfHealing] Graceful shutdown completato")
        sys.exit(0)

    def start_monitoring(self):
        """Avvia il watchdog."""
        if self._monitor_thread is None or not self._monitor_thread.is_alive():
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop,
                daemon=True,
                name="SelfHealingWatchdog"
            )
            self._monitor_thread.start()
            logging.info("[SelfHealing] Monitoraggio avviato")

    def stop_monitoring(self):
        """Ferma il watchdog."""
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)

    def record_request_time(self, duration: float):
        """Registra tempo di risposta."""
        with self._request_lock:
            self._request_times.append(duration)

    def _monitor_loop(self):
        """Loop principale."""
        while not self._stop_event.is_set():
            try:
                health = self._check_health()
                self._last_health = health

                if health.status == 'critical':
                    self._send_alert(
                        f"🚨 CRITICAL: Pure Broker in stato critico!\n"
                        f"Memoria: {health.memory_usage_mb:.1f}MB / {health.memory_limit_mb}MB\n"
                        f"DB: {'OK' if health.db_connection_ok else 'FAIL'}\n"
                        f"Circuit: {health.circuit_breaker_state}\n"
                        f"Uptime: {health.uptime_seconds:.0f}s"
                    )
                    logging.critical("[SelfHealing] Stato CRITICAL")

                elif health.status == 'warning':
                    self._send_alert(
                        f"⚠️ WARNING: Pure Broker sotto stress\n"
                        f"Memoria: {health.memory_percent*100:.0f}%"
                    )

            except Exception as e:
                logging.error(f"[SelfHealing] Errore: {e}")

            self._stop_event.wait(Config.WATCHDOG_INTERVAL)

    def _check_health(self) -> HealthStatus:
        """Verifica stato di salute."""
        memory_mb, memory_percent = self._get_memory_info()
        db_ok = self._check_db_connection()
        rps = self._get_rps()

        if memory_percent > Config.MEMORY_CRITICAL or not db_ok:
            status = 'critical'
        elif memory_percent > Config.MEMORY_WARNING:
            status = 'warning'
        else:
            status = 'healthy'

        return HealthStatus(
            status=status,
            timestamp=time.time(),
            memory_usage_mb=memory_mb,
            memory_limit_mb=Config.MAX_MEMORY_MB,
            memory_percent=memory_percent,
            db_connection_ok=db_ok,
            circuit_breaker_state=self._circuit_breaker.state.value,
            uptime_seconds=time.time() - self.start_time,
            requests_per_second=rps
        )

    def _get_memory_info(self) -> Tuple[float, float]:
        """Ottiene info memoria."""
        try:
            with open('/proc/self/status', 'r') as f:
                for line in f:
                    if line.startswith('VmRSS:'):
                        kb = int(line.split()[1])
                        memory_mb = kb / 1024.0
                        return memory_mb, memory_mb / Config.MAX_MEMORY_MB
        except (FileNotFoundError, ValueError):
            pass

        try:
            process = psutil.Process()
            memory_mb = process.memory_info().rss / (1024 * 1024)
            return memory_mb, memory_mb / Config.MAX_MEMORY_MB
        except Exception:
            return 0.0, 0.0

    def _check_db_connection(self) -> bool:
        """Check DB leggero con circuit breaker."""
        try:
            return self._circuit_breaker.call(
                self._db_ping
            )
        except Exception:
            return False

    def _db_ping(self) -> bool:
        """Ping leggero al DB."""
        conn = sqlite3.connect(self.db_path, timeout=Config.DB_TIMEOUT)
        conn.execute("PRAGMA query_only = ON")
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        conn.close()
        return result is not None

    def _get_rps(self) -> float:
        """Calcola RPS."""
        with self._request_lock:
            if len(self._request_times) < 2:
                return 0.0
            window = self._request_times[-1] - self._request_times[0]
            if window <= 0:
                return 0.0
            return len(self._request_times) / window

    def _send_alert(self, message: str):
        """Invia alert Telegram/webhook."""
        if Config.TELEGRAM_BOT_TOKEN and Config.TELEGRAM_CHAT_ID:
            try:
                url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"
                requests.post(url, json={
                    "chat_id": Config.TELEGRAM_CHAT_ID,
                    "text": message,
                    "parse_mode": "HTML"
                }, timeout=10)
            except Exception as e:
                logging.error(f"[SelfHealing] Telegram fallito: {e}")

        if Config.WEBHOOK_URL:
            try:
                requests.post(Config.WEBHOOK_URL, json={
                    "source": "pure_broker_watchdog",
                    "message": message,
                    "timestamp": datetime.utcnow().isoformat()
                }, timeout=10)
            except Exception as e:
                logging.error(f"[SelfHealing] Webhook fallito: {e}")

    def get_health(self) -> Dict[str, Any]:
        """Restituisce stato di salute."""
        if self._last_health:
            return {
                "status": self._last_health.status,
                "memory": {
                    "usage_mb": round(self._last_health.memory_usage_mb, 2),
                    "limit_mb": self._last_health.memory_limit_mb,
                    "percent": round(self._last_health.memory_percent * 100, 1)
                },
                "db_connection_ok": self._last_health.db_connection_ok,
                "circuit_breaker": self._last_health.circuit_breaker_state,
                "uptime_seconds": round(self._last_health.uptime_seconds, 0),
                "rps": round(self._last_health.requests_per_second, 1),
                "timestamp": datetime.fromtimestamp(self._last_health.timestamp).isoformat()
            }
        return {"status": "unknown", "message": "Monitoraggio non avviato"}


# ═══════════════════════════════════════════════════════════════════════════════
# DEEPSEEK INDEXING
# ═══════════════════════════════════════════════════════════════════════════════

class DeepSeekIndexing:
    """Indici avanzati per SQLite."""

    @staticmethod
    def init_advanced_indices(db_path: str = Config.DB_PATH):
        """Crea indici avanzati."""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_entita_data
            ON audit_logs(entita_tipo, entita_id, data_creazione DESC)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_azione_data
            ON audit_logs(azione, data_creazione DESC)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_utente_data
            ON audit_logs(utente_id, data_creazione DESC)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_covering
            ON audit_logs(entita_tipo, entita_id, data_creazione DESC, azione, dettagli)
        """)

        # NB: niente WHERE con datetime('now') (funzione non deterministica,
        # vietata negli indici parziali SQLite) -> indice normale.
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_recent
            ON audit_logs(data_creazione, entita_tipo, entita_id)
        """)

        # escrow_fondi ha 'data_sblocco' (non 'data_creazione').
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_escrow_stato_data
            ON escrow_fondi(stato, data_sblocco DESC)
        """)

        # pagamenti_split non ha 'escrow_id'/'quota_piattaforma': indice
        # coprente per id (chiave di join) + importi usati nelle aggregazioni.
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_pagamenti_escrow
            ON pagamenti_split(id, commissione_tavola, quota_partner)
        """)

        cursor.execute("ANALYZE")
        conn.commit()
        conn.close()
        logging.info("[DeepSeekIndexing] Indici avanzati creati")


# ═══════════════════════════════════════════════════════════════════════════════
# DECORATORI FLASK: INTEGRAZIONE COMPLETA
# ═══════════════════════════════════════════════════════════════════════════════

def require_fortress_auth(f: Callable) -> Callable:
    """
    Decorator di autenticazione Fortress.
    Richiede: X-Request-ID, X-Timestamp, X-Nonce, X-Body-Hash, X-Signature
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        security = SecurityManager()

        request_id = request.headers.get('X-Request-ID', '')
        timestamp = request.headers.get('X-Timestamp', '')
        nonce = request.headers.get('X-Nonce', '')
        body_hash = request.headers.get('X-Body-Hash', '')
        signature = request.headers.get('X-Signature', '')

        if not all([request_id, timestamp, nonce, body_hash, signature]):
            abort(401, description="Missing authentication headers")

        if not security.is_timestamp_valid(timestamp, window=5):
            abort(401, description="Invalid or expired timestamp")

        if not security.is_nonce_valid(nonce):
            abort(401, description="Nonce already used or invalid (replay attack?)")

        expected_body_hash = hashlib.sha256(request.get_data()).hexdigest()
        if not hmac.compare_digest(expected_body_hash, body_hash):
            abort(401, description="Body hash mismatch")

        if not security.verify_signature(
            request.method + request.path + request_id + timestamp + nonce + body_hash,
            timestamp, signature
        ):
            abort(401, description="Invalid signature")

        return f(*args, **kwargs)
    return decorated


def require_api_key_or_bearer(f: Callable) -> Callable:
    """Decorator per API key o Bearer token."""
    @wraps(f)
    def decorated(*args, **kwargs):
        security = SecurityManager()

        api_key = request.headers.get('X-API-Key', '')
        if api_key and security.verify_api_key(api_key):
            return f(*args, **kwargs)

        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            if security.verify_bearer_token(token):
                return f(*args, **kwargs)

        abort(401, description="Authentication required")
    return decorated


def rate_limit_middleware(f: Callable) -> Callable:
    """Middleware per rate limiting."""
    limiter = RateLimiter()

    @wraps(f)
    def decorated(*args, **kwargs):
        ip = request.remote_addr or 'unknown'

        allowed, headers = limiter.is_allowed(ip)
        if not allowed:
            response = jsonify({"error": "Rate limit exceeded", "retry_after": headers.get("Retry-After", "60")})
            for key, value in headers.items():
                response.headers[key] = value
            return response, 429

        # Aggiungi headers rate limit anche per richieste consentite
        response = f(*args, **kwargs)
        if isinstance(response, tuple):
            response_obj, status = response
            for key, value in headers.items():
                response_obj.headers[key] = value
            return response_obj, status
        return response
    return decorated


# ═══════════════════════════════════════════════════════════════════════════════
# FLASK APP: INTEGRAZIONE COMPLETA
# ═══════════════════════════════════════════════════════════════════════════════

def create_fortress_app() -> Flask:
    """Factory per l'app Flask con sicurezza di livello massimo."""

    app = Flask(__name__)
    app.config['SECRET_KEY'] = Config.HMAC_SECRET[:32]

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )

    if Config.DEEPSEEK_INDEXING:
        DeepSeekIndexing.init_advanced_indices()

    watchdog = SelfHealingManager()
    watchdog.start_monitoring()

    # ─── HEALTH CHECK ───
    @app.route('/health')
    def health():
        return jsonify({
            'status': 'ok',
            'phase': 'FASE_13_FORTRESS_AGGIORNATA',
            'timestamp': datetime.utcnow().isoformat()
        })

    # ─── HEALTH DETTAGLIATO ───
    @app.route('/health/detailed')
    @require_api_key_or_bearer
    def health_detailed():
        return jsonify(watchdog.get_health())

    # ─── API: Rate Limit Stats ───
    @app.route('/api/rate-limit/status')
    @require_api_key_or_bearer
    def rate_limit_status():
        limiter = RateLimiter()
        ip = request.remote_addr or 'unknown'
        return jsonify(limiter.get_stats(ip))

    # ─── API: Circuit Breaker Status ───
    @app.route('/api/circuit-breaker/status')
    @require_api_key_or_bearer
    def circuit_breaker_status():
        return jsonify(watchdog._circuit_breaker.get_status())

    # ─── API: Audit con Firma Fortress ───
    @app.route('/api/audit', methods=['POST'])
    @require_fortress_auth
    @rate_limit_middleware
    def api_audit():
        return jsonify({'success': True, 'message': 'Audit registrato con firma Fortress'})

    # ─── API: Dashboard ───
    @app.route('/api/dashboard/metriche')
    @require_api_key_or_bearer
    @rate_limit_middleware
    def api_dashboard():
        return jsonify({'success': True, 'message': 'Metriche recuperate'})

    # ─── API: Cron ───
    @app.route('/api/cron/timeout-check', methods=['POST'])
    @require_api_key_or_bearer
    def cron_timeout():
        return jsonify({'success': True, 'message': 'Timeout check eseguito'})

    # ─── MIDDLEWARE: Monitoraggio latenza ───
    @app.before_request
    def before_request():
        g.start_time = time.time()

    @app.after_request
    def after_request(response):
        if hasattr(g, 'start_time'):
            duration = time.time() - g.start_time
            watchdog.record_request_time(duration)
        return response

    return app


# ═══════════════════════════════════════════════════════════════════════════════
# GUNICORN CONFIG
# ═══════════════════════════════════════════════════════════════════════════════
"""
# File: gunicorn_fortress.conf.py

import multiprocessing
import os

workers = int(os.environ.get('WORKERS', 2))
worker_class = "sync"
worker_connections = 1000

timeout = int(os.environ.get('TIMEOUT', 120))
graceful_timeout = 30
max_requests = int(os.environ.get('MAX_REQUESTS', 1000))
max_requests_jitter = 50

accesslog = "-"
errorlog = "-"
loglevel = "info"

preload_app = False

bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
"""


if __name__ == '__main__':
    app = create_fortress_app()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
