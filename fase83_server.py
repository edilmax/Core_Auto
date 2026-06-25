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
    # voucher
    "voucher_ok": {"it": "Prenotazione confermata", "en": "Booking confirmed",
                   "es": "Reserva confirmada", "fr": "Reservation confirmee",
                   "de": "Buchung bestatigt"},
    "rif": {"it": "Riferimento", "en": "Reference", "es": "Referencia",
            "fr": "Reference", "de": "Referenz"},
    "dal": {"it": "Dal", "en": "From", "es": "Desde", "fr": "Du", "de": "Von"},
    "al": {"it": "Al", "en": "To", "es": "Hasta", "fr": "Au", "de": "Bis"},
    "self_pass": {"it": "Check-in autonomo: mostra questo codice alla serratura",
                  "en": "Self check-in: show this code at the lock",
                  "es": "Auto check-in: muestra este codigo en la cerradura",
                  "fr": "Auto check-in : montrez ce code a la serrure",
                  "de": "Self-Check-in: diesen Code am Schloss zeigen"},
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
    # Due sitemap: alloggi (vetrina) + landing host inbound SEO (fase97).
    return ("User-agent: *\nAllow: /\nSitemap: %s/sitemap.xml\n"
            "Sitemap: %s/sitemap-host.xml\n" % (base_url, base_url))


def _notti_count(ci: Any, co: Any) -> int:
    import datetime
    try:
        return (datetime.date.fromisoformat(str(co))
                - datetime.date.fromisoformat(str(ci))).days
    except (ValueError, TypeError):
        return 0


def genera_csv_prenotazioni(righe: Any) -> str:
    """CSV delle prenotazioni per la contabilita' (stdlib csv, niente dipendenze)."""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["alloggio", "check_in", "check_out", "notti", "origine", "stato",
                "revenue_eur", "riferimento"])
    for r in (righe or []):
        if not isinstance(r, dict):
            continue
        rev = r.get("revenue_cents", 0)
        rev = rev if isinstance(rev, int) and not isinstance(rev, bool) else 0
        w.writerow([
            r.get("alloggio_id", ""), r.get("check_in", ""), r.get("check_out", ""),
            _notti_count(r.get("check_in"), r.get("check_out")),
            r.get("origine", ""), "rimborsata" if r.get("rimborsato") else "attiva",
            "%d.%02d" % (rev // 100, rev % 100), str(r.get("idem_key", ""))[:16],
        ])
    return buf.getvalue()


def pagina_voucher_html(sistema: Any, token: Any, lingua: str = "it") -> Optional[str]:
    """Voucher di conferma (server-rendered, stampabile, multilingua). Verifica la firma
    del token (non falsificabile). None se assente/manomesso/non un voucher."""
    import html
    firma = getattr(sistema, "firma", None)
    if firma is None:
        return None
    dati = firma.decodifica(token)
    if not isinstance(dati, dict) or dati.get("tipo") != "voucher":
        return None
    lng = lingua if lingua in LINGUE_SUPPORTATE else "it"
    e = html.escape
    prezzo = "%d.%02d" % (dati.get("prezzo_guest_cents", 0) // 100,
                          dati.get("prezzo_guest_cents", 0) % 100)
    pass_code = e(str(dati.get("smart_pass", "")))
    blocco_pass = ("<div style='margin-top:1.2rem;padding:1rem;background:#f0f4fe;"
                   "border-radius:1rem'><strong>%s</strong><br>"
                   "<code style='word-break:break-all;font-size:.8rem'>%s</code></div>"
                   ) % (e(_ui("self_pass", lng)), pass_code) if pass_code else ""
    return (
        "<!DOCTYPE html><html lang=\"%s\"><head><meta charset=\"UTF-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Voucher BookinVIP</title><style>body{font-family:system-ui,sans-serif;"
        "background:#f4f6fa;color:#1a1e2b;padding:2rem;max-width:480px;margin:0 auto}"
        ".v{background:#fff;border-radius:1.5rem;padding:2rem;box-shadow:0 8px 24px "
        "rgba(0,0,0,.06)}h1{color:#1e3c72}.r{display:flex;justify-content:space-between;"
        "padding:.3rem 0;border-bottom:1px solid #eef2f7}</style></head><body><div class=\"v\">"
        "<div style=\"font-weight:700;color:#1e3c72;font-size:1.3rem\">BookinVIP</div>"
        "<h1>✓ %s</h1>"
        "<div class=\"r\"><span>%s</span><strong>%s</strong></div>"
        "<div class=\"r\"><span>%s</span><strong>%s</strong></div>"
        "<div class=\"r\"><span>%s</span><strong>%s</strong></div>"
        "<div class=\"r\"><span>%s</span><strong>%s %s</strong></div>"
        "%s</div></body></html>"
    ) % (
        e(lng), e(_ui("voucher_ok", lng)),
        e(_ui("rif", lng)), e(str(dati.get("riferimento", ""))),
        e(_ui("dal", lng)), e(str(dati.get("check_in", ""))),
        e(_ui("al", lng)), e(str(dati.get("check_out", ""))),
        e(_ui("totale", lng)), e(prezzo), e(str(dati.get("valuta", "EUR"))),
        blocco_pass,
    )


class RouterHTTP:
    """Router PURO (testabile): cabla il SistemaCasaVIP (fase81) sulle rotte HTTP."""

    def __init__(self, sistema: Any, *, host_key: Optional[str] = None,
                 admin_key: Optional[str] = None, base_url: str = "") -> None:
        self._sys = sistema
        self._host_key = host_key
        self._admin_key = admin_key
        self._base_url = base_url or ""
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
        if metodo == "POST" and path == "/api/payments/webhook":
            return self._webhook_stripe(body, headers)
        if metodo == "POST" and path == "/api/marketing/campagna":
            return self._marketing_campagna(body, headers)
        if metodo == "GET" and path == "/api/tassa":
            return self._tassa(query)
        if metodo == "POST" and path == "/api/split/crea":
            return self._split_crea(body)
        if metodo == "POST" and path == "/api/split/paga":
            return self._split_paga(body)
        if metodo == "GET" and path == "/api/split/stato":
            return self._split_stato(query)
        if metodo == "POST" and path == "/api/messaggi":
            return self._msg_invia(body, headers)
        if metodo == "GET" and path == "/api/messaggi":
            return self._msg_thread(query, headers)
        if metodo == "GET" and path == "/api/host/invito":
            return self._host_invito(headers)
        if metodo == "GET" and path == "/api/host/prezzo_suggerito":
            return self._prezzo_suggerito(query, headers)
        if metodo == "POST" and path == "/api/host/invito/registra":
            return self._host_invito_registra(body)
        if metodo == "POST" and path == "/api/host/invito/qualifica":
            return self._host_invito_qualifica(body, headers)
        if metodo == "POST" and path == "/api/host/pubblica":
            return self._host_pubblica(body, headers)
        if metodo == "POST" and path == "/api/host/disponibilita":
            return self._host_disponibilita(body, headers)
        if metodo == "POST" and path == "/api/host/disponibilita_range":
            return self._host_disponibilita_range(body, headers)
        if metodo == "POST" and path == "/api/host/registrazione":
            return self._host_registrazione(body)
        if metodo == "POST" and path == "/api/host/login":
            return self._host_login(body)
        if metodo == "GET" and path == "/api/host/referral":
            return self._host_referral(query, headers)
        if metodo == "POST" and path == "/api/host/ical":
            return self._host_ical(body, headers)
        if metodo == "GET" and path == "/api/host/metriche":
            return self._host_metriche(query, headers)
        if metodo == "GET" and path == "/api/host/calendario":
            return self._host_calendario(query, headers)
        if metodo == "GET" and path == "/api/host/export":
            return self._host_export(query, headers)
        if metodo == "GET" and path == "/api/host/alloggi":
            return self._host_alloggi(query, headers)
        if metodo == "POST" and path == "/api/host/stato":
            return self._host_stato(body, headers)
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

    def _host_id_da_token(self, headers: Dict[str, str]) -> Optional[str]:
        """host_id se la richiesta porta un token host self-service valido, altrimenti None."""
        reg = getattr(self._sys, "registro_host", None)
        if reg is None:
            return None
        tok = headers.get("X-Host-Token", "") or headers.get("x-host-token", "")
        if not tok:
            return None
        try:
            return reg.verifica_token(tok)
        except Exception:
            return None

    def _auth_host(self, headers: Dict[str, str]) -> bool:
        # 1) token host self-service valido
        if self._host_id_da_token(headers):
            return True
        # 2) chiave condivisa dell'operatore (o dev aperto se non configurata)
        if self._host_key is None:
            return True
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
        if status == 201:
            ref = corpo.get("riferimento", "")
            allog = corpo.get("alloggio_id", "")
            ci, co = corpo.get("check_in", ""), corpo.get("check_out", "")
            # smart-pass per il self check-in (incluso nel voucher)
            pass_token = None
            if self._sys.emettitore_pass is not None:
                try:
                    pass_token = self._sys.emettitore_pass.emetti(ref, allog, ci, co)
                    corpo["smart_pass"] = pass_token
                except Exception:
                    logger.warning("emissione smart-pass fallita (ignorata)",
                                   exc_info=True)
            # voucher firmato (conferma + entry pass)
            if getattr(self._sys, "firma", None) is not None:
                try:
                    corpo["voucher_token"] = self._sys.firma.codifica({
                        "tipo": "voucher", "riferimento": ref, "alloggio_id": allog,
                        "check_in": ci, "check_out": co,
                        "prezzo_guest_cents": corpo.get("prezzo_guest_cents", 0),
                        "valuta": corpo.get("valuta", "EUR"),
                        "smart_pass": pass_token or ""})
                except Exception:
                    logger.warning("emissione voucher fallita (ignorata)", exc_info=True)
            # diritto di recensione
            if self._sys.emettitore_recensioni is not None:
                try:
                    corpo["diritto_recensione"] = self._sys.emettitore_recensioni.emetti(
                        ref, allog)
                except Exception:
                    logger.warning("emissione diritto recensione fallita (ignorata)",
                                   exc_info=True)
            # email del voucher all'ospite (best-effort, isolata)
            email = dati.get("email")
            if getattr(self._sys, "email_provider", None) is not None \
                    and isinstance(email, str) and "@" in email:
                try:
                    from fase86_email import corpo_voucher_html
                    vurl = (self._base_url + "/voucher/" + corpo["voucher_token"]) \
                        if corpo.get("voucher_token") else ""
                    html = corpo_voucher_html(allog, ref, ci, co, vurl)
                    self._sys.email_provider.invia(
                        email, "BookinVIP - Prenotazione confermata", html)
                except Exception:
                    logger.warning("invio email voucher fallito (ignorato)",
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

    def _marketing_campagna(self, body, headers):
        """Genera + pubblica una campagna sui canali configurati (gated da env).
        Admin-only. Senza canali -> report con tutti saltati (niente rete)."""
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        mk = getattr(self._sys, "marketing", None)
        if mk is None:
            return 503, {"errore": "marketing_non_attivo"}
        d = self._json(body) or {}
        lingue = d.get("lingue") if isinstance(d.get("lingue"), list) else ["it", "en"]
        try:
            rep = mk.esegui_campagna([str(l) for l in lingue][:5])
        except Exception:
            logger.error("marketing campagna: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        return 200, rep

    # --- motori: tassa di soggiorno (66) + split-payment (65) ---
    def _tassa(self, query):
        eng = getattr(self._sys, "tasse", None)
        if eng is None:
            return 503, {"errore": "tassa_non_attiva"}
        try:
            notti = int(query.get("notti", "0"))
            ospiti = int(query.get("ospiti", "0"))
            imp = int(query.get("imponibile_cents", "0"))
            esenti = int(query.get("esenti", "0"))
        except (ValueError, TypeError):
            return 422, {"errore": "parametri_non_validi"}
        giur = query.get("giurisdizione") or query.get("citta") or ""
        return 200, eng.calcola(giur, notti=notti, ospiti=ospiti,
                                imponibile_cents=imp, esenti=esenti).as_dict()

    def _split_crea(self, body):
        eng = getattr(self._sys, "split", None)
        if eng is None:
            return 503, {"errore": "split_non_attivo"}
        d = self._json(body)
        if d is None:
            return 400, {"errore": "json_non_valido"}
        try:
            cid = eng.crea_conto(
                str(d.get("prenotazione_id", "")), str(d.get("alloggio_id", "")),
                d.get("totale_cents"), d.get("partecipanti") or [],
                metodo=str(d.get("metodo", "equo")), importi=d.get("importi"))
        except Exception:
            logger.error("split crea: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        if not cid:
            return 422, {"errore": "conto_non_valido"}
        return 201, {"conto_id": cid, "stato": eng.stato_conto(cid)}

    def _split_paga(self, body):
        eng = getattr(self._sys, "split", None)
        if eng is None:
            return 503, {"errore": "split_non_attivo"}
        d = self._json(body)
        if d is None:
            return 400, {"errore": "json_non_valido"}
        conto = str(d.get("conto_id", ""))
        part = str(d.get("partecipante_id", ""))
        idem = d.get("idem_key") or (conto + ":" + part)   # idempotente per partecipante
        try:
            e = eng.registra_pagamento(conto, part, idem_key=str(idem))
        except Exception:
            logger.error("split paga: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        if not e.ok:
            return 409, {"stato": "rifiutato", "motivo": e.motivo}
        return 200, {"stato": "pagato", "completato": bool(e.completato),
                     "idempotente": bool(getattr(e, "idempotente", False))}

    def _split_stato(self, query):
        eng = getattr(self._sys, "split", None)
        if eng is None:
            return 503, {"errore": "split_non_attivo"}
        st = eng.stato_conto(query.get("conto_id", ""))
        if st is None:
            return 404, {"errore": "conto_inesistente"}
        return 200, st

    def _webhook_stripe(self, body, headers):
        """Webhook Stripe (conferma pagamento): verifica la FIRMA sul body GREZZO prima di
        credere all'evento. GATED dal webhook secret."""
        secret = getattr(getattr(self._sys, "config", None), "stripe_webhook_secret", "")
        if not secret:
            return 503, {"errore": "webhook_non_configurato"}
        from fase87_stripe_webhook import gestisci_webhook
        sig = headers.get("Stripe-Signature", "") or headers.get("stripe-signature", "")
        ok, tipo, dati = gestisci_webhook(body or "", sig, secret)
        if not ok:
            return 400, {"errore": "firma_non_valida"}
        if tipo == "checkout.session.completed":
            rif = ""
            try:
                rif = (dati or {}).get("object", {}).get("metadata", {}).get(
                    "riferimento", "")
            except Exception:
                rif = ""
            logger.info("Stripe: pagamento CONFERMATO per riferimento '%s'", rif)
        return 200, {"ricevuto": True, "tipo": tipo}

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
    def _host_registrazione(self, body):
        """L'host crea il proprio account DA SOLO (self-service): niente onboarding manuale."""
        reg = getattr(self._sys, "registro_host", None)
        if reg is None:
            return 503, {"errore": "registrazione_non_attiva"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        e = reg.registra(dati.get("email"), dati.get("password"),
                         accetta_termini=bool(dati.get("accetta_termini")),
                         ragione_sociale=str(dati.get("ragione_sociale", "")))
        out = e.as_dict()
        # viral loop: se è arrivato con un codice referral, accredita referente+referee
        if e.ok:
            codice = dati.get("codice_referral")
            viral = getattr(self._sys, "viral", None)
            if viral is not None and isinstance(codice, str) and codice:
                try:
                    r = viral.registra_referee(codice, e.host_id)
                    out["referral"] = {"ok": r.ok,
                                       "credito_cents": r.credito_referee_cents if r.ok else 0}
                except Exception:
                    logger.warning("referral su registrazione fallito (ignorato)",
                                   exc_info=True)
        return (201 if e.ok else 422), out

    def _host_login(self, body):
        reg = getattr(self._sys, "registro_host", None)
        if reg is None:
            return 503, {"errore": "registrazione_non_attiva"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        e = reg.login(dati.get("email"), dati.get("password"))
        return (200 if e.ok else 401), e.as_dict()

    def _host_referral(self, query, headers):
        """Link di invito dell'host + credito disponibile (viral loop fase76)."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        viral = getattr(self._sys, "viral", None)
        if viral is None:
            return 503, {"errore": "viral_non_attivo"}
        host_id = self._host_id_da_token(headers) or query.get("host_id")
        if not (isinstance(host_id, str) and host_id):
            return 422, {"errore": "host_id_mancante"}
        try:
            codice = viral.genera_codice(host_id, tipo="host")
            credito = viral.credito_disponibile(host_id)
        except Exception:
            logger.error("host referral: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        if not codice:
            return 503, {"errore": "codice_non_generato"}
        from urllib.parse import quote
        link = self._base_url + "/diventa-host.html?ref=" + quote(codice)
        return 200, {"codice": codice, "link": link, "credito_cents": int(credito)}

    def _prezzo_suggerito(self, query, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        import fase106_dynamic_pricing as dyn

        def _qi(k, d):
            try:
                return int(query.get(k, d))
            except (TypeError, ValueError):
                return d
        base = _qi("prezzo_base_cents", 0)
        if base <= 0:
            return 422, {"errore": "prezzo_base_non_valido"}
        return 200, dyn.calcola_prezzo(
            base, occupazione_bps=_qi("occupazione_bps", 5000),
            data=query.get("data", ""), giorni_all_arrivo=_qi("giorni", 30))

    def _host_invito(self, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        ref = getattr(self._sys, "referral", None)
        if ref is None:
            return 503, {"errore": "referral_non_attivo"}
        hid = self._host_id_da_token(headers) or "host"
        codice = ref.genera_codice(hid)
        if not codice:
            return 422, {"errore": "codice_non_generato"}
        from urllib.parse import quote
        link = (self._base_url or "") + "/diventa-host.html?ref=" + quote(codice)
        return 200, {"codice": codice, "link": link, "crediti_cents": ref.crediti(hid)}

    def _host_invito_registra(self, body):
        ref = getattr(self._sys, "referral", None)
        if ref is None:
            return 503, {"errore": "referral_non_attivo"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        codice = dati.get("codice")
        nuovo = dati.get("nuovo_host_id")
        if not (isinstance(codice, str) and isinstance(nuovo, str)):
            return 422, {"errore": "campi_non_validi"}
        ok = ref.registra_referral(codice, nuovo)
        return (201, {"stato": "registrato"}) if ok else (409, {"errore": "non_registrabile"})

    def _host_invito_qualifica(self, body, headers):
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        ref = getattr(self._sys, "referral", None)
        if ref is None:
            return 503, {"errore": "referral_non_attivo"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        nuovo = dati.get("nuovo_host_id")
        if not isinstance(nuovo, str):
            return 422, {"errore": "campi_non_validi"}
        bonus = ref.conferma_qualifica(nuovo)
        return 200, {"bonus_cents": bonus}

    def _msg_invia(self, body, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        msg = getattr(self._sys, "messaggistica", None)
        if msg is None:
            return 503, {"errore": "messaggistica_non_attiva"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        pren = dati.get("prenotazione_id")
        guest = dati.get("guest_id")
        testo = dati.get("testo")
        mittente = self._host_id_da_token(headers) or "host"
        if not (isinstance(pren, str) and isinstance(guest, str) and isinstance(testo, str)):
            return 422, {"errore": "campi_non_validi"}
        ok = msg.invia(pren, mittente, guest, mittente, testo)
        return (201, {"stato": "inviato"}) if ok else (422, {"errore": "non_inviato"})

    def _msg_thread(self, query, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        msg = getattr(self._sys, "messaggistica", None)
        if msg is None:
            return 503, {"errore": "messaggistica_non_attiva"}
        pren = query.get("prenotazione_id", "")
        richiedente = self._host_id_da_token(headers) or "host"
        return 200, {"messaggi": msg.thread(pren, richiedente)}

    def _host_pubblica(self, body, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        # se autenticato con token self-service, l'host pubblica SOLO sotto il proprio id
        hid = self._host_id_da_token(headers)
        if hid:
            dati = dict(dati)
            dati["host_id"] = hid
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

    def _host_metriche(self, query, headers):
        """Dashboard host: revenue/occupazione (fase58) + prenotazioni + recensioni."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        alloggio = query.get("alloggio") or None
        da, a = query.get("da") or None, query.get("a") or None
        try:
            inv = self._sys.inventario.metriche(alloggio_id=alloggio, da=da, a=a)
            pren = self._sys.inventario.elenco_prenotazioni(alloggio_id=alloggio,
                                                            limit=500)
        except Exception:
            logger.error("host metriche: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        attive = sum(1 for p in pren if not p["rimborsato"])
        out = {
            "revenue_cents": inv["revenue_cents"],
            "occupazione_bps": inv["occupazione_bps"],
            "notti_occupate": inv["notti_occupate"],
            "notti_totali": inv["notti_totali"],
            "prenotazioni_attive": attive,
            "prenotazioni_rimborsate": len(pren) - attive,
            "valuta": self._valuta_sys(),
            "money_unit": "cents_integer",
        }
        rie = self._riepilogo_recensioni(alloggio) if alloggio else None
        if rie:
            out["recensioni"] = rie
        return 200, out

    def _valuta_sys(self) -> str:
        return getattr(getattr(self._sys, "config", None), "valuta", "EUR")

    def _revenue_prenotazione(self, p: Dict[str, Any]) -> int:
        if p.get("rimborsato"):
            return 0
        try:
            cal = self._sys.inventario.calendario(p.get("alloggio_id", ""),
                                                  p.get("check_in", ""),
                                                  p.get("check_out", ""))
            return sum(g.get("prezzo_netto_cents", 0) for g in cal
                       if isinstance(g.get("prezzo_netto_cents"), int))
        except Exception:
            return 0

    def _host_export(self, query, headers):
        """Export CSV delle prenotazioni (contabilita'). Il CSV viaggia come stringa nel
        JSON; il frontend lo scarica come file."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        alloggio = query.get("alloggio") or None
        try:
            righe = self._sys.inventario.elenco_prenotazioni(alloggio_id=alloggio,
                                                             limit=500)
        except Exception:
            logger.error("host export: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        for r in righe:
            r["revenue_cents"] = self._revenue_prenotazione(r)
        return 200, {"csv": genera_csv_prenotazioni(righe), "righe": len(righe)}

    def _host_alloggi(self, query, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        host_id = query.get("host_id")
        if not (isinstance(host_id, str) and host_id):
            return 422, {"errore": "host_id_mancante"}
        try:
            el = self._sys.catalogo.alloggi_host(host_id, limit=200)
        except Exception:
            logger.error("host alloggi: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        return 200, {"alloggi": el}

    def _host_stato(self, body, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        slug, stato = dati.get("slug"), dati.get("stato")
        if not (isinstance(slug, str) and slug and isinstance(stato, str)):
            return 422, {"errore": "campi_non_validi"}
        ok = self._sys.catalogo.imposta_stato(slug, stato)
        return (200 if ok else 422), {"stato": stato if ok else "rifiutato"}

    def _host_calendario(self, query, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        alloggio = query.get("alloggio")
        da, a = query.get("da"), query.get("a")
        if not (isinstance(alloggio, str) and alloggio and isinstance(da, str)
                and isinstance(a, str)):
            return 422, {"errore": "campi_non_validi"}
        try:
            cal = self._sys.inventario.calendario(alloggio, da, a)
        except Exception:
            logger.error("host calendario: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        return 200, {"giorni": cal}

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
                admin_key: Optional[str] = None, base_url: str = "") -> RouterHTTP:
    return RouterHTTP(sistema, host_key=host_key, admin_key=admin_key, base_url=base_url)


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
    from urllib.parse import urlparse, parse_qs, unquote

    router = crea_router(sistema, host_key=host_key, admin_key=admin_key,
                         base_url=base_url)

    # --- Auto-pubblicazione campagna (GATED, default-off): parte solo se nel .env c'è
    #     CAMPAGNA_AUTO_GIORNI e il sistema ha un motore marketing. Isolato: se fallisce,
    #     il server parte lo stesso.
    _giorni = os.environ.get("CAMPAGNA_AUTO_GIORNI", "").strip()
    if _giorni and getattr(sistema, "marketing", None) is not None:
        try:
            from fase94_scheduler_campagna import crea_scheduler_campagna
            sched = crea_scheduler_campagna(
                sistema.marketing, percorso=os.environ.get(
                    "CAMPAGNA_STATO_FILE", ".campagna_stato.json"),
                cadenza_giorni=int(_giorni))
            sched.avvia_in_thread(intervallo_sec=3600.0)
            logging.getLogger("core_auto.server").info(
                "Scheduler campagna AVVIATO: ogni %s giorni", _giorni)
        except Exception:
            logging.getLogger("core_auto.server").warning(
                "Scheduler campagna NON avviato (ISOLATO)", exc_info=True)

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
                slug = unquote(u.path[len("/alloggio/"):])
                html = pagina_alloggio_html(sistema, slug, base_url)
                if html is None:
                    self._scrivi(404, {"errore": "not_found"})
                else:
                    self._testo(200, "text/html", html)
            elif u.path.startswith("/voucher/"):
                query = {k: v[0] for k, v in parse_qs(u.query).items()}
                lng = query.get("lang", "it")
                html = pagina_voucher_html(sistema, unquote(u.path[len("/voucher/"):]), lng)
                if html is None:
                    self._scrivi(404, {"errore": "voucher_non_valido"})
                else:
                    self._testo(200, "text/html", html)
            elif u.path.startswith("/affitta/"):
                # Inbound SEO/AEO (fase97): landing host per città (server-rendered,
                # crawlabile). Solo città note → niente thin-content da slug arbitrari.
                try:
                    from fase97_inbound_seo import (CITTA_SEED, citta_da_slug,
                                                    genera_landing_host)
                    query = {k: v[0] for k, v in parse_qs(u.query).items()}
                    citta = citta_da_slug(unquote(u.path[len("/affitta/"):]))
                    if citta is None:
                        self._scrivi(404, {"errore": "citta_non_trovata"})
                    else:
                        bps = int(os.environ.get("COMMISSIONE_BPS", "1500"))
                        self._testo(200, "text/html", genera_landing_host(
                            citta, lingua=query.get("lang", "it"), base_url=base_url,
                            commissione_bps=bps, citta_correlate=CITTA_SEED[:8]))
                except Exception:
                    self._scrivi(500, {"errore": "interno"})
            elif u.path == "/llms.txt":
                from fase97_inbound_seo import llms_txt
                bps = int(os.environ.get("COMMISSIONE_BPS", "1500"))
                self._testo(200, "text/plain",
                            llms_txt(base_url, commissione_bps=bps))
            elif u.path == "/sitemap-host.xml":
                from fase97_inbound_seo import sitemap_inbound
                self._testo(200, "application/xml", sitemap_inbound(base_url))
            elif u.path == "/stop":
                # Disiscrizione PUBBLICA (link nelle email outreach). Nessuna auth: il
                # destinatario deve poter dire stop. Opt-out scritto in modo DUREVOLE.
                query = {k: v[0] for k, v in parse_qs(u.query).items()}
                email = (query.get("e") or query.get("email") or "").strip()
                fatto = False
                try:
                    from fase95_outreach_email import StoreOptOut
                    StoreOptOut(os.environ.get("OUTREACH_OPTOUT_FILE",
                                               ".outreach_optout.json")).aggiungi(email)
                    fatto = bool(email)
                except Exception:
                    logging.getLogger("core_auto.server").warning(
                        "opt-out /stop fallito (ISOLATO)", exc_info=True)
                msg = ("✅ Disiscritto. Non riceverai più nostre email." if fatto
                       else "Indirizzo email mancante o non valido.")
                self._testo(200, "text/html",
                            "<!doctype html><meta charset=utf-8><title>BookinVIP</title>"
                            "<body style='font-family:system-ui;max-width:32rem;margin:4rem "
                            "auto;text-align:center'><h1>BookinVIP</h1><p style='font-size:"
                            "1.1rem'>%s</p></body>" % msg)
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
