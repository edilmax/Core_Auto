# -*- coding: utf-8 -*-
"""🛫 PRE-VOLO — i controlli da DUE SECONDI che oggi si pagano in SESSANTOTTO MINUTI.

PERCHE' ESISTE, e non e' teoria. Questa macchina ha guardie sul CODICE e guardie sui
DOCUMENTI. Fino al 2026-08-11 non aveva **una sola guardia sul LAVORO**: ogni regola su
*come si lavora* -- misura il conto dei test prima di lanciare, aggiorna la riga delle
consegne, non lasciare artefatti fuori dal repository -- era affidata al ricordarsene.

Il dato che inchioda il problema non e' che quelle guardie mancassero: e' **QUANDO
girano**. Esistono gia', e girano dentro un ciclo da 68 minuti. Sono controlli da due
secondi messi in fondo a un'ora di attesa:

    sbaglio del 2026-08-11             chi l'ha preso              costo
    ---------------------------------  --------------------------  --------------
    uno `skipTest` zona cieca          guardia DENTRO la suite     68 minuti
    conto dei test non aggiornato      guardia DENTRO la suite     ~3 ore (3 volte)
    riga `CONSEGNE AGGIORNATE A:`      guardia DENTRO la suite     lasciato a domani

Qui gli stessi giudizi si danno PRIMA, in pochi secondi, sulla stessa macchina e dalla
stessa shell che lanciera' la suite (S11/D23: Bash e PowerShell hanno PATH diversi e
danno risposte opposte alla stessa domanda).

COME SI USA
    python collaudi/prima_di_lanciare.py
    python collaudi/prima_di_lanciare.py --scopo fase167.py test_credito.py
Uscita 0 = si puo' lanciare la suite.  Uscita 1 = fermo, e sotto c'e' scritto perche'.

`--scopo` dichiara quali file si toccheranno (regola ferrea 15) e lascia una traccia che
`collaudi/prima_di_dire_fatto.py` rilegge al momento del commit. E' lo stesso meccanismo
gia' usato per la mutazione (`collaudi/guardia_commit.py`): un obbligo affidato alla
memoria si rompe di nuovo, uno affidato a un attrezzo no.

⛔ LE QUATTRO CONDIZIONI D18, che questo strumento deve rispettare essendo esso stesso
   uno strumento che MISURA:
   1. misura prima se stesso -- se non riesce a fare un controllo lo dice e ESCE 1, non
      lo salta (`NON ESEGUITO` non e' mai un successo: sbaglio S7);
   2. e' provato nelle DUE direzioni -- grida col guasto dentro e tace a macchina sana
      (`test_pipeline_ci.TestIlPreVoloVedeIProblemiPRIMA`);
   3. dichiara cosa NON ha esaminato -- lo stampa a ogni giro, sotto i controlli;
   4. e' a sua volta sotto guardia -- se qualcuno lo toglie o lo indebolisce, la suite
      diventa rossa lo stesso giorno.

⛔ DEVE RESTARE VELOCE. Se supera i ~10 secondi la gente smette di lanciarlo, e allora
   non protegge piu' niente. Il tempo si misura e si stampa sempre; il TETTO lo fa
   rispettare una guardia dentro la suite, non un rosso qui -- perche' un pre-volo che
   fallisce per un disco lento sarebbe un falso allarme, e un falso allarme e' un difetto
   quanto un allarme mancato (regola ferrea 10).

⛔ NON DUPLICA LA SUITE. Fa solo i controlli ECONOMICI che storicamente causano il rosso
   CARO. Tutto il resto resta dov'e'.
"""
import collections
import contextlib
import importlib.util
import io
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

# ⛔ La console di Windows (cp1252) non regge i simboli: senza questa riga lo strumento
# ESPLODE invece di spiegarsi, e chi lo lancia vede un traceback al posto delle
# istruzioni. Stessa cura di `collaudi/guardia_commit.py`, per lo stesso motivo.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Il tetto dichiarato. Non e' un'opinione: sopra questa soglia lo strumento smette di
# essere usato, e uno strumento non usato non protegge niente.
TETTO_SECONDI = 10.0

# La traccia dello scopo dichiarato. Stesso posto e stessa logica della traccia di
# mutazione: vive fuori dal repository, cosi' non finisce mai in un commit.
TRACCIA_SCOPO = os.path.join(tempfile.gettempdir(), "bookinvip_scopo_dichiarato.txt")

OK = "OK"
ROSSO = "ROSSO"
NON_ESEGUITO = "NON ESEGUITO"

Esito = collections.namedtuple("Esito", "numero controllo stato dettaglio secondi")

_RIGA_CONSEGNE = re.compile(r"^CONSEGNE AGGIORNATE A:\s*([0-9a-fA-F]{7,40})\s*$", re.M)
# ⛔ ANCORATA A INIZIO RIGA, e non e' pedanteria: il 2026-08-11 il documento ha preso una
# FRASE che nominava `CONSEGNE AGGIORNATE A:` per spiegare una correzione, e da quel momento
# quel nome compariva DUE volte -- una in mezzo a un discorso, una come riga vera. Chi cerca
# senza ancora legge la prima che trova, cioe' la frase.
# MISURATO, non supposto: con una frase «...la riga SUITE ATTUALE: Ran 999 test non e' un
# dato...» messa sopra, la regola ancorata legge **5529** (il dato vero) e quella non
# ancorata legge **999**. L'ancoraggio cambia il verdetto.
# ⚠️ LIMITE DICHIARATO (D18 punto 3): protegge dalle menzioni IN MEZZO A UN DISCORSO, non da
# una frase scritta a COLONNA ZERO -- li' non c'e' differenza fra un dato e una frase, e
# nessuna espressione regolare puo' inventarsela. Dirlo e' meglio che far credere il
# contrario: la prima versione di questo commento prometteva di piu' di quanto l'ancoraggio
# faccia, ed e' stata la prova a smentirla.
_RIGA_SUITE = re.compile(r"^SUITE ATTUALE: Ran (\d+) test", re.M)
_RIGA_AMBIENTE = re.compile(r"^AMBIENTE:(.*(?:\n[ \t]+.*)*)", re.M)

# Estensioni che si leggono come testo. Un `.png` pieno di byte < 32 non e' un difetto:
# dichiarato qui invece di essere scoperto come falso rosso (D18 punto 3).
TESTUALI = (".py", ".md", ".yml", ".yaml", ".sh", ".txt", ".json", ".cfg", ".ini",
            ".toml", ".html", ".css", ".js")

COSA_NON_GUARDA = (
    "non esegue NEMMENO UN test: dice se la suite puo' partire, non se passera'",
    "il conto dei test CONTA, non giudica: duplicare 200 test lo soddisferebbe "
    "(appendice #14). La qualita' la misura la larghezza di mutazione",
    "i byte di controllo li cerca solo nei file TOCCATI e solo in quelli testuali "
    "(%s): un file gia' committato e sporco da prima non lo vede -- quello lo prende "
    "`test_NESSUN_file_python_contiene_byte_di_controllo`, dentro la suite"
    % " ".join(TESTUALI[:5]),
    "l'ambiente lo confronta con quello DICHIARATO in RIPRENDI_QUI.md: se la "
    "dichiarazione e' sbagliata, il confronto e' sbagliato con lei",
    "gli `skipTest` li giudica sui file `test_*.py` della radice, non su `collaudi/`",
    "le bombe a tempo NON le cerca adesso: legge lo schedario gia' misurato da "
    "`collaudi/bombe_a_tempo.py` (cercarle davvero costa ~25 minuti). Se quello schedario e' "
    "vecchio di piu' di 30 giorni questo controllo diventa ROSSO invece di tacere, perche' "
    "una misura scaduta non e' una misura",
)


# --------------------------------------------------------------------------------------
# appoggi
# --------------------------------------------------------------------------------------
def _leggi(percorso):
    with io.open(percorso, encoding="utf-8", errors="replace") as f:
        return f.read()


def _git(radice, *argomenti):
    """Uscita di un comando git, o None se git non risponde. Mai un'eccezione: un
    controllo che esplode e' un controllo che non ha misurato niente."""
    try:
        esito = subprocess.run(["git"] + list(argomenti), cwd=radice,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        return None
    if esito.returncode != 0:
        return None
    return esito.stdout.decode("utf-8", "replace")


def consegne_troppo_indietro(quanti_commit):
    """UNO e' il commit che porta le consegne stesse: quello e' sano. DUE vuol dire che
    dopo averle scritte si e' committato altro lavoro senza toccarle. `None` = non
    misurabile, e dove non si puo' misurare non si inventa un rosso.

    ⛔ Questo giudizio sta QUI, in un posto solo. `test_pipeline_ci.py` lo importa da qui
    invece di tenerne una copia: lo stesso criterio scritto due volte e' la malattia che
    questo progetto ha gia' pagato sei volte in un giorno -- la seconda copia resta
    indietro e nessuno se ne accorge."""
    return quanti_commit is not None and quanti_commit > 1


def _skip_sospetti(radice):
    """Delega al criterio VERO, quello che gira dentro la suite. Non una copia."""
    percorso = os.path.join(radice, "test_suite_senza_zone_cieche.py")
    if not os.path.isfile(percorso):
        return None
    spec = importlib.util.spec_from_file_location("_zone_cieche_prevolo", percorso)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    if not hasattr(modulo, "skip_sospetti"):
        return None
    return modulo.skip_sospetti(radice)


@contextlib.contextmanager
def _in_silenzio():
    """`discover()` importa ogni modulo di test, e parecchi stampano all'import (schemi,
    avvisi di configurazione). Quel rumore renderebbe illeggibile il rapporto. Si cattura
    tutto invece di buttarlo via: se qualcosa va storto, lo si puo' ancora mostrare."""
    catturato = io.StringIO()
    livello = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(catturato), contextlib.redirect_stderr(catturato):
            yield catturato
    finally:
        logging.disable(livello)


# --------------------------------------------------------------------------------------
# 1. il conto dei test dichiarato e' quello vero
# --------------------------------------------------------------------------------------
def controllo_1_conto_dei_test(radice=RADICE, pagina=None):
    """Evita lo sbaglio S14, che e' costato TRE ORE in tre occasioni distinte.

    Il conto NON dipende dall'esecuzione: lo da' il caricatore da fermo in due secondi.
    Il numero non e' invariante fra ambienti (misurato il 2026-08-06: 3.9 con hypothesis
    -> 5437, 3.11 senza -> 5362, perche' quattro moduli non si importano), quindi dove
    l'ambiente e' monco si pretende una cosa piu' debole ma vera: il dichiarato puo' solo
    essere MAGGIORE del raccolto."""
    import unittest
    if pagina is None:
        pagina = _leggi(os.path.join(radice, "RIPRENDI_QUI.md"))
    trovato = _RIGA_SUITE.search(pagina)
    if trovato is None:
        return (ROSSO, "RIPRENDI_QUI.md non dichiara piu' `SUITE ATTUALE: Ran N test`: "
                       "senza quella riga il numero torna a vivere nella testa di chi "
                       "scrive, che e' da dove veniva quello sbagliato (D22)")
    dichiarato = int(trovato.group(1))
    try:
        with _in_silenzio():
            suite = unittest.defaultTestLoader.discover(radice, pattern="test_*.py")
    except Exception as e:
        return (NON_ESEGUITO, "il caricatore non e' partito (%s: %s): senza il conto vero "
                              "non posso confrontare niente" % (type(e).__name__, e))

    def foglie(s):
        for x in s:
            if isinstance(x, unittest.TestSuite):
                for y in foglie(x):
                    yield y
            else:
                yield x

    rotti = sorted({t.id() for t in foglie(suite) if type(t).__name__ == "_FailedTest"})
    raccolti = suite.countTestCases()
    if rotti:
        if dichiarato > raccolti:
            return (OK, "dichiarato %d > raccolti %d, e in questo ambiente %d moduli non "
                        "si importano (%s): un ambiente monco puo' solo raccoglierne meno"
                    % (dichiarato, raccolti, len(rotti), ", ".join(rotti[:4])))
        return (ROSSO, "dichiarato %d, raccolti %d, e %d moduli non si importano (%s). Il "
                       "dichiarato dovrebbe essere MAGGIORE: se e' minore il documento e' "
                       "vecchio davvero. Rimisura con:\n"
                       "      python -c \"import unittest; print(unittest.TestLoader()"
                       ".discover('.', pattern='test_*.py').countTestCases())\""
                % (dichiarato, raccolti, len(rotti), ", ".join(rotti[:4])))
    if dichiarato == raccolti:
        return (OK, "%d == %d" % (dichiarato, raccolti))
    return (ROSSO, "RIPRENDI_QUI.md dichiara %d test, il caricatore ne raccoglie %d. "
                   "Scrivi %d nella riga `SUITE ATTUALE:` PRIMA di lanciare: dopo costa "
                   "un giro di suite intero (S14, gia' pagato tre volte)."
            % (dichiarato, raccolti, raccolti))


# --------------------------------------------------------------------------------------
# 2. la riga delle consegne non e' rimasta indietro
# --------------------------------------------------------------------------------------
def controllo_2_consegne(radice=RADICE, pagina=None):
    """Evita il rosso che l'11 agosto e' stato lasciato di proposito alla sessione dopo,
    perche' correggerlo a suite gia' partita avrebbe voluto dire rilanciarla."""
    if pagina is None:
        pagina = _leggi(os.path.join(radice, "RIPRENDI_QUI.md"))
    trovato = _RIGA_CONSEGNE.search(pagina)
    if trovato is None:
        return (ROSSO, "manca la riga `CONSEGNE AGGIORNATE A: <commit>` in "
                       "RIPRENDI_QUI.md: senza quella riga chi apre una chat nuova non "
                       "puo' sapere se il passaggio di consegne descrive lo stato di "
                       "adesso o quello di tre settimane fa (D21)")
    sha = trovato.group(1)
    uscita = _git(radice, "rev-list", "--count", "--no-merges", "%s..HEAD" % sha)
    if uscita is None:
        return (NON_ESEGUITO, "git non risponde su %s..HEAD: non posso misurare quanto "
                              "sono indietro le consegne (copia senza `.git`, clone "
                              "superficiale, o commit sconosciuto)" % sha)
    try:
        quanti = int(uscita.strip())
    except ValueError:
        return (NON_ESEGUITO, "git ha risposto %r, che non e' un numero" % uscita.strip())
    if consegne_troppo_indietro(quanti):
        return (ROSSO, "dal commit dichiarato (%s) sono passati %d commit di lavoro: le "
                       "consegne descrivono uno stato che non esiste piu'. Rimetti in "
                       "quella riga il commit di HEAD (`git rev-parse --short HEAD`) e "
                       "aggiorna il riquadro in cima a RIPRENDI_QUI.md (D21)."
                % (sha, quanti))
    return (OK, "%s -> %d commit di lavoro dopo (0 o 1 e' sano)" % (sha, quanti))


# --------------------------------------------------------------------------------------
# 3. nessuno skipTest nuovo che non sia ambientale
# --------------------------------------------------------------------------------------
def controllo_3_skip_interni(radice=RADICE):
    """I 68 minuti dell'11 agosto. La guardia esiste ed e' buona -- gira in 2,6 secondi --
    ma girava in fondo alla suite. Qui gira prima."""
    try:
        sospetti = _skip_sospetti(radice)
    except Exception as e:
        return (NON_ESEGUITO, "non sono riuscito a chiedere il giudizio a "
                              "test_suite_senza_zone_cieche (%s: %s)"
                % (type(e).__name__, e))
    if sospetti is None:
        return (NON_ESEGUITO, "test_suite_senza_zone_cieche.py non c'e' o non espone piu' "
                              "`skip_sospetti`: senza di lui questo controllo dovrebbe "
                              "ricopiarne il criterio, e una copia resta indietro")
    if sospetti:
        return (ROSSO, "%d test si assolvono da soli per una condizione che riguarda "
                       "cio' che dovrebbero verificare. Spariscono dal rapporto come "
                       "«skipped» e nessuno li legge piu': asserisci in ENTRAMBI i rami "
                       "invece di saltare.\n      %s"
                % (len(sospetti), "\n      ".join(sospetti[:6])))
    return (OK, "nessuno `skipTest` deciso da cio' che il test dovrebbe verificare")


# --------------------------------------------------------------------------------------
# 4. l'ambiente coincide con quello dichiarato
# --------------------------------------------------------------------------------------
def controllo_4_ambiente(pagina=None, radice=RADICE, quale_python=None, quale_openssl=None,
                         moduli_presenti=None, confronta_path=True):
    """⛔ MISURATO DALLA SHELL CHE LANCERA' LA SUITE, non da un'altra (S11/D23).

    Il 2026-08-10 la suite raccoglieva 5490 test e ne eseguiva 5485: cinque spariti. La
    causa (`openssl` fuori dal PATH) e' stata cercata da Bash, dove c'e' -- mentre la
    suite era partita da PowerShell, dove non c'e'. La stessa domanda, due risposte
    opposte. Qui la domanda la fa il processo stesso che sta per lanciare la suite.

    ⛔ `confronta_path=False` SPEGNE LA PARTE CHE DIPENDE DALLA SHELL, e c'e' un motivo
    misurato. Al primo giro vero dentro il gancio `pre-commit` questo controllo e' uscito
    ROSSO -- correttamente: i ganci di git girano sotto `sh`, dove Git per Windows porta
    `/mingw64/bin/openssl`, mentre da PowerShell openssl NON c'e'. La stessa domanda, due
    risposte opposte: **S11 preso dal proprio strumento**. Ma il giudizio, giusto in se',
    era nel posto sbagliato: al momento del commit non si sta lanciando nessuna suite, e
    un allarme che suona a ogni salvataggio viene spento -- e allora non protegge piu'
    niente (regola ferrea 10). Cosi' il pre-volo confronta TUTTO (e' la shell giusta), il
    pre-fatto confronta solo cio' che NON dipende dalla shell -- la versione di Python e
    le librerie, che vengono dall'interprete -- e DICHIARA di aver lasciato fuori il PATH.

    I parametri servono alle guardie per fingere una macchina diversa senza toccare
    questa: una difesa che non si puo' mettere alla prova non si sa se regge (D19)."""
    if pagina is None:
        pagina = _leggi(os.path.join(radice, "RIPRENDI_QUI.md"))
    trovato = _RIGA_AMBIENTE.search(pagina)
    if trovato is None:
        return (NON_ESEGUITO, "RIPRENDI_QUI.md non dichiara piu' una riga `AMBIENTE:`: "
                              "senza la dichiarazione non c'e' niente con cui confrontare "
                              "la macchina, e un numero senza l'ambiente che l'ha "
                              "prodotto non e' una misura, e' un ricordo (D22)")
    dichiarato = trovato.group(1)
    scarti = []

    atteso_py = re.search(r"Python (\d+\.\d+\.\d+)", dichiarato)
    vero_py = quale_python or "%d.%d.%d" % sys.version_info[:3]
    if atteso_py is None:
        scarti.append("la riga AMBIENTE non dichiara una versione di Python")
    elif atteso_py.group(1) != vero_py:
        scarti.append("Python dichiarato %s, qui gira %s" % (atteso_py.group(1), vero_py))

    # `openssl`: cinque guardie sul ripristino dei backup si mettono da parte IN BLOCCO
    # se manca, e unittest registra UN solo salto senza il nome della classe (D23 punto 3).
    ce_openssl = (shutil.which("openssl") is not None) if quale_openssl is None \
        else bool(quale_openssl)
    dichiarato_senza_openssl = re.search(r"openssl\s+NON\s+nel\s+PATH", dichiarato,
                                         re.I) is not None
    if confronta_path:
        if dichiarato_senza_openssl and ce_openssl:
            scarti.append("la riga AMBIENTE dice «openssl NON nel PATH», ma qui c'e': la "
                          "suite eseguira' cinque guardie in piu' di quelle dichiarate")
        if not dichiarato_senza_openssl and not ce_openssl:
            scarti.append("`openssl` NON e' nel PATH di questa shell, e la riga AMBIENTE "
                          "non lo dichiara: cinque guardie sul ripristino dei backup si "
                          "mettono da parte in blocco e il conto dei test cala senza "
                          "spiegazione")

    for nome, modulo in (("hypothesis", "hypothesis"), ("pyyaml", "yaml"),
                         ("coverage", "coverage")):
        if not re.search(nome, dichiarato, re.I):
            continue
        if moduli_presenti is not None:
            c_e = modulo in moduli_presenti
        else:
            c_e = importlib.util.find_spec(modulo) is not None
        if not c_e:
            scarti.append("la riga AMBIENTE dichiara `%s` installato, ma qui non si "
                          "importa: la suite raccogliera' meno test" % nome)

    if scarti:
        return (ROSSO, "la macchina non e' quella dichiarata in RIPRENDI_QUI.md:\n      "
                + "\n      ".join(scarti))
    if confronta_path:
        return (OK, "coincide con la riga AMBIENTE (Python %s · openssl %s)"
                % (vero_py, "presente" if ce_openssl else "assente"))
    return (OK, "Python %s e le librerie coincidono con la riga AMBIENTE. ⛔ NON ho "
                "confrontato il PATH (openssl): questa non e' la shell che lancera' la "
                "suite, e da qui la risposta sarebbe diversa senza che nessuno abbia "
                "sbagliato niente (S11)" % vero_py)


# --------------------------------------------------------------------------------------
# 5. nessuna traccia di mutazione aperta
# --------------------------------------------------------------------------------------
def controllo_5_traccia_mutazione(radice=RADICE, traccia=None):
    """Non riscrive il giudizio: chiama `collaudi/guardia_commit.py`, che e' il posto dove
    quel giudizio vive. Un giro di mutazione interrotto lascia un guasto DENTRO un file di
    produzione, ed e' gia' successo tre volte in un giorno."""
    percorso = os.path.join(radice, "collaudi", "guardia_commit.py")
    if not os.path.isfile(percorso):
        return (NON_ESEGUITO, "collaudi/guardia_commit.py non c'e' piu': senza di lui "
                              "nessuno sorveglia i giri di mutazione interrotti")
    spec = importlib.util.spec_from_file_location("_guardia_commit_prevolo", percorso)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    # ⛔ `quali` e' un ELENCO dal 2026-08-14: i biglietti sono uno per FILE, e possono
    # essere piu' d'uno (il Giudice gira anche dentro se stesso). Nominarne uno solo
    # darebbe una falsa fine: si rimette a posto quel file e si lancia con l'altro rotto.
    aperta, quali = modulo.mutazione_in_corso(traccia)
    if aperta:
        elenco = ", ".join(quali) if quali else "non indicato"
        return (ROSSO, "un giro di mutazione risulta APERTO (%d file coinvolto/i: %s). "
                       "Quel file potrebbe contenere un guasto messo di proposito: "
                       "lanciare la suite adesso significa giudicare codice rotto. "
                       "Istruzioni complete: python collaudi/guardia_commit.py"
                % (len(quali), elenco))
    return (OK, "nessun giro di mutazione aperto")


# --------------------------------------------------------------------------------------
# 6. nessun byte di controllo nei file toccati
# --------------------------------------------------------------------------------------
def file_toccati(radice=RADICE):
    """Modificati rispetto a HEAD + non tracciati. `None` se git non risponde."""
    modificati = _git(radice, "diff", "--name-only", "HEAD")
    nuovi = _git(radice, "ls-files", "--others", "--exclude-standard")
    if modificati is None or nuovi is None:
        return None
    insieme = set()
    for blocco in (modificati, nuovi):
        for riga in blocco.splitlines():
            if riga.strip():
                insieme.add(riga.strip())
    return sorted(insieme)


def controllo_6_byte_di_controllo(radice=RADICE, quali=None):
    """La trappola dell'heredoc (D9/B2). Il 2026-08-03 `audit_coerenza_tariffe.py`
    conteneva due byte 0x08 al posto di `\\b` in una espressione regolare: `\\bOTA\\b` era
    diventato `<BS>OTA<BS>`, quella parte della regola non combaciava MAI, e lo strumento
    continuava a girare dicendo di aver controllato."""
    if quali is None:
        quali = file_toccati(radice)
    if quali is None:
        return (NON_ESEGUITO, "git non risponde: non so quali file sono stati toccati, "
                              "quindi non posso cercare i byte invisibili")
    sporchi = []
    guardati = 0
    for relativo in quali:
        if not relativo.lower().endswith(TESTUALI):
            continue
        percorso = os.path.join(radice, relativo)
        if not os.path.isfile(percorso):
            continue
        guardati += 1
        with io.open(percorso, "rb") as f:
            dati = f.read()
        trovati = [(i, b) for i, b in enumerate(dati) if b < 32 and b not in (9, 10, 13)]
        if trovati:
            sporchi.append("%s: %s" % (relativo, trovati[:3]))
    if sporchi:
        return (ROSSO, "byte di controllo invisibili (firma tipica di una patch scritta "
                       "con heredoc: uno `\\b` diventato backspace). Posizione e valore "
                       "accanto a ogni file:\n      " + "\n      ".join(sporchi))
    return (OK, "%d file testuali toccati, tutti puliti" % guardati)


# --------------------------------------------------------------------------------------
# 7. nessuna bomba a tempo sta per esplodere
# --------------------------------------------------------------------------------------
def controllo_7_bombe_a_tempo(radice=RADICE, schedario=None):
    """Il 2026-08-13 alle 00:03 un test e' diventato rosso DA SOLO, e ci sono volute mezz'ora
    e tre esecuzioni per capire che il codice era sano: era passata mezzanotte.

    ⛔ IL GIUDIZIO NON STA QUI: sta in `collaudi/bombe_a_tempo.py`, che e' il posto dove
    quella conoscenza vive. Qui si LEGGE lo schedario che quell'attrezzo ha prodotto -- una
    copia del criterio resterebbe indietro il giorno che il criterio cambia.

    ⛔ E NON SI CERCANO LE DATE COL TESTO. Misurato il 2026-08-13: nei test ci sono **1667
    date cablate in 156 file**, e quasi nessuna e' pericolosa. Un allarme su 1667 punti
    verrebbe spento entro tre giorni, e un allarme spento non protegge niente (regola ferrea
    10). Ogni voce dello schedario e' invece **dimostrata**: quel test e' stato visto verde
    oggi e rosso a quella data precisa."""
    percorso = os.path.join(radice, "collaudi", "bombe_a_tempo.py")
    if not os.path.isfile(percorso):
        return (NON_ESEGUITO, "collaudi/bombe_a_tempo.py non c'e' piu': senza di lui nessuno "
                              "sorveglia i test che scadono da soli, e il ritorno di quel "
                              "difetto non lo vedrebbe nessuno fino a mezzanotte")
    spec = importlib.util.spec_from_file_location("_bombe_prevolo", percorso)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    if schedario is None:
        schedario = modulo.leggi_schedario()
    return modulo.giudizio_dallo_schedario(schedario)


# --------------------------------------------------------------------------------------
# la traccia dello scopo
# --------------------------------------------------------------------------------------
def scrivi_scopo(file_dichiarati, radice=RADICE, percorso=None):
    """Lascia scritto cosa si e' promesso di toccare. Lo rilegge il pre-fatto."""
    percorso = percorso or TRACCIA_SCOPO
    testa = _git(radice, "rev-parse", "--short", "HEAD")
    righe = ["# scopo dichiarato (regola ferrea 15) — lo rilegge prima_di_dire_fatto.py",
             "# dichiarato al commit: %s" % (testa.strip() if testa else "sconosciuto")]
    righe.extend(sorted(f.replace("\\", "/") for f in file_dichiarati))
    with io.open(percorso, "w", encoding="utf-8") as f:
        f.write("\n".join(righe) + "\n")
    return percorso


def leggi_scopo(percorso=None):
    """I file dichiarati, o `None` se nessuno scopo e' stato dichiarato."""
    percorso = percorso or TRACCIA_SCOPO
    if not os.path.isfile(percorso):
        return None
    dichiarati = []
    for riga in _leggi(percorso).splitlines():
        riga = riga.strip()
        if riga and not riga.startswith("#"):
            dichiarati.append(riga)
    return dichiarati


# --------------------------------------------------------------------------------------
# il giro
# --------------------------------------------------------------------------------------
CONTROLLI = (
    (1, "il conto dei test dichiarato e' quello vero", controllo_1_conto_dei_test),
    (2, "la riga delle consegne non e' rimasta indietro", controllo_2_consegne),
    (3, "nessuno `skipTest` che si assolve da solo", controllo_3_skip_interni),
    (4, "l'ambiente e' quello dichiarato", controllo_4_ambiente),
    (5, "nessun giro di mutazione aperto", controllo_5_traccia_mutazione),
    (6, "nessun byte invisibile nei file toccati", controllo_6_byte_di_controllo),
    (7, "nessuna bomba a tempo sta per esplodere", controllo_7_bombe_a_tempo),
)


def giro(radice=RADICE, controlli=CONTROLLI):
    """Esegue i controlli e restituisce gli esiti. Un controllo che ESPLODE non fa
    esplodere il giro: diventa `NON ESEGUITO`, che non e' mai un successo (S7)."""
    esiti = []
    for numero, nome, funzione in controlli:
        inizio = time.time()
        try:
            stato, dettaglio = funzione(radice=radice)
        except Exception as e:
            stato = NON_ESEGUITO
            dettaglio = "il controllo e' esploso (%s: %s). Un controllo che esplode non " \
                        "ha misurato niente: non e' verde" % (type(e).__name__, e)
        esiti.append(Esito(numero, nome, stato, dettaglio, time.time() - inizio))
    return esiti


def stampa_divieti(radice=RADICE):
    """⛔ «LE REGOLE SI LEGGONO PRIMA E DOPO OGNI OPERAZIONE» — ordine del fondatore del
    2026-08-11, dato a meta' sessione perche' le avevo lette all'inizio e poi avevo chiuso
    quattro operazioni senza rileggerle. Non era un divieto violato: era il MODO in cui i
    divieti vanno tenuti, e stava nell'unico posto che questo progetto ha dimostrato non
    reggere -- la memoria di chi lavora.

    Non riscrive i divieti: chiama la funzione che li stampa DAL FILE, in
    `collaudi/regole_avvio.py`. Un testo copiato in tre posti diverge in tre modi."""
    percorso = os.path.join(radice, "collaudi", "regole_avvio.py")
    if not os.path.isfile(percorso):
        print("⛔ NON RIESCO A STAMPARE I SEI DIVIETI: collaudi/regole_avvio.py non c'e'.")
        print("   Vanno letti lo stesso: stanno in cima a CLAUDE.md.")
        return False
    try:
        spec = importlib.util.spec_from_file_location("_regole_divieti", percorso)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        modulo.stampa_i_divieti()
        return True
    except Exception as e:
        print("⛔ NON RIESCO A STAMPARE I SEI DIVIETI (%s: %s)." % (type(e).__name__, e))
        print("   Vanno letti lo stesso: python collaudi/regole_avvio.py")
        return False


def _precondizioni(radice):
    """D18 punto 1: prima di misurare, si prova di essere in condizione di misurare. Un
    metro storto va scoperto dal metro, non dal muro."""
    mancanti = []
    if not os.path.isdir(os.path.join(radice, ".git")):
        mancanti.append("%s non e' un repository git (.git assente)" % radice)
    for atteso in ("RIPRENDI_QUI.md", "CLAUDE.md", "test_pipeline_ci.py"):
        if not os.path.isfile(os.path.join(radice, atteso)):
            mancanti.append("manca %s: questa non e' la radice del progetto" % atteso)
    return mancanti


def stampa(esiti, secondi, titolo="🛫 PRE-VOLO", non_guarda=COSA_NON_GUARDA):
    larghezza = 86
    print("=" * larghezza)
    print("%s — %d controlli da fare PRIMA, non dentro un ciclo da 68 minuti"
          % (titolo, len(esiti)))
    print("=" * larghezza)
    for e in esiti:
        print("  %-13s %d. %-46s %5.2fs" % (e.stato, e.numero, e.controllo, e.secondi))
        if e.stato != OK:
            print("      %s" % e.dettaglio)
        else:
            print("      %s" % e.dettaglio)
    print("-" * larghezza)
    print("⛔ COSA QUESTO CONTROLLO NON HA ESAMINATO (D18 punto 3)")
    for riga in non_guarda:
        print("   · %s" % riga)
    print("-" * larghezza)
    fuori = "  ⚠️ SOPRA IL TETTO" if secondi > TETTO_SECONDI else ""
    print("CRONOMETRO: %.2fs   (tetto dichiarato: %.1fs)%s" % (secondi, TETTO_SECONDI, fuori))
    if fuori:
        print("   Un pre-volo lento viene abbandonato, e allora non protegge piu' niente.")
        print("   Non fallisce per questo (sarebbe un falso allarme): a farlo rispettare")
        print("   c'e' una guardia dentro la suite.")


def verdetto(esiti):
    rossi = [e for e in esiti if e.stato == ROSSO]
    non_eseguiti = [e for e in esiti if e.stato == NON_ESEGUITO]
    return rossi, non_eseguiti


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    radice = RADICE
    scopo = None
    if "--scopo" in argv:
        scopo = argv[argv.index("--scopo") + 1:]

    mancanti = _precondizioni(radice)
    if mancanti:
        print("⛔ PRE-VOLO NON ESEGUITO — non sono in condizione di misurare (D18 punto 1)")
        for m in mancanti:
            print("   · %s" % m)
        print("   Un metro storto va scoperto dal metro, non dal muro: non stampo un")
        print("   verdetto che non ho misurato.")
        return 1

    inizio = time.time()
    # PRIMA di iniziare l'operazione: i sei divieti, per intero.
    stampa_divieti(radice)
    esiti = giro(radice)
    secondi = time.time() - inizio
    stampa(esiti, secondi)

    rossi, non_eseguiti = verdetto(esiti)
    if scopo is not None:
        percorso = scrivi_scopo(scopo, radice)
        print("-" * 86)
        print("📋 SCOPO DICHIARATO (regola ferrea 15) — %d file, scritto in %s"
              % (len(scopo), percorso))
        for f in sorted(scopo):
            print("   · %s" % f)
        print("   Lo rilegge `collaudi/prima_di_dire_fatto.py` al momento del commit.")
    print("=" * 86)
    if rossi or non_eseguiti:
        print("VERDETTO: ⛔ FERMO — %d rosso/i, %d non eseguito/i. NON lanciare la suite."
              % (len(rossi), len(non_eseguiti)))
        print("Un `NON ESEGUITO` non e' un successo: e' un controllo che non ha guardato")
        print("niente, e sarebbe il verde peggiore di tutti (sbaglio S7).")
        return 1
    print("VERDETTO: ✅ SI PUO' LANCIARE — %d controlli, 0 rossi, 0 non eseguiti."
          % len(esiti))
    return 0


if __name__ == "__main__":
    sys.exit(main())
