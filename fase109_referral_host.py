"""
CORE_AUTO - Fase 109: Referral host-porta-host (bonus crediti non-cashabili).

Un host iscritto ne invita altri: codice FIRMATO (riusa fase59.FirmaQuote). Quando il
referee si QUALIFICA (prima prenotazione), il referrer riceve un BONUS in crediti a scaglioni
(più ne porta, più vale). Crediti NON-CASHABILI: usabili solo come sconto sulla commissione
(niente payout → account falsi inutili). Anti-frode: no auto-referral, dedup referee.
Store DUREVOLE (file JSON atomico) o in-RAM. BLINDATO: errore → no-op/0.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fase59_concierge import FirmaQuote

logger = logging.getLogger("core_auto.referral_host")

# scaglioni (conteggio_qualificati_<=, bonus_cents): più referee qualificati, più bonus.
TIERS_DEFAULT: Tuple[Tuple[int, int], ...] = ((3, 1000), (9, 1500), (10 ** 9, 2000))


class ReferralHost:
    def __init__(self, segreto: bytes, percorso: str = "", *,
                 tiers: Sequence[Tuple[int, int]] = TIERS_DEFAULT) -> None:
        self._firma = FirmaQuote(segreto)
        self._p = percorso
        self._tiers = tuple(tiers)
        self._mem: Dict[str, Any] = {}

    def _leggi(self) -> Dict[str, Any]:
        if not self._p:
            return self._mem
        try:
            with open(self._p, encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def _scrivi(self, d: Dict[str, Any]) -> None:
        if not self._p:
            self._mem = d
            return
        try:
            dn = os.path.dirname(self._p) or "."
            fd, tmp = tempfile.mkstemp(dir=dn, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(d, f)
                os.replace(tmp, self._p)
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
        except Exception:
            logger.warning("ReferralHost._scrivi fallita (ISOLATA)", exc_info=True)

    def _bonus(self, n_qualificati: int) -> int:
        for soglia, val in self._tiers:
            if n_qualificati <= soglia:
                return int(val)
        return 0

    def genera_codice(self, host_id: str) -> Optional[str]:
        if not host_id:
            return None
        return self._firma.codifica({"ref_host": str(host_id)})

    def registra_referral(self, codice: Any, nuovo_host_id: str) -> bool:
        d = self._leggi()
        dec = self._firma.decodifica(codice) if isinstance(codice, str) else None
        referrer = dec.get("ref_host") if isinstance(dec, dict) else None
        if not (referrer and nuovo_host_id) or referrer == nuovo_host_id:
            return False                                  # firma rotta / auto-referral
        ref = d.setdefault("referral", {})
        if str(nuovo_host_id) in ref:
            return False                                  # referee già associato (dedup)
        ref[str(nuovo_host_id)] = {"referrer": str(referrer), "qualificato": False}
        self._scrivi(d)
        return True

    def conferma_qualifica(self, nuovo_host_id: str) -> int:
        """Referee fa la prima prenotazione → bonus al referrer. Ritorna il bonus (0 se n/a)."""
        d = self._leggi()
        rec = d.get("referral", {}).get(str(nuovo_host_id))
        if not isinstance(rec, dict) or rec.get("qualificato"):
            return 0
        rec["qualificato"] = True
        referrer = rec["referrer"]
        n = sum(1 for r in d.get("referral", {}).values()
                if r.get("referrer") == referrer and r.get("qualificato"))
        bonus = self._bonus(n)
        crediti = d.setdefault("crediti", {})
        crediti[referrer] = int(crediti.get(referrer, 0)) + bonus
        self._scrivi(d)
        return bonus

    def crediti(self, host_id: str) -> int:
        return int(self._leggi().get("crediti", {}).get(str(host_id), 0))

    def usa_credito(self, host_id: str, importo_cents: int) -> int:
        """Applica crediti (non-cashabili) come sconto. Ritorna quanto applicato."""
        d = self._leggi()
        disp = int(d.get("crediti", {}).get(str(host_id), 0))
        chiesto = max(0, int(importo_cents)) if isinstance(importo_cents, int) and \
            not isinstance(importo_cents, bool) else 0
        usato = min(disp, chiesto)
        if usato > 0:
            d.setdefault("crediti", {})[str(host_id)] = disp - usato
            self._scrivi(d)
        return usato


def crea_referral_host(segreto: bytes, percorso: str = "", *,
                       tiers: Sequence[Tuple[int, int]] = TIERS_DEFAULT) -> ReferralHost:
    return ReferralHost(segreto, percorso, tiers=tiers)
