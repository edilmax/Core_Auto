"""
CORE_AUTO - Fase 201: PROGRAMMA PARTNER (candidature affiliati / property manager / creator).

Strategia (direttiva fondatore 2026-07-27: «affiliazioni, portali, la strategia più potente»):
il canale di crescita a COSTO SOLO-A-RISULTATO. La pagina pubblica /partner.html raccoglie le
candidature dei professionisti (property manager con 10-100 proprietà = la scorciatoia verso
la massa critica; creator/blog di viaggio; agenzie). Qui SOLO la cattura durevole: niente
denaro, niente promesse di percentuali (le condizioni economiche le firma il fondatore,
caso per caso). Il referral host→host con crediti resta in fase76/109.

Anti-abuso: dedup per email (PRIMARY KEY, ri-invio = aggiornamento), tetto globale orario
(niente flooding del DB da parte di uno script), campi a lunghezza limitata, consenso privacy
OBBLIGATORIO (GDPR: senza consenso non si registra nulla).
Durevole SQLite (conn-per-op, timeout=30 standard del repo).
"""
from __future__ import annotations

import sqlite3
import time
import unicodedata
from typing import Any, Callable, Dict, List, Optional

TIPI_PARTNER = ("property_manager", "creator", "agenzia", "altro")
MAX_CANDIDATURE_ORA = 30          # tetto GLOBALE orario: anti-flooding, mai limita l'uso reale


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


def _velenoso(c: str) -> bool:
    """Carattere che NON puo' finire in archivio: surrogato isolato (categoria 'Cs': non
    codificabile in UTF-8 -> l'INSERT esplode e la rotta risponde 500) o byte di controllo
    ('Cc': il NUL tronca la stringa in ogni consumatore a valle - CSV, log, librerie C).
    Tabulazione e a-capo restano leciti nei testi liberi."""
    return c not in "\t\n" and unicodedata.category(c) in ("Cc", "Cs")


def _email_norm(e: Any) -> Optional[str]:
    """Email normalizzata per la DEDUP (minuscole, senza spazi ai bordi) oppure None se non
    e' spedibile. Rifiuta spazi INTERNI, caratteri di controllo e surrogati: non sono email
    vere, sono grimaldelli per duplicare la stessa casella o per far esplodere l'archivio."""
    if not isinstance(e, str):
        return None
    e = e.strip().lower()
    if not (3 <= len(e) <= 254):
        return None
    if any(c.isspace() or _velenoso(c) for c in e):
        return None
    locale, sep, dominio = e.partition("@")
    if not sep or not locale or "@" in dominio:
        return None                       # senza destinatario o con due chiocciole: non esiste
    pezzi = dominio.split(".")
    if len(pezzi) < 2 or not all(pezzi):
        return None                       # dominio senza punto, o con punti vuoti ('x.', '.x')
    return e


def _email_ok(e: Any) -> bool:
    return _email_norm(e) is not None


def _testo(v: Any, maxlen: int) -> str:
    if not isinstance(v, str):
        return ""
    return "".join(c for c in v if not _velenoso(c)).strip()[:maxlen]


class GestorePartner:
    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], *,
                 orologio: Optional[Callable[[], int]] = None) -> None:
        self._cf = conn_factory
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
                con.execute("""CREATE TABLE IF NOT EXISTS partner (
                    email TEXT PRIMARY KEY, nome TEXT NOT NULL, tipo TEXT NOT NULL,
                    citta TEXT DEFAULT '', messaggio TEXT DEFAULT '',
                    consenso INTEGER NOT NULL, ts INTEGER NOT NULL)""")
        finally:
            con.close()

    def registra(self, nome: Any, email: Any, tipo: Any, *, citta: Any = "",
                 messaggio: Any = "", consenso: Any = False) -> Dict[str, Any]:
        """Registra una candidatura. Ritorna {'ok': True} o {'errore': ...}.
        GDPR: senza consenso ESPLICITO (True) non si scrive NULLA."""
        if consenso is not True:
            return {"errore": "consenso_richiesto"}
        em = _email_norm(email)
        if em is None:
            return {"errore": "email_non_valida"}
        n = _testo(nome, 80)
        if len(n) < 2:
            return {"errore": "nome_non_valido"}
        if tipo not in TIPI_PARTNER:
            return {"errore": "tipo_non_valido"}
        adesso = self._now()
        con = self._apri()
        try:
            with con:
                recenti = con.execute("SELECT COUNT(*) FROM partner WHERE ts > ?",
                                      (adesso - 3600,)).fetchone()[0]
                if recenti >= MAX_CANDIDATURE_ORA:
                    return {"errore": "riprova_piu_tardi"}
                con.execute("INSERT OR REPLACE INTO partner VALUES (?,?,?,?,?,1,?)",
                            (em, n, tipo, _testo(citta, 80),
                             _testo(messaggio, 2000), adesso))
            return {"ok": True}
        finally:
            con.close()

    def candidati(self, limite: int = 500) -> List[Dict[str, Any]]:
        """Elenco per l'admin (più recenti prima)."""
        con = self._apri()
        try:
            rows = con.execute(
                "SELECT email, nome, tipo, citta, messaggio, ts FROM partner "
                "ORDER BY ts DESC LIMIT ?", (max(1, min(int(limite), 1000)),)).fetchall()
            return [{"email": r[0], "nome": r[1], "tipo": r[2], "citta": r[3],
                     "messaggio": r[4], "ts": r[5]} for r in rows]
        finally:
            con.close()

    def conta(self) -> int:
        con = self._apri()
        try:
            return con.execute("SELECT COUNT(*) FROM partner").fetchone()[0]
        finally:
            con.close()


def crea_gestore_partner(percorso: str, *, orologio: Any = None) -> GestorePartner:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return GestorePartner(lambda: _ConnCondivisa(con), orologio=orologio)
    return GestorePartner(lambda: sqlite3.connect(percorso, timeout=30), orologio=orologio)
