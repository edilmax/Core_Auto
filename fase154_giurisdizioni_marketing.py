"""
CORE_AUTO - Fase 154: Database GIURISDIZIONI MARKETING mondiale (compliance per nazione).

BookinVIP e' MONDIALE, non europeo. Le regole su email/SMS/WhatsApp a freddo cambiano per
paese: in USA l'email B2B a freddo e' LECITA con opt-out (CAN-SPAM) -> tecnica piu' potente;
in UE serve CONSENSO preventivo (GDPR/ePrivacy) -> niente cold. Questo modulo codifica il
regime per nazione e dice, per ogni canale, se si puo' contattare a freddo.

Regola d'oro: FAIL-CLOSED. Paese sconosciuto -> regime PIU' RESTRITTIVO (niente cold). Mai
inventare un permesso. Stati per canale:
  'opt_out'  = cold LECITO se fornisci disiscrizione (il regime "potente").
  'opt_in'   = serve consenso PREVENTIVO -> niente cold (bloccato).
  'vietato'  = mai.

NB: modello operativo SEMPLIFICATO, NON consulenza legale. Verificare con un legale prima di
campagne reali. Denaro: nessuno qui (solo regole). Vincitrice-del-benchmark: tabella dati +
default restrittivo, zero I/O, deterministica.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

OPT_OUT = "opt_out"
OPT_IN = "opt_in"
VIETATO = "vietato"


@dataclass(frozen=True)
class RegoleMarketing:
    paese: str
    email_b2b: str
    sms: str
    whatsapp: str
    dati_pubblici_business: bool
    opt_out_obbligatorio: bool
    legge: str
    intensita: int            # 0..100: quanto ci si puo' spingere (informativo)


# Regime piu' restrittivo: usato per ogni paese sconosciuto (FAIL-CLOSED).
DEFAULT_RESTRITTIVO = RegoleMarketing("??", OPT_IN, OPT_IN, OPT_IN, False, True,
                                      "sconosciuta -> regime restrittivo", 0)

# Stati UE/EEA + CH: GDPR/ePrivacy -> consenso preventivo (niente cold).
_UE_EEA = ("AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU",
           "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES",
           "SE", "NO", "IS", "LI", "CH")


def _ue(paese: str) -> RegoleMarketing:
    return RegoleMarketing(paese, OPT_IN, OPT_IN, OPT_IN, False, True,
                           "GDPR + ePrivacy (consenso preventivo)", 10)


REGOLE: Dict[str, RegoleMarketing] = {p: _ue(p) for p in _UE_EEA}
REGOLE.update({
    # Regimi 'opt-out' (cold B2B lecito con disiscrizione) = le tecniche piu' potenti.
    "US": RegoleMarketing("US", OPT_OUT, OPT_IN, OPT_IN, True, True, "CAN-SPAM / TCPA", 85),
    "GB": RegoleMarketing("GB", OPT_OUT, OPT_IN, OPT_IN, True, True, "PECR (B2B corporate)", 65),
    "AU": RegoleMarketing("AU", OPT_OUT, OPT_IN, OPT_IN, True, True, "Spam Act (B2B published)", 55),
    "NZ": RegoleMarketing("NZ", OPT_OUT, OPT_IN, OPT_IN, True, True, "UEM Act (B2B)", 55),
    "SG": RegoleMarketing("SG", OPT_OUT, OPT_IN, OPT_IN, True, True, "PDPA (business)", 50),
    "ZA": RegoleMarketing("ZA", OPT_OUT, OPT_IN, OPT_IN, True, True, "POPIA / ECTA", 45),
    "JP": RegoleMarketing("JP", OPT_OUT, OPT_IN, OPT_IN, True, True, "Anti-Spam (B2B published)", 45),
    "IN": RegoleMarketing("IN", OPT_OUT, OPT_IN, OPT_IN, True, True, "IT Act (DLT per SMS)", 50),
    # Regimi 'opt-in' espliciti (niente cold).
    "CA": RegoleMarketing("CA", OPT_IN, OPT_IN, OPT_IN, False, True, "CASL (consenso espresso)", 10),
    "BR": RegoleMarketing("BR", OPT_IN, OPT_IN, OPT_IN, False, True, "LGPD", 15),
    "AE": RegoleMarketing("AE", OPT_IN, OPT_IN, OPT_IN, False, True, "TDRA / regolato", 15),
})


def regole_paese(iso: Any) -> RegoleMarketing:
    """Regole del paese (ISO-2). Sconosciuto -> DEFAULT_RESTRITTIVO (fail-closed)."""
    if not isinstance(iso, str) or len(iso.strip()) != 2:
        return DEFAULT_RESTRITTIVO
    return REGOLE.get(iso.strip().upper(), DEFAULT_RESTRITTIVO)


def _stato_canale(r: RegoleMarketing, canale: str) -> str:
    return {"email": r.email_b2b, "sms": r.sms, "whatsapp": r.whatsapp}.get(
        str(canale).lower(), VIETATO)


def puo_contattare_a_freddo(iso: Any, canale: str = "email") -> Tuple[bool, str]:
    """True solo se il canale e' 'opt_out' nel paese (cold lecito con disiscrizione)."""
    r = regole_paese(iso)
    stato = _stato_canale(r, canale)
    if stato == OPT_OUT:
        return True, r.legge
    return False, ("%s: %s richiede %s" % (r.paese, canale, stato))


def canali_permessi(iso: Any) -> List[str]:
    """Canali su cui il cold outreach e' lecito (opt-out) nel paese. Vuoto se nessuno."""
    r = regole_paese(iso)
    return [c for c in ("email", "sms", "whatsapp") if _stato_canale(r, c) == OPT_OUT]


def giurisdizioni_consentite(canale: str = "email") -> List[str]:
    """Tutti i paesi dove il cold outreach su quel canale e' lecito (opt-out). Ordinati per
    intensita' DESC (prima i mercati dove si puo' spingere di piu')."""
    permessi = [(iso, r) for iso, r in REGOLE.items()
                if _stato_canale(r, canale) == OPT_OUT]
    permessi.sort(key=lambda x: -x[1].intensita)
    return [iso for iso, _ in permessi]
