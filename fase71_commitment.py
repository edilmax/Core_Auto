"""
CORE_AUTO - Fase 71: Commitment Engine (l'antidoto alla cancellazione-come-arma).

Le OTA hanno addestrato gli ospiti a cancellare: "book now, decide later", free
cancellation, deposito $0. Risultato: l'ospite prenota 3 case, ne cancella 2 all'ultimo
minuto, l'host resta col calendario bucato in alta stagione. Tre piaghe, tre antidoti
(tutti a costo zero, denaro in centesimi interi):

  1. COMMITMENT (deposito convertibile a scaglioni): l'ospite ha "pelle nel gioco" ma
     non perde tutto. Lontano dal check-in -> deposito piccolo; vicino -> pagamento
     pieno. Se cancella, il deposito diventa un VOUCHER MAGGIORATO -> lo lega a noi
     invece di bruciarlo. Host protetto, ospite incentivato (non punito).
  2. CLEANING FEE TRASPARENTE: non un "hidden fee" da $188 (margine nascosto), ma
     "costo reale + buffer" mostrato in chiaro, e ammortizzato sui soggiorni lunghi.
     L'ospite vede la matematica -> niente abbandono al checkout, niente recensione
     "hidden fee".
  3. CHARGEBACK SHIELD: raccoglie le prove di soggiorno (self check-in usato fase64,
     recensione fase63, ecc.); se ci sono tutte, il chargeback "non sono mai andato" e'
     smontabile -> l'host ha il pacchetto-evidenze pronto.

NB distinzione da fase67: li' il deposito e' per la WAITLIST (posto che potrebbe
liberarsi); qui e' l'anti-cancellazione su una PRENOTAZIONE reale. Complementari.

VINCITRICE DEL BENCHMARK (4 policy anti-cancellazione):
  V3 'deposito convertibile a scaglioni (pelle nel gioco MA voucher se cancella)'.
  Protegge l'host E non spaventa l'ospite (non perde tutto -> il voucher lo fidelizza).
  Le altre perdono: V1 'free cancellation' = l'host subisce sempre; V2 'non-rimborsabile
  secco' = spaventa l'ospite (perde tutto); V4 'penali fisse' = rigido e percepito ingiusto.
  (Idem: cleaning trasparente batte hidden-fee; evidence-package batte zero-prove.)

SOPRAVVIVENZA TOTALE: calcoli PURI e deterministici; input invalidi -> fail-closed
(zero/pagamento pieno, mai un'eccezione); denaro intero, no float; zero dipendenze.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("core_auto.commitment")

MAX_CENTS = 1_000_000_00


def _intero_nn(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


# ─────────────────────────────────────────────────────────────────────────────
# Politica
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PoliticaCommitment:
    # commitment a scaglioni (giorni al check-in)
    soglia_lontano: int = 30
    soglia_medio: int = 7
    deposito_lontano_bps: int = 1000     # 10%
    deposito_medio_bps: int = 2000       # 20%
    voucher_lontano_bps: int = 12000     # voucher = 120% del deposito
    voucher_medio_bps: int = 11500       # voucher = 115% del deposito
    # cleaning fee
    buffer_cleaning_bps: int = 12000     # fee = 120% del costo reale (buffer 20%)
    soglia_soggiorno_lungo: int = 7
    sconto_cleaning_lungo_bps: int = 2000  # -20% sui soggiorni lunghi (ammortizzato)
    # chargeback: prove richieste di default
    evidenze_richieste: Tuple[str, ...] = ("smart_pass_usato", "recensione_lasciata")


# ─────────────────────────────────────────────────────────────────────────────
# 1) Commitment (deposito convertibile a scaglioni)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CalcoloCommitment:
    tipo: str                            # 'deposito_convertibile' | 'pagamento_totale'
    prezzo_totale_cents: int
    deposito_cents: int
    saldo_a_checkin_cents: int
    voucher_se_cancella_cents: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tipo": self.tipo,
            "prezzo_totale_cents": self.prezzo_totale_cents,
            "deposito_cents": self.deposito_cents,
            "saldo_a_checkin_cents": self.saldo_a_checkin_cents,
            "voucher_se_cancella_cents": self.voucher_se_cancella_cents,
            "money_unit": "cents_integer",
        }


def calcola_commitment(prezzo_totale_cents: int, giorni_a_check_in: int, *,
                       politica: Optional[PoliticaCommitment] = None) -> CalcoloCommitment:
    """Deposito convertibile a scaglioni. BLINDATO: input invalidi -> pagamento totale
    (fail-closed: nel dubbio, massima protezione host)."""
    pol = politica or PoliticaCommitment()
    if not (_intero_nn(prezzo_totale_cents) and 0 < prezzo_totale_cents <= MAX_CENTS):
        return CalcoloCommitment("pagamento_totale", 0, 0, 0, 0)
    if not _intero_nn(giorni_a_check_in):
        giorni_a_check_in = 0

    if giorni_a_check_in > pol.soglia_lontano:
        dep_bps, vou_bps = pol.deposito_lontano_bps, pol.voucher_lontano_bps
    elif giorni_a_check_in > pol.soglia_medio:
        dep_bps, vou_bps = pol.deposito_medio_bps, pol.voucher_medio_bps
    else:
        # vicino al check-in: pagamento pieno, nessuna conversione
        return CalcoloCommitment("pagamento_totale", prezzo_totale_cents,
                                 prezzo_totale_cents, 0, 0)

    deposito = (prezzo_totale_cents * dep_bps) // 10000
    if deposito <= 0:
        return CalcoloCommitment("pagamento_totale", prezzo_totale_cents,
                                 prezzo_totale_cents, 0, 0)
    voucher = (deposito * vou_bps) // 10000
    saldo = prezzo_totale_cents - deposito
    return CalcoloCommitment("deposito_convertibile", prezzo_totale_cents,
                             deposito, saldo, voucher)


# ─────────────────────────────────────────────────────────────────────────────
# 2) Cleaning fee trasparente + dinamica
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CalcoloCleaning:
    fee_cents: int
    costo_reale_cents: int
    buffer_cents: int
    sconto_lungo_cents: int
    durata_notti: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "fee_cents": self.fee_cents,
            "costo_reale_cents": self.costo_reale_cents,
            "buffer_cents": self.buffer_cents,
            "sconto_lungo_cents": self.sconto_lungo_cents,
            "durata_notti": self.durata_notti,
            "money_unit": "cents_integer",
        }


def calcola_cleaning_fee(costo_reale_cents: int, durata_notti: int, *,
                         politica: Optional[PoliticaCommitment] = None) -> CalcoloCleaning:
    """Fee = costo reale + buffer, mostrata in chiaro; sconto sui soggiorni lunghi
    (ammortizzata). BLINDATO: input invalidi -> fee 0."""
    pol = politica or PoliticaCommitment()
    if not (_intero_nn(costo_reale_cents) and costo_reale_cents > 0) \
            or not _intero_nn(durata_notti):
        return CalcoloCleaning(0, costo_reale_cents if _intero_nn(costo_reale_cents) else 0,
                               0, 0, durata_notti if _intero_nn(durata_notti) else 0)
    fee_base = (costo_reale_cents * pol.buffer_cleaning_bps) // 10000
    buffer = fee_base - costo_reale_cents
    sconto = 0
    if durata_notti >= pol.soglia_soggiorno_lungo and pol.sconto_cleaning_lungo_bps > 0:
        sconto = (fee_base * pol.sconto_cleaning_lungo_bps) // 10000
    fee = max(0, fee_base - sconto)
    return CalcoloCleaning(fee, costo_reale_cents, buffer, sconto, durata_notti)


# ─────────────────────────────────────────────────────────────────────────────
# 3) Chargeback shield (pacchetto evidenze)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class EsitoChargeback:
    protetto: bool
    evidenze: List[str]
    mancanti: List[str]

    def as_dict(self) -> Dict[str, Any]:
        return {"protetto": self.protetto, "evidenze": self.evidenze,
                "mancanti": self.mancanti}


def valuta_chargeback(checklist: Any, *,
                      richieste: Optional[Sequence[str]] = None,
                      politica: Optional[PoliticaCommitment] = None) -> EsitoChargeback:
    """Verifica le prove di soggiorno. 'protetto' se TUTTE le prove richieste sono
    presenti (=True). BLINDATO: checklist non-dict -> a rischio con tutte mancanti."""
    pol = politica or PoliticaCommitment()
    chiavi = tuple(richieste) if richieste is not None else pol.evidenze_richieste
    if not isinstance(checklist, dict):
        return EsitoChargeback(False, [], list(chiavi))
    evidenze = [k for k in chiavi if checklist.get(k) is True]
    mancanti = [k for k in chiavi if checklist.get(k) is not True]
    return EsitoChargeback(not mancanti, evidenze, mancanti)
