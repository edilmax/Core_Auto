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
        "ja": "ja-JP-KeitaNeural", "zh": "zh-CN-YunxiNeural"}

# ── COPIONE (5 battute): soggetto immagine · testo a schermo · voce (ripiego) — per lingua ──────
# On-screen e ripiego voce in italiano e inglese; le altre lingue ricadono sull'inglese (mai italiano
# fuori Italia). Il copione parlato vero lo scrive Groq nella lingua locale; questo e' la rete.
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
    ordine = C._ORDINE_LINGUA.get(lingua, C._ORDINE_LINGUA["en"])
    lang = C.NOME_LINGUA.get(lingua, "inglese")
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
    voci = _groq_copione(api_key, citta, lingua, len(BEAT_SOGGETTI))
    da_ai = voci is not None
    if not da_ai:
        base = VOCE_RIPIEGO.get(lingua) or VOCE_RIPIEGO["en"]
        voci = [_riempi(x, citta) for x in base]
    schermo = SCHERMO.get(lingua) or SCHERMO["en"]
    scene = []
    for i, sog in enumerate(BEAT_SOGGETTI):
        scene.append({"soggetto": _riempi(sog, citta),
                      "schermo": _riempi(schermo[i], citta),
                      "voce": voci[i]})
    return scene, da_ai


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


def _drawtext_filter(txt_path):
    # box scuro semitrasparente nel terzo basso + testo bianco grande centrato (multilinea via textfile)
    # expansion=none: rende letterale il carattere '%' (0% / 3%), altrimenti ffmpeg lo mangia come codice
    return (
        "drawbox=y=ih-660:x=0:w=iw:h=520:color=black@0.42:t=fill,"
        "drawtext=fontfile=%s:textfile=%s:expansion=none:reload=0:fontcolor=white:fontsize=74:"
        "line_spacing=16:x=(w-text_w)/2:y=h-560:borderw=3:bordercolor=black@0.6" % (FONT, txt_path)
    )


def clip_scena(img, mp3, durata, schermo_txt, tmp, idx, zoom_in=True):
    txt_file = os.path.join(tmp, "t%d.txt" % idx)
    open(txt_file, "w", encoding="utf-8").write(schermo_txt)
    d_frames = int(durata * FPS)
    if zoom_in:
        z = "z='min(zoom+0.0009,1.22)'"
    else:
        z = "z='if(lte(zoom,1.0),1.22,max(zoom-0.0009,1.0))'"
    vf = (
        "scale=1350:2400:force_original_aspect_ratio=increase,crop=1350:2400,"
        "zoompan=%s:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=%d:s=%dx%d:fps=%d,setsar=1,"
        "%s,"
        "fade=t=in:st=0:d=0.4,fade=t=out:st=%.2f:d=0.4"
        % (z, d_frames, W, H, FPS, _drawtext_filter(txt_file), max(0.1, durata - 0.4))
    )
    out = os.path.join(tmp, "scena%d.mp4" % idx)
    _run(["ffmpeg", "-y", "-loop", "1", "-i", img, "-i", mp3,
          "-filter_complex", "[0:v]" + vf + "[v]", "-map", "[v]", "-map", "1:a",
          "-t", "%.2f" % durata, "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "128k", "-r", str(FPS), out])
    return out


def monta(citta, lingua, out_path):
    api = _env("GROQ_API_KEY")
    tmp = tempfile.mkdtemp(prefix="vid_")
    print("Copione (%s / %s)..." % (citta, lingua))
    scene, da_ai = copione(api, citta, lingua)
    print("  copione: %s" % ("Groq" if da_ai else "ripiego"))
    clips = []
    for i, s in enumerate(scene):
        print("  scena %d: %s" % (i + 1, s["voce"]))
        img = os.path.join(tmp, "img%d.jpg" % i)
        if not scarica_immagine(s["soggetto"], img):
            raise RuntimeError("immagine flux non scaricata (scena %d)" % (i + 1))
        mp3 = os.path.join(tmp, "voce%d.mp3" % i)
        dur = sintetizza_voce(s["voce"], VOCI.get(lingua, VOCI["en"]), mp3) + 0.6
        clips.append(clip_scena(img, mp3, dur, s["schermo"], tmp, i, zoom_in=(i % 2 == 0)))
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
    ap.add_argument("--telegram", action="store_true")
    a = ap.parse_args()
    out = monta(a.citta, a.lingua, a.out)
    if a.telegram:
        cap = "BookinVIP — %s. Il tuo viaggio, senza sorprese. bookinvip.com" % a.citta
        print("-> Telegram: %s" % posta_telegram(out, cap))


if __name__ == "__main__":
    main()
