"""AUDIT MILLIMETRICO dei 5 documenti ufficiali contro il MOTORE REALE.
Ogni affermazione verificabile del README (e dei fratelli) viene confrontata con il codice:
conteggi, percorsi, moduli, rotte, variabili d'ambiente, tariffe, logica dei consensi.
Una sola discrepanza = STOP.
"""
import datetime
import io
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

DIFF = []


def ok(voce, esito, atteso="", trovato=""):
    if esito:
        print("  [OK] %s" % voce)
    else:
        DIFF.append((voce, atteso, trovato))
        print("  [!!] %s   atteso=%s trovato=%s" % (voce, atteso, trovato))


def leggi(p):
    return io.open(os.path.join(REPO, p), encoding="utf-8").read()


R = leggi("README.md")
MAIN = leggi("main_casavip.py")
F98 = leggi("fase98_policy_commissione.py")
F83 = leggi("fase83_server.py")
F163 = leggi("fase163_accettazioni.py")
F59 = leggi("fase59_concierge.py")

print("=" * 76)
print("1) STRUTTURA E CONTEGGI DICHIARATI NEL README")
print("=" * 76)
n_fase = len([f for f in os.listdir(REPO) if re.match(r"^fase\d+.*\.py$", f)])
n_test = len([f for f in os.listdir(REPO) if f.startswith("test_") and f.endswith(".py")])
n_html = len([f for f in os.listdir(os.path.join(REPO, "deploy")) if f.endswith(".html")])
ok("moduli fase*.py dichiarati", "%d moduli" % n_fase in R, "%d moduli" % n_fase,
   (re.search(r"(\d+) moduli del motore", R) or ["", "?"])[1])
ok("file di test dichiarati", "%d file di test" % n_test in R, "%d file di test" % n_test,
   (re.search(r"(\d+) file di test", R) or ["", "?"])[1])
ok("pagine deploy dichiarate", "%d pagine" % n_html in R, "%d pagine" % n_html,
   (re.search(r"(\d+) pagine", R) or ["", "?"])[1])

# Ogni percorso citato nell'albero deve esistere -- MA SOLO QUELLI CHE STANNO DAVVERO NEL
# REPOSITORY. `data/` e `contatti/` sono esclusi apposta da .gitignore (righe 13 e 6):
# pretendere che ESISTANO faceva passare l'audit sul computer di chi lavora, dove ci sono, e
# cadere in una COPIA PULITA, dove git non li porta. Trovato il 2026-08-14 dalla CI su Linux
# il giorno in cui questo audit e' entrato nella suite -- prima non lo eseguiva nessuno.
# ⛔ `data` per giunta taceva per FORTUNA, non per costruzione: qualche test la crea durante
# il giro, quindi l'esito dipendeva dall'ORDINE dei test. Regola ferrea 8 in forma pura.
for percorso in ("main_casavip.py", "deploy/index.html", "deploy/host.html",
                 "deploy/admin.html", "deploy/bunker.html", "deploy/commissioni.html",
                 "deploy/termini.html", "deploy/privacy.html", "deploy/contratto-host.html",
                 "deploy/app.js", "legale", "_archivio",
                 "Dockerfile.casavip", "docker-compose.casavip.yml"):
    ok("esiste il percorso citato: %s" % percorso,
       os.path.exists(os.path.join(REPO, percorso)))

# ...e i due che stanno FUORI si controllano AL CONTRARIO: l'esclusione dev'esserci ancora.
# Non e' pignoleria: `contatti/` sono elenchi di persone vere e questo repository e' PUBBLICO
# (lo e' per avere CodeQL gratis). Se qualcuno togliesse quella riga da .gitignore, quei dati
# finirebbero online al primo `git add -A`, e nessuno se ne accorgerebbe. Cosi' invece
# diventa rosso lo stesso giorno. Un controllo che non poteva passare e' diventato una guardia.
GITIGNORE = leggi(".gitignore")
for percorso in ("data", "contatti"):
    ok("resta FUORI dal repository, come deve: %s" % percorso,
       ("%s/" % percorso) in GITIGNORE,
       "%s/ elencata in .gitignore" % percorso,
       "ASSENTE: finirebbe online al primo `git add -A`")

print()
print("=" * 76)
print("2) MODULI CITATI NEL README = MODULI CHE ESISTONO")
print("=" * 76)
citati = sorted(set(re.findall(r"`?fase(\d+)`?", R)))
for num in citati:
    esiste = any(re.match(r"^fase%s_.*\.py$" % num, f) for f in os.listdir(REPO))
    ok("fase%s citata esiste" % num, esiste)

print()
print("=" * 76)
print("3) TARIFFE: README == COSTANTI DEL MOTORE")
print("=" * 76)
psp = int(re.search(r'PAGAMENTO_BPS["\']\s*,\s*["\'](\d+)["\']', MAIN).group(1))
fisso = int(re.search(r'PAGAMENTO_FISSO_CENTS["\']\s*,\s*["\'](\d+)["\']', MAIN).group(1))
comm = int(re.search(r'COMMISSIONE_BPS["\']\s*,\s*["\'](\d+)["\']', MAIN).group(1))
promo_def = re.search(r'PROMO_LANCIO["\']\s*,\s*["\'](\w+)["\']', MAIN).group(1)
diretto = int(re.search(r"BPS_DIRETTO\s*=\s*(\d+)", F98).group(1))
gratis = int(re.search(r"LANCIO_GIORNI_GRATIS\s*=\s*(\d+)", F98).group(1))
f1 = int(re.search(r"LANCIO_BPS_FASE1\s*=\s*(\d+)", F98).group(1))
gg1 = int(re.search(r"LANCIO_GIORNI_FASE1\s*=\s*(\d+)", F98).group(1))
reg = int(re.search(r"LANCIO_BPS_REGIME\s*=\s*(\d+)", F98).group(1))

frase_tariffa = "tariffa tecnica del %d%% + 0,%02d €" % (psp // 100, fisso)
ok("tariffa tecnica dichiarata, quota fissa compresa", frase_tariffa in R, frase_tariffa,
   (re.search(r"tariffa tecnica del [^\n*]+", R) or ["?"])[0])
ok("PAGAMENTO_BPS=%d citato" % psp, "PAGAMENTO_BPS=%d" % psp in R, "PAGAMENTO_BPS=%d" % psp)
ok("primi %d giorni -> 0%%" % gratis, ("primi **%d giorni**" % gratis) in R and "**0%**" in R)
ok("fino a 1 anno -> %d%%" % (f1 // 100), "**%d%%**" % (f1 // 100) in R)
ok("regime -> %d%%" % (reg // 100), "**%d%%**" % (reg // 100) in R)
ok("link diretto -> %d%%" % (diretto // 100), "**%d%%**" % (diretto // 100) in R)
ok("COMMISSIONE_BPS default %d citato" % comm, "`%d` = %d%%" % (comm, comm // 100) in R)
ok("PROMO_LANCIO default '%s' dichiarato attivo" % promo_def,
   promo_def == "true" and "attiva in produzione" in R.lower())
ok("1 anno = %d giorni (coerente col motore)" % gg1, gg1 == 365)
ok("identita' matematica presente",
   "prezzo_ospite = netto_host + commissione + tariffa_tecnica" in R)
ok("il 3%% e' dichiarato SEMPRE dovuto", "SEMPRE dovuta" in R and
   "anche quando la commissione è 0%" in R)
ok("ospite paga 0%", "l'ospite paga sempre **0%**" in R or "ospite paga sempre **0%**" in R)

# l'esempio numerico del README deve tornare col motore -- QUOTA FISSA COMPRESA.
# Nulla di cablato qui: se il motore cambia, cambia l'atteso e il README deve seguirlo.
# Che quei valori non scendano SOTTO COSTO non lo giudica questo audit, ma
# test_fase59_costo_pagamento.test_la_tariffa_tecnica_copre_la_carta_PEGGIORE_a_OGNI_importo.
calc0 = 10000 - 0 - (10000 * psp // 10000) - fisso                          # promo: commissione 0%
calcreg = 10000 - (10000 * reg // 10000) - (10000 * psp // 10000) - fisso   # a regime
e0 = "%d,%02d" % (calc0 // 100, calc0 % 100)
ereg = "%d,%02d" % (calcreg // 100, calcreg % 100)
esempio_ok = (("l'host incassa %s €" % e0) in R) and (("l'host incassa %s €" % ereg) in R)
ok("esempio 100 EUR: host %s (promo) e %s (regime)" % (e0, ereg), esempio_ok,
   "%s/%s" % (e0, ereg),
   "/".join(re.findall(r"l'host incassa ([\d,]+) €", R)) or "?")

print()
print("=" * 76)
print("4) CONSENSI: README == IMPLEMENTAZIONE")
print("=" * 76)
ok("3 consensi separati dichiarati",
   "Contratto Host" in R and "1341-1342" in R and "GDPR" in R)
ok("pulsante bloccato dichiarato", "grigio e non cliccabile" in R)
ok("rifiuto server 422 dichiarato", "422" in R and "consensi_mancanti" in R)
ok("firma HMAC-SHA256 dichiarata", "HMAC-SHA256" in R)
ok("due righe di prova dichiarate", "**due righe**" in R)
ok("ri-accettazione dichiarata", "/api/host/contratto_stato" in R and "/api/host/riaccetta" in R)
# ...e ora la verifica sul CODICE
ok("il server rifiuta davvero (consensi_mancanti in fase83)", "consensi_mancanti" in F83)
ok("controlla tutte e 3 le spunte", all(k in F83 for k in
   ("accetta_termini", "accetta_clausole", "accetta_privacy")))
ok("privacy e' un documento separato (fase163)", "DOCUMENTO_PRIVACY" in F163)
ok("firma HMAC-SHA256 nel registro", "hashlib.sha256" in F163 and "hmac.new" in F163)
ok("rotta contratto_stato cablata", '"/api/host/contratto_stato"' in F83)
ok("rotta riaccetta cablata", '"/api/host/riaccetta"' in F83)
html = leggi("deploy/host.html")
ok("3 caselle nel modulo di registrazione",
   all(('id="%s"' % i) in html for i in ("au_terms", "au_clausole", "au_privacy")))
ok("3 caselle nella ri-accettazione",
   all(('id="%s"' % i) in html for i in ("ra_terms", "ra_clausole", "ra_privacy")))
ok("caselle NON pre-selezionate (nessun 'checked')",
   not re.search(r'id="(au|ra)_(terms|clausole|privacy)"[^>]*\bchecked\b', html))
ok("tasti nascono disabilitati",
   bool(re.search(r'id="btnRegister"[^>]*disabled', html)) and
   bool(re.search(r'id="btnRiaccetta"[^>]*disabled', html)))

print()
print("=" * 76)
print("5) VARIABILI D'AMBIENTE CITATE = VARIABILI LETTE DAL CODICE")
print("=" * 76)
for var in ("COMMISSIONE_BPS", "PAGAMENTO_BPS", "PROMO_LANCIO", "STRIPE_SECRET_KEY",
            "STRIPE_WEBHOOK_SECRET", "HOST_KEY", "ADMIN_KEY", "BUNKER_PASSWORD"):
    ok("%s letta dal codice" % var, var in MAIN or var in F83)

print()
print("=" * 76)
print("6) RADICE BLINDATA E COERENZA FRA I 5 DOCUMENTI")
print("=" * 76)
md = sorted(f for f in os.listdir(REPO) if f.endswith(".md"))
ok("in radice esattamente 5 .md ufficiali",
   md == ["CLAUDE.md", "DEPLOY.md", "README.md", "REGISTRO_INGEGNERIA.md", "RIPRENDI_QUI.md"],
   "5 ufficiali", str(md))
ok("archivio con avviso", os.path.isfile(os.path.join(REPO, "_archivio", "LEGGIMI-ARCHIVIO.md")))
CL = leggi("CLAUDE.md")
ok("CLAUDE.md ha la REGOLA ZERO", "REGOLA ZERO" in CL)
ok("CLAUDE.md vieta nuovi .md", "VIETATO CREARE NUOVI FILE" in CL)
ok("CLAUDE.md elenca gli stessi 5 documenti",
   all(x in CL for x in ("README.md", "REGISTRO_INGEGNERIA.md", "RIPRENDI_QUI.md",
                         "DEPLOY.md", "CLAUDE.md")))
ok("CLAUDE.md riporta le stesse tariffe del README",
   ("**%d%%**" % (reg // 100)) in CL and ("**%d%%**" % (psp // 100)) in CL
   and ("**%d**" % gratis) in CL or ("%d giorni" % gratis) in CL)
ok("CLAUDE.md dice che _archivio non si segue", "_archivio" in CL and "non si segue" in CL.lower())
RQ = leggi("RIPRENDI_QUI.md")
# ⛔ RIPARATA IL 2026-08-22, e il difetto era nel CONTROLLO, non nel documento.
#    Diceva:  ok("RIPRENDI_QUI cita il lavoro di oggi", "2026-07-20" in RQ)
#    Si chiamava «di oggi» e cercava una data FISSA del 20 luglio: sarebbe rimasta verde per
#    sempre mentre il documento invecchiava, ed era esattamente la malattia che questo audit
#    esiste per trovare -- dentro l'audit stesso. Adesso guarda la data PIU' RECENTE citata
#    e pretende che non sia vecchia di piu' di 30 giorni: non c'e' niente da aggiornare a
#    mano, e il controllo non puo' diventare falso restando fermo.
_date = sorted(re.findall(r"20\d\d-\d\d-\d\d", RQ))
if _date:
    _ultima = datetime.datetime.strptime(_date[-1], "%Y-%m-%d").date()
    _giorni = (datetime.date.today() - _ultima).days
    ok("RIPRENDI_QUI cita lavoro recente (data piu' recente: %s, %d giorni fa)"
       % (_date[-1], _giorni), -1 <= _giorni <= 30)
else:
    ok("RIPRENDI_QUI cita lavoro recente (nessuna data nel documento)", False)
DP = leggi("DEPLOY.md")
ok("DEPLOY.md descrive il deploy rm-first", "rm -f" in DP or "rm-first" in DP)

print()
print("=" * 76)
if not DIFF:
    print("VERDETTO: 0 DISCREPANZE — i 5 documenti rispecchiano il motore al millimetro")
else:
    print("VERDETTO: %d DISCREPANZE — STOP" % len(DIFF))
    for v, a, t in DIFF:
        print("   - %s | atteso=%s | trovato=%s" % (v, a, t))
print("=" * 76)
sys.exit(0 if not DIFF else 1)
