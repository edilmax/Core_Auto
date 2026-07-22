"""
CORE_AUTO - Fase 188: "Paga in Struttura" — calcolo ANTICIPO online + SALDO in loco.

STRATEGIA (fondatore + analisi collaudata sui colossi, 2026-07-22):
L'ospite che sceglie "paga in struttura" versa un ANTICIPO online (deposito) e il SALDO
in struttura all'host. L'anticipo:

  1. COPRE SEMPRE LA COMMISSIONE (rampa 0/8/10% per anzianità host, fase98) -> BookinVIP
     la incassa SUBITO dalla carta, zero rischio di non essere pagata (meglio di Booking,
     che fattura l'host a fine mese e mangia i default).
  2. HA UN MINIMO (5.00) + una quota gateway MINIMA che coprono il COSTO FISSO di Stripe
     (~0.25-0.41) anche su 1 sola notte o carta extra-UE -> BookinVIP NON ci perde mai
     (l'obiezione del fondatore: "su 1 notte le commissioni bancarie prosciugano il margine").
  3. RESTA "PREZZO PULITO": l'ospite paga il TOTALE del soggiorno (anticipo + saldo), ZERO
     fee-ospite. Il costo gateway lo ASSORBE l'HOST (identica logica della tariffa tecnica
     3%: l'host paga il gateway anche a commissione 0%). NIENTE surcharge carte extra-UE
     (vietato in UE + auto-gol sulla fiducia: lo assorbe il minimo).
  4. E' NON RIMBORSABILE in caso di cancellazione volontaria dell'ospite (anti no-show,
     stile Hostelworld).

CONSERVAZIONE (invariante): anticipo + saldo == prezzo del soggiorno. host_incassa ==
prezzo - commissione - gateway (l'host assorbe il gateway). Tutto in UNITA' MINORI INTERE
(cents), MAI float. Calcolo PURO: niente rete, niente Stripe, niente stato -> testabile a
tavolino. Il gateway/incasso reale li muove il money-path (fase85/160/162); qui si decide
solo QUANTO addebitare online e QUANTO resta da pagare in loco.
"""
from __future__ import annotations

from typing import Any, Dict

# Soglie (unita' minori intere della valuta dell'alloggio).
DEPOSITO_MINIMO_CENTS = 500        # anticipo minimo: 5.00 (blindaggio soggiorni brevi/economici)
DEPOSITO_PER_NOTTE_CENTS = 150     # 1.50 a notte
# Il gateway che l'host assorbe DEVE coprire il costo Stripe del CASO PEGGIORE (carta
# extra-UE/commerciale ~ 0.25 fisso + 3.25%): se coprissimo solo il 3% "tariffa tecnica",
# sul deposito grande il 3% < 3.25% e BookinVIP ci perderebbe la differenza (l'obiezione del
# fondatore, verificata dal test). Quindi: fisso 0.30 + 3.5% (margine sul 3.25%), mai < 0.50.
GATEWAY_MINIMO_CENTS = 50          # 0.50: copre il FISSO Stripe su addebiti piccoli
GATEWAY_FISSO_CENTS = 30           # 0.30: quota fissa (copre il fisso Stripe ~0.25 + margine)
GATEWAY_BPS = 350                  # 3.5%: copre il 3.25% extra-UE (caso peggiore) + margine


def _intero(v: Any, default: int = 0) -> int:
    try:
        if isinstance(v, bool):
            return default
        return int(v)
    except (TypeError, ValueError):
        return default


def calcola(prezzo_cents: Any, notti: Any, commissione_cents: Any, *,
            psp_bps: int = 300,
            deposito_minimo_cents: int = DEPOSITO_MINIMO_CENTS,
            deposito_per_notte_cents: int = DEPOSITO_PER_NOTTE_CENTS,
            gateway_minimo_cents: int = GATEWAY_MINIMO_CENTS,
            gateway_fisso_cents: int = GATEWAY_FISSO_CENTS,
            gateway_bps: int = GATEWAY_BPS) -> Dict[str, int]:
    """Ritorna la ripartizione 'paga in struttura' per UN soggiorno.

    Input: prezzo TOTALE del soggiorno (cents), numero notti, commissione gia' calcolata
    dalla rampa (cents, 0 nei primi 90 giorni). psp_bps = tariffa tecnica/gateway (300 = 3%).

    Output (tutti cents interi):
      anticipo_online_cents  -> quanto si addebita SUBITO sulla carta (deposito, non rimborsabile)
      saldo_in_loco_cents    -> quanto l'ospite paga all'host in struttura (== prezzo - anticipo)
      commissione_cents      -> ricavo BookinVIP (invariato, la rampa sul prezzo pieno)
      gateway_cents          -> costo gateway coperto dall'anticipo, a carico HOST
      host_incassa_cents     -> netto host = prezzo - commissione - gateway
      di_cui_da_anticipo_cents -> parte del netto host che arriva dall'anticipo (via escrow)
                                  (il resto, il saldo_in_loco, l'host lo prende in contanti)
    Robusto: input assurdi -> valori coerenti, mai negativi, mai solleva."""
    prezzo = max(0, _intero(prezzo_cents))
    n = max(1, _intero(notti, 1))
    comm = min(prezzo, max(0, _intero(commissione_cents)))       # la commissione non supera il prezzo
    bps = max(0, _intero(psp_bps, 300))

    base = max(deposito_minimo_cents, deposito_per_notte_cents * n)

    def _gw(dep: int) -> int:
        # gateway = copre il costo Stripe caso PEGGIORE (fisso + 3.5% > 3.25% extra-UE), mai
        # sotto il minimo, mai sotto la tariffa tecnica psp. L'host lo assorbe (come il 3%).
        per_stripe = gateway_fisso_cents + dep * gateway_bps // 10000
        per_psp = bps * dep // 10000
        return max(gateway_minimo_cents, per_stripe, per_psp)

    # l'anticipo deve coprire base, E commissione + gateway (cosi' BookinVIP incassa entrambi
    # dall'addebito online). Il gateway dipende dall'anticipo -> una passata di assestamento.
    anticipo = max(base, comm + _gw(base))
    anticipo = max(base, comm + _gw(anticipo))
    # non si addebita online piu' del prezzo: soggiorno cifra piccola -> anticipo = tutto
    anticipo = min(anticipo, prezzo)
    gateway = _gw(anticipo)
    # su un prezzo minuscolo, commissione+gateway potrebbero superare l'anticipo=prezzo: si
    # comprime il gateway (poi la commissione) entro l'anticipo, l'host non va mai negativo.
    gateway = min(gateway, max(0, anticipo - comm))
    if comm + gateway > anticipo:
        comm = max(0, anticipo - gateway)

    saldo = prezzo - anticipo
    host_incassa = prezzo - comm - gateway
    di_cui_da_anticipo = anticipo - comm - gateway               # >= 0 per costruzione

    return {
        "anticipo_online_cents": anticipo,
        "saldo_in_loco_cents": saldo,
        "commissione_cents": comm,
        "gateway_cents": gateway,
        "host_incassa_cents": host_incassa,
        "di_cui_da_anticipo_cents": di_cui_da_anticipo,
        "notti": n,
    }
