# -*- coding: utf-8 -*-
"""IL CRICCHETTO DEGLI STRUMENTI STATICI — un motore solo, cinque strumenti.

A COSA SERVE, in una riga: il debito vecchio non blocca nessuno, ma da qui in
avanti **una segnalazione nuova ferma la modifica**.

PERCHE' ESISTE
--------------
Accendere `ruff`, `bandit`, `gitleaks`, `pip-audit` e `semgrep` su un codice gia'
scritto produce oggi centinaia di rilievi. Due strade sbagliate:

  1. farli bloccare subito  -> la CI e' rossa ogni giorno per debito vecchio, e
     nel giro di una settimana il rosso viene ignorato. E' il danno peggiore.
  2. lasciarli informativi  -> nessuno legge il log, e il debito cresce.

La terza strada e' il CRICCHETTO (ratchet): si fotografa lo stato di oggi in una
`baseline`, si dichiara che quello NON blocca, e si blocca su tutto cio' che
compare in piu'. Il numero puo' solo scendere. Non si tocca una riga del codice
di produzione per far tacere uno strumento.

COME E' FATTA LA FOTOGRAFIA (e perche' cosi')
---------------------------------------------
Non si conta il totale, e non si registra il numero di riga.

  · il TOTALE da solo non basta: si toglie un rilievo vecchio da un file e se ne
    aggiunge uno nuovo in un altro, il totale non si muove e il difetto passa.
  · la RIGA e' instabile: basta aggiungere un commento sopra e tutte le righe si
    spostano; una baseline appesa alla riga diventa rossa senza motivo (e' lo
    stesso ragionamento della `chiave` in test_profondo_aperte.py).

La chiave e' quindi **(file relativo, codice della regola)** e il valore e'
**quante volte** compare. Un file che passa da 3 a 4 rilievi `F401` si accende;
lo stesso file che li sposta di venti righe no.
Eccezione dichiarata: `gitleaks` sulla STORIA usa la sua impronta nativa, perche'
un commit gia' scritto non si muove piu' — e' la chiave piu' stretta possibile.

⛔ LA CHIAVE PORTA IL SUO AMBITO. Il file sta DENTRO la chiave, non accanto: due
strumenti diversi hanno baseline separate e non possono spuntarsi a vicenda.

COME SI USA
-----------
    python collaudi/cricchetto_statico.py ruff
    python collaudi/cricchetto_statico.py tutti
    python collaudi/cricchetto_statico.py ruff --azzera     <- rifa' la fotografia

CODICI DI USCITA — uno per esito, e il perche' e' costato una casella cieca
    0 = nessuna segnalazione nuova rispetto alla fotografia
    1 = segnalazioni NUOVE (elencate)          -> il gate blocca
    2 = NON E' NOSTRO: e' l'errore d'uso di argparse (comando scritto male)
    3 = l'attrezzo non c'e'                    -> installalo
    4 = l'attrezzo e' esploso mentre leggeva   -> guarda perche'
    5 = manca la FOTOGRAFIA                    -> rifalla con `--azzera`
    Da 1 a 5 il gate blocca: cambia solo cosa devi andare a fare.

⛔ PERCHE' NON BASTAVA UN 2 PER TUTTI, misurato il 2026-08-28 su `aaf9b59`. Fino a
quel giorno i tre guasti qui sopra uscivano TUTTI `2`, cioe' lo stesso numero con
cui argparse annuncia un refuso nel comando. Chi leggeva un `2` non poteva sapere
se aveva sbagliato a scrivere la riga o se NESSUNO stava piu' cercando le chiavi
finite nel codice — su un repository PUBBLICO, dove una chiave che entra non si
ripara: si revoca, e intanto e' gia' stata letta. Il caso grave era
indistinguibile da quello innocuo, che e' la forma peggiore dell'osservabile
debole (regola ferrea 9): non un log povero, un VERDETTO AMBIGUO.
E la meta' peggiore non era il numero: la tabella finale mappava `2` sull'unica
etichetta «ATTREZZO NON USABILE», quindi quando mancava la fotografia lo
strumento ANNUNCIAVA UN GUASTO CHE NON ERA IL SUO, e mandava a cercare un
attrezzo rotto che stava benissimo (modo di rompersi n. 3, testi che mentono).
Guardia: `TestIlCricchettoDiceQUALEGuastoHaAvuto` in `test_pipeline_ci.py`.

⚠️ COSA IL CODICE D'USCITA COMPLESSIVO NON DICE (D18 punto 3). Con `tutti`, il
verdetto finale e' il PIU' ALTO dei cinque: se un attrezzo manca (3) mentre un
altro ha segnalazioni nuove (1), esce 3 e l'1 non si vede nel numero. Non si
perde niente lo stesso, perche' la tabella in fondo stampa l'esito di OGNI
strumento riga per riga: il numero e' un riassunto, la tabella e' la misura.

⛔ VISTO ROSSO: `--autoprova` inietta una segnalazione finta nella lettura e
pretende che il confronto la veda. Un cricchetto che non e' mai stato visto
rosso non e' un cricchetto: e' un ornamento che stampa "ok".
"""

import argparse
import io
import json
import os
import shutil
import subprocess
import sys

QUI = os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(QUI)
CARTELLA_BASELINE = os.path.join(QUI, "baseline")

# Cartelle che nessuno strumento deve leggere. Sono le stesse dichiarate in
# ruff.toml: storia (`_archivio`, REGOLA ZERO 2), dati, pagine servite, cache.
ESCLUSE = ("_archivio", "data", "deploy", "__pycache__", ".mypy_cache",
           ".ruff_cache", ".hypothesis", ".git", "node_modules", "deploy_backup")


# ---------------------------------------------------------------------------
#  Utilita'
# ---------------------------------------------------------------------------
def _rel(percorso):
    """Percorso relativo alla radice, sempre con la barra in avanti.

    Serve perche' la fotografia si fa su Windows e il confronto gira su Linux:
    senza normalizzazione ogni chiave sarebbe diversa e il cricchetto direbbe
    che TUTTO e' nuovo."""
    if not percorso:
        return "?"
    p = percorso.replace("\\", "/")
    radice = RADICE.replace("\\", "/")
    if p.lower().startswith(radice.lower()):
        p = p[len(radice):]
    p = p.lstrip("./")
    while p.startswith("/"):
        p = p[1:]
    return p


def _esegui(comando, timeout=1800):
    """Lancia un comando e restituisce (codice, stdout, stderr). Non solleva."""
    try:
        p = subprocess.Popen(comando, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, cwd=RADICE)
        fuori, errori = p.communicate(timeout=timeout)
        return (p.returncode,
                fuori.decode("utf-8", "replace"),
                errori.decode("utf-8", "replace"))
    except OSError as e:
        return (127, "", str(e))
    except subprocess.TimeoutExpired:
        p.kill()
        return (124, "", "timeout dopo %d secondi" % timeout)


def _json_da_file(percorso):
    with io.open(percorso, encoding="utf-8", errors="replace") as f:
        return json.load(f)


def _temporaneo(nome):
    cartella = os.path.join(QUI, "baseline", "_ultimo_giro")
    if not os.path.isdir(cartella):
        os.makedirs(cartella)
    return os.path.join(cartella, nome)


#  ---------------------------------------------------------------------------
#   I CODICI D'USCITA, con un nome ciascuno.
#   Perche' un nome e non il numero scritto a mano dentro le funzioni: un numero
#   ripetuto in tre punti si separa in due e nessuno se ne accorge. Il 2 NON
#   compare qui, e non e' una dimenticanza: appartiene ad argparse, che lo usa
#   per l'errore d'uso. Prenderselo significherebbe litigare per sempre con la
#   libreria standard, e riaprire l'ambiguita' che questi nomi chiudono.
#  ---------------------------------------------------------------------------
OK = 0
SEGNALAZIONI_NUOVE = 1
ATTREZZO_ASSENTE = 3
LETTURA_FALLITA = 4
FOTOGRAFIA_MANCANTE = 5

#  L'etichetta che la tabella finale stampa accanto a ogni strumento. Sta qui e
#  non dentro `principale()` perche' la guardia la legge, e perche' una mappa che
#  copre TUTTI i codici non puo' piu' annunciare il guasto sbagliato.
ETICHETTE = {
    OK: "ok",
    SEGNALAZIONI_NUOVE: "SEGNALAZIONI NUOVE",
    ATTREZZO_ASSENTE: "ATTREZZO ASSENTE (installalo)",
    LETTURA_FALLITA: "ATTREZZO ESPLOSO (guarda perche')",
    FOTOGRAFIA_MANCANTE: "MANCA LA FOTOGRAFIA (--azzera)",
}


class AttrezzoAssente(Exception):
    """Lo strumento non e' installato o non e' partito: non e' un difetto del codice."""


# ---------------------------------------------------------------------------
#  I CINQUE LETTORI. Ognuno restituisce una lista di (chiave, descrizione).
#  Nessuno di loro giudica: leggono e basta. Il giudizio e' uno solo, sotto.
# ---------------------------------------------------------------------------
def leggi_ruff():
    exe = shutil.which("ruff")
    comando = ([exe] if exe else [sys.executable, "-m", "ruff"])
    comando += ["check", ".", "--output-format=json", "--quiet"]
    rc, fuori, errori = _esegui(comando)
    if rc not in (0, 1) or not fuori.strip():
        raise AttrezzoAssente("ruff rc=%s %s" % (rc, (errori or fuori)[:400]))
    voci = []
    for v in json.loads(fuori):
        codice = v.get("code") or "SINTASSI"
        voci.append((_rel(v.get("filename")) + "|" + codice,
                     (v.get("message") or "")[:120]))
    return voci


def leggi_bandit():
    fuori_file = _temporaneo("bandit.json")
    comando = [sys.executable, "-m", "bandit", "-r", ".", "-q", "-f", "json",
               "-o", fuori_file,
               "-x", ",".join("./" + c for c in ESCLUSE) + ",./app.py,./collaudi"]
    rc, _, errori = _esegui(comando)
    if not os.path.isfile(fuori_file):
        raise AttrezzoAssente("bandit rc=%s %s" % (rc, errori[:400]))
    dati = _json_da_file(fuori_file)
    voci = []
    for v in dati.get("results", []):
        voci.append((_rel(v.get("filename")) + "|" + (v.get("test_id") or "?"),
                     "%s/%s %s" % (v.get("issue_severity"), v.get("issue_confidence"),
                                   (v.get("issue_text") or "")[:90])))
    return voci


def leggi_gitleaks():
    """Solo la STORIA e il contenuto TRACCIATO: e' quello che il repository pubblica.

    ⛔ Non si usa `gitleaks dir`: legge anche i file esclusi da .gitignore (i
    `_SEGRETI_*.bak` sul disco del fondatore) e accuserebbe di una fuga cose che
    su GitHub non sono mai arrivate. Misurato il 2026-08-26: `dir` 35 rilievi,
    `git` 8 — i 27 di scarto erano tutti file mai versionati."""
    exe = shutil.which("gitleaks")
    if not exe:
        raise AttrezzoAssente("gitleaks non e' nel PATH")
    fuori_file = _temporaneo("gitleaks.json")
    rc, _, errori = _esegui([exe, "git", ".", "--report-format", "json",
                             "--report-path", fuori_file, "--exit-code", "0",
                             "--no-banner"])
    if not os.path.isfile(fuori_file):
        raise AttrezzoAssente("gitleaks rc=%s %s" % (rc, errori[:400]))
    voci = []
    for v in _json_da_file(fuori_file):
        #  L'impronta nativa: commit + file + regola + riga. La storia non si
        #  muove piu', quindi qui la riga E' stabile e la chiave e' la piu'
        #  stretta possibile. ⛔ Non si stampa MAI il segreto trovato.
        impronta = v.get("Fingerprint") or "%s:%s:%s" % (
            v.get("Commit"), v.get("File"), v.get("RuleID"))
        voci.append((impronta,
                     "%s in %s riga %s" % (v.get("RuleID"), _rel(v.get("File")),
                                           v.get("StartLine"))))
    return voci


def leggi_pip_audit():
    """Le librerie dichiarate in requirements.txt, non quelle installate sul runner.

    ⛔ `pip-audit` senza `-r` guarda l'ambiente in cui gira: nella CI quello
    contiene ruff, mypy e bandit, cioe' gli attrezzi, non il prodotto. Misurato
    il 2026-08-26 su questo PC: 136 falle in 31 pacchetti dell'ambiente contro
    10 in 6 pacchetti di requirements.txt. Il primo numero non parla di noi."""
    fuori_file = _temporaneo("pip_audit.json")
    comando = [sys.executable, "-m", "pip_audit", "-r", "requirements.txt",
               "-f", "json", "--progress-spinner", "off", "-o", fuori_file]
    rc, fuori, errori = _esegui(comando, timeout=900)
    if not os.path.isfile(fuori_file):
        raise AttrezzoAssente("pip-audit rc=%s %s" % (rc, (errori or fuori)[:400]))
    dati = _json_da_file(fuori_file)
    voci = []
    for dip in dati.get("dependencies", []):
        for falla in dip.get("vulns", []):
            voci.append(("%s|%s" % (dip.get("name"), falla.get("id")),
                         "%s %s -> %s" % (dip.get("name"), dip.get("version"),
                                          ",".join(falla.get("fix_versions") or [])
                                          or "nessuna correzione pubblicata")))
    return voci


#  Il pacchetto di regole. `p/python` e' la raccolta curata di Semgrep per Python
#  (sicurezza + trappole di linguaggio). ⛔ NON e' vendorizzato dentro il repo di
#  proposito: quelle regole hanno una licenza propria e vivono altrove.
#  ⚠️ CONSEGUENZA DICHIARATA: le regole si aggiornano da remoto, quindi un giorno
#  puo' comparire un rilievo nuovo senza che il codice sia cambiato. Il cricchetto
#  lo mostrera' come "NUOVO": e' un segnale vero (una regola nuova ha visto una
#  cosa vecchia), non un guasto, e si chiude rifacendo la fotografia dopo averlo
#  letto. Misurato il 2026-08-26: 4 rilievi in tutto il repository.
PACCHETTO_SEMGREP = "p/python"

#  ⛔ 12 regole sono andate in TIMEOUT (5 secondi di serie) sui file piu' grossi
#     (fase83_server.py, test_pipeline_ci.py, assistente_gestionale.py): quelle
#     regole NON hanno guardato quei file, ed erano punti ciechi silenziosi.
#     Con 120 secondi il timeout smette di essere la regola.
TIMEOUT_REGOLA_SEMGREP = "120"


def leggi_semgrep():
    exe = shutil.which("semgrep")
    if not exe:
        raise AttrezzoAssente("semgrep non e' nel PATH")
    fuori_file = _temporaneo("semgrep.json")
    comando = [exe, "scan", "--config", PACCHETTO_SEMGREP,
               "--timeout", TIMEOUT_REGOLA_SEMGREP,
               "--json", "--quiet", "--metrics", "off", "--output", fuori_file]
    for c in ESCLUSE:
        comando += ["--exclude", c]
    comando.append(".")
    rc, fuori, errori = _esegui(comando, timeout=3600)
    if not os.path.isfile(fuori_file):
        raise AttrezzoAssente("semgrep rc=%s %s" % (rc, (errori or fuori)[:400]))
    dati = _json_da_file(fuori_file)
    #  ⛔ I PUNTI CIECHI SI DICHIARANO. Una regola andata in timeout non ha
    #  guardato quel file: se restasse muta, "0 rilievi" verrebbe letto come
    #  "pulito" mentre significa "non guardato". Non blocca, ma si vede.
    ciechi = [e for e in dati.get("errors", []) if "imeout" in str(e.get("type"))]
    if ciechi:
        print("  ⚠️  %d regole non hanno guardato il loro file (timeout): sono "
              "punti ciechi, non assoluzioni." % len(ciechi))
        for e in ciechi[:5]:
            print("      %s" % _rel(str(e.get("path"))))
    voci = []
    for v in dati.get("results", []):
        regola = (v.get("check_id") or "?").split(".")[-1]
        voci.append((_rel(v.get("path")) + "|" + regola,
                     (v.get("extra", {}).get("message") or "")[:120]))
    return voci


LETTORI = {
    "ruff": leggi_ruff,
    "bandit": leggi_bandit,
    "gitleaks": leggi_gitleaks,
    "pip-audit": leggi_pip_audit,
    "semgrep": leggi_semgrep,
}
ORDINE = ["ruff", "bandit", "gitleaks", "pip-audit", "semgrep"]


# ---------------------------------------------------------------------------
#  IL GIUDIZIO — uno solo, per tutti e cinque.
# ---------------------------------------------------------------------------
def conta(voci):
    """(chiave -> quante volte). L'ordine non conta, il numero si'."""
    quante = {}
    for chiave, _descrizione in voci:
        quante[chiave] = quante.get(chiave, 0) + 1
    return quante


def percorso_baseline(nome):
    return os.path.join(CARTELLA_BASELINE, nome + ".json")


def carica_baseline(nome):
    percorso = percorso_baseline(nome)
    if not os.path.isfile(percorso):
        return None
    return _json_da_file(percorso)


def scrivi_baseline(nome, voci):
    if not os.path.isdir(CARTELLA_BASELINE):
        os.makedirs(CARTELLA_BASELINE)
    quante = conta(voci)
    dati = {
        "strumento": nome,
        "totale": len(voci),
        "chiavi": len(quante),
        "voci": dict(sorted(quante.items())),
    }
    percorso = percorso_baseline(nome)
    with io.open(percorso, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(dati, indent=1, sort_keys=True, ensure_ascii=False))
        f.write("\n")
    return percorso


def confronta(nome, voci, baseline):
    """Le segnalazioni NUOVE: chiave assente dalla fotografia, o piu' numerosa.

    Restituisce (nuove, sparite). `sparite` non blocca: e' il debito che scende,
    e serve solo a dire quando conviene rifare la fotografia."""
    ora = conta(voci)
    prima = (baseline or {}).get("voci", {})
    nuove = []
    for chiave in sorted(ora):
        delta = ora[chiave] - prima.get(chiave, 0)
        if delta > 0:
            esempio = ""
            for k, d in voci:
                if k == chiave:
                    esempio = d
                    break
            nuove.append((chiave, delta, esempio))
    sparite = sorted(k for k in prima if prima[k] > ora.get(k, 0))
    return nuove, sparite


def giudica(nome, azzera=False, autoprova=False):
    """Ritorna il codice di uscita per UN solo strumento, e stampa il perche'."""
    print("")
    print("=" * 78)
    print("  %s" % nome.upper())
    print("=" * 78)
    try:
        voci = LETTORI[nome]()
    except AttrezzoAssente as e:
        print("  ⛔ ATTREZZO ASSENTE: %s" % e)
        print("     Non e' un giudizio sul codice: e' lo strumento che manca.")
        print("     Finche' manca, qui NON STA GUARDANDO NESSUNO: non e' un verde.")
        return ATTREZZO_ASSENTE
    except (ValueError, OSError) as e:
        print("  ⛔ LETTURA FALLITA: %s: %s" % (type(e).__name__, e))
        print("     L'attrezzo c'e' ed e' partito: si e' rotto mentre leggeva.")
        return LETTURA_FALLITA

    if autoprova:
        #  ⛔ VISTO ROSSO: una segnalazione finta, in un file che non esiste.
        #  Se il confronto qui sotto non la vede, il cricchetto non funziona e
        #  ogni "ok" stampato prima era una bugia.
        voci = list(voci) + [("PROVA_DEL_ROSSO/inesistente.py|FINTA",
                              "segnalazione iniettata dall'autoprova")]

    if azzera:
        percorso = scrivi_baseline(nome, voci)
        print("  📸 FOTOGRAFIA RIFATTA: %d segnalazioni, %d chiavi distinte"
              % (len(voci), len(conta(voci))))
        print("     scritta in %s" % _rel(percorso))
        print("     Da adesso questo e' il debito che NON blocca. Tutto cio' che")
        print("     compare in piu' blocca.")
        return OK

    baseline = carica_baseline(nome)
    if baseline is None:
        print("  ⛔ MANCA LA FOTOGRAFIA: non c'e' %s"
              % _rel(percorso_baseline(nome)))
        print("     L'attrezzo sta benissimo: e' il metro di paragone che non c'e'.")
        print("     Falla con:  python collaudi/cricchetto_statico.py %s --azzera"
              % nome)
        return FOTOGRAFIA_MANCANTE

    nuove, sparite = confronta(nome, voci, baseline)
    print("  segnalazioni adesso ....... %d" % len(voci))
    print("  segnalazioni congelate .... %d" % baseline.get("totale", 0))
    print("  chiavi sparite (debito -) . %d" % len(sparite))
    if not nuove:
        print("  ✅ NESSUNA SEGNALAZIONE NUOVA.")
        return OK
    print("  🔴 SEGNALAZIONI NUOVE: %d" % sum(d for _c, d, _e in nuove))
    for chiave, delta, esempio in nuove:
        print("     +%d  %s" % (delta, chiave))
        if esempio:
            print("         %s" % esempio)
    print("")
    print("  Queste NON sono debito vecchio: sono comparse adesso.")
    print("  Si chiudono nel codice nuovo. La fotografia si rifa' solo per")
    print("  DIMINUIRE il debito, mai per assorbire un rilievo appena creato.")
    return SEGNALAZIONI_NUOVE


def _console_utf8():
    """La console di Windows e' cp1252 e muore sulle emoji.

    Senza questo, `--azzera` finiva in UnicodeEncodeError PRIMA di scrivere la
    fotografia: lo strumento sembrava rotto mentre era rotta la stampa. Si
    ripiega in silenzio se la reconfigure non c'e'."""
    for flusso in (sys.stdout, sys.stderr):
        try:
            flusso.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def principale(argomenti=None):
    _console_utf8()
    p = argparse.ArgumentParser(
        description="Cricchetto degli strumenti statici: il debito vecchio non "
                    "blocca, una segnalazione nuova si'.")
    p.add_argument("strumento", choices=ORDINE + ["tutti"])
    p.add_argument("--azzera", action="store_true",
                   help="rifa' la fotografia del debito attuale")
    p.add_argument("--autoprova", action="store_true",
                   help="inietta una segnalazione finta e pretende di vederla")
    a = p.parse_args(argomenti)

    nomi = ORDINE if a.strumento == "tutti" else [a.strumento]
    esiti = {}
    for nome in nomi:
        esiti[nome] = giudica(nome, azzera=a.azzera, autoprova=a.autoprova)

    print("")
    print("=" * 78)
    for nome in nomi:
        #  ⛔ `ETICHETTE` copre TUTTI i codici, e si legge da li'. La mappa scritta
        #  a mano qui dentro ne conosceva tre e i codici erano cinque: «manca la
        #  fotografia» veniva annunciato come «ATTREZZO NON USABILE», cioe' una
        #  frase falsa che mandava a cercare il guasto dalla parte opposta.
        #  Il `%r` del ripiego non e' ornamentale: se un giorno nascesse un codice
        #  nuovo senza etichetta, qui si vedrebbe il numero nudo invece di una
        #  descrizione sbagliata presa a caso.
        print("  %-12s %s" % (nome, ETICHETTE.get(esiti[nome],
                                                  "codice %r senza etichetta"
                                                  % esiti[nome])))
    print("=" * 78)
    #  Il piu' alto vince: un attrezzo che manca (3/4/5) copre nel NUMERO delle
    #  segnalazioni nuove (1), e la tabella qui sopra e' il posto dove si vedono
    #  tutte e due. `esiti` vuoto non puo' succedere (`choices` di argparse lo
    #  impedisce): se succedesse, non abbiamo giudicato niente, e «niente
    #  giudicato» e' una lettura fallita, non un refuso nel comando.
    return max(esiti.values()) if esiti else LETTURA_FALLITA


if __name__ == "__main__":
    sys.exit(principale())
