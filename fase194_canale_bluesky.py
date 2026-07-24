"""
CORE_AUTO - Fase 194: Canale BLUESKY (AT Protocol, adapter di pubblicazione, gated). GRATUITO.

Bluesky e' un social aperto (AT Protocol); l'API di scrittura e' GRATIS. Due passi: si apre una
sessione (com.atproto.server.createSession con handle + APP PASSWORD generata dalle impostazioni)
-> accessJwt + did; poi si crea il post (com.atproto.repo.createRecord, collection
app.bsky.feed.post). GATED: senza BLUESKY_HANDLE + BLUESKY_APP_PASSWORD nessuna pubblicazione.
`fetch` iniettabile -> test senza rete. `orologio` iniettabile (createdAt deterministico nei test).
BLINDATO: qualunque errore -> False.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, Optional

from fase90_marketing import CanalePubblicazione, Post

logger = logging.getLogger("core_auto.canale_bluesky")

PDS = "https://bsky.social"


def _fetch_reale(url: str, data: Dict[str, Any],
                 headers: Dict[str, str]) -> Dict[str, Any]:  # pragma: no cover
    import urllib.request
    body = json.dumps(data).encode("utf-8")
    h = dict(headers)
    h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


class CanaleBluesky(CanalePubblicazione):
    """Bluesky via AT Protocol (createSession -> createRecord). GRATIS. GATED da handle+app-password."""
    nome = "bluesky"

    def __init__(self, handle: str, app_password: str, *, pds: str = PDS,
                 fetch: Optional[Callable[..., Dict[str, Any]]] = None,
                 orologio: Optional[Callable[[], str]] = None) -> None:
        self._handle = handle or ""
        self._pw = app_password or ""
        self._pds = (pds or PDS).rstrip("/")
        self._fetch = fetch or _fetch_reale
        self._now = orologio or self._ora_iso

    @staticmethod
    def _ora_iso() -> str:  # pragma: no cover
        import datetime
        return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def _configurato(self) -> bool:
        return bool(self._handle and self._pw)

    def pubblica(self, post: Post) -> bool:
        if not (self._configurato() and isinstance(post, Post)):
            return False
        try:
            sess = self._fetch(self._pds + "/xrpc/com.atproto.server.createSession",
                               {"identifier": self._handle, "password": self._pw}, {})
            jwt = sess.get("accessJwt") if isinstance(sess, dict) else None
            did = sess.get("did") if isinstance(sess, dict) else None
            if not (jwt and did):
                return False
            testo = post.testo
            if post.hashtag:
                testo = testo + "\n" + " ".join(post.hashtag)
            if post.link:
                testo = testo + "\n" + post.link
            testo = testo[:300]                            # Bluesky: 300 caratteri
            record = {"$type": "app.bsky.feed.post", "text": testo, "createdAt": self._now()}
            r = self._fetch(self._pds + "/xrpc/com.atproto.repo.createRecord",
                            {"repo": did, "collection": "app.bsky.feed.post", "record": record},
                            {"Authorization": "Bearer " + jwt})
            return bool(isinstance(r, dict) and (r.get("uri") or r.get("cid")))
        except Exception:
            logger.warning("Bluesky pubblica fallita (ISOLATA)", exc_info=True)
            return False


def crea_canale_bluesky_da_env(env: Optional[Dict[str, str]] = None, *,
                               fetch: Any = None) -> Optional[CanaleBluesky]:
    import os
    e = env if env is not None else os.environ
    if not (e.get("BLUESKY_HANDLE") and e.get("BLUESKY_APP_PASSWORD")):
        return None
    return CanaleBluesky(e["BLUESKY_HANDLE"], e["BLUESKY_APP_PASSWORD"], fetch=fetch)
