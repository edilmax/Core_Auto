"""AUDIT DI COERENZA ASSOLUTA su percentuali / commissioni / tariffa tecnica.

MACRO: la VERITA' si legge DAL CODICE (non si assume): default di PAGAMENTO_BPS e
COMMISSIONE_BPS in main_casavip.py + costanti della rampa e del canale diretto in fase98.
MICRO: scansione di OGNI file del progetto (py/html/md/txt/json/conf/yml) per ogni riga che
contenga una percentuale INSIEME a una parola-chiave di costo; ogni cifra viene confrontata
con la verita'. Segnala testi orfani, refusi vecchi e file dimenticati.

Uscita: elenco delle ANOMALIE (file:riga) + verdetto. 0 anomalie = coerenza strutturale.
"""
import io
import os
import re
import sys

try:  # Windows: console cp1252 non regge box-drawing/emoji -> uscita UTF-8 tollerante
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ESCLUDI_DIR = {".git", "__pycache__", "data", "node_modules", "venv", ".venv",
               "certbot", "uploads", "backup"}
ESTENSIONI = (".py", ".html", ".md", ".txt", ".json", ".conf", ".yml", ".yaml", ".js")

# ── 1) LA VERITA', letta dal codice ──────────────────────────────────────────
def leggi(p):
    return io.open(os.path.join(REPO, p), encoding="utf-8", errors="replace").read()


main = leggi("main_casavip.py")
f98 = leggi("fase98_policy_commissione.py")


def _num(src, pat, default=None):
    m = re.search(pat, src)
    return int(m.group(1)) if m else default


PSP = _num(main, r'PAGAMENTO_BPS["\']\s*,\s*["\'](\d+)["\']')
COMM = _num(main, r'COMMISSIONE_BPS["\']\s*,\s*["\'](\d+)["\']')
DIRETTO = _num(f98, r'BPS_DIRETTO\s*=\s*(\d+)')
L_GRATIS = _num(f98, r'LANCIO_GIORNI_GRATIS\s*=\s*(\d+)')
L_F1 = _num(f98, r'LANCIO_BPS_FASE1\s*=\s*(\d+)')
L_GG1 = _num(f98, r'LANCIO_GIORNI_FASE1\s*=\s*(\d+)')
L_REG = _num(f98, r'LANCIO_BPS_REGIME\s*=\s*(\d+)')
PROMO = "true" in (re.search(r'PROMO_LANCIO["\']\s*,\s*["\'](\w+)["\']', main) or
                   [None, "true"])[1].lower()

TECNICA = PSP // 100                      # 3
NOSTRE_COMM = {0, DIRETTO // 100, L_F1 // 100, L_REG // 100, COMM // 100}   # {0,5,8,10}

# ── 2) vocabolario ───────────────────────────────────────────────────────────
KW_TECNICA = re.compile(r"tariffa tecnica|costo carta|costo di pagamento|costo del pagamento|"
                        r"technical fee|payment fee|costo_pagamento|psp_bps|PAGAMENTO_BPS|"
                        r"tarifa t|frais techniques|technische Geb|taxa t|技術|技术", re.I)
KW_COMM = re.compile(r"commission|commissione|commissioni|comisi|Provision|comiss|手数料|佣金", re.I)
# contesti in cui QUALSIASI percentuale e' legittima (non parla di noi)
KW_ALTRUI = re.compile(r"booking|airbnb|vrbo|expedia|agoda|tripadvisor|hostelworld|OTA|"
                       r"coloss|concorren|mercato|competitor|homeaway|market average", re.I)
# percentuali nostre legittime NON commissionali (penali, sconti, politiche, IVA…)
KW_ALTRO_NOSTRO = re.compile(r"penale|penalit|cancellazion|rimbors|sconto|non rimborsabile|"
                             r"soggiorno lungo|IVA|VAT|tassa|occupazione|riempimento|"
                             r"stagional|dynamic|prezzo dinamico|refund|discount|deposito|"
                             r"acconto|caparra|maggiorazion|coverage|width|height|opacity|"
                             r"progress|barra|grafico|chart", re.I)
PERC = re.compile(r"(\d{1,3})(?:[.,]\d+)?\s?%")

anomalie = []
esaminate = 0
righe_rilevanti = 0


def file_da_scansionare():
    for radice, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in ESCLUDI_DIR]
        for f in files:
            if f.endswith(ESTENSIONI):
                yield os.path.join(radice, f)


# I RAPPORTI PRODOTTI DA QUESTO STESSO AUDIT non vanno scansionati: contengono le righe
# che ha appena segnalato, quindi al giro dopo le ritroverebbe "nuove" — un cane che si
# morde la coda, scoperto il 2026-07-21. Si versiona lo strumento, non la sua uscita.
_MIE_USCITE = ("rapporto_coerenza.txt", "baseline_tariffe.txt")

for percorso in file_da_scansionare():
    if os.path.basename(percorso) in _MIE_USCITE:
        continue
    rel = os.path.relpath(percorso, REPO)
    try:
        testo = io.open(percorso, encoding="utf-8", errors="replace").read()
    except Exception:
        continue
    esaminate += 1
    for n, riga in enumerate(testo.splitlines(), 1):
        if not PERC.search(riga):
            continue
        tec = bool(KW_TECNICA.search(riga))
        com = bool(KW_COMM.search(riga))
        if not (tec or com):
            continue
        righe_rilevanti += 1
        if KW_ALTRUI.search(riga):            # parla dei concorrenti: qualsiasi cifra ok
            continue
        cifre = {int(x) for x in PERC.findall(riga)}
        # CSS/markup con percentuali di larghezza dentro righe che citano commissioni
        cifre = {c for c in cifre if c <= 100}
        if tec:
            fuori = {c for c in cifre if c != TECNICA and c not in NOSTRE_COMM and c != 100}
            if fuori and not KW_ALTRO_NOSTRO.search(riga):
                anomalie.append((rel, n, "tariffa tecnica != %d%%" % TECNICA,
                                 sorted(fuori), riga.strip()[:130]))
        elif com:
            fuori = {c for c in cifre
                     if c not in NOSTRE_COMM and c != TECNICA and c != 100}
            if fuori and not KW_ALTRO_NOSTRO.search(riga):
                anomalie.append((rel, n, "commissione fuori da %s" % sorted(NOSTRE_COMM),
                                 sorted(fuori), riga.strip()[:130]))

OUT=[]
def print(*a, **k):
    OUT.append(" ".join(str(x) for x in a))
print("=" * 78)
print("VERITA' LETTA DAL CODICE")
print("  tariffa tecnica (PAGAMENTO_BPS) : %d bps = %d%%" % (PSP, TECNICA))
print("  commissione regime (COMMISSIONE_BPS): %d bps = %d%%" % (COMM, COMM // 100))
print("  canale diretto (BPS_DIRETTO)    : %d bps = %d%%" % (DIRETTO, DIRETTO // 100))
print("  rampa lancio: 0%% per %d giorni -> %d%% fino a %d giorni -> %d%% a regime  (attiva: %s)"
      % (L_GRATIS, L_F1 // 100, L_GG1, L_REG // 100, "SI" if PROMO else "NO"))
print("  percentuali NOSTRE ammesse: %s + tecnica %d%%" % (sorted(NOSTRE_COMM), TECNICA))
print("-" * 78)
print("SCANSIONE: %d file esaminati, %d righe con percentuale+parola-chiave di costo"
      % (esaminate, righe_rilevanti))
if not anomalie:
    print("ANOMALIE: NESSUNA - coerenza strutturale confermata")
else:
    print("ANOMALIE TROVATE: %d" % len(anomalie))
    for rel, n, motivo, cifre, riga in anomalie:
        print("  %s:%d  [%s] cifre=%s" % (rel, n, motivo, cifre))
        print("      %s" % riga)
print("=" * 78)

_dest = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rapporto_coerenza.txt")
# ── BASELINE: le righe gia' ESAMINATE UNA PER UNA e giudicate legittime ──────
# Il 2026-07-21 tutte le segnalazioni sono state aperte e lette: sono descrizioni di
# cifre SUPERATE (_archivio, CLAUDE.md), una PENALE contrattuale ("Commissione + 50%"),
# il costo reale di Stripe in un commento (~2.9%), il racconto di un bug passato, il
# confronto con i colossi (15%) e un test del TETTO del 20% sulla tariffa tecnica.
# Nessuna e' un errore. Registrandole, l'audit smette di essere un elenco da rileggere
# ogni volta e diventa un GUARDIANO: se domani compare una cifra NUOVA, esce rosso.
_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baseline_tariffe.txt")


def _chiave(rel, riga):
    """file + impronta del CONTENUTO. Non il numero di riga: quello slitta appena si
    aggiunge testo piu' in alto, e la guardia darebbe falsi allarmi a ogni modifica di
    documentazione (successo davvero il 2026-07-21). Lo spazio viene normalizzato:
    una riformattazione non e' una cifra nuova."""
    import hashlib
    normale = " ".join(str(riga).split())
    return "%s|%s" % (rel.replace("\\", "/"),
                      hashlib.sha1(normale.encode("utf-8")).hexdigest()[:12])


_ora = sorted(_chiave(rel, r) for rel, _n, _m, _c, r in anomalie)
if os.path.exists(_BASE):
    _note = set(io.open(_BASE, encoding="utf-8").read().split(chr(10))) - {""}
    _primo_giro = False
else:
    # FINTO VERDE CHIUSO (2026-07-21). Prima la baseline si creava DA SOLA al primo
    # giro accettando in silenzio tutto cio' che trovava — comprese eventuali cifre
    # sbagliate — e l'audit usciva VERDE. Chi clonava il progetto (o cancellava il
    # file) otteneva una guardia che approvava lo stato di fatto, qualunque fosse.
    # Ora la si crea ma si esce ROSSI, dicendo che va LETTA da un essere umano.
    io.open(_BASE, "w", encoding="utf-8").write(chr(10).join(_ora))
    _note = set(_ora)
    _primo_giro = True
_nuove = [x for x in _ora if x not in _note]
_sparite = [x for x in _note if x not in _ora]
print("-" * 78)
print("CONFRONTO CON LA BASELINE (righe gia' esaminate e giudicate legittime: %d)"
      % len(_note))
print("  (la chiave e' file + contenuto della riga: spostarla non fa rumore,"
      " cambiarne le cifre si')")
if _nuove:
    print("  CIFRE NUOVE DA ESAMINARE: %d" % len(_nuove))
    _per_chiave = {_chiave(rel, r): (rel, n, r) for rel, n, _m, _c, r in anomalie}
    for x in _nuove:
        rel, n, riga = _per_chiave.get(x, ("?", 0, x))
        print("    -> %s:%d" % (rel, n))
        print("       %s" % str(riga)[:120])
else:
    print("  nessuna cifra nuova")
if _sparite:
    print("  righe sparite (testo cambiato o file rimosso): %d" % len(_sparite))
if _primo_giro:
    print("  PRIMA ESECUZIONE: la baseline non esisteva ed e' stata creata con le %d"
          % len(_ora))
    print("  righe trovate ORA. NON e' un'approvazione: vanno LETTE una per una prima")
    print("  di fidarsi di questo verde. Riesegui dopo averle esaminate.")
print("=" * 78)

io.open(_dest, "w", encoding="utf-8").write(chr(10).join(OUT))
sys.exit(1 if (_nuove or _primo_giro) else 0)
