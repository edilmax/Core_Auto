"""FASE 204 — L'ARCHIVIO DEGLI EVENTI STRIPE: si scrive PRIMA di rispondere.

PERCHE' ESISTE. Fino al 2026-09-08 il gestore dei webhook (`fase83_server._webhook_stripe`)
verificava la firma e poi faceva TUTTO dentro la risposta: confermava, scriveva, mandava
email. Dell'evento in se' non restava traccia da nessuna parte -- cercato su tutto il
progetto, non esisteva ne' una tabella ne' un modulo. Quindi alla domanda «questo evento
l'abbiamo gia' ricevuto?» non rispondeva nessuno.

⛔ E LA RISPOSTA 2xx E' IL PUNTO DI NON RITORNO. Stripe legge 2xx come «ricevuto e gestito»
e non riprova MAI piu'; un non-2xx lo fa ritentare per giorni. Quindi rispondere 200 su un
evento che non e' stato nemmeno registrato non e' un errore di forma: e' l'unico modo di
rendere quella perdita DEFINITIVA. Questo modulo esiste per spostare la scrittura PRIMA
della risposta, cosi' che «ho risposto 2xx» implichi sempre «ce l'ho scritto».

⚠️ COSA QUESTO MODULO **NON** FA, dichiarato qui e non scoperto dopo (D18 punto 3):
  · NON sposta l'elaborazione fuori dalla risposta. La casella 7 del blocco SOLDI chiede
    anche «lo elabora DOPO, in un passo separato»: quello NON e' fatto, e la casella resta
    VUOTA apposta. Misurato prima di decidere: 81 file di collaudo e 19 banchi passano dal
    webhook, 120 chiamate in tutto, quasi tutte aspettandosi la conferma dentro la risposta.
    Spostarla e' un lavoro a se', da fare quando non c'e' altro in volo.
  · NON ritenta da solo gli eventi rimasti indietro. Espone `pendenti()` perche' si possano
    VEDERE -- che e' cio' su cui poggera' la casella 9 -- ma nessuno li rilavora ancora.
  · NON deduplica l'elaborazione: `salva()` non duplica una riga gia' presente, il che e' il
    seme della casella 8, ma la casella 8 chiede anche che due Event DIVERSI per lo stesso
    fatto contino come uno, e questo modulo non lo sa fare.

LOGICA. Una tabella, chiave l'identificativo dell'evento (`evt_...`). Tre stati osservabili:
la riga c'e' (ricevuto), la riga e' segnata elaborata (gestito), la riga c'e' e non e'
segnata (ricevuto e NON gestito: e' quello che si vuole poter vedere).

DIPENDENZE: nessuna nuova, solo `sqlite3` della libreria standard.
STATO: acceso -- lo crea `fase81_bootstrap_casavip.crea_sistema` e lo usa `fase83_server`.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional


class _ConnCondivisa:
    """Guscio per `:memory:`, dove chiudere la connessione butterebbe via il database.

    Stessa forma gia' usata da `fase162_pagamenti_pendenti`: non si inventa un modo nuovo
    per un problema che in questo progetto ha gia' una soluzione.
    """

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


class ArchivioEventiStripe:

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
                con.execute("""CREATE TABLE IF NOT EXISTS eventi_stripe (
                    evt_id TEXT PRIMARY KEY,
                    tipo TEXT NOT NULL DEFAULT '',
                    corpo_json TEXT NOT NULL DEFAULT '',
                    stato TEXT NOT NULL DEFAULT 'da_elaborare',
                    tentativi INTEGER NOT NULL DEFAULT 0,
                    ricevuto_ts INTEGER NOT NULL,
                    elaborato_ts INTEGER NOT NULL DEFAULT 0)""")
                con.execute("CREATE INDEX IF NOT EXISTS ix_eventi_stato "
                            "ON eventi_stripe(stato, ricevuto_ts)")
        finally:
            con.close()

    # ── scrittura ───────────────────────────────────────────────────────────────
    def salva(self, evt_id: Any, *, tipo: str = "", corpo_json: str = "") -> bool:
        """Registra l'evento. True se DOPO questa chiamata la riga c'e'.

        ⛔ IL VALORE DI RITORNO E' UN ESITO, NON UN COMMENTO: chi chiama deve guardarlo, ed
        e' il difetto che questo progetto ha gia' pagato quattro volte nello stesso gestore
        (un metodo dichiarato `-> bool` chiamato e ignorato: «un booleano che nessuno legge
        non e' un esito»).

        ⛔ Un evento GIA' PRESENTE non e' un errore e non si duplica: Stripe consegna piu'
        volte apposta. Torna True perche' la domanda e' «c'e'?», non «l'ho scritto io adesso?».
        """
        if not (isinstance(evt_id, str) and evt_id.strip()):
            return False
        con = self._apri()
        try:
            with con:
                con.execute(
                    "INSERT OR IGNORE INTO eventi_stripe "
                    "(evt_id, tipo, corpo_json, ricevuto_ts) VALUES (?,?,?,?)",
                    (evt_id, str(tipo or ""), str(corpo_json or ""), self._now()))
            r = con.execute("SELECT 1 FROM eventi_stripe WHERE evt_id=?",
                            (evt_id,)).fetchone()
            return r is not None
        finally:
            con.close()

    def segna_elaborato(self, evt_id: Any) -> bool:
        """Segna l'evento come gestito. False se quella riga non c'e'."""
        if not (isinstance(evt_id, str) and evt_id.strip()):
            return False
        con = self._apri()
        try:
            with con:
                cur = con.execute(
                    "UPDATE eventi_stripe SET stato='elaborato', elaborato_ts=? "
                    "WHERE evt_id=?", (self._now(), evt_id))
            return cur.rowcount > 0
        finally:
            con.close()

    def segna_tentativo(self, evt_id: Any) -> int:
        """Conta un tentativo fallito e torna quanti ne ha subiti finora. 0 se non c'e'."""
        if not (isinstance(evt_id, str) and evt_id.strip()):
            return 0
        con = self._apri()
        try:
            with con:
                con.execute("UPDATE eventi_stripe SET tentativi=tentativi+1 WHERE evt_id=?",
                            (evt_id,))
            r = con.execute("SELECT tentativi FROM eventi_stripe WHERE evt_id=?",
                            (evt_id,)).fetchone()
            return int(r[0]) if r else 0
        finally:
            con.close()

    # ── lettura ─────────────────────────────────────────────────────────────────
    def esiste(self, evt_id: Any) -> bool:
        if not isinstance(evt_id, str):
            return False
        con = self._apri()
        try:
            return con.execute("SELECT 1 FROM eventi_stripe WHERE evt_id=?",
                               (evt_id,)).fetchone() is not None
        finally:
            con.close()

    def elaborato(self, evt_id: Any) -> bool:
        """True SOLO se la riga c'e' ED e' segnata elaborata.

        ⛔ Due domande diverse che non si confondono: «non c'e'» e «c'e' e non e' gestito»
        hanno rimedi opposti -- la prima e' un evento perso, la seconda un lavoro rimasto
        indietro. Un metodo che rispondesse False a tutt'e due le renderebbe indistinguibili.
        """
        if not isinstance(evt_id, str):
            return False
        con = self._apri()
        try:
            r = con.execute("SELECT stato FROM eventi_stripe WHERE evt_id=?",
                            (evt_id,)).fetchone()
            return bool(r) and str(r[0]) == "elaborato"
        finally:
            con.close()

    def pendenti(self, *, piu_vecchi_di_sec: int = 0, limite: int = 100) -> List[Dict[str, Any]]:
        """Gli eventi RICEVUTI e NON ancora gestiti: e' il buco che si vuole poter vedere.

        `piu_vecchi_di_sec` esiste perche' un evento appena arrivato e' normale che sia
        ancora da elaborare: senza quella soglia, «pendente» e «in corso» sarebbero la stessa
        cosa, e un allarme che grida su cio' che e' normale viene spento (regola ferrea 10).
        """
        soglia = self._now() - max(0, int(piu_vecchi_di_sec))
        con = self._apri()
        try:
            righe = con.execute(
                "SELECT evt_id, tipo, tentativi, ricevuto_ts FROM eventi_stripe "
                "WHERE stato<>'elaborato' AND ricevuto_ts<=? "
                "ORDER BY ricevuto_ts LIMIT ?", (soglia, max(1, int(limite)))).fetchall()
            return [{"evt_id": r[0], "tipo": r[1], "tentativi": int(r[2]),
                     "ricevuto_ts": int(r[3])} for r in righe]
        finally:
            con.close()


def crea_archivio_eventi(percorso: str, *, orologio: Any = None) -> ArchivioEventiStripe:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        con.row_factory = sqlite3.Row
        return ArchivioEventiStripe(lambda: _ConnCondivisa(con), orologio=orologio)

    def cf() -> sqlite3.Connection:
        c = sqlite3.connect(percorso, timeout=30)
        c.row_factory = sqlite3.Row
        return c
    return ArchivioEventiStripe(cf, orologio=orologio)
