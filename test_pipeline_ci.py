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

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
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
        self.assertEqual(sorted(self.non_bloccanti), ["lint-severo", "zap"],
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


def consegne_troppo_indietro(quanti_commit):
    """Il giudizio, isolato dal resto perche' si possa provare da solo.

    UNO e' il commit che porta le consegne stesse: quello e' sano. DUE vuol dire
    che dopo aver scritto le consegne si e' committato altro lavoro senza
    toccarle. `None` = non misurabile qui (vedi la dichiarazione qui sopra).
    """
    return quanti_commit is not None and quanti_commit > 1


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
        self.assertEqual(3, len(mutazioni),
                         "denominatore cambiato: %d punti che introducono un mutante invece "
                         "di 3. Se il motore e' cambiato di proposito questo numero si "
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
            self.assertEqual((False, ""), m.mutazione_in_corso(vuota),
                             "dice che un giro e' aperto quando non c'e' niente: bloccherebbe "
                             "sempre, e un blocco sempre acceso viene tolto")
            traccia = os.path.join(d, "aperta")
            os.makedirs(traccia)
            with open(os.path.join(traccia, "quale.txt"), "w", encoding="utf-8") as f:
                f.write("fase177_financial_controller.py")
            aperta, quale = m.mutazione_in_corso(traccia)
            self.assertTrue(aperta, "un giro interrotto non viene visto")
            self.assertIn("fase177", quale, "non dice QUALE file potrebbe essere rotto")
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

    CAMPI = ("metodo", "dominio", "data", "prova")
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
        vuoti = [c for c in cls.CAMPI if not isinstance(voce[c], str) or not voce[c].strip()]
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
    TRACCE_SU_FIRMA_LARGA = 5

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
        for frase in self.VIETATI:
            voce = {"metodo": frase, "dominio": "tutto", "data": "2026-08-05",
                    "prova": "sembra una spiegazione e non e' una dimostrazione"}
            motivo = regola(voce)
            self.assertIsNotNone(motivo,
                                 "%r passa come metodo di dimostrazione: e' esattamente cio' "
                                 "che il divieto B6 vieta" % frase)
            self.assertIn("B6", motivo)
        buona = {"metodo": "traccia", "dominio": "il caso `x == 0`", "data": "2026-08-05",
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
