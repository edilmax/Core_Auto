# -*- coding: utf-8 -*-
"""
PARITA' DI AMBIENTE — cio' che la CI giudica deve essere cio' che va in produzione.

CONTRATTO (in sei righe). L'artefatto di produzione e' UNO: l'immagine costruita da
`Dockerfile.casavip` (base python:3.11-slim, ZERO pacchetti installati, avvio
`main_casavip.py`). Allora la CI deve: (1) COSTRUIRE e AVVIARE davvero quell'immagine e
interrogarne la sonda di salute; (2) far girare la suite anche sul Python di quella
immagine; (3) non permettere che il prodotto dipenda da pacchetti che soltanto la CI
installa. Qui `Dockerfile.casavip` e `.github/workflows/ci.yml` sono trattati come DATI
e i tre punti vengono asseriti campo per campo, con valori esatti.

PERCHE' ESISTE (due buchi veri, trovati il 2026-07-29 e chiusi da questo file).

  BUCO 1 - NESSUN JOB COSTRUIVA L'IMMAGINE. Undici job giudicavano i sorgenti sparsi
  sul runner, con i pacchetti di test installati attorno. L'immagine Docker - l'unica
  cosa che gira davvero sul VPS - non veniva mai assemblata ne' avviata. Un commit che
  rompeva il Dockerfile (una `COPY` che non prende piu' i moduli, una `ENV` persa, il
  modulo d'avvio rinominato) passava il gate VERDE e si scopriva soltanto in
  produzione, a deploy fatto, col sito giu'. Il gate diceva "va tutto bene" su una cosa
  che non aveva mai visto.

  BUCO 2 - AMBIENTE DIVERSO (il modo di rompersi n. 8 di CLAUDE.md). La produzione gira
  su python:3.11-slim, la CI girava tutta su 3.9. Verde in CI non voleva dire verde in
  produzione: un cambio di stdlib, una deprecazione avrebbero fatto rosso soltanto sul
  server. Nessun test poteva accorgersene, perche' il difetto stava NELL'AMBIENTE, non
  nel codice. E non era teoria: appena la suite e' stata eseguita per la prima volta su
  3.11 (4582 test) sono usciti **22 rossi** che su 3.9 erano verdi. Il piu' istruttivo:
  in 3.11 `datetime.fromisoformat` accetta le forme ISO "di base" che 3.9 rifiutava
  ('20260905', '2026-W36-6'), quindi IN PRODUZIONE certe date malformate entrano, e i
  test che le credono rifiutate cadono. Per questo la parita' non e' una matrice
  (renderebbe il gate rosso per un debito noto, che insegna a ignorare il rosso) ma un
  job dedicato `full-suite-311` che BLOCCA su tutto cio' che su 3.11 e' gia' verde e
  tiene il debito in un elenco dichiarato, a cricchetto: da li' si possono solo
  togliere moduli.

  TERZO CONTROLLO (dipendenze) - la CI installa `-r requirements.txt hypothesis pyyaml
  coverage`; l'immagine non installa NIENTE (produzione stdlib-pura). E' una divergenza
  voluta, ma pericolosa: un `import stripe` a livello di modulo funzionerebbe in CI e
  ucciderebbe il container all'avvio. Qui si DIMOSTRA leggendo il Dockerfile che
  l'immagine non installa nulla, e si dimostra sul codice che nessun modulo della
  chiusura di produzione importa un pacchetto di terze parti a livello di modulo.

CONFINI (cosa questo file NON fa, dichiarato per non spacciare copertura che non c'e'):
  · non lancia Docker (il computer dello sviluppatore non ce l'ha, e la suite deve
    girare anche li'): il job `immagine` viene verificato come DATO, cioe' si prova che
    esiste, che costruisce e avvia PROPRIO l'artefatto di produzione, che aspetta la
    sonda, che la interroga pretendendo 200, e che il gate lo aspetta. Che il container
    parta davvero lo prova la CI eseguendolo;
  · non esegue la suite su 3.11 (lo fa il job full-suite-311): qui si prova che quel
    job esiste, gira sul Python giusto, blocca, e che il suo elenco di debito e' fatto
    di moduli veri e non puo' allargarsi;
  · non giudica la qualita' del Dockerfile (lo fa test_deploy_config.py) ne' quali
    moduli l'immagine copia (lo fa test_copertura_onesta.py).

MODALITA' DI ERRORE sorvegliate: job immagine cancellato o tolto dal gate · immagine
costruita con un tag e avviata con un altro · sonda interrogata senza pretendere il
200 · container mai spento · avvio senza le variabili che main_casavip pretende (senza
HOST_KEY/ADMIN_KEY rifiuta di partire) · base del Dockerfile cambiata senza aggiornare
la CI · versione di Python usata da un job e non dichiarata · versione dichiarata e non
piu' usata da nessuno · la suite intera che non gira piu' sul Python di produzione ·
versioni scritte come numeri YAML ('3.10' senza apici diventa 3.1) · un pacchetto di
terze parti importato a livello di modulo dal prodotto · il Dockerfile che comincia a
installare pacchetti senza che nessuno lo dichiari.

VISTO ROSSO (2026-07-29). Ogni estrattore e' una funzione PURA provata anche su dati
finti guasti, ma il verde vero e' stato guadagnato guastando i file VERI: 30 guasti
diversi su `ci.yml` e su `Dockerfile.casavip`, uno per volta, ognuno seguito dal
ripristino BYTE-IDENTICO verificato con sha256. Tutti e 30 hanno prodotto il rosso del
test che li sorveglia:
    job immagine         - cancellato · tolto dai needs del gate · costruisce
                           un'immagine e ne avvia un'altra · costruisce il Dockerfile
                           sbagliato · sonda annullata da `|| true` · corpo della
                           risposta non piu' guardato · avvio senza HOST_KEY · marca
                           temporale riaccesa · container non piu' spento · porta
                           pubblicata diversa da EXPOSE · attesa senza limite ·
                           frontend non piu' verificato · setup-python infilato dentro
    versioni             - PRODUZIONE dichiarata 3.12 · versione dichiarata e non piu'
                           usata da nessuno · job su versione non dichiarata · 3.11
                           tolta da tutti i job · versione senza apici (YAML la
                           trasforma in un numero)
    job full-suite-311   - cancellato · fuori dai needs del gate · portato su 3.9 ·
                           debito allargato di un modulo (cricchetto) · debito con un
                           nome fantasma · report-only che non ricopre il debito ·
                           guardia sul numero di moduli tolta · comando bloccante
                           annullato da `|| true`
    Dockerfile.casavip   - `RUN pip install requests` · `COPY requirements.txt` · base
                           portata a 3.12 (due test diversi) · EXPOSE su un'altra porta
E oltre ai guasti: il codice shell del passo che interroga la sonda e' stato ESEGUITO
in bash su 9 risposte diverse (200 col corpo giusto, con le chiavi invertite, senza
spazi -> verde; 500, 404, pagina di nginx, stato degradato, money_unit in euro, corpo
dimezzato -> rosso). E l'ambiente del `docker run` e' stato ricostruito variabile per
variabile (ENV del Dockerfile + le -e del job) ed eseguito davvero attraverso
`main_casavip.main()` con `servi()` intercettato: arriva ad accendere il sistema
(attivo=True, 0.0.0.0:8080), quindi il container del job non e' un rosso fisso.
"""

import ast
import io
import os
import re
import unittest

import yaml

RADICE = os.path.dirname(os.path.abspath(__file__))
CI_YML = os.path.join(RADICE, ".github", "workflows", "ci.yml")
DOCKERFILE = os.path.join(RADICE, "Dockerfile.casavip")
DOCKERFILE_GEMELLO = os.path.join(RADICE, "Dockerfile")
REQUIREMENTS = os.path.join(RADICE, "requirements.txt")
AVVIO = "main_casavip"

JOB_IMMAGINE = "immagine"
GATE = "gate"

# Il nome del pacchetto su PyPI non e' sempre il nome con cui lo si importa.
NOME_IMPORT = {
    "python-dotenv": "dotenv",
    "psycopg2-binary": "psycopg2",
    "pyyaml": "yaml",
    "opencv-python": "cv2",
    "beautifulsoup4": "bs4",
}

# Import di terze parti ANNIDATI (dentro una funzione) che oggi esistono nella chiusura
# di produzione, con il motivo per cui non sono un guasto. Sono adattatori per il
# vecchio stack Flask: `main_casavip.py` non chiama mai queste due funzioni, quindi in
# produzione quel `from flask import ...` non viene mai eseguito. L'elenco e' ESATTO:
# se ne compare un terzo, questo file lo denuncia e qualcuno deve decidere di proposito
# se e' un adattatore morto o una dipendenza vera che l'immagine NON ha.
LAZY_AMMESSI = {
    ("fase57_vetrina", "flask"),      # registra_vetrina(): rotte Flask legacy
    ("fase59_concierge", "flask"),    # registra_concierge(): rotte Flask legacy
}

# Opzioni di `docker run` che si portano dietro un valore: servono a capire dove
# finiscono le opzioni e comincia il NOME DELL'IMMAGINE.
OPZIONI_CON_VALORE = ("-e", "-p", "-v", "-w", "-u", "--name", "--network", "--env",
                      "--volume", "--publish", "--user", "--workdir")


# ---------------------------------------------------------------------------
#  Lettura dei file (nessuna importazione, nessuna esecuzione)
# ---------------------------------------------------------------------------
def _leggi(percorso):
    with io.open(percorso, encoding="utf-8") as f:
        return f.read()


def _doc_ci():
    return yaml.safe_load(_leggi(CI_YML))


def _passi(job):
    return job.get("steps", []) or []


def comandi(job):
    """I comandi shell del job, con le continuazioni di riga ricucite."""
    fuori = []
    for passo in _passi(job):
        run = passo.get("run")
        if isinstance(run, str):
            fuori.append(run.replace("\\\n", " "))
    return fuori


def comando_del_passo(job, frammento):
    """Il comando dell'UNICO passo che contiene il frammento (o AssertionError)."""
    trovati = [c for c in comandi(job) if frammento in c]
    if len(trovati) != 1:
        raise AssertionError(
            "nel job cercavo un solo passo che contenesse %r: trovati %d"
            % (frammento, len(trovati)))
    return trovati[0]


# ---------------------------------------------------------------------------
#  Estrattori PURI (si possono avvelenare con dati finti: e' li' che si vedono rossi)
# ---------------------------------------------------------------------------
def immagini_costruite(elenco_comandi):
    """I tag prodotti dai `docker build -t <tag>`."""
    tag = []
    for c in elenco_comandi:
        if "docker build" not in c:
            continue
        pezzi = c.split()
        for i, p in enumerate(pezzi):
            if p in ("-t", "--tag") and i + 1 < len(pezzi):
                tag.append(pezzi[i + 1])
    return tag


def dockerfile_costruiti(elenco_comandi):
    """I Dockerfile passati a `docker build -f <file>`."""
    file = []
    for c in elenco_comandi:
        if "docker build" not in c:
            continue
        pezzi = c.split()
        for i, p in enumerate(pezzi):
            if p in ("-f", "--file") and i + 1 < len(pezzi):
                file.append(pezzi[i + 1])
    return file


def immagini_avviate(elenco_comandi):
    """Le immagini davvero AVVIATE da `docker run`: si saltano opzioni e valori."""
    avviate = []
    for c in elenco_comandi:
        pezzi = c.split()
        if "docker" not in pezzi:
            continue
        i = pezzi.index("docker")
        if i + 1 >= len(pezzi) or pezzi[i + 1] != "run":
            continue
        i += 2
        while i < len(pezzi) and pezzi[i].startswith("-"):
            i += 2 if pezzi[i] in OPZIONI_CON_VALORE else 1
        if i < len(pezzi):
            avviate.append(pezzi[i])
    return avviate


def variabili_passate_al_run(elenco_comandi):
    """I nomi delle variabili d'ambiente passate con `-e NOME=valore`."""
    nomi = set()
    for c in elenco_comandi:
        if "docker run" not in c:
            continue
        for trovato in re.finditer(r"(?:^|\s)(?:-e|--env)\s+([A-Za-z_][A-Za-z0-9_]*)=",
                                   c):
            nomi.add(trovato.group(1))
    return nomi


def porte_pubblicate(elenco_comandi):
    """Le coppie (porta sull'host, porta nel container) di `docker run -p H:C`."""
    coppie = []
    for c in elenco_comandi:
        if "docker run" not in c:
            continue
        for trovato in re.finditer(r"(?:-p|--publish)\s+(\d+):(\d+)", c):
            coppie.append((int(trovato.group(1)), int(trovato.group(2))))
    return coppie


def porte_interrogate(elenco_comandi):
    """Le porte a cui i comandi del job vanno davvero a bussare."""
    porte = set()
    for c in elenco_comandi:
        for trovato in re.finditer(r"http://127\.0\.0\.1:(\d+)/", c):
            porte.add(int(trovato.group(1)))
    return porte


def variabili_obbligatorie_dell_avvio(percorso_main):
    """Le variabili senza cui `main_casavip.py` RIFIUTA di partire.

    Non e' una lista scritta a mano qui: si legge dal codice dell'avvio. Si cercano le
    comprensioni di lista che scorrono una tupla di nomi MAIUSCOLI e li confrontano con
    `os.environ` (sono quelle che poi sollevano SystemExit). Ce n'e' piu' d'una - una
    per "manca del tutto", una per "c'e' ma e' il segnaposto pubblico" - quindi si
    tornano tutte e il chiamante ne fa l'unione. Se il codice dell'avvio cambia forma,
    questa funzione non trova piu' niente e il test lo dice a voce alta invece di dare
    per buona una lista vecchia.
    """
    albero = ast.parse(_leggi(percorso_main))
    trovate = []
    for nodo in ast.walk(albero):
        if not isinstance(nodo, ast.ListComp) or len(nodo.generators) != 1:
            continue
        gen = nodo.generators[0]
        if not isinstance(gen.iter, (ast.Tuple, ast.List)) or not gen.iter.elts:
            continue
        if not all(isinstance(e, ast.Constant) and isinstance(e.value, str)
                   for e in gen.iter.elts):
            continue
        nomi = [e.value for e in gen.iter.elts]
        if not all(re.match(r"^[A-Z][A-Z0-9_]+$", n) for n in nomi):
            continue
        condizioni = " ".join(ast.dump(c) for c in gen.ifs)
        if "environ" not in condizioni:
            continue
        trovate.append(sorted(nomi))
    return trovate


def versione_base(testo_dockerfile):
    """La versione di Python della riga FROM: `FROM python:3.11-slim` -> '3.11'."""
    for riga in testo_dockerfile.splitlines():
        nuda = riga.strip()
        if nuda.upper().startswith("FROM "):
            trovato = re.match(r"FROM\s+python:(\d+\.\d+)", nuda, re.IGNORECASE)
            if trovato:
                return trovato.group(1)
            return None
    return None


def porta_esposta(testo_dockerfile):
    trovato = re.search(r"^EXPOSE\s+(\d+)", testo_dockerfile, re.MULTILINE)
    return int(trovato.group(1)) if trovato else None


def installazioni_dell_immagine(testo_dockerfile):
    """Le righe del Dockerfile che installano pacchetti. In produzione: nessuna."""
    colpevoli = []
    for riga in testo_dockerfile.splitlines():
        nuda = riga.strip()
        if nuda.startswith("#"):
            continue
        if re.search(r"\b(pip3?|python -m pip)\s+install\b", nuda) or \
                re.search(r"\b(apt-get|apt|apk|yum)\s+(install|add)\b", nuda) or \
                re.search(r"\bpoetry\s+install\b", nuda):
            colpevoli.append(nuda)
    return colpevoli


def dichiarazione_ambiente(testo_ci):
    """Legge il blocco PARITA' DI AMBIENTE in testa a ci.yml.

    Torna {'produzione': '3.11', 'versioni': {'3.11': motivo, '3.9': motivo}}.
    Se il blocco non c'e', torna {} e i test lo denunciano: senza dichiarazione non si
    puo' nemmeno dire se la CI e la produzione divergono.
    """
    righe = testo_ci.splitlines()
    inizio = None
    for i, riga in enumerate(righe):
        if riga.lstrip("# ").startswith("PARITA' DI AMBIENTE"):
            inizio = i + 1
            break
    if inizio is None:
        return {}
    corpo = []
    for riga in righe[inizio:]:
        nuda = riga.strip()
        if not nuda.startswith("#"):
            break
        contenuto = nuda.lstrip("#").strip()
        if contenuto and set(contenuto) == {"="}:
            if corpo:
                break
            continue
        corpo.append(contenuto)
    testo = "\n".join(corpo)
    produzione = re.search(r"PRODUZIONE:\s*python:(\d+\.\d+)", testo)
    versioni = {}
    for trovato in re.finditer(r"^(\d+\.\d+)\s*-\s*MOTIVO:\s*(\S.*)$", testo,
                               re.MULTILINE):
        versioni[trovato.group(1)] = trovato.group(2).strip()
    return {"produzione": produzione.group(1) if produzione else None,
            "versioni": versioni}


def versioni_python_per_job(doc):
    """{nome job: set di versioni di Python}, risolvendo la matrice.

    Un job che non installa Python non compare: usa quello del runner e non e' un
    ambiente in cui gira il PRODOTTO (nel job `immagine` il Python che conta e' quello
    DENTRO l'immagine, che lo dice il Dockerfile).
    """
    fuori = {}
    for nome, job in (doc.get("jobs") or {}).items():
        matrice = ((job.get("strategy") or {}).get("matrix") or {})
        for passo in _passi(job):
            usa = str(passo.get("uses", ""))
            if "actions/setup-python" not in usa:
                continue
            grezzo = (passo.get("with") or {}).get("python-version")
            valori = grezzo if isinstance(grezzo, list) else [grezzo]
            for v in valori:
                riferimento = re.match(r"^\$\{\{\s*matrix\.([\w-]+)\s*\}\}$",
                                       str(v).strip())
                if riferimento:
                    dalla_matrice = matrice.get(riferimento.group(1), [])
                    for w in (dalla_matrice if isinstance(dalla_matrice, list)
                              else [dalla_matrice]):
                        fuori.setdefault(nome, set()).add(w)
                else:
                    fuori.setdefault(nome, set()).add(v)
    return fuori


def job_che_girano_la_suite_intera(doc):
    """I job che mandano in prova TUTTA la suite (non un sottoinsieme scelto).

    Due forme: `unittest discover` (la suite per intero) e l'elenco costruito a
    partire da tutti i `test_*.py` del repo meno il debito dichiarato, che il job
    sulla versione di produzione scrive in `moduli_311.txt`.
    """
    return sorted(nome for nome, job in (doc.get("jobs") or {}).items()
                  if any("unittest discover" in c or "moduli_311.txt" in c
                         for c in comandi(job)))


def moduli_esclusi_dal_gate_311(job):
    """I moduli che il comando BLOCCANTE del job 3.11 lascia fuori (il debito)."""
    for c in comandi(job):
        trovato = re.search(r"grep -vE '\^\(([^)]*)\)\\\.py\$'", c)
        if trovato:
            return sorted(trovato.group(1).split("|"))
    return []


def moduli_del_passo_report(job):
    """I moduli che il passo report-only del job 3.11 rimanda in prova comunque.

    E' il comando che nomina i moduli uno per uno; quello che BLOCCA invece li legge
    da `moduli_311.txt`, e non va confuso con questo.
    """
    for c in comandi(job):
        if "unittest" in c and "moduli_311.txt" not in c:
            return sorted(set(re.findall(r"\btest_[a-z0-9_]+", c)))
    return []


def pacchetti_installati_dalla_ci(doc, requisiti):
    """I pacchetti (nomi di IMPORT) che la CI mette attorno ai test."""
    nomi = set()
    for job in (doc.get("jobs") or {}).values():
        for c in comandi(job):
            for riga in c.splitlines():
                if not re.search(r"\bpip3?\s+install\b", riga):
                    continue
                pezzi = riga.split()
                salta = False
                for p in pezzi[pezzi.index("install") + 1:]:
                    if salta:
                        salta = False
                        continue
                    if p == "-r":
                        salta = True
                        nomi.update(requisiti)
                        continue
                    if p.startswith("-"):
                        continue
                    base = re.split(r"[=<>!\[;]", p)[0].strip().lower()
                    if base:
                        nomi.add(NOME_IMPORT.get(base, base))
    return nomi


def requisiti_di_produzione(percorso):
    """I nomi di import elencati in requirements.txt."""
    nomi = set()
    for riga in _leggi(percorso).splitlines():
        nuda = riga.split("#")[0].strip()
        if not nuda:
            continue
        base = re.split(r"[=<>!\[;]", nuda)[0].strip().lower()
        if base:
            nomi.add(NOME_IMPORT.get(base, base))
    return nomi


# ---------------------------------------------------------------------------
#  Grafo degli import: chi gira davvero in produzione
# ---------------------------------------------------------------------------
def _albero(cartella, modulo):
    percorso = os.path.join(cartella, modulo + ".py")
    if not os.path.isfile(percorso):
        return None
    try:
        return ast.parse(_leggi(percorso))
    except SyntaxError:
        return None


def _moduli_locali(cartella):
    return set(os.path.splitext(n)[0] for n in os.listdir(cartella)
               if n.endswith(".py") and os.path.isfile(os.path.join(cartella, n)))


def _importati(albero):
    """(nome base del modulo importato, nodo) per ogni import dell'albero."""
    fuori = []
    for nodo in ast.walk(albero):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                fuori.append((alias.name.split(".")[0], nodo))
        elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
            fuori.append((nodo.module.split(".")[0], nodo))
    return fuori


def chiusura_di_produzione(cartella, avvio=AVVIO):
    """Tutti i moduli locali raggiungibili dall'avvio, import dopo import."""
    locali = _moduli_locali(cartella)
    visti = set()
    da_fare = [avvio]
    while da_fare:
        modulo = da_fare.pop()
        if modulo in visti:
            continue
        visti.add(modulo)
        albero = _albero(cartella, modulo)
        if albero is None:
            continue
        for base, _ in _importati(albero):
            if base in locali and base not in visti:
                da_fare.append(base)
    return visti


def import_di_terze_parti(cartella, moduli, vietati):
    """Import di pacchetti che l'immagine NON contiene.

    Torna due elenchi: quelli a LIVELLO DI MODULO e senza try (fatali: il container
    muore all'avvio) e quelli ANNIDATI e senza try (fatali solo se quella funzione
    viene chiamata). Un import dentro `try/except ImportError` non conta: e' una
    dipendenza dichiarata opzionale, ed e' il modo giusto di scriverla.
    """
    fatali, annidati = [], []
    for modulo in sorted(moduli):
        albero = _albero(cartella, modulo)
        if albero is None:
            continue
        protetti = set()
        for nodo in ast.walk(albero):
            if isinstance(nodo, ast.Try):
                for figlio in ast.walk(nodo):
                    protetti.add(id(figlio))
        livello_modulo = set(id(n) for n in albero.body)
        for base, nodo in _importati(albero):
            if base not in vietati or id(nodo) in protetti:
                continue
            if id(nodo) in livello_modulo:
                fatali.append((modulo, base, nodo.lineno))
            else:
                annidati.append((modulo, base, nodo.lineno))
    return fatali, annidati


# ===========================================================================
#  BUCO 1 — l'immagine viene costruita, avviata e interrogata
# ===========================================================================
class TestJobImmagine(unittest.TestCase):

    def setUp(self):
        self.testo = _leggi(CI_YML)
        self.doc = _doc_ci()
        self.assertIn(JOB_IMMAGINE, self.doc["jobs"],
                      "il job che costruisce l'immagine di produzione non esiste: la "
                      "CI giudica i sorgenti, non l'artefatto che va sul server")
        self.job = self.doc["jobs"][JOB_IMMAGINE]
        self.comandi = comandi(self.job)

    def test_il_job_e_bloccante_e_dichiarato_tale(self):
        self.assertIn(JOB_IMMAGINE, self.doc["jobs"][GATE]["needs"],
                      "il job esiste ma il gate non lo aspetta: potrebbe essere rosso "
                      "con la CI verde")
        sezione = self.testo.split("BLOCCANTI (entrano")[1].split("NON BLOCCANTI")[0]
        self.assertIn(JOB_IMMAGINE, sezione,
                      "il job non e' nell'elenco dei BLOCCANTI in testa a ci.yml: "
                      "nessuno sa se il suo rosso conta")
        self.assertIsNone(self.job.get("if"),
                          "un `if` a livello di job creerebbe eventi in cui non gira, "
                          "e il gate lo vedrebbe 'skipped'")
        self.assertIsNone(self.job.get("continue-on-error"))
        self.assertEqual(self.job.get("runs-on"), "ubuntu-latest")
        self.assertIn("needs.immagine.result",
                      "\n".join(comandi(self.doc["jobs"][GATE])),
                      "il riepilogo del gate non mostra l'esito del job immagine")

    def test_costruisce_proprio_il_dockerfile_di_produzione(self):
        self.assertEqual(dockerfile_costruiti(self.comandi), ["Dockerfile.casavip"],
                         "il job deve costruire UNA immagine e deve essere quella di "
                         "produzione: e' il file che il compose del VPS usa")

    def test_l_immagine_avviata_e_quella_appena_costruita(self):
        """Il difetto silenzioso: costruirne una e avviarne un'altra (magari vecchia,
        magari tirata giu' da un registro). Il verde direbbe una cosa e l'artefatto ne
        sarebbe un'altra."""
        costruite = immagini_costruite(self.comandi)
        avviate = immagini_avviate(self.comandi)
        self.assertEqual(len(costruite), 1, "tag costruiti: %s" % costruite)
        self.assertEqual(avviate, costruite,
                         "il job costruisce %s ma avvia %s: sta collaudando "
                         "un'immagine diversa da quella che ha appena assemblato"
                         % (costruite, avviate))

    def test_avvia_con_le_variabili_senza_cui_l_avvio_rifiuta_di_partire(self):
        """`main_casavip.py` fallisce CHIUSO se mancano HOST_KEY/ADMIN_KEY. Il job deve
        passarle, altrimenti il container morirebbe sempre e il job sarebbe un rosso
        fisso; e se domani l'avvio ne pretende una terza, questo test lo vede subito."""
        elenchi = variabili_obbligatorie_dell_avvio(
            os.path.join(RADICE, AVVIO + ".py"))
        self.assertGreaterEqual(len(elenchi), 1,
                                "non ho trovato nessuna lista di variabili "
                                "obbligatorie dentro %s.py: il codice d'avvio ha "
                                "cambiato forma e questa guardia va riletta" % AVVIO)
        unione = set()
        for elenco in elenchi:
            unione.update(elenco)
        obbligatorie = sorted(unione)
        self.assertEqual(obbligatorie, ["ADMIN_KEY", "HOST_KEY"])
        passate = variabili_passate_al_run(self.comandi)
        self.assertEqual([v for v in obbligatorie if v not in passate], [],
                         "il container verrebbe avviato senza queste variabili e "
                         "morirebbe con SystemExit(2). Passate: %s" % sorted(passate))
        for spenta in ("GEOCODING", "POI_OSM", "MARCA_TEMPORALE"):
            self.assertIn(spenta, passate,
                          "%r va passata spenta: un job di CI non deve chiamare "
                          "servizi esterni veri (geocoding, POI, marca temporale)"
                          % spenta)

    def test_nessuna_chiave_vera_nel_job(self):
        testo = "\n".join(self.comandi)
        self.assertNotIn("secrets.", testo,
                         "il job non deve toccare i segreti del repository: le chiavi "
                         "qui servono solo a far partire un processo usa-e-getta")
        for veleno in ("sk_live", "sk_test", "whsec_"):
            self.assertNotIn(veleno, testo)

    def test_aspetta_la_sonda_prima_di_interrogarla_e_non_aspetta_per_sempre(self):
        attesa = comando_del_passo(self.job, "State.Health.Status")
        self.assertIn("healthy", attesa)
        self.assertIn("exit 1", attesa,
                      "se l'attesa scade senza che l'immagine diventi sana, il passo "
                      "deve FALLIRE: un'attesa che finisce in silenzio e' un verde")
        self.assertTrue(re.search(r"seq 1 \d+", attesa),
                        "l'attesa deve avere un limite: senza, un container che non "
                        "parte tiene occupato il runner fino al timeout del job")
        self.assertIn("State.Running", attesa,
                      "se il container si spegne da solo (SystemExit dell'avvio) il "
                      "ciclo deve accorgersene subito, non aspettare il timeout")
        sonda = comando_del_passo(self.job, "/api/health")
        indici = [i for i, c in enumerate(self.comandi) if c in (attesa, sonda)]
        self.assertEqual(indici, sorted(indici))
        self.assertLess(self.comandi.index(attesa), self.comandi.index(sonda),
                        "la sonda va interrogata DOPO aver aspettato che l'immagine "
                        "sia sana, altrimenti si misura una corsa, non un servizio")

    def test_interroga_davvero_la_sonda_e_pretende_il_200(self):
        sonda = comando_del_passo(self.job, "/api/health")
        self.assertIn("%{http_code}", sonda,
                      "senza leggere il codice HTTP il passo direbbe verde anche su un "
                      "500: `curl` da solo esce 0 su qualunque risposta")
        self.assertIn('"200"', sonda)
        self.assertIn("exit 1", sonda)
        self.assertNotIn("|| true", sonda,
                         "un `|| true` qui renderebbe la sonda un ornamento")
        self.assertIn("cents_integer", sonda,
                      "il 200 non basta: il corpo deve essere quello del prodotto "
                      "(status ok + money_unit in centesimi interi), altrimenti "
                      "risponderebbe verde anche una pagina di cortesia di nginx")

    def test_prova_anche_che_il_frontend_e_dentro_l_immagine(self):
        """Un'immagine che risponde alle API ma non contiene deploy/ e' rotta lo
        stesso: il sito sarebbe bianco. La `COPY deploy ./deploy` va provata."""
        pagina = comando_del_passo(self.job, "pagina.html")
        self.assertIn("Bookin VIP", pagina)
        self.assertIn("exit 1", pagina)

    def test_la_porta_pubblicata_e_quella_che_si_interroga(self):
        coppie = porte_pubblicate(self.comandi)
        self.assertEqual(len(coppie), 1, "porte pubblicate: %s" % coppie)
        host, container = coppie[0]
        self.assertEqual(container, porta_esposta(_leggi(DOCKERFILE)),
                         "la porta del container non e' quella che il Dockerfile "
                         "dichiara con EXPOSE")
        self.assertEqual(porte_interrogate(self.comandi), {host},
                         "i comandi bussano a una porta diversa da quella pubblicata")
        self.assertIn("PORTA=%d" % container, "\n".join(self.comandi),
                      "la variabile PORTA passata al container deve coincidere con la "
                      "porta pubblicata, o il server ascolterebbe altrove")

    def test_il_container_viene_sempre_spento(self):
        spegnimenti = [p for p in _passi(self.job)
                       if isinstance(p.get("run"), str) and "docker rm -f" in p["run"]]
        self.assertEqual(len(spegnimenti), 1)
        self.assertEqual(str(spegnimenti[0].get("if")).strip(), "always()",
                         "senza `if: always()` un passo rosso lascerebbe il container "
                         "acceso e la porta occupata")
        self.assertIs(spegnimenti[0], _passi(self.job)[-1],
                      "lo spegnimento deve essere l'ultimo passo del job")
        log = [p for p in _passi(self.job)
               if isinstance(p.get("run"), str) and "docker logs" in p["run"]]
        self.assertEqual(len(log), 1)
        self.assertEqual(str(log[0].get("if")).strip(), "always()",
                         "i log del container si vogliono SOPRATTUTTO quando qualcosa "
                         "e' andato storto: sono l'unica diagnosi disponibile")

    def test_i_passi_che_giudicano_non_sono_annullati(self):
        """`|| true` e' ammesso solo sui due passi di servizio (log e spegnimento)."""
        for passo in _passi(self.job):
            run = passo.get("run")
            if not isinstance(run, str):
                continue
            di_servizio = "docker logs" in run or "docker rm -f" in run
            with self.subTest(passo=passo.get("name")):
                self.assertIsNone(passo.get("continue-on-error"))
                if not di_servizio:
                    self.assertNotIn("|| true", run,
                                     "il passo %r non esprime piu' nessun giudizio"
                                     % passo.get("name"))

    # ---------------- VISTO ROSSO degli estrattori (dati finti guasti) -------
    def test_gli_estrattori_vedono_rosso_sui_dati_guasti(self):
        buono = ["docker build -f Dockerfile.casavip -t casavip-app:ci .",
                 "docker run -d --name x -p 18080:8080 -e A=1 casavip-app:ci"]
        self.assertEqual(immagini_costruite(buono), ["casavip-app:ci"])
        self.assertEqual(immagini_avviate(buono), ["casavip-app:ci"])
        self.assertEqual(variabili_passate_al_run(buono), {"A"})
        self.assertEqual(porte_pubblicate(buono), [(18080, 8080)])

        # 1) costruisce una cosa e ne avvia un'altra
        guasto = [buono[0], "docker run -d --name x casavip-app:vecchia"]
        self.assertNotEqual(immagini_avviate(guasto), immagini_costruite(guasto))
        # 2) il Dockerfile costruito non e' quello di produzione
        self.assertEqual(dockerfile_costruiti(["docker build -f Dockerfile.altro -t a ."]),
                         ["Dockerfile.altro"])
        # 3) `-p` scambiato per il nome dell'immagine (l'errore classico del parser)
        self.assertEqual(immagini_avviate(["docker run -p 1:2 -e K=v alpine"]),
                         ["alpine"])
        # 4) nessun avvio: l'estrattore non deve inventarne uno
        self.assertEqual(immagini_avviate(["docker build -t solo-build ."]), [])
        self.assertEqual(variabili_passate_al_run(["echo -e CIAO=1"]), set())

    def test_il_lettore_delle_variabili_obbligatorie_non_e_cieco(self):
        """VISTO ROSSO del lettore: su un avvio finto deve trovare ESATTAMENTE la lista
        giusta, non trovare niente quando la condizione non guarda l'ambiente, e non
        farsi ingannare da una comprensione qualunque."""
        import shutil
        import tempfile
        cartella = tempfile.mkdtemp(prefix="avvio_")
        self.addCleanup(shutil.rmtree, cartella, True)

        def scrivi(nome, testo):
            percorso = os.path.join(cartella, nome)
            with io.open(percorso, "w", encoding="utf-8") as f:
                f.write(testo)
            return percorso

        buono = scrivi("avvio_buono.py",
                       "import os\n"
                       "def main():\n"
                       "    m = [n for n in ('HOST_KEY', 'ADMIN_KEY')\n"
                       "         if not os.environ.get(n)]\n"
                       "    p = [x for x in ('ciao',) if x]\n"
                       "    q = [c for c in sorted(vars(C())) if c]\n"
                       "    if m:\n"
                       "        raise SystemExit(2)\n"
                       "    return p, q\n")
        self.assertEqual(variabili_obbligatorie_dell_avvio(buono),
                         [["ADMIN_KEY", "HOST_KEY"]],
                         "il lettore o non trova la lista vera, o si prende anche le "
                         "comprensioni che non c'entrano niente")
        cieco = scrivi("avvio_cieco.py",
                       "def main():\n"
                       "    m = [n for n in ('HOST_KEY',) if n]\n"
                       "    return m\n")
        self.assertEqual(variabili_obbligatorie_dell_avvio(cieco), [],
                         "una comprensione che non guarda l'ambiente non e' un "
                         "controllo di variabili obbligatorie")
        # sul file VERO: piu' d'un controllo (manca / e' il segnaposto pubblico), ma
        # sempre e solo su quelle due chiavi
        elenchi = variabili_obbligatorie_dell_avvio(
            os.path.join(RADICE, AVVIO + ".py"))
        self.assertTrue(elenchi)
        for elenco in elenchi:
            self.assertEqual(elenco, ["ADMIN_KEY", "HOST_KEY"])

    def test_le_chiavi_del_job_non_sono_i_segnaposto_pubblici(self):
        """L'avvio RIFIUTA di partire anche se la chiave c'e' ma e' il segnaposto di
        .env.casavip.example (che sta su GitHub). Se il job usasse uno di quei valori,
        il container morirebbe sempre e il job sarebbe un rosso fisso senza colpa del
        prodotto. I segnaposto si leggono dal codice d'avvio, non a memoria."""
        albero = ast.parse(_leggi(os.path.join(RADICE, AVVIO + ".py")))
        segnaposto = []
        for nodo in ast.walk(albero):
            if isinstance(nodo, ast.Assign) and any(
                    isinstance(b, ast.Name) and b.id == "SEGNAPOSTO_PUBBLICI"
                    for b in nodo.targets):
                if isinstance(nodo.value, (ast.Tuple, ast.List)):
                    segnaposto = [e.value for e in nodo.value.elts
                                  if isinstance(e, ast.Constant)]
        self.assertTrue(segnaposto,
                        "non trovo piu' SEGNAPOSTO_PUBBLICI in %s.py: il controllo qui "
                        "sotto sarebbe cieco" % AVVIO)
        testo = "\n".join(self.comandi)
        for veleno in segnaposto:
            self.assertNotIn(veleno, testo,
                             "il job avvia il container con il segnaposto pubblico %r: "
                             "l'avvio lo rifiuta e il job sarebbe rosso per sempre"
                             % veleno)


# ===========================================================================
#  BUCO 2 — la CI gira sul Python della produzione, o lo dichiara
# ===========================================================================
class TestParitaVersionePython(unittest.TestCase):

    def setUp(self):
        self.testo = _leggi(CI_YML)
        self.doc = _doc_ci()
        self.dockerfile = _leggi(DOCKERFILE)
        self.produzione = versione_base(self.dockerfile)
        self.dichiarazione = dichiarazione_ambiente(self.testo)
        self.per_job = versioni_python_per_job(self.doc)

    def test_il_dockerfile_dichiara_la_versione_di_produzione(self):
        self.assertEqual(self.produzione, "3.11",
                         "la base dell'immagine e' cambiata: aggiorna la "
                         "dichiarazione PARITA' DI AMBIENTE in ci.yml e la matrice di "
                         "full-suite, poi cambia questo numero di proposito")
        self.assertIn("FROM python:3.11-slim", self.dockerfile)
        self.assertEqual(versione_base(_leggi(DOCKERFILE_GEMELLO)), self.produzione,
                         "Dockerfile e Dockerfile.casavip partono da basi diverse: due "
                         "immagini gemelle che divergono sono due produzioni diverse")

    def test_la_dichiarazione_in_ci_coincide_col_dockerfile(self):
        self.assertTrue(self.dichiarazione,
                        "manca il blocco PARITA' DI AMBIENTE in testa a ci.yml: senza "
                        "dichiarazione nessuno puo' dire se CI e produzione divergono")
        self.assertEqual(
            self.dichiarazione["produzione"], self.produzione,
            "ci.yml dichiara di girare per la produzione %r ma il Dockerfile parte da "
            "%r: uno dei due mente, e quello che conta e' il Dockerfile"
            % (self.dichiarazione["produzione"], self.produzione))

    def test_ogni_versione_usata_da_un_job_e_dichiarata_con_un_motivo(self):
        usate = set()
        for versioni in self.per_job.values():
            usate.update(versioni)
        dichiarate = set(self.dichiarazione["versioni"])
        self.assertEqual(sorted(usate), ["3.11", "3.9"])
        self.assertEqual(
            sorted(usate - dichiarate), [],
            "queste versioni girano in CI senza una nota che dica perche': %s"
            % sorted(usate - dichiarate))
        self.assertEqual(
            sorted(dichiarate - usate), [],
            "queste versioni sono dichiarate ma non le usa piu' nessun job: la "
            "dichiarazione e' invecchiata e racconta una CI che non esiste: %s"
            % sorted(dichiarate - usate))
        for versione, motivo in sorted(self.dichiarazione["versioni"].items()):
            with self.subTest(versione=versione):
                self.assertGreaterEqual(
                    len(motivo), 30,
                    "il motivo di %r e' una riga vuota di cortesia: deve dire perche' "
                    "quella versione esiste" % versione)

    def test_le_versioni_sono_stringhe_e_non_numeri_yaml(self):
        """Trappola vera: `python-version: 3.10` senza apici, YAML lo carica come il
        numero 3.1 e la CI installerebbe Python 3.1."""
        for nome, job in self.doc["jobs"].items():
            matrice = ((job.get("strategy") or {}).get("matrix") or {})
            for valori in matrice.values():
                for v in (valori if isinstance(valori, list) else [valori]):
                    with self.subTest(job=nome, valore=v):
                        self.assertIsInstance(v, str,
                                              "valore di matrice non fra apici in %r"
                                              % nome)
            for passo in _passi(job):
                if "actions/setup-python" not in str(passo.get("uses", "")):
                    continue
                grezzo = (passo.get("with") or {}).get("python-version")
                with self.subTest(job=nome):
                    self.assertIsInstance(grezzo, str,
                                          "python-version senza apici nel job %r: YAML "
                                          "lo trasforma in un numero" % nome)

    def test_la_suite_intera_gira_anche_sulla_versione_di_produzione(self):
        girano = job_che_girano_la_suite_intera(self.doc)
        self.assertEqual(girano, ["copertura", "full-suite", "full-suite-311"],
                         "i job che eseguono la suite INTERA sono cambiati: se ne hai "
                         "aggiunto uno, decidi di proposito su quale Python deve "
                         "girare e scrivilo qui e nella dichiarazione PARITA' DI "
                         "AMBIENTE. Trovati: %s" % girano)
        self.assertEqual(self.per_job.get("full-suite"), {"3.9"})
        self.assertEqual(self.per_job.get("full-suite-311"), {"3.11"},
                         "il job gemello deve girare sul Python della PRODUZIONE: e' "
                         "tutta la sua ragione di esistere")
        coperte = set()
        for nome in girano:
            coperte.update(self.per_job.get(nome, set()))
        self.assertIn(self.produzione, coperte,
                      "nessun job che esegue la suite intera gira sul Python di "
                      "produzione: la CI giudica un ambiente che non esiste sul VPS")
        self.assertIn("full-suite-311", self.doc["jobs"][GATE]["needs"],
                      "il job sulla versione di produzione deve BLOCCARE: se resta "
                      "fuori dal gate, il suo rosso non ferma nessun deploy")

    def test_il_debito_su_3_11_e_dichiarato_modulo_per_modulo_e_a_cricchetto(self):
        """Il job 3.11 blocca su tutto TRANNE un elenco di moduli scritto in chiaro.
        Quell'elenco e' l'unica cosa che lo tiene verde oggi: se diventasse una lista
        aperta, il job non proverebbe piu' niente. Quindi: nomi veri, elenco corto, e
        i moduli esclusi devono comunque girare nel passo report-only."""
        job = self.doc["jobs"]["full-suite-311"]
        esclusi = moduli_esclusi_dal_gate_311(job)
        self.assertEqual(len(esclusi), 7,
                         "CRICCHETTO del debito su 3.11: da questo elenco si possono "
                         "solo TOGLIERE moduli (quando li si corregge), mai "
                         "aggiungerne. Erano 7 il 2026-07-29. Trovati: %s" % esclusi)
        for modulo in esclusi:
            with self.subTest(modulo=modulo):
                self.assertTrue(
                    os.path.isfile(os.path.join(RADICE, modulo + ".py")),
                    "il debito nomina %r, che non esiste piu' come file: o e' un "
                    "refuso (e allora il modulo VERO sta girando senza rete) o e' "
                    "una riga da cancellare" % modulo)
        self.assertEqual(moduli_del_passo_report(job), esclusi,
                         "i moduli esclusi dal comando che blocca e quelli rimandati "
                         "in prova nel passo report-only DEVONO coincidere: se "
                         "divergono, una parte del debito non la guarda piu' nessuno")

    def test_il_job_311_non_puo_svuotarsi_di_nascosto(self):
        """Il difetto peggiore possibile qui: un filtro sbagliato che lascia zero
        moduli. Il comando uscirebbe 0 e il job sarebbe VERDE avendo provato niente."""
        blocco = comando_del_passo(self.doc["jobs"]["full-suite-311"], "moduli_311.txt")
        self.assertNotIn("|| true", blocco)
        self.assertIn("-lt 300", blocco,
                      "manca la guardia sul numero di moduli: senza, un filtro rotto "
                      "renderebbe il job verde a vuoto")
        self.assertIn("exit 1", blocco)
        quanti = len([n for n in os.listdir(RADICE)
                      if n.startswith("test_") and n.endswith(".py")])
        self.assertGreater(quanti, 300,
                           "i moduli di test nel repo sono %d: la soglia -lt 300 "
                           "scritta nel job va rivista, altrimenti diventa un rosso "
                           "fisso" % quanti)

    def test_il_fuzzing_gira_sulla_versione_di_produzione(self):
        self.assertEqual(self.per_job.get("atheris"), {"3.11"},
                         "atheris gira su 3.11 per via della wheel: e' gia' un pezzo "
                         "di parita' d'ambiente e deve restare dichiarato")

    def test_i_job_di_soli_strumenti_restano_sul_pavimento(self):
        for nome in ("money-smoke", "copertura", "mutazione", "qualita", "w3c"):
            with self.subTest(job=nome):
                self.assertEqual(self.per_job.get(nome), {"3.9"},
                                 "il job %r ha cambiato versione senza passare dalla "
                                 "dichiarazione" % nome)

    def test_il_job_immagine_non_installa_python_sul_runner(self):
        """Nel job dell'immagine il Python che conta e' quello DENTRO il container: se
        qualcuno aggiungesse setup-python li', starebbe misurando il runner."""
        self.assertNotIn(JOB_IMMAGINE, self.per_job)

    # ---------------- VISTO ROSSO dei lettori (dati finti guasti) -----------
    def test_il_lettore_della_versione_base_vede_rosso(self):
        self.assertEqual(versione_base("FROM python:3.12-slim\nRUN x\n"), "3.12")
        self.assertEqual(versione_base("FROM python:3.11.9-slim\n"), "3.11")
        self.assertIsNone(versione_base("FROM debian:bookworm\n"))
        self.assertIsNone(versione_base("# solo commenti\n"))

    def test_il_lettore_della_dichiarazione_vede_rosso(self):
        finto = ("# =====\n"
                 "#  PARITA' DI AMBIENTE - prova\n"
                 "# =====\n"
                 "#      PRODUZIONE: python:3.12-slim\n"
                 "#      3.12 - MOTIVO: e' la versione della produzione finta\n"
                 "#      3.7  - MOTIVO: pavimento finto di compatibilita'\n"
                 "# =====\n"
                 "jobs: {}\n")
        letto = dichiarazione_ambiente(finto)
        self.assertEqual(letto["produzione"], "3.12")
        self.assertEqual(sorted(letto["versioni"]), ["3.12", "3.7"])
        self.assertIn("produzione finta", letto["versioni"]["3.12"])
        # divergenza col Dockerfile: e' esattamente il rosso che deve scattare
        self.assertNotEqual(letto["produzione"], versione_base(self.dockerfile))
        # senza il blocco non si inventa niente
        self.assertEqual(dichiarazione_ambiente("name: x\njobs: {}\n"), {})

    def test_il_lettore_delle_versioni_per_job_vede_rosso(self):
        finto = yaml.safe_load(
            "jobs:\n"
            "  a:\n"
            "    strategy:\n"
            "      matrix:\n"
            "        python-version: ['3.9', '3.13']\n"
            "    steps:\n"
            "      - uses: actions/setup-python@v6\n"
            "        with:\n"
            "          python-version: ${{ matrix.python-version }}\n"
            "  b:\n"
            "    steps:\n"
            "      - uses: actions/setup-python@v6\n"
            "        with:\n"
            "          python-version: '3.8'\n"
            "  c:\n"
            "    steps:\n"
            "      - run: echo niente python\n")
        letto = versioni_python_per_job(finto)
        self.assertEqual(letto, {"a": {"3.9", "3.13"}, "b": {"3.8"}},
                         "la matrice non e' stata risolta, o un job senza Python e' "
                         "stato inventato")
        dichiarate = {"3.9"}
        usate = set()
        for v in letto.values():
            usate.update(v)
        self.assertEqual(sorted(usate - dichiarate), ["3.13", "3.8"],
                         "il confronto che denuncia le versioni non dichiarate non "
                         "vede piu' niente")


# ===========================================================================
#  BUCO 3 — le dipendenze della CI non sono quelle dell'immagine
# ===========================================================================
class TestDipendenzeImmagineVsCI(unittest.TestCase):

    def setUp(self):
        self.dockerfile = _leggi(DOCKERFILE)
        self.doc = _doc_ci()
        self.requisiti = requisiti_di_produzione(REQUIREMENTS)
        self.chiusura = chiusura_di_produzione(RADICE)

    def test_l_immagine_non_installa_proprio_niente(self):
        """La produzione e' stdlib-pura: si DIMOSTRA leggendo il Dockerfile, non si
        ricorda a memoria. Se un giorno l'immagine iniziasse a installare qualcosa,
        questo test lo denuncia e la parita' andrebbe ridichiarata."""
        self.assertEqual(installazioni_dell_immagine(self.dockerfile), [],
                         "il Dockerfile ha cominciato a installare pacchetti: da quel "
                         "momento l'immagine non e' piu' stdlib-pura e la CI deve "
                         "installare ESATTAMENTE gli stessi")
        self.assertNotIn("requirements.txt", self.dockerfile,
                         "l'immagine non copia requirements.txt: se lo facesse, "
                         "sarebbe l'inizio di una divergenza fra i due ambienti")
        self.assertIn("stdlib", self.dockerfile.lower(),
                      "il Dockerfile deve dichiarare a parole che la produzione gira "
                      "su stdlib pura: e' cio' che rende leggibile lo zero qui sopra")

    def test_il_lettore_delle_installazioni_vede_rosso(self):
        for guasto in ("RUN pip install requests",
                       "RUN pip3 install -r requirements.txt",
                       "RUN python -m pip install stripe==11.4.0",
                       "RUN apt-get install -y curl",
                       "RUN apk add --no-cache curl"):
            with self.subTest(riga=guasto):
                self.assertEqual(installazioni_dell_immagine(
                    "FROM python:3.11-slim\n" + guasto + "\n"), [guasto])
        self.assertEqual(installazioni_dell_immagine(
            "FROM python:3.11-slim\n# RUN pip install requests\nCOPY a ./\n"), [],
            "una riga di commento non e' un'installazione")

    def test_la_ci_invece_installa_e_la_divergenza_e_reale(self):
        installati = pacchetti_installati_dalla_ci(self.doc, self.requisiti)
        for atteso in ("hypothesis", "coverage", "yaml", "flask", "stripe"):
            self.assertIn(atteso, installati,
                          "controllo cieco: la CI installa pacchetti e questo lettore "
                          "non li vede piu'")
        self.assertEqual(installazioni_dell_immagine(self.dockerfile), [],
                         "divergenza dichiarata: la CI ha %d pacchetti attorno ai "
                         "test, l'immagine zero" % len(installati))

    def test_la_chiusura_di_produzione_e_quella_vera(self):
        self.assertIn(AVVIO, self.chiusura)
        self.assertIn("fase83_server", self.chiusura)
        self.assertIn("fase81_bootstrap_casavip", self.chiusura)
        self.assertGreaterEqual(len(self.chiusura), 80,
                                "la chiusura degli import e' crollata a %d moduli: il "
                                "lettore si e' rotto, oppure il prodotto si e' "
                                "smontato" % len(self.chiusura))
        self.assertNotIn("fase13_protocollo_finale", self.chiusura,
                         "il vecchio stack Flask e' rientrato negli import di "
                         "produzione: importa psutil, requests e flask a livello di "
                         "modulo e l'immagine NON li ha")

    def test_nessun_modulo_di_produzione_importa_terze_parti_all_avvio(self):
        """L'invariante che tiene in piedi tutto: un import di terze parti a livello di
        modulo, dentro la chiusura di produzione, uccide il container all'avvio. In CI
        non si vedrebbe mai, perche' li' quel pacchetto e' installato."""
        vietati = set(self.requisiti) | pacchetti_installati_dalla_ci(self.doc,
                                                                     self.requisiti)
        self.assertIn("flask", vietati)
        self.assertIn("stripe", vietati)
        fatali, annidati = import_di_terze_parti(RADICE, self.chiusura, vietati)
        self.assertEqual(fatali, [],
                         "questi moduli GIRANO in produzione e importano, a livello di "
                         "modulo, pacchetti che l'immagine non contiene: il container "
                         "morirebbe all'avvio. %s" % fatali)
        self.assertEqual(sorted((m, p) for m, p, _ in annidati), sorted(LAZY_AMMESSI),
                         "gli import di terze parti annidati sono cambiati. Quelli "
                         "ammessi sono adattatori Flask che main_casavip non chiama "
                         "mai; uno nuovo va guardato in faccia: se quella funzione "
                         "viene chiamata in produzione, esplode. Trovati: %s"
                         % sorted((m, p) for m, p, _ in annidati))

    def test_lo_scanner_trova_il_caso_VERO_gia_presente_nel_repo(self):
        """VISTO ROSSO su codice vero, non finto. `fase13_protocollo_finale.py` e' il
        vecchio stack e importa psutil, requests e flask A LIVELLO DI MODULO: se
        rientrasse negli import di produzione, il container morirebbe all'avvio. Lo
        scanner lo trova. Se un giorno non lo trovasse piu', il test qui sopra (quello
        che pretende zero import fatali) sarebbe diventato un ornamento."""
        vietati = set(self.requisiti)
        fatali, _ = import_di_terze_parti(RADICE, {"fase13_protocollo_finale"},
                                          vietati)
        self.assertEqual(sorted(p for _, p, _ in fatali),
                         ["flask", "psutil", "requests"],
                         "lo scanner non vede piu' i tre import fatali che esistono "
                         "davvero in fase13_protocollo_finale.py: e' cieco, e lo zero "
                         "che dichiara sulla produzione non vale niente")

    def test_il_lettore_degli_import_vede_rosso(self):
        import shutil
        import tempfile
        cartella = tempfile.mkdtemp(prefix="parita_")
        self.addCleanup(shutil.rmtree, cartella, True)

        def scrivi(nome, testo):
            with io.open(os.path.join(cartella, nome), "w", encoding="utf-8") as f:
                f.write(testo)

        scrivi("main_casavip.py", "import fase_uno\nimport fase_due\n")
        scrivi("fase_uno.py", "import stripe\nimport json\n")
        scrivi("fase_due.py", "import os\n\n\ndef f():\n    import requests\n"
                              "    return requests\n")
        scrivi("fase_tre.py", "try:\n    import flask\nexcept ImportError:\n"
                              "    flask = None\n")
        chiusura = chiusura_di_produzione(cartella)
        self.assertEqual(sorted(chiusura), ["fase_due", "fase_uno", "main_casavip"],
                         "un modulo mai importato non deve entrare nella chiusura")
        fatali, annidati = import_di_terze_parti(
            cartella, chiusura | {"fase_tre"}, {"stripe", "requests", "flask"})
        self.assertEqual(fatali, [("fase_uno", "stripe", 1)],
                         "l'import fatale a livello di modulo non viene piu' visto")
        self.assertEqual(annidati, [("fase_due", "requests", 5)],
                         "l'import annidato non viene piu' visto")
        self.assertNotIn("fase_tre", [m for m, _, _ in fatali + annidati],
                         "un import dentro try/except e' una dipendenza opzionale "
                         "dichiarata: non e' un difetto")


class TestLeCifrePreteseDalJobEsistonoSullaMACCHINA(unittest.TestCase):
    """Due affermazioni del job `immagine` che nessuno confrontava con la realta'.

    Aggiunte il 2026-07-31 unendo questo file con la versione scritta lo stesso giorno
    (commit 59bd540): tutto il resto era gia' coperto qui, meglio; questi due no.

    Il job non si limita a chiedere «risponde?»: pretende DUE VALORI ESATTI — che il
    container giri con l'uid 10001 e che la pagina servita sia la home del prodotto. Se
    domani il `Dockerfile` cambia utente, o la home cambia titolo, quelle due righe
    diventano un ROSSO PERMANENTE su una macchina sanissima: un falso allarme, che la
    REGOLA FERREA 10 considera un difetto quanto un allarme mancato. E un rosso fisso
    insegna a ignorare il rosso, che e' il danno peggiore.

    Qui i due valori vengono confrontati con la loro FONTE, cosi' la divergenza si vede
    in un test locale di mezzo secondo invece che in un job Docker da venti minuti.
    """

    def setUp(self):
        job = _doc_ci()["jobs"].get(JOB_IMMAGINE)
        self.assertIsNotNone(job, "il job `immagine` non c'e' piu'")
        self.cmd = "\n".join(str(p.get("run", "")) for p in job.get("steps", []))

    def test_uid_preteso_uguale_a_quello_che_il_dockerfile_crea(self):
        # ancorata a UID_VERO: senza l'ancora la stessa forma pesca il `!= "200"` del
        # controllo HTTP, e la guardia confronta due numeri che non c'entrano nulla.
        # (Successo davvero mentre si scriveva questo test, il 2026-07-31.)
        atteso = re.search(r'\$UID_VERO"?\s*!=\s*"(\d+)"', self.cmd)
        self.assertIsNotNone(atteso,
                             "il job non verifica piu' che il container NON giri da root")
        creato = re.search(r"useradd[^\n]*-u\s+(\d+)", _leggi(DOCKERFILE))
        self.assertIsNotNone(creato,
                             "Dockerfile.casavip non crea piu' un utente con uid esplicito")
        self.assertEqual(atteso.group(1), creato.group(1),
                         "la CI pretende uid %s ma il Dockerfile ne crea %s: il job "
                         "sarebbe rosso per sempre su un'immagine sana"
                         % (atteso.group(1), creato.group(1)))

    def test_il_titolo_preteso_e_davvero_quello_della_home(self):
        atteso = re.search(r'grep -q "([^"]*<title>[^"]*)" pagina\.html', self.cmd)
        self.assertIsNotNone(atteso,
                             "il job non verifica piu' che / sia la home del prodotto: un "
                             "200 su una pagina vuota passerebbe")
        home = os.path.join(RADICE, "deploy", "index.html")
        self.assertTrue(os.path.exists(home), "manca deploy/index.html")
        self.assertIn(atteso.group(1), _leggi(home),
                      "la CI cerca %r nella home, ma deploy/index.html non lo contiene: "
                      "guardia destinata a un rosso permanente" % atteso.group(1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
