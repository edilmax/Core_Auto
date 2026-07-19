"""
CORE_AUTO - Fase 79: Dichiarazione Vincolante (il notaio, non la polizia).

Non possiamo (ne' vogliamo) controllare tutti gli alloggi: ci tireremmo la zappa sui
piedi. La soluzione: non promettiamo NOI, promette l'HOST - e la dichiarazione e'
VINCOLANTE. Se l'host dichiara "no allergeni", "pet-friendly", "silenzio garantito" e
risulta falso, l'ospite vince automaticamente: rimborso + penale, pagati dall'ESCROW
dell'host (fase34/35), NON da noi. Noi non tocchiamo, non rischiamo, non paghiamo.

Il meccanismo (deterministico, a costo zero):
  - l'host DICHIARA dei claim (opt-in): ogni claim ha una penale e delle PROVE richieste
    per smentirlo (es. "no_allergeni" -> certificato medico; "silenzio" -> misura dB alta);
  - l'ospite, se la dichiarazione e' falsa, apre una CONTESTAZIONE allegando le prove;
  - il CODICE GIUDICA: prove sufficienti -> claim FALSO -> ospite vince (rimborso intero
    + penale dichiarata, in centesimi dal CORE); prove insufficienti -> claim regge,
    nessun pagamento. Si puo' contestare SOLO un claim DICHIARATO (l'host ha scelto di
    impegnarsi); sul "Base" senza dichiarazioni parlano solo le recensioni.

Cosi' chi e' onesto guadagna (piu' dichiarazioni = piu' filtri = piu' prenotazioni),
chi mente viene scoperto e paga lui. Il rischio resta sull'host che si e' impegnato.

VINCITRICE DEL BENCHMARK (4 modi di garantire la qualita'):
  V3 'dichiarazione vincolante + giudizio deterministico da PROVE + payout da escrow
  dell'host'. Host responsabile, ospite protetto, ZERO costo/rischio per noi. Le altre
  perdono: V1 'promesse vaghe dell'OTA, paga l'OTA' = costoso e arbitrario; V2 'nessun
  claim' = nessuna differenziazione, nessun premium; V4 'dispute risolte da umani' =
  lente, costose, soggettive.

SOPRAVVIVENZA TOTALE: store durevole (conn-per-op, WAL, BEGIN IMMEDIATE, idem schema);
contestazione idempotente per (prenotazione,claim); si contesta solo cio' che e'
dichiarato e attivo (fail-closed); giudizio richiede TUTTE le prove (soglia di evidenza);
denaro in CENTESIMI interi dal CORE. Zero dipendenze esterne.
"""
from __future__ import annotations

import datetime
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("core_auto.dichiarazione")

MAX_CENTS = 1_000_000_00

# Registro claim: penale di default (cents) + PROVE richieste per smentire il claim.
CLAIM: Dict[str, Dict[str, Any]] = {
    "no_allergeni": {"penale": 20000, "prove": ("certificato_medico",)},
    "pet_friendly": {"penale": 10000, "prove": ("foto_pet_rifiutato",)},
    "aria_purificata": {"penale": 15000, "prove": ("misura_co2_alta",)},
    "silenzio_garantito": {"penale": 10000, "prove": ("misura_db_alta",)},
    "accessibile": {"penale": 20000, "prove": ("foto_barriera",)},
}


def _intero_nn(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


@dataclass(frozen=True)
class EsitoContestazione:
    stato: str                  # 'accolta'|'respinta'|'non_dichiarato'|'claim_ignoto'|...
    rimborso_cents: int = 0
    penale_cents: int = 0
    idempotente: bool = False


class DichiarazioneEngine:
    def __init__(self, conn_factory: Callable[[], sqlite3.Connection]) -> None:
        self._conn_factory = conn_factory
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
                    CREATE TABLE IF NOT EXISTS dichiarazioni (
                        alloggio_id TEXT NOT NULL,
                        claim TEXT NOT NULL,
                        penale_cents INTEGER NOT NULL,
                        attivo INTEGER NOT NULL DEFAULT 1,
                        creato_ts TEXT NOT NULL,
                        PRIMARY KEY (alloggio_id, claim))""")
                con.execute("""
                    CREATE TABLE IF NOT EXISTS contestazioni (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        prenotazione_id TEXT NOT NULL,
                        alloggio_id TEXT NOT NULL,
                        claim TEXT NOT NULL,
                        stato TEXT NOT NULL,
                        rimborso_cents INTEGER NOT NULL DEFAULT 0,
                        penale_cents INTEGER NOT NULL DEFAULT 0,
                        ts TEXT NOT NULL,
                        UNIQUE (prenotazione_id, claim))""")
        finally:
            con.close()

    # ── dichiarazioni dell'host ────────────────────────────────────────────────
    def dichiara(self, alloggio_id: str, claim: str, *,
                 penale_cents: Optional[int] = None) -> bool:
        if not (isinstance(alloggio_id, str) and alloggio_id.strip()):
            return False
        spec = CLAIM.get(claim)
        if spec is None:
            return False                        # claim non riconosciuto
        penale = penale_cents if (penale_cents is not None) else spec["penale"]
        if not (_intero_nn(penale) and penale <= MAX_CENTS):
            return False
        ora = datetime.datetime.now().isoformat(timespec="seconds")
        con = self._apri()
        try:
            with con:
                con.execute(
                    "INSERT INTO dichiarazioni (alloggio_id, claim, penale_cents, "
                    "attivo, creato_ts) VALUES (?,?,?,1,?) "
                    "ON CONFLICT(alloggio_id, claim) DO UPDATE SET "
                    "penale_cents=excluded.penale_cents, attivo=1",
                    (str(alloggio_id), claim, penale, ora))
            return True
        finally:
            con.close()

    def ritira(self, alloggio_id: str, claim: str) -> bool:
        con = self._apri()
        try:
            with con:
                cur = con.execute("UPDATE dichiarazioni SET attivo=0 WHERE alloggio_id=? "
                                  "AND claim=?", (str(alloggio_id), str(claim)))
            return cur.rowcount > 0
        finally:
            con.close()

    def dichiarazioni_attive(self, alloggio_id: str) -> List[Dict[str, int]]:
        con = self._apri()
        try:
            righe = con.execute("SELECT claim, penale_cents FROM dichiarazioni WHERE "
                                "alloggio_id=? AND attivo=1 ORDER BY claim",
                                (str(alloggio_id),)).fetchall()
        finally:
            con.close()
        return [{"claim": r["claim"], "penale_cents": int(r["penale_cents"])}
                for r in righe]

    # ── contestazione dell'ospite (il codice giudica) ──────────────────────────
    def contesta(self, alloggio_id: str, prenotazione_id: str, claim: str,
                 prezzo_cents: int, prove: Any) -> EsitoContestazione:
        """Giudica la contestazione. Prove sufficienti -> ospite vince (rimborso+penale
        dall'escrow host). Idempotente per (prenotazione, claim)."""
        spec = CLAIM.get(claim)
        if spec is None:
            return EsitoContestazione("claim_ignoto")
        if not (_intero_nn(prezzo_cents) and 0 < prezzo_cents <= MAX_CENTS):
            return EsitoContestazione("prezzo_non_valido")
        prove = prove if isinstance(prove, dict) else {}
        ora = datetime.datetime.now().isoformat(timespec="seconds")
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            prec = con.execute("SELECT stato, rimborso_cents, penale_cents FROM "
                               "contestazioni WHERE prenotazione_id=? AND claim=?",
                               (str(prenotazione_id), claim)).fetchone()
            if prec is not None:                # replay -> stesso esito
                con.execute("COMMIT")
                return EsitoContestazione(prec["stato"], int(prec["rimborso_cents"]),
                                          int(prec["penale_cents"]), idempotente=True)
            dec = con.execute("SELECT penale_cents FROM dichiarazioni WHERE alloggio_id=? "
                              "AND claim=? AND attivo=1",
                              (str(alloggio_id), claim)).fetchone()
            if dec is None:
                con.execute("ROLLBACK")
                return EsitoContestazione("non_dichiarato")   # niente impegno -> niente
            # giudizio: tutte le prove richieste devono essere True
            prove_ok = all(prove.get(k) is True for k in spec["prove"])
            if prove_ok:
                stato = "accolta"
                rimborso = prezzo_cents
                penale = int(dec["penale_cents"])
            else:
                stato = "respinta"
                rimborso = penale = 0
            con.execute(
                "INSERT INTO contestazioni (prenotazione_id, alloggio_id, claim, stato, "
                "rimborso_cents, penale_cents, ts) VALUES (?,?,?,?,?,?,?)",
                (str(prenotazione_id), str(alloggio_id), claim, stato, rimborso, penale,
                 ora))
            con.execute("COMMIT")
            return EsitoContestazione(stato, rimborso, penale)
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    def esito(self, prenotazione_id: str, claim: str) -> Optional[Dict[str, Any]]:
        con = self._apri()
        try:
            r = con.execute("SELECT stato, rimborso_cents, penale_cents FROM "
                            "contestazioni WHERE prenotazione_id=? AND claim=?",
                            (str(prenotazione_id), str(claim))).fetchone()
            return dict(r) if r else None
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


def crea_dichiarazione(percorso: str = ":memory:") -> DichiarazioneEngine:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return DichiarazioneEngine(lambda: _ConnCondivisa(con))
    return DichiarazioneEngine(lambda: sqlite3.connect(percorso, timeout=30))
