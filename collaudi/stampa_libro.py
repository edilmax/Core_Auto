"""STAMPA IL LIBRO DI BOOKINVIP: dal `README.md` al PDF sul Desktop, con un comando solo.

    python collaudi/stampa_libro.py                  -> Desktop\\IL LIBRO DI BOOKINVIP.pdf
    python collaudi/stampa_libro.py --cartella <dir> -> lo stesso PDF in un'altra cartella

Deciso dal fondatore il 2026-10-13: il libro e' UNO, il README; il PDF si STAMPA da li', mai
scritto a mano, con commit e data in copertina, e si ristampa a ogni deploy.

Due attrezzi, tutti e due gia' sul PC (nessuna dipendenza nuova): la libreria `markdown`
trasforma il README in una pagina, e il browser senza finestra (Chrome, o Edge) la stampa.

⛔ IL NOME DICE SE IL LIBRO E' QUELLO VERO. Se il README ha modifiche non ancora salvate in
un commit, il file si chiama «... - PROVA.pdf» e la copertina lo scrive: un PDF col nome
definitivo che descrive un testo mai salvato e' esattamente il documento che mente.

Uscita: 0 stampato e verificato · 1 stampa fallita · 2 manca una premessa (niente stampa).

⚠️ COSA NON CONTROLLA (D18 punto 3): non legge il contenuto del PDF; guarda che il file sia
nato in questa corsa, che cominci con la firma «%PDF» e che non sia minuscolo. Che il libro
dica il vero rispetto al codice non lo sa: quello lo dicono le citazioni `file:riga`.
"""
import argparse
import datetime
import html
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TITOLO = "IL LIBRO DI BOOKINVIP"
BROWSER = (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
           r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
           r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
           r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")
PDF_MINIMO_BYTE = 10000          # sotto, il browser ha stampato una pagina vuota o d'errore

STILE = """
body{font-family:Georgia,serif;font-size:11pt;line-height:1.45;margin:0 1.2cm}
h1{page-break-before:always;font-size:20pt} h2{font-size:15pt} h3{font-size:12.5pt}
table{border-collapse:collapse;width:100%;font-size:9.5pt;margin:.6em 0}
th,td{border:1px solid #999;padding:3px 5px;vertical-align:top}
code{font-family:Consolas,monospace;font-size:9pt;background:#f2f2f2}
pre{background:#f2f2f2;padding:6px;white-space:pre-wrap;font-size:8.5pt}
blockquote{border-left:3px solid #999;margin-left:0;padding-left:10px;color:#333}
.copertina{height:24cm;display:flex;flex-direction:column;justify-content:center;text-align:center}
.copertina h1{page-break-before:avoid;font-size:30pt}
"""


def _git(*argomenti):
    r = subprocess.run(["git", "-C", REPO] + list(argomenti),
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError("git %s -> uscita %d: %s" % (" ".join(argomenti), r.returncode,
                                                        (r.stderr or "").strip()[:200]))
    return r.stdout.strip()


def _premesse():
    """Misura prima se stesso (D18 punto 1): senza una di queste non si stampa niente."""
    mancanti = []
    try:
        import markdown  # noqa: F401  (si prova solo che ci sia)
    except ImportError:
        mancanti.append("la libreria `markdown` non e' installata")
    browser = next((b for b in BROWSER if os.path.isfile(b)), None)
    if browser is None:
        mancanti.append("nessun browser trovato fra: " + " · ".join(BROWSER))
    if not os.path.isfile(os.path.join(REPO, "README.md")):
        mancanti.append("README.md assente in " + REPO)
    if shutil.which("git") is None:
        mancanti.append("git non e' nel PATH (serve il commit per la copertina)")
    return browser, mancanti


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Stampa il Libro di BookinVIP dal README.md")
    ap.add_argument("--cartella", default=os.path.join(os.path.expanduser("~"), "Desktop"),
                    help="dove scrivere il PDF (predefinito: il Desktop)")
    a = ap.parse_args(argv)

    browser, mancanti = _premesse()
    if not os.path.isdir(a.cartella):
        mancanti.append("la cartella di destinazione non esiste: " + a.cartella)
    if mancanti:
        for m in mancanti:
            print("PREMESSA MANCANTE:", m)
        print("STAMPA_USCITA=2")
        return 2

    import markdown
    commit = _git("rev-parse", "--short", "HEAD")
    prova = _git("status", "--porcelain", "--", "README.md") != ""
    adesso = datetime.datetime.now()                 # un orologio solo, letto una volta
    nome = TITOLO + (" - PROVA" if prova else "") + ".pdf"
    destinazione = os.path.join(a.cartella, nome)
    stato = ("commit %s + README modificato e NON ancora salvato: questa e' una PROVA" % commit
             if prova else "commit %s" % commit)

    with open(os.path.join(REPO, "README.md"), encoding="utf-8") as f:
        corpo = markdown.markdown(f.read(), extensions=["tables", "fenced_code", "toc"])
    pagina = ("<!doctype html><html lang=\"it\"><head><meta charset=\"utf-8\">"
              "<title>%s</title><style>%s</style></head><body>"
              "<div class=\"copertina\"><h1>%s</h1><p>Stampato dal README.md il %s</p><p>%s</p>"
              "<p>Se questo libro e il codice dicono cose diverse, ha ragione il codice.</p>"
              "</div>%s</body></html>"
              % (TITOLO, STILE, TITOLO, adesso.strftime("%Y-%m-%d %H:%M"),
                 html.escape(stato), corpo))

    lavoro = os.path.join(a.cartella, ".stampa_libro_in_corso.html")
    with open(lavoro, "w", encoding="utf-8") as f:
        f.write(pagina)
    prima = os.path.getmtime(destinazione) if os.path.exists(destinazione) else None
    try:
        r = subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                            "--print-to-pdf=" + destinazione,
                            "file:///" + lavoro.replace("\\", "/")],
                           capture_output=True, text=True, timeout=300)
    finally:
        os.remove(lavoro)

    # Il file deve essere NATO IN QUESTA CORSA: uno vecchio rimasto li' non e' una stampa.
    nato = os.path.isfile(destinazione) and os.path.getmtime(destinazione) != prima
    firma = b""
    if nato:
        with open(destinazione, "rb") as f:
            firma = f.read(5)
    dimensione = os.path.getsize(destinazione) if nato else 0
    print("browser   :", browser, "-> uscita", r.returncode)
    print("copertina :", stato, "·", adesso.strftime("%Y-%m-%d %H:%M"))
    print("pdf       :", destinazione, "·", dimensione, "byte")
    if r.returncode != 0 or not nato or firma != b"%PDF-" or dimensione < PDF_MINIMO_BYTE:
        print("STAMPA FALLITA: uscita del browser %d, nato in questa corsa %s, firma %r, "
              "%d byte (minimo %d)" % (r.returncode, nato, firma, dimensione, PDF_MINIMO_BYTE))
        print("STAMPA_USCITA=1")
        return 1
    print("STAMPA_USCITA=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
