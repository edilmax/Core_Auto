"""
CORE_AUTO - Fase 49: Ponte verso il Booking (M7) - l'aggancio sicuro.

Ultimo mattone Mango: quando una conversazione CONVERTE, il satellite commerciale
trasforma l'accordo in una prenotazione REALE + link di pagamento riusando ESATTAMENTE
la porta gia' collaudata da fase40: `MotorePrenotazioni.crea` +
`ServizioPagamenti.crea_link_pagamento`. Questo modulo e' l'UNICO touchpoint col
denaro dello strato Mango: Mango propone, il nucleo booking decide e incassa.

PRINCIPIO FERREO (come fase17/27/40/45): il DENARO non si delega MAI all'IA. Gli
importi arrivano gia' calcolati dal CORE (la `Proposta` di fase45, in centesimi
interi) e qui vengono solo INSTRADATI, mai inventati.

Vincitrice del benchmark (4 varianti x 10 stress test concorrenti, at-least-once):
V4 'cache + lock-per-chiave con double-check'. Sotto 64 worker che agganciano la
STESSA conversione, crea ESATTAMENTE una prenotazione per chiave (zero prenotazioni
doppie, zero link orfani) e su conversioni DISTINTE non serializza (42x piu' veloce
del lock globale). Le altre 3 (naive / cache-senza-lock / lock-globale) o martellano
il nucleo con create duplicate (TOCTOU) o serializzano tutto il throughput.

SOPRAVVIVENZA TOTALE:
  - default-OFF (feature-flag `abilitato`/env CORE_PONTE_BOOKING): spento, il ponte
    NON tocca prenotazioni/pagamenti (il motore booking non sa che Mango esiste);
  - fail-closed sugli importi: incasso_mango > prezzo_guest o prezzo<=0 -> niente
    prenotazione; se la `crea` fallisce NON si genera MAI un link (zero orfani);
  - input corrotti -> ValueError nel dataclass (centesimi int>=0, niente bool/float);
  - idempotenza esattamente-una-volta per `chiave_conversione` (cache esiti ok +
    lock-per-chiave) -> consegna at-least-once gestita; thread-safe.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional

from fase34_prenotazioni import RichiestaPrenotazione

logger = logging.getLogger("core_auto.ponte_booking")

_ENV_FLAG = "CORE_PONTE_BOOKING"


class PonteBookingError(Exception):
    """Errore di configurazione del ponte (dipendenze obbligatorie mancanti)."""


def _int_non_neg(v, nome):
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        raise ValueError(f"{nome} deve essere int >= 0")
    return v


@dataclass(frozen=True)
class DatiConversione:
    """Cio' che serve per agganciare una conversazione convertita al booking.
    Gli importi (CENTESIMI) provengono dal CORE (Proposta, fase45), MAI dall'IA.
    `chiave_conversione` = chiave di idempotenza (es. id conversazione)."""
    chiave_conversione: str
    alloggio_id: str
    check_in: str                 # 'YYYY-MM-DD'
    check_out: str                # 'YYYY-MM-DD'
    email: str
    prezzo_guest_cents: int       # quanto paga l'ospite (= importo totale)
    incasso_mango_cents: int      # commissione del Core (la quota host e' il resto)
    ospite_nome: str = ""
    ospite_telefono: str = ""
    origine: str = "mango"

    def __post_init__(self):
        if not self.chiave_conversione:
            raise ValueError("chiave_conversione obbligatoria (idempotenza)")
        _int_non_neg(self.prezzo_guest_cents, "prezzo_guest_cents")
        _int_non_neg(self.incasso_mango_cents, "incasso_mango_cents")

    @classmethod
    def da_proposta(cls, proposta: Any, *, chiave_conversione: str, alloggio_id: str,
                    check_in: str, check_out: str, email: str, ospite_nome: str = "",
                    ospite_telefono: str = "", origine: str = "mango") -> "DatiConversione":
        """Costruisce i dati da una `Proposta` (fase45): il denaro arriva gia'
        calcolato dal motore proposte, qui non si tocca un solo centesimo."""
        return cls(
            chiave_conversione=chiave_conversione, alloggio_id=alloggio_id,
            check_in=check_in, check_out=check_out, email=email,
            prezzo_guest_cents=proposta.prezzo_guest_cents,
            incasso_mango_cents=proposta.incasso_mango_cents,
            ospite_nome=ospite_nome, ospite_telefono=ospite_telefono, origine=origine)


@dataclass(frozen=True)
class EsitoConversione:
    ok: bool
    # "agganciata"|"disattivato"|"dati_non_validi"|"importi_non_validi"
    # |"non_disponibile"|"date_non_valide"|"errore"
    azione: str
    prenotazione_id: Optional[int] = None
    pagamento_id: Optional[int] = None
    payment_url: Optional[str] = None
    idempotente: bool = False     # True se restituito dalla cache (replay at-least-once)
    messaggio: str = ""


class PonteBooking:
    """Instrada una conversione verso il nucleo booking. Default-OFF; idempotente
    esattamente-una-volta per chiave (V4: cache esiti ok + lock-per-chiave)."""

    def __init__(self, motore: Any, servizio: Any, *,
                 abilitato: Optional[bool] = None) -> None:
        if motore is None or servizio is None:
            raise PonteBookingError("motore e servizio pagamenti sono obbligatori")
        self._motore = motore
        self._servizio = servizio
        self._abilitato = (os.environ.get(_ENV_FLAG) == "1"
                           if abilitato is None else bool(abilitato))
        self._cache: Dict[str, EsitoConversione] = {}   # solo esiti OK
        self._lock_globale = threading.Lock()
        self._lock_per_chiave: Dict[str, threading.Lock] = {}

    @property
    def abilitato(self) -> bool:
        return self._abilitato

    def _lock_chiave(self, chiave: str) -> threading.Lock:
        with self._lock_globale:
            lk = self._lock_per_chiave.get(chiave)
            if lk is None:
                lk = threading.Lock()
                self._lock_per_chiave[chiave] = lk
            return lk

    def aggancia(self, dati: DatiConversione) -> EsitoConversione:
        """Crea prenotazione + link pagamento riusando la porta sicura. Fail-closed
        su ogni anomalia; idempotente per `chiave_conversione`; thread-safe."""
        if not self._abilitato:
            return EsitoConversione(False, "disattivato",
                                    messaggio="Ponte booking disattivato (default-off).")

        # fast-path senza lock: replay di una conversione gia' agganciata
        cached = self._cache.get(dati.chiave_conversione)
        if cached is not None:
            return self._replay(cached)

        if not (dati.alloggio_id and dati.check_in and dati.check_out and dati.email):
            return EsitoConversione(False, "dati_non_validi",
                                    messaggio="Servono alloggio, date ed email.")

        # DENARO DAL CORE (mai dall'IA): commissione Tavola/Mango = incasso_mango;
        # quota host (partner) = resto. Fail-closed se gli importi non tornano.
        importo = dati.prezzo_guest_cents
        commissione = dati.incasso_mango_cents
        if importo <= 0 or commissione > importo:
            return EsitoConversione(False, "importi_non_validi",
                                    messaggio="Importi incoerenti (fail-closed).")

        with self._lock_chiave(dati.chiave_conversione):
            cached = self._cache.get(dati.chiave_conversione)   # double-check
            if cached is not None:
                return self._replay(cached)
            esito = self._esegui(dati, importo, commissione)
            if esito.ok:
                self._cache[dati.chiave_conversione] = esito
            return esito

    def _esegui(self, dati: DatiConversione, importo: int,
                commissione: int) -> EsitoConversione:
        esito = self._motore.crea(RichiestaPrenotazione(
            alloggio_id=dati.alloggio_id, ospite_nome=dati.ospite_nome,
            ospite_email=dati.email, check_in=dati.check_in, check_out=dati.check_out,
            importo_totale_cents=importo, commissione_cents=commissione,
            origine=dati.origine, ospite_telefono=dati.ospite_telefono))

        if not getattr(esito, "ok", False):
            motivo = getattr(esito, "motivo", "errore")
            azione = motivo if motivo in ("non_disponibile", "date_non_valide",
                                          "importi_non_validi") else "errore"
            return EsitoConversione(False, azione,
                                    messaggio=f"Prenotazione non creata: {motivo}.")

        # Solo ORA (prenotazione creata) si genera il link: nessun pagamento orfano.
        link = self._servizio.crea_link_pagamento(
            pagamento_id=esito.pagamento_id, importo_cents=importo, email=dati.email)
        return EsitoConversione(
            True, "agganciata", prenotazione_id=esito.prenotazione_id,
            pagamento_id=esito.pagamento_id, payment_url=getattr(link, "url", None),
            messaggio="Prenotazione agganciata, link di pagamento pronto.")

    @staticmethod
    def _replay(cached: EsitoConversione) -> EsitoConversione:
        return EsitoConversione(
            cached.ok, cached.azione, cached.prenotazione_id, cached.pagamento_id,
            cached.payment_url, idempotente=True, messaggio=cached.messaggio)


def crea_ponte_booking(motore: Any, servizio: Any, *,
                       abilitato: Optional[bool] = None) -> PonteBooking:
    """Factory del ponte. `abilitato=None` -> legge l'env CORE_PONTE_BOOKING
    (default-off): il satellite commerciale resta innocuo finche' non lo accendi."""
    return PonteBooking(motore, servizio, abilitato=abilitato)
