"""
CORE_AUTO - Fase 96: Lead discovery MONDIALE da DATI PUBBLICI APERTI (OpenStreetMap).

L'arma di acquisizione host che mancava, fatta LEGALE/GRATIS/AUTONOMA: invece di scrapare
siti protetti (illegale, banna il dominio), interroga **OpenStreetMap via Overpass API** —
dati APERTI (licenza ODbL), gratis, senza chiave, nessun proxy. Estrae SOLO le strutture
ricettive che hanno PUBBLICATO LORO un'email di contatto (`contact:email`/`email`): è
informazione messa online DALL'ATTIVITÀ apposta per essere contattata.

Implementa `fase89.FonteContatti` → si innesta DIRETTAMENTE nel motore outreach compliant
(fase89/95): il gate giurisdizioni fail-closed (UE esclusa di default) e l'opt-out sovrano
continuano ad applicarsi. Si SCOPRE ovunque (leggere dati aperti è lecito ovunque), ma si
CONTATTA solo dove l'operatore ha dichiarato lecito il cold-email B2B (USA, APAC permissivi…).

CONFINI: niente scraping/login/proxy. Solo l'endpoint Overpass pubblico (progettato per query
massive). `fetch` iniettabile → test senza rete. BLINDATO: errore → []. Dedup per email.
User-Agent identificante (etichetta Overpass). Vincitrice benchmark vs liste-comprate
(illegali) e scraping-con-proxy (banna il dominio): open-data-first, deliverability salva.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional

from fase89_jurisdiction_outreach import Contatto, FonteContatti, _email_valida

logger = logging.getLogger("core_auto.fonte_osm")

OVERPASS = "https://overpass-api.de/api/interpreter"
# Tipi di alloggio (tag tourism) che ci interessano come host potenziali.
TIPI_TOURISM = "hotel|guest_house|apartment|hostel|chalet|motel|bed_and_breakfast|resort"
UA = "BookinVIP/1.0 (host outreach; +https://bookinvip.com)"


def _query_overpass(paese_iso: str, limit: int) -> str:
    """Overpass QL: alloggi in un Paese (per codice ISO) che HANNO un'email pubblica."""
    p = str(paese_iso).upper()
    n = max(1, min(int(limit) if isinstance(limit, int) else 50, 1000))
    return (
        '[out:json][timeout:25];'
        'area["ISO3166-1"="%s"][admin_level=2]->.a;'
        '(nwr["tourism"~"%s"]["contact:email"](area.a);'
        ' nwr["tourism"~"%s"]["email"](area.a););'
        'out tags %d;' % (p, TIPI_TOURISM, TIPI_TOURISM, n)
    )


class FonteOpenStreetMap(FonteContatti):
    """Fonte di lead da OpenStreetMap (Overpass). Open data, gratis, senza chiave, no proxy.
    Restituisce SOLO POI ricettivi con email PUBBLICATA dall'attività."""

    def __init__(self, *, endpoint: str = OVERPASS,
                 fetch: Optional[Callable[[str], Dict[str, Any]]] = None,
                 max_per_chiamata: int = 200) -> None:
        self._endpoint = endpoint or OVERPASS
        self._fetch = fetch or self._fetch_reale
        self._cap = max_per_chiamata if isinstance(max_per_chiamata, int) else 200

    def cerca(self, *, paese: str, settore: str = "hospitality",
              limit: int = 50) -> List[Contatto]:
        if not paese:
            return []
        try:
            n = min(int(limit) if isinstance(limit, int) else 50, self._cap)
            data = self._fetch(_query_overpass(paese, n))
        except Exception:
            logger.warning("FonteOpenStreetMap.cerca fallita (ISOLATA → [])", exc_info=True)
            return []
        return self._mappa(data, paese)

    @staticmethod
    def _mappa(data: Any, paese: str) -> List[Contatto]:
        elementi = data.get("elements") if isinstance(data, dict) else None
        out: List[Contatto] = []
        visti = set()
        for el in (elementi or []):
            tags = el.get("tags") if isinstance(el, dict) else None
            if not isinstance(tags, dict):
                continue
            email = tags.get("contact:email") or tags.get("email")
            if not _email_valida(email):
                continue
            chiave = email.strip().lower()
            if chiave in visti:                          # dedup (OSM ha duplicati)
                continue
            visti.add(chiave)
            out.append(Contatto(
                nome=str(tags.get("name", "")),
                email=email,
                paese=str(paese).upper(),
                contatto_pubblico_business=True,          # POI business + email pubblicata
                base_legale="OSM_public_contact",
                fonte="openstreetmap",
                settore="hospitality"))
        return out

    def _fetch_reale(self, query: str) -> Dict[str, Any]:  # pragma: no cover
        import urllib.parse
        import urllib.request
        body = urllib.parse.urlencode({"data": query}).encode()
        req = urllib.request.Request(self._endpoint, data=body,
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())


def crea_fonte_osm(*, fetch: Any = None, endpoint: str = OVERPASS,
                   max_per_chiamata: int = 200) -> FonteOpenStreetMap:
    return FonteOpenStreetMap(endpoint=endpoint, fetch=fetch,
                              max_per_chiamata=max_per_chiamata)
