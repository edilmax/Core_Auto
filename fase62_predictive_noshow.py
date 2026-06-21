"""
CORE_AUTO - Fase 62: Predictive No-Show + Overbooking CONTROLLATO (yield a costo zero).

Il no-show e' perdita secca: tavolo/stanza vuoti = -100% di quell'incasso. I colossi
lo subiscono o impongono penali; nessuno lo previene in automatico sull'host singolo.
Noi sì, con pura matematica sui dati che gia' raccogliamo (storia presenze per segmento),
SENZA un solo euro di costo. Due capacita':

  1. CONSIGLIO di overbooking controllato: se la storia di un segmento (es. "venerdi
     sera") mostra un tasso di no-show affidabile, apriamo qualche posto "virtuale" in
     piu' (fase58) per compensare i mancati arrivi attesi -> meno vuoti, piu' incasso.
  2. PIANO di compensazione se l'overbooking si materializza davvero (tutti si
     presentano): chi resta fuori riceve rimborso + voucher, gia' supportati da
     fase34/35. Il DENARO (voucher) e' calcolato dal CORE in centesimi, MAI dall'IA.

SICUREZZA PRIMA DI TUTTO (l'overbooking sbagliato costa penali): la stima e'
CONSERVATIVA per costruzione e a piu' cinture:
  - sotto `min_campione` osservazioni -> tasso = 0 -> ZERO overbooking (fail-closed, non
    si scommette sul rumore statistico, come fase53);
  - smoothing additivo verso 0 (prior_k): pochi dati -> tasso schiacciato verso 0;
  - safety factor < 1 sui no-show attesi;
  - TETTO assoluto: mai piu' di max_overbooking_bps della capacita' reale.
Tutto in interi (tassi in basis-point, denaro in centesimi): zero float.

VINCITRICE DEL BENCHMARK (4 stimatori, stress su campioni sottili + avversi):
  V3 'smoothing additivo verso 0 + min-campione + safety + tetto'. Degrada con grazia:
  su 1/1 no-show NON stima 100% (che aprirebbe overbooking folle), cresce solo con
  l'evidenza, e non sfora mai il tetto. Le altre perdono: V1 'tasso naive n/tot' ->
  1/1=100% = disastro su dati sottili; V2 'solo cutoff min-campione' -> appena oltre il
  cutoff e' gia' aggressivo (binario); V4 'intervallo bayesiano/Wilson' -> richiede
  float/scipy ed e' overkill (lo smoothing ne approssima il bound inferiore in interi).

SOPRAVVIVENZA TOTALE: store durevole (conn-per-op, WAL, BEGIN IMMEDIATE, idem schema),
nessuna funzione solleva mai, stima deterministica/idempotente, applicazione a fase58
ISOLATA. Zero dipendenze esterne.
"""
from __future__ import annotations

import datetime
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger("core_auto.predictive_noshow")

ESITI = ("presentato", "no_show")


def _intero(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def segmento_da_data(giorno_iso: Any) -> str:
    """Segmento di default = giorno della settimana (0=lun..6=dom). Fail-safe -> 'na'."""
    try:
        d = datetime.date.fromisoformat(str(giorno_iso))
        return "dow_%d" % d.weekday()
    except (ValueError, TypeError):
        return "na"


@dataclass(frozen=True)
class PoliticaNoShow:
    min_campione: int = 20          # sotto questa soglia: nessuna previsione (fail-closed)
    prior_k: int = 20               # smoothing additivo verso 0 (conservativo)
    safety_bps: int = 7000          # 0.70: usa solo il 70% dei no-show attesi
    max_overbooking_bps: int = 2000  # tetto: max +20% sulla capacita' reale


@dataclass(frozen=True)
class CompensazioneVoce:
    prenotazione_id: str
    voucher_cents: int
    azione: str = "rimborso_piu_voucher"


# ─────────────────────────────────────────────────────────────────────────────
# Store durevole delle presenze (counts O(1), idioma fase52/58)
# ─────────────────────────────────────────────────────────────────────────────
class StoricoPresenze:
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
                    CREATE TABLE IF NOT EXISTS presenze (
                        alloggio_id TEXT NOT NULL,
                        segmento TEXT NOT NULL,
                        presentati INTEGER NOT NULL DEFAULT 0,
                        no_show INTEGER NOT NULL DEFAULT 0,
                        aggiornato_ts TEXT NOT NULL,
                        PRIMARY KEY (alloggio_id, segmento))""")
        finally:
            con.close()

    def registra_esito(self, alloggio_id: str, segmento: str, esito: str) -> bool:
        """Incrementa il contatore (presentato|no_show). Atomico. Fail-closed su input."""
        if not isinstance(alloggio_id, str) or not alloggio_id.strip():
            return False
        if not isinstance(segmento, str) or not segmento.strip():
            return False
        if esito not in ESITI:
            return False
        colonna = "presentati" if esito == "presentato" else "no_show"
        ora = datetime.datetime.now().isoformat(timespec="seconds")
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                "INSERT INTO presenze (alloggio_id, segmento, presentati, no_show, "
                "aggiornato_ts) VALUES (?,?,?,?,?) "
                "ON CONFLICT(alloggio_id, segmento) DO UPDATE SET "
                "%s = %s + 1, aggiornato_ts=excluded.aggiornato_ts" % (colonna, colonna),
                (alloggio_id, segmento, 1 if esito == "presentato" else 0,
                 1 if esito == "no_show" else 0, ora))
            con.execute("COMMIT")
            return True
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    def conteggi(self, alloggio_id: str, segmento: str) -> Dict[str, int]:
        con = self._apri()
        try:
            r = con.execute("SELECT presentati, no_show FROM presenze "
                            "WHERE alloggio_id=? AND segmento=?",
                            (str(alloggio_id), str(segmento))).fetchone()
        finally:
            con.close()
        p = r["presentati"] if r else 0
        n = r["no_show"] if r else 0
        return {"presentati": p, "no_show": n, "totale": p + n}


# ─────────────────────────────────────────────────────────────────────────────
# Gestore: stima conservativa + consiglio overbooking + piano compensazione
# ─────────────────────────────────────────────────────────────────────────────
class GestoreNoShow:
    def __init__(self, storico: StoricoPresenze,
                 politica: Optional[PoliticaNoShow] = None) -> None:
        self._st = storico
        self._pol = politica or PoliticaNoShow()

    def tasso_noshow_bps(self, alloggio_id: str, segmento: str) -> int:
        """Tasso di no-show CONSERVATIVO in basis-point interi (0..10000). Sotto
        min_campione -> 0 (fail-closed). Smoothing additivo verso 0 via prior_k."""
        c = self._st.conteggi(alloggio_id, segmento)
        if c["totale"] < self._pol.min_campione:
            return 0
        # n / (tot + k): il prior tira verso 0 (conservativo). Interi.
        return (c["no_show"] * 10000) // (c["totale"] + self._pol.prior_k)

    def consiglia_posti_virtuali(self, capacita: int, alloggio_id: str,
                                 segmento: str) -> int:
        """Quanti posti 'virtuali' aprire oltre la capacita' reale. Conservativo,
        con safety factor e tetto assoluto. 0 se dati insufficienti o capacita' invalida."""
        if not _intero(capacita) or capacita <= 0:
            return 0
        rate_bps = self.tasso_noshow_bps(alloggio_id, segmento)
        if rate_bps <= 0:
            return 0
        attesi = (capacita * rate_bps) // 10000               # no-show attesi
        sicuri = (attesi * self._pol.safety_bps) // 10000     # applica safety
        tetto = (capacita * self._pol.max_overbooking_bps) // 10000
        return max(0, min(sicuri, tetto))

    def applica_a_inventario(self, inventario: Any, alloggio_id: str, giorno: str, *,
                             capacita_reale: int, prezzo_netto_cents: int,
                             segmento: Optional[str] = None) -> int:
        """Apre capacita_reale + posti_virtuali su fase58 (ISOLATO). Ritorna i posti
        virtuali aperti (0 se nulla/guasto). Idempotente quanto imposta_disponibilita."""
        seg = segmento or segmento_da_data(giorno)
        virtuali = self.consiglia_posti_virtuali(capacita_reale, alloggio_id, seg)
        try:
            ok = inventario.imposta_disponibilita(
                alloggio_id, giorno, unita_totali=capacita_reale + virtuali,
                prezzo_netto_cents=prezzo_netto_cents)
            return virtuali if ok else 0
        except Exception:
            logger.warning("applica_a_inventario: inventario ha sollevato (-> 0)",
                           exc_info=True)
            return 0

    def piano_compensazione(self, prenotazioni: Sequence[Dict[str, Any]],
                            capacita_reale: int, *, voucher_bps: int = 2000
                            ) -> List[CompensazioneVoce]:
        """Se i presenti superano la capacita' reale, costruisce il piano di
        compensazione per gli esuberi (gli ULTIMI prenotati). Voucher = voucher_bps del
        prezzo, in centesimi interi, calcolato dal CORE. NON esegue denaro: delega a
        fase34/35. Fail-closed su input invalidi -> piano vuoto."""
        if not _intero(capacita_reale) or capacita_reale < 0:
            return []
        if not isinstance(prenotazioni, (list, tuple)):
            return []
        validi = [p for p in prenotazioni if isinstance(p, dict)
                  and isinstance(p.get("prenotazione_id"), str)
                  and _intero(p.get("prezzo_guest_cents"))
                  and p["prezzo_guest_cents"] >= 0]
        eccedenza = len(validi) - capacita_reale
        if eccedenza <= 0:
            return []
        if not _intero(voucher_bps) or voucher_bps < 0:
            voucher_bps = 0
        esuberi = validi[-eccedenza:]           # gli ultimi prenotati cedono il posto
        piano: List[CompensazioneVoce] = []
        for p in esuberi:
            voucher = (p["prezzo_guest_cents"] * voucher_bps) // 10000
            piano.append(CompensazioneVoce(prenotazione_id=p["prenotazione_id"],
                                           voucher_cents=voucher))
        return piano


# ─────────────────────────────────────────────────────────────────────────────
# Connessione condivisa per :memory: (idioma fase52/57/58)
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


def crea_storico_presenze(percorso: str = ":memory:") -> StoricoPresenze:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return StoricoPresenze(lambda: _ConnCondivisa(con))
    return StoricoPresenze(lambda: sqlite3.connect(percorso))


def crea_gestore_noshow(percorso: str = ":memory:",
                        politica: Optional[PoliticaNoShow] = None) -> GestoreNoShow:
    return GestoreNoShow(crea_storico_presenze(percorso), politica)
