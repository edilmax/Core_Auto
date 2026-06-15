"""
CORE_AUTO / Tavola VIP - Fase 42: Observability (log JSON + metriche).

Visibilita' operativa SENZA dipendenze esterne (stdlib pura):
1. LOG STRUTTURATI JSON: una riga = un oggetto JSON interrogabile (ts, livello,
   logger, msg, correlation_id, campi extra, eccezione). Facile da indicizzare in
   qualunque stack di log.
2. METRICHE thread-safe: contatori + istogrammi di latenza, esposti in formato
   testo Prometheus su `/metrics`. Il registro e' protetto da lock (Variante
   vincitrice del benchmark: un contatore naive PERDE incrementi sotto carico
   concorrente; quello con lock e' esatto al 100%). Zero dipendenze: niente
   prometheus_client.

Isola: modulo a se'; l'agganciamento alle app Flask (booking/admin) e' opt-in via
`strumenta_app`/`registra_metriche` (import lazy di Flask).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Optional, Sequence, Tuple

logger = logging.getLogger("core_auto.observability")

# Campi standard di LogRecord da NON ripetere tra i "campi extra".
_STD = {"name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "taskName"}

BUCKETS_DEFAULT: Tuple[float, ...] = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25,
                                      0.5, 1.0, 2.5, 5.0, 10.0)


# ─────────────────────────────────────────────────────────────────────────────
# 1) Log strutturati JSON
# ─────────────────────────────────────────────────────────────────────────────
class FormatterJSON(logging.Formatter):
    """Serializza ogni LogRecord come una riga JSON. Include correlation_id e i
    campi passati via `extra=`; allega l'eccezione se presente. Mai solleva."""

    def format(self, record: logging.LogRecord) -> str:
        dati: Dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "livello": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for k, v in record.__dict__.items():        # campi extra (es. correlation_id)
            if k not in _STD and not k.startswith("_") and k not in dati:
                try:
                    json.dumps(v)
                    dati[k] = v
                except (TypeError, ValueError):
                    dati[k] = str(v)
        if record.exc_info:
            dati["exc"] = self.formatException(record.exc_info)
        return json.dumps(dati, ensure_ascii=False)


def configura_logging_json(livello: str = "INFO",
                           target: Optional[logging.Logger] = None) -> None:
    """Installa un handler con FormatterJSON sul logger (root di default),
    sostituendo gli handler esistenti. Idempotente per ri-chiamata."""
    lg = target or logging.getLogger()
    handler = logging.StreamHandler()
    handler.setFormatter(FormatterJSON())
    lg.handlers = [handler]
    lg.setLevel(getattr(logging, livello.upper(), logging.INFO))


# ─────────────────────────────────────────────────────────────────────────────
# 2) Registro metriche thread-safe (counter + histogram) -> testo Prometheus
# ─────────────────────────────────────────────────────────────────────────────
def _norm(etichette: Optional[Dict[str, str]]) -> Tuple[Tuple[str, str], ...]:
    if not etichette:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in etichette.items()))


def _rendi_etichette(et: Tuple[Tuple[str, str], ...], extra: str = "") -> str:
    parti = [f'{k}="{_esc(v)}"' for k, v in et]
    if extra:
        parti.append(extra)
    return "{" + ",".join(parti) + "}" if parti else ""


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


class RegistroMetriche:
    """Contatori e istogrammi di latenza, thread-safe (lock). Esposizione in
    formato testo Prometheus 0.0.4."""

    def __init__(self, buckets: Sequence[float] = BUCKETS_DEFAULT) -> None:
        # Bucket ORDINATI + dedup + positivi: l'esposizione Prometheus richiede `le`
        # ascendente; cosi' e' corretta qualunque sia l'ordine in ingresso.
        puliti = sorted({float(b) for b in buckets if b is not None and float(b) > 0})
        if not puliti:
            raise ValueError("buckets deve contenere almeno un valore > 0")
        self._lock = threading.Lock()
        self._contatori: Dict[Tuple[str, Tuple], int] = {}
        self._isto: Dict[Tuple[str, Tuple], Dict[str, Any]] = {}
        self._aiuti: Dict[str, str] = {}
        self._buckets = tuple(puliti)

    def descrivi(self, nome: str, aiuto: str) -> None:
        """Registra la riga `# HELP` di una metrica (standard Prometheus)."""
        with self._lock:
            self._aiuti[nome] = str(aiuto).replace("\n", " ")

    def incrementa(self, nome: str, etichette: Optional[Dict[str, str]] = None,
                   valore: int = 1) -> None:
        chiave = (nome, _norm(etichette))
        with self._lock:
            self._contatori[chiave] = self._contatori.get(chiave, 0) + valore

    def osserva(self, nome: str, secondi: float,
                etichette: Optional[Dict[str, str]] = None) -> None:
        chiave = (nome, _norm(etichette))
        with self._lock:
            h = self._isto.get(chiave)
            if h is None:
                h = {"conteggio": 0, "somma": 0.0, "bucket": [0] * len(self._buckets)}
                self._isto[chiave] = h
            h["conteggio"] += 1
            h["somma"] += secondi
            for i, b in enumerate(self._buckets):
                if secondi <= b:
                    h["bucket"][i] += 1

    @contextmanager
    def cronometra(self, nome: str, etichette: Optional[Dict[str, str]] = None):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.osserva(nome, time.perf_counter() - t0, etichette)

    def reset(self) -> None:
        with self._lock:
            self._contatori.clear()
            self._isto.clear()

    def esporre(self) -> str:
        with self._lock:                       # copia rapida sotto lock, render fuori
            contatori = list(self._contatori.items())
            isto = [(k, v["conteggio"], v["somma"], list(v["bucket"]))
                    for k, v in self._isto.items()]
            aiuti = dict(self._aiuti)
        # Raggruppa per nome in UN passo (O(n), non O(n^2)).
        c_per_nome: Dict[str, list] = {}
        for (n, et), val in contatori:
            c_per_nome.setdefault(n, []).append((et, val))
        i_per_nome: Dict[str, list] = {}
        for (n, et), cnt, somma, bk in isto:
            i_per_nome.setdefault(n, []).append((et, cnt, somma, bk))

        righe = []

        def intesta(nome: str, tipo: str) -> None:
            if nome in aiuti:
                righe.append("# HELP {} {}".format(nome, aiuti[nome]))
            righe.append("# TYPE {} {}".format(nome, tipo))

        for nome in sorted(c_per_nome):
            intesta(nome, "counter")
            for et, val in sorted(c_per_nome[nome], key=lambda x: x[0]):
                righe.append("{}{} {}".format(nome, _rendi_etichette(et), val))
        for nome in sorted(i_per_nome):
            intesta(nome, "histogram")
            for et, cnt, somma, bk in sorted(i_per_nome[nome], key=lambda x: x[0]):
                for i, b in enumerate(self._buckets):
                    et_b = _rendi_etichette(et, 'le="{}"'.format(b))
                    righe.append("{}_bucket{} {}".format(nome, et_b, bk[i]))
                et_inf = _rendi_etichette(et, 'le="+Inf"')
                righe.append("{}_bucket{} {}".format(nome, et_inf, cnt))
                righe.append("{}_sum{} {}".format(nome, _rendi_etichette(et), somma))
                righe.append("{}_count{} {}".format(nome, _rendi_etichette(et), cnt))
        return "\n".join(righe) + "\n"


# Singleton di processo (comodo per l'uso da tutto il backend).
metriche = RegistroMetriche()


# ─────────────────────────────────────────────────────────────────────────────
# 3) Aggancio a Flask (opt-in, import lazy)
# ─────────────────────────────────────────────────────────────────────────────
def registra_metriche(target: Any, registro: Optional[RegistroMetriche] = None,
                      path: str = "/metrics") -> None:
    """Espone le metriche in formato Prometheus su `path` (GET). In produzione
    va raggiunto solo dalla rete interna dello scraper."""
    from flask import Response
    reg = registro or metriche
    if getattr(target, "_metrics_registrato", False):
        return                              # idempotente: niente endpoint duplicato
    target._metrics_registrato = True

    @target.route(path, methods=["GET"], endpoint="metrics_export")
    def _metrics():
        return Response(reg.esporre(), mimetype="text/plain; version=0.0.4")


def strumenta_app(app: Any, registro: Optional[RegistroMetriche] = None) -> Any:
    """Registra contatore richieste + istogramma latenza per ogni richiesta HTTP
    (etichette: metodo, endpoint, stato)."""
    from flask import request, g
    reg = registro or metriche

    @app.before_request
    def _inizio():
        g._obs_t0 = time.perf_counter()

    @app.after_request
    def _fine(resp):
        endpoint = request.endpoint or "ignoto"
        if endpoint == "metrics_export":     # non auto-misurare l'endpoint /metrics
            return resp
        durata = time.perf_counter() - getattr(g, "_obs_t0", time.perf_counter())
        reg.incrementa("http_richieste_totale",
                       {"metodo": request.method, "endpoint": endpoint,
                        "stato": str(resp.status_code)})
        reg.osserva("http_durata_secondi", durata,
                    {"metodo": request.method, "endpoint": endpoint})
        return resp

    return app
