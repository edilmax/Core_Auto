# -*- coding: utf-8 -*-
"""
LA PIPELINE CI COME DATO - un cancello mai visto chiudersi non e' un cancello.

Perche' esiste. La CI di questo progetto ha undici job e un job finale, `gate`, che
riassume tutto: e' quello che il fondatore deve rendere "required" su GitHub. Se il
cablaggio del gate ha anche un solo errore - un job bloccante dimenticato nei `needs`,
una condizione che guarda solo `failure` e lascia passare `cancelled`, una soglia di
copertura scritta ma neutralizzata da un `|| true` - allora il semaforo verde della CI
non e' un verdetto: e' una decorazione. E nessun test del prodotto se ne accorgerebbe
mai, perche' il difetto sta NELLA MACCHINA CHE GIUDICA, non nel prodotto.

Qui il file `.github/workflows/ci.yml` viene trattato per quello che e': un DATO, con
una forma esatta, che si carica con pyyaml e si asserisce campo per campo.

Cosa si dimostra, in ordine:

  1) IGIENE DEL FILE      - 0 byte di controllo, 0 tab, nessun `\\n` letterale (le tre
                            trappole che questo repo ha gia' pagato con le patch via
                            heredoc), e il file si carica davvero come YAML.
  2) TRIGGER              - push E pull_request su master, senza filtri `paths` che
                            permetterebbero a un commit di scivolare fuori dalla CI;
                            token a privilegi minimi.
  3) NEEDS COMPLETO       - ogni job del file e' classificato (bloccante o non
                            bloccante, dichiarato nella mappa in testa a ci.yml) e i
                            `needs` del gate coincidono ESATTAMENTE con i bloccanti.
                            Aggiungere un job nuovo e dimenticarlo fa fallire questo
                            test: e' il punto in cui il "dimenticato" si vede.
  4) CONDIZIONE DEL       - la condizione del verdetto rosso non viene solo cercata come
     VERDETTO               stringa: viene PARSATA e VALUTATA su tutti gli esiti
                            possibili di tutti i needs. E il valutatore stesso e' provato
                            rosso su una condizione volutamente debole.
  5) JOB COPERTURA        - usa .coveragerc, misura i RAMI, e l'ultimo passo confronta
                            davvero con COVERAGE_MIN senza scappatoie.
  6) NIENTE SCAPPATOIE    - nessun `continue-on-error` nei bloccanti, nessuna azione
                            deprecata, nessun `uses:` agganciato a un ramo mobile, e i
                            sette gate che devono bloccare sul contenuto non sono
                            annullati da un `|| true`.
  7) PROVA SUL CAMPO      - il comando di soglia del cricchetto viene ESEGUITO davvero,
                            in una cartella sterile, e si pretende di vederlo uscire
                            diverso da zero sotto la soglia e uguale a zero sopra. In
                            piu' si dimostra che `branch = True` e' portante: lo stesso
                            identico codice, con la stessa identica soglia, passa se si
                            misurano solo le righe e FALLISCE se si misurano anche i
                            rami.

Prova sul campo gia' eseguita a mano sul repo VERO (documentata qui perche' non e'
ripetibile in pochi secondi dentro la suite):

    COVERAGE_FILE=<fuori dal repo> python -m coverage run -m unittest \\
        test_suite_senza_zone_cieche
    python -m coverage report        ->  TOTAL 23436 righe, 6488 rami, 0.0%
    python -m coverage report --fail-under=82   ->  exit 2      (ROSSO, come deve)

    ... e su un sottoinsieme che tocca davvero un motore:
    python -m coverage run -m unittest test_fase98_policy_commissione
    python -m coverage report        ->  TOTAL 0.8%
    python -m coverage report --fail-under=82   ->  exit 2      (ROSSO)
    python -m coverage report --fail-under=0    ->  exit 0      (VERDE: sa anche passare)

Le 23.436 righe e i 6.488 rami coincidono con i numeri dichiarati nel commento del job
`copertura`: la misura del job e' quella vera, non una cifra ricordata a memoria.
"""

import datetime
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

import yaml

QUI = os.path.dirname(os.path.abspath(__file__))
CI_YML = os.path.join(QUI, ".github", "workflows", "ci.yml")
COVERAGERC = os.path.join(QUI, ".coveragerc")

# Il job che riassume tutto: e' lui il check da rendere "required" su GitHub.
GATE = "gate"

# Gli esiti che GitHub puo' assegnare a un job da cui il gate dipende.
ESITI_POSSIBILI = ("success", "failure", "cancelled", "skipped")
ESITI_NON_VERDI = ("failure", "cancelled", "skipped")

# Marcatore obbligatorio: un job che sta nei `needs` ma il cui comando e' neutralizzato
# con `|| true` DEVE dichiararlo nel proprio commento con questa frase esatta. Serve a
# impedire il difetto piu' insidioso di tutti: un commento che promette un controllo che
# il comando sotto non fa (in questo repo e' successo davvero con il job w3c).
MARCATORE_SENZA_DENTI = "NON BLOCCA SUI RILIEVI"

# Per ognuno dei job che DEVONO bloccare sul contenuto: il pezzo di comando che e' il
# loro vero gate. Si pretende che quel comando non sia annullato da un `|| true`.
COMANDI_CHE_DEVONO_BLOCCARE = {
    "money-smoke": "python -m unittest",
    "full-suite": "unittest discover",
    "copertura": "--fail-under=",
    "mutazione": "collaudi/mutazione_prodotto.py",
    "qualita": "bandit -r .",
    "accessibilita": "collaudi/a11y_static.js",
    "atheris": "collaudi/fuzz_soldi.py",
}

# Versione MINIMA accettabile per le azioni di GitHub usate qui. Sotto queste versioni
# l'azione gira su un runtime Node ritirato (node12/node16) o e' stata proprio spenta
# (upload-artifact v3, chiuso a gennaio 2025): sono azioni deprecate.
VERSIONE_MINIMA_AZIONI = {
    "actions/checkout": 4,
    "actions/setup-python": 5,
    "actions/setup-node": 4,
    "actions/setup-java": 4,
    "actions/upload-artifact": 4,
    "actions/download-artifact": 4,
    "actions/cache": 4,
}

# Comandi di workflow ritirati da GitHub: se ricompaiono, il passo che li usa non fa
# piu' quello che crede di fare (e non fallisce: peggio).
COMANDI_RITIRATI = ("::set-output", "::save-state", "::set-env", "::add-path")


def _testo_ci():
    with io.open(CI_YML, encoding="utf-8") as f:
        return f.read()


def _doc_ci():
    return yaml.safe_load(_testo_ci())


def _trigger(doc):
    """In YAML `on:` e' la parola riservata per "vero": pyyaml la carica come True."""
    return doc.get("on", doc.get(True))


def _passi(job):
    return job.get("steps", []) or []


def _run_dei_passi(job):
    return [p["run"] for p in _passi(job) if isinstance(p.get("run"), str)]


def _blocco_di_commento_sopra(testo, chiave_job):
    """Le righe di commento contigue subito sopra la definizione di un job."""
    righe = testo.splitlines()
    bersaglio = "  %s:" % chiave_job
    try:
        i = righe.index(bersaglio)
    except ValueError:
        raise AssertionError("job %r non trovato nel testo di ci.yml" % chiave_job)
    raccolte = []
    j = i - 1
    while j >= 0 and righe[j].strip().startswith("#"):
        raccolte.append(righe[j].strip().lstrip("#").strip())
        j -= 1
    return "\n".join(reversed(raccolte))


def _elenco_dichiarato(testo, intestazione, nomi_validi, fermate=()):
    """Legge dalla mappa in testa a ci.yml l'elenco di job sotto una intestazione.

    Si ferma alla prima riga di commento vuota, a `>>>`, a una riga di separazione, a
    una delle intestazioni successive o alla fine dei commenti: cosi' i paragrafi di
    spiegazione che vengono dopo non finiscono nell'elenco (il paragrafo che spiega il
    gate nomina "gate" e "w3c", e senza questo taglio entrerebbero nella lista).
    """
    trovati = []
    raccogliendo = False
    for riga in testo.splitlines():
        spoglia = riga.strip()
        if not spoglia.startswith("#"):
            if raccogliendo:
                break
            continue
        contenuto = spoglia.lstrip("#").strip()
        if not raccogliendo:
            if contenuto.startswith(intestazione):
                raccogliendo = True
            continue
        if (contenuto == "" or contenuto.startswith(">>>")
                or set(contenuto) == {"="}
                or any(contenuto.startswith(f) for f in fermate)):
            break
        for pezzo in re.findall(r"[a-z][a-z0-9-]+", contenuto):
            if pezzo in nomi_validi and pezzo not in trovati:
                trovati.append(pezzo)
    return trovati


# Un passo che installa dipendenze non e' un controllo: `pip install ...` senza
# `|| true` non rende "con i denti" un job il cui unico vero comando e' neutralizzato.
_INSTALLAZIONE = re.compile(r"^(sudo\s+)?(apt-get|pip3?|npm|npx|python -m pip)\b")


def _e_installazione(comando):
    testa = comando.strip()
    return bool(_INSTALLAZIONE.match(testa)) and "install" in testa


def _comandi_di_controllo(job):
    """I comandi del job che esprimono un giudizio (tolte le installazioni)."""
    return [c for c in _run_dei_passi(job) if not _e_installazione(c)]


# ---------------------------------------------------------------------------
#  Il valutatore della condizione del verdetto.
#  Non cerca stringhe: legge la condizione VERA scritta in ci.yml, la scompone e la
#  valuta come farebbe GitHub. Se la condizione fosse scritta in una forma che non
#  riconosce, solleva: non la accetta "per fiducia".
# ---------------------------------------------------------------------------
_TERMINE = re.compile(r"^contains\(\s*needs\.\*\.result\s*,\s*'([a-z_]+)'\s*\)$")

# Il termine del DENOMINATORE: non cerca una parola brutta fra gli esiti arrivati,
# pretende che siano arrivati TUTTI e siano TUTTI verdi. E' l'unico dei quattro che
# vede il caso "nessun verdetto affatto" (2026-08-06, run 627).
_TERMINE_DENOMINATORE = re.compile(
    r"^join\(\s*needs\.\*\.result\s*,\s*' '\s*\)\s*!=\s*'((?:success )*success)'$")


def _scomponi(espressione):
    """Spezza la condizione del verdetto nei suoi termini, senza fidarsi.

    Restituisce (stati_cercati, denominatore_preteso). Il denominatore e' None se
    quel termine non c'e': ed e' proprio la sua assenza il difetto del 2026-08-06.
    """
    corpo = espressione.strip()
    if corpo.startswith("${{") and corpo.endswith("}}"):
        corpo = corpo[3:-2].strip()
    if "&&" in corpo:
        raise ValueError("la condizione del verdetto contiene un AND: con `&&` "
                         "servirebbero PIU' job rossi insieme per far scattare il "
                         "rosso, e un job rosso da solo passerebbe. Va in OR.")
    stati = []
    denominatore = None
    for parte in corpo.split("||"):
        pezzo = parte.strip()
        trovato = _TERMINE.match(pezzo)
        if trovato is not None:
            stati.append(trovato.group(1))
            continue
        contato = _TERMINE_DENOMINATORE.match(pezzo)
        if contato is not None:
            if denominatore is not None:
                raise ValueError("il termine del denominatore compare due volte")
            denominatore = contato.group(1)
            continue
        raise ValueError("termine non riconosciuto nella condizione del verdetto: "
                         "%r (attesi: contains(needs.*.result, '<esito>') oppure "
                         "join(needs.*.result, ' ') != '<tutti success>')" % pezzo)
    return stati, denominatore


def stati_catturati(espressione):
    return _scomponi(espressione)[0]


def denominatore_preteso(espressione):
    """La stringa di `success` che la condizione pretende, o None se non conta."""
    return _scomponi(espressione)[1]


def verdetto_rosso(stati, risultati):
    """Come GitHub valuta `contains(needs.*.result, X)` su un elenco di esiti."""
    return any(r in stati for r in risultati)


def esiti_che_scappano(stati, quanti_needs):
    """Quali esiti NON verdi passerebbero indisturbati con questi `stati`."""
    scappati = []
    for cattivo in ESITI_NON_VERDI:
        risultati = ["success"] * (quanti_needs - 1) + [cattivo]
        if not verdetto_rosso(stati, risultati):
            scappati.append(cattivo)
    return scappati


class TestIgieneDelFile(unittest.TestCase):
    """Le tre trappole gia' pagate da questo repo: byte invisibili, tab, `\\n` letterali."""

    def test_zero_byte_di_controllo_zero_tab_zero_backslash_n(self):
        with open(CI_YML, "rb") as f:
            dati = f.read()
        controllo = [(i, b) for i, b in enumerate(dati)
                     if b < 32 and b not in (9, 10, 13)]
        self.assertEqual(controllo, [],
                         "byte di controllo invisibili in ci.yml (tipico delle patch "
                         "via heredoc): posizione e valore qui sopra")
        self.assertEqual(dati.count(b"\x09"), 0,
                         "ci.yml contiene TAB: YAML non li ammette come indentazione")
        self.assertEqual(dati.count(b"\x5c\x6e"), 0,
                         "ci.yml contiene la sequenza backslash-n letterale: una "
                         "patch ha scritto \\n invece di andare a capo davvero")
        self.assertEqual(dati.count(b"\x0d"), 0,
                         "ci.yml contiene ritorni carrello (CRLF): il runner e' Linux")

    def test_NESSUN_file_python_contiene_byte_di_controllo(self):
        """⛔ IL CONTROLLO QUI SOPRA GUARDAVA UN FILE SOLO, E INTANTO UN ALTRO ERA GUASTO.

        DIFETTO VERO, trovato il 2026-08-03: `collaudi/audit_coerenza_tariffe.py` conteneva
        due byte `0x08` (backspace) al posto di `\\b` in una espressione regolare -- la firma
        esatta di una patch scritta via heredoc, la trappola che questo repo ha gia' pagato
        piu' volte. Il controllo dei byte invisibili esisteva, ma leggeva **solo `ci.yml`**:
        una guardia che guarda un file mentre il difetto sta in un altro.

        Conseguenza misurata su quel file: `\\bOTA\\b` era diventato `<BS>OTA<BS>`, e siccome
        il carattere backspace non compare mai in un testo vero, quella parte della regola
        **non combaciava mai**. Lo strumento continuava a girare e a dire di aver controllato.

        Qui si guarda TUTTO il codice Python del progetto, una volta sola.
        """
        import glob
        import io
        import os
        radice = os.path.dirname(os.path.abspath(__file__))
        sporchi = []
        for percorso in sorted(glob.glob(os.path.join(radice, "*.py"))
                               + glob.glob(os.path.join(radice, "collaudi", "*.py"))):
            with io.open(percorso, "rb") as f:
                dati = f.read()
            trovati = [(i, b) for i, b in enumerate(dati)
                       if b < 32 and b not in (9, 10, 13)]
            if trovati:
                sporchi.append((os.path.relpath(percorso, radice), trovati[:3]))
        self.assertEqual([], sporchi,
                         "questi file Python contengono byte di controllo invisibili "
                         "(firma tipica di una patch via heredoc: uno `\\b` diventato "
                         "backspace, uno `\\t` diventato tab...). Posizione e valore "
                         "accanto a ogni file: %r" % (sporchi,))

    def test_la_regex_OTA_riconosce_la_PAROLA_e_non_un_pezzo_di_parola(self):
        """⛔ LA GUARDIA CHE IMPEDISCE AL DIFETTO DI TORNARE.

        `KW_ALTRUI` serve all'audit delle tariffe per capire quando una percentuale in un
        documento **parla di altri** (le OTA, i concorrenti) e non di noi: se non riconosce
        «OTA», quella percentuale viene attribuita a noi e l'audit segnala una tariffa
        sbagliata che non esiste -- oppure, peggio, cambia il conto di cio' che va corretto.

        Si guarda il COMPORTAMENTO, non il testo del pattern: se qualcuno rimettesse il
        backspace al posto di `\\b`, «OTA» smetterebbe di combaciare e la prima asserzione
        diventerebbe rossa. E le altre due impediscono la riparazione sbagliata -- togliere
        i `\\b` e basta -- che farebbe combaciare anche «OTAKU» e «NOTA».

        La regex si legge dall'albero sintattico: importare il modulo eseguirebbe l'audit.
        """
        import ast
        import io
        import os
        percorso = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "collaudi", "audit_coerenza_tariffe.py")
        with io.open(percorso, encoding="utf-8") as f:
            albero = ast.parse(f.read())
        pattern = [n.value.args[0].value for n in ast.walk(albero)
                   if isinstance(n, ast.Assign)
                   and getattr(n.targets[0], "id", "") == "KW_ALTRUI"]
        self.assertEqual(1, len(pattern), "KW_ALTRUI non e' piu' dove ci si aspetta")
        regola = re.compile(pattern[0], re.I)
        for testo in ("le OTA prendono il 18%", "prenota su OTA oggi", "il nostro OTA-like"):
            self.assertTrue(regola.search(testo),
                            "«OTA» non viene piu' riconosciuta come parola in %r: se al "
                            "posto di \\b c'e' un byte backspace, quella parte della regola "
                            "non combacia MAI e l'audit attribuisce a noi percentuali che "
                            "parlano di altri" % testo)
        for testo in ("OTAKU", "questa e' una NOTA", "commissione del 15%"):
            self.assertFalse(regola.search(testo),
                             "«%s» viene scambiato per un riferimento alle OTA: i confini "
                             "di parola sono stati tolti invece che riparati" % testo)
        self.assertNotIn(chr(8), pattern[0],
                         "il byte backspace e' tornato dentro la regola: e' la firma di una "
                         "patch via heredoc (D9), non di un editor")

    def test_il_controllo_dei_byte_riconoscerebbe_il_difetto(self):
        """Se il criterio smettesse di vedere, questo controllo sarebbe un ornamento."""
        sporco = b"name: x\n\x08jobs:\n\tdue\n" + b"\x5c\x6e"
        controllo = [(i, b) for i, b in enumerate(sporco)
                     if b < 32 and b not in (9, 10, 13)]
        self.assertEqual([b for _, b in controllo], [8])
        self.assertEqual(sporco.count(b"\x09"), 1)
        self.assertEqual(sporco.count(b"\x5c\x6e"), 1)

    def test_L_AUDIT_DELLE_TARIFFE_VIENE_ESEGUITO_DAVVERO(self):
        """⛔ L'AUDIT ESISTEVA E NESSUNO LO FACEVA GIRARE.

        Trovato il 2026-08-10, ed e' il difetto che ha reso possibile tutta la
        giornata precedente. Questo file conteneva gia' due guardie sull'audit delle
        tariffe -- ma guardavano **com'e' fatto** (che la sua regola non contenesse
        byte invisibili), non **che dicesse la verita'**. Nessuno lo eseguiva: era un
        bottone da premere a mano, e chi non se lo ricordava aveva una suite verde con
        dentro cifre vecchie. Quando il 2026-08-09 la tariffa tecnica e' cambiata,
        **47 righe** in tutto il progetto sono rimaste indietro, e la suite era verde.

        Ora l'audit gira dentro la suite. Se domani ricompare una percentuale che il
        motore non applica -- in un testo pubblico, in un contratto, in un test -- la
        suite diventa ROSSA lo stesso giorno, invece di aspettare che qualcuno se ne
        accorga.

        ⚠️ Cosa NON garantisce (D18 punto 3): confronta le cifre trovate con lo
        SCHEDARIO `collaudi/baseline_tariffe.txt`, cioe' con le righe gia' lette e
        giudicate legittime da una persona. Non giudica da solo se una cifra sia
        giusta: dice che ne e' comparsa una NUOVA e che va letta. Uno schedario
        gonfiato a caso disarma questa guardia -- come per gli EQUIVALENTI_DICHIARATI.
        """
        import subprocess
        import sys as _sys
        radice = os.path.dirname(os.path.abspath(__file__))
        attrezzo = os.path.join(radice, "collaudi", "audit_coerenza_tariffe.py")
        self.assertTrue(os.path.exists(attrezzo),
                        "l'audit delle tariffe non c'e' piu': senza di lui nessuno "
                        "confronta le percentuali dei testi con quelle del motore")
        schedario = os.path.join(radice, "collaudi", "baseline_tariffe.txt")
        self.assertTrue(
            os.path.exists(schedario),
            "manca %s: senza schedario l'audit tratta OGNI cifra come nuova e questa "
            "guardia diventa un allarme sempre acceso (cioe' un allarme che si spegne). "
            "Lo schedario va versionato: non e' un'uscita, e' una decisione." % schedario)
        esito = subprocess.run([_sys.executable, attrezzo], cwd=radice,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if esito.returncode != 0:
            rapporto = os.path.join(radice, "collaudi", "rapporto_coerenza.txt")
            coda = ""
            if os.path.exists(rapporto):
                testo = io.open(rapporto, encoding="utf-8", errors="replace").read()
                taglio = testo.find("CIFRE NUOVE DA ESAMINARE")
                coda = testo[taglio:taglio + 2000] if taglio >= 0 else testo[-2000:]
            self.fail(
                "l'audit delle tariffe esce %d: c'e' almeno una percentuale che il "
                "motore non applica, oppure una cifra NUOVA mai esaminata.\n"
                "Si rilancia a mano con:  python collaudi/audit_coerenza_tariffe.py\n"
                "Il rapporto completo sta in collaudi/rapporto_coerenza.txt\n\n%s"
                % (esito.returncode, coda))

    def test_L_AUDIT_MILLIMETRICO_VIENE_ESEGUITO_DAVVERO(self):
        """⛔ LO STESSO DIFETTO DELL'AUDIT QUI SOPRA, RITROVATO IL 2026-08-14.

        `collaudi/audit_millimetrico.py` confronta i 5 documenti ufficiali col motore
        vero: conteggi, percorsi, rotte, tariffe, logica dei consensi, variabili
        d'ambiente. Lo chiamavano soltanto `campagna_totale.py` e `piramide.py`, cioe'
        due attrezzi d'officina che si lanciano **a mano**. Non stava nella suite, non
        stava nel gancio del commit, non stava in CI: le sue discrepanze restavano
        invisibili finche' qualcuno non si ricordava di premere il bottone.

        Misurato quel giorno su `f835496`: usciva **1** con **5** discrepanze -- fra cui
        tre conteggi del README rimasti indietro (149/390/13 invece di 151/402/14) -- e
        la suite era **verde lo stesso**. E' la regola #23, COSTRUITO non e' COLLEGATO,
        sullo stesso attrezzo e per la seconda volta: il test qui sopra nacque
        il 2026-08-10 per identica ragione, e nessuno estese la lezione al vicino.

        Costa **0,11 s** (misurato il 2026-08-14): tenerlo acceso non ha un prezzo.

        ⚠️ Cosa NON garantisce (D18 punto 3): l'audit dice che i documenti e il motore
        **si raccontano la stessa cosa**, non che il motore faccia la cosa **giusta**.
        Che la tariffa tecnica non scenda sotto costo lo giudica
        `test_fase59_costo_pagamento`, non questo.
        """
        import subprocess
        import sys as _sys
        radice = os.path.dirname(os.path.abspath(__file__))
        attrezzo = os.path.join(radice, "collaudi", "audit_millimetrico.py")
        self.assertTrue(os.path.exists(attrezzo),
                        "l'audit millimetrico non c'e' piu': senza di lui nessuno "
                        "confronta i 5 documenti ufficiali col motore, e i numeri dei "
                        "documenti tornano a invecchiare in silenzio")
        esito = subprocess.run([_sys.executable, attrezzo], cwd=radice,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if esito.returncode != 0:
            uscita = esito.stdout.decode("utf-8", errors="replace")
            taglio = uscita.find("VERDETTO:")
            coda = uscita[taglio:taglio + 2000] if taglio >= 0 else uscita[-2000:]
            self.fail(
                "l'audit millimetrico esce %d: almeno un'affermazione dei 5 documenti "
                "ufficiali non corrisponde piu' al motore.\n"
                "Si rilancia a mano con:  python collaudi/audit_millimetrico.py\n"
                "Ogni rosso nomina il colpevole con atteso= e trovato=.\n\n%s"
                % (esito.returncode, coda))

    def test_il_file_si_carica_come_yaml_ed_e_una_pipeline(self):
        doc = _doc_ci()
        self.assertIsInstance(doc, dict)
        self.assertEqual(doc["name"], "BookinVIP CI")
        self.assertIsInstance(doc["jobs"], dict)
        self.assertGreaterEqual(len(doc["jobs"]), 9)
        self.assertIn(GATE, doc["jobs"],
                      "il job si deve chiamare esattamente 'gate': e' il nome che il "
                      "fondatore seleziona nella branch protection di GitHub, e "
                      "rinominarlo scollega silenziosamente la protezione del ramo")
        for nome, job in doc["jobs"].items():
            self.assertEqual(job.get("runs-on"), "ubuntu-latest",
                             "il job %r non dichiara il runner" % nome)
            self.assertTrue(_passi(job), "il job %r non ha passi" % nome)


class TestIlGancioSTAMPAIlPiano(unittest.TestCase):
    """UNA CHAT NUOVA DEVE TROVARSI DAVANTI IL PIANO, NON DOVERLO CERCARE.

    Il gancio `SessionStart` (`.claude/settings.json`) lancia `collaudi/regole_avvio.py` a
    ogni sessione. Fino al 2026-08-15 stampava le REGOLE -- come lavorare -- ma non il PIANO,
    cioe' COSA fare e in che ordine: ogni chat nuova conosceva il metodo e sceglieva da sola.
    L'ha fatto notare il fondatore -- *«se ogni volta non viene letto siamo a punto a capo»* --
    dopo che questa stessa sessione aveva ignorato il piano per ore, avendone letto solo la
    riga di riassunto nell'indice.

    ⛔ Un piano che vive in un file che nessuno apre non e' un piano: e' un desiderio. Questa
    guardia esiste perche' la stampa non possa sparire in silenzio (D18 punto 4).
    """

    def test_il_piano_ESISTE_nel_registro_e_lo_strumento_lo_LEGGE(self):
        import collaudi.regole_avvio as ra
        piano = ra.leggi_piano()
        self.assertTrue(piano,
                        "il blocco PIANO-INIZIO/PIANO-FINE non c'e' piu' in "
                        "REGISTRO_INGEGNERIA.md: il gancio non ha piu' niente da stampare, e "
                        "ogni chat nuova ricomincera' a scegliere da sola")
        self.assertIn("**A**", piano, "il piano non nomina piu' il primo pezzo in ordine")

    def test_lo_strumento_lo_STAMPA_davvero(self):
        """Non basta che sappia leggerlo: deve finire sullo schermo. Si esegue il programma
        VERO e si guarda la sua uscita -- non si cerca una stringa nel sorgente, che un
        commento soddisferebbe (sbaglio S6)."""
        import subprocess
        import sys as _sys
        radice = os.path.dirname(os.path.abspath(__file__))
        esito = subprocess.run([_sys.executable, os.path.join(radice, "collaudi",
                                                             "regole_avvio.py")],
                               cwd=radice, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        uscita = esito.stdout.decode("utf-8", errors="replace")
        self.assertIn("IL PIANO", uscita,
                      "il gancio non stampa piu' il piano: una chat nuova non lo vedra'")
        self.assertIn("bookinvip-piano-dieci-pezzi", uscita,
                      "non dice piu' DOVE leggere il piano per esteso: la riga di riassunto "
                      "nell'indice non basta, ed e' l'errore da cui nasce questa guardia")

    def test_il_piano_NON_e_RICOPIATO_dentro_lo_strumento(self):
        """La malattia di tutta la giornata del 2026-08-15: la stessa cosa scritta in due
        posti, e la seconda copia che resta indietro. Il piano deve stare in UN posto solo --
        il registro -- e lo strumento deve LEGGERLO."""
        import io as _io
        sorgente = _io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "collaudi", "regole_avvio.py"),
                            encoding="utf-8").read()
        for pezzo in ("copertura decide cosa mutare", "revisore indipendente",
                      "tre uscite"):
            self.assertNotIn(pezzo, sorgente,
                             "il testo del piano e' stato RICOPIATO dentro regole_avvio.py "
                             "(%r): il giorno che il piano cambia, questa copia restera' "
                             "indietro e stampera' il falso. Si legge dal registro." % pezzo)


class TestIlPianoDeiDieciBlocchiNONPuoDivergereDallaMACCHINA(unittest.TestCase):
    """IL PIANO E' DATI, E CHI LI CONTRADDICE DIVENTA ROSSO LO STESSO GIORNO.

    Nato il 2026-08-15 da un'osservazione del fondatore: *«se non mettiamo a posto questo
    foglio, ogni chat fa quel che vuole»*. Aveva ragione, e la prova stava nel codice:
    `collaudi/piano_dei_soldi.py` cerca di capire il piano con espressioni regolari sulla
    PROSA dei documenti (`re.compile(r"passati dal giudice - (\\d+)")`). Una macchina che
    prova a indovinare un tema: cambia una parola e diventa cieca.

    `collaudi/piano.py` gira il verso: il piano e' una struttura di DATI (dieci blocchi per
    mestiere, coi moduli e gli strumenti d'ingegneria che devono superare), e il racconto lo
    stampa la macchina. Queste guardie servono a una cosa sola: che quei dati non possano
    divergere dalla macchina vera senza che qualcosa diventi rosso.

    ⛔ Ognuna e' stata vista ROSSA prima di valere (D4, D20): l'iniezione avviene in memoria,
    passando un elenco di moduli finto, cosi' la prova non tocca il disco (D19).
    """

    def _piano(self):
        import collaudi.piano as p
        return p

    def test_ogni_modulo_del_progetto_sta_in_ESATTAMENTE_un_blocco(self):
        """La difesa contro «costruito e dimenticato». Un `fase*.py` nuovo che nessuno
        classifica non e' un dettaglio burocratico: e' un pezzo di macchina di cui nessuno
        ha deciso chi lo collauda -- e qui ne sono gia' stati contati a decine."""
        p = self._piano()
        problemi = p.contraddizioni()
        self.assertEqual([], problemi,
                         "il piano dei dieci blocchi non coincide piu' con la macchina:\n  - "
                         + "\n  - ".join(problemi))

    def test_DIVENTA_ROSSA_se_un_modulo_nuovo_non_e_in_nessun_blocco(self):
        """La direzione che conta: la guardia deve GRIDARE col guasto dentro. Senza questa
        prova sarebbe un ornamento -- un controllo che non puo' fallire (modo 4)."""
        p = self._piano()
        finto = set(p.moduli_sul_disco()) | {"fase999_mai_classificato"}
        problemi = p.contraddizioni(sul_disco=finto)
        self.assertTrue(any("FUORI DA OGNI BLOCCO" in x for x in problemi),
                        "ho aggiunto un modulo che nessun blocco conosce e la guardia ha "
                        "taciuto: allora non vedrebbe nemmeno un modulo vero dimenticato")

    def test_DIVENTA_ROSSA_se_un_blocco_nomina_un_modulo_che_NON_esiste(self):
        """Sbaglio S2: i nomi si leggono, non si inventano (`fase186_guardiano_stati.py` fu
        inventato due volte in un'ora). Un piano che nomina fantasmi manda a lavorare su
        file che non ci sono."""
        p = self._piano()
        veri = p.moduli_sul_disco()
        sparito = sorted(p.moduli_nel_piano())[0]
        problemi = p.contraddizioni(sul_disco=set(veri) - {sparito})
        self.assertTrue(any("NON ESISTONO" in x for x in problemi),
                        "ho tolto dal disco un modulo che il piano dichiara e la guardia ha "
                        "taciuto: il piano potrebbe nominare fantasmi per sempre")

    def test_se_non_vede_NESSUN_modulo_dice_MISURA_NON_VALIDA_e_non_VERDE(self):
        """Sbaglio S1: un confronto che riceve il vuoto non dice «uguali», dice «misura non
        valida». Il vuoto non e' un valore: e' l'assenza di misura. E' anche D18 punto 1 --
        uno strumento misura prima se stesso."""
        p = self._piano()
        problemi = p.contraddizioni(sul_disco=set())
        self.assertTrue(problemi, "con zero moduli visti la guardia e' rimasta VERDE: e' il "
                                  "verde peggiore, quello di chi non ha guardato niente")
        self.assertTrue(any("MISURA NON VALIDA" in x for x in problemi),
                        "con zero moduli visti deve dire che la misura NON e' valida, non "
                        "inventare un verdetto: %r" % problemi)

    def test_ogni_blocco_dichiara_QUANDO_e_finito_e_CON_QUALI_strumenti(self):
        """Un blocco senza condizione d'arrivo e senza attrezzi non e' un lavoro: e' un
        desiderio. E' la stessa regola che `regole_avvio.lavori_senza_criterio()` applica ai
        lavori in sospeso, portata sui blocchi."""
        p = self._piano()
        for b in p.BLOCCHI:
            self.assertTrue(b["finito_quando"],
                            "il blocco «%s» non dice quando e' finito" % b["nome"])
            self.assertTrue(b["attrezzi"],
                            "il blocco «%s» non dice con quali strumenti lo si dimostra"
                            % b["nome"])
            self.assertTrue(b["moduli"],
                            "il blocco «%s» non contiene nessun modulo" % b["nome"])
            for a in b["attrezzi"]:
                self.assertIn(a, p.ATTREZZI,
                              "il blocco «%s» chiede l'attrezzo %r, che non e' in cassetta"
                              % (b["nome"], a))

    def test_il_gancio_di_avvio_STAMPA_i_dieci_blocchi(self):
        """Non basta che il file esista: deve finire sullo schermo di ogni chat nuova. Si
        esegue il programma VERO e si guarda la sua uscita, non si cerca una stringa nel
        sorgente -- che un commento soddisferebbe (sbaglio S6)."""
        import subprocess
        import sys as _sys
        radice = os.path.dirname(os.path.abspath(__file__))
        esito = subprocess.run([_sys.executable, os.path.join(radice, "collaudi",
                                                             "regole_avvio.py")],
                               cwd=radice, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        uscita = esito.stdout.decode("utf-8", errors="replace")
        self.assertIn("BLOCCHI", uscita,
                      "il gancio non stampa piu' i blocchi: una chat nuova non sapra' quale "
                      "modulo appartiene a quale mestiere, e ricominciera' a scegliere da sola")
        for atteso in ("SOLDI E PAGAMENTI", "PRENOTAZIONI E INVENTARIO"):
            self.assertIn(atteso, uscita,
                          "il gancio non nomina piu' il blocco %r" % atteso)


class TestLaListaDeiLavoriNONPuoMENTIRE(unittest.TestCase):
    """LA LISTA DEI LAVORI IN SOSPESO SI MISURA DA SOLA — perche' mentiva davvero.

    Il 2026-08-15 il fondatore ha chiesto: *«come faccio a sapere se la chat vecchia ha
    fatto tutto quello che c'e' scritto?»*. Misurando, la risposta e' stata imbarazzante:
    la lista teneva **CodeQL al primo posto fra i lavori DA FARE** mentre
    `.github/workflows/codeql.yml` esisteva ed era **verde su master** (API GitHub,
    conclusion=success su 6118d35). Una lista scritta a mano resta indietro sempre, e chi
    la legge rifa' lavoro gia' fatto -- che e' esattamente il difetto del 2026-08-12 da cui
    quella lista era nata.

    Da qui: ogni voce porta una PROVA meccanica, e lo stato lo rifa' la macchina a ogni
    avvio invece di leggerlo scritto.
    """

    def _ra(self):
        import collaudi.regole_avvio as ra
        return ra

    def test_ogni_lavoro_in_sospeso_dice_COME_si_controlla(self):
        """Non basta dire QUANDO e' finito (`fatto_quando`): serve dire CHI lo va a vedere.
        Fra le due c'e' la differenza fra una regola e un desiderio."""
        ra = self._ra()
        senza = ra.lavori_senza_prova()
        self.assertEqual([], senza,
                         "questi lavori non dicono come si controlla se sono finiti, quindi "
                         "il loro stato tornera' a essere una frase scritta a mano: %s"
                         % ", ".join(senza))

    def test_UNA_PROVA_NON_PUO_ESSERE_SODDISFATTA_DAL_TESTO_DELLA_PROVA(self):
        """⛔ VERDE FINTO VERO, 2026-08-15, vissuto pochi minuti dopo aver scritto le prove.

        Le parole cercate ("test_clock", "DENOMINATORE DELLA MACCHINA") sono scritte dentro
        `regole_avvio.py`, nelle prove stesse: la ricerca trovava SE STESSA e due lavori mai
        iniziati risultavano ✅ FATTO. E' lo sbaglio S6 in forma nuova -- una guardia che il
        proprio commento poteva soddisfare.

        Questa guardia prova il MECCANISMO, non lo stato del momento: cerca nella cartella
        `collaudi/` una parola che (oggi) vive solo dentro `regole_avvio.py`, e pretende che
        quel file non venga contato. Cosi' resta valida anche il giorno che i lavori si
        faranno davvero.
        """
        ra = self._ra()
        radice = os.path.dirname(os.path.abspath(__file__))
        trovati = ra._testo_dentro(radice, "collaudi", "", ".py",
                                   "DENOMINATORE DELLA MACCHINA")
        self.assertNotIn("regole_avvio.py", trovati,
                         "la ricerca conta il file che DICHIARA la prova: cosi' un lavoro "
                         "mai iniziato risulta fatto, perche' la parola cercata e' scritta "
                         "nella prova stessa")

    def test_NESSUNA_PROVA_E_SODDISFATTA_DAL_FILE_CHE_LA_RACCONTA(self):
        """⛔ LO STESSO VERDE FINTO, TORNATO SPOSTATO DI UN FILE — 2026-08-16.

        La riparazione del 2026-08-15 escludeva dalla ricerca UN file solo (`regole_avvio.py`,
        e per giunta solo nella propria cartella). Ma la prova non vive piu' in un file solo:
        da quando esiste la guardia qui sopra, le parole cercate sono scritte anche QUI, in
        `test_pipeline_ci.py` -- che sta nella radice e comincia per `test_`, cioe' proprio
        dove la prova del lavoro «orologi di prova Stripe» va a cercare.

        Risultato misurato il 2026-08-16: quel lavoro risultava ✅ FATTO ed era soddisfatto da
        UN SOLO file, `test_pipeline_ci.py`, con UNA sola occorrenza della parola, dentro il
        commento che racconta il difetto -- e ZERO usi veri dell'API di Stripe (`test_helpers`,
        `TestClock`: assenti). Nessuno ha mai creato un orologio di prova, e la lista diceva
        di si'. E' il lavoro che la lista stessa chiama «il giudice esterno piu' vicino ai
        soldi che manca»: il verde finto stava proprio sul denaro.

        ⛔ QUESTA GUARDIA E' GENERALE, e lo e' apposta. Non chiede «il lavoro 3 e' a posto?»
        -- quella domanda diventerebbe falsa il giorno che il lavoro si fa davvero. Chiede che
        NESSUNA prova, presente o futura, sia soddisfatta da uno dei file che COSTITUISCONO
        l'impianto delle prove. Vale ancora il giorno che i lavori si faranno, e vale per i
        lavori che verranno aggiunti domani.
        """
        ra = self._ra()
        radice = os.path.dirname(os.path.abspath(__file__))
        # I file che SONO la prova: la lista con le sue ricerche, e la guardia che la protegge.
        # Se uno di questi soddisfa una prova, la prova sta leggendo se stessa.
        impianto = ("regole_avvio.py", os.path.basename(os.path.abspath(__file__)))
        colpevoli = []
        for v in ra.LAVORI_IN_SOSPESO:
            prova = v.get("prova")
            if not prova or prova.get("tipo") != "testo":
                continue
            for cartella, inizio, fine in prova["dove"]:
                for n in ra._testo_dentro(radice, cartella, inizio, fine, prova["cerca"]):
                    if n in impianto:
                        colpevoli.append("«%s» risulta soddisfatto da %s (cerca %r)"
                                         % (v["nome"], n, prova["cerca"]))
        self.assertEqual([], colpevoli,
                         "una prova e' soddisfatta dal testo che la racconta: il lavoro "
                         "risulta fatto perche' la parola cercata e' scritta nell'impianto "
                         "delle prove, non perche' qualcuno l'abbia fatto -> %s"
                         % "; ".join(colpevoli))

    def test_lo_stato_e_MISURATO_e_diventa_DA_FARE_se_la_prova_non_trova_niente(self):
        """La direzione che conta: puntato su una cartella vuota, ogni lavoro deve tornare
        DA FARE. Se restasse FATTO vorrebbe dire che lo stato e' scritto, non misurato."""
        import tempfile
        ra = self._ra()
        with tempfile.TemporaryDirectory() as vuota:
            for v in ra.LAVORI_IN_SOSPESO:
                esito, _perche = ra.stato_del_lavoro(v, base=vuota)
                self.assertEqual("DA FARE", esito,
                                 "su una cartella vuota il lavoro «%s» risulta %r: quello "
                                 "stato non lo sta misurando nessuno" % (v["nome"], esito))

    def test_un_lavoro_SENZA_prova_viene_denunciato_non_dato_per_buono(self):
        """S7: se manca la premessa il controllo non e' verde, e' NON ESEGUITO."""
        ra = self._ra()
        esito, perche_lo_dico = ra.stato_del_lavoro({"nome": "finto senza prova"})
        self.assertEqual("SENZA PROVA", esito,
                         "una voce senza prova e' passata come se fosse a posto: %r"
                         % perche_lo_dico)

    def test_il_gancio_STAMPA_lo_stato_misurato_accanto_a_ogni_lavoro(self):
        """Si esegue il programma VERO e si guarda l'uscita: cercare la stringa nel sorgente
        sarebbe soddisfatto da un commento (sbaglio S6)."""
        import subprocess
        import sys as _sys
        radice = os.path.dirname(os.path.abspath(__file__))
        esito = subprocess.run([_sys.executable, os.path.join(radice, "collaudi",
                                                             "regole_avvio.py")],
                               cwd=radice, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        uscita = esito.stdout.decode("utf-8", errors="replace")
        self.assertIn("STATO MISURATO ADESSO", uscita,
                      "il gancio non stampa piu' lo stato misurato dei lavori in sospeso: "
                      "si torna a una lista scritta a mano, che resta indietro sempre")


class TestLaSentinellaEsterna(unittest.TestCase):
    """LA TESTA CHE NON MUORE COL SERVER — e la guardia che le sta addosso.

    `deploy/watchdog.sh` gira SUL VPS: se il VPS muore, muore con lui e nessuno grida. La
    seconda testa prevista dal progetto (`REMOTO=1`, dal PC del fondatore) era **manuale**, e
    a mano vuol dire mai. `.github/workflows/sentinella.yml` la rende automatica su macchine
    di GitHub: fuori dal VPS, fuori da casa, sempre accesa, senza account nuovi.

    ⚠️ Questa classe verifica la FORMA, non il comportamento: che il file ci sia, che sia
    programmato, che interroghi la salute e che sia capace di FALLIRE. Il comportamento lo
    esercita GitHub stessa ogni 15 minuti, e un giro rosso si vede nella tabella dei job.

    ⛔ Le ricerche nel testo si fanno DOPO aver tolto i commenti: una guardia che cerca una
    stringa nel sorgente e' soddisfatta da un commento (sbaglio S6), ed e' esattamente il
    difetto del test gemello in `test_email_ciclo.py:287`.
    """

    PERCORSO = os.path.join(QUI, ".github", "workflows", "sentinella.yml")

    def _doc(self):
        self.assertTrue(os.path.exists(self.PERCORSO),
                        "la sentinella esterna non c'e' piu': senza di lei, se il VPS muore "
                        "nessuno se ne accorge, perche' l'altro watchdog muore con lui")
        with io.open(self.PERCORSO, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _script(self):
        """Il testo degli step `run`, SENZA commenti e senza righe vuote."""
        righe = []
        for job in (self._doc().get("jobs") or {}).values():
            for passo in (job.get("steps") or []):
                for riga in (passo.get("run") or "").splitlines():
                    pulita = riga.strip()
                    if pulita and not pulita.startswith("#"):
                        righe.append(pulita)
        self.assertTrue(righe, "la sentinella non esegue NESSUN comando: e' un ornamento")
        return "\n".join(righe)

    def test_e_PROGRAMMATA_e_avviabile_a_mano(self):
        doc = self._doc()
        on = doc.get(True) or doc.get("on") or {}      # PyYAML legge `on:` come booleano True
        sched = on.get("schedule") or []
        self.assertTrue(sched, "la sentinella non e' programmata: girerebbe solo a mano, "
                               "cioe' mai -- ed e' il difetto che nasce per riparare")
        self.assertIn("workflow_dispatch", on,
                      "non si puo' avviare a mano: e' il modo di PROVARLA senza aspettare")

    def test_i_MINUTI_sono_dispari_e_non_e_una_superstizione(self):
        """GitHub documenta che i lavori programmati possono essere RITARDATI o SALTATI sotto
        carico, e il carico si concentra al minuto 0 e 30, dove tutti programmano. I minuti
        dispari sono il rimedio noto. Se qualcuno rimettesse `0 * * * *`, la sentinella
        diventerebbe la piu' probabile a saltare -- e un controllo saltato e' un silenzio."""
        on = self._doc().get(True) or self._doc().get("on") or {}
        for voce in (on.get("schedule") or []):
            minuti = str(voce.get("cron", "")).split(" ")[0]
            self.assertNotIn(minuti, ("0", "30", "0,30"),
                             "programmata nell'ora di punta di GitHub (%r): e' li' che i "
                             "giri vengono ritardati o saltati" % (minuti,))
            self.assertTrue(any(c.isdigit() for c in minuti),
                            "il campo dei minuti non e' un numero: %r" % (minuti,))

    def test_INTERROGA_la_salute_del_sito_vero(self):
        s = self._script()
        doc_txt = io.open(self.PERCORSO, encoding="utf-8").read()
        self.assertIn("/api/health", doc_txt,
                      "la sentinella non interroga la salute: non guarda niente")
        self.assertIn("curl", s, "nessuna richiesta HTTP fuori dai commenti: e' un ornamento")

    def test_PUO_FALLIRE_davvero(self):
        """Un controllo che non puo' fallire e' un ornamento (regola dei 10 collaudi, modo 4).
        Qui si pretende che esistano uscite diverse da zero e che nessuno abbia messo un
        `|| true` sulle righe che decidono (regola ferrea 12: nasconde i fallimenti)."""
        s = self._script()
        self.assertIn("exit 1", s,
                      "la sentinella non esce MAI con errore: qualunque cosa trovi, il lavoro "
                      "resta verde e nessuno viene avvisato")
        for riga in s.splitlines():
            if "|| true" in riga:
                self.assertIn("cat ", riga,
                              "`|| true` su una riga che decide: nasconde il fallimento "
                              "(regola ferrea 12). Riga: %r" % (riga,))
        self.assertNotIn("continue-on-error", io.open(self.PERCORSO, encoding="utf-8").read(),
                         "il lavoro e' dichiarato non-bloccante: griderebbe nel vuoto")

    def test_UN_GUARDIANO_MUTO_fa_fallire_il_giro(self):
        """E' la ragione per cui questa sentinella esiste: vedere DA FUORI che la sentinella
        interna e' morta. Se `muto` non facesse fallire, guarderebbe solo che il sito
        risponde -- cioe' meta' del lavoro, con l'aria di averlo fatto tutto."""
        s = self._script()
        self.assertIn("muto", s,
                      "la sentinella non guarda lo stato del Guardiano dei soldi: controlla "
                      "solo che il sito risponda, e un Guardiano morto le sfugge")

    def test_UN_CAMPO_SPARITO_E_UN_ALLARME_non_un_perdono(self):
        """IL DEBITO E' STATO CHIUSO IL 2026-08-15, E QUESTA GUARDIA IMPEDISCE DI RIAPRIRLO.

        Per qualche ora la sentinella TOLLERAVA l'assenza del campo `guardiano`: il server non
        aveva ancora il codice che lo espone, e pretenderlo avrebbe fatto gridare il controllo
        ogni 15 minuti su un sito sano -- e un allarme sempre acceso viene spento (regola
        ferrea 10). Era una scelta giusta e PERICOLOSA: un «temporaneo» che nessuno toglie
        diventa cecita' permanente, ed e' il modo piu' comune in cui una rete di sicurezza si
        allarga fino a non prendere piu' niente.

        Il deploy e' stato fatto e verificato DALL'ESTERNO lo stesso giorno -- un giro vero di
        questa sentinella ha letto `guardiano: ok` sul sito -- quindi il perdono e' stato
        tolto lo stesso giorno, non "quando capita".

        ⛔ Da adesso: se il campo sparisce (server tornato a una versione vecchia, oppure
        qualcuno che lo rimuove) la sentinella GRIDA. Senza quel campo controllerebbe solo che
        il sito risponda, cioe' meta' del lavoro con l'aria di averlo fatto tutto.
        """
        s = self._script()
        self.assertIn("ASSENTE", s,
                      "la sentinella non distingue piu' il caso «campo assente»: un server "
                      "tornato a una versione vecchia passerebbe inosservato")
        self.assertNotIn("exit 0", s,
                         "c'e' di nuovo un'uscita a ZERO esplicita nello script: era il "
                         "perdono per il campo assente, tolto il 2026-08-15 dopo il deploy. "
                         "Rimetterlo rende questa testa cieca a meta'")


class TestTrigger(unittest.TestCase):
    """Il gate deve girare sui push E sulle pull request, senza vie di fuga."""

    def setUp(self):
        self.doc = _doc_ci()
        self.trigger = _trigger(self.doc)

    def test_push_e_pull_request_su_master(self):
        self.assertIn("push", self.trigger)
        self.assertIn("pull_request", self.trigger)
        self.assertEqual(self.trigger["push"]["branches"], ["master"])
        self.assertEqual(self.trigger["pull_request"]["branches"], ["master"],
                         "senza il trigger pull_request il gate non gira sulle PR e "
                         "renderlo 'required' su GitHub bloccherebbe ogni merge per "
                         "sempre (il check non arriverebbe mai)")

    def test_nessun_filtro_che_permetta_a_un_commit_di_saltare_la_ci(self):
        for evento in ("push", "pull_request"):
            filtri = self.trigger[evento]
            for scappatoia in ("paths", "paths-ignore", "branches-ignore", "types"):
                self.assertNotIn(scappatoia, filtri,
                                 "il trigger %r ha un filtro %r: esisterebbe una "
                                 "categoria di commit che non passa dal gate"
                                 % (evento, scappatoia))

    def test_zap_e_manuale_e_settimanale_non_ad_ogni_commit(self):
        self.assertIn("schedule", self.trigger)
        self.assertIn("workflow_dispatch", self.trigger)
        condizione = self.doc["jobs"]["zap"].get("if", "")
        self.assertIn("schedule", condizione)
        self.assertIn("workflow_dispatch", condizione)

    def test_token_di_ci_a_privilegi_minimi(self):
        self.assertEqual(self.doc["permissions"], {"contents": "read"},
                         "il token della CI deve poter solo LEGGERE il repository")


class TestNeedsDelGateCompleto(unittest.TestCase):
    """Nessun job bloccante puo' restare fuori dai `needs` del gate."""

    def setUp(self):
        self.testo = _testo_ci()
        self.doc = _doc_ci()
        self.jobs = set(self.doc["jobs"])
        self.needs = list(self.doc["jobs"][GATE]["needs"])
        self.bloccanti = _elenco_dichiarato(self.testo, "BLOCCANTI (entrano", self.jobs,
                                            fermate=("NON BLOCCANTI", "ATTENZIONE"))
        self.non_bloccanti = _elenco_dichiarato(self.testo, "NON BLOCCANTI", self.jobs,
                                                fermate=("BLOCCANTI (entrano",
                                                         "ATTENZIONE"))

    def test_la_mappa_in_testa_al_file_e_leggibile_e_non_vuota(self):
        """Ancora contro l'auto-assoluzione: se il lettore della mappa smettesse di
        leggere e tornasse una lista vuota, i due confronti dinamici qui sotto
        potrebbero passare a vuoto. Questa lista scritta a mano lo impedisce."""
        self.assertEqual(sorted(self.bloccanti),
                         ["accessibilita", "atheris", "copertura", "full-suite",
                          "full-suite-311", "immagine", "money-smoke", "mutazione",
                          "qualita", "w3c"],
                         "se hai aggiunto un job BLOCCANTE devi aggiornare questa "
                         "lista di proposito, dopo esserti accertato che sia anche "
                         "nei needs del gate: e' il punto in cui la decisione si "
                         "prende invece di scivolare")
        self.assertEqual(sorted(self.non_bloccanti), ["browser", "lint-severo", "zap"],
                         "un job non bloccante in piu' significa un controllo il cui "
                         "rosso non ferma nessuno: deve essere una scelta esplicita")

    def test_ogni_job_del_file_e_classificato(self):
        classificati = set(self.bloccanti) | set(self.non_bloccanti) | {GATE}
        self.assertEqual(
            self.jobs - classificati, set(),
            "questi job esistono ma non sono ne' dichiarati bloccanti ne' dichiarati "
            "non bloccanti nella mappa in testa a ci.yml: nessuno sa se il loro rosso "
            "conta. Classificali (e se sono bloccanti, mettili nei needs del gate).")
        self.assertEqual(classificati - self.jobs, set(),
                         "la mappa in testa a ci.yml elenca job che non esistono piu'")

    def test_i_needs_del_gate_sono_esattamente_i_bloccanti(self):
        self.assertEqual(sorted(self.needs), sorted(self.bloccanti),
                         "i needs del gate e la mappa dei bloccanti divergono: uno dei "
                         "due mente. Se un bloccante non e' nei needs, il gate resta "
                         "VERDE mentre quel job e' rosso.")

    def test_i_needs_del_gate_sono_tutti_i_job_meno_i_non_bloccanti(self):
        attesi = self.jobs - set(self.non_bloccanti) - {GATE}
        self.assertEqual(set(self.needs), attesi,
                         "un job nuovo e' stato aggiunto senza entrare nel gate")
        self.assertEqual(len(self.needs), len(set(self.needs)),
                         "un job compare due volte nei needs")
        self.assertNotIn(GATE, self.needs)

    def test_i_non_bloccanti_hanno_un_motivo_verificabile(self):
        """Stare fuori dal gate non e' un'opinione: deve avere un appiglio nel file."""
        zap = self.doc["jobs"]["zap"]
        self.assertIn("github.event_name", zap.get("if", ""),
                      "zap sta fuori dal gate perche' gira solo a schedule/manuale: se "
                      "quel gating sparisse, girerebbe ad ogni commit senza che il suo "
                      "esito conti per nessuno")
        lint = self.doc["jobs"]["lint-severo"]
        self.assertIn("NON blocca", lint.get("name", ""),
                      "lint-severo deve dichiarare nel proprio nome che non blocca: e' "
                      "cio' che si legge nell'elenco dei check su GitHub")
        # `browser` (2026-08-18) sta fuori dal gate a termine: finche' ci sta, chi legge
        # l'elenco dei check su GitHub deve vedere DAL NOME che il suo rosso non ferma
        # nessuno. Il giorno che entra nel gate, questa riga si toglie insieme al nome.
        browser = self.doc["jobs"]["browser"]
        self.assertIn("NON blocca", browser.get("name", ""),
                      "browser deve dichiarare nel proprio nome che non blocca: un "
                      "check che sembra bloccante e non lo e' e' peggio che non averlo")

    def test_il_gate_gira_sempre_anche_quando_qualcuno_e_rosso(self):
        gate = self.doc["jobs"][GATE]
        self.assertEqual(str(gate.get("if")).strip(), "always()",
                         "senza `if: always()` il gate viene SALTATO appena un job da "
                         "cui dipende fallisce, e un job saltato non da' nessun rosso")
        self.assertNotIn("continue-on-error", gate)
        self.assertIn("required", gate.get("name", ""),
                      "il nome del gate deve dire a cosa serve: e' il check da rendere "
                      "required nella branch protection")


class TestCondizioneDelVerdetto(unittest.TestCase):
    """La condizione non viene creduta: viene parsata e valutata su ogni esito.

    Nota sulla semantica di GitHub, che qui e' portante: un passo con un `if` che non
    contiene una funzione di stato (always(), failure(), ...) si porta dietro un
    `success()` implicito in AND. Quindi il passo del verdetto rosso gira solo se i
    passi precedenti del gate sono riusciti - e se uno di quelli fallisse, il job
    sarebbe rosso comunque. In tutti i casi il gate fallisce in chiusura: non esiste
    la combinazione "qualcosa e' andato storto ma il gate e' verde".
    """

    def setUp(self):
        self.doc = _doc_ci()
        gate = self.doc["jobs"][GATE]
        self.passi = _passi(gate)
        self.quanti = len(gate["needs"])
        rossi = [p for p in self.passi
                 if isinstance(p.get("run"), str) and "exit 1" in p["run"]]
        self.assertEqual(len(rossi), 1,
                         "nel gate deve esserci UNO e un solo passo che fa fallire il "
                         "job; trovati %d" % len(rossi))
        self.rosso = rossi[0]
        self.i_rosso = self.passi.index(self.rosso)

    def test_la_condizione_e_scritta_in_una_forma_riconoscibile(self):
        stati = stati_catturati(self.rosso["if"])
        self.assertEqual(sorted(set(stati)), ["cancelled", "failure", "skipped"])
        self.assertEqual(len(stati), len(set(stati)), "termine ripetuto")

    def test_il_passo_rosso_fa_fallire_davvero_il_job(self):
        self.assertIn("exit 1", self.rosso["run"])
        self.assertNotIn("|| true", self.rosso["run"])
        self.assertNotIn("continue-on-error", self.rosso)
        self.assertIn("::error", self.rosso["run"],
                      "il rosso deve anche dire A SCHERMO perche' e' rosso")

    def test_ogni_esito_non_verde_di_ogni_needs_fa_scattare_il_rosso(self):
        stati = stati_catturati(self.rosso["if"])
        for posizione in range(self.quanti):
            for cattivo in ESITI_NON_VERDI:
                risultati = ["success"] * self.quanti
                risultati[posizione] = cattivo
                with self.subTest(job=posizione, esito=cattivo):
                    self.assertTrue(
                        verdetto_rosso(stati, risultati),
                        "il job in posizione %d con esito %r passerebbe indisturbato"
                        % (posizione, cattivo))

    def test_tutti_verdi_resta_verde(self):
        """Una condizione sempre-vera bloccherebbe tutto: sarebbe l'altro difetto."""
        stati = stati_catturati(self.rosso["if"])
        self.assertFalse(verdetto_rosso(stati, ["success"] * self.quanti))

    def test_il_valutatore_vede_rosso_su_una_condizione_debole(self):
        """VISTO ROSSO del controllo stesso: su condizioni volutamente guaste il
        valutatore DEVE denunciare gli esiti che scapperebbero."""
        vera = stati_catturati(self.doc["jobs"][GATE]["steps"][self.i_rosso]["if"])
        self.assertEqual(esiti_che_scappano(vera, self.quanti), [])
        self.assertEqual(esiti_che_scappano(["failure"], self.quanti),
                         ["cancelled", "skipped"])
        self.assertEqual(esiti_che_scappano(["failure", "cancelled"], self.quanti),
                         ["skipped"])
        self.assertEqual(sorted(esiti_che_scappano([], self.quanti)),
                         sorted(list(ESITI_NON_VERDI)))

    def test_il_parser_rifiuta_le_forme_che_non_sa_giudicare(self):
        for guasta in ("${{ always() }}",
                       "${{ contains(needs.*.result, 'failure') && "
                       "contains(needs.*.result, 'cancelled') }}",
                       "${{ contains(needs.copertura.result, 'failure') }}",
                       "${{ failure() }}"):
            with self.subTest(condizione=guasta):
                self.assertRaises(ValueError, stati_catturati, guasta)

    def test_il_passo_verde_non_puo_girare_dopo_il_rosso(self):
        """Se il passo del VERDE avesse `if: always()` stamperebbe "CI VERDE" anche
        subito dopo il rosso: il log direbbe l'opposto dell'esito."""
        verdi = [p for p in self.passi
                 if isinstance(p.get("run"), str) and "VERDE" in p["run"]]
        self.assertEqual(len(verdi), 1)
        verde = verdi[0]
        self.assertIsNone(verde.get("if"),
                          "il passo del verdetto verde non deve avere nessun `if`: "
                          "senza `if` gira solo se tutti i passi precedenti sono "
                          "riusciti, che e' esattamente cio' che serve")
        self.assertGreater(self.passi.index(verde), self.i_rosso,
                           "il verdetto verde deve stare DOPO il rosso")

    def test_il_gate_stampa_l_esito_di_ogni_singolo_needs(self):
        """Chi apre la CI deve vedere QUALE job e' rosso, non solo che qualcosa lo e'."""
        testo = "\n".join(_run_dei_passi(self.doc["jobs"][GATE]))
        for job in self.doc["jobs"][GATE]["needs"]:
            riferimento = ("needs['%s'].result" % job) if "-" in job \
                else ("needs.%s.result" % job)
            self.assertIn(riferimento, testo,
                          "il riepilogo del gate non mostra l'esito di %r" % job)


# ---------------------------------------------------------------------------
#  Il caso che nessuno scenario copriva: un job che NON CONSEGNA NIENTE.
#
#  Tutti gli scenari qui sopra costruiscono SEMPRE un elenco lungo quanto i
#  needs e ne guastano una casella. Il 2026-08-06 la realta' ne ha prodotto un
#  altro, e due volte di fila, sulla run 627 del commit a67eef6:
#    - tentativo 1: cinque job bloccanti morti nel passo "Set up job"
#      ("Failed to resolve action download info", "Service Unavailable");
#    - tentativo 2: tre job bloccanti mai partiti
#      ("The job was not acquired by Runner of type hosted").
#  In tutti e due i casi il gate ha concluso `success` con il passo del verdetto
#  rosso SALTATO. La seconda volta gli esiti erano `cancelled`, cioe' una delle
#  tre parole che la sua condizione dichiara per iscritto di sorvegliare.
#
#  COSA E' MISURATO E COSA NO (D22, e non si imbroglia). Misurato dall'API:
#  gli esiti dei job, l'esito del gate, i passi saltati, le note di GitHub e
#  l'incidente "critical" su Actions aperto alle 15:22. NON misurato: il
#  MECCANISMO. Il log del gate risponde 403 senza credenziali e le credenziali
#  non si toccano, quindi non sappiamo se `needs.*.result` fosse incompleto
#  oppure se l'orchestratore abbia compilato male il registro (fra le note della
#  run compare anche un "Internal server error").
#
#  Percio' questa guardia NON pretende di aver capito il meccanismo: pretende la
#  proprieta' che regge in ENTRAMBI i casi. "C'e' scritto da qualche parte
#  `failure`?" e' cieco per omissione; "sono arrivati TUTTI, e sono tutti
#  `success`?" no. E' la stessa lezione gia' pagata dalla rete di mutazione:
#  ogni guardia dichiara il proprio DENOMINATORE, non solo quanti rotti ha visto.
# ---------------------------------------------------------------------------


def verdetto_rosso_completo(espressione, esiti_arrivati):
    """Come GitHub valuta la condizione INTERA, denominatore compreso.

    `esiti_arrivati` e' l'elenco degli esiti che sono davvero arrivati: puo'
    essere piu' corto dei needs, ed e' esattamente il caso che il valutatore
    precedente non sapeva rappresentare.
    """
    stati, denominatore = _scomponi(espressione)
    if denominatore is not None and " ".join(esiti_arrivati) != denominatore:
        return True
    return verdetto_rosso(stati, esiti_arrivati)


class TestUnJobCheNonConsegnaNiente(unittest.TestCase):
    """Un esito che NON ARRIVA deve pesare quanto un esito ROSSO.

    Un job che non ottiene mai una macchina non e' "assente": e' un controllo
    che non e' stato fatto. Se il gate lo tratta come silenzio-assenso, il
    semaforo unico che protegge master diventa verde proprio nel momento in cui
    la CI e' meno affidabile - cioe' quando serve di piu'.
    """

    def setUp(self):
        self.doc = _doc_ci()
        gate = self.doc["jobs"][GATE]
        self.quanti = len(gate["needs"])
        rossi = [p for p in _passi(gate)
                 if isinstance(p.get("run"), str) and "exit 1" in p["run"]]
        self.assertEqual(len(rossi), 1,
                         "nel gate deve esserci UNO e un solo passo che lo fa "
                         "fallire; trovati %d" % len(rossi))
        self.condizione = rossi[0]["if"]
        self.stati = stati_catturati(self.condizione)

    def test_UN_JOB_CHE_NON_CONSEGNA_L_ESITO_FA_SCATTARE_IL_ROSSO(self):
        """Il caso vero del 2026-08-06: tre job annullati e gate VERDE."""
        for mancanti in range(1, self.quanti):
            presenti = ["success"] * (self.quanti - mancanti)
            with self.subTest(mancanti=mancanti):
                self.assertTrue(
                    verdetto_rosso_completo(self.condizione, presenti),
                    "%d job bloccanti su %d non hanno consegnato NESSUN esito e "
                    "il gate resta VERDE: cerca la parola 'failure' fra gli "
                    "esiti arrivati invece di contare quanti ne dovevano "
                    "arrivare, quindi un controllo che sparisce e' "
                    "indistinguibile da un controllo passato"
                    % (mancanti, self.quanti))

    def test_ZERO_ESITI_ARRIVATI_NON_E_UN_SUCCESSO(self):
        """Il caso estremo: non ha girato NIENTE, e il gate dice VERDE."""
        self.assertTrue(
            verdetto_rosso_completo(self.condizione, []),
            "con ZERO esiti ricevuti il gate e' verde: e' il verde piu' finto "
            "possibile, perche' non e' stato controllato proprio niente")

    def test_TUTTI_ARRIVATI_E_TUTTI_VERDI_RESTA_VERDE(self):
        """L'altra direzione. Una guardia che grida sempre viene spenta, e un
        falso allarme e' un difetto quanto un allarme mancato (regola ferrea 10)."""
        self.assertFalse(
            verdetto_rosso_completo(self.condizione, ["success"] * self.quanti),
            "il gate diventa rosso anche a macchina sana: cosi' nessuno potrebbe "
            "piu' unire niente, e in due giorni qualcuno toglierebbe il controllo")

    def test_CONTARE_NON_FA_PERDERE_DI_VISTA_I_ROSSI_NORMALI(self):
        """Il denominatore si AGGIUNGE ai tre esiti sorvegliati, non li sostituisce."""
        for posizione in range(self.quanti):
            for cattivo in ESITI_NON_VERDI:
                arrivati = ["success"] * self.quanti
                arrivati[posizione] = cattivo
                with self.subTest(job=posizione, esito=cattivo):
                    self.assertTrue(
                        verdetto_rosso_completo(self.condizione, arrivati),
                        "il job in posizione %d con esito %r passerebbe "
                        "indisturbato" % (posizione, cattivo))

    def test_IL_DENOMINATORE_DICHIARATO_E_RICALCOLATO_DAI_NEEDS(self):
        """La stringa nel file non si legge: si RIFA' dal numero di job.

        E' il pezzo che impedisce alla riparazione di marcire: chi aggiunge un
        job bloccante senza allungare quella riga trova rosso lo stesso giorno.
        """
        dichiarato = denominatore_preteso(self.condizione)
        self.assertIsNotNone(
            dichiarato,
            "la condizione del verdetto non conta quanti esiti sono arrivati: "
            "e' cieca per omissione, ed e' il difetto visto il 2026-08-06")
        self.assertEqual(
            dichiarato, " ".join(["success"] * self.quanti),
            "il gate dichiara un numero di esiti attesi diverso dai suoi %d "
            "needs: uno dei due mente" % self.quanti)

    def test_LA_CONDIZIONE_DI_IERI_SAREBBE_ROSSA_QUI(self):
        """VISTO ROSSO, e inchiodato nella suite per sempre.

        Se un domani qualcuno riscrive la condizione com'era prima del
        2026-08-06, questa guardia ridiventa rossa lo stesso giorno. E la
        seconda meta' del test dimostra che il valutatore non e' rotto: quella
        condizione i rossi VERI li vedeva benissimo.
        """
        ieri = ("${{ contains(needs.*.result, 'failure') "
                "|| contains(needs.*.result, 'cancelled') "
                "|| contains(needs.*.result, 'skipped') }}")
        self.assertFalse(
            verdetto_rosso_completo(ieri, ["success"] * (self.quanti - 1)),
            "la condizione di ieri avrebbe dovuto lasciar scappare un job che "
            "non consegna niente: se non e' cosi', questa guardia non sta "
            "misurando il difetto che dice di misurare")
        self.assertTrue(
            verdetto_rosso_completo(
                ieri, ["success"] * (self.quanti - 1) + ["failure"]),
            "la condizione di ieri vedeva i rossi veri: se qui risultasse cieca "
            "anche a quelli, il valutatore sarebbe guasto")


class TestJobCopertura(unittest.TestCase):
    """La soglia esiste, misura i rami, e l'ultimo passo la fa valere."""

    def setUp(self):
        self.doc = _doc_ci()
        self.job = self.doc["jobs"]["copertura"]
        with io.open(COVERAGERC, encoding="utf-8") as f:
            self.rc = f.read()

    def test_coveragerc_esiste_misura_i_rami_e_solo_il_prodotto_vivo(self):
        self.assertTrue(os.path.isfile(COVERAGERC))
        self.assertIn("branch = True", self.rc,
                      "senza branch=True si misurano solo le righe: un `if` con il "
                      "ramo else mai provato risulterebbe coperto al 100%")
        self.assertIn("source = .", self.rc)
        for fuori in ("test_*.py", "collaudi/*", "_archivio/*", "app.py"):
            self.assertIn(fuori, self.rc,
                          "%r deve restare fuori dalla misura: non e' prodotto vivo "
                          "e gonfierebbe (o sgonfierebbe) la percentuale" % fuori)

    def test_la_soglia_e_dichiarata_e_a_cricchetto(self):
        grezzo = self.job["env"]["COVERAGE_MIN"]
        self.assertIsInstance(grezzo, str,
                              "COVERAGE_MIN va scritto fra apici: senza, YAML lo "
                              "carica come numero e l'espansione in shell cambia")
        self.assertTrue(grezzo.isdigit())
        self.assertGreaterEqual(int(grezzo), 82,
                                "CRICCHETTO: la soglia di copertura puo' solo salire. "
                                "82 e' la misura vera gia' raggiunta (82,5% su 23.436 "
                                "righe e 6.488 rami): abbassarla vorrebbe dire "
                                "cancellare prove gia' scritte.")
        self.assertLessEqual(int(grezzo), 100)

    def test_la_misura_gira_sulla_suite_intera(self):
        comandi = "\n".join(_run_dei_passi(self.job))
        self.assertIn("coverage run -m unittest discover", comandi,
                      "la copertura va misurata sulla suite INTERA, non su un "
                      "sottoinsieme scelto a mano (sarebbe una misura addomesticata)")
        self.assertIn('-p "test_*.py"', comandi)

    def test_l_ultimo_passo_e_il_cricchetto_e_non_ha_scappatoie(self):
        passi = _passi(self.job)
        ultimo = passi[-1]
        self.assertIn("coverage report --fail-under=${COVERAGE_MIN}", ultimo["run"],
                      "l'ultimo passo del job deve essere il confronto con la soglia, "
                      "e deve leggere COVERAGE_MIN (non un numero riscritto a mano)")
        self.assertNotIn("|| true", ultimo["run"])
        self.assertNotIn("continue-on-error", ultimo)
        self.assertIsNone(ultimo.get("if"),
                          "il passo della soglia non deve avere `if: always()`: con "
                          "always() girerebbe anche dopo una suite rossa e i suoi "
                          "numeri sarebbero senza senso")

    def test_i_passi_di_report_non_mascherano_la_suite_rossa(self):
        """`if: always()` sui report va bene (il numero si vuole comunque), ma nessuno
        di essi deve inghiottire il fallimento della suite."""
        passi = _passi(self.job)
        misure = [p for p in passi
                  if isinstance(p.get("run"), str) and "coverage run" in p["run"]]
        self.assertEqual(len(misure), 1)
        self.assertIsNone(misure[0].get("if"))
        self.assertNotIn("|| true", misure[0]["run"])
        self.assertNotIn("continue-on-error", self.job)

    def test_il_report_html_viene_conservato(self):
        usi = [p.get("uses", "") for p in _passi(self.job)]
        self.assertTrue(any(u.startswith("actions/upload-artifact@") for u in usi),
                        "il dettaglio riga-per-riga deve restare scaricabile: senza, "
                        "un rosso di copertura non e' diagnosticabile")


class TestNienteScappatoie(unittest.TestCase):
    """continue-on-error, azioni deprecate, `|| true` sui gate veri."""

    def setUp(self):
        self.testo = _testo_ci()
        self.doc = _doc_ci()
        self.needs = list(self.doc["jobs"][GATE]["needs"])

    def test_nessun_continue_on_error_nei_job_bloccanti(self):
        colpevoli = []
        for nome in self.needs + [GATE]:
            job = self.doc["jobs"][nome]
            if job.get("continue-on-error"):
                colpevoli.append("%s (job intero)" % nome)
            for i, passo in enumerate(_passi(job)):
                if passo.get("continue-on-error"):
                    colpevoli.append("%s passo %d (%s)"
                                     % (nome, i, passo.get("name", "senza nome")))
        self.assertEqual(colpevoli, [],
                         "continue-on-error rende VERDE un job che ha fallito: il gate "
                         "lo vedrebbe come success. Job coinvolti: %s" % colpevoli)

    def test_i_sette_gate_veri_non_sono_annullati_da_or_true(self):
        for nome, comando in sorted(COMANDI_CHE_DEVONO_BLOCCARE.items()):
            with self.subTest(job=nome):
                self.assertIn(nome, self.needs)
                passi = [p for p in _passi(self.doc["jobs"][nome])
                         if isinstance(p.get("run"), str) and comando in p["run"]]
                self.assertEqual(len(passi), 1,
                                 "nel job %r il comando che deve bloccare (%r) non e' "
                                 "unico: trovate %d occorrenze"
                                 % (nome, comando, len(passi)))
                self.assertNotIn("|| true", passi[0]["run"],
                                 "nel job %r il gate vero e' annullato da `|| true`: "
                                 "esce sempre 0 e non puo' bloccare niente"
                                 % nome)
                self.assertIsNone(passi[0].get("continue-on-error"))

    def test_ruff_stretto_blocca_e_la_sua_lista_e_a_cricchetto(self):
        passi = [p["run"] for p in _passi(self.doc["jobs"]["qualita"])
                 if isinstance(p.get("run"), str) and "--select" in p["run"]]
        self.assertEqual(len(passi), 1)
        self.assertNotIn("|| true", passi[0])
        for regola in ("E9", "F82", "S102", "S307", "S324", "S506", "S602", "S701"):
            self.assertIn(regola, passi[0],
                          "CRICCHETTO del lint: la regola %r e' sparita dalla "
                          "selezione stretta. A quella lista si aggiunge soltanto."
                          % regola)

    def test_chi_non_blocca_sui_rilievi_lo_dichiara_e_chi_blocca_no(self):
        """Il difetto piu' insidioso: un commento che promette un controllo che il
        comando sotto non fa. Qui commento e comando devono dire la stessa cosa."""
        for nome in self.needs:
            job = self.doc["jobs"][nome]
            comandi = _comandi_di_controllo(job)
            self.assertTrue(comandi, "il job %r non esegue nessun controllo" % nome)
            senza_denti = all("|| true" in c for c in comandi)
            commento = _blocco_di_commento_sopra(self.testo, nome)
            dichiarato = MARCATORE_SENZA_DENTI in commento
            with self.subTest(job=nome):
                self.assertEqual(
                    senza_denti, dichiarato,
                    "il job %r: ogni comando neutralizzato con `|| true` = %s, ma la "
                    "dichiarazione %r nel suo commento = %s. O il commento mente sul "
                    "codice, o il codice e' cambiato senza aggiornare il commento."
                    % (nome, senza_denti, MARCATORE_SENZA_DENTI, dichiarato))

    def test_nessuna_azione_deprecata(self):
        usati = re.findall(r"uses:\s*([\w.-]+/[\w.-]+)@v(\d+)", self.testo)
        self.assertTrue(usati, "nessun `uses:` trovato: il file non e' quello atteso")
        vecchie = []
        for azione, versione in usati:
            minima = VERSIONE_MINIMA_AZIONI.get(azione)
            if minima is not None and int(versione) < minima:
                vecchie.append("%s@v%s (minimo v%d)" % (azione, versione, minima))
        self.assertEqual(vecchie, [],
                         "azioni deprecate: girano su un runtime Node ritirato o sono "
                         "state spente da GitHub. %s" % vecchie)
        for azione in VERSIONE_MINIMA_AZIONI:
            if azione in self.testo:
                self.assertIn(azione + "@v", self.testo,
                              "%r usata senza versione esplicita" % azione)

    def test_nessun_comando_di_workflow_ritirato(self):
        for ritirato in COMANDI_RITIRATI:
            self.assertNotIn(ritirato, self.testo,
                             "%r e' stato ritirato da GitHub: il passo che lo usa non "
                             "fa piu' quello che crede, e non fallisce" % ritirato)

    def test_ogni_azione_e_agganciata_a_una_versione_non_a_un_ramo(self):
        riferimenti = re.findall(r"uses:\s*(\S+)", self.testo)
        self.assertTrue(riferimenti)
        mobili = [r for r in riferimenti
                  if not re.search(r"@(v\d+(\.\d+)*|[0-9a-f]{40})$", r)]
        self.assertEqual(mobili, [],
                         "queste azioni sono agganciate a un ramo mobile (@main, "
                         "@master, @latest): il contenuto puo' cambiare sotto i piedi "
                         "della CI senza che nessuno tocchi il repo. %s" % mobili)

    def test_i_job_bloccanti_non_hanno_condizioni_che_li_facciano_sparire(self):
        for nome in self.needs:
            with self.subTest(job=nome):
                self.assertIsNone(
                    self.doc["jobs"][nome].get("if"),
                    "il job bloccante %r ha una condizione al livello del job: "
                    "esisterebbe un evento in cui non gira, e il gate lo vedrebbe "
                    "'skipped'" % nome)


class TestLeDIMOSTRAZIONIMatematicheGIRANODavveroInCI(unittest.TestCase):
    """LE PROVE PIU' FORTI CHE ABBIAMO ERANO VERDI PERCHE' NON VENIVANO ESEGUITE.

    ⛔ Misurato il 2026-08-15, ed e' il pezzo **A** del piano. `z3-solver` non e' fra le
    dipendenze installate dalla CI (`pip install -r requirements.txt hypothesis pyyaml
    coverage`), quindi in CI `test_fase199_invarianti` e `test_fase199_transizioni` fanno
    `skipTest("z3 non installato")`: **35 test** che dimostrano matematicamente le leggi dei
    soldi e le transizioni delle prenotazioni **si saltano puliti**, e la tabella dei job
    resta VERDE. Sul computer del fondatore girano (z3 c'e'), quindi il buco era invisibile
    proprio dove si guarda di piu'.

    E' la forma peggiore di verde finto: non un test debole, ma un test forte **che non
    viene eseguito**. Un guasto nel nucleo degli invarianti passerebbe il cancello.

    ⛔ PERCHE' LA CURA NON E' `requirements.txt`. Quel file e' l'elenco di cio' che finisce
    **dentro l'immagine di produzione**: infilarci un risolutore matematico che il sito non
    usa mai gonfia il server per niente (regola ferrea 1, D1). z3 e' uno strumento **di
    collaudo**, quindi va nella riga d'installazione dei job che lanciano la suite -- e
    questa guardia pretende tutt'e due le cose insieme.
    """

    @staticmethod
    def _job_esegue_le_prove_z3(passi):
        """Il job arriva a `test_fase199_*`? Due modi, e servono tutt'e due.

        ⚠️ La prima versione di questa guardia cercava solo `unittest discover` e si e'
        lasciata sfuggire `full-suite-311`, che lancia la stessa suite con un elenco
        generato (`python -m unittest $(cat moduli_311.txt)`). Un job invisibile a una
        guardia e' peggio di nessuna guardia: da' la sensazione di essere coperti.
        ⛔ Al contrario `money-smoke` elenca a mano dodici moduli dei soldi e NON tocca
        `fase199`: obbligarlo a installare z3 sarebbe spreco, e un falso allarme e' un
        difetto quanto un allarme mancato (regola ferrea 10).
        """
        for p in passi:
            run = p.get("run")
            if not isinstance(run, str) or "-m unittest" not in run:
                continue
            # (a) tutta la suite: `discover`, oppure un elenco GENERATO -> ci passa dentro
            if "discover" in run or "$(" in run:
                return True
            # (b) elenco scritto a mano che nomina proprio quei test
            if "test_fase199" in run:
                return True
        return False

    def test_OGNI_job_che_esegue_le_prove_z3_LE_INSTALLA(self):
        """La formulazione conta: non «la riga 122 contiene z3», ma «ogni job che arriva a
        quei test installa la libreria». Cosi' la guardia sopravvive a una rinomina, e un
        job aggiunto domani senza z3 diventa rosso da solo."""
        doc = _doc_ci()
        senza = []
        for nome, job in doc["jobs"].items():
            passi = _passi(job)
            if not self._job_esegue_le_prove_z3(passi):
                continue
            installa = any(isinstance(p.get("run"), str)
                           and "z3-solver" in p["run"] for p in passi)
            if not installa:
                senza.append(nome)
        self.assertEqual(
            [], senza,
            "questi job arrivano alle dimostrazioni matematiche ma NON installano "
            "z3-solver: %s. Li' quelle prove si saltano in silenzio e la tabella resta "
            "verde -- cioe' il cancello proteggerebbe master senza aver controllato le "
            "prove piu' forti che abbiamo" % ", ".join(sorted(senza)))

    def test_LA_GUARDIA_VEDE_ANCHE_IL_JOB_CHE_NON_USA_discover(self):
        """Prova del METODO, non dello stato: e' il buco vero che avevo lasciato il
        2026-08-15. Se qualcuno restringesse il riconoscimento a `discover`, `full-suite-311`
        tornerebbe invisibile e nessuno se ne accorgerebbe."""
        finto = [{"run": "python -m unittest $(cat moduli_311.txt)"}]
        self.assertTrue(self._job_esegue_le_prove_z3(finto),
                        "un job che lancia la suite con un elenco GENERATO non viene "
                        "riconosciuto: resterebbe senza z3 e senza allarme")
        a_mano = [{"run": "python -m unittest test_paga_struttura test_conservazione_denaro"}]
        self.assertFalse(self._job_esegue_le_prove_z3(a_mano),
                         "un job che elenca a mano moduli che NON toccano fase199 viene "
                         "obbligato a installare z3: e' un falso allarme, e i falsi "
                         "allarmi insegnano a ignorare i segnali (regola ferrea 10)")

    def test_z3_NON_entra_nell_immagine_di_produzione(self):
        """L'altra meta', e non e' pignoleria: la scorciatoia comoda sarebbe metterlo in
        `requirements.txt`, e funzionerebbe. Ma quel file costruisce il server: ci
        entrerebbe un risolutore matematico che il sito non chiama mai. Uno strumento di
        collaudo non viaggia col prodotto."""
        import io as _io
        percorso = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "requirements.txt")
        with _io.open(percorso, encoding="utf-8") as f:
            elenco = f.read()
        self.assertNotIn(
            "z3", elenco.lower(),
            "z3 e' finito in requirements.txt: cosi' entra nell'immagine di produzione, "
            "dove non serve a niente. Va nella riga d'installazione dei job di collaudo")

    def test_le_prove_z3_si_saltano_SOLO_per_la_libreria_mancante(self):
        """S7 e D23: un salto e' ammesso solo se dipende dall'AMBIENTE, mai da cio' che il
        test dovrebbe verificare. Se domani qualcuno allargasse quella condizione, i 35 test
        potrebbero assolversi da soli per un altro motivo e nessuno se ne accorgerebbe."""
        import io as _io
        radice = os.path.dirname(os.path.abspath(__file__))
        for nome in ("test_fase199_invarianti.py", "test_fase199_transizioni.py"):
            with _io.open(os.path.join(radice, nome), encoding="utf-8") as f:
                testo = f.read()
            self.assertIn("import z3", testo,
                          "%s non prova piu' a importare z3: il salto non e' piu' legato "
                          "alla libreria" % nome)
            for riga in testo.splitlines():
                if "skipTest(" in riga:
                    self.assertIn("z3", riga,
                                  "%s ha uno skipTest che NON parla di z3 (%r): un test "
                                  "che si assolve da solo per un motivo diverso "
                                  "dall'ambiente sparisce dal rapporto" % (nome, riga.strip()))


class TestSogliaProvataSulCampo(unittest.TestCase):
    """PUNTO 3: il comando del cricchetto viene ESEGUITO, non letto.

    Si costruisce una cartella sterile con un modulo di quattro istruzioni e un `if`,
    e un test che ne percorre un solo ramo. Numeri esatti, verificati:
        righe   = 3 coperte su 4              -> 75,0 %
        rami    = 1 percorso su 2             -> (3+1)/(4+2) = 66,7 %
    Con una soglia di 70:
        misurando SOLO le righe   -> 75,0 >= 70  -> exit 0   (passerebbe)
        misurando ANCHE i rami    -> 66,7 <  70  -> exit 2   (ROSSO)
    E' la prova che `branch = True` nel .coveragerc non e' un ornamento: cambia il
    verdetto a parita' di codice e di soglia.
    """

    MODULO = ("def classifica(n):\n"
              "    if n > 0:\n"
              "        return 'positivo'\n"
              "    return 'non positivo'\n")

    TEST = ("import unittest\n"
            "import modulo_vivo\n"
            "class T(unittest.TestCase):\n"
            "    def test_solo_il_ramo_positivo(self):\n"
            "        self.assertEqual(modulo_vivo.classifica(1), 'positivo')\n")

    def setUp(self):
        self.cartella = tempfile.mkdtemp(prefix="cricchetto_")
        self.addCleanup(shutil.rmtree, self.cartella, True)

    def _scrivi(self, nome, testo):
        with io.open(os.path.join(self.cartella, nome), "w", encoding="utf-8") as f:
            f.write(testo)

    def _prepara(self, rami):
        self._scrivi("modulo_vivo.py", self.MODULO)
        self._scrivi("test_uno.py", self.TEST)
        self._scrivi(".coveragerc",
                     "[run]\nbranch = %s\nsource = .\nomit =\n    test_*.py\n"
                     "[report]\nprecision = 1\n" % ("True" if rami else "False"))
        esito = self._coverage(["run", "-m", "unittest", "test_uno"])
        self.assertEqual(esito.returncode, 0,
                         "la misura non e' partita: %s" % esito.stderr[-400:])

    def _coverage(self, argomenti):
        return subprocess.run([sys.executable, "-m", "coverage"] + argomenti,
                              cwd=self.cartella, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True)

    def _percentuale(self):
        esito = self._coverage(["report"])
        self.assertEqual(esito.returncode, 0, esito.stderr[-400:])
        ultima = [r for r in esito.stdout.splitlines() if r.startswith("TOTAL")]
        self.assertEqual(len(ultima), 1, esito.stdout)
        return ultima[0].split()[-1]

    def test_il_comando_del_cricchetto_esce_rosso_sotto_la_soglia(self):
        self._prepara(rami=True)
        self.assertEqual(self._percentuale(), "66.7%")
        sotto = self._coverage(["report", "--fail-under=70"])
        self.assertEqual(sotto.returncode, 2,
                         "il comando di soglia NON ha bloccato sotto la soglia: e' "
                         "questo il momento in cui il cricchetto smette di esistere")

    def test_lo_stesso_comando_esce_verde_sopra_la_soglia(self):
        """Un controllo che fallisce sempre e' inutile quanto uno che passa sempre."""
        self._prepara(rami=True)
        sopra = self._coverage(["report", "--fail-under=66"])
        self.assertEqual(sopra.returncode, 0, sopra.stdout[-400:])
        esatta = self._coverage(["report", "--fail-under=66.7"])
        self.assertEqual(esatta.returncode, 0,
                         "alla soglia esatta il confronto deve essere >=, non >")

    def test_misurare_i_rami_cambia_il_verdetto(self):
        """VISTO ROSSO su `branch = True`: si toglie e la stessa soglia passa."""
        self._prepara(rami=False)
        self.assertEqual(self._percentuale(), "75.0%")
        senza_rami = self._coverage(["report", "--fail-under=70"])
        self.assertEqual(senza_rami.returncode, 0,
                         "senza i rami il 70 passerebbe (75,0%)")
        self.setUp()
        self._prepara(rami=True)
        self.assertEqual(self._percentuale(), "66.7%")
        con_rami = self._coverage(["report", "--fail-under=70"])
        self.assertEqual(con_rami.returncode, 2,
                         "con i rami lo stesso identico codice deve fallire il 70: se "
                         "non fallisce, `branch = True` non e' arrivato alla misura")

    def test_e_proprio_il_comando_scritto_nel_job(self):
        """La prova vale solo se prova il comando VERO, non uno somigliante."""
        job = _doc_ci()["jobs"]["copertura"]
        ultimo = _passi(job)[-1]["run"].strip()
        self.assertEqual(ultimo, "coverage report --fail-under=${COVERAGE_MIN}")
        soglia = job["env"]["COVERAGE_MIN"]
        self._prepara(rami=True)
        vero = self._coverage(["report", "--fail-under=" + soglia])
        self.assertEqual(vero.returncode, 2,
                         "con la soglia VERA della CI (%s) e una copertura del 66,7%% "
                         "il job deve essere rosso" % soglia)


class TestRegolaDelMutanteInstabile(unittest.TestCase):
    """UN MUTANTE UCCISO SOLO A VOLTE NON E' UCCISO: E' IGNOTO.

    Il motore di mutazione e' il giudice dei TEST: rompe il motore di proposito e chiede
    "i test se ne accorgono?". Ma la sua regola era rovesciata rispetto alla realta': se un
    mutante sopravviveva al primo giro e moriva a uno dei due successivi, veniva contato
    fra gli UCCISI ("era una flakiness del killer"). Cosi' il punteggio si GONFIA -- ed e'
    proprio il numero che dovrebbe dirci la verita' sui test.

    Non e' teorico: il 2026-07-30 un mutante e' sopravvissuto 3 giri su 3 sulla CI ed e'
    stato ucciso in locale; l'avevamo archiviato come intoppo del runner. Con la regola
    giusta sarebbe rimasto IN SOSPESO -- che era la verita'.

    Meglio un punteggio piu' BASSO e onesto che uno alto e falso: e' la stessa cosa che
    vale per i 4.600 test.
    """

    @staticmethod
    def _classifica(*a):
        import importlib.util
        import os
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "collaudi", "mutazione_prodotto.py")
        spec = importlib.util.spec_from_file_location("_mut", p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m.classifica_mutante(*a)

    def test_muore_subito_e_UCCISO(self):
        """Deterministico: i test lo vedono al primo colpo."""
        self.assertEqual(self._classifica(False, []), "ucciso")

    def test_sopravvive_a_TUTTI_i_giri_e_un_BUCO(self):
        """Il job deve diventare rosso: quel punto non e' protetto."""
        self.assertEqual(self._classifica(True, [True, True]), "sopravvissuto")

    def test_visto_solo_A_VOLTE_e_INCERTO_non_ucciso(self):
        """LA REGOLA CAMBIATA. Prima questi finivano fra gli UCCISI."""
        self.assertEqual(self._classifica(True, [False, True]), "incerto")
        self.assertEqual(self._classifica(True, [True, False]), "incerto")
        self.assertEqual(self._classifica(True, [False, False]), "incerto")

    def test_il_riepilogo_MOSTRA_gli_incerti(self):
        """Un dato che non si vede non serve: la riga di riepilogo deve nominarli."""
        import io
        import os
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "collaudi", "mutazione_prodotto.py")
        s = io.open(p, encoding="utf-8", errors="replace").read()
        self.assertIn("INCERTI:", s, "il riepilogo non mostra gli incerti")
        self.assertIn("NON contano", s, "non e' dichiarato che non contano come uccisi")


class TestLeRegoleSiLeggonoSEMPRE(unittest.TestCase):
    """⛔ UN DIVIETO CHE NON PUO' FERMARTI NON E' UN DIVIETO (regola 17 dell'appendice).

    Il 2026-07-31 ho violato la REGOLA FERREA 15 — una regola scritta da me stesso — perche'
    stava in un file che non si ricarica a ogni sessione. La ricerca lo aveva perfino
    previsto («la compattazione e' amnesia: sopravvive solo CLAUDE.md»). Un regolamento di
    testo dipende da un lettore che si ricordi di leggerlo: e' una speranza, non un controllo.

    Da qui due cose meccaniche, che non dipendono dalla mia buona volonta':
      · un hook `SessionStart` stampa gli obblighi PRIMA di qualunque lavoro;
      · `permissions.deny` blocca i comandi che non devo mai eseguire.
    E questa guardia esiste perche' anche loro possono sparire in silenzio: un hook
    cancellato, un file di impostazioni escluso da git, un conteggio che smette di tornare.
    """

    @staticmethod
    def _radice():
        import os
        return os.path.dirname(os.path.abspath(__file__))

    def _impostazioni(self):
        import io
        import json
        import os
        p = os.path.join(self._radice(), ".claude", "settings.json")
        self.assertTrue(os.path.exists(p),
                        "manca .claude/settings.json: senza, i divieti sono solo prosa")
        with io.open(p, encoding="utf-8") as f:
            return json.load(f)          # un JSON rotto qui puo' impedire di lavorare

    def test_esiste_un_hook_che_stampa_le_regole_a_ogni_avvio(self):
        d = self._impostazioni()
        comandi = [h.get("command", "")
                   for blocco in d.get("hooks", {}).get("SessionStart", [])
                   for h in blocco.get("hooks", [])]
        self.assertTrue(any("regole_avvio" in c for c in comandi),
                        "nessun hook SessionStart mostra le regole: tornerebbero a dipendere "
                        "da qualcuno che si ricordi di leggerle. Comandi trovati: %r" % comandi)

    def test_lo_strumento_dell_hook_ESISTE_ed_esce_zero(self):
        """Un hook che punta a un file inesistente e' peggio di nessun hook: fa rumore
        d'errore a ogni avvio e nessuno legge piu' niente."""
        import os
        import subprocess
        import sys
        p = os.path.join(self._radice(), "collaudi", "regole_avvio.py")
        self.assertTrue(os.path.exists(p), "l'hook punta a un file che non esiste")
        r = subprocess.run([sys.executable, p], cwd=self._radice(),
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(0, r.returncode,
                         "lo strumento delle regole esce %s: un hook che fallisce blocca o "
                         "sporca ogni sessione.\n%s" % (r.returncode, (r.stderr or "")[-400:]))
        self.assertIn("TOTALE OBBLIGHI", r.stdout, "non stampa la mappa degli obblighi")

    def test_IL_REGOLAMENTO_DICE_IL_VERO_SU_SE_STESSO(self):
        """LA GUARDIA CHE CONTA. Il regolamento dichiara quanti obblighi ci sono; questo
        confronta la dichiarazione con il conteggio VERO dei file. Un regolamento che
        sbaglia il proprio numero e' una guardia che non guarda -- ed e' esattamente cosi'
        che il 2026-07-31 e' andata persa una regola per un giorno intero.
        """
        import os
        import subprocess
        import sys
        r = subprocess.run([sys.executable,
                            os.path.join(self._radice(), "collaudi", "regole_avvio.py")],
                           cwd=self._radice(), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        self.assertNotIn("NON DICE IL VERO", r.stdout,
                         "i numeri dichiarati in CLAUDE.md non coincidono con le regole "
                         "davvero presenti nei file:\n%s" % r.stdout[-700:])

    def test_le_direttive_del_fondatore_VIVONO_NEL_REPO_non_solo_in_memoria(self):
        """⛔ UN OBBLIGO CHE STA SOLO NELLA MEMORIA DI SESSIONE NON ESISTE ALTROVE.

        Il 2026-08-01 il conto diceva 74 e sembrava coerente, ma diciassette obblighi del
        fondatore -- chirurgia, mai chiedere credenziali, MAI heredoc, tre posti allineati...
        -- stavano SOLO nella memoria di sessione: non viaggiavano col progetto. Su un altro
        computer, o dentro la CI, semplicemente non c'erano. Lo strumento diceva «tutto
        coerente» e **mentiva senza saperlo**: una guardia che non guarda.

        Il rimedio non e' contarli meglio da un posto che non viaggia -- e' **portarli nel
        repo**, dove chiunque apra il progetto li trova. Questa guardia pretende che ci
        restino: se qualcuno li riporta fuori, diventa rossa lo stesso giorno.
        """
        import io
        import os
        import re
        with io.open(os.path.join(self._radice(), "CLAUDE.md"), encoding="utf-8") as f:
            testo = f.read()
        presenti = set(re.findall(r"^\*\*(D\d+)\.", testo, re.M))
        attese = set("D%d" % i for i in range(1, 23))
        self.assertEqual(set(), attese - presenti,
                         "queste direttive del fondatore sono uscite da CLAUDE.md e "
                         "tornerebbero a vivere solo in memoria: %r"
                         % sorted(attese - presenti))
        for chiave, perche in (
                ("MAI HEREDOC PER LE PATCH",
                 "gli heredoc infilano byte di controllo invisibili nelle patch"),
                ("LE CHIAVI NON SI CHIEDONO E NON SI STAMPANO",
                 "le credenziali non si chiedono al fondatore e non finiscono nei log"),
                ("CHIRURGIA SU RICHIESTA ESPLICITA",
                 "il metodo chirurgico annulla le campagne autonome"),
                ("AL 50% DEL CONTESTO SI SALVA TUTTO, SI ALLINEA TUTTO E SI RICOMINCIA DA CAPO",
                 "oltre meta' contesto l'IA afferma con lo stesso tono numeri mai misurati"),
                ("UN NUMERO SI SCRIVE SOLO CON LA MISURA CHE LO REGGE",
                 "un totale calcolato a mente e' finito in RIPRENDI_QUI.md come misurato")):
            self.assertIn(chiave, testo,
                          "la direttiva su %r non e' piu' nel repo (%s)" % (chiave, perche))

    def test_OGNI_regola_della_spina_dorsale_dice_COME_SI_VERIFICA(self):
        """⛔ UNA REGOLA CHE NON DICE COME SI CONTROLLA E' UN DESIDERIO, NON UNA REGOLA.

        E' esattamente la forma che produceva «tutto verde» e poi le sorprese: un obbligo
        scritto bene, che nessuno puo' smentire perche' non dice cosa guardare. Le 44 della
        ricerca lo dicono tutte; delle 15 ferree lo diceva solo un terzo finche' non e' stato
        chiuso il buco.
        """
        mute = self._motore_regole().senza_verifica()
        self.assertEqual([], mute,
                         "queste regole non dichiarano come si verificano, quindi non si "
                         "possono far fallire -- e cio' che non puo' fallire non protegge "
                         "niente: %r" % (mute,))

    def test_L_AUDIT_DI_VERIFICABILITA_SA_DAVVERO_ACCORGERSENE(self):
        """LA GUARDIA CHE CONTA (iniezione di guasto). Il test qui sopra e' verde: ma sarebbe
        verde ANCHE se `senza_verifica()` restituisse sempre la lista vuota. Qui gli si mette
        davanti un regolamento MALATO -- una regola senza il «si verifica» -- e si pretende
        che la veda. Poi si guarisce quella stessa regola e si pretende che taccia: senza il
        secondo verso, un controllo che grida sempre passerebbe per sveglio."""
        import io
        import os
        import tempfile
        m = self._motore_regole()
        scheletro = (
            "intestazione\n\n## REGOLA FERREA\n"
            "**1. UNA COSA.** prosa.\n**Si verifica:** con un comando.\n\n"
            "**2. ALTRA COSA.** prosa e basta.%s\n\n"
            "## LE 20 DIRETTIVE DEL FONDATORE\n"
            "**D1. QUALCOSA.** prosa.\n*Si verifica:* cosi'.\n\n"
            "## REGOLA DEI 10 COLLAUDI\n\n## DIRETTIVA OPERATIVA\n")
        vero = m.CLAUDE
        cartella = tempfile.mkdtemp()
        try:
            finto = os.path.join(cartella, "CLAUDE.md")
            m.CLAUDE = finto
            with io.open(finto, "w", encoding="utf-8") as f:
                f.write(scheletro % "")                       # regola 2 MUTA
            self.assertEqual(["FERREA 2"], m.senza_verifica(),
                             "l'audit non vede una regola priva del «si verifica»: e' un "
                             "controllo ornamentale, cioe' il difetto che deve scovare")
            with io.open(finto, "w", encoding="utf-8") as f:
                f.write(scheletro % "\n**Si verifica:** guardando il diff.")
            self.assertEqual([], m.senza_verifica(),
                             "l'audit segnala una regola che INVECE dice come si verifica: "
                             "griderebbe sempre, e un allarme sempre acceso viene spento")
        finally:
            m.CLAUDE = vero
            import shutil
            shutil.rmtree(cartella, ignore_errors=True)

    def test_le_DUE_FAMIGLIE_restano_distinte_e_il_totale_e_la_loro_somma(self):
        """Le 44 della ricerca sono costate ~4 milioni di gettoni e sono l'unica famiglia con
        fonte esterna e prova; le altre nascono dai nostri danni. Mescolarle in un numero solo
        fa perdere di vista cio' che e' stato pagato -- ed e' gia' successo. E il totale deve
        essere la SOMMA dei gruppi: se un gruppo viene contato due volte, o dimenticato, il
        cartello torna a mentire."""
        import os
        import re
        import subprocess
        import sys
        r = subprocess.run([sys.executable,
                            os.path.join(self._radice(), "collaudi", "regole_avvio.py")],
                           cwd=self._radice(), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        self.assertIn("DELLA RICERCA", r.stdout, "la famiglia della ricerca non e' piu' "
                                                 "distinta dalle altre")
        self.assertIn("nati dai NOSTRI danni", r.stdout, "l'altra famiglia non e' piu' "
                                                         "riconoscibile")
        n = self._motore_regole().conta_regole()
        atteso = (n["appendice"] + n["blocco"] + n["regola_zero"] + n["direttive"]
                  + n["modi"] + n["collaudi"] + n["finale"])
        self.assertGreaterEqual(n["blocco"], 6,
                                "i sei divieti assoluti del BLOCCO sono spariti da "
                                "CLAUDE.md: sono la cosa che si legge per prima")
        visto = re.search(r"TOTALE OBBLIGHI: (\d+)", r.stdout)
        self.assertIsNotNone(visto, "lo strumento non dichiara piu' un totale")
        self.assertEqual(atteso, int(visto.group(1)),
                         "il totale stampato non e' la somma dei gruppi contati nei file "
                         "(%d): un gruppo e' contato due volte o dimenticato" % atteso)
        self.assertEqual(15, n["ferrea"], "le regole ferree non sono piu' 15: se il taglio "
                                          "delle sezioni si rompe, ogni conteggio qui sopra "
                                          "diventa aria")
        # ⛔ NON un numero scritto a mano qui dentro: si confronta il conteggio VERO col
        # numero che il documento DICHIARA nel proprio titolo. Cosi' la guardia non va
        # ritoccata a ogni direttiva nuova (e nessuno e' tentato di allinearla senza
        # guardare), ma resta rossa il giorno in cui il taglio delle sezioni si rompe o il
        # titolo smette di dire il vero.
        import io
        import os
        with io.open(os.path.join(self._radice(), "CLAUDE.md"), encoding="utf-8") as f:
            titolo = re.search(r"LE (\d+) DIRETTIVE DEL FONDATORE", f.read())
        self.assertIsNotNone(titolo, "il titolo delle direttive non dichiara piu' quante sono")
        self.assertEqual(int(titolo.group(1)), n["direttive"],
                         "il titolo dice %s direttive ma nel testo ce ne sono %d"
                         % (titolo.group(1), n["direttive"]))
        self.assertGreaterEqual(n["direttive"], 22,
                                "il numero delle direttive del fondatore e' SCESO: una "
                                "direttiva non si toglie senza che qualcuno lo decida")

    def test_LA_STAMPA_D_AVVIO_DICE_LE_STESSE_PAROLE_DEL_REGOLAMENTO(self):
        """⛔ NIENTE PAROLE RISCRITTE A MANO: LA STAMPA E IL REGOLAMENTO SONO LA STESSA FONTE.

        Il 2026-08-06 l'elenco delle direttive stampato all'avvio era prosa scritta a mano:
        era rimasto indietro di una direttiva, e una frase e' nata GIA' diversa dal titolo
        vero senza che nulla lo dicesse. Un promemoria che dice una cosa diversa dalla regola
        e' peggio di nessun promemoria, perche' viene letto per primo e ci si fida.
        ⛔ E QUI SI DICHIARA IL DENOMINATORE: non «c'e' questa frase?», ma «ci sono TUTTE?».
        Un `assertIn` su un testo intero non sa quanti posti ha saltato (appendice #15), per
        questo prima si pretende che i titoli estratti siano tanti quante le direttive.
        """
        import os
        import re
        import subprocess
        import sys
        m = self._motore_regole()
        titoli = re.findall(r"^\*\*(D\d+)\. ([^*]+)\*\*", m._pezzi()["direttive"], re.M)
        quante = m.conta_regole()["direttive"]
        self.assertEqual(quante, len(titoli),
                         "i titoli estratti sono %d ma le direttive contate sono %d: il "
                         "denominatore di questa guardia non regge piu', e senza denominatore "
                         "non si sa quanti posti sono stati saltati" % (len(titoli), quante))
        r = subprocess.run([sys.executable,
                            os.path.join(self._radice(), "collaudi", "regole_avvio.py")],
                           cwd=self._radice(), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        for numero, titolo in titoli:
            atteso = " ".join(titolo.split())
            self.assertIn(atteso, r.stdout,
                          "lo strumento d'avvio non stampa il titolo di %s con le stesse "
                          "parole del regolamento: chi legge all'avvio riceve una regola "
                          "diversa da quella scritta. Manca: %r" % (numero, atteso))

    def test_L_AUDIT_VEDE_TUTTI_E_TRE_I_NUMERI_CHE_IL_REGOLAMENTO_DICHIARA(self):
        """LA GUARDIA CHE CONTA (iniezione di guasto, D22).

        Fino al 2026-08-06 lo strumento confrontava SOLO «GLI OBBLIGHI SONO N»: «GLI ALTRI N»
        e «N direttive del fondatore» erano lettera morta e potevano dire il falso restando
        verdi -- i numeri erano giusti per attenzione, non per costruzione. Qui si sporca un
        numero alla volta sul testo VERO e si pretende che lo strumento gridi; poi si pretende
        che taccia sul testo sano, perche' un allarme sempre acceso viene spento.
        """
        import contextlib
        import io
        import os
        import re
        import shutil
        import tempfile
        m = self._motore_regole()
        with io.open(m.CLAUDE, encoding="utf-8") as f:
            sano = f.read()
        vero = m.CLAUDE
        cartella = tempfile.mkdtemp()
        try:
            finto = os.path.join(cartella, "CLAUDE.md")
            m.CLAUDE = finto
            # ⛔ La sostituzione avviene sulla COPIA in memoria, mai sul file del progetto
            # (B2). Il file vero non viene mai riaperto in scrittura.
            for schema, sporco, atteso in (
                    (r"GLI OBBLIGHI SONO \*\*\d+\*\*", "GLI OBBLIGHI SONO **777**",
                     "dichiara 777 obblighi in totale"),
                    (r"GLI ALTRI \*\*\d+\*\*", "GLI ALTRI **777**",
                     "dichiara 777 obblighi «nati dai nostri danni»"),
                    (r"\*\*\d+ direttive del fondatore\*\*",
                     "**777 direttive del fondatore**",
                     "dichiara 777 direttive del fondatore"),
                    # ⛔ E IL TAGLIO DELLE SEZIONI: si rinomina un TITOLO. Prima del
                    # 2026-08-06 questo lasciava lo strumento VERDE con i confini a
                    # spazzatura, perche' `c[:None]` in Python e' una fetta legale.
                    (r"^# .*REGOLA ZERO", "# ⛔ LE FONDAMENTA",
                     "titolo di sezione «REGOLA ZERO» non trovato")):
                malato = re.sub(schema, sporco, sano, count=1, flags=re.M)
                self.assertNotEqual(sano, malato,
                                    "l'iniezione non ha cambiato niente: il regolamento non "
                                    "contiene piu' %r, quindi questa guardia non prova nulla"
                                    % schema)
                with io.open(finto, "w", encoding="utf-8") as f:
                    f.write(malato)
                uscita = io.StringIO()
                with contextlib.redirect_stdout(uscita):
                    m.main()
                # ⛔ NON basta «ha gridato»: si pretende che abbia gridato PER QUESTO. Un
                # allarme che suona per il motivo sbagliato passerebbe lo stesso.
                self.assertIn(atteso, uscita.getvalue(),
                              "lo strumento non vede il guasto %r: e' lettera morta e puo' "
                              "mentire restando verde.\n%s"
                              % (sporco, uscita.getvalue()[-600:]))
            with io.open(finto, "w", encoding="utf-8") as f:
                f.write(sano)
            uscita = io.StringIO()
            with contextlib.redirect_stdout(uscita):
                m.main()
            self.assertNotIn("NON DICE IL VERO", uscita.getvalue(),
                             "lo strumento grida sul regolamento SANO: un allarme che suona "
                             "sempre viene spento, e allora non protegge piu' niente")
        finally:
            m.CLAUDE = vero
            shutil.rmtree(cartella, ignore_errors=True)

    def test_IL_NUMERO_DELLA_SUITE_DICHIARATO_E_QUELLO_VERO(self):
        """⛔ UN NUMERO CALCOLATO A MENTE NON E' UN NUMERO MISURATO (D22).

        Il 2026-08-06 `RIPRENDI_QUI.md` dichiarava `Ran 5429` per un albero che ne conteneva
        5434: il totale era stato ottenuto sommando (5427 + 2 invece di + 7) invece di rifare
        la misura, e la sessione dopo ha dovuto fermare tutto per capire da dove venissero
        cinque test che nessuno aveva aggiunto. Questa guardia ricontrolla la cifra dichiarata
        contro il conteggio VERO del caricatore: se qualcuno aggiunge test e non aggiorna il
        documento, diventa rossa lo stesso giorno.

        ⛔ COSA QUESTA GUARDIA NON FA, dichiarato (D18 punto 3):
          · CONTA, NON GIUDICA. Duplicare 200 test la soddisferebbe alla perfezione
            (appendice #14): la qualita' la misura la larghezza di mutazione, non il totale.
          · IL NUMERO NON E' INVARIANTE FRA AMBIENTI. Misurato il 2026-08-06 sullo stesso
            albero: 3.9 con `hypothesis` -> 5437; 3.11 senza -> 5362, perche' 4 moduli non si
            importano. Per questo l'uguaglianza esatta si pretende SOLO dove l'ambiente e'
            completo; dove non lo e' si pretende comunque qualcosa (mai un `skipTest`), cioe'
            che il dichiarato sia MAGGIORE del raccolto: un ambiente monco puo' solo
            raccoglierne meno. Un cancello messo prima di conoscere la varianza e' un falso
            allarme che aspetta il suo giorno.
          · EFFETTO COLLATERALE: `discover()` importa i moduli di test del repo. Dentro la
            suite intera sono gia' importati e costa ~1s; lanciata da sola, questa guardia
            esegue il codice a livello di modulo di tutti i file di test.
        """
        import io
        import os
        import re
        import unittest as _unittest
        radice = self._radice()
        with io.open(os.path.join(radice, "RIPRENDI_QUI.md"), encoding="utf-8") as f:
            pagina = f.read()
        dichiarato = re.search(r"SUITE ATTUALE: Ran (\d+) test", pagina)
        self.assertIsNotNone(dichiarato,
                             "RIPRENDI_QUI.md non dichiara piu' `SUITE ATTUALE: Ran N test`: "
                             "senza quella riga il numero della suite torna a vivere nella "
                             "testa di chi scrive, che e' da dove veniva quello sbagliato")
        # D22: la cifra da sola non basta mai. Deve dire DOVE e' stata misurata e CON COSA,
        # altrimenti fra sei mesi nessuno sa se il numero vale per questo computer o per la CI.
        for etichetta in ("AMBIENTE:", "COMANDO:"):
            self.assertIn(etichetta, pagina,
                          "la riga `SUITE ATTUALE:` non dichiara piu' %r: un numero senza "
                          "l'ambiente e il comando che l'hanno prodotto non e' una misura, "
                          "e' un ricordo (D22)" % etichetta)
        suite = _unittest.defaultTestLoader.discover(radice, pattern="test_*.py")

        def _foglie(s):
            for x in s:
                if isinstance(x, _unittest.TestSuite):
                    for y in _foglie(x):
                        yield y
                else:
                    yield x

        rotti = sorted({t.id() for t in _foglie(suite)
                        if type(t).__name__ == "_FailedTest"})
        # ⛔ QUI C'ERA UN `skipTest`, ED ERA UNA ZONA CIECA. Il ragionamento sembrava
        # prudente ("se un modulo non si importa il numero non e' confrontabile, taccio per
        # non dare un falso allarme"), ma un test che si assolve da solo sparisce dal
        # rapporto come «skipped» e nessuno lo legge piu': lo vieta
        # `test_gli_skip_interni_sono_solo_per_l_ambiente`, che ha visto rossa proprio
        # questa riga. Si asserisce in TUTTI E DUE i rami -- ma non la stessa cosa, perche'
        # un ambiente senza le dipendenze opzionali raccoglie meno test senza che nessuno
        # abbia sbagliato niente.
        atteso, raccolti = int(dichiarato.group(1)), suite.countTestCases()
        if rotti:
            self.assertGreater(
                atteso, raccolti,
                "in questo ambiente %d moduli non si importano (%r) e il caricatore raccoglie "
                "%d test: il numero dichiarato (%d) dovrebbe essere MAGGIORE, perche' un "
                "ambiente monco puo' solo raccoglierne meno. Se e' minore, il documento e' "
                "vecchio davvero (D22)." % (len(rotti), rotti, raccolti, atteso))
        else:
            self.assertEqual(
                atteso, raccolti,
                "RIPRENDI_QUI.md dichiara %d test ma il caricatore ne trova %d, e qui "
                "l'ambiente e' completo (nessun modulo non importabile): la cifra e' stata "
                "scritta senza rifare la misura (D22)." % (atteso, raccolti))

    @staticmethod
    def _motore_regole():
        import importlib.util
        import os
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "collaudi", "regole_avvio.py")
        spec = importlib.util.spec_from_file_location("_reg_avvio", p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_i_divieti_veri_ci_sono_e_coprono_i_comandi_che_distruggono(self):
        d = self._impostazioni()
        negati = " | ".join(d.get("permissions", {}).get("deny", []))
        for pezzo, perche in (
                ("down -v", "cancella il VOLUME dei dati: 25 archivi, giornale contabile compreso"),
                ("docker-compose", "la versione 1 spegne il sito (successo il 2026-07-30)"),
                ("rm -rf /data", "cancella i dati di produzione"),
                ("--no-verify", "salta i controlli prima di spingere"),
                (".env", "i file dei segreti non si riscrivono mai (REGOLA FERREA 14)")):
            self.assertIn(pezzo, negati,
                          "manca il divieto su %r (%s): resterebbe solo una frase in un "
                          "documento" % (pezzo, perche))

    def test_le_impostazioni_VIAGGIANO_col_progetto(self):
        """Un divieto che vive solo sul computer di uno non protegge il progetto. E
        `.gitignore` ha una riga `*.json` che lo escluderebbe: serve l'eccezione esplicita."""
        import io
        import os
        with io.open(os.path.join(self._radice(), ".gitignore"), encoding="utf-8") as f:
            ignora = f.read()
        self.assertIn("!.claude/settings.json", ignora,
                      "senza l'eccezione in .gitignore le impostazioni restano locali: i "
                      "divieti non arriverebbero a nessun altro")


# ---------------------------------------------------------------------------
#  IL PASSAGGIO DI CONSEGNE NON PUO' RESTARE INDIETRO RISPETTO AL LAVORO.
#
#  Perche' esiste. D21 dice di scrivere il passaggio di consegne, ma per mesi non
#  e' successo, e il fondatore l'ha detto con parole sue: «ogni volta che riapro
#  una chat, dice che l'altra non ha scritto». Il difetto non e' pigrizia: il
#  blocco si scrive ALLA FINE, cioe' nel momento peggiore -- contesto pieno,
#  sessione che puo' essere interrotta. Cosi' il lavoro resta e la memoria no.
#
#  Fino al 2026-08-07 quell'obbligo era affidato alla buona volonta', e D22 dice
#  gia' come va a finire: «un obbligo affidato alla buona volonta' si rompe di
#  nuovo». Qui diventa un muro: se il documento resta indietro, la suite e' ROSSA
#  -- e siccome non si committa con la suite rossa, non si puo' andare avanti
#  lasciando le consegne vecchie. E' D18: non «ha barato?» ma «puo' barare?».
#
#  ⛔ COSA QUESTA GUARDIA NON FA, dichiarato (D18 punto 3):
#    · NON giudica se il testo delle consegne sia UTILE. Conta i commit, non le
#      idee: si puo' soddisfarla scrivendo sciocchezze. Serve a impedire il
#      silenzio, non a garantire la qualita'.
#    · NON puo' misurare dove il commit dichiarato non esiste: nella copia
#      estratta della chiavetta (niente `.git`) e sulla CI, che scarica con
#      profondita' 1. Li' NON si salta -- si pretende comunque che la riga esista
#      e sia un commit ben formato. Un salto silenzioso sarebbe la zona cieca che
#      questo progetto ha gia' pagato.
# ---------------------------------------------------------------------------
_RIGA_CONSEGNE = re.compile(r"^CONSEGNE AGGIORNATE A:\s*([0-9a-fA-F]{7,40})\s*$", re.M)


_PRE_VOLO = []          # cache: il modulo si carica una volta sola


def _pre_volo():
    """`collaudi/prima_di_lanciare.py`, caricato una volta sola."""
    if not _PRE_VOLO:
        import importlib.util
        p = os.path.join(QUI, "collaudi", "prima_di_lanciare.py")
        spec = importlib.util.spec_from_file_location("_pv_condiviso", p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _PRE_VOLO.append(m)
    return _PRE_VOLO[0]


def consegne_troppo_indietro(quanti_commit):
    """⛔ IL GIUDIZIO NON STA PIU' QUI: sta in `collaudi/prima_di_lanciare.py`, e questa
    funzione lo CHIAMA.

    UNO e' il commit che porta le consegne stesse: quello e' sano. DUE vuol dire che dopo
    aver scritto le consegne si e' committato altro lavoro senza toccarle. `None` = non
    misurabile qui (vedi la dichiarazione qui sopra).

    Perche' e' stato spostato il 2026-08-11: lo stesso criterio serve in due momenti --
    dentro la suite (dove diventa un rosso, dopo 68 minuti) e PRIMA di lanciarla (dove
    costa 5 centesimi di secondo). Tenerne due copie e' la malattia che questo progetto ha
    pagato sei volte in un giorno solo: lo stesso fatto scritto due volte, e la seconda
    copia che resta indietro senza che nessuno se ne accorga. Un posto solo, due chiamanti.
    """
    return _pre_volo().consegne_troppo_indietro(quanti_commit)


def _commit_da_allora(sha, radice):
    """Quanti commit VERI (le fusioni non contano) da `sha` a HEAD, o None."""
    import subprocess
    try:
        esito = subprocess.run(
            ["git", "rev-list", "--count", "--no-merges", "%s..HEAD" % sha],
            cwd=radice, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        return None
    if esito.returncode != 0:
        return None
    try:
        return int(esito.stdout.decode("utf-8", "replace").strip())
    except ValueError:
        return None


class TestIlPassaggioDiConsegneNonRestaINDIETRO(unittest.TestCase):
    """Chi apre una chat nuova deve trovare scritto dove siamo, non doverlo chiedere."""

    def setUp(self):
        import io
        percorso = os.path.join(QUI, "RIPRENDI_QUI.md")
        with io.open(percorso, encoding="utf-8") as f:
            self.pagina = f.read()

    def test_LA_RIGA_C_E_ED_E_UN_COMMIT(self):
        trovato = _RIGA_CONSEGNE.search(self.pagina)
        self.assertIsNotNone(
            trovato,
            "RIPRENDI_QUI.md non ha la riga `CONSEGNE AGGIORNATE A: <commit>`: senza "
            "quella riga nessuno puo' sapere se il passaggio di consegne descrive il "
            "lavoro di adesso o quello di tre settimane fa (D21)")
        self.sha = trovato.group(1)

    def test_NON_SI_LAVORA_DUE_COMMIT_SENZA_AGGIORNARLE(self):
        trovato = _RIGA_CONSEGNE.search(self.pagina)
        self.assertIsNotNone(trovato, "manca la riga `CONSEGNE AGGIORNATE A:`")
        quanti = _commit_da_allora(trovato.group(1), QUI)
        if quanti is None:
            # Non misurabile (copia estratta senza `.git`, o clone superficiale).
            # Non si salta: si pretende comunque la forma della riga.
            self.assertRegex(trovato.group(1), r"^[0-9a-fA-F]{7,40}$")
            return
        self.assertFalse(
            consegne_troppo_indietro(quanti),
            "dal commit dichiarato nelle consegne (%s) sono passati %d commit di "
            "lavoro: il passaggio di consegne descrive uno stato che non esiste "
            "piu'. Aggiorna il blocco in cima a RIPRENDI_QUI.md e rimetti in quella "
            "riga il commit di HEAD prima di committare (D21)."
            % (trovato.group(1), quanti))

    def test_IL_GIUDIZIO_SA_DIRE_SI_E_NO(self):
        """Le due direzioni: se dicesse sempre la stessa cosa non varrebbe niente."""
        self.assertFalse(consegne_troppo_indietro(0), "zero commit dopo: e' sano")
        self.assertFalse(consegne_troppo_indietro(1),
                         "UNO e' il commit che porta le consegne stesse: e' sano")
        self.assertTrue(consegne_troppo_indietro(2), "due commit dopo: e' indietro")
        self.assertTrue(consegne_troppo_indietro(37))
        self.assertFalse(consegne_troppo_indietro(None),
                         "dove non si puo' misurare non si inventa un rosso")


class TestIlControlloDeiQuattroPostiVedeCIOCHEGIRA(unittest.TestCase):
    """⛔ `git rev-parse` sul VPS legge il REPOSITORY, non l'immagine che GIRA.

    Trovato sul campo il 2026-08-07 sera. Il passaggio di consegne prescrive quattro
    comandi per misurare i quattro posti, e per il server dice `git rev-parse --short
    HEAD`. Quel comando risponde col commit dei FILE SU DISCO -- ma il sito gira dentro
    un contenitore costruito da un'IMMAGINE, e l'immagine puo' essere di giorni prima.

    Quella sera e' successo esattamente questo: dopo l'unione, il VPS diceva `42edded`
    mentre serviva un'immagine di 34 ore prima, senza le due riparazioni appena fatte.
    «Quattro posti allineati» sarebbe stato VERO sui file e FALSO su cio' che l'utente
    riceveva -- il verde peggiore, quello che non ha guardato la cosa giusta (D23).

    Fino al 2026-08-07 il difetto era invisibile perche' tutti i commit erano di soli
    documenti: il repository e l'immagine coincidevano per fortuna, non per costruzione.

    Questa guardia non puo' misurare il server (la suite gira anche senza rete e senza
    chiavi): pretende che le ISTRUZIONI nominino il controllo giusto. E' lo stesso
    genere di `TestIlPassaggioDiConsegneNonRestaINDIETRO` -- e ne condivide il limite,
    dichiarato: verifica che il metodo sia scritto, non che qualcuno lo esegua.
    """

    def setUp(self):
        import io
        with io.open(os.path.join(QUI, "RIPRENDI_QUI.md"), encoding="utf-8") as f:
            self.pagina = f.read()

    def test_LE_ISTRUZIONI_DICONO_COME_SI_LEGGE_L_IMMAGINE_VIVA(self):
        self.assertIn(
            "docker inspect", self.pagina,
            "il passaggio di consegne non dice da nessuna parte come si legge l'IMMAGINE "
            "che gira sul server. Con i soli `git rev-parse` si puo' dichiarare «quattro "
            "posti allineati» mentre il sito serve codice di giorni prima: e' successo il "
            "2026-08-07. Il comando e' `docker inspect --format=\"{{.Image}}\" casavip_app`")

    def test_IL_CONTROLLO_E_NELLA_SEZIONE_DEI_QUATTRO_POSTI(self):
        """Non basta che la parola esista da qualche parte: deve stare DOVE si guarda.

        Una guardia che si accontenta di «la stringa c'e' in qualche punto del file» e'
        la ricaduta esatta di `server_tokens off` (appendice #15): non sa quanti posti
        ha saltato. Qui si pretende che stia vicino ai quattro comandi, cioe' dove la
        legge chi apre una chat nuova.
        """
        marcatore = "I quattro posti si LEGGONO"
        i = self.pagina.find(marcatore)
        self.assertNotEqual(i, -1,
                            "sparita la riga «I quattro posti si LEGGONO»: senza quella, "
                            "il primo gesto di ogni sessione non e' piu' scritto")
        finestra = self.pagina[i:i + 2500]
        self.assertIn(
            "docker inspect", finestra,
            "«docker inspect» c'e' nel documento ma NON nella sezione dei quattro posti: "
            "chi apre una chat nuova legge quella, e li' troverebbe ancora solo i "
            "`git rev-parse`, che non vedono l'immagine viva")


class TestGeneratoreDiMutanti(unittest.TestCase):
    """I MUTANTI SI GENERANO DAL CODICE, NON SI SCELGONO A MANO (regola 12 dell'appendice).

    I 41 mutanti scritti a mano toccano 12 moduli su 152: il 92% del motore non ha mai visto
    un guasto simulato. E li ha scelti la stessa testa che ha scritto i test, quindi
    confermano i guasti gia' immaginati invece di scoprirne di nuovi.

    Il generatore e' codice NUOVO dentro il GIUDICE: se sbaglia il taglio di un carattere,
    produce mutanti che non compilano (falsi «uccisi»: il test muore per un errore di
    sintassi, non perche' ha visto il guasto) oppure muta il punto sbagliato. Per questo qui
    si prova al carattere, non «piu' o meno».
    """

    @staticmethod
    def _motore():
        import importlib.util
        import os
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "collaudi", "mutazione_prodotto.py")
        spec = importlib.util.spec_from_file_location("_mut_gen", p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_trova_i_confronti_e_li_rovescia_nel_verso_giusto(self):
        m = self._motore()
        mut, _ = m.genera_mutanti("def f(x):\n    return x <= 90\n")
        self.assertEqual(1, len(mut), "atteso esattamente 1 mutante: %r" % (mut,))
        self.assertEqual(("<=", "<", 2), (mut[0]["vecchio"], mut[0]["nuovo"], mut[0]["riga"]))

    def test_trova_and_e_or(self):
        m = self._motore()
        mut, _ = m.genera_mutanti("def f(a, b):\n    return a and b\n")
        self.assertEqual([("and", "or")], [(x["vecchio"], x["nuovo"]) for x in mut])

    def test_CONTA_GLI_OPERATORI_CHE_NON_SA_ROMPERE_invece_di_tacerli(self):
        """⛔ D18 PUNTO 3: UNO STRUMENTO CHE MISURA DICHIARA COSA NON HA ESAMINATO.

        Il generatore conosce solo i confronti fra numeri (`==`, `!=`, `<`, `<=`, `>`, `>=`).
        Le espressioni `is`, `is not`, `in`, `not in` non le sa rompere, e fin qui e' una
        rinuncia legittima: meglio niente che una sostituzione indovinata. Il difetto e' che
        le saltava **senza contarle** -- e allora il denominatore esce piu' piccolo del vero,
        e un punto che nessuno ha mai guardato sembra un punto coperto.

        MISURATO IL 2026-08-04 su `fase160_escrow_garanzia`, non dedotto: il denominatore vero
        era **43 e non 39**. Fra i quattro punti muti c'era `r["stato"] not in attesi`, cioe'
        **la sola condizione che decide se un movimento di denaro e' permesso**. Non era
        scoperta -- romperla fa fallire un test esistente -- ma nessuno l'aveva mai messa alla
        prova, e lo strumento non aveva mai detto di non averla guardata. Sono due cose
        diverse, e la seconda e' quella che rende un punteggio una decorazione.

        Le altre tre rinunce (`a_cavallo`, `catena`, `non_trovato`) erano gia' contate: questa
        no, ed era l'unica che riguardava una FAMIGLIA INTERA di operatori.

        ⛔ IL VALORE ATTESO E' CAMBIATO NEL POMERIGGIO DEL 2026-08-05, e non per far passare
        una modifica: perche' lo strumento e' MIGLIORATO. `is`/`is not`/`in`/`not in` adesso
        li sa rompere davvero (vedi `test_IL_GENERATORE_SA_ROMPERE_ANCHE_is_e_in`), quindi
        non sono piu' una rinuncia: sono punti provati. Contarli ancora fra le rinunce
        significherebbe contarli DUE volte nel denominatore.
        La ragione per cui questa prova esiste — **un generatore che tace sulle proprie
        rinunce mente sulla copertura** — non e' cambiata di una virgola, e qui sotto e'
        verificata sulle famiglie che restano rinunciate: le catene e gli operatori a
        cavallo di due righe. Il verdetto complessivo (mutanti + rinunce = punti veri) e'
        inchiodato su TUTTA la macchina da `test_IL_DENOMINATORE_DICHIARATO_COINCIDE_CON_UN_
        ORACOLO_INDIPENDENTE`, che e' la guardia che non si puo' aggirare.
        """
        m = self._motore()
        cavia = ("def f(x, elenco):\n"
                 "    if x is None:\n"
                 "        return 1\n"
                 "    if x is not None:\n"
                 "        return 2\n"
                 "    if x in elenco:\n"
                 "        return 3\n"
                 "    if x not in elenco:\n"
                 "        return 4\n"
                 "    return 0\n")
        mutanti, saltati = m.genera_mutanti(cavia)
        self.assertEqual(4, len([x for x in mutanti if x["tipo"] == "confronto"]),
                         "i quattro `is`/`in` non vengono piu' rotti: sono tornati a essere "
                         "punti dichiarati e mai provati. Mutanti: %r" % (mutanti,))
        self.assertEqual(0, sum(saltati.values()),
                         "li rompe E li conta ancora fra le rinunce: il denominatore "
                         "conterebbe due volte gli stessi punti. %r" % (saltati,))

        # ── LA RAGIONE DELLA PROVA, sulle famiglie ANCORA rinunciate ──────────────────
        # Un confronto a catena resta fuori dalla portata del generatore (due operatori,
        # e sceglierne uno a caso sarebbe un guasto indovinato). Deve essere CONTATO.
        _mut, catene = m.genera_mutanti("def g(x):\n    return 0 < x <= 5\n")
        self.assertEqual(2, catene["catena"],
                         "una catena con DUE operatori non e' contata per due: il "
                         "denominatore esce corto e la copertura sembra piu' alta di com'e'. "
                         "%r" % (catene,))
        self.assertEqual(2, sum(catene.values()),
                         "le rinunce non tornano col totale: qualche famiglia viene contata "
                         "due volte o non contata affatto. %r" % (catene,))

    def test_IL_DENOMINATORE_DICHIARATO_COINCIDE_CON_UN_ORACOLO_INDIPENDENTE(self):
        """⛔ ORACOLO INDIPENDENTE (collaudo n.5), su TUTTA la macchina, non su una cavia.

        Un secondo conteggio, scritto qui e per conto suo, ricalcola da zero quanti punti di
        logica ci sono in ogni modulo di produzione -- **per OPERATORE, non per nodo** -- e
        pretende che coincida con quello che il generatore dichiara (mutanti + rinunce). Se i
        due numeri divergono, lo strumento sta pubblicando un denominatore piu' piccolo del
        vero: la forma di bugia piu' comoda, perche' fa salire la percentuale di copertura
        senza che nessuno abbia guardato niente in piu'.

        ⛔ E' NATO DA UN ERRORE MIO, il 2026-08-05. Avevo scritto nel diario che dopo la
        riparazione delle rinunce silenziose «`fase160` dichiara 43 punti, esattamente il
        denominatore vero contato a mano il 2026-08-04». Erano d'accordo, ed erano **tutte e
        due sbagliate**: i punti veri sono 46. Le catene (`0 < limite <= 500`) contengono DUE
        operatori mutabili e venivano contate come UNA rinuncia sola. Due misure che si
        confermano a vicenda non sono una verifica -- e la sola cosa che l'ha vista e' stato
        un conteggio scritto SEPARATAMENTE, che e' esattamente questa prova.

        Misurato prima della riparazione: **44 moduli su 152** dichiaravano un denominatore
        corto, per **109 punti** in tutta la macchina.
        """
        import ast
        import glob
        import os
        m = self._motore()
        radice = os.path.dirname(os.path.abspath(__file__))
        corti, esaminati = [], 0
        for percorso in sorted(glob.glob(os.path.join(radice, "fase*.py"))
                               + glob.glob(os.path.join(radice, "main_casavip.py"))):
            try:
                sorgente = m._leggi_intatto(percorso)
                albero = ast.parse(sorgente)
            except (SyntaxError, OSError, ValueError):
                continue          # non analizzabile: lo dicono altri collaudi, non questo
            esaminati += 1
            # L'oracolo: ogni OPERATORE che il generatore sa (o dovrebbe sapere) rompere.
            veri = (sum(len(n.ops) for n in ast.walk(albero) if isinstance(n, ast.Compare))
                    + sum(len(n.values) - 1 for n in ast.walk(albero)
                          if isinstance(n, ast.BoolOp))
                    + sum(1 for n in ast.walk(albero)
                          if isinstance(n, ast.Constant) and isinstance(n.value, bool)))
            mutanti, saltati = m.genera_mutanti(sorgente)
            dichiarati = len(mutanti) + sum(saltati.values())
            if dichiarati != veri:
                corti.append("  %s: punti veri %d, dichiarati %d (mancano %d)"
                             % (os.path.basename(percorso), veri, dichiarati,
                                veri - dichiarati))
        self.assertGreaterEqual(esaminati, 100,
                                "esaminati solo %d moduli: l'oracolo sta guardando quasi "
                                "nulla e il suo verde non varrebbe niente" % esaminati)
        self.assertEqual(
            [], corti,
            "DENOMINATORE: %d moduli di produzione esaminati, %d dichiarano MENO punti di "
            "quanti ne contiene il loro codice, per %d punti in totale. Un punto non "
            "dichiarato non e' un punto sicuro: e' un punto che nessuno ha mai guardato, e "
            "tacerlo fa salire la percentuale senza guardare niente in piu'.\n%s"
            % (esaminati, len(corti), sum(int(r.rsplit(" ", 1)[1].strip(")"))
                                          for r in corti), "\n".join(corti[:20])))

    def test_LE_RINUNCE_SEGUONO_IL_DIFF_e_si_contano_PER_PUNTO_non_per_riga(self):
        """⛔ DUE MODI DI SBAGLIARE UN CONTATORE, che la prima cavia non sapeva vedere.

        (1) **Per riga invece che per punto.** Due operatori ignoti sulla STESSA riga sono due
        rinunce, non una. Se si contasse per riga, il denominatore tornerebbe corto nello
        stesso modo in cui lo era per le catene.

        (2) **In modo `--diff` le rinunce devono riguardare il DIFF**, non tutto il file. Il
        giro sul diff genera mutanti solo sulle righe appena cambiate: se le rinunce le conta
        su tutto il file, il riepilogo dichiara «non provati» centinaia di punti che non
        c'entrano nulla con la modifica -- e la riga «NON PROVATI (dichiarati)» si accende a
        OGNI giro. Un allarme sempre acceso viene spento, ed e' un difetto quanto un allarme
        mancato (regola ferrea 10). Su `fase83_server.py` erano 452 punti di rumore fisso.

        Trovati il 2026-08-05 da una revisione a contesto fresco, che ha misurato che la prima
        cavia -- quattro operatori, uno per riga, nessuna catena, nessun filtro -- restava
        VERDE davanti a tutt'e due le rotture.
        """
        m = self._motore()
        # Due catene sulla riga 2 (due operatori ciascuna) e una sulla riga 4. Le catene sono
        # la famiglia che il generatore rinuncia a rompere ANCHE dopo aver imparato `is`/`in`:
        # con due operatori nella stessa espressione, sceglierne uno sarebbe un guasto
        # indovinato -- e meglio niente che indovinato.
        sorgente = ("def f(x, y):\n"
                    "    if 0 < x <= 5 and 0 < y <= 5:\n"
                    "        return 1\n"
                    "    if 0 < x <= 9:\n"
                    "        return 2\n"
                    "    return 0\n")
        _mut, tutto = m.genera_mutanti(sorgente)
        self.assertEqual(6, tutto["catena"],
                         "attesi 6 punti rinunciati (due catene da due operatori sulla riga "
                         "2, una sulla riga 4): se ne conta meno, il contatore conta le "
                         "RIGHE o i NODI invece dei PUNTI, e il denominatore torna corto. %r"
                         % (tutto,))

        # Solo la riga 4 e' nel diff: le rinunce delle righe non toccate NON devono comparire,
        # o il riepilogo dichiara come «non provato» tutto il resto del file.
        _mut, solo_diff = m.genera_mutanti(sorgente, righe_ammesse={4})
        self.assertEqual(2, sum(solo_diff.values()),
                         "in modo diff le rinunce sono quelle di TUTTO IL FILE invece che "
                         "delle righe cambiate: la riga «NON PROVATI (dichiarati)» si "
                         "accenderebbe a ogni giro, e un allarme sempre acceso viene spento. "
                         "%r" % (solo_diff,))

    def test_IL_CENSIMENTO_DICHIARA_ANCHE_I_PUNTI_CHE_NON_SA_ROMPERE(self):
        """⛔ IL CENSIMENTO E' LA TABELLA CON CUI SI DECIDE DOVE ATTACCARE, e taceva.

        `censimento()` buttava via le rinunce (`mutanti, _ = genera_mutanti(...)`): la riga
        piu' citata del progetto -- «punti di logica sbagliabili in tutta la macchina: 6014» --
        contava solo cio' che il generatore SA rompere, e ometteva **1290 operatori** `is`/`in`
        piu' le catene. Conseguenza concreta, non teorica: un modulo scritto quasi tutto a
        `not in` / `is None` compare con pochi «mutanti», non risulta «SCOPERTO», e nessuno lo
        guarda -- mentre la sua logica non e' mai stata messa alla prova da niente.

        E' la D18 punto 3 lasciata aperta nel consumatore piu' letto, dopo averla chiusa nel
        generatore. Trovata il 2026-08-05 da una revisione a contesto fresco.
        """
        m = self._motore()
        righe = m.censimento()
        self.assertGreaterEqual(len(righe), 100,
                                "il censimento guarda troppo pochi moduli: %d" % len(righe))
        senza = [r["modulo"] for r in righe if "rinunce" not in r]
        self.assertEqual([], senza[:10],
                         "%d moduli su %d non dichiarano le rinunce nel censimento: la "
                         "tabella con cui si sceglie dove attaccare mostra un denominatore "
                         "piu' piccolo del vero" % (len(senza), len(righe)))
        self.assertGreater(
            sum(r["rinunce"] for r in righe), 0,
            "il campo `rinunce` c'e' ma vale zero ovunque: sarebbe un ornamento, e sappiamo "
            "per misura che nella macchina ci sono centinaia di punti che il generatore non "
            "sa rompere")

    def test_OGNI_MUTANTE_GENERATO_COMPILA(self):
        """⛔ LA RETE CHE DEVE ESISTERE PRIMA DI OGNI ESTENSIONE DEL GENERATORE.

        Il generatore TAGLIA CARATTERI dentro un file di produzione. Se sbaglia il taglio di
        un solo carattere, il mutante **non compila**: il test killer muore per errore di
        sintassi invece che per aver visto il guasto, e lo strumento lo conta **«UCCISO»**.
        Il punteggio sale e la protezione non c'e'. E' il modo esatto in cui un giudice mente
        — la stessa famiglia del «42 su 42» del 2026-08-01, misurato su test gia' rossi.

        Qui si prende OGNI mutante che il generatore propone su OGNI modulo di produzione, lo
        si applica davvero (in memoria: nessun file toccato) e si pretende che il risultato
        sia Python valido. E' la rete che rende sicuro estendere l'elenco degli operatori:
        senza, ogni operatore nuovo e' una scommessa sul taglio.

        ⛔ COSA NON FA (D18 punto 3): non dice che il mutante sia SENSATO, solo che e'
        sintatticamente valido. Un mutante che compila ma non cambia niente resta un problema
        diverso (l'equivalenza), e se ne occupa lo schedario.

        ⚡ PERCHE' NON RI-ANALIZZA IL FILE INTERO (2026-08-06). La prima versione lo faceva e
        la CI e' passata da ~10 a **23m42s**. Un controllo che raddoppia l'attesa e' un
        controllo che prima o poi qualcuno spegne, e allora non protegge piu' niente.
        Ora si analizza solo la **funzione piu' interna** che contiene la riga mutata (con
        ripiego sull'istruzione di primo livello, e sul file intero se nemmeno quella c'e').
        La premessa e' una proprieta' della grammatica, non un'euristica: un blocco si analizza
        in modo indipendente, quindi se quello mutato e' valido e il resto del file **non e'
        cambiato** (la mutazione tocca una riga sola e non ne cambia il numero), il file e'
        valido.
        ⛔ MISURATO, NON DEDOTTO, su 7275 mutanti veri di 151 moduli, con TRE tipi di guasto
        iniettati apposta nel generatore (operatore doppio, parentesi non chiusa, parola
        chiave ripetuta):
            file intero (la verita')   186,8 s -> 544 mutanti rotti
            istruzione di 1o livello   116,4 s -> 544, stesso identico insieme
            funzione piu' interna        2,9 s -> 544, stesso identico insieme
        Non «lo stesso numero»: lo **stesso insieme**, confrontato mutante per mutante --
        zero mancati, zero falsi allarmi. Due conteggi uguali possono nascondere due insiemi
        diversi, ed e' per questo che il confronto e' sugli insiemi.
        ⚠️ Il costo NON era `applica_mutante` che ricostruisce il file (misurato: 3,8 s in
        tutto): era l'analisi sintattica, che cresce con le righe del frammento. La prima
        spiegazione che mi ero dato era sbagliata, e la misura l'ha smentita.
        ⛔ Le due condizioni della premessa sono VERIFICATE a ogni giro, non assunte: se la
        mutazione cambiasse il numero di righe, o se la riga cadesse fuori da ogni istruzione
        (puo' capitare), si ricade sull'analisi del FILE INTERO -- e quante volte succede
        viene DETTO nel messaggio.
        """
        import ast
        import glob
        import os
        m = self._motore()
        radice = os.path.dirname(os.path.abspath(__file__))
        rotti, esaminati, mutanti_totali, interi, righe_lette = [], 0, 0, 0, 0
        for percorso in sorted(glob.glob(os.path.join(radice, "fase*.py"))
                               + glob.glob(os.path.join(radice, "main_casavip.py"))):
            try:
                sorgente = m._leggi_intatto(percorso)
                albero = ast.parse(sorgente)
            except (SyntaxError, OSError, ValueError):
                continue
            esaminati += 1
            quante_righe = len(sorgente.splitlines())

            def _intervallo(nodo):
                """Righe del nodo, decoratori compresi: stanno PRIMA del `def` e non sono in
                `lineno`, e senza di loro un mutante su una riga decorata cadrebbe fuori."""
                return (min([nodo.lineno] + [d.lineno
                                             for d in getattr(nodo, "decorator_list", [])]),
                        nodo.end_lineno, nodo.col_offset)

            # Due mappe: le funzioni (la piu' INTERNA che contiene la riga) e, come ripiego,
            # le istruzioni di primo livello.
            funzioni = [_intervallo(n) for n in ast.walk(albero)
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            cima = [(a, b, 0) for a, b, _c in (_intervallo(n) for n in albero.body)]
            mutanti, _saltati = m.genera_mutanti(sorgente)
            for mu in mutanti:
                mutanti_totali += 1
                testo = m.applica_mutante(sorgente, mu)
                righe = testo.splitlines()
                blocco = None
                if len(righe) == quante_righe:          # premessa 1: righe invariate
                    for elenco in (funzioni, cima):     # premessa 2: dentro un blocco
                        for a, b, col in elenco:
                            if a <= mu["riga"] <= b and (blocco is None or a > blocco[0]):
                                blocco = (a, b, col)
                        if blocco is not None:
                            break
                pezzo = None
                if blocco is not None:
                    pezzo = righe[blocco[0] - 1:blocco[1]]
                    # Una funzione dentro una classe e' indentata: per analizzarla da sola le
                    # si toglie l'indentazione, la stessa a tutte le righe.
                    # ⛔ PREMESSA 3, VERIFICATA E NON ASSUNTA: `x[col:]` e' un taglio di
                    # CARATTERI, non un dedent. Su una riga meno indentata del `def` mangia
                    # codice vero -- un commento a colonna 0 dentro un metodo diventa
                    # `ta a colonna zero`, il frammento non compila, e il rosso accusa il
                    # generatore MENTRE IL GENERATORE E' SANO. Un falso allarme che punta al
                    # posto sbagliato: il difetto peggiore che questa rete possa avere.
                    # Oggi nel progetto non esistono righe cosi' (verificato), ma «oggi non
                    # capita» non e' un argomento (D19): se la premessa cade, si ricade sul
                    # file intero come per le altre due. Trovato dalla revisione a contesto
                    # fresco il 2026-08-06.
                    if blocco[2]:
                        if any(x[:blocco[2]].strip() for x in pezzo):
                            pezzo = None
                        else:
                            pezzo = [x[blocco[2]:] for x in pezzo]
                if pezzo is None:
                    frammento, interi = testo, interi + 1
                else:
                    frammento = "\n".join(pezzo)
                righe_lette += frammento.count("\n") + 1
                try:
                    ast.parse(frammento)
                except SyntaxError as e:
                    # Si riporta solo `e.msg`, non l'eccezione intera: la posizione che porta
                    # dentro e' relativa al FRAMMENTO analizzato, e stampare due numeri di riga
                    # diversi manda chi legge il rosso a cercare nel punto sbagliato. La
                    # posizione VERA e' quella che scriviamo noi, `file:riga`.
                    rotti.append("  %s:%s  %s -> %s   %s"
                                 % (os.path.basename(percorso), mu["riga"], mu["vecchio"],
                                    mu["nuovo"], e.msg))
                    if len(rotti) >= 10:
                        break
            if len(rotti) >= 10:
                break
        # ⛔ PRIMA IL DIFETTO VERO, POI I CONTROLLI SUL DENOMINATORE. L'ordine non e' estetico:
        #    la prima versione controllava prima il denominatore, e siccome la ricerca si ferma
        #    ai primi 10 mutanti rotti, il conteggio dei moduli restava fermo a 10 e il rosso
        #    diceva «la rete sta guardando quasi nulla» invece di «il giudice produce Python
        #    non valido». L'allarme suonava e gridava il motivo SBAGLIATO -- un osservabile
        #    debole, che manda chi legge a cercare nel posto sbagliato. Trovato il 2026-08-06
        #    vedendola rossa per la prima volta, con un operatore guasto iniettato apposta.
        self.assertEqual(
            [], rotti,
            "IL GENERATORE PRODUCE PYTHON NON VALIDO (primi %d, la ricerca si ferma qui): il "
            "killer morirebbe di errore di SINTASSI invece che per aver visto il guasto, e il "
            "giudice conterebbe quei mutanti come UCCISI -- punteggio pieno su protezione "
            "assente.\n%s" % (len(rotti), "\n".join(rotti)))
        self.assertGreaterEqual(esaminati, 100,
                                "esaminati solo %d moduli: la rete sta guardando quasi nulla"
                                % esaminati)
        self.assertGreater(mutanti_totali, 1000,
                           "solo %d mutanti generati in tutta la macchina: il generatore sta "
                           "producendo troppo poco perche' questo verde valga qualcosa"
                           % mutanti_totali)
        # ⛔ SI DICHIARA QUANTE VOLTE SI E' RICADUTI SUL FILE INTERO. Non e' un errore -- e' la
        #    via sicura quando la premessa non regge -- ma se diventasse la norma, la rete
        #    sarebbe tornata lenta senza che nessuno se ne accorgesse.
        # ⛔ IL NUMERO DEI RIPIEGHI E' INCHIODATO A UN VALORE PICCOLO, non a un tetto che non
        #    puo' scattare. Il vecchio (`mutanti // 10` = 727) era decorazione: un ripiego
        #    costa ~2232 righe, quindi a 265 ripieghi scatta gia' il cricchetto sul rapporto e
        #    quello sui ripieghi non fallisce MAI. Oggi i ripieghi sono **0**.
        #    ⚠️ Non si pretende zero: ricadere sul file intero e' la via SICURA quando una
        #    premessa non regge (una riga meno indentata del `def` e' Python legale), e farne
        #    un rosso punirebbe codice corretto. Si pretende che restino un'eccezione.
        self.assertLess(interi, 50,
                        "ricaduta sull'analisi del file INTERO %d volte su %d mutanti (oggi "
                        "sono 0): non e' un errore -- e' la via sicura quando una premessa non "
                        "regge -- ma se diventa la norma la rete e' tornata lenta senza che si "
                        "veda. Va capito PERCHE', non alzato il numero."
                        % (interi, mutanti_totali))
        # ⛔ IL CRICCHETTO SUL LAVORO — e si misura il LAVORO, non il TEMPO, per una ragione
        #    misurata il 2026-08-06: la stessa suite sulla stessa macchina e' passata da 1785 a
        #    3818 secondi nello stesso giorno (rumore 2,14x, ±1000 s), mentre il rallentamento
        #    da intercettare ne valeva 90. Un cricchetto sul TEMPO griderebbe sui giri lenti
        #    normali -- e un falso allarme e' un difetto quanto un allarme mancato.
        #    Le righe analizzate invece sono un numero DETERMINISTICO: identico su ogni
        #    macchina e a ogni giro. Falsi allarmi impossibili per costruzione.
        #    Con la vecchia strategia (file intero) erano 16.238.763: questo tetto avrebbe
        #    gridato subito, invece di far scoprire il rallentamento al fondatore su una
        #    pagina web il giorno dopo.
        #    ⚠️ Chi lo alza deve scrivere PERCHE' nel registro, come si fa col numero della
        #    copertura. Alzarlo per far tornare il verde e' la stessa cosa che allargare un
        #    valore atteso perche' il codice non lo raggiunge.
        # ⛔ SI INCHIODA IL RAPPORTO righe/mutante, NON IL TOTALE. Il totale cresce anche per
        #    BUONI motivi: il 2026-08-05 insegnare `is`/`in` al generatore ha aggiunto 1279
        #    punti veri (+18% in un solo commit), e altre due famiglie di operatori o trenta
        #    moduli nuovi porterebbero il totale al tetto SENZA nessuna regressione -- col
        #    rosso che manda a cercare una lentezza che non c'e'. Il rapporto invece dipende
        #    solo dalla STRATEGIA: 56 righe per mutante guardando la funzione piu' interna,
        #    ~2232 tornando all'istruzione di primo livello. Sono 40 volte di distanza: un
        #    tetto a 200 tace su qualunque crescita legittima e grida su un ritorno indietro.
        #    (Rilievo della revisione a contesto fresco, 2026-08-06.)
        per_mutante = righe_lette / float(max(mutanti_totali, 1))
        self.assertLess(per_mutante, 200,
                        "la rete analizza %.0f righe per mutante (%d righe su %d mutanti): "
                        "e' tornata pesante, e il costo si paga a OGNI giro di CI due volte "
                        "(suite intera + copertura). Oggi ne analizza ~56 guardando la "
                        "funzione piu' interna; tornando all'istruzione di primo livello "
                        "sarebbero ~2232. Va capito COSA e' cambiato nella STRATEGIA, non "
                        "alzato il tetto." % (per_mutante, righe_lette, mutanti_totali))

    def test_IL_GENERATORE_SA_ROMPERE_ANCHE_is_e_in(self):
        """⛔ I 1290 PUNTI CHE LO STRUMENTO DICHIARAVA DI NON SAPER ROMPERE.

        `is`, `is not`, `in`, `not in` non erano nel suo elenco di operatori: da oggi li
        DICHIARA fra le rinunce (era la riparazione del 2026-08-05), ma dichiarare non e'
        provare. Un punto che nessuno prova non e' un punto sicuro.

        Il guasto qui e' UNIVOCO — `is` <-> `is not`, `in` <-> `not in` — e per questo si
        parte da loro: nessuna ambiguita' su quale carattere tagliare. Le catene
        (`0 < x <= 5`, due operatori) e gli operatori a cavallo di due righe restano fuori,
        dichiarati, e si toccheranno con piu' rete.

        ⚠️ IL CASO CHE FA PIU' PAURA, ed e' provato qui sotto: `for s in lista` NON deve
        diventare `for s not in lista`, che non e' Python valido. Non lo diventa perche' il
        `for` di una comprensione non e' un confronto (`ast.Compare`) e il generatore guarda
        l'albero sintattico, non il testo — ma «non succede» va dimostrato, non supposto.
        """
        m = self._motore()
        sorgente = ("def f(x, elenco, righe):\n"
                    "    if x is None:\n"
                    "        return 1\n"
                    "    if x is not None:\n"
                    "        return 2\n"
                    "    if x in elenco:\n"
                    "        return 3\n"
                    "    if x not in elenco:\n"
                    "        return 4\n"
                    "    return [r for r in righe if r]\n")
        mutanti, saltati = m.genera_mutanti(sorgente)
        fatti = sorted((mu["vecchio"], mu["nuovo"]) for mu in mutanti)
        self.assertEqual(
            [("in", "not in"), ("is", "is not"), ("is not", "is"), ("not in", "in")], fatti,
            "il generatore non produce i quattro guasti attesi su `is`/`is not`/`in`/`not "
            "in`: quei punti restano dichiarati e mai provati. Trovati: %r · rinunce: %r"
            % (fatti, saltati))
        self.assertEqual(0, saltati["operatore_ignoto"],
                         "li genera ma li conta ancora fra le rinunce: il denominatore "
                         "conterebbe due volte gli stessi punti. %r" % (saltati,))
        # ⛔ E OGNUNO DEI QUATTRO DEVE COMPILARE: `for r in righe` non e' un confronto e non
        #    va toccato: se lo fosse, `for r not in righe` non sarebbe Python valido.
        import ast
        for mu in mutanti:
            testo = m.applica_mutante(sorgente, mu)
            try:
                ast.parse(testo)
            except SyntaxError as e:
                self.fail("il mutante %s -> %s alla riga %s non compila (%s):\n%s"
                          % (mu["vecchio"], mu["nuovo"], mu["riga"], e, testo))
        self.assertNotIn("for r not in righe", "\n".join(
            m.applica_mutante(sorgente, mu) for mu in mutanti),
            "ha mutato il `for` di una comprensione: non e' un confronto, e il risultato non "
            "sarebbe nemmeno Python valido")

    def test_NON_tocca_gli_operatori_dentro_le_stringhe_ne_i_commenti(self):
        """Un `replace` sul testo colpirebbe anche questi. `ast` vede solo il codice VERO."""
        m = self._motore()
        sorgente = ('def f(x):\n'
                    '    messaggio = "usa == per confrontare"   # e qui and or ==\n'
                    '    return x > 0\n')
        mut, _ = m.genera_mutanti(sorgente)
        self.assertEqual([3], [x["riga"] for x in mut],
                         "ha mutato una stringa o un commento: %r" % (mut,))

    def test_taglia_al_CARATTERE_giusto_con_due_operatori_uguali_sulla_riga(self):
        """LA PROVA CHE SEPARA UN GENERATORE DA UN `replace` CIECO. Con due `==` sulla
        stessa riga, un replace testuale colpisce sempre il primo: qui ognuno ha il suo."""
        m = self._motore()
        sorgente = "def f(a, b, c, d):\n    return (a == b) or (c == d)\n"
        mut, _ = m.genera_mutanti(sorgente)
        confronti = [x for x in mut if x["tipo"] == "confronto"]
        self.assertEqual(2, len(confronti), "attesi 2 confronti distinti: %r" % (mut,))
        primo = m.applica_mutante(sorgente, confronti[0]).splitlines()[1]
        secondo = m.applica_mutante(sorgente, confronti[1]).splitlines()[1]
        self.assertEqual("    return (a != b) or (c == d)", primo)
        self.assertEqual("    return (a == b) or (c != d)", secondo)
        self.assertNotEqual(primo, secondo, "i due mutanti colpiscono lo stesso punto")

    def test_ogni_mutante_prodotto_COMPILA_ancora(self):
        """Un mutante che non compila e' un falso UCCISO: il test muore per un errore di
        sintassi, non perche' ha visto il guasto. Qui si compila davvero, uno per uno."""
        import ast as _ast
        import io as _io
        import os as _os
        m = self._motore()
        bersaglio = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  "fase98_policy_commissione.py")
        sorgente = _io.open(bersaglio, encoding="utf-8").read()
        mut, _s = m.genera_mutanti(sorgente)
        self.assertGreater(len(mut), 5,
                           "su un modulo di logica vera attesi piu' di 5 mutanti, trovati %d"
                           % len(mut))
        for x in mut:
            _ast.parse(m.applica_mutante(sorgente, x))       # esplode se il taglio e' storto

    def test_il_mutante_cambia_UNA_riga_sola_e_niente_altro(self):
        import io as _io
        import os as _os
        m = self._motore()
        bersaglio = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  "fase98_policy_commissione.py")
        sorgente = _io.open(bersaglio, encoding="utf-8").read()
        mut, _s = m.genera_mutanti(sorgente)
        prima = sorgente.splitlines()
        for x in mut[:20]:
            dopo = m.applica_mutante(sorgente, x).splitlines()
            self.assertEqual(len(prima), len(dopo), "il mutante ha cambiato il numero di righe")
            diverse = [i for i, (a, b) in enumerate(zip(prima, dopo)) if a != b]
            self.assertEqual([x["riga"] - 1], diverse,
                             "il mutante di riga %d ha toccato anche %r" % (x["riga"], diverse))

    def test_il_diff_restringe_l_ambito(self):
        """Il generatore va usato SUL DIFF: le righe non toccate non si mutano."""
        m = self._motore()
        sorgente = "def f(x, y):\n    a = x > 1\n    b = y < 2\n    return a and b\n"
        tutti, _ = m.genera_mutanti(sorgente)
        solo3, _ = m.genera_mutanti(sorgente, righe_ammesse={3})
        self.assertGreater(len(tutti), len(solo3))
        self.assertEqual([3], sorted({x["riga"] for x in solo3}))

    def test_un_test_che_si_INCHIODA_non_uccide_il_giudice(self):
        """⛔ IL MOTORE NON PUO' MORIRE PER UN INTOPPO, NE' CONTARLO COME UN SUCCESSO.

        Successo il 2026-08-01 su `fase184_marca_temporale`: un mutante ha fatto inchiodare
        i test, `TimeoutExpired` e' salita fino in cima e ha ucciso l'INTERO giro -- 112
        punti di logica non esaminati per colpa di uno solo.

        E c'e' un secondo modo di sbagliare, piu' insidioso: trattare l'attesa infinita come
        un mutante UCCISO. Il vecchio `if verde:` lo avrebbe fatto in silenzio (None e'
        falsy), gonfiando il punteggio con guasti che nessuno ha mai visto morire -- lo
        stesso difetto del bytecode stantio, in un'altra forma.

        Quindi tre esiti distinti, e questo li prova tutti e tre su un comando vero.
        """
        m = self._motore()
        # tempo che NESSUNA esecuzione puo' rispettare: cosi' la prova e' deterministica
        # invece di dipendere da quanto e' lenta la macchina in questo momento.
        verde, uscita = m.esegui("test_pipeline_ci", timeout=0.001)
        self.assertIsNone(verde,
                          "un'esecuzione che non finisce nel tempo dato deve valere NON "
                          "DETERMINABILE (None), non «ucciso»: esito ottenuto %r" % (verde,))
        self.assertIn("TEMPO SCADUTO", uscita,
                      "il motore non dice PERCHE' non ha potuto giudicare")

    def test_i_tre_esiti_sono_DISTINTI_e_nessuno_si_confonde_con_gli_altri(self):
        """Verde/rosso/non-determinabile devono restare tre cose diverse: e' proprio la
        confusione fra «non lo so» e «e' morto» che gonfia i punteggi."""
        m = self._motore()
        passa, _ = m.esegui("test_pipeline_ci.TestLeRegoleSiLeggonoSEMPRE"
                            ".test_esiste_un_hook_che_stampa_le_regole_a_ogni_avvio")
        self.assertIs(True, passa, "un test che passa deve dare True (mutante sopravvive)")
        fallisce, _ = m.esegui("modulo_che_non_esiste_affatto")
        self.assertIs(False, fallisce, "un test che fallisce deve dare False (mutante ucciso)")

    def test_LE_TRE_TRACCE_IN_TEMP_SONO_DISTINTE_PER_WORKTREE(self):
        """⛔ UNA CASELLA PER WORKTREE, non una per macchina.

        `tempfile.gettempdir()` e' lo STESSO per tutti i worktree della stessa macchina: con
        un nome fisso le tre tracce erano una casella sola, condivisa da tutti. Misurato il
        2026-08-27: 3 su 3 coincidevano. Cosa faceva, in concreto: lo scopo dichiarato dalla
        Corsia B sovrascriveva quello della Corsia A; un giro di mutazione aperto in A
        bloccava il commit in B; e il ripristino di un worktree stracciava il biglietto
        dell'altro, cioe' lasciava un file di produzione rotto senza piu' nessuno che lo
        recuperasse. Il piano delle due corsie prescrive proprio di lavorare in worktree
        separati, quindi non e' un caso di scuola.

        ⛔ PERCHE' SERVE QUESTA GUARDIA e non basta la prova fatta a mano quel giorno. Il
        difetto e' stato chiuso con una formula ripetuta in tre file: senza qualcosa che la
        pretenda, domani una «semplificazione» rimette il nome fisso e nessuno se ne
        accorge. Il test del gancio pre-commit ormai CHIEDE il nome allo strumento, quindi
        seguirebbe il nome sbagliato restando verde: sarebbe un verde che non ha guardato.

        ⚠️ COSA NON PROVA (D18 punto 3): il suffisso viene dal NOME della cartella radice,
        quindi due worktree omonimi in percorsi diversi collidono ancora. Qui il worktree
        finto ha un nome diverso, che e' il caso del piano delle due corsie.
        """
        import importlib.util
        import os
        import shutil
        import tempfile

        def carica(radice, nome_file, etichetta):
            percorso = os.path.join(radice, "collaudi", nome_file)
            spec = importlib.util.spec_from_file_location(etichetta, percorso)
            modulo = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(modulo)
            return modulo

        TRE = (("prima_di_lanciare.py", "TRACCIA_SCOPO"),
               ("guardia_commit.py", "TRACCIA"),
               ("mutazione_prodotto.py", "_TRACCIA"))
        a_radice = os.path.dirname(os.path.abspath(__file__))
        b_radice = tempfile.mkdtemp(prefix="worktree_finto_")
        self.addCleanup(shutil.rmtree, b_radice, True)
        os.makedirs(os.path.join(b_radice, "collaudi"))
        for nome, _attr in TRE:
            shutil.copy2(os.path.join(a_radice, "collaudi", nome),
                         os.path.join(b_radice, "collaudi", nome))

        condivise = []
        for i, (nome, attr) in enumerate(TRE):
            da_a = getattr(carica(a_radice, nome, "_wt_a_%d" % i), attr)
            da_b = getattr(carica(b_radice, nome, "_wt_b_%d" % i), attr)
            if da_a == da_b:
                condivise.append("%s.%s -> %s" % (nome, attr, da_a))
        self.assertEqual(
            condivise, [],
            "%d tracce su %d sono la STESSA casella in TEMP per due worktree diversi: due "
            "corsie che lavorano insieme si sovrascrivono a vicenda, e il ripristino "
            "dell'una straccia il biglietto dell'altra. Il nome deve portare il suffisso "
            "della cartella radice.\n    %s"
            % (len(condivise), len(TRE), "\n    ".join(condivise)))

        # ⛔ E L'INVARIANTE OPPOSTO, altrettanto facile da rompere: chi SCRIVE il biglietto e
        # chi lo LEGGE devono guardare nella stessa cartella. Se le due formule divergessero,
        # `guardia_commit` direbbe «via libera» su un giro davvero aperto -- un silenzio
        # scambiato per pace, che e' peggio di un blocco di troppo.
        scrive = getattr(carica(a_radice, "mutazione_prodotto.py", "_wt_scrive"), "_TRACCIA")
        legge = getattr(carica(a_radice, "guardia_commit.py", "_wt_legge"), "TRACCIA")
        self.assertEqual(
            scrive, legge,
            "il giudice scrive il biglietto in %r e la guardia del commit lo cerca in %r: "
            "un giro di mutazione aperto non verrebbe piu' visto, e un file di produzione "
            "mutato passerebbe il commit." % (scrive, legge))

    def _traccia_isolata(self, m):
        """⛔ LA TRACCIA E' UNA SOLA PER TUTTA LA MACCHINA: chi la cancella spegne la rete
        di una campagna in corso, e da quel momento un file di produzione mutato non e'
        piu' protetto da `collaudi/guardia_commit.py`.

        Successo davvero il 2026-08-03: i due test qui sotto mettevano in scena
        l'interruzione sulla traccia VERA e la chiudevano alla fine. Il file rotto era
        finto -- giusto -- ma la traccia no. Siccome `test_pipeline_ci` e' uno dei 9
        sorveglianti di `fase184_marca_temporale`, ogni campagna su quel modulo si
        spegneva la rete da sola a meta' giro: `fase184_marca_temporale.py:336` e' rimasto
        mutato in produzione senza che nulla lo bloccasse.

        Qui la traccia si punta a una cartella usa-e-getta e si rimette com'era.
        """
        import os
        import shutil
        import tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        self.addCleanup(setattr, m, "_TRACCIA", m._TRACCIA)   # prima: cattura l'originale
        m._TRACCIA = os.path.join(d, "bookinvip_mutazione_in_corso")

    def test_un_giro_UCCISO_non_lascia_un_guasto_nel_codice(self):
        """⛔ IL DANNO PEGGIORE CHE QUESTO STRUMENTO POSSA FARE.

        Il `finally` protegge da un'ECCEZIONE, non da un processo UCCISO. E' successo DUE
        volte in due giorni: un giro fermato a meta' ha lasciato un mutante dentro un file
        di PRODUZIONE (`fase184_marca_temporale`: `if valore == 0` diventato `!= 0`). Me ne
        sono accorto solo perche' ho ricontrollato lo stato -- ma un guasto cosi' puo'
        finire dritto in un commit senza che nessuno l'abbia voluto.

        Qui si mette in scena esattamente quello: una traccia lasciata aperta e un file
        mutato sul disco. Il recupero deve rimettere a posto il file **e dirlo**: un
        ripristino silenzioso nasconderebbe proprio l'informazione che serve a capire
        perche' il giro e' morto.
        """
        import io
        import os
        import shutil
        import tempfile
        m = self._motore()
        self._traccia_isolata(m)            # ⛔ mai la traccia condivisa: vedi il metodo
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        vittima = os.path.join(d, "finto_modulo.py")
        sano = "def f(x):\n    return x == 0\n"
        with io.open(vittima, "w", encoding="utf-8", newline="") as f:
            f.write(sano)

        m._apri_traccia(vittima, sano)                       # come fa prima di mutare
        with io.open(vittima, "w", encoding="utf-8", newline="") as f:
            f.write(sano.replace("==", "!="))                # ...e poi viene UCCISO qui
        self.addCleanup(m._chiudi_traccia)

        import contextlib
        uscita = io.StringIO()
        with contextlib.redirect_stdout(uscita):
            recuperato = m.recupera_da_interruzione()

        with io.open(vittima, encoding="utf-8", newline="") as f:
            adesso = f.read()
        self.assertEqual(sano, adesso,
                         "il file NON e' stato rimesso a posto dopo un giro interrotto: un "
                         "guasto resterebbe nel codice di produzione")
        self.assertEqual(vittima, recuperato)
        self.assertIn("::warning", uscita.getvalue(),
                      "il recupero e' avvenuto IN SILENZIO: chi guarda la CI non saprebbe "
                      "che un giro e' morto lasciando un file mutato")
        self.assertIsNone(m.recupera_da_interruzione(),
                          "la traccia non e' stata chiusa: il prossimo giro «recupererebbe» "
                          "un file che non e' mai stato toccato")

    def test_senza_interruzioni_il_recupero_NON_tocca_niente(self):
        """L'altra direzione (REGOLA FERREA 10): se nessun giro e' stato interrotto, il
        recupero deve tacere e non muovere un byte. Un falso recupero riscriverebbe file
        sani con contenuti vecchi -- sarebbe peggio del guasto che previene."""
        m = self._motore()
        self._traccia_isolata(m)            # ⛔ mai la traccia condivisa: vedi il metodo
        m._chiudi_traccia()
        self.assertIsNone(m.recupera_da_interruzione())

    def test_DUE_GIRI_INSIEME_non_si_spengono_la_rete_a_vicenda(self):
        """⛔ D20 — DIFETTO VIVO trovato il 2026-08-14 GUARDANDO, non da un controllo.

        Il Giudice puo' girare DENTRO se stesso: `test_mutation_money` esegue un proprio
        giro di mutazione su `fase162_pagamenti_pendenti.py`, ed e' allo stesso tempo uno
        dei sorveglianti di un giro esterno E parte di OGNI suite da 27 minuti. Con una
        casella sola per tutta la macchina, chi finisce per primo cancella il biglietto
        dell'altro: da quel momento un file di produzione ROTTO non e' piu' sorvegliato,
        `collaudi/guardia_commit.py` risponde «via libera», e il guasto puo' arrivare su
        master e sul server **con tutti i controlli verdi**.

        VISTO DAL VIVO quel giorno, in due campioni distinti durante un giro su `fase59`:
            git status -> M fase59_concierge.py  ·  traccia -> fase162_pagamenti_pendenti.py
            fase59 con sha256 DIVERSO            ·  traccia -> ASSENTE

        ⚠️ Il progetto lo SAPEVA: la docstring di `_traccia_isolata`, qui sopra, descrive
        esattamente questo danno -- ma lo aggirava nei collaudi invece di chiuderlo alla
        radice. Un aggiramento nei test non protegge la produzione.
        """
        import contextlib
        import io
        import os
        import shutil
        import tempfile
        m = self._motore()
        self._traccia_isolata(m)
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)

        a = os.path.join(d, "modulo_esterno.py")
        b = os.path.join(d, "modulo_annidato.py")
        sano_a = "def f(x):\n    return x >= 0\n"
        sano_b = "def g(x):\n    return x <= 0\n"
        for percorso, sano in ((a, sano_a), (b, sano_b)):
            with io.open(percorso, "w", encoding="utf-8", newline="") as f:
                f.write(sano)

        m._apri_traccia(a, sano_a)                      # il giro ESTERNO mette da parte A
        with io.open(a, "w", encoding="utf-8", newline="") as f:
            f.write(sano_a.replace(">=", ">"))          # ...e lo rompe
        self.addCleanup(m._chiudi_traccia)

        m._apri_traccia(b, sano_b)                      # il giro ANNIDATO apre il SUO
        try:
            m._chiudi_traccia(b)          # come DEVE chiudere: solo il proprio biglietto
        except TypeError:
            m._chiudi_traccia()           # come fa OGGI: cancella tutto, anche l'altrui

        # A e' ancora ROTTO sul disco. La rete deve saperlo ancora.
        uscita = io.StringIO()
        with contextlib.redirect_stdout(uscita):
            recuperato = m.recupera_da_interruzione()
        with io.open(a, encoding="utf-8", newline="") as f:
            adesso = f.read()
        self.assertEqual(
            sano_a, adesso,
            "IL GIRO ANNIDATO HA SPENTO LA RETE DEL GIRO ESTERNO: il file rotto NON e' "
            "stato rimesso a posto. Da qui un guasto sui soldi arriva in un commit con "
            "tutti i controlli verdi -- e' il difetto visto dal vivo il 2026-08-14.")
        self.assertEqual(a, recuperato,
                         "il recupero non nomina il file che era rimasto rotto")
        self.assertIn("::warning", uscita.getvalue(),
                      "il recupero e' avvenuto IN SILENZIO: chi guarda la CI non saprebbe "
                      "che un giro e' morto lasciando un file mutato")

    def test_la_guardia_al_commit_ELENCA_TUTTI_i_giri_aperti(self):
        """L'altra meta': non basta che la rete regga, deve anche DIRLO per intero.

        Se due giri sono aperti e la guardia ne nomina uno solo, chi legge rimette a posto
        quel file, vede «via libera» e committa **l'altro** ancora rotto. Una guardia che
        dichiara meno di quello che sa e' peggio di una che tace: da' una falsa fine.
        """
        import importlib.util
        import io
        import os
        import shutil
        import tempfile
        _p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "collaudi", "guardia_commit.py")
        _spec = importlib.util.spec_from_file_location("_gc_elenco", _p)
        gc_mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(gc_mod)
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        traccia = os.path.join(d, "bookinvip_mutazione_in_corso")
        for nome, quale in (("giro_uno", "/prod/fase_alfa.py"),
                            ("giro_due", "/prod/fase_beta.py")):
            os.makedirs(os.path.join(traccia, nome))
            with io.open(os.path.join(traccia, nome, "quale.txt"), "w",
                         encoding="utf-8") as f:
                f.write(quale)
            with io.open(os.path.join(traccia, nome, "originale.txt"), "w",
                         encoding="utf-8") as f:
                f.write("sano\n")
        aperta, quali = gc_mod.mutazione_in_corso(traccia)
        self.assertTrue(aperta, "due giri aperti e la guardia dice «via libera»")
        testo = quali if isinstance(quali, str) else "\n".join(quali)
        for atteso in ("fase_alfa.py", "fase_beta.py"):
            self.assertIn(atteso, testo,
                          "la guardia nomina solo una parte dei giri aperti: chi rimette a "
                          "posto quel file crede di aver finito e committa l'altro rotto")

    def test_le_RINUNCE_sono_contate_e_dichiarate(self):
        """Un generatore che tace sulle proprie rinunce mente sulla copertura. I confronti
        a catena si saltano di proposito: devono comparire nel conto.

        ⛔ IL VALORE ATTESO E' PASSATO DA 1 A 2 IL 2026-08-05, e non per far passare una
        modifica: perche' 1 era SBAGLIATO. `a < b < c` e' UN nodo ma contiene DUE operatori,
        e ognuno dei due e' un punto che si puo' rompere per conto suo. Contando per nodo, il
        denominatore usciva corto su **44 moduli su 152**, per **109 punti** in tutta la
        macchina -- e la percentuale di copertura saliva senza che nessuno guardasse niente
        in piu'. La prova che 2 e' il numero giusto non e' un'opinione ne' il codice nuovo:
        e' `test_IL_DENOMINATORE_DICHIARATO_COINCIDE_CON_UN_ORACOLO_INDIPENDENTE`, un
        conteggio scritto SEPARATAMENTE che confronta i due numeri su ogni modulo.
        """
        m = self._motore()
        mutanti, saltati = m.genera_mutanti("def f(a, b, c):\n    return a < b < c\n")
        self.assertEqual(2, saltati["catena"],
                         "un confronto a catena e' contato PER NODO invece che per "
                         "OPERATORE: `a < b < c` sono DUE punti rinunciati, non uno, e "
                         "contarne uno solo accorcia il denominatore. %r" % (saltati,))
        self.assertEqual((0, 2), (len(mutanti), len(mutanti) + sum(saltati.values())),
                         "l'invariante in piccolo: zero mutanti generati su una catena, e "
                         "mutanti + rinunce = i punti veri della riga (2). %r"
                         % (mutanti, ))


class TestLaReteAntiInterruzioneNONSiSpegneDaSola(unittest.TestCase):
    """⛔ IL COLLAUDO DELLA RETE NON DEVE SPEGNERE LA RETE.

    DIFETTO VERO, TROVATO E RIPRODOTTO IL 2026-08-03 (non dedotto).
    `_TRACCIA` e' UNA SOLA per tutta la macchina: e' la cartella che dice «un giro di
    mutazione e' aperto», ed e' cio' che fa BLOCCARE il salvataggio a
    `collaudi/guardia_commit.py`. Due guardie di `TestGeneratoreDiMutanti` mettevano in
    scena un giro interrotto usando la traccia VERA invece di una propria, e alla fine la
    CANCELLAVANO (`_chiudi_traccia`, e `recupera_da_interruzione` che la chiude nel suo
    `finally`).

    Conseguenza misurata, non temuta: `test_pipeline_ci` e' uno dei 9 sorveglianti di
    `fase184_marca_temporale`. In ogni campagna su quel modulo la sequenza era:
        1. la campagna apre la traccia e ROMPE il file di produzione;
        2. la campagna esegue i sorveglianti, fra cui questo file -> TRACCIA CANCELLATA;
        3. da li' in poi il file e' rotto e NESSUNO lo sa;
        4. il processo muore -> guasto vivo in produzione, salvataggio NON bloccato.
    Successo davvero il 2026-08-03: `fase184_marca_temporale.py:336` e' rimasto con
    `if campi[3][0] == 0x02:` al posto di `!= 0x02` -- nel lettore del token di marca
    QUALIFICATA, cioe' la prova legale dell'ora certificata.

    E' l'ispettore che collauda l'antincendio usando l'allarme VERO del palazzo e poi,
    finito il collaudo, lo spegne e va a casa. L'allarme funziona. Il collaudo funziona.
    Dopo ogni collaudo il palazzo e' senza allarme.

    ⚠️ COSA QUESTA GUARDIA NON ESAMINA (dichiarato, mai taciuto): esegue solo
    `TestGeneratoreDiMutanti`, la classe dov'era il difetto. Un test di un ALTRO file che
    cancellasse la traccia condivisa non verrebbe visto da qui.
    """

    def test_anche_test_mutation_money_APRE_LA_TRACCIA_prima_di_rompere_i_soldi(self):
        """⛔ LA SUITE ORDINARIA ROMPE IL PERCORSO DEI SOLDI, E LO FACEVA SENZA RETE.

        `test_mutation_money.py` non e' una campagna che si lancia apposta: e' un test della
        suite di TUTTI I GIORNI. Rompe di proposito tre moduli di PRODUZIONE per chiedere «i
        test se ne accorgono?»: `fase160_escrow_garanzia` (split host/ospite),
        `fase162_pagamenti_pendenti` (whitelist degli stati), `fase59_concierge` (netto host).
        Tutti e tre sul DENARO.

        Rimetteva a posto con un `finally` e il suo commento diceva «niente residui» -- ma un
        `finally` non protegge da un processo UCCISO, ed e' scritto nero su bianco in
        `collaudi/mutazione_prodotto.py:739` dopo che era gia' successo tre volte. Non usava
        la traccia: zero riferimenti. Quindi un'interruzione lasciava un guasto nel codice dei
        soldi **e `collaudi/guardia_commit.py` non aveva nulla da vedere**.

        SUCCESSO DAVVERO il 2026-08-03: una suite intera e' stata fermata e ha lasciato
        `fase162_pagamenti_pendenti.py:263` con la whitelist allargata a `pagato, cancellato,
        rimborsato`. Trovato guardando `git status`, non da un allarme. E' il caso PEGGIORE
        della famiglia, perche' la suite gira prima di ogni commit e prima di ogni deploy.

        ⚠️ COSA NON ESAMINA (dichiarato): guarda quel file. Un NUOVO test che rompesse la
        produzione senza rete non verrebbe visto da qui.
        """
        import io
        import os
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "test_mutation_money.py")
        with io.open(p, encoding="utf-8") as f:
            righe = f.read().splitlines()
        # DENOMINATORE: i punti che scrivono il MUTANTE dentro il modulo di produzione.
        mutazioni = [n for n, r in enumerate(righe)
                     if "replace(btrova, bmuta, 1)" in r and not r.strip().startswith("#")]
        self.assertEqual(1, len(mutazioni),
                         "denominatore cambiato: %d punti che scrivono un mutante invece di "
                         "1. Se il file e' cambiato di proposito questo numero si aggiorna "
                         "GUARDANDO i punti nuovi, mai per far tornare il verde. Righe: %r"
                         % (len(mutazioni), [n + 1 for n in mutazioni]))
        ciechi = [(n + 1, righe[n].strip()[:60]) for n in mutazioni
                  if "_apri_traccia" not in "\n".join(righe[max(0, n - 8):n + 1])]
        self.assertEqual([], ciechi,
                         "questo punto rompe un modulo del PERCORSO DEI SOLDI senza mettere "
                         "da parte l'originale con `_apri_traccia`: se la suite viene "
                         "interrotta li', il guasto resta nel codice dei soldi e nessuno lo "
                         "sa. %r" % (ciechi,))
        tutto = "\n".join(righe)
        self.assertIn("_chiudi_traccia", tutto,
                      "la traccia viene aperta e mai chiusa: resterebbe li' a bloccare il "
                      "commit successivo per NIENTE, e un falso allarme e' un difetto quanto "
                      "uno mancato (CLAUDE.md, regola 10)")

    def test_eseguire_le_guardie_del_giudice_NON_cancella_una_traccia_viva(self):
        import io
        import os
        import shutil
        import subprocess
        import sys
        import tempfile
        radice = os.path.dirname(os.path.abspath(__file__))
        # Cartella temporanea NOSTRA: il processo figlio ci puntera' la sua `tempfile.
        # gettempdir()`, quindi il suo `_TRACCIA` cade qui dentro. Cosi' questa guardia
        # NON tocca la traccia vera della macchina -- sarebbe lo stesso difetto che vieta.
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        traccia = os.path.join(d, "bookinvip_mutazione_in_corso")
        os.makedirs(traccia)
        with io.open(os.path.join(traccia, "quale.txt"), "w", encoding="utf-8") as f:
            f.write(os.path.join(radice, "fase_finta_di_prova.py"))
        with io.open(os.path.join(traccia, "originale.txt"), "w", encoding="utf-8") as f:
            f.write("def f(x):\n    return x == 0\n")
        self.assertTrue(os.path.isdir(traccia), "precondizione: la traccia dev'esserci")

        amb = dict(os.environ, TMP=d, TEMP=d, TMPDIR=d)
        esito = subprocess.run(
            [sys.executable, "-m", "unittest",
             "test_pipeline_ci.TestGeneratoreDiMutanti",
             "test_pipeline_ci.TestIlGiudiceNonPuoGiudicareCodiceCheNonGIRA"],
            cwd=radice, env=amb, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(0, esito.returncode,
                         "le guardie del generatore non sono verdi: %s"
                         % esito.stdout.decode("utf-8", "replace")[-400:])

        self.assertTrue(
            os.path.isdir(traccia),
            "ESEGUIRE LE GUARDIE HA CANCELLATO LA TRACCIA di un giro in corso. Da questo "
            "istante un file di produzione mutato non e' piu' protetto: "
            "`collaudi/guardia_commit.py` non ha nulla da vedere e lascia salvare il "
            "guasto. Un test che mette in scena un'interruzione deve usare una traccia "
            "SUA (cartella temporanea), mai quella condivisa.")


class TestIlGiudiceNonPuoGiudicareCodiceCheNonGIRA(unittest.TestCase):
    """⛔ IL MOTORE DI MUTAZIONE DEVE PROVARE IL GUASTO, NON LA SUA CACHE.

    DIFETTO VERO, TROVATO E PROVATO IL 2026-07-31 (non dedotto).
    Python non ricompila un modulo se DIMENSIONE e DATA-AL-SECONDO della sorgente
    coincidono con quelle scritte nell'intestazione del suo `.pyc`. Quasi tutti i mutanti
    di `collaudi/mutazione_prodotto.py` cambiano un OPERATORE — `!=` diventa `==` — cioe'
    scrivono ESATTAMENTE LO STESSO NUMERO DI BYTE. Se la riscrittura cade nello stesso
    secondo della precedente, il processo figlio importa la versione compilata di PRIMA ed
    esegue il codice NON MUTATO.

    COSA COSTAVA, nelle due direzioni (una guardia sola non basterebbe):
      · FALSO ROSSO — il motore grida «mutante SOPRAVVISSUTO» per un guasto che non stava
        girando. Successo davvero: il job `mutazione` della CI e' andato rosso su
        `fase83_server.py` (protezione soldi invertita) mentre in casa lo stesso mutante
        moriva. Un'ora di caccia a un fantasma, e un rosso permanente insegna a ignorare
        il rosso — il danno peggiore.
      · FALSO VERDE, che e' peggio — un mutante contato fra gli UCCISI senza essere mai
        stato provato. Il punteggio «41 su 41» diventa una decorazione, e con esso ogni
        verde della suite che quel punteggio dovrebbe certificare.

    Spiega anche l'«instabilita' del job mutazione sul runner CI» scritta nel motore stesso
    e attribuita al carico della macchina: non era il carico, era un secondo di orologio.
    """

    @staticmethod
    def _motore():
        import importlib.util
        import os
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "collaudi", "mutazione_prodotto.py")
        spec = importlib.util.spec_from_file_location("_mut_cache", p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def _cavia(self):
        """Un modulo usa-e-getta, fuori dal progetto: il pericolo si riproduce a comando."""
        import os
        import shutil
        import tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        return d, os.path.join(d, "_cavia_mut.py")

    @staticmethod
    def _scrivi(percorso, segno):
        import io
        with io.open(percorso, "w", encoding="utf-8", newline="\n") as f:
            f.write("SEGNO = '%s'\n" % segno)          # due segni, STESSA dimensione

    @staticmethod
    def _chiedi(cartella):
        """Cosa vede DAVVERO un processo nuovo? L'osservabile forte, non il file su disco."""
        import subprocess
        import sys
        r = subprocess.run([sys.executable, "-c", "import _cavia_mut; print(_cavia_mut.SEGNO)"],
                           cwd=cartella, capture_output=True, text=True)
        return (r.stdout or "").strip()

    def _prepara_trappola(self):
        """Sorgente NUOVA con la data della VECCHIA: e' cio' che accade quando due
        scritture cadono nello stesso secondo, ma riproducibile a comando."""
        import os
        d, p = self._cavia()
        self._scrivi(p, "!=")
        self.assertEqual("!=", self._chiedi(d), "la cavia non parte")   # nasce il .pyc
        marca = os.stat(p).st_mtime
        self._scrivi(p, "==")
        os.utime(p, (marca, marca))
        return d, p

    def test_la_trappola_ESISTE_davvero(self):
        """Prima si dimostra che il pericolo e' reale: senza rimedio il figlio esegue
        il codice VECCHIO mentre sul disco c'e' quello nuovo."""
        d, _ = self._prepara_trappola()
        self.assertEqual("!=", self._chiedi(d),
                         "la trappola non si riproduce piu': se Python ha cambiato regola "
                         "di invalidazione, questa guardia va rivista di proposito")

    def test_invalida_bytecode_LA_DISINNESCA(self):
        d, p = self._prepara_trappola()
        self._motore().invalida_bytecode(p)
        self.assertEqual("==", self._chiedi(d),
                         "dopo l'invalidazione il processo figlio DEVE vedere il codice "
                         "vero: se no il motore giudica una cosa e ne esegue un'altra")

    def test_invalidare_due_volte_non_esplode(self):
        """Il .pyc puo' non esserci (prima esecuzione): non e' un errore, e' la condizione
        che vogliamo. Un'eccezione qui fermerebbe l'intero giro di mutazione."""
        d, p = self._prepara_trappola()
        m = self._motore()
        m.invalida_bytecode(p)
        m.invalida_bytecode(p)

    def test_il_motore_invalida_dopo_OGNI_riscrittura(self):
        """LA GUARDIA CHE CONTA (denominatore): non basta che la funzione esista, deve
        essere CHIAMATA dopo ogni punto in cui un file di produzione viene riscritto.
        Un punto nuovo che se ne dimentica fa diventare rosso questo test il giorno in
        cui nasce, invece di regalare mesi di punteggi falsi."""
        import io
        import os
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "collaudi", "mutazione_prodotto.py")
        with io.open(p, encoding="utf-8") as f:
            righe = f.read().splitlines()
        riscritture = [n for n, r in enumerate(righe)
                       if ('io.open(percorso, "w"' in r or "shutil.copy(os.path.join(riserva" in r)
                       and not r.strip().startswith("#")]
        self.assertGreaterEqual(len(riscritture), 3,
                                "denominatore sospetto: trovati solo %d punti di "
                                "riscrittura, la forma del motore e' cambiata"
                                % len(riscritture))
        ciechi = [(n + 1, righe[n].strip()[:60]) for n in riscritture
                  if "invalida_bytecode" not in "\n".join(righe[n:n + 3])]
        self.assertEqual([], ciechi,
                         "questi punti riscrivono un file di produzione senza buttare via "
                         "la sua versione compilata: il processo figlio potrebbe eseguire "
                         "il codice VECCHIO. %r" % (ciechi,))

    def test_il_motore_APRE_LA_TRACCIA_prima_di_OGNI_mutante(self):
        """LA GUARDIA SORELLA — e mancava proprio nel punto che serviva.

        `_apri_traccia` mette da parte l'originale PRIMA di rompere il file. E' l'unica cosa
        che permette a `recupera_da_interruzione` e a `collaudi/guardia_commit.py` di
        accorgersi di un giro UCCISO: il `finally` non protegge da un processo ucciso, e
        senza traccia non c'e' niente da recuperare e niente da bloccare al commit.

        SUCCESSO DAVVERO, 2026-08-03: il punto che gira la lista `MUTANTI` scriveva il
        mutante SENZA aprire la traccia. Un giro ucciso ha lasciato `if ore >= 99999:` al
        posto di `if ore >= 24:` nella penale no-show (fase83_server.py:6185) -- cioe' la
        penale addebitata SEMPRE, anche a chi disdice con un mese di anticipo. E' rimasto
        sul disco per ore senza che nulla gridasse, e il gancio al commit non poteva vederlo
        perche' non c'era nessuna traccia da vedere. Terza volta in quattro giorni (31 lug,
        1 ago, 3 ago): le prime due erano state chiuse con una rete che copriva due punti
        su tre, e nessuno aveva contato il denominatore.
        """
        import io
        import os
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "collaudi", "mutazione_prodotto.py")
        with io.open(p, encoding="utf-8") as f:
            righe = f.read().splitlines()
        # DENOMINATORE: i punti che INTRODUCONO un mutante dentro un file di produzione.
        # Non «ce n'e' almeno uno»: quanti sono, e sono TUTTI coperti?
        mutazioni = [n for n, r in enumerate(righe)
                     if ("applica_mutante(sorgente" in r or "replace(orig, mut, 1)" in r)
                     and not r.strip().startswith("#")
                     and not r.strip().startswith("def ")]
        # I QUATTRO PUNTI, guardati uno per uno il 2026-08-19 (erano tre fino a quel giorno):
        #   1. modo `--diff`      -- i mutanti sulle righe appena cambiate;
        #   2. modo `--modulo`    -- il giro su un modulo intero;
        #   3. modo `--modulo`, LA RI-CONFERMA: un «ucciso» viene rieseguito per vedere se il
        #      killer lo uccide SEMPRE o solo a volte (pezzo 2 del piano). E' un quarto punto
        #      vero, che rompe un file di produzione come gli altri tre, e apre la traccia
        #      come gli altri tre. ⛔ Apre la SUA traccia DOPO che la prima e' stata chiusa
        #      dal `finally` del primo giro: sequenziale, mai annidata -- la rete
        #      anti-interruzione ha una casella sola e non e' rientrante;
        #   4. il modo della CI  -- la lista `MUTANTI` scritta a mano.
        self.assertEqual(4, len(mutazioni),
                         "denominatore cambiato: %d punti che introducono un mutante invece "
                         "di 4. Se il motore e' cambiato di proposito questo numero si "
                         "aggiorna GUARDANDO i punti nuovi uno per uno, mai per far tornare "
                         "il verde. Righe: %r" % (len(mutazioni), [n + 1 for n in mutazioni]))
        ciechi = [(n + 1, righe[n].strip()[:60]) for n in mutazioni
                  if "_apri_traccia" not in "\n".join(righe[max(0, n - 4):n + 1])]
        self.assertEqual([], ciechi,
                         "questi punti rompono un file di PRODUZIONE senza mettere da parte "
                         "l'originale con `_apri_traccia`: se il processo viene ucciso li', "
                         "il guasto resta sul disco e NE' `recupera_da_interruzione` NE' "
                         "`collaudi/guardia_commit.py` possono accorgersene. %r" % (ciechi,))


    def test_NON_SI_SALVA_MENTRE_UN_GIRO_DI_MUTAZIONE_E_APERTO(self):
        """⛔ DIRETTIVA D18 applicata al salvataggio: la memoria umana non e' una strategia.

        FATTO VERO, 2026-08-02: tre cicli di mutazione interrotti, e OGNI VOLTA un guasto
        rimasto dentro un file di PRODUZIONE. L'ultimo faceva rispondere alla macchina
        «questa penale era gia' stata stornata» anche quando non era vero. Dimostrato che
        senza blocco quel guasto entra nel salvataggio senza che nulla dica niente.

        La rete di recupero del giudice ha la copia buona, ma ripristina al giro SUCCESSIVO:
        fra l'interruzione e il giro dopo c'e' una finestra in cui `git add -A` porta il
        guasto nel commit, poi in produzione, **con tutti i controlli verdi** -- quei punti
        sono scoperti per definizione, e' il motivo per cui li stiamo mutando.

        Ci ha protetto il fatto che me ne sono ricordato tre volte su tre. Non e' un
        controllo: e' fortuna con un nome piu' bello.
        """
        import os
        import shutil
        import tempfile
        radice = os.path.dirname(os.path.abspath(__file__))
        m = self._modulo(os.path.join(radice, "collaudi", "guardia_commit.py"),
                         "_guardia_commit")

        # (1) le DUE direzioni della funzione: con la traccia aperta ferma, senza lascia fare
        d = tempfile.mkdtemp()
        try:
            vuota = os.path.join(d, "non-esiste")
            # ⛔ IL CONTRATTO E' CAMBIATO IL 2026-08-14: il secondo valore e' un ELENCO,
            # non una stringa, perche' i giri aperti possono essere PIU' D'UNO (il Giudice
            # gira anche dentro se stesso). Il controllo qui sotto e' lo stesso di prima --
            # «niente aperto, nessun nome» -- scritto nella forma nuova.
            self.assertEqual((False, []), m.mutazione_in_corso(vuota),
                             "dice che un giro e' aperto quando non c'e' niente: bloccherebbe "
                             "sempre, e un blocco sempre acceso viene tolto")
            traccia = os.path.join(d, "aperta")
            os.makedirs(traccia)
            with open(os.path.join(traccia, "quale.txt"), "w", encoding="utf-8") as f:
                f.write("fase177_financial_controller.py")
            aperta, quali = m.mutazione_in_corso(traccia)
            self.assertTrue(aperta, "un giro interrotto non viene visto")
            self.assertIn("fase177", "\n".join(quali),
                          "non dice QUALE file potrebbe essere rotto")
        finally:
            shutil.rmtree(d, ignore_errors=True)

        # (2) il gancio esiste, e' VERSIONATO (non in .git/hooks, che non viaggia) e chiama
        #     davvero la guardia. Un gancio che vive solo su un computer non protegge nessuno.
        gancio = os.path.join(radice, "deploy", "hooks", "pre-commit")
        self.assertTrue(os.path.exists(gancio),
                        "il gancio pre-commit non e' piu' nel repository: tornerebbe a "
                        "esistere solo sul computer di chi l'ha creato")
        with open(gancio, encoding="utf-8") as f:
            testo = f.read()
        self.assertIn("guardia_commit", testo,
                      "il gancio non chiama piu' la guardia: %r" % testo[:200])
        self.assertTrue(os.path.exists(os.path.join(radice, "deploy", "installa_hook.sh")),
                        "manca lo script che accende i ganci su una macchina nuova")

        # (3) I GANCI RESTANO SOLO-ASCII. Non perche' `sh` se ne accorga -- i commenti non
        #     li interpreta -- ma perche' girano su macchine, shell e lingue diverse, e un
        #     gancio e' l'ultimo posto dove scoprire un problema di codifica. Il 2026-08-02
        #     il programma chiamato da questo gancio e' ESPLOSO su un simbolo non-ASCII:
        #     bloccava il commit per il motivo sbagliato, mostrando un traceback al posto
        #     delle istruzioni. Richiesta esplicita del fondatore, e costa zero mantenerla.
        for nome in sorted(os.listdir(os.path.join(radice, "deploy", "hooks"))):
            p = os.path.join(radice, "deploy", "hooks", nome)
            with open(p, "rb") as f:
                dati = f.read()
            fuori = [(i, b) for i, b in enumerate(dati) if b > 126]
            self.assertEqual([], fuori[:5],
                             "il gancio %s contiene byte non-ASCII (posizione, valore): %r"
                             % (nome, fuori[:5]))

    @staticmethod
    def _modulo(percorso, nome):
        import importlib.util
        spec = importlib.util.spec_from_file_location(nome, percorso)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_IL_GIUDICE_NON_PUO_GIUDICARE_SU_UNA_BASE_ROSSA(self):
        """⛔ DIRETTIVA D18: uno strumento che misura deve avere un controllo MECCANICO che
        gli impedisca di barare — e quel controllo va a sua volta sorvegliato, se no fra sei
        mesi sparisce in una «semplificazione» e nessuno se ne accorge.

        DIFETTO VERO, 2026-08-01. Il giudice ha stampato «42 mutanti su 42 UCCISI» mentre un
        test era ROSSO sul codice sano. Se i test falliscono comunque, falliscono anche con
        ogni guasto dentro: OGNI mutante risulta «ucciso». Il punteggio pieno era aria — ed e'
        la forma piu' insidiosa di finto verde, perche' non arriva come un problema, arriva
        come un trionfo, e nessuno controlla un trionfo.

        Qui si prova la sostanza, non la forma: si costruisce un giudice IDENTICO a quello
        vero ma con la misura della base tolta, e si pretende che il caso malato passi per
        sano. Se un domani il controllo venisse rimosso, questo test lo direbbe lo stesso
        giorno.
        """
        import importlib.util
        import os
        radice = os.path.dirname(os.path.abspath(__file__))
        m = self._motore_giudice(radice)

        # (1) la funzione esiste e risponde davvero a "i test sono verdi?" -- una che
        #     rispondesse sempre `True` sarebbe un ornamento.
        self.assertTrue(hasattr(m, "base_e_verde"),
                        "il controllo della base e' sparito dal giudice: senza, un punteggio "
                        "pieno puo' essere misurato su test gia' rossi")
        m._BASI.clear()
        m._BASI["FINTO_VERDE"] = (True, "")
        m._BASI["FINTO_ROSSO"] = (False, "i test falliscono")
        self.assertEqual((True, ""), m.base_e_verde("FINTO_VERDE"))
        self.assertEqual(False, m.base_e_verde("FINTO_ROSSO")[0],
                         "il controllo dice VERDE anche su una base rossa: non guarda niente")

        # (2) LA GUARDIA CHE CONTA: il controllo dev'essere CHIAMATO in ogni modo che giudica.
        #     Non basta che esista: deve stare sul percorso, prima di rompere qualcosa.
        #
        # ⛔ SI GUARDA L'ALBERO SINTATTICO, NON IL TESTO. La prima versione di questa guardia
        #    cercava la stringa "base_e_verde" nel sorgente: commentare la riga la lasciava
        #    lì, e la guardia passava col controllo spento. Provato il 2026-08-01 -- tre
        #    rimozioni su tre, tutte VERDI. Cioè la prima guardia scritta per la direttiva
        #    D18 ha fallito D18 al primo colpo. Nell'albero sintattico i commenti non
        #    esistono: una chiamata commentata sparisce, ed è l'unica cosa che conta.
        import ast
        import io
        with io.open(os.path.join(radice, "collaudi", "mutazione_prodotto.py"),
                     encoding="utf-8") as f:
            albero = ast.parse(f.read())

        def chiamate(nodo):
            return {n.func.id for n in ast.walk(nodo)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}

        pezzi = {}
        for nodo in albero.body:
            if isinstance(nodo, ast.FunctionDef) and nodo.name in ("giro_su_moduli",
                                                                   "giro_sul_diff"):
                pezzi[nodo.name] = nodo
            # il modo della CI: `if __name__ == "__main__":` SENZA altre condizioni (gli altri
            # tre modi hanno anche `and "--flag" in sys.argv`)
            elif isinstance(nodo, ast.If) and isinstance(nodo.test, ast.Compare):
                pezzi["modo_ci"] = nodo

        for modo, chiave in (("--modulo (campagne per rischio)", "giro_su_moduli"),
                             ("--diff (le righe appena scritte)", "giro_sul_diff"),
                             ("della CI (i 41 mutanti a mano)", "modo_ci")):
            self.assertIn(chiave, pezzi, "il modo %s non esiste piu' nel giudice" % modo)
            fatte = chiamate(pezzi[chiave])
            self.assertTrue(fatte & {"base_e_verde", "misura_normale"},
                            "il modo %s NON chiama il controllo della base: li' i test "
                            "potrebbero essere gia' rossi, ogni mutante risulterebbe "
                            "«ucciso» e il punteggio sarebbe aria. Chiamate trovate: %s"
                            % (modo, sorted(fatte)))
        testo = io.open(os.path.join(radice, "collaudi", "mutazione_prodotto.py"),
                        encoding="utf-8").read()

        # (3) e il verdetto dev'essere ROSSO, non una nota a pie' di pagina: un giro che non
        #     ha giudicato niente non puo' uscire verde.
        self.assertIn("base_rossa", testo)
        coda = testo.split('if __name__ == "__main__":')[-1]
        self.assertIn("basi_rosse", coda,
                      "il modo della CI non tiene il conto delle basi rosse: uscirebbe verde "
                      "dopo aver saltato tutto")

    @staticmethod
    def _motore_giudice(radice):
        import importlib.util
        import os
        p = os.path.join(radice, "collaudi", "mutazione_prodotto.py")
        spec = importlib.util.spec_from_file_location("_giudice_base", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_L_AVVIO_DEL_GIUDICE_E_PROVABILE_E_NON_ESPLODE(self):
        """⛔ IL GIUDICE ERA L'UNICA COSA SENZA UN GIUDICE.

        DIFETTO VERO, 2026-08-01. Il modo senza argomenti -- quello che gira in CI -- inizia
        con un blocco che nessun test attraversava: le tre modalita' a flag (`--censimento`,
        `--modulo`, `--diff`) escono PRIMA. Una modifica mal riuscita ci ha lasciato dentro
        una riga spezzata a meta':

            riserva = tempfile.mkdtemp
            recupera_da_interruzione()(prefix="mutazione_")

        Sintassi valida, quindi nessun lint e nessuna compilazione se ne accorge; esplosione
        certa alla prima esecuzione (`TypeError: 'NoneType' object is not callable`). L'ho
        scoperto **dalla CI, dopo il push**: cioe' nel posto giusto ma nel momento sbagliato.

        Qui l'avvio si esegue davvero, in un secondo, **senza mutare un solo file**: se
        qualcuno rompe di nuovo quel blocco, diventa rosso in casa e non su GitHub.
        """
        import os
        import shutil
        import subprocess
        import sys
        import tempfile
        radice = os.path.dirname(os.path.abspath(__file__))
        # ⛔ CARTELLA TEMPORANEA TUTTA SUA. Lo strumento, a OGNI avvio, chiama
        # `recupera_da_interruzione()`: se trova una traccia la CONSUMA e RISCRIVE il file
        # che vi e' indicato. Con la temporanea condivisa questa prova spegneva la rete di
        # una campagna in corso -- ed e' cosi' che il 2026-08-03 un mutante e' rimasto vivo
        # in `fase184_marca_temporale.py` senza che il gancio al commit potesse vederlo.
        # Qui il processo figlio ha la SUA temporanea: recupera nel vuoto e non tocca nessuno.
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        amb = dict(os.environ, TMP=d, TEMP=d, TMPDIR=d)
        r = subprocess.run([sys.executable, os.path.join(radice, "collaudi",
                                                         "mutazione_prodotto.py"),
                            "--prova-avvio"],
                           cwd=radice, env=amb, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180)
        tutto = (r.stdout or "") + (r.stderr or "")
        self.assertNotIn("Traceback", tutto,
                         "l'avvio del giudice esplode: in CI il job muore prima di provare "
                         "un solo mutante, e il punteggio non esiste.\n%s" % tutto[-800:])
        self.assertEqual(0, r.returncode,
                         "l'avvio del giudice esce %s\n%s" % (r.returncode, tutto[-800:]))
        self.assertIn("AVVIO OK", r.stdout,
                      "il modo di prova non arriva in fondo al blocco d'avvio: proverebbe "
                      "meno di quello che dice")

    def test_la_prova_d_avvio_NON_LASCIA_SPORCO(self):
        """Una prova che modifica i file di produzione sarebbe peggio del difetto che cerca:
        il giudice copia i file in una riserva, e quella riserva va rimossa. Se restasse,
        ogni esecuzione lascerebbe una cartella con dentro **codice di produzione**."""
        import io
        import os
        import re
        radice = os.path.dirname(os.path.abspath(__file__))
        with io.open(os.path.join(radice, "collaudi", "mutazione_prodotto.py"),
                     encoding="utf-8") as f:
            testo = f.read()
        blocco = testo.split('"--prova-avvio" in sys.argv')[-1].split("sys.exit(0)")[0]
        self.assertIn("rmtree(riserva", re.sub(r"\s+", " ", blocco),
                      "il modo di prova non ripulisce la riserva: lascerebbe in giro copie "
                      "dei file di produzione a ogni esecuzione della suite")


def _righe_dello_schedario(motore, nome_file):
    """Le righe del file COME SAREBBE SENZA IL GUASTO -- anche mentre una campagna di
    mutazione lo tiene rotto di proposito. `None` se il file non esiste piu'.

    Serve alle guardie sullo schedario degli equivalenti, che questo file nomina: da quando
    lo nomina, `test_che_nominano` conta `test_pipeline_ci` fra i SORVEGLIANTI di quei
    moduli, e una guardia che leggesse il file mutato diventerebbe rossa facendo contare il
    mutante come «ucciso» senza che nessun comportamento sia stato sorvegliato.

    Il giudice, prima di rompere, mette da parte l'originale nella traccia anti-interruzione.
    Se una traccia e' aperta su QUESTO file, si giudica quell'originale.
    ⛔ SOLA LETTURA, sempre: consumare la traccia spegnerebbe la rete di una campagna viva --
    e' il difetto del 2026-08-03, quando furono i test a spegnerla.

    ⛔ IL BUCO CHE RESTA, dichiarato invece che tappato con un'euristica. Una campagna uccisa
    lascia la traccia APERTA (succede: due giri su quattro il 2026-08-05). Se in quello stato
    qualcuno modifica DAVVERO la riga sotto una dimostrazione, i controlli 1 e 3 giudicano
    l'originale della traccia e restano verdi a torto. Non c'e' un segnale che distingua in
    modo affidabile «campagna viva» da «traccia dimenticata» -- in tutti e due i casi il file
    su disco differisce dall'originale -- e una guardia che scegliesse la sorgente «che fa
    passare il test» sarebbe il peggior disegno possibile. Quel che rende accettabile il buco
    e' che NON PUO' ATTRAVERSARE UN COMMIT: finche' la traccia esiste,
    `collaudi/guardia_commit.py` blocca il salvataggio e dice quale file guardare. La finestra
    cieca vive solo in locale, ed e' rumorosa.
    """
    traccia = getattr(motore, "_TRACCIA", "") or ""
    quale = os.path.join(traccia, "quale.txt")
    originale = os.path.join(traccia, "originale.txt")
    if traccia and os.path.exists(quale) and os.path.exists(originale):
        try:
            with io.open(quale, encoding="utf-8") as f:
                sotto_i_ferri = f.read().strip()
            if (sotto_i_ferri
                    and os.path.basename(sotto_i_ferri) == os.path.basename(nome_file)):
                with io.open(originale, encoding="utf-8", newline="") as f:
                    return f.read().splitlines()
        except OSError:
            pass           # la traccia e' un di piu': se non si legge, si giudica il disco
    pieno = os.path.join(motore.REPO, nome_file)
    if not os.path.exists(pieno):
        return None
    return motore._leggi_intatto(pieno).splitlines()


class TestLoSchedarioDegliEquivalenti_1_ANCORAGGIO(unittest.TestCase):
    """⛔ LA GUARDIA SULLO SCHEDARIO DEGLI EQUIVALENTI — controllo 1 di 4: ANCORAGGIO.

    `EQUIVALENTI_DICHIARATI`, in `collaudi/mutazione_prodotto.py`, e' l'unico posto del
    progetto dove un errore diventa CECITA' PERMANENTE. Una voce li' dentro dice al giudice
    della mutazione: «questo guasto non provarlo piu', non c'e' niente da vedere» -- e da
    quel momento il punteggio esce PIENO senza che quel punto sia mai piu' messo alla prova.
    Un buco SCOPERTO almeno si vede nel riepilogo; un buco PERDONATO non si vede mai piu'.

    TRE VOCI FALSE IN QUATTRO GIORNI, e nessun test guardava lo schedario:
      · 31 lug -- fase100 (DAC7), `_n`  provata su 11 ingressi: dominio piu' piccolo della firma
      · 1 ago  -- fase177/`_cent`      dichiarata perfino con z3, e sbagliata lo stesso
      · 4 ago  -- fase160/`_cent`      ritirata prima del commit da una revisione fresca
    Le prime due sono ancora dentro. La **D18 punto 4** -- «il controllo e' a sua volta sotto
    guardia» -- non era soddisfatta proprio sulla manopola che trasforma un buco in uno zero.

    ⛔ COSA QUESTA GUARDIA NON FA, DETTO PRIMA (D18 punto 3).
    Non giudica se una dimostrazione sia GIUSTA: se potesse, sarebbe lei il dimostratore.
    Il 2026-08-05 un controllo a parole chiave scritto al volo ha accusato a torto NOVE
    dichiarazioni serie -- un controllo debole con verdetto forte e' PEGGIO di nessun
    controllo, perche' insegna a ignorare i rossi (regola ferrea 10). Restano fuori, e sono
    i controlli 2, 3 e 4 dello stesso piano: i campi strutturati (`metodo`, `dominio`,
    `data`, `prova`), il confronto DOMINIO >= FIRMA, e le frasi vietate dal divieto B6.

    QUI si controlla UNA cosa sola, con un confronto ESATTO dove i falsi allarmi non sono
    possibili: **la voce aggancia ancora qualcosa di vivo?** La chiave e'
    (file, funzione, testo della riga, vecchio, nuovo), ed e' esattamente cio' che
    `_e_equivalente` va a cercare. Scritta col TESTO e non col numero, la voce regge se il
    codice si SPOSTA -- ed e' giusto cosi'. Ma se quella riga e' CAMBIATA, o e' finita in
    un'altra funzione, o il file non c'e' piu', la voce non descrive piu' niente: o il codice
    e' cambiato senza rifare la dimostrazione, o e' un residuo. In tutti e due i casi serve
    l'occhio di una persona, e il modo di chiederlo e' un rosso.
    """

    @staticmethod
    def _motore():
        """Il giudice caricato a parte, con un nome tutto suo: si interroga il modulo VERO,
        non una copia delle sue regole scritta qui dentro."""
        import importlib.util
        p = os.path.join(QUI, "collaudi", "mutazione_prodotto.py")
        spec = importlib.util.spec_from_file_location("_schedario_equivalenti", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @classmethod
    def _perche_non_aggancia(cls, motore, chiave):
        """`None` se la voce aggancia una riga viva; altrimenti il MOTIVO, per esteso.

        Si usa `funzione_di` DEL GIUDICE, non una copia scritta qui: cio' che conta non e' se
        la riga esiste «secondo il test», ma se la chiave puo' ancora combaciare dentro
        `_e_equivalente` -- l'unico posto dove una voce fa effetto.
        """
        nome_file, funzione, testo, vecchio, _nuovo = chiave
        righe = _righe_dello_schedario(motore, nome_file)
        if righe is None:
            return "il file non esiste piu' nel repository"
        numeri = [n for n, r in enumerate(righe, 1) if r.strip() == testo]
        if not numeri:
            return "nessuna riga del file e' piu' uguale a %r" % testo
        dentro = [n for n in numeri if motore.funzione_di(righe, n) == funzione]
        if not dentro:
            altrove = sorted({motore.funzione_di(righe, n) or "<fuori da ogni funzione>"
                              for n in numeri})
            return ("la riga %r esiste ma NON dentro %r: sta in %s (righe %r)"
                    % (testo, funzione, altrove, numeri))
        if vecchio not in testo:
            return ("la riga aggancia, ma il pezzo dichiarato %r non compare piu' in %r: "
                    "il giudice non generera' mai quel guasto su questa riga"
                    % (vecchio, testo))
        return None

    def test_IL_CONTROLLO_SA_DIRE_DI_NO_e_SA_DIRE_DI_SI(self):
        """⛔ D18 punti 1 e 2: uno strumento che misura prova PRIMA di essere in condizione
        di misurare, e si prova nelle DUE direzioni.

        Un controllo che rispondesse sempre «va bene» passerebbe anche sullo schedario piu'
        marcio, e sarebbe la peggiore specie di ornamento: uno che porta il nome di una
        difesa. Qui il controllo viene messo davanti a una cavia usa-e-getta, fuori dal
        progetto, dove la verita' e' nota per costruzione: **una voce buona e i QUATTRO modi
        di essere morta**. Se un domani qualcuno lo indebolisse fino a non saper piu' dire di
        no, questo test diventerebbe rosso lo stesso giorno.

        Il terzo caso non e' teorico: e' il difetto vero corretto il 2026-08-01. La riga
        `if v < 0:` compare in DUE funzioni della cavia, esattamente come `if residuo <= 0:`
        in `fase177`, e dichiararne una non deve rendere cieca l'altra.
        """
        motore = self._motore()
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        with io.open(os.path.join(d, "cavia_schedario.py"), "w",
                     encoding="utf-8", newline="\n") as f:
            f.write("def paga(v):\n"
                    "    if v < 0:\n"
                    "        return 0\n"
                    "    return v\n"
                    "\n"
                    "\n"
                    "def rimborsa(v):\n"
                    "    if v < 0:\n"
                    "        return 1\n"
                    "    return v\n")
        motore.REPO = d

        buona = ("cavia_schedario.py", "paga", "if v < 0:", "<", "<=")
        self.assertIsNone(self._perche_non_aggancia(motore, buona),
                          "il controllo accusa una voce SANA: un falso allarme insegna a "
                          "ignorare i rossi, ed e' un difetto quanto un allarme mancato")

        for chiave, pezzo_atteso in (
                (("mai_esistito.py", "paga", "if v < 0:", "<", "<="),
                 "non esiste piu'"),
                (("cavia_schedario.py", "paga", "if v < 999:", "<", "<="),
                 "nessuna riga del file"),
                (("cavia_schedario.py", "funzione_sparita", "if v < 0:", "<", "<="),
                 "NON dentro"),
                (("cavia_schedario.py", "paga", "if v < 0:", ">=", ">"),
                 "non compare piu'")):
            motivo = self._perche_non_aggancia(motore, chiave)
            self.assertIsNotNone(motivo,
                                 "il controllo NON vede una voce morta (%r): con questo "
                                 "buco lo schedario potrebbe marcire in silenzio" % (chiave,))
            self.assertIn(pezzo_atteso, motivo,
                          "vede il problema ma lo racconta male: chi legge il rosso deve "
                          "capire SUBITO perche' la voce e' morta. Voce %r, motivo %r"
                          % (chiave, motivo))

        # E la diagnosi del terzo caso dice anche DOVE sta davvero quella riga: senza, il
        # rosso obbliga a rileggersi il file a mano.
        motivo = self._perche_non_aggancia(
            motore, ("cavia_schedario.py", "funzione_sparita", "if v < 0:", "<", "<="))
        self.assertIn("paga", motivo)
        self.assertIn("rimborsa", motivo,
                      "non elenca tutte le funzioni in cui quella riga vive davvero: %r"
                      % motivo)

    def test_NON_DIVENTA_UN_KILLER_FALSO_durante_una_campagna_di_mutazione(self):
        """⛔ DIFETTO DI QUESTA GUARDIA STESSA, trovato il 2026-08-05 PRIMA che facesse danno.

        Questo file nomina `fase177_financial_controller`, quindi `test_che_nominano` lo conta
        fra i suoi SORVEGLIANTI. Durante una campagna il giudice
        rompe di proposito una riga di quel modulo e lancia anche questa suite: se la guardia
        leggesse il file ROTTO direbbe «la voce non aggancia piu' niente», diventerebbe rossa,
        e il giudice conterebbe quel mutante come UCCISO. Ucciso da cosa? Da un test che ha
        notato che il SORGENTE e' cambiato, non che il COMPORTAMENTO e' sbagliato. E' il
        gonfiaggio del punteggio -- esattamente cio' che questo progetto caccia da giorni, e
        sarebbe entrato dalla porta di una guardia scritta per impedirlo.

        Il rimedio NON e' spegnere la guardia: una guardia che si spegne da sola e' la lezione
        del 2026-08-03, quando furono i test a spegnere la rete anti-interruzione. E' leggere
        la sorgente VERA. Il giudice, prima di rompere, mette da parte l'originale nella
        traccia; se una traccia e' aperta su QUEL file, la guardia giudica quell'originale.
        ⛔ In SOLA LETTURA: consumare la traccia vera spegnerebbe la rete di una campagna viva.
        """
        import io
        motore = self._motore()
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        cavia = os.path.join(d, "cavia_schedario.py")
        sano = ("def paga(v):\n"
                "    if v < 0:\n"
                "        return 0\n"
                "    return v\n")
        with io.open(cavia, "w", encoding="utf-8", newline="\n") as f:
            f.write(sano)
        motore.REPO = d
        voce = ("cavia_schedario.py", "paga", "if v < 0:", "<", "<=")
        self.assertIsNone(self._perche_non_aggancia(motore, voce), "la cavia nasce sana")

        # ⛔ UNA TRACCIA TUTTA SUA, mai quella vera: la traccia vera appartiene a una
        # campagna che potrebbe essere in corso adesso, e toccarla e' il difetto del 3 agosto.
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        motore._TRACCIA = t
        with io.open(os.path.join(t, "quale.txt"), "w", encoding="utf-8") as f:
            f.write(cavia)
        with io.open(os.path.join(t, "originale.txt"), "w", encoding="utf-8", newline="") as f:
            f.write(sano)
        # ...e ora il file su disco e' ROTTO DI PROPOSITO, come durante una campagna
        with io.open(cavia, "w", encoding="utf-8", newline="\n") as f:
            f.write(sano.replace("if v < 0:", "if v <= 0:"))
        self.assertIsNone(
            self._perche_non_aggancia(motore, voce),
            "la guardia giudica il file ROTTO DI PROPOSITO invece dell'originale messo da "
            "parte dal giudice: diventerebbe rossa durante ogni campagna sui moduli che "
            "questo file nomina, e ogni mutante su quelle righe risulterebbe UCCISO senza "
            "che nessun comportamento sia stato davvero sorvegliato")

        # E LA DIREZIONE OPPOSTA: senza campagna in corso, lo stesso file cambiato e' rosso.
        # Se non lo fosse, la guardia avrebbe smesso di guardare invece di guardare meglio.
        shutil.rmtree(t, ignore_errors=True)
        motivo = self._perche_non_aggancia(motore, voce)
        self.assertIsNotNone(motivo,
                             "senza traccia aperta un file davvero cambiato DEVE essere "
                             "rosso: altrimenti la guardia si e' spenta, non affinata")
        self.assertIn("nessuna riga del file", motivo)

    def test_OGNI_VOCE_dello_schedario_HA_LA_FORMA_CHE_QUESTA_GUARDIA_SA_LEGGERE(self):
        """IL DENOMINATORE, prima del giudizio (D18 punto 3: niente tagli silenziosi).

        Se qualcuno aggiungesse una voce con una chiave di forma diversa, il controllo qui
        sotto la salterebbe senza dire niente -- e una voce non esaminata sembrerebbe una
        voce sana. Quindi prima si pretende che OGNI voce sia una chiave a cinque campi di
        testo: file, funzione, riga, vecchio, nuovo. Nessuna esclusa, nessuna «quasi».
        """
        voci = self._motore().EQUIVALENTI_DICHIARATI
        self.assertGreaterEqual(
            len(voci), 1,
            "lo schedario e' VUOTO: o l'elenco e' stato svuotato, o questa guardia sta "
            "leggendo la cosa sbagliata. In tutti e due i casi il verde qui sotto non "
            "significherebbe niente, perche' non avrebbe esaminato nulla")
        storte = [k for k in voci
                  if not (isinstance(k, tuple) and len(k) == 5
                          and all(isinstance(x, str) for x in k))]
        self.assertEqual([], storte,
                         "queste voci non hanno la forma (file, funzione, riga, vecchio, "
                         "nuovo): il controllo di ancoraggio non saprebbe esaminarle e le "
                         "salterebbe in silenzio. Voci su %d totali: %r"
                         % (len(voci), storte))

    def test_OGNI_VOCE_dello_schedario_AGGANCIA_UNA_RIGA_VIVA(self):
        """⛔ LA GUARDIA. Una voce che non aggancia piu' niente e' una voce MORTA.

        Non e' un dettaglio di forma: e' il segnale che il codice sotto la dimostrazione si e'
        mosso. La dimostrazione parlava di UNA riga precisa dentro UNA funzione precisa; se
        quella riga oggi e' diversa, la prova non e' piu' stata fatta su cio' che c'e'. Il
        pericolo non e' solo la voce che smette di valere -- quella e' innocua, il mutante
        torna semplicemente fra i sopravvissuti -- e' che nessuno se ne accorga MAI, e che
        l'elenco si riempia di dichiarazioni che parlano di un codice che non esiste piu'.

        Falsi allarmi impossibili: e' un confronto ESATTO fra il testo dichiarato e il testo
        sul disco, letto con lo stesso lettore del giudice. Se questo diventa rosso, o si
        rifa' la dimostrazione sulla riga di oggi, o la voce si toglie.
        """
        motore = self._motore()
        voci = motore.EQUIVALENTI_DICHIARATI
        morte = []
        for chiave in sorted(voci):
            motivo = self._perche_non_aggancia(motore, chiave)
            if motivo:
                morte.append("  %s · %s · %s -> %s\n      %s"
                             % (chiave[0], chiave[1] or "<fuori da ogni funzione>",
                                chiave[3], chiave[4], motivo))
        self.assertEqual(
            [], morte,
            "DENOMINATORE: %d voci dichiarate, tutte esaminate. Queste %d NON agganciano "
            "piu' nessuna riga viva del sorgente, quindi perdonano un guasto che non "
            "esiste piu' nella forma in cui era stato dimostrato:\n%s"
            % (len(voci), len(morte), "\n".join(morte)))


class TestLoSchedarioDegliEquivalenti_2_CAMPI_STRUTTURATI(unittest.TestCase):
    """⛔ CONTROLLO 2 di 4: OGNI VOCE DICHIARA `metodo`, `dominio`, `data`, `prova`.

    Il controllo 1 chiede se la voce aggancia ancora il codice. Questo chiede una cosa
    diversa e piu' scomoda: **la voce dice COME e' stata dimostrata, e SU QUALE DOMINIO?**

    Finche' la motivazione e' prosa libera, nessuna macchina puo' chiedersi niente: si puo'
    scrivere «e' evidente» e ottenere lo stesso silenzio che si ottiene con una prova vera.
    Con quattro campi la domanda diventa possibile -- ed e' il controllo 3 a farla: *una
    prova esaustiva o z3 copre davvero tutto il dominio che la funzione accetta?* Le tre
    voci false di questi quattro giorni erano tutte la stessa cosa, e senza il campo
    `dominio` accanto al campo `metodo` quella forma comune resta invisibile.

    ⛔ COSA NON FA (D18 punto 3). Non giudica il CONTENUTO della prova: pretende che i campi
    ci siano, che il metodo sia uno dei tre ammessi e che la data sia una data. Una prova
    scritta male ma nei campi giusti passa di qui -- e deve passare, perche' un controllo
    che pretendesse di giudicare le dimostrazioni sarebbe il dimostratore, ed e' l'errore
    che il 2026-08-05 ha prodotto nove accuse sbagliate. Il giudizio sul contenuto resta
    umano; questa guardia serve a rendere quel giudizio POSSIBILE.

    ⛔ E IL VINCOLO CHE NON SI PUO' ROMPERE: il lettore `_e_equivalente` deve continuare a
    restituire TESTO. I suoi due soli consumatori (`mutazione_prodotto.py:905` e `:1052`)
    fanno `motivo[:70]` e `motivo[:60]`: con un dizionario il giro morirebbe con un
    TypeError **dopo** aver gia' rotto un file di produzione. C'e' una prova apposta.
    """

    # ⛔ `ancore` e `impronta` aggiunti il 2026-08-24 per ORDINE DEL FONDATORE, ed e' la
    #    condizione con cui lo schedario e' stato riaperto: «se quella riga cambia, la
    #    dichiarazione di equivalenza decade DA SOLA e il mutante torna da uccidere».
    #    Una prova non parla mai della sola riga mutata: parla anche del codice intorno.
    #    Senza impronta, cambiare quel codice lascia la voce in piedi -- e quel punto non
    #    lo guarda piu' nessuno, per sempre e in silenzio.
    CAMPI = ("ancore", "impronta", "metodo", "dominio", "data", "prova")
    # Insieme CHIUSO, ed e' chiuso apposta: «non e' raggiungibile» e «non e' osservabile»
    # non sono metodi di dimostrazione (divieto B6, direttiva D19). Se non rientra in uno
    # di questi tre, quel mutante resta un sopravvissuto dichiarato.
    METODI = ("esaustiva", "traccia", "z3")

    @staticmethod
    def _motore():
        import importlib.util
        p = os.path.join(QUI, "collaudi", "mutazione_prodotto.py")
        spec = importlib.util.spec_from_file_location("_schedario_campi", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @classmethod
    def _guasto_della_voce(cls, voce):
        """`None` se la voce e' in regola; altrimenti il motivo.

        Prende SOLO il valore, non la chiave: cosi' la stessa identica regola si puo' mettere
        alla prova su voci finte, nelle due direzioni, senza toccare lo schedario vero. Una
        regola che si puo' provare solo sui dati veri non si puo' provare rossa.
        """
        if not isinstance(voce, dict):
            return ("e' prosa libera (%s), non quattro campi: nessuna macchina puo' "
                    "chiedersi su quale dominio sia stata fatta la prova"
                    % type(voce).__name__)
        mancanti = [c for c in cls.CAMPI if c not in voce]
        extra = [c for c in sorted(voce) if c not in cls.CAMPI]
        if mancanti or extra:
            return "campi mancanti %r, campi non previsti %r" % (mancanti, extra)
        # `ancore` e' l'unico campo che NON e' testo: e' l'elenco dei blocchi di sorgente su
        # cui poggia la prova. Un blocco, non una riga sola -- `comm = 0` da sola comparirebbe
        # in mezzo file, e allora la verifica di presenza non direbbe niente.
        if not (isinstance(voce["ancore"], (list, tuple)) and voce["ancore"]
                and all(isinstance(a, str) and a.strip() for a in voce["ancore"])):
            return "`ancore` non e' un elenco non vuoto di blocchi di sorgente: %r" % (
                voce["ancore"],)
        vuoti = [c for c in cls.CAMPI if c != "ancore"
                 and (not isinstance(voce[c], str) or not voce[c].strip())]
        if vuoti:
            return "campi vuoti o non testuali: %r" % (vuoti,)
        if voce["metodo"] not in cls.METODI:
            return ("metodo %r: non e' uno dei tre ammessi %r. «non e' raggiungibile» e "
                    "«non e' osservabile» NON sono metodi di dimostrazione (divieto B6)"
                    % (voce["metodo"], list(cls.METODI)))
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", voce["data"]):
            return ("data %r non e' nella forma AAAA-MM-GG: senza data non si sa se la prova "
                    "e' piu' vecchia del codice" % voce["data"])
        return None

    def test_OGNI_VOCE_PORTA_I_QUATTRO_CAMPI_E_UN_METODO_AMMESSO(self):
        """LA GUARDIA. Il denominatore e' dichiarato: N voci, tutte esaminate, e chi ne
        aggiunge una senza campi diventa rosso LO STESSO GIORNO (D18 punto 4)."""
        voci = self._motore().EQUIVALENTI_DICHIARATI
        self.assertGreaterEqual(len(voci), 1,
                                "schedario vuoto: questa guardia non esaminerebbe nulla e "
                                "il suo verde non significherebbe niente")
        guasti = []
        for chiave in sorted(voci):
            motivo = self._guasto_della_voce(voci[chiave])
            if motivo:
                guasti.append("  %s · %s · %s -> %s\n      %s"
                              % (chiave[0], chiave[1] or "<fuori da ogni funzione>",
                                 chiave[3], chiave[4], motivo))
        self.assertEqual(
            [], guasti,
            "DENOMINATORE: %d voci dichiarate, tutte esaminate; %d non sono in regola. Ogni "
            "voce deve dichiarare metodo (%s), dominio, data e prova -- CAMPI, non prosa:\n%s"
            % (len(voci), len(guasti), "/".join(self.METODI), "\n".join(guasti)))

    def test_IL_LETTORE_RESTITUISCE_TESTO_perche_chi_lo_usa_lo_TAGLIA(self):
        """⛔ IL CONTRATTO CHE NON SI PUO' ROMPERE, provato ESEGUENDOLO.

        Non si guarda la forma del dizionario: si chiama `_e_equivalente` come lo chiama il
        giudice, su una voce VERA e sulle righe VERE del file, e si pretende un testo che si
        possa tagliare. Se qualcuno domani facesse restituire il dizionario intero, il giro
        di mutazione esploderebbe con un TypeError **dopo** aver gia' scritto il guasto
        dentro un file di produzione: il momento peggiore possibile per morire.
        """
        motore = self._motore()
        chiave = sorted(motore.EQUIVALENTI_DICHIARATI)[0]
        # ⛔ LA SORGENTE VERA, non il disco: durante una campagna il file e' rotto di
        # proposito e questa prova fallirebbe facendo contare il mutante come UCCISO. E' lo
        # stesso falso killer chiuso nel controllo 1, e qui era rimasto aperto.
        righe = _righe_dello_schedario(motore, chiave[0])
        numeri = [n for n, r in enumerate(righe, 1)
                  if r.strip() == chiave[2] and motore.funzione_di(righe, n) == chiave[1]]
        self.assertTrue(numeri,
                        "la voce %r non aggancia: questa prova non starebbe esercitando il "
                        "lettore su niente (e il controllo 1 e' gia' rosso)" % (chiave,))
        motivo = motore._e_equivalente(
            chiave[0], righe, {"riga": numeri[0], "vecchio": chiave[3], "nuovo": chiave[4]})
        self.assertIsInstance(motivo, str,
                              "il lettore restituisce %s invece di testo: i due consumatori "
                              "fanno motivo[:70] e motivo[:60] e morirebbero a meta' "
                              "campagna, a file di produzione gia' rotto"
                              % type(motivo).__name__)
        self.assertTrue(motivo.strip(),
                        "il lettore restituisce testo VUOTO: `if motivo:` sarebbe falso e il "
                        "mutante verrebbe provato lo stesso (direzione sicura, ma la voce "
                        "non varrebbe piu' niente e nessuno lo saprebbe)")
        # ⛔ E l'ingresso sbagliato non deve ESPLODERE: una voce lasciata in prosa non perdona
        # nulla (direzione sicura) invece di far morire il giro con un TypeError a meta'
        # campagna, cioe' a file di produzione gia' rotto.
        motore.EQUIVALENTI_DICHIARATI = dict(motore.EQUIVALENTI_DICHIARATI)
        motore.EQUIVALENTI_DICHIARATI[chiave] = "una voce nel vecchio formato, in prosa"
        self.assertIsNone(
            motore._e_equivalente(chiave[0], righe,
                                  {"riga": numeri[0], "vecchio": chiave[3],
                                   "nuovo": chiave[4]}),
            "una voce in PROSA fa esplodere il lettore invece di non perdonare niente: lo "
            "strumento avrebbe un modo di morire che prima non aveva, e morirebbe nel punto "
            "peggiore")


class TestLoSchedarioDegliEquivalenti_2b_L_IMPRONTA_FA_DECADERE(unittest.TestCase):
    """⛔ CONTROLLO 2b: SE IL CODICE SOTTO LA PROVA CAMBIA, LA VOCE DECADE DA SOLA.

    ORDINE DEL FONDATORE, 2026-08-24, ed e' la condizione con cui lo schedario e' stato
    riaperto per i sopravvissuti di `fase59`: *«ogni voce deve portare l'impronta esatta
    della riga a cui si riferisce: se quella riga cambia, la dichiarazione di equivalenza
    decade da sola e il mutante torna da uccidere»*.

    💡 IL BUCO CHE CHIUDE, ed e' quello che rende questo posto pericoloso. Una dimostrazione
    non parla mai della sola riga mutata: parla anche delle righe intorno. Il mutante di
    `costo_pagamento` e' equivalente **perche' venti righe sopra un 422 impedisce a `totale`
    di valere 0**. Togli quel 422 e la dimostrazione crolla -- ma la chiave dello schedario
    (file, funzione, testo della riga, vecchio, nuovo) resta IDENTICA, quindi il mutante
    continuerebbe a essere saltato per sempre, in silenzio, su un codice che nessuno ha piu'
    dimostrato. E' la cecita' permanente che questo schedario puo' produrre, e la chiave da
    sola non la ferma.

    ⛔ E SI PROVA NELLE DUE DIREZIONI: che le voci vere passino non dimostra niente da solo
    (`return True, ""` passerebbe uguale). Serve anche che una voce con un'ancora sparita, e
    una con l'impronta rifatta a mano, DECADANO.
    """

    @staticmethod
    def _motore():
        import importlib.util
        p = os.path.join(QUI, "collaudi", "mutazione_prodotto.py")
        spec = importlib.util.spec_from_file_location("_schedario_impronte", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_OGNI_VOCE_POGGIA_ANCORA_SUL_CODICE_CHE_HA_DIMOSTRATO(self):
        mp = self._motore()
        decadute = []
        for chiave, voce in mp.EQUIVALENTI_DICHIARATI.items():
            percorso = os.path.join(QUI, chiave[0])
            self.assertTrue(os.path.isfile(percorso),
                            "lo schedario nomina un file che non esiste: %s" % chiave[0])
            with io.open(percorso, encoding="utf-8") as f:
                righe = f.read().splitlines()
            ok, perche = mp.ancore_intatte(voce, righe)
            if not ok:
                decadute.append("%s · %s · %s -> %s"
                                % (chiave[0], chiave[1] or "(modulo)", chiave[2][:50], perche))
        self.assertEqual(
            [], decadute,
            "queste dichiarazioni di equivalenza NON poggiano piu' sul codice su cui sono "
            "state fatte. Vanno RIFATTE o TOLTE: finche' restano, quei punti non li guarda "
            "piu' nessuno.\n  " + "\n  ".join(decadute))

    def test_UN_ANCORA_SPARITA_FA_DECADERE_LA_VOCE(self):
        """La prima direzione: il codice cambia -> il mutante torna da uccidere."""
        mp = self._motore()
        voce = {"ancore": ["if guest <= 0:\nreturn 422"],
                "impronta": mp.impronta_di(["if guest <= 0:\nreturn 422"])}
        ok, _ = mp.ancore_intatte(voce, ["if guest <= 0:", "return 422"])
        self.assertTrue(ok, "una voce sana viene rifiutata: la guardia grida sempre")
        ok, perche = mp.ancore_intatte(voce, ["if guest < 0:", "return 422"])
        self.assertFalse(ok, "l'ancora e' cambiata e la voce e' rimasta in piedi: e' "
                             "esattamente la cecita' permanente che questa guardia esiste "
                             "per impedire")
        self.assertIn("non c'e' piu'", perche)

    def test_UN_IMPRONTA_RIFATTA_A_MANO_FA_DECADERE_LA_VOCE(self):
        """La seconda direzione: qualcuno allarga le ancore senza rifare la prova."""
        mp = self._motore()
        righe = ["if guest <= 0:", "return 422", "altro = 1"]
        voce = {"ancore": ["if guest <= 0:\nreturn 422"],
                "impronta": mp.impronta_di(["if guest <= 0:\nreturn 422"])}
        voce["ancore"] = ["if guest <= 0:\nreturn 422", "altro = 1"]   # allargate, non rifatte
        ok, perche = mp.ancore_intatte(voce, righe)
        self.assertFalse(ok, "le ancore sono state cambiate senza rifare l'impronta e la "
                             "voce e' rimasta valida")
        self.assertIn("impronta", perche)

    def test_UNA_VOCE_SENZA_ANCORE_NON_VALE(self):
        """Il formato vecchio non deve valere per omissione: senza impronta, niente sconto."""
        mp = self._motore()
        for voce in ({}, {"ancore": []}, {"ancore": "una stringa"},
                     {"ancore": ["x"], "impronta": None}):
            ok, _ = mp.ancore_intatte(voce, ["x"])
            self.assertFalse(ok, "voce accettata senza impronta valida: %r" % (voce,))

    def test_IL_LETTORE_RIFIUTA_LA_VOCE_SCADUTA_E_IL_MUTANTE_TORNA_DA_UCCIDERE(self):
        """⛔ COSTRUITO != COLLEGATO (#23). `ancore_intatte` puo' essere giusta e non
        essere chiamata da nessuno: qui si prova che e' `_e_equivalente` -- quello che il
        giro di mutazione interroga davvero -- a restituire None su una voce scaduta."""
        mp = self._motore()
        chiave, voce = next(iter(mp.EQUIVALENTI_DICHIARATI.items()))
        nome, _funz, riga, vecchio, nuovo = chiave
        with io.open(os.path.join(QUI, nome), encoding="utf-8") as f:
            righe = f.read().splitlines()
        numero = next(i + 1 for i, r in enumerate(righe) if r.strip() == riga)
        mutante = {"riga": numero, "vecchio": vecchio, "nuovo": nuovo}
        self.assertIsInstance(
            mp._e_equivalente(os.path.join(QUI, nome), righe, mutante), str,
            "sul codice VERO la voce non viene riconosciuta: la prova non misura niente")
        originale = dict(voce)
        try:
            mp.EQUIVALENTI_DICHIARATI[chiave] = dict(voce, impronta="0" * 64)
            self.assertIsNone(
                mp._e_equivalente(os.path.join(QUI, nome), righe, mutante),
                "con l'impronta rotta il lettore dichiara ANCORA equivalente: il mutante "
                "resterebbe saltato su una dimostrazione che non vale piu'")
        finally:
            mp.EQUIVALENTI_DICHIARATI[chiave] = originale


class TestLoSchedarioDegliEquivalenti_3_DOMINIO_MAGGIORE_DELLA_FIRMA(unittest.TestCase):
    """⛔ CONTROLLO 3 di 4: UNA PROVA VALE QUANTO IL MODELLO SU CUI E' FATTA.

    Questa e' la guardia che i tre errori di questi giorni chiedevano. Tutti e tre avevano
    LA STESSA FORMA, ed e' una forma controllabile a macchina:

        _cent(v: Any)  /  _n(v senza tipo)      la funzione accetta QUALUNQUE COSA
        prova: "tutti gli interi" (o z3)         il dominio della prova e' PIU' PICCOLO
        cosa mancava:                            le sottoclassi di int -> tipo restituito
                                                 diverso, e quindi un test che le distingue

    Anche quella dichiarata con z3: il risolutore ragiona sugli INTERI, la funzione accetta
    `Any`. Non ha sbagliato il risolutore -- gli era stata fatta la domanda sbagliata.

    LA REGOLA: se il `metodo` e' `esaustiva` o `z3` e la funzione ha anche UN SOLO argomento
    senza tipo o annotato `Any`, la prova non copre il dominio. Rosso.

    ⚠️ L'ESTRATTORE GUARDA ANCHE GLI ARGOMENTI DOPO L'ASTERISCO (`kwonlyargs`). La prima
    versione scritta il 2026-08-05 li saltava e mostrava «nessun argomento» per quattro
    funzioni di `fase177`, che li hanno tutti dopo l'asterisco: un estrattore cieco avrebbe
    dato il VERDE proprio dove serviva guardare. `self` e `cls` non contano: non sono
    ingressi, e contarli renderebbe rosso ogni metodo del progetto.

    ⛔ COSA NON ESAMINA (D18 punto 3), detto prima:
      · le voci con metodo `traccia`: li' la prova non e' un dominio ma un percorso, e
        giudicarla e' lavoro umano (resta la D19: una traccia che si appoggia a un'ALTRA
        funzione e' fragile, e le quattro voci da rileggere sono elencate in RIPRENDI_QUI);
      · le voci che agganciano codice FUORI da ogni funzione: non c'e' una firma da leggere;
      · i tipi troppo larghi diversi da `Any` (per esempio `object`): la regola dichiarata
        e' «senza tipo o `Any`», e allargarla di nascosto sarebbe un'altra regola;
      · il CONTENUTO della prova, che questa guardia non sa e non deve giudicare.
    """

    ESIGENTI = ("esaustiva", "z3")

    @staticmethod
    def _motore():
        import importlib.util
        p = os.path.join(QUI, "collaudi", "mutazione_prodotto.py")
        spec = importlib.util.spec_from_file_location("_schedario_dominio", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @classmethod
    def _e_any(cls, annotazione):
        """`Any` scritto in uno qualunque dei modi che lo rendono DAVVERO `Any`: `Any`,
        `typing.Any`, la stringa `"Any"`, e `Optional[Any]` / `Union[..., Any]` -- che sono
        `Any` con un nome piu' lungo.

        ⛔ NON conta `Dict[str, Any]` ne' `List[Any]`: li' l'argomento e' vincolato a essere
        un dizionario o una lista, quindi il dominio NON e' «qualunque cosa» e chiamarlo tale
        sarebbe un falso allarme -- il difetto che vale quanto un allarme mancato.
        """
        import ast
        if annotazione is None:
            return False
        if isinstance(annotazione, ast.Name):
            return annotazione.id == "Any"
        if isinstance(annotazione, ast.Attribute):
            return annotazione.attr == "Any"
        if isinstance(annotazione, ast.Constant) and isinstance(annotazione.value, str):
            return annotazione.value.strip().strip("'\"") == "Any"
        if isinstance(annotazione, ast.Subscript):
            base = annotazione.value
            nome = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
            if nome not in ("Optional", "Union"):
                return False
            dentro = annotazione.slice
            if dentro.__class__.__name__ == "Index":        # Python <= 3.8
                dentro = dentro.value
            pezzi = dentro.elts if isinstance(dentro, ast.Tuple) else [dentro]
            return any(cls._e_any(p) for p in pezzi)
        return False

    @classmethod
    def _scoperti(cls, motore, chiave):
        """(applicabile, elenco degli argomenti senza tipo o `Any`, nota).

        `applicabile` e' False quando non c'e' una firma da leggere: codice fuori da ogni
        funzione, o voce che non aggancia (di quella si occupa il controllo 1).
        """
        import ast
        nome_file, funzione, testo = chiave[0], chiave[1], chiave[2]
        if not funzione:
            return False, [], "aggancia codice fuori da ogni funzione: nessuna firma"
        righe = _righe_dello_schedario(motore, nome_file)
        if righe is None:
            return False, [], "il file non esiste piu' (lo dice il controllo 1)"
        numeri = [n for n, r in enumerate(righe, 1)
                  if r.strip() == testo and motore.funzione_di(righe, n) == funzione]
        if not numeri:
            return False, [], "la voce non aggancia (lo dice il controllo 1)"
        albero = ast.parse("\n".join(righe))
        # ⛔ TUTTE le righe che combaciano, non solo la prima: la voce le perdona TUTTE, e
        # leggere la firma di una sola sarebbe di nuovo una dichiarazione che vale oltre il
        # punto dove e' stata guardata -- la famiglia del difetto del 2026-08-01.
        scoperti, firme = [], []
        for numero in numeri:
            dentro = [n for n in ast.walk(albero)
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and n.lineno <= numero <= n.end_lineno]
            if not dentro:
                continue
            nodo = sorted(dentro, key=lambda n: n.lineno)[-1]
            a = nodo.args
            tutti = list(getattr(a, "posonlyargs", [])) + list(a.args) + list(a.kwonlyargs)
            for extra in (a.vararg, a.kwarg):
                if extra is not None:
                    tutti.append(extra)
            firme.append("%s(%s)" % (nodo.name, ", ".join(x.arg for x in tutti)))
            for x in tutti:
                if (x.arg not in ("self", "cls")
                        and (x.annotation is None or cls._e_any(x.annotation))
                        and x.arg not in scoperti):
                    scoperti.append(x.arg)
        if not firme:
            return False, [], "nessuna funzione contiene la riga"
        return True, scoperti, " · ".join(sorted(set(firme)))

    @classmethod
    def _violazione(cls, motore, chiave, voce):
        """(stato, motivo), con stato in: `non_si_applica` · `saltata` · `in_regola` ·
        `violazione`.

        ⛔ `saltata` ESISTE APPOSTA (D18 punto 3). La prima versione restituiva «in regola»
        anche quando non c'era nessuna firma da leggere, e il messaggio diceva «tutte
        esaminate»: una voce saltata in silenzio sembra identica a una voce sana, ed e' il
        taglio silenzioso che questo progetto vieta dentro gli strumenti che misurano.
        """
        if not isinstance(voce, dict) or voce.get("metodo") not in cls.ESIGENTI:
            return "non_si_applica", None
        applicabile, scoperti, nota = cls._scoperti(motore, chiave)
        if not applicabile:
            return "saltata", nota
        if not scoperti:
            return "in_regola", None
        return "violazione", (
            "metodo %r su dominio %r, ma la firma %s accetta QUALUNQUE COSA in %r: la prova "
            "e' fatta su un dominio PIU' PICCOLO di quello che la funzione accetta, quindi "
            "non copre i casi che stanno fuori dal modello (per esempio una SOTTOCLASSE di "
            "int)" % (voce.get("metodo"), voce.get("dominio", "")[:60], nota, scoperti))

    def test_IL_CONTROLLO_SA_DIRE_DI_NO_e_VEDE_DOPO_L_ASTERISCO(self):
        """⛔ D18 punti 1 e 2, piu' la trappola dichiarata nel piano.

        Quattro casi su una cavia usa-e-getta dove la verita' e' nota per costruzione:
        firma tipata -> tace · firma senza tipo -> grida · argomento `Any` DOPO l'asterisco
        (e `self` davanti) -> grida lo stesso, perche' e' esattamente il punto in cui la
        prima versione dell'estrattore era cieca · metodo `traccia` -> non si applica.
        """
        import io
        motore = self._motore()
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        with io.open(os.path.join(d, "cavia_firme.py"), "w",
                     encoding="utf-8", newline="\n") as f:
            f.write("from typing import Any, Dict, Optional\n"
                    "\n"
                    "\n"
                    "def tipata(v: int):\n"
                    "    if v < 0:\n"
                    "        return 0\n"
                    "    return v\n"
                    "\n"
                    "\n"
                    "def senza_tipo(v):\n"
                    "    if v < 1:\n"
                    "        return 0\n"
                    "    return v\n"
                    "\n"
                    "\n"
                    "def travestito(v: Optional[Any]):\n"
                    "    if v < 3:\n"
                    "        return 0\n"
                    "    return v\n"
                    "\n"
                    "\n"
                    "def vincolato(v: Dict[str, Any]):\n"
                    "    if len(v) < 4:\n"
                    "        return 0\n"
                    "    return v\n"
                    "\n"
                    "\n"
                    "class Cassa:\n"
                    "    def dopo_asterisco(self, *, quanto: Any = None):\n"
                    "        if quanto < 2:\n"
                    "            return 0\n"
                    "        return quanto\n")
        motore.REPO = d
        z3 = {"metodo": "z3", "dominio": "gli interi", "data": "2026-08-05", "prova": "x"}
        esa = {"metodo": "esaustiva", "dominio": "gli interi", "data": "2026-08-05",
               "prova": "x"}
        tra = {"metodo": "traccia", "dominio": "un percorso", "data": "2026-08-05",
               "prova": "x"}

        buona = ("cavia_firme.py", "tipata", "if v < 0:", "<", "<=")
        self.assertEqual(("in_regola", None), self._violazione(motore, buona, esa),
                         "accusa una firma TUTTA TIPATA: falso allarme, e un falso allarme "
                         "insegna a ignorare i rossi")

        nuda = ("cavia_firme.py", "senza_tipo", "if v < 1:", "<", "<=")
        stato, motivo = self._violazione(motore, nuda, esa)
        self.assertEqual("violazione", stato,
                         "non vede un argomento SENZA TIPO: e' il caso di `_n` in fase100 "
                         "(DAC7), uno dei tre errori veri")
        self.assertIn("'v'", motivo)

        stella = ("cavia_firme.py", "dopo_asterisco", "if quanto < 2:", "<", "<=")
        stato, motivo = self._violazione(motore, stella, z3)
        self.assertEqual("violazione", stato,
                         "NON VEDE GLI ARGOMENTI DOPO L'ASTERISCO: e' la trappola dichiarata "
                         "nel piano, e quattro funzioni di fase177 hanno tutti gli argomenti "
                         "li'")
        self.assertIn("'quanto'", motivo)
        self.assertNotIn("'self'", motivo,
                         "conta `self` fra gli ingressi: cosi' ogni metodo del progetto "
                         "diventerebbe rosso, e un allarme sempre acceso viene spento")

        # `Optional[Any]` E' `Any` con un nome piu' lungo, e va visto...
        travestito = ("cavia_firme.py", "travestito", "if v < 3:", "<", "<=")
        stato, motivo = self._violazione(motore, travestito, esa)
        self.assertEqual("violazione", stato,
                         "`Optional[Any]` non viene riconosciuto: e' `Any`, e il limite "
                         "dichiarato («i tipi larghi DIVERSI da Any») non lo copre -- sarebbe "
                         "un buco, non una scelta")

        # ...ma `Dict[str, Any]` NO: li' l'argomento e' vincolato a essere un dizionario.
        vincolato = ("cavia_firme.py", "vincolato", "if len(v) < 4:", "<", "<=")
        self.assertEqual(("in_regola", None), self._violazione(motore, vincolato, esa),
                         "accusa `Dict[str, Any]`: il dominio NON e' qualunque cosa, e "
                         "gridare qui sarebbe un falso allarme")

        self.assertEqual(("non_si_applica", None), self._violazione(motore, nuda, tra),
                         "applica la regola anche al metodo `traccia`, che non parla di "
                         "domini ma di percorsi: sarebbe un'altra regola, non dichiarata")

    # Le voci `traccia` che stanno su una funzione con un argomento senza tipo o `Any`. NON
    # sono approvate: sono un DEBITO DICHIARATO. Il numero e' inchiodato perche' la via piu'
    # comoda per aggirare il controllo 3 non e' allargare l'insieme dei metodi (quello lo
    # blocca il controllo 4) ma scrivere `traccia` al posto di `esaustiva`: la dimostrazione
    # tolta il 2026-08-05 da `_n` era LETTERALMENTE una traccia, e chi la riscrivesse in buona
    # fede la classificherebbe cosi' uscendo dal controllo senza accorgersene.
    # ⛔ 5 -> 12 il 2026-08-24, e il numero si alza SOLO scrivendo qui perche'. Le 7 nuove
    #    sono i sopravvissuti di `fase59_concierge` (B5): `quota(self, richiesta)` prende un
    #    dizionario JSON dell'ospite e `_sconto_credito(..., token, ...)` un token qualunque,
    #    quindi la firma e' larga per costruzione e il controllo 3 non le puo' esaminare.
    # ⚠️ MA NON SONO LO STESSO DEBITO DELLE 5 DI fase177. Quelle si appoggiano al
    #    comportamento di un'ALTRA funzione (cio' che la D19 vieta) e restano da rileggere.
    #    Queste 7 tracciano una variabile LOCALE dal punto in cui nasce a quello in cui si
    #    usa, dentro la stessa funzione, e ognuna porta l'IMPRONTA del codice che ha
    #    dimostrato: se quel codice cambia, la voce decade da sola (controllo 2b). E' la
    #    differenza fra un debito e una dichiarazione con una scadenza automatica.
    TRACCE_SU_FIRMA_LARGA = 12

    def test_LA_SCAPPATOIA_DEL_METODO_TRACCIA_E_CONTATA_E_INCHIODATA(self):
        """⛔ IL BUCO CHE RESTA, misurato invece che raccontato (D18 punto 3 + punto 4).

        Il controllo 3 si applica solo a `esaustiva` e `z3`, perche' una `traccia` non parla
        di domini ma di percorsi: e' la regola dichiarata, e allargarla di nascosto sarebbe
        un'altra regola. Ma il `metodo` lo dichiara chi scrive la voce, e nessuno lo verifica
        contro il testo della prova: scrivere `traccia` DISARMA il controllo.

        Qui quelle voci si contano, e il numero sta in `TRACCE_SU_FIRMA_LARGA` qui sopra.
        Oggi sono tutte su `fase177` con l'argomento `payout` senza tipo, e sono le stesse che
        `RIPRENDI_QUI.md` elenca gia' come «da rileggere» perche' la loro traccia si appoggia
        al comportamento di un'ALTRA funzione -- cio' che la D19 vieta. Non sono approvate:
        sono un debito con un numero sopra.

        Se qualcuno ne aggiunge una in piu' -- per esempio riscrivendo come `traccia` una
        dimostrazione appena tolta -- questo diventa rosso LO STESSO GIORNO. E se il debito
        viene pagato, il numero scende e va aggiornato qui: in quella direzione il rosso e'
        una buona notizia.
        """
        motore = self._motore()
        voci = motore.EQUIVALENTI_DICHIARATI
        larghe = []
        for chiave in sorted(voci):
            voce = voci[chiave]
            if not isinstance(voce, dict) or voce.get("metodo") != "traccia":
                continue
            applicabile, scoperti, nota = self._scoperti(motore, chiave)
            if applicabile and scoperti:
                larghe.append("  %s · %s · %s -> %s\n      firma %s, scoperti %r"
                              % (chiave[0], chiave[1], chiave[3], chiave[4], nota, scoperti))
        self.assertEqual(
            self.TRACCE_SU_FIRMA_LARGA, len(larghe),
            "il numero di voci `traccia` su una firma che accetta qualunque cosa e' passato "
            "da %d a %d. IN SU: qualcuno ha aggiunto una dichiarazione che il controllo 3 non "
            "guarda -- e' la scappatoia, va guardata a mano. IN GIU': il debito e' stato "
            "pagato, si aggiorna il numero qui e si scrive perche' nel registro. Mai per far "
            "tornare il verde.\n%s"
            % (self.TRACCE_SU_FIRMA_LARGA, len(larghe), "\n".join(larghe) or "  (nessuna)"))

    def test_NESSUNA_PROVA_ESAUSTIVA_O_Z3_STA_SU_UN_DOMINIO_TROPPO_PICCOLO(self):
        """LA GUARDIA, sui dati veri. Il denominatore e' dichiarato: quante voci esigenti
        ci sono, e sono TUTTE esaminate."""
        motore = self._motore()
        voci = motore.EQUIVALENTI_DICHIARATI
        esigenti = [k for k, v in voci.items()
                    if isinstance(v, dict) and v.get("metodo") in self.ESIGENTI]
        self.assertGreaterEqual(len(esigenti), 1,
                                "nessuna voce dichiara una prova esaustiva o z3: o lo "
                                "schedario e' cambiato forma, o questa guardia sta "
                                "esaminando il vuoto e il suo verde non vale niente")
        guasti, saltate = [], []
        for chiave in sorted(esigenti):
            stato, motivo = self._violazione(motore, chiave, voci[chiave])
            etichetta = "  %s · %s · %s -> %s\n      %s" % (chiave[0], chiave[1], chiave[3],
                                                            chiave[4], motivo)
            if stato == "violazione":
                guasti.append(etichetta)
            elif stato == "saltata":
                saltate.append(etichetta)
        # ⛔ LE SALTATE SI DICHIARANO ANCHE QUANDO NON SONO UN ERRORE: «tutte esaminate» detto
        # mentre qualcuna e' stata saltata e' esattamente il taglio silenzioso della D18
        # punto 3, e sarebbe qui dentro la guardia scritta per impedirlo.
        self.assertEqual(
            [], guasti,
            "DENOMINATORE: %d voci su %d dichiarano una prova esaustiva o z3; %d ESAMINATE, "
            "%d SALTATE (senza una firma da leggere), %d stanno su un dominio piu' piccolo "
            "della firma. Una dimostrazione formale vale quanto il modello su cui e' "
            "fatta.\nVIOLAZIONI:\n%s\nSALTATE (dichiarate, non esaminate):\n%s"
            % (len(esigenti), len(voci), len(esigenti) - len(saltate), len(saltate),
               len(guasti), "\n".join(guasti) or "  (nessuna)",
               "\n".join(saltate) or "  (nessuna)"))


class TestLoSchedarioDegliEquivalenti_4_NIENTE_FRASI_AL_POSTO_DI_UNA_PROVA(unittest.TestCase):
    """⛔ CONTROLLO 4 di 4: «NON E' RAGGIUNGIBILE» NON E' UNA DIMOSTRAZIONE (divieto B6, D19).

    Il divieto B6 dice che o c'e' una dimostrazione, o quel mutante resta un sopravvissuto; e
    la D19 vieta esplicitamente la motivazione «oggi non si raggiunge», perche' e' una
    conclusione con una premessa che sta in un'ALTRA funzione e puo' cadere in silenzio.

    ⛔ COME E' FATTO QUESTO CONTROLLO, ed e' la parte che conta.
    NON cerca parole nel testo libero. Il 2026-08-05 un controllo a parole chiave scritto al
    volo ha accusato a torto NOVE dichiarazioni serie -- perche' una prova onesta CITA le
    frasi vietate per spiegare perche' NON si sta appoggiando a loro (la voce di `fase184` ne
    e' l'esempio: dice «NON e' un "oggi non si raggiunge" alla D19»). Un controllo debole con
    verdetto forte e' peggio di nessun controllo.

    Guarda invece il campo `metodo`, che e' un insieme CHIUSO di tre valori. Una motivazione
    del tipo «non e' raggiungibile» non ha dove entrare: non e' un metodo, e non lo diventa.
    E la sola via per farcela entrare -- allargare l'insieme -- e' proprio cio' che il primo
    test qui sotto rende rumoroso. E' la D18 punto 4 applicata a se stessa: il controllo e' a
    sua volta sotto guardia, e allargarlo di nascosto diventa rosso lo stesso giorno.

    ⛔ COSA NON FA (D18 punto 3): non giudica se una `traccia` sia una traccia onesta. Una
    traccia che si appoggia al comportamento di un'ALTRA funzione e' fragile per la D19, e
    riconoscerlo e' lavoro umano: le quattro voci da rileggere sono elencate in
    `RIPRENDI_QUI.md`, non nascoste qui dentro.
    """

    VIETATI = ("non e' raggiungibile", "non e' osservabile", "non capita mai",
               "e' evidente", "ovvio")

    @staticmethod
    def _motore():
        import importlib.util
        p = os.path.join(QUI, "collaudi", "mutazione_prodotto.py")
        spec = importlib.util.spec_from_file_location("_schedario_frasi", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_L_INSIEME_DEI_METODI_E_CHIUSO_E_NON_SI_ALLARGA_DI_NASCOSTO(self):
        """⛔ LA GUARDIA SULLA GUARDIA (D18 punto 4).

        La via piu' comoda per far passare una voce che non ha una dimostrazione non e'
        scrivere una prova falsa: e' aggiungere un valore all'elenco dei metodi ammessi. Una
        riga, e da quel momento «non e' raggiungibile» sarebbe un metodo. Qui l'elenco e'
        inchiodato: allargarlo resta possibile -- e a volte sara' giusto -- ma diventa un
        atto DELIBERATO e VISIBILE, non una riga che passa in mezzo a un'altra modifica.
        """
        atteso = ("esaustiva", "traccia", "z3")
        self.assertEqual(
            atteso, TestLoSchedarioDegliEquivalenti_2_CAMPI_STRUTTURATI.METODI,
            "l'elenco dei metodi ammessi e' cambiato. Se e' voluto, si cambia ANCHE questa "
            "riga e si scrive perche' nel registro d'ingegneria: un metodo nuovo e' un modo "
            "nuovo di perdonare un mutante per sempre. Se non e' voluto, e' il buco: "
            "atteso %r, trovato %r"
            % (atteso, TestLoSchedarioDegliEquivalenti_2_CAMPI_STRUTTURATI.METODI))

    def test_UNA_FRASE_AL_POSTO_DI_UN_METODO_VIENE_RIFIUTATA(self):
        """LE DUE DIREZIONI, sulla regola vera (non su una copia): le frasi vietate messe nel
        campo `metodo` vengono respinte una per una, e una voce onesta passa."""
        regola = TestLoSchedarioDegliEquivalenti_2_CAMPI_STRUTTURATI._guasto_della_voce
        _ancore = ["if x <= 0:\nreturn 0"]
        _impronta = TestLoSchedarioDegliEquivalenti_2b_L_IMPRONTA_FA_DECADERE._motore(
        ).impronta_di(_ancore)
        for frase in self.VIETATI:
            voce = {"ancore": _ancore, "impronta": _impronta,
                    "metodo": frase, "dominio": "tutto", "data": "2026-08-05",
                    "prova": "sembra una spiegazione e non e' una dimostrazione"}
            motivo = regola(voce)
            self.assertIsNotNone(motivo,
                                 "%r passa come metodo di dimostrazione: e' esattamente cio' "
                                 "che il divieto B6 vieta" % frase)
            self.assertIn("B6", motivo)
        buona = {"ancore": _ancore, "impronta": _impronta,
                 "metodo": "traccia", "dominio": "il caso `x == 0`", "data": "2026-08-05",
                 "prova": "seguito il codice fino allo stato finale: identico."}
        self.assertIsNone(regola(buona),
                          "respinge una voce ONESTA: un falso allarme qui insegna a "
                          "ignorare i rossi, ed e' un difetto quanto un allarme mancato")

    def test_NESSUNA_VOCE_VERA_SI_GIUSTIFICA_CON_UNA_FRASE(self):
        """LA GUARDIA SUI DATI VERI. Oggi e' verde perche' il controllo 2 tiene chiuso
        l'insieme dei metodi; diventerebbe rossa il giorno in cui una voce ci provasse, ed e'
        per quel giorno che esiste. Il denominatore e' dichiarato: tutte le voci, nessuna
        esclusa."""
        voci = self._motore().EQUIVALENTI_DICHIARATI
        self.assertGreaterEqual(len(voci), 1, "schedario vuoto: non esaminerebbe nulla")
        colpevoli = []
        for chiave in sorted(voci):
            voce = voci[chiave]
            metodo = voce.get("metodo", "") if isinstance(voce, dict) else str(voce)
            if metodo not in TestLoSchedarioDegliEquivalenti_2_CAMPI_STRUTTURATI.METODI:
                colpevoli.append("  %s · %s · %s -> %s\n      metodo dichiarato: %r"
                                 % (chiave[0], chiave[1] or "<fuori da ogni funzione>",
                                    chiave[3], chiave[4], metodo[:80]))
        self.assertEqual(
            [], colpevoli,
            "DENOMINATORE: %d voci dichiarate, tutte esaminate; %d si giustificano con "
            "qualcosa che non e' un metodo di dimostrazione. O c'e' una dimostrazione, o quel "
            "mutante resta un SOPRAVVISSUTO (divieto B6):\n%s"
            % (len(voci), len(colpevoli), "\n".join(colpevoli)))


class TestLoSchedarioDegliEquivalenti_5_UNA_PROVA_PERDONA_UN_PUNTO_SOLO(unittest.TestCase):
    """⛔ CONTROLLO 5: UNA VOCE NON PUO' SPEGNERE DUE PUNTI CON UNA PROVA SOLA.

    E' la stessa famiglia del difetto vero corretto il 2026-08-01 — una dichiarazione che si
    estende OLTRE il punto dove e' stata dimostrata — ma un passo piu' in fondo. Allora la
    chiave non portava il nome della FUNZIONE, e `if residuo <= 0:` dichiarata in un posto
    rendeva cieco anche l'altro. Oggi la chiave non porta la COLONNA: se la stessa riga
    contiene lo stesso operatore **due volte**, una prova sola li perdona **tutti e due**.

    DIFETTO VERO, TROVATO IL 2026-08-05 e non dedotto. In `fase177_financial_controller`:
        `if tipo not in ("credito", "debito") or imp <= 0 or not (riferimento and soggetto...`
    ci sono DUE `or`. La voce dichiarata ragionava sul primo («cambia solo che un `tipo`
    sconosciuto non viene piu' fermato qui»), e intanto spegneva anche il secondo. Che NON e'
    equivalente: tabella di verita' su tutte e 8 le combinazioni, due differiscono --
        tipo valido · importo > 0 · CAMPI OBBLIGATORI MANCANTI -> il sano rifiuta, il mutante
        crea la nota (causale vuota) e scrive una riga di GIORNALE;
        tipo valido · IMPORTO <= 0 · campi presenti            -> il sano rifiuta, il mutante prosegue.
    E' il modulo dei SOLDI, e quel punto era spento dal 2026-08-02.

    LA REGOLA: si contano i mutanti VERI che il generatore produce, si calcola la chiave di
    ognuno come fa `_e_equivalente`, e si pretende che nessuna voce ne perdoni piu' di uno.
    Non e' un ragionamento: e' un conteggio sui punti veri di quei file.

    ⛔ COSA NON FA (D18 punto 3): non pretende che ogni voce ne perdoni ALMENO uno. Una voce
    che oggi non aggancia nessun mutante e' inerte, non pericolosa, e il generatore ha
    rinunce dichiarate che cambiano nel tempo: farne un rosso sarebbe un falso allarme in
    attesa. Il numero delle voci inerti viene comunque DETTO nel messaggio.
    """

    @staticmethod
    def _motore():
        import importlib.util
        p = os.path.join(QUI, "collaudi", "mutazione_prodotto.py")
        spec = importlib.util.spec_from_file_location("_schedario_conteggio", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @staticmethod
    def _quanti_perdona(motore):
        """{chiave dello schedario: quanti mutanti VERI perdona}. Conta solo cio' che il
        generatore produce davvero, non cio' che si immagina."""
        import collections
        conta = collections.Counter()
        for nome in sorted({k[0] for k in motore.EQUIVALENTI_DICHIARATI}):
            righe = _righe_dello_schedario(motore, nome)
            if righe is None:
                continue                      # file sparito: lo dice il controllo 1
            mutanti, _saltati = motore.genera_mutanti("\n".join(righe))
            for mu in mutanti:
                n = mu["riga"]
                riga = righe[n - 1].strip() if n <= len(righe) else ""
                chiave = (nome, motore.funzione_di(righe, n), riga,
                          mu["vecchio"], mu["nuovo"])
                if chiave in motore.EQUIVALENTI_DICHIARATI:
                    conta[chiave] += 1
        return conta

    def test_IL_CONTEGGIO_SA_VEDERE_DUE_PUNTI_SOTTO_UNA_PROVA_SOLA(self):
        """⛔ D18 punti 1 e 2: prima si prova che il contatore sa contare fino a due.

        Un contatore che dicesse sempre «uno» darebbe il verde su qualunque schedario. Qui la
        verita' e' nota per costruzione: una riga con UN operatore e una riga con lo STESSO
        operatore DUE VOLTE, in una cavia usa-e-getta fuori dal progetto.
        """
        import io
        motore = self._motore()
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        with io.open(os.path.join(d, "cavia_conteggio.py"), "w",
                     encoding="utf-8", newline="\n") as f:
            f.write("def una_volta(a, b):\n"
                    "    if a or b:\n"
                    "        return 1\n"
                    "    return 0\n"
                    "\n"
                    "\n"
                    "def due_volte(a, b, c):\n"
                    "    if a or b or c:\n"
                    "        return 1\n"
                    "    return 0\n")
        motore.REPO = d
        sola = ("cavia_conteggio.py", "una_volta", "if a or b:", "or", "and")
        doppia = ("cavia_conteggio.py", "due_volte", "if a or b or c:", "or", "and")
        finta = {"metodo": "traccia", "dominio": "x", "data": "2026-08-05", "prova": "x"}
        motore.EQUIVALENTI_DICHIARATI = {sola: finta, doppia: finta}

        conta = self._quanti_perdona(motore)
        self.assertEqual(1, conta.get(sola),
                         "una riga con UN solo operatore deve contare 1: se conta di piu' il "
                         "controllo accuserebbe a torto ogni voce onesta")
        self.assertEqual(2, conta.get(doppia),
                         "una riga con lo STESSO operatore DUE VOLTE deve contare 2: se conta "
                         "1, il controllo non vede proprio il difetto per cui esiste, e una "
                         "prova sola continuerebbe a spegnere due punti")

    def test_NESSUNA_VOCE_PERDONA_PIU_DI_UN_MUTANTE(self):
        """LA GUARDIA, sui punti veri generati dal giudice. Denominatore dichiarato: quante
        voci ci sono, quante agganciano almeno un mutante, quante ne perdonano piu' di uno."""
        motore = self._motore()
        voci = motore.EQUIVALENTI_DICHIARATI
        conta = self._quanti_perdona(motore)
        inerti = len(voci) - len(conta)
        troppe = []
        for chiave, n in sorted(conta.items()):
            if n > 1:
                troppe.append("  %s · %s · %r · %s -> %s\n      una prova sola spegne %d "
                              "punti diversi sulla stessa riga"
                              % (chiave[0], chiave[1] or "<fuori da ogni funzione>",
                                 chiave[2][:70], chiave[3], chiave[4], n))
        self.assertEqual(
            [], troppe,
            "DENOMINATORE: %d voci dichiarate, %d agganciano almeno un mutante vero, %d sono "
            "inerti (dichiarato, non e' un errore). Queste %d perdonano PIU' DI UN PUNTO con "
            "UNA sola dimostrazione: la chiave non porta la colonna, quindi lo stesso "
            "operatore ripetuto sulla stessa riga viene spento tutto insieme -- e la prova ne "
            "descrive uno solo. E' la stessa famiglia del difetto del 2026-08-01, un passo "
            "piu' in fondo:\n%s"
            % (len(voci), len(conta), inerti, len(troppe), "\n".join(troppe)))


class TestIlCronometroNonPuoMENTIRE(unittest.TestCase):
    """⛔ `collaudi/cronometro_suite.py` — LA PRIMA GUARDIA NON E' SUI TEMPI.

    Quello strumento esiste per accorgersi che la macchina rallenta: il 2026-08-05 una guardia
    nuova ha piu' che raddoppiato la CI (da ~10 a 23m42s) e **nessun controllo l'ha detto** --
    l'ha notato il fondatore leggendo una tabella su GitHub il giorno dopo.

    Ma se un domani quel cronometro prendesse il posto di `python -m unittest discover` nel job
    che fa da cancello principale, un suo difetto costerebbe molto piu' della lentezza: uscire
    **verde con test rossi dentro**, oppure eseguire **meno test** di quelli veri. Il cancello
    sembrerebbe chiuso e sarebbe aperto, e nessuno lo saprebbe.

    Per questo qui si prova, PRIMA di ogni cosa e nelle DUE direzioni:
      1. scopre ESATTAMENTE gli stessi test di `unittest discover` -- non uno di meno;
      2. esce **1** su una suite rossa e **0** su una verde -- provato eseguendolo davvero;
      3. il tetto sui tempi grida quando serve e TACE quando non serve;
      4. un rosso vince sempre sul tetto: prima si guarda il rosso.
    """

    SCRIPT = os.path.join(QUI, "collaudi", "cronometro_suite.py")

    def _cavia(self, nome, corpo):
        """Un modulo di test usa-e-getta, FUORI dal repository: si raggiunge con PYTHONPATH,
        cosi' la prova non lascia file dentro il progetto."""
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        with io.open(os.path.join(d, nome + ".py"), "w", encoding="utf-8", newline="\n") as f:
            f.write(corpo)
        return d

    def _esegui(self, cartella, argomenti):
        amb = dict(os.environ)
        amb["PYTHONPATH"] = cartella + os.pathsep + amb.get("PYTHONPATH", "")
        return subprocess.run([sys.executable, self.SCRIPT] + argomenti,
                              cwd=QUI, env=amb, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=300)

    def test_scopre_ESATTAMENTE_gli_stessi_test_di_unittest_discover(self):
        """⛔ LA PIU' IMPORTANTE. Un cronometro che ne esegue anche UNO di meno e' un cancello
        che sembra chiuso ed e' aperto: la suite direbbe «tutto verde» avendo saltato roba."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("_cronometro", self.SCRIPT)
        cro = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cro)
        # ⛔ SI CONFRONTANO GLI INSIEMI, NON I CONTEGGI. Due numeri uguali possono nascondere
        #    due insiemi diversi: un filtro che toglie un modulo da 40 prove mentre un altro
        #    ne raccoglie 40 fa tornare il conto e non esegue piu' niente di quello che
        #    contava. E' la stessa regola usata per dimostrare l'equivalenza delle strategie
        #    della rete («non lo stesso numero: lo stesso insieme»), che qui mancava proprio
        #    nella guardia dichiarata «LA PIU' IMPORTANTE» (revisione a contesto fresco,
        #    2026-08-06).
        # ⚠️ `carica([])` — con argv VUOTO: se leggesse `sys.argv` di questo processo, un giro
        #    lanciato con `--moduli` gli farebbe scoprire un sottoinsieme e questa guardia
        #    diventerebbe rossa per il motivo sbagliato.
        def _ids(suite):
            fuori = []
            for t in suite:
                if isinstance(t, unittest.TestSuite):
                    fuori.extend(_ids(t))
                else:
                    fuori.append(t.id())
            return fuori

        suo = sorted(_ids(cro.carica([])))
        vero = sorted(_ids(unittest.defaultTestLoader.discover(
            QUI, pattern="test_*.py", top_level_dir=QUI)))
        mancanti = sorted(set(vero) - set(suo))
        aggiunti = sorted(set(suo) - set(vero))
        self.assertEqual(
            ([], []), (mancanti[:10], aggiunti[:10]),
            "il cronometro NON esegue lo stesso insieme di `unittest discover`: %d test "
            "sparirebbero e %d comparirebbero dal nulla. Quelli che sparirebbero non li "
            "eseguirebbe piu' nessuno, e il verde della suite varrebbe di meno senza che si "
            "veda.\n  spariti: %r\n  comparsi: %r"
            % (len(mancanti), len(aggiunti), mancanti[:10], aggiunti[:10]))
        self.assertGreater(len(vero), 1000,
                           "la scoperta trova solo %d test: sta guardando la cartella "
                           "sbagliata, e questo confronto non proverebbe niente" % len(vero))

    def test_esce_UNO_su_una_suite_ROSSA_e_ZERO_su_una_VERDE(self):
        """Le due direzioni sul VERDETTO, eseguendo lo strumento vero: e' la proprieta' che
        rende accettabile metterlo sul percorso del cancello principale."""
        verde = self._cavia("zz_cavia_verde", "import unittest\n"
                                              "\n"
                                              "class T(unittest.TestCase):\n"
                                              "    def test_va_bene(self):\n"
                                              "        self.assertEqual(2, 1 + 1)\n")
        r = self._esegui(verde, ["--moduli", "zz_cavia_verde"])
        self.assertEqual(0, r.returncode,
                         "su una suite VERDE esce %d invece di 0: la CI sarebbe rossa sempre, "
                         "e un rosso permanente insegna a ignorare il rosso.\n%s"
                         % (r.returncode, (r.stdout + r.stderr)[-600:]))

        rossa = self._cavia("zz_cavia_rossa", "import unittest\n"
                                              "\n"
                                              "class T(unittest.TestCase):\n"
                                              "    def test_fallisce(self):\n"
                                              "        self.assertEqual(3, 1 + 1)\n")
        r = self._esegui(rossa, ["--moduli", "zz_cavia_rossa"])
        self.assertEqual(1, r.returncode,
                         "⛔ SU UNA SUITE ROSSA ESCE %d INVECE DI 1: il cancello principale "
                         "sarebbe MORTO -- verde con test rossi dentro, e nessuno lo "
                         "saprebbe.\n%s" % (r.returncode, (r.stdout + r.stderr)[-600:]))

    def test_ZERO_TEST_ESEGUITI_non_e_un_successo(self):
        """⛔ IL CANCELLO CHE SEMBRA CHIUSO ED E' APERTO.

        `unittest` considera **riuscita** una suite vuota: senza un controllo esplicito, uno
        strumento che non trova niente da eseguire esce **verde**. Trovato dalla revisione a
        contesto fresco il 2026-08-06: bastava `--moduli --tetto-secondi 30` (il valore
        dell'opzione seguente veniva letto come nome di modulo, l'elenco restava vuoto) per
        avere `Ran 0 tests ... OK` e **uscita 0**. E' esattamente lo scenario che la docstring
        di questa classe dichiara di scongiurare.
        E' anche la D18 punto 1: uno strumento che misura si FERMA invece di stampare un
        numero, quando non e' in condizione di misurare.
        """
        d = self._cavia("zz_cavia_vuota", "import unittest\n")
        r = self._esegui(d, ["--moduli", "--tetto-secondi", "30"])
        self.assertNotEqual(0, r.returncode,
                            "con ZERO test eseguiti esce 0: il cancello sembrerebbe chiuso ed "
                            "e' aperto.\n%s" % (r.stdout + r.stderr)[-500:])
        self.assertIn("ZERO TEST", (r.stdout + r.stderr).upper(),
                      "si ferma ma non dice PERCHE': chi legge non sa che non ha eseguito nulla")

    def test_un_OPZIONE_SCRITTA_MALE_non_spegne_l_allarme_in_silenzio(self):
        """`--tetto 30` invece di `--tetto-secondi 30` lasciava il tetto SPENTO senza dire
        niente: sembrava che avesse controllato e non aveva controllato nulla. Per uno
        strumento candidato a fare da cancello e' la stessa famiglia della suite vuota."""
        d = self._cavia("zz_cavia_ok", "import unittest\n"
                                       "\n"
                                       "class T(unittest.TestCase):\n"
                                       "    def test_ok(self):\n"
                                       "        pass\n")
        r = self._esegui(d, ["--moduli", "zz_cavia_ok", "--tetto", "30"])
        self.assertNotEqual(0, r.returncode,
                            "un'opzione sconosciuta viene ignorata e il giro esce verde: il "
                            "tetto resta spento e nessuno se ne accorge.\n%s" % r.stdout[-400:])
        self.assertIn("opzione sconosciuta", r.stdout + r.stderr)

    def test_il_tetto_GRIDA_quando_serve_e_TACE_quando_non_serve(self):
        """Un allarme provato in una direzione sola potrebbe gridare sempre -- e un allarme
        sempre acceso viene spento (regola ferrea 10).

        ⚠️ L'attesa e' di 0,2 s e non di 2: provare le due direzioni non richiede di essere
        lenti, e sei secondi di `sleep` dentro il lavoro la cui tesi e' «i test lenti vengono
        spenti» erano una contraddizione (revisione a contesto fresco, 2026-08-06)."""
        lenta = self._cavia("zz_cavia_lenta", "import time\n"
                                              "import unittest\n"
                                              "\n"
                                              "class T(unittest.TestCase):\n"
                                              "    def test_lento_ma_sano(self):\n"
                                              "        time.sleep(0.2)\n")
        r = self._esegui(lenta, ["--moduli", "zz_cavia_lenta", "--tetto-secondi", "0.05"])
        self.assertEqual(1, r.returncode,
                         "un test da 0,2 secondi non fa scattare il tetto di 0,05: il "
                         "cronometro non vede la lentezza che deve vedere.\n%s"
                         % r.stdout[-600:])
        self.assertIn("OLTRE IL TETTO", r.stdout,
                      "scatta ma non dice QUALE test e' lento: chi legge non sa dove guardare")
        self.assertIn("zz_cavia_lenta", r.stdout)

        r = self._esegui(lenta, ["--moduli", "zz_cavia_lenta", "--tetto-secondi", "5"])
        self.assertEqual(0, r.returncode,
                         "lo stesso test SANO fa scattare un tetto di 5 secondi: il tetto "
                         "griderebbe sempre, e un allarme sempre acceso viene tolto.\n%s"
                         % r.stdout[-600:])
        self.assertNotIn("OLTRE IL TETTO", r.stdout)

        # ...e senza tetto non deve gridare mai, che e' la condizione di oggi.
        r = self._esegui(lenta, ["--moduli", "zz_cavia_lenta"])
        self.assertEqual(0, r.returncode,
                         "senza `--tetto-secondi` impone un tetto lo stesso: una soglia scelta "
                         "prima di conoscere la varianza e' un falso allarme in attesa")

    def test_un_rosso_vince_SEMPRE_sul_tetto(self):
        """Un test lento su una suite rossa e' un problema minore: il verdetto non deve mai
        essere sostituito da quello sui tempi, ne' in un verso ne' nell'altro."""
        rossa = self._cavia("zz_cavia_rossa2", "import unittest\n"
                                               "\n"
                                               "class T(unittest.TestCase):\n"
                                               "    def test_fallisce(self):\n"
                                               "        self.assertTrue(False)\n")
        r = self._esegui(rossa, ["--moduli", "zz_cavia_rossa2", "--tetto-secondi", "999"])
        self.assertEqual(1, r.returncode,
                         "con un tetto larghissimo una suite ROSSA esce 0: il tetto ha "
                         "coperto il verdetto vero.\n%s" % (r.stdout + r.stderr)[-600:])

    def test_ogni_LENTO_DICHIARATO_porta_il_suo_MOTIVO(self):
        """L'elenco delle esenzioni e' il posto dove la lentezza si nasconde. Una voce senza
        motivo scritto e' un permesso a tempo indeterminato che nessuno rilegge."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("_cronometro_lenti", self.SCRIPT)
        cro = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cro)
        senza = [k for k, v in cro.LENTI_DICHIARATI.items()
                 if not isinstance(v, str) or len(v.strip()) < 30]
        self.assertEqual([], senza,
                         "queste esenzioni non portano un motivo scritto (o e' troppo corto "
                         "per esserlo): %r" % senza)
        # ⛔ E OGNI ESENZIONE DEVE PUNTARE A UN TEST CHE ESISTE DAVVERO. Il giorno che quel
        #    test viene rinominato, l'esenzione resterebbe li' per sempre senza che niente
        #    diventi rosso -- e l'elenco delle esenzioni e' il posto dove la lentezza si
        #    nasconde (revisione a contesto fresco, 2026-08-06).
        def _ids(suite):
            fuori = []
            for t in suite:
                if isinstance(t, unittest.TestSuite):
                    fuori.extend(_ids(t))
                else:
                    fuori.append(t.id())
            return fuori

        veri = set(_ids(cro.carica([])))
        fantasmi = sorted(k for k in cro.LENTI_DICHIARATI if k not in veri)
        self.assertEqual([], fantasmi,
                         "queste esenzioni puntano a test che NON ESISTONO piu': sono permessi "
                         "a tempo indeterminato che nessuno rilegge, e coprirebbero un test "
                         "nuovo che prendesse lo stesso nome. %r" % fantasmi)


class TestIlBancoDiProvaMisuraLaStessaMacchinaDellaProduzione(unittest.TestCase):
    """⛔ Un banco con un ambiente diverso non prova il prodotto: prova un'ALTRA macchina.

    MISURATO IL 2026-08-08, non ipotizzato. `collaudi/banco_prova.sh` accendeva la copia
    di prova con `--env-file .env.casavip` e basta. La produzione riceve altre DICIOTTO
    variabili dal blocco `environment:` di `docker-compose.casavip.yml`, e QUATTORDICI di
    quelle dicono DOVE salvare i database. Senza, `main_casavip.py:105` ripiega sul
    percorso RELATIVO `data/pendenti.db`, cioe' dentro il contenitore invece che nel
    volume montato: 13 database -- fra cui `pendenti`, `payout`, `garanzia`,
    `accettazioni` e le marche temporali (valore legale) -- finivano in `/app/data`, che
    muore con il contenitore.

    Il compose stesso lo dice, in un commento scritto dopo che era gia' successo:
        DB_MARCHE: /data/marche.db  # senza questa riga i token finirebbero in /app/data
    Il banco riproduceva ESATTAMENTE il guasto che quel file esiste per impedire.

    QUANTO E' COSTATO. La «prova generale» del 2026-08-08 ha dichiarato «la catena dei
    soldi REGGE» e ha concluso che la cancellazione non lasciava traccia del rimborso.
    Rimisurato la sera stessa su un giro da 15 prenotazioni: la traccia C'ERA -- 6
    pendenti su 6 marcati `rimborsato`, 6 payout su 6 `trattenuto`, 6 tasse su 6
    stornate -- ma stava in `/app/data/pendenti.db`, che nessuno guardava, e che
    `docker rm -f` aveva cancellato davvero. Una diagnosi intera sbagliata, e un difetto
    scritto nel passaggio di consegne che non era quello vero.

    D18: uno strumento che MISURA deve avere un controllo meccanico che gli impedisca di
    barare. Quel controllo sta in `collaudi/fedelta_banco.py` -- in Python e NON dentro
    lo script di shell -- proprio perche' cosi' lo si puo' provare nelle DUE direzioni
    da qui. Un controllo che nessuno puo' vedere fallire non e' un controllo.

    ⛔ COSA QUESTA GUARDIA NON FA, dichiarato (D18 punto 3):
      · NON accende un banco e NON parla con docker: la suite gira senza rete, senza
        server e senza chiavi. Prova il GIUDIZIO (Python puro) nelle due direzioni, e
        pretende che lo script lo CHIAMI e si FERMI sul verdetto negativo.
      · Che qualcuno esegua davvero lo script, questo non lo dimostra -- come le sue
        sorelle sul passaggio di consegne. E' il suo limite, ed e' scritto.
    """

    # Le DICIOTTO variabili che il 2026-08-08 la produzione aveva e il banco no.
    # Misurate cosi', non ricordate (D22):
    #   docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' <contenitore>
    #   | cut -d= -f1 | sort -u   ->  poi `comm -13 banco produzione`
    MANCAVANO_IL_2026_08_08 = (
        "BASE_URL", "DB_ACCETTAZIONI", "DB_ADMIN_ACCOUNTS", "DB_CREDITO_USATI",
        "DB_DEPOSITO", "DB_DOMANDA", "DB_GARANZIA", "DB_MARCHE", "DB_MESSAGGI",
        "DB_PARTNER", "DB_PAYOUT", "DB_PENDENTI", "DB_RECENSIONI",
        "DB_TASSA_COMUNALE", "FILE_REFERRAL", "PAGAMENTO_BPS", "UPLOAD_DIR",
        "VIDEO_DIR",
    )

    def _fb(self):
        from collaudi import fedelta_banco
        return fedelta_banco

    def setUp(self):
        import io
        self.percorso_sh = os.path.join(QUI, "collaudi", "banco_prova.sh")
        with io.open(self.percorso_sh, encoding="utf-8") as f:
            self.sh = f.read()

    # ------------------------------------------------------------------
    # IL GIUDIZIO, PROVATO NELLE DUE DIREZIONI (D18 punto 2)
    # ------------------------------------------------------------------
    def test_IL_GIUDIZIO_SA_DIRE_SI_E_NO(self):
        """Se dicesse sempre la stessa cosa non varrebbe niente."""
        fb = self._fb()
        self.assertFalse(fb.banco_infedele([], []),
                         "stesse variabili e nessun database fuori posto: e' FEDELE")
        self.assertTrue(fb.banco_infedele(["DB_PENDENTI"], []),
                        "manca una variabile alla produzione: NON e' fedele")
        self.assertTrue(fb.banco_infedele([], ["pendenti.db"]),
                        "un database dentro il contenitore: NON e' fedele")

    def test_IL_GIUDIZIO_VEDE_IL_DIFETTO_VERO_DEL_2026_08_08(self):
        """Il caso reale, non uno inventato: le 18 misurate quel giorno."""
        fb = self._fb()
        mancanti = fb.variabili_mancanti(
            nomi_produzione=("PATH", "DB_FINANZA") + self.MANCAVANO_IL_2026_08_08,
            nomi_banco=("PATH", "DB_FINANZA"))
        self.assertEqual(sorted(self.MANCAVANO_IL_2026_08_08), mancanti)
        self.assertTrue(fb.banco_infedele(mancanti, []),
                        "il difetto vero del 2026-08-08 deve essere giudicato INFEDELE")

    def test_UN_BANCO_CON_PIU_VARIABILI_NON_E_UN_ERRORE(self):
        """Non-compiacenza al contrario: il banco puo' avere roba in piu' (la chiave di
        prova). Cio' che conta e' che non gli MANCHI niente della produzione."""
        fb = self._fb()
        self.assertEqual([], fb.variabili_mancanti(
            nomi_produzione=("DB_PENDENTI",),
            nomi_banco=("DB_PENDENTI", "GIRI", "STRIPE_WEBHOOK_SECRET")))

    def test_I_DATABASE_FUORI_POSTO_SONO_L_IMPRONTA_DEL_DIFETTO(self):
        """Non la configurazione: l'EFFETTO. E' l'unica prova che non si puo' discutere."""
        fb = self._fb()
        self.assertEqual(
            ["garanzia.db", "payout.db", "pendenti.db"],
            fb.database_fuori_posto(["app.log", "pendenti.db", "payout.db", "garanzia.db"]),
            "i .db dentro il contenitore vanno elencati; il resto (log) no")
        self.assertEqual([], fb.database_fuori_posto([]),
                         "cartella vuota = nessun database fuori posto")
        self.assertEqual([], fb.database_fuori_posto(["app.log", "campagna_stato.json"]),
                         "un log dentro il contenitore e' normale: non e' un database")

    # ------------------------------------------------------------------
    # LO SCRIPT DEL BANCO LO CHIAMA DAVVERO, E SI FERMA
    # ------------------------------------------------------------------
    def test_LO_SCRIPT_PRENDE_L_AMBIENTE_DAL_CONTENITORE_CHE_GIRA(self):
        """Non da un elenco ricopiato a mano: quello marcisce il giorno che il compose
        cambia, e nessuno se ne accorge finche' non costa una diagnosi sbagliata."""
        import io
        self.assertIn(
            "fedelta_banco.py ambiente", self.sh,
            "banco_prova.sh non deriva l'ambiente dal contenitore di produzione: "
            "con i soli --env-file gli mancano le 18 variabili del blocco "
            "`environment:` del compose, 14 delle quali dicono dove salvare i "
            "database (misurato il 2026-08-08)")
        # E il MECCANISMO deve stare nello strumento: e' li' che si legge l'ambiente
        # del contenitore VIVO. Pretenderlo su entrambi i file impedisce di svuotare
        # la chiamata lasciandone solo il nome.
        with io.open(os.path.join(QUI, "collaudi", "fedelta_banco.py"),
                     encoding="utf-8") as f:
            strumento = f.read()
        self.assertIn("docker", strumento, "lo strumento non parla col contenitore vero")
        self.assertIn(
            "Config.Env", strumento,
            "lo strumento non legge le variabili del contenitore "
            "(`docker inspect --format '{{range .Config.Env}}...`)")

    def test_LO_SCRIPT_NON_RICOPIA_A_MANO_L_ELENCO_DEI_DATABASE(self):
        """Il modo esatto in cui questo difetto tornerebbe.

        Qualcuno «semplifica» incollando le `DB_*` dentro lo script: funziona il primo
        giorno e diventa una bugia il giorno che il compose ne aggiunge una -- e in
        silenzio, perche' un elenco c'e' e sembra completo. E' la stessa forma del
        difetto che questa classe documenta: non l'assenza di un controllo, ma un
        controllo che ha smesso di guardare la cosa vera.
        """
        eseguibili = [r for r in self.sh.splitlines()
                      if r.strip() and not r.lstrip().startswith("#")]
        incollate = [r.strip() for r in eseguibili if re.search(r"\bDB_[A-Z_]+=", r)]
        self.assertEqual(
            [], incollate,
            "banco_prova.sh assegna a mano dei percorsi di database invece di "
            "derivarli dal contenitore che gira: %r" % incollate)

    def test_LO_SCRIPT_CHIAMA_IL_CONTROLLO_DI_FEDELTA(self):
        self.assertIn(
            "fedelta_banco.py", self.sh,
            "banco_prova.sh non chiama collaudi/fedelta_banco.py: senza, il banco puo' "
            "partire con un ambiente diverso dalla produzione e MISURARE UN'ALTRA "
            "MACCHINA senza dirlo a nessuno (D18)")

    def test_IL_CONTROLLO_FERMA_NON_SI_LIMITA_AD_AVVISARE(self):
        """La lezione del controllo sulla chiave di Stripe, gia' scritta in questo stesso
        script: «un avviso stampato non basta, perche' al giro dopo non lo legge
        nessuno». Qui si pretende che il verdetto negativo porti a un'uscita, e VICINO
        alla chiamata -- non «da qualche parte nel file», che e' la ricaduta di
        `server_tokens off` (appendice #15).
        """
        i = self.sh.find("fedelta_banco.py controlla")
        self.assertNotEqual(
            i, -1,
            "il controllo di fedelta' non viene ESEGUITO: nominarlo in un commento non "
            "controlla niente. Serve la chiamata `fedelta_banco.py controlla ...`")
        prima = self.sh[max(0, i - 200):i]
        self.assertIn(
            "if !", prima,
            "il controllo di fedelta' viene eseguito ma il suo esito non viene nemmeno "
            "guardato: senza `if !` il verdetto negativo passa inosservato")
        self.assertIn(
            "exit 1", self.sh[i:i + 600],
            "il controllo di fedelta' viene guardato ma non ferma niente: un banco "
            "infedele partirebbe lo stesso e i suoi numeri sembrerebbero veri. E' la "
            "lezione gia' scritta nel passo [5] di questo stesso script: «un avviso "
            "stampato non basta, perche' al giro dopo non lo legge nessuno»")

    def test_LO_SCRIPT_DICHIARA_COSA_NON_COPIA(self):
        """D18 punto 3. I segreti NON si copiano dalla produzione al banco: un banco che
        gira con la chiave vera e' un banco che puo' muovere soldi veri. Se pero' la cosa
        resta implicita, un domani qualcuno la scopre col danno."""
        self.assertIn(
            "SEGRETI", self.sh.upper(),
            "banco_prova.sh non dichiara che i segreti della produzione NON vengono "
            "copiati nel banco: un taglio silenzioso fa sembrare «copiato tutto» cio' "
            "che di proposito non lo e'")


class TestIlGiudiceNonPuoUscireVERDESenzaAverMisurato(unittest.TestCase):
    """D18: uno strumento che MISURA deve avere un controllo meccanico che gli impedisca di
    barare — e il giudice della mutazione e' lo strumento che quel principio dovrebbe far
    rispettare a tutti gli altri.

    IL DIFETTO, VISTO DAVVERO il 2026-08-11. Chiesto un modulo col nome sbagliato
    (`--modulo fase167_credito_single_use`, senza `.py`), l'attrezzo ha stampato
    `ASSENTE — file inesistente` ed e' uscito **0**. Cioe': un refuso nel nome, e il giudizio
    piu' severo del progetto diventa un verde che **non ha guardato niente**. In CI sarebbe
    passato liscio, e per mesi avremmo creduto di avere una rete dove non c'era nulla.

    E' la stessa forma dello sbaglio S1 (confrontare due vuoti e scrivere «uguali»): il vuoto
    non e' un risultato, e' assenza di misura. Ed e' il caso peggiore della D18 punto 1 — lo
    strumento deve provare di essere in condizione di misurare PRIMA di misurare.

    La guardia ESEGUE l'attrezzo davvero e ne legge il codice d'uscita: una guardia che
    contasse parole nel sorgente la soddisferebbe anche un commento (sbaglio S6).
    """
    RADICE = os.path.dirname(os.path.abspath(__file__))

    def _esegui(self, *argomenti):
        """Lancia il giudice come processo a se' e restituisce (uscita, testo)."""
        esito = subprocess.run(
            [sys.executable, os.path.join("collaudi", "mutazione_prodotto.py")]
            + list(argomenti),
            cwd=self.RADICE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return esito.returncode, esito.stdout.decode("utf-8", "replace")

    def test_modulo_INESISTENTE_non_esce_verde(self):
        """Il verso in cui deve GRIDARE."""
        uscita, testo = self._esegui("--modulo", "fase_che_non_esiste_MAI.py",
                                     "--tetto", "1", "--minuti", "1")
        self.assertIn("assente", testo.lower(),
                      "l'attrezzo deve DIRE che il modulo non c'e': %r" % (testo[-500:],))
        self.assertNotEqual(
            uscita, 0,
            "un giro che non ha esaminato NEMMENO UN PUNTO non puo' uscire verde: "
            "uscita=%d\n%s" % (uscita, testo[-500:]))

    def test_su_un_modulo_VERO_e_sorvegliato_resta_verde(self):
        """L'ALTRA direzione, obbligatoria (regola ferrea 10: un falso allarme e' un difetto
        quanto un allarme mancato). Un allarme provato in un verso solo potrebbe gridare
        sempre — e un allarme sempre acceso viene spento. Qui il giudice deve TACERE su un
        modulo che esiste ed e' sorvegliato."""
        uscita, testo = self._esegui("--modulo", "fase167_credito_single_use.py",
                                     "--tetto", "1", "--minuti", "6", "--parziale",
                                     "--killer", "test_credito_single_use")
        self.assertNotIn("assente", testo.lower(),
                         "il modulo esiste: non deve risultare assente: %r" % (testo[-500:],))
        self.assertEqual(
            uscita, 0,
            "su un modulo vero e sorvegliato il giudice deve tacere: uscita=%d\n%s"
            % (uscita, testo[-500:]))

    # ----------------------------------------------------------------------------------
    #  PEZZO 1 DEL PIANO — «il Giudice esce ROSSO se ha saltato punti»
    # ----------------------------------------------------------------------------------
    #  IL DIFETTO, misurato il 2026-08-19 leggendo il verdetto (mutazione_prodotto.py, modo
    #  `--modulo`): i punti lasciati fuori dal TETTO, dal TEMPO o dal timeout dei test
    #  venivano stampati e poi ignorati dal codice d'uscita. Un giro col tetto di serie su
    #  `fase59_concierge` ne lasciava fuori **84 su 114** e usciva **0**.
    #
    #  Perche' e' grave e non e' un dettaglio di forma: quel verdetto e' cio' che decide se
    #  un modulo dei soldi puo' dirsi giudicato (D26). Un verde che copre il 26% dei punti
    #  dice la stessa identica cosa di un verde che li copre tutti — e chi legge non ha modo
    #  di distinguerli. E' il modo di rompersi n. 4 (un controllo che non controlla) applicato
    #  allo strumento che dovrebbe scoprirlo negli altri.
    #
    #  La riparazione NON e' «vietare i giri parziali»: un giro corto serve per iterare in
    #  fretta. E' obbligare a DICHIARARLO (`--parziale`), cosi' che il verde di un giro
    #  incompleto non possa essere scambiato per il verde di un giro completo (D18 punto 3:
    #  uno strumento dichiara cio' che NON ha esaminato).
    def test_un_giro_che_ha_lasciato_punti_FUORI_non_esce_verde(self):
        """Il verso in cui deve GRIDARE: `--minuti 0` fa scadere il giro subito, quindi
        NESSUN punto viene esaminato. Senza `--parziale` quel verde sarebbe una bugia."""
        uscita, testo = self._esegui("--modulo", "fase167_credito_single_use.py",
                                     "--minuti", "0",
                                     "--killer", "test_credito_single_use")
        self.assertIn("oltre il TEMPO", testo,
                      "l'attrezzo deve DIRE quanti punti ha lasciato fuori: %r"
                      % (testo[-600:],))
        self.assertNotEqual(
            uscita, 0,
            "un giro che ha lasciato punti NON esaminati non puo' uscire verde se non ha "
            "dichiarato di essere parziale: uscita=%d\n%s" % (uscita, testo[-600:]))

    def test_il_giudice_RIESEGUE_gli_uccisi_e_lo_dichiara(self):
        """PEZZO 2 DEL PIANO — «ri-confermare un ucciso rieseguendolo».

        ⛔ IL DIFETTO CHE CHIUDE. Un test instabile che fallisce per conto suo (il runner
        sotto carico, una rotta a tempo, una risorsa contesa) fa risultare **UCCISO** un punto
        che nessuno sorveglia davvero. Il modo della CI ri-verifica gia' i SOPRAVVISSUTI per
        non gridare a vuoto; nessuno guardava il verso opposto -- ed e' il piu' pericoloso dei
        due, perche' un falso «ucciso» **non grida mai**: sparisce dentro un punteggio pieno.

        Qui si pretende che il meccanismo ESISTA e sia GOVERNABILE (`--riconferme`), e che il
        giro **dichiari il denominatore**: quanti «uccisi» ha rieseguito su quanti. Un
        campione taciuto e' un punteggio che sembra pieno; un campione dichiarato e' una
        misura (⚠️ ri-confermarli tutti raddoppierebbe un giro da ore: il limite e' scelto,
        non subito, ed e' scritto in fondo al giro).
        """
        import importlib
        import inspect
        giudice = importlib.import_module("collaudi.mutazione_prodotto")
        firma = inspect.signature(giudice.giro_su_moduli)
        self.assertIn("riconferme", firma.parameters,
                      "il giro sui moduli non sa piu' ri-confermare un «ucciso»: senza, un "
                      "killer instabile gonfia il punteggio e nessuno se ne accorge")
        self.assertGreater(
            firma.parameters["riconferme"].default, 0,
            "di serie non si ri-conferma niente: il punteggio nasce gia' senza rete")
        sorgente = inspect.getsource(giudice.giro_su_moduli)
        self.assertIn("riconferme_fatte", sorgente,
                      "il giro non tiene il conto delle ri-conferme: senza denominatore, "
                      "«0 sopravvissuti» non si sa su cosa regge")

    def test_il_verdetto_conta_i_punti_NON_esaminati(self):
        """La stessa regola sul pezzo puro, senza aspettare un giro vero: qui si possono
        costruire a mano i tre modi in cui un punto resta fuori (tetto · tempo · i test che
        non finiscono) e si controlla uno per uno. Le tre sono state VISTE tutte e tre.

        ⛔ Il pezzo sta in una funzione apposta (`verdetto_modulo`) proprio per questo: finche'
        il verdetto viveva dentro `if __name__ == "__main__"`, nessun test poteva toccarlo
        senza lanciare un giro da ore — ed era l'unica parte del giudice che nessuno giudicava.
        """
        import importlib
        giudice = importlib.import_module("collaudi.mutazione_prodotto")
        vuoto = {"oltre_il_tetto": 0, "oltre_il_tempo": 0, "generatore": {},
                 "senza_sorveglianti": 0, "normale_sec": {}}
        tutti_uccisi = [{"file": "f.py", "riga": 1, "verdetto": "ucciso", "danno": "x"}]

        # (a) macchina sana: tutto esaminato, tutto ucciso -> VERDE (regola ferrea 10)
        uscita, motivi = giudice.verdetto_modulo(tutti_uccisi, dict(vuoto))
        self.assertEqual((uscita, motivi), (0, []),
                         "un giro completo e tutto ucciso deve TACERE: %r" % (motivi,))

        # (b) i tre modi di lasciare un punto fuori, uno per uno
        for chiave, quanti in (("oltre_il_tetto", 7), ("oltre_il_tempo", 3)):
            rinunce = dict(vuoto)
            rinunce[chiave] = quanti
            uscita, motivi = giudice.verdetto_modulo(tutti_uccisi, rinunce)
            self.assertEqual(uscita, 1,
                             "%d punti lasciati fuori da `%s` e il giudice esce verde: %r"
                             % (quanti, chiave, motivi))
            self.assertTrue(any(str(quanti) in m for m in motivi),
                            "il motivo deve dire QUANTI punti sono rimasti fuori: %r"
                            % (motivi,))
        nd = tutti_uccisi + [{"file": "f.py", "riga": 9,
                              "verdetto": "non_determinabile", "danno": "y"}]
        uscita, motivi = giudice.verdetto_modulo(nd, dict(vuoto))
        self.assertEqual(uscita, 1,
                         "un punto NON DETERMINABILE non e' un punto ucciso: e' un punto su "
                         "cui non si sa niente, e non puo' passare per verde: %r" % (motivi,))

        # (c) un giro DICHIARATO parziale resta verde -- ma lo dice
        uscita, motivi = giudice.verdetto_modulo(tutti_uccisi,
                                                 dict(vuoto, oltre_il_tetto=7), parziale=True)
        self.assertEqual(uscita, 0,
                         "un giro dichiarato parziale non deve gridare: %r" % (motivi,))

        # (c-bis) PEZZO 2 DEL PIANO: un «ucciso» che alla seconda prova non muore piu' non e'
        #     un punto sorvegliato, e' un test instabile che gonfia il punteggio. Deve fare
        #     rosso, e «parziale» NON lo condona: non e' un punto che il giro non ha
        #     guardato, e' un punto che il giro credeva di aver coperto -- ed e' peggio di un
        #     sopravvissuto, perche' un falso «ucciso» non grida mai.
        incerto = [{"file": "f.py", "riga": 3, "verdetto": "incerto",
                    "danno": "ucciso solo a volte"}]
        for parziale in (False, True):
            uscita, motivi = giudice.verdetto_modulo(incerto, dict(vuoto), parziale=parziale)
            self.assertEqual(uscita, 1,
                             "un «ucciso» non ri-confermato deve fare rosso anche con "
                             "parziale=%s: %r" % (parziale, motivi))

        # (d) e cio' che era gia' rosso resta rosso anche in un giro parziale: dichiarare
        #     «parziale» copre i punti NON GUARDATI, non i buchi TROVATI.
        sopravvissuto = [{"file": "f.py", "riga": 2, "verdetto": "sopravvissuto",
                          "danno": "il guasto passa"}]
        uscita, _ = giudice.verdetto_modulo(sopravvissuto, dict(vuoto), parziale=True)
        self.assertEqual(uscita, 1,
                         "«parziale» non e' un condono: un punto SOPRAVVISSUTO resta rosso")


class TestIlDeployNonPuoSALTAREIlPassoDiSicurezza(unittest.TestCase):
    """Il paracadute agganciato all'immagine sbagliata: SEI volte in sei giorni.

    IL 2026-08-11 LA DIAGNOSI E' CAMBIATA. Non mancava lo strumento: `deploy/protocollo_d17.sh`
    esiste dal 2026-08-07, ri-aggancia `:prec` e si FERMA se non coincide (fase `prima`). Ha
    fallito per un motivo diverso: era FACOLTATIVO. Le tre fasi erano indipendenti, quindi si
    poteva chiamare `scambio` senza aver mai fatto `prima` -- ed e' esattamente cio' che e'
    successo quel giorno, deployando a mano passo per passo. Il paracadute puntava a
    un'immagine di 45 ORE prima: tirando la maniglia il sito sarebbe tornato indietro OLTRE il
    deploy della tariffa, rimettendo online quella sotto costo, in silenzio.

    E' la stessa malattia del gancio pre-commit, scoperta lo stesso giorno: una procedura
    corretta che si puo' saltare non e' un controllo. La cura e' la stessa: il passo di
    sicurezza smette di essere un consiglio e diventa una PRECONDIZIONE.

    Queste guardie ESEGUONO lo script per davvero (fase `gettone`, che non tocca ne' git ne'
    docker) e ne leggono il codice d'uscita. Una guardia che cercasse parole nel sorgente la
    soddisferebbe anche un commento (sbaglio S6).

    ⛔ COSA NON PROVANO, dichiarato (D18 punto 3): non provano le fasi `prima`/`scambio` per
    intero -- servono docker e il VPS. Provano il CONTROLLO nuovo, che e' la parte che oggi
    non c'era. E nessun controllo puo' impedire a qualcuno di digitare `docker compose build`
    a mano: quello resta possibile, e va detto invece di far credere il contrario.
    """
    RADICE = os.path.dirname(os.path.abspath(__file__))

    @staticmethod
    def _trova_sh():
        """`sh` NON e' nel PATH di PowerShell su questa macchina, ma ESISTE: Git per Windows
        se lo porta dietro. Arrendersi al primo `which` avrebbe messo da parte queste tre
        guardie proprio dove si lavora -- tre verdi che non guardano niente, cioe' la zona
        cieca peggiore (S11: la stessa domanda da' due risposte fra Bash e PowerShell).
        ⛔ `bash` di C:\\Windows\\system32 e' WSL: un'altra macchina con un altro filesystem.
        Non si usa."""
        trovato = shutil.which("sh")
        if trovato:
            return trovato
        git = shutil.which("git")
        if git:
            base = os.path.dirname(os.path.dirname(git))
            for rel in (("bin", "sh.exe"), ("usr", "bin", "sh.exe")):
                p = os.path.join(base, *rel)
                if os.path.exists(p):
                    return p
        return ""

    def setUp(self):
        self.sh = self._trova_sh()
        self.dir = tempfile.mkdtemp()

    def _almeno_la_struttura(self, marcatore):
        """RAMO POVERO, e sta qui invece di uno `skipTest` per una ragione precisa.

        Saltare avrebbe fatto sparire queste guardie dal rapporto come «skipped», e uno
        skip deciso da cio' che il test dovrebbe verificare e' un controllo che si assolve
        da solo (lo dice `test_suite_senza_zone_cieche`, che infatti ha beccato la prima
        versione di questa classe). Il motivo «`sh` non installato» sarebbe pure passato per
        ambientale -- cioe' sarebbe bastata una PAROLA per zittire la guardia. Non si fa.

        Quindi: senza `sh` non si esegue lo script, ma si asserisce lo stesso qualcosa di
        vero -- che il controllo ESISTA e che `scambio` ci passi PRIMA del `git pull`.
        ⛔ E' piu' debole, e va detto: una guardia che legge il sorgente la soddisferebbe
        anche un commento (S6). E' la rete di riserva, non la rete."""
        with io.open(os.path.join(self.RADICE, "deploy", "protocollo_d17.sh"),
                     encoding="utf-8") as f:
            testo = f.read()
        self.assertIn(marcatore, testo,
                      "lo script deve saper dire %r" % (marcatore,))
        pezzi = testo.split('if [ "$FASE" = "scambio" ]', 1)
        self.assertEqual(len(pezzi), 2, "manca la fase 'scambio' nello script")
        coda = pezzi[1]
        i_controllo, i_pull = coda.find("pretendi_gettone"), coda.find("git pull")
        self.assertNotEqual(i_controllo, -1, "'scambio' non pretende il gettone")
        self.assertNotEqual(i_pull, -1, "'scambio' non fa piu' il git pull?")
        self.assertLess(i_controllo, i_pull,
                        "il passo di sicurezza deve venire PRIMA di prendere il codice nuovo")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _lancia(self):
        amb = dict(os.environ)
        amb["RADICE_D17"] = self.dir
        amb["GETTONE_D17"] = os.path.join(self.dir, "gettone")
        e = subprocess.run([self.sh, os.path.join("deploy", "protocollo_d17.sh"), "gettone"],
                           cwd=self.RADICE, env=amb,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return e.returncode, e.stdout.decode("utf-8", "replace")

    def _scrivi_gettone(self, epoca):
        with open(os.path.join(self.dir, "gettone"), "w", encoding="utf-8") as f:
            f.write("epoca=%d\nimmagine=sha256:finta\ncommit=abc1234\n" % epoca)

    def test_SENZA_il_passo_prima_il_deploy_si_RIFIUTA(self):
        """Il caso vero del 2026-08-11: si arriva allo scambio senza aver mai agganciato il
        paracadute. Deve fermarsi, e deve dire PERCHE'."""
        if not self.sh:
            return self._almeno_la_struttura("GETTONE_MANCANTE")
        uscita, testo = self._lancia()
        self.assertIn("GETTONE_MANCANTE", testo,
                      "deve dire quale controllo ha fallito: %r" % (testo[-400:],))
        self.assertNotEqual(uscita, 0,
                            "senza il passo di sicurezza il deploy non puo' proseguire")

    def test_un_gettone_VECCHIO_non_vale(self):
        """Un `prima` fatto ieri non protegge il deploy di oggi: nel frattempo l'immagine che
        gira puo' essere cambiata, e il paracadute punterebbe di nuovo alla cosa sbagliata."""
        if not self.sh:
            return self._almeno_la_struttura("GETTONE_SCADUTO")
        self._scrivi_gettone(int(time.time()) - 4 * 3600)
        uscita, testo = self._lancia()
        self.assertIn("GETTONE_SCADUTO", testo,
                      "deve distinguere 'vecchio' da 'mancante': %r" % (testo[-400:],))
        self.assertNotEqual(uscita, 0, "un gettone scaduto non autorizza lo scambio")

    def test_un_gettone_FRESCO_lascia_passare(self):
        """L'ALTRA direzione, obbligatoria (regola ferrea 10): un blocco che grida sempre
        viene disattivato, e allora non protegge piu' niente."""
        if not self.sh:
            return self._almeno_la_struttura("gettone OK")
        self._scrivi_gettone(int(time.time()))
        uscita, testo = self._lancia()
        self.assertEqual(uscita, 0,
                         "col passo di sicurezza fatto, il deploy deve poter proseguire: %r"
                         % (testo[-400:],))


class _GuardieSugliAttrezziDelLavoro(unittest.TestCase):
    """Appoggi comuni alle guardie sul PRE-VOLO e sul PRE-FATTO.

    ⛔ PERCHE' QUESTE GUARDIE ESISTONO (D18 punto 4). `collaudi/prima_di_lanciare.py` e
    `collaudi/prima_di_dire_fatto.py` sono strumenti che MISURANO, e uno strumento che
    misura deve avere un controllo meccanico che gli impedisca di barare. Senza queste
    guardie, fra sei mesi una «semplificazione» toglie un controllo e nessuno se ne
    accorge -- che e' esattamente come il gancio pre-commit era rimasto spento e il
    paracadute agganciato all'immagine sbagliata per sei giorni.

    Non leggono il sorgente degli attrezzi: li ESEGUONO. Una guardia che cerca parole in
    un file la soddisferebbe anche un commento (sbaglio S6).
    """
    RADICE = QUI

    @classmethod
    def _carica(cls, nome, etichetta):
        import importlib.util
        percorso = os.path.join(cls.RADICE, "collaudi", nome)
        spec = importlib.util.spec_from_file_location(etichetta, percorso)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        return modulo

    @classmethod
    def pv(cls):
        return cls._carica("prima_di_lanciare.py", "_pv_sotto_guardia")

    @classmethod
    def pf(cls):
        return cls._carica("prima_di_dire_fatto.py", "_pf_sotto_guardia")

    def _esegui(self, attrezzo, *argomenti):
        """Lo strumento eseguito DAVVERO, col codice d'uscita letto diretto (regola
        ferrea 7: `comando | filtro` restituisce l'esito del filtro)."""
        avvio = time.time()
        esito = subprocess.run(
            [sys.executable, os.path.join("collaudi", attrezzo)] + list(argomenti),
            cwd=self.RADICE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return (esito.returncode, esito.stdout.decode("utf-8", "replace"),
                time.time() - avvio)

    def _pagina_sana(self):
        with io.open(os.path.join(self.RADICE, "RIPRENDI_QUI.md"), encoding="utf-8") as f:
            return f.read()


class TestIlPreVoloVedeIProblemiPRIMA(_GuardieSugliAttrezziDelLavoro):
    """🛫 I sei controlli che costano DUE SECONDI e che l'11 agosto sono stati pagati in
    SESSANTOTTO MINUTI, perche' le stesse guardie giravano in fondo alla suite."""

    def test_ESEGUITO_DAVVERO_PRODUCE_UN_RAPPORTO_COMPLETO(self):
        uscita, testo, _ = self._esegui("prima_di_lanciare.py")
        for numero in range(1, 8):
            self.assertRegex(
                testo, r"\b%d\. " % numero,
                "il controllo %d non compare nel rapporto: un pre-volo che perde per "
                "strada un controllo e' un pre-volo che dice verde senza aver guardato "
                "tutto.\n%s" % (numero, testo[-1200:]))
        self.assertIn("COSA QUESTO CONTROLLO NON HA ESAMINATO", testo,
                      "D18 punto 3: uno strumento che misura dichiara SEMPRE cosa ha "
                      "lasciato fuori. Un taglio silenzioso fa sembrare «coperto» cio' "
                      "che non e' stato nemmeno guardato")
        self.assertIn("CRONOMETRO:", testo,
                      "il pre-volo si mette da solo sotto cronometro: se diventa lento "
                      "viene abbandonato, e allora non protegge piu' niente")
        self.assertIn("VERDETTO:", testo, "deve dire un verdetto, non solo elencare")
        self.assertIn(uscita, (0, 1), "uscita inattesa: %r" % uscita)

    def test_IL_CODICE_D_USCITA_NON_PUO_MENTIRE_SUL_RAPPORTO(self):
        """⛔ IL CONTROLLO MECCANICO CHE IMPEDISCE DI BARARE (D18).

        Questa e' la guardia che vale di piu', ed e' scritta apposta per NON dipendere
        dalla macchina: non pretende che il pre-volo sia verde qui (su Linux la riga
        AMBIENTE descrive un'altra macchina, e sarebbe un falso rosso). Pretende che il
        codice d'uscita e il rapporto DICANO LA STESSA COSA. Uno strumento che stampa
        rossi e poi esce 0 e' il verde peggiore di tutti: il giudice della mutazione l'ha
        gia' fatto una volta, stampando «42 mutanti su 42 uccisi» su una base rossa."""
        uscita, testo, _ = self._esegui("prima_di_lanciare.py")
        corpo = testo.split("COSA QUESTO CONTROLLO NON HA ESAMINATO")[0]
        rossi = len(re.findall(r"^  ROSSO ", corpo, re.M))
        non_eseguiti = len(re.findall(r"^  NON ESEGUITO ", corpo, re.M))
        if rossi or non_eseguiti:
            self.assertEqual(
                uscita, 1,
                "il rapporto elenca %d rossi e %d non eseguiti, ma lo strumento e' uscito "
                "%d: un'uscita che non segue il rapporto e' uno strumento che bara.\n%s"
                % (rossi, non_eseguiti, uscita, testo[-1500:]))
        else:
            self.assertEqual(
                uscita, 0,
                "il rapporto non ha nessun rosso e nessun non-eseguito, ma lo strumento "
                "e' uscito %d: allora grida sempre, e un allarme sempre acceso viene "
                "spento (regola ferrea 10).\n%s" % (uscita, testo[-1500:]))

    def test_STAMPA_I_SEI_DIVIETI_PRIMA_DI_TUTTO(self):
        """⛔ ORDINE DEL FONDATORE, 2026-08-11: «LE REGOLE SI LEGGONO PRIMA E DOPO OGNI
        OPERAZIONE». Era l'ultima cosa affidata al ricordarsene, e il ricordarsene in
        questo progetto ha gia' fallito abbastanza volte da non poterci contare."""
        uscita, testo, _ = self._esegui("prima_di_lanciare.py")
        for divieto in ("B1.", "B2.", "B3.", "B4.", "B5.", "B6."):
            self.assertIn(divieto, testo,
                          "il pre-volo non stampa piu' %s: i divieti tornerebbero a "
                          "dipendere da chi si ricorda di rileggerli" % divieto)
        self.assertLess(
            testo.index("B1."), testo.index("PRE-VOLO"),
            "i divieti vanno stampati PRIMA dei controlli: si leggono prima di iniziare "
            "un'operazione, non dopo averla gia' fatta")

    def test_UN_WORKTREE_E_UN_REPOSITORY_GIT(self):
        """⛔ IL ROSSO FINTO E' PEGGIO DEL VERDE FINTO, e il 2026-08-24 e' costato mezz'ora.

        `.git` NON e' sempre una cartella: in un **worktree** (`git worktree add`) e' un FILE
        di una riga che punta al repository principale. `_precondizioni` lo cercava con
        `os.path.isdir`, quindi dentro un worktree il pre-volo si dichiarava «non in
        condizione di misurare» e **OTTO guardie di questo file uscivano rosse senza che
        niente fosse rotto**. E il worktree separato non e' un caso di frontiera: e'
        esattamente il modo di lavorare che il piano delle due corsie PRESCRIVE alla Corsia B.

        💡 Un verde finto lo si va a cercare; un rosso finto insegna a ignorare i rossi, ed
        e' la stessa malattia dell'allarme sempre acceso (regola ferrea 10).

        ⛔ E SI PROVA NELLE DUE DIREZIONI: che il worktree passi NON dimostra niente da solo
        (`return []` passerebbe uguale). Serve anche che su una cartella che repository non
        e' lo strumento continui a fermarsi.
        """
        pdl = self.pv()

        finta = tempfile.mkdtemp(prefix="finto_worktree_")
        self.addCleanup(shutil.rmtree, finta, True)
        for nome in ("RIPRENDI_QUI.md", "CLAUDE.md", "test_pipeline_ci.py"):
            with io.open(os.path.join(finta, nome), "w", encoding="utf-8") as f:
                f.write("segnaposto")
        # ── com'e' fatto un worktree VERO: `.git` e' un FILE, non una cartella ──
        with io.open(os.path.join(finta, ".git"), "w", encoding="utf-8") as f:
            f.write("gitdir: %s\n"
                    % os.path.join(self.RADICE, ".git", "worktrees", "finto"))
        self.assertEqual(
            [], pdl._precondizioni(finta),
            "in un worktree (.git e' un FILE) il pre-volo si dichiara incapace di "
            "misurare, e otto guardie di questo file diventano rosse per finta")

        # ── l'altra direzione: dove un repository NON c'e', deve continuare a fermarsi ──
        nuda = tempfile.mkdtemp(prefix="niente_repo_")
        self.addCleanup(shutil.rmtree, nuda, True)
        for nome in ("RIPRENDI_QUI.md", "CLAUDE.md", "test_pipeline_ci.py"):
            with io.open(os.path.join(nuda, nome), "w", encoding="utf-8") as f:
                f.write("segnaposto")
        impedimenti = pdl._precondizioni(nuda)
        self.assertTrue(
            any("repository git" in m for m in impedimenti),
            "senza nessun .git il pre-volo NON si ferma piu': la precondizione e' stata "
            "allargata fino a non controllare piu' niente (D18 punto 1)")

    def _togli_la_riga(self, pagina, riconoscitore, schema):
        """Toglie una riga di dati e PRETENDE che sia sparita davvero, chiedendolo allo
        stesso riconoscitore che usa lo strumento.

        ⛔ NASCE DA UN ROSSO VERO, il 2026-08-11, e la lezione vale piu' della riparazione.
        La prima versione faceva `pagina.replace("CONSEGNE AGGIORNATE A:", ..., 1)`. Quel
        giorno il documento aveva appena preso una FRASE che nominava quella riga (per
        spiegare una correzione), e la frase stava PRIMA. La sostituzione ha colpito la
        frase; la riga vera e' rimasta intatta; lo strumento l'ha letta e ha risposto
        correttamente OK; e il test ha accusato lo strumento di essere un ornamento.

        💡 **Era il verde finto applicato all'INIEZIONE**: un test convinto di aver messo
        dentro un guasto senza averlo messo. `assertNotEqual(sana, malata)` non bastava --
        qualcosa era cambiato davvero, solo non la cosa che conta. Da qui la regola:
        un'iniezione non si dichiara riuscita perche' il testo e' cambiato, ma perche' il
        riconoscitore dello strumento **non trova piu' cio' che cercava**.
        """
        self.assertIsNotNone(
            riconoscitore.search(pagina),
            "nel documento SANO la riga non c'e' nemmeno: questa prova non proverebbe "
            "niente, e passerebbe per il motivo sbagliato")
        malata = re.sub(schema, "RIGA-TOLTA-DALLA-GUARDIA", pagina, count=1, flags=re.M)
        self.assertIsNone(
            riconoscitore.search(malata),
            "l'iniezione NON ha tolto la riga che lo strumento cerca: ha colpito "
            "qualcos'altro (una frase che la nomina?), e allora questa prova sta per "
            "accusare uno strumento sano")
        return malata

    def test_OGNI_CONTROLLO_GRIDA_COL_GUASTO_DENTRO(self):
        """D18 punto 2, prima meta'. Un allarme provato in un verso solo potrebbe gridare
        sempre -- oppure mai. I guasti si iniettano su COPIE in memoria: il file vero non
        viene mai riaperto in scrittura (B2)."""
        pv = self.pv()
        sana = self._pagina_sana()

        conto_sbagliato = re.sub(r"^SUITE ATTUALE: Ran \d+ test",
                                 "SUITE ATTUALE: Ran 1 test", sana, count=1, flags=re.M)
        detto = pv._RIGA_SUITE.search(conto_sbagliato)
        self.assertIsNotNone(detto, "l'iniezione ha rotto la riga invece di cambiarla")
        self.assertEqual("1", detto.group(1),
                         "l'iniezione non ha cambiato IL NUMERO che lo strumento legge: "
                         "avrebbe accusato uno strumento sano")

        casi = [
            ("1 conto dei test sbagliato",
             lambda: pv.controllo_1_conto_dei_test(radice=self.RADICE,
                                                   pagina=conto_sbagliato)),
            ("1 la riga del conto sparita",
             lambda: pv.controllo_1_conto_dei_test(
                 radice=self.RADICE,
                 pagina=self._togli_la_riga(sana, pv._RIGA_SUITE,
                                            r"^SUITE ATTUALE: Ran \d+ test.*$"))),
            ("2 la riga delle consegne sparita",
             lambda: pv.controllo_2_consegne(
                 radice=self.RADICE,
                 pagina=self._togli_la_riga(sana, pv._RIGA_CONSEGNE,
                                            r"^CONSEGNE AGGIORNATE A:.*$"))),
            ("4 Python diverso da quello dichiarato",
             lambda: pv.controllo_4_ambiente(pagina=sana, radice=self.RADICE,
                                             quale_python="0.0.0")),
            ("4 una libreria dichiarata che non c'e'",
             lambda: pv.controllo_4_ambiente(pagina=sana, radice=self.RADICE,
                                             moduli_presenti=set())),
        ]
        for nome, fai in casi:
            with self.subTest(caso=nome):
                stato, dettaglio = fai()
                self.assertEqual(
                    pv.ROSSO, stato,
                    "col guasto «%s» dentro, il pre-volo NON grida: e' un ornamento.\n"
                    "  ha detto: %s — %s" % (nome, stato, dettaglio[:300]))

    def test_IL_CONTROLLO_DELLE_CONSEGNE_GRIDA_SU_UN_COMMIT_VECCHIO(self):
        """⛔ IL FIXTURE DEVE ESSERE UN COMMIT VERO, e la prima versione di questa guardia
        lo ha dimostrato costando un giro: con un valore inventato (`4b825dc`, l'albero
        vuoto di git) lo strumento risponde NON ESEGUITO -- «git non conosce questo
        commit» -- e ha ragione, perche' dove non si puo' misurare non si inventa un
        rosso. Un fixture sbagliato avrebbe fatto passare per ornamento un controllo sano.

        Qui l'antenato si CHIEDE A GIT: il terzo commit di lavoro a ritroso ha per
        definizione due commit dopo di se', che e' esattamente la soglia."""
        pv = self.pv()
        sana = self._pagina_sana()
        antenato = subprocess.run(
            ["git", "rev-list", "--no-merges", "--skip=2", "-n", "1", "HEAD"],
            cwd=self.RADICE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        misurabile = antenato.returncode == 0 and antenato.stdout.strip()
        if misurabile:
            sha = antenato.stdout.decode("utf-8", "replace").strip()[:7]
            malata = re.sub(r"^CONSEGNE AGGIORNATE A: .*$",
                            "CONSEGNE AGGIORNATE A: " + sha, sana, count=1, flags=re.M)
            self.assertNotEqual(sana, malata,
                                "l'iniezione non ha cambiato niente: questa guardia non "
                                "proverebbe nulla")
            stato, dettaglio = pv.controllo_2_consegne(radice=self.RADICE, pagina=malata)
            self.assertEqual(pv.ROSSO, stato,
                             "consegne ferme a %s (due commit di lavoro fa) e il pre-volo "
                             "non grida: %s" % (sha, dettaglio[:300]))
            self.assertIn(sha, dettaglio, "deve dire da QUALE commit sono ferme")
        # ⛔ Si asserisce in ENTRAMBI i rami, mai uno `skipTest`: dove git non risponde
        # resta comunque vero che il giudizio sa dire si' e no.
        self.assertFalse(pv.consegne_troppo_indietro(0), "zero commit dopo: e' sano")
        self.assertFalse(pv.consegne_troppo_indietro(1),
                         "UNO e' il commit che porta le consegne stesse: e' sano")
        self.assertTrue(pv.consegne_troppo_indietro(2), "due commit dopo: e' indietro")
        self.assertTrue(pv.consegne_troppo_indietro(37))
        self.assertFalse(pv.consegne_troppo_indietro(None),
                         "dove non si puo' misurare non si inventa un rosso")

    def test_IL_CONTROLLO_DELLA_MUTAZIONE_GRIDA_SU_UNA_TRACCIA_APERTA(self):
        """Un giro di mutazione interrotto lascia un guasto DENTRO un file di produzione:
        e' successo tre volte in un giorno solo. La traccia finta si costruisce in una
        cartella temporanea, MAI in quella vera -- che bloccherebbe i commit sul serio."""
        pv = self.pv()
        cartella = tempfile.mkdtemp()
        try:
            finta = os.path.join(cartella, "bookinvip_mutazione_in_corso")
            os.makedirs(finta)
            with io.open(os.path.join(finta, "quale.txt"), "w", encoding="utf-8") as f:
                f.write("fase59_prezzi.py")
            stato, dettaglio = pv.controllo_5_traccia_mutazione(radice=self.RADICE,
                                                                traccia=finta)
            self.assertEqual(pv.ROSSO, stato,
                             "con un giro di mutazione APERTO non si lancia niente: %s"
                             % dettaglio[:300])
            self.assertIn("fase59_prezzi.py", dettaglio,
                          "deve dire QUALE file potrebbe essere rotto, altrimenti chi "
                          "legge non sa dove guardare")
            stato_sano, _ = pv.controllo_5_traccia_mutazione(
                radice=self.RADICE, traccia=os.path.join(cartella, "che-non-esiste"))
            self.assertEqual(pv.OK, stato_sano,
                             "senza traccia deve TACERE: l'altra direzione (regola "
                             "ferrea 10)")
        finally:
            shutil.rmtree(cartella, ignore_errors=True)

    def test_IL_CONTROLLO_DEI_BYTE_VEDE_LA_FIRMA_DELL_HEREDOC(self):
        """Il difetto vero del 2026-08-03: `\\bOTA\\b` diventato `<BS>OTA<BS>` in
        `audit_coerenza_tariffe.py`. Quella parte della regola non combaciava MAI, e lo
        strumento continuava a girare dicendo di aver controllato."""
        pv = self.pv()
        cartella = tempfile.mkdtemp()
        try:
            with io.open(os.path.join(cartella, "sporco.py"), "wb") as f:
                f.write(b'KW = re.compile("\x08OTA\x08")\n')
            with io.open(os.path.join(cartella, "pulito.py"), "wb") as f:
                f.write(b'KW = re.compile(r"\\bOTA\\b")\n')
            stato, dettaglio = pv.controllo_6_byte_di_controllo(radice=cartella,
                                                                quali=["sporco.py"])
            self.assertEqual(pv.ROSSO, stato, "non vede il backspace: %s" % dettaglio[:300])
            stato_ok, _ = pv.controllo_6_byte_di_controllo(radice=cartella,
                                                           quali=["pulito.py"])
            self.assertEqual(pv.OK, stato_ok,
                             "su un file pulito deve tacere, altrimenti e' un allarme che "
                             "suona sempre")
        finally:
            shutil.rmtree(cartella, ignore_errors=True)

    def test_E_TACE_A_MACCHINA_SANA(self):
        """D18 punto 2, seconda meta'. I valori dell'ambiente si iniettano coincidenti con
        la dichiarazione, cosi' la guardia dice la stessa cosa su Windows e su Linux: un
        cancello che dipende dalla macchina e' un falso allarme che aspetta il suo giorno."""
        pv = self.pv()
        sana = self._pagina_sana()
        atteso = re.search(r"Python (\d+\.\d+\.\d+)", sana)
        self.assertIsNotNone(atteso, "la riga AMBIENTE non dichiara piu' un Python")
        stato, dettaglio = pv.controllo_4_ambiente(
            pagina=sana, radice=self.RADICE, quale_python=atteso.group(1),
            quale_openssl=not re.search(r"openssl\s+NON\s+nel\s+PATH", sana, re.I),
            moduli_presenti={"hypothesis", "yaml", "coverage"})
        self.assertEqual(pv.OK, stato,
                         "sulla macchina esattamente DICHIARATA il controllo grida lo "
                         "stesso: %s" % dettaglio[:400])

    def test_IL_METRO_SI_ACCORGE_DA_SE_DI_ESSERE_NELLA_SHELL_SBAGLIATA(self):
        """⛔ D18 CONDIZIONE 1: «misura prima se stesso. Un metro storto va scoperto dal
        metro, non dal muro.» Scritta il 2026-08-16, dopo averlo sbagliato io.

        `controllo_4_ambiente` porta scritto in cima, dalla sua prima riga: *«MISURATO
        DALLA SHELL CHE LANCERA' LA SUITE, non da un'altra (S11/D23)»*. Ma quella frase
        era un **presupposto**, non un controllo: la funzione non aveva modo di sapere in
        che shell stava girando, e si fidava di chi la chiamava. Il 2026-08-16 l'ho
        lanciata da Git Bash mentre la suite parte da PowerShell, e ha risposto sulla
        domanda sbagliata. La frase c'era, scritta in chiaro, nel file che avevo appena
        letto -- ed e' la prova che **un obbligo affidato alla buona volonta' si rompe di
        nuovo, anche quando e' scritto benissimo**.

        ⛔ E IL CASO PERICOLOSO NON E' QUELLO CHE MI E' CAPITATO. A me e' uscito un falso
        ROSSO, che fa perdere tempo e basta. Ma la stessa cecita' produce il falso VERDE:
        se un domani la riga AMBIENTE dichiarasse «openssl presente» e qualcuno
        controllasse da Git Bash -- dove `openssl` C'E' -- il controllo direbbe «ambiente
        a posto», e poi la suite girerebbe da PowerShell **senza cinque guardie sul
        ripristino dei backup**, che `unittest` toglie IN BLOCCO registrando un solo salto
        senza nome (D23 punto 3). Nessuno se ne accorgerebbe.

        Percio' qui non basta un avviso: sulla parte che dipende dal PATH il controllo
        deve rifiutarsi di rispondere -- `NON ESEGUITO`, che in questo progetto **non e'
        mai un successo** (sbaglio S7) e fa uscire il pre-volo con codice 1.

        Le DUE direzioni (D18 condizione 2), perche' un allarme provato in un verso solo
        potrebbe gridare sempre -- e un allarme sempre acceso viene spento.
        """
        pv = self.pv()
        sana = self._pagina_sana()
        atteso = re.search(r"Python (\d+\.\d+\.\d+)", sana)
        self.assertIsNotNone(atteso, "la riga AMBIENTE non dichiara piu' un Python")
        comuni = dict(pagina=sana, radice=self.RADICE, quale_python=atteso.group(1),
                      moduli_presenti={"hypothesis", "yaml", "coverage"})

        def con_msystem(valore):
            """Finge (o toglie) l'impronta che Git Bash lascia nell'ambiente."""
            vecchio = os.environ.get("MSYSTEM")
            if valore is None:
                os.environ.pop("MSYSTEM", None)
            else:
                os.environ["MSYSTEM"] = valore
            try:
                return pv.controllo_4_ambiente(**comuni)
            finally:
                if vecchio is None:
                    os.environ.pop("MSYSTEM", None)
                else:
                    os.environ["MSYSTEM"] = vecchio

        # DIREZIONE 1 — shell estranea: deve RIFIUTARSI, non rispondere.
        stato, dettaglio = con_msystem("MINGW64")
        self.assertEqual(
            pv.NON_ESEGUITO, stato,
            "il pre-volo sta girando sotto Git Bash (MSYSTEM), dove il PATH e' un altro, "
            "e invece di dichiararsi NON in grado di misurare ha dato un giudizio sul "
            "PATH: e' un metro che non sa di essere storto (D18 condizione 1).\n"
            "  ha detto: %s - %s" % (stato, dettaglio[:300]))
        self.assertIn("shell", dettaglio.lower(),
                      "il rifiuto non dice che il problema e' la SHELL, quindi chi legge "
                      "non sa cosa fare: %s" % dettaglio[:300])

        # DIREZIONE 2 — shell giusta: deve tornare a GIUDICARE, o sarebbe un cancello
        # che non si apre mai, cioe' un controllo spento.
        stato2, dettaglio2 = con_msystem(None)
        self.assertNotEqual(
            pv.NON_ESEGUITO, stato2,
            "senza MSYSTEM siamo nella shell che lancia la suite: qui il controllo DEVE "
            "giudicare. Se si rifiuta sempre, non protegge niente e verra' tolto.\n"
            "  ha detto: %s - %s" % (stato2, dettaglio2[:300]))

    def test_UN_CONTROLLO_CHE_ESPLODE_DIVENTA_NON_ESEGUITO_NON_VERDE(self):
        """Sbaglio S7: se manca la premessa il controllo non e' verde, e' NON ESEGUITO. Un
        controllo che esplode non ha misurato niente."""
        pv = self.pv()

        def scoppia(radice=None):
            raise RuntimeError("il metro si e' rotto")

        esiti = pv.giro(self.RADICE, ((99, "un controllo che esplode", scoppia),))
        self.assertEqual(pv.NON_ESEGUITO, esiti[0].stato,
                         "un controllo che esplode deve diventare NON ESEGUITO, non "
                         "sparire e non passare per verde")
        rossi, non_eseguiti = pv.verdetto(esiti)
        self.assertEqual(1, len(non_eseguiti),
                         "il verdetto deve CONTARLO: un non-eseguito ignorato e' una zona "
                         "cieca con l'aspetto della copertura")

    def test_SI_FERMA_SE_NON_E_IN_CONDIZIONE_DI_MISURARE(self):
        """D18 punto 1: un metro storto va scoperto dal metro, non dal muro."""
        pv = self.pv()
        cartella = tempfile.mkdtemp()
        try:
            mancanti = pv._precondizioni(cartella)
            self.assertTrue(mancanti,
                            "su una cartella vuota il pre-volo si crede in grado di "
                            "misurare: stamperebbe un verdetto che non ha misurato")
        finally:
            shutil.rmtree(cartella, ignore_errors=True)
        self.assertEqual([], pv._precondizioni(self.RADICE),
                         "sulla radice vera non deve inventarsi impedimenti")

    def test_RESTA_SOTTO_IL_TETTO_DICHIARATO(self):
        """⛔ LA TRAPPOLA DA NON RIPAGARE. Se il pre-volo diventa lento la gente smette di
        lanciarlo, e allora non protegge piu' niente -- e' il modo esatto in cui un
        controllo corretto muore. Il tetto e' dichiarato nello strumento e non si puo'
        alzare a piacere per far passare questa guardia: qui si pretende che resti basso.

        ⛔ La soglia di fallimento e' generosa apposta (tre volte il tetto): una macchina
        di CI lenta non deve produrre un rosso finto -- un falso allarme e' un difetto
        quanto un allarme mancato. Serve a prendere una REGRESSIONE vera, non un secondo
        di scarto. Misurato il 2026-08-11 su questo computer: 2,44 secondi."""
        pv = self.pv()
        self.assertLessEqual(pv.TETTO_SECONDI, 10.0,
                             "il tetto e' stato alzato sopra i 10 secondi: cosi' la "
                             "guardia sulla velocita' non guarda piu' niente")
        uscita, testo, muro = self._esegui("prima_di_lanciare.py")
        detto = re.search(r"CRONOMETRO: ([\d.]+)s", testo)
        self.assertIsNotNone(detto,
                             "il pre-volo non si mette piu' sotto cronometro: senza la "
                             "misura, «deve restare veloce» torna a essere un auspicio")
        self.assertLess(float(detto.group(1)), pv.TETTO_SECONDI * 3,
                        "il pre-volo dichiara %ss contro un tetto di %ss: e' diventato "
                        "lento, e un pre-volo lento viene abbandonato"
                        % (detto.group(1), pv.TETTO_SECONDI))
        self.assertLess(muro, 60.0,
                        "il pre-volo ha impiegato %.1fs di orologio vero: qualcuno gli ha "
                        "fatto fare il lavoro della suite" % muro)

    def test_IL_CRITERIO_DEGLI_SKIP_NON_E_UNA_COPIA(self):
        """⛔ LA MALATTIA DI QUESTO PROGETTO E' LO STESSO FATTO SCRITTO DUE VOLTE, con la
        seconda copia che resta indietro (sei volte in un giorno, il 2026-08-09). Il
        criterio sugli `skipTest` vive in `test_suite_senza_zone_cieche.skip_sospetti` e
        il pre-volo lo CHIAMA. Se qualcuno lo togliesse di li' e lo ricopiasse
        nell'attrezzo, questa guardia non se ne accorgerebbe leggendo il sorgente -- e
        allora si prova al contrario: si costruisce una radice dove quella funzione NON
        c'e' e si pretende che il pre-volo lo DICA invece di arrangiarsi."""
        pv = self.pv()
        cartella = tempfile.mkdtemp()
        try:
            with io.open(os.path.join(cartella, "test_suite_senza_zone_cieche.py"), "w",
                         encoding="utf-8") as f:
                f.write("# una versione senza `skip_sospetti`\n")
            stato, dettaglio = pv.controllo_3_skip_interni(radice=cartella)
            self.assertEqual(
                pv.NON_ESEGUITO, stato,
                "senza `skip_sospetti` il pre-volo dovrebbe fermarsi e dirlo. Se invece "
                "risponde %r vuol dire che si e' fatto una copia propria del criterio, e "
                "una copia resta indietro." % stato)
            self.assertIn("skip_sospetti", dettaglio,
                          "deve dire cosa manca, non solo che qualcosa manca")
        finally:
            shutil.rmtree(cartella, ignore_errors=True)
        # e sulla radice vera la funzione c'e' e risponde
        self.assertEqual(pv.OK, pv.controllo_3_skip_interni(radice=self.RADICE)[0],
                         "sulla radice vera il criterio deve rispondere, non fermarsi")


class TestLeBombeATempo(_GuardieSugliAttrezziDelLavoro):
    """💣 L'attrezzo che trova i test che diventano rossi DA SOLI.

    ⛔ PERCHE' QUESTE GUARDIE, E PERCHE' PROPRIO QUESTE. Il 2026-08-13 ho scritto
    `collaudi/bombe_a_tempo.py` e la prima versione aveva TRE difetti, tutti misurati:
      1. lo scarto d'orologio applicato DUE volte (chiesti 200 giorni, ottenuti 400);
      2. l'orologio di SQLite non spostato -> due test SANI accusati di essere bombe;
      3. i processi figli, che vedono l'ora vera -> un terzo innocente accusato.
    Nessuno dei tre si vede leggendo il codice: si vedono solo confrontando due numeri che
    dovevano coincidere. Queste guardie fissano quei tre confronti, cosi' se qualcuno
    «semplifica» l'orologio i falsi allarmi tornano lo stesso giorno, non fra sei mesi.

    ⛔ E GIRANO IN UN PROCESSO A PARTE. Installare l'orologio finto dentro la suite
    falserebbe tutti gli altri test: questo attrezzo si interroga da FUORI."""

    @classmethod
    def bt(cls):
        return cls._carica("bombe_a_tempo.py", "_bombe_sotto_guardia")

    def _orologio(self, giorni, istante=None):
        """Le date viste dai due orologi, chieste a un processo separato.

        `istante` (secondi dall'epoca) COSTRUISCE l'ora del giorno da provare invece di
        subire quella in cui capita di girare: senza, il difetto del 2026-08-14 si vedeva
        un'ora su ventiquattro -- cioe' quasi mai, e mai in CI (dove l'orologio e' UTC)."""
        argomenti = ["--prova-orologio", str(giorni)]
        if istante is not None:
            argomenti.append(repr(float(istante)))
        uscita, testo, _ = self._esegui("bombe_a_tempo.py", *argomenti)
        self.assertEqual(0, uscita, "la diagnosi dell'orologio e' fallita:\n%s" % testo)
        letti = {}
        for riga in testo.splitlines():
            if " " in riga:
                chiave, _, valore = riga.partition(" ")
                letti[chiave.strip()] = valore.strip()
        return letti

    def test_L_ATTREZZO_SI_VEDE_GRIDARE_E_TACERE_PRIMA_DI_GIUDICARE(self):
        """D18 punto 2. Due test gemelli con la STESSA intenzione: uno con la data cablata,
        uno che la calcola da oggi. Passato il tempo, il primo deve esplodere e il secondo
        no. Un allarme mai visto gridare e' un ornamento."""
        uscita, testo, _ = self._esegui("bombe_a_tempo.py", "--autoprova")
        self.assertEqual(0, uscita,
                         "l'autoprova dell'attrezzo e' fallita: non si comporta come "
                         "promette, quindi non puo' giudicare nessuno.\n%s" % testo[-1500:])
        self.assertIn("COSA QUESTO ATTREZZO NON HA ESAMINATO", testo,
                      "D18 punto 3: deve dichiarare sempre cosa ha lasciato fuori")

    def test_LO_SCARTO_NON_SI_APPLICA_DUE_VOLTE(self):
        """⛔ IL DIFETTO VERO N.1, misurato il 2026-08-13: `date.today()` in CPython chiede
        l'ora a `time.time()`. Spostando ANCHE `date` oltre a `time`, lo scarto si sommava:
        chiesti 200 giorni, ottenuti 400. Un orologio che mente del doppio non trova bombe:
        ne INVENTA."""
        for giorni in (1, 200):
            with self.subTest(giorni=giorni):
                letti = self._orologio(giorni)
                self.assertEqual(
                    letti["atteso"], letti["python_date"],
                    "chiesti %d giorni: `date.today()` dice %s invece di %s. Se la "
                    "differenza e' il DOPPIO dello scarto, qualcuno ha rimesso il patch su "
                    "`datetime.date` sopra quello su `time.time` (difetto del 2026-08-13)."
                    % (giorni, letti["python_date"], letti["atteso"]))
                self.assertEqual(letti["atteso"], letti["python_now"],
                                 "`datetime.now()` non coincide con `date.today()`: i due "
                                 "orologi di Python si sono disallineati fra loro")
                # ⛔ DIFETTO VERO N.5, 2026-08-13: `time.gmtime()` e `time.localtime()`
                # leggono l'orologio di SISTEMA, non `time.time()`. Non spostandoli,
                # `test_dac7_blocco_payout` chiedeva l'anno 2026 mentre i suoi movimenti
                # erano datati 2027, e risultava una bomba pur essendo sano.
                # ⛔ OGNI OROLOGIO CON LA SUA ZONA (difetto del 2026-08-14): `gmtime`
                # risponde in UTC, `localtime` in ora locale. Per un'ora al giorno stanno in
                # giorni DIVERSI, e un solo valore atteso ne accusava uno dei due da
                # innocente -- tre guardie sane rosse a mezzanotte.
                for chiave, zona in (("time_gmtime", "atteso_utc"),
                                     ("time_local", "atteso")):
                    self.assertEqual(
                        letti[zona], letti[chiave],
                        "%s dice %s invece di %s: un pezzo dell'orologio e' rimasto "
                        "indietro, e i test che chiedono l'ANNO da li' verranno accusati "
                        "da innocenti" % (chiave, letti[chiave], letti[zona]))

    def test_L_OROLOGIO_SPOSTA_ANCHE_QUELLO_DENTRO_IL_DATABASE(self):
        """⛔ IL DIFETTO VERO N.2, e vale piu' degli altri: `freezegun` e `time-machine` --
        le due librerie standard di Python -- NON spostano `datetime('now')` di SQLite. E'
        un limite NOTO (fonte in REGISTRO_INGEGNERIA.md, appendice R1). Qui e' costato DUE
        test sani accusati di essere bombe: il test scriveva col nostro orologio e il
        database giudicava col suo."""
        letti = self._orologio(200)
        # `date('now')` di SQLite e' documentato in UTC: va confrontato con l'attesa UTC,
        # non con quella locale (difetto del 2026-08-14).
        self.assertEqual(
            letti["atteso_utc"], letti["sqlite_now"],
            "SQLite vede %s mentre Python vede %s: i due orologi litigano, e ogni test che "
            "chiede l'ora al database verra' accusato di essere una bomba senza esserlo."
            % (letti["sqlite_now"], letti["atteso_utc"]))
        self.assertEqual(
            "2026-07-01", letti["sqlite_fissa"],
            "una data FISSA dentro SQLite si e' mossa: l'attrezzo non sta spostando "
            "l'orologio, sta riscrivendo i dati. Sarebbe molto peggio di non funzionare")

    def test_L_OROLOGIO_REGGE_A_TUTTE_LE_24_ORE_DEL_GIORNO(self):
        """⛔ IL DIFETTO DEL 2026-08-14, e la ragione per cui questa guardia esiste in
        questa forma. Tre guardie SANE sono diventate rosse a mezzanotte: l'attesa si
        calcolava sommando giorni al CALENDARIO locale, mentre l'orologio si sposta in
        SECONDI. Le due aritmetiche divergono a cavallo della mezzanotte.

        ⚠️ E il pezzo che conta piu' del difetto: quella finestra dura UN'ORA su 24, e in CI
        non si apre MAI, perche' li' l'orologio e' UTC. Una guardia che puo' gridare solo in
        quell'ora, e solo sul computer di casa, non e' verificabile a comando -- cioe' e' un
        ornamento (regola dei 10 collaudi). Qui l'ora del giorno si COSTRUISCE (D19) e si
        prova il giro intero: se qualcuno rimette l'aritmetica di calendario, questo diventa
        rosso SUBITO e a qualunque ora, invece che la notte dopo.

        ⛔ E prova anche che servono DUE attese e non una: alle 01:00 `gmtime` e SQLite (UTC)
        stanno in un giorno diverso da `date.today()` e `localtime` (locale). Con un solo
        atteso il difetto non sparirebbe, si sposterebbe di un'ora -- misurato: 23 ore su 24
        coperte invece di 24 su 24."""
        mezzanotte = datetime.datetime.combine(datetime.date.today(), datetime.time(0, 0))
        zone = (("python_date", "atteso"), ("python_now", "atteso"),
                ("time_local", "atteso"), ("time_gmtime", "atteso_utc"),
                ("sqlite_now", "atteso_utc"))
        # Entrambe le distanze del difetto originale: a 1 giorno si vede il salto di
        # mezzanotte, a 200 anche il cambio dell'ora legale (agosto e' UTC+2, marzo UTC+1).
        for ora in range(24):
            istante = (mezzanotte + datetime.timedelta(hours=ora)).timestamp()
            for giorni in (1, 200):
                with self.subTest(ora=ora, giorni=giorni):
                    letti = self._orologio(giorni, istante=istante)
                    for chiave, zona in zone:
                        self.assertEqual(
                            letti[zona], letti[chiave],
                            "alle %02d:00, con %d giorni di scarto, %s dice %s mentre "
                            "l'attesa della SUA zona e' %s: o l'orologio e' rimasto "
                            "indietro, o l'attesa e' tornata a contare giorni di "
                            "calendario invece che secondi."
                            % (ora, giorni, chiave, letti[chiave], letti[zona]))

    def test_UN_TEST_CHE_AVVIA_PROCESSI_ESTERNI_NON_E_GIUDICABILE(self):
        """⛔ IL DIFETTO VERO N.3: il figlio vede l'ora VERA mentre il padre la vede
        spostata, e il disaccordo lo crea l'attrezzo. Un caso cosi' NON va contato fra le
        bombe (sarebbe un innocente) ne' fra i sani (non l'abbiamo giudicato): va
        dichiarato. E' lo sbaglio S7 applicato a questo attrezzo."""
        bt = self.bt()
        self.assertTrue(
            bt.avvia_processi("test_pipeline_ci",
                              "TestIlDeployNonPuoSALTAREIlPassoDiSicurezza", self.RADICE),
            "questa classe avvia davvero processi esterni (lo fa `_esegui`): se l'attrezzo "
            "non se ne accorge, la conta come bomba e accusa un innocente")
        self.assertIn("PROCESSI FIGLI", " ".join(bt.NON_GUARDA),
                      "il limite va DICHIARATO a ogni giro, non solo conosciuto")

    def test_IL_GIUDIZIO_GRIDA_SU_UNA_BOMBA_VICINA_E_TACE_SU_UNA_LONTANA(self):
        """Le due direzioni sul giudizio che legge il PRE-VOLO. Gli schedari sono finti e
        costruiti qui: quello vero non viene mai toccato."""
        bt = self.bt()
        oggi = datetime.date.today()

        def schedario(giorni, misurato=0):
            return {"esito": "OK",
                    "misurato_il": str(oggi - datetime.timedelta(days=misurato)),
                    "commit": "abc1234", "candidati": 150, "file_di_test": 402,
                    "eseguiti": 2670, "non_giudicabili": [],
                    "bombe": [{"test": "test_finto.TestFinto.test_scade",
                               "giorni": giorni, "confine_confermato": True,
                               "esplode_il": str(oggi + datetime.timedelta(days=giorni))}]}

        stato, dettaglio = bt.giudizio_dallo_schedario(schedario(3), oggi=oggi)
        self.assertEqual("ROSSO", stato,
                         "una bomba che esplode fra TRE giorni e il controllo tace: "
                         "e' un ornamento. Ha detto: %s" % dettaglio[:200])
        self.assertIn("test_finto", dettaglio, "deve dire QUALE test, non solo che ce n'e' uno")

        stato_ok, dett_ok = bt.giudizio_dallo_schedario(schedario(200), oggi=oggi)
        self.assertEqual("OK", stato_ok,
                         "una bomba a 200 giorni fa gridare il controllo a ogni pre-volo: "
                         "un allarme sempre acceso viene spento (regola ferrea 10). "
                         "Ha detto: %s" % dett_ok[:200])

        # ⛔ DUE BOMBE LO STESSO GIORNO: difetto VERO del 2026-08-13, trovato dal giro vero e
        # non da questa guardia, che allora provava una bomba SOLA. `vicine.sort()` su
        # coppie (giorni, dizionario) confronta i dizionari quando i giorni pareggiano, e
        # scoppia con TypeError -- cioe' il controllo NON dice «attento», dice «non ho
        # misurato». E' successo davvero: `test_ical_export` ha DUE test che scadono lo
        # stesso giorno, ed e' il caso piu' normale del mondo, non un caso limite.
        doppia = schedario(5)
        doppia["bombe"].append(dict(doppia["bombe"][0], test="test_finto.TestFinto.test_2"))
        stato_doppio, dett_doppio = bt.giudizio_dallo_schedario(doppia, oggi=oggi)
        self.assertEqual("ROSSO", stato_doppio,
                         "con DUE bombe che scadono lo stesso giorno il giudizio deve "
                         "gridare come con una: se qui esce NON ESEGUITO, l'ordinamento sta "
                         "confrontando i dizionari. Ha detto: %s" % dett_doppio[:200])
        self.assertIn("test_finto.TestFinto.test_2", dett_doppio,
                      "deve elencarle TUTTE e due: perderne una per strada e' una zona "
                      "cieca con l'aspetto della copertura")

        # il confine esatto, misurato dalla soglia dichiarata e non da una cifra a mano
        soglia = bt.GIORNI_ALLARME
        self.assertEqual("ROSSO", bt.giudizio_dallo_schedario(schedario(soglia), oggi=oggi)[0],
                         "sulla soglia esatta (%d giorni) deve gridare" % soglia)
        self.assertEqual("OK", bt.giudizio_dallo_schedario(schedario(soglia + 1),
                                                          oggi=oggi)[0],
                         "un giorno oltre la soglia deve tacere")

    def test_UNO_SCHEDARIO_VECCHIO_E_ROSSO_E_SENZA_SCHEDARIO_E_NON_ESEGUITO(self):
        """⛔ Le due porte da cui rientrerebbe il difetto. Una misura scaduta non e' una
        misura (D22), e un controllo senza dati non e' verde: e' NON ESEGUITO (S7)."""
        bt = self.bt()
        oggi = datetime.date.today()
        vecchio = {"esito": "OK", "commit": "abc1234", "bombe": [], "non_giudicabili": [],
                   "candidati": 150, "file_di_test": 402, "eseguiti": 2670,
                   "misurato_il": str(oggi - datetime.timedelta(
                       days=bt.GIORNI_SCHEDARIO_VECCHIO + 1))}
        stato, dettaglio = bt.giudizio_dallo_schedario(vecchio, oggi=oggi)
        self.assertEqual("ROSSO", stato,
                         "uno schedario piu' vecchio della soglia deve gridare: se tace, "
                         "il controllo continua a rassicurare su una misura scaduta")
        self.assertIn("ricordo", dettaglio, "deve dire PERCHE', non solo che e' vecchio")

        fresco = dict(vecchio, misurato_il=str(oggi))
        self.assertEqual("OK", bt.giudizio_dallo_schedario(fresco, oggi=oggi)[0],
                         "su uno schedario fresco e senza bombe deve tacere")

        self.assertEqual("NON ESEGUITO", bt.giudizio_dallo_schedario(None, oggi=oggi)[0],
                         "senza schedario il controllo non ha misurato niente: chiamarlo "
                         "verde sarebbe il verde peggiore di tutti (S7)")
        rossi_prima = {"esito": "NON ESEGUITO", "misurato_il": str(oggi),
                       "rossi_a_orologio_fermo": ["test_x.T.test_y"], "bombe": []}
        self.assertEqual("NON ESEGUITO",
                         bt.giudizio_dallo_schedario(rossi_prima, oggi=oggi)[0],
                         "se a orologio FERMO qualcosa era gia' rosso, il verdetto sul "
                         "tempo non vale: non si saprebbe chi ha causato il rosso")

    def test_IL_CONTROLLO_7_DEL_PREVOLO_CHIEDE_IL_GIUDIZIO_A_QUESTO_ATTREZZO(self):
        """⛔ REGOLA #23, «COSTRUITO ≠ COLLEGATO». Il pezzo che conta non e' l'attrezzo: e'
        che il pre-volo lo CHIAMI. E deve chiamarlo, non ricopiarne il criterio -- una
        copia resta indietro il giorno che il criterio cambia (gia' pagato sei volte)."""
        pv = self.pv()
        numeri = [n for n, _, _ in pv.CONTROLLI]
        self.assertIn(7, numeri,
                      "il controllo 7 e' sparito dal pre-volo: le bombe a tempo tornerebbero "
                      "a essere scoperte solo a mezzanotte, da un rosso misterioso")
        oggi = datetime.date.today()
        finto = {"esito": "OK", "misurato_il": str(oggi), "commit": "abc1234",
                 "candidati": 1, "file_di_test": 1, "eseguiti": 1, "non_giudicabili": [],
                 "bombe": [{"test": "test_iniettato.T.test_scade", "giorni": 1,
                            "confine_confermato": True,
                            "esplode_il": str(oggi + datetime.timedelta(days=1))}]}
        stato, dettaglio = pv.controllo_7_bombe_a_tempo(radice=self.RADICE,
                                                        schedario=finto)
        self.assertEqual(pv.ROSSO, stato,
                         "col guasto dentro (una bomba che esplode domani) il pre-volo NON "
                         "grida: e' un ornamento. Ha detto: %s" % dettaglio[:200])
        self.assertIn("test_iniettato", dettaglio,
                      "il pre-volo deve riportare il giudizio VERO, non riassumerlo")


class TestIlPreFattoVedeIProblemiPRIMA(_GuardieSugliAttrezziDelLavoro):
    """🛬 I tre controlli che l'11 agosto sono stati fatti A MANO, o non fatti affatto."""

    def test_CONTROLLO_7_UN_ATTREZZO_ORFANO_E_UN_ROSSO(self):
        """Il caso vero: un E2E contro Stripe VERO da 11 KB -- l'unico collaudo che prova i
        crediti contro Stripe vero -- rimasto fuori dal repository e ritrovato PER FORTUNA,
        rileggendo. Nessuna guardia lo vedeva."""
        pf = self.pf()
        cartella = tempfile.mkdtemp()
        try:
            with io.open(os.path.join(cartella, "attrezzo_mai_portato_dentro.py"), "w",
                         encoding="utf-8") as f:
                f.write("# lavoro che il giorno che serve non c'e'\n")
            stato, dettaglio = pf.controllo_8_artefatti_fuori(radice=self.RADICE,
                                                              cartelle=[cartella])
            self.assertEqual(pf.ROSSO, stato,
                             "un `.py` fuori dal repository, senza nessun file con quel "
                             "nome dentro, deve essere un ROSSO: %s" % dettaglio[:300])
            self.assertIn("attrezzo_mai_portato_dentro.py", dettaglio,
                          "deve dire QUALE file, altrimenti non serve a niente")
            # ── L'ALTRA DIREZIONE, e il 2026-08-19 ha cambiato il requisito ──────────────
            # Fino a quel giorno qui bastava il NOME: «un nome che esiste gia' nel
            # repository non e' un orfano». Sembrava prudenza contro i falsi allarmi, ed era
            # una porta aperta: la copia fuori puo' avere lo stesso nome e contenuto
            # **VECCHIO**. E' successo davvero -- due attrezzi del Desktop hanno
            # sovrascritto in `collaudi/` riparazioni gia' fatte, rimettendo un percorso
            # cablato -- e questo controllo taceva, perche' guardava il nome.
            # ⛔ Il requisito nuovo separa le due cose, e tiene tutt'e due le direzioni:
            #     · stesso nome, contenuto IDENTICO  -> OK   (niente falsi allarmi)
            #     · stesso nome, contenuto DIVERSO   -> ROSSO (candidato a sovrascrivere)
            os.remove(os.path.join(cartella, "attrezzo_mai_portato_dentro.py"))
            vero = os.path.join(self.RADICE, "collaudi", "guardia_commit.py")
            with io.open(vero, "rb") as f:
                identico = f.read()
            with io.open(os.path.join(cartella, "guardia_commit.py"), "wb") as f:
                f.write(identico)
            self.assertEqual(
                pf.OK,
                pf.controllo_8_artefatti_fuori(radice=self.RADICE, cartelle=[cartella])[0],
                "una copia IDENTICA byte per byte non e' un pericolo: gridare qui sarebbe "
                "un falso allarme a ogni commit, e un allarme che grida sempre viene spento")
            with io.open(os.path.join(cartella, "guardia_commit.py"), "wb") as f:
                f.write(identico + b"\n# riga in piu': ora la copia NON e' piu' quella\n")
            stato2, dett2 = pf.controllo_8_artefatti_fuori(radice=self.RADICE,
                                                           cartelle=[cartella])
            self.assertEqual(
                pf.ROSSO, stato2,
                "una copia con lo STESSO NOME e CONTENUTO DIVERSO deve gridare: e' quella "
                "che il 2026-08-19 ha sovrascritto due riparazioni gia' fatte. Ha detto: %s"
                % dett2[:200])
            self.assertIn("CONTENUTO DIVERSO", dett2,
                          "deve dire PERCHE' grida, se no chi legge pensa a un orfano")
        finally:
            shutil.rmtree(cartella, ignore_errors=True)

    def test_CONTROLLO_8_LO_SCOPO_CHE_SI_ALLARGA_DA_SOLO(self):
        """Regola ferrea 15. «Avevo dichiarato due file, ne ho toccati quattro. Il lavoro
        in piu' era buono, ma uno scopo che si allarga da solo e' il canale principale
        delle regressioni.»"""
        pf = self.pf()
        casi = (
            ("toccato un file fuori elenco", ["a.py"], ["a.py", "fase83_server.py"],
             pf.ROSSO),
            ("toccati esattamente quelli dichiarati", ["a.py", "b/c.py"],
             ["b/c.py", "a.py"], pf.OK),
            ("dichiarato in piu' e non toccato: NOTA, non rosso", ["a.py", "b.py"],
             ["a.py"], pf.OK),
            ("le barre di Windows non fanno un falso rosso", [r"collaudi\x.py"],
             ["collaudi/x.py"], pf.OK),
        )
        for nome, dichiarati, toccati, atteso in casi:
            with self.subTest(caso=nome):
                stato, dettaglio = pf.controllo_9_scopo(
                    radice=self.RADICE, dichiarati=dichiarati, toccati=toccati)
                self.assertEqual(atteso, stato, "%s -> %s: %s"
                                 % (nome, stato, dettaglio[:300]))
        # ⛔ La traccia si punta a un percorso CHE NON ESISTE. La prima versione di questa
        # guardia leggeva la traccia VERA della macchina: verde su questo computer (dove
        # uno scopo era stato dichiarato) e rossa in CI. Un test che dipende da dove lo
        # lanci e' la forma piu' subdola di verde finto (S11).
        cartella = tempfile.mkdtemp()
        try:
            mai = os.path.join(cartella, "nessuna-traccia.txt")
            senza, dettaglio = pf.controllo_9_scopo(radice=self.RADICE, dichiarati=None,
                                                    toccati=["a.py"], traccia=mai)
        finally:
            shutil.rmtree(cartella, ignore_errors=True)
        self.assertEqual(pf.NON_ESEGUITO, senza,
                         "senza scopo dichiarato non si puo' giudicare: e' NON ESEGUITO, "
                         "che non e' un successo (S7). Rispondere OK sarebbe il verde "
                         "peggiore di tutti")
        self.assertIn("prima_di_lanciare.py --scopo", dettaglio,
                      "un blocco deve dire come si sblocca, altrimenti viene aggirato")

    def test_CONTROLLO_9_IL_MESSAGGIO_DI_COMMIT_NELLE_DUE_DIREZIONI(self):
        pf = self.pf()
        buono = ("un lavoro vero\n\nCo-Authored-By: Claude Opus 5 (1M context) "
                 "<noreply@anthropic.com>\n")
        casi = (
            ("un messaggio in ordine", buono, pf.OK),
            ("vuoto", "\n# solo commenti di git\n", pf.ROSSO),
            ("con un segnaposto", buono.replace("un lavoro vero", "__DA_RIEMPIRE__"),
             pf.ROSSO),
            ("con caratteri non-ASCII", buono.replace("vero", "vero \u2014 ecco"),
             pf.ROSSO),
            ("senza la firma", "un lavoro senza firma\n", pf.ROSSO),
            ("una fusione non ha bisogno della firma",
             "Merge pull request #28 from edilmax/ramo\n", pf.OK),
            ("le righe commentate da git non contano",
             buono + "\n# __DA_RIEMPIRE__ questa la mette git\n", pf.OK),
        )
        for nome, testo, atteso in casi:
            with self.subTest(caso=nome):
                stato, dettaglio = pf.controllo_9_messaggio(testo=testo)
                self.assertEqual(atteso, stato, "%s -> %s: %s"
                                 % (nome, stato, dettaglio[:300]))

    def test_IL_PATH_NON_SI_CONFRONTA_MA_IL_RESTO_SI(self):
        """⛔ LA GUARDIA CHE IMPEDISCE ALLA RINUNCIA DI DIVENTARE UNA ZONA CIECA.

        Il 2026-08-11, al primo giro vero dentro il gancio `pre-commit`, il controllo
        sull'ambiente e' uscito ROSSO: i ganci di git girano sotto `sh`, dove Git per
        Windows porta `/mingw64/bin/openssl`, mentre da PowerShell -- la shell da cui
        parte la suite -- openssl non c'e'. La stessa domanda, due risposte opposte: e' lo
        sbaglio S11 preso dallo strumento su se stesso.

        La cura e' stata spegnere il confronto sul PATH nel solo pre-fatto. Una cura
        cosi' e' pericolosa: la prossima «semplificazione» potrebbe spegnere tutto il
        controllo, e nessuno se ne accorgerebbe perche' resterebbe verde. Qui si pretende
        che il pre-fatto abbia perso SOLO il PATH e continui a vedere tutto il resto.

        ⛔ E QUESTA GUARDIA HA GIA' SBAGLIATO UNA VOLTA, il 2026-08-11: era VERDE su
        Windows e ROSSA in CI. Una delle tre asserzioni non iniettava la versione di
        Python e usava quella vera: su questo computer e' esattamente la `3.9.10`
        dichiarata, su Linux no. Da qui la regola: **si iniettano TUTTI i valori
        dell'ambiente, anche quelli che qui sarebbero giusti.** Un valore vero lasciato
        passare lega la guardia alla macchina su cui gira, ed e' la forma piu' subdola di
        verde finto -- quella che si scopre solo davanti al giudice (regola ferrea 8).
        """
        pv, pf = self.pv(), self.pf()
        sana = self._pagina_sana()
        atteso = re.search(r"Python (\d+\.\d+\.\d+)", sana)
        self.assertIsNotNone(atteso, "la riga AMBIENTE non dichiara piu' un Python: "
                                     "questa guardia non avrebbe piu' niente da iniettare")
        # La macchina ESATTAMENTE come la dichiara il documento, costruita a mano: cosi'
        # questa guardia dice la stessa cosa su Windows, su Linux e su qualunque Python.
        sano = dict(pagina=sana, radice=self.RADICE, confronta_path=False,
                    quale_python=atteso.group(1), quale_openssl=True,
                    moduli_presenti={"hypothesis", "yaml", "coverage"})

        stato, dettaglio = pv.controllo_4_ambiente(**sano)
        self.assertEqual(pv.OK, stato,
                         "col PATH spento openssl non deve piu' contare: %s"
                         % dettaglio[:300])
        self.assertIn("NON ho confrontato il PATH", dettaglio,
                      "una rinuncia si DICHIARA (D18 punto 3): un taglio silenzioso fa "
                      "sembrare «coperto» cio' che non e' stato guardato")

        # ⛔ E NON BASTA CHE SIA ROSSO: si pretende che sia rosso PER QUESTO. Un allarme
        # che suona per il motivo sbagliato passerebbe lo stesso, e la rinuncia sul PATH
        # potrebbe essersi mangiata il resto senza che nessuno se ne accorga.
        stato, dettaglio = pv.controllo_4_ambiente(**dict(sano, quale_python="0.0.0"))
        self.assertEqual(pv.ROSSO, stato,
                         "col PATH spento il controllo non vede piu' nemmeno un Python "
                         "sbagliato: non e' stato ristretto, e' stato accecato")
        self.assertIn("Python dichiarato", dettaglio,
                      "e' rosso, ma non per il Python: %s" % dettaglio[:300])

        stato, dettaglio = pv.controllo_4_ambiente(**dict(sano, moduli_presenti=set()))
        self.assertEqual(pv.ROSSO, stato,
                         "col PATH spento non vede piu' una libreria dichiarata e assente")
        self.assertIn("non si importa", dettaglio,
                      "e' rosso, ma non per la libreria mancante: %s" % dettaglio[:300])

        numeri = [n for n, _, _ in pf.CONTROLLI]
        # ⛔ IL 9 MANCA DI PROPOSITO, e non e' una dimenticanza: `controllo_9_messaggio` vive
        # FUORI da `CONTROLLI` perche' gira sul gancio `commit-msg`, l'unico a cui git passa
        # il messaggio. E l'elenco e' ESATTO, non un minimo: un `assertGreaterEqual` qui
        # lascerebbe sparire un controllo in silenzio.
        self.assertEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], sorted(numeri),
                         "i controlli del pre-fatto non sono quelli attesi: %r. Se ne hai "
                         "aggiunto uno, aggiorna questo elenco nello stesso commit; se ne e' "
                         "sparito uno, il pre-fatto ha smesso di guardare qualcosa"
                         % (numeri,))

    def test_STAMPA_I_SEI_DIVIETI_DOPO_AVER_FINITO(self):
        """«Si rileggono prima di iniziare un'operazione E DOPO averla finita, cosi' la
        fine di un lavoro non diventa l'inizio di una violazione.» Il pre-fatto e' il
        «dopo»: gira quando si sta per salvare, cioe' quando B1 e B4 contano di piu'."""
        uscita, testo, _ = self._esegui("prima_di_dire_fatto.py")
        for divieto in ("B1.", "B2.", "B3.", "B4.", "B5.", "B6."):
            self.assertIn(divieto, testo,
                          "il pre-fatto non stampa piu' %s" % divieto)
        self.assertLess(
            testo.index("PRE-FATTO"), testo.index("B1."),
            "nel pre-fatto i divieti vanno DOPO i controlli: e' il momento del «dopo "
            "averla finita»")

    def test_IL_PRE_FATTO_RILEGGE_ANCHE_LA_BATTERIA(self):
        """⛔ D24, dettata dal fondatore il 2026-08-12: «leggere prima e dopo tutte le regole
        E I TEST e quelli esterni prima e dopo ogni operazione».

        I sei divieti li stampava gia'. Mancava LA BATTERIA -- ed e' la differenza fra «non ho
        violato un divieto» e «ho dimostrato che funziona»: quel giorno avevo scritto «provata
        nelle due direzioni» avendo passato i livelli ① e ② e **zero** dei dieci collaudi, col
        giudice esterno e la CI mai sfiorati.
        ⛔ E QUI SI DICHIARA IL DENOMINATORE (appendice #15): non «c'e' un collaudo?», ma «ci
        sono TUTTI?». I nomi si contano da `CLAUDE.md` con un conto INDIPENDENTE, non con la
        funzione che si sta giudicando -- se no il confronto sarebbe con se stesso.
        """
        import io
        import os
        import re
        import shutil
        import tempfile
        from collaudi import prima_di_dire_fatto as pf

        with io.open(os.path.join(QUI, "CLAUDE.md"), encoding="utf-8") as f:
            coda = f.read().split("I 10 COLLAUDI, IN QUEST'ORDINE")[-1]
        nomi = [n.strip().replace("**", "") for _num, n, _c
                in re.findall(r"^\|\s*(\d+)\s*\|([^|]+)\|([^|]+)\|", coda, re.M)]
        self.assertGreaterEqual(
            len(nomi), 10,
            "in CLAUDE.md trovo solo %d collaudi nella tabella: il denominatore di questa "
            "guardia non regge piu', e senza denominatore non so quanti ne ha saltati il "
            "pre-fatto" % len(nomi))

        uscita, testo, _ = self._esegui("prima_di_dire_fatto.py")
        self.assertIn("E LA BATTERIA?", testo,
                      "il pre-fatto non rilegge piu' la batteria: D24 e' tornata a dipendere "
                      "dal ricordarsene, e un obbligo affidato alla memoria si rompe di nuovo")
        mancanti = [n for n in nomi if n[:25] not in testo]
        self.assertEqual(
            [], mancanti,
            "il pre-fatto stampa la batteria ma ne SALTA %d: %s. Un promemoria incompleto e' "
            "peggio di nessun promemoria, perche' chi lo legge crede di aver visto tutto"
            % (len(mancanti), ", ".join(mancanti)))
        for esterno in ("GIUDICE ESTERNO", "CI SU LINUX"):
            self.assertIn(esterno, testo,
                          "manca il promemoria su «%s»: sono le DUE cose che questo computer "
                          "non puo' dare da solo, ed e' la meta' dell'ordine del fondatore "
                          "(«e quelli esterni»)" % esterno)
        self.assertLess(
            testo.index("B1."), testo.index("E LA BATTERIA?"),
            "la batteria va DOPO i sei divieti: prima quello che vieta, poi quello che "
            "dimostra")

        # LE DUE DIREZIONI: senza la tabella il promemoria deve GRIDARE, non tacere.
        cartella = tempfile.mkdtemp()
        try:
            with io.open(os.path.join(cartella, "CLAUDE.md"), "w", encoding="utf-8") as f:
                f.write("un CLAUDE.md senza la tabella dei collaudi\n")
            self.assertEqual(
                [], pf.batteria_dal_regolamento(cartella),
                "su un CLAUDE.md senza la tabella la funzione inventa delle righe: allora "
                "non le sta leggendo dal regolamento")
            self.assertEqual(
                [], pf.batteria_dal_regolamento(os.path.join(cartella, "non-esiste")),
                "su una cartella inesistente deve dire «niente», non esplodere: il pre-fatto "
                "gira dentro un gancio di git e un traceback li' blocca il commit per il "
                "motivo sbagliato (e' gia' successo il 2026-08-02)")
        finally:
            shutil.rmtree(cartella, ignore_errors=True)

    def test_IL_CODICE_D_USCITA_NON_PUO_MENTIRE_SUL_RAPPORTO(self):
        """Lo stesso controllo anti-imbroglio del pre-volo, sul pre-fatto."""
        uscita, testo, _ = self._esegui("prima_di_dire_fatto.py")
        corpo = testo.split("COSA QUESTO CONTROLLO NON HA ESAMINATO")[0]
        guasti = (len(re.findall(r"^  ROSSO ", corpo, re.M))
                  + len(re.findall(r"^  NON ESEGUITO ", corpo, re.M)))
        self.assertEqual(
            0 if guasti == 0 else 1, uscita,
            "il rapporto elenca %d fra rossi e non-eseguiti, ma lo strumento e' uscito "
            "%d: l'uscita deve seguire il rapporto.\n%s" % (guasti, uscita, testo[-1500:]))


class TestIGanciDiGitCHIAMANODavveroGliAttrezzi(_GuardieSugliAttrezziDelLavoro):
    """⛔ UN CONTROLLO CORRETTO CHE NESSUNO CHIAMA NON E' UN CONTROLLO.

    E' la lezione piu' cara del 2026-08-11, imparata due volte nello stesso giorno: il
    gancio pre-commit era SPENTO, e il protocollo di deploy era FACOLTATIVO. Tutti e due
    scritti bene. Qui i ganci si ESEGUONO per davvero -- una guardia che cercasse il nome
    dell'attrezzo dentro lo script la soddisferebbe anche un commento (S6).
    """

    @staticmethod
    def _trova_sh():
        """`sh` NON e' nel PATH di PowerShell su questa macchina, ma ESISTE: Git per
        Windows se lo porta dietro. Arrendersi al primo `which` metterebbe da parte queste
        guardie proprio dove si lavora (S11).
        ⛔ `bash` di C:\\Windows\\system32 e' WSL: un'altra macchina. Non si usa."""
        trovato = shutil.which("sh")
        if trovato:
            return trovato
        git = shutil.which("git")
        if git:
            base = os.path.dirname(os.path.dirname(git))
            for rel in (("bin", "sh.exe"), ("usr", "bin", "sh.exe")):
                p = os.path.join(base, *rel)
                if os.path.exists(p):
                    return p
        return ""

    def setUp(self):
        self.sh = self._trova_sh()

    def _sorgente(self, gancio):
        with io.open(os.path.join(self.RADICE, "deploy", "hooks", gancio),
                     encoding="utf-8") as f:
            return f.read()

    def _senza_sh(self, gancio, atteso):
        """RAMO POVERO, e sta qui invece di uno `skipTest`. Saltare farebbe sparire questa
        guardia dal rapporto come «skipped» e nessuno la leggerebbe piu'; e il motivo «sh
        non installato» passerebbe pure per ambientale, cioe' basterebbe una PAROLA per
        zittirla. Si asserisce lo stesso qualcosa di vero, dichiarando che e' piu' debole:
        questa legge il sorgente, e un sorgente lo soddisfa anche un commento (S6)."""
        self.assertIn(atteso, self._sorgente(gancio),
                      "il gancio %s non nomina piu' %r" % (gancio, atteso))

    def test_I_GANCI_SONO_ASCII_PURO(self):
        """Girano su macchine, shell e lingue diverse: e' l'ultimo posto dove si vuole
        scoprire un problema di codifica. Il 2026-08-02 il programma chiamato dal gancio
        e' ESPLOSO su un simbolo non-ASCII, mostrando un traceback al posto delle
        istruzioni -- e un blocco che non dice come si sblocca viene aggirato."""
        for gancio in ("pre-commit", "commit-msg"):
            with self.subTest(gancio=gancio):
                with io.open(os.path.join(self.RADICE, "deploy", "hooks", gancio),
                             "rb") as f:
                    dati = f.read()
                cattivi = sorted({b for b in dati if b > 127 or (b < 32
                                                                 and b not in (9, 10, 13))})
                self.assertEqual([], cattivi,
                                 "%s contiene byte fuori dall'ASCII: %r" % (gancio, cattivi))

    def test_IL_GANCIO_COMMIT_MSG_RIFIUTA_E_ACCETTA(self):
        """Le due direzioni, sul gancio ESEGUITO. E' l'unico gancio a cui git passa il
        messaggio: al `pre-commit` non esiste ancora."""
        if not self.sh:
            return self._senza_sh("commit-msg", "--messaggio")
        cartella = tempfile.mkdtemp()
        try:
            buono = os.path.join(cartella, "buono.txt")
            with io.open(buono, "w", encoding="utf-8") as f:
                f.write("un lavoro vero\n\nCo-Authored-By: Claude Opus 5 (1M context) "
                        "<noreply@anthropic.com>\n")
            e = subprocess.run([self.sh, "deploy/hooks/commit-msg", buono],
                               cwd=self.RADICE, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT)
            self.assertEqual(0, e.returncode,
                             "un messaggio in ordine deve passare: %r"
                             % e.stdout.decode("utf-8", "replace")[-400:])
            cattivo = os.path.join(cartella, "cattivo.txt")
            with io.open(cattivo, "w", encoding="utf-8") as f:
                f.write("un lavoro senza firma\n")
            e = subprocess.run([self.sh, "deploy/hooks/commit-msg", cattivo],
                               cwd=self.RADICE, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT)
            testo = e.stdout.decode("utf-8", "replace")
            self.assertNotEqual(0, e.returncode,
                                "un messaggio senza firma non deve passare: %r"
                                % testo[-400:])
            self.assertIn("Co-Authored-By", testo,
                          "deve dire COSA manca, non solo che qualcosa non va")
        finally:
            shutil.rmtree(cartella, ignore_errors=True)

    def test_IL_GANCIO_PRE_COMMIT_CHIAMA_DAVVERO_IL_PRE_FATTO(self):
        """Non si cerca il nome nello script: si guarda se nell'uscita compare il rapporto
        del pre-fatto. Quello lo puo' produrre solo l'attrezzo eseguito davvero."""
        if not self.sh:
            return self._senza_sh("pre-commit", "prima_di_dire_fatto.py")
        e = subprocess.run([self.sh, "deploy/hooks/pre-commit"], cwd=self.RADICE,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        testo = e.stdout.decode("utf-8", "replace")
        self.assertIn("PRE-FATTO", testo,
                      "il gancio pre-commit non esegue il pre-fatto: un controllo che "
                      "nessuno chiama non e' un controllo.\n%s" % testo[-800:])
        self.assertRegex(testo, r"\b8\. ",
                         "il rapporto del pre-fatto arriva monco: manca il controllo 8")

    def test_IL_PRE_COMMIT_SI_FERMA_PRIMA_SE_UNA_MUTAZIONE_E_APERTA(self):
        """L'ORDINE CONTA, e qui si dimostra. Se un giro di mutazione e' rimasto aperto, un
        file di PRODUZIONE puo' contenere un guasto messo di proposito: il gancio deve
        fermarsi SUBITO, senza nemmeno arrivare agli altri otto controlli.

        La traccia finta si costruisce in una cartella temporanea e si punta lo strumento
        li' con `TMP`/`TEMP` (`tempfile.gettempdir()` li legge): la traccia VERA non viene
        mai toccata -- crearla per davvero bloccherebbe i commit di chi lavora."""
        if not self.sh:
            return self._senza_sh("pre-commit", "guardia_commit.py")
        cartella = tempfile.mkdtemp()
        try:
            # ⛔ IL NOME LO CHIEDE ALLO STRUMENTO, non lo scrive a mano. Scritto qui era una
            # QUARTA copia della stessa regola: il 2026-08-27, rendendo le tracce distinte
            # per worktree, `guardia_commit` ha smesso di trovare questa cartella e il
            # controllo 5 ha detto «nessun giro aperto» su un giro APERTO. Il gancio si
            # fermava lo stesso, ma per un altro motivo -- cioe' sembrava protetto senza
            # aver guardato niente. Chiedendo il nome, il test segue la formula da solo.
            nome_traccia = os.path.basename(
                self._carica("guardia_commit.py", "_gc_nome_traccia").TRACCIA)
            os.makedirs(os.path.join(cartella, nome_traccia))
            amb = dict(os.environ)
            amb["TMP"] = amb["TEMP"] = amb["TMPDIR"] = cartella
            e = subprocess.run([self.sh, "deploy/hooks/pre-commit"], cwd=self.RADICE,
                               env=amb, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            testo = e.stdout.decode("utf-8", "replace")
            self.assertNotEqual(0, e.returncode,
                                "con un giro di mutazione aperto il gancio deve fermare "
                                "il salvataggio: %r" % testo[-400:])
            self.assertIn("SALVATAGGIO BLOCCATO", testo,
                          "deve dire perche' si e' fermato: %r" % testo[-400:])
            self.assertNotIn(
                "PRE-FATTO", testo,
                "il gancio e' arrivato al pre-fatto nonostante la mutazione aperta: i due "
                "controlli non sono in serie, e il primo non ferma piu' niente")
        finally:
            shutil.rmtree(cartella, ignore_errors=True)


class TestIlGuardianoDelPianoDeiSoldiHaANCORAIDENTI(unittest.TestCase):
    """D18 PUNTO 4 — se qualcuno lo smonta, qualcosa diventa rosso LO STESSO GIORNO.

    `test_piano_dei_soldi.py` impedisce due difetti capitati davvero: un modulo dichiarato
    FATTO in un posto e DA FARE in un altro (2026-08-12, sarebbe costato una sessione intera
    a rifare `fase66`), e un modulo «da fare» che e' codice morto (2026-08-11, `fase43` con
    31 punti di mutazione su codice che la produzione non raggiunge).

    ⛔ PERCHE' QUESTA GUARDIA ESISTE, e non basta il guardiano stesso. Un attrezzo che
    protegge se stesso non protegge niente: se il file viene cancellato in una
    «semplificazione», con lui spariscono i suoi 14 collaudi e **nessuno se ne accorge**.
    Qui l'`import` fallisce e la suite diventa rossa subito.
    ⛔ E NON CONTA PAROLE NEL SORGENTE: chiama le funzioni del giudizio con il guasto dentro.
    Una guardia che cercasse `contraddizioni` nel testo del file la soddisferebbe anche un
    commento (sbaglio S6).
    """

    def test_IL_GIUDIZIO_SA_DIRE_SI_E_NO(self):
        """Le due direzioni sul giudizio nudo, senza passare dai documenti."""
        from collaudi import piano_dei_soldi as pds
        rotto = [("fase901", pds.FATTO, "posto A"), ("fase901", pds.DA_FARE, "posto B")]
        self.assertIn(
            "fase901", pds.contraddizioni(rotto),
            "il giudizio non vede piu' lo stesso modulo dichiarato FATTO in un posto e DA "
            "FARE in un altro: e' il difetto del 2026-08-12, e senza questo una chat nuova "
            "rifa' da capo un lavoro finito")
        self.assertEqual(
            {}, pds.contraddizioni([("fase901", pds.FATTO, "posto A"),
                                    ("fase901", pds.FATTO, "posto B")]),
            "grida anche quando i posti sono D'ACCORDO: un allarme sempre acceso viene "
            "spento (regola ferrea 10)")
        self.assertEqual(
            ["fase902"],
            pds.da_fare_ma_morti([("fase902", pds.DA_FARE, "posto A")], ["fase902_x"]),
            "il giudizio non incrocia piu' il piano con la raggiungibilita': e' il difetto "
            "dell'11 agosto, 31 punti di lavoro su codice morto")
        self.assertEqual(
            [], pds.da_fare_ma_morti([("fase902", pds.DA_FARE, "posto A")], ["fase903_x"]),
            "dice morto un modulo che non e' nell'elenco dei morti")

    def test_I_TRE_POSTI_VERI_SONO_ANCORA_LEGGIBILI_E_D_ACCORDO(self):
        """Il giudizio sano non basta: va provato che i documenti VERI lo attraversino.

        Se un'ancora non si trovasse piu' (prosa riscritta, sezione spostata), gli estrattori
        alzano `MisuraNonValida` e questo test e' rosso -- che e' il verso giusto: un
        guardiano che sui documenti riscritti resta verde e' peggio di nessun guardiano,
        perche' rassicura senza aver guardato (sbaglio S1).
        """
        from collaudi import piano_dei_soldi as pds
        tutte = pds.osservazioni(pds.leggi(pds.REGISTRO), pds.leggi(pds.CONSEGNE))
        distinti = set(m for m, _s, _d in tutte)
        self.assertGreaterEqual(
            len(distinti), 15,
            "il guardiano legge solo %d moduli dai tre posti: al 2026-08-12 erano 20 (6 "
            "fatti + 11 da fare + 3 morti). Un denominatore che crolla e' un controllo che "
            "ha smesso di guardare, non un piano che si e' accorciato" % len(distinti))
        self.assertEqual(
            {}, pds.contraddizioni(tutte),
            "i tre posti del piano dei soldi si contraddicono: esegui "
            "`python collaudi/piano_dei_soldi.py` per il dettaglio, modulo per modulo")

    def test_IL_CONTROLLO_10_DEL_PRE_FATTO_FERMA_DAVVERO_IL_COMMIT(self):
        """⛔ IL GIUDIZIO GIUSTO IN UN POSTO CHE NESSUNO INTERROGA NON FERMA NIENTE.

        Fino al 2026-08-12 il guardiano viveva SOLO nella suite, cioe' dentro un ciclo da
        ~25 minuti: si POTEVA committare un piano contraddittorio e lo si scopriva mezz'ora
        dopo, o alla CI dopo il push. Questa guardia pretende che il pre-fatto -- quello che
        i ganci di git chiamano da soli -- abbia il controllo E che sappia dire SI e NO.
        ⛔ Non conta parole nel sorgente: CHIAMA il controllo col guasto dentro (S6).
        """
        from collaudi import piano_dei_soldi as pds
        from collaudi import prima_di_dire_fatto as pf

        sano_reg = ("\U0001f4ca **DOVE SIAMO, rimisurato col censimento il 2026-01-01**:\n"
                    "**1 moduli dei soldi giudicati** · **1 che restano, per 24 punti**. "
                    "uno sono stati fatti (`fase901`) e **uno e' codice\nmorto** "
                    "(`fase903` 31 = **31 punti che non vanno fatti**).\n\n"
                    "| **1** | ✅ `fase901_a` **FATTO** · ▶️ `fase902_b` (24) | 24 |\n\n")
        sano_con = ("**Moduli dei SOLDI GIÀ passati dal giudice — 1:**\n"
                    "✅ **`fase901_a`** (11 su 11).\n\n"
                    "**Moduli dei SOLDI CHE RESTANO — 1, per 24 punti.**\n\n"
                    "| `fase902_b` | 24 | **2** | 1 |\n\n"
                    "⛔ **FUORI DALL'ELENCO PERCHÈ SONO CODICE MORTO**:\n"
                    "`fase903_c` (31) = **31 punti che NON vanno fatti**.\n\n")

        stato, dettaglio = pf.controllo_10_piano_dei_soldi(
            registro=sano_reg, consegne=sano_con, morti=["fase999_inesistente"])
        self.assertEqual(pf.OK, stato,
                         "il controllo 10 grida su un piano SANO: un allarme sempre acceso "
                         "viene spento entro tre giorni (regola ferrea 10). %s" % dettaglio)

        rotto = sano_reg.replace("▶️ `fase902_b` (24)", "✅ `fase902_b` **FATTO**")
        self.assertNotEqual(rotto, sano_reg, "l'iniezione non ha cambiato niente")
        stato, dettaglio = pf.controllo_10_piano_dei_soldi(
            registro=rotto, consegne=sano_con, morti=["fase999_inesistente"])
        self.assertEqual(pf.ROSSO, stato,
                         "col piano contraddittorio il pre-fatto NON ferma il commit: il "
                         "guardiano e' un allarme in una stanza vuota")
        self.assertIn("fase902", dettaglio,
                      "e' rosso, ma non nomina il modulo colpevole: %s" % dettaglio[:400])

        stato, dettaglio = pf.controllo_10_piano_dei_soldi(
            registro=sano_reg, consegne=sano_con, morti=["fase902_b"])
        self.assertEqual(pf.ROSSO, stato,
                         "un modulo «da fare» che la produzione non raggiunge non ferma il "
                         "commit: e' il difetto dell'11 agosto, 31 punti buttati")

        # E il vuoto NON e' un verde: senza documenti leggibili e' NON ESEGUITO (S1/S7).
        stato, _d = pf.controllo_10_piano_dei_soldi(
            registro="niente", consegne="niente", morti=[])
        self.assertEqual(pf.NON_ESEGUITO, stato,
                         "su documenti illeggibili il controllo esce OK: e' il verde "
                         "peggiore di tutti, quello che non ha guardato niente")

        numeri = [n for n, _, _ in pf.CONTROLLI]
        self.assertIn(10, numeri,
                      "il controllo 10 non e' nell'elenco che i ganci di git eseguono: "
                      "esiste ma non lo chiama nessuno (regola 23, «costruito != "
                      "collegato»). Numeri presenti: %r" % (numeri,))
        self.assertTrue(pds.NON_CONTROLLO, "il giudizio non dichiara piu' i suoi limiti")


class TestLaListaDelleTecnicheStaInUnPostoSolo(unittest.TestCase):
    """⛔ UNA LISTA SOLA, UN FILE SOLO, LETTA DA QUALUNQUE CHAT.

    Ordine del fondatore, 2026-08-17: *«va corretto sono 11 e deve rimanere solo quello e
    nessun altro file cosi' evitiamo che capiti ancora e quello va letto da qualunque chat»*.

    **Il fatto che l'ha generata, e non e' un'ipotesi.** `RIPRENDI_QUI.md` conteneva una
    SECONDA lista delle tecniche di verifica -- «i sei metodi AWS», con la sua tabella -- e una
    sessione intera ha ragionato su quel numero: ha perfino cercato online tecniche «mancanti»
    che il progetto ha gia' in casa, arrivando a un passo dall'aggiungere strumenti nuovi in un
    progetto che ha bisogno del contrario. La lista vera dice **11**, e sta in
    `REGISTRO_INGEGNERIA.md` fra `TECNICHE-INIZIO`/`TECNICHE-FINE`.

    Tre guardie, perche' i modi di rompersi sono tre: il blocco **sparisce** · il blocco
    **mente sul proprio totale** · qualcuno apre una **seconda lista** da un'altra parte.
    """

    def _blocco(self):
        import collaudi.regole_avvio as ra
        return ra, ra.leggi_tecniche(QUI)

    def test_IL_BLOCCO_C_E_E_DICHIARA_IL_SUO_TOTALE(self):
        ra, blocco = self._blocco()
        self.assertTrue(
            blocco, "il blocco delle tecniche non c'e' piu' in REGISTRO_INGEGNERIA.md "
                    "(marcatori TECNICHE-INIZIO / TECNICHE-FINE): senza di lui il gancio "
                    "d'avvio non ha niente da stampare e ogni chat riparte a indovinare")
        _contate, dichiarate = ra.conta_tecniche(blocco)
        self.assertIsNotNone(
            dichiarate, "il blocco non dichiara `TOTALE DICHIARATO: N`: senza quel numero "
                        "nessuna macchina puo' accorgersi che la lista e' cambiata, e torna a "
                        "essere un elenco custodito dalla buona volonta' (D22)")

    def test_IL_NUMERO_DICHIARATO_E_QUELLO_CONTATO(self):
        """⛔ Il numero non si crede, si conta. Quello delle regole ha mentito TRE volte
        (75 -> 103 -> 104) finche' a scriverlo era una persona invece di una macchina."""
        ra, blocco = self._blocco()
        contate, dichiarate = ra.conta_tecniche(blocco)
        self.assertEqual(
            contate, dichiarate,
            "la lista delle tecniche MENTE SU SE STESSA: dichiara %r, ne ho contate %d. "
            "Correggi `TOTALE DICHIARATO:` oppure la lista." % (dichiarate, contate))

    def test_NESSUN_ALTRO_FILE_TIENE_UNA_SECONDA_LISTA(self):
        """⛔ La seconda lista e' il difetto, non la ridondanza. Qui si cerca in TUTTI i
        documenti ufficiali la frase che dichiara un totale diverso, e la si pretende assente
        -- tranne dentro il blocco vero, che la cita come storia di cio' che e' stato corretto.
        """
        ra, blocco = self._blocco()
        sospetta = re.compile(r"(?:\b6\b|sei|SEI)\s+metodi", re.IGNORECASE)
        colpevoli = []
        for nome in ("README.md", "RIPRENDI_QUI.md", "DEPLOY.md", "CLAUDE.md",
                     "REGISTRO_INGEGNERIA.md"):
            percorso = os.path.join(QUI, nome)
            if not os.path.exists(percorso):
                continue
            with io.open(percorso, encoding="utf-8") as f:
                testo = f.read()
            if nome == "REGISTRO_INGEGNERIA.md" and blocco:
                testo = testo.replace(blocco, "")      # il blocco vero puo' citare la storia
            for riga in testo.splitlines():
                if sospetta.search(riga):
                    colpevoli.append("%s: %s" % (nome, riga.strip()[:110]))
        self.assertEqual(
            colpevoli, [],
            "c'e' una SECONDA lista dei metodi di verifica fuori dal blocco unico: e' cosi' "
            "che il 2026-08-17 una sessione ha ragionato sul numero sbagliato. Togli la "
            "seconda e mettici un rimando a REGISTRO_INGEGNERIA.md "
            "(TECNICHE-INIZIO/TECNICHE-FINE). Trovate: %r" % (colpevoli,))


class TestLaRaggiungibilitaNONPuoGuardareUnIngressoSOLO(unittest.TestCase):
    """⛔ IL NUMERO CHE DECIDE SU COSA SI LAVORA NASCEVA MONCO.

    **Il fatto, misurato il 2026-08-17 e non ricordato.** `collaudi/raggiungibilita.py`
    cammina dagli import a partire da UN solo file (`main_casavip.py`) e dichiara «63 moduli
    morti su 151». Ma sul disco gli ingressi che esistono sono TRE -- `main_casavip.py`,
    `app.py`, `fase83_server.py` -- e partendo da tutti e tre i morti sono **59**. Quattro
    moduli venivano dichiarati cadaveri mentre la produzione li accende.

    **Perche' e' un difetto vivo e non una sfumatura.** Quel numero non sta in un rapporto che
    nessuno legge: `REGISTRO_INGEGNERIA.md` lo usa come ISTRUZIONE -- *«prima di ogni blocco si
    guarda se il modulo e' acceso: 63 su 151 non sono raggiungibili»* -- e la classifica
    «rischio x cecita'» che ordina i moduli dei soldi ci si appoggia. Si decideva **su cosa
    lavorare** con un numero sbagliato, e nessuno strumento lo diceva.

    ⛔ E il verso in cui sbaglia e' quello brutto. Il file dichiara da se' un bias GENEROSO --
    *«se dice MORTO, e' morto davvero»* -- e quella promessa era **falsa**: chiamava morti
    quattro moduli vivi. Un attrezzo che promette di sbagliare in un verso e sbaglia
    nell'altro e' peggio di un attrezzo senza promesse (S15).

    Le guardie sono tre, una per modo di rompersi: l'ingresso dimenticato · gli ingressi non
    dichiarati · il numero ricopiato a mano in un documento invece che prodotto.
    """

    # ⛔ SCRITTI QUI E NON LETTI DALLO STRUMENTO, DI PROPOSITO. Se li leggessi da
    # `raggiungibilita.INGRESSI` la guardia direbbe soltanto «lo strumento e' d'accordo con se
    # stesso», che e' il verde piu' vuoto di tutti: cancellando un ingresso resterebbe verde.
    # Il denominatore lo porta la guardia, non il sorvegliato (regola: ogni guardia dichiara
    # il proprio denominatore).
    #
    # ⛔⛔ QUI DENTRO C'ERA `app.py`, E FU UN ERRORE MIO DEL 2026-08-17. Tolto il 2026-08-18
    # dopo averlo MISURATO: nessuna delle due immagini lo copia, l'avvio e'
    # `python main_casavip.py`, e dentro il container `ls app.py` risponde «No such file or
    # directory». Costava 4 moduli dichiarati vivi a torto -- `fase13_protocollo_finale`,
    # `fase15_idempotency`, `fase17_money`, `fase23_datastore` -- e faceva dire 59 morti
    # invece di 63.
    # ⛔⛔ E POI E' USCITO ANCHE `fase83_server.py`, lo stesso giorno, dopo una revisione
    # indipendente: misurato, come ingresso aggiunge ZERO moduli (e' gia' raggiunto da
    # `main`), quindi non era un ingresso ma un modulo elencato due volte. Resta il solo
    # criterio che non si puo' allargare: il file che l'immagine AVVIA.
    INGRESSI_VERI = ("main_casavip.py",)

    # Il file da cui si legge la verita' su cosa viene spedito. Non e' un dettaglio di questa
    # guardia: e' il punto in cui l'elenco smette di poter mentire.
    DOCKERFILE = "Dockerfile.casavip"

    def _copiati_nell_immagine(self):
        """I modelli di file che l'immagine di produzione copia dentro di se', letti dal
        Dockerfile. Se un giorno il Dockerfile cambia, questa guardia lo segue da sola."""
        percorso = os.path.join(QUI, self.DOCKERFILE)
        self.assertTrue(
            os.path.isfile(percorso),
            "manca %s: senza il Dockerfile non c'e' nessuna autorita' su cosa finisce in "
            "produzione, e l'elenco degli ingressi torna a essere una frase scritta a mano"
            % self.DOCKERFILE)
        modelli = []
        with io.open(percorso, encoding="utf-8") as f:
            for riga in f:
                pulita = riga.strip()
                if not pulita.upper().startswith("COPY "):
                    continue
                pezzi = pulita.split()[1:]
                if len(pezzi) >= 2:
                    modelli.extend(pezzi[:-1])   # l'ultimo e' la destinazione
        self.assertTrue(
            modelli,
            "%s non ha nessuna riga COPY: o il file e' cambiato forma, o l'immagine non "
            "contiene niente. In tutt'e due i casi questa guardia non puo' misurare"
            % self.DOCKERFILE)
        return modelli

    def test_UN_INGRESSO_E_UN_FILE_CHE_LA_PRODUZIONE_SPEDISCE_DAVVERO(self):
        """⛔ LA GUARDIA NATA DALLA BUGIA DEL 2026-08-18.

        Il 17 agosto `app.py` e' stato dichiarato «uno dei file da cui la macchina si accende
        davvero». Non lo era: l'immagine non lo copia e nel container non esiste. Da quella
        riga dipendeva il conto dei moduli morti, e quel conto decide **su cosa si lavora**.

        Qui l'elenco degli ingressi smette di poter mentire: ogni nome dichiarato deve
        corrispondere a qualcosa che il Dockerfile **copia davvero** dentro l'immagine. Non
        e' una regola di stile -- e' la differenza fra «questo file esiste» e «questo file
        gira», che e' esattamente il punto in cui ci siamo sbagliati.
        """
        import fnmatch
        r = self._modulo()
        modelli = self._copiati_nell_immagine()
        non_spediti = []
        for ingresso in getattr(r, "INGRESSI", ()):
            if not any(fnmatch.fnmatch(ingresso, m.rstrip("/")) for m in modelli):
                non_spediti.append(ingresso)
        self.assertEqual(
            [], non_spediti,
            "`raggiungibilita.INGRESSI` dichiara file che l'immagine di produzione NON "
            "spedisce: %r.\n        Le COPY del %s sono %r.\n        Un file che non entra "
            "nell'immagine non accende niente: contarlo come ingresso gonfia i moduli "
            "«vivi» e nasconde i morti, che e' come si sceglie male su cosa lavorare."
            % (non_spediti, self.DOCKERFILE, modelli))

    def test_GLI_INGRESSI_SONO_ESATTAMENTE_QUELLO_CHE_L_IMMAGINE_AVVIA(self):
        """⛔ UGUAGLIANZA, NON INCLUSIONE — e la differenza l'ha vista una revisione
        indipendente, non io.

        La prima stesura pretendeva solo che gli ingressi fossero **spediti** (cioe'
        comparissero fra le `COPY`). Sembrava stretto e non lo era: il Dockerfile copia
        `fase*.py`, quindi quel criterio avrebbe accettato come «ingresso di produzione»
        **151 moduli su 152**. Bastava aggiungerne uno qualsiasi per gonfiare il conto dei
        vivi -- cioe' il difetto del 2026-08-17 sarebbe rientrato sotto un altro nome, con
        tutte le guardie verdi.

        Il criterio che non si puo' allargare e' uno solo: **gli ingressi sono ESATTAMENTE i
        moduli che il `CMD` avvia**. Non «almeno», non «compresi»: uguali. Un processo nuovo
        (un secondo `CMD`, un lavoratore in coda) fa diventare rossa questa riga il giorno
        stesso, ed e' giusto cosi': e' un ingresso nuovo e va dichiarato.
        """
        r = self._modulo()
        percorso = os.path.join(QUI, self.DOCKERFILE)
        with io.open(percorso, encoding="utf-8") as f:
            testo = f.read()
        avviati = re.findall(r"([A-Za-z0-9_./-]+\.py)",
                             "\n".join(l for l in testo.splitlines()
                                       if l.strip().upper().startswith("CMD")))
        self.assertTrue(
            avviati,
            "il %s non dichiara nessun `.py` nel suo CMD: non so piu' cosa avvia la "
            "produzione" % self.DOCKERFILE)
        dichiarati = set(getattr(r, "INGRESSI", ()))
        in_piu = sorted(dichiarati - set(avviati))
        self.assertEqual(
            [], in_piu,
            "`INGRESSI` dichiara file che l'immagine NON AVVIA: %r (il CMD nomina %r).\n"
            "        ⛔ Un modulo spedito non e' un ingresso: il Dockerfile copia `fase*.py`, "
            "quindi con il criterio «basta che sia spedito» si potrebbero dichiarare "
            "ingresso 151 moduli su 152 e gonfiare il conto dei vivi senza che nessuna "
            "guardia gridi. Gli ingressi sono ESATTAMENTE cio' che il CMD avvia."
            % (in_piu, avviati))
        mancanti = [a for a in avviati if a not in dichiarati]
        # ⛔ NEL MESSAGGIO VA `mancanti`, NON `avviati`. Trovato da una revisione
        # indipendente il 2026-08-18: scrivendo `avviati` il rosso avrebbe elencato ANCHE i
        # file gia' dichiarati correttamente, mandando chi legge a «riparare» nomi giusti
        # mentre il colpevole vero era l'unico dentro `mancanti`. Oggi i due coincidono
        # perche' il CMD nomina un file solo -- cioe' il difetto e' invisibile finche' non
        # serve, che e' il modo peggiore in cui un messaggio puo' sbagliare.
        self.assertEqual(
            [], mancanti,
            "questi file, che l'immagine AVVIA, non sono fra gli ingressi dichiarati: %r "
            "(il CMD ne nomina %r, gli ingressi dichiarati sono %r). Il cammino partirebbe "
            "da tutt'altro rispetto a cio' che gira davvero."
            % (mancanti, avviati, sorted(dichiarati)))

    def _modulo(self):
        sys.path.insert(0, os.path.join(QUI, "collaudi"))
        import raggiungibilita
        return raggiungibilita

    def test_GLI_INGRESSI_DI_QUESTA_GUARDIA_SONO_SPEDITI_IN_PRODUZIONE(self):
        """Il metro si misura prima del muro (D18 punto 1): se questi nomi non fossero veri,
        le guardie sotto girerebbero a vuoto stampando verde. E' lo sbaglio S2 -- i nomi si
        leggono, non si ricordano -- applicato alla guardia stessa.

        ⛔⛔ **E FINO AL 2026-08-18 QUESTA VERIFICA USAVA IL CRITERIO SBAGLIATO**: chiedeva
        `os.path.isfile`, cioe' esattamente cio' che quel giorno abbiamo dimostrato non
        significare niente (`app.py` sta sul disco e non va in produzione). Trovato da una
        revisione indipendente, ed era la parte piu' insidiosa: con quel criterio bastava
        rimettere `app.py` **qui dentro** e la guardia relazionale sarebbe diventata rossa
        accusando `raggiungibilita.py` di dichiarare morti dei vivi -- cioe' il rosso stesso
        avrebbe **ordinato di rimettere il difetto**. Una guardia che, sbagliando, insegna a
        reintrodurre il guasto e' peggio di nessuna guardia.
        """
        import fnmatch
        modelli = self._copiati_nell_immagine()
        non_spediti = [n for n in self.INGRESSI_VERI
                       if not any(fnmatch.fnmatch(n, m.rstrip("/")) for m in modelli)]
        self.assertEqual(
            [], non_spediti,
            "questa guardia nomina come ingressi dei file che l'immagine di produzione NON "
            "spedisce (%r). Non e' un dettaglio: e' il criterio sbagliato -- «sta sul disco» "
            "invece di «l'artefatto lo contiene e lo avvia» -- ed e' esattamente l'errore del "
            "2026-08-17. Le COPY del Dockerfile sono %r." % (non_spediti, modelli))
        mancanti = [n for n in self.INGRESSI_VERI
                    if not os.path.isfile(os.path.join(QUI, n))]
        self.assertEqual(
            [], mancanti,
            "questa guardia nomina file che sul disco non ci sono piu' (%r): il Dockerfile "
            "li spedirebbe, ma non esistono. In tutt'e due i casi non sta provando niente."
            % (mancanti,))

    def test_UN_MODULO_RAGGIUNTO_DA_UN_INGRESSO_VERO_NON_PUO_RISULTARE_MORTO(self):
        """⛔ LA GUARDIA CHE VEDE IL DIFETTO. Non pretende un numero (un numero invecchia,
        D22): pretende una RELAZIONE -- se un ingresso vero raggiunge un modulo, quel modulo
        non e' morto. Regge anche il giorno che i moduli diventano 200."""
        r = self._modulo()
        _vivi, morti, _tutti = r.cammina(QUI)
        accusati = {}
        for ingresso in self.INGRESSI_VERI:
            if not os.path.isfile(os.path.join(QUI, ingresso)):
                continue
            raggiunti = r.cammina(QUI, partenza=ingresso)[0]
            sbagliati = sorted(raggiunti & morti)
            if sbagliati:
                accusati[ingresso] = sbagliati
        self.assertEqual(
            accusati, {},
            "`raggiungibilita.py` dichiara MORTI dei moduli che un ingresso VERO della "
            "produzione raggiunge, e il file promette il contrario («se dice MORTO, e' morto "
            "davvero»).\n        ⛔ PRIMA DI AGGIUNGERE UN INGRESSO, CONTROLLA CHE SIA "
            "SPEDITO: deve comparire fra le COPY del Dockerfile e finire dentro l'immagine. "
            "«Sta sul disco» NON basta, ed e' l'errore del 2026-08-17 (app.py). Se l'ingresso "
            "e' spedito, allora `raggiungibilita.py` deve partire anche da li'.\n"
            "        Accusati a torto: %r" % (accusati,))

    def test_LO_STRUMENTO_DICHIARA_DA_DOVE_PARTE(self):
        """Un attrezzo che misura dichiara cosa NON ha esaminato (D18 punto 3). Qui la cosa
        non esaminata era un ingresso intero, e il file non lo diceva."""
        r = self._modulo()
        ingressi = getattr(r, "INGRESSI", None)
        # ⛔ NON basta «non e' nullo»: una tupla vuota, o piena di nomi inventati, passerebbe.
        # E' la lezione del 2026-08-14 (sette guardie verdi col guasto dentro perche'
        # `exc_info=False` non e' `None`): si chiede LA COSA, del tipo giusto.
        self.assertIsInstance(
            ingressi, tuple,
            "`raggiungibilita.py` non dichiara `INGRESSI`: da dove parte il cammino resta "
            "un dettaglio sepolto nel codice, e il giorno che ne nasce un quarto nessuno se "
            "ne accorge")
        esistono = [n for n in ingressi if os.path.isfile(os.path.join(QUI, n))]
        self.assertEqual(
            sorted(esistono), sorted(ingressi),
            "`INGRESSI` nomina file che sul disco non ci sono: dichiarati %r, esistono %r"
            % (sorted(ingressi), sorted(esistono)))
        self.assertGreaterEqual(
            len(ingressi), len(self.INGRESSI_VERI),
            "`INGRESSI` ne dichiara %d, ma sul disco ce ne sono almeno %d: un ingresso "
            "dimenticato e' esattamente il difetto del 2026-08-17"
            % (len(ingressi), len(self.INGRESSI_VERI)))


class TestNessunRiferimentoGREZZOEntraNelREGISTRO(unittest.TestCase):
    """🪤 IL REGISTRO E' LO STRUMENTO CON CUI SI VEDONO I DIFETTI: una riga fabbricata li'
    dentro non e' un difetto qualunque.

    **Il fatto, 2026-08-18.** CodeQL ha bocciato la richiesta #66 con **10 allarmi, 5 gravi**
    (`py/log-injection` + `py/clear-text-logging-sensitive-data`) su **codice scritto da me
    poche ore prima**. Il `riferimento` arriva dal CORPO della richiesta e finiva grezzo nel
    registro: un a-capo li' dentro fabbrica righe di allarme FALSE proprio dove il Guardiano
    (fase186) guarda ogni giorno per sapere se un guasto sui soldi e' avvenuto.

    ⛔ **E LA STESSA CLASSE ERA GIA' STATA CHIUSA SULLA #59.** Il rimedio
    (`_rif_per_registro`) esisteva, era documentato, e io non l'ho usato. Perche' e' tornata?
    **Perche' nessun test la sorvegliava**: quella riparazione fu applicata a mano, punto per
    punto. E' D20 vista dal lato in cui si rompe -- *«la guardia e' la memoria del difetto: se
    qualcuno riscrive quella riga com'era, diventa rossa lo stesso giorno»*. Senza guardia, la
    memoria era la mia, e non ha retto nove giorni.

    ⛔⛔ **CRICCHETTO, NON CANCELLO — e il perche' e' onesto.** Misurando si e' scoperto che i
    punti scoperti non erano 5: erano **32**, quasi tutti anteriori a questo lavoro (CodeQL
    segnalava solo i miei perche' erano *nuovi*). Ripararli tutti in un colpo, di notte, su
    codice che muove denaro, sarebbe stato peggio del difetto. Quindi il tetto e' fissato a
    quello che c'e' **oggi** e puo' solo SCENDERE: nessuna riga nuova puo' entrare, e ogni
    volta che se ne ripara una si abbassa il numero qui sotto. E' la stessa tecnica che la CI
    usa gia' per la copertura («soglia a cricchetto»).
    """

    # ⛔ QUESTO NUMERO PUO' SOLO SCENDERE. Se sale, qualcuno ha aggiunto una riga di registro
    # con un riferimento grezzo: si ripara la riga, non si alza il tetto.
    #
    # 32 -> 0 il 2026-08-18. Il tetto era nato la notte prima come debito dichiarato:
    # «ripararli tutti di notte, su codice che muove denaro, sarebbe stato peggio del
    # difetto». Il giorno dopo sono stati chiusi tutti e trentadue, uno per uno con
    # l'editor, e il conto e' stato rifatto dalla macchina invece che da me. Da qui in
    # avanti il cricchetto e' un CANCELLO: nessuna riga di registro puo' piu' scrivere un
    # riferimento grezzo, e la prima che ci prova diventa rossa.
    TETTO = 0
    NOMI_GREZZI = {"riferimento", "rif", "ref", "riferimento_id"}

    def _scoperti(self):
        import ast
        with io.open(os.path.join(QUI, "fase83_server.py"), encoding="utf-8") as f:
            albero = ast.parse(f.read())

        def grezzo(nodo):
            if isinstance(nodo, ast.Name) and nodo.id in self.NOMI_GREZZI:
                return nodo.id
            # `str(rif)` non ripulisce niente: cambia il tipo, non il contenuto.
            if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
                    and nodo.func.id == "str" and nodo.args
                    and isinstance(nodo.args[0], ast.Name)
                    and nodo.args[0].id in self.NOMI_GREZZI):
                return "str(%s)" % nodo.args[0].id
            return None

        fuori = []
        for n in ast.walk(albero):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
                continue
            if not (isinstance(n.func.value, ast.Name) and n.func.value.id == "logger"):
                continue
            # il primo argomento e' il modello della riga: quello e' nostro e non e' un dato
            for a in n.args[1:]:
                nome = grezzo(a)
                if nome:
                    fuori.append("riga %d: logger.%s(... %s ...)" % (n.lineno, n.func.attr,
                                                                     nome))
        return sorted(fuori)

    def test_IL_NUMERO_DI_RIGHE_SCOPERTE_PUO_SOLO_SCENDERE(self):
        scoperti = self._scoperti()
        self.assertLessEqual(
            len(scoperti), self.TETTO,
            "SONO AUMENTATE le righe di registro che scrivono un riferimento GREZZO: %d "
            "contro un tetto di %d. Il riferimento arriva dal corpo della richiesta, e il "
            "registro e' dove il Guardiano cerca i guasti sui soldi: un a-capo li' dentro "
            "fabbrica allarmi falsi. Usa `_rif_per_registro(...)`. ⛔ Non alzare il tetto: "
            "ripara la riga.\n      %s"
            % (len(scoperti), self.TETTO, "\n      ".join(scoperti[-8:])))

    def test_IL_TETTO_NON_RESTA_PIU_ALTO_DEL_VERO(self):
        """⛔ D18 punto 1: il metro si misura prima del muro. Un cricchetto che resta sopra il
        numero vero smette di stringere -- e allora non e' piu' un cricchetto, e' un commento.
        Quando si ripara una riga si abbassa il tetto, e questa guardia lo pretende."""
        scoperti = self._scoperti()
        self.assertEqual(
            len(scoperti), self.TETTO,
            "il tetto dichiarato (%d) non e' piu' quello vero (%d): se hai riparato delle "
            "righe, abbassa `TETTO` nello stesso commit, o il cricchetto lascia rientrare "
            "quello che hai appena tolto." % (self.TETTO, len(scoperti)))

    def test_IL_RIMEDIO_ESISTE_ANCORA(self):
        """Se qualcuno toglie `_rif_per_registro`, le due guardie sopra continuerebbero a
        contare felici mentre il rimedio non c'e' piu' (sbaglio S2: i nomi si leggono)."""
        with io.open(os.path.join(QUI, "fase83_server.py"), encoding="utf-8") as f:
            testo = f.read()
        self.assertIn(
            "def _rif_per_registro", testo,
            "il rimedio contro le righe di registro fabbricate e' sparito: senza di lui il "
            "cricchetto qui sopra sorveglia una difesa che non esiste piu'")


class TestLaPuliziaDelRegistroDEVEESSEREVISIBILEACHIANALIZZA(unittest.TestCase):
    """🔬 UNA DIFESA CHE FUNZIONA MA CHE L'ANALIZZATORE NON VEDE VIENE BOCCIATA LO STESSO.

    **Il fatto, 2026-08-18.** La riparazione della richiesta #66 e' stata scritta, provata e
    spinta: `_rif_per_registro` ripulisce il riferimento con una `re.sub` che tiene **solo**
    lettere, cifre e quattro segni. E' piu' severa di qualunque rimedio suggerito. CodeQL ha
    rifatto l'analisi **sullo stesso identico file** (verificato: il blob di `fase83_server.py`
    nel commit analizzato `fb42d97` ha la stessa impronta `8a28c8f` di quello sul disco) e ha
    segnalato **di nuovo le stesse cinque righe**.

    ⛔ **Il motivo non e' un'opinione: sta scritto nel sorgente della regola.** Dal file
    `python/ql/lib/semmle/python/security/dataflow/LogInjectionCustomizations.qll` del
    repository `github/codeql`, unica barriera prevista oltre al confronto con una costante:

        class ReplaceLineBreaksSanitizer extends Sanitizer, DataFlow::CallCfgNode {
          ReplaceLineBreaksSanitizer() {
            this.getFunction().(DataFlow::AttrRead).getAttributeName() = "replace" and
            this.getArg(0).asExpr().(StringLiteral).getText() in ["\\r\\n", "\\n"]
          }
        }

    Cioe': CodeQL riconosce **una forma sola**, `qualcosa.replace("\\n", ...)`. La nostra
    `re.sub` toglie molto di piu', ma per l'analisi e' **invisibile**, e il veleno risulta
    passare. 💡 La lezione, ed e' quella che questa guardia mette in cassaforte: **una difesa
    ha due destinatari** — il programma, che deve restare sano, e lo strumento che sorveglia,
    che deve poterlo **dimostrare**. Se il secondo non la vede, l'allarme non si spegne mai e
    prima o poi qualcuno lo spegne a mano: e quello e' il vero difetto.

    ⛔ Percio' qui si pretendono **due cose diverse**, e servono tutt'e due:
      1. che la pulizia **funzioni davvero** (nessun a-capo sopravvive, in nessuna delle sue
         otto forme) — l'invariante del prodotto;
      2. che la pulizia sia **scritta nella forma che l'analizzatore riconosce**, e che il
         valore ripulito sia proprio quello che **esce** dalla funzione — l'invariante dello
         strumento. Una barriera messa su una variabile che nessuno restituisce non protegge
         niente, e sarebbe verde qui e rossa in CI.
    """

    # ⛔ COPIATA DAL SORGENTE DELLA REGOLA, non dedotta: sono le due sole stringhe che
    # `ReplaceLineBreaksSanitizer` accetta come primo argomento di `.replace(...)`.
    A_CAPO_RICONOSCIUTI = ("\n", "\r\n")

    # Tutti i modi in cui un carattere puo' spezzare una riga di registro. Non e' un elenco
    # inventato: sono esattamente quelli su cui `str.splitlines()` di Python taglia, ed e' il
    # secondo giudice usato piu' sotto (un conto scritto DIVERSO, tecnica «oracolo
    # indipendente»: se i due non concordano, uno dei due sbaglia e si vede).
    SPEZZARIGHE = ("\n", "\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85",
                   " ", " ")

    def _funzione_rimedio(self):
        """L'albero sintattico di `_rif_per_registro`, letto dal file di produzione."""
        import ast
        with io.open(os.path.join(QUI, "fase83_server.py"), encoding="utf-8") as f:
            albero = ast.parse(f.read())
        for n in ast.walk(albero):
            if isinstance(n, ast.FunctionDef) and n.name == "_rif_per_registro":
                return n
        return None

    def _replace_riconosciute(self, funzione):
        """Le chiamate `.replace("\\n", ...)` che CodeQL conta come barriera. Stessa regola
        del sorgente citato nella docstring: nome dell'attributo + primo argomento letterale."""
        import ast
        trovate = []
        for n in ast.walk(funzione):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
                continue
            if n.func.attr != "replace" or not n.args:
                continue
            primo = n.args[0]
            if isinstance(primo, ast.Constant) and isinstance(primo.value, str) \
                    and primo.value in self.A_CAPO_RICONOSCIUTI:
                trovate.append(n)
        return trovate

    def test_LA_PULIZIA_ESISTE_NELLA_FORMA_CHE_CODEQL_RICONOSCE(self):
        import ast
        funzione = self._funzione_rimedio()
        # ⛔ Non «non e' nullo» (lezione del 2026-08-14: `False` non e' `None`), ma «e' LA
        # cosa, del tipo giusto»: una definizione di funzione con quel nome esatto.
        self.assertIsInstance(
            funzione, ast.FunctionDef,
            "`_rif_per_registro` non esiste piu' come funzione in fase83_server.py: non "
            "c'e' nessuna pulizia da rendere visibile, e le guardie qui sotto "
            "sorveglierebbero il vuoto")
        chiamate = self._replace_riconosciute(funzione)
        self.assertTrue(
            chiamate,
            "DENTRO `_rif_per_registro` NON C'E' NESSUNA `.replace(\"\\\\n\", ...)`.\n"
            "        La pulizia con `re.sub` funziona, ma CodeQL NON la vede: l'unica "
            "barriera che la sua regola riconosce e' `ReplaceLineBreaksSanitizer` "
            "(github/codeql, LogInjectionCustomizations.qll), cioe' una chiamata "
            "`.replace(...)` col primo argomento uguale a \"\\\\n\" o \"\\\\r\\\\n\".\n"
            "        ⛔ Senza quella forma la richiesta resta ROSSA anche a difesa "
            "perfetta, e l'unico modo per farla passare diventa spegnere l'allarme a mano. "
            "La `re.sub` NON si toglie: la `.replace` si aggiunge ACCANTO.")

    def test_IL_VALORE_RIPULITO_E_PROPRIO_QUELLO_CHE_ESCE(self):
        """⛔ Una barriera su una variabile che poi nessuno restituisce e' un ornamento:
        sarebbe verde in questo file e rossa in CI, che e' il peggiore dei due mondi."""
        import ast
        funzione = self._funzione_rimedio()
        chiamate = self._replace_riconosciute(funzione)
        # ⛔ NESSUN `skipTest` quando non ce ne sono: un test che si assolve da solo sparisce
        # dal rapporto come «skipped» e non lo legge piu' nessuno (bocciato due volte da due
        # guardie indipendenti, il 2026-08-17). Se la barriera manca, questa guardia dev'essere
        # ROSSA quanto quella qui sopra: l'invariante e' unico e vale in tutt'e due i rami.
        nomi_resi = set()
        for n in ast.walk(funzione):
            if isinstance(n, ast.Return) and n.value is not None:
                for m in ast.walk(n.value):
                    if isinstance(m, ast.Name):
                        nomi_resi.add(m.id)

        nomi_ripuliti = set()
        for n in ast.walk(funzione):
            if not isinstance(n, ast.Assign):
                continue
            dentro = [x for x in ast.walk(n.value) if any(x is c for c in chiamate)]
            if not dentro:
                continue
            for t in n.targets:
                for m in ast.walk(t):
                    if isinstance(m, ast.Name):
                        nomi_ripuliti.add(m.id)

        # oppure la `.replace` sta direttamente dentro il `return`
        diretta = any(any(x is c for c in chiamate)
                      for n in ast.walk(funzione) if isinstance(n, ast.Return)
                      and n.value is not None
                      for x in ast.walk(n.value))

        self.assertTrue(
            diretta or (nomi_resi & nomi_ripuliti),
            "la `.replace(\"\\\\n\", ...)` c'e', ma il valore che ne esce NON e' quello che "
            "la funzione restituisce (restituisce %s, ripulisce %s): la barriera non sta "
            "sulla strada del dato, quindi CodeQL continuera' a vedere il veleno passare."
            % (sorted(nomi_resi) or "niente", sorted(nomi_ripuliti) or "niente"))

    def test_NESSUN_A_CAPO_SOPRAVVIVE_ALLA_PULIZIA(self):
        """L'invariante del PRODOTTO, indipendente da come e' scritto il rimedio: qualunque
        cosa entri, dal registro non puo' uscire piu' di UNA riga."""
        from fase83_server import _rif_per_registro
        for spezza in self.SPEZZARIGHE:
            veleno = "REF-123%sinfo GUASTO SUI SOLDI: rimborso mai partito" % spezza
            with self.subTest(carattere=repr(spezza)):
                uscita = _rif_per_registro(veleno)
                for c in self.SPEZZARIGHE:
                    self.assertNotIn(
                        c, uscita,
                        "il carattere %r e' sopravvissuto alla pulizia: con quello si "
                        "fabbrica una riga di allarme FALSA nel registro che il Guardiano "
                        "(fase186) legge ogni giorno" % (c,))
                # ⛔ SECONDO GIUDICE, scritto diverso dal primo: `splitlines` di Python taglia
                # su tutti e dieci quei caratteri. Se conta piu' di una riga, la difesa ha un
                # buco che l'elenco qui sopra non ha visto.
                self.assertEqual(
                    len(uscita.splitlines()), 1,
                    "da un solo riferimento sono uscite %d righe (%r): il registro si puo' "
                    "ancora falsificare" % (len(uscita.splitlines()), uscita))

    def test_LA_PULIZIA_NON_RESTITUISCE_MAI_UNA_STRINGA_VUOTA(self):
        """Una riga di registro con un riferimento vuoto e' illeggibile quanto una falsa:
        chi legge non sa piu' di quale prenotazione si parlava."""
        from fase83_server import _rif_per_registro
        for vuoto in ("", "\n\n\n", "   ", None, " "):
            with self.subTest(ingresso=repr(vuoto)):
                uscita = _rif_per_registro(vuoto)
                self.assertTrue(
                    isinstance(uscita, str) and uscita.strip(),
                    "da %r e' uscito %r: nel registro finirebbe una riga senza riferimento"
                    % (vuoto, uscita))
                self.assertLessEqual(
                    len(uscita), 64,
                    "il riferimento ripulito supera i 64 caratteri dichiarati: %r" % (uscita,))


class TestLaListaDeiFileESCLUSIDaCodeQL(unittest.TestCase):
    """🚧 UN ELENCO DI ESCLUSIONI E' LA SCAPPATOIA PIU' COMODA CHE ESISTA: qui c'e' il suo
    guardiano.

    **Il fatto, 2026-08-18.** Su 164 allarmi aperti, **47** erano `clear-text-logging` e
    **45 di quei 47 non erano difetti**: nascevano da tre file di collaudo che contengono la
    parola `password` con dentro dati finti (`PASSWORD_ROMA`, `"password1"`). CodeQL li
    classifica come dati sensibili e li segue fin dentro il server. In produzione quel
    passaggio non esiste. E **non si puo' riparare nel codice**: nella versione di regole che
    gira nella nostra CI (`codeql/python-all 7.2.3+44a68d3a`, scaricata al commit esatto e
    confrontata per impronta), `CleartextLoggingCustomizations.qll` dichiara
    `abstract class Sanitizer` e **non ne implementa nemmeno una**.

    Quindi il codice di collaudo esce dall'analisi, e la scelta sta scritta in un file
    leggibile del repository (`.github/codeql/codeql-config.yml`) invece che in allarmi
    archiviati a mano su un sito.

    ⛔ **Ma un'esclusione senza guardiano e' un interruttore per spegnere gli allarmi
    scomodi.** Domani basta aggiungere una riga con `fase83_server.py` e la sorveglianza sul
    file che muove i soldi sparisce **senza che nulla diventi rosso**. Percio' qui si
    pretendono cinque cose, e la piu' importante e' la terza:

      1. il file di configurazione esiste e si carica davvero come YAML;
      2. ogni riga dell'elenco corrisponde a file che esistono (una riga morta e' un
         elenco che nessuno ha piu' riletto);
      3. **nessun file di produzione puo' finire escluso** — le righe vengono espanse sui
         file veri del repository, non lette come testo;
      4. i tre punti d'ingresso veri (`fase83_server.py`, `app.py`, `main_casavip.py`)
         restano dentro l'analisi, detti per nome;
      5. il workflow **punta davvero** a questo file (regola ferrea 23, «costruito ≠
         collegato»): una configurazione perfetta che nessuno carica e' un ornamento, ed e'
         il difetto piu' frequente di questo progetto.
    """

    CONFIG = os.path.join(".github", "codeql", "codeql-config.yml")
    WORKFLOW = os.path.join(".github", "workflows", "codeql.yml")
    INGRESSI = ("fase83_server.py", "app.py", "main_casavip.py")

    def _config(self):
        percorso = os.path.join(QUI, self.CONFIG)
        self.assertTrue(
            os.path.isfile(percorso),
            "manca %s: il workflow lo carica e senza quel file CodeQL parte con la "
            "configurazione di serie, cioe' torna a inondare di allarmi finti" % self.CONFIG)
        with io.open(percorso, encoding="utf-8") as f:
            return yaml.safe_load(f.read())

    def _file_del_repository(self):
        """Tutti i `.py` versionati, in percorso relativo con le barre di git."""
        fuori = []
        for radice, cartelle, nomi in os.walk(QUI):
            cartelle[:] = [c for c in cartelle
                           if c not in (".git", "__pycache__", ".venv", "venv", "node_modules",
                                        ".mypy_cache", ".pytest_cache", "htmlcov")]
            for n in nomi:
                if not n.endswith(".py"):
                    continue
                rel = os.path.relpath(os.path.join(radice, n), QUI).replace(os.sep, "/")
                fuori.append(rel)
        return sorted(fuori)

    @staticmethod
    def _e_di_collaudo(percorso):
        base = percorso.split("/")[-1]
        return (base.startswith("test_")
                or percorso.startswith("collaudi/")
                or percorso.startswith("tests/"))

    @staticmethod
    def _corrisponde(modello, percorso):
        """Vero se il modello dell'elenco copre quel file.

        ⛔ Volutamente GENEROSO: `fnmatch` lascia che `*` scavalchi anche le barre, quindi
        questa funzione dichiara «escluso» piu' di quanto CodeQL escluderebbe davvero. E'
        il verso giusto in cui sbagliare: un modello troppo largo qui diventa ROSSO, non
        invisibile (lo sbaglio S15 e' stato esattamente il contrario).
        """
        import fnmatch
        m = str(modello).strip().strip('"').strip("'")
        if not m:
            return False
        if m.endswith("/"):
            return percorso.startswith(m)
        if m.startswith("**/"):
            coda = m[3:]
            return (fnmatch.fnmatch(percorso, coda)
                    or fnmatch.fnmatch(percorso.split("/")[-1], coda)
                    or fnmatch.fnmatch(percorso, m))
        return fnmatch.fnmatch(percorso, m)

    def _esclusi(self):
        cfg = self._config()
        modelli = cfg.get("paths-ignore") or []
        tutti = self._file_del_repository()
        mappa = {}
        for m in modelli:
            mappa[m] = [p for p in tutti if self._corrisponde(m, p)]
        return modelli, mappa, tutti

    def test_IL_FILE_DI_CONFIGURAZIONE_ESISTE_E_HA_UN_ELENCO(self):
        cfg = self._config()
        self.assertIsInstance(
            cfg, dict, "%s non si carica come YAML: CodeQL fallirebbe l'avvio" % self.CONFIG)
        modelli = cfg.get("paths-ignore")
        self.assertTrue(
            isinstance(modelli, list) and modelli,
            "`paths-ignore` e' vuoto o non e' un elenco: allora questo file non serve a "
            "niente e va tolto, invece di restare li' a far credere che qualcosa sia "
            "configurato (trovato: %r)" % (modelli,))

    def test_NESSUN_FILE_DI_PRODUZIONE_PUO_FINIRE_ESCLUSO(self):
        """⛔ LA GUARDIA CHE CONTA. Se qualcuno aggiunge `fase*.py` all'elenco per far
        tacere un allarme, questa riga diventa rossa lo stesso giorno."""
        _modelli, mappa, _tutti = self._esclusi()
        colpevoli = {}
        for m, colpiti in mappa.items():
            produzione = [p for p in colpiti if not self._e_di_collaudo(p)]
            if produzione:
                colpevoli[m] = produzione
        self.assertEqual(
            {}, colpevoli,
            "L'ELENCO DELLE ESCLUSIONI DI CODEQL TOGLIE DALL'ANALISI DEL CODICE DI "
            "PRODUZIONE.\n        %s\n        ⛔ Il codice che gira per gli ospiti si "
            "analizza tutto. Se un allarme e' falso si spiega e si archivia quello, non si "
            "spegne il faro."
            % "\n        ".join("%r -> %s" % (m, ", ".join(v[:6])) for m, v in colpevoli.items()))

    def test_I_TRE_INGRESSI_VERI_RESTANO_DENTRO_L_ANALISI(self):
        """La guardia sopra dice «niente produzione»; questa dice i tre nomi. Sono due
        affermazioni diverse: la prima puo' restare verde su un repository vuoto."""
        _modelli, mappa, tutti = self._esclusi()
        esclusi = set()
        for colpiti in mappa.values():
            esclusi.update(colpiti)
        for nome in self.INGRESSI:
            self.assertIn(nome, tutti, "%s non c'e' piu' sul disco: la guardia sorveglia "
                                       "un file che non esiste" % nome)
            self.assertNotIn(
                nome, esclusi,
                "%s e' finito FUORI dall'analisi di CodeQL: e' uno dei tre punti d'ingresso "
                "veri della macchina, e da solo raccoglie la maggior parte degli allarmi "
                "sui soldi" % nome)

    def test_OGNI_RIGA_DELL_ELENCO_CORRISPONDE_A_FILE_CHE_ESISTONO(self):
        """Una riga che non prende piu' niente e' un elenco che nessuno ha riletto: o il
        file e' stato rinominato (e allora non e' piu' escluso davvero, senza che nessuno
        se ne accorga), o la riga andava tolta."""
        modelli, mappa, _tutti = self._esclusi()
        morte = [m for m in modelli if not mappa[m]]
        self.assertEqual(
            [], morte,
            "queste righe di `paths-ignore` non corrispondono a nessun file del "
            "repository: %s" % ", ".join(repr(m) for m in morte))

    def test_IL_WORKFLOW_PUNTA_DAVVERO_A_QUESTO_FILE(self):
        """⛔ REGOLA FERREA 23 — COSTRUITO ≠ COLLEGATO. E' il difetto che questo progetto
        ha gia' fatto piu' volte: l'attrezzo giusto, scritto bene, che nessuno esegue."""
        percorso = os.path.join(QUI, self.WORKFLOW)
        with io.open(percorso, encoding="utf-8") as f:
            testo = f.read()
        wf = yaml.safe_load(testo)
        passi = []
        for job in (wf.get("jobs") or {}).values():
            passi.extend(job.get("steps") or [])
        init = [p for p in passi if "codeql-action/init" in str(p.get("uses", ""))]
        self.assertTrue(init, "il workflow CodeQL non ha piu' un passo `init`")
        dichiarato = [str((p.get("with") or {}).get("config-file", "")) for p in init]
        atteso = "./" + self.CONFIG.replace(os.sep, "/")
        self.assertIn(
            atteso, dichiarato,
            "il passo `init` di CodeQL NON carica %s (dichiara %r): la configurazione "
            "esiste sul disco e non la legge nessuno, quindi l'analisi gira con le "
            "impostazioni di serie e questo file e' un ornamento." % (atteso, dichiarato))
        # e il file puntato dev'essere quello che esiste davvero
        self.assertTrue(
            os.path.isfile(os.path.join(QUI, atteso[2:].replace("/", os.sep))),
            "il workflow punta a %r, che sul disco non c'e': l'analisi fallirebbe "
            "all'avvio" % atteso)


class TestLaSuiteRIFIUTADiGirareDallaShellSBAGLIATA(unittest.TestCase):
    """🚫 LA SHELL FA PARTE DELLA MISURA — e questa guardia nasce da un errore MIO.

    **Il fatto, 2026-08-17, poche ore dopo aver documentato lo sbaglio S11.** Ho lanciato la
    suite intera da **Git Bash** invece che da PowerShell. Risultato: `Ran 5813 tests` e
    **sei rossi**, di cui tre erano solo la conseguenza della shell — il pre-volo si rifiutava
    (giustamente) di giudicare un ambiente che non e' quello da cui parte la suite. Mezz'ora
    di macchina buttata, e per un istante sei rossi che sembravano difetti del prodotto.

    ⛔ **E il verso peggiore e' l'altro.** Da Git Bash `openssl` **c'e'**, da PowerShell **no**:
    la stessa domanda da' due risposte opposte. Un giro fatto dalla shell sbagliata puo'
    quindi eseguire guardie che nella shell vera **si spengono in silenzio** — e allora il
    verde dichiara coperto cio' che nessuno ha guardato. E' D23 punto 3, ed e' il tipo di
    verde che questo progetto esiste per estirpare.

    💡 **L'ha chiesta il fondatore** (2026-08-17): *«rileva l'ambiente di esecuzione del
    terminale e blocca l'avvio dei test se rileva una shell errata, che potrebbe nascondere
    il salto dei test di backup»*. Aveva ragione, e l'ho dimostrato cadendoci io.

    ⛔ **NON e' un promemoria: e' un ROSSO.** Un avviso stampato si legge quando si e' gia'
    aspettato mezz'ora; un rosso rende il giro **non spacciabile per buono**, che e' il punto.

    ⛔⛔ **E NON SI SALTA SU LINUX, benche' li' il caso non esista.** La prima stesura faceva
    `skipTest` fuori da Windows, e **due guardie indipendenti l'hanno bocciata** nello stesso
    giro (`controllo_3_skip_interni` del pre-volo e `test_gli_skip_interni_sono_solo_per_
    l_ambiente`): *«un test che si assolve da solo sparisce dal rapporto come skipped e nessuno
    lo legge piu'; asserisci in ENTRAMBI i rami invece di saltare»*. Avevano ragione, e la
    correzione ha reso la guardia **piu' forte**: `MSYSTEM` lo imposta **soltanto** MSYS/Git
    for Windows, quindi su Linux e su PowerShell e' vuoto per costruzione. Pretendere che sia
    vuoto **sempre** e' lo stesso invariante senza nessun salto — e vale anche in CI, dove
    prima non avrebbe guardato niente.
    """

    def test_la_suite_non_gira_da_GIT_BASH(self):
        # ⛔ Nessun `if` sul sistema operativo e nessun salto: l'invariante e' unico. `MSYSTEM`
        # esiste solo dentro MSYS/Git Bash; su Linux (CI) e da PowerShell e' vuoto, quindi
        # questa riga e' verde per costruzione dove il caso non si pone, e rossa dove si pone.
        msys = os.environ.get("MSYSTEM", "")
        self.assertFalse(
            msys,
            "SUITE LANCIATA DALLA SHELL SBAGLIATA (MSYSTEM=%r: Git Bash/MSYS).\n"
            "        Da qui `openssl` C'E', da PowerShell NO: le guardie sul ripristino dei "
            "backup si comportano in modo diverso, e questo giro NON misura la stessa "
            "macchina che misurera' il prossimo (sbaglio S11, direttiva D23 punto 3).\n"
            "        ⛔ Il risultato di questa suite NON vale. Rilanciala da PowerShell:\n"
            "            python -m unittest discover -s . -p \"test_*.py\"\n"
            "        Il numero dei test dichiarato in RIPRENDI_QUI.md (`SUITE ATTUALE:`) e' "
            "misurato in QUELLA shell, e la riga `AMBIENTE:` lo dice." % (msys,))

    def test_LA_GUARDIA_SA_DIRE_QUAL_E_LA_SHELL_GIUSTA(self):
        """D18 punto 1: il metro si misura prima del muro. Se domani `MSYSTEM` sparisse dai
        nomi che MSYS imposta, la guardia sopra tacerebbe per sempre e nessuno lo saprebbe —
        quindi qui si pretende che la variabile su cui si regge esista almeno come concetto
        noto, e che la riga AMBIENTE dichiari la shell."""
        with io.open(os.path.join(QUI, "RIPRENDI_QUI.md"), encoding="utf-8") as f:
            testo = f.read()
        self.assertIn(
            "AMBIENTE:", testo,
            "`RIPRENDI_QUI.md` non dichiara piu' l'ambiente della misura: senza quella riga "
            "nessuno sa in quale shell il numero della suite e' stato contato, e il confronto "
            "fra due giri non vale niente (D22 + D23)")


class TestIlBigliettoNONSiStracciaSeIlFileNONEDavveroTornato(unittest.TestCase):
    """🔐 L'IMPRONTA sha256 ENTRA NELLA RETE — finora la confrontavo A MANO.

    **Il buco, e non e' quello gia' chiuso.** La rete anti-interruzione protegge dal giro
    UCCISO: se il processo muore fra il «rompi» e il «ripara», il biglietto resta aperto e
    `collaudi/guardia_commit.py` -- che il gancio `pre-commit` esegue -- blocca il
    salvataggio. Quella parte funziona.

    Ma il biglietto si stracciava **senza guardare il file**. Lo schema e' sempre questo:

        finally:
            _riscrivi_intatto(pieno, sorgente)     # rimetto a posto
            _chiudi_traccia(pieno)                 # e straccio il biglietto

    Se la riscrittura solleva, il `finally` propaga e il biglietto resta (bene). Ma se
    riscrive **byte diversi** senza sollevare -- disco pieno che tronca, fine-riga tradotti,
    una codifica che cambia sotto -- il biglietto viene stracciato lo stesso, `guardia_commit`
    risponde **«via libera»**, e un file di produzione col guasto dentro entra nel commit con
    tutti i controlli verdi. E' esattamente il danno peggiore che questo strumento possa
    fare, per una strada che nessuno sorvegliava.

    **Finora a guardare era io.** Il 2026-08-17 ho confrontato gli sha256 a mano **quattro
    volte**, dopo ogni giro. Ha funzionato quattro volte su quattro — e *«la memoria umana
    non e' una strategia»* e' scritto in cima a `guardia_commit.py`. D18: la domanda non e'
    «ha barato?», e' «puo' barare?».

    ⛔ E LA RIPARAZIONE NON AGGIUNGE UN GANCIO NUOVO. Il gancio che serve c'e' gia' e gia'
    chiama `guardia_commit.py`: basta che il biglietto diventi **onesto** — si straccia solo
    se il file e' tornato identico al byte. Un pezzo in meno, non uno in piu' (regola ferrea 1).
    """

    def _motore(self):
        sys.path.insert(0, os.path.join(QUI, "collaudi"))
        import mutazione_prodotto
        return mutazione_prodotto

    def _guardia(self):
        sys.path.insert(0, os.path.join(QUI, "collaudi"))
        import guardia_commit
        return guardia_commit

    def _traccia_isolata(self, m):
        """⛔ MAI LA TRACCIA VERA. Un collaudo che usa la traccia condivisa spegne la rete di
        una campagna in corso: e' il difetto del 2026-08-03, che lascio' `fase184` mutato in
        produzione. Qui si punta a una cartella usa-e-getta e si rimette com'era."""
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        self.addCleanup(setattr, m, "_TRACCIA", m._TRACCIA)
        m._TRACCIA = os.path.join(d, "bookinvip_mutazione_in_corso")

    def _vittima(self, testo):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        percorso = os.path.join(d, "finto_modulo.py")
        with io.open(percorso, "w", encoding="utf-8", newline="") as f:
            f.write(testo)
        return percorso

    SANO = "def f(x):\n    return x == 0\n"
    MUTATO = "def f(x):\n    return x != 0\n"

    def test_un_ripristino_FALLITO_NON_puo_stracciare_il_biglietto(self):
        """La direzione «grida»: il file NON e' tornato quello di prima, quindi la rete resta
        accesa e il salvataggio resta bloccato."""
        m, g = self._motore(), self._guardia()
        self._traccia_isolata(m)
        percorso = self._vittima(self.SANO)
        m._apri_traccia(percorso, self.SANO)
        # il «ripristino» va storto SENZA sollevare: sul disco resta il mutante.
        with io.open(percorso, "w", encoding="utf-8", newline="") as f:
            f.write(self.MUTATO)
        m._chiudi_traccia(percorso)
        aperta, quali = g.mutazione_in_corso(m._TRACCIA)
        self.assertTrue(
            aperta,
            "il biglietto e' stato stracciato mentre sul disco c'e' ancora il mutante: da "
            "questo momento `guardia_commit.py` risponde «via libera» e un file di produzione "
            "col guasto dentro entra nel commit con tutti i controlli verdi")
        self.assertIn(
            percorso, quali,
            "la rete e' rimasta accesa ma non dice QUALE file e' rotto (%r): una guardia che "
            "sa meno di quello che potrebbe manda a cercare alla cieca" % (quali,))

    def test_un_ripristino_RIUSCITO_chiude_il_biglietto(self):
        """La direzione «tace». Se il file e' tornato identico al byte, il biglietto DEVE
        sparire: un allarme che resta acceso a lavoro finito blocca ogni commit successivo,
        e un allarme sempre acceso viene spento (regola ferrea 10)."""
        m, g = self._motore(), self._guardia()
        self._traccia_isolata(m)
        percorso = self._vittima(self.SANO)
        m._apri_traccia(percorso, self.SANO)
        with io.open(percorso, "w", encoding="utf-8", newline="") as f:
            f.write(self.MUTATO)                      # il giro rompe
        m._riscrivi_intatto(percorso, self.SANO)      # e ripara davvero
        m._chiudi_traccia(percorso)
        aperta, quali = g.mutazione_in_corso(m._TRACCIA)
        self.assertFalse(
            aperta,
            "il file e' tornato identico ma il biglietto e' rimasto aperto (%r): da qui in "
            "poi ogni salvataggio sarebbe bloccato per un guasto che non c'e', e la prima "
            "cosa che si fa con un allarme che suona a vuoto e' spegnerlo" % (quali,))

    def test_UN_ALTRO_giro_aperto_non_viene_travolto(self):
        """⛔ La rete non e' rientrante per caso: `test_mutation_money` apre un giro DENTRO un
        giro. Chiudere il proprio biglietto non deve toccare quello di un altro file — e
        nemmeno quando il proprio ripristino e' andato storto."""
        m, g = self._motore(), self._guardia()
        self._traccia_isolata(m)
        mio = self._vittima(self.SANO)
        altrui = self._vittima(self.SANO)
        m._apri_traccia(mio, self.SANO)
        m._apri_traccia(altrui, self.SANO)
        with io.open(mio, "w", encoding="utf-8", newline="") as f:
            f.write(self.MUTATO)                      # il MIO ripristino fallisce
        m._chiudi_traccia(mio)
        _aperta, quali = g.mutazione_in_corso(m._TRACCIA)
        self.assertIn(altrui, quali,
                      "il biglietto di un ALTRO giro e' sparito: da quel momento il suo file "
                      "di produzione non e' piu' protetto da nessuno (difetto del 2026-08-14)")
        self.assertIn(mio, quali,
                      "il mio biglietto e' sparito col mutante ancora sul disco")


class TestIlFoglioUnicoDeiControlli(unittest.TestCase):
    """🧾 UN FOGLIO SOLO — e le guardie che gli impediscono di diventare la SESTA copia.

    Ordine del fondatore, 2026-08-17: *«sono tanti e quelli dobbiamo farli per forza. Poi
    c'erano altri che sono scritti ma che non usiamo piu', perche' sono ancora scritti? Tanta
    roba da eliminare. Bisogna fare un foglio solo.»*

    Il pericolo non e' che il foglio manchi: e' che diventi **un riassunto**. Un riassunto
    invecchia -- e' successo il 2026-08-17 con la lista dei metodi AWS, che ha fatto ragionare
    una sessione intera sul numero sbagliato. Quindi qui si pretendono tre cose diverse:
    che il foglio sia **collegato** ai due momenti che contano · che ogni voce **punti a un
    posto che esiste** invece di contenere il fatto · e che la voce che sorveglia i numeri
    funzioni **nelle due direzioni** (grida sul numero sbagliato, tace su quello giusto).
    """

    def _foglio(self):
        sys.path.insert(0, os.path.join(QUI, "collaudi"))
        import foglio_unico
        return foglio_unico

    # ── il foglio e' COLLEGATO (appendice 23: costruito != collegato) ──────────────────
    def test_IL_FOGLIO_E_COLLEGATO_AI_DUE_MOMENTI_CHE_CONTANO(self):
        """All'AVVIO informa, al COMMIT conferma. Se qualcuno stacca una delle due chiamate,
        questa guardia diventa rossa lo stesso giorno (D18 punto 4).

        ⛔ SI GUARDA L'ALBERO SINTATTICO, NON IL TESTO — e non e' eleganza, e' una guardia
        gia' vista mentire. Scritta come «la parola `foglio_unico` compare nel file», il
        2026-08-17 e' rimasta VERDE con la chiamata cancellata: bastava che la parola
        sopravvivesse in un commento o in una docstring. E' esattamente lo sbaglio **S6**
        (*«ho scritto una guardia che un commento poteva soddisfare»*), ricomparso a nove
        giorni di distanza in un file nuovo. Un commento non produce un nodo `Call`.
        """
        import ast
        scollegati = []
        for nome in ("collaudi/regole_avvio.py", "collaudi/prima_di_dire_fatto.py"):
            with io.open(os.path.join(QUI, nome.replace("/", os.sep)), encoding="utf-8") as f:
                albero = ast.parse(f.read())
            chiamate = {
                n.func.attr
                for n in ast.walk(albero)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "foglio_unico"
            }
            mancanti = {"giro", "stampa"} - chiamate
            if mancanti:
                scollegati.append("%s non chiama foglio_unico.%s"
                                  % (nome, "/".join(sorted(mancanti))))
        self.assertEqual(
            scollegati, [],
            "il foglio unico non e' piu' CHIAMATO (non basta che sia nominato): %r. "
            "Costruito ma scollegato e' un controllo che misura se stesso invece del lavoro "
            "(appendice 23). All'avvio informa, al commit conferma: servono tutt'e due."
            % (scollegati,))

    def test_OGNI_VOCE_PUNTA_A_UN_POSTO_CHE_ESISTE(self):
        """⛔ LA GUARDIA CONTRO LA SESTA COPIA. Una voce vale solo se dice CHI possiede il
        fatto; se il posto non esiste, quella voce ha smesso di puntare e ha cominciato a
        raccontare. E' lo sbaglio S2 (i nomi si leggono, non si ricordano)."""
        fu = self._foglio()
        rotte = []
        for titolo, possiede, _funzione in fu.VOCI:
            self.assertTrue(possiede.strip(), "la voce %r non dice chi possiede il fatto"
                            % titolo)
            for pezzo in re.findall(r"[A-Za-z_][A-Za-z0-9_./]*\.(?:py|md)|deploy/hooks/",
                                    possiede):
                if not os.path.exists(os.path.join(QUI, pezzo.replace("/", os.sep))):
                    rotte.append("%s -> %s" % (titolo, pezzo))
        self.assertEqual(
            rotte, [],
            "queste voci puntano a un posto che non esiste piu': %r. Un foglio che punta nel "
            "vuoto e' diventato un riassunto, ed e' esattamente cio' che non doveva "
            "diventare." % (rotte,))

    def test_UNA_VOCE_CHE_ESPLODE_NON_DIVENTA_VERDE(self):
        """D18 punto 2, e sbaglio S7: se manca la premessa il controllo non e' verde, e'
        NON ESEGUITO. Un giro che inghiotte l'errore e stampa ✅ sarebbe il verde peggiore."""
        fu = self._foglio()
        def _esplode(_radice):
            raise RuntimeError("misura impossibile, di proposito")
        vere = fu.VOCI
        try:
            fu.VOCI = (("voce che esplode", "CLAUDE.md", _esplode),)
            esiti = fu.giro(QUI)
        finally:
            fu.VOCI = vere
        self.assertEqual(len(esiti), 1)
        self.assertEqual(
            esiti[0][3], fu.NON_ESEGUITO,
            "una voce che esplode e' uscita %r invece di NON ESEGUITO: il giro sta "
            "inghiottendo gli errori e stampando un verde che non ha guardato niente"
            % (esiti[0][3],))

    # ── la voce 7, provata NELLE DUE DIREZIONI su documenti finti ─────────────────────
    def _finto_progetto(self, righe_documento):
        """Un progetto in miniatura: un ingresso, due moduli (uno vivo, uno morto) e un
        documento. Cosi' la prova non tocca i documenti veri (D19) e non dipende da quanti
        moduli abbia il progetto oggi."""
        cartella = tempfile.mkdtemp(prefix="foglio_unico_")
        self.addCleanup(shutil.rmtree, cartella, True)
        with io.open(os.path.join(cartella, "main_casavip.py"), "w", encoding="utf-8") as f:
            f.write("import fase1_vivo\n")
        for nome in ("fase1_vivo.py", "fase2_morto.py"):
            with io.open(os.path.join(cartella, nome), "w", encoding="utf-8") as f:
                f.write("# niente\n")
        with io.open(os.path.join(cartella, "CLAUDE.md"), "w", encoding="utf-8") as f:
            f.write(righe_documento)
        return cartella

    def test_LA_VOCE_7_GRIDA_SUL_NUMERO_SBAGLIATO(self):
        """La direzione «grida». Nel finto progetto i moduli non raggiunti sono 1: un
        documento che ne scrive 7 sta mentendo sullo stato della macchina."""
        fu = self._foglio()
        dove = self._finto_progetto("Il piano: 7 moduli morti, si lavora su quelli vivi.\n")
        colpevoli, guasto = fu.numeri_scritti_a_mano(dove)
        self.assertIsNone(guasto, "la misura non e' riuscita: %s" % guasto)
        self.assertTrue(
            colpevoli,
            "la voce 7 NON ha visto un numero sbagliato scritto a mano (il documento dice 7, "
            "la macchina misura 1): e' una guardia che non puo' fallire, cioe' un ornamento")

    def test_LA_VOCE_7_TACE_SUL_NUMERO_GIUSTO(self):
        """La direzione «tace». Un falso allarme e' un difetto quanto un allarme mancato
        (regola ferrea 10): un allarme che suona sempre viene spento."""
        fu = self._foglio()
        dove = self._finto_progetto("Il piano: 1 moduli morti, si lavora su quelli vivi.\n")
        colpevoli, guasto = fu.numeri_scritti_a_mano(dove)
        self.assertIsNone(guasto, "la misura non e' riuscita: %s" % guasto)
        self.assertEqual(
            colpevoli, [],
            "la voce 7 grida su un numero GIUSTO: %r. Un falso allarme insegna a ignorare "
            "lo strumento, e allora non protegge piu' niente." % (colpevoli,))

    def test_LA_VOCE_7_NON_GRIDA_SU_UNA_MISURA_STORICA_NE_SU_ALTRI_MESTIERI(self):
        """Le due rinunce dichiarate, provate invece che promesse.

        (a) **la data esenta** — D22 dice che un numero si scrive con la misura che lo regge:
            «misurato il 2026-08-09: 7 moduli morti» e' una misura storica, non
            un'affermazione su oggi, e si tiene.
        (b) **il tema conta** — la parola «morti» vale anche per i punti di mutazione. Al
            primo giro questa voce ha prodotto nove falsi allarmi su trenta proprio cosi'
            (`39 vivi + 3 morti` erano mutanti, non moduli).
        """
        fu = self._foglio()
        dove = self._finto_progetto(
            "Misurato il 2026-08-09: 7 moduli morti su 151.\n"
            "fase59_concierge 114 punti, 72 uccisi -> 42 scoperti (39 vivi + 3 morti)\n")
        colpevoli, guasto = fu.numeri_scritti_a_mano(dove)
        self.assertIsNone(guasto, "la misura non e' riuscita: %s" % guasto)
        self.assertEqual(
            colpevoli, [],
            "la voce 7 ha gridato su una misura storica (che porta la sua data) o su un "
            "numero di un altro mestiere (punti di mutazione, non moduli): %r" % (colpevoli,))

    # ── la voce 10: quante guardie spegne la shell (sbaglio S11, aperto per sette giorni) ──
    def test_LA_VOCE_10_CONTA_LE_GUARDIE_SPENTE_COL_PARSER_NON_COL_GREP(self):
        """⛔ IL NUMERO CHE FINORA SCRIVEVO A MANO. Il 2026-08-17 la suite e' girata cinque
        volte e ogni volta ho dichiarato **io** che «5 guardie sui backup sono saltate»: una
        dichiarazione affidata a chi scrive e' precisamente cio' che questo progetto ha
        imparato a non fare (S11, D22).

        Si conta con `ast`, non col `grep`: un `def test_` dentro un commento o una docstring
        non produce un nodo dell'albero, quindi non puo' gonfiare il conto (sbaglio S6).
        """
        fu = self._foglio()
        for v in fu.GUARDIE_CHE_DIPENDONO_DAL_PATH:
            quanti = fu._metodi_di_prova(QUI, v["file"], v["classe"])
            self.assertIsInstance(
                quanti, int,
                "la voce 10 non trova %s::%s: sta stampando un conto su una classe che non "
                "esiste piu'" % (v["file"], v["classe"]))
            self.assertGreater(
                quanti, 0,
                "%s::%s risulta con zero metodi di prova: o la classe si e' svuotata, o il "
                "conto e' rotto — e in tutt'e due i casi il foglio direbbe «non si spegne "
                "niente» mentre qualcosa si spegne" % (v["file"], v["classe"]))

    def test_LA_VOCE_10_DIVENTA_ROSSA_SE_LA_CLASSE_SORVEGLIATA_SPARISCE(self):
        """D18 punto 1: il metro storto va scoperto dal metro. Se qualcuno rinomina la classe,
        il conto scenderebbe a zero e il foglio direbbe «tutto a posto» — cioe' il verde
        peggiore, quello che non ha guardato niente."""
        fu = self._foglio()
        vere = fu.GUARDIE_CHE_DIPENDONO_DAL_PATH
        try:
            fu.GUARDIE_CHE_DIPENDONO_DAL_PATH = ({
                "file": "test_backup_completo.py",
                "classe": "ClasseCheNonEsistePiu",
                "attrezzi": ("openssl",),
                "cosa_difende": "niente, e' la prova",
            },)
            stato, dettaglio = fu._v10_ambiente(QUI)
        finally:
            fu.GUARDIE_CHE_DIPENDONO_DAL_PATH = vere
        self.assertEqual(
            stato, fu.ROSSO,
            "con la classe sorvegliata sparita la voce 10 e' uscita %r (%s) invece di ROSSO: "
            "sta stampando un conto finto con l'aria di una misura" % (stato, dettaglio))

    def test_LA_VOCE_10_TACE_QUANDO_GLI_ATTREZZI_CI_SONO(self):
        """L'altra direzione (D18 punto 2). Un allarme provato in un verso solo potrebbe
        gridare sempre — e un allarme sempre acceso viene spento (regola ferrea 10). Qui si
        punta a un attrezzo che c'e' di sicuro: l'interprete con cui gira questo test."""
        import os as _os
        fu = self._foglio()
        vere = fu.GUARDIE_CHE_DIPENDONO_DAL_PATH
        interprete = _os.path.basename(sys.executable).replace(".exe", "")
        try:
            fu.GUARDIE_CHE_DIPENDONO_DAL_PATH = ({
                "file": "test_backup_completo.py",
                "classe": "TestRipristinoAPezziNonPassa",
                "attrezzi": (interprete,),
                "cosa_difende": "niente, e' la prova",
            },)
            spente, _dettagli, rotte = fu.guardie_spente_dalla_shell(QUI)
        finally:
            fu.GUARDIE_CHE_DIPENDONO_DAL_PATH = vere
        self.assertEqual(rotte, [], "la prova stessa e' rotta: %r" % (rotte,))
        self.assertEqual(
            spente, 0,
            "la voce 10 dichiara %d guardie spente mentre l'attrezzo che chiede (%r) e' "
            "presente: e' un falso allarme, e un falso allarme e' un difetto quanto un "
            "allarme mancato" % (spente, interprete))

    def test_SENZA_INGRESSI_LA_VOCE_7_NON_E_VERDE_MA_NON_ESEGUITA(self):
        """S1: il vuoto non e' un valore, e' l'assenza di misura. Se il camminatore non ha da
        dove partire, il foglio non deve dire «nessun numero sbagliato» -- non ha guardato."""
        fu = self._foglio()
        cartella = tempfile.mkdtemp(prefix="foglio_unico_vuoto_")
        self.addCleanup(shutil.rmtree, cartella, True)
        with io.open(os.path.join(cartella, "CLAUDE.md"), "w", encoding="utf-8") as f:
            f.write("999 moduli morti\n")
        stato, dettaglio = fu._v7_numeri(cartella)
        self.assertEqual(
            stato, fu.NON_ESEGUITO,
            "senza nessun ingresso la voce 7 e' uscita %r (%s): un controllo che non ha "
            "potuto misurare non e' un verde" % (stato, dettaglio))


class TestIlBrowserNonDIPENDEDaAPT(unittest.TestCase):
    """⛔ UN MIRROR UBUNTU GIU' NON DEVE TENERE FERMO IL CANCELLO.

    Misurato il 2026-08-19 sulla richiesta di unione #79. Il job `accessibilita` e' fallito
    **due volte su due** su questo passo:
    ```
    Failed to install browsers / Installation process exited with code: 100
    Ign: http://azure.archive.ubuntu.com/ubuntu noble InRelease
    ```
    Il cancello e' rimasto **rosso per mezz'ora** su un lavoro sui soldi che era tutto verde
    -- `money-smoke`, `full-suite`, `mutazione`, `copertura`, l'immagine di produzione e
    CodeQL: tutti `success`. Il prodotto non c'entrava niente.

    **La causa e' una confusione fra due cose diverse.** Il browser si scarica dalla CDN di
    Playwright; `--with-deps` invece reinstalla via **apt** le librerie di sistema di
    Chromium -- che nell'immagine dei runner **ci sono gia'**. Legandoli in un comando solo,
    un guasto del mirror Ubuntu diventa un guasto del nostro prodotto.

    ⛔ E la cura NON puo' essere `continue-on-error`: questi job stanno nel gate, e quel flag
    li farebbe risultare **success anche falliti** (una guardia sorella mi ci ha gia' preso
    oggi). Il ripiego sta **dentro** il comando, e l'ultima riga non e' protetta: se il
    browser davvero non si scarica, il job e' rosso -- ed e' giusto, perche' senza browser
    non si e' guardato niente.
    """
    def test_ogni_passo_che_installa_il_browser_ha_il_ripiego_senza_apt(self):
        import io
        import os
        import yaml
        percorso = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                ".github", "workflows", "ci.yml")
        with io.open(percorso, encoding="utf-8") as f:
            impianto = yaml.safe_load(f)
        passi = [(nome, p) for nome, corpo in (impianto.get("jobs") or {}).items()
                 for p in (corpo or {}).get("steps") or []
                 if isinstance(p.get("run"), str) and "playwright install" in p["run"]]
        self.assertTrue(passi,
                        "nessun passo installa il browser: o e' sparito il collaudo col "
                        "browser vero, o questa guardia sta misurando il nulla (S1)")
        for nome, p in passi:
            comando = p["run"]
            self.assertIn(
                "playwright install chromium", comando,
                "il job %r installa il browser SOLO con `--with-deps`, cioe' passando da "
                "apt: il giorno che il mirror Ubuntu non risponde il cancello si blocca su "
                "un guasto che col prodotto non c'entra. Serve il ripiego che scarica il "
                "solo browser (le librerie di sistema sono gia' nell'immagine)." % nome)
            self.assertNotIn(
                "|| true", comando,
                "il job %r nasconde il fallimento con `|| true`: senza browser non si e' "
                "guardato niente, e deve risultare rosso" % nome)


class TestOgniJobDellaCIHaUnTETTO(unittest.TestCase):
    """⛔ UN JOB SENZA TETTO PUO' TENERE FERMO IL CANCELLO PER SEI ORE.

    Misurato il 2026-08-19. Il job `atheris` fa un fuzz con un tetto di **due minuti**, ma
    e' rimasto appeso **110 minuti** su `apt-get install clang`: un intoppo del mirror, un
    passo senza attesa limitata, e il valore di serie di GitHub per un job e' **sei ore**.
    Il `gate` aspetta quel job, quindi un intoppo di rete blocca l'unione per una giornata
    intera -- e chi guarda vede solo «in corso», che somiglia moltissimo a «sta lavorando».

    ⛔ E' LA STESSA CREPA DEL 2026-08-18, quando il job del browser resto' appeso 19 minuti
    a scaricare Chromium. Quel giorno fu riparata **li'** -- attesa limitata e secondo
    tentativo -- e non fu cercata altrove: dieci job su quattordici erano ancora senza tetto.
    💡 Un difetto riparato in un posto solo torna: quello che chiude la classe non e' la
    riparazione, e' la guardia che la pretende **dappertutto**.

    ⚠️ I tetti sono scelti sul tempo MISURATO di ogni job (dal registro dei job del giro
    precedente), con abbondanza: un tetto stretto sarebbe un falso rosso che aspetta, e un
    falso allarme e' un difetto quanto un allarme mancato (regola ferrea 10).
    """
    def test_nessun_job_puo_restare_appeso_senza_limite(self):
        import io
        import os
        import yaml
        percorso = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                ".github", "workflows", "ci.yml")
        with io.open(percorso, encoding="utf-8") as f:
            impianto = yaml.safe_load(f)
        job = impianto.get("jobs") or {}
        self.assertTrue(job, "non ho trovato nessun job in ci.yml: senza l'elenco questa "
                             "guardia non sta misurando niente (S1)")
        senza = sorted(n for n, corpo in job.items() if "timeout-minutes" not in (corpo or {}))
        self.assertEqual(
            [], senza,
            "questi job della CI non dichiarano `timeout-minutes`: se uno si impianta resta "
            "appeso fino al valore di serie di GitHub (SEI ORE) e il `gate` aspetta lui, "
            "cioe' un intoppo di rete blocca l'unione per una giornata. Il tetto si sceglie "
            "sul tempo misurato del job, con abbondanza. Job scoperti: %r" % (senza,))


class TestNessunCollaudoPuoPRETENDERE_LaTariffaVECCHIA(unittest.TestCase):
    """⛔ UNA GUARDIA CHE CHIEDE IL DIFETTO E' PEGGIO DI NESSUNA GUARDIA.

    Misurato il 2026-08-19. `collaudi/collaudo_finale_totale.py` aveva `PSP = 300` scritto a
    mano: la tariffa tecnica di PRIMA del 2026-08-09, quando quella percentuale fu misurata
    **sotto costo** e sostituita. (⛔ La cifra non si scrive nemmeno qui: sbaglio S17, il
    numero vecchio che sopravvive nei commenti che spiegano il nuovo.) Due conseguenze, e la
    seconda e' la peggiore:

      · il collaudo «totale» faceva girare tutta la macchina con una tariffa **che non esiste
        in produzione** (e con quota fissa ZERO): non provava noi, provava un'altra azienda;
      · il suo controllo B1 pretendeva che il **contratto** e la **pagina host** dichiarassero
        la **cifra vecchia** -- cioe' il suo rosso ORDINAVA di rimettere dentro il numero
        sbagliato. Chi avesse obbedito avrebbe peggiorato il prodotto per far tacere un
        collaudo.

    E' la stessa forma che la revisione indipendente aveva gia' trovato il 2026-08-18 («una
    guardia validava il proprio elenco col criterio che quel commit dichiarava falso»). Il
    rimedio non e' aggiornare il numero: e' **toglierlo**. Un valore che descrive la macchina
    si legge dalla macchina (D22), se no il giorno che cambia resta indietro un'altra volta.
    """
    def test_la_tariffa_del_collaudo_totale_si_LEGGE_non_si_scrive(self):
        import ast
        import io
        import os
        radice = os.path.dirname(os.path.abspath(__file__))
        percorso = os.path.join(radice, "collaudi", "collaudo_finale_totale.py")
        with io.open(percorso, encoding="utf-8") as f:
            albero = ast.parse(f.read())
        assegnazioni = {}
        for nodo in albero.body:
            if isinstance(nodo, ast.Assign):
                for bersaglio in nodo.targets:
                    if isinstance(bersaglio, ast.Name):
                        assegnazioni[bersaglio.id] = nodo.value
        for nome in ("PSP", "PSP_FISSO"):
            self.assertIn(nome, assegnazioni,
                          "%s non esiste piu' in collaudo_finale_totale.py: se e' stato "
                          "rinominato, questa guardia va aggiornata insieme" % nome)
            valore = assegnazioni[nome]
            self.assertIsInstance(
                valore, ast.Call,
                "%s e' un valore SCRITTO A MANO (%s). La tariffa si legge da "
                "main_casavip.py: scritta qui, il giorno che cambia questo collaudo prova "
                "una macchina che non esiste e pretende che i documenti dichiarino la cifra "
                "vecchia." % (nome, ast.dump(valore)[:60]))

    def test_la_tariffa_letta_e_QUELLA_VERA_del_motore(self):
        """L'altra meta': non basta che sia letta, deve venire fuori il numero giusto.
        Un lettore che sbaglia espressione tornerebbe `None` o una cifra a caso, e la guardia
        di sopra sarebbe contenta lo stesso (D18 punto 1: prima si prova di saper misurare)."""
        import io
        import os
        import re
        radice = os.path.dirname(os.path.abspath(__file__))
        with io.open(os.path.join(radice, "main_casavip.py"), encoding="utf-8") as f:
            motore = f.read()
        atteso = int(re.search(r'PAGAMENTO_BPS["\']\s*,\s*["\'](\d+)["\']', motore).group(1))
        atteso_fisso = int(re.search(r'PAGAMENTO_FISSO_CENTS["\']\s*,\s*["\'](\d+)["\']',
                                     motore).group(1))
        import importlib
        collaudo = importlib.import_module("collaudi.collaudo_finale_totale")
        self.assertEqual(
            (collaudo.PSP, collaudo.PSP_FISSO), (atteso, atteso_fisso),
            "il collaudo totale gira con una tariffa diversa da quella del motore: "
            "collaudo=(%s, %s) motore=(%s, %s)"
            % (collaudo.PSP, collaudo.PSP_FISSO, atteso, atteso_fisso))


class TestIlDenominatoreDEVEPoterDireDiNO(unittest.TestCase):
    """`collaudi/denominatore.py` trasforma «cosa sto dimenticando?» in un numero. Ma un
    contatore che dice sempre «tutto coperto» e' peggio di nessun contatore: rassicura.

    ⛔ E' SUCCESSO AL PRIMO GIRO, il 19 agosto 2026. La prima versione cercava il nome nudo
    («la rotta compare da qualche parte?») e ha stampato **0 scoperte su tutte e quattro le
    famiglie**. Non era una buona notizia: era un criterio che non poteva fallire -- il modo
    di rompersi n. 4 dentro l'attrezzo che dovrebbe scoprirlo negli altri. Col criterio
    forte, la stessa macchina dichiara **77 coppie messaggio x lingua** che nessun collaudo
    genera.

    ⛔ E il verso opposto vale quanto questo (regola ferrea 10): la SECONDA versione accusava
    tre rotte innocenti (`/sitemap-host-`, `/stop`, `/host/azione`, dichiarate col prefisso e
    provate da sette file). Uno strumento che accusa innocenti viene spento.
    """
    @staticmethod
    def _attrezzo():
        import importlib
        return importlib.import_module("collaudi.denominatore")

    def test_una_voce_che_nessuno_nomina_viene_DICHIARATA_scoperta(self):
        """Il verso in cui deve GRIDARE."""
        d = self._attrezzo()
        testi = {"finto_test.py": 'g("GET", "/api/host/pubblica")\n'}
        self.assertFalse(
            d.attraversa("/api/rotta-che-non-esiste-in-nessun-collaudo", testi,
                         d._virgolette_o_prefisso("/api/rotta-che-non-esiste-in-nessun-collaudo")),
            "una rotta che nessuno chiama deve risultare SCOPERTA, se no il contatore "
            "e' un ornamento")

    def test_una_rotta_PREFISSO_chiamata_col_percorso_intero_NON_e_scoperta(self):
        """L'altra direzione: il falso allarme che ha gia' colpito una volta."""
        d = self._attrezzo()
        testi = {"finto_test.py": 'g("GET", "/sitemap-host-1.xml")\n'}
        self.assertTrue(
            d.attraversa("/sitemap-host-", testi, d._virgolette_o_prefisso("/sitemap-host-")),
            "`/sitemap-host-` e' un PREFISSO e il collaudo la chiama col percorso intero: "
            "dichiararla scoperta e' un falso allarme, e i falsi allarmi fanno spegnere "
            "l'attrezzo")

    def test_la_coppia_messaggio_lingua_vuole_la_STESSA_riga(self):
        """Non basta che un file parli di un messaggio in un punto e di una lingua in un
        altro: la coppia e' provata solo se quella riga genera QUEL messaggio in QUELLA
        lingua. E' il modo di rompersi n. 11 (lingua congelata), che nessun test aveva mai
        trovato -- lo vide il fondatore guardando il sito."""
        d = self._attrezzo()
        messaggi, codici = d.email(), d.lingue()
        self.assertTrue(messaggi and codici,
                        "senza messaggi o senza lingue non c'e' niente da misurare (S1): "
                        "messaggi=%r lingue=%r" % (messaggi, codici))
        m, c = messaggi[0], codici[0]
        vicine = {"a.py": '%s("x", lingua="%s")\n' % (m, c)}
        lontane = {"b.py": '%s("x")\nlingua = "%s"\n' % (m, c)}
        _tutte, mancanti_vicine = d.coppie_messaggio_lingua(vicine)
        _tutte, mancanti_lontane = d.coppie_messaggio_lingua(lontane)
        self.assertNotIn((m, c), mancanti_vicine,
                         "sulla stessa riga la coppia %s/%s e' provata" % (m, c))
        self.assertIn((m, c), mancanti_lontane,
                      "in due righe diverse la coppia %s/%s NON e' provata: contarla "
                      "sarebbe un verde finto" % (m, c))

    def test_il_CICLO_sulle_lingue_vale_quanto_le_otto_righe_scritte_a_mano(self):
        """⛔ Un contatore che premia il copia-incolla verrebbe ignorato.

        Se la coppia contasse SOLO quando la lingua e' scritta a mano sulla riga, un collaudo
        che fa `for lingua in LINGUE_SUPPORTATE:` -- cioe' il modo giusto, e quello che prova
        davvero tutte e otto -- risulterebbe SCOPERTO, e per far calare il numero bisognerebbe
        scrivere ottanta righe uguali. Un attrezzo che spinge a scrivere codice peggiore viene
        spento, e un attrezzo spento non protegge niente."""
        d = self._attrezzo()
        m = d.email()[0]
        col_ciclo = {"a.py": "for lingua in LINGUE_SUPPORTATE:\n    %s('x', lingua=lingua)\n" % m}
        senza = {"b.py": "%s('x', lingua=lingua)\n" % m}
        _tutte, mancanti_col_ciclo = d.coppie_messaggio_lingua(col_ciclo)
        _tutte, mancanti_senza = d.coppie_messaggio_lingua(senza)
        self.assertEqual([c for c in mancanti_col_ciclo if c[0] == m], [],
                         "il ciclo prova %s in tutte le lingue: dichiararlo scoperto e' un "
                         "falso allarme" % m)
        self.assertTrue([c for c in mancanti_senza if c[0] == m],
                        "senza ciclo e senza lingua scritta, %s NON e' provato in nessuna "
                        "lingua: contarlo sarebbe un verde finto" % m)

    def test_i_QUATTRO_TOTALI_li_produce_la_macchina_e_non_sono_zero(self):
        """D18 punto 1: lo strumento prova di essere in condizione di misurare PRIMA di
        misurare. Un totale a zero non e' «tutto coperto», e' assenza di misura (S1)."""
        d = self._attrezzo()
        for nome, quante in (("rotte", len(d.rotte())), ("pagine", len(d.pagine())),
                             ("email", len(d.email())), ("lingue", len(d.lingue()))):
            self.assertGreater(quante, 0,
                               "il denominatore delle %s e' ZERO: o e' cambiato il posto da "
                               "cui si conta, o l'attrezzo non sta misurando niente" % nome)


class TestLaSchedaNonSiScriveAMano(unittest.TestCase):
    """⛔ NESSUN BLOCCO POTEVA RISULTARE FINITO, MAI, PER COSTRUZIONE.

    Misurato il 2026-08-21: `collaudi/piano.py` stampava le condizioni di arrivo con `☐`,
    e quel `☐` era una **costante** (una sola riga, `print("       ☐ %s" % c)`); in tutto il
    progetto non esisteva **nessun `☑`**. Il fondatore ha passato settimane a chiedere «il
    Blocco 1 e' finito?» a una macchina costruita per non rispondere mai.

    💡 LA CURA, dalla ricerca (fitness function · attestation in-toto/SLSA · spec drift ·
    configuration drift), e' una sola frase: **un'affermazione sul sistema non esiste se non
    porta con se' chi l'ha prodotta, su quale commit, e su quante cose ha guardato.**
    Da cui la SCHEDA: nessuno la scrive a mano, e ogni riga porta le sue tre cose.

    ⛔ E LE QUATTRO REGOLE CHE LA RENDONO ONESTA, ognuna nata da un danno di oggi:
      · **mai misurata** non e' verde -- e' l'assenza di misura (sbaglio S1)
      · **misurata su un ALTRO commit** non vale piu': il codice e' cambiato sotto. E' la
        stessa regola dello schedario delle bombe («oltre quell'eta' non e' una misura, e'
        un ricordo»), ma sul COMMIT invece che sui giorni -- piu' stretta e piu' vera
      · **denominatore zero** non e' verde: `plausibilita.py` dice «ogni numero sta in una
        banda che il mondo consente» dopo averne guardato **uno**
      · **esito falso** resta rosso, ovviamente
    """

    def _scheda(self):
        percorso = os.path.join(QUI, "collaudi", "scheda.py")
        self.assertTrue(
            os.path.isfile(percorso),
            "collaudi/scheda.py non esiste: senza, nessuna casella potra' mai essere "
            "spuntata da una macchina, e «il Blocco 1 e' finito?» resta senza risposta")
        import importlib.util
        spec = importlib.util.spec_from_file_location("_scheda_prova", percorso)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        return modulo

    def test_IL_PIANO_NON_STAMPA_PIU_UNA_CASELLA_COSTANTE(self):
        """La casella dev'essere un RISULTATO, non una lettera scritta nel codice."""
        percorso = os.path.join(QUI, "collaudi", "piano.py")
        with io.open(percorso, encoding="utf-8") as f:
            sorgente = f.read()
        # ⛔ SI GUARDA IL CODICE, NON LA PROSA. La prima versione di questa guardia cercava la
        # riga vecchia dentro il testo grezzo, e il 2026-08-21 e' scattata sul COMMENTO che
        # quella riga la cita per spiegare il difetto: un falso allarme, e un falso allarme
        # costa quanto un allarme mancato (ferrea 10). `tokenize` butta via i commenti.
        import tokenize
        codice = []
        with open(percorso, "rb") as grezzo:
            for pezzo in tokenize.tokenize(grezzo.readline):
                if pezzo.type != tokenize.COMMENT:
                    codice.append(pezzo.string)
        solo_codice = " ".join(codice)
        # ⛔ `assertFalse(... in ...)` e NON `assertNotIn`: il secondo riverserebbe l'INTERO
        # file dentro il messaggio d'errore, e un rosso illeggibile non aiuta nessuno.
        self.assertFalse(
            "☐ %s" in solo_codice and "_scheda_stato" not in solo_codice,
            "collaudi/piano.py stampa ancora la casella VUOTA come costante, senza chiedere "
            "niente a nessuno: qualunque cosa facciamo, ogni blocco mostrera' per sempre "
            "quadratini vuoti")
        self.assertIn(
            "scheda", sorgente,
            "collaudi/piano.py non consulta la scheda: la casella non puo' venire da "
            "nessuna parte se non da una misura registrata")

    def test_LA_CASELLA_SI_SPUNTA_SOLO_CON_UNA_MISURA_VALIDA_SU_QUESTO_COMMIT(self):
        """Le quattro direzioni. Un giudizio che dice sempre di si' non e' un giudizio."""
        scheda = self._scheda()
        testo = "una condizione di prova, che nessuno misura davvero"
        vuoto = {}
        spuntata, motivo = scheda.stato(testo, 1, vuoto, impronta="aaaaaaa")
        self.assertFalse(spuntata, "una condizione MAI MISURATA non puo' risultare fatta")
        self.assertIn("mai misurata", motivo.lower(),
                      "il motivo deve dire che non e' stata misurata, non tacere: %r" % motivo)

        buona = {scheda.chiave(testo, 1): {"esito": True, "denominatore": 12,
                                           "comando": "python collaudi/finto.py",
                                           "impronta": "aaaaaaa", "commit": "c0ffee0",
                                           "quando": "2026-08-21T00:00:00"}}
        spuntata, motivo = scheda.stato(testo, 1, buona, impronta="aaaaaaa")
        self.assertTrue(spuntata,
                        "una misura VERA, sul commit giusto e con un denominatore, deve "
                        "spuntare la casella -- se no la scheda non serve a niente: %r" % motivo)

        for guasto, atteso, perche in (
                ({"esito": True, "denominatore": 12, "comando": "x",
                  "impronta": "bbbbbbb", "quando": "2026-08-21T00:00:00"},
                 "impronta",
                 "misurata su un ALTRO codice: i moduli del blocco sono cambiati sotto, "
                 "quella misura non parla piu' di questo codice"),
                ({"esito": True, "denominatore": 0, "comando": "x",
                  "impronta": "aaaaaaa", "quando": "2026-08-21T00:00:00"},
                 "denominatore",
                 "denominatore ZERO: un OK senza aver guardato niente e' il verde peggiore "
                 "di tutti (sbaglio S7)"),
                ({"esito": False, "denominatore": 12, "comando": "x",
                  "impronta": "aaaaaaa", "quando": "2026-08-21T00:00:00"},
                 "",
                 "esito falso: resta rossa")):
            with self.subTest(perche=perche):
                s, m = scheda.stato(testo, 1, {scheda.chiave(testo, 1): guasto},
                                    impronta="aaaaaaa")
                self.assertFalse(s, perche)
                if atteso:
                    self.assertIn(atteso, m.lower(),
                                  "il motivo non nomina la causa (%s): %r" % (atteso, m))

    def test_UNA_MISURA_SENZA_IL_COMANDO_CHE_LA_PRODUCE_NON_SI_REGISTRA(self):
        """Il giro completo di SCRITTURA, che senza questa guardia non provava nessuno.

        ⛔ E il comando non e' un ornamento: senza, chi legge la scheda fra sei mesi ha una
        casella verde e nessun modo di rifare la misura -- cioe' di nuovo un documento da
        credere sulla parola, che e' precisamente cio' che questa scheda esiste per abolire.
        """
        import shutil
        import tempfile
        scheda = self._scheda()
        culla = tempfile.mkdtemp(prefix="prova_scheda_")
        try:
            dove = os.path.join(culla, "scheda.json")
            testo = "una condizione di prova che qualcuno misura davvero"
            scheda.registra(testo, esito=True, denominatore=41,
                            comando="python collaudi/finto.py", ordine=1, percorso=dove,
                            commit="ccccccc")
            riletta = scheda.leggi(dove)
            # ⛔ Nessuna impronta passata a mano: la calcola lei sul progetto vero, la
            #    stessa che `registra` ha appena scritto. E' il giro completo.
            spuntata, motivo = scheda.stato(testo, 1, riletta)
            self.assertTrue(spuntata,
                            "scritta e riletta, la misura non spunta la casella: la scheda "
                            "non conserva quello che le si dice (%r)" % motivo)
            self.assertIn("41", motivo,
                          "il motivo non dice SU QUANTE COSE ha guardato: %r" % motivo)
            self.assertIn("finto.py", motivo,
                          "il motivo non dice CON QUALE COMANDO rifare la misura: %r" % motivo)
            with self.assertRaises(ValueError):
                scheda.registra(testo, esito=True, denominatore=1, comando="  ",
                                ordine=1, percorso=dove, commit="ccccccc")
        finally:
            shutil.rmtree(culla, ignore_errors=True)

    def test_CAMBIARE_IL_TESTO_DELLA_CONDIZIONE_INVALIDA_LA_MISURA(self):
        """⛔ La chiave e' l'IMPRONTA DEL TESTO, e non e' un dettaglio tecnico: se qualcuno
        riscrive la condizione, sta chiedendo un'altra cosa -- e la vecchia misura non
        risponde piu' a quella domanda. La casella deve tornare vuota DA SOLA."""
        scheda = self._scheda()
        prima = "i soldi tornano all'ospite da OGNI strada"
        dopo = "i soldi tornano all'ospite da ogni strada, ENTRO 24 ORE"
        registro = {scheda.chiave(prima, 1): {"esito": True, "denominatore": 7,
                                              "comando": "x", "impronta": "aaaaaaa",
                                              "quando": "2026-08-21"}}
        self.assertTrue(scheda.stato(prima, 1, registro, impronta="aaaaaaa")[0])
        spuntata, motivo = scheda.stato(dopo, 1, registro, impronta="aaaaaaa")
        self.assertFalse(
            spuntata,
            "la condizione e' stata RISCRITTA e la vecchia misura la spunta lo stesso: "
            "cosi' si dichiara fatta una cosa che nessuno ha mai verificato (%r)" % motivo)


class TestIlTraguardoDeveEssereRAGGIUNGIBILE(unittest.TestCase):
    """⛔⛔ SEI ESAMI IN SEI SESSIONI NON POTEVANO MAI STARE SPUNTATI INSIEME.

    Trovato il 2026-08-21 **dal fondatore**, con una domanda in italiano: *«se non è finito
    il Blocco 1 devi ricominciare da capo?»*. Sì — ogni volta. Dimostrato:
        lunedi'  passo l'esame 1 (commit A)  -> 1 su 2
        martedi' passo l'esame 2 (commit B)  -> l'esame 1 SI SVUOTA -> ancora 1 su 2
    La casella scadeva sul **commit**, e ogni sessione fa un commit: il traguardo era
    **impossibile per costruzione**. E' lo stesso difetto della casella-costante del giorno
    prima, tornato in una forma nuova -- e questa volta era stato COLLEGATO da me.

    ✅ LA CURA: la casella scade quando cambia **il codice che quella casella misura**
    (l'impronta dei moduli del blocco), non quando cambia un commit qualunque. Correggo un
    documento? La casella dei soldi resta. Tocco `fase85`? Scade, ed e' giusto.

    ⛔ Queste due guardie sono la ragione per cui il difetto non puo' tornare: la prima
    pretende che il traguardo si POSSA raggiungere, la seconda che la casella scada davvero
    quando deve. Senza la seconda, «raggiungibile» si otterrebbe non scadendo mai.
    """

    def _scheda(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_scheda_tragu", os.path.join(QUI, "collaudi", "scheda.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_SEI_ESAMI_PASSATI_IN_SEI_MOMENTI_DIVERSI_RESTANO_PASSATI(self):
        """La direzione che mancava: si passano uno alla volta e restano spuntati."""
        import shutil
        import tempfile
        scheda = self._scheda()
        culla = tempfile.mkdtemp(prefix="traguardo_")
        try:
            dove = os.path.join(culla, "scheda.json")
            esami = ["esame numero %d, finto" % i for i in range(1, 7)]
            # Si passano UNO ALLA VOLTA, come succede davvero: sei sessioni, sei momenti.
            for e in esami:
                scheda.registra(e, esito=True, denominatore=10, comando="prova finta",
                                ordine=1, percorso=dove)
            dati = scheda.leggi(dove)
            imp = scheda.impronta_del_blocco(1)
            self.assertTrue(imp, "impronta del blocco 1 non calcolabile: misura non valida")
            passati = [e for e in esami if scheda.stato(e, 1, dati, imp)[0]]
            self.assertEqual(
                len(passati), 6,
                "passati %d su 6: gli esami dati in momenti diversi si svuotano a vicenda, "
                "quindi il blocco non potra' MAI risultare finito -- e' lo stesso difetto "
                "della casella-costante, in forma nuova. Motivo del primo: %r"
                % (len(passati), scheda.stato(esami[0], 1, dati, imp)[1]))
        finally:
            shutil.rmtree(culla, ignore_errors=True)

    def test_MA_SE_CAMBIA_IL_CODICE_DEL_BLOCCO_LA_CASELLA_SCADE_LO_STESSO(self):
        """⛔ L'ALTRA DIREZIONE (ferrea 10), e senza di lei la prima sarebbe pericolosa:
        «raggiungibile» si otterrebbe benissimo non facendo scadere MAI niente -- cioe'
        dichiarando finito un blocco il cui codice e' cambiato sotto."""
        import shutil
        import tempfile
        scheda = self._scheda()
        culla = tempfile.mkdtemp(prefix="traguardo2_")
        try:
            dove = os.path.join(culla, "scheda.json")
            testo = "una condizione finta del blocco 1"
            scheda.registra(testo, esito=True, denominatore=10, comando="prova", ordine=1,
                            percorso=dove)
            dati = scheda.leggi(dove)
            self.assertTrue(scheda.stato(testo, 1, dati)[0],
                            "appena scritta e gia' non vale: la scheda non conserva niente")
            # Ora si finge che il codice del blocco sia cambiato.
            ok, motivo = scheda.stato(testo, 1, dati, impronta="cambiata0000")
            self.assertFalse(
                ok,
                "il codice del blocco e' cambiato e la casella resta SPUNTATA: cosi' si "
                "dichiara finito un blocco che nessuno ha piu' misurato (%r)" % motivo)
            self.assertIn("impronta", motivo.lower(),
                          "il motivo non dice che a cambiare e' stato il codice: %r" % motivo)
        finally:
            shutil.rmtree(culla, ignore_errors=True)


class TestDueBlocchiNonPossonoCondividereUnaCasella(unittest.TestCase):
    """⛔ SPUNTARE I SOLDI AVREBBE SPUNTATO ANCHE LE PRENOTAZIONI.

    Misurato il 2026-08-21, prima di scriverci sopra:
        caselle totali nel piano ........... 30
        chiavi distinte .................... 29
        chiavi CONDIVISE da piu' blocchi ....  1
          2x  blocchi [1, 2]  ->  «zero punti di mutazione scoperti sul codice che la
                                   produzione ESEGUE»        chiave 41d41915359a
    La chiave della scheda era lo sha256 del solo TESTO, e quella frase compare identica
    nel Blocco 1 (soldi) e nel Blocco 2 (prenotazioni). Un giro di mutazione sui soldi
    avrebbe dichiarato finito anche un blocco che nessuno aveva misurato.

    ⛔ NON E' UN DIFETTO NUOVO: e' lo stesso, identico, gia' trovato e riparato il
       2026-08-01 nello schedario degli equivalenti, dove la chiave non portava il nome
       della FUNZIONE e una dichiarazione si estendeva a tutte le righe identiche del file
       (`if residuo <= 0:` in due funzioni di fase177). La regola scritta li' vale qui
       parola per parola: **una dichiarazione vale SOLO dove e' stata dimostrata.**

    ⚠️ Era LATENTE per un motivo preciso: `scheda.json` non esiste e nessuno scrive. Il
       pezzo 5 del piano e' esattamente cio' che comincia a scrivere -- sarebbe stato quel
       lavoro ad accenderlo. Riparato prima, costa zero: nessuna misura da rifare.

    ⛔ E SI RIPARA LA CHIAVE, NON IL TESTO NEL PIANO. Riscrivere una delle due condizioni
       chiuderebbe QUESTO caso e lascerebbe la porta aperta: domani due blocchi fanno la
       stessa domanda con le stesse parole e il difetto torna, in silenzio. La chiave che
       porta il blocco lo chiude PER COSTRUZIONE -- e' la stessa lezione di
       `raggiungibilita.py`: il criterio giusto e' l'unico che non si puo' allargare.
    """

    def _scheda(self):
        import importlib.util
        percorso = os.path.join(QUI, "collaudi", "scheda.py")
        spec = importlib.util.spec_from_file_location("_scheda_chiave", percorso)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def _piano(self):
        import importlib.util
        percorso = os.path.join(QUI, "collaudi", "piano.py")
        spec = importlib.util.spec_from_file_location("_piano_chiave", percorso)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_OGNI_CASELLA_DEL_PIANO_HA_UNA_CHIAVE_TUTTA_SUA(self):
        """La direzione «oggi non ci sono doppioni», sul piano VERO."""
        import collections
        piano = self._piano()
        scheda = self._scheda()
        dove = collections.defaultdict(list)
        totale = 0
        for b in piano.BLOCCHI:
            for c in b["finito_quando"]:
                dove[scheda.chiave(c, b["ordine"])].append(b["ordine"])
                totale += 1
        # ⛔ IL DENOMINATORE SI DICHIARA: senza, «zero doppioni» su zero caselle sarebbe un
        #    verde per assenza -- la forma di bugia che questo progetto conosce meglio.
        self.assertGreater(totale, 0,
                           "nessuna casella nel piano: e' assenza di misura, non un verde")
        doppie = {k: v for k, v in dove.items() if len(v) > 1}
        self.assertFalse(
            doppie,
            "queste caselle sono LA STESSA per la scheda pur stando in blocchi diversi: "
            "spuntarne una spunterebbe l'altra, e un blocco risulterebbe finito senza che "
            "nessuno l'abbia misurato -- %r (su %d caselle esaminate)" % (doppie, totale))

    def test_LA_STESSA_DOMANDA_IN_DUE_BLOCCHI_DA_DUE_CHIAVI_DIVERSE(self):
        """L'altra direzione (ferrea 10): non basta che oggi non ci siano doppioni -- la
        scheda deve SAPER distinguere due blocchi che fanno la stessa domanda."""
        scheda = self._scheda()
        testo = "zero punti di mutazione scoperti sul codice che la produzione ESEGUE"
        self.assertNotEqual(
            scheda.chiave(testo, 1), scheda.chiave(testo, 2),
            "la stessa frase in due blocchi da' la STESSA chiave: la scheda non sa "
            "distinguere i soldi dalle prenotazioni")
        self.assertEqual(
            scheda.chiave(testo, 1), scheda.chiave("\n  ".join(testo.split()), 1),
            "normalizzare gli spazi cambia la chiave: mandare a capo una frase non cambia "
            "la domanda, e la casella non deve svuotarsi per una riformattazione")


class TestLaProduzioneDecideCosaValeLaPenaRompere(unittest.TestCase):
    """PEZZO 3 DEL PIANO — «la copertura decide cosa mutare».

    MISURATO il 2026-08-21 sull'AST, su tutti e 151 i moduli: su **7542** punti di
    mutazione, **1443 (19,13%)** stanno in moduli che la produzione NON raggiunge. Non sono
    punti difficili da uccidere: sono punti **impossibili** da uccidere --
      «Such mutants are unreachable and are unable to infect the program state, thus they
       can never be killed»  (arXiv 2210.17215)
    Un quinto della fatica di ogni giro andava li' dentro a produrre rossi che nessuno puo'
    chiudere, e un allarme che non si puo' chiudere si impara a ignorare (ferrea 10).

    ⚠️ Queste guardie non pretendono che il filtro esista: pretendono che, quando c'e', non
    menta in nessuna delle tre direzioni in cui puo' mentire.
    """

    def _mut(self):
        import importlib.util
        percorso = os.path.join(QUI, "collaudi", "mutazione_prodotto.py")
        spec = importlib.util.spec_from_file_location("_mut_guardia", percorso)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_IL_FILTRO_DELLA_PRODUZIONE_NON_PUO_SCARTARE_UN_INGRESSO(self):
        """⛔ `cammina()` elenca i `fase*` RAGGIUNTI dagli import: l'ingresso non e' fra
        loro, perche' e' il punto di PARTENZA. Senza correzione il filtro salterebbe in
        silenzio `main_casavip.py` -- il file da cui la produzione si accende -- contandolo
        fra i «non eseguiti dalla produzione», cioe' l'esatto contrario del vero.
        Trovato scrivendo il codice, prima di innestarlo."""
        import importlib.util
        m = self._mut()
        vivi, motivo = m.moduli_che_la_produzione_esegue(QUI)
        self.assertIsNotNone(vivi, "la raggiungibilita' non risponde: %s" % motivo)
        spec = importlib.util.spec_from_file_location(
            "_rag_guardia", os.path.join(QUI, "collaudi", "raggiungibilita.py"))
        rag = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rag)
        ingressi = rag.ingressi_veri(QUI)
        self.assertTrue(ingressi,
                        "nessun ingresso dichiarato esiste sul disco: misura non valida, "
                        "non un risultato (sbaglio S1)")
        for nome in ingressi:
            self.assertIn(nome[:-3], vivi,
                          "l'ingresso %s risulta NON eseguito dalla produzione: e' proprio "
                          "il file che la produzione AVVIA" % nome)

    def test_SENZA_LA_RAGGIUNGIBILITA_NON_SI_FILTRA_NIENTE(self):
        """⛔ L'assenza di misura non e' mai un permesso a sopprimere (sbaglio S1: il vuoto
        non e' un valore). Se lo strumento che dice «chi e' vivo» non risponde, si deve
        mutare TUTTO, non zero -- e si deve DIRE perche'."""
        m = self._mut()
        vivi, motivo = m.moduli_che_la_produzione_esegue(
            os.path.join(QUI, "_cartella_che_non_esiste_mai"))
        self.assertIsNone(
            vivi,
            "su una radice inesistente ha risposto un insieme (%r): starebbe filtrando su "
            "una misura che non c'e'" % (vivi,))
        self.assertTrue(str(motivo).strip(),
                        "ha rinunciato a filtrare SENZA dire perche': una rinuncia muta e' "
                        "indistinguibile da un filtro che funziona")

    def test_I_PUNTI_LASCIATI_FUORI_SONO_CONTATI_E_NOMINATI(self):
        """⛔ Un taglio silenzioso e' il difetto che questo strumento esiste per trovare.
        Il giro deve tenere il CONTO e i NOMI: un numero senza nomi non si puo' verificare,
        e «19% di punti in meno» diventerebbe indistinguibile da «19% che nessuno ha
        guardato»."""
        m = self._mut()
        _esiti, rinunce = m.giro_su_moduli([], minuti=0)
        self.assertIn("fuori_produzione", rinunce,
                      "il giro non tiene il conto dei punti lasciati fuori dalla produzione")
        self.assertIn("moduli_fuori_produzione", rinunce,
                      "il giro conta i punti ma non dice su QUALI moduli")

    def test_UN_GIRO_CHE_HA_SALTATO_TUTTO_NON_ESCE_VERDE(self):
        """⛔ Saltare codice che la produzione non esegue e' una SCELTA del piano, non un
        buco -- ma un giro lanciato solo su moduli morti non ha misurato niente, e uscire 0
        li' sarebbe il verde per assenza. Le due direzioni, con e senza punti esaminati."""
        m = self._mut()
        rinunce = {"fuori_produzione": 42, "moduli_fuori_produzione": ["fase17_money.py"]}
        uscita, motivi = m.verdetto_modulo([], rinunce)
        self.assertEqual(uscita, 1,
                         "ha saltato 42 punti, non ne ha esaminato nessuno, ed esce VERDE: "
                         "e' il verde per assenza (%r)" % motivi)
        # ...e con almeno un punto davvero esaminato, i saltati NON lo fanno rosso.
        esiti = [{"file": "fase85_pagamenti_stripe.py", "riga": 1, "verdetto": "ucciso",
                  "danno": "finto"}]
        uscita2, motivi2 = m.verdetto_modulo(esiti, rinunce)
        self.assertEqual(uscita2, 0,
                         "un punto esaminato e ucciso, piu' dei saltati DICHIARATI, deve "
                         "restare verde: altrimenti il filtro rende impossibile il verde "
                         "(%r)" % motivi2)


class TestIlGiudiceScriveDaSeLaScheda(unittest.TestCase):
    """PEZZO 5 DEL PIANO — «il Giudice scrive da se' la scheda, il guardiano la pretende».

    La scheda sa registrare dal 2026-08-21, ma NESSUN attrezzo la scriveva: Blocco 1 = 0 su
    6, e `piano.py` lo diceva da solo («ma nessuno la scrive ancora»). E' la regola #23 in
    forma pura: COSTRUITO != COLLEGATO.
    """

    def _mut(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_mut_scheda", os.path.join(QUI, "collaudi", "mutazione_prodotto.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_IL_TESTO_DELLA_CASELLA_SI_LEGGE_DAL_PIANO_E_NON_SI_RICOPIA(self):
        """⛔ LA TRAPPOLA VERA DI QUESTO PEZZO. La chiave della scheda e' lo sha256 del
        testo: una copia con UN carattere diverso non spunterebbe mai quella casella, e
        resterebbe «mai misurata» -- indistinguibile dal non aver lanciato lo strumento.
        Un ROSSO finto, che fa rifare un lavoro gia' fatto."""
        import importlib.util
        m = self._mut()
        spec = importlib.util.spec_from_file_location(
            "_piano_g", os.path.join(QUI, "collaudi", "piano.py"))
        piano = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(piano)
        for ordine in (1, 2):
            testo = m.condizione_della_mutazione(QUI, ordine)
            blocco = [b for b in piano.BLOCCHI if b["ordine"] == ordine][0]
            self.assertIn(
                testo, list(blocco["finito_quando"]),
                "per il blocco %d il giudice usa un testo che nel piano NON c'e': quella "
                "casella non si spuntera' mai, e nessuno se ne accorgera'" % ordine)

    def test_SE_LE_CASELLE_CANDIDATE_NON_SONO_UNA_SI_FERMA_INVECE_DI_INDOVINARE(self):
        """⛔ Zero candidate = il piano e' cambiato sotto. Due = non si sa quale si sta
        misurando. In tutti e due i casi la risposta giusta e' un'eccezione: spuntare la
        casella sbagliata avvelenerebbe lo strumento nato per smettere di mentire."""
        m = self._mut()
        with self.assertRaises(ValueError):
            m.condizione_della_mutazione(QUI, ordine=3)   # il blocco 3 non ha quella casella

    def test_UN_GIRO_MISTO_NON_DICHIARA_FINITO_NESSUN_BLOCCO(self):
        """⛔ Le caselle sulla mutazione sono DUE. Un giro su moduli di blocchi diversi non
        ha finito nessuno dei due, e non si sceglie a maggioranza."""
        m = self._mut()
        ordine, motivo = m.blocco_dei_moduli(["fase85_pagamenti_stripe.py",
                                              "fase111_cancellazione.py"])
        self.assertIsNone(ordine,
                          "un giro su soldi E prenotazioni ha scelto il blocco %r: cosi' "
                          "si dichiara misurato un blocco che nessuno ha guardato (%s)"
                          % (ordine, motivo))
        solo_soldi, _ = m.blocco_dei_moduli(["fase85_pagamenti_stripe.py"])
        self.assertEqual(solo_soldi, 1,
                         "un giro sui soli moduli dei soldi deve riconoscere il Blocco 1")

    def test_UN_GIRO_SU_UN_MODULO_NON_DICHIARA_FINITI_VENTIQUATTRO(self):
        """⛔ IL BUCO PIU' GROSSO CHE QUESTO PEZZO POTEVA LASCIARE.

        La casella dice «zero punti di mutazione scoperti sul codice che la produzione
        ESEGUE» -- cioe' su TUTTO il blocco. Spuntarla dopo un giro su `fase188` (4 punti)
        dichiarerebbe misurati anche gli altri 23 moduli dei soldi, che nessuno ha aperto.
        E' la stessa malattia della chiave condivisa, un piano piu' su.

        ⛔ E non basta scrivere `esito=False`: direbbe «misurata e non passa», mentre la
        verita' e' «non l'ho misurata affatto». Un rosso falso manda a caccia di un guasto
        che non esiste e costa quanto un verde falso (ferrea 10). Non si scrive.
        """
        import shutil
        import tempfile
        m = self._mut()
        culla = tempfile.mkdtemp(prefix="scheda_parziale_")
        try:
            finta = os.path.join(culla, "scheda.json")
            esiti = [{"file": "fase188_paga_struttura.py", "riga": 1, "verdetto": "ucciso",
                      "danno": "finto"}]
            riga, motivo = m.scrivi_la_scheda(esiti, {}, comando="prova", radice=QUI,
                                              percorso=finta)
            self.assertIsNone(
                riga,
                "un giro su UN modulo ha spuntato la casella di tutto il blocco: cosi' si "
                "dichiara finito un blocco che nessuno ha misurato (%s)" % motivo)
            self.assertIn("blocco", str(motivo).lower(),
                          "non dice che il giro era incompleto: %r" % motivo)
            self.assertFalse(
                os.path.isfile(finta),
                "ha comunque creato la scheda: una casella che non si puo' dichiarare non "
                "deve lasciare traccia, o al giro dopo sembrera' misurata")
        finally:
            shutil.rmtree(culla, ignore_errors=True)

    def test_LA_CASELLA_DELLA_MUTAZIONE_SI_MISURA_DOVE_PASSA_IL_DENARO(self):
        """⛔ DECISIONE DEL FONDATORE, 2026-08-22 — e nasce da una misura, non da una comodita'.

        La casella pretendeva zero punti scoperti su TUTTI i 24 moduli del blocco: misurati
        col censimento sono **1.097 punti**, e a 84 secondi a punto (misurato su `fase87` il
        2026-08-22: 15 punti in 21 minuti) fanno **~25 ore di solo calcolo**, prima ancora di
        scrivere i test che mancheranno. Peggio: quel numero **cresce** quando si migliora il
        generatore -- da 6.012 a 7.566 punti in due settimane, a codice fermo. Un traguardo
        che si allontana mentre cammini non e' severo: e' irraggiungibile, ed e' il motivo per
        cui il Blocco 1 e' rimasto aperto dal 20 luglio al 22 agosto.

        💡 E lo dice anche la ricerca gia' in casa (appendice, Google): l'85% dei mutanti e'
        inutile e **il punteggio di mutazione non e' il numero da inseguire**. Noi lo stavamo
        inseguendo su tutto il blocco.

        La riga d'arrivo diventa il **percorso del denaro**: i moduli che un euro attraversa
        davvero quando entra, si divide e esce. Restano dichiarati in `piano.py`, non qui:
        una copia potrebbe mentire il giorno che il piano cambia.

        ⛔ E si prova nelle DUE direzioni (D18 punto 2): un giro che li copre TUTTI scrive,
        un giro che ne salta anche UNO SOLO non scrive. Senza la seconda meta', "raggiungibile"
        si otterrebbe semplicemente non pretendendo piu' niente.
        """
        import importlib.util
        import shutil
        import tempfile
        spec = importlib.util.spec_from_file_location(
            "_piano_denaro", os.path.join(QUI, "collaudi", "piano.py"))
        piano = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(piano)
        blocco = [b for b in piano.BLOCCHI if b["ordine"] == 1][0]
        moduli_mut = tuple(blocco.get("moduli_mutazione") or ())
        self.assertTrue(
            moduli_mut,
            "il blocco 1 non dichiara su QUALI moduli si misura la mutazione: senza, la "
            "casella torna a pretendere tutti i %d moduli del blocco (1.097 punti, ~25 ore) "
            "e il blocco non finisce mai" % len(blocco["moduli"]))
        self.assertTrue(
            set(moduli_mut) <= set(blocco["moduli"]),
            "i moduli della mutazione non sono un sottoinsieme del blocco: %r"
            % (sorted(set(moduli_mut) - set(blocco["moduli"])),))
        m = self._mut()
        culla = tempfile.mkdtemp(prefix="scheda_denaro_")
        try:
            esiti = [{"file": n + ".py", "riga": 1, "verdetto": "ucciso",
                      "danno": "finto, per la guardia"} for n in moduli_mut]
            riga, motivo = m.scrivi_la_scheda(
                esiti, {}, comando="prova", radice=QUI,
                percorso=os.path.join(culla, "tutti.json"))
            self.assertIsNotNone(
                riga,
                "un giro che copre TUTTO il percorso del denaro non spunta la casella: il "
                "traguardo resta irraggiungibile (%s)" % motivo)
            riga2, motivo2 = m.scrivi_la_scheda(
                esiti[:-1], {}, comando="prova", radice=QUI,
                percorso=os.path.join(culla, "meno_uno.json"))
            self.assertIsNone(
                riga2,
                "ha spuntato la casella saltando %r: cosi' 'raggiungibile' si otterrebbe "
                "non pretendendo piu' niente (%s)" % (moduli_mut[-1], motivo2))
        finally:
            shutil.rmtree(culla, ignore_errors=True)

    def test_UN_GIRO_CHE_NON_HA_ESAMINATO_NIENTE_NON_SPUNTA_LA_CASELLA(self):
        """⛔ Denominatore zero non e' verde. La scheda gia' lo applica: qui si pretende che
        il COLLEGAMENTO lo rispetti, cioe' che il giudice le passi i punti VERAMENTE
        esaminati e non una costante."""
        import importlib.util
        import shutil
        import tempfile
        m = self._mut()
        # ⛔ SU UNA SCHEDA FINTA: un collaudo non usa mai l'attrezzo vero. Scrivendo su
        #    `collaudi/scheda.json` questa guardia spunterebbe una casella VERA girando
        #    dentro la suite -- verde perche' un test l'ha scritto, non perche' qualcuno
        #    abbia misurato. Il verde finto piu' velenoso che ci sia.
        culla = tempfile.mkdtemp(prefix="scheda_guardia_")
        try:
            finta = os.path.join(culla, "scheda.json")
            # ⛔ TUTTI i moduli del blocco, o il giro risulta incompleto e (giustamente)
            #    non scrive affatto -- vedi la guardia sul giro parziale qui sotto. Qui si
            #    misura l'ALTRA cosa: giro completo, ma nessun punto esaminato.
            spec = importlib.util.spec_from_file_location(
                "_piano_den", os.path.join(QUI, "collaudi", "piano.py"))
            piano = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(piano)
            del_blocco = [b for b in piano.BLOCCHI if b["ordine"] == 1][0]["moduli"]
            esiti = [{"file": n + ".py", "riga": 0, "verdetto": "assente",
                      "danno": "finto, per la guardia"} for n in del_blocco]
            riga, motivo = m.scrivi_la_scheda(esiti, {}, comando="prova finta", radice=QUI,
                                              percorso=finta)
            self.assertIsNotNone(riga, "non ha scritto niente: %s" % motivo)
            self.assertEqual(riga["denominatore"], 0,
                             "un giro senza punti esaminati dichiara di averne guardati %r"
                             % riga["denominatore"])
            spec = importlib.util.spec_from_file_location(
                "_scheda_g", os.path.join(QUI, "collaudi", "scheda.py"))
            sch = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(sch)
            ok, perche = sch.stato(riga["condizione"], riga["blocco"], sch.leggi(finta),
                                   riga["impronta"])
            self.assertFalse(ok,
                             "denominatore ZERO e la casella risulta SPUNTATA: %s" % perche)
        finally:
            shutil.rmtree(culla, ignore_errors=True)


class TestIMutantiSuiLogNonSiSopprimonoMai(unittest.TestCase):
    """PEZZO 4 DEL PIANO — e la ragione, MISURATA, per cui non si costruisce come Google.

    Misurato il 2026-08-21 sull'AST, su tutti e 151 i moduli, denominatore **7542** punti:
        attese/memoria/print/assiomatici (sopprimibili) ...     1 punto  (0,01%)
        LOG ...............................................   403 punti (5,34%)
    Google dichiara ~85% di mutanti improduttivi tolti dai nodi aridi: il loro C++ e' pieno
    di `std::vector::reserve`, `Wait` gRPC e cache lookup. Il nostro Python dei soldi non ne
    ha. Costruire quel meccanismo qui toglierebbe UN punto su 7542 e lascerebbe in casa un
    interruttore che un domani qualcuno allarga fino ai mutanti veri sui soldi -- rischio
    che Google stessa dichiara: «the proposed heuristic **may suppress mutation in relevant
    nodes** as a side-effect».

    ⛔ Quindi il pezzo 4 si chiude con LA MISURA SOTTO GUARDIA, non con un meccanismo --
    deciso dal fondatore il 2026-08-21. Se un domani il codice cambia (arrivano attese,
    cache, code), questo numero cambia e la decisione si rivede: con un dato, non con un
    ricordo.
    """

    def test_NESSUNA_SOPPRESSIONE_SUI_LOG_E_ENTRATA_NEL_GENERATORE(self):
        """La falsa equivalenza sui log fu tolta il 2026-08-01 perche' FALSA (`exc_info` e'
        osservabile), e il 14/08 quei mutanti hanno scoperto SETTE guardie finte. Se
        qualcuno la rimettesse, sette bugie tornerebbero invisibili."""
        percorso = os.path.join(QUI, "collaudi", "mutazione_prodotto.py")
        # ⛔ I COMMENTI SI BUTTANO VIA: una guardia identica, il 2026-08-21, era un FALSO
        #    ALLARME perche' scattava sul COMMENTO che cita la riga vecchia. Chi legge del
        #    codice deve sapere cos'e' codice e cos'e' prosa (ferrea 10).
        import tokenize
        codice = []
        with open(percorso, "rb") as grezzo:
            for pezzo in tokenize.tokenize(grezzo.readline):
                if pezzo.type != tokenize.COMMENT:
                    codice.append(pezzo.string)
        solo_codice = " ".join(codice)
        for spia in ("nodo_arido", "sopprimi_log", "_e_arido", "NODI_ARIDI"):
            # ⛔ `assertFalse(... in ...)` e NON `assertNotIn`: il secondo riverserebbe
            #    l'INTERO file nel messaggio d'errore, e un rosso illeggibile non aiuta.
            self.assertFalse(
                spia in solo_codice,
                "nel CODICE di mutazione_prodotto.py compare %r: se e' una soppressione sui "
                "log, sta rimettendo la falsa equivalenza tolta il 2026-08-01 perche' FALSA "
                "-- e il 14/08 quei mutanti hanno scoperto SETTE guardie finte" % spia)

    def test_I_PUNTI_SUI_LOG_ESISTONO_ANCORA_E_SONO_TANTI(self):
        """⛔ L'altra direzione, e senza di lei la guardia sopra sarebbe vuota: si puo'
        smettere di sopprimere i log anche solo smettendo di GENERARE mutanti li' sopra.
        Qui si pretende il fatto positivo, con il suo denominatore: su un modulo dei soldi
        che contiene log, i punti su quelle righe devono esserci."""
        import importlib.util
        import re
        spec = importlib.util.spec_from_file_location(
            "_mut_log", os.path.join(QUI, "collaudi", "mutazione_prodotto.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        LOG = re.compile(r"\b(?:logger|logging|log)\s*\.\s*(?:debug|info|warning|error|"
                         r"critical|exception)\b")
        esaminati = su_log = 0
        for nome in ("fase177_financial_controller.py", "fase131_payout_dashboard.py"):
            percorso = os.path.join(QUI, nome)
            if not os.path.isfile(percorso):
                continue
            with io.open(percorso, encoding="utf-8", errors="replace") as f:
                sorgente = f.read()
            mutanti, _ = m.genera_mutanti(sorgente)
            righe = sorgente.splitlines()
            esaminati += len(mutanti)
            su_log += sum(1 for mu in mutanti
                          if mu["riga"] <= len(righe) and LOG.search(righe[mu["riga"] - 1]))
        self.assertGreater(esaminati, 0,
                           "nessun punto esaminato: misura non valida, non un verde (S1)")
        self.assertGreater(
            su_log, 0,
            "su %d punti esaminati in due moduli dei soldi che CONTENGONO log, nemmeno uno "
            "cade su una riga di log: qualcuno ha smesso di generarli, che e' sopprimerli "
            "senza chiamarlo cosi'" % esaminati)


class TestIlBancoSIPUOGIUDICAREANCHEFUORIDALCONTENITORE(unittest.TestCase):
    """⛔ IL BANCO DICHIARAVA SETTE BUCHI, E CINQUE AVEVANO LA MOTIVAZIONE SBAGLIATA.

    Misurato il 2026-08-20. `collaudi/giro_banco.py` cerca i database SOLO in `/data` e
    `/app/data`, cioe' dentro il contenitore, e accanto ai controlli saltati scriveva «il
    database sta in /data». Ma il banco che quei controlli devono giudicare e'
    `collaudi/avvia_server_visivo.py`, che i database li mette in una cartella temporanea
    senza nome — e il libro giornale non lo metteva da nessuna parte: `db_finanza` restava
    `:memory:` per omissione, cioe' non esisteva su nessun disco. Quindi non era «colpa di
    Docker»: era il giudice che cercava dove il giudicato non aveva mai scritto.

    Le tre cose che rendono quei controlli MISURABILI, piu' la quarta che toglie un verde
    per assenza dallo stesso file.

    ⛔ COSA QUESTE GUARDIE NON FANNO (D18 punto 3): non eseguono il giro del banco — servono
    un server sulla 8080 e una chiave Stripe di prova — quindi NON dicono che i conti
    tornano. Dicono che si possono guardare. Il verdetto sui conti lo da' solo il giro.
    """

    def _funzione_del_banco(self, nome):
        """Prende una funzione VERA da `collaudi/giro_banco.py` e la rende chiamabile da
        sola. Il file non si puo' importare: appena importato ESEGUE il giro intero, che
        parla con un server sulla 8080. Quindi si estrae il nodo col parser di Python e lo
        si esegue: cosi' la guardia prova CIO' CHE LA FUNZIONE FA, non che nel testo
        compaia una parola — che e' lo sbaglio S6."""
        import ast
        import sqlite3
        with io.open(os.path.join(QUI, "collaudi", "giro_banco.py"),
                     encoding="utf-8") as f:
            sorgente = f.read()
        nodo = None
        for n in ast.parse(sorgente).body:
            if isinstance(n, ast.FunctionDef) and n.name == nome:
                nodo = n
        self.assertIsNotNone(nodo, "collaudi/giro_banco.py non ha piu' la funzione %s(): "
                                   "o e' stata rinominata, o qualcuno l'ha tolta" % nome)
        spazio = {"os": os, "sqlite3": sqlite3}
        # ⛔ IL NOME FRA PARENTESI ANGOLARI NON E' ORNAMENTO. Qui c'era `"giro_banco.%s"`,
        # che con `nome="db"` diventava **`giro_banco.db`**: per `coverage` e' il percorso di
        # un sorgente da aprire, non lo trova e **muore** -- `No source for code`, uscita 1.
        # Il job `copertura` della CI e' andato rosso cosi' il 2026-08-20, e la copertura non
        # e' stata nemmeno calcolata (`COPERTURA TOTALE = n/d`). Le parentesi angolari sono la
        # convenzione di Python per il codice che NON viene da un file (`<string>`, `<stdin>`),
        # e gli strumenti la rispettano.
        exec(compile(ast.Module(body=[nodo], type_ignores=[]),
                     "<giro_banco.%s>" % nome, "exec"), spazio)
        return spazio[nome]

    def _con_cartella_dichiarata(self, cartella, azione):
        """Esegue `azione` con `BANCO_DATI` impostata, e rimette l'ambiente com'era: una
        guardia che sporca l'ambiente del processo fa cadere i test che vengono dopo, e il
        rosso finirebbe addosso a chi non c'entra."""
        prima = os.environ.get("BANCO_DATI")
        os.environ["BANCO_DATI"] = cartella
        try:
            return azione()
        finally:
            if prima is None:
                os.environ.pop("BANCO_DATI", None)
            else:
                os.environ["BANCO_DATI"] = prima

    def test_il_banco_LEGGE_i_database_dalla_cartella_che_il_server_DICHIARA(self):
        import sqlite3
        cartella = tempfile.mkdtemp(prefix="banco_dati_")
        c = sqlite3.connect(os.path.join(cartella, "finanza.db"))
        c.execute("CREATE TABLE libro_giornale (seq INTEGER)")
        c.commit()
        c.close()
        db = self._funzione_del_banco("db")
        conn = self._con_cartella_dichiarata(cartella, lambda: db("finanza"))
        self.assertIsNotNone(
            conn, "il banco non guarda nella cartella che il server dichiara (BANCO_DATI): "
                  "fuori da Docker i cinque controlli sui soldi non sono misurabili affatto, "
                  "e il motivo scritto accanto a loro dice il falso")
        conn.close()

    def test_dove_non_c_e_niente_il_banco_dice_NON_SO_e_non_esplode(self):
        """L'altra direzione (regola ferrea 10): un allarme provato in un verso solo
        potrebbe gridare sempre. Qui si pretende il silenzio quando non c'e' niente da
        leggere — `None`, cioe' «non misurabile», mai una connessione finta."""
        db = self._funzione_del_banco("db")
        vuota = os.path.join(tempfile.mkdtemp(prefix="banco_vuoto_"), "che_non_esiste")
        self.assertIsNone(self._con_cartella_dichiarata(vuota, lambda: db("finanza")),
                          "senza database il banco deve dire «non misurabile», non "
                          "restituire qualcosa su cui poi si conterebbero righe inesistenti")

    def test_il_banco_scrive_il_LIBRO_GIORNALE_su_file_e_non_in_memoria(self):
        """`db_finanza` non era dichiarato affatto e il valore predefinito e' `:memory:`:
        il libro dei soldi del banco viveva nella RAM del server e moriva con lui. E' il
        modo di rompersi n. 1 (dati effimeri) dentro lo strumento che deve scoprirlo."""
        import ast
        with io.open(os.path.join(QUI, "collaudi", "avvia_server_visivo.py"),
                     encoding="utf-8") as f:
            sorgente = f.read()
        chiamata = None
        for n in ast.walk(ast.parse(sorgente)):
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "ConfigCasaVIP":
                chiamata = n
        self.assertIsNotNone(chiamata, "il banco non costruisce piu' ConfigCasaVIP")
        detti = dict((k.arg, k.value) for k in chiamata.keywords if k.arg)
        for campo, chi in (("db_finanza", "il libro giornale"),
                           ("db_payout", "i soldi in attesa dell'host")):
            self.assertIn(campo, detti,
                          "%s del banco non e' dichiarato: resta `:memory:` per omissione, "
                          "e da fuori non lo legge nessuno" % chi)
            pezzi = [p.value for p in ast.walk(detti[campo])
                     if isinstance(p, ast.Constant) and isinstance(p.value, str)]
            self.assertNotIn(":memory:", pezzi,
                             "%s del banco sta in RAM: nessun processo esterno puo' "
                             "guardarlo, quindi i controlli contabili non si misurano" % chi)
            atteso = campo[3:] + ".db"     # db_finanza -> finanza.db, come cerca `db(nome)`
            self.assertTrue(any(p.endswith(atteso) for p in pezzi),
                            "il file di %s non si chiama %s: `db(nome)` cerca `nome + .db`, "
                            "e con un altro nome non lo trova mai" % (chi, atteso))

    def test_i_database_fuori_posto_NON_si_dichiarano_puliti_senza_aver_guardato(self):
        """Il controllo [9] del banco faceva `os.listdir("/app/data")`: su una macchina
        senza Docker sollevava `FileNotFoundError`, la lista restava vuota e il verdetto
        usciva OK **senza aver guardato niente**. E' lo sbaglio S7 — premessa mancante non
        e' un verde — lo stesso che era gia' stato tolto alla catena di impronte in questo
        stesso file, e che li' era rimasto."""
        fuori = self._funzione_del_banco("db_fuori_posto")
        assente = os.path.join(tempfile.mkdtemp(prefix="assente_"), "non_esiste")
        self.assertIsNone(fuori(assente),
                          "una cartella che non esiste non e' «nessun database fuori "
                          "posto»: e' una misura che non si e' potuta fare")
        sporca = tempfile.mkdtemp(prefix="sporca_")
        with io.open(os.path.join(sporca, "intruso.db"), "w", encoding="utf-8") as f:
            f.write("x")
        self.assertEqual(fuori(sporca), ["intruso.db"],
                         "un database nato nel posto sbagliato deve VEDERSI: e' l'unica "
                         "cosa che questo controllo esiste per trovare")

    def test_UNO_STRUMENTO_DI_collaudi_NON_VEDE_I_MODULI_DELLA_RADICE_DA_SOLO(self):
        """⛔ IL FATTO CHE HA FATTO FALLIRE IL BANCO DENTRO LA BATTERIA, IL 2026-08-21.

        `python collaudi/giro_banco.py` mette in cammino la cartella dello SCRIPT
        (`collaudi/`), non la radice: al primo `from fase163_accettazioni import ...` muore con
        `ModuleNotFoundError`. Fuori dalla batteria non si vedeva, perche' a mano il banco si
        lancia su stdin (`python - < collaudi/giro_banco.py`, la forma di
        `collaudi/banco_prova.sh:151`) e li' il cammino parte dalla cartella corrente.
        💡 La lezione non e' sul banco: **e' che l'ambiente con cui lanci fa parte della
        misura** (D23). La batteria lo lanciava «come si lancia uno script» e otteneva un rosso
        che non parlava del prodotto.

        Qui si prova il FATTO, su un modulo qualunque della cartella, senza avviare niente:
        con la radice nel cammino l'import passa, senza no.
        """
        import subprocess
        radice = QUI
        codice = "import fase163_accettazioni"
        senza = subprocess.run([sys.executable, "-c", codice], cwd=os.path.join(radice, "collaudi"),
                               capture_output=True, text=True, timeout=60,
                               env=dict(os.environ, PYTHONPATH=""))
        self.assertIn(
            "ModuleNotFoundError", (senza.stderr or ""),
            "premessa cambiata: da dentro `collaudi/` i moduli della radice si importano gia'. "
            "Allora e' questa guardia a dover cambiare, non la batteria")
        con = subprocess.run([sys.executable, "-c", codice], cwd=os.path.join(radice, "collaudi"),
                             capture_output=True, text=True, timeout=60,
                             env=dict(os.environ, PYTHONPATH=radice))
        self.assertEqual(
            0, con.returncode,
            "con la radice in PYTHONPATH l'import DEVE passare, altrimenti la riparazione "
            "della batteria non serve a niente: %s" % (con.stderr or "")[-300:])

    def test_LA_BATTERIA_DA_AL_BANCO_LA_RADICE_NEL_CAMMINO(self):
        """La riparazione, dal lato di chi lancia: senza questo il banco muore prima di
        guardare un solo euro, e il rosso parla della cartella invece che dei soldi."""
        import ast
        with io.open(os.path.join(QUI, "collaudi", "batteria.py"), encoding="utf-8") as f:
            albero = ast.parse(f.read())
        trovata = False
        for nodo in ast.walk(albero):
            if not isinstance(nodo, ast.Call):
                continue
            testo = ast.dump(nodo)
            if "giro_banco.py" in testo:
                trovata = True
                self.assertIn(
                    "PYTHONPATH", testo,
                    "la batteria lancia il banco SENZA dargli la radice nel cammino: morira' "
                    "con ModuleNotFoundError prima di esaminare un solo euro (misurato il "
                    "2026-08-21, fase 8c fallita in 0 secondi)")
        self.assertTrue(trovata, "la batteria non lancia piu' il banco: la fase 8c e' sparita, "
                                 "e con lei l'unico collaudo in cui i soldi si muovono davvero")

    def test_IL_CONTO_DEGLI_STRUMENTI_QUADRA_E_OGNI_ESCLUSIONE_HA_IL_SUO_MOTIVO(self):
        """⛔ «HO LANCIATO LA BATTERIA» NON PUO' VOLER DIRE «HO GUARDATO TUTTO».

        Nasce il 2026-08-21 da un ordine del fondatore — *ogni lavoro deve passare da tutti
        questi test* — e da cio' che si e' trovato cercando (D10): `collaudi/batteria.py`, il
        comando che si chiama «batteria COMPLETA», **saltava proprio i collaudi sui soldi**.
        Ora `regole_avvio.py` stampa a ogni avvio quanti collaudi restano FUORI, e qui si
        pretendono le due cose che rendono quel numero degno di fiducia:
          1. il conto QUADRA (lanciati + fuori = collaudi): un totale che non torna e' un
             numero che ha gia' cominciato a mentire;
          2. ogni attrezzo escluso dal conto porta un MOTIVO scritto -- altrimenti si potrebbe
             far sparire un collaudo dai «fuori» semplicemente dichiarandolo «non un collaudo».
        """
        import importlib.util
        percorso = os.path.join(QUI, "collaudi", "regole_avvio.py")
        spec = importlib.util.spec_from_file_location("_regole_avvio_guardia", percorso)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)

        collaudi, lanciati, fuori = modulo.strumenti_e_batteria()
        self.assertEqual(
            len(collaudi), len(lanciati) + len(fuori),
            "il conto degli strumenti NON quadra: %d collaudi, %d lanciati, %d fuori. Un "
            "totale che non torna e' un numero che ha gia' cominciato a mentire (D22)"
            % (len(collaudi), len(lanciati), len(fuori)))
        self.assertTrue(collaudi, "nessun collaudo trovato: lo strumento non sta guardando "
                                  "la cartella giusta, e allora il suo numero non vale niente")

        for nome, motivo in modulo.NON_SONO_COLLAUDI.items():
            with self.subTest(escluso=nome):
                self.assertTrue(
                    motivo and motivo.strip(),
                    "l'attrezzo %r e' escluso dal conto dei collaudi SENZA un motivo scritto: "
                    "cosi' chiunque puo' far sparire un collaudo dai «fuori» dichiarandolo "
                    "«non un collaudo», ed e' proprio il buco che questo conto deve chiudere"
                    % nome)
                self.assertTrue(
                    os.path.exists(os.path.join(QUI, "collaudi", nome + ".py")),
                    "l'elenco delle esclusioni nomina %r, che non esiste piu' in collaudi/: "
                    "un'esclusione orfana e' un elenco rimasto indietro" % nome)

    def test_IL_BANCO_SI_PUO_PUNTARE_DOVE_IL_SERVER_STA_DAVVERO(self):
        """⛔ LA PORTA DEL BANCO ERA L'UNICA CABLATA, E UNA PORTA CABLATA HA GIA' MENTITO.

        `collaudi/giro_banco.py` aveva `BASE = "http://127.0.0.1:8080"` scritto dentro, mentre
        ogni altro strumento che parla col banco (`vicoli_ciechi.py`,
        `percorso_ospite_host.js`) legge `BASE_VISIVO`. Il danno di una porta che non si puo'
        spostare e' gia' nel catalogo degli sbagli, alla voce **S12**: un banco interrogato
        sulla porta sbagliata stampo' **21 rossi finti**, che per un istante sembravano un
        disastro.
        💡 E il motivo per cui si ripara adesso e' concreto: `collaudi/batteria.py` accende il
        suo server sulla **8099**, quindi finche' la porta resta incisa il banco non puo'
        entrare nella batteria — cioe' resta fuori dal comando che lancia «tutti i test».

        Si prova il FATTO, non la parola: si esegue l'assegnazione vera estratta dal file, con
        e senza la variabile, e si guarda cosa ne esce (regola ferrea 10, le due direzioni).
        """
        import ast
        with io.open(os.path.join(QUI, "collaudi", "giro_banco.py"),
                     encoding="utf-8") as f:
            sorgente = f.read()
        nodo = None
        for n in ast.parse(sorgente).body:
            if isinstance(n, ast.Assign) and any(
                    getattr(t, "id", "") == "BASE" for t in n.targets):
                nodo = n
        self.assertIsNotNone(nodo, "collaudi/giro_banco.py non assegna piu' BASE")

        def _valuta(ambiente):
            spazio = {"os": type("_", (), {"environ": ambiente})()}
            exec(compile(ast.Module(body=[nodo], type_ignores=[]),
                         "<giro_banco.BASE>", "exec"), spazio)
            return spazio["BASE"]

        self.assertEqual(
            "http://127.0.0.1:9911", _valuta({"BASE_VISIVO": "http://127.0.0.1:9911"}),
            "il banco NON guarda dove gli si dice: la porta e' incisa nel codice, e allora "
            "interrogherebbe una porta vuota stampando rossi che non esistono (sbaglio S12)")
        self.assertEqual(
            "http://127.0.0.1:8080", _valuta({}),
            "senza la variabile il banco deve comportarsi ESATTAMENTE come prima: il ripiego "
            "e' il valore storico, altrimenti questa riparazione romperebbe chi lo lancia a "
            "mano come ha sempre fatto")

    # ⛔ I ripieghi che DEVONO coincidere: sono strette di mano: un processo si autentica
    # all'altro, e se i due valori differiscono la porta si chiude in silenzio.
    STRETTA_DI_MANO = {
        "STRIPE_WEBHOOK_SECRET": "il banco FIRMA il webhook, il server ne VERIFICA la firma",
        "ADMIN_KEY": "il banco entra nel pannello che il server protegge",
        "BUNKER_PASSWORD": "il banco supera il secondo muro del server",
    }
    # ...e quelli che possono legittimamente differire, OGNUNO COL SUO MOTIVO SCRITTO.
    RIPIEGHI_DIVERSI_A_RAGIONE = {
        "STRIPE_SECRET_KEY": "il server accetta una chiave finta pur di accendersi (e' un "
                             "banco di prova); il banco ne vuole una VERA di prova, se no "
                             "misurerebbe se stesso invece del prodotto",
    }

    def _ripieghi_letti_dal_file(self, nome_file):
        """I valori di ripiego VERI, estratti dal sorgente: `os.environ.get(NOME, "VAL")`
        e `os.environ.setdefault(NOME, "VAL")`. Solo quelli con un valore scritto."""
        import re as _re
        with io.open(os.path.join(QUI, "collaudi", nome_file), encoding="utf-8") as f:
            testo = f.read()
        trovati = {}
        for nome, valore in _re.findall(
                r"\b_?os\.environ\.(?:get|setdefault)\(\s*[\"'](\w+)[\"']\s*,\s*[\"']([^\"']*)[\"']",
                testo):
            trovati.setdefault(nome, valore)
        return trovati

    def test_IL_BANCO_E_IL_SERVER_NON_POSSONO_AVERE_RIPIEGHI_DIVERSI(self):
        """⛔ 2026-08-21 — TREDICI PAGAMENTI ROSSI PER DUE VALORI PREDEFINITI DIVERSI.

        Misurato lanciando la batteria per intero: la fase 8c usciva `NON OK 13` e OGNI
        pagamento rispondeva `400`. **Non era il prodotto.** Il server verifica la firma del
        webhook col suo ripiego `whsec_v` (`avvia_server_visivo.py`), il banco la firmava col
        proprio, che era la **stringa vuota** (`giro_banco.py`): due processi, lo stesso
        segreto, due valori diversi -> `400 firma_non_valida` -> nessuna prenotazione paga ->
        undici controlli contabili senza piu' niente da leggere. Identico su `ADMIN_KEY` e
        `BUNKER_PASSWORD`. Allineandoli: `PASSI 34 · OK 34 · NON OK 0`.

        💡 E il danno vero non era il rosso: era che il rosso **accusava i soldi**. Un falso
        allarme e' un difetto quanto un allarme mancato (regola ferrea 10) -- e costava una
        giornata a cercare un guasto che non esiste.

        ⛔ Non si confronta una lista scritta a mano: si estraggono i ripieghi VERI dai due
        file, e ogni variabile che i due condividono deve stare in ESATTAMENTE una delle due
        categorie. Cosi' una variabile nuova non puo' entrare di nascosto: o e' una stretta
        di mano e i valori devono coincidere, o e' diversa a ragione e la ragione e' scritta.
        """
        banco = self._ripieghi_letti_dal_file("giro_banco.py")
        server = self._ripieghi_letti_dal_file("avvia_server_visivo.py")
        comuni = sorted(set(banco) & set(server))
        self.assertTrue(
            comuni,
            "nessuna variabile in comune fra banco e server: l'estrazione non ha trovato "
            "niente, quindi questa guardia non sta provando nulla (denominatore zero)")

        non_classificate = [n for n in comuni
                            if n not in self.STRETTA_DI_MANO
                            and n not in self.RIPIEGHI_DIVERSI_A_RAGIONE]
        self.assertEqual(
            [], non_classificate,
            "queste variabili le leggono TUTTI E DUE e nessuno ha detto se devono "
            "coincidere: %s. O e' una stretta di mano, o la differenza porta il suo motivo "
            "scritto -- altrimenti la prossima divergenza passa in silenzio come quella del "
            "2026-08-21" % non_classificate)

        divergenti = ["%s: il server ripiega su %r, il banco su %r (%s)"
                      % (n, server[n], banco[n], self.STRETTA_DI_MANO[n])
                      for n in comuni
                      if n in self.STRETTA_DI_MANO and server[n] != banco[n]]
        self.assertEqual(
            [], divergenti,
            "BANCO E SERVER NON SI RICONOSCONO, E IL BANCO ACCUSERA' I SOLDI:\n"
            + "\n".join(divergenti))

    def test_UNA_FIRMA_RIFIUTATA_NON_SI_CONTA_COME_UN_GUASTO_DEI_SOLDI(self):
        """⛔ TREDICI FALLIMENTI IDENTICI SONO **UN** PROBLEMA, NON TREDICI DIFETTI.

        Col segreto disallineato il banco stampava tredici volte `pagamento del giro N
        (atteso 200 / ottenuto 400)` e li contava come tredici rossi sui soldi. Ma
        `400 {"errore": "firma_non_valida"}` e' l'unica risposta che il webhook da' quando
        chi firma e chi verifica non concordano (`fase83_server._webhook_stripe`): non dice
        niente sul prodotto, dice che **il banco non lo sta misurando**.

        E' la stessa forma gia' usata per la chiave mancante: si DICHIARA il buco col motivo
        (`saltato`), non si da' un giudizio. Un giudizio senza premessa e' lo sbaglio S7.

        ⛔ Si prova la funzione VERA estratta dal file (il modulo non si puo' importare: e'
        uno script che al primo import parte e prenota davvero), nelle DUE direzioni, e si
        pretende che qualcuno la CHIAMI: una funzione giusta che non chiama nessuno e' la
        regola #23, COSTRUITO != COLLEGATO.
        """
        import ast
        with io.open(os.path.join(QUI, "collaudi", "giro_banco.py"), encoding="utf-8") as f:
            sorgente = f.read()
        nodo = None
        for n in ast.parse(sorgente).body:
            if isinstance(n, ast.FunctionDef) and n.name == "non_sto_misurando":
                nodo = n
        self.assertIsNotNone(
            nodo,
            "collaudi/giro_banco.py non ha una funzione `non_sto_misurando`: senza, un "
            "disallineamento di configurazione torna a presentarsi come tredici guasti dei "
            "soldi, ed e' il falso allarme che ha fatto perdere il giro del 2026-08-21")
        spazio = {}
        exec(compile(ast.Module(body=[nodo], type_ignores=[]), "<giro_banco>", "exec"), spazio)
        giudizio = spazio["non_sto_misurando"]

        self.assertTrue(
            giudizio(400, {"errore": "firma_non_valida"}),
            "la firma rifiutata NON viene riconosciuta: il banco continuerebbe a contarla "
            "come un guasto dei soldi")
        for stato, corpo, perche in (
                (400, {"errore": "prenotazione_inesistente"},
                 "un 400 per un ALTRO motivo e' un difetto vero e va contato"),
                (500, {"errore": "firma_non_valida"},
                 "un 500 e' il server che si rompe, non una configurazione disallineata"),
                (200, {}, "un pagamento riuscito non e' un buco"),
                (400, None, "un corpo illeggibile non autorizza a scusare il rosso")):
            with self.subTest(stato=stato, corpo=corpo):
                self.assertFalse(
                    giudizio(stato, corpo),
                    "%s: cosi' la scusa diventerebbe un tappeto sotto cui nascondere i "
                    "rossi veri" % perche)

        self.assertGreaterEqual(
            sorgente.count("non_sto_misurando("), 2,
            "la funzione esiste ma non la chiama nessuno: e' COSTRUITO != COLLEGATO "
            "(regola #23), e il banco continuerebbe ad accusare i soldi come prima")

    def test_LA_BATTERIA_DA_AL_SERVER_E_AL_BANCO_LA_STESSA_CARTELLA_DEI_DATI(self):
        """⛔ CINQUE CONTROLLI CONTABILI CHE NON GIRANO MAI, E NESSUNO SE NE ACCORGE.

        Misurato il 2026-08-21 con un giro vero: dentro `collaudi/batteria.py` il server si
        accende SENZA `BANCO_DATI`, quindi si sceglie da solo una cartella temporanea con un
        nome a caso -- e il banco, che e' un altro processo, non sa dove sia. Risultato:
        `somma degli incassi`, `tariffa tecnica su ogni incasso`, `ogni cancellazione lascia
        la sua riga di rimborso`, `catena di impronte del libro giornale` e `i soldi
        dell'host si FERMANO` escono **NON ESEGUITI** a ogni singola batteria.

        💡 Sono dichiarati, quindi non e' un verde falso -- ma sono **cinque controlli sui
        soldi che nessuno esegue mai**, e la dichiarazione scorre via in mezzo alle altre
        righe. `BANCO_DATI` esiste apposta perche' i due processi si scambino il nome della
        cartella: chi accende il server deve passarglielo, o quel meccanismo non serve a
        niente. Misurato: con la cartella condivisa i passi vanno da **29 a 34**.
        """
        import ast
        with io.open(os.path.join(QUI, "collaudi", "batteria.py"), encoding="utf-8") as f:
            sorgente = f.read()
        popen_server = []
        for nodo in ast.walk(ast.parse(sorgente)):
            if not isinstance(nodo, ast.Call):
                continue
            testo = ast.dump(nodo)
            if "avvia_server_visivo.py" in testo and "Popen" in ast.dump(nodo.func):
                popen_server.append(nodo)
        self.assertEqual(
            1, len(popen_server),
            "in collaudi/batteria.py non si trova (o si trova piu' di una volta) l'accensione "
            "di avvia_server_visivo.py: questa guardia non sa piu' cosa sta guardando")
        chiavi = [k.arg for k in popen_server[0].keywords]
        self.assertIn(
            "env", chiavi,
            "la batteria accende il server SENZA passargli un ambiente: allora il server si "
            "sceglie una cartella dati a caso e i controlli contabili del banco non la "
            "troveranno mai -- cinque prove sui soldi che non girano a ogni giro")
        self.assertIn(
            "BANCO_DATI", sorgente,
            "collaudi/batteria.py non nomina BANCO_DATI: e' la cartella che i due processi "
            "si scambiano, e senza quella il libro giornale resta illeggibile al banco")

    def _rete_dalla_batteria(self):
        """La funzione VERA estratta da `collaudi/batteria.py`, senza importare il modulo
        (importarlo lancerebbe la batteria intera)."""
        import ast
        with io.open(os.path.join(QUI, "collaudi", "batteria.py"), encoding="utf-8") as f:
            sorgente = f.read()
        nodo = None
        for n in ast.parse(sorgente).body:
            if isinstance(n, ast.FunctionDef) and n.name == "_rete_mutazione":
                nodo = n
        return sorgente, nodo

    def test_LA_BATTERIA_NON_PUO_LASCIARE_MUTANTI_DENTRO_LA_PRODUZIONE(self):
        """⛔ 2026-08-21 — LA BATTERIA SI E' SPARATA SUI PIEDI, E POI HA GIUDICATO IL FORO.

        La fase 3 (mutazione) ha un tetto di 900s. Quel giorno l'ha sforato ed e' stata
        **uccisa**: `subprocess.run` ammazza il processo, e il `finally` del Giudice non
        protegge da un processo ucciso. Sul disco e' rimasto, dentro il motore dei soldi:
            fase111_cancellazione.py:  rimborso = pagato     <- il 100% a chiunque, sempre
        Le **quindici fasi successive** hanno girato su quel codice: due sono uscite rosse e
        per un'ora sono sembrate difetti veri. E quel guasto e' rimasto li', dove chiunque
        poteva committarlo.

        💡 LA RETE C'ERA GIA', E AVEVA DUE STRATI: il Giudice ripristina **all'avvio
        successivo**, e `guardia_commit.py` **blocca il commit**. Mancava quello **di
        mezzo**: fra il colpo e il riavvio non rimette a posto nessuno, e tutto cio' che
        gira nel frattempo giudica codice rotto. Questa guardia pretende l'anello mancante.

        ⚠️ Non alza il tetto: un tetto che si alza per far smettere il rosso e' un allarme
        spento. Il tetto resta, e l'interruzione smette di fare danno.
        """
        sorgente, nodo = self._rete_dalla_batteria()
        self.assertIsNotNone(
            nodo,
            "collaudi/batteria.py non ha `_rete_mutazione`: se la mutazione viene uccisa, "
            "i mutanti restano dentro i file di produzione e le fasi dopo giudicano codice "
            "deliberatamente rotto")
        # ⛔ COSTRUITO != COLLEGATO (regola #23): deve chiamarla, e DOPO la mutazione.
        self.assertGreaterEqual(
            sorgente.count("_rete_mutazione("), 2,
            "la rete esiste ma non la chiama nessuno: e' esattamente il difetto #23")
        dopo_mutazione = sorgente.split("3. Mutazione")[-1]
        self.assertIn(
            "_rete_mutazione(", dopo_mutazione,
            "la rete viene chiamata PRIMA della fase di mutazione: li' non c'e' ancora "
            "niente da rimettere a posto, e dopo il colpo non interverrebbe nessuno")

    def test_LA_RETE_RIMETTE_A_POSTO_DAVVERO_E_TACE_A_MACCHINA_SANA(self):
        """Le DUE DIREZIONI (ferrea 10): col guasto dentro deve rimettere a posto e dirlo,
        a macchina sana deve tacere. Un allarme provato in un verso solo non e' provato."""
        import ast
        import shutil
        import tempfile
        _sorgente, nodo = self._rete_dalla_batteria()
        if nodo is None:
            self.fail("`_rete_mutazione` non esiste: niente da provare")
        import importlib
        import importlib.util          # perche' `importlib.util` sia un attributo raggiungibile
        spazio = {"os": os, "io": io, "importlib": importlib, "RADICE": QUI}
        exec(compile(ast.Module(body=[nodo], type_ignores=[]), "<batteria>", "exec"), spazio)
        rete = spazio["_rete_mutazione"]

        culla = tempfile.mkdtemp(prefix="prova_rete_")
        try:
            # un finto file di PRODUZIONE, sano, poi mutato a mano
            vittima = os.path.join(culla, "finto_fase_soldi.py")
            sano = "def rimborso(p, bps):\n    return p * bps // 10000\n"
            with io.open(vittima, "w", encoding="utf-8", newline="") as f:
                f.write(sano)
            with io.open(vittima, "w", encoding="utf-8", newline="") as f:
                f.write("def rimborso(p, bps):\n    return p\n")      # <- il mutante

            # il biglietto, nella forma vera: una cartella con quale.txt e originale.txt
            traccia = os.path.join(culla, "traccia")
            biglietto = os.path.join(traccia, "giro_prova")
            os.makedirs(biglietto)
            with io.open(os.path.join(biglietto, "quale.txt"), "w", encoding="utf-8") as f:
                f.write(vittima)
            with io.open(os.path.join(biglietto, "originale.txt"), "w",
                         encoding="utf-8", newline="") as f:
                f.write(sano)

            # ① col guasto dentro: deve gridare E rimettere a posto
            rimessi = rete(traccia)
            self.assertTrue(
                rimessi,
                "la rete non ha dichiarato NIENTE mentre un file era rimasto mutato: un "
                "ripristino silenzioso nasconde proprio il motivo per cui il giro e' morto")
            with io.open(vittima, encoding="utf-8", newline="") as f:
                self.assertEqual(
                    sano, f.read(),
                    "il file NON e' tornato quello di prima: la rete dichiara di aver "
                    "rimesso a posto senza averlo fatto, che e' peggio di non fare nulla")

            # ② a macchina sana: deve tacere, e non esplodere
            self.assertEqual(
                [], rete(os.path.join(culla, "traccia_che_non_esiste")),
                "la rete grida senza che ci sia niente da rimettere a posto: un falso "
                "allarme costa quanto un allarme mancato (ferrea 10)")
        finally:
            shutil.rmtree(culla, ignore_errors=True)

    def test_I_CONTI_NON_SI_DICHIARANO_QUADRATI_SU_UN_LIBRO_GIORNALE_VUOTO(self):
        """⛔ 2026-08-21 — LO STESSO S7 DEL CONTROLLO [9], TROVATO ANCHE NEL [8].

        Misurato con un giro vero del banco su dati puliti: il libro giornale ESISTEVA su
        disco ma aveva ZERO righe (senza chiave Stripe nessuna prenotazione paga), e quattro
        controlli contabili sono usciti **OK** senza aver esaminato una sola riga:
            OK  somma degli incassi = pagate x prezzo   (atteso 0 (0 x 1000) / ottenuto 0)
            OK  commissione + tariffa tecnica su ogni incasso
            OK  ogni host vede SOLO i propri soldi
            OK  ogni cancellazione pagata lascia la sua riga di rimborso nel giornale
        La guardia che c'era copriva il caso «il file non c'e'», non il caso «c'e' ed e'
        vuoto» — e sessanta righe piu' sotto, nello STESSO file, il controllo della catena
        di impronte il caso vuoto lo dichiarava gia': *«oppure e' vuoto: senza righe la
        catena non si verifica, quindi NON si misura»*. Due controlli vicini, due risposte
        diverse alla stessa domanda: e' la copia rimasta indietro, di nuovo.

        ⚠️ Portata dichiarata (D18 punto 3): in quel giro il VERDETTO complessivo non ha
        mentito (il banco e' uscito 1 per altri rossi). Il difetto e' che quei quattro OK
        sarebbero sopravvissuti a un giro senza rossi, dichiarando quadrati dei conti che
        nessuno aveva guardato.
        """
        perche = self._funzione_del_banco("_perche_i_conti_non_si_misurano")
        self.assertIsNotNone(
            perche(False, 0),
            "senza libro giornale i conti non si possono misurare, e il banco deve dirlo")
        self.assertIsNotNone(
            perche(True, 0),
            "IL CASO DEL 2026-08-21: il libro c'e' ma e' VUOTO, e il banco dichiara OK "
            "quattro controlli sui soldi senza aver letto una riga (sbaglio S7). Zero righe "
            "non e' «i conti tornano»: e' «non ho guardato»")
        # l'altra direzione (regola ferrea 10): con righe vere si DEVE misurare, o questa
        # guardia avrebbe solo spento quattro controlli invece di renderli onesti
        self.assertIsNone(
            perche(True, 13),
            "con un libro giornale pieno i conti si misurano eccome: se qui esce un motivo, "
            "i quattro controlli contabili non girerebbero MAI e il banco sarebbe cieco "
            "proprio dove serve")


class TestGliALLARMIDiCodeQLSICHIUDONOALLAFONTE(unittest.TestCase):
    """🔬 I 33 ALLARMI APERTI, CHIUSI DOVE NASCONO — e ognuno nella forma che si VEDE.

    Misurati dall'API il 2026-08-20 su `839b9b8`: **1 grave** (`py/insecure-protocol`) e 32
    medi, tutti in cinque punti soli. Questa classe non ripete l'analisi di CodeQL — non
    potrebbe — : mette in cassaforte **la forma della difesa**, cioe' la sola cosa che qui si
    puo' controllare senza aspettare la CI. E' la stessa lezione di
    `TestLaPuliziaDelRegistroDEVEESSEREVISIBILEACHIANALIZZA`: *una difesa ha due destinatari,
    il programma e chi sorveglia*.

    ⛔ COSA QUESTA CLASSE NON FA (D18 punto 3): **non dimostra che gli allarmi si chiudano.**
    Quello lo dice solo la tabella di `code-scanning/alerts` letta dall'API dopo che il
    codice e' su GitHub (regola ferrea 8). Qui si dimostra che la difesa **c'e' e ha la forma
    giusta**; che a CodeQL basti, lo dira' CodeQL.
    """

    def _albero(self, nome_file):
        import ast
        with io.open(os.path.join(QUI, nome_file), encoding="utf-8") as f:
            return ast.parse(f.read())

    def _funzioni_che_chiamano(self, albero, attributo):
        """Le funzioni che contengono una chiamata `qualcosa.<attributo>(...)`."""
        import ast
        trovate = []
        for n in ast.walk(albero):
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for c in ast.walk(n):
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) \
                        and c.func.attr == attributo:
                    trovate.append(n)
                    break
        return trovate

    def test_il_canale_nostr_DICHIARA_la_versione_minima_di_TLS(self):
        """⛔ `py/insecure-protocol`, GRAVE, aperto dal 2026-08-14 su
        `fase197_canale_nostr.py`. Il codice usa `ssl.create_default_context()`, che **e' gia'
        sicuro** (verifica il certificato e non parla TLS vecchio): l'allarme e' un falso
        positivo. Ma un falso allarme che non si spegne costa quanto un allarme mancato
        (regola ferrea 10), e la forma riconosciuta si aggiunge **accanto**, mai al posto: la
        versione minima si dichiara esplicitamente, e la difesa vera resta dov'era."""
        import ast
        albero = self._albero("fase197_canale_nostr.py")
        funzioni = self._funzioni_che_chiamano(albero, "wrap_socket")
        self.assertTrue(funzioni, "nessun `wrap_socket` in fase197_canale_nostr.py: o il "
                                  "canale non parla piu' TLS, o questa guardia cerca male")
        for f in funzioni:
            dichiarata = False
            for n in ast.walk(f):
                if isinstance(n, ast.Attribute) and n.attr == "minimum_version":
                    dichiarata = True
            self.assertTrue(dichiarata,
                            "`%s` avvolge il socket in TLS senza dichiarare "
                            "`minimum_version`: e' sicuro e CodeQL non puo' vederlo" % f.name)

    def test_il_tipo_di_contenuto_non_puo_portare_un_a_capo_nelle_intestazioni(self):
        """⛔ `py/http-response-splitting` ×2 in `fase83_server.py`: il `Content-Type` esce da
        `mimetypes.guess_type()` su un percorso che arriva dall'utente. In pratica quella
        funzione restituisce un tipo da tabella e un a-capo non ci puo' entrare — ma
        l'analizzatore vede solo il percorso non fidato che finisce in un'intestazione, e ha
        ragione a non fidarsi di un ragionamento che non puo' verificare."""
        import ast
        albero = self._albero("fase83_server.py")
        funzioni = self._funzioni_che_chiamano(albero, "guess_type")
        self.assertTrue(funzioni, "nessun `guess_type` in fase83_server.py")
        for f in funzioni:
            pulito = False
            for n in ast.walk(f):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                        and n.func.attr == "replace" and n.args \
                        and isinstance(n.args[0], ast.Constant) \
                        and n.args[0].value in ("\n", "\r\n", "\r"):
                    pulito = True
            self.assertTrue(pulito,
                            "`%s` mette in un'intestazione un tipo ricavato da un percorso "
                            "non fidato senza togliere gli a-capo nella forma che CodeQL "
                            "riconosce (`.replace(\"\\n\", ...)`)" % f.name)

    def test_il_dettaglio_dell_errore_NON_torna_a_chi_ha_sbagliato_la_richiesta(self):
        """⛔ `py/stack-trace-exposure` in `fase36_booking_api.py`: la risposta 400 conteneva
        `str(e)`, cioe' il testo dell'eccezione. Non e' pignoleria: quel testo racconta a chi
        prova a forzare la porta **come e' fatto dentro**, ed e' il primo passo di chi cerca
        un varco. Il dettaglio si registra nel log del server, dove serve a noi."""
        import ast
        albero = self._albero("fase36_booking_api.py")
        for n in ast.walk(albero):
            if not (isinstance(n, ast.Call) and getattr(n.func, "id", "") == "jsonify"):
                continue
            for dentro in ast.walk(n):
                if isinstance(dentro, ast.Call) and getattr(dentro.func, "id", "") == "str" \
                        and dentro.args and getattr(dentro.args[0], "id", "") == "e":
                    self.fail("una risposta di `fase36_booking_api.py` rimanda al chiamante "
                              "il testo dell'eccezione (`str(e)`): il dettaglio va nel log, "
                              "non nella risposta")

    # ⛔ QUI C'ERA UNA GUARDIA SULLO STILE, ED E' STATA TOLTA PERCHE' GUARDAVA LA COSA
    # SBAGLIATA. Pretendeva che nessun intervallo di `_EMOJI` superasse i 256 caratteri, per
    # far tacere `py/overly-large-range`. Misurato il 2026-08-20 sul commit vero: spezzare
    # l'intervallo in undici blocchi ha portato quella regola **da 1 allarme a 10** — CodeQL
    # li conta uno per uno. Il conto degli allarmi non e' il punteggio da inseguire, ma dieci
    # righe di rumore su una regola di leggibilita' sporcano la lista dove un giorno dovra'
    # spiccare una cosa vera. Al suo posto c'e' la guardia qui sotto, che pretende la cosa che
    # conta davvero e che nessuno stava controllando: **quali caratteri vengono filtrati**.

    def test_il_filtro_delle_emoji_copre_ESATTAMENTE_gli_stessi_caratteri(self):
        """L'insieme filtrato da `_EMOJI`, misurato attraversando TUTTO lo spazio Unicode e
        confrontato con quello dichiarato carattere per carattere. Non e' una guardia sullo
        stile: se qualcuno riscrive quella classe — per far tacere un analizzatore, per
        leggibilita', per sbaglio — e cambia anche un solo carattere, qui diventa rossa.

        ⛔ I confini NON sono ricopiati dal sorgente: sono i code point misurati sul file
        originale il 2026-08-20, prima di toccarlo. Ricopiarli dal codice attuale farebbe una
        guardia che approva se stessa (baseline compiacente, sbaglio F5)."""
        import fase200_campagna_persuasiva as C
        atteso = set()
        for a, b in ((0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x1F1E6, 0x1F1FF),
                     (0x2B00, 0x2BFF), (0xFE00, 0xFE0F), (0x24C2, 0x24C2), (0x20E3, 0x20E3)):
            atteso.update(range(a, b + 1))
        trovato = set()
        for cp in range(0x0, 0x110000):
            if 0xD800 <= cp <= 0xDFFF:        # i surrogati non sono caratteri
                continue
            if C._EMOJI.match(chr(cp)):
                trovato.add(cp)
        persi = sorted(atteso - trovato)
        nuovi = sorted(trovato - atteso)
        self.assertEqual(
            (len(persi), len(nuovi)), (0, 0),
            "il filtro delle emoji non copre piu' lo stesso insieme: %d spariti (%s...) e "
            "%d aggiunti (%s...). Erano %d caratteri."
            % (len(persi), ", ".join("U+%04X" % c for c in persi[:5]),
               len(nuovi), ", ".join("U+%04X" % c for c in nuovi[:5]), len(atteso)))

    def test_DOVE_SONO_I_DATI_si_risponde_in_UN_POSTO_SOLO(self):
        """⛔ IL DIFETTO ERA GIA' STATO TROVATO E RIPARATO IN UN PUNTO, E UN ALTRO E' RIMASTO
        INDIETRO. In `fase83_server.py` la cartella dei dati si ricava in due modi diversi:
        `_data_dir()` (che parte da `DB_FINANZA` quando `DATA_DIR` manca o e' vuota) e, dentro
        `_bunker_stato`, un `os.environ.get("DATA_DIR", "data")` scritto a mano. Nel
        contenitore la cartella corrente e' `/app`, `data` non esiste, e la sala di controllo
        del bunker rispondeva **due allarmi CRITICI falsi**: «NESSUN backup trovato» e «il
        Guardiano dei soldi non batte piu'» — su una macchina con 25 database, backup di
        mezz'ora prima e battito regolare. Misurato dentro il contenitore di produzione il
        2026-08-20: `stato` vedeva **0** database, `integrita` ne vedeva **25**.

        💡 E la parte che fa male: accanto all'altro punto, riparato prima, c'era gia' scritto
        il perche' (*«nel container DATA_DIR esiste ma e' VUOTA... Fix: stesso fallback
        robusto di _data_dir()»*). La riparazione c'era, la copia no. Questa guardia pretende
        che quel fatto abbia **un padrone solo**.

        ⚠️ Un falso allarme sui soldi non e' meno grave di un allarme mancato: e' il modo in
        cui si insegna a ignorare i rossi (regola ferrea 10)."""
        import ast
        albero = self._albero("fase83_server.py")
        fuori = []
        for f in ast.walk(albero):
            if not isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if f.name == "_data_dir":
                continue
            for n in ast.walk(f):
                if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
                    continue
                if n.func.attr != "get" or not n.args:
                    continue
                primo = n.args[0]
                if isinstance(primo, ast.Constant) and primo.value == "DATA_DIR":
                    fuori.append("%s (riga %d)" % (f.name, n.lineno))
        self.assertEqual(fuori, [],
                         "questi punti chiedono `DATA_DIR` per conto loro invece di passare "
                         "da `_data_dir()`: %s. Due modi di rispondere alla stessa domanda "
                         "sono due risposte che prima o poi divergono, ed e' gia' successo"
                         % fuori)

    def test_ogni_valore_non_fidato_nei_log_di_app_passa_dal_ripulitore(self):
        """⛔ `py/log-injection` ×28, **tutti in `app.py`**: il percorso della richiesta, il
        metodo e l'indirizzo di chi chiama finiscono nel registro senza passare da
        `_sanitize_log`, che in quel file c'e' gia' ed e' scritto **nella forma riconosciuta**
        (`.replace("\\r", ...).replace("\\n", ...)`). Non mancava il rimedio: mancava usarlo.

        ⛔ E `app.py` NON si esclude dall'analisi, anche se il `Dockerfile` non lo spedisce:
        `TestLaListaDeiFileESCLUSIDaCodeQL` lo dichiara punto d'ingresso e pretende che resti
        dentro. Un'esclusione qui sarebbe l'interruttore per spegnere gli allarmi scomodi."""
        import ast
        albero = self._albero("app.py")
        sporchi = {"path", "method", "full_path", "query_string"}
        colpevoli = []
        for n in ast.walk(albero):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
                continue
            if getattr(n.func.value, "id", "") != "logger":
                continue
            for arg in n.args:
                if isinstance(arg, ast.Attribute) and arg.attr in sporchi \
                        and getattr(arg.value, "id", "") == "request":
                    colpevoli.append((n.lineno, "request." + arg.attr))
                if isinstance(arg, ast.Call) and getattr(arg.func, "id", "") == "_client_ip":
                    colpevoli.append((n.lineno, "_client_ip()"))
        self.assertEqual(colpevoli, [],
                         "in app.py questi valori non fidati entrano nel registro senza "
                         "`_sanitize_log(...)`: %s" % colpevoli)


class TestUnaSolaListaDiCoseDaFare(unittest.TestCase):
    """⛔ REGOLA ZERO 3, riscritta dal fondatore il 2026-08-22: le cose da fare stanno in UN
    SOLO posto, `RIPRENDI_QUI.md`. Nessun altro file puo' aprire un elenco di lavori.

    ⛔ PERCHE' ESISTE, e non e' un'opinione. Quel giorno abbiamo misurato:
        - DUE liste chiamate «Blocco 1»: una con 4 fasi dichiarata CHIUSA il 13 agosto,
          una con 24 moduli e 6 caselle a `0 su 6`. Il fondatore ricordava «5 fasi, era
          finito», lo strumento rispondeva «0 su 6»: nessuno dei due sbagliava, contavano
          COSE DIVERSE, e nessuno poteva accorgersene leggendo.
        - 111 righe «APERTO», in gran parte gia' chiuse.
        - 4 lavori «da fare» finiti da settimane.
    Il vecchio divieto («non creare nuovi .md») non impediva niente di tutto questo: il
    danno era DENTRO i file che c'erano gia'.

    ⛔ E LA DIRETTIVA FINALE 4 ERA L'UNICA SENZA UN «si verifica cosi'» -- ed e' esattamente
    quella che si e' rotta, pretendendo una seconda lista dentro il registro. Questa guardia
    e' la macchina che le mancava: un obbligo affidato alla buona volonta' si rompe di nuovo.

    ⚠️ COSA QUESTA GUARDIA NON FA (D18 punto 3):
      - non sa se una lista dice il VERO: sa che ne esiste una dove non dovrebbe stare;
      - guarda solo le APERTURE (titoli di sezione e commenti `# TODO:`), non le frasi che
        NOMINANO quelle parole -- se no il testo della regola stessa la farebbe fallire, e
        una guardia che punisce chi la descrive verrebbe spenta il giorno dopo (ferrea 10);
      - non entra in `_archivio/` (dichiarato storico dalla REGOLA ZERO 2).
    """

    #  I due posti dove una lista di lavori PUO' stare. `piano.py` e' l'eccezione dichiarata
    #  in REGOLA ZERO 3: quella lista la PRODUCE una macchina misurando il codice, e se le
    #  due si contraddicono vince lei.
    ESENTI = ("RIPRENDI_QUI.md", os.path.join("collaudi", "piano.py"))

    #  ⛔ Costruite per pezzi, di proposito: scritte per esteso, questo file conterrebbe le
    #     aperture che vieta e si accuserebbe da solo al primo giro.
    APERTURE = ("DA " + "FARE", "PROSSIMI " + "PASSI", "RIPARTI " + "DA QUI",
                "COSA " + "MANCA", "TO" + "DO", "FIX" + "ME")

    def _file_del_progetto(self):
        radice = QUI
        for cartella, sotto, nomi in os.walk(radice):
            sotto[:] = [s for s in sotto
                        if s not in (".git", "__pycache__", "_archivio", "node_modules",
                                     ".hypothesis", "data", "deploy_backup")]
            for n in nomi:
                if n.endswith(".md") or n.endswith(".py"):
                    yield os.path.join(cartella, n)

    def _apre_un_elenco(self, riga, e_python):
        """Vero solo se la riga APRE un elenco di lavori, non se lo nomina."""
        secca = riga.strip()
        su = secca.upper()
        #  B20 (2026-08-25): le aperture si cercano come PAROLE INTERE, non come
        #  sottostringhe. Cercando `TO`+`DO` dentro qualunque testo, la parola italiana
        #  «METODO» lo contiene: un titolo che parla di metodo veniva letto come
        #  l'apertura di un elenco di lavori, e ha mandato rossa la CI della richiesta
        #  106 su tre job. `\b` e' piu' STRETTO della sottostringa: puo' solo togliere
        #  accuse, mai aggiungerne -- nessun file prima pulito diventa colpevole.
        contiene = any(re.search(r"\b" + re.escape(a) + r"\b", su)
                       for a in self.APERTURE)
        if not contiene:
            return False
        if e_python:
            #  Solo i commenti-segnaposto veri: `# TODO: ...` / `# FIXME: ...`
            return bool(re.match(r"^#\s*(TO" + r"DO|FIX" + r"ME)\b", secca))
        #  Nei documenti: solo i TITOLI di sezione (righe che cominciano con #).
        return bool(re.match(r"^#{1,6}\s", secca))

    def test_UNA_SOLA_LISTA_DI_COSE_DA_FARE(self):
        colpevoli = []
        for percorso in self._file_del_progetto():
            rel = os.path.relpath(percorso, QUI)
            if any(rel.replace("/", os.sep).endswith(e) for e in self.ESENTI):
                continue
            e_python = rel.endswith(".py")
            try:
                with io.open(percorso, encoding="utf-8", errors="replace") as f:
                    for n, riga in enumerate(f, 1):
                        if self._apre_un_elenco(riga, e_python):
                            colpevoli.append("%s:%d  %s"
                                             % (rel, n, " ".join(riga.split())[:90]))
            except OSError:
                continue
        self.assertEqual(
            colpevoli, [],
            "TROVATE %d APERTURE DI ELENCHI DI LAVORI FUORI DAI DUE POSTI AMMESSI.\n"
            "  Ammessi: %s\n"
            "  Le cose da fare stanno in UN SOLO posto (REGOLA ZERO 3). Ogni riga qui sotto\n"
            "  e' una lista che vive per conto suo e che un giorno dira' il falso senza che\n"
            "  nessuno se ne accorga:\n    %s"
            % (len(colpevoli), " e ".join(self.ESENTI), "\n    ".join(colpevoli)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
