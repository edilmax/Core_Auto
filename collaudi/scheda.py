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


def impronte_dei_moduli(ordine, radice=RADICE):
    """{modulo: impronta} per ogni modulo del blocco. Serve a dire QUALE e' cambiato.

    ⛔⛔ PERCHE' ESISTE, ed e' una domanda del fondatore del 2026-09-09: *«andiamo avanti e
    poi indietro, non capisco»*. Una casella scaduta diceva soltanto *«aveva impronta
    1e861914e310, adesso e' 736625024342»* -- due identita' illeggibili al posto dell'unica
    cosa su cui si puo' agire: **quale file e' cambiato**. Per rispondergli quel giorno ho
    dovuto scrivere uno script apposta, cioe' l'attrezzo non stava dicendo cio' che sapeva.
    ⚠️ Il totale (`impronta_del_blocco`) NON si ricava sommando queste: resta il criterio di
    scadenza, e questo e' il modo di **spiegarla**. Due strumenti, due domande diverse.
    """
    percorso = os.path.join(QUI, "piano.py")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_piano_per_modulo", percorso)
        piano = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(piano)
        blocchi = [b for b in piano.BLOCCHI if b["ordine"] == ordine]
        if len(blocchi) != 1:
            return {}
        moduli = sorted(blocchi[0].get("moduli") or ())
    except Exception:
        return {}
    fuori = {}
    for nome in moduli:
        h = hashlib.sha256()
        try:
            with io.open(os.path.join(radice, nome + ".py"), "rb") as f:
                # Stessa normalizzazione del totale: i fine riga non sono codice (D23).
                h.update(f.read().replace(b"\r\n", b"\n"))
        except OSError:
            h.update(b"(assente)")
        fuori[nome] = h.hexdigest()[:12]
    return fuori


def _moduli_cambiati(riga, ordine):
    """I nomi dei moduli che sono cambiati da quando la casella e' stata scritta.

    Torna `None` se non si puo' sapere: le righe scritte prima del 2026-09-09 non portano le
    impronte dei singoli moduli, e **inventare un colpevole sarebbe peggio che tacere** (S1:
    il vuoto non e' un valore). In quel caso il motivo resta quello vecchio, dichiarato.
    """
    allora = riga.get("impronte_moduli")
    if not isinstance(allora, dict) or not allora:
        return None
    adesso = impronte_dei_moduli(ordine)
    if not adesso:
        return None
    cambiati = [n for n in sorted(set(allora) | set(adesso))
                if allora.get(n) != adesso.get(n)]
    return cambiati


def _perche_scaduta(riga, ordine, suo, ora):
    """Il motivo della scadenza, in italiano e con i NOMI quando si sanno."""
    cambiati = _moduli_cambiati(riga, ordine)
    if cambiati is None:
        return ("misurata quando il codice del blocco aveva impronta %s, adesso e' %s: quei "
                "moduli sono cambiati sotto, e quella misura non parla piu' di questo codice. "
                "⚠️ QUALI moduli non si sa: questa riga e' stata scritta prima che lo "
                "schedario registrasse le impronte dei singoli file. Si rilancia l'attrezzo "
                "(`%s`) e da li' in avanti lo dira'."
                % (suo or "(non indicata)", ora, riga.get("comando", "?")))
    if not cambiati:
        return ("l'impronta del blocco non coincide (%s -> %s) ma nessun modulo risulta "
                "cambiato: e' cambiato l'ELENCO dei moduli nel piano, oppure lo schedario "
                "e' stato scritto a mano. Si rilancia l'attrezzo: `%s`"
                % (suo or "(non indicata)", ora, riga.get("comando", "?")))
    return ("SCADUTA perche' sono cambiati questi file: %s. La misura parlava del codice di "
            "allora, non di questo. Non e' un guasto: si rilancia `%s` e la casella torna a "
            "dire la verita' di oggi."
            % (", ".join(cambiati), riga.get("comando", "?")))


def da_rimisurare(schedario=None):
    """(eseguibili, a_mano): le caselle scadute e l'attrezzo che le rimette.

    ⛔ DICHIARA CIO' CHE NON PUO' FARE DA SOLO. Alcuni attrezzi vogliono materiale preso sul
    server (le letture del deploy, un archivio di salvataggio scaricato dal volume): il loro
    comando porta un segnaposto fra parentesi angolari. Quelli finiscono in `a_mano` invece
    di sparire: un elenco che tace sulle proprie esclusioni fa sembrare «coperto» cio' che
    non e' stato nemmeno guardato (D18 punto 3, sbaglio S7).
    """
    dati = leggi() if schedario is None else schedario
    eseguibili, a_mano = [], []
    for blocco in _blocchi():
        ordine = blocco["ordine"]
        impronta = impronta_del_blocco(ordine)
        for testo in blocco.get("finito_quando") or ():
            riga = dati.get(chiave(testo, ordine))
            if not isinstance(riga, dict):
                continue                      # mai misurata: non e' una RI-misura
            spuntata, motivo = stato(testo, ordine, schedario=dati, impronta=impronta)
            if spuntata:
                continue
            if not str(motivo).startswith(("SCADUTA", "misurata quando", "l'impronta")):
                continue                      # rossa o senza denominatore: e' un altro caso
            comando = str(riga.get("comando") or "")
            voce = {"blocco": ordine, "casella": testo[:70], "comando": comando,
                    "motivo": motivo}
            (a_mano if ("<" in comando and ">" in comando) else eseguibili).append(voce)
    return eseguibili, a_mano


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
        # ⛔ E L'IMPRONTA DI OGNI SINGOLO MODULO, dal 2026-09-09: senza, una casella scaduta
        #    puo' solo confrontare due totali illeggibili e chi legge non sa su cosa agire.
        #    Il fondatore ha dovuto chiedere «non capisco», e aveva ragione. Costa qualche
        #    riga nello schedario e trasforma un'identita' in una spiegazione.
        "impronte_moduli": impronte_dei_moduli(int(ordine)),
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
        return (False, _perche_scaduta(riga, ordine, suo, ora))
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


# ═══════════════════════════════════════════════════════════════════════════════════════
#  LA MISURA SEGUE IL CODICE — il cricchetto delle caselle (DECISIONE DEL METODO, 8/10/2026)
# ═══════════════════════════════════════════════════════════════════════════════════════
#  ⛔ PERCHE' ESISTE, misurato: l'8/10 `piano.py` contava 25 caselle da fare e 21 erano SOLO
#  SCADUTE -- le unioni cambiavano il codice dei blocchi e nessuno rimisurava, perche'
#  rimisurare era un gesto a mano (`rimisura.py`). Regola 2 della decisione: «una PR che fa
#  scadere una casella non si unisce se non la rimisura nella stessa PR». Il gate la fa
#  rispettare: `python collaudi/scheda.py --cricchetto HEAD^1 --riesegui` (job `caselle`).
#  Fonti (D25): SonarSource, «Clean as You Code» -- il gate guarda il codice NUOVO, e «nessun
#  problema nuovo» e' una condizione che non si allenta; Petrovic, Ivankovic, Fraser, Just,
#  «Practical Mutation Testing at Scale», IEEE TSE 2021 -- la mutazione sulle righe cambiate
#  (il passo `--diff` dello stesso job).
#  Guardia: `test_pipeline_ci.TestLaMisuraSegueIlCodice`.

# Le misure che in CI guarderebbero un'ALTRA cosa: la produzione, Stripe di prova, il server.
# Dalla CI misurerebbero il sito vivo, non il codice della PR (D23: l'ambiente fa parte della
# misura). Si rifanno a mano, una volta, alla chiusura del blocco. ⛔ L'elenco NON si allarga
# per comodita': la guardia pretende che ogni voce apra davvero la rete, paghi su Stripe o
# entri nel server, cosi' un esame che la CI sa fare non si toglie dal gate scrivendolo qui.
FUORI_CI = {
    "python collaudi/esame_accessi.py --casella matrice --scrivi":
        "interroga il SITO VIVO: dalla CI misurerebbe la produzione, non il codice della PR",
    "python collaudi/esame_accessi.py --casella sonde --scrivi":
        "interroga il SITO VIVO: dalla CI misurerebbe la produzione, non il codice della PR",
    "python collaudi/esame_plausibilita.py --scrivi":
        "legge i numeri dal SITO VIVO, non dal codice della PR",
    "python collaudi/esame_orologi.py --scrivi":
        "paga su Stripe di PROVA: la chiave sta sul computer del fondatore, non in CI",
    "python collaudi/esame_produzione.py --scrivi":
        "legge gli invarianti sulla macchina di PRODUZIONE (ssh)",
    "python collaudi/esame_produzione.py --casella ogni-ora --scrivi":
        "legge il registro del server di PRODUZIONE (ssh)",
    "python collaudi/esame_sentinella.py --scrivi":
        "legge la sentinella esterna sul sito vivo e l'API di GitHub",
}
TETTO_RIFAI_SEC = 3600       # un esame che in CI non finisce in un'ora e' appeso, non lento

NON_GUARDA_CRICCHETTO = (
    "non giudica se la condizione e' giusta ne' se l'attrezzo misura bene: confronta la scheda "
    "di master con quella della PR e, con --riesegui, rifa' l'attrezzo",
    "i TEST che cambiano non fanno scadere nessuna casella (l'impronta guarda solo i moduli del "
    "blocco): una PR che indebolisce un test non la ferma questo controllo",
    "le caselle FUORI_CI, quelle «a mano» e il giro di mutazione intero qui si DICHIARANO e non "
    "si rifanno: si rimisurano una volta, alla chiusura del blocco (le righe cambiate le "
    "sorveglia il passo `--diff` dello stesso job)",
    "una casella spuntata che SPARISCE dal piano (testo riscritto o tolto) si dichiara e non "
    "ferma: la decisione si legge nel diff di collaudi/piano.py",
    "--riesegui rifa' SOLO le righe che la PR ha scritto o cambiato: una spunta di master che "
    "la PR non tocca resta creduta com'era quando fu misurata",
)


def come_si_rimisura(comando):
    """Chi puo' rifare questa misura: 'a_mano' (vuole materiale preso sul server, il
    segnaposto fra <>), 'mutazione' (il giro intero dura ore: in CI vale il `--diff`),
    'fuori_ci' (vedi FUORI_CI) oppure 'ci'."""
    comando = " ".join(str(comando or "").split())
    if "<" in comando and ">" in comando:
        return "a_mano"
    if "mutazione_prodotto.py" in comando:
        return "mutazione"
    if comando in FUORI_CI:
        return "fuori_ci"
    return "ci"


def stati_dell_albero(radice):
    """{chiave: casella} per ogni condizione del piano DI QUELL'ALBERO, giudicata con lo
    `scheda.py` DI QUELL'ALBERO: le sue regole, il suo piano, la sua scheda, i suoi moduli.

    ⛔ Giudicare master con le regole della PR (o viceversa) confronterebbe due cose diverse:
    ogni albero si giudica da se', e poi si confrontano i due giudizi.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_scheda_di_un_albero", os.path.join(radice, "collaudi", "scheda.py"))
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    dati = modulo.leggi()
    fuori = {}
    for blocco in modulo._blocchi():
        ordine = blocco["ordine"]
        impronta = modulo.impronta_del_blocco(ordine)
        for testo in blocco.get("finito_quando") or ():
            k = modulo.chiave(testo, ordine)
            spuntata, motivo = modulo.stato(testo, ordine, schedario=dati, impronta=impronta)
            riga = dati.get(k) if isinstance(dati.get(k), dict) else None
            fuori[k] = {"chiave": k, "blocco": ordine, "testo": " ".join(str(testo).split()),
                        "spuntata": bool(spuntata), "motivo": str(motivo),
                        "comando": str((riga or {}).get("comando") or ""), "riga": riga}
    return fuori


def confronta(prima, dopo):
    """Il giudizio, puro: {'rossi', 'dichiarati', 'da_rifare'} fra master (prima) e la PR.

    · ROSSA: spuntata su master, non piu' spuntata nella PR, e la CI la sa rimisurare; oppure
      una QUALUNQUE che la PR ha lasciato rossa, senza denominatore o senza riga: «a mano»
      copre una misura che manca, mai un rosso trovato.
    · DICHIARATA: spuntata su master e SCADUTA nella PR, ma da rifare a mano, sulla
      produzione, con Stripe di prova o col giro di mutazione intero (alla chiusura del
      blocco); spuntata e SPARITA dal piano; scritta dalla PR ma non rifacibile in CI.
    · DA RIFARE IN CI: ogni riga della scheda che la PR ha scritto o cambiato, spuntata, e
      misurabile in CI.
    """
    ordine = lambda kv: (kv[1]["blocco"], kv[1]["testo"])  # noqa: E731
    rossi, dichiarati, da_rifare = [], [], []
    for k, v in sorted(prima.items(), key=ordine):
        if not v["spuntata"]:
            continue
        d = dopo.get(k)
        if d is None:
            dichiarati.append(dict(v, perche="spuntata su master e SPARITA dal piano della PR "
                                             "(condizione riscritta o tolta)"))
            continue
        if d["spuntata"]:
            continue
        modo = come_si_rimisura(d["comando"] or v["comando"])
        scaduta = d["motivo"].startswith(("SCADUTA", "misurata quando", "l'impronta"))
        if modo == "ci" or not scaduta:
            rossi.append(dict(d, perche="spuntata su master, nella PR no: %s" % d["motivo"]))
        else:
            dichiarati.append(dict(d, perche="scaduta, si rimisura alla chiusura del blocco "
                                             "(%s)" % modo))
    for k, d in sorted(dopo.items(), key=ordine):
        p = prima.get(k)
        if not d["spuntata"] or (p is not None and p["riga"] == d["riga"]):
            continue
        modo = come_si_rimisura(d["comando"])
        if modo == "ci":
            da_rifare.append(d)
        else:
            dichiarati.append(dict(d, perche="scritta dalla PR, la CI non puo' rifarla (%s)"
                                             % modo))
    return {"rossi": rossi, "dichiarati": dichiarati, "da_rifare": da_rifare}


def _rifai(comandi, radice):
    """{comando: (uscita, coda dell'uscita)}: uno alla volta, l'uscita letta DIRETTA (ferrea 7)."""
    import shlex
    esiti = {}
    for comando in comandi:
        pezzi = shlex.split(comando, posix=True)
        if pezzi and pezzi[0] in ("python", "python3", "py"):
            pezzi[0] = sys.executable
        try:
            p = subprocess.run(  # nosec B603 - comandi letti dalla scheda del progetto, mai input esterno  # noqa: S603
                pezzi, cwd=radice, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=TETTO_RIFAI_SEC,
                env=dict(os.environ, PYTHONIOENCODING="utf-8"))
            esiti[comando] = (p.returncode, (p.stdout + p.stderr)[-1200:])
        except subprocess.TimeoutExpired:
            esiti[comando] = ("SCADUTO dopo %ds" % TETTO_RIFAI_SEC, "")
    return esiti


def cricchetto(base, radice=RADICE, riesegui=False):
    """(uscita, giudizio): 0 nessuna casella persa, 1 ROSSO, 2 non ho potuto misurare.

    `base` e' il commit di master (in CI: HEAD^1 del commit d'unione). Si apre in un albero a
    parte (`git worktree`), si giudica con le SUE regole, si confronta con l'albero della PR.
    """
    import shutil
    import tempfile
    righe = []
    giudizio = {"rossi": [], "dichiarati": [], "da_rifare": [], "rifatte": [], "righe": righe}
    culla = tempfile.mkdtemp(prefix="cricchetto_base_")
    albero = os.path.join(culla, "base")
    git = ["git", "-C", radice]
    try:
        p = subprocess.run(git + ["worktree", "add", "--detach", albero, base],  # nosec B603 B607 - git, argomenti fissi  # noqa: S603 S607
                           capture_output=True, text=True, timeout=300)
        if p.returncode != 0:
            righe.append("⛔ FERMO: la base %r non si apre (%s): senza base non c'e' confronto, "
                         "e nessun confronto non e' «nessuna casella persa»"
                         % (base, (p.stderr or "").strip()[-200:]))
            return 2, giudizio
        try:
            prima = stati_dell_albero(albero)
        except Exception as e:  # noqa: BLE001 - una base che non si giudica e' una misura mancata, si dichiara
            righe.append("⛔ FERMO: la scheda della base non si giudica (%s: %s)"
                         % (type(e).__name__, e))
            return 2, giudizio
        finally:
            subprocess.run(git + ["worktree", "remove", "--force", albero],  # nosec B603 B607 - git, argomenti fissi  # noqa: S603 S607
                           capture_output=True, text=True, timeout=300)
    finally:
        shutil.rmtree(culla, ignore_errors=True)
        subprocess.run(git + ["worktree", "prune"],  # nosec B603 B607 - git, argomenti fissi  # noqa: S603 S607
                       capture_output=True, text=True, timeout=120)
    try:
        dopo = stati_dell_albero(radice)
    except Exception as e:  # noqa: BLE001 - idem: la PR che non si giudica non passa per verde
        righe.append("⛔ FERMO: la scheda della PR non si giudica (%s: %s)" % (type(e).__name__, e))
        return 2, giudizio
    if not prima or not dopo:
        righe.append("⛔ FERMO: nessuna casella letta (base %d, PR %d): il confronto non "
                     "misurerebbe niente (S1)" % (len(prima), len(dopo)))
        return 2, giudizio
    esito = confronta(prima, dopo)
    giudizio.update(esito)
    if riesegui and esito["da_rifare"]:
        comandi = sorted({v["comando"] for v in esito["da_rifare"]})
        esiti = _rifai(comandi, radice)
        riletti = stati_dell_albero(radice)
        for v in esito["da_rifare"]:
            uscita, coda = esiti[v["comando"]]
            ora = riletti.get(v["chiave"]) or {}
            if uscita == 0 and ora.get("spuntata"):
                giudizio["rifatte"].append(v)
            else:
                giudizio["rossi"].append(dict(v, perche="la PR la scrive spuntata, rifatta in "
                                                        "CI no: uscita %s, %s\n%s"
                                                        % (uscita, ora.get("motivo", "?"), coda)))
    n_prima = sum(1 for v in prima.values() if v["spuntata"])
    n_dopo = sum(1 for v in dopo.values() if v["spuntata"])
    righe.append("caselle spuntate: su master %d · nella PR %d · rosse %d · dichiarate %d · "
                 "da rifare in CI %d · rifatte e confermate %d%s"
                 % (n_prima, n_dopo, len(giudizio["rossi"]), len(giudizio["dichiarati"]),
                    len(giudizio["da_rifare"]), len(giudizio["rifatte"]),
                    "" if riesegui else " (senza --riesegui: non rifatte)"))
    for v in giudizio["rossi"]:
        righe.append("  ⛔ ROSSA  blocco %d  %s\n      %s\n      si rimisura: %s"
                     % (v["blocco"], v["testo"][:110], v["perche"][:900], v["comando"] or "?"))
    for v in giudizio["dichiarati"]:
        righe.append("  ⚠️  DICHIARATA  blocco %d  %s -- %s"
                     % (v["blocco"], v["testo"][:90], v["perche"]))
    for v in giudizio["rifatte"]:
        righe.append("  ✅ RIFATTA IN CI  blocco %d  %s" % (v["blocco"], v["testo"][:110]))
    righe.append("⛔ COSA QUESTO CONTROLLO NON GUARDA (D18 punto 3)")
    righe.extend("   · %s" % r for r in NON_GUARDA_CRICCHETTO)
    uscita = 1 if giudizio["rossi"] else 0
    righe.append("VERDETTO: %s" % ("✅ nessuna casella persa" if uscita == 0 else
                                   "⛔ la PR fa perdere caselle: si rimisurano NELLA STESSA PR"))
    return uscita, giudizio


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
    p.add_argument("--rimisura", action="store_true",
                   help="elenca gli attrezzi da rilanciare per le caselle SCADUTE")
    p.add_argument("--cricchetto", metavar="BASE", default=None,
                   help="ROSSO se una casella spuntata su BASE non lo e' piu' qui (il gate)")
    p.add_argument("--riesegui", action="store_true",
                   help="col --cricchetto: rifa' gli attrezzi delle righe scritte dalla PR")
    argomenti = p.parse_args(list(argv if argv is not None else sys.argv[1:]))
    if argomenti.cricchetto:
        print("=" * 78)
        print("🔒 IL CRICCHETTO DELLE CASELLE — base %s (decisione del metodo, 8/10)"
              % argomenti.cricchetto)
        print("=" * 78)
        uscita, giudizio = cricchetto(argomenti.cricchetto, riesegui=argomenti.riesegui)
        for r in giudizio["righe"]:
            print(r)
        return uscita
    if argomenti.rimisura:
        # ⛔ ELENCA, NON ESEGUE. Fra questi comandi ci sono giri di mutazione da 60 e da 600
        #    minuti: lanciarli «per comodita'» da un attrezzo di lettura sarebbe un gesto
        #    lungo deciso da chi non sapeva di deciderlo. Chi legge sceglie e lancia.
        eseguibili, a_mano = da_rimisurare()
        print("=" * 78)
        print("CASELLE SCADUTE — cosa rilanciare perche' il conto torni a dire OGGI")
        print("=" * 78)
        if not eseguibili and not a_mano:
            print("  nessuna casella scaduta: il conto parla del codice di adesso")
        visti = []
        for v in eseguibili:
            if v["comando"] in visti:
                continue
            visti.append(v["comando"])
            print("  blocco %-2d  %s" % (v["blocco"], v["comando"]))
        if a_mano:
            print()
            print("  ⛔ QUESTI NON SI POSSONO RILANCIARE DA SOLI: vogliono materiale preso")
            print("     sul server (letture del deploy, un archivio di salvataggio vero).")
            print("     Il segnaposto fra <> dice cosa manca.")
            for v in a_mano:
                print("  blocco %-2d  %s" % (v["blocco"], v["comando"]))
        print()
        print("  ⚠️  Un comando qui dentro puo' costare ore (i giri di mutazione dichiarano")
        print("      i loro minuti). Questo elenco NON li esegue: li mette in fila.")
        return 0
    return stampa(solo=argomenti.blocco)


if __name__ == "__main__":
    sys.exit(main())
