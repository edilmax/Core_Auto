"""
CORE_AUTO - Fase 193: Canale MASTODON (adapter di pubblicazione, gated da .env). GRATUITO.

Mastodon e' un social APERTO e federato: l'API di scrittura e' GRATIS (nessun tier a pagamento
come X). Si pubblica un "toot" (POST /api/v1/statuses) con un Bearer token personale generato
dalle impostazioni dell'account (Sviluppo -> Nuova applicazione -> token). GATED: senza
MASTODON_INSTANCE + MASTODON_TOKEN nessuna pubblicazione. `fetch` iniettabile -> test senza rete.
BLINDATO: qualunque errore -> False (mai rompe il giro di pubblicazione multi-canale).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, Optional

from fase90_marketing import CanalePubblicazione, Post

logger = logging.getLogger("core_auto.canale_mastodon")


def _fetch_reale(url: str, data: Dict[str, Any],
                 headers: Dict[str, str]) -> Dict[str, Any]:  # pragma: no cover
    import urllib.request
    body = json.dumps(data).encode("utf-8")
    h = dict(headers)
    h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _base(instanza: str) -> str:
    s = str(instanza or "").strip().rstrip("/")
    if s and not s.startswith("http"):
        s = "https://" + s
    return s


class CanaleMastodon(CanalePubblicazione):
    """Mastodon via API v1 (/api/v1/statuses) + Bearer token. GRATIS. GATED da istanza+token."""
    nome = "mastodon"

    def __init__(self, istanza: str, token: str, *,
                 fetch: Optional[Callable[..., Dict[str, Any]]] = None) -> None:
        self._base = _base(istanza)
        self._token = token or ""
        self._fetch = fetch or _fetch_reale

    def _configurato(self) -> bool:
        return bool(self._base and self._token)

    def pubblica(self, post: Post) -> bool:
        if not (self._configurato() and isinstance(post, Post)):
            return False
        try:
            testo = post.testo
            if post.hashtag:
                testo = testo + "\n" + " ".join(post.hashtag)
            if post.link:
                testo = testo + "\n" + post.link
            testo = testo[:500]                            # Mastodon: 500 caratteri (default)
            url = self._base + "/api/v1/statuses"
            headers = {"Authorization": "Bearer " + self._token}
            r = self._fetch(url, {"status": testo, "visibility": "public"}, headers)
            return bool(isinstance(r, dict) and r.get("id"))
        except Exception:
            logger.warning("Mastodon pubblica fallita (ISOLATA)", exc_info=True)
            return False


def crea_canale_mastodon_da_env(env: Optional[Dict[str, str]] = None, *,
                                fetch: Any = None) -> Optional[CanaleMastodon]:
    import os
    e = env if env is not None else os.environ
    if not (e.get("MASTODON_INSTANCE") and e.get("MASTODON_TOKEN")):
        return None
    return CanaleMastodon(e["MASTODON_INSTANCE"], e["MASTODON_TOKEN"], fetch=fetch)
