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
Poi, per dimezzamenti, si trova **il giorno esatto** in cui esplode -- e quel giorno si
verifica nelle due direzioni (verde il giorno prima, rosso quel giorno), mai dedotto.

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
   2. **provato nelle DUE direzioni**: `--autoprova` costruisce due test gemelli -- uno con la
      data CABLATA, uno con la stessa intenzione calcolata da oggi -- e pretende di vedere il
      primo rosso e il secondo verde. Se non li vede, esce 1;
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
)


# --------------------------------------------------------------------------------------
# l'orologio finto: Python + SQLite, da un'unica sorgente di verita'
# --------------------------------------------------------------------------------------
_SCARTO = [0]
_vero_time = _time.time
_vero_gmtime = _time.gmtime
_vero_localtime = _time.localtime
_vera_dt = _dt.datetime
_vera_connect = _sq.connect
_aux = _vera_connect(":memory:")     # connessione di servizio, mai patchata
_installato = [False]


def _adesso():
    return _vero_time() + _SCARTO[0] * 86400.0


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


# --------------------------------------------------------------------------------------
# chi e' candidato, e chi non e' giudicabile
# --------------------------------------------------------------------------------------
SEGNI_PROCESSO = ("subprocess", "os.system", "Popen", "check_output", "protocollo_d17")


def file_di_test(radice=RADICE):
    return sorted(n for n in os.listdir(radice)
                  if n.startswith("test_") and n.endswith(".py"))


def candidati(radice=RADICE, orizzonte=ORIZZONTE, oggi=None):
    """I file che contengono almeno una data cablata entro l'orizzonte. Non e' un giudizio:
    e' solo il modo di non rieseguire tutta la suite due volte per niente."""
    oggi = oggi or _vera_dt.fromtimestamp(_vero_time()).date()
    fuori = []
    for nome in file_di_test(radice):
        try:
            with io.open(os.path.join(radice, nome), encoding="utf-8", errors="replace") as f:
                albero = ast.parse(f.read())
        except Exception:
            continue
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
                fuori.append(nome)
                break
    return fuori


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


def giorno_di_esplosione(nome, orizzonte=ORIZZONTE):
    """Il primo giorno in cui il test diventa rosso, per dimezzamenti.

    ⛔ NON si assume che «una volta rossa resti rossa»: trovato il confine, si VERIFICA che
    il giorno prima sia verde e quel giorno sia rosso. Un confine dedotto non e' misurato.
    Ritorna (giorni, confermato) oppure (None, False)."""
    def e_rosso(g):
        return bool(esegui_fuori([nome], g)[1])

    if e_rosso(0) or not e_rosso(orizzonte):
        return None, False
    basso, alto = 0, orizzonte
    while alto - basso > 1:
        mezzo = (basso + alto) // 2
        if e_rosso(mezzo):
            alto = mezzo
        else:
            basso = mezzo
    confermato = (not e_rosso(basso)) and e_rosso(alto)
    return alto, confermato


def caccia(radice=RADICE, orizzonte=ORIZZONTE, cerca_il_giorno=True):
    """Il giro completo. Ritorna un dizionario pronto per lo schedario."""
    if radice not in sys.path:
        sys.path.insert(0, radice)
    os.chdir(radice)
    cand = candidati(radice, orizzonte)
    # ⛔ OGNI PASSATA IN UN PROCESSO NUOVO: vedi `esegui_fuori`. Nello stesso processo, i
    # test che calcolano le date all'import vengono accusati da innocenti.
    quanti, base = esegui_fuori(cand, 0, radice=radice)
    if base:
        return {"esito": "NON ESEGUITO", "rossi_a_orologio_fermo": sorted(base),
                "candidati": len(cand), "file_di_test": len(file_di_test(radice)),
                "eseguiti": quanti, "bombe": [], "non_giudicabili": []}
    _, dopo = esegui_fuori(cand, orizzonte, radice=radice)
    bombe, non_giudicabili = [], []
    for pieno in sorted(dopo - base):
        pezzi = pieno.split(".")
        modulo, classe = pezzi[0], (pezzi[1] if len(pezzi) > 2 else "")
        if avvia_processi(modulo, classe, radice):
            non_giudicabili.append(pieno)
            continue
        giorni, confermato = (giorno_di_esplosione(pieno, orizzonte)
                              if cerca_il_giorno else (None, False))
        voce = {"test": pieno, "giorni": giorni, "confine_confermato": confermato}
        if giorni is not None:
            voce["esplode_il"] = str(oggi_vero() + _dt.timedelta(days=giorni))
        bombe.append(voce)
    vai_a(0)
    return {"esito": "OK", "rossi_a_orologio_fermo": [], "candidati": len(cand),
            "file_di_test": len(file_di_test(radice)), "eseguiti": quanti,
            "bombe": bombe, "non_giudicabili": non_giudicabili}


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
    return ("OK", "%d bombe note, nessuna entro %d giorni · %d non giudicabili · misurato %d "
                  "giorni fa su %d file candidati (di %d file di test, %d test eseguiti)"
            % (quante, giorni_allarme, ng, eta, schedario.get("candidati", 0),
               schedario.get("file_di_test", 0), schedario.get("eseguiti", 0)))


# --------------------------------------------------------------------------------------
# D18 punto 2: la prova nelle DUE direzioni, che si puo' rifare quando si vuole
# --------------------------------------------------------------------------------------
_GEMELLI = '''# -*- coding: utf-8 -*-
"""Tre test con la STESSA intenzione, scritta in tre modi diversi."""
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
'''


def autoprova(radice=RADICE):
    """Costruisce i due gemelli in una cartella temporanea e PRETENDE di vedere la bomba
    rossa e il sano verde. Ritorna (riuscita, righe di rapporto)."""
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
                                "giorno": bersaglio.day, "fra": fra})
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
        giorni = int(argv[argv.index("--prova-orologio") + 1])
        atteso = oggi_vero() + _dt.timedelta(days=giorni)
        installa_orologio()
        vai_a(giorni)
        con = _sq.connect(":memory:")
        print("chiesto      %d" % giorni)
        print("atteso       %s" % atteso)
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
        print("USO:  python collaudi/bombe_a_tempo.py --caccia      (lungo: ~25 minuti)")
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
