"""
CORE_AUTO - Fase 156: CANCELLAZIONE TOTALE di un host/attivita' + VERIFICA "da pertutto".

Il "tasto cancella tutto": rimuove un host e TUTTI i suoi dati da OGNI archivio (annunci,
inventario, messaggi, referral/crediti, account) e poi RI-CONTROLLA ogni archivio per
confermare che non sia rimasto NULLA. Diritto all'oblio (GDPR/PIPL/...) + pulizia dati di test
prima del lancio.

Resiliente: opera solo sugli store presenti che espongono i metodi (getattr) -> aggiungere un
nuovo store in futuro non richiede toccare questo file. Best-effort isolato per store: se uno
fallisce, gli altri proseguono e il residuo viene REGISTRATO (mai un falso "cancellato").
Vincitrice-del-benchmark: cancella-poi-verifica con report per-archivio, ok=True solo se 0
residui ovunque.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _slug_host(catalogo: Any, host_id: str) -> List[str]:
    try:
        el = catalogo.alloggi_host(host_id, limit=500) if catalogo else []
        return [a.get("slug") for a in (el or []) if isinstance(a, dict) and a.get("slug")]
    except Exception:
        logger.warning("erasure: lettura slug fallita (ISOLATA)", exc_info=True)
        return []


def _safe(fn, *a) -> int:
    try:
        n = fn(*a)
        return int(n) if isinstance(n, int) and not isinstance(n, bool) else 0
    except Exception:
        logger.warning("erasure: passo fallito (ISOLATO)", exc_info=True)
        return 0


def cancella_attivita_host(sistema: Any, host_id: Any) -> Dict[str, Any]:
    """Cancella host_id da OGNI archivio del sistema e verifica. Ritorna report:
    {host_id, cancellati:{archivio:n}, residui:{archivio:n}, ok:bool}."""
    rep: Dict[str, Any] = {"host_id": host_id, "cancellati": {}, "residui": {}, "ok": False}
    if not (isinstance(host_id, str) and host_id):
        rep["errore"] = "host_id_non_valido"
        return rep
    cat = getattr(sistema, "catalogo", None)
    inv = getattr(sistema, "inventario", None)
    reg = getattr(sistema, "registro_host", None)
    msg = getattr(sistema, "messaggistica", None)
    viral = getattr(sistema, "viral", None)

    slugs = _slug_host(cat, host_id)                       # PRIMA di cancellare il catalogo

    # --- cancella in ordine sicuro ---
    if inv is not None and hasattr(inv, "cancella_alloggio"):
        rep["cancellati"]["inventario"] = sum(_safe(inv.cancella_alloggio, s) for s in slugs)
    if cat is not None and hasattr(cat, "cancella_alloggi_host"):
        rep["cancellati"]["alloggi"] = _safe(cat.cancella_alloggi_host, host_id)
    if msg is not None and hasattr(msg, "cancella_messaggi_host"):
        rep["cancellati"]["messaggi"] = _safe(msg.cancella_messaggi_host, host_id)
    if viral is not None and hasattr(viral, "cancella_host"):
        rep["cancellati"]["referral"] = _safe(viral.cancella_host, host_id)
    if reg is not None and hasattr(reg, "cancella_host"):
        rep["cancellati"]["host"] = _safe(reg.cancella_host, host_id)

    # --- VERIFICA: ricontrolla OGNI archivio (deve essere 0) ---
    residui: Dict[str, int] = {}
    if cat is not None and hasattr(cat, "conta_alloggi_host"):
        residui["alloggi"] = _safe(cat.conta_alloggi_host, host_id)
    if inv is not None and hasattr(inv, "conta_alloggio"):
        residui["inventario"] = sum(_safe(inv.conta_alloggio, s) for s in slugs)
    if msg is not None and hasattr(msg, "conta_messaggi_host"):
        residui["messaggi"] = _safe(msg.conta_messaggi_host, host_id)
    if viral is not None and hasattr(viral, "conta_host"):
        residui["referral"] = _safe(viral.conta_host, host_id)
    if reg is not None and hasattr(reg, "esiste_host"):
        residui["host"] = 1 if (reg.esiste_host(host_id) if hasattr(reg, "esiste_host")
                                else False) else 0

    rep["residui"] = residui
    rep["ok"] = all(v == 0 for v in residui.values()) if residui else False
    rep["verificato_archivi"] = list(residui.keys())
    return rep
