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


def main():
    n = conta_regole()
    ricerca = n["appendice"]                       # le 44: 15 in CLAUDE.md + 29 in appendice
    solo_appendice = max(0, n["appendice"] - n["ferrea"])
    altri = (n["blocco"] + n["regola_zero"] + n["direttive"] + n["modi"] + n["collaudi"]
             + n["finale"])
    totale = ricerca + altri

    stampa_i_divieti(n)
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
    print("=" * 78)
    return 0


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
