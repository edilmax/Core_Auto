# -*- coding: utf-8 -*-
"""🛡️ IL GIUDIZIO SUL PIANO DEI SOLDI — un posto solo, tre chiamanti.

PERCHE' STA QUI E NON DENTRO IL COLLAUDO. Il fatto «`faseNN` e' FATTO» e' scritto **a mano
in tre posti**: la tabella dei blocchi in `REGISTRO_INGEGNERIA.md` §2-bis, il riepilogo
«DOVE SIAMO» poche righe sopra, e la tabella «QUANTO MANCA SUI SOLDI» in `RIPRENDI_QUI.md`.
Il 2026-08-12 ne e' stato aggiornato **UNO SOLO**: gli altri due dicevano ancora che
`fase66` era «il prossimo da fare» quando era finito, con cinque difetti sui soldi chiusi
dentro. **Una chat nuova avrebbe rifatto da capo un lavoro finito** -- una sessione intera.

⛔ E IL GIUDIZIO STA IN UN POSTO SOLO PER LA STESSA RAGIONE CHE LO HA RESO NECESSARIO. Se
vivesse dentro `test_piano_dei_soldi.py`, il pre-fatto dovrebbe importare un *collaudo* per
decidere se fermare un commit -- direzione sbagliata -- oppure tenerne una copia. La copia
e' la malattia: *lo stesso criterio scritto due volte, e la seconda che resta indietro*.
Il precedente e' `consegne_troppo_indietro` in `prima_di_lanciare.py:145`, importata da
`test_pipeline_ci.py` invece di essere ricopiata, con lo stesso commento.

I TRE CHIAMANTI:
  · `test_piano_dei_soldi.py` ......... le guardie nella suite
  · `collaudi/prima_di_dire_fatto.py` . il controllo 10, che FERMA IL COMMIT in 0,1 secondi
  · chiunque, a mano ................. `python collaudi/piano_dei_soldi.py`

I DUE DIFETTI CHE SORVEGLIA sono capitati davvero, in due giorni, e non sono immaginati:
  · **2026-08-12** -- lo stesso modulo dichiarato FATTO in un posto e DA FARE in un altro.
  · **2026-08-11** -- un modulo «da fare» che e' **codice morto**: `fase43_commissione` con
    31 punti di mutazione su codice che la produzione non raggiunge. Con `fase44` e `fase35`
    fanno **81 punti che stavano per essere buttati**.

⛔ IL MARCATORE NON E' LA SPUNTA VERDE, ED E' LA TRAPPOLA PRINCIPALE DI QUESTO FILE.
Nel Blocco 2 c'e' `✅ fase147_tassa_comunale **AGGIUNTO: e' VIVO**`: ha la spunta e **non e'
fatto** -- e' stato aggiunto al piano. E nel Blocco 3 c'e' `fase133 (gia' fatto in 1)`, che
vuol dire «gia' ELENCATO nel Blocco 1». Leggere la spunta, o ignorare le maiuscole,
griderebbe su moduli che nessuno ha finito -- e **un falso allarme e' un difetto quanto un
allarme mancato** (regola ferrea 10): insegna a ignorare i segnali, e un guardiano che grida
a torto viene spento entro tre giorni.

COME E' COSTRUITO (D18):
  1. **Misura prima se stesso**: ancora assente o elenco vuoto -> `MisuraNonValida`. Il
     vuoto non e' un valore, e' assenza di misura (sbaglio S1).
  2. **Provabile nelle DUE direzioni**: ogni funzione accetta il **testo**, non il percorso.
     Un giudizio che sa leggere solo i file veri non si puo' mettere alla prova senza
     sporcarli (D19).
  3. **Dichiara cosa NON esamina**: `NON_CONTROLLO`, stampata dentro il testo di ogni
     rosso -- si legge quando serve, non in un documento che nessuno apre.
"""
import io
import os
import re
import sys

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRO = "REGISTRO_INGEGNERIA.md"
CONSEGNE = "RIPRENDI_QUI.md"

FATTO, DA_FARE, MORTO = "FATTO", "DA FARE", "CODICE MORTO"

# `fase167_credito_single_use` e `fase167` sono LO STESSO modulo, e i documenti li scrivono
# in entrambi i modi: si confronta il NUMERO, se no il guardiano griderebbe sugli abbreviati.
_FASE = re.compile(r"\bfase(\d+)")

# `| **1** | <i moduli del blocco> | <punti> | <perche'> |` -- la tabella dei blocchi §2-bis.
_RIGA_BLOCCO = re.compile(r"^\|\s*\*\*(\d+)\*\*\s*\|(.+?)\|", re.M)

# `| `fase162_pagamenti_pendenti` | 91 | 13 | 4 |` -- la tabella «QUANTO MANCA SUI SOLDI».
_RIGA_CENSIMENTO = re.compile(
    r"^\|\s*`(fase\d+[A-Za-z0-9_]*)`\s*\|\s*(\d+)\s*\|\s*\**(\d+)\**\s*\|", re.M)

_TRATTINO = r"\s*[—–-]\s*"
_ANCORA_GIUDICATI = re.compile(r"passati dal giudice" + _TRATTINO + r"(\d+)")
_ANCORA_RESTANO = re.compile(r"CHE RESTANO" + _TRATTINO + r"(\d+),\s*per\s*(\d+)\s*punti")
_ANCORA_MORTI = re.compile(r"FUORI DALL'ELENCO PERCH\w+ SONO CODICE MORTO")
_ANCORA_RIEPILOGO = re.compile(r"DOVE SIAMO,\s*rimisurato col censimento")

_CONTO_GIUDICATI = re.compile(r"(\d+) moduli dei soldi giudicati")
_CONTO_RESTANO = re.compile(r"(\d+) che restano, per (\d+) punti")
_CONTO_MORTI = re.compile(r"(\d+) punti che [Nn][Oo][Nn] vanno fatti")

# D18 punto 3. Non e' una formalita': un taglio silenzioso fa sembrare «coperto» cio' che
# nessuno ha guardato. Queste righe finiscono DENTRO il testo di ogni rosso.
NON_CONTROLLO = (
    "non dice se un modulo dichiarato FATTO lo sia DAVVERO: quello lo dice solo un giro del "
    "Giudice (`collaudi/mutazione_prodotto.py`), non un documento",
    "non verifica i PUNTI di mutazione dichiarati per ogni modulo contro il censimento vero: "
    "controlla solo che la somma della tabella sia il totale che la tabella stessa dichiara",
    "legge TRE posti, quelli noti al 2026-08-12: se qualcuno scrive lo stesso fatto in un "
    "QUARTO posto, questo guardiano non lo sa e non lo dira'",
    "⛔ NON VEDE UN MODULO VIVO CON DENTRO CODICE MORTO, ed e' il buco piu' grosso. "
    "`raggiungibilita.py` conta gli IMPORT, non i SIMBOLI usati: misurato il 2026-08-12 su "
    "`fase133_split_quote_uguali`, la produzione ne raggiunge ~9 righe su 142 (la sola "
    "`riparti_uguale`, da `fase83_server.py:6747`) mentre la classe `SplitQuoteUguali` non e' "
    "istanziabile da nessun punto -- zero chiamate a `crea_split_quote`. Il modulo risulta "
    "VIVO e dentro e' morto al 94%, quindi i punti di mutazione che il piano gli attribuisce "
    "sono in buona parte su codice che nessuno esegue. Questo guardiano NON lo dice",
    "non giudica i moduli che NON sono dei soldi: il piano parla solo di quelli",
)


class MisuraNonValida(Exception):
    """L'ancora non c'e', o l'elenco e' vuoto. Non e' un verde: e' assenza di misura (S1)."""


def leggi(nome, radice=RADICE):
    with io.open(os.path.join(radice, nome), encoding="utf-8") as f:
        return f.read()


def _fasi(testo):
    """I numeri di fase citati in `testo`, nell'ordine in cui compaiono."""
    return ["fase" + n for n in _FASE.findall(testo)]


def _appiattisci(testo):
    """Gli a-capo dei `.md` spezzano le frasi a meta' (`codice\\nmorto`): qui non contano."""
    return re.sub(r"\s+", " ", testo)


def _paragrafo_dopo(testo, ancora, nome):
    trovato = ancora.search(testo)
    if trovato is None:
        raise MisuraNonValida(
            "non trovo l'ancora di %s. Questo giudizio legge posti PRECISI: se la prosa e' "
            "stata riscritta, o la sezione spostata, va aggiornata l'ancora in "
            "collaudi/piano_dei_soldi.py -- non si lascia il controllo muto, perche' un "
            "controllo che non trova il bersaglio e' ROSSO, non silenzioso (sbaglio S2)."
            % nome)
    resto = testo[trovato.end():]
    fine = resto.find("\n\n")
    return (resto if fine < 0 else resto[:fine]), trovato


def stato_della_voce(voce):
    """FATTO / CODICE MORTO / DA FARE per una voce della tabella dei blocchi.

    ⛔ Il case CONTA e non e' un vezzo: `(gia' fatto in 1)` in minuscolo vuol dire «gia'
    ELENCATO nel Blocco 1», non «completato». Con un `.upper()` quella nota diventerebbe un
    FATTO e il guardiano griderebbe su `fase133`, che nessuno ha finito.
    """
    if "CODICE MORTO" in voce:
        return MORTO
    if "FATTO" in voce:
        return FATTO
    return DA_FARE


# --------------------------------------------------------------------------------------
# i tre posti -- ognuno restituisce OSSERVAZIONI `(modulo, stato, dove)`, non un dizionario:
# un dizionario farebbe vincere in silenzio l'ultimo posto letto, cioe' perderebbe proprio
# la contraddizione che questo file esiste per trovare.
# --------------------------------------------------------------------------------------
def posto1_tabella_dei_blocchi(registro):
    """`REGISTRO_INGEGNERIA.md` §2-bis: i cinque blocchi, voci separate da `·`."""
    osservate = []
    for numero, cella in _RIGA_BLOCCO.findall(registro):
        for voce in cella.split("·"):
            stato = stato_della_voce(voce)
            for modulo in _fasi(voce):
                osservate.append((modulo, stato, "%s blocco %s" % (REGISTRO, numero)))
    if not osservate:
        raise MisuraNonValida(
            "la tabella dei blocchi di %s §2-bis non nomina NESSUN modulo: o e' stata "
            "riscritta in un'altra forma, o e' sparita. In entrambi i casi il piano dei "
            "soldi non e' piu' leggibile da una macchina." % REGISTRO)
    return osservate


def posto2_riepilogo(registro):
    """Il riepilogo «DOVE SIAMO» di `REGISTRO_INGEGNERIA.md`: nomi **e** conti dichiarati."""
    grezzo, _ = _paragrafo_dopo(registro, _ANCORA_RIEPILOGO, "«DOVE SIAMO» in " + REGISTRO)
    piatto = _appiattisci(grezzo)
    osservate = []
    fatti = re.search(r"sono stati fatti\s*\(([^)]*)\)", piatto)
    if fatti:
        for modulo in _fasi(fatti.group(1)):
            osservate.append((modulo, FATTO, "%s riepilogo DOVE SIAMO" % REGISTRO))
    morti = re.search(r"codice morto\**\s*\(([^)]*)\)", piatto)
    if morti:
        for modulo in _fasi(morti.group(1)):
            osservate.append((modulo, MORTO, "%s riepilogo DOVE SIAMO" % REGISTRO))
    conti = {}
    for chiave, regex in (("giudicati", _CONTO_GIUDICATI), ("morti", _CONTO_MORTI)):
        trovato = regex.search(piatto)
        if trovato is None:
            raise MisuraNonValida(
                "il riepilogo «DOVE SIAMO» di %s non dichiara piu' il conto dei %s. Quel "
                "numero e' l'unica cosa che permette di accorgersi che gli elenchi sono "
                "cresciuti e il riepilogo no (D22)." % (REGISTRO, chiave))
        conti[chiave] = int(trovato.group(1))
    restano = _CONTO_RESTANO.search(piatto)
    if restano is None:
        raise MisuraNonValida(
            "il riepilogo «DOVE SIAMO» di %s non dichiara piu' «N che restano, per M punti»"
            % REGISTRO)
    conti["restano"], conti["punti"] = int(restano.group(1)), int(restano.group(2))
    return osservate, conti


def posto3_censimento(consegne):
    """`RIPRENDI_QUI.md` «QUANTO MANCA SUI SOLDI»: i giudicati, la tabella, i morti."""
    osservate, conti = [], {}

    giudicati, ancora_g = _paragrafo_dopo(
        consegne, _ANCORA_GIUDICATI, "«passati dal giudice» in " + CONSEGNE)
    conti["giudicati"] = int(ancora_g.group(1))
    for modulo in _fasi(giudicati):
        osservate.append((modulo, FATTO, "%s passati dal giudice" % CONSEGNE))

    inizio = _ANCORA_RESTANO.search(consegne)
    if inizio is None:
        raise MisuraNonValida(
            "%s non dichiara piu' «Moduli dei SOLDI CHE RESTANO - N, per M punti»: senza "
            "quella riga la tabella qui sotto non ha un totale con cui confrontarsi, e un "
            "elenco senza denominatore non dice quanto manca." % CONSEGNE)
    conti["restano"], conti["punti"] = int(inizio.group(1)), int(inizio.group(2))
    fine = _ANCORA_MORTI.search(consegne, inizio.end())
    if fine is None:
        raise MisuraNonValida(
            "%s non dichiara piu' quali moduli sono FUORI DALL'ELENCO perche' codice morto. "
            "E' la riga che l'11 agosto ha salvato 81 punti di lavoro inutile: senza, il "
            "piano torna a mandare a setacciare codice che la produzione non raggiunge."
            % CONSEGNE)
    tabella = consegne[inizio.end():fine.start()]
    punti_tabella = 0
    for modulo, punti, _nomi in _RIGA_CENSIMENTO.findall(tabella):
        osservate.append((_fasi(modulo)[0], DA_FARE, "%s tabella che RESTANO" % CONSEGNE))
        punti_tabella += int(punti)
    conti["punti_tabella"] = punti_tabella

    blocco_morti, _ = _paragrafo_dopo(consegne, _ANCORA_MORTI, "i morti in " + CONSEGNE)
    piatto = _appiattisci(blocco_morti)
    for modulo in _fasi(piatto):
        osservate.append((modulo, MORTO, "%s fuori perche' morti" % CONSEGNE))
    trovato = _CONTO_MORTI.search(piatto)
    if trovato is None:
        raise MisuraNonValida(
            "l'elenco dei morti in %s non dichiara piu' quanti punti sono «che NON vanno "
            "fatti»: e' il numero che dice quanto lavoro quella riga ha risparmiato."
            % CONSEGNE)
    conti["morti"] = int(trovato.group(1))
    return osservate, conti


def osservazioni(registro, consegne):
    """Tutte le dichiarazioni dei tre posti, ognuna con il posto che l'ha fatta."""
    tutte = list(posto1_tabella_dei_blocchi(registro))
    tutte.extend(posto2_riepilogo(registro)[0])
    tutte.extend(posto3_censimento(consegne)[0])
    return tutte


def contraddizioni(tutte):
    """{modulo: {stato: [posti]}} per i moduli su cui i posti NON dicono la stessa cosa."""
    per_modulo = {}
    for modulo, stato, dove in tutte:
        per_modulo.setdefault(modulo, {}).setdefault(stato, []).append(dove)
    return dict((m, s) for m, s in per_modulo.items() if len(s) > 1)


def da_fare_ma_morti(tutte, morti_veri):
    """I moduli che il piano manda a setacciare e che la produzione non raggiunge.

    `morti_veri` arriva da FUORI (`raggiungibilita.cammina()`) di proposito: cosi' questo
    giudizio si puo' provare iniettando un elenco finto, senza dipendere dal disco.
    """
    dichiarati = set(m for m, stato, _ in tutte if stato == DA_FARE)
    numeri_morti = set(_fasi(m)[0] for m in morti_veri if _fasi(m))
    return sorted(dichiarati & numeri_morti, key=lambda x: int(x[4:]))


def orfani_senza_blocco(registro, consegne):
    """I moduli «da fare» che non stanno in NESSUN blocco: mai giudicati, per sempre.

    ⛔ IL DIFETTO DI `fase147`, e il confronto fra stati NON PUO' VEDERLO: un modulo che sta
    in un posto solo non contraddice nessuno. L'11 agosto `fase147_tassa_comunale` era vivo,
    dei soldi, e fuori da ogni blocco -- cioe' nessuno l'avrebbe mai preso in mano.
    """
    nei_blocchi = set(m for m, _s, _d in posto1_tabella_dei_blocchi(registro))
    da_fare = set(m for m, s, _d in posto3_censimento(consegne)[0] if s == DA_FARE)
    return sorted(da_fare - nei_blocchi, key=lambda x: int(x[4:]))


def conti_che_non_tornano(registro, consegne):
    """Le righe dei numeri scritti a mano che non combaciano con gli elenchi veri.

    E' il difetto del 12 agosto nella sua forma piu' facile da commettere: si toglie un
    modulo dall'elenco e si dimentica di cambiare il titolo che lo conta. Un elenco senza
    denominatore non dice quanto manca (D22).
    """
    _o2, c2 = posto2_riepilogo(registro)
    oss3, c3 = posto3_censimento(consegne)
    guasti = []
    for chiave in ("giudicati", "restano", "punti", "morti"):
        if c2[chiave] != c3[chiave]:
            guasti.append("%s dice %s=%d e %s dice %d: la stessa cifra in due posti, e la "
                          "seconda e' rimasta indietro"
                          % (REGISTRO, chiave, c2[chiave], CONSEGNE, c3[chiave]))
    elencati = len(set(m for m, s, d in oss3 if s == FATTO and "passati dal giudice" in d))
    if c3["giudicati"] != elencati:
        guasti.append("«passati dal giudice - %d» ma l'elenco ne nomina %d"
                      % (c3["giudicati"], elencati))
    in_tabella = len([m for m, s, d in oss3 if s == DA_FARE and "tabella" in d])
    if c3["restano"] != in_tabella:
        guasti.append("«CHE RESTANO - %d» ma la tabella ha %d righe: finire un modulo vuol "
                      "dire togliere la riga E cambiare il numero, e farne uno solo e' il "
                      "difetto del 2026-08-12" % (c3["restano"], in_tabella))
    if c3["punti"] != c3["punti_tabella"]:
        guasti.append("«per %d punti» ma la colonna somma %d: un totale che non e' la somma "
                      "delle sue parti e' un numero calcolato a mente (D22, `Ran 5429`)"
                      % (c3["punti"], c3["punti_tabella"]))
    return guasti


def limiti_dichiarati():
    """Le righe di `NON_CONTROLLO`, pronte da incollare in un messaggio di rosso."""
    return "\n".join("   ⚠ " + riga for riga in NON_CONTROLLO)


def rapporto(registro, consegne, morti_veri):
    """(va_bene, righe) -- TUTTI i criteri e TUTTO il testo, in un posto solo.

    ⛔ Sta qui e non nei chiamanti per la stessa ragione di tutto il resto: se il collaudo e
    il pre-fatto scrivessero due messaggi loro, sarebbero due copie e una resterebbe
    indietro. Chi chiama decide solo il verdetto (rosso, uscita 1, ...), non le parole.
    ⛔ E copre TUTTI E QUATTRO i modi in cui il piano si rompe, non i due piu' evidenti: il
    gancio di git chiama questa funzione, quindi quello che manca qui non ferma nessun commit.
    """
    righe = []
    tutte = osservazioni(registro, consegne)

    rotti = contraddizioni(tutte)
    if rotti:
        righe.append("I TRE POSTI SI CONTRADDICONO su %d modulo/i: chi legge il posto "
                     "sbagliato rifa' un lavoro finito, o salta un lavoro aperto. E' il "
                     "difetto del 2026-08-12." % len(rotti))
        for modulo in sorted(rotti, key=lambda x: int(x[4:])):
            for stato, posti in sorted(rotti[modulo].items()):
                righe.append("   %-8s -> %-12s in: %s" % (modulo, stato, ", ".join(posti)))

    sprecati = da_fare_ma_morti(tutte, morti_veri)
    if sprecati:
        righe.append(
            "IL PIANO MANDA A SETACCIARE CODICE MORTO: %s. E' il difetto del 2026-08-11 "
            "(`fase43_commissione`, 31 punti su codice che la produzione non raggiunge). "
            "`raggiungibilita.py` ha bias GENEROSO: se dice MORTO, e' morto."
            % ", ".join(sprecati))

    orfani = orfani_senza_blocco(registro, consegne)
    if orfani:
        righe.append(
            "MODULI DEI SOLDI FUORI DA OGNI BLOCCO: %s. Fuori da ogni blocco vuol dire che "
            "nessuno li prendera' in mano -- mai giudicati, per sempre. E' il difetto di "
            "`fase147_tassa_comunale`, trovato l'11 agosto." % ", ".join(orfani))

    for guasto in conti_che_non_tornano(registro, consegne):
        righe.append("I CONTI DEL PIANO NON TORNANO: " + guasto)

    return (not righe), righe


def main():
    try:
        import raggiungibilita
    except ImportError:  # chiamato da fuori `collaudi/`
        from collaudi import raggiungibilita
    registro, consegne = leggi(REGISTRO), leggi(CONSEGNE)
    _vivi, morti, _tutti = raggiungibilita.cammina()
    tutte = osservazioni(registro, consegne)
    va_bene, righe = rapporto(registro, consegne, morti)
    print("=" * 86)
    print("\U0001f6e1️  IL PIANO DEI SOLDI -- i tre posti dicono la stessa cosa?")
    print("=" * 86)
    for stato in (FATTO, DA_FARE, MORTO):
        moduli = sorted(set(m for m, s, _ in tutte if s == stato), key=lambda x: int(x[4:]))
        print("  %-13s %2d: %s" % (stato, len(moduli), " ".join(moduli)))
    print("  %-13s %2d dichiarazioni su %d moduli distinti (il DENOMINATORE)"
          % ("in tutto", len(tutte), len(set(m for m, _s, _d in tutte))))
    print("-" * 86)
    if va_bene:
        print("  OK    i tre posti sono d'accordo, e nessun modulo del piano e' codice morto")
    else:
        for riga in righe:
            print("  " + riga)
    print("-" * 86)
    print("⛔ COSA QUESTO CONTROLLO NON ESAMINA (D18 punto 3)")
    print(limiti_dichiarati())
    print("=" * 86)
    return 0 if va_bene else 1


if __name__ == "__main__":
    sys.exit(main())
