"""
CORE_AUTO - Fase 195: Canale REDDIT (adapter di pubblicazione, gated da .env). GRATUITO.

Reddit permette di pubblicare via API GRATIS con una "script app": si ottiene un access_token
(POST /api/v1/access_token, Basic auth client_id:secret + grant_type=password) e si invia un post
a un subreddit (POST /api/submit, kind=link, sr, title, url). GATED: senza le 5 credenziali ->
niente pubblicazione. Reddit RICHIEDE un User-Agent descrittivo (altrimenti 429). `fetch`
iniettabile -> test senza rete. BLINDATO: qualunque errore -> False.

NB pratico: pubblicare SOLO in subreddit dove l'autopromozione e' consentita (regole del sub),
altrimenti si rischia il ban. Il subreddit va scelto con cura in REDDIT_SUBREDDIT.
"""
from __future__ import annotations

import base64
import json
import logging
import urllib.parse
from typing import Any, Callable, Dict, Optional

from fase90_marketing import CanalePubblicazione, Post

logger = logging.getLogger("core_auto.canale_reddit")

UA = "web:bookinvip:1.0 (by /u/bookinvip)"


def _fetch_reale(url: str, data: Dict[str, Any],
                 headers: Dict[str, str]) -> Dict[str, Any]:  # pragma: no cover
    """POST form-urlencoded (Reddit non usa JSON). Ritorna il JSON di risposta."""
    import urllib.request
    body = urllib.parse.urlencode(data).encode("utf-8")
    h = dict(headers)
    h.setdefault("Content-Type", "application/x-www-form-urlencoded")
    h.setdefault("User-Agent", UA)
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


class CanaleReddit(CanalePubblicazione):
    """Reddit via API (access_token -> submit). GRATIS. GATED dalle credenziali script-app."""
    nome = "reddit"

    def __init__(self, client_id: str, client_secret: str, username: str, password: str,
                 subreddit: str, *,
                 fetch: Optional[Callable[..., Dict[str, Any]]] = None) -> None:
        self._cid = client_id or ""
        self._csec = client_secret or ""
        self._user = username or ""
        self._pw = password or ""
        self._sr = (subreddit or "").lstrip("r/").strip("/")
        self._fetch = fetch or _fetch_reale

    def _configurato(self) -> bool:
        return all((self._cid, self._csec, self._user, self._pw, self._sr))

    def _token(self) -> Optional[str]:
        basic = base64.b64encode(("%s:%s" % (self._cid, self._csec)).encode()).decode()
        r = self._fetch("https://www.reddit.com/api/v1/access_token",
                        {"grant_type": "password", "username": self._user, "password": self._pw},
                        {"Authorization": "Basic " + basic, "User-Agent": UA})
        return r.get("access_token") if isinstance(r, dict) else None

    def pubblica(self, post: Post) -> bool:
        if not (self._configurato() and isinstance(post, Post) and post.link):
            return False
        try:
            tok = self._token()
            if not tok:
                return False
            titolo = (post.testo.splitlines()[0] if post.testo else "BookinVIP")[:300]
            r = self._fetch("https://oauth.reddit.com/api/submit",
                            {"sr": self._sr, "kind": "link", "title": titolo,
                             "url": post.link, "resubmit": "true", "api_type": "json"},
                            {"Authorization": "Bearer " + tok, "User-Agent": UA})
            if not isinstance(r, dict):
                return False
            errs = (((r.get("json") or {}).get("errors")) or [])
            return not errs                               # nessun errore = pubblicato
        except Exception:
            logger.warning("Reddit pubblica fallita (ISOLATA)", exc_info=True)
            return False


def crea_canale_reddit_da_env(env: Optional[Dict[str, str]] = None, *,
                              fetch: Any = None) -> Optional[CanaleReddit]:
    import os
    e = env if env is not None else os.environ
    ch = ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USERNAME",
          "REDDIT_PASSWORD", "REDDIT_SUBREDDIT")
    if not all(e.get(k) for k in ch):
        return None
    return CanaleReddit(e["REDDIT_CLIENT_ID"], e["REDDIT_CLIENT_SECRET"],
                        e["REDDIT_USERNAME"], e["REDDIT_PASSWORD"],
                        e["REDDIT_SUBREDDIT"], fetch=fetch)
