"""
CORE_AUTO - Fase 77: Portability Import Engine (il "virus legale" anti-OTA).

GDPR Art. 20 + EU Data Act + DMA: l'host ha il DIRITTO di portare via i suoi dati da
Booking/Airbnb in formato machine-readable, e i gatekeeper DEVONO permetterlo. Non
convinciamo l'host: gli diamo un bottone che esercita il SUO diritto. In 10 secondi, non
10 mesi: foto, descrizioni, prezzi, disponibilita' importati e pronti su Tavola VIP.

Questo modulo NON fa scraping (illegale, fragile): ingerisce un EXPORT machine-readable
(il diritto dell'host) e lo NORMALIZZA nel nostro schema, convertendo i prezzi in
CENTESIMI INTERI all'ingestione (Decimal, mai float -> niente drift di arrotondamento) e
validando in modo blindato. Poi applica al catalogo (fase57) e all'inventario (fase58)
via oggetti INIETTATI e ISOLATI. La connessione API live al gatekeeper e' gated
(credenziali/accesso); parsing+normalizzazione+applicazione sono puri e testabili.

VINCITRICE DEL BENCHMARK (4 modi di onboardare l'host):
  V3 'import da data-portability (export machine-readable) normalizzato + cents-at-
  ingestion + apply isolato'. Legale (e' un DIRITTO), ~10 secondi, deterministico,
  interoperabile. Le altre perdono: V1 're-immissione manuale' = ore, errori, l'host non
  lo fa; V2 'scraping Booking' = illegale (diritto banche dati) e fragile (bot-defense);
  V4 'import proprietario chiuso' = lock-in, non interoperabile.

SOPRAVVIVENZA TOTALE: adapter per sorgente (booking/airbnb/canonico) tolleranti; prezzi
solo Decimal-string -> cents (float/negativi rifiutati, fail-closed); validatori che non
sollevano mai; apply al catalogo/inventario isolato (un errore non abbatte l'import);
report con cosa e' entrato e cosa e' fallito. Zero dipendenze esterne.
"""
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("core_auto.portability")

MAX_CENTS = 1_000_000_00
LIMITE_CAMPO = 256
LIMITE_TESTO = 4000


def _stringa(v: Any, limite: int = LIMITE_CAMPO) -> Optional[str]:
    if not isinstance(v, str):
        return None
    v = v.strip()
    return v if v and len(v) <= limite else None


def _intero_pos(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def prezzo_a_cents(valore: Any) -> Optional[int]:
    """Converte un prezzo in unita' valuta (stringa decimale, es. '82.00') in centesimi
    interi (Decimal HALF_UP). float/negativi/non-stringa -> None (fail-closed)."""
    if not isinstance(valore, str):
        return None
    try:
        d = Decimal(valore.strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    if d < 0:
        return None
    cents = int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return cents if 0 <= cents <= MAX_CENTS else None


# ─────────────────────────────────────────────────────────────────────────────
# Adapter per sorgente (best-effort, tolleranti ai nomi dei campi)
# ─────────────────────────────────────────────────────────────────────────────
def _primo(raw: Dict[str, Any], *chiavi: str) -> Any:
    for k in chiavi:
        if k in raw and raw[k] not in (None, ""):
            return raw[k]
    return None


def da_booking(raw: Any) -> Dict[str, Any]:
    """Mappa un export stile Booking al formato canonico (best-effort)."""
    if not isinstance(raw, dict):
        return {}
    return {
        "host_id": _primo(raw, "host_id", "hotel_id", "property_id", "partner_id"),
        "slug": _primo(raw, "slug", "property_id", "hotel_id"),
        "titolo": _primo(raw, "property_name", "name", "title"),
        "citta": _primo(raw, "city", "address_city", "town"),
        "prezzo_notte": _primo(raw, "base_rate", "rate", "base_price", "price"),
        "capacita": _primo(raw, "max_occupancy", "capacity", "max_guests"),
        "descrizione": _primo(raw, "description", "summary"),
        "servizi": _primo(raw, "facilities", "amenities", "services"),
        "immagini": _primo(raw, "photos", "images"),
        "disponibilita": _primo(raw, "availability", "calendar"),
    }


def da_airbnb(raw: Any) -> Dict[str, Any]:
    """Mappa un export stile Airbnb al formato canonico (best-effort)."""
    if not isinstance(raw, dict):
        return {}
    return {
        "host_id": _primo(raw, "host_id", "listing_host_id"),
        "slug": _primo(raw, "slug", "listing_id", "id"),
        "titolo": _primo(raw, "listing_title", "name", "title"),
        "citta": _primo(raw, "city", "location_city"),
        "prezzo_notte": _primo(raw, "nightly_price", "price", "base_price"),
        "capacita": _primo(raw, "accommodates", "guests", "capacity"),
        "descrizione": _primo(raw, "description", "summary"),
        "servizi": _primo(raw, "amenities", "facilities"),
        "immagini": _primo(raw, "picture_urls", "photos", "images"),
        "disponibilita": _primo(raw, "calendar", "availability"),
    }


_ADAPTER = {"booking": da_booking, "airbnb": da_airbnb, "canonico": lambda r: r}


# ─────────────────────────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ReportImport:
    ok: bool
    slug: str = ""
    errori: List[str] = field(default_factory=list)
    scheda: Optional[Dict[str, Any]] = None
    immagini: List[str] = field(default_factory=list)
    notti: List[Dict[str, int]] = field(default_factory=list)
    catalogo_applicato: bool = False
    notti_applicate: int = 0


def _normalizza(canonico: Dict[str, Any]) -> Tuple[List[str], Optional[Dict[str, Any]],
                                                   List[str], List[Dict[str, int]]]:
    errori: List[str] = []
    host_id = _stringa(canonico.get("host_id"))
    slug = _stringa(canonico.get("slug"))
    titolo = _stringa(canonico.get("titolo"))
    citta = _stringa(canonico.get("citta"))
    prezzo = prezzo_a_cents(canonico.get("prezzo_notte"))
    capacita = canonico.get("capacita")
    if host_id is None:
        errori.append("host_id_mancante")
    if slug is None:
        errori.append("slug_mancante")
    if titolo is None:
        errori.append("titolo_mancante")
    if citta is None:
        errori.append("citta_mancante")
    if prezzo is None or prezzo <= 0:
        errori.append("prezzo_non_valido")
    if not _intero_pos(capacita):
        errori.append("capacita_non_valida")

    descr = canonico.get("descrizione") if isinstance(canonico.get("descrizione"), str) else ""
    servizi_in = canonico.get("servizi")
    servizi = tuple(str(s).strip().lower() for s in servizi_in
                    if isinstance(s, str)) if isinstance(servizi_in, (list, tuple)) else ()
    immagini_in = canonico.get("immagini")
    immagini = [u for u in immagini_in if isinstance(u, str)
                and (u.startswith("http://") or u.startswith("https://"))] \
        if isinstance(immagini_in, (list, tuple)) else []

    notti: List[Dict[str, int]] = []
    dispo = canonico.get("disponibilita")
    if isinstance(dispo, (list, tuple)):
        for d in dispo:
            if not isinstance(d, dict):
                continue
            giorno = d.get("giorno") or d.get("date")
            try:
                datetime.date.fromisoformat(str(giorno))
            except (ValueError, TypeError):
                continue
            unita = d.get("unita", d.get("units", 1))
            if not _intero_pos(unita):
                continue
            p = prezzo_a_cents(d.get("prezzo", d.get("price"))) if (
                d.get("prezzo") or d.get("price")) is not None else prezzo
            if p is None or p <= 0:
                continue
            notti.append({"giorno": str(giorno), "unita": unita, "prezzo_cents": p})

    if errori:
        return errori, None, immagini, notti
    scheda = {
        "host_id": host_id, "slug": slug, "titolo": titolo, "citta": citta,
        "prezzo_notte_cents": prezzo, "capacita": int(capacita),
        "descrizione": descr.strip()[:LIMITE_TESTO], "servizi": servizi,
    }
    return errori, scheda, immagini, notti


def importa(raw: Any, *, sorgente: str = "canonico", catalogo: Any = None,
            inventario: Any = None) -> ReportImport:
    """Importa una proprieta' da un export (data-portability). Dry-run se catalogo/
    inventario non forniti; altrimenti applica (isolato)."""
    adapter = _ADAPTER.get(sorgente, _ADAPTER["canonico"])
    canonico = adapter(raw)
    if not isinstance(canonico, dict):
        return ReportImport(False, errori=["payload_non_valido"])
    errori, scheda, immagini, notti = _normalizza(canonico)
    if errori or scheda is None:
        return ReportImport(False, errori=errori, immagini=immagini, notti=notti)

    rep = ReportImport(True, slug=scheda["slug"], scheda=scheda, immagini=immagini,
                       notti=notti)
    if catalogo is not None:
        try:
            from fase57_vetrina import Immagine, SchedaAlloggio
            sch = SchedaAlloggio(host_id=scheda["host_id"], slug=scheda["slug"],
                                 titolo=scheda["titolo"], citta=scheda["citta"],
                                 prezzo_notte_cents=scheda["prezzo_notte_cents"],
                                 capacita=scheda["capacita"],
                                 descrizione=scheda["descrizione"],
                                 servizi=scheda["servizi"])
            imgs = [Immagine(u, i) for i, u in enumerate(immagini)]
            catalogo.pubblica(sch, imgs)
            rep.catalogo_applicato = True
        except Exception:
            logger.error("import: catalogo.pubblica ISOLATO ha sollevato", exc_info=True)
            rep.errori.append("catalogo_non_applicato")
    if inventario is not None:
        for n in notti:
            try:
                if inventario.imposta_disponibilita(
                        scheda["slug"], n["giorno"], unita_totali=n["unita"],
                        prezzo_netto_cents=n["prezzo_cents"]):
                    rep.notti_applicate += 1
            except Exception:
                logger.warning("import: imposta_disponibilita ISOLATA fallita",
                               exc_info=True)
    return rep
