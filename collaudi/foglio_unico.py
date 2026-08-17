# -*- coding: utf-8 -*-
"""🧾 IL FOGLIO UNICO DEI CONTROLLI — «cosa devo fare prima di dire FATTO, e l'ho fatto?»

⛔ PERCHE' ESISTE (2026-08-17, ordine del fondatore)
==============================================================================
*«sono tanti e quelli dobbiamo farli per forza. Poi c'erano altri che sono scritti ma che non
usiamo piu', perche' sono ancora scritti? Tanta roba da eliminare. Bisogna fare un foglio
solo.»*

Aveva ragione, e si misura: quella domanda oggi risponde in **cinque posti** —
`CLAUDE.md` (divieti, sbagli, ferree, direttive, modi, collaudi) · `REGISTRO_INGEGNERIA.md`
(tecniche, piano, appendice) · `collaudi/piano.py` (blocchi e moduli) ·
`collaudi/prima_di_dire_fatto.py` (i controlli al commit) · e **fuori dal computer** (la
tabella della CI, Stripe vero, CodeQL). Chi apre una sessione nuova non li mette insieme, e
quello che non si mette insieme non si fa.

⛔⛔ E LA CURA NON E' UN RIASSUNTO. Un riassunto sarebbe la **sesta copia**, e invecchierebbe
come le altre cinque: e' successo il 2026-08-17 con la lista dei metodi AWS, che ha fatto
ragionare una sessione intera sul numero sbagliato. Qui non si ricopia **niente**: ogni voce
dice **chi possiede il fatto** e va a **misurarlo adesso**. Se il posto che lo possiede
cambia, questo foglio cambia con lui; se sparisce, questo foglio lo grida.

==============================================================================
COSA DICE LA RICERCA, e ha corretto l'istinto invece di confermarlo (D25)
==============================================================================
· **Beyer, Jones, Petoff, Murphy, «Site Reliability Engineering», O'Reilly 2016, cap. 27
  "Reliable Product Launches at Scale"** — Google la lista di lancio la tiene **curata a
  mano**, non generata, e il pericolo che nomina esplicitamente e' il **gonfiarsi**:
  *«there is a near-infinite number of questions to ask about any system, and it is easy for
  the checklist to grow to an unmanageable size»* — al punto che aggiungere una domanda
  richiedeva l'approvazione di un **vicepresidente**. Cioe': il valore sta nella POTATURA,
  non nella completezza. Da qui la scelta di tenere questo foglio a **nove voci**, e di non
  ripetere il contenuto dei posti che gia' lo stampano.
· **Gawande, «The Checklist Manifesto», 2009** — due forme: **READ-DO** (si fa leggendo) e
  **DO-CONFIRM** (si lavora a memoria, poi ci si ferma e si CONFERMA). E la regola sulla
  lunghezza: solo i **killer items**, all'incirca **5-9**, il limite della memoria di lavoro.
  Questo foglio e' un **DO-CONFIRM**: non insegna a lavorare, conferma prima di chiudere.
· **Documentazione generata dalla fonte** (Fern, «Generated vs manual docs», 2026 · ClickHelp,
  «Code-to-Docs», 2025) — una fonte di verita' per ogni tipo di fatto, e il resto **generato**;
  la deriva si combatte accorgendosi che la fonte e' cambiata. E' il meccanismo della voce 7.

⚠️ Limite dichiarato sulla lettura (D18 punto 3): il capitolo SRE e' stato letto alla fonte
(sre.google); di Gawande e delle fonti sulla documentazione ho letto **riassunti concordi**,
non i testi integrali. Sta scritto qui perche' *«lo dice il documento»* non e' *«misurato»*.

==============================================================================
COSA GARANTISCE, E COSA NO (D18 punto 3)
==============================================================================
GARANTISCE: ogni voce porta lo stato **misurato adesso**, e nessuna voce contiene una copia
del fatto -- solo il puntatore a chi lo possiede.
NON GARANTISCE: che tu abbia **fatto** il lavoro. Le cose che vivono fuori da questo computer
(la tabella della CI, un giudice non nostro, CodeQL) qui NON si misurano: escono `FUORI` col
comando esatto per andarle a leggere. `FUORI` non e' un verde -- e' un controllo che questo
computer non puo' fare (sbaglio S7).

USO:
    python collaudi/foglio_unico.py            # il foglio, misurato adesso
    python collaudi/foglio_unico.py --breve    # una riga per voce (lo usano i ganci)
Uscita 0 = niente di rosso. Uscita 1 = c'e' almeno una voce rossa.
"""
import io
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

QUI = os.path.dirname(os.path.abspath(__file__))
if QUI not in sys.path:
    sys.path.insert(0, QUI)

RADICE = os.path.dirname(QUI)

FATTO, ROSSO, FUORI, NON_ESEGUITO = "FATTO", "ROSSO", "FUORI", "NON ESEGUITO"
# ⛔ `APERTO` NON E' ROSSO, ED E' UNA SCELTA GIA' PAGATA. I lavori obbligatori in sospeso sono
# aperti per decisione del fondatore, non per un guasto: farli uscire rossi renderebbe questo
# foglio rosso ogni singolo giorno, e *un allarme che suona sempre viene spento* (regola
# ferrea 10). E' la stessa ragione, scritta nero su bianco, per cui `regole_avvio.py` non li
# ha mai fatti diventare un test rosso: «quattro rossi permanenti al terzo giorno non li
# guarda piu' nessuno, e si sarebbe peggiorata la situazione».
APERTO = "APERTO"
SEGNO = {FATTO: "✅ FATTO", ROSSO: "🔴 ROSSO", FUORI: "🛰️  FUORI",
         APERTO: "⏳ APERTO", NON_ESEGUITO: "⚠️  NON ESEGUITO"}

# I cinque documenti ufficiali (REGOLA ZERO 1). Si leggono, non si giudicano a memoria.
DOCUMENTI = ("CLAUDE.md", "README.md", "REGISTRO_INGEGNERIA.md", "RIPRENDI_QUI.md",
             "DEPLOY.md")


def _leggi(percorso):
    try:
        with io.open(percorso, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


# ══════════════════════════════════════════════════════════════════════════════════════
#  LA VOCE 7 — I NUMERI CHE UNA MACCHINA PRODUCE NON SI SCRIVONO A MANO
# ══════════════════════════════════════════════════════════════════════════════════════
# ⛔ IL FATTO CHE L'HA GENERATA, misurato il 2026-08-17. «63 moduli morti su 151» era scritto
# in SETTE punti fra documenti e strumenti. Era **sbagliato** -- sono 59 -- perche' lo
# strumento partiva da un ingresso su tre. E non era un numero decorativo:
# `REGISTRO_INGEGNERIA.md` lo usava come ISTRUZIONE (*«prima di ogni blocco si guarda se il
# modulo e' acceso: 63 su 151 non sono raggiungibili»*), e la classifica «rischio x cecita'»
# dei moduli dei soldi ci si appoggiava. Si sceglieva **su cosa lavorare** con una cifra falsa.
#
# 💡 LA REGOLA CHE NE ESCE, e vale oltre questo caso: *un numero che descrive lo stato della
# macchina non si SCRIVE, si PRODUCE quando lo si legge.* Scritto, invecchia in silenzio; e un
# numero invecchiato che serve a DECIDERE e' peggio di nessun numero.
#
# ⛔ LA LISTA E' CHIUSA E CURATA A MANO, ED E' UNA SCELTA. Google (SRE, cap. 27) tiene corta
# la lista di lancio perche' *«e' facile che cresca fino a diventare ingestibile»*. Qui dentro
# entrano solo i numeri che (a) una macchina sa produrre e (b) NON hanno gia' una guardia.
# Il totale degli obblighi, il totale delle tecniche e il conto della suite hanno gia' la
# loro: rimetterli qui sarebbe una seconda copia, cioe' la malattia da curare.
#
# ⛔ E LA DATA ESENTA, PERCHE' D22 LO DICE. Una riga che porta una data (`2026-08-09`) o dice
# «misurato il» e' una misura STORICA col suo appoggio, non un'affermazione sullo stato di
# oggi: quella si tiene. Un numero nudo no.
DATA_O_MISURA = re.compile(r"20\d\d-\d\d-\d\d|misurat[oaie]\s+il|Misurato il")

# ⛔ IL TEMA DELLA RIGA, e non e' un dettaglio: senza, questo controllo e' una macchina da
# FALSI ALLARMI. Al primo giro (2026-08-17) ne ha prodotti nove su trenta: «3 morti» erano
# punti di mutazione, «167» veniva da `fase167`, «15» dalla parola «raggiungibilita'» seguita
# da un numero qualsiasi. Un falso allarme e' un difetto quanto un allarme mancato (regola
# ferrea 10), e uno strumento che grida a vuoto viene spento -- quindi si pretende che la riga
# stia davvero parlando di MODULI, non che contenga per caso la parola.
PARLA_DI_MODULI = re.compile(r"modul|raggiungibil", re.IGNORECASE)

# ⛔ E GLI SCHEMI GUARDANO IN UNA DIREZIONE SOLA: il numero DAVANTI alla parola («63 morti»,
# «88 raggiungibili»). La forma all'indietro («morti: fase35...») pescava il numero del nome
# di un modulo. Un metro che sbaglia si stringe, non si allarga.
NUMERI_PRODOTTI = (
    {
        "nome": "moduli che la produzione RAGGIUNGE",
        "lo_produce": "python collaudi/raggiungibilita.py",
        "schemi": (r"(\d+)\s*(?:\*\*\s*)?(?:moduli\s+)?raggiungibili",),
    },
    {
        "nome": "moduli che la produzione NON raggiunge (codice morto)",
        "lo_produce": "python collaudi/raggiungibilita.py",
        "schemi": (r"(\d+)\s*(?:\*\*\s*)?(?:moduli\s+)?morti\b",),
    },
)


def misura_i_numeri(radice=RADICE):
    """(valori, guasto): i numeri prodotti ADESSO dagli strumenti che li possiedono."""
    try:
        import raggiungibilita
        vivi, morti, _tutti = raggiungibilita.cammina(radice)
    except Exception as errore:                       # noqa: BLE001 — lo DICE, non tace
        return (None, "`collaudi/raggiungibilita.py` non risponde (%s: %s): senza di lui "
                      "non so quali numeri dovrebbero essere veri"
                      % (errore.__class__.__name__, errore))
    return ({"moduli che la produzione RAGGIUNGE": len(vivi),
             "moduli che la produzione NON raggiunge (codice morto)": len(morti)}, None)


def numeri_scritti_a_mano(radice=RADICE):
    """Le righe dei 5 documenti che scrivono un numero che una macchina produce, e lo
    sbagliano. Ritorna `(colpevoli, guasto)`.

    ⚠️ Un falso allarme e' un difetto quanto un allarme mancato (regola ferrea 10): qui e'
    colpevole SOLO la riga che scrive un numero DIVERSO da quello misurato adesso, e che non
    porta una data. Una riga che scrive il numero giusto e' ridondante, non falsa: si lascia.
    """
    valori, guasto = misura_i_numeri(radice)
    if guasto:
        return ([], guasto)
    colpevoli = []
    for nome in DOCUMENTI:
        testo = _leggi(os.path.join(radice, nome))
        if testo is None:
            continue
        for numero_riga, riga in enumerate(testo.splitlines(), 1):
            if DATA_O_MISURA.search(riga):
                continue                              # misura storica: la porta con se'
            if not PARLA_DI_MODULI.search(riga):
                continue                              # non sta parlando di moduli
            for voce in NUMERI_PRODOTTI:
                vero = valori[voce["nome"]]
                for schema in voce["schemi"]:
                    for trovato in re.findall(schema, riga):
                        if int(trovato) != vero:
                            colpevoli.append(
                                "%s:%d scrive %s dove la macchina misura %d (%s) — «%s»"
                                % (nome, numero_riga, trovato, vero, voce["nome"],
                                   riga.strip()[:80]))
    return (sorted(set(colpevoli)), None)


# ══════════════════════════════════════════════════════════════════════════════════════
#  LE NOVE VOCI — ognuna dice CHI possiede il fatto, e va a misurarlo
# ══════════════════════════════════════════════════════════════════════════════════════
def _v1_divieti(radice):
    import regole_avvio as ra
    mancanti = ra.titoli_mancanti()
    if mancanti:
        return (ROSSO, "le sezioni %s non si trovano in CLAUDE.md: il promemoria che stampa "
                       "i divieti a ogni avvio sta leggendo spazzatura" % ", ".join(mancanti))
    quanti = ra.conta_regole()["blocco"]
    mute = ra.senza_verifica()
    if not quanti:
        return (ROSSO, "IL BLOCCO non c'e' piu' in CLAUDE.md")
    if mute:
        return (ROSSO, "%d divieti, ma queste regole non dicono come si verificano: %s"
                % (quanti, ", ".join(mute)))
    return (FATTO, "%d divieti in CLAUDE.md, ognuno col suo «si verifica». Li stampa per "
                   "intero `regole_avvio.py` a ogni avvio e `prima_di_dire_fatto.py` al "
                   "commit: qui NON si ricopiano" % quanti)


def _v2_batteria(radice):
    import prima_di_dire_fatto as pf
    righe = pf.batteria_dal_regolamento(radice)
    if not righe:
        return (ROSSO, "la tabella dei 10 collaudi non si trova in CLAUDE.md: D24 non ha "
                       "piu' niente da far rileggere")
    return (FATTO, "%d collaudi nella tabella di CLAUDE.md. ⚠️ Che tu abbia scritto l'esito "
                   "(o il motivo) per OGNUNO questo foglio non lo puo' vedere: e' la parte "
                   "che resta a chi lavora" % len(righe))


def _v3_scopo(radice):
    import prima_di_lanciare as pv
    dichiarati = pv.leggi_scopo()
    if not dichiarati:
        return (ROSSO, "nessuno scopo dichiarato: non si sa cosa avevi promesso di toccare, "
                       "quindi nessuno puo' dire se ti sei allargato (regola ferrea 15).\n"
                       "        python collaudi/prima_di_lanciare.py --scopo <file...>")
    return (FATTO, "%d file dichiarati; il confronto con quelli toccati lo fa il controllo 9 "
                   "del pre-fatto, dentro il gancio `pre-commit`" % len(dichiarati))


def _v4_ganci(radice):
    """⛔ COSTRUITO != COLLEGATO (appendice 23). Un controllo che nessuno esegue nel momento
    della decisione misura se stesso, non il lavoro."""
    import subprocess
    try:
        dove = subprocess.run(["git", "config", "core.hooksPath"], cwd=radice,
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception as errore:                       # noqa: BLE001
        return (NON_ESEGUITO, "git non risponde (%s): non so dove stanno i ganci" % errore)
    if not dove:
        return (ROSSO, "`core.hooksPath` non e' impostato: i ganci di questo repository non "
                       "girano, e il pre-fatto e' costruito ma scollegato")
    attesi = {"pre-commit": "prima_di_dire_fatto", "commit-msg": "prima_di_dire_fatto"}
    guasti = []
    for gancio, chiamata in attesi.items():
        percorso = os.path.join(radice, dove.replace("/", os.sep), gancio)
        testo = _leggi(percorso)
        if testo is None:
            guasti.append("%s non esiste" % gancio)
        elif chiamata not in testo:
            guasti.append("%s non chiama %s" % (gancio, chiamata))
    if guasti:
        return (ROSSO, "i controlli del commit sono scollegati: %s" % ", ".join(guasti))
    return (FATTO, "%d ganci in `%s`, tutti e due chiamano `prima_di_dire_fatto.py`: i "
                   "controlli girano al momento della decisione, non mezz'ora dopo"
            % (len(attesi), dove))


def _v5_piano_soldi(radice):
    import prima_di_dire_fatto as pf
    stato, dettaglio = pf.controllo_10_piano_dei_soldi(radice=radice)
    return ({pf.OK: FATTO, pf.ROSSO: ROSSO}.get(stato, NON_ESEGUITO), dettaglio)


def _v6_piano_e_tecniche(radice):
    import regole_avvio as ra
    guasti = []
    if not ra.leggi_piano(radice):
        guasti.append("il blocco PIANO-INIZIO/PIANO-FINE non c'e' piu' in "
                      "REGISTRO_INGEGNERIA.md")
    blocco = ra.leggi_tecniche(radice)
    if not blocco:
        guasti.append("il blocco TECNICHE-INIZIO/TECNICHE-FINE non c'e' piu'")
    else:
        contate, dichiarate = ra.conta_tecniche(blocco)
        if dichiarate is None:
            guasti.append("il blocco delle tecniche non dichiara `TOTALE DICHIARATO: N`")
        elif contate != dichiarate:
            guasti.append("le tecniche dichiarano %d e sono %d" % (dichiarate, contate))
    try:
        import piano as _piano
        problemi = _piano.contraddizioni()
    except Exception as errore:                       # noqa: BLE001
        return (NON_ESEGUITO, "collaudi/piano.py non risponde (%s)" % errore)
    guasti += list(problemi)
    if guasti:
        return (ROSSO, "; ".join(guasti))
    return (FATTO, "il piano, le tecniche e i dieci blocchi dicono il vero su se stessi "
                   "(letti da REGISTRO_INGEGNERIA.md e collaudi/piano.py, non ricopiati)")


def _v7_numeri(radice):
    colpevoli, guasto = numeri_scritti_a_mano(radice)
    if guasto:
        return (NON_ESEGUITO, guasto)
    if colpevoli:
        return (ROSSO, "un numero che descrive lo stato della macchina e' scritto a mano nei "
                       "documenti, e non e' piu' vero. Si toglie e si mette il comando che "
                       "lo produce.\n        " + "\n        ".join(colpevoli))
    return (FATTO, "%d numeri sorvegliati (lista chiusa e curata: ci entra solo cio' che una "
                   "macchina produce e che non ha gia' una guardia), nessun documento li "
                   "scrive sbagliati" % len(NUMERI_PRODOTTI))


# ══════════════════════════════════════════════════════════════════════════════════════
#  LA VOCE 10 — QUANTE GUARDIE SPEGNE, IN SILENZIO, LA SHELL DA CUI STAI LANCIANDO
# ══════════════════════════════════════════════════════════════════════════════════════
# ⛔ E' LO SBAGLIO S11, RIMASTO APERTO PER SETTE GIORNI. Il 2026-08-10 la suite raccoglieva
# 5490 test e ne eseguiva 5485: cinque spariti. La causa e' che `openssl` non sta nel PATH di
# PowerShell (in Git Bash si', da qui le due risposte opposte alla stessa domanda), e le
# guardie sul RIPRISTINO dei salvataggi si mettono da parte in blocco.
#
# ⛔ E IL MODO IN CUI SPARISCONO E' LA PARTE CATTIVA. Il salto e' su `setUpClass`, quindi
# `unittest` stampa **UN** salto -- senza il nome della classe -- e i suoi metodi **non
# entrano nel totale `Ran`**. Cioe': cinque guardie sui salvataggi non girano, e il rapporto
# finale non ha nessun modo di dirtelo. E' D23 punto 3 vista dal lato in cui si rompe.
#
# 💡 PERCHE' STA QUI E NON IN UN CONTROLLO A SE'. Fino a oggi quel numero lo dichiaravo **io**,
# a mano, a ogni giro -- cinque volte in un giorno solo (2026-08-17). Una dichiarazione
# affidata a chi scrive e' precisamente cio' che questo progetto ha imparato a non fare: il
# conto lo produce una macchina, leggendo i metodi dal file col parser di Python. Un commento
# o una docstring non possono soddisfarlo (sbaglio S6).
GUARDIE_CHE_DIPENDONO_DAL_PATH = (
    {
        "file": "test_backup_completo.py",
        "classe": "TestRipristinoAPezziNonPassa",
        "attrezzi": ("bash", "openssl"),
        "cosa_difende": "che un salvataggio cifrato si RIMETTA INSIEME e il database torni "
                        "leggibile: un backup che nessuno ha mai riaperto non e' un backup",
    },
)


def _metodi_di_prova(radice, nome_file, nome_classe):
    """Quanti `def test_*` ha quella classe. Contati col parser di Python, non col `grep`:
    un commento non produce un nodo dell'albero. `None` se il file o la classe non ci sono --
    e chi chiama lo DICE, invece di scrivere zero (S1: il vuoto non e' una misura)."""
    import ast
    testo = _leggi(os.path.join(radice, nome_file))
    if testo is None:
        return None
    try:
        albero = ast.parse(testo)
    except SyntaxError:
        return None
    for nodo in ast.walk(albero):
        if isinstance(nodo, ast.ClassDef) and nodo.name == nome_classe:
            return sum(1 for f in nodo.body
                       if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
                       and f.name.startswith("test"))
    return None


def guardie_spente_dalla_shell(radice=RADICE):
    """(spente, dettagli, rotte): quante guardie questa shell sta spegnendo in silenzio.

    ⛔ SI GUARDA IL PATH DI QUESTA SHELL, non «di solito». La stessa domanda da Git Bash e da
    PowerShell da' due risposte opposte, e la misura che conta e' quella della shell che
    lancera' la suite (sbaglio S11).
    """
    import shutil as _sh
    spente, dettagli, rotte = 0, [], []
    for v in GUARDIE_CHE_DIPENDONO_DAL_PATH:
        quanti = _metodi_di_prova(radice, v["file"], v["classe"])
        if quanti is None:
            rotte.append("%s::%s non esiste piu': questa voce non sta misurando niente"
                         % (v["file"], v["classe"]))
            continue
        mancanti = [a for a in v["attrezzi"] if _sh.which(a) is None]
        if not mancanti:
            continue
        spente += quanti
        dettagli.append("%s::%s — %d guardie, spente perche' in questa shell manca %s. "
                        "Difendono: %s"
                        % (v["file"], v["classe"], quanti, " e ".join(mancanti),
                           v["cosa_difende"]))
    return spente, dettagli, rotte


def _v10_ambiente(radice):
    spente, dettagli, rotte = guardie_spente_dalla_shell(radice)
    if rotte:
        return (ROSSO, "questa voce punta a guardie che non esistono piu', quindi il conto "
                       "che stampa e' finto: " + " · ".join(rotte))
    if not spente:
        return (FATTO, "nessuna guardia si spegne: in questa shell ci sono tutti gli attrezzi "
                       "di sistema che servono (%d gruppi sorvegliati)"
                % len(GUARDIE_CHE_DIPENDONO_DAL_PATH))
    return (APERTO,
            "⚠️  %d GUARDIE NON GIRERANNO, e `unittest` te lo dira' come UN SOLO salto senza "
            "nome — i loro metodi non entrano nemmeno nel totale `Ran`.\n        %s\n"
            "        ⛔ Non e' un guasto del prodotto: e' questa shell. In CI (Linux) girano. "
            "Ma il conto adesso lo produce una macchina, non chi scrive il rapporto (S11)."
            % (spente, "\n        ".join(dettagli)))


def _v8_lavori(radice):
    import regole_avvio as ra
    conti = {}
    for v in ra.LAVORI_IN_SOSPESO:
        esito = ra.stato_del_lavoro(v, radice)[0]
        conti[esito] = conti.get(esito, 0) + 1
    aperti = len(ra.LAVORI_IN_SOSPESO) - conti.get("FATTO", 0)
    riga = " · ".join("%s %d" % (k, n) for k, n in sorted(conti.items()))
    senza_prova = ra.lavori_senza_prova() + ra.lavori_senza_criterio()
    # ⛔ ROSSO SOLO SE UNA VOCE NON SI PUO' CONTROLLARE. Che un lavoro sia ancora aperto e' una
    # decisione del fondatore, non un guasto: e' `APERTO`. Che una voce non dica QUANDO e'
    # finita, o CHI lo va a vedere, e' un desiderio travestito da lavoro -- e quello e' rosso.
    if senza_prova:
        return (ROSSO, "questi lavori non dicono quando sono finiti o chi lo va a vedere "
                       "(sono desideri, non lavori): %s" % ", ".join(sorted(set(senza_prova))))
    if aperti:
        return (APERTO, "%d lavori obbligatori ancora aperti (%s) — aperti per decisione del "
                        "fondatore, non per un guasto. L'elenco per esteso, col «fatto "
                        "quando» e lo stato misurato di ognuno, lo stampa `regole_avvio.py` "
                        "all'avvio: qui NON si ricopia" % (aperti, riga))
    return (FATTO, "tutti chiusi (%s)" % riga)


def _v9_fuori(radice):
    """⛔ QUESTA VOCE NON DIVENTA MAI VERDE, E NON E' UN DIFETTO.

    Sono le tre cose che questo computer NON puo' misurare. Farle uscire verdi sarebbe il
    verde peggiore di tutti: quello che non ha guardato niente. Escono `FUORI` col comando
    esatto -- perche' «immagino sia verde» e' precisamente cio' che la regola ferrea 8 vieta.
    """
    return (FUORI,
            "questo computer non le puo' vedere. Si vanno a leggere, mai a indovinare:\n"
            "        · LA TABELLA DELLA CI (regola ferrea 8) — api.github.com/repos/<repo>/"
            "commits/<sha>/check-runs, e si guarda `conclusion` di OGNI job\n"
            "        · IL GIUDICE ESTERNO (collaudo 7) — uno strumento NON nostro: "
            "`collaudi/e2e_rimborso_stripe.py`, `openssl`, `curl` sul sito vero\n"
            "        · CODEQL — la sua tabella sta nella stessa risposta della CI; i rilievi "
            "si triano uno per uno, col motivo")


VOCI = (
    ("i SEI DIVIETI, e ognuno dice come si verifica", "CLAUDE.md", _v1_divieti),
    ("la BATTERIA dei 10 collaudi (D24)", "CLAUDE.md", _v2_batteria),
    ("lo SCOPO dichiarato prima di aprire i file (ferrea 15)",
     "collaudi/prima_di_lanciare.py", _v3_scopo),
    ("i controlli del commit sono COLLEGATI ai ganci", "deploy/hooks/", _v4_ganci),
    ("il PIANO DEI SOLDI non si contraddice", "collaudi/piano_dei_soldi.py", _v5_piano_soldi),
    ("il piano, le tecniche e i 10 blocchi dicono il vero su se stessi",
     "REGISTRO_INGEGNERIA.md + collaudi/piano.py", _v6_piano_e_tecniche),
    ("i NUMERI della macchina non sono scritti a mano nei documenti",
     "gli strumenti che li producono", _v7_numeri),
    ("i LAVORI OBBLIGATORI in sospeso", "collaudi/regole_avvio.py", _v8_lavori),
    ("FUORI DAL COMPUTER: la CI · il giudice esterno · CodeQL",
     "GitHub, Stripe — non questo disco", _v9_fuori),
    ("quante guardie SPEGNE la shell da cui lanci", "il PATH di questa shell", _v10_ambiente),
)

# ⛔ DIECI, E LA DECIMA E' L'ULTIMA CHE ENTRA DA SOLA. Gawande (2009) mette il limite utile a
# 5-9 voci -- oltre, la lista smette di essere un promemoria e diventa un modulo da compilare.
# Google (SRE, cap. 27) e' arrivato a chiedere l'approvazione di un VICEPRESIDENTE per
# aggiungere una domanda alla lista di lancio, proprio perche' *«e' facile che cresca fino a
# diventare ingestibile»*. Qui la regola equivalente e' questa: **l'undicesima voce entra solo
# col via del fondatore**, e chi la propone deve prima dire quale delle dieci esce.


def giro(radice=RADICE):
    """(numero, titolo, possiede, stato, dettaglio) per ogni voce. Una voce che esplode non
    ferma il giro: diventa `NON ESEGUITO` e lo dice (S7)."""
    esiti = []
    for numero, (titolo, possiede, funzione) in enumerate(VOCI, 1):
        try:
            stato, dettaglio = funzione(radice)
        except Exception as errore:                   # noqa: BLE001
            stato = NON_ESEGUITO
            dettaglio = ("la misura e' esplosa (%s: %s) — non e' un verde, e' un controllo "
                         "che non ha guardato" % (errore.__class__.__name__, errore))
        esiti.append((numero, titolo, possiede, stato, dettaglio))
    return esiti


def stampa(esiti, breve=False):
    print("=" * 86)
    print("🧾 IL FOGLIO UNICO DEI CONTROLLI — %d voci, stato MISURATO ADESSO" % len(esiti))
    print("   Non e' una copia: ogni voce dice CHI possiede il fatto, e ci va a leggere.")
    print("=" * 86)
    for numero, titolo, possiede, stato, dettaglio in esiti:
        print("  %d. %-56s %s" % (numero, titolo[:56], SEGNO.get(stato, stato)))
        if breve:
            continue
        print("     possiede il fatto: %s" % possiede)
        print("     %s" % dettaglio)
        print()
    rossi = [e for e in esiti if e[3] == ROSSO]
    fuori = [e for e in esiti if e[3] == FUORI]
    aperti = [e for e in esiti if e[3] == APERTO]
    non_eseguiti = [e for e in esiti if e[3] == NON_ESEGUITO]
    print("-" * 86)
    print("  DENOMINATORE: %d voci · %d rosse · %d aperte · %d non eseguite · %d che questo "
          "computer NON puo' misurare"
          % (len(esiti), len(rossi), len(aperti), len(non_eseguiti), len(fuori)))
    print("  ⛔ `FUORI` non e' un verde: e' un controllo che va fatto altrove. «Immagino sia")
    print("     verde» e' esattamente cio' che la regola ferrea 8 vieta.")
    print("=" * 86)
    return 1 if rossi else 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    return stampa(giro(), breve="--breve" in argv)


if __name__ == "__main__":
    sys.exit(main())
