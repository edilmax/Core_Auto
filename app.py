"""
CORE_AUTO - Fase 14: Flask Application.

Integrazione finale di Sicurezza (HMAC/Nonce/Rate-limit), Circuit Breaker,
Self-Healing, Audit e Logging sopra i moduli reali del progetto.

NOTA DI ADATTAMENTO: il prompt della Fase 14 elencava moduli `fase01..fase12`
non presenti nel repository. L'architettura reale e' in due moduli, da cui qui
si IMPORTA (senza modificarli):
  - fase13_protocollo_finale.py : Config, SecurityManager, DBCircuitBreaker,
                                  SelfHealingManager, RateLimiter, get_*().
  - assistente_gestionale.py    : DatabaseCandidati (schema/WAL/audit_logs/
                                  escrow_fondi/pagamenti_split), EscrowManager,
                                  PagamentoSplitManager, AuditManager,
                                  DashboardManager, AzioneAudit.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import sqlite3
import time
from functools import wraps
from typing import Any, Callable, Dict, Optional, Tuple

from flask import Blueprint, Flask, current_app, g, jsonify, request
from flask.wrappers import Response

from fase13_protocollo_finale import (
    Config,
    DBCircuitBreaker,
    SelfHealingManager,
    _canonical_string,
    get_rate_limiter,
    get_security_manager,
)
from assistente_gestionale import (
    AuditManager,
    AzioneAudit,
    DashboardManager,
    DatabaseCandidati,
    EscrowManager,
    PagamentoSplitManager,
)

# Logger centralizzato. TODO: il modulo fase08_logging citato dal prompt non
# esiste nel repo -> si usa il logging standard (rotazione delegata a Gunicorn).
logger = logging.getLogger("core_auto")

# C2: X-Forwarded-For e' attendibile SOLO se la connessione proviene da un proxy
# fidato (altrimenti e' spoofabile -> bypass del rate-limit per-IP).
_TRUSTED_PROXIES = set(
    p.strip() for p in os.environ.get("TRUSTED_PROXIES", "127.0.0.1,::1").split(",")
    if p.strip())
# Quale hop della catena XFF usare: "first" (client originale) o "last" (proxy).
XFF_MODE = os.environ.get("XFF_MODE", "first")

# Metodi HTTP considerati "sicuri" (sola lettura): ammessi anche in HALF_OPEN.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

api = Blueprint("api", __name__, url_prefix="/api/v1")


# ═══════════════════════════════════════════════════════════════════════════
# Accesso ai servizi e helper di risposta/DB
# ═══════════════════════════════════════════════════════════════════════════
def _services() -> Dict[str, Any]:
    """Restituisce il contenitore dei servizi registrato sull'app.

    Returns:
        Il dizionario `current_app.extensions['core_auto']` con db e manager.
    """
    return current_app.extensions["core_auto"]


def _sanitize_ip(value: str) -> Optional[str]:
    """Valida e normalizza un IP (v4/v6).

    Args:
        value: stringa IP candidata.

    Returns:
        L'IP in forma canonica, oppure None se non valido.
    """
    try:
        return str(ipaddress.ip_address(value.strip()))
    except (ValueError, AttributeError):
        return None


def _client_ip() -> str:
    """Ricava l'IP reale del client in modo resistente allo spoofing.

    `X-Forwarded-For` viene considerato SOLO se la connessione arriva da un
    proxy fidato (`_TRUSTED_PROXIES`); in produzione gli IP privati/loopback
    presenti in XFF vengono scartati (possibile spoof interno). In ogni caso
    di dubbio si torna all'indirizzo del peer (`remote_addr`).

    Returns:
        L'IP del client da usare come chiave (rate-limit, log, audit).
    """
    peer = request.remote_addr or "unknown"
    if peer not in _TRUSTED_PROXIES:
        return peer  # connessione diretta: XFF non e' attendibile
    xff = request.headers.get("X-Forwarded-For", "")
    if not xff:
        return peer
    catena = [c.strip() for c in xff.split(",") if c.strip()]
    if not catena:
        return peer
    candidato = catena[0] if XFF_MODE == "first" else catena[-1]
    ip = _sanitize_ip(candidato)
    if ip is None:
        return peer
    if os.environ.get("FLASK_ENV") == "production":
        try:
            if ipaddress.ip_address(ip).is_private or ipaddress.ip_address(ip).is_loopback:
                return peer  # XFF privato in prod -> sospetto, usa il peer
        except ValueError:
            return peer
    return ip


def _error(status: int, code: str,
           headers: Optional[Dict[str, str]] = None) -> Tuple[Response, int]:
    """Costruisce una risposta JSON di errore generica (nessun dettaglio interno).

    Args:
        status: codice HTTP.
        code: identificatore di errore lato client (stringa stabile).
        headers: header opzionali (es. Retry-After).

    Returns:
        Tupla (Response JSON, status).
    """
    resp = jsonify({"error": code})
    if headers:
        for key, value in headers.items():
            resp.headers[key] = value
    return resp, status


def _query(sql: str, params: Tuple = ()) -> list:
    """Esegue una SELECT e restituisce righe come liste di dict.

    Args:
        sql: query SELECT.
        params: parametri posizionali.

    Returns:
        Lista di dizionari (una per riga).
    """
    conn = _services()["db"].connessione()
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _execute(sql: str, params: Tuple = ()) -> int:
    """Esegue una scrittura (commit) e restituisce il numero di righe toccate.

    Args:
        sql: query di scrittura.
        params: parametri posizionali.

    Returns:
        `cursor.rowcount`.
    """
    conn = _services()["db"].connessione()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# Decoratori di sicurezza e resilienza
# ═══════════════════════════════════════════════════════════════════════════
def _verifica_fortress() -> Tuple[bool, int]:
    """Verifica l'autenticazione "fortress" (HMAC + nonce + timestamp + body).

    Returns:
        (True, 200) se valida; (False, 401) se autenticazione assente/scaduta;
        (False, 403) se la firma o il body-hash non sono validi.
    """
    import hashlib
    import hmac as _hmac

    sm = get_security_manager()
    request_id = request.headers.get("X-Request-ID", "")
    timestamp = request.headers.get("X-Timestamp", "")
    nonce = request.headers.get("X-Nonce", "")
    body_hash = request.headers.get("X-Body-Hash", "")
    signature = request.headers.get("X-Signature", "")

    if not all([request_id, timestamp, nonce, body_hash, signature]):
        return False, 401
    if not sm.is_timestamp_valid(timestamp, window=300):  # ±5 minuti
        return False, 401
    if not sm.is_nonce_valid(nonce):
        return False, 401
    expected_body = hashlib.sha256(request.get_data()).hexdigest()
    if not _hmac.compare_digest(expected_body, body_hash):
        return False, 403
    # H2: canonicalizzazione con length-prefix (anti-collisione) e full_path
    # (firma anche la query string, non solo il path).
    payload = _canonical_string([
        request.method, request.full_path, request_id,
        timestamp, nonce, body_hash,
    ]).decode("utf-8")
    if not sm.verify_signature(payload, timestamp, signature):
        return False, 403
    return True, 200


def fortress(func: Callable) -> Callable:
    """Decoratore per route che MODIFICANO stato: rate-limit + HMAC fortress.

    In caso di fallimento logga a livello WARNING e restituisce 401/403/429
    senza esporre dettagli interni. Un'eccezione interna -> CRITICAL + 500.
    """
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        ip = _client_ip()
        allowed, headers = get_rate_limiter().is_allowed(ip)
        if not allowed:
            logger.warning("Rate limit superato (fortress) ip=%s path=%s",
                           ip, request.path)
            return _error(429, "rate_limited", headers)
        try:
            ok, code = _verifica_fortress()
        except Exception:  # pragma: no cover - difensivo
            logger.critical("Errore interno autenticazione fortress path=%s",
                            request.path, exc_info=True)
            return _error(500, "internal_error")
        if not ok:
            logger.warning("Auth fortress fallita (%s) ip=%s path=%s",
                           code, ip, request.path)
            return _error(code, "unauthorized" if code == 401 else "forbidden")
        return func(*args, **kwargs)
    return wrapper


def fortress_readonly(func: Callable) -> Callable:
    """Decoratore per route GET: rate-limit + dual auth (API key / Bearer).

    Piu' permissivo della `fortress`: non richiede firma HMAC del body.
    """
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        ip = _client_ip()
        allowed, headers = get_rate_limiter().is_allowed(ip)
        if not allowed:
            logger.warning("Rate limit superato (readonly) ip=%s path=%s",
                           ip, request.path)
            return _error(429, "rate_limited", headers)
        try:
            sm = get_security_manager()
            api_key = request.headers.get("X-API-Key", "")
            auth = request.headers.get("Authorization", "")
            token = auth[7:] if auth.startswith("Bearer ") else ""
            autorizzato = sm.verify_api_key(api_key) or sm.verify_bearer_token(token)
        except Exception:  # pragma: no cover - difensivo
            logger.critical("Errore interno auth readonly path=%s",
                            request.path, exc_info=True)
            return _error(500, "internal_error")
        if not autorizzato:
            logger.warning("Auth readonly fallita ip=%s path=%s", ip, request.path)
            return _error(401, "unauthorized")
        return func(*args, **kwargs)
    return wrapper


# H1: classificazione degli errori DB per il circuit breaker.
# - INFRA (transitori/infrastrutturali) -> aprono il breaker, 503.
# - CLIENT (input/programmazione) -> NON aprono il breaker, 400.
# - altro -> 500. NB: IntegrityError/ProgrammingError sottoclassi di
#   DatabaseError: vanno intercettate PRIMA di DB_INFRA_ERRORS.
DB_INFRA_ERRORS = (sqlite3.OperationalError, sqlite3.DatabaseError)
DB_CLIENT_ERRORS = (sqlite3.IntegrityError, sqlite3.ProgrammingError)


def _is_db_infra_error(exc: BaseException) -> bool:
    """True se l'errore DB e' infrastrutturale/transitorio.

    Args:
        exc: eccezione catturata.

    Returns:
        True se il messaggio indica contesa/indisponibilita' (busy/locked/timeout).
    """
    msg = str(exc).lower()
    return any(k in msg for k in ("busy", "locked", "timeout"))


def _cb_record_failure(cb: DBCircuitBreaker) -> None:
    """Conta un fallimento infra sul breaker e lo apre oltre la soglia."""
    with cb._lock:
        cb.failures += 1
        cb.last_failure = time.time()
        if cb.failures >= cb.failure_threshold:
            cb.state = DBCircuitBreaker.State.OPEN


def _cb_record_success(cb: DBCircuitBreaker) -> None:
    """Registra un successo: chiude il breaker (da HALF_OPEN) e azzera i fail."""
    with cb._lock:
        if cb.state == DBCircuitBreaker.State.HALF_OPEN:
            cb.state = DBCircuitBreaker.State.CLOSED
        cb.failures = 0


def with_circuit_breaker(func: Callable) -> Callable:
    """Decoratore: protegge l'accesso al DB con il circuit breaker.

    - OPEN (entro il timeout): 503 + Retry-After, senza toccare il DB.
    - HALF_OPEN: ammette solo metodi sicuri (GET) per testare il recupero.
    - CLOSED / OPEN scaduto: esegue la route. Il breaker si APRE solo su errori
      DB infrastrutturali (`_is_db_infra_error`); gli errori client danno 400,
      gli altri 500 — senza falsare lo stato del breaker.
    """
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        cb: DBCircuitBreaker = _services()["circuit"]
        stato = cb.state
        scaduto = (time.time() - cb.last_failure) > cb.timeout
        if stato == DBCircuitBreaker.State.OPEN and not scaduto:
            retry = int(cb.timeout - (time.time() - cb.last_failure)) + 1
            logger.warning("Circuit breaker OPEN path=%s retry=%ss",
                           request.path, retry)
            return _error(503, "service_unavailable", {"Retry-After": str(retry)})
        if stato == DBCircuitBreaker.State.HALF_OPEN and request.method not in _SAFE_METHODS:
            logger.warning("Circuit breaker HALF_OPEN: scrittura rifiutata path=%s",
                           request.path)
            return _error(503, "service_unavailable", {"Retry-After": "5"})
        if stato == DBCircuitBreaker.State.OPEN and scaduto:
            with cb._lock:  # finestra di test di recupero
                cb.state = DBCircuitBreaker.State.HALF_OPEN
        try:
            result = func(*args, **kwargs)
        except DB_CLIENT_ERRORS:
            logger.warning("Errore DB client path=%s", request.path)
            return _error(400, "bad_request")
        except DB_INFRA_ERRORS as exc:
            if _is_db_infra_error(exc):
                _cb_record_failure(cb)
                logger.error("Errore DB infra (breaker++) path=%s",
                             request.path, exc_info=True)
                return _error(503, "service_unavailable",
                              {"Retry-After": str(cb.timeout)})
            logger.critical("Errore DB non-infra path=%s", request.path, exc_info=True)
            return _error(500, "internal_error")
        except Exception:
            logger.critical("Errore route path=%s", request.path, exc_info=True)
            return _error(500, "internal_error")
        _cb_record_success(cb)
        return result
    return wrapper


# ═══════════════════════════════════════════════════════════════════════════
# Route: AUTH & HEALTH
# ═══════════════════════════════════════════════════════════════════════════
@api.route("/auth/token", methods=["POST"])
@fortress
def auth_token() -> Any:
    """Endpoint di emissione token (placeholder: l'auth e' a chiave/HMAC).

    Returns:
        JSON con il bearer token configurato (solo se la richiesta e' firmata).
    """
    return jsonify({"token_type": "bearer", "token": Config.BEARER_TOKEN})


@api.route("/health", methods=["GET"])
def health() -> Any:
    """Health check base (nessuna autenticazione, solo rate limiting).

    Returns:
        200 se il DB risponde, altrimenti 503.
    """
    ip = _client_ip()
    allowed, headers = get_rate_limiter().is_allowed(ip)
    if not allowed:
        return _error(429, "rate_limited", headers)
    try:
        _query("SELECT 1")
        return jsonify({"status": "ok"})
    except Exception:
        logger.error("Health check DB fallito", exc_info=True)
        return _error(503, "service_unavailable", {"Retry-After": "5"})


@api.route("/health/circuit", methods=["GET"])
def health_circuit() -> Any:
    """Stato del circuit breaker (rate limiting base, no auth).

    Returns:
        JSON con lo stato corrente del `DBCircuitBreaker`.
    """
    ip = _client_ip()
    allowed, headers = get_rate_limiter().is_allowed(ip)
    if not allowed:
        return _error(429, "rate_limited", headers)
    try:
        return jsonify(_services()["circuit"].get_status())
    except Exception:
        logger.error("health/circuit fallito", exc_info=True)
        return _error(500, "internal_error")


@api.route("/health/system", methods=["GET"])
def health_system() -> Any:
    """Metriche di sistema (RSS, uptime, stato circuito, heartbeat).

    Returns:
        JSON con lo stato di salute calcolato dal SelfHealingManager.
    """
    ip = _client_ip()
    allowed, headers = get_rate_limiter().is_allowed(ip)
    if not allowed:
        return _error(429, "rate_limited", headers)
    try:
        watchdog: SelfHealingManager = _services()["watchdog"]
        salute = watchdog._check_health()  # snapshot corrente (no polling attivo)
        return jsonify({
            "status": salute.status,
            "memory_rss_mb": round(salute.memory_usage_mb, 2),
            "memory_percent": round(salute.memory_percent * 100, 1),
            "uptime_seconds": round(salute.uptime_seconds, 0),
            "circuit_breaker": salute.circuit_breaker_state,
            "db_connection_ok": salute.db_connection_ok,
            "heartbeat": salute.timestamp,
        })
    except Exception:
        logger.error("health/system fallito", exc_info=True)
        return _error(500, "internal_error")


# ═══════════════════════════════════════════════════════════════════════════
# Route: ESCROW
# ═══════════════════════════════════════════════════════════════════════════
@api.route("/escrow/create", methods=["POST"])
@fortress
@with_circuit_breaker
def escrow_create() -> Any:
    """Crea una transazione escrow (pagamento split + fondi bloccati).

    Body JSON: prenotazione_id, importo_totale, commissione_tavola, quota_partner.

    Returns:
        201 con escrow_id/pagamento_id; 400 se il payload non e' valido.
    """
    data = request.get_json(silent=True) or {}
    try:
        prenotazione_id = int(data["prenotazione_id"])
        importo = float(data["importo_totale"])
        commissione = float(data["commissione_tavola"])
        quota = float(data["quota_partner"])
    except (KeyError, TypeError, ValueError):
        return _error(400, "invalid_payload")

    svc = _services()
    pagamento_id = svc["payments"].registra_pagamento(
        prenotazione_id, importo, commissione, quota)
    escrow_id = svc["escrow"].inizializza_escrow(pagamento_id)
    svc["audit"].registra_azione(
        "ESCROW", escrow_id, AzioneAudit.ESCROW_CREATO,
        {"pagamento_id": pagamento_id, "importo": importo})
    return jsonify({"escrow_id": escrow_id, "pagamento_id": pagamento_id,
                    "stato": "bloccato"}), 201


@api.route("/escrow/<int:escrow_id>", methods=["GET"])
@fortress_readonly
@with_circuit_breaker
def escrow_detail(escrow_id: int) -> Any:
    """Dettaglio di una transazione escrow.

    Args:
        escrow_id: id del record in `escrow_fondi`.

    Returns:
        200 con il record; 404 se inesistente.
    """
    righe = _query("SELECT * FROM escrow_fondi WHERE id = ?", (escrow_id,))
    if not righe:
        return _error(404, "not_found")
    return jsonify(righe[0])


@api.route("/escrow/<int:escrow_id>/release", methods=["POST"])
@fortress
@with_circuit_breaker
def escrow_release(escrow_id: int) -> Any:
    """Rilascia i fondi al venditore (solo da stato 'DA_APPROVARE_ADMIN').

    Args:
        escrow_id: id dell'escrow.

    Returns:
        200 se sbloccato; 409 se non in uno stato rilasciabile.
    """
    svc = _services()
    if svc["escrow"].approva_sblocco_admin(escrow_id):
        svc["audit"].registra_azione(
            "ESCROW", escrow_id, AzioneAudit.ESCROW_SBLOCCATO, {})
        return jsonify({"escrow_id": escrow_id, "stato": "sbloccato"})
    return _error(409, "not_releasable")


@api.route("/escrow/<int:escrow_id>/refund", methods=["POST"])
@fortress
@with_circuit_breaker
def escrow_refund(escrow_id: int) -> Any:
    """Rimborsa l'acquirente (consentito se i fondi non sono gia' sbloccati).

    Args:
        escrow_id: id dell'escrow.

    Returns:
        200 se rimborsato; 409 se gia' sbloccato/inesistente.
    """
    toccate = _execute(
        "UPDATE escrow_fondi SET stato = 'rimborsato' "
        "WHERE id = ? AND stato != 'sbloccato'", (escrow_id,))
    if toccate == 0:
        return _error(409, "not_refundable")
    _services()["audit"].registra_azione(
        "ESCROW", escrow_id, AzioneAudit.ESCROW_DISPUTA, {"azione": "refund"})
    return jsonify({"escrow_id": escrow_id, "stato": "rimborsato"})


@api.route("/escrow/list", methods=["GET"])
@fortress_readonly
@with_circuit_breaker
def escrow_list() -> Any:
    """Lista paginata delle transazioni escrow.

    Query string: page (>=1), per_page (1..100).

    Returns:
        200 con elenco e metadati di paginazione.
    """
    page = max(1, request.args.get("page", default=1, type=int))
    per_page = min(100, max(1, request.args.get("per_page", default=20, type=int)))
    offset = (page - 1) * per_page
    righe = _query("SELECT * FROM escrow_fondi ORDER BY id DESC LIMIT ? OFFSET ?",
                   (per_page, offset))
    return jsonify({"page": page, "per_page": per_page, "items": righe})


# ═══════════════════════════════════════════════════════════════════════════
# Route: PAGAMENTI SPLIT
# ═══════════════════════════════════════════════════════════════════════════
@api.route("/payments/split", methods=["POST"])
@fortress
@with_circuit_breaker
def payments_split() -> Any:
    """Registra un pagamento con ripartizione (split).

    Body JSON: prenotazione_id, importo_totale, commissione_tavola, quota_partner.

    Returns:
        201 con pagamento_id; 400 se il payload non e' valido.
    """
    data = request.get_json(silent=True) or {}
    try:
        prenotazione_id = int(data["prenotazione_id"])
        importo = float(data["importo_totale"])
        commissione = float(data["commissione_tavola"])
        quota = float(data["quota_partner"])
    except (KeyError, TypeError, ValueError):
        return _error(400, "invalid_payload")
    pagamento_id = _services()["payments"].registra_pagamento(
        prenotazione_id, importo, commissione, quota)
    return jsonify({"pagamento_id": pagamento_id, "stato": "pending"}), 201


@api.route("/payments/<int:pagamento_id>", methods=["GET"])
@fortress_readonly
@with_circuit_breaker
def payments_detail(pagamento_id: int) -> Any:
    """Dettaglio di un pagamento split.

    Args:
        pagamento_id: id del record in `pagamenti_split`.

    Returns:
        200 con il record; 404 se inesistente.
    """
    righe = _query("SELECT * FROM pagamenti_split WHERE id = ?", (pagamento_id,))
    if not righe:
        return _error(404, "not_found")
    return jsonify(righe[0])


@api.route("/payments/summary", methods=["GET"])
@fortress_readonly
@with_circuit_breaker
def payments_summary() -> Any:
    """Riepilogo finanziario (quote piattaforma/partner, dispute, notifiche).

    Returns:
        200 con le metriche aggregate del `DashboardManager`.
    """
    metriche = _services()["dashboard"].get_riepilogo_finanziario()
    return jsonify({
        "commissioni_nette": metriche.commissioni_nette,
        "fondi_partner_bloccati": metriche.fondi_partner_bloccati,
        "escrow_in_disputa": metriche.escrow_in_disputa,
        "notifiche_non_lette": metriche.notifiche_non_lette,
    })


# ═══════════════════════════════════════════════════════════════════════════
# Route: AUDIT
# ═══════════════════════════════════════════════════════════════════════════
@api.route("/audit/logs", methods=["GET"])
@fortress_readonly
@with_circuit_breaker
def audit_logs() -> Any:
    """Log di audit, paginati e filtrabili.

    Query string: entita_tipo, azione, dal (ISO), al (ISO), page, per_page.

    Returns:
        200 con elenco filtrato (sola lettura sulla tabella immutabile).
    """
    page = max(1, request.args.get("page", default=1, type=int))
    per_page = min(100, max(1, request.args.get("per_page", default=20, type=int)))
    offset = (page - 1) * per_page

    condizioni = []
    params: list = []
    for campo, colonna in (("entita_tipo", "entita_tipo"), ("azione", "azione")):
        valore = request.args.get(campo)
        if valore:
            condizioni.append(f"{colonna} = ?")
            params.append(valore)
    dal = request.args.get("dal")
    al = request.args.get("al")
    if dal:
        condizioni.append("data_creazione >= ?")
        params.append(dal)
    if al:
        condizioni.append("data_creazione <= ?")
        params.append(al)
    where = (" WHERE " + " AND ".join(condizioni)) if condizioni else ""
    sql = ("SELECT * FROM audit_logs" + where +
           " ORDER BY data_creazione DESC, id DESC LIMIT ? OFFSET ?")
    righe = _query(sql, tuple(params) + (per_page, offset))
    return jsonify({"page": page, "per_page": per_page, "items": righe})


# ═══════════════════════════════════════════════════════════════════════════
# App factory
# ═══════════════════════════════════════════════════════════════════════════
def _registra_error_handlers(app: Flask) -> None:
    """Registra gli error handler globali che rispondono sempre in JSON."""

    @app.errorhandler(404)
    def _not_found(_e: Exception) -> Any:
        logger.info("404 path=%s", request.path)
        return _error(404, "not_found")

    @app.errorhandler(413)
    def _payload_too_large(_e: Exception) -> Any:
        logger.warning("413 path=%s ip=%s", request.path, _client_ip())
        return _error(413, "payload_too_large")

    @app.errorhandler(429)
    def _too_many(_e: Exception) -> Any:
        return _error(429, "rate_limited")

    @app.errorhandler(503)
    def _unavailable(_e: Exception) -> Any:
        logger.warning("503 path=%s", request.path)
        return _error(503, "service_unavailable", {"Retry-After": "5"})

    @app.errorhandler(500)
    def _server_error(_e: Exception) -> Any:
        logger.critical("500 path=%s", request.path, exc_info=True)
        return _error(500, "internal_error")


def _registra_middleware_logging(app: Flask) -> None:
    """Aggiunge il logging strutturato per richiesta (durata, status, ip)."""

    @app.before_request
    def _start_timer() -> None:
        g.start_time = time.time()

    @app.after_request
    def _log_request(response: Response) -> Response:
        duration_ms = round((time.time() - getattr(g, "start_time", time.time())) * 1000, 2)
        logger.info(
            "request method=%s path=%s status=%s duration_ms=%s ip=%s ua=%s",
            request.method, request.path, response.status_code, duration_ms,
            _client_ip(), request.headers.get("User-Agent", "-"))
        return response

    @app.teardown_appcontext
    def _teardown(_exc: Optional[BaseException]) -> None:
        # Connessione-per-operazione: nessuna connessione persistente da chiudere.
        return None


def create_app(config_name: str = "production") -> Flask:
    """Crea e configura l'applicazione Flask (factory pattern).

    Args:
        config_name: nome ambiente (informativo; la config reale viene da env).

    Returns:
        L'istanza Flask pronta, con servizi, route, error handler e middleware.
    """
    app = Flask(__name__)
    app.config["ENV_NAME"] = config_name
    app.config["JSON_SORT_KEYS"] = False
    # H3: limite dimensione body (anti-DoS). Default 1 MiB, override via env.
    app.config["MAX_CONTENT_LENGTH"] = int(
        os.environ.get("MAX_BODY_BYTES", str(1024 * 1024)))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # Servizi reali (DatabaseCandidati crea/garantisce lo schema in WAL).
    db = DatabaseCandidati(Config.DB_PATH)
    escrow = EscrowManager(db)
    watchdog = SelfHealingManager(db_path=Config.DB_PATH)
    app.extensions["core_auto"] = {
        "db": db,
        "escrow": escrow,
        "payments": PagamentoSplitManager(db),
        "audit": AuditManager(db),
        "dashboard": DashboardManager(db),
        "circuit": DBCircuitBreaker(),
        "watchdog": watchdog,
    }

    app.register_blueprint(api)
    _registra_error_handlers(app)
    _registra_middleware_logging(app)

    # Cleanup risorse all'uscita del processo (oltre ai signal di Gunicorn).
    import atexit
    atexit.register(watchdog.stop_monitoring)

    logger.info("CORE_AUTO app inizializzata (env=%s, db=%s)",
                config_name, Config.DB_PATH)
    return app


if __name__ == "__main__":
    import os

    application = create_app()
    application.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
