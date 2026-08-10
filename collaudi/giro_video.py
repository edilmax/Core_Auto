# -*- coding: utf-8 -*-
"""
GIRO VIDEO MONDIALE — la macchina che porta BookinVIP in video in tutto il mondo, da sola.

Ogni tappa = una città top con la SUA lingua (voce neurale locale + copione AI locale, guardiano
anti-italiano) → spot renderizzato da collaudi/video_render.py → pubblicato su TUTTI i canali con
chiave (Telegram, Facebook, Mastodon), didascalia nella lingua del posto + LINK TRACCIATO (UTM per
canale) alla landing /affitta/{città}: si misura QUALE canale porta host.

Strategia (non spam): il mondo si copre A ROTAZIONE — un video al giorno per sempre (cron), copione
AI sempre nuovo → mai lo stesso video due volte. La copertura "tutte le nazioni" su Google c'è già
dalle 2990 landing SEO; i video concentrano la spinta sulle città a più alto traffico.

Uso (sul VPS, da /var/www/bookinvip):
  python3 collaudi/giro_video.py --giornaliero          # prossima tappa del giro (per il cron)
  python3 collaudi/giro_video.py --lotto seoul,osaka    # tappe esplicite, in sequenza
  python3 collaudi/giro_video.py --pubblica-esistenti   # i video già fatti → anche FB+Mastodon
Stato durevole del giro: /root/bookinvip_giro_video.json
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import video_render as V
import pubblica_video as P

STATO = "/root/bookinvip_giro_video.json"

# ── LE TAPPE DEL GIRO: (slug landing /affitta/, città per il render, lingua, voce esplicita) ────
# Le lingue sono quelle del POSTO (fiducia = parlare la lingua di casa); l'arabo ha la voce ma lo
# schermo resta EN (drawtext non fa lo shaping RTL). Slug TUTTI verificati vivi (200) sul sito.
TAPPE = [
    ("roma", "Roma", "it", None),
    ("barcelona", "Barcelona", "es", None),
    ("lisbon", "Lisboa", "pt", None),
    ("paris", "Paris", "fr", None),
    ("london", "London", "en", "en-GB-RyanNeural"),
    ("amsterdam", "Amsterdam", "nl", None),
    ("berlin", "Berlin", "de", None),
    ("new-york", "New York", "en", None),
    ("miami", "Miami", "en", None),
    ("dubai", "Dubai", "ar", None),
    ("bangkok", "Bangkok", "th", None),
    ("tokyo", "Tokyo", "ja", None),
    ("istanbul", "Istanbul", "tr", None),
    ("seoul", "Seoul", "ko", None),
    ("osaka", "Osaka", "ja", None),
    ("kyoto", "Kyoto", "ja", None),
    ("hong-kong", "Hong Kong", "zh", None),
    ("taipei", "Taipei", "zh", None),
    ("shanghai", "Shanghai", "zh", None),
    ("beijing", "Beijing", "zh", None),
    ("singapore", "Singapore", "en", None),
    ("kuala-lumpur", "Kuala Lumpur", "en", None),
    ("manila", "Manila", "en", None),
    ("jakarta", "Jakarta", "id", None),
    ("bali", "Bali", "id", None),
    ("hanoi", "Hanoi", "vi", None),
    ("ho-chi-minh-city", "Ho Chi Minh City", "vi", None),
    ("chiang-mai", "Chiang Mai", "th", None),
    ("phuket", "Phuket", "th", None),
    ("sydney", "Sydney", "en", None),
    ("mexico-city", "Mexico City", "es", None),
    ("buenos-aires", "Buenos Aires", "es", None),
    ("madrid", "Madrid", "es", None),
    ("rio-de-janeiro", "Rio de Janeiro", "pt", "pt-BR-AntonioNeural"),
    ("vienna", "Vienna", "de", None),
    ("moscow", "Moscow", "ru", None),
    ("mumbai", "Mumbai", "en", None),
    ("cairo", "Cairo", "ar", None),
    ("cape-town", "Cape Town", "en", None),
    ("marrakech", "Marrakech", "fr", None),
    # — LE CITTÀ PIÙ BELLE DEL MONDO (direttiva fondatore 27/07 notte): le gemme oltre le capitali
    #   del traffico. Slug tutti VERIFICATI vivi (200) su /affitta/.
    ("venezia", "Venezia", "it", None),
    ("firenze", "Firenze", "it", None),
    ("napoli", "Napoli", "it", None),
    ("prague", "Prague", "en", None),
    ("athens", "Athens", "en", None),
    ("santorini", "Santorini", "en", None),
    ("dubrovnik", "Dubrovnik", "en", None),
    ("budapest", "Budapest", "en", None),
    ("edinburgh", "Edinburgh", "en", "en-GB-RyanNeural"),
    ("san-francisco", "San Francisco", "en", None),
    ("krakow", "Krakow", "en", None),
    ("porto", "Porto", "pt", None),
    ("seville", "Sevilla", "es", None),
    ("granada", "Granada", "es", None),
]

# ── ONDATA MONDIALE (direttiva «tutte, anche se sono 200»): il resto delle 230 città del seed
# SEO (fase97 = fonte unica: OGNI città del seed ha la landing viva per costruzione) entra nel
# giro AUTOMATICAMENTE, con la lingua del posto (fra le 16 con didascalia+voce) e ripiego EN.
from fase97_inbound_seo import CITTA_SEED, slug_citta as _slug97

LINGUA_ONDATA = {
    # Italia
    "Milano": "it", "Torino": "it", "Bologna": "it", "Verona": "it", "Palermo": "it", "Genova": "it",
    # Europa de/fr/nl
    "Munich": "de", "Hamburg": "de", "Frankfurt": "de", "Salzburg": "de", "Zurich": "de",
    "Geneva": "fr", "Brussels": "fr", "Luxembourg": "fr", "Monaco": "fr",
    "Rotterdam": "nl", "The Hague": "nl",
    "Nice": "fr", "Lyon": "fr", "Marseille": "fr", "Bordeaux": "fr", "Cannes": "fr",
    # Iberia / LatAm ispanofona
    "Valencia": "es", "Malaga": "es", "Bilbao": "es", "Palma": "es",
    "Cancun": "es", "Tulum": "es", "Guadalajara": "es", "Playa del Carmen": "es",
    "Puerto Vallarta": "es", "Havana": "es", "Punta Cana": "es", "Santo Domingo": "es",
    "San Juan": "es", "Panama City": "es", "San José": "es", "Lima": "es", "Cusco": "es",
    "Santiago": "es", "Bogota": "es", "Cartagena": "es", "Medellin": "es", "Quito": "es",
    "La Paz": "es", "Montevideo": "es", "Caracas": "es",
    # Brasile (voce pt-BR sotto)
    "Sao Paulo": "pt", "Salvador": "pt", "Florianopolis": "pt", "Brasilia": "pt",
    # Turchia / Russia+russofoni
    "Antalya": "tr", "Cappadocia": "tr",
    "Saint Petersburg": "ru", "Almaty": "ru", "Tashkent": "ru", "Samarkand": "ru",
    # Asia Est
    "Guangzhou": "zh", "Shenzhen": "zh", "Chengdu": "zh", "Xian": "zh", "Macau": "zh",
    "Busan": "ko", "Jeju": "ko", "Nagoya": "ja", "Fukuoka": "ja", "Sapporo": "ja",
    # Sud-Est asiatico
    "Pattaya": "th", "Krabi": "th", "Koh Samui": "th",
    "Yogyakarta": "id", "Ubud": "id", "Da Nang": "vi", "Hoi An": "vi",
    # Medio Oriente / Nord Africa arabofono+francofono
    "Abu Dhabi": "ar", "Doha": "ar", "Riyadh": "ar", "Jeddah": "ar", "Kuwait City": "ar",
    "Manama": "ar", "Muscat": "ar", "Amman": "ar", "Beirut": "ar",
    "Hurghada": "ar", "Sharm El Sheikh": "ar",
    "Casablanca": "fr", "Fez": "fr", "Tunis": "fr", "Dakar": "fr",
    # Canada francofono
    "Montreal": "fr", "Quebec City": "fr",
}
VOCE_ONDATA = {
    "Manchester": "en-GB-RyanNeural", "Liverpool": "en-GB-RyanNeural",
    "Oxford": "en-GB-RyanNeural", "Dublin": "en-IE-ConnorNeural",
    "Sao Paulo": "pt-BR-AntonioNeural", "Salvador": "pt-BR-AntonioNeural",
    "Florianopolis": "pt-BR-AntonioNeural", "Brasilia": "pt-BR-AntonioNeural",
}
_gia = {t[0] for t in TAPPE}
for _c in CITTA_SEED:
    _s = _slug97(_c)
    if _s and _s not in _gia:
        _gia.add(_s)
        TAPPE.append((_s, _c, LINGUA_ONDATA.get(_c, "en"), VOCE_ONDATA.get(_c)))

# ── DIDASCALIE per lingua ({c}=città, {link}=landing con UTM).
# ⛔ REGOLA D'ORO: la TARIFFA TECNICA va SEMPRE detta, e con la cifra VERA.
# Il 2026-08-10 e' passata dal 3% al 5% + 0,25 EUR (7% + 0,25 sugli annunci non in euro) e
# queste sedici didascalie stavano ancora dicendo 3%: sono i testi dei video che vanno agli
# host VERI, cioe' un numero sbagliato detto prima della firma. Le ha trovate
# `collaudi/audit_coerenza_tariffe.py`, non una persona.
CAPTION = {
    "it": "Hai una casa a {c}? Mettila a reddito senza pensieri: 0% commissioni per i primi 90 "
          "giorni, solo una tariffa tecnica del 5% + 0,25 € dichiarata prima. L'ospite non paga nulla. {link}",
    "en": "Do you own a place in {c}? Put it to work: 0% commission for the first 90 days, only a "
          "5% + EUR 0.25 technical fee, told upfront. Guests pay nothing. {link}",
    "es": "¿Tienes una casa en {c}? Ponla a trabajar: 0% de comisión los primeros 90 días, solo una "
          "tarifa técnica del 5% + 0,25 €, dicha antes. El huésped no paga nada. {link}",
    "fr": "Vous avez un logement à {c} ? Mettez-le en location : 0 % de commission pendant 90 jours, "
          "seulement 5 % + 0,25 € de frais techniques, annoncés d'avance. Le voyageur ne paie rien. {link}",
    "de": "Sie haben eine Wohnung in {c}? Vermieten Sie sie: 0% Provision in den ersten 90 Tagen, "
          "nur eine Technikgebühr von 5% + 0,25 €, vorab gesagt. Gäste zahlen nichts. {link}",
    "pt": "Tem uma casa em {c}? Ponha-a a render: 0% de comissão nos primeiros 90 dias, apenas uma "
          "taxa técnica de 5% + 0,25 €, dita antes. O hóspede não paga nada. {link}",
    "nl": "Heeft u een woning in {c}? Verhuur zonder verrassingen: 0% commissie de eerste 90 dagen, "
          "alleen 5% + € 0,25 technische kosten, vooraf gemeld. Gasten betalen niets. {link}",
    "tr": "{c} şehrinde eviniz mi var? Sürpriz yok: ilk 90 gün %0 komisyon, yalnızca önceden "
          "söylenen %5 + 0,25 € teknik ücret. Misafir hiçbir şey ödemez. {link}",
    "ru": "У вас есть жильё в городе {c}? 0% комиссии первые 90 дней, только технический сбор 5% + 0,25 €, "
          "о нём говорим заранее. Гости не платят ничего. {link}",
    "id": "Punya properti di {c}? Komisi 0% selama 90 hari pertama, hanya biaya teknis 5% + €0,25, "
          "diberitahukan di awal. Tamu tidak membayar apa pun. {link}",
    "vi": "Bạn có nhà tại {c}? 0% hoa hồng trong 90 ngày đầu, chỉ 5% + 0,25 € phí kỹ thuật, thông báo "
          "trước. Khách không trả gì. {link}",
    "ko": "{c}에 숙소를 갖고 계신가요? 첫 90일 수수료 0%, 기술 수수료는 5% + 0,25유로뿐, 사전에 안내합니다. "
          "게스트 부담 없음. {link}",
    "zh": "您在{c}有房源吗？前90天0%佣金，仅5% + 0,25欧元技术费，事先说明。房客零费用。{link}",
    "th": "มีที่พักใน {c} ไหม? 90 วันแรกค่าคอมมิชชั่น 0% มีเพียงค่าธรรมเนียมเทคนิค 5% + 0.25 ยูโร "
          "แจ้งล่วงหน้า ผู้เข้าพักไม่จ่ายอะไรเลย {link}",
    "ja": "{c}に物件をお持ちですか？最初の90日間は手数料0%、技術手数料は5% + 0,25ユーロのみ、事前にお伝えします。"
          "ゲストの負担はゼロ。{link}",
    "ar": "هل لديك عقار في {c}؟ عمولة 0% لأول 90 يومًا، فقط رسوم تقنية 5% + 0.25 يورو نعلنها مسبقًا. "
          "الضيف لا يدفع شيئًا. {link}",
}

# I video già renderizzati dal primo giro (nomi file storici ≠ slug landing in 2 casi).
# SOLO le città che NON vengono rifatte in lingua locale (quelle rifatte ripassano dal --lotto).
ESISTENTI = [
    ("/tmp/roma2.mp4", "roma", "Roma", "it"),
    ("/tmp/bv_barcelona.mp4", "barcelona", "Barcelona", "es"),
    ("/tmp/bv_lisboa.mp4", "lisbon", "Lisboa", "pt"),
    ("/tmp/bv_paris.mp4", "paris", "Paris", "fr"),
    ("/tmp/bv_london.mp4", "london", "London", "en"),
    ("/tmp/bv_berlin.mp4", "berlin", "Berlin", "de"),
    ("/tmp/bv_newyork.mp4", "new-york", "New York", "en"),
    ("/tmp/bv_miami.mp4", "miami", "Miami", "en"),
    ("/tmp/bv_tokyo.mp4", "tokyo", "Tokyo", "ja"),
]

CANALI = [("telegram", P.telegram), ("facebook", P.facebook), ("mastodon", P.mastodon)]


def _link(slug, canale):
    return ("https://bookinvip.com/affitta/%s?utm_source=%s&utm_medium=video&utm_campaign=host-%s"
            % (slug, canale, slug))


def _caption(lingua, citta, slug, canale):
    return CAPTION.get(lingua, CAPTION["en"]).format(c=citta, link=_link(slug, canale))


def pubblica(path, slug, citta, lingua, canali=CANALI):
    esiti = []
    for nome, fn in canali:
        r = fn(path, _caption(lingua, citta, slug, nome))
        esiti.append("%s:%s" % (nome, r))
        print("   -> %-9s %s" % (nome, r), flush=True)
        time.sleep(3)
    return esiti


def tappa_per_slug(slug):
    for t in TAPPE:
        if t[0] == slug:
            return t
    raise SystemExit("tappa sconosciuta: %s" % slug)


def esegui_tappa(t):
    slug, citta, lingua, voce = t
    out = "/tmp/bv_%s.mp4" % slug.replace("-", "")
    t0 = time.time()
    V.monta(citta, lingua, out, voce=voce)
    esiti = pubblica(out, slug, citta, lingua)
    print("[FATTA] %-16s %s  %ds  %s" % (slug, lingua, int(time.time() - t0),
                                         " | ".join(esiti)), flush=True)
    return esiti


def _stato():
    try:
        return json.load(open(STATO, encoding="utf-8"))
    except Exception:
        return {"indice": 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--giornaliero", action="store_true")
    ap.add_argument("--lotto", default="")
    ap.add_argument("--pubblica-esistenti", action="store_true", dest="esistenti")
    a = ap.parse_args()
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    if a.giornaliero:
        st = _stato()
        t = TAPPE[st["indice"] % len(TAPPE)]
        print("GIRO tappa %d: %s" % (st["indice"], t[0]), flush=True)
        try:
            esegui_tappa(t)
        finally:
            st["indice"] = st["indice"] + 1          # mai bloccarsi sulla stessa tappa
            json.dump(st, open(STATO, "w", encoding="utf-8"))

    if a.lotto:
        ok, err = 0, 0
        for slug in [s.strip() for s in a.lotto.split(",") if s.strip()]:
            try:
                esegui_tappa(tappa_per_slug(slug))
                ok += 1
            except Exception as e:
                err += 1
                print("[ERRORE] %s: %r" % (slug, e), flush=True)
            time.sleep(10)
        print("LOTTO FINITO: %d ok, %d errori" % (ok, err), flush=True)

    if a.esistenti:
        for path, slug, citta, lingua in ESISTENTI:
            if not os.path.exists(path):
                print("[SALTO] %s (file assente)" % slug, flush=True)
                continue
            print("[ESISTENTE] %s -> FB+Mastodon" % slug, flush=True)
            pubblica(path, slug, citta, lingua, canali=CANALI[1:])   # Telegram li ha già
            time.sleep(5)
        print("ESISTENTI FINITI", flush=True)


if __name__ == "__main__":
    main()
