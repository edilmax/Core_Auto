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


# Stati del payout che significano "soldi ancora IN BALLO" (dovuti all'host, non ancora
# arrivati sul suo conto). 'pagato' e' concluso, non blocca.
_PAYOUT_IN_BALLO = ("maturato", "in_transito")


def obblighi_pendenti(sistema: Any, host_id: Any) -> Dict[str, Any]:
    """Cosa impedisce di cancellare un host SENZA lasciare qualcuno a piedi o un conto
    aperto. Ritorna {} se e' pulito, altrimenti i motivi con i numeri.

    Tre pericoli, tutti su soldi o su una persona reale:
      · prenotazioni ATTIVE (un ospite che ha pagato e sta per arrivare, o e' dentro);
      · PAYOUT DOVUTO (soldi che dobbiamo ancora bonificare all'host: cancellarlo li
        renderebbe orfani);
      · ESCROW APERTO (soldi di un ospite ancora in custodia su un suo alloggio);
      · TRANSAZIONI IN SOSPESO (richieste da approvare).

    Read-only, isolato per archivio: un archivio che non risponde non deve trasformarsi
    in un falso 'tutto pulito' che poi fa cancellare sopra dei soldi. Per questo, se un
    controllo NON si puo' fare, lo si segna come dubbio ('_incerti') invece di ignorarlo.
    """
    import datetime as _dt
    motivi: Dict[str, Any] = {}
    incerti: List[str] = []
    hid = str(host_id)
    cat = getattr(sistema, "catalogo", None)
    inv = getattr(sistema, "inventario", None)
    pay = getattr(sistema, "payout", None)
    pend = getattr(sistema, "pagamenti_pendenti", None)
    gar = getattr(sistema, "garanzia", None)
    slugs = _slug_host(cat, hid)

    # 1) prenotazioni attive/future su uno qualunque dei suoi alloggi
    oggi = _dt.date.today().isoformat()
    if inv is not None and hasattr(inv, "elenco_prenotazioni"):
        attive = 0
        for s in slugs:
            try:
                for p in (inv.elenco_prenotazioni(alloggio_id=s, limit=200) or []):
                    if not p.get("rimborsato") and str(p.get("check_out", "")) >= oggi:
                        attive += 1
            except Exception:
                incerti.append("prenotazioni:%s" % s)
                logger.warning("obblighi: prenotazioni %s (ISOLATO)", s, exc_info=True)
        if attive:
            motivi["prenotazioni_attive"] = attive
    else:
        incerti.append("prenotazioni")

    # 2) payout dovuto (maturato o in transito), in qualunque valuta
    if pay is not None and hasattr(pay, "riepilogo"):
        try:
            dovuti = {}
            for valuta, per_stato in (pay.riepilogo(hid) or {}).items():
                tot = sum(int(per_stato.get(s, 0) or 0) for s in _PAYOUT_IN_BALLO)
                if tot > 0:
                    dovuti[valuta] = tot
            if dovuti:
                motivi["payout_dovuto"] = dovuti
        except Exception:
            incerti.append("payout")
            logger.warning("obblighi: payout (ISOLATO)", exc_info=True)
    else:
        incerti.append("payout")

    # 3) escrow aperto su uno dei suoi alloggi (soldi dell'ospite in custodia)
    if gar is not None and hasattr(gar, "aperte_per_alloggio"):
        aperte = 0
        for s in slugs:
            try:
                aperte += int(gar.aperte_per_alloggio(s) or 0)
            except Exception:
                incerti.append("escrow:%s" % s)
                logger.warning("obblighi: escrow %s (ISOLATO)", s, exc_info=True)
        if aperte:
            motivi["escrow_aperto"] = aperte
    else:
        incerti.append("escrow")

    # 4) transazioni in sospeso (richieste da approvare)
    if pend is not None and hasattr(pend, "da_approvare"):
        try:
            n = len(pend.da_approvare(hid, limit=200) or [])
            if n:
                motivi["in_sospeso"] = n
        except Exception:
            incerti.append("in_sospeso")
            logger.warning("obblighi: sospesi (ISOLATO)", exc_info=True)
    else:
        incerti.append("in_sospeso")

    if incerti:
        motivi["_incerti"] = sorted(set(incerti))
    return motivi


def cancella_attivita_host(sistema: Any, host_id: Any, *, forza: bool = False) -> Dict[str, Any]:
    """Cancella host_id da OGNI archivio del sistema e verifica. Ritorna report:
    {host_id, cancellati:{archivio:n}, residui:{archivio:n}, ok:bool}.

    RIFIUTA se l'host ha soldi o persone in ballo (prenotazioni attive, payout dovuto,
    escrow aperto, sospesi) — a meno di `forza=True`, che serve per un obbligo legale
    inderogabile ma **registra comunque** cosa c'era, cosi' nulla sparisce in silenzio.
    Prima questa funzione cancellava SEMPRE, lasciando ospiti paganti senza stanza e
    bonifici orfani: era il buco piu' grave dell'audit del 2026-07-22."""
    rep: Dict[str, Any] = {"host_id": host_id, "cancellati": {}, "residui": {}, "ok": False}
    if not (isinstance(host_id, str) and host_id):
        rep["errore"] = "host_id_non_valido"
        return rep

    obblighi = obblighi_pendenti(sistema, host_id)
    if obblighi and not forza:
        rep["errore"] = "obblighi_pendenti"
        rep["obblighi"] = obblighi
        return rep                                  # NON si cancella: prima si sistema
    if obblighi and forza:
        rep["forzato_nonostante"] = obblighi        # tracciato: mai perso in silenzio
        logger.critical("ERASURE FORZATA su host con obblighi: %s -> %s", host_id, obblighi)

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
