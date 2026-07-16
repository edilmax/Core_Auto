"""
CORE_AUTO - Fase 127: Check-in digitale guest (pre-registrazione + sblocco verificabile).

Flusso pre-arrivo: il guest compila i dati ospiti (nome/documento) entro la finestra; il
sistema emette un ESITO firmato (riusa fase64 smart-pass per lo sblocco porta). Verifica
documenti minima (formato), conteggio ospiti vs capacità, completamento obbligatorio prima
dello sblocco. Store DUREVOLE SQLite. Orologio iniettabile. BLINDATO: errore → esito negato.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("core_auto.checkin_digitale")

_DOC = re.compile(r"^[A-Za-z0-9]{5,20}$")


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


def valida_ospiti(ospiti: Any, capacita: int) -> Optional[List[Dict[str, str]]]:
    """Lista ospiti valida (nome + documento formattato) entro capacità. None se invalida."""
    if not isinstance(ospiti, (list, tuple)) or not ospiti:
        return None
    cap = capacita if isinstance(capacita, int) and not isinstance(capacita, bool) else 0
    if cap > 0 and len(ospiti) > cap:
        return None
    out = []
    for o in ospiti:
        if not isinstance(o, dict):
            return None
        nome = str(o.get("nome", "")).strip()
        doc = str(o.get("documento", "")).strip()
        if not (2 <= len(nome) <= 80 and _DOC.match(doc)):
            return None
        out.append({"nome": nome[:80], "documento": doc})
    return out


class CheckinDigitale:
    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], emettitore_pass: Any,
                 *, orologio: Optional[Callable[[], int]] = None) -> None:
        self._cf = conn_factory
        self._pass = emettitore_pass            # fase64: .emetti(prenotazione, alloggio, ...)
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
                con.execute("""CREATE TABLE IF NOT EXISTS checkin (
                    prenotazione_id TEXT PRIMARY KEY, alloggio_id TEXT NOT NULL,
                    ospiti_json TEXT NOT NULL, ts INTEGER NOT NULL,
                    completato INTEGER NOT NULL DEFAULT 1,
                    revocato INTEGER NOT NULL DEFAULT 0)""")
                # migrazione: aggiungi 'revocato' su schemi vecchi (tombstone della cancellazione)
                try:
                    con.execute("ALTER TABLE checkin ADD COLUMN revocato INTEGER NOT NULL DEFAULT 0")
                except sqlite3.OperationalError:
                    pass
        finally:
            con.close()

    def pre_registra(self, prenotazione_id: str, alloggio_id: str, ospiti: Any,
                     capacita: int) -> Dict[str, Any]:
        if not (prenotazione_id and alloggio_id):
            return {"ok": False, "errore": "id_mancante"}
        val = valida_ospiti(ospiti, capacita)
        if val is None:
            return {"ok": False, "errore": "ospiti_non_validi"}
        con = self._apri()
        try:
            # ATOMICO (BEGIN IMMEDIATE) + TOMBSTONE: se la prenotazione e' stata REVOCATA
            # (cancellata/rimborsata) il check-in NON si puo' (ri)creare -> chiude la TOCTOU
            # in cui una pre_registra in volo re-inseriva DOPO la revoca (BUG provato in
            # concorrenza: 40/40). La cancellazione e' terminale: il tombstone e' permanente.
            with con:
                con.execute("BEGIN IMMEDIATE")
                r = con.execute("SELECT revocato FROM checkin WHERE prenotazione_id=?",
                                (str(prenotazione_id),)).fetchone()
                if r is not None and int(r[0] if not hasattr(r, "keys") else r["revocato"]):
                    return {"ok": False, "errore": "prenotazione_cancellata"}
                con.execute("INSERT OR REPLACE INTO checkin (prenotazione_id, alloggio_id, "
                            "ospiti_json, ts, completato, revocato) VALUES (?,?,?,?,1,0)",
                            (str(prenotazione_id), str(alloggio_id),
                             json.dumps(val), self._now()))
            return {"ok": True, "ospiti": len(val)}
        except Exception:
            logger.warning("pre_registra fallita (ISOLATA)", exc_info=True)
            return {"ok": False, "errore": "interno"}
        finally:
            con.close()

    def completato(self, prenotazione_id: str) -> bool:
        con = self._apri()
        try:
            r = con.execute("SELECT completato FROM checkin WHERE prenotazione_id=?",
                            (str(prenotazione_id),)).fetchone()
            return bool(r and r[0])
        except Exception:
            return False
        finally:
            con.close()

    def revoca(self, prenotazione_id: Any) -> bool:
        """REVOCA il check-in (prenotazione cancellata/rimborsata): elimina la riga -> lo
        smart-pass non e' piu' emettibile (`completato` torna False) E i dati degli ospiti
        pre-registrati spariscono (niente ospiti-fantasma nell'export Alloggiati, privacy).
        Idempotente e isolata. Va chiamata da OGNI percorso di cancellazione: senza, un
        ospite che fa check-in e poi cancella (o viene rimborsato) mantiene il pass valido
        -> sblocco porta indebito quando c'e' una serratura vera (BUG provato in concorrenza)."""
        if not (isinstance(prenotazione_id, str) and prenotazione_id):
            return False
        con = self._apri()
        try:
            # TOMBSTONE PERMANENTE (non semplice DELETE): completato=0 + revocato=1. Cosi'
            # una pre_registra concorrente che tenta di (ri)creare la riga DOPO la revoca
            # viene respinta dal check `revocato` (in BEGIN IMMEDIATE) invece di resuscitare
            # il check-in. INSERT-or-UPDATE: vale anche se la revoca precede ogni check-in.
            with con:
                con.execute("BEGIN IMMEDIATE")
                con.execute(
                    "INSERT INTO checkin (prenotazione_id, alloggio_id, ospiti_json, ts, "
                    "completato, revocato) VALUES (?, '', '[]', ?, 0, 1) "
                    "ON CONFLICT(prenotazione_id) DO UPDATE SET completato=0, revocato=1",
                    (str(prenotazione_id), self._now()))
            return True
        except Exception:
            logger.warning("revoca check-in fallita (ISOLATA)", exc_info=True)
            return False
        finally:
            con.close()

    def sblocca(self, prenotazione_id: str, alloggio_id: str,
                **kw: Any) -> Optional[str]:
        """Emette lo smart-pass (fase64) SOLO se il check-in è completato. None altrimenti."""
        if not self.completato(prenotazione_id):
            return None
        try:
            return self._pass.emetti(prenotazione_id, alloggio_id, **kw)
        except Exception:
            logger.warning("emissione pass fallita (ISOLATA)", exc_info=True)
            return None


def crea_checkin_digitale(percorso: str, emettitore_pass: Any, *,
                          orologio: Any = None) -> CheckinDigitale:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return CheckinDigitale(lambda: _ConnCondivisa(con), emettitore_pass,
                               orologio=orologio)
    return CheckinDigitale(lambda: sqlite3.connect(percorso), emettitore_pass,
                           orologio=orologio)
