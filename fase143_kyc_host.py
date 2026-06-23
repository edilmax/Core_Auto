"""
CORE_AUTO - Fase 143: Verifica identità host KYC (handoff a provider, no PII sui ns server).

Avvia la verifica KYC/KYB presso un provider ESTERNO (es. Stripe Identity/Express, iniettato):
noi NON conserviamo documenti — teniamo solo stato (non_avviata/in_corso/verificato/respinto)
+ il riferimento sessione del provider. Il provider conferma via callback (verifica firma del
payload, anti-replay). Gate: un host non verificato non riceve payout (collega fase100/131).
Store DUREVOLE SQLite. GATED dal provider. BLINDATO: errore → stato invariato / False.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("core_auto.kyc_host")

STATI = ("non_avviata", "in_corso", "verificato", "respinto")
_TRANS = {"non_avviata": {"in_corso"}, "in_corso": {"verificato", "respinto"},
          "respinto": {"in_corso"}, "verificato": set()}


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


class KYCHost:
    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], *,
                 avvia_sessione: Optional[Callable[[str], Optional[str]]] = None,
                 orologio: Optional[Callable[[], int]] = None) -> None:
        self._cf = conn_factory
        self._avvia = avvia_sessione          # provider: host_id -> session_ref (gated)
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
                con.execute("""CREATE TABLE IF NOT EXISTS kyc (
                    host_id TEXT PRIMARY KEY, stato TEXT NOT NULL,
                    session_ref TEXT NOT NULL DEFAULT '', ts INTEGER NOT NULL)""")
        finally:
            con.close()

    def stato(self, host_id: str) -> str:
        con = self._apri()
        try:
            r = con.execute("SELECT stato FROM kyc WHERE host_id=?",
                            (str(host_id),)).fetchone()
            return r[0] if r else "non_avviata"
        finally:
            con.close()

    def verificato(self, host_id: str) -> bool:
        return self.stato(host_id) == "verificato"

    def avvia(self, host_id: str) -> Dict[str, Any]:
        """GATED: senza provider → nessuna sessione. Ritorna il riferimento per il redirect."""
        if not host_id or self._avvia is None:
            return {"ok": False, "errore": "provider_non_configurato"}
        try:
            ref = self._avvia(str(host_id))
        except Exception:
            logger.warning("avvio sessione KYC fallito (ISOLATO)", exc_info=True)
            ref = None
        if not ref:
            return {"ok": False, "errore": "sessione_non_creata"}
        if not self._transita(host_id, "in_corso", ref):
            return {"ok": False, "errore": "transizione_non_valida",
                    "stato": self.stato(host_id)}
        return {"ok": True, "stato": "in_corso", "session_ref": ref}

    def conferma(self, host_id: str, esito: str) -> bool:
        """Callback del provider (già autenticato a monte): 'verificato'/'respinto'."""
        if esito not in ("verificato", "respinto"):
            return False
        return self._transita(host_id, esito, None)

    def _transita(self, host_id: str, nuovo: str, ref: Optional[str]) -> bool:
        if nuovo not in STATI:
            return False
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            r = con.execute("SELECT stato, session_ref FROM kyc WHERE host_id=?",
                            (str(host_id),)).fetchone()
            corrente = r[0] if r else "non_avviata"
            if nuovo not in _TRANS.get(corrente, set()):
                con.execute("ROLLBACK")
                return False
            sref = ref if ref is not None else (r[1] if r else "")
            con.execute("INSERT OR REPLACE INTO kyc (host_id, stato, session_ref, ts) "
                        "VALUES (?,?,?,?)",
                        (str(host_id), nuovo, sref, self._now()))
            con.execute("COMMIT")
            return True
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            logger.warning("transizione KYC fallita (ISOLATA)", exc_info=True)
            return False
        finally:
            con.close()


def crea_kyc_host(percorso: str, *, avvia_sessione: Any = None,
                  orologio: Any = None) -> KYCHost:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return KYCHost(lambda: _ConnCondivisa(con), avvia_sessione=avvia_sessione,
                       orologio=orologio)
    return KYCHost(lambda: sqlite3.connect(percorso), avvia_sessione=avvia_sessione,
                   orologio=orologio)
