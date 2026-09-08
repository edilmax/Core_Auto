"""
CORE_AUTO - Fase 82: iCal Sync (la portabilita' REALE, non quella gonfiata).

Verita' onesta (validata da una critica di mercato): NON esiste un'API pubblica per
esportare l'inventario host da Booking/Airbnb. Il "bottone Importa da Booking in 10
secondi" e' un'illusione. Ma esiste un canale di portabilita' REALE, legale e
UNIVERSALE che ogni OTA offre davvero all'host: il calendario iCal (.ics). Airbnb,
Booking, Vrbo esportano tutti un link iCal con le date gia' occupate/bloccate.

Questo modulo fa la cosa vera: parser iCal PURO (zero dipendenze - la libreria
`icalendar` non e' installata e non serve), estrae i periodi occupati dai VEVENT, e li
sincronizza nell'inventario (fase58) marcandoli NON disponibili. E' il vero anti-
overbooking cross-canale: una prenotazione presa su Airbnb blocca quelle date anche da
noi, automaticamente, senza scraping ne' API proprietarie.

Semantica corretta: in iCal con VALUE=DATE, DTEND e' ESCLUSIVO -> coincide con il nostro
intervallo semi-aperto [check_in, check_out) (fase34/58). Niente off-by-one.

VINCITRICE DEL BENCHMARK (4 modi di sincronizzare i canali):
  V3 'parser iCal puro + blocco idempotente per-giorno su fase58'. Reale (iCal e' lo
  standard universale), legale (link fornito dall'host), zero dipendenze, idempotente
  (ri-sincronizzare non rompe nulla). Le altre perdono: V1 'API inventario Booking' =
  NON ESISTE; V2 'scraping' = illegale (ToS) e fragile; V4 'import CSV manuale' =
  attrito, si fa una volta sola, non si sincronizza.

SOPRAVVIVENZA TOTALE: parser blindato (righe/eventi malformati IGNORATI, mai
un'eccezione); date invalide scartate; sync isolato (un giorno che fallisce non abbatte
il resto); blocco via imposta_disponibilita (unita_totali=0) che NON scende mai sotto
l'occupato reale (fail-safe). Zero dipendenze esterne.
"""
from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("core_auto.ical_sync")

MAX_GIORNI_EVENTO = 366    # tetto anti-abuso su un singolo VEVENT


def _srotola(testo: str) -> List[str]:
    """RFC5545 line unfolding: una riga che inizia con spazio/tab continua la precedente."""
    righe: List[str] = []
    for riga in testo.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if riga[:1] in (" ", "\t") and righe:
            righe[-1] += riga[1:]
        else:
            righe.append(riga)
    return righe


def _data_da_valore(valore: str) -> Optional[datetime.date]:
    """Estrae la data da un valore DTSTART/DTEND ('20260701' o '20260701T140000Z')."""
    cifre = ""
    for ch in valore.strip():
        if ch.isdigit():
            cifre += ch
            if len(cifre) == 8:
                break
        else:
            if cifre:
                break
    if len(cifre) != 8:
        return None
    try:
        return datetime.date(int(cifre[:4]), int(cifre[4:6]), int(cifre[6:8]))
    except ValueError:
        return None


def analizza_ical(testo: Any) -> List[Tuple[str, str]]:
    """Estrae i periodi occupati (check_in, check_out) ISO da un .ics. BLINDATO."""
    if not isinstance(testo, str):
        return []
    eventi: List[Tuple[str, str]] = []
    dentro = False
    dtstart: Optional[datetime.date] = None
    dtend: Optional[datetime.date] = None
    for riga in _srotola(testo):
        u = riga.strip().upper()
        if u == "BEGIN:VEVENT":
            dentro, dtstart, dtend = True, None, None
            continue
        if u == "END:VEVENT":
            if dtstart and dtend and dtstart < dtend \
                    and (dtend - dtstart).days <= MAX_GIORNI_EVENTO:
                eventi.append((dtstart.isoformat(), dtend.isoformat()))
            dentro = False
            continue
        if not dentro or ":" not in riga:
            continue
        chiave, _, valore = riga.partition(":")
        nome = chiave.split(";")[0].strip().upper()
        if nome == "DTSTART":
            dtstart = _data_da_valore(valore)
        elif nome == "DTEND":
            dtend = _data_da_valore(valore)
    return eventi


def _giorni(check_in: str, check_out: str) -> List[str]:
    ci = datetime.date.fromisoformat(check_in)
    co = datetime.date.fromisoformat(check_out)
    return [(ci + datetime.timedelta(days=i)).isoformat()
            for i in range((co - ci).days)]


MARCA_NOSTRA = "//BookinVIP//"     # come si riconosce un feed uscito da casa nostra
FEED_UNICO = "(feed unico)"        # identita' di ripiego per chi non ne passa una


def prodid(testo: Any) -> str:
    """Il PRODID dichiarato dal calendario, o stringa vuota. Serve a riconoscere l'ECO."""
    if not isinstance(testo, str):
        return ""
    for riga in _srotola(testo):
        chiave, _, valore = riga.partition(":")
        if chiave.split(";")[0].strip().upper() == "PRODID":
            return valore.strip()
    return ""


def e_nostro(testo: Any) -> bool:
    """⛔ L'ECO. `fase135` esporta le nostre notti occupate; l'OTA ripubblica quel
    calendario; se lo rileggessimo chiuderemmo le NOSTRE stesse notti, e ogni giro ne
    chiuderebbe altre. Un anello che si stringe da solo. Il nostro PRODID e' li' apposta:
    fino al 2026-09-07 c'era e non lo guardava nessuno (misurato: la nostra notte passava
    a (0, 0) dando in pasto al sincronizzatore il feed del nostro esportatore).
    ⚠️ Il legame fra questa marca e il PRODID di fase135 e' CONTROLLATO, non sperato: la
    guardia sta in `collaudi/esame_feed_due_versi.py` (sezione «eco»), perche' fase135
    importa questo modulo e importarlo al contrario sarebbe un anello di import."""
    return MARCA_NOSTRA in prodid(testo)


def giorni_occupati(ical_testo: Any) -> List[str]:
    """I giorni coperti dagli eventi del feed, senza doppioni e in ordine."""
    visti = set()
    for ci, co in analizza_ical(ical_testo):
        try:
            visti.update(_giorni(ci, co))
        except (ValueError, TypeError):
            continue
    return sorted(visti)


def sincronizza(inventario: Any, alloggio_id: str, ical_testo: Any,
                feed_id: Optional[str] = None) -> Dict[str, Any]:
    """Allinea l'inventario (fase58) a QUESTO feed, **nei due versi**.

    Prima del 2026-09-07 questa funzione andava in un verso solo: scriveva
    `unita_totali=0, prezzo_netto_cents=0` SOPRA la riga dell'inventario. Tre conseguenze,
    tutte misurate: una notte chiusa da un calendario non si riapriva mai piu'; il prezzo
    dell'host spariva, quindi non esisteva piu' niente a cui tornare; e non si sapeva
    QUALE feed l'avesse chiusa, percio' con due calendari «si riapre quando sparisce da
    quel feed e da nessun altro» non era nemmeno esprimibile.

    Adesso il blocco esterno e' un OGGETTO con un'origine (`fase58.feed_applica`) e la
    riga dell'inventario ne e' la proiezione. Ritorna {eventi, giorni_bloccati, ...} --
    le due chiavi storiche restano e vogliono dire quello di prima, cosi' nessun chiamante
    cambia.
    """
    fid = str(feed_id).strip() if isinstance(feed_id, str) and feed_id.strip() else FEED_UNICO
    aid = str(alloggio_id)

    if e_nostro(ical_testo):
        logger.warning("ical_sync: feed IGNORATO, e' il nostro calendario riesportato "
                       "(alloggio=%s feed=%s prodid=%s)", aid, fid, prodid(ical_testo))
        return {"eventi": 0, "giorni_bloccati": 0, "riaperte": 0, "tenute_da_altri": 0,
                "mano_dell_host": 0, "occupate": 0, "eco_ignorata": True,
                "anomalia": ""}

    eventi = analizza_ical(ical_testo)
    giorni = giorni_occupati(ical_testo)

    if not hasattr(inventario, "feed_applica"):
        # RIPIEGO per un inventario che non conosce i blocchi esterni: si comporta come
        # prima (un verso solo). Dichiarato, non silenzioso: chi lo usa lo legge nel
        # risultato e sa che la riapertura li' non c'e'.
        bloccati = 0
        for g in giorni:
            try:
                if inventario.imposta_disponibilita(aid, g, unita_totali=0,
                                                    prezzo_netto_cents=0):
                    bloccati += 1
            except Exception:
                logger.warning("ical_sync: blocco giorno %s fallito (isolato)", g,
                               exc_info=True)
        return {"eventi": len(eventi), "giorni_bloccati": bloccati, "riaperte": 0,
                "tenute_da_altri": 0, "mano_dell_host": 0, "occupate": 0,
                "eco_ignorata": False, "anomalia": "",
                "un_verso_solo": "l'inventario non conosce i blocchi esterni"}

    try:
        prima = list(inventario.feed_giorni(aid, fid))
    except Exception:
        prima = []

    # ⛔ DA N A ZERO. Un feed che ieri portava eventi e oggi ne porta zero quasi mai vuol
    # dire «l'host ha liberato tutto»: vuol dire URL scaduto, autenticazione caduta, OTA
    # che risponde una pagina vuota con 200. Riaprire tutto su quel silenzio e' il modo
    # migliore per vendere due volte la stessa notte. Quindi: non si tocca NIENTE, e si
    # dichiara un'anomalia che qualcuno a valle deve leggere.
    if prima and not giorni:
        logger.error("ical_sync | codice: feed_azzerato | sottocodice: da_%d_a_zero | "
                     "messaggio: il feed teneva %d notti e adesso non porta nessun evento: "
                     "NON riapro niente (alloggio=%s feed=%s)",
                     len(prima), len(prima), aid, fid)
        return {"eventi": 0, "giorni_bloccati": len(prima), "riaperte": 0,
                "tenute_da_altri": 0, "mano_dell_host": 0, "occupate": 0,
                "eco_ignorata": False,
                "anomalia": "feed_azzerato: teneva %d notti, adesso zero eventi. Non ho "
                            "riaperto niente: un feed vuoto e' quasi sempre un feed rotto,"
                            " e riaprire su un silenzio vende due volte la stessa notte"
                            % len(prima)}

    try:
        r = inventario.feed_applica(aid, fid, giorni)
    except Exception:
        # ⛔ SI RIPIEGA SUL VERSO VECCHIO, non si esce a mani vuote. Fra i due modi di
        # sbagliare qui non c'e' partita: una notte chiusa di troppo si riapre a mano, una
        # notte lasciata aperta si vende DUE VOLTE -- e la seconda vendita la paghiamo noi,
        # con l'ospite davanti a una porta occupata. Quindi: blocca comunque, e dichiara
        # nel risultato che la riapertura in questo giro non c'e' stata.
        logger.error("ical_sync | codice: feed_applica_fallita | sottocodice: ripiego_un_verso "
                     "| messaggio: blocco comunque le notti occupate, nessuna riapertura "
                     "(alloggio=%s feed=%s)", aid, fid, exc_info=True)
        bloccati = 0
        for g in giorni:
            try:
                if inventario.imposta_disponibilita(aid, g, unita_totali=0,
                                                    prezzo_netto_cents=0):
                    bloccati += 1
            except Exception:
                logger.warning("ical_sync: blocco giorno %s fallito (isolato)", g,
                               exc_info=True)
        return {"eventi": len(eventi), "giorni_bloccati": bloccati, "riaperte": 0,
                "tenute_da_altri": 0, "mano_dell_host": 0, "occupate": 0,
                "eco_ignorata": False,
                "anomalia": "feed_applica non ha funzionato: ho bloccato le notti nel verso "
                            "vecchio e NON ho riaperto niente. Meglio una notte chiusa di "
                            "troppo che la stessa notte venduta due volte"}

    occupate = int(r.get("occupate", 0))
    return {"eventi": len(eventi),
            # storico: quante notti questo feed tiene chiuse adesso (non «quante ne ho
            # chiuse in questo giro»): ri-sincronizzare lo stesso feed da lo stesso numero
            "giorni_bloccati": max(0, len(giorni) - occupate),
            "riaperte": int(r.get("riaperte", 0)),
            "tenute_da_altri": int(r.get("tenute_da_altri", 0)),
            "mano_dell_host": int(r.get("mano_dell_host", 0)),
            "occupate": occupate,
            "eco_ignorata": False,
            "anomalia": ""}
