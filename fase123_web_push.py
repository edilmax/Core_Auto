"""
CORE_AUTO - Fase 123: Notifiche Web Push guest (Web Push API + VAPID, GATED, gratis).

Registro durevole delle subscription (endpoint+keys del browser) per guest e invio di
notifiche tramite il servizio push del browser (chiamata REST via urllib stdlib, header
VAPID). GATED dalle chiavi VAPID: senza chiavi → nessun invio. `fetch` iniettabile → test
senza rete. Store SQLite (conn-per-op + _ConnCondivisa). BLINDATO: errore → False/0/[].

Nota: la firma VAPID (ECDSA P-256) richiederebbe una libreria crypto; qui l'header di
autorizzazione è iniettabile (`firma_vapid`) per restare zero-dipendenze e testabile.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import urllib.parse
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("core_auto.web_push")


class _ConnCondivisa:
    def __init__(self, con: sqlite3.Connection) -> None:
        object.__setattr__(self, "_con", con)

    def close(self) -> None:
        pass

    def __enter__(self):
        return self._con.__enter__()

    def __exit__(self, *a):
        return self._con.__exit__(*a)

    def __getattr__(self, n):
        return getattr(self._con, n)


def _valida_sub(s: Any) -> bool:
    return (isinstance(s, dict) and isinstance(s.get("endpoint"), str)
            and s["endpoint"].startswith("https://")
            and isinstance(s.get("keys"), dict))


class WebPush:
    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], *,
                 vapid_public: str = "", firma_vapid: Optional[Callable[[str], str]] = None,
                 fetch: Optional[Callable[..., int]] = None,
                 orologio: Optional[Callable[[], int]] = None) -> None:
        self._cf = conn_factory
        self._vapid = vapid_public or ""
        self._firma = firma_vapid                          # endpoint -> header Authorization
        self._fetch = fetch or self._fetch_reale
        self._now = orologio or (lambda: int(time.time()))

    def _apri(self) -> sqlite3.Connection:
        con = self._cf()
        try:
            con.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass
        return con

    def inizializza_schema(self) -> None:
        con = self._apri()
        try:
            with con:
                con.execute("""CREATE TABLE IF NOT EXISTS push_sub (
                    guest_id TEXT NOT NULL, endpoint TEXT NOT NULL,
                    sub_json TEXT NOT NULL, ts INTEGER NOT NULL,
                    PRIMARY KEY (guest_id, endpoint))""")
        finally:
            con.close()

    def registra(self, guest_id: str, subscription: Dict[str, Any]) -> bool:
        if not guest_id or not _valida_sub(subscription):
            return False
        con = self._apri()
        try:
            with con:
                con.execute("INSERT OR REPLACE INTO push_sub (guest_id, endpoint, "
                            "sub_json, ts) VALUES (?,?,?,?)",
                            (str(guest_id), subscription["endpoint"],
                             json.dumps(subscription), self._now()))
            return True
        except Exception:
            logger.warning("registra sub fallita (ISOLATA)", exc_info=True)
            return False
        finally:
            con.close()

    def disiscrivi(self, guest_id: str, endpoint: str) -> bool:
        con = self._apri()
        try:
            with con:
                cur = con.execute("DELETE FROM push_sub WHERE guest_id=? AND endpoint=?",
                                  (str(guest_id), str(endpoint)))
            return cur.rowcount > 0
        except Exception:
            return False
        finally:
            con.close()

    def _subs(self, guest_id: str) -> List[Dict[str, Any]]:
        con = self._apri()
        try:
            rows = con.execute("SELECT sub_json FROM push_sub WHERE guest_id=?",
                               (str(guest_id),)).fetchall()
            return [json.loads(r[0]) for r in rows]
        except Exception:
            return []
        finally:
            con.close()

    def invia(self, guest_id: str, titolo: str, corpo: str, *,
              url: str = "") -> int:
        """Invia a TUTTE le subscription del guest. Ritorna quante consegnate.
        GATED: senza VAPID public+firma → 0 (nessun invio)."""
        if not (self._vapid and self._firma and guest_id):
            return 0
        payload = json.dumps({"title": str(titolo), "body": str(corpo), "url": str(url)})
        n = 0
        for s in self._subs(guest_id):
            try:
                ep = s.get("endpoint", "")
                headers = {"Authorization": self._firma(ep), "TTL": "86400",
                           "Content-Type": "application/octet-stream"}
                code = self._fetch(ep, payload.encode("utf-8"), headers)
                if isinstance(code, int) and 200 <= code < 300:
                    n += 1
            except Exception:
                logger.warning("invio push fallito (ISOLATO)", exc_info=True)
        return n

    def _fetch_reale(self, url: str, body: bytes,
                     headers: Dict[str, str]) -> int:  # pragma: no cover
        import urllib.request
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status


def crea_web_push(percorso: str, *, vapid_public: str = "",
                  firma_vapid: Any = None, fetch: Any = None,
                  orologio: Any = None) -> WebPush:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return WebPush(lambda: _ConnCondivisa(con), vapid_public=vapid_public,
                       firma_vapid=firma_vapid, fetch=fetch, orologio=orologio)
    return WebPush(lambda: sqlite3.connect(percorso), vapid_public=vapid_public,
                   firma_vapid=firma_vapid, fetch=fetch, orologio=orologio)
