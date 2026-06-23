"""
CORE_AUTO - Fase 91: Canali social reali (adapter di pubblicazione, gated da .env).

Implementazioni concrete di `CanalePubblicazione` (fase90) sulle API UFFICIALI: pubblicano
i NOSTRI contenuti promozionali sui NOSTRI account/pagine (social media management lecito,
non scraping, non engagement falso).

CONFINI:
  - Credenziali SOLO da ambiente/costruttore: MAI hardcoded. Senza credenziali -> il canale
    è 'spento' (pubblica -> False), come Stripe/email.
  - `fetch` iniettabile -> test deterministici senza rete.
  - Telegram = GRATIS (Bot API). Meta (FB/IG) = API gratis ma richiede setup/app-review;
    IG richiede l'immagine a un URL pubblico (passato come image_url).
  - Niente solleva: errore -> False, isolato.

ENV attese (esempi): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID; META_PAGE_ID, META_PAGE_TOKEN,
META_IG_USER_ID. (I segreti vivono nel .env del server, non nel codice.)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, Optional

from fase90_marketing import CanalePubblicazione, Post

logger = logging.getLogger("core_auto.canali_social")

GRAPH = "https://graph.facebook.com/v19.0"
TG = "https://api.telegram.org"


def _fetch_reale(url: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:  # pragma: no cover
    import urllib.parse
    import urllib.request
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _testo_post(post: Post) -> str:
    return post.testo + ("\n" + " ".join(post.hashtag) if post.hashtag else "")


class CanaleTelegram(CanalePubblicazione):
    """GRATIS. Pubblica su un canale/chat Telegram via Bot API."""
    nome = "telegram"

    def __init__(self, bot_token: str, chat_id: str, *,
                 fetch: Optional[Callable[..., Dict[str, Any]]] = None) -> None:
        self._token = bot_token or ""
        self._chat = chat_id or ""
        self._fetch = fetch or _fetch_reale

    def pubblica(self, post: Post) -> bool:
        if not (self._token and self._chat and isinstance(post, Post)):
            return False
        try:
            url = "%s/bot%s/sendMessage" % (TG, self._token)
            r = self._fetch(url, {"chat_id": self._chat, "text": _testo_post(post),
                                  "disable_web_page_preview": "false"})
            return bool(isinstance(r, dict) and r.get("ok"))
        except Exception:
            logger.warning("Telegram pubblica fallita (ISOLATA)", exc_info=True)
            return False


class CanaleMetaGraph(CanalePubblicazione):
    """Facebook Page + Instagram Business via Graph API. GATED da page_token.
    FB: post testo/link sul feed. IG: 2-step (container + publish), richiede image_url
    pubblico."""
    nome = "meta"

    def __init__(self, page_id: str, page_token: str, *, ig_user_id: str = "",
                 fetch: Optional[Callable[..., Dict[str, Any]]] = None) -> None:
        self._page = page_id or ""
        self._token = page_token or ""
        self._ig = ig_user_id or ""
        self._fetch = fetch or _fetch_reale

    def pubblica(self, post: Post) -> bool:
        """Default: post sul feed della Pagina Facebook (testo + link)."""
        if not (self._page and self._token and isinstance(post, Post)):
            return False
        try:
            url = "%s/%s/feed" % (GRAPH, self._page)
            r = self._fetch(url, {"message": _testo_post(post), "link": post.link,
                                  "access_token": self._token})
            return bool(isinstance(r, dict) and r.get("id"))
        except Exception:
            logger.warning("Meta FB pubblica fallita (ISOLATA)", exc_info=True)
            return False

    def pubblica_instagram(self, post: Post, image_url: str) -> bool:
        """IG Business: crea il container con l'immagine (URL pubblico) + caption, poi
        pubblica. Senza ig_user_id o image_url -> False."""
        if not (self._ig and self._token and image_url and isinstance(post, Post)):
            return False
        try:
            c = self._fetch("%s/%s/media" % (GRAPH, self._ig),
                            {"image_url": image_url, "caption": _testo_post(post),
                             "access_token": self._token})
            cid = c.get("id") if isinstance(c, dict) else None
            if not cid:
                return False
            r = self._fetch("%s/%s/media_publish" % (GRAPH, self._ig),
                            {"creation_id": cid, "access_token": self._token})
            return bool(isinstance(r, dict) and r.get("id"))
        except Exception:
            logger.warning("Meta IG pubblica fallita (ISOLATA)", exc_info=True)
            return False


def crea_canali_da_env(env: Optional[Dict[str, str]] = None, *,
                       fetch: Any = None) -> Dict[str, CanalePubblicazione]:
    """Costruisce i canali CONFIGURATI (gated). Senza credenziali -> canale assente."""
    import os
    e = env if env is not None else os.environ
    canali: Dict[str, CanalePubblicazione] = {}
    if e.get("TELEGRAM_BOT_TOKEN") and e.get("TELEGRAM_CHAT_ID"):
        canali["telegram"] = CanaleTelegram(e["TELEGRAM_BOT_TOKEN"],
                                            e["TELEGRAM_CHAT_ID"], fetch=fetch)
    if e.get("META_PAGE_ID") and e.get("META_PAGE_TOKEN"):
        canali["meta"] = CanaleMetaGraph(e["META_PAGE_ID"], e["META_PAGE_TOKEN"],
                                         ig_user_id=e.get("META_IG_USER_ID", ""),
                                         fetch=fetch)
    return canali
