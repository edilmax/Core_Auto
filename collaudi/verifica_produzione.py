"""VERIFICA DI PRODUZIONE — il sito VERO, interrogato da fuori come farebbe un utente.

I test girano sul computer: provano il codice, non il SITO. Qui si interroga bookinvip.com
dall'esterno, in SOLA LETTURA, e si pretende che ogni cosa importante risponda giusto:

  P1  LE PAGINE        - tutto quello che un utente puo' aprire risponde 200 (o 302 se riservato)
  P2  LE PORTE APERTE  - le API pubbliche rispondono e dicono la verita' sulle tariffe
  P3  LE PORTE CHIUSE  - ogni porta riservata risponde 401/403, MAI 200
  P4  LA CORAZZA       - HTTPS, certificato, intestazioni di sicurezza, niente http in chiaro
  P5  LA COERENZA      - le percentuali dette al pubblico sono quelle del motore
  P6  ROBUSTEZZA       - input assurdi non fanno cadere niente

NON crea prenotazioni, NON tocca denaro, NON scrive nulla. Sola lettura.
"""
import json
import re
import ssl
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "https://bookinvip.com"
VIOL = []
CONTA = {"n": 0}


def check(liv, regola, ok, dett=""):
    CONTA["n"] += 1
    if not ok:
        VIOL.append("[%s] %s %s" % (liv, regola, dett))


def chiedi(percorso, metodo="GET", testate=None, timeout=25, segui=False):
    """Ritorna (stato, testate, corpo). Mai solleva."""
    req = urllib.request.Request(BASE + percorso, method=metodo,
                                 headers=testate or {"User-Agent": "BookinVIP-Verifica/1.0"})
    op = urllib.request.build_opener() if segui else urllib.request.build_opener(
        _NoRedirect)
    try:
        with op.open(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read(400000)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), (e.read(80000) or b"")
    except Exception as e:
        return -1, {}, str(e).encode()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


# ═══════════════════════════════════════════════════════════════════════════════
def p1_pagine():
    pubbliche = ["/", "/index.html", "/commissioni.html", "/termini.html",
                 "/privacy.html", "/contratto-host.html", "/app.js", "/robots.txt",
                 "/sitemap.xml"]
    for p in pubbliche:
        st, _, corpo = chiedi(p)
        check("P1", "pagina-pubblica-%s" % p, st == 200, "stato %d" % st)
        if st == 200 and p.endswith(".html"):
            check("P1", "pagina-non-vuota-%s" % p, len(corpo) > 1500,
                  "%d byte" % len(corpo))
    # le pagine riservate devono RIMANDARE al login, non aprirsi
    for p in ["/host.html", "/admin.html", "/bunker.html"]:
        st, testate, _ = chiedi(p)
        check("P1", "pagina-riservata-protetta-%s" % p, st in (302, 303, 401, 403),
              "stato %d (200 = APERTA A CHIUNQUE!)" % st)


def p2_porte_aperte():
    st, _, corpo = chiedi("/api/trasparenza")
    check("P2", "trasparenza-risponde", st == 200, "stato %d" % st)
    if st == 200:
        try:
            d = json.loads(corpo)
            check("P2", "trasparenza-e-json", isinstance(d, dict))
            check("P2", "trasparenza-ha-i-due-scenari",
                  "scenario_nostro" in d and "scenario_ota" in d, str(list(d)[:6]))
        except Exception as e:
            check("P2", "trasparenza-json-valido", False, str(e))
    for rotta, atteso in [("/api/catalogo", (200,)), ("/api/health", (200,)),
                          ("/api/lingue", (200,)), ("/api/mappa", (200, 400)),
                          ("/api/domanda/conta", (200,)),
                          ("/api/legale/contratto-host?lang=it", (200,))]:
        st, _, corpo = chiedi(rotta)
        check("P2", "porta-pubblica-%s" % rotta.split("?")[0], st in atteso,
              "stato %d" % st)
        if rotta.startswith("/api/catalogo") and st == 200:
            try:
                d = json.loads(corpo)
                check("P2", "catalogo-e-una-struttura-valida",
                      isinstance(d, (list, dict)))
            except Exception as e:
                check("P2", "catalogo-json-valido", False, str(e))


def p3_porte_chiuse():
    riservate = [
        "/api/bunker/stato", "/api/bunker/prove_legali", "/api/bunker/scaglioni_host",
        "/api/bunker/costi_tecnici", "/api/bunker/marche_temporali",
        "/api/bunker/marca.tsr?id=1", "/api/bunker/export_legale",
        "/api/bunker/export_contabile", "/api/bunker/integrita", "/api/bunker/log",
        "/api/bunker/riconciliazione",
        "/api/admin/prenotazioni", "/api/admin/diagnosi", "/api/admin/audit",
        "/api/admin/verifiche",
    ]
    for p in riservate:
        st, _, corpo = chiedi(p)
        check("P3", "porta-chiusa-%s" % p, st in (401, 403), "stato %d" % st)
        check("P3", "niente-dati-nella-risposta-%s" % p, len(corpo) < 800,
              "%d byte trapelati" % len(corpo))
    # con una chiave/sessione inventata deve restare chiusa
    for testate in [{"X-Admin-Key": "inventata"}, {"X-Bunker-Session": "falsa"},
                    {"X-Bunker-Session": "a" * 200}]:
        st, _, _ = chiedi("/api/bunker/prove_legali", testate=dict(
            testate, **{"User-Agent": "V"}))
        check("P3", "chiave-inventata-respinta", st in (401, 403), "stato %d" % st)
    # le azioni che scrivono, senza credenziali
    for p in ["/api/bunker/marca_ora", "/api/admin/rimborso"]:
        st, _, _ = chiedi(p, metodo="POST")
        check("P3", "scrittura-riservata-bloccata-%s" % p,
              st in (401, 403, 404, 405), "stato %d" % st)


def p4_corazza():
    st, testate, _ = chiedi("/")
    check("P4", "home-200", st == 200, "stato %d" % st)
    csp = testate.get("Content-Security-Policy", "")
    check("P4", "csp-presente", bool(csp), "manca l'intestazione CSP")
    check("P4", "csp-blocca-oggetti-esterni",
          "default-src" in csp, csp[:120])
    hsts = testate.get("Strict-Transport-Security", "")
    check("P4", "hsts-presente", "max-age" in hsts, hsts or "assente")
    check("P4", "niente-sniffing", testate.get("X-Content-Type-Options", "").lower()
          == "nosniff", testate.get("X-Content-Type-Options", "assente"))
    # http deve mandare a https
    try:
        req = urllib.request.Request("http://bookinvip.com/",
                                     headers={"User-Agent": "V"})
        op = urllib.request.build_opener(_NoRedirect)
        try:
            with op.open(req, timeout=20) as r:
                st2, loc = r.status, r.headers.get("Location", "")
        except urllib.error.HTTPError as e:
            st2, loc = e.code, e.headers.get("Location", "")
        check("P4", "http-rimanda-a-https", st2 in (301, 302, 308)
              and loc.startswith("https://"), "stato %d loc %s" % (st2, loc))
    except Exception as e:
        check("P4", "http-raggiungibile", False, str(e))
    # certificato: quanto manca alla scadenza
    try:
        ctx = ssl.create_default_context()
        import socket
        with socket.create_connection(("bookinvip.com", 443), timeout=20) as s:
            with ctx.wrap_socket(s, server_hostname="bookinvip.com") as ss:
                cert = ss.getpeercert()
        scad = ssl.cert_time_to_seconds(cert["notAfter"])
        giorni = (scad - time.time()) / 86400.0
        check("P4", "certificato-non-in-scadenza", giorni > 15,
              "mancano %.1f giorni" % giorni)
        print("      certificato valido ancora %.0f giorni" % giorni)
    except Exception as e:
        check("P4", "certificato-leggibile", False, str(e))


def p5_coerenza():
    """Le percentuali dette al pubblico devono essere quelle vere del motore."""
    st, _, corpo = chiedi("/commissioni.html")
    testo = corpo.decode("utf-8", "replace") if st == 200 else ""
    check("P5", "pagina-commissioni-viva", st == 200 and len(testo) > 1000)
    if testo:
        # la tariffa tecnica 3% DEVE essere dichiarata (era la bugia scoperta il 20/07)
        check("P5", "tariffa-tecnica-3-dichiarata",
              re.search(r"3\s*%", testo) is not None,
              "la pagina non nomina il 3%")
        check("P5", "promo-zero-dichiarata",
              re.search(r"0\s*%", testo) is not None)
    st, _, _ = chiedi("/contratto-host.html")
    check("P5", "guscio-contratto-vivo", st == 200, "stato %d" % st)
    # la pagina e' un GUSCIO: il testo arriva dall'API, quindi si controlla LI'
    st, _, corpo = chiedi("/api/legale/contratto-host?lang=it")
    check("P5", "api-contratto-risponde", st == 200, "stato %d" % st)
    if st == 200:
        try:
            d = json.loads(corpo)
            testo = d.get("testo", "")
            check("P5", "contratto-completo", len(testo) > 5000, "%d caratteri" % len(testo))
            check("P5", "contratto-nomina-la-tariffa-tecnica-3",
                  re.search(r"3\s*%", testo) is not None, "ART. 6-BIS assente!")
            check("P5", "contratto-ha-lart-6-bis", "6-BIS" in testo)
            check("P5", "contratto-ha-le-clausole-vessatorie",
                  "1341" in testo and "1342" in testo)
            check("P5", "contratto-ha-versione-e-impronta",
                  bool(d.get("versione")) and len(d.get("doc_sha256") or "") == 64,
                  str(d.get("versione")))
            check("P5", "contratto-versione-aggiornata",
                  str(d.get("versione")) >= "2026-07-20", str(d.get("versione")))
        except Exception as e:
            check("P5", "contratto-json-valido", False, str(e))
    # anche in inglese
    st, _, corpo = chiedi("/api/legale/contratto-host?lang=en")
    if st == 200:
        try:
            t = json.loads(corpo).get("testo", "")
            check("P5", "contratto-inglese-nomina-il-3",
                  re.search(r"3\s*%", t) is not None, "versione EN senza 3%")
        except Exception:
            pass
    # coerenza fra pagina tariffe e API trasparenza
    st, _, corpo = chiedi("/api/trasparenza")
    if st == 200:
        try:
            d = json.loads(corpo)
            nostro = d.get("scenario_nostro", {})
            check("P5", "trasparenza-espone-il-psp", "psp_cents" in nostro,
                  str(list(nostro)[:6]))
        except Exception:
            pass


def p6_robustezza():
    """Input assurdi: nessuna risposta 500, nessun crash, niente tracce interne."""
    cattivi = [
        "/api/catalogo?citta=%00%01%02",
        "/api/catalogo?citta=%27%20OR%201%3D1--",
        "/api/catalogo?citta=%3Cscript%3Ealert(1)%3C/script%3E",
        "/api/catalogo?citta=" + "A" * 3000,
        "/api/dettaglio?slug=../../etc/passwd",
        "/api/dettaglio?slug=" + "%2e%2e%2f" * 40,
        "/voucher/" + "x" * 800,
        "/recensione/token-inventato",
        "/ricevuta/000",
        "/api/trasparenza?prezzo=-999999999",
        "/api/trasparenza?prezzo=abc",
        "/" + "a" * 1500,
    ]
    for p in cattivi:
        # nessun carattere di controllo grezzo: altrimenti urllib rifiuta PRIMA di
        # partire e il collaudo non prova niente (errore trovato il 2026-07-21)
        check("P6", "richiesta-inviabile",
              all(ord(c) > 32 for c in p),
              "input non percent-encoded: %s" % p[:50])
        st, _, corpo = chiedi(p)
        check("P6", "niente-errore-interno", st != 500,
              "%s -> 500" % p[:60])
        check("P6", "risposta-arriva", st != -1, "%s -> %s" % (p[:50], corpo[:60]))
        testo = corpo.decode("utf-8", "replace")[:4000].lower()
        for spia in ["traceback", "file \"/app", "sqlite3.", "stripe_secret",
                     "sk_live", "whsec_"]:
            check("P6", "niente-interni-esposti", spia not in testo,
                  "%s rivela '%s'" % (p[:40], spia))


if __name__ == "__main__":
    giri = 1
    for a in sys.argv:
        if a.startswith("--giri="):
            giri = int(a.split("=")[1])
    print("=" * 78)
    print("VERIFICA DI PRODUZIONE — %s  (%d giri, SOLA LETTURA)" % (BASE, giri))
    print("=" * 78)
    t0 = time.time()
    for g in range(1, giri + 1):
        print("\n-- giro %d di %d --" % (g, giri))
        for nome, fn in [("P1 pagine", p1_pagine), ("P2 porte aperte", p2_porte_aperte),
                         ("P3 porte chiuse", p3_porte_chiuse), ("P4 corazza", p4_corazza),
                         ("P5 coerenza tariffe", p5_coerenza),
                         ("P6 robustezza", p6_robustezza)]:
            prima = len(VIOL)
            fn()
            print("   %-22s %s" % (nome, "OK" if len(VIOL) == prima
                                   else "%d VIOLAZIONI" % (len(VIOL) - prima)))
    print("\n" + "=" * 78)
    print("controlli: %d in %.1fs" % (CONTA["n"], time.time() - t0))
    if VIOL:
        print("VIOLAZIONI: %d" % len(VIOL))
        visti = set()
        for v in VIOL:
            if v not in visti:
                print("  X", v)
                visti.add(v)
        sys.exit(1)
    print("VIOLAZIONI: 0 — il sito vero si comporta come deve")
    sys.exit(0)
