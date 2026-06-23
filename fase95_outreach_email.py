"""
CORE_AUTO - Fase 95: Outreach durevole — opt-out persistente + invio email reale.

Completa fase89 (Jurisdiction Radar & Outreach) con i due pezzi mancanti per usarlo
davvero e in modo LEGALE:
  1) OPT-OUT DUREVOLE: chi si disiscrive NON deve MAI più essere contattato, neppure
     dopo un riavvio del server. fase89 teneva l'opt-out solo in RAM -> qui lo rendiamo
     persistente (file JSON, scrittura ATOMICA temp+rename, come fase94). È un OBBLIGO
     legale, non un'opzione: per questo il default è durevole.
  2) INVIO EMAIL REALE: adatta il provider SMTP (fase86) alla firma `invia(email, oggetto,
     corpo, lingua) -> bool` che il motore si aspetta. GATED: senza provider configurato
     l'invio è un no-op che ritorna False (nessuna eccezione, nessuna email).

VINCITRICE benchmark (3 varianti per lo store): RAM (persa al riavvio -> ricontatti chi si
era disiscritto = ILLEGALE, SCARTATA); sqlite (durevole ma overkill per un set di email,
SCARTATA); file-JSON atomico (VINCITRICE: durevole, semplice, niente dipendenze, atomica).

BLINDATO: niente solleva; email normalizzata (lower/strip) per confronti robusti.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any, Callable, List, Optional, Sequence

from fase89_jurisdiction_outreach import (ALLOW_LIST_DEFAULT, MotoreRadarOutreach,
                                          _email_valida)

logger = logging.getLogger("core_auto.outreach_email")


def _norm(email: Any) -> str:
    return email.strip().lower() if isinstance(email, str) else ""


# --------------------------------------------------------------- opt-out durevole
class StoreOptOut:
    """Insieme durevole di email disiscritte. Scrittura ATOMICA (temp+rename): mai un file
    mezzo-scritto. Isolato: errore in lettura -> insieme vuoto; errore in scrittura -> log."""

    def __init__(self, percorso: str) -> None:
        self._p = percorso

    def _leggi_set(self) -> set:
        try:
            with open(self._p, encoding="utf-8") as f:
                d = json.load(f) or {}
            return {_norm(e) for e in d.get("optout", []) if _norm(e)}
        except Exception:
            return set()

    def _scrivi_set(self, s: set) -> None:
        try:
            d = os.path.dirname(self._p) or "."
            fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"optout": sorted(s)}, f)
                os.replace(tmp, self._p)
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
        except Exception:
            logger.warning("StoreOptOut.scrivi fallita (ISOLATA)", exc_info=True)

    def aggiungi(self, email: str) -> bool:
        e = _norm(email)
        if not e:
            return False
        s = self._leggi_set()
        if e in s:
            return True                                # già disiscritto (idempotente)
        s.add(e)
        self._scrivi_set(s)
        return True

    def contiene(self, email: str) -> bool:
        return _norm(email) in self._leggi_set()

    def tutti(self) -> List[str]:
        return sorted(self._leggi_set())


class StoreOptOutMemoria:
    """Variante in RAM per i test (non durevole)."""
    def __init__(self, iniziali: Optional[Sequence[str]] = None) -> None:
        self._s = {_norm(e) for e in (iniziali or []) if _norm(e)}

    def aggiungi(self, email: str) -> bool:
        e = _norm(email)
        if e:
            self._s.add(e)
        return bool(e)

    def contiene(self, email: str) -> bool:
        return _norm(email) in self._s

    def tutti(self) -> List[str]:
        return sorted(self._s)


# ----------------------------------------------- motore con opt-out persistente
class MotoreOutreachDurevole(MotoreRadarOutreach):
    """Come fase89 ma l'opt-out è caricato all'avvio dallo store e ogni nuova
    disiscrizione viene SCRITTA (sopravvive al riavvio)."""

    def __init__(self, store: Any, *,
                 giurisdizioni_permesse: Sequence[str] = ALLOW_LIST_DEFAULT,
                 link_opt_out: str = "https://bookinvip.com/stop") -> None:
        super().__init__(giurisdizioni_permesse=giurisdizioni_permesse,
                         link_opt_out=link_opt_out)
        self._store = store
        for e in store.tutti():                        # preload durevole -> RAM
            super().opt_out(e)

    def opt_out(self, email: str) -> None:
        super().opt_out(email)                         # RAM (effetto immediato)
        try:
            self._store.aggiungi(email)                # disco (sopravvive al riavvio)
        except Exception:
            logger.warning("persistenza opt-out fallita (ISOLATA)", exc_info=True)


# --------------------------------------------------- adattatore invio email reale
def adatta_invio_email(email_provider: Any) -> Callable[[str, str, str, str], bool]:
    """Ritorna una funzione `invia(email, oggetto, corpo, lingua) -> bool` che usa il
    provider SMTP (fase86). GATED: senza provider -> sempre False (no-op). Mai solleva."""
    def invia(email: str, oggetto: str, corpo: str, lingua: str = "en") -> bool:
        if email_provider is None or not _email_valida(email):
            return False
        try:
            import html as _html
            corpo_html = "<div style='font-family:sans-serif;white-space:pre-wrap'>%s</div>" \
                % _html.escape(corpo)
            return bool(email_provider.invia(email, oggetto, corpo_html))
        except Exception:
            logger.warning("invio outreach fallito (ISOLATO)", exc_info=True)
            return False
    return invia


def crea_motore_outreach_durevole(*, percorso_optout: Optional[str] = None,
                                  giurisdizioni_permesse: Sequence[str] = ALLOW_LIST_DEFAULT,
                                  link_opt_out: str = "https://bookinvip.com/stop"
                                  ) -> MotoreOutreachDurevole:
    """percorso_optout -> opt-out DUREVOLE su file; altrimenti in RAM (solo dev/test)."""
    store = StoreOptOut(percorso_optout) if percorso_optout else StoreOptOutMemoria()
    return MotoreOutreachDurevole(store, giurisdizioni_permesse=giurisdizioni_permesse,
                                  link_opt_out=link_opt_out)
