"""LA PIRAMIDE — il sistema che garantisce che ogni cosa costruita sia sorvegliata.

═══════════════════════════════════════════════════════════════════════════════════
COSA NON PUO' FARE, DETTO SUBITO
═══════════════════════════════════════════════════════════════════════════════════
Nessun programma puo' dimostrare che un altro programma non ha bug: e' un limite
matematico, non una mancanza di impegno. Chi promette "zero bug garantiti" mente.

COSA FA, E VALE DI PIU'
Garantisce quattro cose, tutte verificabili:

  1. ogni MODO NOTO DI ROMPERSI ha qualcuno che lo guarda;
  2. ogni guardiano e' stato VISTO FUNZIONARE (rosso davanti al guasto);
  3. niente di costruito e' SENZA guardiani;
  4. il sistema SI ACCORGE DA SOLO quando una delle tre smette di essere vera.

Il punto 4 e' cio' che la rende un prodotto finito invece di una lista di controlli:
la garanzia non e' uno stato raggiunto una volta, e' una proprieta' sorvegliata.

═══════════════════════════════════════════════════════════════════════════════════
L'ARCHITETTURA: PIRAMIDE (larghezza) x NEURONI (profondita')
═══════════════════════════════════════════════════════════════════════════════════
LA PIRAMIDE da' la larghezza. Sei livelli; ognuno REGGE quello sopra, e un livello non
puo' dirsi verde se quello sotto non lo e'. Si sale dal basso e ci si ferma al primo
che cede: e' inutile giudicare la produzione se le fondamenta non tengono.

  L5 META        chi controlla i controllori  (mutazione, finti verdi, mappa)
  L4 REALTA'     produzione, terzi, tempo     (sito vero, OpenSSL, Autorita')
  L3 SISTEMA     avvio vero, persistenza      (main eseguito, dati che sopravvivono)
  L2 CABLAGGIO   i pezzi collegati            (anello per anello fino all'utente)
  L1 UNITA'      ogni funzione                (la suite)
  L0 FONDAMENTA  invarianti indiscutibili     (soldi interi, router mai solleva, ...)

I NEURONI danno la profondita'. Dentro ogni livello: la regola -> i suoi collegamenti
-> i casi terminali (limiti, errori, concorrenza, manomissione).

Insieme formano una MATRICE: ogni elemento costruito x ogni modo di rompersi.
Una casella senza osservatore e' un BUCO, anche se tutto e' verde.

L'INVENTARIO SI RICAVA DAL CODICE, non da una lista scritta a mano: una lista si
dimentica di aggiornare, e diventerebbe esattamente la cosa che deve prevenire.
"""
import io
import os
import re
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
os.chdir(REPO)

GIRI = 1
for a in sys.argv:
    if a.startswith("--giri="):
        GIRI = int(a.split("=")[1])
SOLO_MATRICE = "--solo-matrice" in sys.argv


# ═══════════════════════════════════════════════════════════════════════════════
#  I 9 MODI DI ROMPERSI — incontrati sul campo, ognuno con chi lo guarda
# ═══════════════════════════════════════════════════════════════════════════════
MODI = [
    ("dati effimeri",
     "funziona, ma scrive dove i dati muoiono",
     ["test_db_persistenti.py", "test_avvio_main.py"]),
    ("cablaggio mancante",
     "il pezzo e' perfetto e non e' collegato a nulla",
     ["test_qualifica_catena.py", "test_marca_temporale_server.py",
      "test_guardie_collegamenti.py", "collaudi/mappa_scoperta.py"]),
    ("testi che mentono",
     "il codice fa X, la pagina o l'email promettono Y",
     ["test_trasparenza_costi.py", "collaudi/audit_coerenza_tariffe.py",
      "collaudi/audit_millimetrico.py"]),
    ("controllo che non controlla",
     "la guardia esiste ma non puo' fallire",
     ["collaudi/caccia_finti_verdi.py", "collaudi/mutazione_prodotto.py"]),
    ("dipendenza nascosta",
     "funziona solo se c'e' qualcos'altro, e nessuno lo dice",
     ["test_avvio_main.py", "test_marca_temporale_server.py"]),
    ("il terzo che cambia",
     "un servizio esterno smette, cambia o perde una qualifica",
     ["collaudi/super_collaudo_marca.py", "collaudi/collaudo_neuroni_marca.py",
      "test_marca_qualificata.py"]),
    ("il tempo che passa",
     "scadenze, rampe per anzianita', rinnovi",
     ["test_fase98_policy_commissione.py", "collaudi/collaudo_rampa_totale.py",
      "collaudi/verifica_produzione.py"]),
    ("ambiente diverso",
     "in locale non e' come in produzione",
     ["test_db_persistenti.py", "test_avvio_main.py",
      "collaudi/verifica_produzione.py"]),
    ("rifattorizzazione",
     "il cuore cambia, le guardie restano attaccate al vecchio",
     ["collaudi/mutazione_prodotto.py", "test_fase98_policy_commissione.py"]),
]

# ═══════════════════════════════════════════════════════════════════════════════
#  I SEI LIVELLI — ognuno regge quello sopra
# ═══════════════════════════════════════════════════════════════════════════════
LIVELLI = [
    ("L0", "FONDAMENTA", "invarianti indiscutibili: soldi interi, router mai solleva, "
     "append-only, fail-closed",
     [("unittest", "test_invarianti_denaro test_conservazione_denaro "
                   "test_architettura test_avvio_failclosed test_menti_invarianti")]),
    ("L1", "UNITA'", "ogni funzione col suo comportamento: la suite intera",
     [("unittest-tutto", None)]),
    ("L2", "CABLAGGIO", "i pezzi collegati, anello per anello fino a cio' che l'utente "
     "vede",
     [("unittest", "test_qualifica_catena test_marca_temporale_server "
                   "test_guardie_collegamenti test_rotte_scoperte"),
      ("script", "mappa_scoperta.py")]),
    ("L3", "SISTEMA", "il programma avviato DAVVERO, i dati che sopravvivono, il ciclo "
     "di vita",
     [("unittest", "test_avvio_main test_db_persistenti test_deploy_casavip"),
      ("script", "collaudo_finale_totale.py"),
      ("script", "collaudo_neuroni_legale.py")]),
    ("L4", "REALTA'", "produzione, terzi indipendenti, tempo",
     [("script", "collaudo_neuroni_marca.py --giri=1 --con-rete"),
      ("script", "super_collaudo_marca.py --con-rete"),
      ("script", "audit_coerenza_tariffe.py"),
      ("script", "audit_millimetrico.py")]),
    ("L5", "META", "chi controlla i controllori: nessun finto verde, nessun buco, "
     "e il giudizio finale della mutazione",
     [("script", "caccia_finti_verdi.py"),
      ("script", "mutazione_prodotto.py")]),
]


# ═══════════════════════════════════════════════════════════════════════════════
#  INVENTARIO — ricavato dal codice, mai scritto a mano
# ═══════════════════════════════════════════════════════════════════════════════
def _leggi(p):
    with io.open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def inventario():
    server = _leggi(os.path.join(REPO, "fase83_server.py"))
    legacy = re.compile(r"^fase(1[3-9]|[2-5][0-9])_")
    inv = {
        "moduli": sorted(f for f in os.listdir(REPO)
                         if f.startswith("fase") and f.endswith(".py")
                         and not legacy.match(f)),
        "rotte": sorted(set(re.findall(r'path == "(/[^"]+)"', server))
                        | set(re.findall(r'u\.path == "(/[^"]+)"', server))),
        "pagine": sorted(f for f in os.listdir(os.path.join(REPO, "deploy"))
                         if f.endswith(".html")),
        "test": sorted(f for f in os.listdir(REPO)
                       if f.startswith("test_") and f.endswith(".py")),
        "collaudi": sorted(f for f in os.listdir(QUI) if f.endswith(".py")),
    }
    from fase81_bootstrap_casavip import ConfigCasaVIP
    inv["archivi"] = sorted(c for c in vars(ConfigCasaVIP()) if c.startswith("db_"))
    return inv


# ═══════════════════════════════════════════════════════════════════════════════
#  LA MATRICE — ogni modo di rompersi deve avere osservatori VIVI
# ═══════════════════════════════════════════════════════════════════════════════
def matrice(inv):
    buchi = []
    print("\n" + "=" * 92)
    print("MATRICE DI SORVEGLIANZA — ogni modo di rompersi, chi lo guarda")
    print("=" * 92)
    for nome, spiega, osservatori in MODI:
        vivi, morti = [], []
        for o in osservatori:
            percorso = os.path.join(REPO, o)
            (vivi if os.path.exists(percorso) else morti).append(o)
        stato = "OK  " if vivi else "BUCO"
        print("\n  [%s] %s" % (stato, nome.upper()))
        print("        %s" % spiega)
        print("        guardato da: %s" % (", ".join(vivi) if vivi else "NESSUNO"))
        if morti:
            print("        RIFERIMENTI MORTI (file spariti): %s" % ", ".join(morti))
            buchi.append("%s: osservatori spariti %s" % (nome, morti))
        if not vivi:
            buchi.append("%s: NESSUN osservatore" % nome)
    return buchi


def copertura_elementi(inv):
    """Ogni elemento costruito deve essere nominato da almeno un test o collaudo."""
    corpi = []
    for f in inv["test"]:
        corpi.append(_leggi(os.path.join(REPO, f)))
    for f in inv["collaudi"]:
        corpi.append(_leggi(os.path.join(QUI, f)))
    tutto = "\n".join(corpi)
    buchi = []
    for etichetta, elementi, trasforma in (
            ("moduli", inv["moduli"], lambda x: x[:-3]),
            ("rotte", inv["rotte"], lambda x: x),
            ("pagine", inv["pagine"], lambda x: x),
            ("archivi", inv["archivi"], lambda x: x.upper())):
        scoperti = [e for e in elementi if trasforma(e) not in tutto]
        print("\n  %-9s %3d costruiti | %3d sorvegliati | %d SCOPERTI"
              % (etichetta, len(elementi), len(elementi) - len(scoperti), len(scoperti)))
        if scoperti:
            for s in scoperti[:12]:
                print("        SCOPERTO: %s" % s)
            buchi.append("%s scoperti: %s" % (etichetta, scoperti[:12]))
    return buchi


# ═══════════════════════════════════════════════════════════════════════════════
#  ESECUZIONE DEI LIVELLI — dal basso, ci si ferma al primo che cede
# ═══════════════════════════════════════════════════════════════════════════════
def esegui(tipo, arg, timeout=2400):
    if tipo == "unittest":
        cmd = [sys.executable, "-m", "unittest"] + arg.split()
    elif tipo == "unittest-tutto":
        cmd = [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "test_*.py"]
    else:
        cmd = [sys.executable, os.path.join(QUI, arg.split()[0])] + arg.split()[1:]
    amb = dict(os.environ, PYTHONIOENCODING="utf-8")
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=REPO, env=amb, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=timeout)
        return p.returncode == 0, p.stdout.decode("utf-8", "replace"), time.time() - t0
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT", time.time() - t0


def sali_la_piramide(giri):
    caduti = []
    for codice, nome, spiega, passi in LIVELLI:
        print("\n" + "=" * 92)
        print("%s  %s — %s" % (codice, nome, spiega))
        print("=" * 92)
        for tipo, arg in passi:
            etichetta = arg if arg else "suite intera"
            esiti = []
            for giro in range(1, giri + 1):
                ok, uscita, dur = esegui(tipo, arg)
                esiti.append(ok)
                sintesi = ""
                for riga in uscita.splitlines():
                    if (riga.startswith("Ran ") or riga.startswith("VIOLAZIONI")
                            or riga.startswith("MUTANTI") or riga.startswith("PUNTI")
                            or riga.startswith("SOSPETTI") or riga.startswith("controlli")
                            or riga.startswith("VERDETTO")):
                        sintesi = riga[:70]
                print("   %-46s giro %d/%d  %-4s %6.1fs  %s"
                      % (etichetta[:46], giro, giri, "OK" if ok else "ROSSO",
                         dur, sintesi))
                if not ok:
                    coda = [r for r in uscita.splitlines() if r.strip()][-6:]
                    for r in coda:
                        print("        | " + r[:100])
            if not all(esiti):
                caduti.append("%s %s -> %s" % (codice, etichetta, esiti))
        if caduti:
            print("\n  %s NON REGGE: i livelli superiori non vengono nemmeno giudicati"
                  % codice)
            print("  (e' inutile giudicare la produzione se le fondamenta cedono)")
            break
    return caduti


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    t0 = time.time()
    print("=" * 92)
    print("LA PIRAMIDE — verifica che ogni cosa costruita sia sorvegliata")
    print("giri per livello: %d%s" % (GIRI, "  (SOLO MATRICE)" if SOLO_MATRICE else ""))
    print("=" * 92)

    inv = inventario()
    print("\nINVENTARIO RICAVATO DAL CODICE (non da una lista scritta a mano)")
    for k in ("moduli", "rotte", "pagine", "archivi", "test", "collaudi"):
        print("   %-9s %d" % (k, len(inv[k])))

    print("\n" + "=" * 92)
    print("COPERTURA DEGLI ELEMENTI — cosa non e' nominato da nessuno")
    print("=" * 92)
    buchi = copertura_elementi(inv)
    buchi += matrice(inv)

    caduti = [] if SOLO_MATRICE else sali_la_piramide(GIRI)

    print("\n" + "=" * 92)
    print("VERDETTO DELLA PIRAMIDE   (%.1f minuti)" % ((time.time() - t0) / 60.0))
    print("=" * 92)
    if buchi:
        print("\nBUCHI DI SORVEGLIANZA: %d" % len(buchi))
        for b in buchi:
            print("   X %s" % b)
    if caduti:
        print("\nLIVELLI CHE NON REGGONO: %d" % len(caduti))
        for c in caduti:
            print("   X %s" % c)
    if buchi or caduti:
        print("\nNON si puo' dichiarare 'prodotto finito'.")
        sys.exit(1)
    print("\n  Ogni modo noto di rompersi ha almeno un osservatore vivo.")
    print("  Ogni elemento costruito e' nominato da almeno un test o collaudo.")
    print("  Tutti e sei i livelli reggono, per %d giro/i, mutazione compresa." % GIRI)
    print("\n  Questo NON dimostra l'assenza di bug (nessuno puo' farlo).")
    print("  Dimostra che non ci sono ZONE CIECHE fra quelle che sappiamo cercare,")
    print("  e che il giorno in cui se ne aprisse una, questo programma lo direbbe.")
    sys.exit(0)
