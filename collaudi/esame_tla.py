"""L'ESAME DELLA CASELLA «IL MODELLO TLA+ DEGLI STATI DEL DENARO GIRA IN CI COL MODEL CHECKER
TLC A OGNI UNIONE» — blocco SOLDI, tecnica 2 di 8 (mappa del fondatore del 15/11).

    python collaudi/esame_tla.py               misura e MOSTRA, senza scrivere (cosi' gira in CI)
    python collaudi/esame_tla.py --scrivi      misura e SCRIVE la casella (anche falsa)
    python collaudi/esame_tla.py --autoprova   SOLO il metro (il giro buono e le varianti): non
                                               guarda ancore e CI, e non e' un cancello

⛔ IL TESTO DELLA CASELLA NON SI RICOPIA: si cerca in `piano.py` per contenuto e deve comparire
   UNA volta sola; se sparisce o si sdoppia, l'esame si ferma.

COME MISURA. Il modello e' `collaudi/tla/Soldi.tla`: i soldi di una prenotazione dal pagamento
(subito o bloccato sulla carta) all'incasso, alle cancellazioni, alla garanzia, al bonifico
all'host e alla contestazione della banca. TLC (il model checker ufficiale di TLA+, jar
inchiodato per impronta) lo esplora TUTTO, ogni sequenza di passi. La casella chiede tre cose:
  1. le regole vere PASSANO: con DIFETTO = "nessuno" (il codice di oggi) TLC finisce con
     «No error has been found», uscita 0, e OGNI passo del modello e' scattato almeno una
     volta (un passo che non scatta mai e' un controllo vuoto);
  2. le varianti col difetto messo apposta VENGONO TROVATE: per ognuna di VARIANTI (un difetto
     gia' riparato, rimesso togliendo la sua guardia) TLC esce 12 sulla regola attesa;
  3. gira in CI a ogni unione: il job `qualita` (che il `gate` aspetta) esegue proprio QUESTO
     esame, senza `|| true` e senza `continue-on-error`.
In piu', perche' il modello non resti indietro rispetto al codice: ogni variante nomina le
guardie del codice che la riparano (ANCORE: file, funzione, pezzo di codice eseguibile), e se
una manca l'esame e' rosso. Il modello le da' per scontate: tolte dal codice, il verde del
modello non direbbe piu' niente sul prodotto.

Uscite di TLC (tlc2.output.EC.ExitStatus, tla2tools v1.7.4): 0 nessun errore, 10 ASSUME
violata, 12 regola (invariante) violata, 150/151 errori di lettura del modello o della
configurazione.

⛔ D18: precondizioni che fermano il giro (casella, modello, Java, jar con l'impronta giusta,
   ancore, CI), il metro provato nelle due direzioni a OGNI giro (il giro buono deve tacere,
   le varianti devono gridare), NON_GUARDA stampato, e la guardia
   `TestLEsameTlaNonPuoBARARE` in test_pipeline_ci.py.
"""
import ast
import functools
import glob
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize

QUI = os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(QUI)
for _p in (RADICE, QUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from piano import BLOCCHI  # noqa: E402
import scheda  # noqa: E402

BLOCCO_SOLDI = 1
SEGNALE = "il modello TLA+ degli stati del denaro"
COMANDO = "python collaudi/esame_tla.py --scrivi"
CI = os.path.join(RADICE, ".github", "workflows", "ci.yml")
JOB_CI = "qualita"
PASSO_CI = "python collaudi/esame_tla.py"
MODELLO = os.path.join(QUI, "tla", "Soldi.tla")
# tla2tools v1.7.4, l'ultima stabile (github.com/tlaplus/tlaplus/releases, letta il 23/11):
# l'impronta e' quella del jar scaricato da questo indirizzo il 23/11, identica a quella del
# jar di strumenti_verifica\tla (sha1 bee4a54f..., misurato il 22/11).
JAR_URL = "https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar"
JAR_SHA256 = "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
JAVA_MINIMO = 11            # tla2tools 1.7.x chiede Java 11 o piu'
TETTO_SEC = 600             # un giro di TLC su questo modello dura un secondo: 600 e' un guasto
# Le regole del giro buono: tutte quelle in fondo al modello.
REGOLE = ("TypeOK", "SoldiNostri", "BonificoSoloSuIncasso", "Doppio", "OspiteUnaVolta",
          "Totale", "NienteDopoLaPersa", "ReclamoAspettaLArbitro")
# I passi del modello che devono scattare nel giro buono (copertura di TLC, `-coverage`). Ogni
# strada e' un passo a se' (code-review, 23/11): TLC conta i passi, non i rami dentro un passo.
PASSI = ("Init", "Tempo", "GiroIncassa", "GiroScade", "GiroAnnulla", "GiroGiaIncassato",
         "CancellaSenzaPenale", "CancellaConPenale", "CancellaHost", "AdminRimborso",
         "ConfermaOspite", "Segnala", "AutoRilascio", "Bonifico", "BancaApre", "BancaVince",
         "BancaPerde", "ArbitroPersa", "ArbitroDivide")
_F83 = "fase83_server.py"
# difetto -> (regola che TLC deve trovare violata, guardie del codice che lo riparano). Ogni
# guardia e' (file, funzione, pezzo di codice eseguibile: commenti e docstring non contano).
VARIANTI = {
    # PR #342 (22-23/11): la contestazione PERSA divideva la garanzia («190 su 100»)
    "persa_divide": ("NienteDopoLaPersa", (
        (_F83, "_admin_controversia_risolvi_sotto_chiave", "g.chiudi_contestazione_persa("),
        ("fase160_escrow_garanzia.py", "chiudi_contestazione_persa",
         "host=0, rimborso=0"))),
    # F2 (13/10): l'arbitro divideva mentre la banca contestava ancora
    "arbitro_prima_della_banca": ("OspiteUnaVolta", (
        (_F83, "_admin_controversia_risolvi", '{"errore": "decide_la_banca"}'),)),
    # variant-analysis (23/11): la banca su una garanzia gia' segnalata dall'ospite
    "banca_su_reclamo_ignorata": ("OspiteUnaVolta", (
        (_F83, "_contestazione_carta", "gz.segna_contestazione_banca("),)),
    # C53-B1-4 / voce 138 (b): il chargeback ferma il bonifico non ancora partito
    "banca_non_trattiene": ("Totale", (
        (_F83, "_contestazione_carta", 'pd.aggiorna_stato(rif, "trattenuto")'),)),
    # voce 180 (busta A1, 27/10): 'trattenuto' non paga mai in automatico
    "trattenuto_paga": ("Totale", (
        (_F83, "_trasferisci_sotto_chiave", '_stato_pay == "trattenuto"'),)),
    # il blocco sulla carta: niente bonifico su soldi solo autorizzati o mai entrati
    "bonifico_su_blocco": ("BonificoSoloSuIncasso", (
        (_F83, "_trasferisci_sotto_chiave", '_blocco(rec)["stato"] in ("aperto", "annullato")'),)),
    # la guardia anti-doppio del bonifico
    "doppio_bonifico": ("Doppio", (
        (_F83, "_trasferisci_sotto_chiave", '_stato_pay in ("in_transito", "pagato")'),)),
    # F1/F2 e pacco 1 voce 2: con una controversia aperta nessuna strada restituisce i soldi
    "cancella_in_contestazione": ("OspiteUnaVolta", (
        (_F83, "_cancella_prenotazione_sotto_chiave", "self._controversia_aperta(rif)"),
        (_F83, "_host_cancella_sotto_chiave", "self._controversia_aperta(ref)"),
        (_F83, "_admin_rimborso_sotto_chiave", "self._controversia_aperta(_rif_c)"))),
    # consegne 30 punto c, (al): dopo la garanzia data o divisa non si restituisce piu'
    "rimborso_su_garanzia_chiusa": ("SoldiNostri", (
        (_F83, "_cancella_prenotazione_sotto_chiave", "self._garanzia_gia_divisa(rif)"),
        (_F83, "_admin_rimborso_sotto_chiave", "self._garanzia_gia_divisa(idem)"),
        (_F83, "_host_cancella_sotto_chiave", '_st.get("stato") in ("rilasciato", "risolto")'),
        (_F83, "_garanzia_gia_divisa", 'pd.stato_di(rif) in ("in_transito", "pagato")'))),
    # il CAS del rilascio automatico (3/300 al collaudo): una contestazione non si sovrascrive.
    # La riga che RILASCIA, non quella che annulla: «AND stato='in_garanzia'» c'e' in tutte e due.
    "rilascio_su_contestato": ("ReclamoAspettaLArbitro", (
        ("fase160_escrow_garanzia.py", "auto_rilascia",
         "\"aggiornato_ts=? WHERE prenotazione_id=? AND stato='in_garanzia'\", "
         "(r[\"importo_host_cents\"], ora, rif)"),)),
    # busta A3 colpo 1: la quota dell'arbitro riscrive anche la riga 'in_attesa'
    "riallinea_senza_in_attesa": ("SoldiNostri", (
        ("fase131_payout_dashboard.py", "riallinea_maturato",
         "\"AND stato IN ('trattenuto', 'maturato', 'in_attesa')\""),)),
}
NON_GUARDA = (
    "UNA prenotazione con importi fissi (prezzo 100, quota dell'host 90, penale 50 di cui 45 "
    "all'host): i difetti che dipendono dall'aritmetica dei centesimi li guardano z3, "
    "Hypothesis e la mutazione, non questo modello",
    "ogni passo del modello e' una funzione eseguita tutta insieme (nel codice sotto "
    "_BONIFICI_LOCK o in una transazione): una gara DENTRO una funzione non si vede qui",
    "si assume che l'avviso di Stripe sull'apertura della contestazione arrivi (webhook "
    "iscritto a charge.dispute.created) e che la banca non riprenda soldi gia' rimborsati",
    "la contestazione della banca DOPO il bonifico all'host e' una perdita finche' una persona "
    "non la recupera dall'host: il modello controlla che sia GRIDATA (ERROR), non evitata",
    "solo regole di sicurezza («non succede mai una cosa brutta»): che un bonifico fermo prima "
    "o poi parta (vivacita') non e' controllato",
    "le ancore controllano che le guardie del codice CI SIANO (parola per parola, una volta "
    "sola, fuori da commenti, docstring e funzioni annidate, non precedute da `not`), non che "
    "funzionino ne' che si raggiungano: una guardia sotto `if False:` passerebbe. Che "
    "funzionino lo dicono le prove di fase83, fase160 e fase131",
    "la copertura conta i PASSI del modello (ogni strada e' un passo a se'), non i rami di un "
    "IF dentro un passo (per esempio Restituisci con o senza il blocco sulla carta)",
    "la casella scade quando cambiano i moduli del blocco, non quando cambiano il modello o "
    "questo esame: a quelli pensa il job qualita, che li rifa' a ogni unione (e il gate lo "
    "aspetta)",
    "TypeOK (i valori ammessi di ogni variabile) non ha una variante che la faccia fallire",
    "il tetto Limite (bonifici fino a 2x, rimborsi fino a 3x il prezzo) taglia solo stati che "
    "violano gia' SoldiNostri: TLC si ferma prima",
)

_RE_DISTINTI = re.compile(r"(\d+) distinct states found")
_RE_VIOLATA = re.compile(r"^Error: Invariant (\w+) is violated\.", re.M)
_RE_STATO = re.compile(r"^State (\d+):", re.M)
_RE_COPERTURA = re.compile(r"^<(\w+) line \d+, col \d+ to line \d+, col \d+ of module Soldi>: "
                           r"(\d+):(\d+)\s*$", re.M)


def testo_casella():
    """Il testo della casella DAL PIANO, cercato per contenuto e preteso UNICO."""
    condizioni = BLOCCHI[BLOCCO_SOLDI - 1]["finito_quando"]
    trovate = [" ".join(str(c).split()) for c in condizioni if SEGNALE in " ".join(str(c).split())]
    if len(trovate) != 1:
        raise ValueError("nel blocco %d le caselle che nominano %r sono %d, non 1: il piano e' "
                         "cambiato e questo esame non sa piu' a cosa punta"
                         % (BLOCCO_SOLDI, SEGNALE, len(trovate)))
    return trovate[0]


def difetti_del_modello(testo):
    """I valori di DIFETTO che il modello conosce (`DIFETTI == {...}`), letti dal file."""
    m = re.search(r"^DIFETTI\s*==\s*\{(.*?)\}", testo, re.M | re.S)
    return set(re.findall(r'"(\w+)"', m.group(1))) if m else set()


def definizioni_del_modello(testo):
    """I nomi definiti al margine sinistro del modello (`Nome ==` o `Nome(x) ==`)."""
    return set(re.findall(r"^(\w+)(?:\([^)]*\))?\s*==", testo, re.M))


_SALTATI = (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
            tokenize.ENDMARKER)


@functools.lru_cache(maxsize=8)
def _analizza(sorgente):
    """(albero, gettoni) di un file, calcolati UNA volta: le ancore ne leggono tante funzioni
    (code-review, 23/11: diciassette analisi di fase83_server.py per giro). None se non si
    legge."""
    try:
        return ast.parse(sorgente), tuple(tokenize.generate_tokens(io.StringIO(sorgente).readline))
    except (SyntaxError, tokenize.TokenError, ValueError):
        return None


def _gettoni_del_frammento(frammento):
    """I gettoni di un pezzo di codice (anche con una parentesi lasciata aperta)."""
    fuori = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(str(frammento)).readline):
            if tok.type not in _SALTATI:
                fuori.append(tok.string)
    except (tokenize.TokenError, IndentationError):
        pass
    return fuori


def _codice_eseguibile(sorgente, funzione):
    """I gettoni della funzione `funzione` senza commenti, docstring e funzioni o classi
    annidate (il loro codice non gira quando gira lei), o None se nel file non c'e' UNA sola
    funzione con quel nome."""
    analisi = _analizza(sorgente)
    if analisi is None:
        return None
    albero, gettoni = analisi
    nodi = [n for n in ast.walk(albero)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == funzione]
    if len(nodi) != 1:
        return None
    nodo = nodi[0]
    fuori = []          # tratti (inizio, fine) da saltare: la docstring e le definizioni annidate
    if (nodo.body and isinstance(nodo.body[0], ast.Expr)
            and isinstance(getattr(nodo.body[0], "value", None), ast.Constant)
            and isinstance(nodo.body[0].value.value, str)):
        d = nodo.body[0]          # anche fatta di piu' stringhe adiacenti: si salta tutta
        fuori.append(((d.lineno, d.col_offset), (d.end_lineno, d.end_col_offset)))
    for n in ast.walk(nodo):
        if n is not nodo and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                            ast.ClassDef)):
            inizio = min([n.lineno] + [x.lineno for x in getattr(n, "decorator_list", [])])
            fuori.append(((inizio, 0), (n.end_lineno, n.end_col_offset)))
    pezzi = []
    for tok in gettoni:
        if not (nodo.lineno <= tok.start[0] <= nodo.end_lineno) or tok.type in _SALTATI:
            continue
        if any(a <= tok.start and tok.end <= b for a, b in fuori):
            continue
        pezzi.append(tok.string)
    return pezzi


def ancora_presente(sorgente, funzione, frammento):
    """True se `frammento` sta UNA volta sola nel codice ESEGUIBILE di `funzione`, parola per
    parola (S6: un commento, la docstring o una funzione annidata non bastano; spazi e a capo
    non contano; `xself._f(...)` non e' `self._f(...)`) e non dopo un `not`, che la
    rovescerebbe (silent-failure-hunter, 23/11). Due volte e' un'ancora ambigua e conta come
    mancante: tolta la guardia vera, l'altra copia la terrebbe trovata (successo il 23/11 nel
    rilascio automatico, visto dalla differential-review)."""
    codice = _codice_eseguibile(sorgente, funzione)
    voluto = _gettoni_del_frammento(frammento)
    if not codice or not voluto:
        return False
    n = len(voluto)
    dove = [i for i in range(len(codice) - n + 1) if codice[i:i + n] == voluto]
    return len(dove) == 1 and not (dove[0] > 0 and codice[dove[0] - 1] == "not")


def ancore_mancanti():
    """[(difetto, file, funzione, frammento)] delle guardie che il codice non ha piu'."""
    mancanti, letti = [], {}
    for difetto, (_regola, ancore) in sorted(VARIANTI.items()):
        for file, funzione, frammento in ancore:
            if file not in letti:
                try:
                    with io.open(os.path.join(RADICE, file), encoding="utf-8") as f:
                        letti[file] = f.read()
                except (OSError, ValueError):   # anche un byte non UTF-8 (code-review, 23/11)
                    letti[file] = ""
            if not ancora_presente(letti[file], funzione, frammento):
                mancanti.append((difetto, file, funzione, frammento))
    return mancanti


def passo_ci_bloccante(testo_ci):
    """(ok, dettaglio): il job JOB_CI esegue PASSO_CI ESATTAMENTE, gli dice dov'e' TLC, e
    niente ne spegne l'esito. Le stesse regole di `esame_mypy.passo_ci_bloccante` (cinque modi
    di spegnere un passo trovati dal cacciatore di errori silenziosi il 22/11), piu' il jar."""
    try:
        import yaml
    except Exception as e:
        return False, "PyYAML non si importa: il file della CI non si puo' leggere (%s)" % e
    try:
        doc = yaml.safe_load(testo_ci)
    except Exception as e:
        return False, "ci.yml illeggibile come YAML: %s" % e
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    if not isinstance(jobs, dict) or not isinstance(jobs.get(JOB_CI), dict):
        return False, "il job %r non c'e' in ci.yml" % JOB_CI
    job = jobs[JOB_CI]
    for chiave in ("if", "continue-on-error"):
        if chiave in job:
            return False, "il job %r ha %r: %r" % (JOB_CI, chiave, job[chiave])
    passi = [s for s in (job.get("steps") or [])
             if isinstance(s, dict) and PASSO_CI in str(s.get("run", ""))]
    if len(passi) != 1:
        return False, "il job %r esegue %r %d volte, non una" % (JOB_CI, PASSO_CI, len(passi))
    passo = passi[0]
    comando = str(passo.get("run", "")).strip()
    if comando != PASSO_CI:
        return False, "il comando del passo dev'essere esattamente %r, e' %r" % (PASSO_CI, comando)
    for chiave in ("if", "continue-on-error", "shell", "working-directory"):
        if chiave in passo:
            return False, "il passo ha %r: %r" % (chiave, passo[chiave])
    if not str((passo.get("env") or {}).get("TLA2TOOLS_JAR") or "").strip():
        return False, "il passo non dice dov'e' TLC (env TLA2TOOLS_JAR)"
    gate = jobs.get("gate")
    needs = gate.get("needs") if isinstance(gate, dict) else None
    if isinstance(needs, str):
        needs = [needs]
    if not isinstance(needs, list) or JOB_CI not in needs:
        return False, "il job %r non e' fra quelli che il gate aspetta" % JOB_CI
    return True, "%s esegue %r, bloccante, aspettato dal gate" % (JOB_CI, PASSO_CI)


def trova_jar():
    """Il jar di TLC: TLA2TOOLS_JAR (la CI lo scarica li'), altrimenti quello del PC."""
    scelto = os.environ.get("TLA2TOOLS_JAR", "").strip()
    if scelto:
        # assoluto: TLC parte in una cartella temporanea, e un percorso relativo misurato qui
        # non sarebbe il jar che TLC carica (silent-failure-hunter, 23/11)
        return os.path.abspath(os.path.expanduser(scelto))
    return os.path.join(os.path.expanduser("~"), "strumenti_verifica", "tla", "tla2tools.jar")


def trova_java():
    """Java: JAVA_HOME, poi il PATH, poi il JDK di strumenti_verifica sul PC."""
    nome = "java.exe" if os.name == "nt" else "java"
    casa = os.environ.get("JAVA_HOME", "").strip()
    if casa and os.path.isfile(os.path.join(casa, "bin", nome)):
        return os.path.join(casa, "bin", nome)
    dal_path = shutil.which("java")
    if dal_path:
        return dal_path
    trovati = sorted(glob.glob(os.path.join(os.path.expanduser("~"), "strumenti_verifica",
                                            "jdk*", "*", "bin", nome)))
    return trovati[-1] if trovati else ""


def _sha256(percorso):
    h = hashlib.sha256()
    with open(percorso, "rb") as f:
        for blocco in iter(lambda: f.read(1 << 20), b""):
            h.update(blocco)
    return h.hexdigest()


def versione_java(java):
    """La versione principale di Java (21, 17, ...) o 0 se non si legge."""
    try:
        p = subprocess.run([java, "-version"], capture_output=True, text=True,  # nosec B603 - java trovato da trova_java, argomenti fissi  # noqa: S603
                           encoding="utf-8", errors="replace", timeout=60)
    except Exception:
        return 0
    m = re.search(r'version "(\d+)(?:\.(\d+))?', (p.stderr or "") + (p.stdout or ""))
    if not m:
        return 0
    principale = int(m.group(1))
    return int(m.group(2) or 0) if principale == 1 else principale     # «1.8» = Java 8


def _configurazione(difetto, regole):
    return ("SPECIFICATION Spec\nCONSTANT DIFETTO = \"%s\"\nCONSTRAINT Limite\n"
            "INVARIANT %s\nCHECK_DEADLOCK FALSE\n" % (difetto, " ".join(regole)))


def esegui_tlc(difetto, regole, *, copertura=False, java=None, jar=None):
    """(uscita, testo) di UN giro di TLC sul modello, in una cartella temporanea (il modello vi
    si copia: TLC non scrive niente nel progetto). Un giro che scade o non parte torna come
    uscita None col suo motivo: non e' ne' «passato» ne' «trovato»."""
    java = java or trova_java()
    jar = jar or trova_jar()
    cartella = tempfile.mkdtemp(prefix="esame_tla_")
    try:
        shutil.copyfile(MODELLO, os.path.join(cartella, "Soldi.tla"))
        with io.open(os.path.join(cartella, "Giro.cfg"), "w", encoding="ascii") as f:
            f.write(_configurazione(difetto, regole))
        comando = [java, "-XX:+UseParallelGC", "-cp", jar, "tlc2.TLC", "-config", "Giro.cfg",
                   "-workers", "1", "-metadir", os.path.join(cartella, "stati"), "-cleanup"]
        if copertura:
            comando += ["-coverage", "1"]
        comando.append("Soldi.tla")
        try:
            p = subprocess.run(comando, cwd=cartella, capture_output=True, text=True,  # nosec B603 - java e jar controllati da precondizioni(), argomenti fissi  # noqa: S603
                               encoding="utf-8", errors="replace", timeout=TETTO_SEC)
        except subprocess.TimeoutExpired:
            return None, "TLC non ha finito in %d secondi" % TETTO_SEC
        except OSError as e:
            return None, "TLC non parte: %s" % e
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    finally:
        shutil.rmtree(cartella, ignore_errors=True)


def giudica_buono(uscita, testo):
    """(ok, motivo) del giro buono: uscita 0, «No error has been found», stati contati e OGNI
    passo di PASSI scattato almeno una volta (S7: un TLC che non ha girato non e' verde)."""
    if uscita != 0:
        trovata = _RE_VIOLATA.search(testo or "")
        return False, ("le regole vere NON passano: TLC uscito %s%s" % (
            uscita, ", violata %s" % trovata.group(1) if trovata else ""))
    if "Model checking completed. No error has been found." not in (testo or ""):
        return False, "TLC uscito 0 senza dire «No error has been found»: misura non valida"
    m = _RE_DISTINTI.search(testo)
    if not m or int(m.group(1)) <= 0:
        return False, "TLC non dice quanti stati ha esplorato (o zero): misura non valida"
    # «<Passo ...>: distinti:generati». Scattato = ha GENERATO stati: un passo che porta solo a
    # stati gia' visti da altri ha 0 distinti e scatta lo stesso (silent-failure-hunter, 23/11;
    # misurato: la somma dei primi numeri fa gli stati distinti, quella dei secondi i generati)
    scattati = {nome: int(gen) for nome, _distinti, gen in _RE_COPERTURA.findall(testo)}
    vuoti = [p for p in PASSI if scattati.get(p, 0) <= 0]
    if vuoti:
        return False, "passi del modello mai scattati (controllo vuoto): %s" % ", ".join(vuoti)
    return True, "%s stati distinti, %d passi tutti scattati" % (m.group(1), len(PASSI))


def giudica_variante(uscita, testo, attesa):
    """(ok, motivo) di una variante col difetto: uscita 12, la regola ATTESA violata, e una
    sequenza di almeno due stati (violata gia' allo stato iniziale non sarebbe il difetto)."""
    if uscita != 12:
        return False, "TLC uscito %s invece di 12: il difetto NON e' stato trovato" % uscita
    trovata = _RE_VIOLATA.search(testo or "")
    if not trovata or trovata.group(1) != attesa:
        return False, "violata %s invece di %s" % (trovata.group(1) if trovata else "niente",
                                                    attesa)
    passi = len(_RE_STATO.findall(testo))
    if passi < 2:
        return False, "violata con %d stati: non e' la sequenza del difetto" % passi
    return True, "%s violata in %d passi" % (attesa, passi)


def precondizioni():
    """(tutte_ok, righe). Un metro storto va scoperto dal metro (D18 punto 1)."""
    righe = []
    try:
        testo_casella()
        righe.append(("la casella si legge dal piano, una volta sola", True, SEGNALE))
    except Exception as e:
        righe.append(("la casella si legge dal piano, una volta sola", False, str(e)))
    try:
        with io.open(MODELLO, encoding="utf-8") as f:
            modello = f.read()
        noti = difetti_del_modello(modello)
        attesi = set(VARIANTI) | {"nessuno"}
        definite = definizioni_del_modello(modello)
        mancano = [n for n in REGOLE + PASSI if n not in definite]
        ok = noti == attesi and not mancano
        righe.append(("il modello e le varianti dell'esame coincidono", ok,
                      "%d varianti" % len(VARIANTI) if ok else
                      "nel modello e non qui: %s · qui e non nel modello: %s · nomi mancanti: %s"
                      % (sorted(noti - attesi), sorted(attesi - noti), mancano)))
    except Exception as e:
        righe.append(("il modello e le varianti dell'esame coincidono", False, str(e)))
    java = trova_java()
    v = versione_java(java) if java else 0
    righe.append(("Java si esegue", v >= JAVA_MINIMO,
                  "%s (Java %d)" % (java, v) if java else "java non trovato"))
    jar = trova_jar()
    try:
        impronta = _sha256(jar)
    except OSError as e:
        impronta = "illeggibile: %s" % e
    righe.append(("il jar di TLC e' quello inchiodato", impronta == JAR_SHA256,
                  "%s sha256 %s" % (jar, impronta[:16])))
    mancanti = ancore_mancanti()
    righe.append(("le guardie che il modello da' per scontate sono nel codice", not mancanti,
                  "%d ancore" % sum(len(a) for _r, a in VARIANTI.values()) if not mancanti else
                  "; ".join("%s: %s %s %r" % m for m in mancanti)))
    try:
        with io.open(CI, encoding="utf-8") as f:
            ok, dettaglio = passo_ci_bloccante(f.read())
    except Exception as e:
        ok, dettaglio = False, str(e)
    righe.append(("in CI il controllo BLOCCA", ok, dettaglio))
    return all(ok for _, ok, _ in righe), righe


def misura():
    """[(nome, ok, motivo)]: il giro buono, poi una variante per difetto."""
    esiti = []
    uscita, testo = esegui_tlc("nessuno", REGOLE, copertura=True)
    esiti.append(("le regole vere passano (DIFETTO = nessuno)",) + giudica_buono(uscita, testo))
    for difetto, (attesa, _ancore) in sorted(VARIANTI.items()):
        uscita, testo = esegui_tlc(difetto, (attesa,))
        esiti.append(("variante %s" % difetto,) + giudica_variante(uscita, testo, attesa))
    return esiti


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    tutte_ok, righe = precondizioni()
    print("=" * 86)
    print("🧮 ESAME TLA+ — «gli stati del denaro, ogni sequenza, in CI a ogni unione» (blocco SOLDI)")
    print("=" * 86)
    for nome, ok, dettaglio in righe:
        print("  %-6s %s  %s" % ("OK" if ok else "ROSSO", nome, dettaglio))
    # S7: senza casella, modello, Java o jar giusti non si misura niente e non si scrive niente,
    # nemmeno con --autoprova (girerebbe un altro TLC). Solo le ancore e la CI si misurano lo
    # stesso: rendono la casella falsa, col loro motivo.
    misurabili = ("le guardie che il modello da' per scontate sono nel codice",
                  "in CI il controllo BLOCCA")
    if not all(ok for nome, ok, _ in righe if nome not in misurabili):
        print("VERDETTO: ⛔ NON ESEGUIBILE — le precondizioni non reggono (S7): niente "
              "scritture, niente numeri")
        return 2
    if "--autoprova" in argv:
        esiti = misura()
        for nome, ok, motivo in esiti:
            print("  %-6s %s  %s" % ("OK" if ok else "ROSSO", nome, motivo))
        return 0 if all(ok for _n, ok, _m in esiti) else 1
    esiti = misura()
    for nome, ok, motivo in esiti:
        print("  %-6s %s  %s" % ("OK" if ok else "ROSSO", nome, motivo))
    motivi = ["%s: %s" % (n, m) for n, ok, m in esiti if not ok]
    motivi += ["%s: %s" % (n, d) for n, ok, d in righe if not ok]
    esito = not motivi
    denominatore = len(esiti)
    print("  casella %s  (denominatore %d giri di TLC: 1 buono + %d varianti)%s"
          % ("☑" if esito else "☐", denominatore, len(VARIANTI),
             ("\n     perche': %s" % "; ".join(motivi)) if motivi else ""))
    print("  ⛔ COSA NON GUARDA:")
    for r in NON_GUARDA:
        print("     · %s" % r)
    if "--scrivi" in argv:
        scheda.registra(testo_casella(), esito=esito, denominatore=denominatore,
                        comando=COMANDO, ordine=BLOCCO_SOLDI,
                        motivo="; ".join(motivi)[:900] or None)
        print("  🗂️  casella scritta%s" % ("" if esito else " (falsa, col motivo)"))
    print("VERDETTO: %s — %d giri di TLC, %d non come atteso"
          % ("✅" if esito else "⛔", denominatore, sum(1 for _n, ok, _m in esiti if not ok)))
    return 0 if esito else 1


if __name__ == "__main__":
    sys.exit(main())
