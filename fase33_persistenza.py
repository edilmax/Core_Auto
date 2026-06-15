"""
CORE_AUTO - Fase 33 / BLOCCO 3: Stato conversazionale DUREVOLE e cross-worker.

Chiude un anello debole esposto dalla rivalutazione globale: la
`MemoriaConversazioni` (FASE 31) vive in RAM di UN processo -> sotto gunicorn
multi-worker (e a ogni restart) l'agente ha AMNESIA: turno 1 al worker A, turno 2
al worker B che non ricorda nulla. Il multi-turno, in produzione, non funziona.

`MemoriaConversazioniDurevole` (drop-in: stessa interfaccia, si innesta
nell'`AgenteConversazionale` senza modifiche) persiste i turni in modo DUREVOLE e
CROSS-WORKER (Datastore condiviso, SQLite/Postgres come nonce/idempotency/Outbox).

Strategia = **Variante C "cache + append durevole"**, vincitrice di un benchmark
a 4 (write-through-RMW / write-behind / cache+append / append+ricostruzione) sotto
carico estremo multi-worker (150 chat x 17 turni, 8 worker concorrenti):
- DURABILITA': il write-behind perde la coda non flushata su crash -> SCARTATO.
- CORRETTEZZA CROSS-WORKER: ogni turno e' un INSERT append committato; un worker
  fresco (o dopo restart) RICOSTRUISCE lo stato dal DB.
- COSTO: l'append (1 INSERT/turno) evita il read-modify-write sotto lock del
  write-through (piu' veloce, niente contesa); una cache LRU in-RAM (semantica
  Variante D: ancora-intento + ring recente) rende le LETTURE dei caldi O(1).

La memoria resta LIMITATA su DUE dimensioni come la FASE 31: il ring (potatura dei
turni vecchi per chat, preservando l'ancora) e la cache LRU (numero di chat calde).
"""
from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, List, Optional

from fase23_datastore import get_datastore
from fase30_llm import Messaggio

logger = logging.getLogger("core_auto.persistenza")

_TABELLA = "memoria_conversazioni"


@dataclass
class _Sessione:
    """Vista in-RAM di una chat: ancora-intento + ring recente (cache di lettura)."""
    ancora: Optional[Messaggio] = None
    recenti: Deque[Messaggio] = field(default_factory=deque)
    inserimenti: int = 0  # contatore per potatura ammortizzata


class MemoriaConversazioniDurevole:
    """Storico per-destinatario DUREVOLE e cross-worker (Variante C). Stessa
    interfaccia di `MemoriaConversazioni` (registra/cronologia/dimentica/
    num_sessioni) -> drop-in per `AgenteConversazionale`.

    Durabilita': ogni turno e' un INSERT append committato sul Datastore. Letture:
    cache LRU in-RAM (ancora + ring); cache-miss -> ricostruzione dal DB (cosi' un
    worker fresco/dopo-restart riprende la conversazione). Memoria limitata: ring
    per-chat (potatura) + LRU sul numero di chat calde."""

    def __init__(self, *, max_turni: int = 12, max_cache: int = 256,
                 datastore: Any = None, location: Optional[str] = None,
                 pota_ogni: Optional[int] = None) -> None:
        if max_turni <= 0 or max_cache <= 0:
            raise ValueError("max_turni e max_cache devono essere > 0")
        self._ds = datastore or get_datastore(location)
        self._max_turni = max_turni
        self._max_cache = max_cache
        self._pota_ogni = pota_ogni or (max_turni * 4)
        self._cache: "OrderedDict[str, _Sessione]" = OrderedDict()
        self._cl = threading.Lock()
        self._init_schema()

    # --- schema (idempotente, dialetto-portabile) ---
    def _init_schema(self) -> None:
        with self._ds.connection() as conn:
            self._ds.execute(conn,
                f"CREATE TABLE IF NOT EXISTS {_TABELLA} ("
                f"id {self._ds.autoincrement_pk()}, "
                f"conv TEXT NOT NULL, ruolo TEXT NOT NULL, "
                f"contenuto TEXT NOT NULL, creato_a TIMESTAMP NOT NULL)")
            self._ds.execute(conn,
                f"CREATE INDEX IF NOT EXISTS ix_{_TABELLA}_conv "
                f"ON {_TABELLA}(conv, id)")
            conn.commit()

    # --- scrittura ---
    def registra(self, destinatario: str, ruolo: str, contenuto: str) -> None:
        """Append DUREVOLE del turno + aggiornamento cache. Su prima-toccata di
        una chat gia' esistente nel DB, la sessione viene RICOSTRUITA prima (cosi'
        l'ancora-intento storica e' preservata, non sovrascritta dal turno nuovo)."""
        msg = Messaggio(ruolo, contenuto)  # valida il ruolo
        with self._cl:
            presente = destinatario in self._cache
        sessione = None if presente else self._carica_sessione(destinatario)

        with self._ds.transaction() as conn:
            self._ds.execute(conn,
                f"INSERT INTO {_TABELLA}(conv, ruolo, contenuto, creato_a) "
                f"VALUES(?, ?, ?, {self._ds.now_expr()})",
                (destinatario, ruolo, contenuto))

        potatura = False
        with self._cl:
            s = self._cache.get(destinatario)
            if s is None:
                s = sessione if sessione is not None else _Sessione(
                    recenti=deque(maxlen=self._max_turni))
                self._cache[destinatario] = s
            self._cache.move_to_end(destinatario)
            if s.ancora is None and ruolo == "user":
                s.ancora = msg  # primo turno utente = intento (immune al ring)
            s.recenti.append(msg)
            s.inserimenti += 1
            potatura = (s.inserimenti % self._pota_ogni == 0)
            while len(self._cache) > self._max_cache:
                self._cache.popitem(last=False)  # sfratta la chat piu' idle
        if potatura:
            self._pota(destinatario)

    # --- lettura ---
    def cronologia(self, destinatario: str,
                   system: Optional[str] = None) -> List[Messaggio]:
        """[system] + [ancora-intento] + turni-recenti. Cache-hit O(1); miss ->
        ricostruzione dal DB (riprende una chat su un worker fresco o dopo restart)."""
        with self._cl:
            s = self._cache.get(destinatario)
            if s is not None:
                self._cache.move_to_end(destinatario)
                return self._costruisci(s, system)
        s = self._carica_sessione(destinatario)
        with self._cl:
            esistente = self._cache.get(destinatario)
            if esistente is not None:
                s = esistente
            else:
                self._cache[destinatario] = s
                while len(self._cache) > self._max_cache:
                    self._cache.popitem(last=False)
            self._cache.move_to_end(destinatario)
            return self._costruisci(s, system)

    def _costruisci(self, s: _Sessione, system: Optional[str]) -> List[Messaggio]:
        out: List[Messaggio] = []
        if system:
            out.append(Messaggio("system", system))
        # dedup per VALORE: l'ancora ricostruita dal DB e' un oggetto diverso ma
        # uguale a un elemento del ring quando la chat e' ancora corta.
        if s.ancora is not None and s.ancora not in s.recenti:
            out.append(s.ancora)
        out.extend(s.recenti)
        return out

    def _carica_sessione(self, destinatario: str) -> _Sessione:
        """Ricostruisce ancora (primo turno utente) + ultimi `max_turni` dal DB."""
        s = _Sessione(recenti=deque(maxlen=self._max_turni))
        with self._ds.connection() as conn:
            anc = self._ds.execute(conn,
                f"SELECT ruolo, contenuto FROM {_TABELLA} WHERE conv=? "
                f"AND ruolo='user' ORDER BY id ASC LIMIT 1", (destinatario,)).fetchone()
            righe = self._ds.execute(conn,
                f"SELECT ruolo, contenuto FROM {_TABELLA} WHERE conv=? "
                f"ORDER BY id DESC LIMIT ?", (destinatario, self._max_turni)).fetchall()
        if anc is not None:
            s.ancora = Messaggio(anc["ruolo"], anc["contenuto"])
        for r in reversed(righe):  # da DESC a ordine cronologico
            s.recenti.append(Messaggio(r["ruolo"], r["contenuto"]))
        return s

    def _pota(self, destinatario: str) -> None:
        """Potatura durevole: conserva l'ancora (primo turno utente) + gli ultimi
        `max_turni`; cancella il mezzo -> righe-per-chat LIMITATE anche a lungo termine."""
        with self._ds.transaction() as conn:
            self._ds.execute(conn,
                f"DELETE FROM {_TABELLA} WHERE conv=? "
                f"AND id <> (SELECT MIN(id) FROM {_TABELLA} WHERE conv=? AND ruolo='user') "
                f"AND id NOT IN (SELECT id FROM {_TABELLA} WHERE conv=? "
                f"ORDER BY id DESC LIMIT ?)",
                (destinatario, destinatario, destinatario, self._max_turni))

    # --- manutenzione / osservabilita' ---
    def dimentica(self, destinatario: str) -> None:
        with self._ds.transaction() as conn:
            self._ds.execute(conn, f"DELETE FROM {_TABELLA} WHERE conv=?",
                             (destinatario,))
        with self._cl:
            self._cache.pop(destinatario, None)

    def num_sessioni(self) -> int:
        """Numero di chat DISTINTE persistite (autoritativo, dal DB)."""
        with self._ds.connection() as conn:
            row = self._ds.execute(conn,
                f"SELECT COUNT(DISTINCT conv) AS n FROM {_TABELLA}").fetchone()
        return int(row["n"]) if row else 0


def crea_memoria_conversazioni(*, durevole: Optional[bool] = None,
                               max_turni: int = 12, max_cache: int = 256,
                               location: Optional[str] = None) -> Any:
    """Factory feature-flag (contratto d'isolamento): ritorna la memoria DUREVOLE
    se CONV_MEMORY_DURABLE e' acceso (o durevole=True), altrimenti la
    `MemoriaConversazioni` in-RAM (FASE 31). DEFAULT-OFF: spento => comportamento
    attuale identico. Import lazy della in-RAM per non accoppiare i moduli."""
    if durevole is None:
        durevole = os.environ.get("CONV_MEMORY_DURABLE", "").strip().lower() \
            in ("1", "true", "yes", "on")
    if durevole:
        return MemoriaConversazioniDurevole(max_turni=max_turni, max_cache=max_cache,
                                            location=location)
    from fase31_conversazione import MemoriaConversazioni
    return MemoriaConversazioni(max_sessioni=max_cache, max_turni=max_turni)
