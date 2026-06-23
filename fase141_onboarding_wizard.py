"""
CORE_AUTO - Fase 141: Host onboarding wizard guidato (macchina a stati deterministica).

Guida l'host passo-passo: account → struttura → foto → prezzo → disponibilità → pagamenti →
pubblicato. Ogni passo valida i dati e calcola la % di completamento; il passo "pubblica" è
sbloccato SOLO quando i requisiti minimi sono soddisfatti (gate, fail-closed). Store DUREVOLE
SQLite (stato per host). PURO per la logica dei passi. BLINDATO: input invalido → non avanza.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("core_auto.onboarding_wizard")

# (chiave_passo, etichetta, campi_obbligatori)
PASSI: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("account", "Crea account", ("email",)),
    ("struttura", "Dati struttura", ("titolo", "citta", "capacita")),
    ("foto", "Carica foto", ("foto",)),
    ("prezzo", "Imposta prezzo", ("prezzo_cents",)),
    ("disponibilita", "Apri disponibilità", ("giorni_aperti",)),
    ("pagamenti", "Collega pagamenti", ("payout_account",)),
)
ORDINE = [p[0] for p in PASSI]
# passi minimi per pubblicare (pagamenti opzionale in fase iniziale)
MINIMI = ("account", "struttura", "foto", "prezzo", "disponibilita")


def _valido(passo: str, dati: Dict[str, Any]) -> bool:
    req = next((r for k, _, r in PASSI if k == passo), ())
    for c in req:
        v = dati.get(c)
        if v is None or v == "" or v == [] or (isinstance(v, int) and not
                                               isinstance(v, bool) and v <= 0):
            return False
    return True


def stato_wizard(dati: Dict[str, Any]) -> Dict[str, Any]:
    d = dati if isinstance(dati, dict) else {}
    completati = [k for k, _, _ in PASSI if _valido(k, d)]
    prossimo = next((k for k in ORDINE if k not in completati), None)
    pubblicabile = all(m in completati for m in MINIMI)
    perc = len(completati) * 10000 // len(PASSI)         # bps
    return {"completati": completati, "prossimo_passo": prossimo,
            "pubblicabile": pubblicabile, "completamento_bps": perc,
            "passi": [{"chiave": k, "etichetta": e, "fatto": k in completati}
                      for k, e, _ in PASSI]}


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


class OnboardingWizard:
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
                con.execute("""CREATE TABLE IF NOT EXISTS wizard (
                    host_id TEXT PRIMARY KEY, dati_json TEXT NOT NULL,
                    pubblicato INTEGER NOT NULL DEFAULT 0, ts INTEGER NOT NULL)""")
        finally:
            con.close()

    def _dati(self, con: sqlite3.Connection, host_id: str) -> Dict[str, Any]:
        r = con.execute("SELECT dati_json FROM wizard WHERE host_id=?",
                        (str(host_id),)).fetchone()
        return json.loads(r[0]) if r else {}

    def salva_passo(self, host_id: str, passo: str, dati_passo: Dict[str, Any]
                    ) -> Dict[str, Any]:
        if not host_id or passo not in ORDINE or not isinstance(dati_passo, dict):
            return {"ok": False, "errore": "input_non_valido"}
        if not _valido(passo, dati_passo):
            return {"ok": False, "errore": "passo_incompleto", "passo": passo}
        con = self._apri()
        try:
            with con:
                d = self._dati(con, host_id)
                d.update(dati_passo)
                con.execute("INSERT OR REPLACE INTO wizard (host_id, dati_json, "
                            "pubblicato, ts) VALUES (?,?, COALESCE((SELECT pubblicato "
                            "FROM wizard WHERE host_id=?),0), ?)",
                            (str(host_id), json.dumps(d), str(host_id), self._now()))
            return {"ok": True, **self.stato(host_id)}
        except Exception:
            logger.warning("salva_passo fallita (ISOLATA)", exc_info=True)
            return {"ok": False, "errore": "interno"}
        finally:
            con.close()

    def stato(self, host_id: str) -> Dict[str, Any]:
        con = self._apri()
        try:
            d = self._dati(con, host_id)
            st = stato_wizard(d)
            r = con.execute("SELECT pubblicato FROM wizard WHERE host_id=?",
                            (str(host_id),)).fetchone()
            st["pubblicato"] = bool(r and r[0])
            return st
        finally:
            con.close()

    def pubblica(self, host_id: str) -> Dict[str, Any]:
        """Gate fail-closed: pubblica solo se i requisiti minimi sono soddisfatti."""
        con = self._apri()
        try:
            with con:
                d = self._dati(con, host_id)
                st = stato_wizard(d)
                if not st["pubblicabile"]:
                    return {"ok": False, "errore": "requisiti_minimi_mancanti",
                            "prossimo_passo": st["prossimo_passo"]}
                con.execute("UPDATE wizard SET pubblicato=1, ts=? WHERE host_id=?",
                            (self._now(), str(host_id)))
            return {"ok": True, "pubblicato": True}
        except Exception:
            return {"ok": False, "errore": "interno"}
        finally:
            con.close()


def crea_onboarding_wizard(percorso: str, *, orologio: Any = None) -> OnboardingWizard:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return OnboardingWizard(lambda: _ConnCondivisa(con), orologio=orologio)
    return OnboardingWizard(lambda: sqlite3.connect(percorso), orologio=orologio)
