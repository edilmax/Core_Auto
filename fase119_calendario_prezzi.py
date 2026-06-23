"""
CORE_AUTO - Fase 119: Calendario prezzi visuale host.

Genera una griglia giorno-per-giorno (per un range di date) con stato + prezzo suggerito,
unendo: disponibilità/prezzo base dall'inventario (fase58, iniettato) + prezzo dinamico
(fase106) calcolato sull'occupazione e la data. Output dati (per il frontend) o HTML inline.
PURO: provider iniettato → test senza DB. BLINDATO: errore per-giorno → cella 'errore'.
"""
from __future__ import annotations

import html
import logging
from typing import Any, Callable, Dict, List, Optional

import fase106_dynamic_pricing as dyn

logger = logging.getLogger("core_auto.calendario_prezzi")


def _giorni(da: str, a: str) -> List[str]:
    try:
        from datetime import date, timedelta
        y1, m1, g1 = (int(x) for x in str(da).split("-"))
        y2, m2, g2 = (int(x) for x in str(a).split("-"))
        d0, d1 = date(y1, m1, g1), date(y2, m2, g2)
        if d1 < d0 or (d1 - d0).days > 366:
            return []
        out, cur = [], d0
        while cur <= d1:
            out.append(cur.isoformat())
            cur += timedelta(days=1)
        return out
    except Exception:
        return []


def costruisci_calendario(slug: str, da: str, a: str, *,
                          stato_giorno: Callable[[str, str], Dict[str, Any]],
                          occupazione_bps: int = 5000,
                          pol: dyn.PoliticaPrezzo = dyn.PoliticaPrezzo()
                          ) -> List[Dict[str, Any]]:
    """Per ogni giorno: stato (libero/prenotato/chiuso) + prezzo base + prezzo dinamico."""
    celle: List[Dict[str, Any]] = []
    for g in _giorni(da, a):
        try:
            st = stato_giorno(slug, g) or {}
            base = st.get("prezzo_netto_cents")
            unita = st.get("unita_totali", st.get("unita", 1))
            venduto = st.get("venduto", st.get("occupati", 0))
            if not isinstance(base, int) or base <= 0:
                celle.append({"giorno": g, "stato": "non_aperto", "prezzo_cents": None,
                              "prezzo_dinamico_cents": None})
                continue
            if isinstance(unita, int) and isinstance(venduto, int) and unita > 0:
                stato = "prenotato" if venduto >= unita else "libero"
            else:
                stato = "libero"
            din = dyn.calcola_prezzo(base, occupazione_bps=occupazione_bps, data=g, pol=pol)
            celle.append({"giorno": g, "stato": stato, "prezzo_cents": base,
                          "prezzo_dinamico_cents": din["prezzo_cents"],
                          "moltiplicatore_bps": din.get("moltiplicatore_bps", 10000)})
        except Exception:
            logger.warning("cella calendario fallita (ISOLATA)", exc_info=True)
            celle.append({"giorno": g, "stato": "errore", "prezzo_cents": None,
                          "prezzo_dinamico_cents": None})
    return celle


_COLORE = {"libero": "#d4edda", "prenotato": "#f8d7da", "chiuso": "#e2e3e5",
           "non_aperto": "#ffffff", "errore": "#fff3cd"}


def calendario_html(celle: List[Dict[str, Any]]) -> str:
    """Griglia HTML inline (XSS-safe) dal risultato di costruisci_calendario."""
    out = ['<table style="border-collapse:collapse;font-family:system-ui">']
    for c in celle:
        col = _COLORE.get(c.get("stato"), "#fff")
        pd = c.get("prezzo_dinamico_cents")
        prezzo = ("€%d.%02d" % (pd // 100, pd % 100)) if isinstance(pd, int) else "-"
        out.append('<td style="border:1px solid #ccc;padding:.4rem;background:%s">'
                   '<div>%s</div><b>%s</b></td>'
                   % (col, html.escape(str(c.get("giorno", ""))[5:]), html.escape(prezzo)))
    out.append("</table>")
    return "".join(out)
