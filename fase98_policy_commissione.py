"""
CORE_AUTO - Fase 98: Policy commissione (Regola primi-1000-host + split asimmetrico 3%/12%).

Esegue due moduli dello studio finanziario [[bookinvip-architettura-finanziaria]]:
  - REGOLA 1 (primi 1000 host): la commissione dipende dall'ORDINALE di registrazione
    dell'host (da fase88.numero_host). I primi `soglia` (1000) host = tariffa fondatori
    (15%); oltre = tariffa post-fondatori (configurabile; default ANCORA 15% finché non si
    decide). Funzione PURA + blindata: input ignoto/non valido → tariffa standard (mai 0).
  - MODULO 4 (commissione asimmetrica): il 15% totale si ripartisce host 3% + ospite 12%.
    L'host trattiene poco (copre i costi carta, bassa barriera d'ingresso), l'ospite paga la
    guest service fee (stile Airbnb). CONSERVAZIONE ESATTA al centesimo: quanto incassiamo =
    host_fee + guest_fee; quanto paga l'ospite = prezzo + guest_fee; quanto prende l'host =
    prezzo - host_fee. Niente float, solo centesimi interi (per-valuta, valuta-agnostico).

PURO (nessun I/O, nessuna dipendenza): tutto testabile. La % totale resta 15% sia come
commissione piatta (`commissione_bps_per_host`) sia come split (`ripartisci_host_guest`,
host_bps+guest_bps=1500). Nessuna regola fiscale qui (quelle sono gated altrove).
"""
from __future__ import annotations

from typing import Any, Dict

# Parametri della strategia (configurabili dal chiamante; default = blindatura 15%).
SOGLIA_FONDATORI = 1000          # i primi N host
BPS_FONDATORI = 1500             # 15% per i fondatori
BPS_DOPO = 1500                  # post-fondatori: default uguale (l'utente deciderà)
HOST_BPS = 300                   # 3% trattenuto all'host
GUEST_BPS = 1200                 # 12% aggiunto all'ospite  (3% + 12% = 15%)
# Tariffa PER FONTE (modello 0% ospite, commissione DEDOTTA dall'host):
BPS_DIRETTO = 500                # 5% sulle prenotazioni DIRETTE dell'host (no-loss: copre Stripe)
BPS_MARKETPLACE = 1500           # 15% sulle prenotazioni portate da BookinVIP (vetrina/SEO)


def _intero(v: Any, default: int = 0) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else default


def commissione_bps_per_host(numero_host: Any, *, bps_fondatori: int = BPS_FONDATORI,
                             soglia: int = SOGLIA_FONDATORI,
                             bps_dopo: int = BPS_DOPO) -> int:
    """bps della commissione totale per un host dato il suo ORDINALE (1-based).
    <= soglia → fondatori; oltre → post. Ordinale ignoto/non valido (<1) → tariffa standard
    (post): fail-safe, non si regala lo sconto fondatori a chi non risulta censito."""
    n = _intero(numero_host, 0)
    bf = max(0, min(10000, _intero(bps_fondatori, BPS_FONDATORI)))
    bd = max(0, min(10000, _intero(bps_dopo, BPS_DOPO)))
    s = max(0, _intero(soglia, SOGLIA_FONDATORI))
    if n < 1:
        return bd
    return bf if n <= s else bd


def commissione_bps_fonte(fonte: Any, numero_host: Any = 0, *,
                          bps_diretto: int = BPS_DIRETTO,
                          bps_marketplace: int = BPS_MARKETPLACE,
                          soglia: int = SOGLIA_FONDATORI) -> int:
    """bps secondo la FONTE della prenotazione (modello 0% ospite):
    'diretto' (cliente dell'host) → 5% (copre solo i costi di pagamento, no-loss);
    altro/'marketplace' (cliente portato da BookinVIP) → 15% (primi-1000 = 15%)."""
    if str(fonte).lower() == "diretto":
        return max(0, min(10000, _intero(bps_diretto, BPS_DIRETTO)))
    bm = max(0, min(10000, _intero(bps_marketplace, BPS_MARKETPLACE)))
    return commissione_bps_per_host(numero_host, bps_fondatori=bm, bps_dopo=bm, soglia=soglia)


# --- RAMPA DI LANCIO (land-grab): riempire SUBITO la copertura host globale ---
LANCIO_GIORNI_GRATIS = 90        # primi ~3 mesi: 0% (l'host pubblica gratis e tiene tutto)
LANCIO_BPS_FASE1 = 800           # poi 8%
LANCIO_GIORNI_FASE1 = 365        # fino a 1 anno di anzianità
LANCIO_BPS_REGIME = 1000         # oltre: 10% a regime (sempre < 15,5% dei colossi)


def commissione_bps_lancio(giorni_da_registrazione: Any, *,
                           giorni_gratis: int = LANCIO_GIORNI_GRATIS,
                           bps_fase1: int = LANCIO_BPS_FASE1,
                           giorni_fase1: int = LANCIO_GIORNI_FASE1,
                           bps_regime: int = LANCIO_BPS_REGIME) -> int:
    """Commissione marketplace a RAMPA per anzianità dell'host (giorni da registrazione):
    0% i primi ~3 mesi → 8% fino a 1 anno → 10% a regime. Strategia land-grab SENZA perdita:
    riempi ora (0%, host tiene tutto), recuperi nel tempo. Fail-safe: giorni ignoti/non validi
    → tariffa a regime (non si regala lo 0% per errore)."""
    g = giorni_da_registrazione if isinstance(giorni_da_registrazione, int) and \
        not isinstance(giorni_da_registrazione, bool) and giorni_da_registrazione >= 0 else 10**9
    gg = max(0, _intero(giorni_gratis, LANCIO_GIORNI_GRATIS))
    gf = max(gg, _intero(giorni_fase1, LANCIO_GIORNI_FASE1))
    b1 = max(0, min(10000, _intero(bps_fase1, LANCIO_BPS_FASE1)))
    br = max(0, min(10000, _intero(bps_regime, LANCIO_BPS_REGIME)))
    if g < gg:
        return 0
    if g < gf:
        return b1
    return br


def e_fondatore(numero_host: Any, *, soglia: int = SOGLIA_FONDATORI) -> bool:
    n = _intero(numero_host, 0)
    return 1 <= n <= max(0, _intero(soglia, SOGLIA_FONDATORI))


def commissione_cents(prezzo_cents: Any, bps: Any) -> int:
    """Commissione in centesimi interi da prezzo (cents) e bps. Floor, mai negativa."""
    p = max(0, _intero(prezzo_cents, 0))
    b = max(0, min(10000, _intero(bps, 0)))
    return p * b // 10000


def ripartisci_host_guest(prezzo_cents: Any, *, host_bps: int = HOST_BPS,
                          guest_bps: int = GUEST_BPS) -> Dict[str, int]:
    """MODULO 4. Ripartisce il 15% in host_bps (trattenuto) + guest_bps (aggiunto).
    Tutto in centesimi interi; conservazione esatta:
        totale_ospite = prezzo + guest_fee   (quanto paga l'ospite)
        netto_host    = prezzo - host_fee     (quanto incassa l'host)
        nostra_commissione = host_fee + guest_fee = totale_ospite - netto_host
    """
    p = max(0, _intero(prezzo_cents, 0))
    fee_host = commissione_cents(p, host_bps)
    fee_guest = commissione_cents(p, guest_bps)
    return {
        "prezzo": p,
        "host_fee": fee_host,                 # 3% trattenuto all'host
        "guest_fee": fee_guest,               # 12% pagato dall'ospite
        "nostra_commissione": fee_host + fee_guest,   # il nostro 15% totale
        "netto_host": p - fee_host,           # l'host incassa
        "totale_ospite": p + fee_guest,       # l'ospite paga
    }


def fattura_startup_cents(prezzo_cents: Any, *, host_bps: int = HOST_BPS,
                          guest_bps: int = GUEST_BPS) -> int:
    """MODULO 3 (tutela forfettario): SOLO la nostra commissione è fatturato della startup
    (intermediario puro). NON il lordo. Serve a calcolare il consumo della soglia 85k:
    GMV_max ≈ 85k / (15%) ≈ €566k. L'85% non transita come nostro ricavo."""
    r = ripartisci_host_guest(prezzo_cents, host_bps=host_bps, guest_bps=guest_bps)
    return r["nostra_commissione"]
