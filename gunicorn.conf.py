"""
CORE_AUTO - Fase 14: Gunicorn Configuration.

Configurazione di produzione + hook di lifecycle integrati col SelfHealingManager
(monitoraggio master, ciclo di vita dei worker, alerting). Ogni hook e' blindato
in try/except: un errore di monitoraggio non deve MAI far cadere Gunicorn.

NOTA DI ADATTAMENTO: il prompt citava moduli `fase10_watchdog`/`fase11_alerting`
non presenti. Si importa il SelfHealingManager reale da `fase13_protocollo_finale`
(che incorpora anche l'alerting Telegram/webhook in `_send_alert`).
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import time
from typing import Any, Optional

import psutil

logger = logging.getLogger("core_auto.gunicorn")

# M1: riferimento globale al SelfHealingManager. worker_abort gira nel processo
# worker (non ha l'oggetto `server`), quindi non puo' raggiungere il monitor via
# `server.self_healing`; con preload_app il global ereditato dal master e' invece
# accessibile. Usato per inviare alert di timeout dal worker in abort.
_MONITOR: Optional[Any] = None

# ═══════════════════════════════════════════════════════════════════════════
# Configurazione base
# ═══════════════════════════════════════════════════════════════════════════
bind: str = os.environ.get("BIND", os.environ.get("PORT") and
                           f"0.0.0.0:{os.environ['PORT']}" or "0.0.0.0:8000")
workers: int = int(os.environ.get("WEB_CONCURRENCY",
                                  str(multiprocessing.cpu_count() * 2 + 1)))
worker_class: str = os.environ.get("WORKER_CLASS", "sync")
# Per I/O-bound si puo' usare i thread:
# worker_class = "gthread"; threads = int(os.environ.get("THREADS", "4"))

timeout: int = int(os.environ.get("TIMEOUT", "30"))
graceful_timeout: int = int(os.environ.get("GRACEFUL_TIMEOUT", "60"))  # K5: worker drain
keepalive: int = int(os.environ.get("KEEPALIVE", "5"))

max_requests: int = int(os.environ.get("MAX_REQUESTS", "1000"))
max_requests_jitter: int = int(os.environ.get("MAX_REQUESTS_JITTER", "100"))

# preload_app=True: il codice (e i singleton, es. SecurityManager) viene
# caricato una sola volta nel master e condiviso via fork dai worker.
preload_app: bool = True

accesslog: str = "-"   # stdout
errorlog: str = "-"    # stderr
loglevel: str = os.environ.get("LOGLEVEL", "info")
capture_output: bool = True

# Limiti di sicurezza sulle richieste (mitigano abusi / header flooding).
limit_request_line: int = 4094
limit_request_fields: int = 100
limit_request_field_size: int = 8190

forwarded_allow_ips: str = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")
secure_scheme_headers: dict = {
    "X-FORWARDED-PROTOCOL": "ssl",
    "X-FORWARDED-PROTO": "https",
    "X-FORWARDED-SSL": "on",
}

# Utente/gruppo: solo in produzione (decommentare e impostare via env).
# user = os.environ.get("GUNICORN_USER")
# group = os.environ.get("GUNICORN_GROUP")

# SSL/TLS: in produzione dietro reverse proxy di solito si termina TLS la';
# se serve TLS diretto, impostare via env (TLS 1.2+):
# import ssl
# certfile = os.environ.get("SSL_CERTFILE")
# keyfile = os.environ.get("SSL_KEYFILE")
# ssl_version = ssl.PROTOCOL_TLS_SERVER

# Formato access log con ip, metodo, path, status, durata, user-agent.
access_log_format: str = '%(h)s %(m)s %(U)s %(s)s %(L)ss "%(a)s"'

# Soglie self-healing del master.
_MASTER_MEMORY_WARNING_MB: int = int(os.environ.get("MASTER_MEM_WARNING_MB", "400"))
_WORKER_FAILURE_THRESHOLD: int = int(os.environ.get("WORKER_FAILURE_THRESHOLD", "5"))


# ═══════════════════════════════════════════════════════════════════════════
# Helper interni
# ═══════════════════════════════════════════════════════════════════════════
def _get_self_healing(server: Any) -> Optional[Any]:
    """Restituisce il SelfHealingManager agganciato al server, se presente.

    Args:
        server: istanza del server Gunicorn.

    Returns:
        Il SelfHealingManager oppure None.
    """
    return getattr(server, "self_healing", None)


def _alert(server: Any, message: str) -> None:
    """Invia un alert tramite il SelfHealingManager (Telegram/webhook), se c'e'.

    Args:
        server: istanza del server Gunicorn.
        message: testo dell'alert.
    """
    monitor = _get_self_healing(server)
    if monitor is not None:
        try:
            monitor._send_alert(message)
        except Exception:  # pragma: no cover - difensivo
            logger.error("Invio alert fallito", exc_info=True)


def _idempotency_maintenance(fase: str) -> None:
    """Sweep dei lock idempotenza morti + purge delle cache scadute (best-effort).

    Complementa la manutenzione periodica del SelfHealingManager: al boot
    recupera lo stato orfano lasciato da un processo precedente crashato, allo
    shutdown fa pulizia finale. Import lazy + try/except: non deve mai far
    fallire un hook di Gunicorn.

    Args:
        fase: etichetta dell'hook chiamante (per il log).
    """
    try:
        from fase13_protocollo_finale import Config
        from fase15_idempotency import IdempotencyManager
        mgr = IdempotencyManager(Config.DB_PATH)
        liberati = mgr.sweep()
        rimossi = mgr.purge_expired()
        logger.info("[Gunicorn] %s: idempotency maintenance (%s lock liberati, "
                    "%s chiavi scadute rimosse)", fase, liberati, rimossi)
    except Exception:  # pragma: no cover - difensivo
        logger.error("[Gunicorn] %s: idempotency maintenance fallita", fase,
                     exc_info=True)


# ═══════════════════════════════════════════════════════════════════════════
# Hook di lifecycle
# ═══════════════════════════════════════════════════════════════════════════
def on_starting(server: Any) -> None:
    """Chiamato prima dell'inizializzazione del master (nessun worker ancora).

    Args:
        server: istanza del server Gunicorn.
    """
    try:
        server._worker_failures = 0
        # Recupero stato idempotenza orfano da un eventuale run precedente.
        _idempotency_maintenance("on_starting")
        logger.info("[Gunicorn] on_starting: master in inizializzazione")
    except Exception:  # pragma: no cover - difensivo
        logger.error("on_starting fallito", exc_info=True)


def when_ready(server: Any) -> None:
    """Chiamato quando il server e' pronto: avvia il SelfHealingManager master.

    Args:
        server: istanza del server Gunicorn.
    """
    try:
        global _MONITOR
        from fase13_protocollo_finale import Config, SelfHealingManager
        monitor = SelfHealingManager(db_path=Config.DB_PATH)
        monitor.start_monitoring()
        server.self_healing = monitor
        _MONITOR = monitor  # M1: visibile ai worker (preload_app)
        logger.info("[Gunicorn] when_ready: SelfHealingManager avviato (master)")
    except Exception:  # pragma: no cover - difensivo
        logger.error("when_ready fallito (monitor non avviato)", exc_info=True)


def pre_fork(server: Any, worker: Any) -> None:
    """Prima di forkare un worker: avvisa se il circuit breaker e' OPEN.

    Args:
        server: istanza del server Gunicorn.
        worker: worker in via di creazione.
    """
    try:
        monitor = _get_self_healing(server)
        if monitor is not None and getattr(monitor, "_circuit_breaker", None):
            stato = monitor._circuit_breaker.state.value
            if stato == "open":
                logger.warning("[Gunicorn] pre_fork: circuit breaker OPEN "
                               "(fork comunque consentito)")
    except Exception:  # pragma: no cover - difensivo
        logger.error("pre_fork fallito", exc_info=True)


def post_fork(server: Any, worker: Any) -> None:
    """Dopo il fork del worker: log di registrazione.

    Args:
        server: istanza del server Gunicorn.
        worker: worker appena creato.

    Note:
        Con SQLite in WAL la connessione e' aperta on-demand dai manager
        (connessione-per-operazione), quindi non serve inizializzarla qui.
    """
    try:
        logger.info("[Gunicorn] post_fork: worker pid=%s avviato", worker.pid)
    except Exception:  # pragma: no cover - difensivo
        logger.error("post_fork fallito", exc_info=True)


def worker_int(worker: Any) -> None:
    """Worker riceve SIGINT/SIGQUIT: cleanup leggero.

    Args:
        worker: worker che si sta fermando.
    """
    try:
        logger.info("[Gunicorn] worker_int: cleanup worker pid=%s", worker.pid)
    except Exception:  # pragma: no cover - difensivo
        logger.error("worker_int fallito", exc_info=True)


def worker_abort(worker: Any) -> None:
    """Worker riceve SIGABRT (timeout): log CRITICAL + alert (niente cleanup).

    Args:
        worker: worker in abort.
    """
    try:
        logger.critical("[Gunicorn] worker_abort: timeout worker pid=%s", worker.pid)
        # M1: il worker sta morendo: nessun cleanup, solo notifica best-effort
        # tramite il monitor globale (ereditato dal master via preload_app).
        # NB: SelfHealingManager espone `_send_alert` (non esiste `alert`).
        if _MONITOR is not None:
            _MONITOR._send_alert(f"🚨 Worker timeout: {worker.pid}")
    except Exception:  # pragma: no cover - difensivo
        logger.error("worker_abort fallito", exc_info=True)


def child_exit(server: Any, worker: Any) -> None:
    """Worker uscito (lato master): aggiorna metriche e conta i fallimenti.

    Args:
        server: istanza del server Gunicorn.
        worker: worker terminato.
    """
    try:
        exitcode = getattr(worker, "exitcode", 0) or 0
        if exitcode != 0:
            server._worker_failures = getattr(server, "_worker_failures", 0) + 1
            logger.warning("[Gunicorn] child_exit: worker pid=%s exit=%s (failures=%s)",
                           worker.pid, exitcode, server._worker_failures)
            if server._worker_failures >= _WORKER_FAILURE_THRESHOLD:
                logger.critical("[Gunicorn] soglia fallimenti worker superata (%s)",
                                server._worker_failures)
                _alert(server, f"🚨 {server._worker_failures} worker falliti: "
                               "possibile instabilita' del servizio.")
    except Exception:  # pragma: no cover - difensivo
        logger.error("child_exit fallito", exc_info=True)


def on_exit(server: Any) -> None:
    """Prima dell'uscita del master: ferma il monitor e notifica lo shutdown.

    Args:
        server: istanza del server Gunicorn.
    """
    try:
        monitor = _get_self_healing(server)
        if monitor is not None:
            monitor.stop_monitoring()
        _idempotency_maintenance("on_exit")  # housekeeping finale
        _alert(server, "ℹ️ CORE_AUTO: shutdown completato")
        logger.info("[Gunicorn] on_exit: shutdown completato")
    except Exception:  # pragma: no cover - difensivo
        logger.error("on_exit fallito", exc_info=True)
