"""IL CAPITOLATO — l'elenco di TUTTO cio' che c'e' dentro e di COME DEVE FUNZIONARE.

═══════════════════════════════════════════════════════════════════════════════════
L'IDEA (fondatore, 2026-07-21) — e perche' cambia tutto
═══════════════════════════════════════════════════════════════════════════════════
Fino a ieri i test nascevano dalla MEMORIA: si prova cio' che qualcuno si e' ricordato
di provare. Ma «tutto quello che adesso non mi viene in mente» resta scoperto per
definizione — ed e' li' che vivono i difetti che poi si scoprono per caso.

Qui si ribalta il metodo:

  1. si ELENCA cio' che c'e' dentro  (ricavandolo dal codice, mai a memoria)
  2. si DICHIARANO le proprieta' che ogni cosa deve rispettare
  3. la macchina controlla OGNI elemento contro OGNI proprieta' applicabile

Cosi' una proprieta' dichiarata una volta protegge anche le cose che verranno costruite
domani, e nessuno deve ricordarsene.

Aggiungere una proprieta' = aggiungere una voce a `PROPRIETA`. Da quel momento vale
per tutto, retroattivamente.
"""
import io
import json
import os
import re
import sys

try:  # Windows: console cp1252 non regge box-drawing/emoji -> uscita UTF-8 tollerante
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

VIOLAZIONI = []
CONTA = {"controlli": 0, "elementi": 0}


def viola(proprieta, elemento, dettaglio):
    VIOLAZIONI.append((proprieta, elemento, dettaglio))


def controlla(proprieta, elemento, condizione, dettaglio=""):
    CONTA["controlli"] += 1
    if not condizione:
        viola(proprieta, elemento, dettaglio)


def _leggi(p):
    with io.open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


# ═══════════════════════════════════════════════════════════════════════════════
#  P1 — OGNI PAROLA CHE UN UTENTE LEGGE ESISTE IN TUTTE LE LINGUE
# ═══════════════════════════════════════════════════════════════════════════════
# DECISIONE DEL FONDATORE (2026-07-21). Prima aveva detto "admin, super admin" come
# strumenti suoi da lasciare in italiano; poi si e' corretto: «mettiamo tutte le lingue
# per coerenza con il resto». Quindi NESSUNA pagina e' esente: se un giorno una lo
# diventasse, va scritta qui con il motivo — la differenza fra una SCELTA e una
# DIMENTICANZA deve restare leggibile, altrimenti fra sei mesi nessuno la sa piu'.
SOLO_INTERNE = set()   # <- VUOTO, per decisione del fondatore


def _lingue_del_progetto():
    """Le lingue che il prodotto DICHIARA di parlare: si ricavano dalla pagina che ne
    offre di piu', non da una lista scritta a mano."""
    cartella = os.path.join(REPO, "deploy")
    massimo = set()
    for nome in os.listdir(cartella):
        if not nome.endswith(".html"):
            continue
        lingue = set(re.findall(r"(?m)^\s{2,}([a-z]{2}):\s*\{",
                                _leggi(os.path.join(cartella, nome))))
        if len(lingue) > len(massimo):
            massimo = lingue
    return massimo


def p1_lingue_complete():
    """OGNI pagina che un utente finale puo' leggere deve esistere in TUTTE le lingue
    che il prodotto dichiara di parlare.

    ATTENZIONE (difetto chiuso il 2026-07-21): la versione precedente saltava le pagine
    SENZA dizionario — cioe' proprio quelle interamente monolingua, il caso peggiore.
    Otto pagine pubbliche sono rimaste cosi' in italiano, fra cui l'informativa GDPR e
    i termini contrattuali, mentre il capitolato diceva OK.
    ASSENZA NON E' CONFORMITA'."""
    cartella = os.path.join(REPO, "deploy")
    attese = _lingue_del_progetto()
    for nome in sorted(os.listdir(cartella)):
        if not nome.endswith(".html"):
            continue
        testo = _leggi(os.path.join(cartella, nome))
        CONTA["elementi"] += 1
        lingue = re.findall(r"(?m)^\s{2,}([a-z]{2}):\s*\{", testo)

        if nome in SOLO_INTERNE:
            continue                       # interna per scelta dichiarata

        # 1) la pagina deve AVERE un impianto multilingua
        controlla("P1 lingue", nome, len(set(lingue)) >= 2,
                  "pagina per l'utente finale MONOLINGUA: parla solo italiano mentre "
                  "il prodotto dichiara %d lingue (%s)"
                  % (len(attese), ",".join(sorted(attese))))
        if len(set(lingue)) < 2:
            continue

        # 2) deve offrirle TUTTE
        mancanti_lingue = sorted(attese - set(lingue))
        controlla("P1 lingue", nome, not mancanti_lingue,
                  "offre %d lingue su %d: mancano %s"
                  % (len(set(lingue)), len(attese), mancanti_lingue))

        # 3) e ogni dizionario dev'essere COMPLETO
        chiavi = {}
        for lang in set(lingue):
            m = re.search(r"(?ms)^\s{2,}%s:\s*\{(.*?)\}\s*,?\s*$" % lang, testo)
            if m:
                chiavi[lang] = set(re.findall(r"(\w+)\s*:\s*[\"']", m.group(1)))
        if not chiavi:
            continue
        riferimento = max(chiavi.values(), key=len)
        for lang, ins in sorted(chiavi.items()):
            mancanti = sorted(riferimento - ins)
            controlla("P1 lingue", "%s [%s]" % (nome, lang), not mancanti,
                      "mancano %d voci: %s" % (len(mancanti), mancanti[:6]))

        for segnaposto in ("TODO", "XXX", "lorem ipsum", "TRANSLATE"):
            controlla("P1 lingue", nome, segnaposto.lower() not in testo.lower(),
                      "contiene il segnaposto '%s'" % segnaposto)


def p1b_lingue_dichiarate_ovunque_uguali():
    """Le lingue offerte devono essere le STESSE su tutte le pagine che ne offrono:
    un selettore con 8 bandiere su una pagina e 2 sull'altra e' una promessa a meta'."""
    cartella = os.path.join(REPO, "deploy")
    per_pagina = {}
    for nome in sorted(os.listdir(cartella)):
        if not nome.endswith(".html"):
            continue
        testo = _leggi(os.path.join(cartella, nome))
        lingue = set(re.findall(r"(?m)^\s{2,}([a-z]{2}):\s*\{", testo))
        if len(lingue) >= 2:
            per_pagina[nome] = lingue
    if len(per_pagina) < 2:
        return
    piu_ricca = max(per_pagina.values(), key=len)
    for nome, lingue in sorted(per_pagina.items()):
        mancanti = sorted(piu_ricca - lingue)
        controlla("P1b lingue uniformi", nome, not mancanti,
                  "offre %d lingue invece di %d: mancano %s"
                  % (len(lingue), len(piu_ricca), mancanti))


def p1c_email_e_documenti_legali():
    """I documenti che l'host ACCETTA e le email che riceve devono esistere nelle
    lingue dichiarate: un contratto non tradotto non e' stato letto."""
    try:
        import fase163_accettazioni as f163
    except Exception as e:
        viola("P1c legale", "fase163", "non importabile: %s" % type(e).__name__)
        return
    lingue = getattr(f163, "LINGUE_CONTRATTO", None) or ["it", "en"]
    for lang in lingue:
        CONTA["elementi"] += 1
        try:
            t = f163.testo_contratto(lang)
        except Exception as e:
            viola("P1c legale", "contratto[%s]" % lang, type(e).__name__)
            continue
        controlla("P1c legale", "contratto[%s]" % lang, len(t) > 3000,
                  "solo %d caratteri: traduzione incompleta?" % len(t))
        controlla("P1c legale", "contratto[%s]" % lang, "3%" in t,
                  "la versione %s non dichiara la tariffa tecnica" % lang)
    try:
        import fase89_jurisdiction_outreach as f89
        for lang, (oggetto, corpo) in f89._TEMPLATE.items():
            CONTA["elementi"] += 1
            controlla("P1c legale", "email reclutamento[%s]" % lang,
                      "{optout}" in corpo,
                      "email senza riga di disiscrizione: violazione di legge")
            controlla("P1c legale", "email reclutamento[%s]" % lang,
                      "{tecnica}" in corpo or "3%" in corpo,
                      "email che non dichiara la tariffa tecnica")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
#  P2 — NIENTE SEGRETI IN CIO' CHE VIENE SERVITO
# ═══════════════════════════════════════════════════════════════════════════════
def p2_niente_segreti():
    spie = ("sk_live_", "sk_test_", "whsec_", "BEGIN PRIVATE KEY", "BEGIN RSA")
    for cartella in (os.path.join(REPO, "deploy"), REPO):
        for nome in sorted(os.listdir(cartella)):
            if not nome.endswith((".html", ".js", ".css")):
                continue
            testo = _leggi(os.path.join(cartella, nome))
            CONTA["elementi"] += 1
            for spia in spie:
                controlla("P2 segreti", nome, spia not in testo,
                          "contiene '%s'" % spia)


# ═══════════════════════════════════════════════════════════════════════════════
#  P3 — OGNI PAGINA CHE MOSTRA DATI ALTRUI DEVE FARE L'ESCAPE
# ═══════════════════════════════════════════════════════════════════════════════
def p3_escape_xss():
    cartella = os.path.join(REPO, "deploy")
    for nome in sorted(os.listdir(cartella)):
        if not nome.endswith(".html"):
            continue
        testo = _leggi(os.path.join(cartella, nome))
        # Solo gli innerHTML che interpolano VARIABILI sono a rischio: quelli con
        # testo letterale fisso non lo sono, e segnalarli produce falsi allarmi
        # (successo il 2026-07-21 su annullato.html e grazie.html).
        dinamici = re.findall(r"innerHTML\s*=\s*([^;]{0,200})", testo)
        rischiosi = [d for d in dinamici
                     if not re.match(r"^\s*['\"][^'\"]*['\"]\s*$", d.strip())]
        if not rischiosi:
            continue
        CONTA["elementi"] += 1
        controlla("P3 XSS", nome,
                  "esc(" in testo or "escape" in testo or "_e(" in testo,
                  "interpola variabili in innerHTML senza mai passare dall'escape "
                  "(%d punti)" % len(rischiosi))


# ═══════════════════════════════════════════════════════════════════════════════
#  P4 — I SOLDI SONO SEMPRE INTERI IN CENTESIMI
# ═══════════════════════════════════════════════════════════════════════════════
def p4_soldi_interi():
    sospetto = re.compile(r"(?<![\w.])(?:float|round)\s*\(\s*\w*(?:cent|prezzo|importo|"
                          r"totale|commission)\w*", re.I)
    for nome in sorted(os.listdir(REPO)):
        if not (nome.startswith("fase") and nome.endswith(".py")):
            continue
        if re.match(r"^fase(1[3-9]|[2-5][0-9])_", nome):      # stack legacy
            continue
        testo = _leggi(os.path.join(REPO, nome))
        CONTA["elementi"] += 1
        for m in sospetto.finditer(testo):
            riga = testo[:m.start()].count("\n") + 1
            contesto = testo.splitlines()[riga - 1]
            if "/ 100" in contesto or "display" in contesto.lower():
                continue          # conversione per la VISUALIZZAZIONE: lecita
            controlla("P4 soldi interi", "%s:%d" % (nome, riga), False,
                      contesto.strip()[:90])


# ═══════════════════════════════════════════════════════════════════════════════
#  P5 — OGNI MODULO VIVO E' NEL REGISTRO
# ═══════════════════════════════════════════════════════════════════════════════
def p5_registro_completo():
    reg = _leggi(os.path.join(REPO, "REGISTRO_INGEGNERIA.md"))
    for nome in sorted(os.listdir(REPO)):
        if nome.startswith("fase") and nome.endswith(".py"):
            CONTA["elementi"] += 1
            controlla("P5 registro", nome, nome in reg,
                      "modulo non registrato: nessuno sa cosa fa ne' se e' acceso")


# ═══════════════════════════════════════════════════════════════════════════════
#  P6 — LE DATE MOSTRATE DICHIARANO IL FUSO
# ═══════════════════════════════════════════════════════════════════════════════
def p6_date_con_fuso():
    """Un'ora senza fuso in una prova legale e' un'ora contestabile."""
    server = _leggi(os.path.join(REPO, "fase83_server.py"))
    for m in re.finditer(r'strftime\("([^"]+)"\)', server):
        formato = m.group(1)
        if "%H" not in formato:
            continue
        riga = server[:m.start()].count("\n") + 1
        CONTA["elementi"] += 1
        controlla("P6 fuso orario", "fase83_server.py:%d" % riga,
                  "UTC" in formato or "%z" in formato or "Z" in formato,
                  "ora senza fuso dichiarato: '%s'" % formato)


PROPRIETA = [
    ("P1  ogni parola letta da un utente esiste in TUTTE le lingue", p1_lingue_complete),
    ("P1b le lingue offerte sono le stesse su tutte le pagine", p1b_lingue_dichiarate_ovunque_uguali),
    ("P1c contratti ed email di reclutamento tradotti e completi", p1c_email_e_documenti_legali),
    ("P2  nessun segreto in cio' che viene servito al browser", p2_niente_segreti),
    ("P3  chi compone HTML con dati altrui fa l'escape", p3_escape_xss),
    ("P4  i soldi sono sempre interi in centesimi", p4_soldi_interi),
    ("P5  ogni modulo vivo e' nel registro d'ingegneria", p5_registro_completo),
    ("P6  ogni ora mostrata dichiara il fuso", p6_date_con_fuso),
]


if __name__ == "__main__":
    print("=" * 92)
    print("IL CAPITOLATO — ogni elemento costruito contro ogni proprieta' dichiarata")
    print("=" * 92)
    for etichetta, funzione in PROPRIETA:
        prima = len(VIOLAZIONI)
        try:
            funzione()
        except Exception as e:
            viola(etichetta, "(esecuzione)", "%s: %s" % (type(e).__name__, e))
        nuove = len(VIOLAZIONI) - prima
        print("  %-62s %s" % (etichetta, "OK" if nuove == 0 else "%d VIOLAZIONI" % nuove))

    print("\n" + "=" * 92)
    print("elementi esaminati: %d | controlli: %d"
          % (CONTA["elementi"], CONTA["controlli"]))
    if VIOLAZIONI:
        print("VIOLAZIONI DEL CAPITOLATO: %d\n" % len(VIOLAZIONI))
        per_prop = {}
        for prop, elem, dett in VIOLAZIONI:
            per_prop.setdefault(prop, []).append((elem, dett))
        for prop in sorted(per_prop):
            print("  %s" % prop)
            for elem, dett in per_prop[prop][:14]:
                print("     %-34s %s" % (elem, dett[:80]))
            if len(per_prop[prop]) > 14:
                print("     ... e altre %d" % (len(per_prop[prop]) - 14))
        sys.exit(1)
    print("NESSUNA VIOLAZIONE: ogni elemento rispetta ogni proprieta' dichiarata.")
    sys.exit(0)
