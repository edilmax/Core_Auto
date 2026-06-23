"""
CORE_AUTO - Fase 92: Canale X/Twitter (adapter di pubblicazione, gated da .env).

Pubblica i NOSTRI post promozionali sul NOSTRO account X via API v2 (POST /2/tweets),
firma OAuth 1.0a User Context in stdlib (hmac-sha1). GATED: senza le 4 credenziali ->
nessuna pubblicazione. `fetch` iniettabile -> test senza rete. BLINDATO: errore -> False.

⚠️ L'API di SCRITTURA di X è A PAGAMENTO (tier Basic ~$100/mese; free tier scrive
pochissimo). Le credenziali vivono SOLO nel .env del server, mai nel codice.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
import urllib.parse
from typing import Any, Callable, Dict, Optional

from fase90_marketing import CanalePubblicazione, Post

logger = logging.getLogger("core_auto.canale_x")

URL_TWEET = "https://api.twitter.com/2/tweets"


def _fetch_reale(url: str, data: Dict[str, Any],
                 headers: Dict[str, str]) -> Dict[str, Any]:  # pragma: no cover
    import urllib.request
    body = json.dumps(data).encode("utf-8")
    h = dict(headers)
    h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _q(s: str) -> str:
    return urllib.parse.quote(str(s), safe="")


class CanaleX(CanalePubblicazione):
    """X/Twitter via API v2 + OAuth 1.0a. GATED dalle credenziali."""
    nome = "x"

    def __init__(self, api_key: str, api_secret: str, access_token: str,
                 access_secret: str, *,
                 fetch: Optional[Callable[..., Dict[str, Any]]] = None) -> None:
        self._ck = api_key or ""
        self._cs = api_secret or ""
        self._tok = access_token or ""
        self._ts = access_secret or ""
        self._fetch = fetch or _fetch_reale

    def _configurato(self) -> bool:
        return all((self._ck, self._cs, self._tok, self._ts))

    def _oauth_header(self, method: str, url: str) -> str:
        oauth = {
            "oauth_consumer_key": self._ck,
            "oauth_nonce": secrets.token_hex(16),
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(int(time.time())),
            "oauth_token": self._tok,
            "oauth_version": "1.0",
        }
        param = "&".join("%s=%s" % (_q(k), _q(oauth[k])) for k in sorted(oauth))
        base = "&".join((method.upper(), _q(url), _q(param)))
        key = _q(self._cs) + "&" + _q(self._ts)
        firma = base64.b64encode(
            hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
        oauth["oauth_signature"] = firma
        return "OAuth " + ", ".join('%s="%s"' % (_q(k), _q(v))
                                    for k, v in sorted(oauth.items()))

    def pubblica(self, post: Post) -> bool:
        if not (self._configurato() and isinstance(post, Post)):
            return False
        try:
            testo = post.testo[:280]                       # X limita a 280 caratteri
            headers = {"Authorization": self._oauth_header("POST", URL_TWEET)}
            r = self._fetch(URL_TWEET, {"text": testo}, headers)
            return bool(isinstance(r, dict) and r.get("data", {}).get("id"))
        except Exception:
            logger.warning("X pubblica fallita (ISOLATA)", exc_info=True)
            return False


def crea_canale_x_da_env(env: Optional[Dict[str, str]] = None, *,
                         fetch: Any = None) -> Optional[CanaleX]:
    import os
    e = env if env is not None else os.environ
    if not all(e.get(k) for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN",
                                  "X_ACCESS_SECRET")):
        return None
    return CanaleX(e["X_API_KEY"], e["X_API_SECRET"], e["X_ACCESS_TOKEN"],
                   e["X_ACCESS_SECRET"], fetch=fetch)
