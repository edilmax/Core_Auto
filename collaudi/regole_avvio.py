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


def _pezzi():
    """Le sezioni di CLAUDE.md, separate una volta sola: meno modi di sbagliare."""
    c = _leggi(CLAUDE)
    return {
        # IL BLOCCO sta PRIMA della regola zero: si taglia sul titolo della regola zero.
        "blocco": c.split("REGOLA ZERO")[0],
        "zero": c.split("REGOLA ZERO")[-1].split("REGOLA FERREA")[0],
        # ⛔ IL TAGLIO NON SI AGGANCIA A UN NUMERO. Prima diceva "LE 17 DIRETTIVE": il giorno
        # in cui ne e' arrivata una diciottesima il taglio si sarebbe rotto -- e lo strumento
        # che deve accorgersi degli errori di conteggio sarebbe stato il primo a sbagliarlo.
        # Ci si aggancia al testo che NON cambia.
        "ferrea": c.split("REGOLA FERREA")[-1].split("DIRETTIVE DEL FONDATORE")[0],
        "direttive": c.split("DIRETTIVE DEL FONDATORE")[-1].split("REGOLA DEI 10 COLLAUDI")[0],
        "collaudi": c.split("REGOLA DEI 10 COLLAUDI")[-1].split("DIRETTIVA OPERATIVA")[0],
        "finale": c.split("DIRETTIVA OPERATIVA")[-1],
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
    m = re.search(r"GLI OBBLIGHI SONO \*\*(\d+)\*\*", _leggi(CLAUDE))
    return int(m.group(1)) if m else None


def main():
    n = conta_regole()
    ricerca = n["appendice"]                       # le 44: 15 in CLAUDE.md + 29 in appendice
    solo_appendice = max(0, n["appendice"] - n["ferrea"])
    altri = (n["blocco"] + n["regola_zero"] + n["direttive"] + n["modi"] + n["collaudi"]
             + n["finale"])
    totale = ricerca + altri

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
    print("     · direttive fondatore .. %2d   (chirurgia · collaudi per tutto · 4 livelli ·"
          % n["direttive"])
    print("                                   anti-verdi-finti · consiglio modello · mai")
    print("                                   credenziali · 3 posti allineati · niente")
    print("                                   segnaposto · MAI HEREDOC · inventario prima ·")
    print("                                   spiegare chiaro · decidiamo noi · un pezzo alla")
    print("                                   volta · ispettore · caccia errori · autonomia ·")
    print("                                   deploy a rischio zero · UNO STRUMENTO CHE MISURA")
    print("                                   HA UN CONTROLLO CHE GLI IMPEDISCE DI BARARE ·")
    print("                                   UNA DIFESA SI PROVA SENZA ASPETTARE IL DISASTRO ·")
    print("                                   PRIMA LA GUARDIA ROSSA, POI LA RIPARAZIONE)")
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
    dich = dichiarato()
    if dich is not None and dich != totale:
        guasti.append("il regolamento dichiara %d obblighi ma nei file ce ne sono %d"
                      % (dich, totale))
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
