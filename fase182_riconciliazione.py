"""FASE 182 — RICONCILIAZIONE STRIPE (l'ultimo fantasma del pre-mortem: "re-sync").

L'Audit Console (fase181) controlla UNA prenotazione contro Stripe; questa controlla
TUTTO IL PERIODO: ogni sessione PAGATA che Stripe conosce contro ogni 'incasso' del
giornale immutabile (match per metadata[riferimento], che fase85 mette in ogni
sessione), al centesimo e per valuta. In più confronta i TOTALI del periodo
(charge/refund/transfer di Stripe vs incasso/rimborso/payout del giornale).

Segnala i FANTASMI:
  - solo_stripe:    Stripe ha incassato e il giornale non lo sa (webhook perso!);
  - solo_giornale:  il giornale dice incassato ma Stripe non ha la sessione pagata;
  - importo_diverso: stessa prenotazione, cifre diverse (al centesimo).

READ-ONLY totale (mai una scrittura, né da noi né su Stripe). GATED dalla chiave.
`fetch` iniettabile per i test; paginazione con tetto anti-runaway.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("core_auto.riconciliazione")

_MAX_PAGINE = 20          # 20 x 100 = 2000 record per giro: tetto anti-runaway onesto


def _fetch_reale(percorso: str, params: Dict[str, Any], chiave: str) -> Dict[str, Any]:
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen
    import json as _j
    url = "https://api.stripe.com/v1/" + percorso
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={"Authorization": "Bearer " + chiave})
    with urlopen(req, timeout=10) as r:
        return _j.loads(r.read().decode("utf-8"))


def _pagina(percorso: str, chiave: str, da_ts: int, fetch: Callable,
            extra: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Scarica TUTTE le pagine (tetto _MAX_PAGINE) di una lista Stripe dal ts dato."""
    out: List[Dict[str, Any]] = []
    dopo = None
    for _ in range(_MAX_PAGINE):
        params: Dict[str, Any] = {"limit": 100, "created[gte]": int(da_ts)}
        if extra:
            params.update(extra)
        if dopo:
            params["starting_after"] = dopo
        blocco = fetch(percorso, params, chiave)
        dati = blocco.get("data") or []
        out.extend(dati)
        if not blocco.get("has_more") or not dati:
            return out
        dopo = dati[-1].get("id")
    logger.warning("riconciliazione: tetto pagine raggiunto su %s (%d record: "
                   "risultato PARZIALE, indicato nel report)", percorso, len(out))
    return out


def stripe_sessioni_pagate(chiave: str, da_ts: int, *, fetch: Any = None
                           ) -> List[Dict[str, Any]]:
    """Le checkout session PAGATE del periodo: [{riferimento, cents, valuta, id}].
    Le non pagate (link creati e abbandonati) NON sono incassi: filtrate."""
    f = fetch or _fetch_reale
    out = []
    for s in _pagina("checkout/sessions", chiave, da_ts, f):
        if s.get("payment_status") != "paid":
            continue
        rif = ((s.get("metadata") or {}).get("riferimento") or "").strip()
        out.append({"riferimento": rif, "cents": int(s.get("amount_total") or 0),
                    "valuta": str(s.get("currency") or "").upper(),
                    "id": s.get("id", "")})
    return out


def stripe_somme_balance(chiave: str, da_ts: int, *, fetch: Any = None
                         ) -> Dict[str, Dict[str, int]]:
    """Somme delle balance transaction per categoria e valuta:
    {'charge': {'EUR': cents}, 'refund': {...}, 'transfer': {...}}.
    refund/transfer arrivano NEGATIVI da Stripe: qui in valore assoluto."""
    f = fetch or _fetch_reale
    out: Dict[str, Dict[str, int]] = {}
    for t in _pagina("balance_transactions", chiave, da_ts, f):
        cat = str(t.get("reporting_category") or t.get("type") or "")
        val = str(t.get("currency") or "").upper()
        out.setdefault(cat, {})
        out[cat][val] = out[cat].get(val, 0) + abs(int(t.get("amount") or 0))
    return out


def riconcilia(fc: Any, chiave: str, *, giorni: int = 30, fetch: Any = None,
               ora: Any = None) -> Dict[str, Any]:
    """Il confronto completo. Ritorna il report col verdetto:
    ok = nessun fantasma e delta zero sui totali confrontabili."""
    adesso = int((ora or time.time)())
    g = giorni if isinstance(giorni, int) and 0 < giorni <= 365 else 30
    da_ts = adesso - g * 86400
    sessioni = stripe_sessioni_pagate(chiave, da_ts, fetch=fetch)
    balance = stripe_somme_balance(chiave, da_ts, fetch=fetch)
    incassi = fc.incassi_periodo(da_ts) if fc is not None else {}
    somme = fc.somme_periodo(da_ts) if fc is not None else {}
    # ── match per riferimento (al centesimo) ─────────────────────────────────
    solo_stripe: List[Dict[str, Any]] = []
    importo_diverso: List[Dict[str, Any]] = []
    visti = set()
    for s in sessioni:
        rif = s["riferimento"]
        if not rif:
            solo_stripe.append({**s, "nota": "sessione senza riferimento nei metadata"})
            continue
        visti.add(rif)
        nostro = incassi.get(rif)
        if nostro is None:
            solo_stripe.append(s)                    # Stripe incassato, giornale MUTO
        elif (nostro["cents"] != s["cents"]
              or nostro["valuta"].upper() != s["valuta"]):
            importo_diverso.append({"riferimento": rif, "stripe_cents": s["cents"],
                                    "giornale_cents": nostro["cents"],
                                    "valuta_stripe": s["valuta"],
                                    "valuta_giornale": nostro["valuta"]})
    solo_giornale = [{"riferimento": r, **v} for r, v in sorted(incassi.items())
                     if r not in visti]
    # ── totali per categoria e valuta ────────────────────────────────────────
    def _tot(cat_stripe: str, tipi_giornale: List[str]) -> Dict[str, Any]:
        s_tot = dict(balance.get(cat_stripe, {}))
        g_tot: Dict[str, int] = {}
        for t in tipi_giornale:
            for val, c in (somme.get(t) or {}).items():
                g_tot[val.upper()] = g_tot.get(val.upper(), 0) + int(c)
        valute = sorted(set(s_tot) | set(g_tot))
        return {"stripe": s_tot, "giornale": g_tot,
                "delta": {v: s_tot.get(v, 0) - g_tot.get(v, 0) for v in valute}}
    confronti = {"incassi": _tot("charge", ["incasso"]),
                 "rimborsi": _tot("refund", ["rimborso"]),
                 "transfer": _tot("transfer", ["payout_host"])}
    fantasmi = len(solo_stripe) + len(solo_giornale) + len(importo_diverso)
    ok = (fantasmi == 0
          and all(d == 0 for c in confronti.values() for d in c["delta"].values()))
    return {"ok": ok, "giorni": g, "da_ts": da_ts,
            "sessioni_pagate": len(sessioni),
            "incassi_giornale": len(incassi),
            "solo_stripe": solo_stripe[:50],
            "solo_giornale": solo_giornale[:50],
            "importo_diverso": importo_diverso[:50],
            "confronti": confronti}
