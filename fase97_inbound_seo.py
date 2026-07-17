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

LINGUE = ("it", "en", "es", "fr", "de", "pt", "ja", "zh")

# Data (YYYY-MM-DD) in cui il CONTENUTO/template delle landing è cambiato l'ultima volta.
# Va nel <lastmod> della sitemap inbound. Le landing sono generate da codice (città × lingua):
# cambiano solo quando cambia questo template o le tariffe → il lastmod è una COSTANTE che si
# bumpa a mano quando cambia il contenuto. NON usare now(): un lastmod che cambia a ogni
# generazione senza che il contenuto cambi è una bugia e i crawler smettono di fidarsene.
SEO_LASTMOD = "2026-07-17"

# hreflang lingua+PAESE: per i mercati dove UNA lingua serve regioni distinte (targeting
# geografico legittimo, non penalizzato — è l'uso previsto di hreflang, es. en-US/en-GB). Ogni
# variante-regione è un URL DISTINTO, self-canonical e reciproco. it/ja restano solo-lingua
# (mercato unico dominante). Curata (anti-spam: una regione fuori mappa viene ignorata).
REGIONI_HREFLANG: Dict[str, Tuple[str, ...]] = {
    "en": ("US", "GB"), "es": ("ES", "MX"), "pt": ("PT", "BR"),
    "fr": ("FR", "CA"), "de": ("DE", "AT"), "zh": ("CN", "TW"),
}
# territorio di default per og:locale quando manca la regione (formato language_TERRITORY).
TERRITORIO_DEFAULT: Dict[str, str] = {
    "it": "IT", "en": "US", "es": "ES", "fr": "FR",
    "de": "DE", "pt": "PT", "ja": "JP", "zh": "CN",
}

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


def maglia_link_interni(citta: Sequence[str] = CITTA_SEED, *,
                        k: int = 6) -> Dict[str, List[str]]:
    """ALGORITMO 'maglia small-world' per i link interni tra le landing città — crawl-ottimale e
    white-hat (policy Google: link interni RILEVANTI e in numero ragionevole, non l'elenco intero
    ripetuto = pattern 'link farm'). Proprietà garantite:
      (1) FORTEMENTE CONNESSO: ogni pagina è raggiungibile da ogni altra → nessun orfano, il
          crawler arriva ovunque (l'anello i→(i+1) è un ciclo hamiltoniano che copre tutti).
      (2) DIAMETRO PICCOLO: k-1 'corde' a passo ~n/k accorciano le distanze (topologia
          small-world) → link-equity distribuita e crawl efficiente (pochi hop tra due pagine).
      (3) GRADO COSTANTE e LIMITATO: ogni pagina ha esattamente k link (non 27) → niente
          boilerplate ripetuto, segnale di rilevanza più forte.
    Puro e DETERMINISTICO (ordine canonico per slug) → interamente testabile in sandbox."""
    nomi: List[str] = []
    visti = set()
    for c in citta:
        s = slug_citta(c)
        if s and s not in visti:
            visti.add(s)
            nomi.append(c)
    nomi.sort(key=slug_citta)                        # ordine canonico deterministico
    n = len(nomi)
    if n <= 1:
        return {c: [] for c in nomi}
    k_eff = max(1, min(int(k) if isinstance(k, int) else 6, n - 1))
    strides = [1]                                    # anello: connessione forte garantita
    for j in range(1, k_eff):
        strides.append(round(j * n / k_eff) % n)     # corde small-world
    out: Dict[str, List[str]] = {}
    for i, c in enumerate(nomi):
        vicini: List[str] = []
        usati = {i}
        for st in strides:
            idx = (i + st) % n
            if idx not in usati:
                usati.add(idx)
                vicini.append(nomi[idx])
        step = 1                                     # riempi se collisioni (n piccolo)
        while len(vicini) < k_eff and step < n:
            idx = (i + step) % n
            if idx not in usati:
                usati.add(idx)
                vicini.append(nomi[idx])
            step += 1
        out[c] = vicini
    return out


def vicini_di(citta: str, tutte: Sequence[str] = CITTA_SEED, *, k: int = 6) -> List[str]:
    """I k vicini di UNA città nella maglia (per la rotta /affitta/<slug>). [] se città ignota.
    Confronto per slug: robusto se `citta` non è identica a un elemento di `tutte`."""
    m = maglia_link_interni(tutte, k=k)
    if citta in m:
        return m[citta]
    s = slug_citta(citta)
    for c, vic in m.items():
        if slug_citta(c) == s:
            return vic
    return []


def registro_citta(citta_inventario: Sequence[str] = (), *,
                   seed: Sequence[str] = CITTA_SEED) -> List[str]:
    """REGISTRO DETERMINISTICO delle città che hanno diritto a una landing. Unione di:
      - SEED curati (mercati-obiettivo per l'acquisizione host: sempre presenti, sono lander
        host-acquisition con calcolatore risparmio + FAQ = valore proprio, non doorway);
      - città con INVENTARIO reale (data-driven dal catalogo): così la superficie SEO cresce
        verso le 195 nazioni SOLO dove c'è valore vero, senza generare pagine vuote (= niente
        doorway / scaled-content abuse penalizzato da Google).
    Dedup per slug (prima occorrenza vince), ordine canonico per slug → stabile e testabile.
    Una città FUORI dal registro NON ha pagina (la rotta risponde 404): è il gate anti-doorway."""
    visti: Dict[str, str] = {}
    for c in list(seed) + list(citta_inventario or ()):
        s = slug_citta(c)
        if s and s not in visti:
            visti[s] = c
    return [visti[s] for s in sorted(visti)]


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
    "pt": {
        "title": "Alugue o seu imóvel em {citta} sem comissões altas | BookinVIP",
        "desc": "Anfitriões em {citta}: pare de dar {ota}% ao Booking/Airbnb. Com a BookinVIP "
                "paga apenas {noi}% e fica com mais em cada reserva. Grátis, self-service.",
        "h1": "Aluga em {citta}? Fique com mais em cada noite.",
        "intro": "As OTA ficam com até {ota}% — muitas vezes com clientes que já são SEUS "
                 "(boca a boca, Instagram, recorrentes). A BookinVIP cobra {noi}% e dá-lhe site "
                 "de reservas, pagamento, voucher e check-in automático — grátis.",
        "calc": "Numa noite de €{prezzo}: com a OTA fica com €{netto_ota}, connosco €{netto_noi} "
                "→ <b>+€{risparmio} por noite</b>.",
        "cta": "Publique o seu alojamento grátis",
        "rel": "Alugueres noutras cidades",
        "faqh": "Perguntas frequentes",
    },
    "ja": {
        "title": "{citta}で高い手数料なしに貸し出す | BookinVIP",
        "desc": "{citta}のホストの皆様：Booking/Airbnbに{ota}%を払うのはやめましょう。BookinVIPなら"
                "手数料は{noi}%だけ、予約ごとに手元に多く残ります。無料・セルフサービス。",
        "h1": "{citta}で貸していますか？1泊ごとに手元に多く残しましょう。",
        "intro": "OTAは最大{ota}%を取ります——多くは口コミ・Instagram・リピーターなど、すでに"
                 "あなたの顧客からです。BookinVIPの手数料は{noi}%で、予約サイト・決済・バウチャー・"
                 "セルフチェックインが無料で使えます。",
        "calc": "1泊€{prezzo}の場合：OTAでは手元に€{netto_ota}、当社なら€{netto_noi} "
                "→ <b>+€{risparmio}/泊</b>。",
        "cta": "無料で掲載する",
        "rel": "他の都市で貸す",
        "faqh": "よくある質問",
    },
    "zh": {
        "title": "在{citta}出租，无高额佣金 | BookinVIP",
        "desc": "{citta}的房东：不要再把{ota}%交给Booking/Airbnb。用BookinVIP只需支付{noi}%，"
                "每笔预订留存更多。免费、自助。",
        "h1": "在{citta}出租？每晚留存更多。",
        "intro": "OTA最高抽取{ota}%——往往还是你自己的客户（口碑、Instagram、回头客）。"
                 "BookinVIP只收{noi}%，并免费提供预订网站、支付、凭证和自助入住。",
        "calc": "以每晚€{prezzo}为例：通过OTA你留存€{netto_ota}，通过我们€{netto_noi} "
                "→ <b>每晚+€{risparmio}</b>。",
        "cta": "免费发布你的房源",
        "rel": "在其他城市出租",
        "faqh": "常见问题",
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
    "pt": [("Quanto custa a BookinVIP?", "Publicar é grátis. Paga apenas uma comissão de "
            "{noi}% por reserva — abaixo dos {ota}% das grandes OTA."),
           ("Tenho de deixar o Booking/Airbnb?", "Não. Use em paralelo: importa o calendário "
            "iCal e as datas ficam sincronizadas, sem overbooking."),
           ("Como recebo os pagamentos?", "Por pagamento seguro; recebe um voucher assinado "
            "que é também a chave do check-in automático. Tudo automático.")],
    "ja": [("BookinVIPの利用料は？", "掲載は無料です。予約ごとに{noi}%の手数料のみ——"
            "大手OTAの{ota}%より低い料金です。"),
           ("Booking/Airbnbをやめる必要は？", "いいえ。併用できます：iCalカレンダーを取り込めば"
            "日程は同期され、ダブルブッキングを防ぎます。"),
           ("支払いはどう受け取りますか？", "安全な決済を通じて。署名付きバウチャー"
            "（セルフチェックインの鍵も兼ねる）を受け取ります。すべて自動です。")],
    "zh": [("使用BookinVIP要多少钱？", "发布免费。每笔预订只需支付{noi}%的佣金——"
            "低于大型OTA的{ota}%。"),
           ("我必须离开Booking/Airbnb吗？", "不必。可同时使用：导入iCal日历，日期自动同步，"
            "避免超额预订。"),
           ("我如何收款？", "通过安全支付；你会收到签名凭证，它也是自助入住的钥匙。全部自动。")],
}


def _jsonld(obj: object) -> str:
    """JSON-LD con < > & neutralizzati (niente break-out da <script>), come fase83."""
    return (json.dumps(obj, ensure_ascii=False)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def faq_jsonld(lingua: str = "it", *, commissione_bps: int = 1000,
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


def breadcrumb_jsonld(citta: str, base_url: str = "", *, lingua: str = "it",
                      canonical: Optional[str] = None) -> str:
    """BreadcrumbList Schema.org (Home > città): rich result + gerarchia chiara per i crawler.
    Il nome città è dato grezzo → `_jsonld` neutralizza <>& (XSS-safe come faq_jsonld). Se
    `canonical` è dato, l'item punta a quello (coerente col locale della pagina)."""
    lng = lingua if lingua in _T else "en"
    base = (base_url or "").rstrip("/")
    slug = slug_citta(citta)
    if not canonical:
        canonical = base + "/affitta/" + slug + ("?lang=" + lng if lng != "it" else "")
    home = (base + "/") if base else "/"
    return _jsonld({"@context": "https://schema.org", "@type": "BreadcrumbList",
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": "Home", "item": home},
                        {"@type": "ListItem", "position": 2, "name": citta,
                         "item": canonical}]})


def _lang_regione(codice: Any) -> Tuple[str, Optional[str]]:
    """'es-MX' -> ('es','MX'); 'es' -> ('es',None). Lingua ignota -> ('en',None). Regione fuori
    dalla mappa curata -> ignorata (anti-spam: niente locali arbitrari indicizzabili)."""
    if not isinstance(codice, str):
        return ("it", None)
    parti = codice.replace("_", "-").split("-", 1)
    lang = parti[0].lower()
    reg = parti[1].upper() if len(parti) > 1 and parti[1] else None
    if lang not in _T:
        return ("en", None)
    if reg and reg not in REGIONI_HREFLANG.get(lang, ()):
        reg = None
    return (lang, reg)


def _bcp47(lang: str, regione: Optional[str]) -> str:
    return "%s-%s" % (lang, regione) if regione else lang


def locali_hreflang() -> List[str]:
    """Tutti i codici hreflang (lingue + varianti-regione curate), ordine deterministico."""
    out: List[str] = []
    for L in _T:
        out.append(L)
        for rr in REGIONI_HREFLANG.get(L, ()):
            out.append("%s-%s" % (L, rr))
    return out


def _url_locale(base: str, slug: str, codice: str) -> str:
    """URL della landing per un locale. Default (it) = URL pulito; resto = ?lang=<codice>."""
    return base + "/affitta/" + slug + ("" if codice == "it" else "?lang=" + codice)


def genera_landing_host(citta: str, *, lingua: str = "it", base_url: str = "",
                        commissione_bps: int = 1500, ota_bps: int = 2500,
                        prezzo_demo_cents: int = 10000,
                        citta_correlate: Sequence[str] = ()) -> str:
    """Pagina landing host per una città (SEO + FAQ JSON-LD + calcolo + CTA). XSS-safe.
    `lingua` accetta un codice BCP-47 (es. 'es-MX'): il testo usa la lingua base, mentre
    canonical/hreflang/og:locale usano il locale completo (targeting lingua+paese)."""
    lang, regione = _lang_regione(lingua)
    lng = lang                                        # lingua base per testi/JSON-LD
    codice = _bcp47(lang, regione)                    # BCP-47 completo (es. 'es-MX')
    t = _T[lng]
    noi, ota = _pct(commissione_bps), _pct(ota_bps)
    r = risparmio_notte(prezzo_demo_cents, commissione_bps, ota_bps)
    e = html.escape
    citta_e = e(citta)
    slug = slug_citta(citta)
    base = (base_url or "").rstrip("/")
    canonical = _url_locale(base, slug, codice)       # self-canonical del locale corrente

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
        "<!doctype html><html lang=\"%s\"><head><meta charset=\"utf-8\">" % codice
        + "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        + "<title>" + fmt(t["title"]) + "</title>"
        + "<meta name=\"description\" content=\"" + fmt(t["desc"]) + "\">"
        + "<link rel=\"canonical\" href=\"" + e(canonical) + "\">"
        # hreflang lingua+PAESE: ogni locale è un URL distinto, il set è identico su tutte le
        # varianti (reciproco) + x-default -> Google mostra la variante giusta per regione.
        + "".join(
            "<link rel=\"alternate\" hreflang=\"%s\" href=\"%s\">"
            % (code, e(_url_locale(base, slug, code)))
            for code in locali_hreflang())
        + "<link rel=\"alternate\" hreflang=\"x-default\" href=\""
        + e(base + "/affitta/" + slug) + "\">"
        + "<meta property=\"og:title\" content=\"" + fmt(t["title"]) + "\">"
        + "<meta property=\"og:type\" content=\"website\">"
        + "<meta property=\"og:url\" content=\"" + e(canonical) + "\">"
        + "<meta property=\"og:locale\" content=\""
        + (lang + "_" + (regione or TERRITORIO_DEFAULT.get(lang, "US"))) + "\">"
        + "".join(
            "<meta property=\"og:locale:alternate\" content=\"%s_%s\">"
            % (L2, TERRITORIO_DEFAULT.get(L2, "US"))
            for L2 in _T if L2 != lang)
        + "<script type=\"application/ld+json\">"
        + faq_jsonld(lng, commissione_bps=commissione_bps, ota_bps=ota_bps)
        + "</script>"
        + "<script type=\"application/ld+json\">"
        + breadcrumb_jsonld(citta, base_url=base, lingua=lng, canonical=canonical)
        + "</script>"
        + "<style>body{font-family:system-ui,Segoe UI,sans-serif;max-width:46rem;"
          "margin:2rem auto;padding:0 1rem;line-height:1.6;color:#1a1e2b}"
          "h1{color:#1e3c72}.box{background:#eef6ff;border-radius:1rem;padding:1rem 1.2rem;"
          "margin:1.2rem 0}.cta{display:inline-block;background:#1e3c72;color:#fff;"
          "padding:.8rem 1.6rem;border-radius:2rem;text-decoration:none;font-weight:600}"
          "details{margin:.5rem 0}summary{cursor:pointer;font-weight:600}"
          "nav a{color:#2a5298;margin-right:.4rem;font-size:.9rem}</style></head><body>"
        # <main> = contenuto primario isolato dal boilerplate (assistive tech "salta al
        # contenuto" + estrattori/crawler, inclusi gli AEO, distinguono corpo da navigazione).
        # Il <nav> "altre citta'" resta FUORI dal <main>: e' navigazione, e la pagina deve
        # avere UN SOLO <main>. La FAQ e' una <section> etichettata dal suo <h2> (regione
        # nominata + specchio del FAQPage JSON-LD).
        + "<main>"
        + "<h1>" + fmt(t["h1"]) + "</h1>"
        + "<p>" + fmt(t["intro"]) + "</p>"
        + "<div class=\"box\">" + fmt(t["calc"]) + "</div>"
        + "<p><a class=\"cta\" href=\"" + e(cta_url) + "\">" + e(t["cta"]) + "</a></p>"
        + "<section aria-labelledby=\"faq\"><h2 id=\"faq\">" + e(t["faqh"]) + "</h2>"
        + faq_html + "</section>"
        + "</main>"
        + ("<nav aria-labelledby=\"rel\"><h2 id=\"rel\">" + e(t["rel"]) + "</h2>"
           + rel_links + "</nav>" if rel_links else "")
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
                    lingue: Sequence[str] = LINGUE, lastmod: str = SEO_LASTMOD) -> str:
    """sitemap.xml delle landing host (una per città × lingua) per l'indicizzazione. Ogni <url>
    porta il <lastmod> (data in cui il template è cambiato): i crawler usano questo segnale per
    il budget di scansione (ricrawl solo se cambiato)."""
    base = (base_url or "").rstrip("/")
    lm = ("<lastmod>%s</lastmod>" % html.escape(lastmod)) if lastmod else ""
    urls = []
    for c in citta:
        s = slug_citta(c)
        if not s:
            continue
        for lng in lingue:
            loc = base + "/affitta/" + s + ("?lang=" + lng if lng != "it" else "")
            urls.append("<url><loc>%s</loc>%s</url>" % (html.escape(loc), lm))
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(urls) + "</urlset>")
