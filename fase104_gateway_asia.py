"""
CORE_AUTO - Fase 104: Gateway Asia (Alipay + WeChat Pay) + adattatore Weibo.

Aggancia Alipay e WeChat Pay allo split 10% di Stripe Connect (fase101): stessa destination
charge (90% al conto host) + application_fee (nostra 10%), cambia solo il payment_method.
GATED da STRIPE_SECRET_KEY. Weibo = CanalePubblicazione (fase90) gated da access_token.
`fetch` iniettabile → test senza rete. ISOLATO: errore → None/False.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
from typing import Any, Callable, Dict, Optional

from fase101_stripe_connect import STRIPE_URL, costruisci_params
from fase90_marketing import CanalePubblicazione, Post

logger = logging.getLogger("core_auto.gateway_asia")

METODI = ("alipay", "wechat_pay", "card")
WEIBO_URL = "https://api.weibo.com/2/statuses/share.json"


def costruisci_params_asia(prezzo_guest_cents: int, application_fee_cents: int,
                           host_account: str, metodo: str, *, valuta: str = "cny",
                           riferimento: str = "", success_url: str = "",
                           cancel_url: str = "") -> Optional[Dict[str, str]]:
    if metodo not in METODI:
        return None
    p = costruisci_params(prezzo_guest_cents, application_fee_cents, host_account,
                          valuta=valuta, riferimento=riferimento,
                          success_url=success_url, cancel_url=cancel_url)
    if p is None:
        return None
    p["payment_method_types[0]"] = metodo
    if metodo == "wechat_pay":
        p["payment_method_options[wechat_pay][client]"] = "web"
    return p


class ProviderAsia:
    """Checkout Stripe con Alipay/WeChat Pay + split-all'origine (fase101)."""

    def __init__(self, secret_key: str, *, success_url: str = "", cancel_url: str = "",
                 valuta: str = "cny",
                 fetch: Optional[Callable[[str, bytes, Dict[str, str]], Dict[str, Any]]]
                 = None) -> None:
        self._key = secret_key or ""
        self._ok = success_url
        self._ko = cancel_url
        self._valuta = (valuta or "cny").lower()
        self._fetch = fetch or self._fetch_reale

    def crea_link(self, dati: Dict[str, Any]) -> Optional[str]:
        try:
            if not self._key or not isinstance(dati, dict):
                return None
            params = costruisci_params_asia(
                dati.get("prezzo_guest_cents"), dati.get("commissione_cents"),
                str(dati.get("host_account", "")), str(dati.get("metodo", "alipay")),
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
            logger.warning("ProviderAsia.crea_link fallita (ISOLATA)", exc_info=True)
            return None

    def _fetch_reale(self, url: str, body: bytes,
                     headers: Dict[str, str]) -> Dict[str, Any]:  # pragma: no cover
        import urllib.request
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())


class CanaleWeibo(CanalePubblicazione):
    """Pubblica sul NOSTRO account Weibo. GATED da access_token. fetch iniettabile."""
    nome = "weibo"

    def __init__(self, access_token: str, *,
                 fetch: Optional[Callable[..., Dict[str, Any]]] = None) -> None:
        self._tok = access_token or ""
        self._fetch = fetch or self._fetch_reale

    def pubblica(self, post: Post) -> bool:
        if not (self._tok and isinstance(post, Post)):
            return False
        try:
            testo = post.testo + ("\n" + " ".join(post.hashtag) if post.hashtag else "")
            r = self._fetch(WEIBO_URL, {"access_token": self._tok, "status": testo[:280]})
            return bool(isinstance(r, dict) and (r.get("id") or r.get("idstr")))
        except Exception:
            logger.warning("Weibo pubblica fallita (ISOLATA)", exc_info=True)
            return False

    def _fetch_reale(self, url: str, data: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover
        import urllib.request
        body = urllib.parse.urlencode(data).encode()
        with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=15) as r:
            return json.loads(r.read())


def crea_provider_asia_da_env(env: Optional[Dict[str, str]] = None, *,
                              fetch: Any = None) -> Optional[ProviderAsia]:
    import os
    e = env if env is not None else os.environ
    key = e.get("STRIPE_SECRET_KEY")
    if not key:
        return None
    return ProviderAsia(key, success_url=e.get("STRIPE_SUCCESS_URL", ""),
                        cancel_url=e.get("STRIPE_CANCEL_URL", ""),
                        valuta=e.get("VALUTA_ASIA", "cny"), fetch=fetch)


def crea_canale_weibo_da_env(env: Optional[Dict[str, str]] = None, *,
                             fetch: Any = None) -> Optional[CanaleWeibo]:
    import os
    e = env if env is not None else os.environ
    if not e.get("WEIBO_ACCESS_TOKEN"):
        return None
    return CanaleWeibo(e["WEIBO_ACCESS_TOKEN"], fetch=fetch)
