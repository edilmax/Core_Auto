"""
CORE_AUTO - Fase 188: "Paga in Struttura" — calcolo ANTICIPO online + SALDO in loco.

STRATEGIA (fondatore, decisa 2026-07-22 dopo analisi dei colossi):
Due modi di pagare, e la differenza e' voluta e TRASPARENTE (si mostrano ENTRAMBI i prezzi):

  - PAGA ONLINE  -> PREZZO PULITO (0% fee ospite): e' qui che teniamo la coerenza del brand,
    ed e' l'opzione consigliata (soldi in garanzia da noi, protezione totale).
  - PAGA IN STRUTTURA -> l'ospite paga un po' di PIU' (una fee di servizio, 1.50/notte), come
    fa Booking (in struttura costa qualche euro in piu' che online). L'host incassa UGUALE: il
    sovrapprezzo lo paga l'ospite che sceglie la comodita' di pagare di persona. Sono briciole,
    ma e' giusto guadagnare qualcosa su un servizio in piu' (e piu' rischioso) per noi.

COSA PRENDIAMO ONLINE (subito, dalla carta, tutto nostro):
  1. la NOSTRA COMMISSIONE (rampa 0/8/10% per anzianita' host, fase98) -> incassata SUBITO,
     zero rischio di non essere pagati (meglio di Booking che fattura l'host a fine mese);
  2. la FEE di servizio paga-in-struttura (1.50/notte, a carico OSPITE);
  3. la COPERTURA CARTA (costo Stripe del caso peggiore extra-UE + 30c di sicurezza), assorbita
     dall'host come la tariffa tecnica 3% -> BookinVIP NON ci perde MAI, nemmeno su 1 notte con
     carta straniera (l'obiezione del fondatore, verificata dal test).

Il SALDO (prezzo - quello che abbiamo preso noi) lo paga l'ospite all'host, DI PERSONA. Quei
soldi non passano mai da noi -> in caso di disputa NON possiamo rimborsarli (lo diciamo chiaro
nel box trasparenza): la nostra garanzia vale solo su cio' che incassiamo online. NIENTE giro
storto: l'host prende il suo netto DIRETTAMENTE in loco, noi non gli restituiamo nulla.

Invarianti: ospite_paga_totale == prezzo + fee; anticipo_online + saldo_in_loco == ospite_paga
_totale; host_incassa == prezzo - commissione - gateway (== saldo, tutto diretto, mai negativo).
Tutto in UNITA' MINORI INTERE. Calcolo PURO: niente rete/Stripe/stato -> testabile a tavolino.
"""
from __future__ import annotations

from typing import Any, Dict

# Soglie (unita' minori intere della valuta dell'alloggio).
FEE_PER_NOTTE_CENTS = 150          # sovrapprezzo OSPITE per il paga-in-struttura: 1.50/notte
# La copertura carta che l'host assorbe DEVE coprire il costo Stripe del CASO PEGGIORE (carta
# extra-UE ~ 0.25 fisso + 3.25%), PIU' 30c di sicurezza (voluti dal fondatore): fisso 0.55
# (0.25 Stripe + 0.30 sicurezza) + 3.25%. Cosi' BookinVIP non ci perde mai. Mai < 0.50.
GATEWAY_MINIMO_CENTS = 50          # 0.50: pavimento su addebiti piccoli
GATEWAY_FISSO_CENTS = 55           # 0.55 = 0.25 fisso Stripe + 0.30 sicurezza
GATEWAY_BPS = 325                  # 3.25%: il caso peggiore extra-UE


def _intero(v: Any, default: int = 0) -> int:
    try:
        if isinstance(v, bool):
            return default
        return int(v)
    except (TypeError, ValueError):
        return default


def calcola(prezzo_cents: Any, notti: Any, commissione_cents: Any, *,
            psp_bps: int = 300,
            fee_per_notte_cents: int = FEE_PER_NOTTE_CENTS,
            gateway_minimo_cents: int = GATEWAY_MINIMO_CENTS,
            gateway_fisso_cents: int = GATEWAY_FISSO_CENTS,
            gateway_bps: int = GATEWAY_BPS) -> Dict[str, int]:
    """Ripartizione 'paga in struttura' per UN soggiorno (tutti cents interi).

    Input: prezzo TOTALE del soggiorno (== prezzo online pulito), notti, commissione gia'
    calcolata dalla rampa (0 nei primi 90 giorni). Output:
      ospite_paga_totale_cents -> quanto paga l'ospite scegliendo 'in struttura' (= prezzo + fee)
      anticipo_online_cents    -> addebitato SUBITO sulla carta (commissione + fee + carta) = tutto nostro
      saldo_in_loco_cents      -> pagato all'host di persona (== ospite_paga_totale - anticipo)
      commissione_cents        -> ricavo BookinVIP (rampa sul prezzo)
      fee_cents                -> sovrapprezzo ospite per il servizio (ricavo BookinVIP)
      gateway_cents            -> copertura carta assorbita dall'HOST
      host_incassa_cents       -> netto host = prezzo - commissione - gateway (tutto dal saldo, diretto)
      noi_incassiamo_cents     -> commissione + fee (il gateway copre Stripe, non e' ricavo)
    Robusto: input assurdi -> valori coerenti, mai negativi, mai solleva."""
    prezzo = max(0, _intero(prezzo_cents))
    n = max(1, _intero(notti, 1))
    comm = min(prezzo, max(0, _intero(commissione_cents)))       # la commissione non supera il prezzo
    bps = max(0, _intero(psp_bps, 300))
    fee = max(0, _intero(fee_per_notte_cents, 0)) * n            # a carico OSPITE
    ospite_totale = prezzo + fee

    def _gw(addebito: int) -> int:
        # copre il costo Stripe caso PEGGIORE (fisso+sicurezza + 3.25% extra-UE), mai sotto il
        # minimo, mai sotto la tariffa tecnica psp. L'host lo assorbe (come il 3%).
        per_stripe = gateway_fisso_cents + addebito * gateway_bps // 10000
        per_psp = bps * addebito // 10000
        return max(gateway_minimo_cents, per_stripe, per_psp)

    # anticipo online = commissione + fee + copertura carta (tutto nostro). Il gateway dipende
    # dall'anticipo: e' un PUNTO FISSO (anticipo = comm + fee + _gw(anticipo)). Iterando converge
    # in pochi passi (l'incremento cala di ~3,25% a passo); iterare invece di fare 2 sole passate
    # rende il gateway ESATTO a QUALSIASI grandezza -> niente sotto-copertura di Stripe nemmeno
    # su prenotazioni enormi (bug provato dal test P0 a 1M: 2 passate lasciavano un buco di ~2€).
    anticipo = comm + fee + _gw(comm + fee)
    for _ in range(8):
        nuovo = comm + fee + _gw(anticipo)
        if nuovo == anticipo:
            break
        anticipo = nuovo
    anticipo = min(anticipo, ospite_totale)                     # mai piu' del totale (prezzi minuscoli)
    gateway = _gw(anticipo)
    # su un totale minuscolo comm+fee+gateway potrebbero superare l'anticipo: si comprime prima
    # il gateway, poi la fee, poi la commissione, entro l'anticipo. L'host non va mai negativo.
    gateway = min(gateway, max(0, anticipo - comm - fee))
    if comm + fee + gateway > anticipo:
        fee = max(0, anticipo - comm - gateway)
    if comm + fee + gateway > anticipo:
        comm = max(0, anticipo - fee - gateway)

    saldo = ospite_totale - anticipo
    host_incassa = prezzo - comm - gateway                      # == saldo (tutto diretto in loco)
    noi_incassiamo = comm + fee

    return {
        "ospite_paga_totale_cents": ospite_totale,
        "anticipo_online_cents": anticipo,
        "saldo_in_loco_cents": saldo,
        "commissione_cents": comm,
        "fee_cents": fee,
        "gateway_cents": gateway,
        "host_incassa_cents": host_incassa,
        "noi_incassiamo_cents": noi_incassiamo,
        "notti": n,
    }
