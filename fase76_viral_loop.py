"""
CORE_AUTO - Fase 76: Viral Loop Engine (crescita virale a costo ZERO, anti-frode).

I colossi spendono ~$17.8B/anno in marketing. Noi spendiamo ZERO: la rete cresce da
sola con un loop virale host->host e guest->guest, e l'arma e' che i premi sono CREDITI
NON-CASHABILI -> sconto su commissione/prenotazione FUTURA, non denaro.

Perche' e' imbattibile (e anti-frode per costruzione):
  - non puoi incassare il credito -> creare account falsi per "ritirare" non serve a
    nulla; per usare il credito DEVI usare la piattaforma (host: piu' soggiorni; guest:
    piu' prenotazioni) -> il loop si auto-alimenta;
  - codice referral firmato HMAC (riusa fase59.FirmaQuote) -> non falsificabile, non
    indovinabile;
  - niente auto-referral, dedup del referee -> niente abuso.

Denaro: crediti in CENTESIMI interi, con scadenza; si applicano SOLO per ridurre un
importo dovuto (mai un pay-out). Compone con fase43 (commissione), fase69 (trasparenza:
"con noi guadagni di piu'"), fase57/58.

VINCITRICE DEL BENCHMARK (4 strategie di crescita):
  V3 'crediti NON-cashabili firmati + dedup + no-self'. Costo zero, anti-frode, auto-
  alimentante. Le altre perdono: V1 'bonus referral in CASH' = costoso e frodabile
  (account fantasma che incassano); V2 'marketing a pagamento' = i $17.8B delle OTA; V4
  'crediti cashabili con KYC' = attrito + costo + sportello frodi.

SOPRAVVIVENZA TOTALE: store durevole (conn-per-op, WAL, BEGIN IMMEDIATE, idem schema);
codice idempotente per (referente,tipo); registrazione atomica; firma verificata;
validatori BLINDATI; crediti scaduti esclusi; uso credito mai sotto zero ne' oltre il
dovuto; orologio iniettabile. Zero dipendenze esterne (HMAC da fase59).
"""
from __future__ import annotations

import datetime
import logging
import secrets
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from fase59_concierge import FirmaQuote

logger = logging.getLogger("core_auto.viral_loop")

GIORNO = 86400


def _intero_pos(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


@dataclass(frozen=True)
class EsitoReferral:
    ok: bool
    motivo: str = ""
    credito_referente_cents: int = 0
    credito_referee_cents: int = 0


class ViralLoopEngine:
    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], firma: FirmaQuote, *,
                 credito_referente_cents: int = 5000,
                 credito_referee_cents: int = 5000,
                 validita_giorni: int = 365,
                 orologio: Optional[Callable[[], int]] = None) -> None:
        self._conn_factory = conn_factory
        self._firma = firma
        self._cr_ref = max(0, int(credito_referente_cents))
        self._cr_ree = max(0, int(credito_referee_cents))
        self._validita = max(1, int(validita_giorni)) * GIORNO
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
                    CREATE TABLE IF NOT EXISTS referral_codici (
                        codice TEXT PRIMARY KEY,
                        referente_id TEXT NOT NULL,
                        tipo TEXT NOT NULL,
                        creato_ts TEXT NOT NULL,
                        UNIQUE (referente_id, tipo))""")
                con.execute("""
                    CREATE TABLE IF NOT EXISTS referral_eventi (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        codice TEXT NOT NULL,
                        referee_id TEXT NOT NULL,
                        tipo TEXT NOT NULL,
                        ts INTEGER NOT NULL,
                        UNIQUE (referee_id, tipo))""")
                con.execute("""
                    CREATE TABLE IF NOT EXISTS crediti (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        utente_id TEXT NOT NULL,
                        importo_cents INTEGER NOT NULL,
                        residuo_cents INTEGER NOT NULL,
                        scadenza INTEGER NOT NULL,
                        motivo TEXT NOT NULL DEFAULT '',
                        creato_ts INTEGER NOT NULL)""")
                con.execute("CREATE INDEX IF NOT EXISTS idx_crediti_utente "
                            "ON crediti(utente_id, scadenza)")
        finally:
            con.close()

    # ── codice referral (idempotente per referente+tipo) ───────────────────────
    def genera_codice(self, referente_id: str, *, tipo: str = "host") -> Optional[str]:
        if not (isinstance(referente_id, str) and referente_id.strip()):
            return None
        if tipo not in ("host", "guest"):
            return None
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            esistente = con.execute("SELECT codice FROM referral_codici WHERE "
                                    "referente_id=? AND tipo=?",
                                    (str(referente_id), tipo)).fetchone()
            if esistente is not None:
                con.execute("COMMIT")
                return esistente["codice"]
            codice = self._firma.codifica({"ref": str(referente_id), "tipo": tipo,
                                           "n": secrets.token_hex(6)})
            con.execute("INSERT INTO referral_codici (codice, referente_id, tipo, "
                        "creato_ts) VALUES (?,?,?,?)",
                        (codice, str(referente_id), tipo,
                         datetime.datetime.now().isoformat(timespec="seconds")))
            con.execute("COMMIT")
            return codice
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    # ── registrazione referee -> crediti per entrambi ──────────────────────────
    def registra_referee(self, codice: Any, referee_id: str) -> EsitoReferral:
        if self._firma.decodifica(codice) is None:
            return EsitoReferral(False, "firma_invalida")     # codice falsificato
        if not (isinstance(referee_id, str) and referee_id.strip()):
            return EsitoReferral(False, "referee_non_valido")
        ora = self._now()
        scad = ora + self._validita
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            rec = con.execute("SELECT referente_id, tipo FROM referral_codici WHERE "
                              "codice=?", (codice,)).fetchone()
            if rec is None:
                con.execute("ROLLBACK")
                return EsitoReferral(False, "codice_inesistente")
            referente, tipo = rec["referente_id"], rec["tipo"]
            if str(referee_id) == referente:
                con.execute("ROLLBACK")
                return EsitoReferral(False, "auto_referral")
            gia = con.execute("SELECT 1 FROM referral_eventi WHERE referee_id=? AND "
                              "tipo=?", (str(referee_id), tipo)).fetchone()
            if gia is not None:
                con.execute("ROLLBACK")
                return EsitoReferral(False, "gia_referito")
            con.execute("INSERT INTO referral_eventi (codice, referee_id, tipo, ts) "
                        "VALUES (?,?,?,?)", (codice, str(referee_id), tipo, ora))
            self._accredita(con, referente, self._cr_ref, scad, ora, "referral_referente")
            self._accredita(con, str(referee_id), self._cr_ree, scad, ora,
                            "referral_referee")
            con.execute("COMMIT")
            return EsitoReferral(True, "", self._cr_ref, self._cr_ree)
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    @staticmethod
    def _accredita(con: sqlite3.Connection, utente: str, importo: int, scad: int,
                   ora: int, motivo: str) -> None:
        if importo <= 0:
            return
        con.execute("INSERT INTO crediti (utente_id, importo_cents, residuo_cents, "
                    "scadenza, motivo, creato_ts) VALUES (?,?,?,?,?,?)",
                    (utente, importo, importo, scad, motivo, ora))

    # ── credito: disponibile + uso (non-cashabile, solo riduzione del dovuto) ──
    def credito_disponibile(self, utente_id: str) -> int:
        ora = self._now()
        con = self._apri()
        try:
            r = con.execute("SELECT COALESCE(SUM(residuo_cents),0) AS s FROM crediti "
                            "WHERE utente_id=? AND scadenza>? AND residuo_cents>0",
                            (str(utente_id), ora)).fetchone()
            return int(r["s"])
        finally:
            con.close()

    def usa_credito(self, utente_id: str, dovuto_cents: int) -> Dict[str, int]:
        """Applica i crediti NON SCADUTI (prima quelli che scadono prima) per ridurre il
        dovuto. Mai sotto zero, mai oltre il dovuto. Ritorna {scontato, da_pagare}."""
        if not _intero_pos(dovuto_cents):
            return {"scontato_cents": 0, "da_pagare_cents": 0}
        ora = self._now()
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            righe = con.execute(
                "SELECT id, residuo_cents FROM crediti WHERE utente_id=? AND scadenza>? "
                "AND residuo_cents>0 ORDER BY scadenza ASC, id ASC",
                (str(utente_id), ora)).fetchall()
            scontato = 0
            for r in righe:
                if scontato >= dovuto_cents:
                    break
                applica = min(r["residuo_cents"], dovuto_cents - scontato)
                con.execute("UPDATE crediti SET residuo_cents=residuo_cents-? WHERE id=?",
                            (applica, r["id"]))
                scontato += applica
            con.execute("COMMIT")
            return {"scontato_cents": scontato,
                    "da_pagare_cents": dovuto_cents - scontato}
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
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


def crea_viral_loop(percorso: str, segreto: bytes, **kw: Any) -> ViralLoopEngine:
    firma = FirmaQuote(segreto)
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return ViralLoopEngine(lambda: _ConnCondivisa(con), firma, **kw)
    return ViralLoopEngine(lambda: sqlite3.connect(percorso), firma, **kw)
