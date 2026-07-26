"""
ANTEPRIMA della campagna persuasiva (fase200) con l'AI VERA (Groq) — per mostrare al fondatore
esempi reali PRIMA di accendere l'auto-pubblicazione. Genera un contenuto per OGNI leva di Cialdini
(didascalia scritta da Groq + immagine flux), li stampa, e (opzionale) posta i primi N su Telegram
cosi' si vedono immagine + didascalia insieme.

Uso (sul VPS, dove ci sono le chiavi):
    cd /var/www/bookinvip && python3 collaudi/anteprima_campagna.py           # solo stampa
    cd /var/www/bookinvip && python3 collaudi/anteprima_campagna.py --telegram 3   # posta i primi 3
Legge GROQ_API_KEY (e per Telegram TELEGRAM_BOT_TOKEN/CHAT_ID) da .env.casavip.
"""
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import fase200_campagna_persuasiva as C

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELLO = os.environ.get("GROQ_MODELLO", "llama-3.3-70b-versatile")


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


def _groq(api_key):
    def genera_testo(prompt):
        if not api_key:
            return None
        body = json.dumps({"model": GROQ_MODELLO, "temperature": 0.9, "max_tokens": 220,
                           "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
        req = urllib.request.Request(GROQ_URL, data=body, method="POST",
                                     headers={"Authorization": "Bearer " + api_key,
                                              "Content-Type": "application/json",
                                              "User-Agent": "Mozilla/5.0 (BookinVIP)"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
            return d["choices"][0]["message"]["content"]
        except Exception as e:
            print("   [Groq errore: %r]" % e)
            return None
    return genera_testo


def _riscalda(immagine, tentativi=3):
    """PRE-RISCALDO: flux ci mette ~30-60s a generare; se Telegram/Facebook vanno a prenderla per URL
    prima che sia pronta è un 400. La scarico io PER INTERO (non solo 64 byte): così Pollinations la
    genera e la mette in CACHE, e la fetch successiva (TG/FB) la trova pronta e istantanea."""
    for _ in range(tentativi):
        try:
            with urllib.request.urlopen(immagine, timeout=95) as r:
                if len(r.read()) > 1000:      # immagine vera, non una pagina d'errore
                    return True
        except Exception:
            pass
    return False


def _posta_telegram(token, chat, immagine, didascalia):
    if not (token and chat):
        return "no-token"
    body = json.dumps({"chat_id": chat, "photo": immagine, "caption": didascalia}).encode("utf-8")
    req = urllib.request.Request("https://api.telegram.org/bot%s/sendPhoto" % token, data=body,
                                 method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        return "OK id %s" % d["result"]["message_id"] if d.get("ok") else "ERR %s" % d.get("description")
    except Exception as e:
        return "ERR %r" % e


def _posta_facebook(page_id, page_token, immagine, didascalia):
    """Posta la FOTO (immagine flux) + didascalia sulla Pagina Facebook via Graph /photos.
    FB scarica l'immagine per URL: il pre-riscaldo l'ha già messa in cache di Pollinations."""
    if not (page_id and page_token):
        return "no-token"
    body = urllib.parse.urlencode({"url": immagine, "caption": didascalia,
                                   "access_token": page_token}).encode("utf-8")
    req = urllib.request.Request("https://graph.facebook.com/v19.0/%s/photos" % page_id, data=body,
                                 method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        return ("OK id %s" % d.get("id")) if d.get("id") else ("ERR %s" % d)
    except Exception as e:
        return "ERR %r" % e


def main():
    n_telegram = 0
    if "--telegram" in sys.argv:
        i = sys.argv.index("--telegram")
        n_telegram = int(sys.argv[i + 1]) if i + 1 < len(sys.argv) else 3

    n_facebook = 0
    if "--facebook" in sys.argv:
        i = sys.argv.index("--facebook")
        n_facebook = int(sys.argv[i + 1]) if i + 1 < len(sys.argv) else 3

    # --globale N: mostra N contenuti del giro MONDIALE (città top diverse, lingua del posto).
    n_globale = 0
    if "--globale" in sys.argv:
        i = sys.argv.index("--globale")
        n_globale = int(sys.argv[i + 1]) if i + 1 < len(sys.argv) else len(C.CITTA_TOP)

    gk = _env("GROQ_API_KEY")
    print("=" * 84)
    modo = "GIRO MONDIALE (%d città top, lingua locale)" % n_globale if n_globale else "7 leve di Cialdini (Roma)"
    print("ANTEPRIMA CAMPAGNA PERSUASIVA — %s (Groq: %s)" % (modo, "SI" if gk else "NO -> ripiego"))
    print("=" * 84)
    gen = C.crea_generatore_campagna(_groq(gk), citta="Roma")
    if n_globale:
        giro = [gen.genera_globale() for _ in range(n_globale)]
    else:
        giro = gen.genera_giro_completo()

    tg_token = _env("TELEGRAM_BOT_TOKEN")
    tg_chat = _env("TELEGRAM_CHAT_ID")
    fb_id = _env("META_PAGE_ID")
    fb_token = _env("META_PAGE_TOKEN")
    for idx, r in enumerate(giro, 1):
        dove = "  [%s / %s]" % (r.get("citta", ""), r.get("lingua", "")) if n_globale else ""
        print("\n%2d) LEVA: %s%s  %s" % (idx, r["leva"], dove, "" if r["da_ai"] else "(ripiego)"))
        print("    DIDASCALIA: %s" % r["didascalia"])
        print("    IMMAGINE:   %s" % r["immagine"][:110] + "...")
        if idx <= max(n_telegram, n_facebook):
            pronto = _riscalda(r["immagine"])          # una volta sola, poi la usano entrambi i canali
            print("    IMMAGINE pronta in cache: %s" % ("SI" if pronto else "NO (posto lo stesso)"))
            if idx <= n_telegram:
                print("    -> Telegram: %s" % _posta_telegram(tg_token, tg_chat, r["immagine"], r["didascalia"]))
            if idx <= n_facebook:
                print("    -> Facebook: %s" % _posta_facebook(fb_id, fb_token, r["immagine"], r["didascalia"]))
    print("\n" + "=" * 84)
    coda = []
    if n_telegram:
        coda.append("%d su Telegram" % n_telegram)
    if n_facebook:
        coda.append("%d su Facebook" % n_facebook)
    print("Fatto. %d esempi generati%s." % (len(giro), (", postati: " + " + ".join(coda)) if coda else ""))


if __name__ == "__main__":
    main()
