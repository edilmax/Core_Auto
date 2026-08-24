"""ORACOLO INDIPENDENTE per il payout dell'host (fase131) — il SECONDO conto.

PERCHE' QUESTO FILE ESISTE (B6, 2026-08-24)
-------------------------------------------
Sul bonifico all'host ci sono sei file di test — `test_fase131_payout_dashboard`,
`test_payout_in_attesa`, `test_payout_valuta_storica`, `test_split_penale_payout`,
`test_dac7_blocco_payout`, `test_fase101_stripe_connect` — e tutti fanno la STESSA
domanda: «la cifra che abbiamo scritto nel registro e' quella che rileggiamo?».
Nessuno chiede: **«quella cifra e' quella giusta?»**

E' la tecnica **04** (oracolo indipendente), che in casa esiste gia' in due punti:
`collaudi/prezzi_coerenti.py` sul prezzo e `collaudi/oracolo_tassa.py` sulla tassa.
Sul payout mancava. ⛔ Ed e' **il primo numero che un host vero controlla**: se sbaglia
non lo scopriamo noi, lo scopre lui, e lo scopre sul suo conto corrente.

I DUE CONTI, e perche' sono davvero DUE
---------------------------------------
La produzione calcola il payout **dal lato dell'host**, scendendo dal listino
(`fase83_server._da_versare_host`, riga 5857):

    payout = netto_host_cents + tassa_soggiorno_cents

dove `netto_host_cents` e' quello che resta dopo commissione e costo carta.

Questo oracolo lo ricalcola **dal lato dell'OSPITE**, partendo da quello che l'ospite
ha pagato davvero e togliendo tutto cio' che non e' dell'host:

    payout = totale_cents - commissione_cents + sconto_credito_cents - costo_pagamento_cents

Il `+ sconto_credito_cents` non e' un aggiustamento di comodo: lo sconto del credito
fondatore e' finanziato dalla NOSTRA commissione, quindi l'ospite ha pagato di meno ma
**l'host non ci rimette niente** — va rimesso nel conto.

⛔ **Sono due letture che non condividono nessun campo**: la prima legge
`netto_host_cents` e `tassa_soggiorno_cents`, la seconda legge `totale_cents`,
`commissione_cents`, `sconto_credito_cents` e `costo_pagamento_cents`. Se **uno solo**
dei sei numeri di un preventivo si sposta, le due letture divergono. Questo e' il punto:
un secondo conto che riusasse gli stessi campi non sarebbe un secondo conto.

LA CONSERVAZIONE — ogni cent ha un padrone
-------------------------------------------
La stessa cosa detta in avanti, come bilancio:

    totale_cents + sconto_credito_cents  ==  payout + commissione_cents + costo_pagamento_cents
    \_________ quello che entra ________/     \________ dove finisce, fino all'ultimo cent ___/

Se questa somma non torna, **un cent e' stato creato o distrutto** — e su un preventivo
vero vuol dire che qualcuno (l'host, l'ospite o noi) sta perdendo soldi in silenzio.

⛔ COSA QUESTO ORACOLO **NON** FA (D18 punto 3), detto PRIMA e non dopo:
  · NON dice che il LISTINO sia giusto, ne' che la commissione sia quella pattuita:
    prende il preventivo come e' e chiede solo che i suoi numeri stiano in piedi fra
    loro. Se `commissione_cents` portasse una presa assurda, questo oracolo tacerebbe.
    La percentuale la sorvegliano `test_fase98_policy_commissione`, l'audit delle
    tariffe (`collaudi/audit_coerenza_tariffe.py`) e `collaudi/piano_dei_soldi.py`.
  · NON attraversa Stripe: dice quanto SPETTA all'host, non quanto e' stato bonificato.
    Il confronto col traffico vero di Stripe e' B7, e non esiste ancora.
  · NON copre le RETTIFICHE POSTUME da solo: `aumenta_payout` (credito referral scalato
    all'host) e `imposta_importo` (split di una controversia, penale trattenuta) cambiano
    la riga DOPO. Si dichiarano a `contro_il_ledger` con `aumento_cents` / `importo_deciso`:
    non dichiararle fa uscire una differenza, ed e' voluto — una rettifica silenziosa e'
    esattamente il caso in cui l'host viene pagato male.
  · NON esplora tutti gli interi: esplora la griglia dichiarata in `GRIGLIA`, scelta sui
    confini (0, 1, il cent, il tetto) piu' i valori sporchi in ogni posizione.

⚠️ E UNA PARTE DI QUESTO NON E' NUOVA, va detto qui e non scoperto dopo. Sul PREVENTIVO
un secondo conto c'era gia': `oracolo_preventivo` in `test_happy_conti.py` ricalcola da
zero il listino, e `identita_conto` (stesso file) controlla la stessa conservazione che
qui si chiama `residuo_conservazione`, per giunta su preventivi VERI. Quello che mancava
— e che B6 chiedeva — e' il pezzo dopo: **nessuno confrontava quei numeri con la riga del
REGISTRO payout**, quella da cui parte il bonifico. Cioe' il conto era sorvegliato fino
alla pagina che l'ospite legge, e da li' in poi la cifra viaggiava sulla fiducia.
Il pezzo nuovo e' `contro_il_ledger`, e la classe che lo mette al lavoro sulla catena
vera e' `test_oracolo_payout.TestSullaCatenaVERA`.
"""
import itertools
import os
import sys

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RADICE not in sys.path:                       # la radice si RICAVA, non si cabla:
    sys.path.insert(0, RADICE)                   # un percorso cablato muore su Linux e in CI

MAX_CENTS = 1_000_000_00

CAMPI_OSPITE = ("totale_cents", "commissione_cents", "sconto_credito_cents",
                "costo_pagamento_cents")
CAMPI_HOST = ("netto_host_cents", "tassa_soggiorno_cents")


def _cent(v):
    """Un importo in centesimi: intero, non bool, non negativo. Fuori da questo -> 0.

    Copia deliberata di `_c` in `fase83_server._da_versare_host`: l'oracolo NON importa
    quella funzione, se no cadrebbe insieme a lei. Un oracolo che condivide il codice con
    cio' che giudica non e' un oracolo, e' un'eco.
    """
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def da_versare_host(corpo):
    """QUANTO SPETTA ALL'HOST, contato dal lato dell'OSPITE.

    Non legge `netto_host_cents`: parte da quello che l'ospite ha pagato e toglie
    cio' che non e' dell'host. Restituisce sempre un intero >= 0.
    """
    if not isinstance(corpo, dict):
        return 0
    totale = _cent(corpo.get("totale_cents"))
    comm = _cent(corpo.get("commissione_cents"))
    sconto = _cent(corpo.get("sconto_credito_cents"))
    costo = _cent(corpo.get("costo_pagamento_cents"))
    return max(0, totale - comm + sconto - costo)


def regola_di_produzione(corpo):
    """La regola VERA, riscritta qui per poterla far correre fianco a fianco.

    ⚠️ E' un TESTIMONE, non l'originale: l'originale e' `_da_versare_host` in
    `fase83_server.py`. Che i due non divergano lo sorveglia
    `test_oracolo_payout.TestLaRegolaVeraNonSiEAllontanata`, che chiama quella vera
    attraverso il router e confronta i numeri. Senza quella guardia questo sarebbe
    l'ennesima copia destinata a invecchiare in silenzio.
    """
    if not isinstance(corpo, dict):
        return 0
    return (_cent(corpo.get("netto_host_cents"))
            + _cent(corpo.get("tassa_soggiorno_cents")))


def residuo_conservazione(corpo):
    """Quanti cent NON hanno un padrone. Deve fare 0, sempre.

        totale + sconto_credito - (payout + commissione + costo_pagamento)

    Un numero diverso da 0 vuol dire che un cent e' stato creato (positivo) o distrutto
    (negativo) fra quello che l'ospite paga e quello che i tre soggetti ricevono.
    """
    if not isinstance(corpo, dict):
        return 0
    entra = _cent(corpo.get("totale_cents")) + _cent(corpo.get("sconto_credito_cents"))
    esce = (regola_di_produzione(corpo)
            + _cent(corpo.get("commissione_cents"))
            + _cent(corpo.get("costo_pagamento_cents")))
    return entra - esce


# ── LA GRIGLIA — i pezzi di soldi da cui si costruisce un preventivo. Dichiarata. ─────
#    ⛔ Sono gli INGREDIENTI, non il preventivo: il preventivo lo monta `monta_corpo`
#       esattamente come lo monta `fase59_concierge.quota`, cosi' la griglia copre forme
#       che possono davvero uscire dalla produzione e non combinazioni impossibili.
GRIGLIA = {
    "netto": [0, 1, 100, 12000, 250000, MAX_CENTS],   # il soggiorno, gia' scontato
    "comm": [0, 1, 960, 25000],                       # la nostra presa (dedotta all'host)
    "sconto": [0, 1, 500, 5000],                      # credito fondatore (lo paghiamo noi)
    "tassa": [0, 1, 350, 21000],                      # pass-through al Comune
    "costo": [0, 25, 385, 7250],                      # costo carta (a carico host)
}
SPORCHI = [-1, 7.5, True, "7", None, float("nan")]


def monta_corpo(netto, comm, sconto, tassa, costo):
    """Il corpo di un preventivo, montato con la stessa aritmetica di `fase59.quota`.

    guest = netto - sconto · totale = guest + tassa · netto_host = netto - comm - costo
    """
    guest = netto - sconto if isinstance(netto, int) and isinstance(sconto, int) else netto
    try:
        totale = guest + tassa
    except Exception:
        totale = guest
    try:
        netto_host = netto - comm - costo
    except Exception:
        netto_host = netto
    return {
        "prezzo_netto_cents": netto,
        "commissione_cents": comm,
        "sconto_credito_cents": sconto,
        "prezzo_guest_cents": guest,
        "tassa_soggiorno_cents": tassa,
        "totale_cents": totale,
        "costo_pagamento_cents": costo,
        "netto_host_cents": netto_host,
        "valuta": "EUR",
    }


def _combinazioni_sane():
    """Le combinazioni SENSATE: la commissione e il costo carta non superano il netto.

    Le altre non si scartano per comodita': un preventivo con `comm > netto` la
    produzione non lo emette (`comm` viene tosata a `netto`, e sotto il costo carta
    risponde 422 `prezzo_non_sostenibile`). Provarle qui misurerebbe un caso che non
    esiste, e un numero gonfio e' peggio di un numero piccolo.
    """
    for netto, comm, sconto, tassa, costo in itertools.product(
            GRIGLIA["netto"], GRIGLIA["comm"], GRIGLIA["sconto"],
            GRIGLIA["tassa"], GRIGLIA["costo"]):
        if comm > netto:
            continue
        if netto - comm < costo:                 # 422 prezzo_non_sostenibile
            continue
        if sconto > netto:                       # guest <= 0 -> 422 prezzo_fuori_banda
            continue
        yield netto, comm, sconto, tassa, costo


def confronta(funzione_vera=None):
    """Fa correre i due conti fianco a fianco su tutta la griglia.

    Restituisce (provate, differenze, rotture, eccezioni):
      · `differenze` — i due conti danno numeri diversi
      · `rotture`    — la conservazione non torna: un cent senza padrone
      · `eccezioni`  — il contratto dice: MAI un'eccezione

    Sono ELENCHI di casi, non conteggi: un numero da solo non fa riparare niente.

    ⛔ `funzione_vera` E' INIETTABILE APPOSTA. Un oracolo che sa solo dire «uguali» e'
    indistinguibile da un oracolo rotto: la prova che funziona e' passargli una funzione
    SBAGLIATA e vederlo gridare (regola ferrea 10, le due direzioni).
    """
    if funzione_vera is None:
        funzione_vera = regola_di_produzione
    differenze, rotture, eccezioni, provate = [], [], [], 0

    for combo in _combinazioni_sane():
        provate += 1
        corpo = monta_corpo(*combo)
        try:
            mio = da_versare_host(corpo)
            suo = funzione_vera(corpo)
            resto = residuo_conservazione(corpo)
        except Exception as e:
            eccezioni.append((combo, type(e).__name__, str(e)))
            continue
        if mio != suo:
            differenze.append((combo, mio, suo))
        if resto != 0:
            rotture.append((combo, resto))

    # secondo giro: un valore SPORCO in ogni posizione. Qui NON si chiede che i due conti
    # coincidano (con un `None` dentro non ha senso parlare di payout): si chiede che
    # nessuno dei due ESPLODA e che entrambi restino interi >= 0. Un'eccezione qui
    # significa una prenotazione confermata e un registro payout vuoto.
    for posizione in range(5):
        for sporco in SPORCHI:
            campi = [12000, 960, 500, 350, 385]
            campi[posizione] = sporco
            provate += 1
            corpo = monta_corpo(*campi)
            try:
                mio = da_versare_host(corpo)
                suo = funzione_vera(corpo)
            except Exception as e:
                eccezioni.append((tuple(campi), type(e).__name__, str(e)))
                continue
            for nome, valore in (("oracolo", mio), ("produzione", suo)):
                if not (isinstance(valore, int) and not isinstance(valore, bool)
                        and valore >= 0):
                    differenze.append((tuple(campi), "%s ha reso %r" % (nome, valore), None))

    return provate, differenze, rotture, eccezioni


def contro_il_ledger(dashboard, prenotazione_id, corpo, *, aumento_cents=0,
                     importo_deciso=None):
    """Il numero SCRITTO nel registro (fase131) contro il numero RICALCOLATO.

    E' il pezzo che rende l'oracolo COLLEGATO invece che solo costruito (regola #23):
    senza questa funzione avremmo un secondo conto che nessuno confronta col registro
    da cui parte il bonifico vero.

    · `aumento_cents`  — un `aumenta_payout` gia' applicato (credito referral all'host)
    · `importo_deciso` — un `imposta_importo` gia' applicato (controversia/penale): se
      c'e', comanda lui e il preventivo non c'entra piu'.

    Restituisce (atteso, scritto, differenza). differenza == 0 vuol dire che il registro
    dice la verita'.
    """
    riga = None
    try:
        riga = dashboard.info(prenotazione_id)
    except Exception:
        riga = None
    scritto = _cent(riga.get("minori")) if isinstance(riga, dict) else None
    if importo_deciso is not None:
        atteso = _cent(importo_deciso)
    else:
        atteso = da_versare_host(corpo) + _cent(aumento_cents)
    if scritto is None:
        return atteso, None, atteso
    return atteso, scritto, atteso - scritto


def main():
    provate, differenze, rotture, eccezioni = confronta()
    print("=" * 86)
    print("ORACOLO DEL PAYOUT — il conto dal lato OSPITE contro quello dal lato HOST")
    print("=" * 86)
    print("  combinazioni provate ..... %d" % provate)
    print("  risultati diversi ........ %d" % len(differenze))
    print("  conservazione rotta ...... %d   (cent senza padrone)" % len(rotture))
    print("  eccezioni sollevate ...... %d   (il contratto dice: MAI un'eccezione)"
          % len(eccezioni))
    for c, a, b in differenze[:10]:
        print("    %r -> oracolo %r  produzione %r" % (c, a, b))
    for c, r in rotture[:10]:
        print("    %r -> residuo %d cent" % (c, r))
    for c, tipo, msg in eccezioni[:10]:
        print("    %r -> %s: %s" % (c, tipo, msg))
    print("-" * 86)
    print("⛔ COSA NON HA ESAMINATO: se il listino e la percentuale di commissione siano")
    print("   quelli pattuiti · il traffico vero di Stripe (e' B7, non esiste) · le")
    print("   rettifiche postume non dichiarate · gli interi fuori dalla griglia.")
    print("=" * 86)
    if differenze or rotture or eccezioni:
        print("VERDETTO: ⛔ I DUE CONTI NON COINCIDONO.")
        return 1
    print("VERDETTO: ✅ %d combinazioni, ZERO differenze, ZERO cent senza padrone." % provate)
    return 0


if __name__ == "__main__":
    sys.exit(main())
