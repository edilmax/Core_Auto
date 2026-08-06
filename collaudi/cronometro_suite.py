# -*- coding: utf-8 -*-
"""IL CRONOMETRO DELLA SUITE — quale test costa quanto, e da quando.

⛔ PERCHE' ESISTE. Il 2026-08-05 una guardia nuova ha piu' che RADDOPPIATO il tempo della CI
(da ~10 a 23m42s) e **nessun controllo l'ha detto**: l'ha notato il fondatore leggendo una
tabella su GitHub il giorno dopo. Un controllo che rallenta la macchina e' un controllo che
prima o poi qualcuno spegne, e allora non protegge piu' niente.

⛔ PERCHE' NON MISURA IL TEMPO TOTALE. Misurato il 2026-08-06 sulla stessa macchina e nello
stesso giorno: la stessa suite e' passata da **1785 a 3818 secondi** (rumore 2,14x, ±1000 s),
e il giro con PIU' test e' stato il PIU' VELOCE. Il rallentamento da intercettare valeva 90 s:
undici volte piu' piccolo del rumore. Un cricchetto sul totale griderebbe sui giri lenti
normali -- e un falso allarme e' un difetto quanto un allarme mancato (regola ferrea 10).
Il tempo del SINGOLO test invece separa bene: 0,1 s e 90 s restano distinguibili anche col
doppio di rumore. E' quello che si misura qui.

⛔ COSA NON FA, dichiarato (D18 punto 3):
  · non cambia il verdetto della suite. Il verdetto lo da' `unittest`, non questo file: si usa
    il suo runner e il suo `wasSuccessful()`. Se questo strumento avesse un difetto che lo fa
    uscire verde su test rossi, il cancello principale sarebbe morto e nessuno lo saprebbe --
    per questo la prima guardia non e' sui tempi, e' sul codice d'uscita nelle DUE direzioni
    (`test_pipeline_ci.TestIlCronometroNonPuoMENTIRE`);
  · non impone nessun tetto **finche' non gliene si passa uno** (`--tetto-secondi N`): una
    soglia scelta prima di conoscere la varianza e' un falso allarme in attesa;
  · non misura la memoria ne' l'uso di rete: solo il tempo di parete per test;
  · **non attribuisce a nessun test** il tempo di `setUpClass`, `setUpModule` e degli IMPORT:
    `startTest`/`stopTest` racchiudono il metodo con `setUp`/`tearDown`, non l'apparecchiatura
    di classe. In questo repository `setUpClass` e' ovunque, quindi un rallentamento
    parcheggiato li' sarebbe **invisibile allo strumento il cui unico scopo e' trovarli**.
    Non potendolo attribuire, lo si DICHIARA: in fondo al giro si stampa quanto tempo di
    parete non e' finito in nessun test (2026-08-06, revisione a contesto fresco).

USO:
    python collaudi/cronometro_suite.py                      # come `unittest discover`, + tempi
    python collaudi/cronometro_suite.py -b                    # uscita dei test in memoria
    python collaudi/cronometro_suite.py --quanti 40           # quanti test lenti elencare
    python collaudi/cronometro_suite.py --tetto-secondi 30    # ROSSO se un test supera 30 s
    python collaudi/cronometro_suite.py --moduli test_a test_b   # solo quei moduli
"""
import os
import sys
import time
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(QUI)

# Test che possono superare il tetto PER RAGIONI DICHIARATE, e nessun altro. Ogni voce porta il
# motivo: un elenco di esenzioni senza motivi diventa il posto dove si nasconde la lentezza.
# ⛔ Si aggiunge una voce solo se la lentezza e' NECESSARIA (avvia processi, prova un
#    ripristino, rompe e ricostruisce file). «E' sempre stato lento» non e' un motivo.
LENTI_DICHIARATI = {
    "test_mutation_money.TestMutationMoney.test_ogni_mutante_viene_ucciso":
        "rompe TRE moduli di produzione uno per volta e per ognuno lancia una suite killer "
        "in un processo separato: la lentezza e' il lavoro, non uno spreco",
}


class RisultatoCronometrato(unittest.TextTestResult):
    """Il risultato di `unittest`, piu' un cronometro per test. Non tocca il verdetto."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.tempi = []
        self._inizio = None

    def startTest(self, test):
        self._inizio = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test):
        super().stopTest(test)
        if self._inizio is not None:
            self.tempi.append((time.perf_counter() - self._inizio, test.id()))
            self._inizio = None


OPZIONI = ("-b", "--buffer", "--quanti", "--tetto-secondi", "--moduli")


def _controlla_opzioni(argv):
    """⛔ UN'OPZIONE SCRITTA MALE NON DEVE SPEGNERE L'ALLARME IN SILENZIO.

    `--tetto 30` invece di `--tetto-secondi 30` lasciava `tetto` a `None`: nessun tetto,
    uscita 0, nessun avviso. Per uno strumento candidato a fare da cancello e' la stessa
    famiglia del «verde con la suite vuota»: sembra che abbia controllato e non ha controllato
    niente. Qui un'opzione sconosciuta e' un ERRORE, non un'alzata di spalle.
    """
    dopo_moduli = False
    for a in argv[1:]:
        if a == "--moduli":
            dopo_moduli = True
            continue
        if a.startswith("-"):
            dopo_moduli = False
            base = a.split("=")[0]
            if base not in OPZIONI:
                return ("opzione sconosciuta: %r. Quelle valide sono: %s"
                        % (a, " ".join(OPZIONI)))
            if "=" in a:
                return ("l'opzione %r usa `=`: qui il valore va separato da uno spazio "
                        "(`%s 30`), se no non viene letto e il controllo resta SPENTO"
                        % (a, base))
        elif not dopo_moduli:
            pass          # e' il valore di un'opzione precedente
    return None


def _argomento(nome, predefinito, argv):
    """Il valore che segue `nome` sulla riga di comando, o il predefinito."""
    if nome in argv:
        i = argv.index(nome)
        if i + 1 < len(argv):
            return argv[i + 1]
    return predefinito


def carica(argv=None):
    """Gli stessi test che troverebbe `python -m unittest discover -s . -p "test_*.py"`.

    ⛔ La scoperta deve essere IDENTICA: un cronometro che esegue meno test di quelli veri
    sarebbe un cancello che sembra chiuso ed e' aperto. Sotto guardia in
    `test_pipeline_ci.TestIlCronometroNonPuoMENTIRE.test_scopre_ESATTAMENTE_gli_stessi_test`.

    ⛔ `argv` SI PASSA, non si legge dal globale. Difetto trovato dalla revisione a contesto
    fresco il 2026-08-06: cronometrando un modulo alla volta
    (`cronometro_suite.py --moduli test_pipeline_ci`) la guardia qui dentro rileggeva LO STESSO
    `sys.argv`, vedeva `--moduli`, e confrontava un sottoinsieme con la scoperta intera -->
    ROSSA per il motivo sbagliato, proprio nel modo d'uso principale dello strumento.
    """
    argv = sys.argv if argv is None else argv
    if "--moduli" in argv:
        i = argv.index("--moduli")
        # ⛔ SI FERMA ALLA PRIMA OPZIONE, non salta le opzioni raccogliendo i loro VALORI.
        # Difetto vero trovato dalla sua guardia il 2026-08-06: con
        # `--moduli x --tetto-secondi 30` il numero `30` finiva fra i nomi dei moduli, e
        # `unittest` lo caricava come `_FailedTest` -- suite rossa per un modulo inesistente.
        # Peggio: il controllo «il tetto grida» passava lo stesso, cioe' un VERDE per il
        # motivo sbagliato.
        nomi = []
        for a in argv[i + 1:]:
            if a.startswith("-"):
                break
            nomi.append(a)
        if not nomi:
            raise ValueError("`--moduli` senza nessun nome: non c'e' niente da eseguire. "
                             "Uno strumento che esegue ZERO test ed esce verde e' un cancello "
                             "che sembra chiuso ed e' aperto.")
        return unittest.defaultTestLoader.loadTestsFromNames(nomi)
    return unittest.defaultTestLoader.discover(REPO, pattern="test_*.py", top_level_dir=REPO)


def main(argv=None):
    argv = sys.argv if argv is None else argv
    guaio = _controlla_opzioni(argv)
    if guaio:
        print("::error title=CRONOMETRO: riga di comando non valida::%s" % guaio)
        return 2
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    os.chdir(REPO)
    try:
        quanti = int(_argomento("--quanti", "25", argv))
        tetto = _argomento("--tetto-secondi", None, argv)
        tetto = float(tetto) if tetto is not None else None
        suite = carica(argv)
    except ValueError as e:
        print("::error title=CRONOMETRO: non posso partire::%s" % e)
        return 2

    inizio = time.perf_counter()
    runner = unittest.TextTestRunner(verbosity=1,
                                     buffer=("-b" in argv or "--buffer" in argv),
                                     resultclass=RisultatoCronometrato)
    risultato = runner.run(suite)
    parete = time.perf_counter() - inizio

    # ⛔ ZERO TEST ESEGUITI E' UN ERRORE, NON UN SUCCESSO. `unittest` considera «riuscita» una
    #    suite vuota, quindi senza questo controllo lo strumento uscirebbe VERDE senza aver
    #    provato niente -- il cancello che sembra chiuso ed e' aperto, cioe' proprio la cosa
    #    che le sue guardie dichiarano di scongiurare. Trovato dalla revisione a contesto
    #    fresco il 2026-08-06. E' anche la D18 punto 1: uno strumento che misura si ferma
    #    invece di stampare un numero, quando non e' in condizione di misurare.
    if not risultato.testsRun:
        print("::error title=CRONOMETRO: ZERO TEST ESEGUITI::la scoperta non ha trovato "
              "niente da eseguire. Una suite vuota NON e' una suite verde.")
        return 1

    tempi = sorted(risultato.tempi, reverse=True)
    print()
    print("=" * 78)
    print("I %d TEST PIU' LENTI (tempo di parete, su %d misurati)" % (min(quanti, len(tempi)),
                                                                     len(tempi)))
    print("=" * 78)
    for secondi, nome in tempi[:quanti]:
        print("  %8.2f s  %s%s" % (secondi, nome,
                                   "   [LENTO DICHIARATO]" if nome in LENTI_DICHIARATI else ""))
    somma = sum(s for s, _n in tempi)
    if tempi:
        print("-" * 78)
        print("  somma dei tempi per test: %.1f s · i %d piu' lenti ne fanno %.1f s (%.0f%%)"
              % (somma, min(quanti, len(tempi)), sum(s for s, _n in tempi[:quanti]),
                 100.0 * sum(s for s, _n in tempi[:quanti]) / max(somma, 0.001)))
        # ⛔ IL TEMPO CHE QUESTO STRUMENTO NON VEDE, DETTO INVECE CHE TACIUTO (D18 punto 3).
        #    `startTest`/`stopTest` racchiudono il metodo con `setUp`/`tearDown`, ma NON
        #    `setUpClass`, `setUpModule` ne' il tempo di IMPORT dei moduli. In questo
        #    repository `setUpClass` e' ovunque: un rallentamento parcheggiato li' sarebbe
        #    invisibile allo strumento il cui unico scopo e' trovare i rallentamenti.
        #    Non si puo' misurarlo per test, ma si puo' DIRE quanto vale in totale.
        print("  tempo di parete: %.1f s · NON attribuito a nessun test: %.1f s (%.0f%%)"
              % (parete, max(0.0, parete - somma),
                 100.0 * max(0.0, parete - somma) / max(parete, 0.001)))
        print("    (quel tempo sta in `setUpClass`/`setUpModule` e negli import: questo")
        print("     strumento NON lo attribuisce, e se cresce va cercato li'.)")

    # ⛔ IL TETTO E' FACOLTATIVO E, QUANDO C'E', NON PUO' CANCELLARE UN VERDETTO ROSSO.
    #    Un test lento su una suite rossa resta un problema minore: prima si guarda il rosso.
    oltre = []
    if tetto is not None:
        oltre = [(s, n) for s, n in tempi if s > tetto and n not in LENTI_DICHIARATI]
        if oltre:
            print()
            print("::error title=SUITE RALLENTATA::%d test superano il tetto di %.0f s"
                  % (len(oltre), tetto))
            for s, n in oltre:
                print("  OLTRE IL TETTO  %8.2f s  %s" % (s, n))
            print("  Un test cosi' lento si paga a OGNI giro di CI, due volte (suite intera e")
            print("  copertura). Va reso veloce, oppure dichiarato in LENTI_DICHIARATI con il")
            print("  MOTIVO -- e «e' sempre stato lento» non e' un motivo.")

    if not risultato.wasSuccessful():
        return 1
    return 1 if oltre else 0


if __name__ == "__main__":
    sys.exit(main())
