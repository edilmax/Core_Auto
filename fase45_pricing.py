"""
CORE_AUTO - Fase 45: Motore delle PROPOSTE del Core (M3) - lo split a 3 vie.

FONDE M1 (PoliticaCommerciale) + M2 (PoliticaPrezzo) per costruire la proposta di
disintermediazione. Idea: passando dall'OTA (commissione alta) a Mango (commissione
bassa) si libera un SURPLUS S = commissione_OTA - commissione_Mango (sul prezzo di
riferimento P_o). Vincitrice del benchmark (4 varianti x 10 stress test): UNICAMENTE
V3 'bilanciato 3-vie', che ripartisce S tra GUEST (sconto), HOST (margine extra) e
MANGO (sostenibilita'), col flywheel completo. Le altre 3 (tutto-guest, tutto-host,
greedy-Mango) lasciano sempre qualcuno senza incentivo -> scartate.

Conservazione esatta: prezzo_guest == netto_host + incasso_mango (centesimi, mai
float, largest-remainder). Fail-closed: se Mango non e' competitivo (S<0) o l'host
netterebbe sotto il suo floor (M2) -> CircuitBreakerProposta (autopreservazione).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from typing import List

from fase17_money import valida_split
from fase43_commissione import BPS_DENOM, commissione_cents, ConfigMotore
from fase44_prezzo import PoliticaPrezzo


class CircuitBreakerProposta(Exception):
    """Autopreservazione: la proposta viola i parametri di sicurezza (Mango non
    competitivo, o host sotto il suo floor). Il motore BLOCCA (fail-closed)."""


def _int_non_neg(v, nome):
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        raise ValueError(f"{nome} deve essere int >= 0")
    return v


def ripartisci_esatto(totale: int, quote_bps) -> List[int]:
    """Ripartisce 'totale' centesimi secondo quote_bps (somma 10000), conservando
    OGNI centesimo (largest-remainder, mai float)."""
    _int_non_neg(totale, "totale")
    raw = [Decimal(totale) * Decimal(q) / Decimal(BPS_DENOM) for q in quote_bps]
    fl = [int(r.to_integral_value(rounding=ROUND_FLOOR)) for r in raw]
    resto = totale - sum(fl)
    ordine = sorted(range(len(raw)), key=lambda i: raw[i] - fl[i], reverse=True)
    for k in range(resto):
        fl[ordine[k]] += 1
    return fl


@dataclass(frozen=True)
class PoliticaSplit3Vie:
    """Vincitrice V3: ripartizione del surplus tra guest/host/Mango (somma 10000 bps)."""
    quota_guest_bps: int = 4000
    quota_host_bps: int = 4000
    quota_mango_bps: int = 2000

    def __post_init__(self):
        for nome in ("quota_guest_bps", "quota_host_bps", "quota_mango_bps"):
            _int_non_neg(getattr(self, nome), nome)
        if self.quota_guest_bps + self.quota_host_bps + self.quota_mango_bps != BPS_DENOM:
            raise ValueError("le quote devono sommare a 10000 bps")

    def quote(self) -> tuple:
        return (self.quota_guest_bps, self.quota_host_bps, self.quota_mango_bps)


@dataclass(frozen=True)
class ContestoProposta:
    """Riferimento di mercato per la proposta. prezzo_ota_cents = P_o (prezzo OTA);
    comm_ota_bps = commissione OTA stimata (dato di mercato)."""
    prezzo_ota_cents: int
    comm_ota_bps: int

    def __post_init__(self):
        _int_non_neg(self.prezzo_ota_cents, "prezzo_ota_cents")
        if (not isinstance(self.comm_ota_bps, int) or isinstance(self.comm_ota_bps, bool)
                or not (0 <= self.comm_ota_bps < BPS_DENOM)):
            raise ValueError("comm_ota_bps deve essere int in [0,10000)")


@dataclass(frozen=True)
class Proposta:
    """Proposta a 3 vie. Invariante: prezzo_guest == netto_host + incasso_mango."""
    prezzo_ota_cents: int
    prezzo_guest_cents: int
    netto_host_cents: int
    incasso_mango_cents: int
    risparmio_guest_cents: int           # P_o - P_g  (quanto risparmia l'ospite vs OTA)
    guadagno_host_cents: int             # N_h - N_o  (quanto guadagna l'host vs OTA)
    surplus_cents: int                   # S = commissione_OTA - commissione_Mango
    prezzo_host_autoritativo_cents: int  # da M2 (tariffa dinamica host)


class MotoreProposte:
    """Fonde M1 (commissione) + M2 (prezzo host) ripartendo il surplus a 3 vie."""

    def __init__(self, cfg_motore: ConfigMotore, pol_split: PoliticaSplit3Vie,
                 pol_prezzo: PoliticaPrezzo):
        self.cfg = cfg_motore
        self.split = pol_split
        self.prezzo = pol_prezzo

    def componi(self, ctx_proposta: ContestoProposta, stato, metriche,
                ctx_prezzo) -> Proposta:
        P_o = ctx_proposta.prezzo_ota_cents
        C_ota = commissione_cents(P_o, ctx_proposta.comm_ota_bps)
        C_mango = self.cfg.politica.commissione_cents(P_o, stato, metriche)   # M1
        S = C_ota - C_mango
        if S < 0:
            raise CircuitBreakerProposta(
                f"Mango non competitivo: commissione {C_mango} > OTA {C_ota}")
        g, h, mq = ripartisci_esatto(S, self.split.quote())
        prezzo_guest = P_o - g
        incasso_mango = C_mango + mq
        netto_host = prezzo_guest - incasso_mango
        netto_host_ota = P_o - C_ota
        # M2: prezzo autoritativo host + floor di sicurezza (l'host non netta MAI sotto)
        esito = self.prezzo.risolvi(ctx_prezzo)
        if esito.stato != "ok":
            raise CircuitBreakerProposta("host non disponibile (M2 nosale)")
        if netto_host < ctx_prezzo.floor_host_cents:
            raise CircuitBreakerProposta(
                f"netto host {netto_host} sotto il floor {ctx_prezzo.floor_host_cents}")
        valida_split(prezzo_guest, incasso_mango, netto_host)   # conservazione esatta
        return Proposta(P_o, prezzo_guest, netto_host, incasso_mango,
                        P_o - prezzo_guest, netto_host - netto_host_ota, S,
                        esito.prezzo_cents)


def politica_split_da_config(d: dict) -> PoliticaSplit3Vie:
    campi = ("quota_guest_bps", "quota_host_bps", "quota_mango_bps")
    return PoliticaSplit3Vie(**{k: d[k] for k in campi if k in d})
