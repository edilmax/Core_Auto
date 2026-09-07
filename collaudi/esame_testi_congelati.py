"""L'ESAME DELLA CASELLA 1 DEL BLOCCO 6 — «ZERO parole ferme in italiano».

    python collaudi/esame_testi_congelati.py              esegue l'occhio, misura e MOSTRA
    python collaudi/esame_testi_congelati.py --scrivi      misura e SCRIVE nella scheda
    python collaudi/esame_testi_congelati.py --da-file F   giudica un'uscita gia' salvata
    python collaudi/esame_testi_congelati.py --con-guasto  storce l'uscita: deve gridare, e
                                                           NON scrive mai
    python collaudi/esame_testi_congelati.py --autoprova   si vede gridare e tacere, senza
                                                           eseguire l'occhio (D18 punto 2)

⛔ LA CASELLA SI TROVA PER SOTTOSTRINGA STABILE, NON PER INDICE E NON PER TESTO INTERO.
   Il testo completo cambia (il 2026-09-06 conteneva «restano ~1034 parole», numero vecchio di
   settimane); l'indice cambia se qualcuno riordina il blocco. La sottostringa **«ZERO parole
   ferme»** e' la parte che descrive la CONDIZIONE, non il suo contorno.
   ⛔ E dev'essere UNA SOLA nel blocco: se due caselle la contenessero, l'esame non saprebbe
   quale sta spuntando -- e spuntare la casella sbagliata e' il difetto del 2026-08-21 («la
   chiave deve portare il suo ambito»). Due corrispondenze = si ferma.

COSA MISURA, e da dove
  `collaudi/occhio_del_fondatore.py` legge le pagine di `deploy/` e conta, per ciascuna, quante
  parole visibili restano fuori dagli elementi marcati per la traduzione: quelle restano in
  ITALIANO in tutte e 8 le lingue, per sempre. Questo esame non rifa' quel conto: lo ESEGUE e
  ne giudica l'esito.
  Verde solo se TUTTE E QUATTRO:
    1. l'occhio esce con codice 0                  (letto DIRETTO, mai da un tubo);
    2. la riga di totale c'e'                      (se l'occhio muore a meta', l'uscita troncata
                                                    somiglia a un esito);
    3. le pagine esaminate sono > 0                ⛔ zero pagine = verde cieco;
    4. zero parole ferme sulle pagine NON-GUSCIO.

⛔ PERCHE' I «GUSCI» SI ESCLUDONO, e perche' non e' un condono. Cinque pagine (`annullato`,
   `contratto-host`, `grazie`, `privacy`, `termini`) hanno una parola sola nel file: sono
   involucri, e il testo vero arriva dal server — `fase185_testi_legali` lo serve in tutte e 8
   le lingue, con l'impronta e la clausola su quale lingua fa fede. Contarle come «ferme»
   direbbe che il sito e' peggio di com'e'. ⛔ Ma l'esclusione la decide **l'occhio**, che marca
   la riga con «guscio»: questo esame non tiene un elenco di nomi a mano, se no il giorno che
   una pagina smette di essere un guscio resterebbe esclusa per sempre.

IL DENOMINATORE e' pagine-non-guscio x lingue: le pagine si CONTANO dall'uscita dell'occhio, le
lingue si leggono da `fase61_localizzazione.LINGUE_SUPPORTATE`. Nessuno dei due e' scritto qui.

⛔ D18: 1. `precondizioni` (senza occhio, senza casella nel piano, senza lingue si FERMA e non
   scrive) · 2. `--autoprova` nelle due direzioni · 3. `NON_GUARDA` stampato a ogni giro ·
   4. sotto guardia in `test_pipeline_ci.TestLEsameDeiTestiCongelatiNonPuoBARARE`.
"""
from __future__ import annotations

import io
import os
import re
import subprocess  # nosec B404 - esegue un nostro script, argomenti costanti, mai input esterno
import sys

QUI = os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(QUI)
sys.path.insert(0, QUI)
sys.path.insert(0, RADICE)

import scheda  # noqa: E402
from piano import BLOCCHI  # noqa: E402

BLOCCO = 6
MARCA = "ZERO parole ferme"                # la sottostringa STABILE che identifica la casella
COMANDO = "python collaudi/esame_testi_congelati.py --scrivi"
OCCHIO = os.path.join(QUI, "occhio_del_fondatore.py")

# «  nome.html   parole   tradotte   FERME   esito»
RIGA_PAGINA = re.compile(r"^\s+(\S+\.html)\s+(\d+)\s+(\d+)\s+(\d+)\s+(.*?)\s*$", re.M)
RIGA_TOTALE = re.compile(r"^parole visibili che restano in italiano su TUTTO il sito:\s*(\d+)",
                         re.M)

NON_GUARDA = (
    "non conta le parole da se': si fida del criterio dell'occhio del fondatore, e quindi",
    "  eredita i suoi punti ciechi (cio' che l'occhio non considera «visibile», non lo vede)",
    "non giudica la QUALITA' della traduzione: solo che il testo non resti congelato in italiano",
    "non guarda i testi serviti dal server (termini, privacy, contratto): quelli vivono in",
    "  `fase185_testi_legali` e hanno una loro casella",
    "non guarda le pagine servite dal VPS: legge i file di questo albero",
)


def lingue():
    from fase61_localizzazione import LINGUE_SUPPORTATE
    return LINGUE_SUPPORTATE


# --------------------------------------------------------------------------------------
#  LA CASELLA — trovata per sottostringa, e dev'essere UNA SOLA
# --------------------------------------------------------------------------------------
def caselle_candidate(blocchi=None):
    blocchi = BLOCCHI if blocchi is None else blocchi
    cond = [b for b in blocchi if b["ordine"] == BLOCCO][0]["finito_quando"]
    return [c for c in cond if MARCA in " ".join(str(c).split())]


def testo_della_casella(blocchi=None):
    trovate = caselle_candidate(blocchi)
    if len(trovate) != 1:
        raise LookupError("la casella con «%s» nel blocco %d: trovate %d, ne serve UNA"
                          % (MARCA, BLOCCO, len(trovate)))
    return trovate[0]


# --------------------------------------------------------------------------------------
#  LETTURA
# --------------------------------------------------------------------------------------
def esegui_occhio(timeout=180):
    esito = subprocess.run(  # nosec B603 - nessun shell, argomenti costanti, script nostro
        [sys.executable, OCCHIO], cwd=RADICE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, timeout=timeout)
    return esito.returncode, esito.stdout.decode("utf-8", "replace")


def pagine(uscita):
    """[(nome, parole, tradotte, ferme, guscio?)] — l'etichetta «guscio» la mette l'occhio."""
    fuori = []
    for nome, tot, trad, ferme, esito in RIGA_PAGINA.findall(uscita):
        fuori.append((nome, int(tot), int(trad), int(ferme), "guscio" in esito.lower()))
    return fuori


# --------------------------------------------------------------------------------------
#  GIUDIZIO
# --------------------------------------------------------------------------------------
def giudica(codice, uscita, n_lingue=None):
    n_lingue = len(lingue()) if n_lingue is None else n_lingue
    righe = pagine(uscita)
    vere = [p for p in righe if not p[4]]
    denominatore = len(vere) * n_lingue

    if not righe:
        return False, 0, ("l'occhio non ha esaminato NESSUNA pagina: zero righe. "
                          "Un verde senza pagine e' cieco, non e' un verde")
    if not vere:
        return False, 0, ("tutte le %d pagine risultano gusci: non resta niente da giudicare, "
                          "e un verde qui non direbbe nulla sul sito" % len(righe))
    if RIGA_TOTALE.search(uscita) is None:
        return False, denominatore, ("l'occhio non ha stampato la riga di totale: e' morto a "
                                     "meta' (%d pagine lette). Un'uscita troncata somiglia a "
                                     "un esito" % len(righe))
    ferme = [(p[0], p[3]) for p in vere if p[3] > 0]
    totale = sum(n for _, n in ferme)
    if ferme:
        return False, denominatore, ("%d parole restano congelate in italiano su %d pagine "
                                     "(su %d pagine vere x %d lingue): %s"
                                     % (totale, len(ferme), len(vere), n_lingue,
                                        ", ".join("%s:%d" % (n, k) for n, k in ferme)))
    if codice != 0:
        return False, denominatore, ("zero parole ferme ma l'occhio e' uscito con codice %d: "
                                     "esito e codice non concordano" % codice)
    return True, denominatore, ""


# --------------------------------------------------------------------------------------
#  PRECONDIZIONI
# --------------------------------------------------------------------------------------
def precondizioni():
    fuori = []
    fuori.append(("l'occhio esiste sul disco", os.path.isfile(OCCHIO), OCCHIO))
    try:
        trovate = caselle_candidate()
        fuori.append(("la casella «%s» esiste nel piano, UNA sola" % MARCA, len(trovate) == 1,
                      "trovate %d" % len(trovate)))
    except Exception as e:
        fuori.append(("la casella «%s» esiste nel piano, UNA sola" % MARCA, False,
                      "%s: %s" % (type(e).__name__, e)))
    try:
        n = len(lingue())
        fuori.append(("so quante lingue dichiariamo", n > 1, "%d lingue" % n))
    except Exception as e:
        fuori.append(("so quante lingue dichiariamo", False, "%s: %s" % (type(e).__name__, e)))
    return fuori


# --------------------------------------------------------------------------------------
#  AUTOPROVA
# --------------------------------------------------------------------------------------
def _finta(pagine_vere=(0, 0), gusci=1, totale=True):
    righe = ["  pagina                    parole  tradotte     FERME   esito"]
    for i, ferme in enumerate(pagine_vere):
        righe.append("  vera%d.html                   100        %3d       %3d   OK"
                     % (i, 100 - ferme, ferme))
    for i in range(gusci):
        righe.append("  guscio%d.html                   1          0         1   "
                     "-- guscio: il testo arriva dal server" % i)
    if totale:
        righe.append("parole visibili che restano in italiano su TUTTO il sito: %d"
                     % (sum(pagine_vere) + gusci))
    return "\n".join(righe) + "\n"


def autoprova():
    casi = [
        ("sana: 2 pagine vere, 0 ferme, 1 guscio", 0, _finta((0, 0), 1), True, 16),
        ("una parola ferma su una pagina vera", 1, _finta((1, 0), 1), False, 16),
        ("il guscio ha 1 ferma ma NON conta", 0, _finta((0, 0), 3), True, 16),
        ("nessuna pagina (l'occhio non ha guardato)", 0, "", False, 0),
        ("solo gusci: niente da giudicare", 0, _finta((), 2), False, 0),
        ("troncata: nessuna riga di totale", 0, _finta((0, 0), 1, totale=False), False, 16),
        ("zero ferme ma codice d'uscita 1", 1, _finta((0, 0), 1), False, 16),
    ]
    print("AUTOPROVA — l'esame sa gridare E sa tacere (D18 punto 2)")
    tutto = True
    for nome, codice, uscita, atteso_verde, atteso_den in casi:
        verde, den, motivo = giudica(codice, uscita, n_lingue=8)
        bene = (verde == atteso_verde) and (den == atteso_den)
        tutto = tutto and bene
        print("  %-44s -> %-5s den=%-3d %s" % (nome[:44], "VERDE" if verde else "rosso", den,
                                               "OK" if bene else "⛔ ATTESO DIVERSO"))
        if motivo and not verde:
            print("        perche': %s" % motivo[:104])

    # La casella si trova per sottostringa: si prova anche QUELLO, con piani costruiti.
    print("")
    print("  la casella si trova per sottostringa, e dev'essere UNA sola:")
    finti = {
        "una sola": [{"ordine": BLOCCO, "finito_quando": ["x " + MARCA + " y", "altro"]}],
        "nessuna": [{"ordine": BLOCCO, "finito_quando": ["testo vecchio con ~1034", "altro"]}],
        "due (ambigua)": [{"ordine": BLOCCO,
                           "finito_quando": ["a " + MARCA, "b " + MARCA]}],
    }
    attesi = {"una sola": True, "nessuna": False, "due (ambigua)": False}
    for nome, blocchi in finti.items():
        try:
            testo_della_casella(blocchi)
            esito = True
        except LookupError:
            esito = False
        bene = esito == attesi[nome]
        tutto = tutto and bene
        print("    %-16s -> %-9s %s" % (nome, "trovata" if esito else "si ferma",
                                        "OK" if bene else "⛔ ATTESO DIVERSO"))
    print("")
    print("VERDETTO AUTOPROVA: %s" % ("l'esame distingue tutti i casi"
                                      if tutto else "⛔ NON DISTINGUE: non fidarsi"))
    return 0 if tutto else 1


# --------------------------------------------------------------------------------------
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--autoprova" in argv:
        return autoprova()

    print("=" * 92)
    try:
        print("L'ESAME DEI TESTI CONGELATI — «%s»"
              % " ".join(str(testo_della_casella()).split())[:72])
    except Exception:
        print("L'ESAME DEI TESTI CONGELATI — (casella non trovata nel piano di questo albero)")
    print("=" * 92)

    fuori = precondizioni()
    print("PRECONDIZIONI (l'attrezzo misura prima se stesso)")
    for voce, esito, dett in fuori:
        print("  %-46s %-3s %s" % (voce[:46], "OK" if esito else "NO", str(dett)[:38]))
    if not all(e for _, e, _ in fuori):
        print("")
        print("⛔ PRECONDIZIONI NON SODDISFATTE: mi fermo e NON scrivo nella scheda.")
        return 2

    if "--da-file" in argv:
        p = argv[argv.index("--da-file") + 1]
        uscita = io.open(p, encoding="utf-8", errors="replace").read()
        codice = 0
        print("\nletto da file: %s" % p)
    else:
        print("\nESEGUO collaudi/occhio_del_fondatore.py ...")
        codice, uscita = esegui_occhio()
        print("  codice d'uscita LETTO DIRETTO: %d" % codice)

    if "--con-guasto" in argv:
        uscita = uscita.replace("  admin.html", "  admin.html   GUASTO", 1)
        uscita = re.sub(r"^(\s+admin\.html\s+\d+\s+\d+\s+)\d+", r"\g<1>7", uscita,
                        count=1, flags=re.M)
        codice = 1
        print("  ⚠️  --con-guasto: 7 parole ferme iniettate. Deve gridare, e NON scrivere.")

    verde, denominatore, motivo = giudica(codice, uscita)
    righe = pagine(uscita)
    vere = [p for p in righe if not p[4]]

    print("")
    print("MISURA")
    print("  pagine esaminate                      : %d (di cui %d gusci, esclusi dall'occhio)"
          % (len(righe), len(righe) - len(vere)))
    print("  denominatore (pagine vere x lingue)   : %d" % denominatore)
    print("  esito                                 : %s" % ("VERDE" if verde else "ROSSO"))
    if motivo:
        print("  perche'                               : %s" % motivo)

    print("")
    print("⚠️  COSA QUESTO ESAME **NON** GUARDA (D18 punto 3)")
    for r in NON_GUARDA:
        print("  · %s" % r)

    if "--scrivi" in argv:
        if "--con-guasto" in argv:
            print("\n⛔ --con-guasto NON scrive mai nella scheda.")
            return 1
        print("")
        print("SCRITTURA NELLA SCHEDA")
        riga = scheda.registra(testo_della_casella(), esito=verde, denominatore=denominatore,
                               comando=COMANDO, ordine=BLOCCO, motivo=motivo or None)
        print("  scritta: blocco %d · esito %s · denominatore %d · impronta %s · motivo: %s"
              % (riga["blocco"], riga["esito"], riga["denominatore"], riga["impronta"],
                 riga.get("motivo") or "-"))
    return 0 if verde else 1


if __name__ == "__main__":
    sys.exit(main())
