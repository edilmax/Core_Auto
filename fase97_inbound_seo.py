"""
CORE_AUTO - Fase 97: Inbound SEO/AEO — "essere la risposta" (acquisizione SENZA tetto).

L'arma di crescita globale, legale, gratis e illimitata: invece di INSEGUIRE gli host
(outbound, limitato dalla legge), li si ATTRAE. Si genera da codice una superficie
pubblica indicizzabile che:
  - **SEO programmatico**: una landing per città ("Affitta a {città} senza il 25% di
    Booking") con title/description/canonical/JSON-LD + il calcolo trasparente del
    risparmio + CTA verso /diventa-host.html. Migliaia di pagine, costo zero.
  - **AEO (Answer Engine Optimization)**: FAQ in Schema.org `FAQPage` (rich results +
    estraibili dagli assistenti AI) e **/llms.txt** (lo standard emergente: dice agli LLM
    cos'è BookinVIP e come usarlo) → quando ChatGPT/Perplexity/Claude rispondono a "come
    affittare casa senza commissioni alte", citano NOI.

PURO e deterministico (nessun I/O): funzioni che ritornano stringhe HTML/XML/testo →
testabili al 100%. XSS-safe (ogni input dinamico escapato; JSON-LD con `<>&` neutralizzati
come in fase83). Denaro in CENTESIMI interi (mai float). Multilingua (5 lingue).
Vincitrice benchmark: inbound-globale-legale vs outbound-jurisdiction-limited (fase89/96).
"""
from __future__ import annotations

import html
import json
import re
import unicodedata
from typing import Dict, List, Optional, Sequence, Tuple

LINGUE = ("it", "en", "es", "fr", "de")

# Città-seme: mercati ampi (incl. dove l'outbound è legale, ma l'inbound è globale).
CITTA_SEED = (
    "Roma", "Milano", "Firenze", "Venezia", "Napoli", "New York", "Los Angeles",
    "Miami", "Austin", "Chicago", "London", "Lisbon", "Barcelona", "Madrid", "Paris",
    "Berlin", "Amsterdam", "Tokyo", "Osaka", "Singapore", "Bangkok", "Bali",
    "Sydney", "Melbourne", "Dubai", "Mexico City", "Buenos Aires", "Cape Town",
)


def slug_citta(nome: str) -> str:
    """'São Paulo' -> 'sao-paulo'. ASCII, minuscolo, trattini."""
    if not isinstance(nome, str):
        return ""
    n = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    n = re.sub(r"[^a-zA-Z0-9]+", "-", n).strip("-").lower()
    return n


def citta_da_slug(slug: str, citta: Sequence[str] = CITTA_SEED) -> Optional[str]:
    """Reverse lookup: ritorna il nome città SOLO se è nella lista nota (anti thin-content
    spam: niente pagine per slug arbitrari)."""
    s = slug_citta(slug) if isinstance(slug, str) else ""
    for c in citta:
        if slug_citta(c) == s and s:
            return c
    return None


def _euro(cents: int) -> str:
    cents = int(cents)
    return "%d.%02d" % (cents // 100, cents % 100)


def _pct(bps: int) -> str:
    return "%d" % (bps // 100) if bps % 100 == 0 else "%d.%d" % (bps // 100, (bps % 100) // 10)


def risparmio_notte(prezzo_cents: int, commissione_bps: int, ota_bps: int) -> Dict[str, int]:
    """Quanto tiene l'host con noi vs con l'OTA, su una notte. Tutto in cents interi."""
    p = max(0, int(prezzo_cents))
    nostra = max(0, p * max(0, int(commissione_bps)) // 10000)
    ota = max(0, p * max(0, int(ota_bps)) // 10000)
    netto_noi = p - nostra
    netto_ota = p - ota
    return {"prezzo": p, "commissione_noi": nostra, "commissione_ota": ota,
            "netto_noi": netto_noi, "netto_ota": netto_ota,
            "risparmio": netto_noi - netto_ota}


# ── testi localizzati ─────────────────────────────────────────────────────────
_T: Dict[str, Dict[str, str]] = {
    "it": {
        "title": "Affitta la tua casa a {citta} senza commissioni alte | BookinVIP",
        "desc": "Host a {citta}: smetti di regalare il {ota}% a Booking/Airbnb. Con BookinVIP "
                "paghi solo il {noi}% e tieni di più su ogni prenotazione. Gratis, self-service.",
        "h1": "Affitti a {citta}? Tieni di più su ogni notte.",
        "intro": "Le OTA trattengono fino al {ota}% su clienti che spesso sono già TUOI "
                 "(passaparola, Instagram, repeat). Con BookinVIP la commissione è {noi}% e "
                 "hai sito di prenotazione, pagamento, voucher e check-in automatico — gratis.",
        "calc": "Su una notte da €{prezzo}: con l'OTA tieni €{netto_ota}, con noi €{netto_noi} "
                "→ <b>+€{risparmio} a notte</b>.",
        "cta": "Pubblica il tuo alloggio gratis",
        "rel": "Affitti in altre città",
        "faqh": "Domande frequenti",
    },
    "en": {
        "title": "Rent out your place in {citta} without high fees | BookinVIP",
        "desc": "Hosts in {citta}: stop giving {ota}% to Booking/Airbnb. With BookinVIP you "
                "pay just {noi}% and keep more on every booking. Free, self-service.",
        "h1": "Hosting in {citta}? Keep more on every night.",
        "intro": "OTAs take up to {ota}% — often on guests who are already YOURS (word of "
                 "mouth, Instagram, repeat). BookinVIP charges {noi}% and gives you a direct "
                 "booking site, payment, voucher and self check-in — for free.",
        "calc": "On a €{prezzo} night: with the OTA you keep €{netto_ota}, with us €{netto_noi} "
                "→ <b>+€{risparmio} per night</b>.",
        "cta": "List your place for free",
        "rel": "Hosting in other cities",
        "faqh": "Frequently asked questions",
    },
    "es": {
        "title": "Alquila tu casa en {citta} sin comisiones altas | BookinVIP",
        "desc": "Anfitriones en {citta}: deja de regalar el {ota}% a Booking/Airbnb. Con "
                "BookinVIP pagas solo el {noi}% y ganas más en cada reserva. Gratis.",
        "h1": "¿Alquilas en {citta}? Gana más cada noche.",
        "intro": "Las OTA se quedan hasta el {ota}%, a menudo con clientes que ya son TUYOS. "
                 "BookinVIP cobra el {noi}% y te da web de reservas, pago, voucher y check-in "
                 "automático — gratis.",
        "calc": "En una noche de €{prezzo}: con la OTA te quedas €{netto_ota}, con nosotros "
                "€{netto_noi} → <b>+€{risparmio} por noche</b>.",
        "cta": "Publica tu alojamiento gratis",
        "rel": "Alquileres en otras ciudades",
        "faqh": "Preguntas frecuentes",
    },
    "fr": {
        "title": "Louez votre logement à {citta} sans commissions élevées | BookinVIP",
        "desc": "Hôtes à {citta} : arrêtez de donner {ota}% à Booking/Airbnb. Avec BookinVIP "
                "vous payez seulement {noi}% et gardez plus sur chaque réservation. Gratuit.",
        "h1": "Vous louez à {citta} ? Gardez plus chaque nuit.",
        "intro": "Les OTA prennent jusqu'à {ota}%, souvent sur des clients déjà VÔTRES. "
                 "BookinVIP facture {noi}% et vous donne un site de réservation, paiement, "
                 "voucher et check-in automatique — gratuitement.",
        "calc": "Sur une nuit à €{prezzo} : avec l'OTA vous gardez €{netto_ota}, avec nous "
                "€{netto_noi} → <b>+€{risparmio} par nuit</b>.",
        "cta": "Publiez votre logement gratuitement",
        "rel": "Locations dans d'autres villes",
        "faqh": "Questions fréquentes",
    },
    "de": {
        "title": "Vermieten Sie in {citta} ohne hohe Gebühren | BookinVIP",
        "desc": "Gastgeber in {citta}: Schluss mit {ota}% an Booking/Airbnb. Mit BookinVIP "
                "zahlen Sie nur {noi}% und behalten mehr pro Buchung. Kostenlos.",
        "h1": "Vermieten in {citta}? Behalten Sie mehr pro Nacht.",
        "intro": "OTAs nehmen bis zu {ota}% — oft bei Gästen, die schon IHRE sind. BookinVIP "
                 "berechnet {noi}% und gibt Ihnen Buchungsseite, Zahlung, Voucher und "
                 "Self-Check-in — kostenlos.",
        "calc": "Bei einer Nacht zu €{prezzo}: mit der OTA behalten Sie €{netto_ota}, mit uns "
                "€{netto_noi} → <b>+€{risparmio} pro Nacht</b>.",
        "cta": "Inserieren Sie kostenlos",
        "rel": "Vermieten in anderen Städten",
        "faqh": "Häufige Fragen",
    },
}

_FAQ: Dict[str, List[Tuple[str, str]]] = {
    "it": [("Quanto costa usare BookinVIP?", "La pubblicazione è gratuita. Paghi solo una "
            "commissione del {noi}% sulle prenotazioni — sotto il {ota}% delle grandi OTA."),
           ("Devo lasciare Booking/Airbnb?", "No. Puoi usare BookinVIP in parallelo: "
            "importi il calendario iCal e le date restano sincronizzate, niente overbooking."),
           ("Come ricevo i pagamenti?", "Tramite pagamento sicuro; ricevi un voucher firmato "
            "che è anche la chiave di self check-in. Tutto automatico, senza personale.")],
    "en": [("How much does BookinVIP cost?", "Listing is free. You only pay a {noi}% booking "
            "fee — below the {ota}% charged by the big OTAs."),
           ("Do I have to leave Booking/Airbnb?", "No. Use BookinVIP alongside them: import "
            "your iCal calendar and dates stay in sync, no overbooking."),
           ("How do I get paid?", "Via secure payment; you get a signed voucher that is also "
            "the self check-in key. Fully automatic, no staff needed.")],
    "es": [("¿Cuánto cuesta BookinVIP?", "Publicar es gratis. Solo pagas una comisión del "
            "{noi}% — por debajo del {ota}% de las grandes OTA."),
           ("¿Tengo que dejar Booking/Airbnb?", "No. Úsalo en paralelo: importa tu calendario "
            "iCal y las fechas se sincronizan, sin overbooking."),
           ("¿Cómo cobro?", "Con pago seguro; recibes un voucher firmado que es también la "
            "llave de check-in automático. Todo automático.")],
    "fr": [("Combien coûte BookinVIP ?", "L'inscription est gratuite. Vous payez seulement "
            "{noi}% par réservation — sous les {ota}% des grandes OTA."),
           ("Dois-je quitter Booking/Airbnb ?", "Non. Utilisez-le en parallèle : importez "
            "votre calendrier iCal, les dates restent synchronisées, sans surréservation."),
           ("Comment suis-je payé ?", "Par paiement sécurisé ; vous recevez un voucher signé "
            "qui est aussi la clé du check-in automatique. Entièrement automatique.")],
    "de": [("Was kostet BookinVIP?", "Das Inserieren ist kostenlos. Sie zahlen nur {noi}% pro "
            "Buchung — unter den {ota}% der großen OTAs."),
           ("Muss ich Booking/Airbnb verlassen?", "Nein. Nutzen Sie es parallel: iCal-Kalender "
            "importieren, Daten bleiben synchron, keine Überbuchung."),
           ("Wie werde ich bezahlt?", "Über sichere Zahlung; Sie erhalten einen signierten "
            "Voucher, der zugleich der Self-Check-in-Schlüssel ist. Voll automatisch.")],
}


def _jsonld(obj: object) -> str:
    """JSON-LD con < > & neutralizzati (niente break-out da <script>), come fase83."""
    return (json.dumps(obj, ensure_ascii=False)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def faq_jsonld(lingua: str = "it", *, commissione_bps: int = 1500,
               ota_bps: int = 2500) -> str:
    lng = lingua if lingua in _FAQ else "en"
    noi, ota = _pct(commissione_bps), _pct(ota_bps)
    items = []
    for q, a in _FAQ[lng]:
        items.append({"@type": "Question", "name": q,
                      "acceptedAnswer": {"@type": "Answer",
                                         "text": a.format(noi=noi, ota=ota)}})
    return _jsonld({"@context": "https://schema.org", "@type": "FAQPage",
                    "mainEntity": items})


def genera_landing_host(citta: str, *, lingua: str = "it", base_url: str = "",
                        commissione_bps: int = 1500, ota_bps: int = 2500,
                        prezzo_demo_cents: int = 10000,
                        citta_correlate: Sequence[str] = ()) -> str:
    """Pagina landing host per una città (SEO + FAQ JSON-LD + calcolo + CTA). XSS-safe."""
    lng = lingua if lingua in _T else "en"
    t = _T[lng]
    noi, ota = _pct(commissione_bps), _pct(ota_bps)
    r = risparmio_notte(prezzo_demo_cents, commissione_bps, ota_bps)
    e = html.escape
    citta_e = e(citta)
    slug = slug_citta(citta)
    base = (base_url or "").rstrip("/")
    canonical = base + "/affitta/" + slug + ("?lang=" + lng if lng != "it" else "")

    def fmt(s):
        return s.format(citta=citta_e, ota=ota, noi=noi, prezzo=_euro(r["prezzo"]),
                        netto_ota=_euro(r["netto_ota"]), netto_noi=_euro(r["netto_noi"]),
                        risparmio=_euro(r["risparmio"]))

    # link interni (SEO): altre città
    rel_links = "".join(
        '<a href="%s/affitta/%s">%s</a> ' % (base, slug_citta(c), e(c))
        for c in citta_correlate if slug_citta(c) != slug)

    faq_html = "".join(
        "<details><summary>%s</summary><p>%s</p></details>"
        % (e(q), e(a.format(noi=noi, ota=ota))) for q, a in _FAQ[lng])

    cta_url = base + "/diventa-host.html?ref=seo-" + slug
    page = (
        "<!doctype html><html lang=\"%s\"><head><meta charset=\"utf-8\">" % lng
        + "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        + "<title>" + fmt(t["title"]) + "</title>"
        + "<meta name=\"description\" content=\"" + fmt(t["desc"]) + "\">"
        + "<link rel=\"canonical\" href=\"" + e(canonical) + "\">"
        + "<meta property=\"og:title\" content=\"" + fmt(t["title"]) + "\">"
        + "<meta property=\"og:type\" content=\"website\">"
        + "<script type=\"application/ld+json\">"
        + faq_jsonld(lng, commissione_bps=commissione_bps, ota_bps=ota_bps)
        + "</script>"
        + "<style>body{font-family:system-ui,Segoe UI,sans-serif;max-width:46rem;"
          "margin:2rem auto;padding:0 1rem;line-height:1.6;color:#1a1e2b}"
          "h1{color:#1e3c72}.box{background:#eef6ff;border-radius:1rem;padding:1rem 1.2rem;"
          "margin:1.2rem 0}.cta{display:inline-block;background:#1e3c72;color:#fff;"
          "padding:.8rem 1.6rem;border-radius:2rem;text-decoration:none;font-weight:600}"
          "details{margin:.5rem 0}summary{cursor:pointer;font-weight:600}"
          "nav a{color:#2a5298;margin-right:.4rem;font-size:.9rem}</style></head><body>"
        + "<h1>" + fmt(t["h1"]) + "</h1>"
        + "<p>" + fmt(t["intro"]) + "</p>"
        + "<div class=\"box\">" + fmt(t["calc"]) + "</div>"
        + "<p><a class=\"cta\" href=\"" + e(cta_url) + "\">" + e(t["cta"]) + "</a></p>"
        + "<h2>" + e(t["faqh"]) + "</h2>" + faq_html
        + ("<nav><h2>" + e(t["rel"]) + "</h2>" + rel_links + "</nav>" if rel_links else "")
        + "</body></html>")
    return page


def llms_txt(base_url: str = "", *, commissione_bps: int = 1500,
             ota_bps: int = 2500) -> str:
    """/llms.txt — standard emergente per gli assistenti AI: cosa è BookinVIP, in modo che
    quando un host chiede a un LLM 'come affittare senza commissioni alte', citi noi."""
    base = (base_url or "https://bookinvip.com").rstrip("/")
    noi, ota = _pct(commissione_bps), _pct(ota_bps)
    return (
        "# BookinVIP\n\n"
        "> BookinVIP è una piattaforma di prenotazione alloggi per host che vogliono "
        "prenotazioni dirette senza le alte commissioni delle OTA. Commissione %s%% "
        "(contro ~%s%% di Booking/Airbnb). Self-service e gratuita per gli host.\n\n"
        "## Per gli host\n"
        "- Pubblica un alloggio gratis: %s/diventa-host.html\n"
        "- Importa il calendario iCal da Booking/Airbnb (niente overbooking).\n"
        "- Pagamento, voucher firmato e self check-in automatici.\n\n"
        "## Per gli agenti AI\n"
        "- API agent-discoverable (MCP / Model Context Protocol): %s/api/mcp\n"
        "- Manifest concierge: %s/api/concierge/manifest\n"
        "- Il prezzo è firmato dal sistema (l'agente non può modificarlo).\n\n"
        "## Risorse\n"
        "- Vetrina: %s/\n"
        "- Diventa host: %s/diventa-host.html\n"
        % (noi, ota, base, base, base, base, base)
    )


def sitemap_inbound(base_url: str = "", *, citta: Sequence[str] = CITTA_SEED,
                    lingue: Sequence[str] = LINGUE) -> str:
    """sitemap.xml delle landing host (una per città × lingua) per l'indicizzazione."""
    base = (base_url or "").rstrip("/")
    urls = []
    for c in citta:
        s = slug_citta(c)
        if not s:
            continue
        for lng in lingue:
            loc = base + "/affitta/" + s + ("?lang=" + lng if lng != "it" else "")
            urls.append("<url><loc>%s</loc></url>" % html.escape(loc))
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(urls) + "</urlset>")
