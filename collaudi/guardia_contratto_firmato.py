#!/usr/bin/env python3
"""A1 — L'ETICHETTA, IL LINK E IL DOCUMENTO FIRMATO DEVONO ESSERE LO STESSO DOCUMENTO.

Il difetto che questa guardia impedisce di far tornare (misurato il 2026-08-25):
  · `fase83_server.py:1617` mostrava «Contratto Host» su un link a `/termini.html`
    (documento `termini`, motore fase185) mentre `:1631-1634` spediva l'impronta del
    Contratto Host -> la prova HMAC nomina un documento che l'host non ha mai visto;
  · `deploy/host.html:97,136` faceva l'errore speculare: link giusto, etichetta i18n
    `termini` («Termini»/«Terms»/«条款»).

Nessuna guardia esistente vede questa specie: `audit_coerenza_tariffe` guarda le CIFRE,
`coverage_pannelli` guarda che il bottone chiami una funzione VIVA — e qui href e
funzione erano entrambi vivi. La domanda che mancava non e' «il link funziona?» ma
«il link porta al documento di cui si firma l'impronta?».

DENOMINATORE DICHIARATO a ogni giro: quante caselle d'accettazione sono state trovate
e quante controllate. Se il numero trovato scende sotto quelle note, e' ROSSO: significa
che una casella e' stata spostata e la guardia ha smesso di guardarla (regola: ogni
guardia dichiara il suo denominatore).

Uscita: 0 = tutte le terne coerenti · 1 = almeno una divergenza · 2 = denominatore calato.
"""
import os
import re
import sys

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)

# Caselle note: (descrizione, file, come si estrae la terna). Il numero e' il DENOMINATORE.
CASELLE_ATTESE = 3          # gate server + host.html registrazione + host.html riaccettazione


def _leggi(rel):
    with open(os.path.join(RADICE, rel), encoding="utf-8") as f:
        return f.read()


def _errore(lista, testo):
    lista.append(testo)


def main():
    from fase163_accettazioni import (PAGINA_CONTRATTO, ETICHETTA_CONTRATTO,
                                      DOCUMENTO_HOST, doc_sha256, link_contratto,
                                      lingua_contratto_servita)
    errori, trovate = [], 0

    # ── 1. IL GATE DEL SERVER (fase83_server.pagina_login_gate) ──────────────
    # Si costruisce la pagina VERA, non si legge il sorgente: cosi' la guardia misura
    # cio' che l'host vede, non cio' che il codice sembra dire.
    from fase83_server import pagina_login_gate
    for lang in ("it", "en", "de", "ja"):
        html = pagina_login_gate("host", "", lang)
        m = re.search(r'id="c1"[^>]*>\s*[^<]*<a href="([^"]+)"[^>]*>([^<]+)</a>', html)
        if not m:
            _errore(errori, "gate/%s: casella c1 non trovata (spostata? la guardia e' cieca)" % lang)
            continue
        trovate += 1 if lang == "it" else 0
        href, etichetta = m.group(1), m.group(2).strip()
        atteso_href = link_contratto(lang)
        if href != atteso_href:
            _errore(errori, "gate/%s: la casella linka %r, il documento firmato e' a %r"
                            % (lang, href, atteso_href))
        if etichetta != ETICHETTA_CONTRATTO.get(lingua_contratto_servita(lang),
                                                ETICHETTA_CONTRATTO["en"]) \
                and etichetta not in ETICHETTA_CONTRATTO.values():
            _errore(errori, "gate/%s: etichetta %r non e' il nome del documento firmato"
                            % (lang, etichetta))
        # l'impronta spedita dev'essere QUELLA del documento linkato
        if doc_sha256() not in html:
            _errore(errori, "gate/%s: la pagina non spedisce l'impronta viva del contratto" % lang)
        # e nessuna casella d'accettazione puo' puntare a un ALTRO documento legale
        if "/termini.html" in html and "id=\"c1\"" in html:
            seg = html.split('id="c1"', 1)[1].split("</label>", 1)[0]
            if "/termini.html" in seg:
                _errore(errori, "gate/%s: la casella del contratto punta ai Termini di servizio" % lang)

    # ── 2. LE CASELLE DI deploy/host.html ────────────────────────────────────
    host = _leggi("deploy/host.html")
    ancore = re.findall(r'<a href="(/[a-z0-9\-]+\.html)"[^>]*data-i18n="([a-z_]+)"[^>]*>', host)
    for href, chiave in ancore:
        if href != PAGINA_CONTRATTO:
            continue
        trovate += 1
        # la chiave i18n con cui l'etichetta viene RISCRITTA a runtime deve nominare
        # il contratto, non i Termini: `applica()` sovrascrive il testo dell'HTML.
        if chiave != "contratto":
            _errore(errori, "host.html: link al contratto con etichetta i18n %r "
                            "(a schermo diventa il nome di un altro documento)" % chiave)
    # la chiave dev'esistere in TUTTE le lingue del pannello, altrimenti il fallback
    # rimette in campo il nome sbagliato
    for lang in ("it", "en", "es", "fr", "de", "pt", "ja", "zh"):
        if not re.search(r'\n  %s:\{.*contratto:"' % lang, host):
            _errore(errori, "host.html: manca la chiave i18n 'contratto' in %r" % lang)
    # e il link dev'essere riscritto con la lingua servita
    if "a.lk-contratto" not in host or "/contratto-host.html?lang=" not in host:
        _errore(errori, "host.html: il link al contratto non porta la lingua servita")

    # ── 3. IL RIPIEGO DELLA PAGINA = QUELLO DEL SERVER ───────────────────────
    pag = _leggi("deploy/contratto-host.html")
    if lingua_contratto_servita("de") == "en" and re.search(r"b==='en'\?'en':'it'", pag):
        _errore(errori, "contratto-host.html: ripiega su 'it', il server su 'en' -> "
                        "l'host legge una lingua e la prova ne registra un'altra")

    # ── DENOMINATORE ─────────────────────────────────────────────────────────
    print("caselle d'accettazione trovate: %d (attese %d)" % (trovate, CASELLE_ATTESE))
    print("documento firmato: %s  impronta: %s" % (DOCUMENTO_HOST, doc_sha256()[:16]))
    if trovate < CASELLE_ATTESE:
        print("ROSSO: denominatore calato -> una casella non e' piu' sotto guardia")
        return 2
    for e in errori:
        print("ROSSO: " + e)
    print("VERDE: etichetta, link e documento firmato coincidono" if not errori else
          "ROSSO: %d divergenze" % len(errori))
    return 1 if errori else 0


if __name__ == "__main__":
    sys.exit(main())
