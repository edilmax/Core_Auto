"""
GIOIELLO VIDEO — renderer AUTONOMO del video di reclutamento host BookinVIP.

Vive FUORI dalla produzione (usa ffmpeg + edge-tts, non stdlib): gira sul VPS (host), non nel
container. Tutto GRATIS e SENZA CHIAVI ne' intervento del fondatore, illimitato:
  - immagini:  Pollinations flux (keyless, illimitato) — 1080x1920 verticale (Reel/Short/TikTok)
  - voce:      edge-tts (voci neurali Microsoft, keyless) nella lingua della citta'
  - copione:   Groq (una AI a giro, come da strategia) — con guardiano-lingua di fase200; se tace,
               ripiego deterministico gia' scritto (mai vuoto, mai italiano fuori Italia)
  - montaggio: ffmpeg — Ken Burns (zoom lento), testo sovrimpresso elegante, dissolvenze, end-card brand

Uso (sul VPS):
    python3 collaudi/video_render.py --citta Roma --lingua it [--telegram] [--out /tmp/v.mp4]
Legge GROQ_API_KEY / TELEGRAM_* da .env.casavip.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import fase200_campagna_persuasiva as C

W, H, FPS = 1080, 1920, 30
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELLO = os.environ.get("GROQ_MODELLO", "llama-3.3-70b-versatile")

# Voci neurali edge-tts per lingua (naturali, maschili calde). Ripiego: inglese.
VOCI = {"it": "it-IT-DiegoNeural", "en": "en-US-GuyNeural", "es": "es-ES-AlvaroNeural",
        "fr": "fr-FR-HenriNeural", "de": "de-DE-ConradNeural", "pt": "pt-PT-DuarteNeural",
        "ja": "ja-JP-KeitaNeural", "zh": "zh-CN-YunxiNeural",
        "ko": "ko-KR-InJoonNeural", "th": "th-TH-NiwatNeural", "vi": "vi-VN-NamMinhNeural",
        "id": "id-ID-ArdiNeural", "ru": "ru-RU-DmitryNeural", "tr": "tr-TR-AhmetNeural",
        "nl": "nl-NL-MaartenNeural", "ar": "ar-AE-HamdanNeural"}

# Font per lingua DELLO SCHERMO: DejaVu copre latino esteso (vi/tr/nl/id inclusi) e cirillico;
# CJK (ja/zh/ko) e thai vogliono font dedicati (installati sul VPS). ⚠️ LEZIONE VISTA SUI FOTOGRAMMI:
# NotoSansThai ha SOLO l'alfabeto thai — niente cifre ne' '%' -> "3%" usciva a QUADRATINI. Il font
# thai giusto e' Loma (TLWG): thai + latino + cifre insieme (verificato su PNG). I Noto CJK invece
# le cifre le hanno (verificato). Candidati in ordine; se NESSUNO esiste -> MAI quadratini: lo
# schermo degrada a inglese (gestito in monta), non a DejaVu.
FONT_LINGUA = {"ja": ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"],
               "zh": ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"],
               "ko": ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"],
               "th": ["/usr/share/fonts/truetype/tlwg/Loma-Bold.ttf",
                      "/usr/share/fonts/truetype/tlwg/Waree-Bold.ttf"]}


def _font(lingua_schermo):
    """Ritorna il font per la lingua, o None se la lingua esige un font speciale che MANCA
    (il chiamante degrada lo schermo a inglese: mai quadratini)."""
    if lingua_schermo in FONT_LINGUA:
        for f in FONT_LINGUA[lingua_schermo]:
            if os.path.exists(f):
                return f
        return None
    return FONT


# Invito «attiva l'audio» (primi ~3s): i social partono SEMPRE muti (anti-disturbo, per tutti) —
# la pratica professionale e' scritte che reggono il muto + un invito discreto ad alzare il volume.
AUDIO_HINT = {"it": "Attiva l'audio", "en": "Sound on", "es": "Activa el sonido",
              "fr": "Activez le son", "de": "Ton einschalten", "pt": "Ativa o som",
              "nl": "Geluid aan", "tr": "Sesi aç", "ru": "Включите звук",
              "id": "Nyalakan suara", "vi": "Bật âm thanh", "ko": "소리 켜기",
              "zh": "打开声音", "th": "เปิดเสียง", "ja": "音声をオンに"}


# Lingue OLTRE le 8 di fase200: nome (per il prompt) + ordine-di-lingua scritto NELLA lingua stessa
# (stessa tecnica del guardiano: posizione forte, il modello obbedisce alla sua lingua).
# NB: l'arabo ha la VOCE ma NON lo schermo (ffmpeg drawtext non fa lo shaping RTL -> resta EN a video).
EXTRA_NOME = {"ko": "coreano", "th": "thailandese", "vi": "vietnamita", "id": "indonesiano",
              "ru": "russo", "tr": "turco", "nl": "olandese", "ar": "arabo"}
EXTRA_ORDINE = {
    "ko": "대본은 반드시 한국어로만 작성하세요.",
    "th": "เขียนทั้งหมดเป็นภาษาไทยเท่านั้น",
    "vi": "Viết toàn bộ bằng tiếng Việt.",
    "id": "Tulis semuanya dalam bahasa Indonesia.",
    "ru": "Пиши весь текст только по-русски.",
    "tr": "Tamamını Türkçe yaz.",
    "nl": "Schrijf alles in het Nederlands.",
    "ar": "اكتب كل النص باللغة العربية فقط.",
}

# ── COPIONE (5 battute): soggetto immagine · testo a schermo · voce (ripiego) — per lingua ──────
# On-screen in 14 lingue: latine+cirillico con DejaVu, CJK (ja/zh/ko) e thai coi Noto del VPS
# (FONT_LINGUA). L'arabo NON ha lo schermo (drawtext senza shaping RTL) ma ha la voce. Se manca
# il ripiego voce locale si degrada TUTTO a inglese, coerente (mai italiano fuori Italia). Il
# copione parlato vero lo scrive Groq nella lingua locale; questo e' la rete.
BEAT_SOGGETTI = [
    "cinematic aerial golden hour view of {citta} skyline and rooftops, warm light, photorealistic",
    "beautiful cozy sunlit apartment interior in {citta}, inviting, warm, photorealistic",
    "warm human moment, a host handing keys to a happy guest at an apartment door in {citta}, photorealistic",
    "elegant modern minimal apartment interior in {citta}, transparent glass, natural light, photorealistic",
    "aspirational cinematic sunset skyline of {citta}, luxury travel mood, photorealistic",
]
SCHERMO = {
    "it": ["{citta}.", "Mettila a reddito,\nsenza sorprese.", "0% commissioni\nper 90 giorni",
           "3% tecnico,\ndetto prima.", "BookinVIP\nbookinvip.com"],
    "en": ["{citta}.", "Earn from it,\nno surprises.", "0% commission\nfor 90 days",
           "3% technical fee,\ntold upfront.", "BookinVIP\nbookinvip.com"],
    "es": ["{citta}.", "Ponla a trabajar,\nsin sorpresas.", "0% de comisión\ndurante 90 días",
           "3% técnico,\ndicho antes.", "BookinVIP\nbookinvip.com"],
    "fr": ["{citta}.", "Mettez-le en location,\nsans surprises.", "0 % de commission\npendant 90 jours",
           "3 % techniques,\nannoncés d'avance.", "BookinVIP\nbookinvip.com"],
    "de": ["{citta}.", "Vermieten,\nohne Überraschungen.", "0% Provision\nfür 90 Tage",
           "3% Technikgebühr,\nvorab gesagt.", "BookinVIP\nbookinvip.com"],
    "pt": ["{citta}.", "Ponha-a a render,\nsem surpresas.", "0% de comissão\npor 90 dias",
           "3% técnica,\ndita antes.", "BookinVIP\nbookinvip.com"],
    "nl": ["{citta}.", "Verhuur zonder\nverrassingen.", "0% commissie\nvoor 90 dagen",
           "3% technische kosten,\nvooraf gemeld.", "BookinVIP\nbookinvip.com"],
    "tr": ["{citta}.", "Evinizi gelire çevirin,\nsürpriz yok.", "90 gün boyunca\n%0 komisyon",
           "%3 teknik ücret,\nönceden söylenir.", "BookinVIP\nbookinvip.com"],
    "ru": ["{citta}.", "Сдавайте жильё\nбез сюрпризов.", "0% комиссии\n90 дней",
           "3% техсбор,\nоб этом заранее.", "BookinVIP\nbookinvip.com"],
    "id": ["{citta}.", "Sewakan tanpa\nkejutan.", "Komisi 0%\nselama 90 hari",
           "Biaya teknis 3%,\ndiberitahu di awal.", "BookinVIP\nbookinvip.com"],
    "vi": ["{citta}.", "Cho thuê,\nkhông bất ngờ.", "0% hoa hồng\ntrong 90 ngày",
           "3% phí kỹ thuật,\nbáo trước.", "BookinVIP\nbookinvip.com"],
    "ko": ["{citta}.", "숙소를 수익으로,\n부담 없이.", "첫 90일\n수수료 0%",
           "기술 수수료 3%,\n사전 안내.", "BookinVIP\nbookinvip.com"],
    "zh": ["{citta}.", "轻松出租，\n没有意外。", "前90天\n0%佣金",
           "3%技术费，\n事先说明。", "BookinVIP\nbookinvip.com"],
    "th": ["{citta}.", "ปล่อยเช่า\nไม่มีเซอร์ไพรส์", "ค่าคอมมิชชั่น 0%\n90 วันแรก",
           "ค่าเทคนิค 3%\nแจ้งล่วงหน้า", "BookinVIP\nbookinvip.com"],
    "ja": ["{citta}.", "手間なく貸して、\n収入に。", "最初の90日間\n手数料0%",
           "技術手数料3%、\n事前にお伝え。", "BookinVIP\nbookinvip.com"],
}
VOCE_RIPIEGO = {
    "it": ["Hai una casa a {citta}?", "Mettila a reddito, senza pensieri.",
           "I primi novanta giorni pubblichi a zero commissioni.",
           "Solo un tre per cento tecnico, dichiarato prima. L'ospite non paga nulla.",
           "BookinVIP. Il tuo viaggio, senza sorprese."],
    "en": ["Do you own a place in {citta}?", "Put it to work, effortlessly.",
           "For the first ninety days you list with zero commission.",
           "Only a three percent technical fee, told upfront. Guests pay nothing.",
           "BookinVIP. Your trip, without surprises."],
    "es": ["¿Tienes una casa en {citta}?", "Ponla a trabajar, sin preocupaciones.",
           "Los primeros noventa días publicas con cero comisión.",
           "Solo una tarifa técnica del tres por ciento, dicha antes. El huésped no paga nada.",
           "BookinVIP. Tu viaje, sin sorpresas."],
    "fr": ["Vous avez un logement à {citta} ?", "Mettez-le en location, sans souci.",
           "Pendant les quatre-vingt-dix premiers jours, zéro commission.",
           "Seulement trois pour cent de frais techniques, annoncés d'avance. Le voyageur ne paie rien.",
           "BookinVIP. Votre voyage, sans surprises."],
    "de": ["Haben Sie eine Wohnung in {citta}?", "Vermieten Sie sie, ganz ohne Aufwand.",
           "In den ersten neunzig Tagen listen Sie mit null Prozent Provision.",
           "Nur drei Prozent Technikgebühr, vorab gesagt. Gäste zahlen nichts.",
           "BookinVIP. Ihre Reise, ohne Überraschungen."],
    "pt": ["Tem uma casa em {citta}?", "Ponha-a a render, sem preocupações.",
           "Nos primeiros noventa dias publica com zero comissão.",
           "Apenas uma taxa técnica de três por cento, dita antes. O hóspede não paga nada.",
           "BookinVIP. A sua viagem, sem surpresas."],
    "ja": ["{citta}に物件をお持ちですか？", "手間なく貸し出して、収入に。",
           "最初の90日間は手数料ゼロで掲載できます。",
           "技術手数料は3%のみ。事前にきちんとお伝えします。ゲストは何も払いません。",
           "BookinVIP。あなたの旅を、驚きなしで。"],
}


def _env(nome, default=""):
    v = os.environ.get(nome)
    if v:
        return v
    try:
        for line in open(".env.casavip", encoding="utf-8"):
            line = line.strip()
            if line.startswith(nome + "="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return default


def _riempi(t, citta):
    return t.replace("{citta}", citta)


def _run(cmd, **kw):
    """Esegue un comando; solleva con stderr leggibile se fallisce."""
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if p.returncode != 0:
        raise RuntimeError("comando fallito (%d): %s\n%s" % (p.returncode, " ".join(cmd[:3]),
                                                             (p.stderr or "")[-800:]))
    return p


# ── COPIONE VOCE via Groq (una AI a giro), lingua locale + guardiano lingua ─────────────────────
def _groq_copione(api_key, citta, lingua, n):
    """Chiede a Groq le n battute di voce nella lingua locale, separate da '|'. Ritorna lista o None."""
    if not api_key:
        return None
    ordine = EXTRA_ORDINE.get(lingua) or C._ORDINE_LINGUA.get(lingua, C._ORDINE_LINGUA["en"])
    lang = EXTRA_NOME.get(lingua) or C.NOME_LINGUA.get(lingua, "inglese")
    prompt = (
        "%s\n\nSei un copywriter pubblicitario (scuola Ogilvy). Scrivi il copione PARLATO di uno spot "
        "video di %d battute BREVISSIME per invitare un HOST di %s a pubblicare la sua casa su BookinVIP. "
        "Fatti veri: 0%% commissione i primi 90 giorni (poi 8%%), l'ospite paga 0%%, una tariffa tecnica "
        "del 3%% detta PRIMA della firma. Promessa: «Il tuo viaggio, senza sorprese».\n"
        "Struttura le %d battute cosi': 1) aggancio con la citta'  2) metti a reddito senza pensieri  "
        "3) l'offerta 0%%/90 giorni  4) la trasparenza del 3%%  5) invito: BookinVIP, bookinvip.com.\n"
        "Regole: ogni battuta max 12 parole, parlata e naturale, NIENTE emoji, NIENTE virgolette. "
        "Rispondi SOLO con le %d battute separate dal carattere '|', nient'altro. "
        "IMPORTANTE: scrivi interamente in %s.%s"
        % (ordine, n, citta, n, n, lang,
           "" if lingua == "it" else " Nessuna parola italiana.")
    )
    body = json.dumps({"model": GROQ_MODELLO, "temperature": 0.7, "max_tokens": 320,
                       "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
    req = urllib.request.Request(GROQ_URL, data=body, method="POST",
                                 headers={"Authorization": "Bearer " + api_key,
                                          "Content-Type": "application/json",
                                          "User-Agent": "Mozilla/5.0 (BookinVIP)"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        testo = d["choices"][0]["message"]["content"]
    except Exception as e:
        print("   [Groq errore: %r]" % e)
        return None
    parti = [C.pulisci_didascalia(x) for x in testo.split("|")]
    parti = [x for x in parti if x]
    if len(parti) < n:
        return None
    parti = parti[:n]
    if any(C._contaminato_italiano(x, lingua) for x in parti):
        print("   [copione scartato: italiano fuori Italia -> ripiego]")
        return None
    return parti


def copione(api_key, citta, lingua):
    """Ritorna (scene, da_ai, lingua_voce, lingua_schermo). Coerenza garantita: se l'AI tace e
    NON esiste un ripiego locale, si degrada TUTTO a inglese (voce+schermo insieme, mai misti)."""
    voci = _groq_copione(api_key, citta, lingua, len(BEAT_SOGGETTI))
    da_ai = voci is not None
    lingua_voce = lingua
    if not da_ai:
        lingua_voce = lingua if lingua in VOCE_RIPIEGO else "en"
        base = VOCE_RIPIEGO[lingua_voce]
        voci = [_riempi(x, citta) for x in base]
    lingua_schermo = lingua_voce if lingua_voce in SCHERMO else "en"
    schermo = SCHERMO[lingua_schermo]
    scene = []
    for i, sog in enumerate(BEAT_SOGGETTI):
        scene.append({"soggetto": _riempi(sog, citta),
                      "schermo": _riempi(schermo[i], citta),
                      "voce": voci[i]})
    return scene, da_ai, lingua_voce, lingua_schermo


# ── immagine flux + voce edge-tts + clip ffmpeg per scena ───────────────────────────────────────
def scarica_immagine(soggetto, dest):
    url = (C.POLLINATIONS + urllib.parse.quote(soggetto) +
           "?width=%d&height=%d&model=flux&enhance=true&nologo=true&seed=%d"
           % (W, H, abs(hash(soggetto)) % 100000))
    # NB: Pollinations (Cloudflare) blocca lo User-Agent di default di Python -> serve un UA "browser"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (BookinVIP)"})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=95) as r:
                dati = r.read()
            if len(dati) > 3000 and dati[:3] in (b"\xff\xd8\xff", b"\x89PN"):   # JPEG o PNG veri
                open(dest, "wb").write(dati)
                return True
        except Exception:
            pass
    return False


def sintetizza_voce(testo, voce, dest):
    _run(["python3", "-m", "edge_tts", "--voice", voce, "--text", testo, "--write-media", dest])
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", dest], capture_output=True, text=True)
    try:
        return max(1.6, float(p.stdout.strip()))
    except Exception:
        return 3.0


def _drawtext_filter(txt_path, font):
    # box scuro semitrasparente nel terzo basso + testo bianco grande centrato (multilinea via textfile)
    # expansion=none: rende letterale il carattere '%' (0% / 3%), altrimenti ffmpeg lo mangia come codice
    return (
        "drawbox=y=ih-660:x=0:w=iw:h=520:color=black@0.42:t=fill,"
        "drawtext=fontfile=%s:textfile=%s:expansion=none:reload=0:fontcolor=white:fontsize=74:"
        "line_spacing=16:x=(w-text_w)/2:y=h-560:borderw=3:bordercolor=black@0.6" % (font, txt_path)
    )


def clip_scena(img, mp3, durata, schermo_txt, tmp, idx, zoom_in=True, font=FONT, hint=None):
    txt_file = os.path.join(tmp, "t%d.txt" % idx)
    open(txt_file, "w", encoding="utf-8").write(schermo_txt)
    d_frames = int(durata * FPS)
    if zoom_in:
        z = "z='min(zoom+0.0009,1.22)'"
    else:
        z = "z='if(lte(zoom,1.0),1.22,max(zoom-0.0009,1.0))'"
    testo = _drawtext_filter(txt_file, font)
    if hint:
        hint_file = os.path.join(tmp, "hint%d.txt" % idx)
        open(hint_file, "w", encoding="utf-8").write(hint)
        testo += (",drawtext=fontfile=%s:textfile=%s:expansion=none:fontcolor=white:fontsize=44:"
                  "x=(w-text_w)/2:y=190:box=1:boxcolor=black@0.38:boxborderw=18:enable='lt(t,3.2)'"
                  % (font, hint_file))
    vf = (
        "scale=1350:2400:force_original_aspect_ratio=increase,crop=1350:2400,"
        "zoompan=%s:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=%d:s=%dx%d:fps=%d,setsar=1,"
        "%s,"
        "fade=t=in:st=0:d=0.4,fade=t=out:st=%.2f:d=0.4"
        % (z, d_frames, W, H, FPS, testo, max(0.1, durata - 0.4))
    )
    out = os.path.join(tmp, "scena%d.mp4" % idx)
    _run(["ffmpeg", "-y", "-loop", "1", "-i", img, "-i", mp3,
          "-filter_complex", "[0:v]" + vf + "[v]", "-map", "[v]", "-map", "1:a",
          "-t", "%.2f" % durata, "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "128k", "-r", str(FPS), out])
    return out


def monta(citta, lingua, out_path, voce=None):
    api = _env("GROQ_API_KEY")
    tmp = tempfile.mkdtemp(prefix="vid_")
    print("Copione (%s / %s)..." % (citta, lingua))
    scene, da_ai, lingua_voce, lingua_schermo = copione(api, citta, lingua)
    print("  copione: %s (voce=%s schermo=%s)" % ("Groq" if da_ai else "ripiego",
                                                  lingua_voce, lingua_schermo))
    voce_scelta = voce or VOCI.get(lingua_voce, VOCI["en"])
    font = _font(lingua_schermo)
    if font is None:   # font speciale richiesto ma ASSENTE -> mai quadratini: schermo in inglese
        print("  [font %s assente -> schermo in inglese]" % lingua_schermo)
        lingua_schermo, font = "en", FONT
        for i, s in enumerate(scene):
            s["schermo"] = _riempi(SCHERMO["en"][i], citta)
    hint = AUDIO_HINT.get(lingua_schermo, AUDIO_HINT["en"])
    clips = []
    for i, s in enumerate(scene):
        print("  scena %d: %s" % (i + 1, s["voce"]))
        img = os.path.join(tmp, "img%d.jpg" % i)
        if not scarica_immagine(s["soggetto"], img):
            raise RuntimeError("immagine flux non scaricata (scena %d)" % (i + 1))
        mp3 = os.path.join(tmp, "voce%d.mp3" % i)
        dur = sintetizza_voce(s["voce"], voce_scelta, mp3) + 0.6
        clips.append(clip_scena(img, mp3, dur, s["schermo"], tmp, i, zoom_in=(i % 2 == 0),
                                font=font, hint=(hint if i == 0 else None)))
    lista = os.path.join(tmp, "lista.txt")
    open(lista, "w").write("".join("file '%s'\n" % c for c in clips))
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lista, "-c", "copy", out_path])
    print("VIDEO pronto: %s (%.1f MB)" % (out_path, os.path.getsize(out_path) / 1e6))
    return out_path


def posta_telegram(path, caption):
    token, chat = _env("TELEGRAM_BOT_TOKEN"), _env("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return "no-token"
    # curl = multipart affidabile per l'upload del file video
    p = subprocess.run(["curl", "-s", "-F", "chat_id=" + chat, "-F", "video=@" + path,
                        "-F", "caption=" + caption, "-F", "supports_streaming=true",
                        "https://api.telegram.org/bot%s/sendVideo" % token],
                       capture_output=True, text=True)
    try:
        d = json.loads(p.stdout)
        return "OK id %s" % d["result"]["message_id"] if d.get("ok") else "ERR %s" % d.get("description")
    except Exception:
        return "ERR %s" % (p.stdout or p.stderr)[:200]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--citta", default="Roma")
    ap.add_argument("--lingua", default="it")
    ap.add_argument("--out", default="/tmp/bookinvip_video.mp4")
    ap.add_argument("--voce", default=None, help="voce edge-tts esplicita (es. en-GB-RyanNeural per Londra)")
    ap.add_argument("--telegram", action="store_true")
    a = ap.parse_args()
    out = monta(a.citta, a.lingua, a.out, voce=a.voce)
    if a.telegram:
        cap = "BookinVIP — %s. Il tuo viaggio, senza sorprese. bookinvip.com" % a.citta
        print("-> Telegram: %s" % posta_telegram(out, cap))


if __name__ == "__main__":
    main()
