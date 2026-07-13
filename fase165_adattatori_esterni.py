"""
CORE_AUTO - Fase 165: Adattatori esterni gated (provider AI a rotazione + upload YouTube).

Aggancia servizi esterni GRATIS (free tier) al pool a rotazione fase164 e aggiunge il canale
video YouTube. Tutto GATED (senza chiave -> assente) e con `fetch` INIETTABILE -> costruibile
e testabile SENZA rete e SENZA chiavi. La rete reale è isolata (errore -> None / QuotaEsaurita).

Provider inclusi:
  - TESTO/strategia: Groq (OpenAI-compatible, molto veloce) + Google Gemini (free tier).
  - IMMAGINI: Pollinations (SENZA chiave -> fallback sempre-attivo, ritorna un URL immagine
    pubblico usabile per IG/Facebook).
  - VIDEO/canale: YouTube Data API v3 (upload multipart; token OAuth, refresh gated).

Contratto col pool (fase164): ogni provider espone `chiama(richiesta)->risultato|None` e
solleva `QuotaEsaurita` sul 429/quota -> il pool passa al successivo. `richiesta` = stringa
(prompt) oppure dict {"prompt","sistema","max_token"}.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import quote

from fase164_pool_ai import ProviderAI, QuotaEsaurita, crea_pool_ai

logger = logging.getLogger("core_auto.adattatori_esterni")

_Fetch = Callable[..., Tuple[int, Any]]

# User-Agent "da browser": alcuni provider (Groq dietro Cloudflare) bloccano il default
# `Python-urllib` con 403/1010. Sempre presente salvo override esplicito.
_USER_AGENT = "Mozilla/5.0 (compatible; BookinVIP/1.0; +https://bookinvip.com)"


def _fetch_reale(url: str, *, metodo: str = "GET", intestazioni: Optional[Dict[str, str]] = None,
                 corpo: Optional[bytes] = None, timeout: float = 30.0) -> Tuple[int, Any]:
    """HTTP reale (stdlib). Ritorna (status, corpo): corpo = dict/list se JSON, altrimenti
    bytes. status 0 = errore di rete (nessuna risposta). Non solleva."""
    import urllib.error
    import urllib.request
    testa = dict(intestazioni or {})
    if not any(k.lower() == "user-agent" for k in testa):
        testa["User-Agent"] = _USER_AGENT      # evita il blocco Cloudflare 1010
    req = urllib.request.Request(url, data=corpo, method=metodo, headers=testa)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            status = getattr(r, "status", 200) or 200
    except urllib.error.HTTPError as e:
        try:
            raw = e.read()
        except Exception:
            raw = b""
        status = e.code
    except Exception:
        return 0, None
    try:
        return status, json.loads(raw.decode("utf-8"))
    except Exception:
        return status, raw


def _norm(richiesta: Any) -> Tuple[str, str, int]:
    """Normalizza la richiesta -> (prompt, sistema, max_token)."""
    if isinstance(richiesta, str):
        return richiesta.strip(), "", 500
    if isinstance(richiesta, dict):
        p = str(richiesta.get("prompt", "")).strip()
        s = str(richiesta.get("sistema", "")).strip()
        mt = richiesta.get("max_token", 500)
        mt = mt if isinstance(mt, int) and not isinstance(mt, bool) and mt > 0 else 500
        return p, s, mt
    return "", "", 500


# ─────────────────────────────────────────────────────────────── TESTO: Groq
class AdattatoreGroq:
    URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: str, *, modello: str = "llama-3.1-8b-instant",
                 fetch: Optional[_Fetch] = None) -> None:
        self._key = api_key or ""
        self._modello = modello or "llama-3.1-8b-instant"
        self._fetch = fetch or _fetch_reale

    def genera_testo(self, richiesta: Any) -> Optional[str]:
        prompt, sistema, maxtok = _norm(richiesta)
        if not (self._key and prompt):
            return None
        msgs = ([{"role": "system", "content": sistema}] if sistema else []) + \
               [{"role": "user", "content": prompt}]
        corpo = json.dumps({"model": self._modello, "messages": msgs,
                            "max_tokens": maxtok, "temperature": 0.7}).encode("utf-8")
        st, obj = self._fetch(self.URL, metodo="POST", corpo=corpo, intestazioni={
            "Authorization": "Bearer " + self._key, "Content-Type": "application/json"})
        if st == 429:
            raise QuotaEsaurita()
        if st != 200 or not isinstance(obj, dict):
            return None
        try:
            txt = obj["choices"][0]["message"]["content"]
            return txt.strip() or None if isinstance(txt, str) else None
        except Exception:
            return None

    def provider(self, nome: str = "groq") -> ProviderAI:
        return ProviderAI(nome=nome, chiama=self.genera_testo)


# ───────────────────────────────────────────────────────────── TESTO: Gemini
class AdattatoreGemini:
    BASE = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s"

    def __init__(self, api_key: str, *, modello: str = "gemini-1.5-flash",
                 fetch: Optional[_Fetch] = None) -> None:
        self._key = api_key or ""
        self._modello = modello or "gemini-1.5-flash"
        self._fetch = fetch or _fetch_reale

    def genera_testo(self, richiesta: Any) -> Optional[str]:
        prompt, sistema, _ = _norm(richiesta)
        if not (self._key and prompt):
            return None
        testo = (sistema + "\n\n" if sistema else "") + prompt
        corpo = json.dumps({"contents": [{"parts": [{"text": testo}]}]}).encode("utf-8")
        st, obj = self._fetch(self.BASE % (self._modello, self._key), metodo="POST",
                              corpo=corpo, intestazioni={"Content-Type": "application/json"})
        if st == 429 or (isinstance(obj, dict) and _gemini_quota(obj)):
            raise QuotaEsaurita()
        if st != 200 or not isinstance(obj, dict):
            return None
        try:
            return obj["candidates"][0]["content"]["parts"][0]["text"].strip() or None
        except Exception:
            return None

    def provider(self, nome: str = "gemini") -> ProviderAI:
        return ProviderAI(nome=nome, chiama=self.genera_testo)


def _gemini_quota(obj: Dict[str, Any]) -> bool:
    try:
        err = obj.get("error", {})
        return err.get("code") == 429 or err.get("status") == "RESOURCE_EXHAUSTED"
    except Exception:
        return False


# ─────────────────────────────────────────────────────── IMMAGINI: Pollinations
class AdattatorePollinations:
    """Immagini SENZA chiave: ritorna un URL immagine pubblico (usabile per IG/Facebook e
    scaricabile). Fallback sempre-attivo del pool immagini."""

    BASE = "https://image.pollinations.ai/prompt/"

    def __init__(self, *, larghezza: int = 1080, altezza: int = 1080,
                 fetch: Optional[_Fetch] = None) -> None:
        self._w = int(larghezza) if larghezza else 1080
        self._h = int(altezza) if altezza else 1080
        self._fetch = fetch or _fetch_reale     # non usato (URL diretto), tenuto per uniformità

    def genera_immagine(self, richiesta: Any) -> Optional[str]:
        prompt, _, _ = _norm(richiesta)
        if not prompt:
            return None
        return "%s%s?width=%d&height=%d&nologo=true" % (
            self.BASE, quote(prompt[:400]), self._w, self._h)

    def provider(self, nome: str = "pollinations") -> ProviderAI:
        return ProviderAI(nome=nome, chiama=self.genera_immagine)


# ─────────────────────────────────────────────────────────── VIDEO: YouTube
class AdattatoreYouTube:
    """Upload video su YouTube (Data API v3, multipart). GATED da token OAuth; se assente ma
    ci sono client_id+secret+refresh_token, ottiene il token da solo. Isolato: errore -> None."""

    UPLOAD = ("https://www.googleapis.com/upload/youtube/v3/videos"
              "?uploadType=multipart&part=snippet,status")
    TOKEN = "https://oauth2.googleapis.com/token"

    def __init__(self, *, access_token: str = "", client_id: str = "",
                 client_secret: str = "", refresh_token: str = "",
                 fetch: Optional[_Fetch] = None) -> None:
        self._tok = access_token or ""
        self._cid = client_id or ""
        self._csec = client_secret or ""
        self._rtok = refresh_token or ""
        self._fetch = fetch or _fetch_reale

    def _assicura_token(self) -> bool:
        if self._tok:
            return True
        if not (self._cid and self._csec and self._rtok):
            return False
        corpo = ("client_id=%s&client_secret=%s&refresh_token=%s&grant_type=refresh_token"
                 % (quote(self._cid), quote(self._csec), quote(self._rtok))).encode("utf-8")
        st, obj = self._fetch(self.TOKEN, metodo="POST", corpo=corpo,
                              intestazioni={"Content-Type": "application/x-www-form-urlencoded"})
        if st == 200 and isinstance(obj, dict) and obj.get("access_token"):
            self._tok = obj["access_token"]
            return True
        return False

    def pubblica_video(self, video: bytes, *, titolo: str, descrizione: str = "",
                       tags: Any = None, privacy: str = "public",
                       _riprova: bool = True) -> Optional[Dict[str, str]]:
        if not (isinstance(video, (bytes, bytearray)) and video and titolo):
            return None
        if not self._assicura_token():
            return None
        import secrets
        meta = {"snippet": {"title": str(titolo)[:100], "description": str(descrizione)[:5000],
                            "tags": [str(t) for t in (tags or [])][:30]},
                "status": {"privacyStatus": privacy if privacy in
                           ("public", "unlisted", "private") else "unlisted"}}
        b = "----bvip" + secrets.token_hex(8)
        bb = b.encode("utf-8")
        corpo = (b"--" + bb + b"\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
                 + json.dumps(meta).encode("utf-8") + b"\r\n"
                 + b"--" + bb + b"\r\nContent-Type: video/*\r\n\r\n"
                 + bytes(video) + b"\r\n--" + bb + b"--\r\n")
        st, obj = self._fetch(self.UPLOAD, metodo="POST", corpo=corpo, intestazioni={
            "Authorization": "Bearer " + self._tok,
            "Content-Type": "multipart/related; boundary=" + b})
        if st == 401 and _riprova and (self._cid and self._csec and self._rtok):
            self._tok = ""                      # token scaduto -> rinnova e riprova una volta
            return self.pubblica_video(video, titolo=titolo, descrizione=descrizione,
                                       tags=tags, privacy=privacy, _riprova=False)
        if st in (200, 201) and isinstance(obj, dict) and obj.get("id"):
            return {"video_id": obj["id"], "url": "https://youtu.be/" + obj["id"]}
        logger.warning("YouTube upload fallito (status %s)", st)
        return None


# ─────────────────────────────────────────────────────────── factory da env
def crea_pool_testo_da_env(env: Optional[Dict[str, str]] = None, *,
                           fetch: Optional[_Fetch] = None,
                           percorso_stato: Optional[str] = None) -> Any:
    """Pool TESTO a rotazione dai provider con chiave presente (Groq, poi Gemini)."""
    e = env if env is not None else os.environ
    provs = []
    if e.get("GROQ_API_KEY"):
        provs.append(AdattatoreGroq(e["GROQ_API_KEY"],
                                    modello=e.get("GROQ_MODELLO", "llama-3.1-8b-instant"),
                                    fetch=fetch).provider("groq"))
    if e.get("GEMINI_API_KEY"):
        provs.append(AdattatoreGemini(e["GEMINI_API_KEY"],
                                      modello=e.get("GEMINI_MODELLO", "gemini-1.5-flash"),
                                      fetch=fetch).provider("gemini"))
    return crea_pool_ai(provs, percorso_stato=percorso_stato)


def crea_pool_immagine_da_env(env: Optional[Dict[str, str]] = None, *,
                              fetch: Optional[_Fetch] = None,
                              percorso_stato: Optional[str] = None) -> Any:
    """Pool IMMAGINI: eventuali provider con chiave PRIMA, Pollinations (no chiave) come
    fallback SEMPRE-attivo in coda."""
    e = env if env is not None else os.environ
    provs = []
    # (spazio per provider immagine con chiave: Cloudflare/HF/Together -> vanno qui, PRIMA)
    provs.append(AdattatorePollinations(fetch=fetch).provider("pollinations"))
    return crea_pool_ai(provs, percorso_stato=percorso_stato)


def crea_youtube_da_env(env: Optional[Dict[str, str]] = None, *,
                        fetch: Optional[_Fetch] = None) -> Optional[AdattatoreYouTube]:
    """Canale YouTube se ci sono le credenziali (access token diretto o refresh completo)."""
    e = env if env is not None else os.environ
    tok = e.get("YT_ACCESS_TOKEN", "")
    cid, csec, rtok = (e.get("YT_CLIENT_ID", ""), e.get("YT_CLIENT_SECRET", ""),
                       e.get("YT_REFRESH_TOKEN", ""))
    if not (tok or (cid and csec and rtok)):
        return None
    return AdattatoreYouTube(access_token=tok, client_id=cid, client_secret=csec,
                             refresh_token=rtok, fetch=fetch)
