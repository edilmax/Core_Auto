"""
CORE_AUTO - Fase 160: ESCROW DI GARANZIA (i soldi all'host solo se la struttura corrisponde).

Il differenziatore vs i colossi: alla prenotazione i fondi destinati all'host restano BLOCCATI
in garanzia. L'host li riceve SOLO se:
  - l'ospite entra e conferma "tutto come dichiarato", OPPURE
  - passa la finestra post check-in senza contestazioni (auto-rilascio).
Se l'ospite contesta (servizio dichiarato mancante / non conforme) -> i fondi NON vengono
rilasciati: si apre una risoluzione (rimborso totale/parziale all'ospite). Tutela ospite E noi.

Macchina a stati DETERMINISTICA, durevole (SQLite, conn-per-op), denaro SOLO in cents interi,
CONSERVAZIONE esatta (host_riceve + ospite_rimborso == importo). Il movimento reale di denaro
(payout/refund Stripe) e' DELEGATO/gated: qui si decide CHI prende COSA, mai si tocca il PSP.
Stati: in_garanzia -> rilasciato | contestato -> risolto(rilasciato|rimborsato|parziale).
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional

FINESTRA_ORE_DEFAULT = 24          # ore dopo il check-in per l'auto-rilascio


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


def _cent(v: Any) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


class EscrowGaranzia:
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
                con.execute("""CREATE TABLE IF NOT EXISTS garanzia (
                    prenotazione_id TEXT PRIMARY KEY,
                    alloggio_id TEXT NOT NULL DEFAULT '',
                    importo_host_cents INTEGER NOT NULL,
                    host_riceve_cents INTEGER NOT NULL DEFAULT 0,
                    ospite_rimborso_cents INTEGER NOT NULL DEFAULT 0,
                    stato TEXT NOT NULL DEFAULT 'in_garanzia',
                    motivo TEXT NOT NULL DEFAULT '',
                    sblocco_auto_ts INTEGER NOT NULL,
                    aperto_ts INTEGER NOT NULL,
                    aggiornato_ts INTEGER NOT NULL)""")
        finally:
            con.close()

    def apri(self, prenotazione_id: Any, importo_host_cents: Any, *,
             alloggio_id: str = "", ora_checkin_ts: Any = None,
             finestra_ore: int = FINESTRA_ORE_DEFAULT) -> bool:
        """Apre la garanzia alla prenotazione (idempotente per prenotazione_id)."""
        if not (isinstance(prenotazione_id, str) and prenotazione_id):
            return False
        imp = _cent(importo_host_cents)
        if imp <= 0:
            return False
        now = self._now()
        base = ora_checkin_ts if isinstance(ora_checkin_ts, int) and not isinstance(
            ora_checkin_ts, bool) else now
        sblocco = base + max(1, int(finestra_ore)) * 3600
        con = self._apri()
        try:
            with con:
                con.execute(
                    "INSERT INTO garanzia (prenotazione_id, alloggio_id, importo_host_cents, "
                    "stato, sblocco_auto_ts, aperto_ts, aggiornato_ts) "
                    "VALUES (?,?,?, 'in_garanzia', ?,?,?) "
                    "ON CONFLICT(prenotazione_id) DO NOTHING",
                    (prenotazione_id, str(alloggio_id or ""), imp, sblocco, now, now))
            return True
        finally:
            con.close()

    def _muta(self, pren_id: str, attesi: tuple, nuovo: str, *,
              host: int = 0, rimborso: int = 0, motivo: str = "") -> Dict[str, Any]:
        con = self._apri()
        try:
            with con:
                con.execute("BEGIN IMMEDIATE")
                r = con.execute("SELECT stato, importo_host_cents FROM garanzia "
                                "WHERE prenotazione_id=?", (pren_id,)).fetchone()
                if r is None:
                    return {"ok": False, "motivo": "non_trovata"}
                if r["stato"] not in attesi:
                    return {"ok": False, "motivo": "stato_non_valido", "stato": r["stato"]}
                con.execute("UPDATE garanzia SET stato=?, host_riceve_cents=?, "
                            "ospite_rimborso_cents=?, motivo=?, aggiornato_ts=? "
                            "WHERE prenotazione_id=?",
                            (nuovo, host, rimborso, motivo or "", self._now(), pren_id))
            return {"ok": True, "stato": nuovo, "host_riceve_cents": host,
                    "ospite_rimborso_cents": rimborso}
        finally:
            con.close()

    def conferma_ospite(self, prenotazione_id: Any) -> Dict[str, Any]:
        """L'ospite e' entrato e conferma 'tutto ok' -> rilascia TUTTO all'host."""
        if not isinstance(prenotazione_id, str):
            return {"ok": False, "motivo": "id_non_valido"}
        imp = self._importo(prenotazione_id)
        return self._muta(prenotazione_id, ("in_garanzia",), "rilasciato", host=imp)

    def contesta(self, prenotazione_id: Any, motivo: str = "") -> Dict[str, Any]:
        """L'ospite contesta (servizio mancante / non conforme) -> blocca l'auto-rilascio."""
        if not isinstance(prenotazione_id, str):
            return {"ok": False, "motivo": "id_non_valido"}
        return self._muta(prenotazione_id, ("in_garanzia",), "contestato", motivo=str(motivo))

    def annulla(self, prenotazione_id: Any) -> Dict[str, Any]:
        """Prenotazione cancellata SENZA penale (rimborso pieno): host 0, niente auto-rilascio."""
        if not isinstance(prenotazione_id, str):
            return {"ok": False, "motivo": "id_non_valido"}
        return self._muta(prenotazione_id, ("in_garanzia", "contestato"), "annullato")

    def chiudi_proporzionale(self, prenotazione_id: Any, host_tiene_cents: Any) -> Dict[str, Any]:
        """Cancellazione CON penale: l'host TIENE la sua quota (tutela host), il resto torna
        all'ospite. Conservazione esatta. Dal solo stato 'in_garanzia'."""
        if not isinstance(prenotazione_id, str):
            return {"ok": False, "motivo": "id_non_valido"}
        imp = self._importo(prenotazione_id)
        if imp <= 0:
            return {"ok": False, "motivo": "non_trovata"}
        host = max(0, min(_cent(host_tiene_cents), imp))
        return self._muta(prenotazione_id, ("in_garanzia",), "risolto",
                          host=host, rimborso=imp - host)

    def risolvi(self, prenotazione_id: Any, *, rimborso_ospite_cents: Any) -> Dict[str, Any]:
        """Risoluzione (admin/giudice): rimborsa N all'ospite, il resto all'host. Conservazione
        esatta. Dal solo stato 'contestato'."""
        if not isinstance(prenotazione_id, str):
            return {"ok": False, "motivo": "id_non_valido"}
        imp = self._importo(prenotazione_id)
        if imp <= 0:
            return {"ok": False, "motivo": "non_trovata"}
        rimb = min(_cent(rimborso_ospite_cents), imp)
        return self._muta(prenotazione_id, ("contestato",), "risolto",
                          host=imp - rimb, rimborso=rimb)

    def auto_rilascia(self, *, ora_ts: Any = None, dettagli: bool = False) -> Any:
        """Rilascia all'host tutte le garanzie 'in_garanzia' con finestra scaduta e nessuna
        contestazione. Ritorna quante ne ha rilasciate; con dettagli=True la LISTA
        [{prenotazione_id, host_riceve_cents}] (per i bonifici automatici Connect)."""
        ora = ora_ts if isinstance(ora_ts, int) and not isinstance(ora_ts, bool) else self._now()
        con = self._apri()
        try:
            with con:
                righe = con.execute(
                    "SELECT prenotazione_id, importo_host_cents FROM garanzia "
                    "WHERE stato='in_garanzia' AND sblocco_auto_ts<=?", (ora,)).fetchall()
                for r in righe:
                    con.execute("UPDATE garanzia SET stato='rilasciato', host_riceve_cents=?, "
                                "aggiornato_ts=? WHERE prenotazione_id=?",
                                (r["importo_host_cents"], ora, r["prenotazione_id"]))
            if dettagli:
                return [{"prenotazione_id": r["prenotazione_id"],
                         "host_riceve_cents": int(r["importo_host_cents"])} for r in righe]
            return len(righe)
        finally:
            con.close()

    def _importo(self, pren_id: str) -> int:
        con = self._apri()
        try:
            r = con.execute("SELECT importo_host_cents FROM garanzia WHERE prenotazione_id=?",
                            (pren_id,)).fetchone()
            return int(r["importo_host_cents"]) if r else 0
        finally:
            con.close()

    def contestate(self, *, limit: int = 100) -> List[Dict[str, Any]]:
        """Elenco delle garanzie CONTESTATE (controversie aperte) per il pannello admin:
        l'operatore le vede e decide lo split del rimborso. Read-only."""
        lim = limit if isinstance(limit, int) and not isinstance(limit, bool) \
            and 0 < limit <= 500 else 100
        con = self._apri()
        try:
            righe = con.execute(
                "SELECT prenotazione_id, alloggio_id, importo_host_cents, motivo, aggiornato_ts "
                "FROM garanzia WHERE stato='contestato' ORDER BY aggiornato_ts DESC LIMIT ?",
                (lim,)).fetchall()
        finally:
            con.close()
        return [{"prenotazione_id": r["prenotazione_id"], "alloggio_id": r["alloggio_id"],
                 "importo_host_cents": int(r["importo_host_cents"]),
                 "motivo": r["motivo"], "ts": int(r["aggiornato_ts"]),
                 "money_unit": "cents_integer"} for r in righe]

    def stato(self, prenotazione_id: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(prenotazione_id, str):
            return None
        con = self._apri()
        try:
            r = con.execute("SELECT * FROM garanzia WHERE prenotazione_id=?",
                            (prenotazione_id,)).fetchone()
        finally:
            con.close()
        if r is None:
            return None
        return {"prenotazione_id": r["prenotazione_id"], "stato": r["stato"],
                "importo_host_cents": int(r["importo_host_cents"]),
                "host_riceve_cents": int(r["host_riceve_cents"]),
                "ospite_rimborso_cents": int(r["ospite_rimborso_cents"]),
                "motivo": r["motivo"], "money_unit": "cents_integer"}


def crea_escrow_garanzia(percorso: str, *, orologio: Any = None) -> EscrowGaranzia:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        con.row_factory = sqlite3.Row
        return EscrowGaranzia(lambda: _ConnCondivisa(con), orologio=orologio)

    def cf() -> sqlite3.Connection:
        c = sqlite3.connect(percorso)
        c.row_factory = sqlite3.Row
        return c
    return EscrowGaranzia(cf, orologio=orologio)
