"""FASE 181 — FINANCIAL AUDIT CONSOLE (lo "Spotlight" contabile del Field).

Incolli QUALSIASI identificativo e ottieni la scheda contabile unica, READ-ONLY:
  - riferimento (hex, anche parziale >= 8 char) o codice cliente BVIP-XXXX-XXXX
    (che E' il riferimento: primi 8 hex resi leggibili, fase59);
  - nota ND-/NC-<anno>-<progressivo> (porta alla scheda della sua prenotazione);
  - host_id (h_...) -> scheda host (payout per valuta, debiti, movimenti).

La scheda unisce i libri (prenotazione fase162, payout fase131, garanzia fase160,
giornale+note+debiti fase177) e da' un SEMAFORO D'INTEGRITA' per componente e
complessivo:
  🟢 verde  = i libri raccontano la stessa storia (incassato<->giornale,
              bonifico<->giornale, rimborso<->giornale, ledger<->giornale);
  🔴 rosso  = MISMATCH: qualcuno dice una cosa e qualcun altro un'altra;
  🟡 giallo = Stripe non verificabile ADESSO (timeout 2s / errore rete);
  ⚪ grigio = non applicabile (pagamento non online / cs_ non salvato — storico
              pre-audit: ONESTO, non finto-verde).
SHADOW-CHECK Stripe: se il webhook ha salvato l'id sessione (cs_...), la scheda
interroga Stripe (read-only, 2s) e confronta payment_status con il nostro stato.

ZERO SCRITTURE: la console non tocca MAI nessun libro (provato dal test: il
giornale ha lo stesso numero di righe prima e dopo N consultazioni).
Whitelist campi: MAI dati fiscali (CF/P.IVA/IBAN) ne' roba del Bunker.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("core_auto.audit_console")

_RE_NOTA = re.compile(r"^(ND|NC)-\d{4}-\d{1,6}$", re.IGNORECASE)
_RE_BVIP = re.compile(r"^BVIP-([0-9A-Fa-f]{4})-([0-9A-Fa-f]{4})$", re.IGNORECASE)
_RE_HEX = re.compile(r"^[0-9a-f]{8,64}$")


def stripe_session_fetch(secret_key: str, cs_id: str, *, timeout: float = 2.0
                         ) -> Dict[str, Any]:
    """SHADOW-CHECK reale: legge la sessione checkout da Stripe (GET, read-only).
    Ritorna {'ok': True, 'payment_status': ...} o {'ok': False, 'motivo': ...}.
    Timeout CORTO (2s): la scheda non deve mai restare appesa per Stripe."""
    if not (secret_key and isinstance(cs_id, str) and cs_id.startswith("cs_")):
        return {"ok": False, "motivo": "non_configurato"}
    try:
        from urllib.request import Request, urlopen
        req = Request("https://api.stripe.com/v1/checkout/sessions/" + cs_id,
                      headers={"Authorization": "Bearer " + secret_key})
        with urlopen(req, timeout=timeout) as r:
            dati = json.loads(r.read().decode("utf-8"))
        return {"ok": True, "payment_status": dati.get("payment_status", ""),
                "status": dati.get("status", "")}
    except Exception as e:  # timeout / rete / 4xx: la scheda resta GIALLA, mai appesa
        return {"ok": False, "motivo": type(e).__name__}


def risolvi_id(sistema: Any, termine: Any) -> Dict[str, Any]:
    """Riconosce COSA e' il termine e lo risolve. {'tipo': 'nota'|'host'|'riferimento'|
    'ambiguo'|None, ...}. BVIP-XXXX-XXXX e prefissi hex si risolvono via ricerca a
    prefisso sul registro prenotazioni (indice PK)."""
    t = str(termine or "").strip()
    if not t:
        return {"tipo": None}
    if _RE_NOTA.match(t):
        fc = getattr(sistema, "finanza", None)
        n = fc.nota(t) if fc is not None else None
        if n:
            return {"tipo": "nota", "nota": n, "riferimento": n.get("riferimento", "")}
        return {"tipo": None}
    if t.startswith("h_"):
        reg = getattr(sistema, "registro_host", None)
        info = reg.info_host(t) if reg is not None else None
        if info:
            return {"tipo": "host", "host_id": t}
        return {"tipo": None}
    m = _RE_BVIP.match(t)
    prefisso = ((m.group(1) + m.group(2)).lower() if m
                else (t.lower() if _RE_HEX.match(t.lower()) else ""))
    if prefisso:
        pp = getattr(sistema, "pagamenti_pendenti", None)
        if pp is None or not hasattr(pp, "cerca_prenotazioni"):
            return {"tipo": None}
        r = pp.cerca_prenotazioni(prefisso, limit=3)
        pren = r.get("prenotazioni", [])
        if len(pren) == 1:
            return {"tipo": "riferimento", "riferimento": pren[0]["riferimento"]}
        if len(pren) > 1:
            return {"tipo": "ambiguo",
                    "candidati": [p["riferimento"] for p in pren]}
        return {"tipo": None}
    return {"tipo": None}


def _semaforo_coerenza(pren: Optional[Dict[str, Any]], payout: Optional[Dict[str, Any]],
                       tipi_giornale: List[str]) -> Dict[str, Any]:
    """Confronto incrociato dei libri: ogni violazione e' un ROSSO col suo perche'."""
    problemi: List[str] = []
    stato = (pren or {}).get("stato", "")
    if stato == "pagato" and "incasso" not in tipi_giornale:
        problemi.append("stato 'pagato' ma NESSUN 'incasso' nel giornale")
    if stato == "rimborsato" and "rimborso" not in tipi_giornale:
        problemi.append("stato 'rimborsato' ma NESSUN 'rimborso' nel giornale")
    st_pay = (payout or {}).get("stato", "")
    bonifico_nel_giornale = ("payout_host" in tipi_giornale
                             or "payout_manuale" in tipi_giornale)
    if st_pay in ("in_transito", "pagato") and not bonifico_nel_giornale:
        problemi.append("payout '%s' ma NESSUN bonifico nel giornale" % st_pay)
    if "payout_host" in tipi_giornale and st_pay == "maturato":
        problemi.append("bonifico nel giornale ma ledger payout fermo a 'maturato'")
    if pren is None:
        return {"colore": "grigio", "problemi": []}
    return {"colore": "rosso" if problemi else "verde", "problemi": problemi}


def _semaforo_stripe(pren: Optional[Dict[str, Any]],
                     stripe_check: Optional[Callable[[str], Dict[str, Any]]]
                     ) -> Dict[str, Any]:
    """Verde = Stripe conferma; giallo = non verificabile ORA; grigio = n/a (onesto)."""
    cs = ""
    try:
        dj = json.loads((pren or {}).get("corpo_json") or "{}")
        cs = dj.get("stripe_cs", "") if isinstance(dj, dict) else ""
    except Exception:
        cs = ""
    if not cs or stripe_check is None:
        return {"colore": "grigio",
                "nota": "cs_ non disponibile (storico pre-audit o pagamento non online)"}
    esito = stripe_check(cs)
    if not esito.get("ok"):
        return {"colore": "giallo", "nota": "Stripe non verificabile ora (%s)"
                % esito.get("motivo", "?"), "cs": cs}
    paid = esito.get("payment_status") == "paid"
    nostro_pagato = (pren or {}).get("stato") in ("pagato", "rimborsato")
    if paid == nostro_pagato or ((pren or {}).get("stato") == "rimborsato"):
        return {"colore": "verde", "payment_status": esito.get("payment_status"),
                "cs": cs}
    return {"colore": "rosso", "nota": "Stripe dice '%s' ma da noi lo stato e' '%s'"
            % (esito.get("payment_status"), (pren or {}).get("stato")), "cs": cs}


def scheda_riferimento(sistema: Any, rif: str, *,
                       stripe_check: Optional[Callable[[str], Dict[str, Any]]] = None
                       ) -> Dict[str, Any]:
    """La scheda contabile unica di UNA prenotazione (read-only, whitelist campi)."""
    pp = getattr(sistema, "pagamenti_pendenti", None)
    pd = getattr(sistema, "payout", None)
    gz = getattr(sistema, "garanzia", None)
    fc = getattr(sistema, "finanza", None)
    pren = pp.info(rif) if pp is not None else None
    payout = pd.info(rif) if pd is not None else None
    gar = gz.stato(rif) if gz is not None else None
    movimenti = fc.movimenti(rif) if fc is not None else []
    note = fc.note_per_riferimento(rif) if fc is not None else []
    tipi = [m.get("tipo", "") for m in movimenti]
    coer = _semaforo_coerenza(pren, payout, tipi)
    stripe_sem = _semaforo_stripe(pren, stripe_check)
    colori = [coer["colore"], stripe_sem["colore"]]
    complessivo = ("rosso" if "rosso" in colori
                   else "giallo" if "giallo" in colori else "verde")
    # WHITELIST: solo campi operativi (mai corpo_json/idem_key nella risposta)
    p_op = None
    if pren:
        p_op = {k: pren.get(k) for k in ("riferimento", "alloggio_id", "check_in",
                                          "check_out", "stato", "host_id", "email")}
    return {"tipo": "riferimento", "riferimento": rif,
            "prenotazione": p_op,
            "payout": ({k: payout.get(k) for k in ("stato", "minori", "valuta")}
                       if payout else None),
            "garanzia": ({k: gar.get(k) for k in ("stato", "importo_host_cents",
                                                   "host_riceve_cents",
                                                   "ospite_rimborso_cents", "motivo")}
                         if gar else None),
            "movimenti": [{k: m.get(k) for k in ("tipo", "importo_cents", "valuta",
                                                  "ts", "causale")} for m in movimenti],
            "note": [{k: n.get(k) for k in ("nota_id", "tipo", "importo_cents",
                                             "valuta", "stato", "causale")}
                     for n in note],
            "semaforo": {"complessivo": complessivo, "coerenza": coer,
                         "stripe": stripe_sem}}


def scheda_host(sistema: Any, host_id: str) -> Dict[str, Any]:
    """Scheda host (read-only): payout per valuta, debiti aperti, identita' OPERATIVA
    (mai CF/P.IVA/IBAN: quelli restano al Bunker/DAC7)."""
    reg = getattr(sistema, "registro_host", None)
    pd = getattr(sistema, "payout", None)
    fc = getattr(sistema, "finanza", None)
    info = (reg.info_host(host_id) or {}) if reg is not None else {}
    debiti = fc.debiti_host(host_id, stato="aperto") if fc is not None else []
    return {"tipo": "host", "host_id": host_id,
            "identita": {"email": info.get("email", ""),
                         "ragione_sociale": info.get("ragione_sociale", ""),
                         "stato": info.get("stato", "")},
            "payout": (pd.riepilogo(host_id) if pd is not None else {}),
            "debiti_aperti": [{"nota": d.get("debito_id"), "residuo_cents":
                               d.get("residuo_cents"), "valuta": d.get("valuta"),
                               "riferimento": d.get("riferimento")} for d in debiti]}


def componi(sistema: Any, termine: Any, *,
            stripe_check: Optional[Callable[[str], Dict[str, Any]]] = None
            ) -> Dict[str, Any]:
    """Punto d'ingresso: risolve il termine e compone la scheda giusta."""
    ris = risolvi_id(sistema, termine)
    tipo = ris.get("tipo")
    if tipo == "host":
        return scheda_host(sistema, ris["host_id"])
    if tipo in ("riferimento", "nota"):
        scheda = scheda_riferimento(sistema, ris["riferimento"],
                                    stripe_check=stripe_check)
        if tipo == "nota":
            n = ris["nota"]
            scheda["nota_cercata"] = {k: n.get(k) for k in
                                      ("nota_id", "tipo", "importo_cents", "valuta",
                                       "stato", "causale")}
        return scheda
    if tipo == "ambiguo":
        return {"tipo": "ambiguo", "candidati": ris["candidati"]}
    return {"tipo": None, "errore": "id_non_riconosciuto"}
