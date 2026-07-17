"""
CORE_AUTO - Fase 169: IndexNow — notifica ISTANTANEA multi-motore dei cambi di URL.

IndexNow (indexnow.org) è supportato da Bing, Yandex, Seznam, Naver: un SINGOLO ping li avvisa
tutti. Serve alla strategia "Google non è il mondo": quando una landing/annuncio cambia, i motori
NON-Google lo scoprono SUBITO (non aspettano il prossimo ricrawl). Google non usa IndexNow, ma lì
la sitemap-index + <lastmod> copre lo stesso bisogno.

DUE STRATI:
  - PURO e testabile (nessun I/O): payload_indexnow(), key_file_body(), urls_valide().
  - I/O GATED: IndexNow.submit() è attivo SOLO con la chiave (env INDEXNOW_KEY). Default DISATTIVO,
    BLINDATO (mai solleva: un errore di rete non deve rompere il flusso chiamante), come gli
    adapter social e il money-path. Senza chiave: no-op che ritorna {'inviato': False}.

Verifica di proprietà: il motore scarica https://HOST/CHIAVE.txt e controlla che contenga la
chiave (key_file_body). Fino a 10.000 URL per invio, tutti dello STESSO host.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Sequence
from urllib.parse import urlsplit

logger = logging.getLogger("core_auto.indexnow")

INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
MAX_URL_BATCH = 10000


def _host_di(url: Any) -> Optional[str]:
    """Host di un URL http(s), o None."""
    if not isinstance(url, str):
        return None
    try:
        p = urlsplit(url.strip())
    except Exception:
        return None
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    return p.netloc.lower()


def urls_valide(urls: Sequence[str], host: str) -> List[str]:
    """Filtra: solo URL http(s) dello STESSO host, dedup (ordine preservato), cap MAX_URL_BATCH."""
    h = (host or "").lower()
    out: List[str] = []
    visti = set()
    for u in (urls or ()):
        if not isinstance(u, str):
            continue
        u = u.strip()
        if _host_di(u) != h or not h:
            continue                          # host diverso o mancante → scartato (regola IndexNow)
        if u in visti:
            continue
        visti.add(u)
        out.append(u)
        if len(out) >= MAX_URL_BATCH:
            break
    return out


def payload_indexnow(host: str, key: str, urls: Sequence[str], *,
                     key_location: Optional[str] = None) -> Dict[str, Any]:
    """Corpo JSON del POST IndexNow: {host, key, keyLocation?, urlList}. Gli URL sono già filtrati
    allo stesso host e cappati a 10.000."""
    corpo: Dict[str, Any] = {"host": host, "key": key,
                             "urlList": urls_valide(urls, host)}
    if key_location:
        corpo["keyLocation"] = key_location
    return corpo


def key_file_body(key: Any) -> str:
    """Contenuto del file di verifica /CHIAVE.txt = la chiave stessa (una riga)."""
    return str(key or "").strip()


def _post_reale(url: str, body: bytes, headers: Dict[str, str]) -> int:
    import urllib.request
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:   # nosec: endpoint fisso indexnow.org
        return int(getattr(r, "status", 0) or 0)


class IndexNow:
    """Adapter GATED. `fetch` iniettabile (per i test); None = POST reale via urllib."""

    def __init__(self, key: Optional[str], host: Optional[str], *,
                 key_location: Optional[str] = None,
                 endpoint: str = INDEXNOW_ENDPOINT,
                 fetch: Optional[Callable[[str, bytes, Dict[str, str]], int]] = None) -> None:
        self._key = (key or "").strip() or None
        self._host = (host or "").strip().lower() or None
        self._key_location = key_location or (
            "https://%s/%s.txt" % (self._host, self._key) if self._key and self._host else None)
        self._endpoint = endpoint
        self._fetch = fetch

    @property
    def attivo(self) -> bool:
        return bool(self._key and self._host)

    def submit(self, urls: Sequence[str]) -> Dict[str, Any]:
        """Invia gli URL a IndexNow. BLINDATO: senza chiave o su errore → {'inviato': False,...}."""
        if not self.attivo:
            return {"inviato": False, "motivo": "disattivo"}
        buoni = urls_valide(urls, self._host)
        if not buoni:
            return {"inviato": False, "motivo": "nessun_url_valido"}
        corpo = payload_indexnow(self._host, self._key, buoni,
                                 key_location=self._key_location)
        try:
            fetch = self._fetch or _post_reale
            stato = fetch(self._endpoint,
                          json.dumps(corpo).encode("utf-8"),
                          {"Content-Type": "application/json; charset=utf-8",
                           # senza User-Agent api.indexnow.org risponde 403 (stessa
                           # classe del 403 Cloudflare di Groq in fase165)
                           "User-Agent": "Mozilla/5.0 (compatible; BookinVIP-IndexNow/1.0)"})
            return {"inviato": True, "url": len(buoni), "stato": stato}
        except Exception:
            logger.warning("IndexNow submit fallita (ISOLATA)", exc_info=True)
            return {"inviato": False, "motivo": "errore_rete"}


def crea_indexnow(env: Optional[Dict[str, str]] = None) -> IndexNow:
    """Factory da ambiente: INDEXNOW_KEY (obbligatoria per attivare) + INDEXNOW_HOST. Default OFF."""
    if env is None:
        import os
        env = os.environ
    return IndexNow(env.get("INDEXNOW_KEY"), env.get("INDEXNOW_HOST"))
