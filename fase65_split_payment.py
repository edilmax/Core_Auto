"""
CORE_AUTO - Fase 65: Split-payment di gruppo (dividere il costo di un soggiorno).

Un gruppo prenota un alloggio e vuole dividere il conto: ognuno paga la sua quota, e
solo quando TUTTE le quote sono pagate l'alloggio e' finanziato (-> escrow/conferma
via fase34). I colossi gestiscono male o per niente lo split; per noi e' logica pura,
a costo zero, sopra l'escrow gia' esistente.

Garanzie dure (il denaro non perdona):
  1. CONSERVAZIONE ESATTA al centesimo: la somma delle quote == totale, SEMPRE. Niente
     centesimo perso o creato (zero float).
  2. IDEMPOTENZA dei pagamenti: un retry/duplicato (rete, webhook ripetuto) non fa
     pagare due volte la stessa quota.
  3. COMPLETAMENTO atomico: il conto diventa 'completato' solo quando il raccolto ==
     totale; finche' manca anche 1 cent, l'alloggio NON e' finanziato (fail-closed).
  4. RIDISTRIBUZIONE su rinuncia: se alla scadenza qualcuno non ha pagato, il mancante
     si riparte (esatto, largest-remainder) tra chi ha gia' pagato ("chi paga copre"),
     oppure il conto si annulla se non paga nessuno. Il piano e' calcolato dal CORE;
     l'addebito reale e' delegato a fase35.

SPLIT VINCITORE DEL BENCHMARK (4 metodi, conservazione sotto importi/partecipanti avversi):
  V3 'interi con largest-remainder'. base = totale//n a tutti, +1 cent ai primi
  (totale % n): somma ESATTAMENTE il totale, differenza max 1 cent tra quote (equo),
  deterministico. Le altre perdono: V1 'float/2 decimali' perde/crea centesimi su
  arrotondamento; V2 'totale//n a tutti' lascia indietro `resto` centesimi (raccolto <
  totale -> non si completa mai); V4 'un pagatore copre il resto' concentra l'errore.

SOPRAVVIVENZA TOTALE: store durevole (conn-per-op, WAL, BEGIN IMMEDIATE, idem schema);
validatori BLINDATI; importi non interi/somma sbagliata -> fail-closed; orologio
iniettabile (scadenza deterministica nei test). Zero dipendenze esterne.
"""
from __future__ import annotations

import datetime
import logging
import secrets
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger("core_auto.split_payment")

MAX_CENTS = 1_000_000_00
MAX_PARTECIPANTI = 50


def _intero(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def riparti_equo(totale_cents: int, n: int) -> List[int]:
    """Divide `totale_cents` in n quote intere che sommano ESATTAMENTE al totale
    (largest-remainder): i primi `totale%n` ricevono +1 cent. Differenza max 1 cent."""
    if not _intero(totale_cents) or totale_cents < 0 or not _intero(n) or n <= 0:
        return []
    base = totale_cents // n
    resto = totale_cents % n
    return [base + (1 if i < resto else 0) for i in range(n)]


@dataclass(frozen=True)
class EsitoQuota:
    ok: bool
    motivo: str = ""
    idempotente: bool = False
    completato: bool = False


@dataclass(frozen=True)
class VoceRidistribuzione:
    partecipante_id: str
    extra_cents: int


# ─────────────────────────────────────────────────────────────────────────────
# Store durevole dei conti divisi
# ─────────────────────────────────────────────────────────────────────────────
class GestoreSplit:
    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], *,
                 orologio: Optional[Callable[[], int]] = None) -> None:
        self._conn_factory = conn_factory
        self._now = orologio or (lambda: int(time.time()))
        self.inizializza_schema()

    def _apri(self) -> sqlite3.Connection:
        con = self._conn_factory()
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass
        return con

    def inizializza_schema(self) -> None:
        con = self._apri()
        try:
            with con:
                con.execute("""
                    CREATE TABLE IF NOT EXISTS conti (
                        conto_id TEXT PRIMARY KEY,
                        prenotazione_id TEXT NOT NULL,
                        alloggio_id TEXT NOT NULL,
                        totale_cents INTEGER NOT NULL,
                        stato TEXT NOT NULL DEFAULT 'aperto',
                        scadenza INTEGER,
                        creato_ts TEXT NOT NULL)""")
                con.execute("""
                    CREATE TABLE IF NOT EXISTS quote (
                        conto_id TEXT NOT NULL,
                        partecipante_id TEXT NOT NULL,
                        dovuto_cents INTEGER NOT NULL,
                        pagato INTEGER NOT NULL DEFAULT 0,
                        pagamento_idem TEXT,
                        PRIMARY KEY (conto_id, partecipante_id))""")
        finally:
            con.close()

    # ── creazione conto ────────────────────────────────────────────────────────
    def crea_conto(self, prenotazione_id: str, alloggio_id: str, totale_cents: int,
                   partecipanti: Sequence[str], *, metodo: str = "equo",
                   importi: Optional[Dict[str, int]] = None,
                   scadenza: Optional[int] = None,
                   conto_id: Optional[str] = None) -> Optional[str]:
        """Crea un conto diviso. Ritorna conto_id, o None se input invalido (fail-closed).
        metodo='equo' (largest-remainder) | 'importi' (dict che DEVE sommare al totale)."""
        if not (isinstance(prenotazione_id, str) and prenotazione_id.strip()):
            return None
        if not (isinstance(alloggio_id, str) and alloggio_id.strip()):
            return None
        if not (_intero(totale_cents) and 0 < totale_cents <= MAX_CENTS):
            return None
        if not isinstance(partecipanti, (list, tuple)):
            return None
        ids = [str(p).strip() for p in partecipanti]
        if not ids or any(not p for p in ids) or len(set(ids)) != len(ids):
            return None
        if len(ids) > MAX_PARTECIPANTI:
            return None

        if metodo == "equo":
            quote = dict(zip(ids, riparti_equo(totale_cents, len(ids))))
        elif metodo == "importi":
            if not isinstance(importi, dict) or set(importi.keys()) != set(ids):
                return None
            if any(not _intero(v) or v < 0 for v in importi.values()):
                return None
            if sum(importi.values()) != totale_cents:        # conservazione esatta
                return None
            quote = {k: int(importi[k]) for k in ids}
        else:
            return None

        cid = conto_id or secrets.token_hex(8)
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            if con.execute("SELECT 1 FROM conti WHERE conto_id=?", (cid,)).fetchone():
                con.execute("ROLLBACK")
                return None
            con.execute(
                "INSERT INTO conti (conto_id, prenotazione_id, alloggio_id, "
                "totale_cents, stato, scadenza, creato_ts) VALUES (?,?,?,?,?,?,?)",
                (cid, prenotazione_id, alloggio_id, totale_cents, "aperto",
                 scadenza if _intero(scadenza) else None, ts))
            con.executemany(
                "INSERT INTO quote (conto_id, partecipante_id, dovuto_cents) "
                "VALUES (?,?,?)", [(cid, p, quote[p]) for p in ids])
            con.execute("COMMIT")
            return cid
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    # ── pagamento di una quota (idempotente) ───────────────────────────────────
    def registra_pagamento(self, conto_id: str, partecipante_id: str, *,
                           idem_key: str) -> EsitoQuota:
        if not (isinstance(idem_key, str) and idem_key.strip()):
            return EsitoQuota(False, "idem_key_mancante")
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            conto = con.execute("SELECT stato, scadenza, totale_cents FROM conti "
                                "WHERE conto_id=?", (str(conto_id),)).fetchone()
            if conto is None:
                con.execute("ROLLBACK")
                return EsitoQuota(False, "conto_inesistente")
            q = con.execute("SELECT pagato FROM quote WHERE conto_id=? AND "
                            "partecipante_id=?", (str(conto_id), str(partecipante_id))
                            ).fetchone()
            if q is None:
                con.execute("ROLLBACK")
                return EsitoQuota(False, "partecipante_ignoto")
            if q["pagato"]:                                   # replay -> idempotente
                completo = conto["stato"] == "completato"
                con.execute("COMMIT")
                return EsitoQuota(True, "", idempotente=True, completato=completo)
            if conto["stato"] != "aperto":
                con.execute("ROLLBACK")
                return EsitoQuota(False, "conto_non_aperto")
            if conto["scadenza"] is not None and self._now() > conto["scadenza"]:
                con.execute("ROLLBACK")
                return EsitoQuota(False, "scaduto")
            con.execute("UPDATE quote SET pagato=1, pagamento_idem=? WHERE conto_id=? "
                        "AND partecipante_id=?",
                        (idem_key, str(conto_id), str(partecipante_id)))
            raccolto = con.execute(
                "SELECT COALESCE(SUM(dovuto_cents),0) AS r FROM quote "
                "WHERE conto_id=? AND pagato=1", (str(conto_id),)).fetchone()["r"]
            completato = raccolto >= conto["totale_cents"]
            if completato:
                con.execute("UPDATE conti SET stato='completato' WHERE conto_id=?",
                            (str(conto_id),))
            con.execute("COMMIT")
            return EsitoQuota(True, "", completato=completato)
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    # ── stato ──────────────────────────────────────────────────────────────────
    def stato_conto(self, conto_id: str) -> Optional[Dict[str, Any]]:
        con = self._apri()
        try:
            c = con.execute("SELECT * FROM conti WHERE conto_id=?",
                            (str(conto_id),)).fetchone()
            if c is None:
                return None
            quote = con.execute("SELECT partecipante_id, dovuto_cents, pagato FROM quote "
                                "WHERE conto_id=? ORDER BY partecipante_id",
                                (str(conto_id),)).fetchall()
        finally:
            con.close()
        raccolto = sum(q["dovuto_cents"] for q in quote if q["pagato"])
        return {
            "conto_id": c["conto_id"], "prenotazione_id": c["prenotazione_id"],
            "alloggio_id": c["alloggio_id"], "totale_cents": int(c["totale_cents"]),
            "raccolto_cents": int(raccolto),
            "mancante_cents": int(c["totale_cents"] - raccolto),
            "stato": c["stato"], "completato": c["stato"] == "completato",
            "pronto_per_escrow": c["stato"] == "completato",
            "quote": [{"partecipante_id": q["partecipante_id"],
                       "dovuto_cents": int(q["dovuto_cents"]),
                       "pagato": bool(q["pagato"])} for q in quote],
        }

    # ── ridistribuzione su rinuncia (alla scadenza) ────────────────────────────
    def ridistribuisci_mancante(self, conto_id: str) -> Dict[str, Any]:
        """Se il conto e' incompleto, riparte il mancante (esatto) tra chi ha gia'
        pagato. Ritorna il piano; l'addebito reale e' delegato a fase35. Se non ha
        pagato nessuno -> coperto=False (il conto va annullato)."""
        st = self.stato_conto(conto_id)
        if st is None or st["completato"] or st["mancante_cents"] <= 0:
            return {"coperto": False, "mancante_cents": 0, "voci": []}
        pagatori = [q["partecipante_id"] for q in st["quote"] if q["pagato"]]
        mancante = st["mancante_cents"]
        if not pagatori:
            return {"coperto": False, "mancante_cents": mancante, "voci": []}
        extra = riparti_equo(mancante, len(pagatori))
        voci = [VoceRidistribuzione(p, e) for p, e in zip(pagatori, extra)]
        return {"coperto": True, "mancante_cents": mancante, "voci": voci}

    def annulla(self, conto_id: str) -> bool:
        con = self._apri()
        try:
            with con:
                cur = con.execute("UPDATE conti SET stato='annullato' WHERE conto_id=? "
                                  "AND stato='aperto'", (str(conto_id),))
            return cur.rowcount > 0
        finally:
            con.close()


# ─────────────────────────────────────────────────────────────────────────────
# Connessione condivisa per :memory:
# ─────────────────────────────────────────────────────────────────────────────
class _ConnCondivisa:
    def __init__(self, con: sqlite3.Connection) -> None:
        object.__setattr__(self, "_con", con)

    def close(self) -> None:
        pass

    def __enter__(self):
        return self._con.__enter__()

    def __exit__(self, *a):
        return self._con.__exit__(*a)

    def __getattr__(self, name):
        return getattr(self._con, name)

    def __setattr__(self, name, value):
        setattr(self._con, name, value)


def crea_gestore_split(percorso: str = ":memory:", *,
                       orologio: Optional[Callable[[], int]] = None) -> GestoreSplit:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return GestoreSplit(lambda: _ConnCondivisa(con), orologio=orologio)
    # timeout 30s: sotto burst simultaneo (tutti i membri pagano nello stesso
    # istante) il default 5s produceva 'database is locked' -> 503; i writer
    # ora si ACCODANO (bug #36, bombardamento split)
    return GestoreSplit(lambda: sqlite3.connect(percorso, timeout=30),
                        orologio=orologio)
