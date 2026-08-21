# -*- coding: utf-8 -*-
"""🗂️ LA SCHEDA — le caselle di arrivo le spunta una MACCHINA, mai una persona.

⛔ PERCHE' ESISTE (2026-08-21, deciso col fondatore dopo settimane di domande senza risposta)
==============================================================================
Il fondatore chiedeva da settimane: *«il Blocco 1 e' finito, si' o no?»*. Nessuno gli ha mai
risposto, e non per pigrizia: **la macchina non era capace di rispondere**. `collaudi/piano.py`
stampava le condizioni di arrivo con `☐`, e quel `☐` era **una costante** -- una riga sola,
`print("       ☐ %s" % c)`. In tutto il progetto non esisteva **nessun `☑`**. Qualunque cosa si
facesse, ogni blocco avrebbe mostrato per sempre quadratini vuoti.

E' il pezzo **5** del piano, quello che il piano stesso chiama *«il Giudice scrive da se' la
scheda, il guardiano la pretende»*, e senza il quale -- lo dice `piano.py` da solo -- **nessun
blocco puo' risultare FINITO**.

==============================================================================
LA REGOLA, IN UNA FRASE
==============================================================================
    Un'affermazione sul sistema non esiste se non porta con se'
    CHI l'ha prodotta, su QUALE COMMIT, e SU QUANTE COSE ha guardato.

Non e' un'invenzione nostra: e' quello che il mondo ha gia' risolto quattro volte, e le quattro
risposte dicono la stessa cosa da quattro lati (ricerca del 2026-08-21, fonti nel registro):
  · **fitness function** (Ford/Parsons/Kua) — la condizione di arrivo si SCRIVE come codice
    eseguibile che gira nella catena. Se non e' eseguibile non e' una condizione: e' un desiderio.
  · **attestation** (in-toto / SLSA) — un'affermazione vale solo LEGATA a un artefatto preciso.
    Cambia l'artefatto, l'attestazione non vale piu'. Qui l'artefatto e' il **commit**.
  · **spec drift** — il testo leggibile si GENERA dai dati; due copie a mano divergono sempre.
  · **assertion-free test** — un controllo senza asserzioni e' un difetto catalogato, e si stana
    contando quante cose ha davvero esaminato.

==============================================================================
LE QUATTRO REGOLE CHE LA RENDONO ONESTA — ognuna nata da un danno vero
==============================================================================
  1. **mai misurata** non e' verde. E' assenza di misura (sbaglio S1: il vuoto non e' un valore).
  2. **misurata su un ALTRO commit** non vale piu': il codice e' cambiato sotto, e quella misura
     non parla piu' di questo codice. La casella **si svuota da sola** -- nessuno deve
     ricordarsi di aggiornarla, ed e' esattamente la cura per «i file dicono cose vecchie».
     💡 E' la stessa regola dello schedario delle bombe a tempo (*«oltre quell'eta' non e' piu'
     una misura, e' un ricordo»*), ma legata al COMMIT invece che ai giorni: piu' stretta, e
     piu' vera.
  3. **denominatore zero non e' verde.** Il 2026-08-21 `plausibilita.py` ha dichiarato «ogni
     numero sta in una banda che il mondo consente» dopo averne esaminato **UNO**, e il banco
     dava OK su un libro giornale **vuoto** confrontando zero contro zero.
  4. **esito falso resta rosso**, ovviamente.

==============================================================================
COSA QUESTA SCHEDA **NON** FA (dichiarato, D18 punto 3)
==============================================================================
  · **Non sa se la condizione e' quella giusta.** Se scriviamo una condizione sbagliata, la
    spuntera' diligentemente. Le condizioni le decide il fondatore, non questo file.
  · **Non misura niente da se'.** Registra quello che un attrezzo ha misurato. Se l'attrezzo
    guarda una riga sola, qui si leggera' «denominatore 1» -- piu' onesto, non piu' coperto.
  · **Non spunta le condizioni che nessuna macchina puo' verificare.** Restano vuote col loro
    motivo, invece di sparire fra i verdi: la fonte stessa (Thoughtworks) dice che quando una
    caratteristica non e' verificabile da una macchina resta un giudizio umano, e allora va
    marcato come tale.

==============================================================================
COME SI USA
==============================================================================
    python collaudi/scheda.py              # stampa lo stato delle caselle, blocco per blocco
    python collaudi/scheda.py --blocco 1   # solo il Blocco 1

E da dentro un attrezzo che ha appena misurato qualcosa:

    import scheda
    scheda.registra(testo_della_condizione, esito=True, denominatore=41,
                    comando="python collaudi/giro_banco.py")

⛔ NESSUNO SCRIVE `scheda.json` A MANO. Se lo si facesse, si tornerebbe al punto di partenza:
un documento che dice quello che qualcuno si ricordava, non quello che la macchina ha visto.
"""
import argparse
import hashlib
import io
import json
import os
import subprocess
import sys

try:  # Windows: la console cp1252 non regge gli accenti -> uscita tollerante
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

QUI = os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(QUI)
SCHEDA = os.path.join(QUI, "scheda.json")


def chiave(testo):
    """L'impronta del TESTO della condizione, ed e' una scelta, non una comodita'.

    ⛔ Se qualcuno RISCRIVE una condizione sta chiedendo un'altra cosa, e la misura vecchia
    non risponde piu' a quella domanda: la casella deve tornare vuota DA SOLA. Con una chiave
    scritta a mano, invece, un testo cambiato terrebbe la sua vecchia spunta -- cioe' si
    dichiarerebbe fatta una cosa che nessuno ha mai verificato.
    ⚠️ Gli spazi si normalizzano: mandare a capo una frase non cambia la domanda.
    """
    return hashlib.sha256(" ".join(str(testo).split()).encode("utf-8")).hexdigest()[:12]


def commit_attuale(radice=RADICE):
    """Il commit su cui stiamo. Stringa vuota se git non risponde -- e allora nessuna
    casella si spunta, perche' senza sapere DOVE siamo una misura non e' ancorata a niente."""
    try:
        esito = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=radice,
                               capture_output=True, text=True, timeout=15)
        return esito.stdout.strip() if esito.returncode == 0 else ""
    except Exception:
        return ""


def leggi(percorso=SCHEDA):
    """La scheda dal disco. Dizionario vuoto se non c'e' o non si legge: l'assenza di scheda
    e' «nessuna misura», mai «tutto a posto»."""
    try:
        with io.open(percorso, encoding="utf-8") as f:
            dati = json.load(f)
        return dati if isinstance(dati, dict) else {}
    except Exception:
        return {}


def registra(testo, esito, denominatore, comando, percorso=SCHEDA, commit=None, quando=None):
    """Un attrezzo dichiara cosa ha misurato. Torna la riga scritta.

    ⛔ `denominatore` NON e' facoltativo ed e' il cuore: e' *su quante cose* l'attrezzo ha
    guardato. Zero significa «non ho esaminato niente», e allora l'esito non vale.
    """
    if not comando or not str(comando).strip():
        raise ValueError("una misura senza il COMANDO che la produce non e' verificabile: "
                         "chi legge non potrebbe rifarla")
    import datetime
    riga = {
        "condizione": " ".join(str(testo).split()),
        "esito": bool(esito),
        "denominatore": int(denominatore),
        "comando": str(comando).strip(),
        "commit": commit if commit is not None else commit_attuale(),
        "quando": quando or datetime.datetime.now().isoformat(timespec="seconds"),
    }
    dati = leggi(percorso)
    dati[chiave(testo)] = riga
    with io.open(percorso, "w", encoding="utf-8") as f:
        json.dump(dati, f, indent=1, ensure_ascii=False, sort_keys=True)
    return riga


def stato(testo, schedario=None, commit=None):
    """(spuntata, motivo) per UNA condizione. E' qui che vivono le quattro regole.

    ⛔ `schedario is None` e non `schedario or ...`: un dizionario VUOTO e' un dato legittimo
    («la scheda non ha niente»), e trattarlo come «non me l'hai passato» farebbe leggere il
    file vero durante un collaudo -- cioe' giudicare una cosa diversa da quella che si voleva.
    """
    dati = leggi() if schedario is None else schedario
    ora = commit_attuale() if commit is None else commit
    riga = dati.get(chiave(testo))
    if not isinstance(riga, dict):
        return (False, "mai misurata: nessun attrezzo ha ancora scritto questa casella")
    if not ora:
        return (False, "non so su quale commit siamo (git non risponde): una misura senza "
                       "ancoraggio non vale")
    suo = str(riga.get("commit") or "")
    if suo != ora:
        return (False, "misurata sul commit %s, adesso siamo su %s: il codice e' cambiato "
                       "sotto, quella misura non parla piu' di questo codice"
                % (suo or "(non indicato)", ora))
    denominatore = riga.get("denominatore")
    if not isinstance(denominatore, int) or denominatore <= 0:
        return (False, "denominatore %r: l'attrezzo non ha esaminato NIENTE, quindi il suo "
                       "esito non e' un giudizio (sbaglio S7)" % (denominatore,))
    if not riga.get("esito"):
        return (False, "ROSSA: l'attrezzo l'ha misurata e non passa (%s)"
                % riga.get("comando", "comando non indicato"))
    return (True, "misurata su %s, %d cose esaminate, da `%s`"
            % (suo, denominatore, riga.get("comando", "?")))


def _blocchi():
    """I blocchi VERI, letti da `collaudi/piano.py`: il piano sta li', e una seconda copia
    qui dentro sarebbe esattamente la malattia che questa scheda esiste per curare."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_piano_scheda",
                                                  os.path.join(QUI, "piano.py"))
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo.BLOCCHI


def stampa(solo=None):
    dati = leggi()
    ora = commit_attuale()
    print("=" * 78)
    print("🗂️  LA SCHEDA — le caselle le spunta una macchina, mai una persona")
    print("=" * 78)
    print("  commit: %s   ·   righe nella scheda: %d" % (ora or "(git non risponde)", len(dati)))
    print("  ⛔ Una casella vuota NON e' un rimprovero: e' la verita' su cosa sappiamo.")
    print("")
    uscita = 0
    for b in sorted(_blocchi(), key=lambda x: x["ordine"]):
        if solo and b["ordine"] != solo:
            continue
        condizioni = list(b["finito_quando"])
        spuntate = 0
        print("-" * 78)
        print(" %2d. %s" % (b["ordine"], b["nome"]))
        for c in condizioni:
            ok, motivo = stato(c, dati, ora)
            if ok:
                spuntate += 1
            testo = " ".join(str(c).split())
            print("   %s %s" % ("☑" if ok else "☐", testo[:150]))
            print("       %s" % motivo)
        print("   --> %d su %d" % (spuntate, len(condizioni)))
        if spuntate < len(condizioni):
            uscita = 1
        print("")
    print("=" * 78)
    print("⚠️  COSA QUESTA SCHEDA NON FA (D18 punto 3)")
    print("=" * 78)
    print("  · non sa se la condizione e' quella GIUSTA: se e' sbagliata, la spunta lo stesso")
    print("  · non misura niente da se': registra cio' che un attrezzo ha misurato")
    print("  · una condizione che nessuna macchina puo' verificare resta VUOTA col suo motivo,")
    print("    invece di sparire fra i verdi")
    print("=" * 78)
    return uscita


def main(argv=None):
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument("--blocco", type=int, default=None,
                   help="stampa solo il blocco indicato (es. --blocco 1)")
    argomenti = p.parse_args(list(argv if argv is not None else sys.argv[1:]))
    return stampa(solo=argomenti.blocco)


if __name__ == "__main__":
    sys.exit(main())
