"""
CORE_AUTO - Fase 93: Canale TikTok (adapter di pubblicazione, gated da .env).

Pubblica sul NOSTRO account TikTok via Content Posting API. TikTok è VIDEO-first:
`pubblica` da solo (senza video) ritorna False; serve `pubblica_video(post, video_url)`.
GATED dall'access_token. `fetch` iniettabile -> test senza rete. BLINDATO: errore -> False.

⚠️ Serve l'app TikTok for Developers + Content Posting API con AUDIT/approvazione. È
video-first (niente video = niente post). Le credenziali vivono SOLO nel .env del server.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, Optional

from fase90_marketing import CanalePubblicazione, Post

logger = logging.getLogger("core_auto.canale_tiktok")

URL_INIT = "https://open.tiktokapis.com/v2/post/publish/video/init/"


def _fetch_reale(url: str, data: Dict[str, Any],
                 headers: Dict[str, str]) -> Dict[str, Any]:  # pragma: no cover
    import urllib.request
    h = dict(headers)
    h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"),
                                 headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


class CanaleTikTok(CanalePubblicazione):
    """TikTok via Content Posting API. GATED dall'access_token. Video-first."""
    nome = "tiktok"

    def __init__(self, access_token: str, *,
                 fetch: Optional[Callable[..., Dict[str, Any]]] = None) -> None:
        self._tok = access_token or ""
        self._fetch = fetch or _fetch_reale

    def pubblica(self, post: Post) -> bool:
        """TikTok è video-first: senza un video non si pubblica."""
        logger.info("TikTok: pubblica() richiede un video -> usa pubblica_video()")
        return False

    def pubblica_video(self, post: Post, video_url: str) -> bool:
        if not (self._tok and video_url and isinstance(post, Post)):
            return False
        try:
            headers = {"Authorization": "Bearer " + self._tok}
            payload = {
                "post_info": {"title": post.testo[:150],
                              "privacy_level": "PUBLIC_TO_EVERYONE"},
                "source_info": {"source": "PULL_FROM_URL", "video_url": video_url},
            }
            r = self._fetch(URL_INIT, payload, headers)
            return bool(isinstance(r, dict) and r.get("data", {}).get("publish_id"))
        except Exception:
            logger.warning("TikTok pubblica fallita (ISOLATA)", exc_info=True)
            return False


def crea_canale_tiktok_da_env(env: Optional[Dict[str, str]] = None, *,
                              fetch: Any = None) -> Optional[CanaleTikTok]:
    import os
    e = env if env is not None else os.environ
    if not e.get("TIKTOK_ACCESS_TOKEN"):
        return None
    return CanaleTikTok(e["TIKTOK_ACCESS_TOKEN"], fetch=fetch)
