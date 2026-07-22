"""
CORE_AUTO - Fase 186: IL GUARDIANO DEGLI STATI IMPOSSIBILI.

Nasce dall'audit del 2026-07-22, dove tre indagini indipendenti (doppio-addebito ·
riconciliazione con Stripe · integrita' fra i 21 archivi) hanno trovato che cio' che e'
costruito e' solido, ma mancava LA STESSA unica cosa: **nessun processo automatico
controlla gli stati che NON dovrebbero poter esistere, e nessuno grida quando li trova.**

Su un sistema di pagamenti "non dovrebbe poter succedere" succede: un messaggio di Stripe
si perde, il server muore a meta' di un'operazione, una cancellazione salta un invariante.
Il paracadute non e' prevedere ogni bug (impossibile) — e' accorgersi in fretta quando la
realta' e i nostri registri divergono.

COSA GUARDA, tutto READ-ONLY, senza toccare nulla:

  1. RICONCILIAZIONE con Stripe (riusa fase182, se Stripe e il giornale ci sono):
     addebiti su Stripe senza riga nel giornale (webhook perso), righe nel giornale senza
     Stripe, importi diversi, e i totali charge/refund/transfer che non tornano.
  2. ESCROW BLOCCATO: garanzie ancora 'in_garanzia' il cui rilascio automatico e' passato
     da piu' di 48h -> il giro orario che paga l'host ha fallito, o la riga e' orfana.
  3. BONIFICO FERMO: payout 'maturato' fermo da piu' di 7 giorni -> soldi dovuti all'host
     mai partiti.
  4. PAYOUT ORFANO: una riga di payout il cui host non esiste piu' -> residuo di una
     cancellazione forzata; soldi dovuti a nessuno.

`scansiona()` e' PURA (nessun invio, nessuna scrittura): ritorna il referto. E' il server
(giro giornaliero) a mandare l'email di allarme se il referto non e' pulito. Cosi' il
Guardiano si prova senza rete e senza effetti collaterali.

Soglie LARGHE di proposito: un allarme che grida per un ritardo normale e' un allarme che
si impara a ignorare, e allora il grido vero non lo guarda piu' nessuno.
"""
from __future__ import annotations

import html as _html
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("core_auto.guardiano")

# Soglie: oltre queste, uno stato e' "impossibile" e va segnalato.
GRAZIA_ESCROW_ORE = 48          # un escrow gia' scaduto da 2 giorni non dovrebbe esistere
GIORNI_PAYOUT_FERMO = 7         # un bonifico 'maturato' fermo da una settimana e' bloccato
GIORNI_RICONCILIAZIONE = 30     # finestra del confronto con Stripe
ORE_CAMBIO_FERMO = 26           # cambio valuta (OXR): nessun tasso riuscito da >1 giorno NONOSTANTE
#                                 la sonda giornaliera = il terzo (OXR) e' giu'. Soglia >24h per
#                                 non gridare su un singolo blip che si riprende al giro dopo.


def _ora(ora: Any) -> int:
    return int((ora or time.time)())


def _riconciliazione(sistema: Any, giorni: int) -> Optional[Dict[str, Any]]:
    """Confronto con Stripe (fase182), solo se Stripe e il giornale sono configurati.
    None se non applicabile (non e' un'anomalia: e' che non c'e' Stripe da confrontare)."""
    sk = getattr(getattr(sistema, "config", None), "stripe_secret_key", "") or ""
    fc = getattr(sistema, "finanza", None)
    if not sk or fc is None:
        return None
    try:
        from fase182_riconciliazione import riconcilia
        rep = riconcilia(fc, sk, giorni=giorni)
    except Exception:
        logger.error("guardiano: riconciliazione fallita (ISOLATA)", exc_info=True)
        return {"errore": "riconciliazione_non_eseguita"}
    if rep.get("ok"):
        return None                                  # tutto quadra: niente da segnalare
    # si tiene solo cio' che NON torna
    delta_non_zero = {}
    for cat, c in (rep.get("confronti") or {}).items():
        nz = {v: d for v, d in (c.get("delta") or {}).items() if d != 0}
        if nz:
            delta_non_zero[cat] = nz
    return {"solo_stripe": rep.get("solo_stripe") or [],
            "solo_giornale": rep.get("solo_giornale") or [],
            "importo_diverso": rep.get("importo_diverso") or [],
            "delta_totali": delta_non_zero}


def _escrow_bloccati(sistema: Any, ora_ts: int, grazia_ore: int) -> List[Dict[str, Any]]:
    gar = getattr(sistema, "garanzia", None)
    if gar is None or not hasattr(gar, "aperte_scadute"):
        return []
    try:
        return gar.aperte_scadute(ora_ts=ora_ts, grazia_ore=grazia_ore)
    except Exception:
        logger.warning("guardiano: scan escrow fallito (ISOLATO)", exc_info=True)
        return []


def _payout_anomali(sistema: Any, ora_ts: int, giorni_fermo: int
                    ) -> Dict[str, List[Dict[str, Any]]]:
    """Bonifici fermi da troppo tempo e bonifici il cui host non esiste piu'."""
    pay = getattr(sistema, "payout", None)
    reg = getattr(sistema, "registro_host", None)
    fermi: List[Dict[str, Any]] = []
    orfani: List[Dict[str, Any]] = []
    if pay is None or not hasattr(pay, "tutti"):
        return {"bonifico_fermo": fermi, "payout_orfano": orfani}
    soglia = ora_ts - max(0, int(giorni_fermo)) * 86400
    try:
        righe = pay.tutti(limit=5000)
    except Exception:
        logger.warning("guardiano: scan payout fallito (ISOLATO)", exc_info=True)
        return {"bonifico_fermo": fermi, "payout_orfano": orfani}
    for r in righe:
        stato = r.get("stato")
        # host che non esiste piu' + soldi ancora dovuti = orfano
        if stato in ("maturato", "in_transito") and reg is not None \
                and hasattr(reg, "esiste_host"):
            try:
                if not reg.esiste_host(r.get("host_id", "")):
                    orfani.append(r)
                    continue
            except Exception:
                pass
        if stato == "maturato" and int(r.get("ts", 0)) < soglia:
            fermi.append({**r, "giorni_fermo": int((ora_ts - r.get("ts", 0)) / 86400)})
    return {"bonifico_fermo": fermi, "payout_orfano": orfani}


def _cambio_valuta_fermo(sistema: Any, ora_ts: int,
                         soglia_ore: int) -> Optional[Dict[str, Any]]:
    """Il convertitore valuta (OXR, fase99) è configurato ma non prende i tassi da troppo tempo?
    È SOLO display (nessun addebito ne dipende: l'ospite paga sempre nella valuta dell'alloggio),
    ma se resta muto il fondatore deve saperlo — è "il terzo che cambia". `stato()` è READ-ONLY
    (nessuna rete qui): la sonda VERA la fa il giro giornaliero prima di chiamare scansiona.
    Nessuna chiave OXR → None (niente allarme: la funzione è semplicemente spenta)."""
    tassi = getattr(sistema, "tassi", None)
    if tassi is None:
        return None
    st = tassi.stato(ora_ts)
    if not st.get("configurato"):
        return None
    eta = st.get("eta_ore")
    fermo = bool(st.get("mai_riuscito")) or (eta is not None and eta > soglia_ore)
    if not fermo:
        return None
    return {"eta_ore": eta, "mai_riuscito": bool(st.get("mai_riuscito")),
            "ultimo_ok_ts": st.get("ultimo_ok_ts"), "soglia_ore": soglia_ore}


def scansiona(sistema: Any, *, ora: Any = None,
              giorni_riconciliazione: int = GIORNI_RICONCILIAZIONE,
              grazia_escrow_ore: int = GRAZIA_ESCROW_ORE,
              giorni_payout_fermo: int = GIORNI_PAYOUT_FERMO,
              ore_cambio_fermo: int = ORE_CAMBIO_FERMO) -> Dict[str, Any]:
    """Cerca tutti gli stati impossibili e li raccoglie. READ-ONLY. Ritorna:
    {pulito: bool, conta: N, anomalie: {categoria: [...]/{...}}, ts, ...}."""
    ora_ts = _ora(ora)
    anomalie: Dict[str, Any] = {}

    # Ogni controllo isolato: un archivio rotto non deve impedire agli altri di girare
    # ne' far sollevare il Guardiano (che gira in un thread daemon: se esplode, muore in
    # silenzio e non guarda piu' niente). getattr NON basta: un __getattr__ che solleva un
    # errore diverso da AttributeError buca il default -> serve un try/except vero.
    def _prova(f, *a):
        try:
            return f(*a)
        except Exception:
            logger.error("guardiano: un controllo e' fallito (ISOLATO)", exc_info=True)
            return None

    ric = _prova(_riconciliazione, sistema, giorni_riconciliazione)
    if ric:
        anomalie["riconciliazione_stripe"] = ric

    escrow = _prova(_escrow_bloccati, sistema, ora_ts, grazia_escrow_ore)
    if escrow:
        anomalie["escrow_bloccato"] = escrow

    pa = _prova(_payout_anomali, sistema, ora_ts, giorni_payout_fermo) or {}
    if pa.get("bonifico_fermo"):
        anomalie["bonifico_fermo"] = pa["bonifico_fermo"]
    if pa.get("payout_orfano"):
        anomalie["payout_orfano"] = pa["payout_orfano"]

    cv = _prova(_cambio_valuta_fermo, sistema, ora_ts, ore_cambio_fermo)
    if cv:
        anomalie["cambio_valuta_fermo"] = cv

    def _conta(v: Any) -> int:
        if isinstance(v, list):
            return len(v)
        if isinstance(v, dict):
            return sum(_conta(x) for x in v.values())
        return 1 if v else 0

    conta = sum(_conta(v) for v in anomalie.values())
    return {"pulito": conta == 0, "conta": conta, "anomalie": anomalie,
            "ts": ora_ts, "soglie": {"grazia_escrow_ore": grazia_escrow_ore,
                                     "giorni_payout_fermo": giorni_payout_fermo,
                                     "giorni_riconciliazione": giorni_riconciliazione}}


_TITOLI = {
    "riconciliazione_stripe": "I conti non tornano con Stripe",
    "escrow_bloccato": "Escrow bloccati (soldi ospite non rilasciati)",
    "bonifico_fermo": "Bonifici dovuti all'host, fermi da troppo tempo",
    "payout_orfano": "Bonifici dovuti a un host che non esiste piu'",
    "cambio_valuta_fermo": "Cambio valuta (OXR) fermo: la stima «≈ nella tua moneta» non si aggiorna",
}


def riassunto_html(report: Dict[str, Any]) -> str:
    """Corpo dell'email di allarme (XSS-safe). Solo se il report NON e' pulito."""
    e = _html.escape
    an = report.get("anomalie") or {}
    righe = []
    for chiave, contenuto in an.items():
        titolo = _TITOLI.get(chiave, chiave)
        n = contenuto if isinstance(contenuto, int) else (
            len(contenuto) if isinstance(contenuto, list) else "")
        campione = ""
        if isinstance(contenuto, list) and contenuto:
            campione = "<br>".join(e(str(x)[:180]) for x in contenuto[:5])
        elif isinstance(contenuto, dict):
            campione = "<br>".join("%s: %s" % (e(str(k)), e(str(v)[:180]))
                                   for k, v in contenuto.items())
        righe.append(
            "<div style=\"margin:.8rem 0;padding:.6rem .9rem;border-left:3px solid #c0392b;"
            "background:#fdecec\"><strong>%s</strong>%s<div style=\"color:#5e6f8d;"
            "font-size:.85rem;margin-top:.3rem\">%s</div></div>"
            % (e(titolo), (" (%s)" % n if n != "" else ""), campione))
    return (
        "<div style=\"font-family:sans-serif;max-width:640px\">"
        "<h2 style=\"color:#c0392b\">&#9888; Il Guardiano ha trovato %d stato/i anomalo/i</h2>"
        "<p>Sono situazioni che <strong>non dovrebbero poter esistere</strong>: i nostri "
        "registri e la realta' (Stripe, gli archivi fra loro) non tornano. Vanno guardate "
        "a mano. Nessuna azione automatica e' stata eseguita.</p>%s"
        "<p style=\"color:#5e6f8d;font-size:.8rem\">Guardiano automatico (fase186) - "
        "controllo giornaliero. Se questo elenco e' vuoto non ricevi nulla.</p></div>"
    ) % (report.get("conta", 0), "".join(righe))
