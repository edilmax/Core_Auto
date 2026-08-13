# -*- coding: utf-8 -*-
"""🛬 PRE-FATTO — i controlli che l'11 agosto sono stati fatti A MANO, o non fatti affatto.

Fa tutto il PRE-VOLO (`collaudi/prima_di_lanciare.py`, sei controlli) e ci aggiunge i tre
che riguardano il momento del commit:

    7. NIENTE ARTEFATTI MIEI FUORI DAL REPOSITORY
       L'11 agosto un E2E contro Stripe VERO da 11 KB -- l'UNICO collaudo che prova i
       crediti contro Stripe vero -- e' rimasto in una cartella fuori dal progetto ed e'
       stato ritrovato PER FORTUNA, rileggendo. Nessuna guardia lo vedeva. Un attrezzo
       che sta fuori dal repository non viaggia con la chiavetta, non gira in CI, e il
       giorno che serve non c'e'.

    8. I FILE CAMBIATI SONO QUELLI CHE AVEVI DICHIARATO (regola ferrea 15)
       «Avevo dichiarato due file, ne ho toccati quattro. Il lavoro in piu' era buono, ma
       nessuno l'aveva autorizzato, e uno scopo che si allarga da solo e' il canale
       principale delle regressioni.»

    9. IL MESSAGGIO DI COMMIT
       Tre controlli fatti a mano l'11 agosto: nessun segnaposto, ASCII puro, e la riga
       della firma. Fatti a mano vuol dire che un giorno non si fanno.

COME SI USA
    python collaudi/prima_di_dire_fatto.py                 # i controlli 1-8
    python collaudi/prima_di_dire_fatto.py --messaggio F   # solo il 9, sul file F
Uscita 0 = si puo' salvare. Uscita 1 = fermo, e sotto c'e' scritto perche'.

Lo chiamano da soli i ganci di git, cosi' non dipende dal ricordarsene:
    deploy/hooks/pre-commit   -> i controlli 1-8
    deploy/hooks/commit-msg   -> il controllo 9 (e' l'unico gancio a cui git passa il
                                 messaggio: al `pre-commit` non esiste ancora)

⛔ IL CONTROLLO 8 PRETENDE CHE IL PRE-VOLO SIA GIRATO PRIMA. Deve sapere COSA avevi
   promesso di toccare, e quello glielo dice `prima_di_lanciare.py --scopo <file...>`.
   Senza traccia il controllo e' `NON ESEGUITO`, che non e' un successo (sbaglio S7):
   si ferma e stampa il comando da lanciare. Costa quattro secondi, ed e' il modo in cui
   «prima di aprire il primo file si scrive quali file si toccheranno» smette di
   dipendere dalla memoria di qualcuno.

⛔ UNA COSA CHE QUESTO STRUMENTO NON FA, ED E' UNA SCELTA DICHIARATA. La regola ferrea 15
   dice «`git status` deve contenere ESATTAMENTE i file dichiarati». Qui e' ROSSO solo il
   caso in cui si e' toccato qualcosa che NON era dichiarato -- che e' il danno vero, lo
   scopo che si allarga da solo. Aver dichiarato un file e poi non averlo toccato viene
   stampato come NOTA, non come rosso: accorgersi che un file non serviva e' buona
   pratica, e un falso allarme e' un difetto quanto un allarme mancato (regola ferrea 10).
"""
import io
import os
import re
import sys

QUI = os.path.dirname(os.path.abspath(__file__))
if QUI not in sys.path:
    sys.path.insert(0, QUI)

import prima_di_lanciare as pv          # noqa: E402  (dopo l'aggiustamento di sys.path)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RADICE = pv.RADICE
OK, ROSSO, NON_ESEGUITO = pv.OK, pv.ROSSO, pv.NON_ESEGUITO

# Cartelle di transito FUORI dal repository, dove un attrezzo puo' restare orfano.
# La prima si ricava dalla posizione del progetto, non e' cablata a una macchina.
CARTELLA_DI_TRANSITO = "DA_METTERE_IN_collaudi"
VARIABILE_CARTELLE = "BOOKINVIP_CARTELLE_DI_LAVORO"

# Segnaposto inequivocabili. Volutamente CORTA: «TODO» e «XXX» compaiono in messaggi
# legittimi («rimosso un TODO»), e un falso rosso insegna a ignorare lo strumento.
SEGNAPOSTO = ("__DA_RIEMPIRE__", "PLACEHOLDER", "FIXME", "TBD", "<inserisci")
FIRMA = "Co-Authored-By:"
INIZI_DI_FUSIONE = ("Merge pull request", "Merge branch", "Merge remote-tracking")

COSA_NON_GUARDA = pv.COSA_NON_GUARDA + (
    "gli artefatti orfani li cerca in `%s` accanto al progetto (piu' quelle elencate in "
    "%s): un file lasciato in una cartella qualsiasi del disco non lo vede nessuno"
    % (CARTELLA_DI_TRANSITO, VARIABILE_CARTELLE),
    "il confronto con lo scopo e' sui NOMI dei file, non su quante righe hai cambiato "
    "dentro ognuno",
    "il messaggio di commit lo controlla il gancio `commit-msg`, non questo giro: al "
    "`pre-commit` il messaggio non esiste ancora",
    "⛔ IL PATH NON VIENE CONFRONTATO (openssl). Questo giro parte da un gancio di git, "
    "cioe' da `sh`, che ha un PATH diverso dalla shell che lancera' la suite: da qui la "
    "risposta sarebbe opposta senza che nessuno abbia sbagliato niente (S11). Quel "
    "confronto lo fa il PRE-VOLO, che gira nella shell giusta",
    "il controllo 10 dichiara i PROPRI limiti dentro `collaudi/piano_dei_soldi.py` "
    "(`NON_CONTROLLO`, che li stampa con `python collaudi/piano_dei_soldi.py`), e non si "
    "ricopiano qui: sarebbero una seconda copia che resta indietro. Il piu' grosso: un "
    "modulo puo' risultare VIVO e avere dentro codice morto, perche' `raggiungibilita.py` "
    "conta gli IMPORT e non i SIMBOLI usati -- misurato su `fase133`, ~9 righe vive su 142",
)


# --------------------------------------------------------------------------------------
# 7. niente artefatti miei fuori dal repository
# --------------------------------------------------------------------------------------
def cartelle_di_transito(radice=RADICE):
    """Dove cercare. La cartella accanto al progetto si ricava, non si caccia dentro il
    codice un percorso che vale su un computer solo."""
    trovate = [os.path.join(os.path.dirname(radice), CARTELLA_DI_TRANSITO)]
    for extra in os.environ.get(VARIABILE_CARTELLE, "").split(os.pathsep):
        if extra.strip():
            trovate.append(extra.strip())
    return trovate


def _nomi_python_nel_repo(radice):
    """I nomi (senza percorso) di tutti i `.py` del repository, tracciati e non. `None`
    se git non risponde: senza l'elenco non si puo' dire che un file «manca»."""
    tracciati = pv._git(radice, "ls-files", "*.py")
    nuovi = pv._git(radice, "ls-files", "--others", "--exclude-standard", "*.py")
    if tracciati is None or nuovi is None:
        return None
    nomi = set()
    for blocco in (tracciati, nuovi):
        for riga in blocco.splitlines():
            if riga.strip():
                nomi.add(os.path.basename(riga.strip()))
    return nomi


def controllo_8_artefatti_fuori(radice=RADICE, cartelle=None):
    cartelle = cartelle_di_transito(radice) if cartelle is None else list(cartelle)
    esistenti = [c for c in cartelle if os.path.isdir(c)]
    if not esistenti:
        return (OK, "nessuna cartella di transito da esaminare (cercate: %s)"
                % ", ".join(os.path.basename(c) or c for c in cartelle))
    dentro = _nomi_python_nel_repo(radice)
    if dentro is None:
        return (NON_ESEGUITO, "git non risponde: non so quali file stanno nel "
                              "repository, quindi non posso dire quali sono orfani")
    orfani = []
    guardati = 0
    for cartella in esistenti:
        for nome in sorted(os.listdir(cartella)):
            if not nome.endswith(".py"):
                continue
            guardati += 1
            if nome in dentro:
                continue
            percorso = os.path.join(cartella, nome)
            orfani.append("%s (%d byte)" % (percorso, os.path.getsize(percorso)))
    if orfani:
        return (ROSSO, "questi attrezzi stanno FUORI dal repository e nel progetto non "
                       "esiste nessun file con quel nome: non viaggiano con la "
                       "chiavetta, non girano in CI, e il giorno che servono non ci "
                       "sono.\n      " + "\n      ".join(orfani))
    return (OK, "%d file .py nelle cartelle di transito, tutti presenti nel repository"
            % guardati)


# --------------------------------------------------------------------------------------
# 8. i file cambiati sono quelli dichiarati
# --------------------------------------------------------------------------------------
def _normalizza(percorsi):
    puliti = set()
    for p in percorsi:
        p = p.strip().replace("\\", "/").lstrip("./")
        if p:
            puliti.add(p)
    return puliti


def confronta_scopo(dichiarati, toccati):
    """(fuori_elenco, dichiarati_e_non_toccati). Isolato perche' si possa provare da solo,
    senza un repository vero intorno."""
    a, b = _normalizza(dichiarati), _normalizza(toccati)
    return sorted(b - a), sorted(a - b)


def controllo_9_scopo(radice=RADICE, dichiarati=None, toccati=None, traccia=None):
    """`traccia` serve alle guardie per puntare a una traccia che NON esiste e provare il
    ramo «nessuno scopo dichiarato». Senza questo parametro la guardia leggeva la traccia
    VERA della macchina su cui girava: verde qui, rossa in CI -- cioe' un test che dipende
    da dove lo lanci, che e' la forma piu' subdola di verde finto (S11)."""
    if dichiarati is None:
        dichiarati = pv.leggi_scopo(traccia)
    if dichiarati is None:
        return (NON_ESEGUITO,
                "nessuno scopo dichiarato: non so cosa avevi promesso di toccare, quindi "
                "non posso dire se ti sei allargato. Dichiaralo (costa 4 secondi):\n"
                "      python collaudi/prima_di_lanciare.py --scopo <file1> <file2> ...")
    if toccati is None:
        toccati = pv.file_toccati(radice)
    if toccati is None:
        return (NON_ESEGUITO, "git non risponde: non so quali file sono stati toccati")
    fuori, non_toccati = confronta_scopo(dichiarati, toccati)
    nota = ""
    if non_toccati:
        nota = ("\n      NOTA (non e' un rosso): dichiarati e non toccati -> %s"
                % ", ".join(non_toccati))
    if fuori:
        return (ROSSO, "questi file sono cambiati ma NON erano nello scopo dichiarato. "
                       "Uno scopo che si allarga da solo e' il canale principale delle "
                       "regressioni (regola ferrea 15): fermati, aggiorna la "
                       "dichiarazione col PERCHE', e solo allora procedi.\n      %s%s"
                % ("\n      ".join(fuori), nota))
    return (OK, "%d file toccati, tutti dichiarati%s" % (len(_normalizza(toccati)), nota))


# --------------------------------------------------------------------------------------
# 9. il messaggio di commit
# --------------------------------------------------------------------------------------
def controllo_9_messaggio(testo=None, percorso=None):
    """Le righe che git commenta con `#` non fanno parte del messaggio e non si giudicano.

    ⛔ Le fusioni sono esentate dalla firma: `Merge pull request #28 from ...` lo scrive
    git, non chi lavora. Misurato sugli ultimi 40 commit di questo repository: 21 hanno la
    firma, 19 sono fusioni. Pretenderla anche li' sarebbe un falso rosso a ogni unione."""
    if testo is None:
        if percorso is None or not os.path.isfile(percorso):
            return (NON_ESEGUITO, "nessun messaggio da esaminare (percorso: %r)" % percorso)
        with io.open(percorso, encoding="utf-8", errors="replace") as f:
            testo = f.read()
    utili = [r for r in testo.splitlines() if not r.lstrip().startswith("#")]
    corpo = "\n".join(utili).strip()
    problemi = []
    if not corpo:
        return (ROSSO, "il messaggio di commit e' vuoto")
    for s in SEGNAPOSTO:
        if s.lower() in corpo.lower():
            problemi.append("contiene il segnaposto %r: e' un messaggio non finito" % s)
    non_ascii = sorted({c for c in corpo if ord(c) > 127})
    if non_ascii:
        problemi.append("contiene %d caratteri non-ASCII (%s): questo repository li "
                        "tiene fuori dai messaggi perche' passano per shell, ganci e "
                        "terminali con codifiche diverse, ed e' l'ultimo posto dove si "
                        "vuole scoprire un problema di codifica"
                        % (len(non_ascii), " ".join(repr(c) for c in non_ascii[:6])))
    e_fusione = corpo.startswith(INIZI_DI_FUSIONE)
    if not e_fusione and FIRMA not in corpo:
        problemi.append("manca la riga `%s`: senza di lei non si sa chi ha scritto questo "
                        "lavoro" % FIRMA)
    if problemi:
        return (ROSSO, "il messaggio di commit non va bene:\n      "
                + "\n      ".join(problemi))
    return (OK, "%d righe utili%s, nessun segnaposto, ASCII puro, firma %s"
            % (len(utili), " (fusione)" if e_fusione else "",
               "non richiesta" if e_fusione else "presente"))


# --------------------------------------------------------------------------------------
# il giro
# --------------------------------------------------------------------------------------
def controllo_4_ambiente_senza_il_path(radice=RADICE):
    """⛔ QUI IL CONFRONTO SUL PATH SI SPEGNE, E NON E' UNA COMODITA'.

    Trovato al primo giro vero dentro il gancio `pre-commit`, il 2026-08-11: il controllo
    e' uscito ROSSO dicendo «la riga AMBIENTE dice openssl NON nel PATH, ma qui c'e'».
    Aveva ragione: i ganci di git girano sotto `sh`, e Git per Windows porta con se'
    `/mingw64/bin/openssl` -- mentre da PowerShell, che e' la shell da cui parte la suite,
    openssl NON c'e'. La stessa domanda, due risposte opposte: e' lo sbaglio S11 preso
    dallo strumento su se stesso.

    Ma un giudizio giusto nel posto sbagliato e' un allarme che suona a OGNI salvataggio,
    e un allarme che suona sempre viene spento (regola ferrea 10) -- e allora non protegge
    piu' niente, che era proprio la trappola da non ripagare. Al momento del commit non si
    sta lanciando nessuna suite: cio' che dipende dalla shell non c'entra. Resta il
    confronto su Python e sulle librerie, che vengono dall'interprete e non dal PATH.
    ⛔ E la rinuncia si DICHIARA (D18 punto 3): sta nell'elenco qui sotto."""
    return pv.controllo_4_ambiente(radice=radice, confronta_path=False)


# --------------------------------------------------------------------------------------
# 10. il piano dei soldi non si contraddice
# --------------------------------------------------------------------------------------
# PERCHE' STA QUI E NON SOLO NELLA SUITE. Il guardiano `test_piano_dei_soldi.py` gira dentro
# `unittest discover`, cioe' dentro un ciclo da ~25 minuti. Finche' era solo li', si POTEVA
# committare un piano contraddittorio e lo si scopriva mezz'ora dopo -- o alla CI, dopo il
# push. E' esattamente il difetto di TEMPO che questo file esiste per curare («il difetto era
# QUANDO giravano»), applicato a se stesso. Il giudizio costa 0,1 secondi.
# ⛔ E' anche la regola 23 dell'appendice, «COSTRUITO != COLLEGATO»: un controllo che nessuno
# esegue nel momento della decisione misura se stesso, non il lavoro.
#
# ⛔ PERCHE' 10 E NON 9. Il 9 esiste: e' `controllo_9_messaggio`, e vive FUORI da `CONTROLLI`
# perche' gira su un altro gancio (`commit-msg`), l'unico a cui git passa il messaggio. Il
# buco nella numerazione e' voluto e dichiarato: riusare il 9 renderebbe ambigui i rapporti.
def controllo_10_piano_dei_soldi(radice=RADICE, registro=None, consegne=None, morti=None):
    """I tre posti che dichiarano «faseNN e' FATTO» dicono la stessa cosa?

    ⛔ Il giudizio NON e' scritto qui: sta in `collaudi/piano_dei_soldi.py`, in un posto solo,
    e lo usano anche `test_piano_dei_soldi.py` e chiunque a mano. Una seconda copia del
    criterio sarebbe la malattia che quel guardiano esiste per curare.
    I tre testi si possono INIETTARE, ed e' quello che permette di provare questo controllo
    nelle due direzioni senza sporcare i documenti veri (D19).
    """
    try:
        import piano_dei_soldi as pds
    except ImportError as errore:
        return (NON_ESEGUITO,
                "`collaudi/piano_dei_soldi.py` non si importa (%s): il giudizio sul piano "
                "dei soldi non c'e' piu'. Non e' un verde -- e' il controllo che manca."
                % errore)
    if morti is None:
        try:
            import raggiungibilita
            morti = raggiungibilita.cammina()[1]
        except Exception as errore:
            return (NON_ESEGUITO,
                    "`collaudi/raggiungibilita.py` non risponde (%s): senza l'elenco dei "
                    "moduli morti non posso dire se il piano manda a setacciare codice che "
                    "la produzione non raggiunge" % errore)
    try:
        if registro is None:
            registro = pds.leggi(pds.REGISTRO, radice)
        if consegne is None:
            consegne = pds.leggi(pds.CONSEGNE, radice)
    except OSError as errore:
        return (NON_ESEGUITO, "non riesco a leggere i documenti del piano: %s" % errore)
    try:
        va_bene, righe = pds.rapporto(registro, consegne, morti)
        quanti = len(set(m for m, _s, _d in pds.osservazioni(registro, consegne)))
    except pds.MisuraNonValida as errore:
        return (NON_ESEGUITO, "%s" % errore)
    if not va_bene:
        return (ROSSO, "\n      ".join(righe))
    return (OK, "%d moduli dei soldi, i tre posti sono d'accordo e nessuno di quelli «da "
                "fare» e' codice morto" % quanti)


CONTROLLI = tuple(
    (numero, nome, controllo_4_ambiente_senza_il_path if numero == 4 else funzione)
    for numero, nome, funzione in pv.CONTROLLI
) + (
    # ⛔ QUESTI NUMERI CONTINUANO QUELLI DEL PRE-VOLO, NON RIPARTONO DA CAPO. Il 2026-08-13
    # il pre-volo ha preso un controllo nuovo (il 7, le bombe a tempo) e qui c'erano DUE
    # controlli numerati 7: la guardia `test_IL_PATH_NON_SI_CONFRONTA_MA_IL_RESTO_SI` l'ha
    # visto subito (`[..., 7, 7, 8, 10]`). Chi aggiunge un controllo al pre-volo deve far
    # scalare anche questi -- e i NOMI delle funzioni seguono il numero, se no fra sei mesi
    # `controllo_7_*` sara' il controllo 8 e chi legge inseguira' un numero che mente.
    (8, "niente artefatti miei fuori dal repository", controllo_8_artefatti_fuori),
    (9, "i file cambiati sono quelli dichiarati", controllo_9_scopo),
    (10, "il piano dei soldi non si contraddice", controllo_10_piano_dei_soldi),
)


def batteria_dal_regolamento(radice=RADICE):
    """Le righe della tabella dei 10 collaudi, lette da `CLAUDE.md`. `[]` se non si trova.

    ⛔ IL TESTO NON E' SCRITTO QUI. Ricopiare la tabella renderebbe questo promemoria capace
    di dire il falso il giorno che la tabella cambia -- e sarebbe esattamente il difetto che
    D24 nasce per impedire: lo stesso fatto in due posti, e la copia che resta indietro.
    ⛔ Si taglia DOPO il titolo «I 10 COLLAUDI, IN QUEST'ORDINE» perche' poco sopra c'e' la
    tabella degli 11 modi di rompersi, che ha la stessa forma: senza il taglio si stamperebbe
    quella, cioe' il promemoria sbagliato con l'aria di essere giusto.
    """
    try:
        with io.open(os.path.join(radice, "CLAUDE.md"), encoding="utf-8") as f:
            testo = f.read()
    except OSError:
        return []
    coda = testo.split("I 10 COLLAUDI, IN QUEST'ORDINE")[-1]
    return re.findall(r"^\|\s*(\d+)\s*\|([^|]+)\|([^|]+)\|", coda, re.M)


def stampa_la_batteria(radice=RADICE):
    """⛔ D24 — prima di dire «fatto» si rilegge LA BATTERIA, non solo i sei divieti.

    Dettata dal fondatore il 2026-08-12, dopo che avevo dichiarato «provata nelle due
    direzioni» avendo passato i livelli ① e ② e ZERO dei dieci collaudi, col giudice esterno
    e la CI mai sfiorati. Un divieto non violato non e' una dimostrazione che funziona.
    """
    righe = batteria_dal_regolamento(radice)
    print("=" * 86)
    print("⛔⛔ E LA BATTERIA? (D24) — si rilegge PRIMA e DOPO, e «i test» sono anche "
          "QUELLI ESTERNI")
    print("=" * 86)
    if not righe:
        print("  ⛔ LA TABELLA DEI 10 COLLAUDI NON SI TROVA in CLAUDE.md.")
        print("     Non e' un verde: e' il promemoria che ha smesso di funzionare. Va")
        print("     riletta a mano, sezione «REGOLA DEI 10 COLLAUDI».")
    else:
        for numero, nome, cerca in righe:
            print("  %2s. %-30s %s" % (numero, nome.strip().replace("**", "")[:30],
                                       cerca.strip().replace("**", "")[:44]))
        print()
        print("  Per OGNUNO: l'esito, OPPURE il motivo dichiarato per cui non si applica.")
        print("  Un collaudo senza esito e senza motivo non e' un successo: e' NON ESEGUITO")
        print("  (sbaglio S7), e sarebbe il verde peggiore -- quello che non ha guardato.")
    print()
    print("  ⛔ E «QUELLI ESTERNI» sono le due cose che questo computer NON puo' darti:")
    print("     · il GIUDICE ESTERNO (collaudo 7): uno strumento NON nostro che conferma")
    print("     · la CI SU LINUX (regola ferrea 8): il verde locale e' un INDIZIO. Il")
    print("       giudice e' la tabella dei job letta dall'API, mai «immagino sia verde»")
    print("=" * 86)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    radice = RADICE

    if "--messaggio" in argv:
        percorso = argv[argv.index("--messaggio") + 1]
        stato, dettaglio = controllo_9_messaggio(percorso=percorso)
        print("=" * 86)
        print("🛬 PRE-FATTO — controllo 9: il messaggio di commit")
        print("=" * 86)
        print("  %-13s %s" % (stato, dettaglio))
        if stato == OK:
            return 0
        print("=" * 86)
        print("VERDETTO: ⛔ COMMIT FERMO. Correggi il messaggio e riprova.")
        return 1

    mancanti = pv._precondizioni(radice)
    if mancanti:
        print("⛔ PRE-FATTO NON ESEGUITO — non sono in condizione di misurare (D18 punto 1)")
        for m in mancanti:
            print("   · %s" % m)
        return 1

    import time
    inizio = time.time()
    esiti = pv.giro(radice, CONTROLLI)
    secondi = time.time() - inizio
    pv.stampa(esiti, secondi, titolo="🛬 PRE-FATTO", non_guarda=COSA_NON_GUARDA)

    # ⛔ DOPO aver finito l'operazione: i sei divieti si rileggono. «Prima di iniziare
    # un'operazione E DOPO averla finita» -- cosi' la fine di un lavoro non diventa
    # l'inizio di una violazione. Non e' una decorazione: e' il momento in cui si sta per
    # committare, cioe' quello in cui B1 e B4 contano piu' che mai.
    print()
    print("⛔⛔ E ADESSO SI RILEGGONO, PERCHE' HAI FINITO — e stai per salvare.")
    pv.stampa_divieti(radice)
    stampa_la_batteria(radice)

    rossi, non_eseguiti = pv.verdetto(esiti)
    print("=" * 86)
    if rossi or non_eseguiti:
        print("VERDETTO: ⛔ NON E' FATTO — %d rosso/i, %d non eseguito/i. Commit fermo."
              % (len(rossi), len(non_eseguiti)))
        print("Un `NON ESEGUITO` non e' un successo: e' un controllo che non ha guardato")
        print("niente, e sarebbe il verde peggiore di tutti (sbaglio S7).")
        return 1
    print("VERDETTO: ✅ SI PUO' SALVARE — %d controlli, 0 rossi, 0 non eseguiti."
          % len(esiti))
    print("⛔ Ricorda che questo NON sostituisce la suite intera (regola ferrea 6): dice")
    print("   che il lavoro e' in ordine, non che il prodotto funziona.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
