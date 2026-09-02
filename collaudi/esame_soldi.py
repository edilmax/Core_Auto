"""L'ESAME DEL BLOCCO SOLDI — misura due caselle e le scrive nella scheda.

    python collaudi/esame_soldi.py            misura e MOSTRA, senza scrivere
    python collaudi/esame_soldi.py --scrivi   misura e SCRIVE nella scheda
    python collaudi/esame_soldi.py --autoprova   si vede gridare e tacere (D18 punto 2)

Le due caselle sono la PRIMA e la QUARTA del blocco SOLDI: quella sulle dimostrazioni
matematiche (girano in CI? i test che le portano si saltano?) e quella sulle relazioni
metamorfiche dell'aritmetica del denaro. Il testo esatto si legge dal piano.

⛔ IL TESTO DELLE CASELLE NON SI RICOPIA, NEMMENO QUI DENTRO IN UN COMMENTO: si legge da
   `collaudi/piano.py`. Una copia a mano spunterebbe una casella DIVERSA il giorno che il
   piano cambia una virgola, e nessuno se ne accorgerebbe -- la chiave della scheda e' il
   testo.
   💡 E questa riga non e' teorica: la prima stesura di questo file le RICOPIAVA tutt'e due
   qui sopra, e la guardia `test_IL_TESTO_DELLE_CASELLE_NON_E_RICOPIATO_A_MANO` l'ha preso
   al primo giro. Una delle due copie sfuggiva soltanto perche' un a-capo la spezzava: una
   copia che coincide QUASI e' peggio di una che coincide, perche' nessuno la trova.

⛔ E I CRITERI NON SI RISCRIVONO QUI. Questo attrezzo non decide da se' se le prove z3 sono
   collegate o se le relazioni reggono: ESEGUE le guardie che gia' lo dicono, e legge il
   loro esito. Una seconda copia del criterio e' la malattia che la scheda esiste per
   curare -- due giudici che rispondono diverso, e nessuno che sappia quale credere.

⛔ D18, LE QUATTRO CONDIZIONI DI UNO STRUMENTO CHE MISURA:
   1. misura PRIMA se stesso: `precondizioni()` ferma il giro invece di stampare un numero;
   2. provato nelle DUE direzioni: `--autoprova` lo vede gridare col guasto e tacere sano;
   3. dichiara cosa NON ha esaminato: `NON_GUARDA`, stampato a ogni giro;
   4. e' a sua volta sotto guardia: `test_pipeline_ci.TestLEsameDeiSoldiNonPuoBARARE`.
"""
import io
import os
import sys
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(QUI)
for _p in (RADICE, QUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import scheda  # noqa: E402
from piano import BLOCCHI  # noqa: E402

BLOCCO_SOLDI = 1

NON_GUARDA = (
    "se il CI ha DAVVERO eseguito quelle prove nell'ultimo giro: quello si legge dalla "
    "tabella dei job (regola ferrea 8), non da qui. Questo attrezzo misura che ogni job "
    "che le raggiunge installa z3, e che nell'ambiente in cui gira non si saltano",
    "se le relazioni metamorfiche siano le relazioni GIUSTE: dice che quelle scritte "
    "reggono e sanno accendersi, non che coprano tutta l'aritmetica del denaro",
    "l'iniezione dei guasti e' al CONFINE OSSERVABILE (l'uscita delle funzioni), non dentro "
    "il corpo: prova che le relazioni vedono QUELLA deviazione, non ogni difetto interno",
    "le altre quattro caselle del blocco (rimborsi da ogni strada, orologi Stripe, "
    "mutazione sul percorso del denaro, invarianti in produzione): non le tocca",
)


# --------------------------------------------------------------------------------------
# 1. MISURA PRIMA SE STESSO (D18 punto 1)
# --------------------------------------------------------------------------------------
def precondizioni():
    """(tutte_ok, [(nome, ok, motivo)]). Un metro storto va scoperto dal metro."""
    fuori = []

    try:
        import z3
        fuori.append(("z3 e' importabile qui", True, z3.get_version_string()))
    except Exception as e:
        fuori.append(("z3 e' importabile qui", False,
                      "senza z3 i test si saltano LEGITTIMAMENTE, quindi da qui non si puo' "
                      "sapere se si saltano per un ALTRO motivo: la domanda della casella "
                      "non e' misurabile in questo ambiente (%s)" % e))

    try:
        import hypothesis
        fuori.append(("hypothesis e' importabile qui", True, hypothesis.__version__))
    except Exception as e:
        fuori.append(("hypothesis e' importabile qui", False, str(e)))

    try:
        import test_pipeline_ci as TPC
        moduli = TPC._moduli_di_test_con_prove_z3()
        fuori.append(("i moduli con prove z3 si derivano", bool(moduli),
                      "%d moduli: %s" % (len(moduli), ", ".join(sorted(moduli)))
                      if moduli else "NESSUNO: o sono spariti, o la derivazione si e' rotta. "
                                     "Il vuoto non e' un valore (sbaglio S1)"))
    except Exception as e:
        fuori.append(("i moduli con prove z3 si derivano", False, str(e)))

    try:
        import test_property_soldi as TPS
        rel = TPS._tutte_le_relazioni()
        fuori.append(("le relazioni metamorfiche si contano", bool(rel),
                      "%d relazioni" % len(rel) if rel else "NESSUNA relazione dichiarata"))
    except Exception as e:
        fuori.append(("le relazioni metamorfiche si contano", False, str(e)))

    try:
        impronta = scheda.impronta_del_blocco(BLOCCO_SOLDI)
        fuori.append(("il blocco ha un'impronta", bool(impronta),
                      impronta or "il piano non si legge: una misura senza ancoraggio non vale"))
    except Exception as e:
        fuori.append(("il blocco ha un'impronta", False, str(e)))

    return all(ok for _, ok, _ in fuori), fuori


# --------------------------------------------------------------------------------------
# 2. LE DUE MISURE — eseguono le guardie vere, non riscrivono i criteri
# --------------------------------------------------------------------------------------
_GIRO = {}

# ⛔ I DUE PEZZI DEL PERIMETRO CHE NON SI DERIVANO, scritti qui una volta sola invece che
#    ripetuti dentro le funzioni: la guardia che dimostra il cablaggio in CI, e le classi che
#    appartengono alla casella delle relazioni. Vedi `perimetri()` per il perche'.
GUARDIA_DEL_CABLAGGIO = "test_pipeline_ci.TestLeDIMOSTRAZIONIMatematicheGIRANODavveroInCI"
CLASSI_DELLE_RELAZIONI = (
    "test_property_soldi.TestRelazioniMetamorficheSulDenaro",
    "test_property_soldi.TestLeRelazioniMetamorficheSANNODiventareROSSE",
)


def bersagli():
    """Cosa va eseguito, DERIVATO: i moduli che portano prove z3 (dentro c'e' anche quello
    delle relazioni) piu' la guardia sul cablaggio in CI."""
    import test_pipeline_ci as TPC
    return sorted(TPC._moduli_di_test_con_prove_z3()) + [GUARDIA_DEL_CABLAGGIO]


def giro_unico():
    """Esegue UNA VOLTA SOLA tutto cio' che serve alle due caselle, e smista gli esiti.

    ⛔ UNA VOLTA SOLA, E NON E' UN'OTTIMIZZAZIONE. `test_property_soldi` serve a tutt'e due
    le caselle: alla prima come modulo che porta prove z3 (si guarda se si salta), alla
    seconda come casa delle relazioni. Eseguendolo DUE volte nello stesso processo,
    Hypothesis alza `FailedHealthCheck: differing_executors` e fa fallire TUTTE le
    relazioni -- per un motivo che non ha niente a che vedere coi soldi.
    Misurato il 2026-09-02: 12 rosse su 12 al primo giro dell'esame, e la colpa era di
    questo attrezzo, non del motore. E' lo sbaglio S3: quando la misura e' assurda, il
    primo sospetto va allo strumento.
    """
    if _GIRO:
        return _GIRO
    caricatore = unittest.TestLoader()
    suite = unittest.TestSuite()
    for n in bersagli():
        suite.addTests(caricatore.loadTestsFromName(n))
    flusso = io.StringIO()
    esito = unittest.TextTestRunner(stream=flusso, verbosity=0).run(suite)

    def _dove(t):
        return "%s.%s" % (type(t).__module__, type(t).__name__)

    _GIRO.clear()
    _GIRO.update({
        "eseguiti": esito.testsRun,
        "rossi": [(_dove(t), str(t)) for t, _ in
                  list(esito.failures) + list(esito.errors)],
        "saltati": [(_dove(t), str(t), m) for t, m in esito.skipped],
        "testo": flusso.getvalue(),
    })
    return _GIRO


def _classi(nomi):
    """{'modulo.Classe': quanti test} per i nomi dati. Li conta il CARICATORE, non io."""
    caricatore = unittest.TestLoader()
    fuori = {}

    def _giu(suite):
        for t in suite:
            if isinstance(t, unittest.TestSuite):
                _giu(t)
            else:
                k = "%s.%s" % (type(t).__module__, type(t).__name__)
                fuori[k] = fuori.get(k, 0) + 1

    for n in nomi:
        _giu(caricatore.loadTestsFromName(n))
    return fuori


def perimetri():
    """SU COSA si pronuncia ogni casella: le classi, elencate una per una.

    ⛔ RIPARAZIONE DEL 2026-09-03, e chiude DUE difetti che sono lo stesso difetto visto dai
    due lati. Li hanno trovati la revisione incrociata della corsia C e, verificando la sua,
    la corsia A:
      · il DENOMINATORE era piu' STRETTO del verdetto: contava solo i moduli con prove z3
        (64), mentre il verdetto giudicava anche la guardia sul cablaggio in CI (+5). Un
        rosso venuto dal cablaggio finiva in scheda con un denominatore in cui non si trova;
      · il FILTRO era piu' LARGO della frase della casella: confrontava il PREFISSO del
        modulo, quindi la casella 1 -- che parla di *dimostrazioni z3 che girano e non si
        saltano* -- si prendeva QUALUNQUE rosso di `test_property_soldi`, comprese le
        relazioni metamorfiche sul denaro, che sono la casella 4 e con z3 non c'entrano.
    In tutt'e due i casi **il perimetro non era quello che la frase dichiarava**. Qui il
    perimetro si scrive UNA VOLTA SOLA, ed e' la stessa fonte per il denominatore e per il
    verdetto: due cifre che nascono dalla stessa espressione non possono divergere.

    ⚠️ IL DENOMINATORE DELLA CASELLA 1 SCENDE DA 64 A 54, E NON E' UN ALLENTAMENTO. Chi legge
    un numero di sorveglianza che cala pensa «hanno abbassato l'asticella»: qui e' il
    contrario, e i tre pezzi sono
        64  i test dei moduli con prove z3
       -15  quelli che appartengono alla casella 4 (misuravano un'altra cosa)
        +5  la guardia sul cablaggio, che il verdetto giudicava senza contarla
        ===
        54  cio' su cui la casella si pronuncia davvero
    Un numero di sorveglianza che scende porta la sua spiegazione, o non scende.
    """
    import test_pipeline_ci as TPC
    moduli = sorted(TPC._moduli_di_test_con_prove_z3())
    tutte = _classi(list(moduli) + [GUARDIA_DEL_CABLAGGIO])
    quattro = {k: v for k, v in tutte.items() if k in CLASSI_DELLE_RELAZIONI}
    uno = {k: v for k, v in tutte.items() if k not in CLASSI_DELLE_RELAZIONI}
    return {"moduli_z3": list(moduli), "casella1": uno, "casella4": quattro}


def _dentro(voci, perimetro):
    """Le voci che cadono ESATTAMENTE dentro il perimetro.

    ⛔ Confronto esatto sulla classe, non `startswith` sul modulo: col prefisso una casella si
    prendeva i rossi di un'altra (vedi `perimetri`). «Comincia per» e «appartiene a» si
    scrivono quasi uguale e significano cose diverse."""
    return [v[1] for v in voci if v[0] in perimetro]


def misura_z3():
    """Casella 1. Denominatore = cardinalita' del suo perimetro, non un secondo conteggio."""
    tutti = perimetri()
    p = tutti["casella1"]
    quanti = sum(p.values())
    # ⛔ La composizione si CALCOLA, non si scrive: un numero di sorveglianza che scende porta
    #    la sua spiegazione, o sembra un allentamento. E una spiegazione con le cifre a mano
    #    diventa falsa il giorno che il perimetro cambia (S17).
    cablaggio = p.get(GUARDIA_DEL_CABLAGGIO, 0)
    altrui = sum(tutti["casella4"].values())
    g = giro_unico()
    rossi, saltati = _dentro(g["rossi"], p), _dentro(g["saltati"], p)
    return (not rossi and not saltati), quanti, {
        "perimetro": sorted(p),
        "test_nel_perimetro": quanti,
        "composizione": "%d test nei moduli con prove z3, MENO %d che sono la casella 4, "
                        "PIU' %d della guardia sul cablaggio = %d"
                        % (quanti - cablaggio + altrui, altrui, cablaggio, quanti),
        "saltati": saltati,
        "rossi": rossi,
    }


def misura_relazioni():
    """Casella 4. Stesso criterio della 1: il denominatore E' il perimetro.

    ⛔ Anche qui era 12 (le relazioni dichiarate) mentre il verdetto ne giudicava 15 -- le 12
    piu' le 3 che dimostrano che le 12 sanno diventare rosse. Riparare la casella 1 e lasciare
    lo stesso difetto qui sarebbe stato peggio che non riparare: avrebbe fatto sembrare il
    problema chiuso. Il «quante relazioni» resta nel dettaglio, dove informa senza poter
    mentire sul verdetto."""
    import test_property_soldi as TPS
    p = perimetri()["casella4"]
    quanti = sum(p.values())
    g = giro_unico()
    rossi, saltati = _dentro(g["rossi"], p), _dentro(g["saltati"], p)
    return (not rossi and not saltati), quanti, {
        "perimetro": sorted(p),
        "test_nel_perimetro": quanti,
        "relazioni_dichiarate": len(TPS._tutte_le_relazioni()),
        "rossi": rossi,
        "saltati": saltati,
    }


# --------------------------------------------------------------------------------------
# 3. L'AUTOPROVA (D18 punto 2): si vede gridare, e tacere
# --------------------------------------------------------------------------------------
def inietta_il_guasto():
    """Rompe il riparto fra ospiti a RUNTIME: le quote non sommano piu' al totale.
    ⛔ Nessun `fase*.py` viene toccato (B4): si sostituisce la funzione nel modulo
    importato, dentro questo processo, che muore alla fine della passata."""
    import fase133_split_quote_uguali as SPLIT
    vero = SPLIT.riparti_uguale
    SPLIT.riparti_uguale = lambda t, n: (
        lambda q: [min(q)] * len(q) if q else q)(vero(t, n))


def autoprova():
    """Due passate IN PROCESSI NUOVI: una col guasto dentro (deve uscire ROSSA) e una sana
    (deve uscire VERDE).

    ⛔ PROCESSI NUOVI, e non e' uno scrupolo di stile. Hypothesis rifiuta lo stesso test
    eseguito da due «executor» diversi nello stesso processo: rimisurare qui dentro
    farebbe fallire tutto per un motivo che non c'entra col guasto, e l'autoprova
    direbbe «grida» quando invece sta solo rompendosi. E' la stessa ragione per cui
    `collaudi/bombe_a_tempo.py` esegue ogni passata fuori.
    """
    import subprocess
    righe, riuscita = [], True
    io_stesso = os.path.abspath(__file__)

    for etichetta, extra, atteso_rosso in (
            ("col riparto ROTTO", ["--con-guasto"], True),
            ("a macchina SANA", [], False)):
        e = subprocess.run([sys.executable, io_stesso] + extra, cwd=RADICE,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        rosso = e.returncode != 0
        ok = (rosso == atteso_rosso)
        righe.append("   %-20s uscita=%d -> %s   %s"
                     % (etichetta, e.returncode,
                        "ROSSA" if rosso else "VERDE",
                        "atteso" if ok else "⛔ NON E' QUELLO CHE DOVEVA SUCCEDERE"))
        if not ok:
            riuscita = False
            coda = e.stdout.decode("utf-8", "replace")[-500:]
            righe.append("      ultime righe del figlio: %s" % coda.replace("\n", " | "))
    return riuscita, righe


# --------------------------------------------------------------------------------------
def _stampa_non_guarda():
    print("-" * 86)
    print("⛔ COSA QUESTO ESAME NON HA ESAMINATO (D18 punto 3)")
    for r in NON_GUARDA:
        print("   · %s" % r)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    os.chdir(RADICE)

    print("=" * 86)
    print("🧾 ESAME DEL BLOCCO SOLDI — caselle 1 e 4")
    print("=" * 86)

    if "--autoprova" in argv:
        print("🔁 AUTOPROVA — l'esame si vede gridare e tacere (D18 punto 2)")
        riuscita, righe = autoprova()
        for r in righe:
            print(r)
        _stampa_non_guarda()
        print("=" * 86)
        print("VERDETTO: %s" % ("✅ l'esame grida col guasto e tace a macchina sana"
                                if riuscita else
                                "⛔ L'ESAME NON E' AFFIDABILE — non si comporta come promette"))
        return 0 if riuscita else 1

    if "--con-guasto" in argv:
        # ⛔ IL CANCELLO, e non e' uno scrupolo: prima qui c'era solo un COMMENTO che diceva
        #    «non si usa a mano», e i due `if` (`--con-guasto` e `--scrivi`) erano
        #    indipendenti, con in mezzo un solo `return` che guarda le precondizioni -- le
        #    quali non sanno niente del modulo in cui il guasto viene iniettato. Quindi
        #        python collaudi/esame_soldi.py --con-guasto --scrivi
        #    iniettava il guasto, misurava ROSSO e REGISTRAVA quel rosso nella scheda vera.
        #    Trovato dalla revisione incrociata della corsia C il 2026-09-03; lei non l'ha
        #    eseguito apposta, perche' eseguirlo avrebbe prodotto il danno.
        # 🔑 Un commento e' una DICHIARAZIONE, un `if` e' un CONTROLLO. D18 punto 1 chiede il
        #    secondo: la domanda non e' «ha barato?» ma «PUO' barare?».
        # ⚠️ E la scheda e' fuori da git (`.gitignore:25:*.json`): una riga falsa li' dentro
        #    non viaggia, ma NESSUN `checkout` la ripara e nessun `diff` la mostra. Non e' una
        #    bugia che si propaga: e' una bugia che RESTA, dove i nostri attrezzi non arrivano.
        if "--scrivi" in argv:
            print("⛔ FERMO: `--con-guasto` non scrive. Serve a vedere l'esame diventare")
            print("   ROSSO col guasto dentro; registrare quel rosso significherebbe mettere")
            print("   nella scheda la misura di una macchina rotta di proposito.")
            return 2
        print("⚠️  PASSATA COL GUASTO DENTRO (riparto fra ospiti rotto a runtime)")
        inietta_il_guasto()

    tutte_ok, righe = precondizioni()
    print("PRIMA DI MISURARE, L'ESAME MISURA SE STESSO (D18 punto 1)")
    for nome, ok, motivo in righe:
        print("  %-9s %-34s %s" % ("OK" if ok else "⛔ NO", nome, motivo))
    if not tutte_ok:
        print("-" * 86)
        print("VERDETTO: ⛔ FERMO — una precondizione non regge, quindi NON misuro e NON")
        print("scrivo niente. Un numero prodotto da un metro storto e' peggio di nessun")
        print("numero: sembra una risposta.")
        _stampa_non_guarda()
        print("=" * 86)
        return 2

    condizioni = [b for b in BLOCCHI if b["ordine"] == BLOCCO_SOLDI][0]["finito_quando"]
    lavori = (
        (0, "le prove z3 girano e non si saltano", misura_z3,
         "python collaudi/esame_soldi.py --scrivi"),
        (3, "le relazioni metamorfiche sul denaro", misura_relazioni,
         "python collaudi/esame_soldi.py --scrivi"),
    )

    print("")
    esiti = []
    for indice, etichetta, misura, comando in lavori:
        esito, denominatore, dettaglio = misura()
        esiti.append((indice, etichetta, esito, denominatore, dettaglio, comando))
        print("  %-9s casella %d — %s" % ("VERDE" if esito else "⛔ ROSSA", indice + 1, etichetta))
        print("            denominatore: %d" % denominatore)
        for k, v in sorted(dettaglio.items()):
            # ⛔ il PERIMETRO si stampa una classe per riga: chi legge la scheda fra sei mesi
            #    deve vedere SU COSA e' stato dato il verdetto, senza doverlo dedurre da due
            #    espressioni in due funzioni diverse (chiesto dalla corsia C in revisione).
            if k == "perimetro":
                print("            perimetro (%d classi):" % len(v))
                for classe in v:
                    print("               · %s" % classe)
            else:
                print("            %-28s %s" % (k, v))

    if "--scrivi" in argv:
        print("")
        print("SCRITTURA NELLA SCHEDA")
        for indice, _, esito, denominatore, _, comando in esiti:
            # ⛔ il testo si PRENDE dal piano, non si ricopia
            riga = scheda.registra(condizioni[indice], esito=esito,
                                   denominatore=denominatore, comando=comando,
                                   ordine=BLOCCO_SOLDI)
            print("  scritta: blocco %d · esito %s · denominatore %d · impronta %s"
                  % (riga["blocco"], riga["esito"], riga["denominatore"], riga["impronta"]))
    else:
        print("")
        print("(non ho scritto niente: aggiungi --scrivi per registrare nella scheda)")

    _stampa_non_guarda()
    print("=" * 86)
    return 0 if all(e[2] for e in esiti) else 1


if __name__ == "__main__":
    sys.exit(main())
