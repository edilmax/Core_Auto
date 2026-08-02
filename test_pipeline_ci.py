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


def stati_catturati(espressione):
    corpo = espressione.strip()
    if corpo.startswith("${{") and corpo.endswith("}}"):
        corpo = corpo[3:-2].strip()
    if "&&" in corpo:
        raise ValueError("la condizione del verdetto contiene un AND: con `&&` "
                         "servirebbero PIU' job rossi insieme per far scattare il "
                         "rosso, e un job rosso da solo passerebbe. Va in OR.")
    stati = []
    for parte in corpo.split("||"):
        trovato = _TERMINE.match(parte.strip())
        if trovato is None:
            raise ValueError("termine non riconosciuto nella condizione del verdetto: "
                             "%r (atteso: contains(needs.*.result, '<esito>'))"
                             % parte.strip())
        stati.append(trovato.group(1))
    return stati


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
        attese = set("D%d" % i for i in range(1, 20))
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
                 "il metodo chirurgico annulla le campagne autonome")):
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
            "## LE 19 DIRETTIVE DEL FONDATORE\n"
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
        atteso = (n["appendice"] + n["regola_zero"] + n["direttive"]
                  + n["modi"] + n["collaudi"] + n["finale"])
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
        self.assertGreaterEqual(n["direttive"], 19,
                                "il numero delle direttive del fondatore e' SCESO: una "
                                "direttiva non si toglie senza che qualcuno lo decida")

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
        m._chiudi_traccia()
        self.assertIsNone(m.recupera_da_interruzione())

    def test_le_RINUNCE_sono_contate_e_dichiarate(self):
        """Un generatore che tace sulle proprie rinunce mente sulla copertura. I confronti
        a catena si saltano di proposito: devono comparire nel conto."""
        m = self._motore()
        _mut, saltati = m.genera_mutanti("def f(a, b, c):\n    return a < b < c\n")
        self.assertEqual(1, saltati["catena"],
                         "un confronto a catena non e' stato contato fra le rinunce: %r"
                         % (saltati,))


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
        import subprocess
        import sys
        radice = os.path.dirname(os.path.abspath(__file__))
        r = subprocess.run([sys.executable, os.path.join(radice, "collaudi",
                                                         "mutazione_prodotto.py"),
                            "--prova-avvio"],
                           cwd=radice, capture_output=True, text=True,
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
