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

# ── DIDASCALIE per lingua ({c}=città, {link}=landing con UTM). Regola d'oro: il 3% SEMPRE detto. ─
CAPTION = {
    "it": "Hai una casa a {c}? Mettila a reddito senza pensieri: 0% commissioni per i primi 90 "
          "giorni, solo una tariffa tecnica del 3% dichiarata prima. L'ospite non paga nulla. {link}",
    "en": "Do you own a place in {c}? Put it to work: 0% commission for the first 90 days, only a "
          "3% technical fee, told upfront. Guests pay nothing. {link}",
    "es": "¿Tienes una casa en {c}? Ponla a trabajar: 0% de comisión los primeros 90 días, solo una "
          "tarifa técnica del 3%, dicha antes. El huésped no paga nada. {link}",
    "fr": "Vous avez un logement à {c} ? Mettez-le en location : 0 % de commission pendant 90 jours, "
          "seulement 3 % de frais techniques, annoncés d'avance. Le voyageur ne paie rien. {link}",
    "de": "Sie haben eine Wohnung in {c}? Vermieten Sie sie: 0% Provision in den ersten 90 Tagen, "
          "nur eine 3% Technikgebühr, vorab gesagt. Gäste zahlen nichts. {link}",
    "pt": "Tem uma casa em {c}? Ponha-a a render: 0% de comissão nos primeiros 90 dias, apenas uma "
          "taxa técnica de 3%, dita antes. O hóspede não paga nada. {link}",
    "nl": "Heeft u een woning in {c}? Verhuur zonder verrassingen: 0% commissie de eerste 90 dagen, "
          "alleen 3% technische kosten, vooraf gemeld. Gasten betalen niets. {link}",
    "tr": "{c} şehrinde eviniz mi var? Sürpriz yok: ilk 90 gün %0 komisyon, yalnızca önceden "
          "söylenen %3 teknik ücret. Misafir hiçbir şey ödemez. {link}",
    "ru": "У вас есть жильё в городе {c}? 0% комиссии первые 90 дней, только технический сбор 3%, "
          "о нём говорим заранее. Гости не платят ничего. {link}",
    "id": "Punya properti di {c}? Komisi 0% selama 90 hari pertama, hanya biaya teknis 3%, "
          "diberitahukan di awal. Tamu tidak membayar apa pun. {link}",
    "vi": "Bạn có nhà tại {c}? 0% hoa hồng trong 90 ngày đầu, chỉ 3% phí kỹ thuật, thông báo "
          "trước. Khách không trả gì. {link}",
    "ko": "{c}에 숙소를 갖고 계신가요? 첫 90일 수수료 0%, 기술 수수료는 3%뿐, 사전에 안내합니다. "
          "게스트 부담 없음. {link}",
    "zh": "您在{c}有房源吗？前90天0%佣金，仅3%技术费，事先说明。房客零费用。{link}",
    "th": "มีที่พักใน {c} ไหม? 90 วันแรกค่าคอมมิชชั่น 0% มีเพียงค่าธรรมเนียมเทคนิค 3% "
          "แจ้งล่วงหน้า ผู้เข้าพักไม่จ่ายอะไรเลย {link}",
    "ja": "{c}に物件をお持ちですか？最初の90日間は手数料0%、技術手数料は3%のみ、事前にお伝えします。"
          "ゲストの負担はゼロ。{link}",
    "ar": "هل لديك عقار في {c}؟ عمولة 0% لأول 90 يومًا، فقط رسوم تقنية 3% نعلنها مسبقًا. "
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
