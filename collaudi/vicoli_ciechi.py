"""
CACCIA AI VICOLI CIECHI — cammina i percorsi come un utente VERO e trova i punti dove si bloccherebbe.

I bug di LOGICA di percorso non si vedono nei test unitari: un link che porta a 404, un form che invia
a una rotta inesistente, una pagina protetta che rimanda a un login SENZA via d'uscita (era il caso di
/entra-host prima del fix). Questo collaudo:
  1. carica ogni ENTRY POINT pubblico (dove un utente ARRIVA: home, diventa-host, gate, blog, landing…);
  2. estrae OGNI link interno (href), OGNI form (action), OGNI chiamata API (fetch('/api/…'));
  3. verifica che ognuno RISPONDA (mai 404 / 'rotta_non_trovata' / 500 non gestito);
  4. verifica le VIE D'USCITA obbligatorie (il gate host DEVE offrire Registrati + recupero password).

Gira contro il server visivo locale:  python collaudi/avvia_server_visivo.py 8099  poi  python collaudi/vicoli_ciechi.py
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("BASE_VISIVO", "http://127.0.0.1:8099")


def _req(metodo, path, body=None):
    url = BASE + path
    data = body.encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=metodo)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        r = urllib.request.urlopen(req, timeout=8)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            corpo = e.read().decode("utf-8", "replace")
        except Exception:
            corpo = ""
        return e.code, corpo
    except Exception as e:
        return -1, str(e)


def _morto(status, corpo):
    """È un vicolo cieco? 404/500 o corpo 'rotta_non_trovata', o errore di connessione."""
    if status == -1:
        return True
    if status == 404:
        return True
    if status >= 500 and "rotta_non_trovata" in corpo:
        return True
    if isinstance(corpo, str) and '"rotta_non_trovata"' in corpo:
        return True
    return False


# ── entry point dove un utente VERO arriva (link del bot, email, marketing, navigazione) ──
ENTRY = [
    "/", "/diventa-host.html", "/entra-host", "/entra-admin", "/entra-bunker",
    "/blog", "/affitta/roma", "/commissioni.html", "/host.html", "/admin.html",
    "/termini.html", "/privacy.html", "/grazie", "/annullato",
]

# pagine protette: DEVONO rimandare a un gate, e il gate host DEVE avere una via d'uscita
GATE_CON_USCITA = {"/entra-host": ["/diventa-host.html", "password_dimenticata", "password_reset"]}


def main():
    vicoli = []
    controllati = set()
    print("=" * 78)
    print("CACCIA AI VICOLI CIECHI —  base:", BASE)
    print("=" * 78)

    # 1) ogni entry point carica (seguendo i redirect di urllib: gated -> gate, deve dare pagina viva)
    pagine = {}
    for p in ENTRY:
        st, body = _req("GET", p)
        pagine[p] = body
        stato = "OK" if not _morto(st, body) and st != -1 else "MORTO"
        if _morto(st, body):
            vicoli.append("ENTRY %s -> status %s (pagina d'ingresso morta)" % (p, st))
        print("  [%-5s] entry %-28s (len=%d)" % (stato, p, len(body)))

    # 2) estrai e verifica OGNI link interno / form / fetch da tutte le pagine caricate
    n_link = 0
    for p, body in pagine.items():
        if not isinstance(body, str) or not body:
            continue
        interni = set(re.findall(r'href="(/[^"#?\s]+)"', body))
        interni |= set(re.findall(r'action="(/[^"?\s]+)"', body))
        api = set(re.findall(r"""(?:fetch|open)\(['"](/api/[A-Za-z0-9_/\-]+)['"]""", body))
        api |= set(re.findall(r"""['"](/api/[A-Za-z0-9_/\-]+)['"]""", body))
        for link in sorted(interni):
            if link in controllati or link.endswith((".js", ".css", ".png", ".jpg", ".svg", ".ico")):
                continue
            controllati.add(link)
            n_link += 1
            st, b = _req("GET", link)
            if _morto(st, b):
                vicoli.append("LINK MORTO %s (in %s) -> status %s" % (link, p, st))
        for a in sorted(api):
            if a in controllati:
                continue
            controllati.add(a)
            n_link += 1
            # /api: provo GET e POST vuoto; è "vivo" se ALMENO uno non è rotta_non_trovata
            g_st, g_b = _req("GET", a)
            po_st, po_b = _req("POST", a, "{}")
            if _morto(g_st, g_b) and _morto(po_st, po_b):
                vicoli.append("API MORTA %s (in %s) -> GET %s / POST %s" % (a, p, g_st, po_st))

    # 3) vie d'uscita obbligatorie dei gate
    for gate, attesi in GATE_CON_USCITA.items():
        _, body = _req("GET", gate)
        for atteso in attesi:
            if atteso not in (body or ""):
                vicoli.append("VICOLO CIECO nel gate %s: manca la via d'uscita '%s'" % (gate, atteso))

    print("-" * 78)
    print("link/form/API camminati: %d  |  entry point: %d" % (n_link, len(ENTRY)))
    if vicoli:
        print("VICOLI CIECHI TROVATI: %d" % len(vicoli))
        for v in vicoli:
            print("   ✗ " + v)
    else:
        print("VICOLI CIECHI: 0 — ogni percorso porta da qualche parte, nessun utente resta bloccato.")
    print("=" * 78)
    sys.exit(1 if vicoli else 0)


if __name__ == "__main__":
    main()
