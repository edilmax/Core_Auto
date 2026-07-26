"""
Pubblica un VIDEO locale sui canali, in PURO Python (multipart fatto a mano) — niente curl (sul VPS
il curl -F non riesce a leggere il file). Legge le chiavi da .env.casavip.
  - Telegram: sendVideo (bot API, file fino a 50MB)
  - Facebook: /{page_id}/videos (upload diretto)
Uso: python3 collaudi/pubblica_video.py /tmp/roma2.mp4 --telegram --facebook --caption "..."
"""
import argparse
import io
import json
import os
import sys
import urllib.request
import uuid


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


def _multipart(campi, files):
    """campi: {nome: valore}; files: {nome: (filename, bytes, content_type)} -> (boundary, corpo)."""
    boundary = "----BVIP" + uuid.uuid4().hex
    b = io.BytesIO()

    def w(x):
        b.write(x.encode("utf-8") if isinstance(x, str) else x)

    for k, v in campi.items():
        w("--%s\r\n" % boundary)
        w('Content-Disposition: form-data; name="%s"\r\n\r\n' % k)
        w("%s\r\n" % v)
    for nome, (fn, data, ct) in files.items():
        w("--%s\r\n" % boundary)
        w('Content-Disposition: form-data; name="%s"; filename="%s"\r\n' % (nome, fn))
        w("Content-Type: %s\r\n\r\n" % ct)
        w(data)
        w("\r\n")
    w("--%s--\r\n" % boundary)
    return boundary, b.getvalue()


def _post_multipart(url, campi, files, timeout=240):
    boundary, corpo = _multipart(campi, files)
    req = urllib.request.Request(url, data=corpo, method="POST",
                                 headers={"Content-Type": "multipart/form-data; boundary=" + boundary,
                                          "User-Agent": "Mozilla/5.0 (BookinVIP)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def telegram(path, caption):
    tok, chat = _env("TELEGRAM_BOT_TOKEN"), _env("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return "no-token"
    data = open(path, "rb").read()
    try:
        d = _post_multipart("https://api.telegram.org/bot%s/sendVideo" % tok,
                            {"chat_id": chat, "caption": caption, "supports_streaming": "true"},
                            {"video": (os.path.basename(path), data, "video/mp4")})
        return "OK id %s" % d["result"]["message_id"] if d.get("ok") else "ERR %s" % d.get("description")
    except Exception as e:
        return "ERR %r" % e


def facebook(path, caption):
    page, tok = _env("META_PAGE_ID"), _env("META_PAGE_TOKEN")
    if not (page and tok):
        return "no-token"
    data = open(path, "rb").read()
    try:
        d = _post_multipart("https://graph-video.facebook.com/v19.0/%s/videos" % page,
                            {"access_token": tok, "description": caption},
                            {"source": (os.path.basename(path), data, "video/mp4")})
        return ("OK id %s" % d.get("id")) if d.get("id") else ("ERR %s" % d)
    except Exception as e:
        return "ERR %r" % e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--telegram", action="store_true")
    ap.add_argument("--facebook", action="store_true")
    ap.add_argument("--caption", default="BookinVIP. Il tuo viaggio, senza sorprese. bookinvip.com")
    a = ap.parse_args()
    if not os.path.exists(a.path):
        print("file inesistente: %s" % a.path)
        sys.exit(1)
    print("file: %s (%.1f MB)" % (a.path, os.path.getsize(a.path) / 1e6))
    if a.telegram:
        print("-> Telegram: %s" % telegram(a.path, a.caption))
    if a.facebook:
        print("-> Facebook: %s" % facebook(a.path, a.caption))


if __name__ == "__main__":
    main()
