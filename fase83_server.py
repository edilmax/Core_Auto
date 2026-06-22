"""
CORE_AUTO - Fase 83: Server HTTP (la COLLA che fa uscire la Ferrari dal garage).

Critica accettata: avevamo 24 moduli backend ma NESSUN server che li espone come API, e
nessuna faccia. Questo modulo e' il collante eseguibile: cabla il SistemaCasaVIP (fase81)
e lo espone via HTTP, MULTILINGUA (clienti E host), a ZERO dipendenze (solo stdlib -
niente Flask, fedele a "gratuito e autonomo").

Due strati:
  1. RouterHTTP: PURO e testabile - `gestisci(metodo, path, query, body, headers)` ->
     (status, corpo_dict). Nessun socket: si testa come una funzione. Rotte:
       GET  /api/health
       GET  /api/lingue                      -> lingue supportate
       GET  /api/i18n?lang=xx                 -> dizionario UI+servizi+stati (per il frontend)
       GET  /api/catalogo?citta=..&lang=..    -> vetrina (servizi tradotti se lang)
       GET  /api/catalogo/<slug>?lang=..      -> dettaglio
       POST /api/concierge/quote              -> preventivo firmato (fase59)
       POST /api/concierge/book               -> prenotazione (fase59)
       POST /api/mcp                          -> JSON-RPC agenti IA (fase60)
       POST /api/host/pubblica  (X-Host-Key)  -> pubblica un alloggio (fase57)
       POST /api/host/disponibilita (X-Host-Key) -> imposta disponibilita' (fase58)
  2. server HTTP stdlib (http.server) che instrada /api/* al router e serve i file
     statici (index.html, host.html) - NON testato (I/O), thin wrapper.

I18N: il backend e' lingua-agnostico (codici servizio, cents, ISO); il frontend chiede
/api/i18n?lang=xx e rende l'interfaccia nella lingua scelta. Le risposte del catalogo
includono `servizi_label` tradotti via fase61. Cosi' clienti E host vedono tutto nella
loro lingua, a costo zero.

SOPRAVVIVENZA TOTALE: il router NON solleva MAI (eccezione -> 500); body JSON invalido ->
400; rotta ignota -> 404; host senza chiave -> 401; CORS aperto per il frontend. Stateless.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Tuple

from fase61_localizzazione import Localizzatore, LINGUE_SUPPORTATE

logger = logging.getLogger("core_auto.server")


# Stringhe UI per il frontend (chrome), multilingua. Fallback -> 'en' -> chiave.
ETICHETTE_UI: Dict[str, Dict[str, str]] = {
    "cerca": {"it": "Cerca", "en": "Search", "es": "Buscar", "fr": "Rechercher",
              "de": "Suchen"},
    "citta": {"it": "Citta", "en": "City", "es": "Ciudad", "fr": "Ville", "de": "Stadt"},
    "checkin": {"it": "Check-in", "en": "Check-in", "es": "Entrada", "fr": "Arrivee",
                "de": "Anreise"},
    "checkout": {"it": "Check-out", "en": "Check-out", "es": "Salida", "fr": "Depart",
                 "de": "Abreise"},
    "ospiti": {"it": "Ospiti", "en": "Guests", "es": "Huespedes", "fr": "Voyageurs",
               "de": "Gaste"},
    "notte": {"it": "notte", "en": "night", "es": "noche", "fr": "nuit", "de": "Nacht"},
    "dettaglio": {"it": "Vedi dettaglio", "en": "View details", "es": "Ver detalles",
                  "fr": "Voir details", "de": "Details ansehen"},
    "prenota": {"it": "Prenota ora", "en": "Book now", "es": "Reservar", "fr": "Reserver",
                "de": "Buchen"},
    "totale": {"it": "Totale", "en": "Total", "es": "Total", "fr": "Total", "de": "Gesamt"},
    "netto": {"it": "Alloggio", "en": "Lodging", "es": "Alojamiento", "fr": "Logement",
              "de": "Unterkunft"},
    "commissione": {"it": "Commissione", "en": "Fee", "es": "Comision", "fr": "Commission",
                    "de": "Gebuhr"},
    "tassa": {"it": "Tassa soggiorno", "en": "City tax", "es": "Tasa turistica",
              "fr": "Taxe de sejour", "de": "Kurtaxe"},
    "nessun_risultato": {"it": "Nessun alloggio trovato", "en": "No lodging found",
                         "es": "Sin resultados", "fr": "Aucun resultat", "de": "Keine Treffer"},
    "caricamento": {"it": "Caricamento...", "en": "Loading...", "es": "Cargando...",
                    "fr": "Chargement...", "de": "Laden..."},
    "errore": {"it": "Errore", "en": "Error", "es": "Error", "fr": "Erreur", "de": "Fehler"},
    "email": {"it": "Email", "en": "Email", "es": "Correo", "fr": "E-mail", "de": "E-Mail"},
    "conferma": {"it": "Prenotazione confermata!", "en": "Booking confirmed!",
                 "es": "Reserva confirmada!", "fr": "Reservation confirmee!",
                 "de": "Buchung bestatigt!"},
    "non_disp": {"it": "Non disponibile", "en": "Not available", "es": "No disponible",
                 "fr": "Indisponible", "de": "Nicht verfugbar"},
    # host
    "pannello_host": {"it": "Pannello Host", "en": "Host Panel", "es": "Panel Anfitrion",
                      "fr": "Espace Hote", "de": "Gastgeber-Panel"},
    "pubblica": {"it": "Pubblica alloggio", "en": "Publish listing",
                 "es": "Publicar", "fr": "Publier", "de": "Veroffentlichen"},
    "salva_disp": {"it": "Salva disponibilita", "en": "Save availability",
                   "es": "Guardar disponibilidad", "fr": "Enregistrer", "de": "Speichern"},
    "prezzo_notte": {"it": "Prezzo/notte (cent)", "en": "Price/night (cents)",
                     "es": "Precio/noche", "fr": "Prix/nuit", "de": "Preis/Nacht"},
}


def _ui(chiave: str, lingua: str) -> str:
    tab = ETICHETTE_UI.get(chiave, {})
    return tab.get(lingua) or tab.get("en") or chiave


def _dizionario_i18n(lingua: str) -> Dict[str, Any]:
    from fase61_localizzazione import ETICHETTE_SERVIZI, ETICHETTE_STATI
    loc = Localizzatore()
    return {
        "lingua": lingua,
        "ui": {k: _ui(k, lingua) for k in ETICHETTE_UI},
        "servizi": {c: loc.servizio(c, lingua) for c in ETICHETTE_SERVIZI},
        "stati": {c: loc.stato(c, lingua) for c in ETICHETTE_STATI},
    }


def _lingua(query: Dict[str, str]) -> str:
    lng = (query or {}).get("lang", "")
    return lng if lng in LINGUE_SUPPORTATE else "en"


# ─────────────────────────────────────────────────────────────────────────────
# SEO / discoverability (gratis): pagina crawlabile per alloggio + JSON-LD + sitemap.
# Funzioni PURE e testabili. base_url = dominio (vuoto = relativo finche' non c'e').
# ─────────────────────────────────────────────────────────────────────────────
def _euro(cents: Any) -> str:
    if not isinstance(cents, int) or isinstance(cents, bool) or cents < 0:
        return "0.00"
    return "%d.%02d" % (cents // 100, cents % 100)        # no float, deterministico


def jsonld_alloggio(dettaglio: Dict[str, Any], base_url: str = "",
                    recensioni: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Schema.org per un alloggio (rich results Google + leggibile dagli agenti).
    Se ci sono recensioni, aggiunge aggregateRating (stelle nei risultati Google)."""
    servizi = dettaglio.get("servizi", []) or []
    ld = {
        "@context": "https://schema.org",
        "@type": "Apartment",
        "name": dettaglio.get("titolo", ""),
        "description": dettaglio.get("descrizione", ""),
        "url": base_url + "/alloggio/" + str(dettaglio.get("slug", "")),
        "address": {"@type": "PostalAddress",
                    "addressLocality": dettaglio.get("citta", ""),
                    "addressCountry": dettaglio.get("paese", "")},
        "numberOfRooms": dettaglio.get("camere", 1),
        "occupancy": {"@type": "QuantitativeValue",
                      "maxValue": dettaglio.get("capacita", 1)},
        "amenityFeature": [{"@type": "LocationFeatureSpecification",
                            "name": s, "value": True} for s in servizi],
        "offers": {"@type": "Offer",
                   "price": _euro(dettaglio.get("prezzo_notte_cents", 0)),
                   "priceCurrency": dettaglio.get("valuta", "EUR")},
    }
    if isinstance(recensioni, dict) and recensioni.get("conteggio", 0) > 0:
        media = recensioni.get("media_centesimi", 0)
        ld["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": "%d.%02d" % (media // 100, media % 100),  # es. 4.25, no float
            "reviewCount": int(recensioni["conteggio"]),
            "bestRating": "5", "worstRating": "1",
        }
    return ld


def pagina_alloggio_html(sistema: Any, slug: str, base_url: str = "") -> Optional[str]:
    """Pagina HTML crawlabile (server-rendered) con JSON-LD. None se assente. Le SPA
    sono indicizzate male: questa rende il contenuto a Google e agli agenti SENZA JS."""
    import html
    try:
        d = sistema.catalogo.dettaglio(slug)
    except Exception:
        return None
    if d is None:
        return None
    e = html.escape
    rie = None
    if getattr(sistema, "recensioni", None) is not None:
        try:
            rr = sistema.recensioni.riepilogo(slug)
            rie = {"conteggio": rr["conteggio"], "media_centesimi": rr["media_centesimi"]}
        except Exception:
            rie = None
    servizi = "".join("<li>%s</li>" % e(str(s)) for s in d.get("servizi", []) or [])
    ld = json.dumps(jsonld_alloggio(d, base_url, rie), ensure_ascii=False)
    # neutralizza la chiusura del tag <script> dentro il JSON-LD (anti-XSS): unicode-escape
    ld = ld.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return (
        "<!DOCTYPE html><html lang=\"it\"><head><meta charset=\"UTF-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>%s - BookinVIP</title>"
        "<meta name=\"description\" content=\"%s\">"
        "<link rel=\"canonical\" href=\"%s/alloggio/%s\">"
        "<script type=\"application/ld+json\">%s</script></head><body>"
        "<h1>%s</h1><p><strong>%s</strong>%s</p><p>%s</p>"
        "<p>Prezzo: %s %s / notte</p><ul>%s</ul>"
        "<p><a href=\"/?slug=%s\">Prenota su BookinVIP</a></p></body></html>"
    ) % (
        e(d.get("titolo", "")), e(d.get("descrizione", ""))[:160],
        e(base_url), e(slug), ld,
        e(d.get("titolo", "")), e(d.get("citta", "")),
        ", " + e(d.get("paese", "")) if d.get("paese") else "",
        e(d.get("descrizione", "")),
        e(_euro(d.get("prezzo_notte_cents", 0))), e(d.get("valuta", "EUR")),
        servizi, e(slug),
    )


def sitemap_xml(sistema: Any, base_url: str = "") -> str:
    """sitemap.xml con tutte le schede pubblicate (per Google)."""
    from fase57_vetrina import CriteriRicerca, PAGINA_MAX
    slugs: List[str] = []
    offset = 0
    try:
        while offset < 10000:
            res = sistema.catalogo.cerca(CriteriRicerca(limit=PAGINA_MAX, offset=offset))
            righe = res.get("risultati", [])
            if not righe:
                break
            slugs.extend(str(r.get("slug", "")) for r in righe if r.get("slug"))
            if len(righe) < PAGINA_MAX:
                break
            offset += PAGINA_MAX
    except Exception:
        pass
    urls = "".join("<url><loc>%s/alloggio/%s</loc></url>" % (base_url, s) for s in slugs)
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            '<url><loc>%s/</loc></url>%s</urlset>' % (base_url, urls))


def robots_txt(base_url: str = "") -> str:
    return "User-agent: *\nAllow: /\nSitemap: %s/sitemap.xml\n" % base_url


class RouterHTTP:
    """Router PURO (testabile): cabla il SistemaCasaVIP (fase81) sulle rotte HTTP."""

    def __init__(self, sistema: Any, *, host_key: Optional[str] = None,
                 admin_key: Optional[str] = None) -> None:
        self._sys = sistema
        self._host_key = host_key
        self._admin_key = admin_key
        self._loc = Localizzatore()

    def gestisci(self, metodo: str, path: str, query: Optional[Dict[str, str]] = None,
                 body: Optional[str] = None,
                 headers: Optional[Dict[str, str]] = None) -> Tuple[int, Dict[str, Any]]:
        query = query or {}
        headers = headers or {}
        try:
            return self._instrada(metodo, path, query, body, headers)
        except Exception:
            logger.error("RouterHTTP: eccezione ISOLATA (-> 500)", exc_info=True)
            return 500, {"errore": "errore_interno"}

    def _instrada(self, metodo, path, query, body, headers):
        if not self._sys.attivo:
            return 503, {"errore": "sistema_spento"}
        if metodo == "GET" and path == "/api/health":
            return 200, {"status": "ok", "money_unit": "cents_integer"}
        if metodo == "GET" and path == "/api/lingue":
            return 200, {"lingue": list(LINGUE_SUPPORTATE)}
        if metodo == "GET" and path == "/api/i18n":
            return 200, _dizionario_i18n(_lingua(query))
        if metodo == "GET" and path == "/api/trasparenza":
            return self._trasparenza(query)
        if metodo == "GET" and path == "/api/catalogo":
            return self._catalogo(query)
        if metodo == "GET" and path.startswith("/api/catalogo/"):
            return self._dettaglio(path[len("/api/catalogo/"):], _lingua(query))
        if metodo == "POST" and path == "/api/concierge/quote":
            return self._concierge(self._sys.concierge.quota, body)
        if metodo == "POST" and path == "/api/concierge/book":
            return self._book(body)
        if metodo == "GET" and path.startswith("/api/recensioni/"):
            return self._recensioni(path[len("/api/recensioni/"):])
        if metodo == "POST" and path == "/api/recensioni":
            return self._invia_recensione(body)
        if metodo == "POST" and path == "/api/mcp":
            return self._mcp(body)
        if metodo == "POST" and path == "/api/host/pubblica":
            return self._host_pubblica(body, headers)
        if metodo == "POST" and path == "/api/host/disponibilita":
            return self._host_disponibilita(body, headers)
        if metodo == "POST" and path == "/api/host/disponibilita_range":
            return self._host_disponibilita_range(body, headers)
        if metodo == "POST" and path == "/api/host/ical":
            return self._host_ical(body, headers)
        if metodo == "GET" and path == "/api/admin/prenotazioni":
            return self._admin_prenotazioni(query, headers)
        if metodo == "POST" and path == "/api/admin/rimborso":
            return self._admin_rimborso(body, headers)
        return 404, {"errore": "rotta_non_trovata"}

    # --- helper ---
    @staticmethod
    def _json(body: Optional[str]) -> Optional[Dict[str, Any]]:
        try:
            d = json.loads(body) if body else None
            return d if isinstance(d, dict) else None
        except (ValueError, TypeError):
            return None

    def _auth_host(self, headers: Dict[str, str]) -> bool:
        if self._host_key is None:
            return True            # nessuna chiave configurata = aperto (dev)
        import hmac
        fornita = headers.get("X-Host-Key", "") or headers.get("x-host-key", "")
        return hmac.compare_digest(str(fornita), str(self._host_key))

    def _auth_admin(self, headers: Dict[str, str]) -> bool:
        if self._admin_key is None:
            return True            # nessuna chiave configurata = aperto (dev)
        import hmac
        fornita = headers.get("X-Admin-Key", "") or headers.get("x-admin-key", "")
        return hmac.compare_digest(str(fornita), str(self._admin_key))

    # --- admin: dashboard rimborsi ---
    def _admin_prenotazioni(self, query, headers):
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        alloggio = query.get("alloggio") or None
        try:
            el = self._sys.inventario.elenco_prenotazioni(alloggio_id=alloggio, limit=100)
        except Exception:
            logger.error("admin prenotazioni: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        return 200, {"prenotazioni": el}

    def _admin_rimborso(self, body, headers):
        """Rimborso = cancellazione: libera le date sull'inventario (fase58.rilascia).
        Il rimborso Stripe vero si esegue quando il PSP e' attivo (gated)."""
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        alloggio = dati.get("alloggio_id")
        ci, co = dati.get("check_in"), dati.get("check_out")
        idem = dati.get("idem_key")
        if not all(isinstance(x, str) and x for x in (alloggio, ci, co, idem)):
            return 422, {"errore": "campi_non_validi"}
        try:
            e = self._sys.inventario.rilascia(alloggio, ci, co, idem_key=idem)
        except Exception:
            logger.error("admin rimborso: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        if not getattr(e, "ok", False):
            return 409, {"stato": "rifiutato", "motivo": getattr(e, "motivo", "")}
        return 200, {"stato": "rimborsato", "date_liberate": True,
                     "idempotente": bool(getattr(e, "idempotente", False)),
                     "nota": "date liberate; rimborso PSP da eseguire quando Stripe e' live"}

    def _traduci_servizi(self, item: Dict[str, Any], lingua: str) -> Dict[str, Any]:
        if isinstance(item.get("servizi"), list):
            item = dict(item)
            item["servizi_label"] = [self._loc.servizio(c, lingua)
                                     for c in item["servizi"]]
        return item

    # --- rotte cliente ---
    def _catalogo(self, query):
        from fase57_vetrina import CriteriRicerca
        lingua = _lingua(query)

        def _int(k):
            try:
                return int(query[k]) if query.get(k) not in (None, "") else None
            except (ValueError, TypeError):
                return None
        servizi = tuple(s for s in query.get("servizi", "").split(",") if s)
        criteri = CriteriRicerca(
            citta=query.get("citta") or None,
            prezzo_min_cents=_int("prezzo_min_cents"),
            prezzo_max_cents=_int("prezzo_max_cents"),
            capacita_min=_int("capacita_min"), servizi=servizi,
            ordine=query.get("ordine", "recente"),
            limit=_int("limit") or 24, offset=_int("offset") or 0,
            check_in=query.get("check_in") or None,
            check_out=query.get("check_out") or None)
        res = self._sys.catalogo.cerca(criteri)
        res = dict(res)
        cards = []
        for r in res["risultati"]:
            card = self._traduci_servizi(r, lingua)
            rie = self._riepilogo_recensioni(card.get("slug"))
            if rie:
                card["recensioni"] = rie
            cards.append(card)
        res["risultati"] = cards
        res["lingua"] = lingua
        return 200, res

    # --- recensioni verificate (fase63) ---
    def _riepilogo_recensioni(self, slug: Any) -> Optional[Dict[str, Any]]:
        if self._sys.recensioni is None or not isinstance(slug, str):
            return None
        try:
            r = self._sys.recensioni.riepilogo(slug)
            return {"conteggio": r["conteggio"], "media_centesimi": r["media_centesimi"]}
        except Exception:
            return None

    def _recensioni(self, slug):
        if self._sys.recensioni is None:
            return 503, {"errore": "recensioni_disattivate"}
        try:
            rie = self._sys.recensioni.riepilogo(slug)
            elenco = self._sys.recensioni.elenco(slug, 20)
        except Exception:
            logger.error("recensioni: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        return 200, {"riepilogo": rie, "recensioni": elenco}

    def _invia_recensione(self, body):
        if self._sys.recensioni is None:
            return 503, {"errore": "recensioni_disattivate"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        e = self._sys.recensioni.invia(dati.get("token"), dati.get("voto"),
                                       dati.get("testo", ""), dati.get("lingua", "en"))
        status = 201 if e.ok else (409 if e.motivo == "gia_recensita" else 400)
        return status, {"ok": e.ok, "motivo": e.motivo, "verificata": e.verificata}

    def _book(self, body):
        """Prenotazione (fase59) + emissione del DIRITTO di recensione (fase63)."""
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        r = self._sys.concierge.prenota(dati)
        status = int(getattr(r, "status", 200))
        corpo = dict(getattr(r, "corpo", {}) or {})
        if status == 201 and self._sys.emettitore_recensioni is not None:
            try:
                corpo["diritto_recensione"] = self._sys.emettitore_recensioni.emetti(
                    corpo.get("riferimento", ""), corpo.get("alloggio_id", ""))
            except Exception:
                logger.warning("emissione diritto recensione fallita (ignorata)",
                               exc_info=True)
        return status, corpo

    def _trasparenza(self, query):
        """Confronto noi-vs-OTA (fase69): 'con Booking incassi X, con noi Y'."""
        from fase69_trasparenza import confronta_piattaforma
        try:
            prezzo = int(query.get("prezzo_cents", "0"))
        except (ValueError, TypeError):
            prezzo = 0
        ota = query.get("ota", "booking")
        return 200, confronta_piattaforma(prezzo, ota).as_dict()

    def _dettaglio(self, slug, lingua):
        d = self._sys.catalogo.dettaglio(slug)
        if d is None:
            return 404, {"errore": "not_found"}
        d = self._traduci_servizi(d, lingua)
        rie = self._riepilogo_recensioni(slug)
        if rie:
            d["recensioni"] = rie
        return 200, d

    def _concierge(self, fn, body):
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        r = fn(dati)
        return int(getattr(r, "status", 200)), getattr(r, "corpo", {}) or {}

    def _mcp(self, body):
        if self._sys.mcp is None:
            return 503, {"errore": "mcp_disattivato"}
        out = self._sys.mcp.gestisci_raw(body or "")
        if out is None:
            return 204, {}
        try:
            return 200, json.loads(out)
        except (ValueError, TypeError):
            return 200, {"raw": out}

    # --- rotte host ---
    def _host_pubblica(self, body, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        from fase57_vetrina import Immagine, SchedaAlloggio, valida_scheda
        ok, codice, scheda = valida_scheda(dati)
        if not ok:
            return 422, {"errore": "scheda_non_valida", "dettaglio": codice}
        imgs = [Immagine(u, i) for i, u in enumerate(dati.get("immagini", []))
                if isinstance(u, str)]
        self._sys.catalogo.pubblica(scheda, imgs)
        return 201, {"stato": "pubblicato", "slug": scheda.slug}

    def _host_disponibilita(self, body, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        alloggio = dati.get("alloggio_id")
        giorno = dati.get("giorno")
        unita = dati.get("unita_totali")
        prezzo = dati.get("prezzo_netto_cents")
        if not (isinstance(alloggio, str) and isinstance(giorno, str)
                and isinstance(unita, int) and not isinstance(unita, bool)
                and isinstance(prezzo, int) and not isinstance(prezzo, bool)):
            return 422, {"errore": "campi_non_validi"}
        ok = self._sys.inventario.imposta_disponibilita(
            alloggio, giorno, unita_totali=unita, prezzo_netto_cents=prezzo,
            chiuso=bool(dati.get("chiuso", False)))
        return (200 if ok else 422), {"stato": "ok" if ok else "rifiutato"}

    def _host_disponibilita_range(self, body, headers):
        """Apre un INTERO periodo (onboarding): imposta unita+prezzo per ogni notte
        [da, a). Max 366 giorni."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        import datetime
        alloggio = dati.get("alloggio_id")
        da, a = dati.get("da"), dati.get("a")
        unita, prezzo = dati.get("unita_totali"), dati.get("prezzo_netto_cents")
        if not (isinstance(alloggio, str) and isinstance(da, str) and isinstance(a, str)
                and isinstance(unita, int) and not isinstance(unita, bool)
                and isinstance(prezzo, int) and not isinstance(prezzo, bool)):
            return 422, {"errore": "campi_non_validi"}
        try:
            d0 = datetime.date.fromisoformat(da)
            d1 = datetime.date.fromisoformat(a)
        except (ValueError, TypeError):
            return 422, {"errore": "date_non_valide"}
        n = (d1 - d0).days
        if n <= 0 or n > 366:
            return 422, {"errore": "intervallo_non_valido"}
        impostati = 0
        for i in range(n):
            g = (d0 + datetime.timedelta(days=i)).isoformat()
            if self._sys.inventario.imposta_disponibilita(
                    alloggio, g, unita_totali=unita, prezzo_netto_cents=prezzo):
                impostati += 1
        return 200, {"giorni_impostati": impostati}

    def _host_ical(self, body, headers):
        """Importa il calendario iCal (Airbnb/Booking/Vrbo): blocca le date occupate
        sull'inventario (fase82). La vera portabilita' cross-canale."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        alloggio, ical = dati.get("alloggio_id"), dati.get("ical")
        if not (isinstance(alloggio, str) and alloggio and isinstance(ical, str)):
            return 422, {"errore": "campi_non_validi"}
        from fase82_ical_sync import sincronizza
        return 200, sincronizza(self._sys.inventario, alloggio, ical)


def crea_router(sistema: Any, *, host_key: Optional[str] = None,
                admin_key: Optional[str] = None) -> RouterHTTP:
    return RouterHTTP(sistema, host_key=host_key, admin_key=admin_key)


def percorso_statico_sicuro(path: str, cartella: str) -> Optional[str]:
    """Risolve un path statico DENTRO `cartella`, neutralizzando il path-traversal.
    Ritorna un percorso contenuto in `cartella`, o None (dotfile / fuori radice).
    PURO e testabile -> la difesa anti-`../`/`%00` e' un invariante, non uno slogan."""
    import os
    if not isinstance(path, str):
        return None
    nome = "index.html" if path in ("/", "") else path.lstrip("/")
    base = os.path.basename(nome)          # strip di ogni componente di directory
    if not base or base.startswith(".") or "\x00" in base:
        return None                         # niente dotfile (.env, .git...), niente NUL
    candidato = os.path.join(cartella, base)
    cart_real = os.path.realpath(cartella)
    cand_real = os.path.realpath(candidato)
    try:
        if os.path.commonpath([cart_real, cand_real]) != cart_real:
            return None                     # doppia cintura: mai fuori dalla radice
    except ValueError:
        return None
    return candidato


# ─────────────────────────────────────────────────────────────────────────────
# Server HTTP stdlib (thin wrapper, NON testato - I/O)
# ─────────────────────────────────────────────────────────────────────────────
def servi(sistema: Any, *, host: str = "127.0.0.1", porta: int = 8080,
          cartella_statica: str = "deploy", host_key: Optional[str] = None,
          base_url: str = "", admin_key: Optional[str] = None
          ) -> None:  # pragma: no cover
    import os
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse, parse_qs

    router = crea_router(sistema, host_key=host_key, admin_key=admin_key)

    class Handler(BaseHTTPRequestHandler):
        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Host-Key")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

        def _scrivi(self, status, corpo):
            dati = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self._cors()
            self.end_headers()
            self.wfile.write(dati)

        def _statico(self, path):
            fpath = percorso_statico_sicuro(path, cartella_statica)
            if fpath is None or not os.path.isfile(fpath):
                self._scrivi(404, {"errore": "file_non_trovato"})
                return
            with open(fpath, "rb") as f:
                dati = f.read()
            import mimetypes
            ctype = mimetypes.guess_type(fpath)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/json",
                                                       "application/javascript",
                                                       "image/svg+xml"):
                ctype += "; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Service-Worker-Allowed", "/")
            self._cors()
            self.end_headers()
            self.wfile.write(dati)

        def _testo(self, status, ctype, testo):
            dati = testo.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self._cors()
            self.end_headers()
            self.wfile.write(dati)

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            u = urlparse(self.path)
            if u.path.startswith("/api/"):
                query = {k: v[0] for k, v in parse_qs(u.query).items()}
                s, c = router.gestisci("GET", u.path, query, None, dict(self.headers))
                self._scrivi(s, c)
            elif u.path == "/sitemap.xml":
                self._testo(200, "application/xml", sitemap_xml(sistema, base_url))
            elif u.path == "/robots.txt":
                self._testo(200, "text/plain", robots_txt(base_url))
            elif u.path.startswith("/alloggio/"):
                html = pagina_alloggio_html(sistema, u.path[len("/alloggio/"):], base_url)
                if html is None:
                    self._scrivi(404, {"errore": "not_found"})
                else:
                    self._testo(200, "text/html", html)
            else:
                self._statico(u.path)

        def do_POST(self):
            u = urlparse(self.path)
            lung = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(lung).decode("utf-8") if lung else ""
            s, c = router.gestisci("POST", u.path, {}, body, dict(self.headers))
            self._scrivi(s, c)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer((host, porta), Handler)
    logger.info("BookinVIP server su http://%s:%d", host, porta)
    srv.serve_forever()
