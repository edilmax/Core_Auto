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


def chiave(testo, ordine):
    """L'impronta della condizione: il suo TESTO **e il blocco in cui vive**.

    ⛔ IL TESTO, perche' se qualcuno RISCRIVE una condizione sta chiedendo un'altra cosa, e
    la misura vecchia non risponde piu' a quella domanda: la casella deve tornare vuota DA
    SOLA. Con una chiave scritta a mano, invece, un testo cambiato terrebbe la sua vecchia
    spunta -- cioe' si dichiarerebbe fatta una cosa che nessuno ha mai verificato.
    ⚠️ Gli spazi si normalizzano: mandare a capo una frase non cambia la domanda.

    ⛔⛔ E IL BLOCCO, dal 2026-08-21, perche' senza di lui due blocchi che fanno la stessa
    domanda con le stesse parole CONDIVIDONO la casella. Misurato prima di ripararlo:
        caselle totali nel piano ........... 30
        chiavi distinte .................... 29
        chiavi condivise da piu' blocchi ....  1
          2x  blocchi [1, 2]  ->  «zero punti di mutazione scoperti sul codice che la
                                   produzione ESEGUE»       chiave 41d41915359a
    Cioe' un giro di mutazione sui SOLDI avrebbe dichiarato finite anche le PRENOTAZIONI.
    💡 Non e' «lo stesso testo, quindi la stessa domanda»: nel Blocco 1 quella frase parla
    dei moduli dei soldi, nel Blocco 2 di quelli delle prenotazioni. Due domande diverse
    scritte uguali -- e la chiave deve saperlo.

    ⛔ E' lo STESSO difetto gia' riparato il 2026-08-01 nello schedario degli equivalenti,
    dove la chiave non portava il nome della FUNZIONE e una dichiarazione si estendeva a
    tutte le righe identiche del file. La regola scritta li' vale qui parola per parola:
    **una dichiarazione vale SOLO dove e' stata dimostrata.**
    ⚠️ Era LATENTE: `scheda.json` non esisteva e nessuno scriveva. Il pezzo 5 del piano e'
    esattamente cio' che comincia a scrivere -- sarebbe stato quel lavoro ad accenderlo.
    Guardia: `test_pipeline_ci.TestDueBlocchiNonPossonoCondividereUnaCasella`.
    """
    normale = " ".join(str(testo).split())
    return hashlib.sha256(("%s|%s" % (ordine, normale)).encode("utf-8")).hexdigest()[:12]


def impronta_del_blocco(ordine, radice=RADICE):
    """L'impronta del CODICE che questo blocco misura. `None` se non si puo' sapere.

    ⛔⛔ PERCHE' NON IL COMMIT, e non e' un dettaglio: e' la differenza fra un traguardo
    raggiungibile e uno impossibile. Fino al 2026-08-21 la casella scadeva quando cambiava
    il **commit**, qualunque cosa fosse cambiata. Ma per passare sei esami servono sei
    sessioni, e ogni sessione fa un commit -- quindi:
        lunedi'  passo l'esame 1 (commit A)  -> 1 su 6
        martedi' passo l'esame 2 (commit B)  -> l'esame 1 SI SVUOTA -> di nuovo 1 su 6
    Il blocco non poteva **MAI** arrivare a 6 su 6: era impossibile PER COSTRUZIONE, lo
    stesso difetto della casella-costante di ieri, in una forma nuova. L'ha trovato il
    fondatore con una domanda: «se non e' finito devi ricominciare da capo?». Si', ogni volta.

    ✅ Il criterio giusto e' l'unico che non si puo' allargare: **la misura scade quando
    cambia il codice CHE QUELLA MISURA GUARDA.** Correggo una virgola in un documento, o
    aggiungo un collaudo? La casella dei soldi resta valida, perche' i soldi non sono
    cambiati. Tocco `fase85_pagamenti_stripe.py`? Scade, ed e' giusto.

    ⛔ E se il piano non si legge si torna `None`: senza sapere QUALE codice la casella
    guarda, quella misura non e' ancorata a niente -- e una casella non ancorata non e'
    verde (sbaglio S1: il vuoto non e' un valore).
    """
    percorso = os.path.join(QUI, "piano.py")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_piano_impronta", percorso)
        piano = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(piano)
        blocchi = [b for b in piano.BLOCCHI if b["ordine"] == ordine]
        if len(blocchi) != 1:
            return None
        moduli = sorted(blocchi[0].get("moduli") or ())
    except Exception:
        return None
    if not moduli:
        return None
    h = hashlib.sha256()
    for nome in moduli:
        h.update(nome.encode("utf-8"))
        h.update(b"\0")
        try:
            with io.open(os.path.join(radice, nome + ".py"), "rb") as f:
                # ⛔ I fine riga NON sono codice (2026-09-05): git su Windows riscrive
                #    CRLF/LF da una cartella all'altra, e sui byte grezzi lo STESSO
                #    Blocco 1 leggeva 6 su 6 in un albero e 0 su 6 in un altro. La
                #    misura deve dipendere dal codice, non dalla cartella (D23).
                h.update(f.read().replace(b"\r\n", b"\n"))
        except OSError:
            # ⛔ Un modulo che sparisce CAMBIA l'impronta, e deve: la casella diceva
            #    qualcosa su un insieme di file, e quell'insieme non e' piu' lo stesso.
            h.update(b"(assente)")
        h.update(b"\0")
    return h.hexdigest()[:12]


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


def registra(testo, esito, denominatore, comando, ordine, percorso=SCHEDA, commit=None,
             quando=None, motivo=None):
    """Un attrezzo dichiara cosa ha misurato. Torna la riga scritta.

    ⛔ `denominatore` NON e' facoltativo ed e' il cuore: e' *su quante cose* l'attrezzo ha
    guardato. Zero significa «non ho esaminato niente», e allora l'esito non vale.
    ⛔ `ordine` NON e' facoltativo ed e' il BLOCCO a cui la casella appartiene: senza, due
    blocchi che fanno la stessa domanda si spuntano a vicenda (vedi `chiave`). E' scritto
    anche dentro la riga, cosi' chi apre `scheda.json` vede DI CHE COSA parla ogni misura
    senza doverla dedurre dalla chiave.
    `motivo` (dal 2026-09-03) e' il PERCHE' di un esito falso, nelle parole dell'attrezzo:
    un `False` muto manda a caccia di un guasto che puo' non esistere («un quinto del blocco
    non era giudicabile» non e' «c'e' un guasto nei soldi»), e costa quanto un verde falso
    (ferrea 10). Sta in un campo che una macchina legge, non lasciato a dedurre dal
    denominatore.
    """
    if not comando or not str(comando).strip():
        raise ValueError("una misura senza il COMANDO che la produce non e' verificabile: "
                         "chi legge non potrebbe rifarla")
    import datetime
    riga = {
        "condizione": " ".join(str(testo).split()),
        "blocco": int(ordine),
        "esito": bool(esito),
        "denominatore": int(denominatore),
        "comando": str(comando).strip(),
        # ⛔ L'IMPRONTA E' CIO' CHE DECIDE se la misura vale ancora (vedi
        #    `impronta_del_blocco`): e' il codice che questa casella guarda, non il commit
        #    del repository. Col commit, sei esami in sei sessioni non potevano MAI stare
        #    spuntati insieme.
        "impronta": impronta_del_blocco(int(ordine)),
        # Il commit resta scritto perche' serve a CHI LEGGE (ritrovare il giro, rifarlo),
        # ma NON e' piu' lui a decidere: e' informazione, non giudizio.
        "commit": commit if commit is not None else commit_attuale(),
        "quando": quando or datetime.datetime.now().isoformat(timespec="seconds"),
        "motivo": " ".join(str(motivo).split()) if motivo else "",
    }
    dati = leggi(percorso)
    dati[chiave(testo, ordine)] = riga
    with io.open(percorso, "w", encoding="utf-8") as f:
        json.dump(dati, f, indent=1, ensure_ascii=False, sort_keys=True)
    return riga


def stato(testo, ordine, schedario=None, impronta=None):
    """(spuntata, motivo) per UNA condizione DI UN BLOCCO. Qui vivono le quattro regole.

    ⛔ `schedario is None` e non `schedario or ...`: un dizionario VUOTO e' un dato legittimo
    («la scheda non ha niente»), e trattarlo come «non me l'hai passato» farebbe leggere il
    file vero durante un collaudo -- cioe' giudicare una cosa diversa da quella che si voleva.

    ⛔ `ordine` e' obbligatorio e sta PRIMA dello schedario apposta: chi chiede lo stato di
    una casella deve dire di quale blocco parla, e non deve poterlo dimenticare. La stessa
    frase in due blocchi e' due domande diverse (vedi `chiave`).

    ⛔⛔ E LA SCADENZA GUARDA IL CODICE DEL BLOCCO, NON IL COMMIT (2026-08-21). Col commit,
    sei esami in sei sessioni non potevano MAI stare spuntati insieme: ogni sessione fa un
    commit, e ogni commit svuotava i cinque passati prima. Il traguardo era irraggiungibile
    per costruzione. Vedi `impronta_del_blocco` per il perche' per esteso.
    """
    dati = leggi() if schedario is None else schedario
    ora = impronta_del_blocco(ordine) if impronta is None else impronta
    riga = dati.get(chiave(testo, ordine))
    if not isinstance(riga, dict):
        return (False, "mai misurata: nessun attrezzo ha ancora scritto questa casella")
    if not ora:
        return (False, "non so QUALE codice guarda questa casella (il piano non si legge): "
                       "una misura senza ancoraggio non vale")
    suo = str(riga.get("impronta") or "")
    if suo != ora:
        return (False, "misurata quando il codice del blocco aveva impronta %s, adesso e' "
                       "%s: quei moduli sono cambiati sotto, e quella misura non parla piu' "
                       "di questo codice" % (suo or "(non indicata)", ora))
    denominatore = riga.get("denominatore")
    if not isinstance(denominatore, int) or denominatore <= 0:
        return (False, "denominatore %r: l'attrezzo non ha esaminato NIENTE, quindi il suo "
                       "esito non e' un giudizio (sbaglio S7)" % (denominatore,))
    if not riga.get("esito"):
        perche = riga.get("motivo") or ""
        return (False, "ROSSA: l'attrezzo l'ha misurata e non passa (%s)%s"
                % (riga.get("comando", "comando non indicato"),
                   (" -- perche': %s" % perche) if perche else ""))
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
        # L'impronta si calcola UNA volta per blocco, non per ogni casella: e' la stessa,
        # e ricalcolarla sei volte vorrebbe dire rileggere ventiquattro file sei volte.
        imp = impronta_del_blocco(b["ordine"])
        for c in condizioni:
            ok, motivo = stato(c, b["ordine"], dati, imp)
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
