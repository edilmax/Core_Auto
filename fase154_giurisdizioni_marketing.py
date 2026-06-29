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


def _restr(paese: str, legge: str, intensita: int = 10) -> RegoleMarketing:
    """Paese NOTO ma a regime opt-in DURO (niente cold, neanche B2B): trappole reali."""
    return RegoleMarketing(paese, OPT_IN, OPT_IN, OPT_IN, False, True, legge, intensita)


def _b2b(paese: str, legge: str, intensita: int) -> RegoleMarketing:
    """Mercato dove il cold email B2B a indirizzo business PUBBLICO con opt-out e' difendibile
    (esenzione B2B / enforcement debole-nascente): UN messaggio rilevante, basso volume.
    NON e' spam di massa ne' verso consumatori. SMS/WhatsApp restano opt-in."""
    return RegoleMarketing(paese, OPT_OUT, OPT_IN, OPT_IN, True, True, legge, intensita)


# Mezzi SEMPRE leciti, ovunque (l'host viene da TE -> niente consenso da chiedere):
MEZZI_SEMPRE_LECITI = ("inbound_seo", "social_organico", "link_diretto_host", "referral",
                       "annunci_a_pagamento")


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
    # --- ASIA EST: opt-out (tecniche piu' forti dove lecito) ---
    "HK": RegoleMarketing("HK", OPT_OUT, OPT_IN, OPT_IN, True, True, "PDPO + UEMO (opt-out)", 58),
    "TW": RegoleMarketing("TW", OPT_OUT, OPT_IN, OPT_IN, True, True, "PDPA Taiwan", 48),
    # --- AMERICHE: opt-out ---
    "MX": RegoleMarketing("MX", OPT_OUT, OPT_IN, OPT_IN, True, True, "LFPDPPP (opt-out)", 50),
    "AR": RegoleMarketing("AR", OPT_OUT, OPT_IN, OPT_IN, True, True, "Ley 25.326 (opt-out)", 38),
    "CL": RegoleMarketing("CL", OPT_OUT, OPT_IN, OPT_IN, True, True, "Ley 19.628 (opt-out)", 38),
    # --- SUD-EST ASIATICO (turismo in forte crescita): B2B pubblico + opt-out OK ---
    "TH": _b2b("TH", "PDPA TH (B2B pubblico + opt-out)", 50),
    "VN": _b2b("VN", "PDPD VN (B2B pubblico + opt-out)", 48),
    "PH": _b2b("PH", "DPA PH (B2B pubblico + opt-out)", 48),
    "ID": _b2b("ID", "PDP Law ID (B2B pubblico + opt-out)", 50),
    "MY": _b2b("MY", "PDPA MY (B2B pubblico + opt-out)", 46),
    "KH": _b2b("KH", "Cambogia (B2B pubblico, regime nascente)", 45),
    "LA": _b2b("LA", "Laos (B2B pubblico, regime nascente)", 40),
    # --- ASIA SUD / AFRICA / AMERICHE: enforcement debole -> B2B pubblico + opt-out ---
    "PK": _b2b("PK", "PK (B2B pubblico)", 35),
    "BD": _b2b("BD", "BD (B2B pubblico)", 35),
    "LK": _b2b("LK", "PDPA LK (B2B pubblico)", 35),
    "NG": _b2b("NG", "NDPR (B2B pubblico)", 38),
    "KE": _b2b("KE", "DPA KE (B2B pubblico)", 36),
    "EG": _b2b("EG", "PDPL EG (B2B pubblico)", 34),
    "CO": _b2b("CO", "Habeas Data CO (B2B pubblico)", 36),
    # --- TRAPPOLE REALI: opt-in DURO (puniscono anche il B2B) -> usa ALTRI MEZZI ---
    "CN": _restr("CN", "PIPL + Advertising Law (consenso, enforcement duro)", 5),
    "KR": _restr("KR", "PIPA + Network Act (opt-in stretto, label obbligatoria)", 5),
    "CA": _restr("CA", "CASL (danni per-email, opt-in espresso)", 8),
    "IL": _restr("IL", "Spam Law Amend.40 (danni statutari per-email)", 6),
    "BR": _restr("BR", "LGPD (ANPD attiva)", 12),
    "TR": _restr("TR", "KVKK + registro IYS obbligatorio", 8),
    "SA": _restr("SA", "CITC anti-spam", 8),
    "AE": _restr("AE", "TDRA / regolato", 12),
    "QA": _restr("QA", "regolato", 8),
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


def strategia_paese(iso: Any) -> Dict[str, Any]:
    """Cosa fare per acquisire host in QUEL paese: email a freddo dove lecito (B2B pubblico +
    opt-out), e SEMPRE i mezzi senza-consenso (l'host viene da te). 'Spingi ovunque, ma con lo
    strumento giusto per la nazione.'"""
    r = regole_paese(iso)
    freddi = canali_permessi(iso)
    return {
        "paese": r.paese,
        "cold_email_lecito": "email" in freddi,
        "canali_a_freddo": freddi,                 # dove puoi contattare per primo
        "altri_mezzi_sempre": list(MEZZI_SEMPRE_LECITI),  # leciti anche in UE/CN/KR
        "legge": r.legge,
        "intensita": r.intensita,
    }
