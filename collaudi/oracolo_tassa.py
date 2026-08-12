"""ORACOLO INDIPENDENTE per la tassa di soggiorno (fase66) — e la PROVA di una rimozione.

PERCHE' QUESTO FILE ESISTE
--------------------------
Il 2026-08-12 sono stati tolti da `calcola_tassa` alcuni controlli (`_intero_nn(...)`,
`... > 0`) diventati **ridondanti** dopo l'introduzione della precondizione
`_regola_malformata`. Erano 11 punti che il Giudice della mutazione segnalava come NON
SORVEGLIATI e che nessun collaudo poteva uccidere, perche' non cambiavano nessun risultato
osservabile. Le alternative erano due:

  (a) dichiararli equivalenti in `EQUIVALENTI_DICHIARATI` -> VIETATO senza dimostrazione (B6),
      ed e' l'unico posto del progetto dove un errore diventa cecita' PERMANENTE;
  (b) togliere il codice morto, dimostrando che il risultato non cambia.

E' stata scelta la (b). ⛔ MA UNA DIMOSTRAZIONE CHE VIVE IN UNA CARTELLA TEMPORANEA NON E'
UNA DIMOSTRAZIONE: sparisce a fine sessione e resta solo la parola di chi l'ha scritta in un
commento. E' la lezione dei due attrezzi orfani trovati per fortuna il 2026-08-11. Per questo
la versione PRUDENTE (quella di prima) vive qui dentro, per sempre, e un collaudo della suite
la fa correre fianco a fianco con quella vera a ogni giro.

COSA E' `riferimento_prudente`
-------------------------------
E' `calcola_tassa` **com'era prima della rimozione**: stessa aritmetica, ma con tutti i
controlli difensivi al loro posto. Non e' una copia di comodo: e' il TESTIMONE storico. Se
un domani la versione vera smettesse di coincidere con questa, vorrebbe dire che la rimozione
del 2026-08-12 ha cambiato qualcosa -- e lo si saprebbe subito, invece che dai soldi.

⛔ COSA QUESTO ORACOLO **NON** FA (D18 punto 3), detto prima e non dopo:
  · NON dice che la formula sia GIUSTA: dice che le due versioni sono INDISTINGUIBILI. Se la
    regola di calcolo fosse sbagliata, sarebbero sbagliate tutte e due allo stesso modo.
    La correttezza la sorvegliano i collaudi di `test_fase66_tassa_soggiorno` (che pinnano
    numeri esatti) e l'oracolo di `test_happy_conti` (che ricalcola il conto per un'altra
    strada). Questo qui sorveglia una cosa sola: che TOGLIERE non abbia CAMBIATO.
  · NON esplora tutti gli interi: esplora la griglia dichiarata in `GRIGLIA`, scelta sui
    confini (0, 1, valori veri, il tetto) piu' i valori sporchi in ogni posizione. Una
    griglia e' un campione ragionato, non l'infinito.
  · NON attraversa la catena: e' aritmetica pura. Il percorso vero (annuncio -> preventivo)
    lo prova `test_tassa_pre_acquisto`.
"""
import itertools
import os
import sys

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RADICE not in sys.path:                       # la radice si RICAVA, non si cabla:
    sys.path.insert(0, RADICE)                   # un percorso cablato muore su Linux e in CI

MAX_CENTS = 1_000_000_00


def _intero_nn(v):
    """Intero non-negativo (no bool, no float). Copia deliberata: l'oracolo non deve
    dipendere dal modulo che sta giudicando, se no cade con lui."""
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _malformata(pp, perc, maxn, tetto):
    for v in (pp, perc):
        if not _intero_nn(v):
            return True
    for v in (maxn, tetto):
        if v is not None and not _intero_nn(v):
            return True
    return False


def riferimento_prudente(pp, perc, maxn, tetto, notti, ospiti, imponibile, esenti):
    """`calcola_tassa` COM'ERA prima della rimozione del 2026-08-12.

    Restituisce la tupla (tassa, fissa, percentuale, notti_tassabili, ospiti_tassabili),
    cioe' gli stessi cinque numeri osservabili di `CalcoloTassa`.
    """
    if not (_intero_nn(notti) and _intero_nn(ospiti)):
        return (0, 0, 0, 0, 0)
    if _malformata(pp, perc, maxn, tetto):
        return (0, 0, 0, 0, 0)
    imponibile = imponibile if _intero_nn(imponibile) else 0
    esenti = esenti if _intero_nn(esenti) else 0

    # ── i controlli che sono stati TOLTI dalla versione vera stanno qui, intatti ──
    if maxn is not None and _intero_nn(maxn):
        notti_tass = min(notti, maxn)
    else:
        notti_tass = notti
    ospiti_tass = max(0, ospiti - esenti)

    fissa = 0
    if _intero_nn(pp) and pp > 0 and ospiti_tass > 0 and notti_tass > 0:
        per_persona = pp * notti_tass
        if tetto is not None and _intero_nn(tetto):
            per_persona = min(per_persona, tetto)
        fissa = per_persona * ospiti_tass

    perc_cents = 0
    if _intero_nn(perc) and perc > 0 and imponibile > 0:
        perc_cents = (perc * imponibile) // 10000

    tassa = fissa + perc_cents
    if tassa > MAX_CENTS:
        return (0, 0, 0, notti_tass, ospiti_tass)
    return (tassa, fissa, perc_cents, notti_tass, ospiti_tass)


# ── LA GRIGLIA — confini, valori veri, e il tetto. Dichiarata, non nascosta. ──────────
GRIGLIA = {
    "pp": [0, 1, 350, 100000, MAX_CENTS],
    "perc": [0, 1, 500, 10000],
    "maxn": [None, 0, 1, 7, 366],
    "tetto": [None, 0, 1, 1000, MAX_CENTS],
    "notti": [0, 1, 2, 7, 30],
    "ospiti": [0, 1, 2, 5],
    "imponibile": [0, 1, 20000],
    "esenti": [0, 1, 5],
}
SPORCHI = [-1, 7.5, True, "7", None]


def _vero(pp, perc, maxn, tetto, notti, ospiti, imponibile, esenti):
    """La versione VERA, chiamata attraverso la sua interfaccia pubblica."""
    from fase66_tassa_soggiorno import RegolaTassa, calcola_tassa
    regola = RegolaTassa(per_persona_notte_cents=pp, percentuale_bps=perc,
                         max_notti_tassabili=maxn, tetto_per_persona_soggiorno_cents=tetto)
    c = calcola_tassa(regola, notti=notti, ospiti=ospiti,
                      imponibile_cents=imponibile, esenti=esenti)
    return (c.tassa_cents, c.componente_fissa_cents, c.componente_percentuale_cents,
            c.notti_tassabili, c.ospiti_tassabili)


def confronta(funzione_vera=None):
    """Fa correre le due versioni fianco a fianco.

    Restituisce (provate, differenze, eccezioni). `differenze` ed `eccezioni` sono elenchi
    di casi, non conteggi: un numero da solo non fa riparare niente.

    ⛔ `funzione_vera` E' INIETTABILE APPOSTA, e non e' un vezzo. Un oracolo che sa solo dire
    «uguali» e' indistinguibile da un oracolo rotto: la prova che funziona e' fargli passare
    una funzione SBAGLIATA e vederlo gridare (regola ferrea 10, le due direzioni). Senza
    questo appiglio quella prova non si potrebbe scrivere, e resterebbe un verde di cui
    fidarsi sulla parola.
    """
    if funzione_vera is None:
        funzione_vera = _vero
    differenze, eccezioni, provate = [], [], 0

    for combo in itertools.product(
            GRIGLIA["pp"], GRIGLIA["perc"], GRIGLIA["maxn"], GRIGLIA["tetto"],
            GRIGLIA["notti"], GRIGLIA["ospiti"], GRIGLIA["imponibile"], GRIGLIA["esenti"]):
        provate += 1
        try:
            a = riferimento_prudente(*combo)
            b = funzione_vera(*combo)
        except Exception as e:                    # il contratto dice: MAI un'eccezione
            eccezioni.append((combo, type(e).__name__, str(e)))
            continue
        if a != b:
            differenze.append((combo, a, b))

    # secondo giro: un valore SPORCO in ogni posizione della regola
    for posizione in range(4):
        for sporco in SPORCHI:
            for notti, ospiti in itertools.product(GRIGLIA["notti"], GRIGLIA["ospiti"]):
                campi = [350, 500, 7, 1000]
                campi[posizione] = sporco
                combo = (campi[0], campi[1], campi[2], campi[3], notti, ospiti, 20000, 0)
                provate += 1
                try:
                    a = riferimento_prudente(*combo)
                    b = funzione_vera(*combo)
                except Exception as e:
                    eccezioni.append((combo, type(e).__name__, str(e)))
                    continue
                if a != b:
                    differenze.append((combo, a, b))

    return provate, differenze, eccezioni


def main():
    provate, differenze, eccezioni = confronta()
    print("=" * 86)
    print("ORACOLO DELLA TASSA — la versione prudente contro quella vera")
    print("=" * 86)
    print("  combinazioni provate ..... %d" % provate)
    print("  risultati diversi ........ %d" % len(differenze))
    print("  eccezioni sollevate ...... %d   (il contratto dice: MAI un'eccezione)"
          % len(eccezioni))
    for c, a, b in differenze[:10]:
        print("    %r -> prudente %r  vera %r" % (c, a, b))
    for c, tipo, msg in eccezioni[:10]:
        print("    %r -> %s: %s" % (c, tipo, msg))
    print("-" * 86)
    print("⛔ COSA NON HA ESAMINATO: se la FORMULA sia giusta (sarebbero sbagliate tutte e")
    print("   due allo stesso modo) · gli interi fuori dalla griglia · la catena vera.")
    print("=" * 86)
    if differenze or eccezioni:
        print("VERDETTO: ⛔ LE DUE VERSIONI NON COINCIDONO.")
        return 1
    print("VERDETTO: ✅ %d combinazioni, ZERO differenze, ZERO eccezioni." % provate)
    return 0


if __name__ == "__main__":
    sys.exit(main())
