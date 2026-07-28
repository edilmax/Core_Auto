"""
CORE_AUTO - Fase 198: BLOG / GUIDA multilingua (canale di crescita SEO, ZERO-account, sempre-attivo).

Un blog è il canale gratis più duraturo: contenuto SEMPREVERDE, indicizzabile, che porta visite per
anni senza spendere. Qui è generato DA CODICE (come le landing fase97): niente CMS, niente
dipendenze. Ogni articolo è una pagina server-rendered con title/description/canonical, **hreflang**
lingua+paese, **JSON-LD** (Article + BreadcrumbList = rich result e citabile dagli answer-engine AI),
link interni verso le landing città (/affitta) e /diventa-host → distribuisce link-equity e converte.

PURO e deterministico (nessun I/O): funzioni che ritornano stringhe HTML/XML → testabili al 100%.
XSS-safe (ogni testo escapato; JSON-LD con <>& neutralizzati). Contenuto VERO e generale (perché la
prenotazione diretta, come funziona il check-in): niente affermazioni fiscali/legali inventate.

Lingue: le 8 "vetted" dell'app (le 5 asiatiche di fase97 si aggiungono con rilettura madrelingua per
la qualità del testo lungo). Aggiungere un articolo = aggiungere un dict ad ARTICOLI (il motore scala).
"""
from __future__ import annotations

import html
import json
from typing import Dict, List, Optional, Sequence, Tuple

BLOG_LINGUE: Tuple[str, ...] = ("it", "en", "es", "fr", "de", "pt", "ja", "zh")

# Data (YYYY-MM-DD) in cui il contenuto del blog è cambiato l'ultima volta → <lastmod> sitemap.
BLOG_LASTMOD = "2026-07-24"

TERRITORIO: Dict[str, str] = {
    "it": "IT", "en": "US", "es": "ES", "fr": "FR",
    "de": "DE", "pt": "PT", "ja": "JP", "zh": "CN",
}

# etichette d'interfaccia del blog (indice, breadcrumb, CTA) per lingua.
_UI: Dict[str, Dict[str, str]] = {
    "it": {"blog": "Guida BookinVIP", "tutti": "Tutti gli articoli", "home": "Home",
           "cta": "Pubblica il tuo alloggio gratis", "leggi": "Leggi", "altri": "Altri articoli"},
    "en": {"blog": "BookinVIP Guide", "tutti": "All articles", "home": "Home",
           "cta": "List your place for free", "leggi": "Read", "altri": "More articles"},
    "es": {"blog": "Guía BookinVIP", "tutti": "Todos los artículos", "home": "Inicio",
           "cta": "Publica tu alojamiento gratis", "leggi": "Leer", "altri": "Más artículos"},
    "fr": {"blog": "Guide BookinVIP", "tutti": "Tous les articles", "home": "Accueil",
           "cta": "Publiez votre logement gratuitement", "leggi": "Lire", "altri": "Plus d'articles"},
    "de": {"blog": "BookinVIP-Ratgeber", "tutti": "Alle Artikel", "home": "Start",
           "cta": "Inserieren Sie kostenlos", "leggi": "Lesen", "altri": "Weitere Artikel"},
    "pt": {"blog": "Guia BookinVIP", "tutti": "Todos os artigos", "home": "Início",
           "cta": "Publique o seu alojamento grátis", "leggi": "Ler", "altri": "Mais artigos"},
    "ja": {"blog": "BookinVIP ガイド", "tutti": "すべての記事", "home": "ホーム",
           "cta": "無料で掲載する", "leggi": "読む", "altri": "その他の記事"},
    "zh": {"blog": "BookinVIP 指南", "tutti": "全部文章", "home": "首页",
           "cta": "免费发布你的房源", "leggi": "阅读", "altri": "更多文章"},
}


def _art(slug: str, data: str, T: Dict[str, Dict[str, object]]) -> Dict[str, object]:
    return {"slug": slug, "data": data, "T": T}


# ── Articoli (sempreverdi, valore vero). corpo = lista di paragrafi. ─────────────────
ARTICOLI: List[Dict[str, object]] = [
    _art("prenotazioni-dirette", "2026-07-24", {
        "it": {"titolo": "Perché le prenotazioni dirette convengono agli host",
               "sommario": "Le grandi OTA trattengono fino a un quarto dell'incasso su clienti che "
                           "spesso sono già tuoi. Ecco perché la prenotazione diretta ti fa tenere di più.",
               "corpo": ["Ogni prenotazione che arriva da un grande portale porta con sé una "
                         "commissione elevata. Il problema è che molti di quegli ospiti ti "
                         "avrebbero trovato comunque: dal passaparola, dai social, dai clienti "
                         "che tornano. Su di loro la commissione è denaro regalato.",
                         "Con la prenotazione diretta l'ospite paga te, tu tieni di più e resti "
                         "padrone del rapporto: dati di contatto, offerte per il ritorno, "
                         "recensioni. BookinVIP ti dà un sito di prenotazione, pagamento sicuro, "
                         "voucher e check-in automatico — con una commissione molto più bassa.",
                         "Non devi lasciare i portali: puoi usarli in parallelo e sincronizzare il "
                         "calendario (iCal) per evitare le doppie prenotazioni."]},
        "en": {"titolo": "Why direct bookings pay off for hosts",
               "sommario": "The big OTAs keep up to a quarter of your revenue — often on guests who "
                           "are already yours. Here's why direct booking lets you keep more.",
               "corpo": ["Every booking from a large portal carries a hefty commission. The catch "
                         "is that many of those guests would have found you anyway — word of "
                         "mouth, social media, repeat customers. On them, the commission is money "
                         "given away.",
                         "With direct booking the guest pays you, you keep more and you own the "
                         "relationship: contact details, offers to bring them back, reviews. "
                         "BookinVIP gives you a booking site, secure payment, a voucher and self "
                         "check-in — at a much lower fee.",
                         "You don't have to leave the portals: use them alongside and sync your "
                         "calendar (iCal) to avoid double bookings."]},
        "es": {"titolo": "Por qué las reservas directas convienen a los anfitriones",
               "sommario": "Las grandes OTA se quedan hasta un cuarto de tus ingresos, a menudo con "
                           "clientes que ya son tuyos. Por eso la reserva directa te hace ganar más.",
               "corpo": ["Cada reserva de un gran portal lleva una comisión alta. El problema es "
                         "que muchos de esos huéspedes te habrían encontrado igualmente: boca a "
                         "boca, redes sociales, clientes que vuelven. En ellos la comisión es "
                         "dinero regalado.",
                         "Con la reserva directa el huésped te paga a ti, ganas más y controlas la "
                         "relación: contactos, ofertas para que vuelvan, reseñas. BookinVIP te da "
                         "web de reservas, pago seguro, voucher y check-in automático, con una "
                         "comisión mucho más baja.",
                         "No tienes que dejar los portales: úsalos en paralelo y sincroniza el "
                         "calendario (iCal) para evitar reservas dobles."]},
        "fr": {"titolo": "Pourquoi les réservations directes rapportent aux hôtes",
               "sommario": "Les grandes OTA prennent jusqu'à un quart de vos revenus, souvent sur "
                           "des clients déjà vôtres. Voici pourquoi le direct vous fait garder plus.",
               "corpo": ["Chaque réservation d'un grand portail s'accompagne d'une commission "
                         "élevée. Or beaucoup de ces voyageurs vous auraient trouvé de toute façon "
                         "— bouche-à-oreille, réseaux sociaux, clients fidèles. Sur eux, la "
                         "commission est de l'argent offert.",
                         "En direct, le voyageur vous paie, vous gardez plus et vous maîtrisez la "
                         "relation : contacts, offres de retour, avis. BookinVIP vous donne un "
                         "site de réservation, un paiement sécurisé, un voucher et un check-in "
                         "autonome — avec une commission bien plus basse.",
                         "Pas besoin de quitter les portails : utilisez-les en parallèle et "
                         "synchronisez le calendrier (iCal) pour éviter les doublons."]},
        "de": {"titolo": "Warum Direktbuchungen sich für Gastgeber lohnen",
               "sommario": "Große OTAs behalten bis zu ein Viertel Ihrer Einnahmen — oft bei Gästen, "
                           "die schon Ihre sind. Deshalb bleibt bei Direktbuchung mehr für Sie.",
               "corpo": ["Jede Buchung über ein großes Portal bringt eine hohe Provision mit sich. "
                         "Das Problem: Viele dieser Gäste hätten Sie ohnehin gefunden — Mundpropaganda, "
                         "soziale Medien, Stammgäste. Bei ihnen ist die Provision verschenktes Geld.",
                         "Bei der Direktbuchung zahlt der Gast an Sie, Sie behalten mehr und "
                         "besitzen die Beziehung: Kontaktdaten, Angebote für die Rückkehr, "
                         "Bewertungen. BookinVIP gibt Ihnen Buchungsseite, sichere Zahlung, "
                         "Voucher und Self-Check-in — zu einer viel niedrigeren Gebühr.",
                         "Sie müssen die Portale nicht verlassen: Nutzen Sie sie parallel und "
                         "synchronisieren Sie den Kalender (iCal), um Doppelbuchungen zu vermeiden."]},
        "pt": {"titolo": "Porque as reservas diretas compensam para os anfitriões",
               "sommario": "As grandes OTA ficam com até um quarto da sua receita, muitas vezes com "
                           "clientes que já são seus. Por isso a reserva direta faz-lhe ganhar mais.",
               "corpo": ["Cada reserva de um grande portal traz uma comissão elevada. O problema é "
                         "que muitos desses hóspedes tê-lo-iam encontrado de qualquer forma — "
                         "boca a boca, redes sociais, clientes que voltam. Neles, a comissão é "
                         "dinheiro oferecido.",
                         "Com a reserva direta o hóspede paga-lhe a si, fica com mais e controla a "
                         "relação: contactos, ofertas de regresso, avaliações. A BookinVIP dá-lhe "
                         "site de reservas, pagamento seguro, voucher e check-in automático — com "
                         "uma comissão muito mais baixa.",
                         "Não precisa de deixar os portais: use-os em paralelo e sincronize o "
                         "calendário (iCal) para evitar reservas duplicadas."]},
        "ja": {"titolo": "直接予約がホストに有利な理由",
               "sommario": "大手OTAは売上の最大4分の1を取ります——多くはすでにあなたの顧客からです。"
                           "だからこそ直接予約なら手元に多く残ります。",
               "corpo": ["大手ポータル経由の予約には高い手数料がかかります。問題は、その多くのゲストが"
                         "口コミ・SNS・リピーターなど、どのみちあなたを見つけたであろう客だという点です。"
                         "彼らにかかる手数料は、事実上ただ渡しているお金です。",
                         "直接予約ならゲストはあなたに支払い、手元に多く残り、関係もあなたのものになります"
                         "——連絡先、再来のオファー、レビュー。BookinVIPは予約サイト・安全な決済・"
                         "バウチャー・セルフチェックインを、ずっと低い手数料で提供します。",
                         "ポータルをやめる必要はありません。併用し、カレンダー（iCal）を同期して"
                         "ダブルブッキングを防げます。"]},
        "zh": {"titolo": "为什么直接预订对房东更划算",
               "sommario": "大型OTA最多抽取你四分之一的收入——而且往往还是你自己的客户。这就是直接预订"
                           "让你留存更多的原因。",
               "corpo": ["每一笔来自大型平台的预订都伴随着高额佣金。问题在于，其中许多客人本来就会找到你"
                         "——口碑、社交媒体、回头客。对他们收取的佣金，等于白白送出的钱。",
                         "直接预订时，客人付款给你，你留存更多，也掌握了客户关系：联系方式、促其回头的优惠、"
                         "评价。BookinVIP为你提供预订网站、安全支付、凭证和自助入住，佣金低得多。",
                         "你不必离开这些平台：可以并行使用，并同步日历（iCal）以避免重复预订。"]},
    }),
    _art("check-in-automatico", "2026-07-24", {
        "it": {"titolo": "Check-in automatico e voucher: come funziona",
               "sommario": "Niente attese alla consegna delle chiavi. Con il voucher firmato l'ospite "
                           "entra da solo, in sicurezza — e tu risparmi tempo.",
               "corpo": ["Dopo il pagamento l'ospite riceve un voucher firmato dal sistema: è la "
                         "sua conferma e, insieme, la chiave del check-in automatico. Non serve "
                         "essere sul posto a un orario preciso.",
                         "Per te significa meno telefonate, meno appuntamenti, nessun personale "
                         "dedicato. Per l'ospite significa arrivare quando vuole, con istruzioni "
                         "chiare e un codice valido solo per il suo soggiorno.",
                         "Tutto è tracciato e verificabile: la firma digitale evita voucher falsi e "
                         "protegge entrambe le parti."]},
        "en": {"titolo": "Self check-in and vouchers: how it works",
               "sommario": "No more waiting to hand over keys. With the signed voucher the guest "
                           "lets themselves in, securely — and you save time.",
               "corpo": ["After payment the guest receives a system-signed voucher: it's their "
                         "confirmation and, at the same time, the self check-in key. No need to be "
                         "on site at a fixed time.",
                         "For you that means fewer calls, fewer appointments, no dedicated staff. "
                         "For the guest it means arriving whenever they want, with clear "
                         "instructions and a code valid only for their stay.",
                         "Everything is tracked and verifiable: the digital signature prevents fake "
                         "vouchers and protects both sides."]},
        "es": {"titolo": "Check-in automático y vouchers: cómo funciona",
               "sommario": "Se acabó esperar para entregar las llaves. Con el voucher firmado el "
                           "huésped entra solo, de forma segura, y tú ahorras tiempo.",
               "corpo": ["Tras el pago el huésped recibe un voucher firmado por el sistema: es su "
                         "confirmación y, a la vez, la llave del check-in automático. No hace falta "
                         "estar allí a una hora fija.",
                         "Para ti significa menos llamadas, menos citas, sin personal dedicado. "
                         "Para el huésped, llegar cuando quiera, con instrucciones claras y un "
                         "código válido solo para su estancia.",
                         "Todo queda registrado y verificable: la firma digital evita vouchers "
                         "falsos y protege a ambas partes."]},
        "fr": {"titolo": "Check-in autonome et vouchers : comment ça marche",
               "sommario": "Fini l'attente pour remettre les clés. Avec le voucher signé, le "
                           "voyageur entre seul, en sécurité — et vous gagnez du temps.",
               "corpo": ["Après le paiement, le voyageur reçoit un voucher signé par le système : "
                         "c'est sa confirmation et, en même temps, la clé du check-in autonome. "
                         "Pas besoin d'être sur place à une heure précise.",
                         "Pour vous : moins d'appels, moins de rendez-vous, aucun personnel dédié. "
                         "Pour le voyageur : arriver quand il veut, avec des instructions claires "
                         "et un code valable seulement pour son séjour.",
                         "Tout est tracé et vérifiable : la signature numérique empêche les faux "
                         "vouchers et protège les deux parties."]},
        "de": {"titolo": "Self-Check-in und Voucher: so funktioniert es",
               "sommario": "Kein Warten bei der Schlüsselübergabe mehr. Mit dem signierten Voucher "
                           "kommt der Gast sicher selbst hinein — und Sie sparen Zeit.",
               "corpo": ["Nach der Zahlung erhält der Gast einen vom System signierten Voucher: "
                         "seine Bestätigung und zugleich der Schlüssel für den Self-Check-in. Sie "
                         "müssen nicht zu einer festen Uhrzeit vor Ort sein.",
                         "Für Sie bedeutet das weniger Anrufe, weniger Termine, kein eigenes "
                         "Personal. Für den Gast: ankommen, wann er will, mit klaren Anweisungen "
                         "und einem Code, der nur für seinen Aufenthalt gilt.",
                         "Alles ist nachvollziehbar und prüfbar: Die digitale Signatur verhindert "
                         "gefälschte Voucher und schützt beide Seiten."]},
        "pt": {"titolo": "Check-in automático e vouchers: como funciona",
               "sommario": "Acabou a espera para entregar as chaves. Com o voucher assinado o "
                           "hóspede entra sozinho, em segurança — e você poupa tempo.",
               "corpo": ["Após o pagamento o hóspede recebe um voucher assinado pelo sistema: é a "
                         "sua confirmação e, ao mesmo tempo, a chave do check-in automático. Não "
                         "precisa de estar no local a uma hora fixa.",
                         "Para si significa menos chamadas, menos marcações, sem pessoal dedicado. "
                         "Para o hóspede, chegar quando quiser, com instruções claras e um código "
                         "válido apenas para a sua estadia.",
                         "Tudo é registado e verificável: a assinatura digital evita vouchers "
                         "falsos e protege ambas as partes."]},
        "ja": {"titolo": "セルフチェックインとバウチャー：仕組み",
               "sommario": "鍵の受け渡しで待つ必要はありません。署名付きバウチャーでゲストは安全に"
                           "自分で入室でき、あなたの時間も節約できます。",
               "corpo": ["支払い後、ゲストはシステムが署名したバウチャーを受け取ります。これは予約確認で"
                         "あると同時に、セルフチェックインの鍵でもあります。決まった時間に現地にいる必要は"
                         "ありません。",
                         "あなたにとっては、電話も約束も減り、専任スタッフも不要。ゲストにとっては、"
                         "好きな時間に到着でき、明確な案内と、その滞在だけに有効なコードが手に入ります。",
                         "すべて記録され検証可能です。デジタル署名が偽バウチャーを防ぎ、双方を守ります。"]},
        "zh": {"titolo": "自助入住与凭证：运作方式",
               "sommario": "不再为交钥匙而等待。凭签名凭证，客人可安全地自助入住——你也节省了时间。",
               "corpo": ["付款后，客人会收到系统签名的凭证：既是预订确认，也是自助入住的钥匙。你无需"
                         "在固定时间到现场。",
                         "对你而言，这意味着更少的电话、更少的预约、无需专职人员。对客人而言，可随时到达，"
                         "附有清晰指引，以及仅在其住宿期间有效的密码。",
                         "一切均可追踪、可核验：数字签名可防止伪造凭证，并保护双方。"]},
    }),
]


def _articolo_da_slug(slug: str) -> Optional[Dict[str, object]]:
    for a in ARTICOLI:
        if a["slug"] == slug:
            return a
    return None


def _lng(lingua: object) -> str:
    """La lingua da servire: quella chiesta se esiste, altrimenti INGLESE.

    Ripiegava sull'ITALIANO: un lettore che arrivava con `?lang=ru` (lingua servita
    dalle landing di fase97 ma non dal blog) o con un codice qualsiasi si trovava
    l'articolo in italiano. Su un blog che esiste per portare traffico da tutto il
    mondo, «non conosco questa lingua» non puo' voler dire «italiano»: la lingua
    franca e' l'inglese (stessa regola di fase86 e di `fase83._lingua`)."""
    return lingua if isinstance(lingua, str) and lingua in _UI else "en"


def _jsonld(obj: object) -> str:
    return (json.dumps(obj, ensure_ascii=False)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def _url_articolo(base: str, slug: str, lng: str) -> str:
    return base + "/blog/" + slug + ("" if lng == "it" else "?lang=" + lng)


def _url_indice(base: str, lng: str) -> str:
    return base + "/blog" + ("" if lng == "it" else "?lang=" + lng)


def _hreflang_blocco(base: str, url_fn) -> str:
    out = "".join('<link rel="alternate" hreflang="%s" href="%s">' % (L, html.escape(url_fn(L)))
                  for L in BLOG_LINGUE)
    return out + '<link rel="alternate" hreflang="x-default" href="%s">' % html.escape(url_fn("it"))


_CSS = ("<style>body{font-family:system-ui,Segoe UI,sans-serif;max-width:46rem;margin:2rem auto;"
        "padding:0 1rem;line-height:1.7;color:#1a1e2b}h1{color:#1e3c72;line-height:1.3}"
        "a{color:#2a5298}.cta{display:inline-block;background:#1e3c72;color:#fff;padding:.8rem 1.6rem;"
        "border-radius:2rem;text-decoration:none;font-weight:600;margin:1rem 0}"
        ".meta{color:#667;font-size:.9rem}nav a{margin-right:.6rem}"
        "article p{margin:1rem 0}ul.lista li{margin:.3rem 0}</style>")


def genera_articolo_html(slug: str, *, lingua: str = "it", base_url: str = "") -> Optional[str]:
    """Pagina articolo completa (SEO + Article/Breadcrumb JSON-LD + link interni). None se assente."""
    art = _articolo_da_slug(slug)
    if art is None:
        return None
    lng = _lng(lingua)
    T = art["T"]                                       # type: ignore[index]
    t = T.get(lng) or T["it"]                          # type: ignore[union-attr]
    base = (base_url or "").rstrip("/")
    e = html.escape
    ui = _UI[lng]
    canonical = _url_articolo(base, slug, lng)
    titolo = str(t["titolo"])
    sommario = str(t["sommario"])
    corpo = t.get("corpo") or []                       # type: ignore[union-attr]
    corpo_html = "".join("<p>%s</p>" % e(str(p)) for p in corpo)

    # link interni: /diventa-host + gli ALTRI articoli (crawl + retention)
    altri = [a for a in ARTICOLI if a["slug"] != slug]
    altri_html = "".join(
        '<li><a href="%s">%s</a></li>'
        % (e(_url_articolo(base, str(a["slug"]), lng)),
           e(str((a["T"].get(lng) or a["T"]["it"])["titolo"])))    # type: ignore[union-attr,index]
        for a in altri)

    article_ld = _jsonld({"@context": "https://schema.org", "@type": "Article",
                          "headline": titolo, "description": sommario,
                          "inLanguage": lng, "datePublished": art["data"],
                          "dateModified": BLOG_LASTMOD,
                          "author": {"@type": "Organization", "name": "BookinVIP"},
                          "publisher": {"@type": "Organization", "name": "BookinVIP"},
                          "mainEntityOfPage": canonical})
    bc_ld = _jsonld({"@context": "https://schema.org", "@type": "BreadcrumbList",
                     "itemListElement": [
                         {"@type": "ListItem", "position": 1, "name": ui["home"],
                          "item": (base + "/") if base else "/"},
                         {"@type": "ListItem", "position": 2, "name": ui["blog"],
                          "item": _url_indice(base, lng)},
                         {"@type": "ListItem", "position": 3, "name": titolo, "item": canonical}]})

    return (
        '<!doctype html><html lang="%s"><head><meta charset="utf-8">' % lng
        + '<meta name="viewport" content="width=device-width,initial-scale=1">'
        + "<title>" + e(titolo) + " | BookinVIP</title>"
        + '<meta name="description" content="' + e(sommario) + '">'
        + '<link rel="canonical" href="' + e(canonical) + '">'
        + _hreflang_blocco(base, lambda L: _url_articolo(base, slug, L))
        + '<meta property="og:type" content="article">'
        + '<meta property="og:title" content="' + e(titolo) + '">'
        + '<meta property="og:url" content="' + e(canonical) + '">'
        + '<meta property="og:locale" content="' + lng + "_" + TERRITORIO.get(lng, "US") + '">'
        + '<script type="application/ld+json">' + article_ld + "</script>"
        + '<script type="application/ld+json">' + bc_ld + "</script>"
        + _CSS + "</head><body>"
        + '<nav class="meta"><a href="%s">%s</a> › <a href="%s">%s</a></nav>'
          % (e((base + "/") if base else "/"), e(ui["home"]),
             e(_url_indice(base, lng)), e(ui["blog"]))
        + "<main><article><h1>" + e(titolo) + "</h1>"
        + '<p class="meta">' + e(str(art["data"])) + "</p>"
        + "<p><b>" + e(sommario) + "</b></p>"
        + corpo_html
        + '<p><a class="cta" href="%s">%s</a></p>'
          % (e(base + "/diventa-host.html?ref=blog-" + slug), e(ui["cta"]))
        + "</article></main>"
        + ('<nav aria-label="%s"><h2>%s</h2><ul class="lista">%s</ul></nav>'
           % (e(ui["altri"]), e(ui["altri"]), altri_html) if altri_html else "")
        + '<footer><a href="%s">BookinVIP</a></footer>' % e((base + "/") if base else "/")
        + "</body></html>")


def genera_indice_blog(*, lingua: str = "it", base_url: str = "") -> str:
    """Pagina indice /blog: elenco degli articoli con titolo+sommario (crawlabile, hub SEO)."""
    lng = _lng(lingua)
    base = (base_url or "").rstrip("/")
    e = html.escape
    ui = _UI[lng]
    canonical = _url_indice(base, lng)
    voci = "".join(
        '<li><h2><a href="%s">%s</a></h2><p>%s</p></li>'
        % (e(_url_articolo(base, str(a["slug"]), lng)),
           e(str((a["T"].get(lng) or a["T"]["it"])["titolo"])),          # type: ignore[union-attr,index]
           e(str((a["T"].get(lng) or a["T"]["it"])["sommario"])))        # type: ignore[union-attr,index]
        for a in ARTICOLI)
    return (
        '<!doctype html><html lang="%s"><head><meta charset="utf-8">' % lng
        + '<meta name="viewport" content="width=device-width,initial-scale=1">'
        + "<title>" + e(ui["blog"]) + " | BookinVIP</title>"
        + '<meta name="description" content="' + e(ui["blog"]) + " — " + e(ui["tutti"]) + '">'
        + '<link rel="canonical" href="' + e(canonical) + '">'
        + _hreflang_blocco(base, lambda L: _url_indice(base, L))
        + '<link rel="alternate" type="application/rss+xml" href="' + e(base + "/feed.xml") + '">'
        + _CSS + "</head><body><main>"
        + "<h1>" + e(ui["blog"]) + "</h1>"
        + '<ul class="lista" style="list-style:none;padding:0">' + voci + "</ul>"
        + '<p><a class="cta" href="%s">%s</a></p>'
          % (e(base + "/diventa-host.html?ref=blog"), e(ui["cta"]))
        + "</main><footer><a href=\"%s\">BookinVIP</a></footer></body></html>"
          % e((base + "/") if base else "/"))


def sitemap_blog(base_url: str = "", *, lingue: Sequence[str] = BLOG_LINGUE,
                 lastmod: str = BLOG_LASTMOD) -> str:
    """sitemap.xml del blog (indice + ogni articolo × lingua) con <lastmod>."""
    base = (base_url or "").rstrip("/")
    lm = ("<lastmod>%s</lastmod>" % html.escape(lastmod)) if lastmod else ""
    urls = []
    for lng in lingue:
        urls.append("<url><loc>%s</loc>%s</url>" % (html.escape(_url_indice(base, lng)), lm))
    for a in ARTICOLI:
        for lng in lingue:
            urls.append("<url><loc>%s</loc>%s</url>"
                        % (html.escape(_url_articolo(base, str(a["slug"]), lng)), lm))
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(urls) + "</urlset>")


def url_blog(base_url: str = "") -> List[str]:
    """Tutti gli URL del blog (per IndexNow / ping)."""
    base = (base_url or "").rstrip("/")
    out = [_url_indice(base, L) for L in BLOG_LINGUE]
    for a in ARTICOLI:
        for L in BLOG_LINGUE:
            out.append(_url_articolo(base, str(a["slug"]), L))
    return out
