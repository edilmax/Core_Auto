# -*- coding: utf-8 -*-
"""LE REGOLE SI LEGGONO SEMPRE, PRIMA DI FARE QUALUNQUE COSA.

Lo esegue un hook `SessionStart` (vedi `.claude/settings.json`): la sua uscita entra nel
contesto della sessione PRIMA di ogni altra cosa, quindi non dipende da nessuno che si
ricordi di leggere.

PERCHE' ESISTE, e la storia conta perche' l'errore si e' ripetuto tre volte:
  · 2026-07-31 — ho violato la REGOLA FERREA 15 (una regola scritta da me) perche' stava
    nell'appendice invece che nel file che si ricarica sempre. La ricerca lo aveva perfino
    previsto: «la compattazione e' amnesia: sopravvive solo CLAUDE.md».
  · 2026-08-01 mattina — il conto diceva 74, ma altri obblighi stavano SOLO nella memoria di
    sessione, che NON viaggia col progetto: su un altro computer, o in CI, non esistevano.
  · 2026-08-01 sera — avevo mescolato in un unico numero le regole della RICERCA (pagate, con
    fonte e prova) e quelle nate dai nostri danni. Mescolare fa perdere di vista cio' che e'
    stato pagato.

COSA FA, e la terza cosa e' quella che impedisce all'errore di tornare:
  1. stampa la MAPPA degli obblighi, in DUE FAMIGLIE distinte;
  2. CONTA le regole nei file e le confronta con i numeri dichiarati: se divergono, GRIDA;
  3. controlla che OGNI regola dica **come si verifica**. Una regola che non si puo'
     controllare non e' una regola: e' un desiderio -- ed e' esattamente il tipo di regola
     che dava «tutto verde» e poi le sorprese.

Uscita 0 sempre: questo strumento INFORMA, non blocca. I divieti che fermano davvero sono
i `permissions.deny` di `.claude/settings.json`, che non dipendono dalla mia buona volonta'.
"""
import io
import os
import re
import sys

# La console di Windows (cp1252) non regge i simboli: senza questa riga lo strumento
# ESPLODE invece di stampare le regole -- e un hook che va in errore e' peggio di nessun
# hook. Stessa protezione gia' usata da `collaudi/mutazione_prodotto.py`.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLAUDE = os.path.join(RADICE, "CLAUDE.md")
REGISTRO = os.path.join(RADICE, "REGISTRO_INGEGNERIA.md")

# Le parole con cui una regola dichiara COME si controlla. Se non c'e' nessuna di queste,
# quella regola non e' verificabile -- e va segnalata, non lasciata passare.
SEGNI_DI_VERIFICA = ("Si verifica", "si verifica", "SI VERIFICA")


def _leggi(percorso):
    with io.open(percorso, encoding="utf-8", errors="replace") as f:
        return f.read()


def _confini(c, nome):
    """Dove comincia e dove finisce la RIGA DI TITOLO che contiene `nome`.

    ⛔ SI AGGANCIA AL TITOLO (`# ...`), NON ALLA PRESENZA DELLE PAROLE NEL TESTO.
    Il 2026-08-06 una direttiva nuova ha citato «REGOLA ZERO 3» nel proprio corpo: il taglio
    di prima prendeva l'ULTIMA occorrenza delle parole, quindi il confine di una sezione e'
    saltato in avanti di 300 righe e un conteggio e' sceso da 5 a 4. Se ne e' accorto il
    controllo dei totali -- ma un travaso fra due gruppi che lascia la somma invariata
    sarebbe passato in silenzio, ed e' il tipo di guasto peggiore.
    ⛔ E IL TAGLIO NON SI AGGANCIA A UN NUMERO. Prima diceva "LE 17 DIRETTIVE": il giorno in
    cui ne e' arrivata una diciottesima si sarebbe rotto -- e lo strumento che deve
    accorgersi degli errori di conteggio sarebbe stato il primo a sbagliarlo.
    """
    m = re.compile(r"^#+ .*" + re.escape(nome), re.M).search(c)
    return (m.start(), m.end()) if m else (None, None)


SEZIONI = ("REGOLA ZERO", "REGOLA FERREA", "DIRETTIVE DEL FONDATORE",
           "REGOLA DEI 10 COLLAUDI", "DIRETTIVA OPERATIVA")


def titoli_mancanti():
    """I titoli di sezione che il taglio NON trova. Senza questo, il metro storto non si
    accorge di esserlo.

    ⛔ `_confini` torna `(None, None)` quando un titolo non c'e', e in Python `c[:None]` e
    `c[None:x]` sono fette **legali**: nessuna eccezione, nessun rosso, e i conteggi
    verrebbero da confini di spazzatura mentre lo strumento stampa il suo bollino verde.
    Bastava rinominare un titolo. L'ha visto una revisione a contesto fresco il 2026-08-06,
    non un test -- ed e' D18 punto 1 («un metro storto va scoperto dal metro») violata proprio
    dal file che esiste per applicarla.
    """
    c = _leggi(CLAUDE)
    return [nome for nome in SEZIONI if _confini(c, nome) == (None, None)]


def _pezzi():
    """Le sezioni di CLAUDE.md, separate una volta sola: meno modi di sbagliare."""
    c = _leggi(CLAUDE)
    zero, ferrea = _confini(c, "REGOLA ZERO"), _confini(c, "REGOLA FERREA")
    direttive = _confini(c, "DIRETTIVE DEL FONDATORE")
    collaudi, finale = _confini(c, "REGOLA DEI 10 COLLAUDI"), _confini(c, "DIRETTIVA OPERATIVA")
    # Ogni sezione comincia DOPO il proprio titolo e finisce PRIMA del successivo. Il "dopo"
    # non e' un dettaglio: il titolo dei collaudi contiene "I 10 COLLAUDI", la stringa su cui
    # piu' sotto si dividono i modi di rompersi dai collaudi. Includerlo li conterebbe male.
    return {
        # IL BLOCCO sta PRIMA della regola zero: finisce dove comincia il suo titolo.
        "blocco": c[:zero[0]],
        "zero": c[zero[1]:ferrea[0]],
        "ferrea": c[ferrea[1]:direttive[0]],
        "direttive": c[direttive[1]:collaudi[0]],
        "collaudi": c[collaudi[1]:finale[0]],
        "finale": c[finale[1]:],
        "tutto": c,
    }


def conta_regole():
    """I numeri VERI, contati dai file. Mai a memoria: e' la REGOLA ZERO n.4."""
    p = _pezzi()
    appendice = _leggi(REGISTRO).split("APPENDICE")[-1]
    coll = p["collaudi"]
    return {
        "blocco": len(re.findall(r"^\*\*B\d+\.", p["blocco"], re.M)),
        "regola_zero": len(re.findall(r"^\*\*\d+\.", p["zero"], re.M)),
        "ferrea": len(re.findall(r"^\*\*\d+\.", p["ferrea"], re.M)),
        "direttive": len(re.findall(r"^\*\*D\d+\.", p["direttive"], re.M)),
        "modi": len(re.findall(r"^\| \d+ \|", coll.split("I 10 COLLAUDI")[0], re.M)),
        "collaudi": len(re.findall(r"^\| \d+ \|", coll.split("I 10 COLLAUDI")[-1], re.M)),
        "finale": len(re.findall(r"^\*\*\d+\.", p["finale"], re.M)),
        "appendice": len(re.findall(r"^\*\*\d+\. ", appendice, re.M)),
        "appendice_verificabili": appendice.count("SI VERIFICA COSI"),
        "uccise": sum(int(x) for x in re.findall(
            r"Uccise dal revisore ostile in questa ricerca: (\d+)", appendice)),
    }


def senza_verifica():
    """Le regole che NON dicono come si controllano. Il cuore di tutto lo strumento."""
    p = _pezzi()
    fuori = []
    for etichetta, testo, marca in (("BLOCCO", p["blocco"], r"^\*\*(B\d+)\."),
                                    ("FERREA", p["ferrea"], r"^\*\*(\d+)\."),
                                    ("DIRETTIVA", p["direttive"], r"^\*\*(D\d+)\.")):
        blocchi = re.split(marca, testo, flags=re.M)[1:]
        for numero, corpo in zip(blocchi[0::2], blocchi[1::2]):
            if not any(k in corpo for k in SEGNI_DI_VERIFICA):
                fuori.append("%s %s" % (etichetta, numero))
    return fuori


def dichiarato():
    """I numeri che il regolamento dichiara SU SE STESSO. Sono TRE, non uno.

    Fino al 2026-08-06 qui si leggeva solo il totale: «GLI ALTRI **N**» e «**N** direttive
    del fondatore» erano lettera morta, e potevano dire il falso lasciando lo strumento
    verde -- cioe' esattamente la modalita' di guasto che questo file esiste per scovare.
    L'ha trovato una revisione a contesto fresco, non un test: i numeri erano giusti per
    attenzione, non per costruzione (D22).
    """
    c = _leggi(CLAUDE)

    def _numero(schema):
        m = re.search(schema, c)
        return int(m.group(1)) if m else None

    return {
        "totale": _numero(r"GLI OBBLIGHI SONO \*\*(\d+)\*\*"),
        "altri": _numero(r"GLI ALTRI \*\*(\d+)\*\*"),
        "direttive": _numero(r"\*\*(\d+) direttive del fondatore\*\*"),
    }


def stampa_i_divieti(n=None):
    """I SEI DIVIETI, per intero. Sta in una funzione a se' perche' lo chiamano in TRE.

    ⛔ ORDINE DEL FONDATORE, 2026-08-11, dato a meta' sessione: «LE REGOLE SI LEGGONO
    PRIMA E DOPO OGNI OPERAZIONE». Fino a quel momento «rileggerle dopo» era affidato al
    ricordarsene -- ed e' esattamente la categoria di obbligo che questo progetto ha
    dimostrato rompersi di nuovo. Adesso lo fanno gli attrezzi:
        collaudi/regole_avvio.py        -> a ogni avvio di sessione
        collaudi/prima_di_lanciare.py   -> PRIMA di ogni operazione lunga
        collaudi/prima_di_dire_fatto.py -> DOPO, prima di ogni commit
    Il testo sta in un posto solo (`CLAUDE.md`) e lo stampa una funzione sola: tre copie
    a mano sarebbero tre cose che divergono, che e' la malattia di sempre.
    """
    n = n or conta_regole()
    print("=" * 78)
    print("⛔⛔ IL BLOCCO — %d DIVIETI ASSOLUTI (prima di tutto, anche della regola zero)"
          % n["blocco"])
    print("=" * 78)
    # ⛔ SI STAMPANO PER INTERO, non si nominano. Un divieto riassunto e' un divieto che
    # qualcuno dovra' andare a cercare -- e non lo cerchera'. Il testo si legge DAL FILE:
    # se qualcuno lo cambia, qui cambia; se qualcuno lo toglie, qui sparisce e si vede.
    for numero, titolo in re.findall(r"^\*\*(B\d+)\. ([^*]+)\*\*", _pezzi()["blocco"], re.M):
        testo = " ".join(titolo.split())
        print("  %s. %s" % (numero, testo))
    print()
    print("  Se ne violi uno: «REGOLA VIOLATA: [nome]. MI SONO FERMATO. Aspetto istruzioni.»")
    print("  Poi ti fermi. Non agisci, non committi, non ripari, non riassumi.")
    print("  SI RILEGGONO: prima di iniziare un'operazione E dopo averla finita.")
    print()
    # IL CATALOGO DEGLI SBAGLI (ordine del fondatore, 2026-08-08): sta in cima a CLAUDE.md,
    # subito dopo i sei divieti. Il numero si CONTA dal file, non si scrive a mano (D22):
    # un catalogo che cresce e un numero che resta fermo e' la prima bugia del documento.
    _sbagli = re.findall(r"^\*\*(S\d+)\. ", _leggi(CLAUDE), re.M)
    print("  🩹 IL CATALOGO DEGLI SBAGLI — %d voci, in cima a CLAUDE.md subito dopo questi"
          % len(_sbagli))
    print("     divieti. Sono errori FATTI DAVVERO, ognuno con la data, come si e' visto e")
    print("     la riga che lo impedisce. SI RILEGGE PRIMA DI DIRE «FATTO».")
    print()


# ─────────────────────────────────────────────────────────────────────────────────────
#  I LAVORI OBBLIGATORI CHE NESSUNA CHAT DEVE POTER DIMENTICARE
# ─────────────────────────────────────────────────────────────────────────────────────
# PERCHE' STANNO QUI E NON IN UN DOCUMENTO. Il 2026-08-12 il fondatore ha chiesto: «queste
# vanno fatte, scrivilo in modo che TUTTE le chat le facciano». Scriverle in un `.md` non
# basta, ed e' dimostrato dai fatti di quello stesso giorno: il piano dei soldi era scritto
# in tre punti diversi e ne era stato aggiornato uno solo, cosi' due documenti dicevano
# ancora «`fase66` e' il prossimo da fare» quando era gia' finito. Una chat nuova l'avrebbe
# rifatto da capo. Questo file invece lo esegue un hook `SessionStart`: la sua uscita entra
# nel contesto PRIMA di ogni altra cosa, quindi non dipende da chi si ricorda di leggere.
#
# ⛔ E NON SONO UN TEST ROSSO, DI PROPOSITO. L'istinto sarebbe «finche' non sono fatti la
# suite e' rossa». Sarebbe la trappola gia' pagata da questo progetto: *un allarme che suona
# sempre viene spento*. Quattro rossi permanenti al terzo giorno non li guarda piu' nessuno,
# e si sarebbe peggiorata la situazione. Qui si INFORMA a ogni avvio; il rosso sta dove
# serve, cioe' su una lista che si corrompe (vedi `fatto_quando` qui sotto).
#
# ⛔ OGNI VOCE DEVE DIRE QUANDO E' FINITA. E' la stessa regola che questo file applica gia'
# alle norme: una cosa che non si puo' controllare non e' un lavoro, e' un desiderio -- e
# «fai CodeQL» senza criterio e' come «trova tutto»: non finisce mai. Se qualcuno aggiunge
# una voce senza `fatto_quando`, lo strumento GRIDA (vedi `main`).
# ✅ FATTO il 2026-08-12 e TOLTO da questa lista nello stesso commit, com'e' scritto sotto:
#    «il guardiano del piano dei soldi — test_piano_dei_soldi.py». Vive in
#    `test_piano_dei_soldi.py` (14 collaudi) piu' una guardia in `test_pipeline_ci.py` che lo
#    tiene in piedi (D18 punto 4: se il file sparisce, l'import fallisce e la suite e' rossa
#    lo stesso giorno). Visto ROSSO sui documenti VERI su ENTRAMBI i difetti che sorveglia --
#    `fase66` FATTO qui e DA FARE la' (12 agosto), e `fase43` morto rimesso nel piano
#    (11 agosto) -- con ripristino byte-identico dopo ognuno.
# ✅ FATTO il 2026-08-13 e TOLTO da questa lista nello stesso commit: «le BOMBE A TEMPO nei
#    test». Vive in `collaudi/bombe_a_tempo.py` (sposta l'orologio di Python, di SQLite e di
#    `gmtime`, e guarda CHI diventa rosso) + `controllo_7` nel PRE-VOLO, che legge lo
#    schedario in 0,03 s e grida su cio' che scade entro 30 giorni + 7 guardie in
#    `test_pipeline_ci.TestLeBombeATempo`. Trovate e riparate **13 bombe** (la prima sarebbe
#    esplosa il 2026-09-02); il giro di conferma dice **0**.
#    ⛔ LA LEZIONE CHE VALE PIU' DEL LAVORO: la strada «cerca le date col grep» era sbagliata
#    e MISURATA sbagliata -- 1667 date cablate in 156 file, quasi tutte innocue. E l'attrezzo
#    ha avuto CINQUE difetti (scarto doppio · SQLite fermo · processi figli · stesso processo
#    per le due passate · `time.gmtime`), ognuno dei quali accusava test SANI: tre li aveva
#    gia' accusati. Si sono visti solo aprendo i casi uno per uno, mai leggendo il codice.
LAVORI_IN_SOSPESO = (
    {
        "nome": "CodeQL",
        "costo": "30 minuti",
        "priorita": "SUBITO: e' il piu' economico di tutti",
        "perche": "analisi statica di sicurezza, GRATIS finche' il repository e' pubblico "
                  "(lo e'), e non richiede nessun intervento del fondatore",
        "fatto_quando": "esiste .github/workflows/codeql.yml, gira su master, ed e' VERDE — "
                        "oppure i suoi rilievi sono scritti e triati uno per uno, col motivo",
        "prova": {
            "tipo": "file",
            "bersagli": (".github/workflows/codeql.yml",),
            "parziale": "il VERDE su master questo strumento NON lo puo' vedere: si legge "
                        "dalla tabella dei job via API (regola ferrea 8). ⛔ Misurato il "
                        "2026-08-15 su 6118d35: conclusion=success. Prima di rifarlo, guarda.",
            "se_manca": "il file del flusso di lavoro non c'e'",
        },
    },
    {
        "nome": "libfaketime in CI — il giudice ESTERNO sull'orologio (solo Linux)",
        "costo": "5 minuti la prova che apre o chiude la strada, poi mezza sessione il job",
        "priorita": "MEDIA — ⛔ il PRIMO passo e' la prova da 5 minuti: puo' chiudere la strada",
        "perche": "il nostro attrezzo (`collaudi/bombe_a_tempo.py`) sposta l'orologio di Python "
                  "E di SQLite, ma NON quello dei processi FIGLI: e' un limite che dichiara da "
                  "se', ed e' il motivo per cui un test del deploy risulta «non giudicabile». "
                  "`libfaketime` (LD_PRELOAD) intercetta l'orologio a livello di libc, quindi "
                  "copre TUTTO -- figli, database, script di shell -- e sarebbe anche un "
                  "GIUDICE ESTERNO (collaudo 7: uno strumento non nostro che ci controlla). "
                  "⛔ Non gira su Windows, quindi non sul PC del fondatore: solo in CI, che "
                  "gira su `ubuntu-latest` (verificato in .github/workflows/ci.yml). "
                  "Fonti e limiti per esteso: REGISTRO_INGEGNERIA.md, appendice, voce R1",
        "fatto_quando": "PRIMA la prova che apre o chiude la strada, e costa 5 minuti: un job "
                        "che sotto `faketime '+400d'` stampa la data vista da Python E quella "
                        "vista da SQLite (`SELECT date('now')`). ⛔ Se una delle due NON si "
                        "sposta la strada e' chiusa e si scrive perche': il vDSO del kernel puo' "
                        "rispondere «che ore sono» scavalcando la libreria intercettata, e "
                        "allora l'orologio resta fermo e il giro dice «nessuna bomba» -- un "
                        "FALSO SILENZIO, peggio di un falso allarme. SOLO se la prova passa: un "
                        "job che rilancia la suite a +400 giorni e confronta i rossi con quelli "
                        "a orologio fermo. ⚠️ Altri limiti noti da mettere in conto: non "
                        "falsifica i clock monotoni, e il suo involucro Python non e' "
                        "thread-safe (noi useremmo il COMANDO, non l'involucro)",
        "prova": {
            "tipo": "testo",
            "dove": ((".github/workflows", "", ".yml"),),
            "cerca": "faketime",
            "se_manca": "nessun job della CI nomina faketime: la prova da 5 minuti non "
                        "e' mai stata fatta",
        },
    },
    {
        "nome": "orologi di prova Stripe (test clocks)",
        "costo": "1 sessione",
        "priorita": "ALTA: e' il giudice esterno piu' vicino ai soldi che manca",
        "perche": "fanno passare il TEMPO davvero: oggi hold, maturazione dei bonifici e "
                  "finestre di penale non sono mai stati visti scadere sul serio",
        "fatto_quando": "un collaudo crea un test clock, avanza il tempo e verifica ALMENO "
                        "tre cose: l'hold che scade · il payout che matura a 24h · una "
                        "finestra di penale — con identificativi Stripe VERI nel registro",
        "prova": {
            "tipo": "testo",
            "dove": (("", "test_", ".py"), ("collaudi", "", ".py")),
            "cerca": "test_clock",
            "se_manca": "nessun collaudo crea un orologio di prova Stripe: hold, payout e "
                        "penale non sono mai stati visti scadere davvero",
        },
    },
    {
        "nome": "collaudi metamorfici sull'aritmetica del denaro",
        "costo": "mezza sessione",
        "priorita": "MEDIA — e va fatto insieme a F6 «chi perde se va storta»",
        "perche": "e' l'UNICA delle 11 tecniche di verifica avanzata che il progetto non ha "
                  "(le altre 10 erano gia' in casa)",
        "fatto_quando": "esistono relazioni provate sull'aritmetica dei soldi, per esempio: "
                        "raddoppiare le notti raddoppia la componente fissa · un ospite "
                        "esente in piu' non cambia la tassa · l'ordine in cui si applicano "
                        "gli sconti non cambia il totale. ⛔ SOLO sull'aritmetica del denaro, "
                        "non su tutto: allargarlo e' il modo in cui questi progetti non "
                        "finiscono mai",
        "prova": {
            "tipo": "testo",
            "dove": (("", "test_", ".py"),),
            "cerca": "metamorf",
            "parziale": "misurato il 2026-08-15: esiste `TestRelazioniMetamorfiche` in "
                        "test_fase119_calendario_prezzi.py. ⛔ Il lavoro chiede l'aritmetica "
                        "del DENARO (tassa, commissione, ordine degli sconti): va guardato "
                        "se quelle relazioni la coprono, o se coprono solo il calendario",
            "se_manca": "nessun collaudo prova relazioni metamorfiche",
        },
    },
    {
        "nome": "il DENOMINATORE",
        "costo": "1 sessione",
        "priorita": "ALTA",
        "perche": "trasforma «cosa sto dimenticando?» in un NUMERO. Due strade indipendenti "
                  "sono arrivate alla stessa conclusione: la ricerca esterna e la nostra "
                  "regola «ogni guardia dichiara il denominatore»",
        "fatto_quando": "un attrezzo elenca DALLA MACCHINA quante rotte HTTP, email, pagine "
                        "pubbliche e lingue esistono, e per ognuna dice se un collaudo la "
                        "attraversa; e stampa quante NON sono attraversate",
        "prova": {
            "tipo": "testo",
            "dove": (("collaudi", "", ".py"),),
            "cerca": "DENOMINATORE DELLA MACCHINA",
            "se_manca": "nessun attrezzo elenca rotte, email, pagine e lingue col loro "
                        "denominatore. ⚠️ `collaudi/mappa_scoperta.py` ne fa un PEZZO "
                        "(rotte e moduli mai nominati): si parte da li', non da zero",
        },
    },
)


def lavori_senza_criterio():
    """Le voci che non dicono quando sono finite: sono desideri, non lavori."""
    return [v.get("nome", "(senza nome)") for v in LAVORI_IN_SOSPESO
            if not str(v.get("fatto_quando", "")).strip()]


def lavori_senza_prova():
    """Le voci che non dicono COME si controlla se sono finite.

    Non e' la stessa cosa di `lavori_senza_criterio()`. Quella chiede: «e' scritto quando
    e' finito?». Questa chiede: «e' scritto **chi lo va a vedere**?». Fra le due c'e' tutta
    la differenza fra una regola e un desiderio -- ed e' la stessa distinzione che il
    regolamento applica a se stesso col «si verifica:» di ogni direttiva.
    """
    return [v.get("nome", "(senza nome)") for v in LAVORI_IN_SOSPESO if not v.get("prova")]


def _c_e_il_file(base, relativo):
    return os.path.isfile(os.path.join(base, relativo.replace("/", os.sep)))


def _testo_dentro(base, cartella, inizio, fine, ago):
    """I file di `cartella` (nome che inizia/finisce come detto) che contengono `ago`.

    Sola lettura, tollerante: un file illeggibile si salta invece di far esplodere il
    gancio -- ma NON si conta come «trovato», perche' un errore non e' una prova.

    ⛔ L'IMPIANTO DELLE PROVE E' ESCLUSO DALLA RICERCA, e non e' un dettaglio: e' un verde
    finto vero, successo il 2026-08-15 pochi minuti dopo aver scritto queste prove. Le parole
    cercate ("test_clock", "DENOMINATORE DELLA MACCHINA") sono scritte QUI DENTRO, nelle prove
    stesse: la ricerca trovava se stessa e due lavori mai iniziati risultavano ✅ FATTO.
    E' lo sbaglio S6 (una guardia che un commento poteva soddisfare) in forma nuova:
    **una prova non puo' essere soddisfatta dal testo della prova.**

    ⛔⛔ E IL 2026-08-16 E' TORNATO, SPOSTATO DI UN FILE. La riparazione di ieri escludeva UN
    file solo -- questo. Ma da quando esiste la guardia che protegge la riparazione, le stesse
    parole vivono anche in `test_pipeline_ci.py`, che sta nella RADICE e comincia per `test_`:
    cioe' esattamente dove la prova degli «orologi di prova Stripe» va a cercare. Misurato:
    quel lavoro risultava ✅ FATTO soddisfatto da UN solo file, con UNA sola occorrenza della
    parola, dentro il commento che racconta il difetto -- e ZERO usi veri dell'API di Stripe.
    💡 La lezione, che vale oltre il caso: **la prova non e' un file, e' un IMPIANTO** -- e
    l'impianto cresce, perche' ogni riparazione si porta dietro la guardia che la difende.
    Escludere "me stesso" non basta piu' il giorno che "me stesso" diventa due file.

    ⚠️ LIMITE DICHIARATO (D18 punto 3): l'esclusione e' per NOME, quindi un file che si
    chiamasse cosi' in un'altra cartella non verrebbe contato lo stesso. Sono due nomi unici
    nel progetto, e restano riservati all'impianto delle prove: non si usino per altro.
    """
    dove = os.path.join(base, cartella) if cartella else base
    try:
        nomi = os.listdir(dove)
    except OSError:
        return []
    # I file che SONO la prova: questa lista con le sue ricerche, e la guardia che la protegge.
    # Se uno di questi soddisfa una prova, la prova sta leggendo se stessa.
    impianto = (os.path.basename(os.path.abspath(__file__)), "test_pipeline_ci.py")
    trovati = []
    for n in nomi:
        if not (n.startswith(inizio) and n.endswith(fine)):
            continue
        if n in impianto:
            continue
        percorso = os.path.join(dove, n)
        if not os.path.isfile(percorso):
            continue
        try:
            with io.open(percorso, encoding="utf-8", errors="replace") as f:
                if ago.lower() in f.read().lower():
                    trovati.append(n)
        except OSError:
            continue
    return trovati


def stato_del_lavoro(v, base=None):
    """Il lavoro e' finito? Lo dice una MISURA, non la voce dell'elenco.

    ⛔ PERCHE' ESISTE (2026-08-15). Il fondatore ha chiesto: *«come faccio a sapere se la
    chat vecchia ha fatto tutto quello che c'e' scritto?»*. Misurando, si e' scoperto che
    questa lista **mentiva**: metteva **CodeQL al primo posto fra i lavori da fare** mentre
    `.github/workflows/codeql.yml` esisteva ed era **verde su master** (letto dall'API).
    Una lista scritta a mano resta indietro sempre: e' la stessa malattia del paracadute
    `:prec` (sbagliato quattro volte in quattro giorni) e la cura e' la stessa -- toglierla
    dalla buona volonta' e darla a un attrezzo.

    Tre esiti, mai due (S7: se manca la premessa non e' «verde», e' «non eseguito»):
      FATTO    la prova meccanica e' soddisfatta per intero
      META'    la parte che vive QUI c'e'; quella che vive FUORI (CI, API, Stripe) questo
               strumento non la puo' vedere, e lo dice invece di indovinare
      DA FARE  la prova non trova niente
    """
    base = base or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    prova = v.get("prova")
    if not prova:
        return ("SENZA PROVA", "questa voce non dice come si controlla: e' un desiderio")

    tipo = prova.get("tipo")
    if tipo == "file":
        trovati = [b for b in prova["bersagli"] if _c_e_il_file(base, b)]
    elif tipo == "testo":
        trovati = []
        for cartella, inizio, fine in prova["dove"]:
            trovati += ["%s/%s" % (cartella or ".", n)
                        for n in _testo_dentro(base, cartella, inizio, fine, prova["cerca"])]
    else:
        return ("SENZA PROVA", "tipo di prova sconosciuto: %r" % tipo)

    if not trovati:
        return ("DA FARE", prova.get("se_manca", "la prova non trova niente sul disco"))
    dettaglio = ", ".join(sorted(trovati)[:4])
    if prova.get("parziale"):
        return ("META'", "trovato: %s — ma %s" % (dettaglio, prova["parziale"]))
    return ("FATTO", "trovato: %s" % dettaglio)


def stampa_i_lavori_in_sospeso():
    print("=" * 78)
    print("⏳ LAVORI OBBLIGATORI IN SOSPESO — %d  (decisi dal fondatore, non opzionali)"
          % len(LAVORI_IN_SOSPESO))
    print("=" * 78)
    segno = {"FATTO": "✅ FATTO", "META'": "⚠️  META'", "DA FARE": "⏳ DA FARE",
             "SENZA PROVA": "🔴 SENZA PROVA"}
    for i, v in enumerate(LAVORI_IN_SOSPESO, 1):
        esito, perche_lo_dico = stato_del_lavoro(v)
        print("  %d. %s" % (i, v["nome"]))
        print("     STATO MISURATO ADESSO: %s — %s"
              % (segno.get(esito, esito), perche_lo_dico))
        print("     costo: %s  ·  priorita': %s" % (v["costo"], v["priorita"]))
        print("     perche': %s" % v["perche"])
        print("     ✅ FATTO QUANDO: %s" % v["fatto_quando"])
        print()
    print("  ⛔ Quando ne finisci uno, TOGLILO DA QUESTA LISTA nello stesso commit del")
    print("     lavoro: una lista che resta indietro rimanda a rifare cose gia' fatte, ed e'")
    print("     esattamente il difetto del 2026-08-12 che ha reso necessaria questa lista.")
    print("  ⛔ E lo «STATO MISURATO ADESSO» non e' scritto qui da nessuno: lo rifa' la")
    print("     macchina a ogni avvio. Nasce il 2026-08-15, quando questa lista teneva")
    print("     CodeQL al primo posto fra i lavori da fare mentre era gia' VERDE su master:")
    print("     una lista scritta a mano resta indietro sempre, e chi legge rifa' il lavoro.")
    print("=" * 78)
    print()


# ⛔ NON SONO COLLAUDI, E OGNUNO DICE PERCHE'. Senza questo elenco il conto dei «fuori dalla
# batteria» mescolava i ganci di git e gli attrezzi di marketing coi collaudi veri, e dava un
# numero che allarma senza dire niente: un falso allarme e' un difetto quanto un allarme
# mancato (regola ferrea 10). ⛔ Un motivo VUOTO non e' ammesso: lo pretende una guardia in
# test_pipeline_ci.py, cosi' nessuno puo' far sparire un collaudo da qui senza spiegarsi.
NON_SONO_COLLAUDI = {
    "regole_avvio": "e' questo strumento: gira dal gancio a ogni avvio di sessione",
    "prima_di_lanciare": "gancio: si lancia PRIMA di un'operazione lunga, non dentro la batteria",
    "prima_di_dire_fatto": "gancio del commit: lo esegue git, non la batteria",
    "guardia_commit": "gancio di git",
    "batteria": "e' la batteria stessa",
    "sentinella_ci": "guarda i job della CI su GitHub, non il prodotto in locale",
    "avvia_server_visivo": "non giudica niente: accende il banco perche' altri lo giudichino",
    "_srv_caos": "avviatore di servizio per il collaudo del caos",
    "dati_realistici": "e' un corpus di dati, non un giudice",
    "capitolato": "documento generato: dice cosa c'e', non se funziona",
    "piano": "elenca i dieci blocchi; il suo esito lo legge gia' `piano_dei_soldi`",
    "cronometro_suite": "misura QUANTO COSTA la suite, non se passa",
    "foglio_unico": "riepilogo dei controlli, gia' stampato dal pre-fatto",
    "bombe_a_tempo": "costa ~25 minuti e ha il suo schedario: lo legge il pre-volo",
    "mappa_scoperta": "censimento del costruito-e-dimenticato, non un giudice",
    "raggiungibilita": "censimento dei moduli vivi, non un giudice",
    "piramide": "descrive il sistema di sorveglianza, non lo esercita",
    "logiche": "ragionamenti a catena, si legge",
    "anteprima_campagna": "marketing: chiama un'AI vera, non e' un collaudo",
    "campagna_totale": "ripete OGNI collaudo 5 volte: e' la batteria x5, si lancia a parte",
    "drip_facebook": "pubblica su Facebook: strumento di marketing",
    "giro_video": "produce video: strumento di marketing",
    "pubblica_video": "pubblica video: strumento di marketing",
    "video_render": "produce video: strumento di marketing",
    "sonda_qtsp": "sonda autorita' esterne europee: dipende da terzi, non da noi",
}


def strumenti_e_batteria(radice=None):
    """Quanti COLLAUDI esistono, quanti ne lancia `collaudi/batteria.py`, e quali restano fuori.

    ⛔ NON E' UN ELENCO SCRITTO A MANO: gli strumenti si contano dalla cartella e i lanciati
    si leggono dentro la batteria. Un elenco scritto a mano rimane indietro il giorno che
    qualcuno aggiunge un attrezzo, e allora dice il falso proprio su «li ho lanciati tutti».
    Gli esclusi invece SONO scritti a mano, ma ognuno col motivo, e una guardia lo pretende.
    """
    base = radice or os.path.dirname(os.path.abspath(__file__))
    tutti = sorted(f[:-3] for f in os.listdir(base)
                   if f.endswith(".py") and not f.startswith("__"))
    collaudi = [s for s in tutti if s not in NON_SONO_COLLAUDI]
    try:
        with io.open(os.path.join(base, "batteria.py"), encoding="utf-8") as f:
            testo = f.read()
    except OSError:
        return collaudi, [], collaudi
    citati = set(re.findall(r"collaudi/([a-z0-9_]+)\.py", testo))
    # ⛔ «lanciati» conta SOLO i collaudi: la batteria nomina anche `avvia_server_visivo`, che
    # non giudica niente (accende il banco). Contarlo fra i lanciati gonfierebbe il numero
    # che deve rassicurare -- ed e' esattamente il modo in cui un conto si mette a mentire.
    lanciati = sorted(s for s in citati if s in collaudi)
    fuori = [s for s in collaudi if s not in citati]
    return collaudi, lanciati, fuori


def stampa_gli_strumenti():
    """⛔ «TUTTI I TEST» DEVE ESSERE UN COMANDO SOLO, E DEVE DIRE COSA NON HA GUARDATO.

    Nasce il 2026-08-21 da un ordine del fondatore: *ogni lavoro deve passare da tutti questi
    test*. Cercando cosa esisteva gia' (D10) e' venuto fuori che `collaudi/batteria.py` — il
    comando che si chiama «batteria COMPLETA» — saltava proprio i collaudi sui soldi: il
    banco, le percentuali, gli incroci dell'ospite e i quattro guardiani dei documenti.
    💡 Un elenco che dice «tutto» ed e' incompleto e' peggio di nessun elenco, perche' chi lo
    lancia crede di aver guardato. Percio' qui il numero di quelli FUORI si stampa sempre:
    e' il denominatore degli strumenti, e deve poter dare fastidio.
    """
    esistono, lanciati, fuori = strumenti_e_batteria()
    print("=" * 78)
    print("🧰 GLI STRUMENTI — «tutti i test» e' UN COMANDO SOLO")
    print("=" * 78)
    print("     python collaudi/batteria.py        <- li lancia in fila, uno dopo l'altro")
    print("     STRIPE_SECRET_KEY=sk_test_... python collaudi/batteria.py")
    print("                                        <- ...e cosi' PAGA DAVVERO (banco dei soldi)")
    print()
    print("  COLLAUDI: %d   ·   lanciati dalla batteria: %d   ·   FUORI: %d"
          "   (+%d attrezzi che non sono collaudi, ognuno col motivo)"
          % (len(esistono), len(lanciati), len(fuori), len(NON_SONO_COLLAUDI)))
    if fuori:
        print("  ⛔ i %d FUORI non sono «coperti da qualcos'altro»: nessuno li lancia da solo,"
              % len(fuori))
        print("     quindi «ho lanciato la batteria» NON vuol dire che sono stati eseguiti.")
        for i in range(0, len(fuori), 4):
            print("     " + "  ".join("%-19s" % s for s in fuori[i:i + 4]))
    else:
        print("  ✅ nessun collaudo resta fuori dalla batteria.")
    print("  ⚠️ E la batteria NON sostituisce la CI (regola ferrea 8): il verde locale e' un")
    print("     indizio, il giudice e' la tabella dei job letta dall'API.")
    print()


def main():
    n = conta_regole()
    ricerca = n["appendice"]                       # le 44: 15 in CLAUDE.md + 29 in appendice
    solo_appendice = max(0, n["appendice"] - n["ferrea"])
    altri = (n["blocco"] + n["regola_zero"] + n["direttive"] + n["modi"] + n["collaudi"]
             + n["finale"])
    totale = ricerca + altri

    stampa_i_divieti(n)
    stampa_i_lavori_in_sospeso()
    stampa_gli_strumenti()
    print("=" * 78)
    print("⛔ REGOLE DEL PROGETTO — si leggono PRIMA di fare qualunque cosa")
    print("=" * 78)
    print()
    print("  🔬 LE %d DELLA RICERCA  (~4 milioni di token, 77 agenti, 2026-07-30)" % ricerca)
    print("     Unica famiglia con FONTE ESTERNA, PROVA e COME SI VERIFICA.")
    print("     · %2d in CLAUDE.md ...... si ricaricano SEMPRE, valgono a ogni lavoro"
          % n["ferrea"])
    print("     · %2d nell'appendice ... da leggere PRIMA di: mutazione · modificare codice"
          % solo_appendice)
    print("                              esistente · sessione lunga o riassunta · dire «fatto»")
    print("     · %2d uccise dai revisori, col motivo: dicono cosa NON rifare" % n["uccise"])
    print("     verificabili: %d su %d" % (n["appendice_verificabili"], n["appendice"]))
    print()
    print("  🧭 GLI ALTRI %d — nati dai NOSTRI danni, non da uno studio" % altri)
    print("     · IL BLOCCO ............ %2d   (i sei divieti assoluti, stampati qui sopra)"
          % n["blocco"])
    print("     · regola zero .......... %2d   (fonti di verita', niente .md nuovi, numeri"
          % n["regola_zero"])
    print("                                   verificati nel codice)")
    print("     · direttive fondatore .. %2d   (i titoli, letti dal file, uno per riga:)"
          % n["direttive"])
    # ⛔ I TITOLI SI LEGGONO DAL FILE, NON SI RISCRIVONO A MANO. Qui c'era un elenco scritto a
    # mano: e' rimasto indietro di una direttiva e la stampa e' nata GIA' diversa dal titolo
    # vero, senza che nulla lo dicesse (2026-08-06, visto da una revisione a contesto fresco).
    # Cosi' invece non possono piu' divergere: sono la stessa stringa. E' lo schema gia' usato
    # per IL BLOCCO qui sopra -- e una guardia in test_pipeline_ci.py pretende che ogni titolo
    # compaia qui, col denominatore dichiarato (quante sono, e ci sono TUTTE?).
    for numero, titolo in re.findall(r"^\*\*(D\d+)\. ([^*]+)\*\*", _pezzi()["direttive"], re.M):
        print("        %-4s %s" % (numero, " ".join(titolo.split())))
    print("     · modi di rompersi ..... %2d   (dati effimeri, cablaggio mancante, ambiente"
          % n["modi"])
    print("                                   diverso, tempo che passa, dato assurdo...)")
    print("     · collaudi obbligatori . %2d   (in ordine, mutazione per ULTIMA)" % n["collaudi"])
    print("     · direttiva finale ..... %2d" % n["finale"])
    print()
    print("  " + "-" * 74)
    print("  TOTALE OBBLIGHI: %d — valgono TUTTI. Non chiamare «le regole» un sottoinsieme:"
          % totale)
    print("  è così che si perdono. (Il conto è stato sbagliato tre volte: vedi CLAUDE.md.)")
    print()

    guasti = []
    for nome in titoli_mancanti():
        guasti.append("titolo di sezione «%s» non trovato: il taglio non e' affidabile e "
                      "TUTTI i conteggi qui sopra sono da buttare" % nome)
    dich = dichiarato()
    for chiave, dice, vero in (("obblighi in totale", dich["totale"], totale),
                               ("obblighi «nati dai nostri danni»", dich["altri"], altri),
                               ("direttive del fondatore", dich["direttive"], n["direttive"])):
        if dice is not None and dice != vero:
            guasti.append("il regolamento dichiara %d %s ma nei file ce ne sono %d"
                          % (dice, chiave, vero))
    if n["appendice_verificabili"] != n["appendice"]:
        guasti.append("delle %d regole della ricerca solo %d dicono come si verificano"
                      % (n["appendice"], n["appendice_verificabili"]))
    mute = senza_verifica()
    if mute:
        guasti.append("queste regole NON dicono come si verificano (sono desideri, non "
                      "regole): %s" % ", ".join(mute))
    # Stessa asta per i lavori in sospeso: uno che non dice quando e' finito non si chiude
    # mai, perche' nessuno puo' dimostrare di averlo chiuso.
    senza = lavori_senza_criterio()
    if senza:
        guasti.append("questi lavori in sospeso non dicono QUANDO sono finiti (sono "
                      "desideri, non lavori): %s" % ", ".join(senza))

    if guasti:
        print("  🔴 IL REGOLAMENTO NON DICE IL VERO SU SE STESSO:")
        for g in guasti:
            print("     · %s" % g)
        print("     Va corretto PRIMA di lavorare: un regolamento che sbaglia il proprio")
        print("     conteggio, o che contiene regole non controllabili, è una guardia che")
        print("     non guarda — cioè il difetto che questo progetto esiste per estirpare.")
    else:
        print("  ✅ Il regolamento dice il vero su se stesso, e OGNI regola dichiara come si")
        print("     verifica (conteggi rifatti adesso dai file, non a memoria).")
    stampa_piano()
    stampa_tecniche()
    stampa_i_blocchi()
    stampa_il_foglio()
    print("=" * 78)
    return 0


def stampa_il_foglio():
    """🧾 IL FOGLIO UNICO DEI CONTROLLI — l'ultima cosa che si legge all'avvio.

    Sta in fondo di proposito: sopra c'e' il METODO (le regole) e la ROTTA (il piano); questo
    e' il quadro degli strumenti, cioe' com'e' messa la macchina **adesso**. Nato il
    2026-08-17 da una richiesta del fondatore: *«Bisogna fare un foglio solo»* -- perche'
    «cosa devo fare prima di dire fatto» rispondeva in cinque posti diversi.

    ⛔ NON RICOPIA NIENTE. Il foglio vive in `collaudi/foglio_unico.py`, che per ogni voce dice
    chi possiede il fatto e va a misurarlo. Qui si CHIAMA, non si riscrive: una seconda copia
    sarebbe esattamente il difetto che il foglio esiste per curare.
    """
    try:
        import foglio_unico
        foglio_unico.stampa(foglio_unico.giro(RADICE), breve=True)
    except Exception as exc:                     # un gancio non rompe mai la sessione: lo DICE
        print()
        print("  ⚠️  IL FOGLIO UNICO DEI CONTROLLI NON SI STAMPA (%s: %s)"
              % (exc.__class__.__name__, exc))
        print("     Va guardato: senza di lui «cosa devo fare prima di dire fatto» torna a")
        print("     rispondere in cinque posti diversi. Comando: python collaudi/foglio_unico.py")


PIANO_INIZIO = "<!-- PIANO-INIZIO"
PIANO_FINE = "<!-- PIANO-FINE"


def leggi_piano(radice=None):
    """L'ordine dei lavori, LETTO da `REGISTRO_INGEGNERIA.md` fra i due marcatori.

    ⛔ Si LEGGE, non si ricopia. Una copia del piano dentro questo file resterebbe indietro il
    giorno che il piano cambia -- ed e' esattamente il difetto che il 2026-08-15 e' costato una
    CI rossa e un difetto in produzione (la riga del PIN scritta in tre posti).

    Ritorna la stringa vuota se il blocco non c'e': chi chiama lo DICE, non tace (S7).
    """
    base = radice or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        with io.open(os.path.join(base, "REGISTRO_INGEGNERIA.md"), encoding="utf-8") as f:
            testo = f.read()
    except OSError:
        return ""
    i = testo.find(PIANO_INIZIO)
    j = testo.find(PIANO_FINE)
    if i < 0 or j <= i:
        return ""
    corpo = testo[testo.find("\n", i) + 1:j]
    return corpo.strip()


def stampa_piano():
    """Il gancio stampa le REGOLE (come lavorare) e da oggi anche IL PIANO (cosa fare).

    Nato il 2026-08-15 da un'osservazione del fondatore: *«se ogni volta non viene letto siamo
    a punto a capo»*. Aveva ragione -- una chat nuova riceveva il metodo e non l'ordine dei
    lavori, e ricominciava a scegliere da sola. Un piano che vive solo in un file che nessuno
    apre non e' un piano: e' un desiderio.
    """
    piano = leggi_piano()
    print()
    print("=" * 78)
    print("🧭 IL PIANO — L'ORDINE DEI LAVORI (letto da REGISTRO_INGEGNERIA.md, non ricopiato)")
    print("=" * 78)
    if not piano:
        # Non si tace: un promemoria sparito senza avviso e' la stessa forma di guasto che
        # tutto questo strumento esiste per combattere.
        print("  ⛔ IL BLOCCO DEL PIANO NON C'E' PIU' in REGISTRO_INGEGNERIA.md")
        print("     (cercavo i marcatori PIANO-INIZIO / PIANO-FINE).")
        print("     Qualcuno l'ha tolto o rinominato: RIMETTILO prima di decidere cosa fare.")
        return
    for riga in piano.splitlines():
        print("  " + riga)
    print()
    print("  ⛔ PRIMA DI SCEGLIERE COSA FARE, apri e leggi PER INTERO (la riga di riassunto")
    print("     nell'indice NON basta -- e' l'errore fatto il 2026-08-15):")
    print("       memory/bookinvip-piano-dieci-pezzi.md")
    print("       memory/bookinvip-ricerca-industriale.md")


TECNICHE_INIZIO = "<!-- TECNICHE-INIZIO"
TECNICHE_FINE = "<!-- TECNICHE-FINE"


def leggi_tecniche(radice=None):
    """LA LISTA UNICA DELLE TECNICHE DI VERIFICA, letta da `REGISTRO_INGEGNERIA.md`.

    ⛔ Si LEGGE, non si ricopia, e sta in UN POSTO SOLO. Nasce il 2026-08-17 da un ordine del
    fondatore: *«va corretto sono 11 e deve rimanere solo quello e nessun altro file cosi'
    evitiamo che capiti ancora e quello va letto da qualunque chat»*. Il fatto: una SECONDA
    lista («i sei metodi AWS») viveva in `RIPRENDI_QUI.md`, e una sessione intera ha ragionato
    sul numero sbagliato -- fino a andare a cercare online tecniche in piu' che il progetto ha
    gia'. Due liste che dicono cose diverse non sono ridondanza: sono il difetto.

    Ritorna la stringa vuota se il blocco non c'e': chi chiama lo DICE, non tace (S7).
    """
    base = radice or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        with io.open(os.path.join(base, "REGISTRO_INGEGNERIA.md"), encoding="utf-8") as f:
            testo = f.read()
    except OSError:
        return ""
    i = testo.find(TECNICHE_INIZIO)
    j = testo.find(TECNICHE_FINE)
    if i < 0 or j <= i:
        return ""
    return testo[testo.find("\n", i) + 1:j].strip()


def conta_tecniche(blocco=None):
    """Quante tecniche ci sono DAVVERO, e quante il blocco dichiara di averne.

    ⛔ D18 e D22: il numero non si crede, si CONTA. Il conteggio delle regole ha mentito TRE
    volte (75 -> 103 -> 104) finche' a scriverlo era una persona invece di una macchina.
    Ritorna `(contate, dichiarate)`; `dichiarate` e' None se la riga `TOTALE DICHIARATO:`
    non c'e' -- e allora nessuna macchina puo' accorgersi che la lista e' cambiata.
    """
    testo = blocco if blocco is not None else leggi_tecniche()
    righe = testo.splitlines()
    contate = sum(1 for r in righe if r.startswith("- **"))
    dichiarate = None
    for r in righe:
        if r.strip().startswith("TOTALE DICHIARATO:"):
            try:
                dichiarate = int(r.split(":", 1)[1].strip())
            except ValueError:
                dichiarate = None
            break
    return contate, dichiarate


def stampa_tecniche():
    """Le tecniche di verifica: UNA lista, UN file, letta da qualunque chat.

    ⛔ Non stampa solo: CONTROLLA. Se il blocco dichiara un numero diverso da quante righe
    ha davvero, GRIDA -- perche' un elenco che mente su se stesso e' peggio di nessun elenco.
    Ritorna 0 se tutto torna, 1 se c'e' qualcosa da correggere (il chiamante NON rompe la
    sessione per questo: la guardia che fa diventare rossa la CI sta in `test_pipeline_ci.py`).
    """
    blocco = leggi_tecniche()
    print()
    print("=" * 78)
    print("🔬 LE TECNICHE DI VERIFICA — LA LISTA UNICA (letta da REGISTRO_INGEGNERIA.md)")
    print("=" * 78)
    if not blocco:
        print("  ⛔ IL BLOCCO DELLE TECNICHE NON C'E' PIU' in REGISTRO_INGEGNERIA.md")
        print("     (cercavo i marcatori TECNICHE-INIZIO / TECNICHE-FINE).")
        print("     Qualcuno l'ha tolto o rinominato: RIMETTILO prima di decidere cosa fare.")
        return 1
    for riga in blocco.splitlines():
        print("  " + riga)
    print()
    contate, dichiarate = conta_tecniche(blocco)
    if dichiarate is None:
        print("  ⛔ IL BLOCCO NON DICHIARA IL TOTALE: manca la riga `TOTALE DICHIARATO: N`,")
        print("     quindi nessuna macchina puo' accorgersi se la lista cambia. RIMETTILA.")
        return 1
    if contate != dichiarate:
        print("  ⛔⛔ IL BLOCCO MENTE SU SE STESSO: dichiara %d tecniche, ne ho contate %d."
              % (dichiarate, contate))
        print("      Correggi `TOTALE DICHIARATO:` oppure la lista, PRIMA di lavorare.")
        return 1
    print("  ✅ %d dichiarate, %d contate adesso dal file: il blocco dice il vero su se stesso."
          % (dichiarate, contate))
    return 0


def stampa_i_blocchi():
    """I DIECI BLOCCHI della macchina, misurati adesso da `collaudi/piano.py`.

    ⛔ Perche' e' separato dal piano qui sopra, e non e' un doppione. Il blocco
    `PIANO-INIZIO/PIANO-FINE` dice **in che ordine si lavora adesso** (gli attrezzi da
    accendere: z3 in CI, il Giudice che esce rosso...). Questo dice **com'e' fatta la
    macchina**: dieci mestieri, quali moduli stanno in ognuno, con quali strumenti
    d'ingegneria si dimostra che sono finiti. Il primo e' la rotta di oggi, il secondo e'
    la mappa: servono tutti e due, e nessuno dei due si scrive a mano.

    Nato il 2026-08-15 dall'osservazione del fondatore: *«se non mettiamo a posto questo
    foglio, ogni chat fa quel che vuole»*. La cura non e' scrivere meglio il foglio: e'
    smettere di far decidere a un foglio. Qui il piano e' DATI, e chi li contraddice
    diventa rosso lo stesso giorno.
    """
    print()
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import piano as _piano
        blocchi = sorted(_piano.BLOCCHI, key=lambda b: b["ordine"])
        sul_disco = _piano.moduli_sul_disco()
        nominati = _piano.moduli_nominati_dai_test()
        problemi = _piano.contraddizioni()
    except Exception as exc:  # un gancio non rompe mai la sessione: lo DICE
        print("  ⚠️  non riesco a leggere collaudi/piano.py (%s: %s)"
              % (exc.__class__.__name__, exc))
        print("     Va guardato: senza quel file nessuno sa piu' quale modulo sta in quale")
        print("     blocco, ed e' cosi' che i pezzi diventano «costruiti e dimenticati».")
        return
    print("=" * 78)
    print("🧱 LA MACCHINA IN %d BLOCCHI — misurati adesso, non ricordati "
          "(python collaudi/piano.py)" % len(blocchi))
    print("=" * 78)
    for b in blocchi:
        s = _piano.stato_del_blocco(b, sul_disco, nominati)
        print("  %2d. %-34s %3d moduli · %d mai nominati da un test"
              % (b["ordine"], b["nome"], s["moduli"], len(s["scoperti"])))
    print("  ⛔ «nominato da un test» NON vuol dire eseguito: e' il limite dichiarato N1.")
    print("     Nessun blocco puo' dirsi FINITO finche' gli strumenti non scrivono da soli")
    print("     la loro scheda (pezzo 5 del piano). Il dettaglio: python collaudi/piano.py")
    if problemi:
        print("  🔴 IL PIANO E LA MACCHINA NON COINCIDONO — %d contraddizioni:" % len(problemi))
        for p in problemi:
            print("     · %s" % p)


if __name__ == "__main__":
    # ⛔ UN HOOK NON PUO' MAI ROMPERE LA SESSIONE. Se questo strumento esplode (file spostato,
    # permessi, console esotica) deve DIRLO e uscire 0, non impedire di lavorare. Il silenzio
    # no: un promemoria che sparisce senza avvisare e' la stessa forma di guasto che stiamo
    # combattendo -- lo strumento che tace mentre e' rotto.
    try:
        sys.exit(main())
    except Exception as _e:                                    # pragma: no cover
        print("REGOLE NON MOSTRATE (%s: %s) -- leggi CLAUDE.md a mano PRIMA di lavorare."
              % (type(_e).__name__, _e))
        sys.exit(0)
