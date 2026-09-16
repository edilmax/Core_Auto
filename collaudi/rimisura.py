"""RIMISURA — dopo OGNI unione in `master`, gli attrezzi delle caselle SCADUTE si rilanciano in fila.

    python collaudi/rimisura.py                     esegue i comandi RAPIDI; i giri di mutazione li SALTA e lo dice
    python collaudi/rimisura.py --anche-mutazione   esegue anche i giri di mutazione (dichiarano ore: 60 e 600 minuti)
    python collaudi/rimisura.py --salta PAROLA      salta i comandi che contengono PAROLA (ripetibile), e li DICHIARA
    python collaudi/rimisura.py --elenca            elenca soltanto, come `scheda.py --rimisura`: non esegue niente
    python collaudi/rimisura.py --autoprova         si prova nelle due direzioni su comandi finti (D18 punto 2)

PERCHE' ESISTE (regola del fondatore, 2026-09-16). Ogni casella e' legata all'impronta dei moduli del suo
blocco: un'unione che li tocca la fa SCADERE, ed e' giusto (la misura parlava del codice di allora). Ma
dall'11 al 16 settembre ci sono state 18 unioni e NESSUNA rimisura: il conto e' sceso da 25 su 42 a 3 su 43
senza che una sola prova fallisse. Il numero misurava «quanto sono fresche le misure», non «quanto lavoro e'
finito», e nessuno lo diceva. La regola nuova: DOPO OGNI UNIONE, PRIMA DI APRIRE LAVORO NUOVO, si lancia
questo comando; finche' restano caselle scadute, `prima_di_lanciare.py --scopo` non lascia dichiarare uno
scopo che tocca la produzione (il blocco e' meccanico, non una frase in un documento: S19, D22).

COSA FA. Legge i comandi da `scheda.da_rimisurare()` -- la stessa fonte di `scheda.py --rimisura`, mai una
copia --, li esegue UNO ALLA VOLTA (due giri insieme si sporcano a vicenda: regola ferrea 4), legge ogni
codice d'uscita DIRETTO (ferrea 7), scrive il registro di ognuno in una cartella FUORI dal repository e
rilegge dalla scheda se la casella e' tornata spuntata. In fondo stampa la tabella e un verdetto che segue
i fatti: FINITO (uscita 0) solo se ogni comando e' uscito 0, ogni casella e' spuntata, e niente e' stato
saltato o lasciato «a mano». Altrimenti NON FINITO (uscita 1), e dice cosa manca.

⛔ D18: (1) misura prima se stesso (`precondizioni`: git, scheda, piano, interprete); (2) `--autoprova` lo
vede gridare su un comando che fallisce e tacere su uno che passa; (3) dichiara cosa NON esegue (i saltati,
gli «a mano» e `NON_GUARDA`, stampati a ogni giro); (4) sotto guardia:
`test_pipeline_ci.TestLaRimisuraNonPuoBARARE`.
"""
import contextlib
import datetime
import io
import os
import shlex
import shutil
import subprocess  # nosec B404 - esegue gli attrezzi del progetto: comandi letti dalla scheda, mai input esterno
import sys
import tempfile
import time

QUI = os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(QUI)
for _p in (RADICE, QUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)

with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import scheda  # noqa: E402

PAROLA_MUTAZIONE = "mutazione_prodotto.py"
REGISTRI = os.path.join(tempfile.gettempdir(), "bookinvip_rimisure")
TETTO_SECONDI = 3600           # un attrezzo rapido che non finisce in un'ora e' un attrezzo appeso, non lento

NON_GUARDA = (
    "esegue SOLO i comandi delle caselle SCADUTE: le «mai misurate» e le ROSSE non sono una ri-misura e "
    "restano com'erano (le rosse si rileggono in `python collaudi/piano.py`, col loro motivo)",
    "i giri di mutazione (%s) li salta di default: dichiarano 60 e 600 minuti, si lanciano con "
    "--anche-mutazione, staccati, e mentre girano non si tocca niente (ferrea 4)" % PAROLA_MUTAZIONE,
    "i comandi «a mano» (con un segnaposto fra <>) vogliono materiale preso sul server: li elenca, non li esegue",
    "non giudica gli attrezzi che lancia: legge il loro codice d'uscita e lo stato che lasciano nella scheda",
    "non pretende l'albero pulito: lo STAMPA (git status); gli attrezzi registrano il commit HEAD, e i file "
    "modificati non ci sono dentro",
    "non e' la suite: le guardie sui documenti e sulla scheda le esegue solo `unittest discover`",
)


def precondizioni(radice=RADICE):
    """(tutte_ok, righe). Un metro storto va scoperto dal metro, non dal muro (D18 punto 1)."""
    righe = []
    commit = scheda.commit_attuale(radice)
    righe.append(("git risponde (HEAD %s)" % (commit or "?"), bool(commit)))
    dati = scheda.leggi()
    righe.append(("la scheda esiste e ha delle righe (%d)" % len(dati),
                  os.path.isfile(scheda.SCHEDA) and bool(dati)))
    try:
        blocchi = scheda._blocchi()
    except Exception:  # noqa: BLE001 - un piano che non si legge e' una precondizione rossa, non un'eccezione da nascondere
        blocchi = []
    righe.append(("il piano si legge (%d blocchi)" % len(blocchi), bool(blocchi)))
    righe.append(("l'interprete esiste (%s)" % sys.executable, os.path.isfile(sys.executable)))
    return all(ok for _, ok in righe), righe


def elenca():
    """(comandi eseguibili, comandi a mano): senza doppioni, nell'ordine dei blocchi, dalla scheda."""
    eseguibili, a_mano = scheda.da_rimisurare()
    comandi, manuali = [], []
    for v in eseguibili:
        if v["comando"] not in comandi:
            comandi.append(v["comando"])
    for v in a_mano:
        if v["comando"] not in manuali:
            manuali.append(v["comando"])
    return comandi, manuali


def dividi(comandi, anche_mutazione=False, salta=()):
    """(da_fare, saltati): la mutazione resta fuori finche' non la si chiede; `salta` toglie per parola."""
    da_fare, saltati = [], []
    for c in comandi:
        if (PAROLA_MUTAZIONE in c and not anche_mutazione) or any(p and p in c for p in salta):
            saltati.append(c)
        else:
            da_fare.append(c)
    return da_fare, saltati


def _in_lista(comando):
    """Il comando della scheda come lista per subprocess: `python` diventa QUESTO interprete."""
    pezzi = shlex.split(comando, posix=True)
    if pezzi and pezzi[0] in ("python", "python3", "py"):
        pezzi[0] = sys.executable
    return pezzi


def _tetto(comando):
    """I giri di mutazione dichiarano i loro minuti (`--minuti N`): il tetto li rispetta, con margine."""
    pezzi = comando.split()
    if "--minuti" in pezzi:
        with contextlib.suppress(ValueError, IndexError):
            return int(pezzi[pezzi.index("--minuti") + 1]) * 90 + 600
    return TETTO_SECONDI


def _nome(comando):
    for pezzo in comando.split():
        if pezzo.startswith("collaudi/") and pezzo.endswith(".py"):
            return pezzo[len("collaudi/"):-3]
    return "comando"


def esegui(comandi, cartella, radice=RADICE):
    """Uno alla volta. Per ognuno: comando, uscita (intero, oppure "SCADUTO"), secondi, registro."""
    os.makedirs(cartella, exist_ok=True)
    esiti = []
    for n, comando in enumerate(comandi, 1):
        registro = os.path.join(cartella, "%02d_%s.log" % (n, _nome(comando)))
        t0 = time.time()
        with io.open(registro, "w", encoding="utf-8", errors="replace") as f:
            f.write("COMANDO: %s\nINIZIO: %s\n\n"
                    % (comando, datetime.datetime.now().isoformat(timespec="seconds")))
            f.flush()
            try:
                p = subprocess.run(  # nosec B603 - comandi letti dalla scheda del progetto, mai input esterno  # noqa: S603
                    _in_lista(comando), cwd=radice, stdout=f, stderr=subprocess.STDOUT,
                    timeout=_tetto(comando), env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                uscita = p.returncode
            except subprocess.TimeoutExpired:
                uscita = "SCADUTO"
            f.write("\nUSCITA_DIRETTA=%s\nFINE: %s\n"
                    % (uscita, datetime.datetime.now().isoformat(timespec="seconds")))
        secondi = time.time() - t0
        esiti.append({"comando": comando, "uscita": uscita, "secondi": secondi, "registro": registro})
        print("  %-6s %6.0fs  %s" % ("OK" if uscita == 0 else "ROSSO", secondi, comando[:100]))
    return esiti


def caselle_di(comando, dati=None):
    """(spuntate, non_spuntate) fra le caselle che la scheda lega a QUESTO comando, rilette adesso."""
    dati = scheda.leggi() if dati is None else dati
    spuntate, non_spuntate = [], []
    for blocco in scheda._blocchi():
        for testo in blocco.get("finito_quando") or ():
            riga = dati.get(scheda.chiave(testo, blocco["ordine"]))
            if isinstance(riga, dict) and riga.get("comando") == comando:
                ok, motivo = scheda.stato(testo, blocco["ordine"], schedario=dati)
                (spuntate if ok else non_spuntate).append((blocco["ordine"], testo[:60], motivo))
    return spuntate, non_spuntate


def verdetto(esiti, saltati, a_mano, non_spuntate=()):
    """0 = FINITO, 1 = NON FINITO. Segue i fatti: un rosso, un saltato o un «a mano» bastano da soli."""
    rossi = [e for e in esiti if e["uscita"] != 0]
    return 0 if not (rossi or saltati or a_mano or non_spuntate) else 1


def autoprova():
    """Le due direzioni su comandi finti (D18 punto 2): grida su chi esce 1, tace su chi esce 0."""
    righe, riuscita = [], True
    cartella = tempfile.mkdtemp(prefix="rimisura_autoprova_")
    finto = 'python -c "import sys; sys.exit(%d)"'
    mutazione = ["python collaudi/mutazione_prodotto.py --modulo x.py --minuti 1"]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            buoni = esegui([finto % 0, finto % 0], cartella)
            misti = esegui([finto % 0, finto % 1], cartella)
        casi = (
            ("due comandi verdi -> FINITO (uscita 0)", verdetto(buoni, [], []) == 0),
            ("un comando rosso -> NON FINITO (uscita 1)", verdetto(misti, [], []) == 1),
            ("le uscite si leggono DIRETTE (0 e 1)", [e["uscita"] for e in misti] == [0, 1]),
            ("ogni comando lascia il suo registro", all(os.path.isfile(e["registro"]) for e in misti)),
            ("un saltato basta a NON finire", verdetto(buoni, ["x"], []) == 1),
            ("un «a mano» basta a NON finire", verdetto(buoni, [], ["y"]) == 1),
            ("la mutazione si salta di default", dividi(mutazione) == ([], mutazione)),
            ("...e si esegue solo se chiesta", dividi(mutazione, anche_mutazione=True) == (mutazione, [])),
            ("--salta toglie per parola e dichiara", dividi(["python collaudi/a.py"], salta=("a.py",)) == ([], ["python collaudi/a.py"])),
        )
        for nome, ok in casi:
            riuscita = riuscita and ok
            righe.append("  %-4s %s" % ("OK" if ok else "NO", nome))
    finally:
        shutil.rmtree(cartella, ignore_errors=True)
    return riuscita, righe


def _stampa_non_guarda():
    print("-" * 86)
    print("⛔ COSA QUESTO COMANDO NON FA (D18 punto 3)")
    for r in NON_GUARDA:
        print("   · %s" % r)


def _git_status(radice=RADICE):
    try:
        p = subprocess.run(  # nosec B603 B607 - git, argomenti fissi  # noqa: S603 S607
            ["git", "status", "--porcelain"], cwd=radice, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return [r for r in p.stdout.splitlines() if r.strip()] if p.returncode == 0 else None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    print("=" * 86)
    print("🔁 RIMISURA — dopo ogni unione, le caselle SCADUTE si rimisurano PRIMA di aprire lavoro nuovo")
    print("=" * 86)
    if "--autoprova" in argv:
        riuscita, righe = autoprova()
        print("AUTOPROVA — il lanciatore si vede gridare e tacere su comandi finti (D18 punto 2)")
        for r in righe:
            print(r)
        _stampa_non_guarda()
        print("VERDETTO: %s" % ("✅ il lanciatore distingue un rosso da un verde" if riuscita
                                else "⛔ IL LANCIATORE NON E' AFFIDABILE"))
        return 0 if riuscita else 1
    tutte_ok, righe = precondizioni()
    print("PRIMA DI LANCIARE, IL LANCIATORE MISURA SE STESSO (D18 punto 1)")
    for nome, ok in righe:
        print("  %-6s %s" % ("OK" if ok else "⛔ NO", nome))
    if not tutte_ok:
        print("VERDETTO: ⛔ FERMO — una precondizione non regge: non lancio niente e non dichiaro niente finito.")
        return 2
    salta = tuple(argv[i + 1] for i, a in enumerate(argv) if a == "--salta" and i + 1 < len(argv))
    comandi, a_mano = elenca()
    da_fare, saltati = dividi(comandi, anche_mutazione="--anche-mutazione" in argv, salta=salta)
    print("caselle scadute: %d comando/i -> %d da eseguire ora, %d saltato/i, %d a mano"
          % (len(comandi), len(da_fare), len(saltati), len(a_mano)))
    for c in da_fare:
        print("  ESEGUO  %s" % c[:110])
    for c in saltati:
        print("  SALTO   %s" % c[:110])
    for c in a_mano:
        print("  A MANO  %s" % c[:110])
    if "--elenca" in argv:
        print("(--elenca: non eseguo niente)")
        return 0 if not comandi and not a_mano else 1
    stato = _git_status()
    if stato is None:
        print("⚠️  git status non si legge: non so se l'albero e' pulito")
    elif stato:
        print("⚠️  albero NON pulito (%d file): gli attrezzi registrano il commit HEAD, ma i file modificati "
              "non ci sono dentro" % len(stato))
        for r in stato[:12]:
            print("     %s" % r)
    cartella = os.path.join(REGISTRI, datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    print("registri in %s" % cartella)
    print("-" * 86)
    esiti = esegui(da_fare, cartella)
    print("-" * 86)
    dati = scheda.leggi()
    non_spuntate = []
    for e in esiti:
        spuntate, non_sp = caselle_di(e["comando"], dati)
        non_spuntate.extend(non_sp)
        for ordine, testo, _motivo in spuntate:
            print("  ☑ blocco %d  %s" % (ordine, testo))
        for ordine, testo, motivo in non_sp:
            print("  ☐ blocco %d  %s -- %s" % (ordine, testo, motivo[:90]))
    codice = verdetto(esiti, saltati, a_mano, non_spuntate)
    _stampa_non_guarda()
    print("=" * 86)
    print("VERDETTO: %s — eseguiti %d (rossi %d) · caselle non spuntate %d · saltati %d · a mano %d"
          % ("✅ FINITO" if codice == 0 else "⛔ NON FINITO", len(esiti),
             sum(1 for e in esiti if e["uscita"] != 0), len(non_spuntate), len(saltati), len(a_mano)))
    print("   il conto della macchina, adesso:  python collaudi/piano.py")
    return codice


if __name__ == "__main__":
    sys.exit(main())
