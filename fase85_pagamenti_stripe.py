"""
CORE_AUTO - Fase 85: Provider Pagamento Stripe (l'ultimo pezzo del money-path).

Finora la prenotazione (concierge fase59) conferma e blocca l'inventario, ma NON incassa:
il `link_pagamento` era un'astrazione iniettabile mai cablata. Questo modulo la riempie
con Stripe Checkout, a ZERO dipendenze (chiamata REST via urllib stdlib - niente libreria
`stripe`). E' GATED dalla chiave: se la chiave non c'e', il sistema si comporta come ora
(nessun link); appena metti STRIPE_SECRET_KEY, ogni prenotazione produce un link di
pagamento reale - SENZA toccare il codice.

Il prezzo arriva GIA' firmato dal CORE (fase59, mai dall'IA) e qui viene solo passato a
Stripe in CENTESIMI interi (unit_amount). Riferimento e email viaggiano nei metadata per
la riconciliazione. La chiamata e' ISOLATA: se Stripe e' giu', `crea_link` ritorna None e
la prenotazione resta valida (il link si rigenera) - non si propaga mai un errore.

VINCITRICE DEL BENCHMARK (4 modi di cablare i pagamenti):
  V3 'provider iniettato gated da env + chiamata REST stdlib isolata'. Zero dipendenze,
  accensione senza modifiche, fail-safe. Le altre perdono: V1 'libreria stripe' = una
  dipendenza in piu' (contro "zero spese/dipendenze"); V2 'hardcode la chiave' = segreto
  nel codice; V4 'redirect lato client' = il prezzo passerebbe dal browser (manomettibile).

SOPRAVVIVENZA TOTALE: `crea_link` non solleva MAI (eccezione -> None); cents non validi ->
None; `fetch` iniettabile (test deterministici senza chiamare Stripe davvero); nessuna
chiave -> provider non creato. Denaro in centesimi interi.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("core_auto.pagamenti_stripe")

STRIPE_URL = "https://api.stripe.com/v1/checkout/sessions"


def _intero_pos(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


class ProviderStripe:
    """Crea una Checkout Session Stripe. `fetch(url, body_bytes, headers) -> dict` e'
    iniettabile (default: urllib reale) per testare senza chiamare Stripe."""

    def __init__(self, secret_key: str, success_url: str, cancel_url: str, *,
                 valuta: str = "eur",
                 fetch: Optional[Callable[[str, bytes, Dict[str, str]], Dict[str, Any]]]
                 = None) -> None:
        self._key = secret_key
        self._ok = success_url
        self._ko = cancel_url
        self._valuta = (valuta or "eur").lower()
        self._fetch = fetch or self._fetch_reale

    def crea_link(self, dati: Dict[str, Any]) -> Optional[str]:
        """Da un dict prenotazione (prezzo_guest_cents, riferimento, email) -> URL di
        pagamento Stripe, o None (chiave/cents invalidi o Stripe non raggiungibile)."""
        try:
            if not isinstance(dati, dict):
                return None
            # addebita il TOTALE (soggiorno + tassa di soggiorno); fallback al solo soggiorno
            cents = dati.get("totale_cents")
            if not _intero_pos(cents):
                cents = dati.get("prezzo_guest_cents")
            if not _intero_pos(cents):
                return None
            ref = str(dati.get("riferimento", ""))
            params: List[Tuple[str, str]] = [
                ("mode", "payment"),
                ("success_url", self._ok or "https://bookinvip.com/ok"),
                ("cancel_url", self._ko or "https://bookinvip.com/ko"),
                ("line_items[0][quantity]", "1"),
                ("line_items[0][price_data][currency]", self._valuta),
                ("line_items[0][price_data][unit_amount]", str(cents)),
                ("line_items[0][price_data][product_data][name]",
                 "BookinVIP " + (ref or "prenotazione")),
                ("client_reference_id", ref),
                ("metadata[riferimento]", ref),
            ]
            email = dati.get("email")
            if isinstance(email, str) and "@" in email:
                params.append(("customer_email", email))
            from urllib.parse import urlencode
            body = urlencode(params).encode("utf-8")
            headers = {"Authorization": "Bearer " + self._key,
                       "Content-Type": "application/x-www-form-urlencoded"}
            resp = self._fetch(STRIPE_URL, body, headers)
            url = resp.get("url") if isinstance(resp, dict) else None
            return url if isinstance(url, str) and url else None
        except Exception:
            logger.warning("Stripe: creazione link fallita (ISOLATA -> None)",
                           exc_info=True)
            return None

    @staticmethod
    def _fetch_reale(url: str, body: bytes,
                     headers: Dict[str, str]) -> Dict[str, Any]:  # pragma: no cover
        import urllib.request
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())


def crea_provider_stripe(secret_key: Optional[str], success_url: str = "",
                         cancel_url: str = "", *, valuta: str = "eur",
                         fetch: Any = None) -> Optional[ProviderStripe]:
    """Factory GATED: ritorna un provider solo se c'e' una chiave; altrimenti None
    (il sistema resta senza link di pagamento, come oggi)."""
    if not (isinstance(secret_key, str) and secret_key.strip()):
        return None
    return ProviderStripe(secret_key.strip(), success_url, cancel_url, valuta=valuta,
                          fetch=fetch)
