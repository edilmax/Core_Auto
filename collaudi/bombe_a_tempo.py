# -*- coding: utf-8 -*-
"""💣 LE BOMBE A TEMPO — i test che diventano rossi DA SOLI, senza che nessuno tocchi il codice.

PERCHE' ESISTE, e non e' teoria. Il **2026-08-13 alle 00:03**
`test_fase156_erasure.test_host_con_prenotazione_e_RIFIUTATO_senza_forza` e' diventato rosso
**da solo**: cablava `check_out 2026-08-12` per una prenotazione che il suo commento dichiarava
FUTURA, e a mezzanotte il 12 e' passato. Rosso 3 volte su 3, quindi deterministico.
⚠️ **Un test che scade e' peggio di un test mancante**: manda a cercare per mezz'ora un difetto
che non esiste, e insegna a rilanciare la suite «che tanto poi passa» -- che e' esattamente il
modo in cui si nasconde un difetto vero.

⛔ LA STRADA FACILE E' SBAGLIATA, ED E' MISURATA. Cercare le date cablate col testo
(`grep 2026-`) trova **1667 date in 156 file** (misurato il 2026-08-13, commit bf2e1b6), e di
quelle **quasi nessuna e' pericolosa**: un allarme su 1667 punti verrebbe spento in tre giorni,
e un allarme spento non protegge niente (regola ferrea 10). Nessuna analisi del TESTO puo'
distinguerle: nel caso vero la data cablata non stava nemmeno nel test che falliva, stava nel
suo apparecchio di preparazione.

✅ QUINDI SI MISURA IL COMPORTAMENTO, NON IL TESTO: si sposta l'orologio e si guarda chi
diventa rosso. **Verde a orologio fermo + rosso a orologio spostato = BOMBA, dimostrata.**
Poi si cerca **il giorno esatto** in cui esplode, e quel giorno si verifica nelle due
direzioni (verde il giorno prima, rosso quel giorno), mai dedotto.

⛔ E LA SECONDA VOLTA, IL 2026-09-01, LA BOMBA L'HA PERSA QUESTO ATTREZZO. `test_calendario_
prezzi` e' esploso da solo -- stesso commit `dc7c25b`, `gate=success` il 29 agosto e
`gate=failure` il 31 nella tabella della CI, senza che nessuno avesse toccato una riga --
mentre lo schedario diceva `"bombe": []`. Non era vecchio (17 giorni su 30 di tolleranza) e
l'orologio finto funzionava benissimo: **a sbagliare era DOVE si guardava.**
Il giro campionava DUE punti, il giorno 0 e l'orizzonte a 400 giorni. Ma quel test era rosso
solo in una **finestra di 6 giorni** e poi **guariva da solo**, perche' passata la data il
motore ripiega su un valore neutro (`fase119_calendario_prezzi.py:62`, `return d if d >= 0
else 30`). Misurato sull'artefatto vero, con l'attrezzo di allora:
      scarto -19 (il 13 agosto, il suo «giorno 0»)   -> verde
      scarto -2 .. +3                                 -> ROSSO   <- la finestra
      scarto +381 (13 agosto + 400, il suo orizzonte) -> verde
⛔ E NON E' SFORTUNA, E' IMPOSSIBILITA': una bomba che guarisce da sola e' verde a QUALUNQUE
distanza oltre la sua finestra, quindi **e' certamente verde all'orizzonte, per qualunque
orizzonte**. Il secondo campione era verde per costruzione. ⇒ **allungare `ORIZZONTE`
peggiora**: e' il punto in cui tutto e' piu' sicuramente guarito. Non e' un numero da tarare.

✅ LA RIPARAZIONE: NON PIU' DUE PUNTI SCELTI SENZA GUARDARE, MA UN PIANO RICAVATO DALLE DATE.
Per ogni data cablata futura si prova lo scarto che la porta esattamente su OGGI: e' li' che
le soglie di calendario cambiano parere. Vedi `piano_di_campionamento`.
⛔ E LA STRADA CHE SEMBRA OVVIA E' MISURATA E SBAGLIATA: una **griglia fissa** di 11 punti --
cioe' «campioniamo di piu'», la riparazione che verra' in mente a chiunque -- costa QUATTRO
volte questo giro e trova ESATTAMENTE quanto i due punti di prima (banco del 2026-09-01, 9
forme a verita' nota: 3 su 6 per tutt'e due). **La griglia non sa dove guardare; le date lo
sanno.**

📚 FONTI (D25, lette il 2026-08-13 -- per esteso in REGISTRO_INGEGNERIA.md, appendice R1):
   · Luo, Hariri, Eloussi, Marinov, *An empirical analysis of flaky tests*, FSE 2014:
     «time» e' una delle 10 cause radice riconosciute dei test instabili.
   · freezegun / time-machine: mockano Python ma **NON** `datetime('now')` di SQLite.
     E' un limite NOTO degli strumenti di riferimento, ed e' il caso che conta qui.
   · libfaketime (LD_PRELOAD): coprirebbe anche i processi figli, ma **non gira su Windows**.
     E' in lista fra i lavori obbligatori, con la prova da fare per prima.

⛔ LE QUATTRO CONDIZIONI D18 (questo e' uno strumento che MISURA):
   1. **misura prima se stesso**: se a orologio FERMO qualcosa e' gia' rosso, il verdetto sul
      futuro non vale -- non si saprebbe se il rosso l'ha causato il tempo o l'attrezzo. In
      quel caso esce NON ESEGUITO, che non e' mai un successo (sbaglio S7);
   2. **provato nelle DUE direzioni**: `--autoprova` costruisce dei test gemelli -- con la
      data CABLATA, con la stessa intenzione calcolata da oggi, e una bomba che GUARISCE DA
      SOLA -- e pretende due cose diverse: che l'OROLOGIO faccia diventare rossa la bomba e
      lasci verde il sano, e che la CACCIA se ne ACCORGA. La seconda meta' e' nata il
      2026-09-01: le prove di allora guardavano solo l'orologio, che funzionava, e non
      potevano vedere che a sbagliare era il modo di cercare. Se non le vede, esce 1;
   3. **dichiara cosa NON ha esaminato**: `NON_GUARDA`, stampato a ogni giro;
   4. **e' a sua volta sotto guardia**: `test_pipeline_ci.TestLeBombeATempo`.
"""
import ast
import datetime as _dt
import io
import json
import os
import re
import sqlite3 as _sq
import subprocess
import sys
import time as _time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEDARIO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bombe_a_tempo.json")

# La soglia d'allarme NON e' inventata: e' la pratica industriale sulle scadenze in CI
# (si avvisa PRIMA, non quando la cosa e' gia' scaduta). Fonte in appendice R1.
GIORNI_ALLARME = 30
# Quanto lontano si guarda. Un anno e mezzo: oltre, un test che cambia comportamento e'
# quasi sempre una regola di prodotto che cambia sul serio, non una data dimenticata.
ORIZZONTE = 400
# Oltre questa eta' lo schedario non e' piu' una misura, e' un ricordo (D22).
GIORNI_SCHEDARIO_VECCHIO = 30

_DATA_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")

NON_GUARDA = (
    "l'orologio dei PROCESSI FIGLI (shell, script di deploy): il figlio vede l'ora VERA "
    "mentre il padre la vede spostata, e il disaccordo lo creerebbe questo attrezzo. I test "
    "che avviano processi esterni sono elencati a parte come NON GIUDICABILI, mai come sani",
    "`CURRENT_TIMESTAMP` di SQLite: e' una parola chiave, non una funzione, e non si puo' "
    "sovrascrivere. Un test che dipende SOLO da quella non e' giudicabile qui",
    "le date gia' scritte dentro i file su disco e i timestamp del filesystem",
    "i test che NON contengono nessuna data cablata entro un anno: non sono nemmeno "
    "candidati, quindi non sono stati eseguiti a orologio spostato",
    "il MOTIVO del rosso: questo attrezzo dimostra CHE una data lo provoca, non QUALE riga "
    "va cambiata. Quello si legge aprendo il test",
    "le soglie LONTANE dall'attraversamento. Si prova lo scarto che porta ogni data cablata "
    "esattamente su OGGI, quindi una regola che cambia parere a 60 giorni di distanza -- "
    "l'anticipo di `fase106:28` -- non viene esercitata. Misurato sul banco del 2026-09-01: "
    "e' la forma 3, ed e' PERSA. Prenderla costerebbe otto volte questo giro",
    "le date scritte in forma NUMERICA: `datetime.date(2026, 9, 21)` non e' vista, solo "
    "\"2026-09-21\". Misurato il 2026-09-01 su due file gemelli (`candidati` ne restituisce "
    "uno solo). Quanti file veri usino quella forma NON e' stato misurato: e' un rilievo "
    "aperto, non un buco quantificato",
)


# --------------------------------------------------------------------------------------
# l'orologio finto: Python + SQLite, da un'unica sorgente di verita'
# --------------------------------------------------------------------------------------
_SCARTO = [0]
_BASE = [None]
_vero_time = _time.time
_vero_gmtime = _time.gmtime
_vero_localtime = _time.localtime
_vera_dt = _dt.datetime
_vera_connect = _sq.connect
_aux = _vera_connect(":memory:")     # connessione di servizio, mai patchata
_installato = [False]


def _adesso():
    # `_BASE` esiste per UNA ragione sola: permettere di costruire a mano l'ora del giorno
    # in cui le due zone litigano, invece di aspettare mezzanotte per scoprirlo (D19). Se
    # nessuno la imposta vale l'ora vera, cioe' il comportamento di sempre.
    base = _vero_time() if _BASE[0] is None else _BASE[0]
    return base + _SCARTO[0] * 86400.0


class _DataOra(_vera_dt):
    """⛔ `datetime.now()` NON legge `time.time()` (misurato): va spostata a parte. Ma si
    calcola dall'ora VERA, mai da quella gia' spostata, se no lo scarto si applica DUE volte
    -- errore vero del 2026-08-13: chiesti 200 giorni, ottenuti 400."""

    @classmethod
    def now(cls, tz=None):
        return _vera_dt.fromtimestamp(_adesso(), tz)

    @classmethod
    def utcnow(cls):
        return _vera_dt.utcfromtimestamp(_adesso())

    @classmethod
    def today(cls):
        return _vera_dt.fromtimestamp(_adesso())


def _funzione_sqlite(nome):
    """`X('now', ...)` diventa `X('<istante spostato>', ...)`; i modificatori restano quelli
    VERI di SQLite, delegati a lui. ⛔ Senza questo, un test scrive col nostro orologio e il
    database giudica col suo: due falsi allarmi su diciassette, il 2026-08-13."""
    def f(*args):
        args = list(args)
        if args and isinstance(args[0], str) and args[0].strip().lower() == "now":
            args[0] = _vera_dt.utcfromtimestamp(_adesso()).strftime("%Y-%m-%d %H:%M:%S")
        posti = ", ".join("?" * len(args))
        return _aux.execute("SELECT %s(%s)" % (nome, posti), args).fetchone()[0]
    return f


def _connect(*a, **k):
    con = _vera_connect(*a, **k)
    for nome in ("datetime", "date", "time", "julianday", "strftime", "unixepoch"):
        try:
            con.create_function(nome, -1, _funzione_sqlite(nome))
        except Exception:
            pass
    return con


def installa_orologio():
    """UNA volta sola, PRIMA di importare i test. Poi ci si sposta con `vai_a`.
    ⛔ `date.today()` legge `time.time()` (misurato): spostando `time` si sposta da sola --
    per questo NON si tocca `datetime.date`, che darebbe il doppio conteggio."""
    if _installato[0]:
        return
    _time.time = lambda: _adesso()
    # ⛔ `gmtime()`/`localtime()` SENZA ARGOMENTI leggono l'orologio di sistema, non
    # `time.time()`: e' il quinto difetto di questo attrezzo (2026-08-13). Senza queste due
    # righe, `test_dac7_blocco_payout` chiedeva l'anno fiscale a `time.gmtime().tm_year` --
    # cioe' 2026 -- mentre i suoi movimenti erano datati 2027, e risultava una BOMBA pur
    # essendo sano. ⚠️ Con un argomento devono restare quelle vere: convertono un istante
    # dato, non dicono che ore sono.
    _time.gmtime = lambda t=None: _vero_gmtime(_adesso() if t is None else t)
    _time.localtime = lambda t=None: _vero_localtime(_adesso() if t is None else t)
    _dt.datetime = _DataOra
    _sq.connect = _connect
    _installato[0] = True


def vai_a(giorni):
    _SCARTO[0] = int(giorni)


def oggi_vero():
    return _vera_dt.fromtimestamp(_vero_time()).date()


def attese(istante, giorni):
    """Le due date che l'orologio spostato DEVE mostrare, calcolate come le calcola lui:
    in SECONDI (`istante + giorni*86400`), non in giorni di calendario.

    ⛔ IL DIFETTO CHE QUESTA FUNZIONE CHIUDE, misurato il 2026-08-14: l'attesa si calcolava
    sommando giorni al CALENDARIO locale, mentre l'orologio si sposta in SECONDI. Le due
    aritmetiche coincidono quasi sempre e divergono a cavallo della mezzanotte -- e quella
    notte tre guardie sane sono risultate rosse.

    ⛔ E PERCHE' SONO DUE, non una. `date.today()`, `datetime.now()` e `time.localtime()`
    rispondono in ora LOCALE; `time.gmtime()` e il `date('now')` di SQLite rispondono in
    UTC. Per un'ora al giorno le due zone stanno in giorni DIVERSI: un solo valore atteso
    non puo' accontentarle entrambe, e chi resta indietro viene accusato da innocente.
    Misurato: un solo atteso calcolato in secondi copre 23 ore su 24 -- non ripara il
    difetto, lo SPOSTA di un'ora. Due attese ne coprono 24 su 24.
    """
    spostato = istante + giorni * 86400.0
    return (_vera_dt.fromtimestamp(spostato).date(),
            _vera_dt.utcfromtimestamp(spostato).date())


# --------------------------------------------------------------------------------------
# chi e' candidato, e chi non e' giudicabile
# --------------------------------------------------------------------------------------
SEGNI_PROCESSO = ("subprocess", "os.system", "Popen", "check_output", "protocollo_d17")


def file_di_test(radice=RADICE):
    return sorted(n for n in os.listdir(radice)
                  if n.startswith("test_") and n.endswith(".py"))


def date_cablate(nome, radice=RADICE, orizzonte=ORIZZONTE, oggi=None):
    """Le date cablate in un file, misurate in GIORNI DA OGGI.

    ⛔ PRIMA QUESTA INFORMAZIONE VENIVA ESTRATTA E BUTTATA VIA. `candidati()` faceva
    esattamente questo lavoro e teneva soltanto il NOME del file: l'unica cosa che l'attrezzo
    sapesse su DOVE guardare la perdeva per strada, e poi campionava due punti su
    quattrocento -- il giorno 0 e l'orizzonte -- scelti senza guardare niente.
    ⚠️ LIMITE DICHIARATO: vede solo le date scritte come STRINGA ISO. La forma
    `datetime.date(2026, 9, 21)` e' invisibile. Misurato il 2026-09-01 su due file gemelli,
    uno per forma:  file_di_test ['test_numerica.py', 'test_stringa.py']  ->  candidati
    ['test_stringa.py']."""
    oggi = oggi or _vera_dt.fromtimestamp(_vero_time()).date()
    fuori = set()
    try:
        with io.open(os.path.join(radice, nome), encoding="utf-8", errors="replace") as f:
            albero = ast.parse(f.read())
    except Exception:
        return fuori
    for n in ast.walk(albero):
        if not (isinstance(n, ast.Constant) and isinstance(n.value, str)):
            continue
        m = _DATA_ISO.match(n.value.strip())
        if not m:
            continue
        try:
            d = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        if abs((d - oggi).days) <= orizzonte:
            fuori.add((d - oggi).days)
    return fuori


def candidati(radice=RADICE, orizzonte=ORIZZONTE, oggi=None):
    """I file che contengono almeno una data cablata entro l'orizzonte. Non e' un giudizio:
    e' solo il modo di non rieseguire tutta la suite due volte per niente."""
    return [nome for nome in file_di_test(radice)
            if date_cablate(nome, radice, orizzonte, oggi)]


def piano_di_campionamento(radice=RADICE, orizzonte=ORIZZONTE, oggi=None, cand=None):
    """DOVE guardare. Ritorna ({scarto: [file...]}, dettaglio).

    Per ogni data cablata FUTURA si prova lo scarto d'orologio che la porta esattamente su
    OGGI. E' li' che quasi tutte le soglie di calendario cambiano parere -- «e' ancora
    futura?», «e' scaduta?», «manca poco?» -- e una sola passata mette tutte le date del
    file a distanze diverse in un colpo solo.

    ⛔ PERCHE' NON UNA GRIGLIA FISSA DI PUNTI, e non e' un'opinione. Misurato il 2026-09-01
    su un banco di 9 forme a verita' nota e sui 147 candidati veri: una griglia di 11 punti
    costa QUATTRO volte questo giro e trova ESATTAMENTE quanto i due punti di prima -- 3
    forme su 6. **La griglia non sa dove guardare; le date lo sanno.** Chi vorra' riparare
    questo attrezzo aggiungendo punti alla cieca ha gia' la misura che dice che non funziona.

    ⚠️ NON SI SALTANO i file con sole date passate. Sembrerebbe gratis -- sono 50 su 147, il
    39 per cento del giro -- e sarebbe un buco nuovo: la forma 9 del banco cabla una data
    PASSATA e resta una bomba, perche' la sua soglia guarda INDIETRO («non piu' vecchia di
    60 giorni») e allontanandosi diventa rossa. Quei file non hanno scarti mirati (non ne
    servono), ma la passata all'orizzonte la ricevono come tutti gli altri."""
    cand = candidati(radice, orizzonte, oggi) if cand is None else cand
    piano, quante_date, senza_future = {}, 0, 0
    for nome in cand:
        distanze = date_cablate(nome, radice, orizzonte, oggi)
        quante_date += len(distanze)
        future = [d for d in distanze if d >= 0]
        if not future:
            senza_future += 1
            continue
        for d in future:
            if 1 <= d <= orizzonte:
                piano.setdefault(d, []).append(nome)
    return piano, {"date_esaminate": quante_date,
                   "file_senza_date_future": senza_future,
                   "scarti_provati": sorted(piano)}


def avvia_processi(modulo, classe, radice=RADICE):
    """⛔ Un test che avvia un processo esterno NON e' giudicabile da qui: il figlio vede
    l'ora vera. Si dichiara, non si conta fra i sani e nemmeno fra le bombe."""
    percorso = os.path.join(radice, modulo + ".py")
    if not os.path.isfile(percorso):
        return None
    try:
        with io.open(percorso, encoding="utf-8", errors="replace") as f:
            sorgente = f.read()
        albero = ast.parse(sorgente)
    except Exception:
        return None
    for n in ast.walk(albero):
        if isinstance(n, ast.ClassDef) and n.name == classe:
            pezzo = ast.get_source_segment(sorgente, n) or ""
            return any(s in pezzo for s in SEGNI_PROCESSO)
    return any(s in sorgente for s in SEGNI_PROCESSO)


# --------------------------------------------------------------------------------------
# il giro
# --------------------------------------------------------------------------------------
def esegui_fuori(nomi, giorni, percorso_extra=None, radice=RADICE):
    """Come `esegui`, ma IN UN PROCESSO NUOVO. ⛔ E non e' uno scrupolo di stile: e' la
    riparazione del quarto difetto di questo attrezzo, misurato il 2026-08-13.

    Parecchi file di test calcolano le loro date **all'import** (`test_happy_admin.py:47`:
    `_BASE = date.today() + timedelta(days=30)`). Facendo le due passate nello stesso
    processo, al secondo giro quel valore e' gia' congelato dal primo: la prenotazione
    risulta nel passato e un test **sano** viene accusato di essere una bomba. Misurato:
    stesso processo -> 1 rosso; processo nuovo -> 0 rossi, sullo stesso identico test.
    💡 Costa un avvio di Python per passata. Vale: l'alternativa e' accusare innocenti, e
    un allarme che accusa innocenti viene spento."""
    import shutil
    import tempfile
    cartella = tempfile.mkdtemp(prefix="bombe_giro_")
    try:
        lista = os.path.join(cartella, "lista.txt")
        uscita = os.path.join(cartella, "esito.json")
        with io.open(lista, "w", encoding="utf-8") as f:
            f.write("\n".join(nomi))
        comando = [sys.executable, os.path.abspath(__file__), "--esegui-json",
                   str(giorni), lista, uscita]
        if percorso_extra:
            comando += ["--percorso", percorso_extra]
        esito = subprocess.run(comando, cwd=radice, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
        if not os.path.isfile(uscita):
            raise RuntimeError(
                "il giro figlio non ha prodotto nessun esito (uscita %d). Un giro senza "
                "esito NON e' un giro verde: %s"
                % (esito.returncode, esito.stderr.decode("utf-8", "replace")[-400:]))
        with io.open(uscita, encoding="utf-8") as f:
            letto = json.load(f)
        return letto["ran"], set(letto["rossi"])
    finally:
        shutil.rmtree(cartella, ignore_errors=True)


def esegui(nomi, giorni):
    """Esegue i test indicati con l'orologio a `giorni`. Ritorna (quanti, insieme dei rossi).
    ⛔ USO INTERNO AL PROCESSO FIGLIO: chi giudica deve chiamare `esegui_fuori`."""
    import unittest
    vai_a(giorni)
    caricatore = unittest.TestLoader()
    suite = unittest.TestSuite()
    for n in nomi:
        try:
            suite.addTests(caricatore.loadTestsFromName(n[:-3] if n.endswith(".py") else n))
        except Exception:
            pass
    esito = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    rossi = set(c.id() for c, _ in list(esito.failures) + list(esito.errors))
    return esito.testsRun, rossi


def giorno_di_esplosione(nome, orizzonte=ORIZZONTE, percorso_extra=None, radice=RADICE,
                         primo_rosso=None):
    """Il primo giorno in cui il test diventa rosso.

    ⛔ DUE STRADE, PERCHE' LE BOMBE NON SONO TUTTE DELLA STESSA SPECIE. Prima ce n'era una
    sola, e la sua docstring diceva «NON si assume che una volta rossa resti rossa» -- ma il
    suo cancello lo assumeva eccome: `if ... not e_rosso(orizzonte): return None`. La
    verifica riguardava il CONFINE, non il RITROVAMENTO. E' lo stesso difetto di `caccia()`,
    un piano piu' giu'.
    · Rossa ANCHE all'orizzonte -> famiglia a GRADINO (una volta rossa resta rossa): si
      dimezza, ed e' esatto.
    · Rossa solo dentro una FINESTRA e gia' guarita all'orizzonte -> dimezzare NON vale: la
      ricerca per dimezzamenti pretende che il rosso non torni verde, e qui torna. Si prende
      allora il primo scarto in cui il PIANO l'ha vista rossa e si guarda il giorno prima.
      Se anche quello e' rosso, il confine vero e' ancora piu' indietro e nessuno l'ha
      campionato: si dichiara NON confermato invece di inventarlo.
    Ritorna (giorni, confermato) oppure (None, False)."""
    def e_rosso(g):
        return bool(esegui_fuori([nome], g, percorso_extra=percorso_extra,
                                 radice=radice)[1])

    if e_rosso(0):
        return None, False
    if e_rosso(orizzonte):
        basso, alto = 0, orizzonte
        while alto - basso > 1:
            mezzo = (basso + alto) // 2
            if e_rosso(mezzo):
                alto = mezzo
            else:
                basso = mezzo
        confermato = (not e_rosso(basso)) and e_rosso(alto)
        return alto, confermato
    if primo_rosso is None or primo_rosso < 1:
        return None, False
    return primo_rosso, not e_rosso(primo_rosso - 1)


def caccia(radice=RADICE, orizzonte=ORIZZONTE, cerca_il_giorno=True,
           percorso_extra=None):
    """Il giro completo. Ritorna un dizionario pronto per lo schedario.

    ⛔ `percorso_extra` E' LA CUCITURA CHE RENDE QUESTO ATTREZZO COLLAUDABILE DA SOLO, e non
    e' un vezzo: senza, `radice` NON arriva al processo figlio (che si rimette sempre su
    RADICE), i moduli di un albero finto non si importano, e `unittest` trasforma ogni
    fallimento d'import in un `_FailedTest` che conta come un test ROSSO.
    Misurato il 2026-09-01 su un albero finto con un solo test:
        esito NON ESEGUITO · eseguiti 1 · rossi_a_orologio_fermo
        ['unittest.loader._FailedTest.test_sempre_rosso']
    cioe' un rosso FINTO, che coprirebbe qualunque difetto vero si stesse provando.
    ⚠️ Il giro vero non la usa (gira sulla radice del progetto): la usa la GUARDIA. E non
    ripara niente -- il campionamento resta quello di prima."""
    if radice not in sys.path:
        sys.path.insert(0, radice)
    os.chdir(radice)
    cand = candidati(radice, orizzonte)
    # ⛔ OGNI PASSATA IN UN PROCESSO NUOVO: vedi `esegui_fuori`. Nello stesso processo, i
    # test che calcolano le date all'import vengono accusati da innocenti.
    quanti, base = esegui_fuori(cand, 0, percorso_extra=percorso_extra, radice=radice)
    if base:
        return {"esito": "NON ESEGUITO", "rossi_a_orologio_fermo": sorted(base),
                "candidati": len(cand), "file_di_test": len(file_di_test(radice)),
                "eseguiti": quanti, "bombe": [], "non_giudicabili": []}
    # [1] la passata all'ORIZZONTE, su TUTTI: prende la famiglia a GRADINO, quella che una
    #     volta rossa resta rossa. E' l'unica che l'attrezzo sapesse vedere.
    _, dopo = esegui_fuori(cand, orizzonte, percorso_extra=percorso_extra, radice=radice)
    trovati = dict((t, orizzonte) for t in (dopo - base))

    # [2] il PIANO: per ogni data cablata futura, lo scarto che la porta su oggi. Prende la
    #     famiglia a FINESTRA -- quella che guarisce da sola e che all'orizzonte e' verde
    #     per costruzione, quindi al passo [1] e' invisibile per quanto lontano si guardi.
    piano, dettaglio = piano_di_campionamento(radice, orizzonte, cand=cand)
    for g in sorted(piano):
        _, rossi = esegui_fuori(piano[g], g, percorso_extra=percorso_extra, radice=radice)
        for t in (rossi - base):
            if g < trovati.get(t, orizzonte + 1):
                trovati[t] = g

    bombe, non_giudicabili = [], []
    for pieno in sorted(trovati):
        pezzi = pieno.split(".")
        modulo, classe = pezzi[0], (pezzi[1] if len(pezzi) > 2 else "")
        if avvia_processi(modulo, classe, radice):
            non_giudicabili.append(pieno)
            continue
        giorni, confermato = (giorno_di_esplosione(pieno, orizzonte, percorso_extra,
                                                   radice, trovati[pieno])
                              if cerca_il_giorno else (trovati[pieno], False))
        voce = {"test": pieno, "giorni": giorni, "confine_confermato": confermato}
        if giorni is not None:
            voce["esplode_il"] = str(oggi_vero() + _dt.timedelta(days=giorni))
        bombe.append(voce)
    vai_a(0)
    esito = {"esito": "OK", "rossi_a_orologio_fermo": [], "candidati": len(cand),
             "file_di_test": len(file_di_test(radice)), "eseguiti": quanti,
             "bombe": bombe, "non_giudicabili": non_giudicabili}
    # ⛔ IL PIANO VA NELLO SCHEDARIO, e non e' un ornamento: senza, `"bombe": []` e' un vuoto
    # che non dice se non c'era niente o se non si e' guardato. Con questi campi quel vuoto
    # diventa «nessuna bomba FRA GLI SCARTI ELENCATI», che e' una misura e si puo' contestare.
    esito.update(dettaglio)
    return esito


# --------------------------------------------------------------------------------------
# lo schedario, che il PRE-VOLO rilegge in millisecondi
# --------------------------------------------------------------------------------------
def scrivi_schedario(esito, radice=RADICE, percorso=SCHEDARIO):
    testa = _git(radice, "rev-parse", "--short", "HEAD")
    esito = dict(esito)
    esito["misurato_il"] = str(oggi_vero())
    esito["commit"] = (testa or "sconosciuto").strip()
    esito["orizzonte_giorni"] = ORIZZONTE
    with io.open(percorso, "w", encoding="utf-8") as f:
        json.dump(esito, f, indent=1, ensure_ascii=False, sort_keys=True)
    return percorso


def leggi_schedario(percorso=SCHEDARIO):
    if not os.path.isfile(percorso):
        return None
    try:
        with io.open(percorso, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _git(radice, *argomenti):
    try:
        e = subprocess.run(["git"] + list(argomenti), cwd=radice,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        return None
    return e.stdout.decode("utf-8", "replace") if e.returncode == 0 else None


def giudizio_dallo_schedario(schedario, oggi=None, giorni_allarme=GIORNI_ALLARME,
                             vecchio=GIORNI_SCHEDARIO_VECCHIO):
    """Il giudizio del PRE-VOLO, in un posto solo. Ritorna (stato, dettaglio).

    ⛔ Sta QUI e non nel pre-volo perche' lo stesso criterio scritto in due posti diverge in
    due modi: e' la malattia che questo progetto ha gia' pagato sei volte in un giorno."""
    if schedario is None:
        return ("NON ESEGUITO",
                "lo schedario delle bombe non c'e' (%s): senza di lui questo controllo non "
                "ha misurato niente. Si rifa' con:  python collaudi/bombe_a_tempo.py --caccia"
                % os.path.basename(SCHEDARIO))
    if schedario.get("esito") != "OK":
        return ("NON ESEGUITO",
                "l'ultimo giro non ha potuto giudicare: %d test erano rossi gia' a orologio "
                "fermo. Un verdetto sul tempo non vale se il rosso c'era gia' prima."
                % len(schedario.get("rossi_a_orologio_fermo") or []))
    oggi = oggi or _vera_dt.fromtimestamp(_vero_time()).date()
    try:
        misurato = _dt.date(*[int(x) for x in schedario["misurato_il"].split("-")])
    except Exception:
        return ("NON ESEGUITO", "lo schedario non dice quando e' stato misurato")
    eta = (oggi - misurato).days
    if eta > vecchio:
        return ("ROSSO",
                "lo schedario delle bombe risale a %d giorni fa (%s, commit %s): oltre %d "
                "giorni non e' piu' una misura, e' un ricordo (D22). Rifallo:\n"
                "      python collaudi/bombe_a_tempo.py --caccia"
                % (eta, schedario["misurato_il"], schedario.get("commit", "?"), vecchio))
    vicine = []
    for b in schedario.get("bombe") or []:
        g = b.get("giorni")
        if g is None:
            continue
        restano = g - eta
        if restano <= giorni_allarme:
            vicine.append((restano, b))
    if vicine:
        # ⛔ SI ORDINA SOLO SUI GIORNI. Un `sort()` nudo su coppie (giorni, dizionario)
        # confronta i DIZIONARI quando i giorni pareggiano, e scoppia con TypeError: il
        # controllo smette di dire «attento» e dice «non ho misurato». Difetto vero del
        # 2026-08-13, trovato dal giro vero -- `test_ical_export` ha due test che scadono
        # lo stesso giorno, che e' il caso piu' normale del mondo.
        vicine.sort(key=lambda coppia: coppia[0])
        righe = ["%s  ->  fra %d giorni (%s)"
                 % (b["test"], restano, b.get("esplode_il", "?"))
                 for restano, b in vicine]
        return ("ROSSO",
                "%d test diventeranno rossi DA SOLI entro %d giorni, senza che nessuno tocchi "
                "il codice. Si riparano scrivendo l'INTENZIONE («fra tre giorni») invece della "
                "cifra sul calendario:\n      %s"
                % (len(vicine), giorni_allarme, "\n      ".join(righe)))
    quante = len(schedario.get("bombe") or [])
    ng = len(schedario.get("non_giudicabili") or [])
    scarti = schedario.get("scarti_provati")
    if scarti is None:
        # ⛔ UNO SCHEDARIO CHE NON DICE DOVE HA GUARDATO NON E' UNA MISURA. Gli schedari
        # scritti prima del 2026-09-01 vengono da un giro che campionava DUE punti, il
        # giorno 0 e l'orizzonte, e che per costruzione non poteva vedere le bombe che
        # guariscono da sole: il suo `"bombe": []` non significa «nessuna bomba», significa
        # «nessun test rosso esattamente fra 400 giorni». Trattarlo come un OK sarebbe
        # ripetere l'errore che questo attrezzo e' stato riparato per non fare piu'.
        return ("ROSSO",
                "lo schedario non dichiara DOVE ha guardato (manca `scarti_provati`): viene "
                "da un giro col campionamento vecchio a due punti, che non poteva vedere le "
                "bombe che guariscono da sole. Il suo «%d bombe» non e' un verdetto. "
                "Rifallo:\n      python collaudi/bombe_a_tempo.py --caccia" % quante)
    return ("OK", "%d bombe note, nessuna entro %d giorni · %d non giudicabili · misurato %d "
                  "giorni fa su %d file candidati (di %d file di test, %d test eseguiti) · "
                  "guardati %d scarti d'orologio su %d date cablate, piu' il giorno 0 e "
                  "l'orizzonte a %d giorni (%d file non avevano date future)"
            % (quante, giorni_allarme, ng, eta, schedario.get("candidati", 0),
               schedario.get("file_di_test", 0), schedario.get("eseguiti", 0),
               len(scarti), schedario.get("date_esaminate", 0),
               schedario.get("orizzonte_giorni", 0),
               schedario.get("file_senza_date_future", 0)))


# --------------------------------------------------------------------------------------
# D18 punto 2: la prova nelle DUE direzioni, che si puo' rifare quando si vuole
# --------------------------------------------------------------------------------------
_GEMELLI = '''# -*- coding: utf-8 -*-
"""Cinque test: tre con la STESSA intenzione scritta in tre modi diversi, piu' due bombe di
famiglie che il campionamento a due punti non sapeva vedere -- quella che GUARISCE DA SOLA e
quella che INVECCHIA."""
import datetime
import unittest

# ⛔ CALCOLATO ALL'IMPORT, e non e' un caso di scuola: `test_happy_admin.py:47` fa
# esattamente cosi'. Un attrezzo che esegue le due passate NELLO STESSO PROCESSO trova
# questo valore gia' congelato al primo giro e accusa un test SANO. Difetto vero del
# 2026-08-13, e il quarto di questo attrezzo.
_ALL_IMPORT = datetime.date.today() + datetime.timedelta(days=%(fra)d)


class TestGemelli(unittest.TestCase):

    def test_LA_BOMBA_data_cablata_dichiarata_futura(self):
        check_out = datetime.date(%(anno)d, %(mese)d, %(giorno)d)
        self.assertGreater(check_out, datetime.date.today())

    def test_IL_SANO_stessa_intenzione_calcolata_da_oggi(self):
        check_out = datetime.date.today() + datetime.timedelta(days=%(fra)d)
        self.assertGreater(check_out, datetime.date.today())

    def test_IL_SANO_2_stessa_intenzione_calcolata_ALL_IMPORT(self):
        self.assertGreater(_ALL_IMPORT, datetime.date.today())

    def test_LA_BOMBA_A_FINESTRA_che_guarisce_da_sola(self):
        # ⛔ LA FAMIGLIA CHE NESSUN ORIZZONTE PUO' VEDERE, e non e' teoria: modella
        # `fase119_calendario_prezzi.py:62` (`return d if d >= 0 else 30`). Passata la data,
        # il codice RIPIEGA su un valore neutro e il test torna VERDE DA SOLO: e' rosso solo
        # dentro una finestra stretta, e verde prima E dopo -- cioe' verde a QUALUNQUE
        # orizzonte, per costruzione.
        # Misurata sul vero il 2026-09-01 (`test_calendario_prezzi`, quattro date cablate):
        # finestra di 6 giorni su 400, scarti -2..+3. I due campioni di `caccia()` -- il
        # giorno 0 e l'orizzonte -- cadono tutti e due FUORI, e non per sfortuna: quello
        # all'orizzonte e' verde sempre, perche' e' li' che tutto e' certamente guarito.
        # ⚠️ LA DATA SI CABLA COME STRINGA APPOSTA, e non e' uno stile: `candidati()` (:209)
        # riconosce solo le date scritte come stringa ISO ed e' CIECO su
        # `datetime.date(2026, 9, 21)`. Misurato il 2026-09-01 su due file gemelli, uno per
        # forma: `candidati` ne ha restituito uno solo, quello con la stringa. Con la forma
        # numerica questo file non sarebbe nemmeno CANDIDATO, e la guardia diventerebbe rossa
        # per il motivo sbagliato (0 candidati) invece che per il campionamento -- un rosso
        # finto, che vale quanto un verde finto.
        arrivo = "%(iso)s"
        y, m, g = (int(x) for x in arrivo.split("-"))
        d = (datetime.date(y, m, g) - datetime.date.today()).days
        distanza = d if d >= 0 else 30
        # ⚠️ Il messaggio dice COSA HA OSSERVATO, non di chi e' la colpa: una guardia che
        # nomina il colpevole sbagliato manda a riparare codice sano.
        self.assertFalse(0 <= distanza <= 2,
                         "distanza osservata dal motore: " + str(distanza))

    def test_LA_BOMBA_CHE_INVECCHIA_data_gia_passata(self):
        # ⛔ LA CONTROPROVA DEL TAGLIO CHE SEMBRA GRATIS, e sta qui per impedirlo.
        # Il 2026-09-01 era stato proposto -- e approvato -- di saltare i file che hanno SOLO
        # date passate: sono 50 su 147, il 39 per cento del giro, e «non possono esplodere
        # andando avanti». E' FALSO, ed e' vero solo per le soglie dal lato FUTURO: qui la
        # data e' gia' passata e la soglia guarda INDIETRO, quindi allontanandosi diventa
        # rossa.
        # Il piano non le assegna nessuno scarto mirato, perche' non ha date future: la
        # prende SOLO il campione all'orizzonte. ⇒ se qualcuno toglie quel campione per
        # risparmiare quel 39 per cento, questa riga diventa rossa LO STESSO GIORNO. E' D18
        # punto 4, e senza di lei il risparmio si rifa' fra sei mesi.
        scritto = "%(iso_vecchio)s"
        y, m, g = (int(x) for x in scritto.split("-"))
        eta = (datetime.date.today() - datetime.date(y, m, g)).days
        self.assertLess(eta, 60, "eta' osservata: " + str(eta))
'''


def autoprova(radice=RADICE):
    """Costruisce i gemelli in una cartella temporanea e PRETENDE due cose diverse:
    (1) che l'OROLOGIO faccia diventare rossa la bomba e lasci verde il sano;
    (2) che la CACCIA se ne accorga -- di tutte e due le famiglie di bomba, non solo di
        quella che resta rossa per sempre.
    Ritorna (riuscita, righe di rapporto)."""
    import shutil
    import tempfile
    fra = 20
    bersaglio = oggi_vero() + _dt.timedelta(days=fra)
    cartella = tempfile.mkdtemp(prefix="bombe_autoprova_")
    righe, riuscita = [], True
    try:
        with io.open(os.path.join(cartella, "test_gemelli_bombe.py"), "w",
                     encoding="utf-8") as f:
            f.write(_GEMELLI % {"anno": bersaglio.year, "mese": bersaglio.month,
                                "giorno": bersaglio.day, "fra": fra,
                                "iso": bersaglio.isoformat(),
                                "iso_vecchio": (oggi_vero()
                                                - _dt.timedelta(days=10)).isoformat()})
        try:
            for giorni, attesa_bomba in ((0, False), (fra + 5, True)):
                # ⛔ NELLO STESSO MODO IN CUI GIRA IL GIRO VERO (processi separati): se
                # l'autoprova provasse un meccanismo diverso da quello usato davvero,
                # sarebbe un ornamento -- proverebbe qualcosa che nessuno esegue.
                _, rossi_pieni = esegui_fuori(["test_gemelli_bombe"], giorni,
                                              percorso_extra=cartella, radice=radice)
                rossi = set(x.split(".")[-1] for x in rossi_pieni)
                bomba_rossa = "test_LA_BOMBA_data_cablata_dichiarata_futura" in rossi
                sano_rosso = "test_IL_SANO_stessa_intenzione_calcolata_da_oggi" in rossi
                # ⛔ IL TERZO E' LA GUARDIA SUL DIFETTO N.4: un test che calcola la data
                # ALL'IMPORT e' sano, e un attrezzo che riusa il processo lo accusa lo stesso.
                import_rosso = "test_IL_SANO_2_stessa_intenzione_calcolata_ALL_IMPORT" in rossi
                ok = (bomba_rossa == attesa_bomba) and not sano_rosso and not import_rosso
                riuscita = riuscita and ok
                righe.append("  %-6s scarto +%-4d  bomba %s (attesa %s)  ·  sano %s  ·  "
                             "sano-all-import %s"
                             % ("OK" if ok else "ROSSO", giorni,
                                "ROSSA" if bomba_rossa else "verde",
                                "ROSSA" if attesa_bomba else "verde",
                                "ROSSO" if sano_rosso else "verde",
                                "ROSSO" if import_rosso else "verde"))

            # ⛔ FIN QUI SI E' PROVATO L'OROLOGIO. ADESSO SI PROVA LA DECISIONE, ed e' una
            # domanda diversa: le righe sopra chiedono «i gemelli diventano rossi quando
            # devono?», questa chiede «e l'attrezzo SE NE ACCORGE?». Il 2026-09-01
            # `test_calendario_prezzi` e' esploso davvero -- stesso commit verde il 29 e
            # rosso il 31 nella tabella della CI -- mentre lo schedario diceva `"bombe": []`.
            # L'orologio non c'entrava niente: funzionava benissimo. A sbagliare era il modo
            # di CERCARE, e nessuna delle prove qui sopra poteva vederlo.
            # ⚠️ Si chiama `caccia()` VERA, non una sua copia: una guardia che rifa' il
            # calcolo per conto proprio resta verde il giorno che `caccia()` cambia, ed e'
            # esattamente il genere di ornamento che questo progetto ha gia' pagato.
            vecchia_cwd = os.getcwd()
            try:
                esito = caccia(radice=cartella, cerca_il_giorno=False,
                               percorso_extra=cartella)
            finally:
                # ⛔ `caccia()` fa `os.chdir(radice)` e non torna indietro: senza questa
                # riga la cartella temporanea resta la cartella corrente e su Windows non
                # si puo' cancellare.
                os.chdir(vecchia_cwd)
            viste = set(b["test"].split(".")[-1] for b in (esito.get("bombe") or []))
            gradino = "test_LA_BOMBA_data_cablata_dichiarata_futura" in viste
            finestra = "test_LA_BOMBA_A_FINESTRA_che_guarisce_da_sola" in viste
            invecchia = "test_LA_BOMBA_CHE_INVECCHIA_data_gia_passata" in viste
            ok = ((esito.get("esito") == "OK") and gradino and finestra and invecchia)
            riuscita = riuscita and ok
            righe.append("  %-6s la CACCIA vede:  gradino %s  ·  finestra %s  ·  invecchia "
                         "%s   (esito %s, %d candidati)"
                         % ("OK" if ok else "ROSSO",
                            "SI" if gradino else "NO",
                            "SI" if finestra else "NO",
                            "SI" if invecchia else "NO",
                            esito.get("esito"), esito.get("candidati", 0)))
            if not finestra:
                righe.append(
                    "         ⛔ la bomba a FINESTRA non e' stata vista. E' verde il giorno "
                    "0 ed e' verde all'orizzonte, e chi guarda SOLO quei due punti non puo' "
                    "vederla: guarisce da sola molto prima di arrivare la'.")
            if not invecchia:
                righe.append(
                    "         ⛔ la bomba che INVECCHIA non e' stata vista. La sua data e' "
                    "gia' passata, quindi il piano non le assegna nessuno scarto mirato: la "
                    "prende SOLO il campione all'orizzonte. Se quello e' stato tolto per "
                    "risparmiare il 39 per cento del giro, questa riga e' il motivo per cui "
                    "non si poteva.")
        finally:
            vai_a(0)
    finally:
        shutil.rmtree(cartella, ignore_errors=True)
    return riuscita, righe


# --------------------------------------------------------------------------------------
def _stampa_non_guarda():
    print("-" * 86)
    print("⛔ COSA QUESTO ATTREZZO NON HA ESAMINATO (D18 punto 3)")
    for r in NON_GUARDA:
        print("   · %s" % r)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    if "--autoprova" in argv:
        print("=" * 86)
        print("🔁 AUTOPROVA — l'attrezzo si vede gridare e tacere (D18 punto 2)")
        print("=" * 86)
        riuscita, righe = autoprova()
        for r in righe:
            print(r)
        _stampa_non_guarda()
        print("=" * 86)
        if not riuscita:
            print("VERDETTO: ⛔ L'ATTREZZO NON E' AFFIDABILE — non si comporta come promette.")
            return 1
        print("VERDETTO: ✅ grida sulla data cablata e tace su quella calcolata da oggi.")
        return 0

    if "--esegui-json" in argv:
        # ⛔ MODALITA' FIGLIO, non si chiama a mano. Esiste perche' ogni passata deve girare
        # in un processo NUOVO: vedi `esegui_fuori`. Il padre legge il JSON che scriviamo.
        i = argv.index("--esegui-json")
        giorni_f, lista_f, uscita_f = int(argv[i + 1]), argv[i + 2], argv[i + 3]
        if "--percorso" in argv:
            sys.path.insert(0, argv[argv.index("--percorso") + 1])
        installa_orologio()
        vai_a(giorni_f)
        if RADICE not in sys.path:
            sys.path.insert(0, RADICE)
        os.chdir(RADICE)
        with io.open(lista_f, encoding="utf-8") as f:
            nomi_f = [r.strip() for r in f if r.strip()]
        quanti_f, rossi_f = esegui(nomi_f, giorni_f)
        with io.open(uscita_f, "w", encoding="utf-8") as f:
            json.dump({"ran": quanti_f, "rossi": sorted(rossi_f)}, f)
        return 0

    if "--prova-orologio" in argv:
        # ⛔ SI USA DA UN PROCESSO A PARTE, MAI DENTRO LA SUITE: installare l'orologio finto
        # nel processo che sta eseguendo i test falserebbe TUTTI gli altri. Serve alle
        # guardie di `test_pipeline_ci.py`, che lo interrogano da fuori e leggono queste
        # righe. Stampa quello che i DUE orologi vedono, cosi' un doppio conteggio o un
        # SQLite rimasto indietro si vedono a occhio nudo invece di falsare un verdetto.
        _i = argv.index("--prova-orologio")
        giorni = int(argv[_i + 1])
        # ISTANTE opzionale (secondi dall'epoca): serve alla guardia delle 24 ore per
        # COSTRUIRE a mano l'ora in cui le due zone stanno in giorni diversi, invece di
        # aspettare mezzanotte per accorgersene (D19). Senza, vale l'ora vera di adesso.
        if len(argv) > _i + 2 and not argv[_i + 2].startswith("--"):
            _BASE[0] = float(argv[_i + 2])
        atteso, atteso_utc = attese(
            _vero_time() if _BASE[0] is None else _BASE[0], giorni)
        installa_orologio()
        vai_a(giorni)
        con = _sq.connect(":memory:")
        print("chiesto      %d" % giorni)
        print("atteso       %s" % atteso)
        print("atteso_utc   %s" % atteso_utc)
        print("python_date  %s" % _dt.date.today())
        print("python_now   %s" % _dt.datetime.now().date())
        print("time_gmtime  %s" % _time.strftime("%Y-%m-%d", _time.gmtime()))
        print("time_local   %s" % _time.strftime("%Y-%m-%d", _time.localtime()))
        print("sqlite_now   %s" % con.execute("SELECT date('now')").fetchone()[0])
        print("sqlite_fissa %s" % con.execute(
            "SELECT date('2026-07-01')").fetchone()[0])
        return 0

    if "--giudizio" in argv:
        stato, dettaglio = giudizio_dallo_schedario(leggi_schedario())
        print("%s  %s" % (stato, dettaglio))
        return 0 if stato == "OK" else 1

    if "--caccia" not in argv:
        print(__doc__)
        # ⛔ IL COSTO E' MISURATO, NON STIMATO -- e la stima che c'era qui era falsa di sei
        # volte. Diceva «~25 minuti», provenienza ignota, e ci si era costruita sopra una
        # seconda stima («66 minuti») che ne ereditava l'errore. Il numero qui sotto porta
        # la sua provenienza, come pretende D22: chi lo legge sa DOVE e QUANDO e' stato preso.
        # ⚠️ E non e' un dato dello strumento: e' lo strumento PIU' il carico della macchina.
        print("USO:  python collaudi/bombe_a_tempo.py --caccia"
              "      (lungo: 156 minuti misurati il 2026-09-01, albero principale,"
              " 147 candidati, 123 scarti su 703 date)")
        print("      python collaudi/bombe_a_tempo.py --autoprova   (secondi)")
        print("      python collaudi/bombe_a_tempo.py --giudizio    (millisecondi)")
        return 0

    print("=" * 86)
    print("💣 CACCIA ALLE BOMBE A TEMPO — si sposta l'orologio e si guarda chi diventa rosso")
    print("=" * 86)
    riuscita, righe = autoprova()
    for r in righe:
        print(r)
    if not riuscita:
        print("⛔ FERMO: l'autoprova e' fallita. Un attrezzo che non si comporta come promette")
        print("   non puo' giudicare nessuno (D18 punto 1).")
        return 1
    print("-" * 86)
    esito = caccia()
    if esito["esito"] != "OK":
        print("⛔ NON ESEGUITO — %d test sono rossi GIA' a orologio fermo:"
              % len(esito["rossi_a_orologio_fermo"]))
        for r in esito["rossi_a_orologio_fermo"][:10]:
            print("     %s" % r)
        print("   Il verdetto sul tempo non varrebbe: non si saprebbe se il rosso l'ha")
        print("   causato il calendario o qualcos'altro.")
        _stampa_non_guarda()
        return 1
    print("  candidati: %d file su %d di test  ·  %d test eseguiti a orologio fermo, 0 rossi"
          % (esito["candidati"], esito["file_di_test"], esito["eseguiti"]))
    print("  piano: %d scarti d'orologio ricavati da %d date cablate, piu' il giorno 0 e "
          "l'orizzonte a %d  ·  %d file non hanno date future"
          % (len(esito.get("scarti_provati") or []), esito.get("date_esaminate", 0),
             ORIZZONTE, esito.get("file_senza_date_future", 0)))
    print("-" * 86)
    print("💣 BOMBE DIMOSTRATE: %d" % len(esito["bombe"]))
    for b in sorted(esito["bombe"], key=lambda x: (x["giorni"] is None, x["giorni"])):
        print("   fra %4s giorni  (%s)%s  %s"
              % (b["giorni"], b.get("esplode_il", "?"),
                 "" if b["confine_confermato"] else "  ⚠️ CONFINE NON CONFERMATO", b["test"]))
    if esito["non_giudicabili"]:
        print("⚠️ NON GIUDICABILI (avviano processi esterni, che vedono l'ora vera): %d"
              % len(esito["non_giudicabili"]))
        for n in esito["non_giudicabili"]:
            print("     %s" % n)
    percorso = scrivi_schedario(esito)
    print("-" * 86)
    print("schedario scritto in %s" % os.path.basename(percorso))
    _stampa_non_guarda()
    print("=" * 86)
    return 0


if __name__ == "__main__":
    sys.exit(main())
