"""
CORE_AUTO - Fase 131: Host payout dashboard (tracciamento incassi/payout per valuta).

Registra i movimenti del payout host (maturato a check-in, in transito, pagato) e ne riepiloga
i totali PER VALUTA (coerente fase99: mai mischiare valute). Store DUREVOLE SQLite. Importi in
unità minori intere. Stati: maturato → in_transito → pagato (o trattenuto da DAC7 fase100).
BLINDATO: errore → False/{}; transizioni di stato validate. Orologio iniettabile.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("core_auto.payout_dashboard")

STATI = ("in_attesa", "maturato", "in_transito", "pagato", "trattenuto")
_TRANSIZIONI = {
    "in_attesa": {"maturato", "trattenuto"},   # in attesa di pagamento -> pagato(maturato) o trattenuto
    "maturato": {"in_transito", "trattenuto"},
    "in_transito": {"pagato", "trattenuto"},
    "trattenuto": {"in_transito"},
    "pagato": set(),
}


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


def _pos(v: Any) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else -1


class PayoutDashboard:
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
                con.execute("""CREATE TABLE IF NOT EXISTS payout (
                    prenotazione_id TEXT PRIMARY KEY, host_id TEXT NOT NULL,
                    minori INTEGER NOT NULL, valuta TEXT NOT NULL,
                    stato TEXT NOT NULL, ts INTEGER NOT NULL)""")
                con.execute("CREATE INDEX IF NOT EXISTS ix_payout_host "
                            "ON payout(host_id)")
        finally:
            con.close()

    def registra_maturato(self, prenotazione_id: str, host_id: str, minori: int,
                          valuta: str) -> bool:
        if not (prenotazione_id and host_id and _valuta(valuta)) or _pos(minori) < 0:
            return False
        con = self._apri()
        try:
            with con:
                con.execute("INSERT OR IGNORE INTO payout (prenotazione_id, host_id, "
                            "minori, valuta, stato, ts) VALUES (?,?,?,?, 'maturato', ?)",
                            (str(prenotazione_id), str(host_id), int(minori),
                             valuta.upper(), self._now()))
            return True
        except Exception:
            logger.warning("registra_maturato fallita (ISOLATA)", exc_info=True)
            return False
        finally:
            con.close()

    def registra_in_attesa(self, prenotazione_id: str, host_id: str, minori: int,
                            valuta: str) -> bool:
        """Payout di una prenotazione NON ancora pagata (hold): stato 'in_attesa'. NON conta
        come guadagno finché il pagamento non è confermato (poi -> 'maturato') o l'hold scade
        (-> rimosso). Evita di mostrare all'host incassi da prenotazioni mai pagate."""
        if not (prenotazione_id and host_id and _valuta(valuta)) or _pos(minori) < 0:
            return False
        con = self._apri()
        try:
            with con:
                con.execute("INSERT OR IGNORE INTO payout (prenotazione_id, host_id, "
                            "minori, valuta, stato, ts) VALUES (?,?,?,?, 'in_attesa', ?)",
                            (str(prenotazione_id), str(host_id), int(minori),
                             valuta.upper(), self._now()))
            return True
        except Exception:
            logger.warning("registra_in_attesa fallita (ISOLATA)", exc_info=True)
            return False
        finally:
            con.close()

    def rimuovi(self, prenotazione_id: str) -> bool:
        """Elimina il payout di una prenotazione (hold scaduto/non pagato -> niente incasso).
        Idempotente."""
        con = self._apri()
        try:
            with con:
                con.execute("DELETE FROM payout WHERE prenotazione_id=?",
                            (str(prenotazione_id),))
            return True
        except Exception:
            logger.warning("rimuovi payout fallita (ISOLATA)", exc_info=True)
            return False
        finally:
            con.close()

    def aggiorna_stato(self, prenotazione_id: str, nuovo: str) -> bool:
        if nuovo not in STATI:
            return False
        con = self._apri()
        try:
            with con:
                r = con.execute("SELECT stato FROM payout WHERE prenotazione_id=?",
                                (str(prenotazione_id),)).fetchone()
                if not r or nuovo not in _TRANSIZIONI.get(r[0], set()):
                    return False
                con.execute("UPDATE payout SET stato=?, ts=? WHERE prenotazione_id=?",
                            (nuovo, self._now(), str(prenotazione_id)))
            return True
        except Exception:
            return False
        finally:
            con.close()

    def riepilogo(self, host_id: str) -> Dict[str, Dict[str, int]]:
        """{valuta: {stato: totale_minori, ...}, ...} per l'host."""
        con = self._apri()
        try:
            rows = con.execute("SELECT valuta, stato, SUM(minori) FROM payout "
                               "WHERE host_id=? GROUP BY valuta, stato",
                               (str(host_id),)).fetchall()
            out: Dict[str, Dict[str, int]] = {}
            for valuta, stato, tot in rows:
                out.setdefault(valuta, {})[stato] = int(tot or 0)
            return out
        except Exception:
            return {}
        finally:
            con.close()

    def conta_pagati(self, host_id: str) -> int:
        """Quante prenotazioni PAGATE ha ricevuto l'host (stati maturato/in_transito/pagato).
        Usato per la qualifica referral (l'invitato produce -> premio al referente)."""
        con = self._apri()
        try:
            r = con.execute("SELECT COUNT(*) FROM payout WHERE host_id=? AND stato IN "
                            "('maturato','in_transito','pagato')", (str(host_id),)).fetchone()
            return int(r[0]) if r else 0
        except Exception:
            return 0
        finally:
            con.close()

    def stato_di(self, prenotazione_id: Any) -> str:
        """Stato del payout di UNA prenotazione ('' se assente). Per la guardia anti-doppio
        del bonifico automatico Connect."""
        if not (isinstance(prenotazione_id, str) and prenotazione_id):
            return ""
        con = self._apri()
        try:
            r = con.execute("SELECT stato FROM payout WHERE prenotazione_id=?",
                            (prenotazione_id,)).fetchone()
            return r[0] if r else ""
        except Exception:
            return ""
        finally:
            con.close()

    def aumenta_payout(self, prenotazione_id: str, delta_cents: int) -> bool:
        """Aumenta l'incasso dell'host per una prenotazione (es. credito referral scalato ->
        meno commissione -> l'host riceve di più). delta>0. Idempotente NO: chiamare una volta."""
        d = _pos(delta_cents)
        if d <= 0:
            return False
        con = self._apri()
        try:
            with con:
                cur = con.execute("UPDATE payout SET minori=minori+?, ts=? WHERE prenotazione_id=?",
                                  (d, self._now(), str(prenotazione_id)))
            return bool(cur.rowcount)
        except Exception:
            logger.warning("aumenta_payout fallita (ISOLATA)", exc_info=True)
            return False
        finally:
            con.close()

    def info(self, prenotazione_id: Any) -> Optional[Dict[str, Any]]:
        """Il record payout di UNA prenotazione (host_id/minori/valuta/stato), None se assente.
        Serve ai flussi che devono RICOSTRUIRE il payout (es. quota host post-controversia)."""
        if not (isinstance(prenotazione_id, str) and prenotazione_id):
            return None
        con = self._apri()
        try:
            r = con.execute("SELECT prenotazione_id, host_id, minori, valuta, stato "
                            "FROM payout WHERE prenotazione_id=?", (prenotazione_id,)).fetchone()
            if r is None:
                return None
            return {"prenotazione_id": r[0], "host_id": r[1], "minori": int(r[2]),
                    "valuta": r[3], "stato": r[4]}
        except Exception:
            return None
        finally:
            con.close()

    def elenca(self, host_id: str, *, stato: Optional[str] = None,
               valuta: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        """Righe payout di un host (per l'OFFSET penali del Financial Controller
        fase177: servono le righe 'maturato' nella valuta della penale, FIFO).
        Read-only, ordine per ts crescente (le piu' vecchie si compensano prima)."""
        if not (isinstance(host_id, str) and host_id):
            return []
        lim = limit if isinstance(limit, int) and 0 < limit <= 500 else 200
        sql = "SELECT prenotazione_id, host_id, minori, valuta, stato, ts FROM payout " \
              "WHERE host_id=?"
        par: List[Any] = [host_id]
        if isinstance(stato, str) and stato:
            sql += " AND stato=?"
            par.append(stato)
        if isinstance(valuta, str) and valuta:
            sql += " AND valuta=?"
            par.append(valuta.upper())
        sql += " ORDER BY ts, prenotazione_id LIMIT ?"
        par.append(lim)
        con = self._apri()
        try:
            return [{"prenotazione_id": r[0], "host_id": r[1], "minori": int(r[2]),
                     "valuta": r[3], "stato": r[4], "ts": int(r[5])}
                    for r in con.execute(sql, par)]
        except Exception:
            logger.warning("elenca payout fallita (ISOLATA)", exc_info=True)
            return []
        finally:
            con.close()

    def imposta_importo(self, prenotazione_id: str, minori: int) -> bool:
        """Riallinea l'importo del payout alla quota DECISA per l'host (split di una
        controversia, penale trattenuta su cancellazione): il ledger deve dire quanto
        l'host riceve DAVVERO. Senza, il record restava all'importo PIENO: dashboard
        gonfiata e — per i bonifici manuali fatti da `da_pagare` — pagamento all'host
        anche della quota gia' rimborsata all'ospite (perdita reale)."""
        m = _pos(minori)
        if m <= 0 or not (isinstance(prenotazione_id, str) and prenotazione_id):
            return False
        con = self._apri()
        try:
            with con:
                cur = con.execute("UPDATE payout SET minori=?, ts=? WHERE prenotazione_id=?",
                                  (m, self._now(), prenotazione_id))
            return bool(cur.rowcount)
        except Exception:
            logger.warning("imposta_importo fallita (ISOLATA)", exc_info=True)
            return False
        finally:
            con.close()

    def da_pagare(self, host_id: str, valuta: str) -> int:
        rie = self.riepilogo(host_id).get(str(valuta).upper(), {})
        return rie.get("maturato", 0) + rie.get("in_transito", 0)


def _valuta(v: Any) -> bool:
    return isinstance(v, str) and len(v.strip()) == 3 and v.strip().isalpha()


def crea_payout_dashboard(percorso: str, *, orologio: Any = None) -> PayoutDashboard:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return PayoutDashboard(lambda: _ConnCondivisa(con), orologio=orologio)
    return PayoutDashboard(lambda: sqlite3.connect(percorso), orologio=orologio)
