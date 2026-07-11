"""
CORE_AUTO - Fase 101: Stripe Connect split-all'origine (Modulo 3 - tutela forfettario).

Lo split avviene NEL gateway al checkout: il 90% (netto host) va DIRETTO al conto connesso
dell'host (destination charge), solo la nostra commissione (application_fee) resta a noi →
legalmente solo il 10% è nostro fatturato (intermediario puro, soglia 85k tutelata).
ZERO dipendenze (REST via urllib stdlib). GATED da STRIPE_SECRET_KEY + host_account.
`fetch` iniettabile → test senza rete. ISOLATO: errore → None, mai solleva.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("core_auto.stripe_connect")

STRIPE_URL = "https://api.stripe.com/v1/checkout/sessions"


def _intero_pos(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def costruisci_params(prezzo_guest_cents: int, application_fee_cents: int,
                      host_account: str, *, valuta: str = "eur",
                      riferimento: str = "", success_url: str = "",
                      cancel_url: str = "") -> Optional[Dict[str, str]]:
    """Params Checkout con destination charge: il lordo va al conto host, l'application_fee
    (nostra commissione) resta a noi. None se importi invalidi o fee >= lordo."""
    if not (_intero_pos(prezzo_guest_cents) and host_account):
        return None
    fee = application_fee_cents if isinstance(application_fee_cents, int) and \
        not isinstance(application_fee_cents, bool) else -1
    if fee < 0 or fee >= prezzo_guest_cents:
        return None
    return {
        "mode": "payment",
        "success_url": success_url or "https://bookinvip.com/grazie",
        "cancel_url": cancel_url or "https://bookinvip.com/annullato",
        "line_items[0][price_data][currency]": (valuta or "eur").lower(),
        "line_items[0][price_data][product_data][name]": "BookinVIP %s" % (riferimento or ""),
        "line_items[0][price_data][unit_amount]": str(prezzo_guest_cents),
        "line_items[0][quantity]": "1",
        "payment_intent_data[application_fee_amount]": str(fee),
        "payment_intent_data[transfer_data][destination]": str(host_account),
        "client_reference_id": str(riferimento or ""),
    }


class ProviderStripeConnect:
    """Crea una Checkout Session con split-all'origine verso il conto connesso dell'host."""

    def __init__(self, secret_key: str, *, success_url: str = "", cancel_url: str = "",
                 valuta: str = "eur",
                 fetch: Optional[Callable[[str, bytes, Dict[str, str]], Dict[str, Any]]]
                 = None) -> None:
        self._key = secret_key or ""
        self._ok = success_url
        self._ko = cancel_url
        self._valuta = (valuta or "eur").lower()
        self._fetch = fetch or self._fetch_reale

    def crea_link(self, dati: Dict[str, Any]) -> Optional[str]:
        """dati: prezzo_guest_cents, commissione_cents, host_account, riferimento, valuta."""
        try:
            if not self._key or not isinstance(dati, dict):
                return None
            params = costruisci_params(
                dati.get("prezzo_guest_cents"), dati.get("commissione_cents"),
                str(dati.get("host_account", "")),
                valuta=dati.get("valuta", self._valuta),
                riferimento=str(dati.get("riferimento", "")),
                success_url=self._ok, cancel_url=self._ko)
            if params is None:
                return None
            body = urllib.parse.urlencode(params).encode()
            headers = {"Authorization": "Bearer " + self._key,
                       "Content-Type": "application/x-www-form-urlencoded"}
            r = self._fetch(STRIPE_URL, body, headers)
            return r.get("url") if isinstance(r, dict) else None
        except Exception:
            logger.warning("StripeConnect.crea_link fallita (ISOLATA)", exc_info=True)
            return None

    def _fetch_reale(self, url: str, body: bytes,
                     headers: Dict[str, str]) -> Dict[str, Any]:  # pragma: no cover
        import urllib.request
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())


def crea_provider_stripe_connect(secret_key: Optional[str], *, success_url: str = "",
                                 cancel_url: str = "", valuta: str = "eur",
                                 fetch: Any = None) -> Optional[ProviderStripeConnect]:
    if not secret_key:
        return None
    return ProviderStripeConnect(secret_key, success_url=success_url,
                                 cancel_url=cancel_url, valuta=valuta, fetch=fetch)
