"""L'ESAME DELLA CASELLA 1 DEL BLOCCO 4 — «ogni cifra pubblica coincide col motore».

    python collaudi/esame_cifre_pubbliche.py              esegue l'audit, misura e MOSTRA
    python collaudi/esame_cifre_pubbliche.py --scrivi      misura e SCRIVE nella scheda (anche
                                                           un rosso, col suo motivo)
    python collaudi/esame_cifre_pubbliche.py --da-file F   giudica un'uscita gia' salvata
    python collaudi/esame_cifre_pubbliche.py --con-guasto  storce l'uscita: deve gridare, e
                                                           NON scrive mai
    python collaudi/esame_cifre_pubbliche.py --autoprova   si vede gridare e tacere, senza
                                                           eseguire l'audit (D18 punto 2)

⛔ IL TESTO DELLA CASELLA NON SI RICOPIA: si legge da `collaudi/piano.py`. E' la chiave della
   scheda, e una copia a mano spunterebbe **una casella diversa** il giorno che il piano cambia.
   (Costato il 2026-08-21: una chiave senza il suo ambito spuntava la casella sbagliata.)

COSA MISURA, e da dove
  `collaudi/audit_millimetrico.py` confronta gia' ogni affermazione verificabile dei 5 documenti
  ufficiali col motore reale: tariffe, conteggi, percorsi, rotte, variabili d'ambiente. Questo
  esame **non rifa' quel lavoro**: lo ESEGUE e ne giudica l'esito, perche' due copie dello stesso
  criterio divergono sempre (la malattia che questo progetto ha gia' pagato sei volte).
  Il giudizio e' verde solo se TUTTE E QUATTRO:
    1. l'audit esce con codice 0                     (letto DIRETTO, mai da un tubo);
    2. zero righe `[!!]`                             (nessuna discrepanza);
    3. la riga `VERDETTO: 0 DISCREPANZE` c'e'        (l'audit ha davvero concluso, non e' morto
                                                      a meta' lasciando un'uscita che sembra sana);
    4. i confronti eseguiti sono > 0                 ⛔ E' LA CONDIZIONE CHE CONTA DAVVERO.

⛔ PERCHE' IL PUNTO 4 ESISTE. Un audit che non confronta NIENTE esce con 0 e dice «0
   discrepanze»: sarebbe un verde perfetto e cieco. E' il modo di sbagliare piu' pericoloso che
   conosciamo (D18 punto 1: «prima di credere a un verde, l'attrezzo ha guardato qualcosa?»).
   Il denominatore percio' NON e' un numero scritto qui: si CONTA dalle righe che l'audit ha
   stampato. Misurato il 2026-09-06: **78 confronti**, mentre le chiamate scritte nel sorgente
   sono **47** -- alcune stanno dentro cicli. Chi avesse contato a mano avrebbe scritto 47, e il
   denominatore avrebbe mentito restando plausibile.

⛔ D18, LE QUATTRO CONDIZIONI DI UNO STRUMENTO CHE MISURA:
   1. misura PRIMA se stesso (`precondizioni`): senza l'audit, senza python, senza la casella nel
      piano si FERMA e non scrive;
   2. provato nelle DUE direzioni (`--autoprova`): si vede gridare su un'uscita con una
      discrepanza, su una troncata, su una VUOTA -- e tacere su una sana;
   3. dichiara cosa NON ha esaminato: `NON_GUARDA`, stampato a ogni giro;
   4. e' sotto guardia: `test_pipeline_ci.TestLEsameDelleCifrePubblicheNonPuoBARARE`.
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

import scheda  # noqa: E402
from piano import BLOCCHI  # noqa: E402

BLOCCO = 4
INDICE_CASELLA = 0                       # la prima casella del blocco (0-based)
COMANDO = "python collaudi/esame_cifre_pubbliche.py --scrivi"
AUDIT = os.path.join(QUI, "audit_millimetrico.py")

RIGA_OK = re.compile(r"^\s*\[OK\]\s", re.M)
RIGA_KO = re.compile(r"^\s*\[!!\]\s", re.M)
RIGA_VERDETTO = re.compile(r"^VERDETTO:\s*(\d+)\s*DISCREPANZE", re.M)

NON_GUARDA = (
    "non verifica le cifre da se': si fida del criterio di `audit_millimetrico.py`, e quindi",
    "  eredita i suoi punti ciechi (cio' che l'audit non confronta, questo esame non lo vede)",
    "non guarda le pagine servite dal VPS: confronta i documenti del repository col codice",
    "  del repository -- se il server gira un altro commit, questa misura non parla di quello",
    "non giudica i testi tradotti: quelli sono la casella 1 del Blocco 6",
)


# --------------------------------------------------------------------------------------
#  LETTURA
# --------------------------------------------------------------------------------------
def esegui_audit(timeout=180):
    """Esegue l'audit come PROCESSO e restituisce (codice_uscita, uscita).

    ⛔ Come processo e non come import, per due ragioni misurate: il modulo fa `os.chdir` e
    `sys.exit` a livello superiore, quindi importarlo cambierebbe la cartella di lavoro di chi
    lo importa e ne ucciderebbe il processo. Un attrezzo che misura non deve poter uccidere
    chi lo chiama.
    """
    esito = subprocess.run(  # nosec B603 - nessun shell, argomenti costanti, script nostro
        [sys.executable, AUDIT], cwd=RADICE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, timeout=timeout)
    return esito.returncode, esito.stdout.decode("utf-8", "replace")


# --------------------------------------------------------------------------------------
#  GIUDIZIO
# --------------------------------------------------------------------------------------
def giudica(codice, uscita):
    """(verde, denominatore, motivo). Il denominatore e' CONTATO, mai dichiarato."""
    confronti = len(RIGA_OK.findall(uscita)) + len(RIGA_KO.findall(uscita))
    discrepanze = len(RIGA_KO.findall(uscita))
    m = RIGA_VERDETTO.search(uscita)

    if confronti == 0:
        return False, 0, ("l'audit non ha confrontato NIENTE: zero righe di esito. "
                          "Un verde senza confronti e' cieco, non e' un verde")
    if m is None:
        return False, confronti, ("l'audit non ha stampato la riga VERDETTO: e' morto a meta' "
                                  "(%d confronti fatti). Un'uscita troncata somiglia a un esito"
                                  % confronti)
    dichiarate = int(m.group(1))
    if dichiarate != discrepanze:
        return False, confronti, ("l'audit dichiara %d discrepanze ma le righe [!!] sono %d: "
                                  "il suo verdetto e il suo dettaglio non concordano"
                                  % (dichiarate, discrepanze))
    if discrepanze:
        prime = [l.strip() for l in uscita.splitlines() if l.strip().startswith("[!!]")][:3]
        return False, confronti, ("%d cifre pubbliche NON coincidono col motore (su %d "
                                  "confrontate). Prime: %s" % (discrepanze, confronti, prime))
    if codice != 0:
        return False, confronti, ("zero discrepanze ma l'audit e' uscito con codice %d: "
                                  "esito e codice non concordano" % codice)
    return True, confronti, ""


# --------------------------------------------------------------------------------------
#  PRECONDIZIONI — l'attrezzo misura PRIMA se stesso
# --------------------------------------------------------------------------------------
def precondizioni():
    fuori = []
    fuori.append(("l'audit esiste sul disco", os.path.isfile(AUDIT), AUDIT))
    try:
        cond = [b for b in BLOCCHI if b["ordine"] == BLOCCO][0]["finito_quando"]
        c_e = len(cond) > INDICE_CASELLA
        fuori.append(("la casella esiste nel piano", c_e,
                      " ".join(str(cond[INDICE_CASELLA]).split())[:70] if c_e else "assente"))
    except Exception as e:
        fuori.append(("la casella esiste nel piano", False, "%s: %s" % (type(e).__name__, e)))
    fuori.append(("so con quale python eseguirla", bool(sys.executable), sys.executable or "-"))
    return fuori


def testo_della_casella():
    cond = [b for b in BLOCCHI if b["ordine"] == BLOCCO][0]["finito_quando"]
    return cond[INDICE_CASELLA]


# --------------------------------------------------------------------------------------
#  AUTOPROVA — nelle DUE direzioni, senza eseguire l'audit
# --------------------------------------------------------------------------------------
def _finta(ok=3, ko=0, verdetto=True, dichiarate=None):
    righe = ["  [OK] cosa numero %d" % i for i in range(ok)]
    righe += ["  [!!] cosa storta %d   atteso=1 trovato=2" % i for i in range(ko)]
    if verdetto:
        righe.append("VERDETTO: %d DISCREPANZE" % (ko if dichiarate is None else dichiarate))
    return "\n".join(righe) + "\n"


def autoprova():
    casi = [
        ("uscita sana (3 confronti, 0 discrepanze)", 0, _finta(3, 0), True, 3),
        ("una discrepanza vera", 1, _finta(3, 1), False, 4),
        ("uscita VUOTA (l'audit non ha guardato niente)", 0, "", False, 0),
        ("uscita troncata (nessuna riga VERDETTO)", 0, _finta(3, 0, verdetto=False), False, 3),
        ("verdetto che non concorda col dettaglio", 0, _finta(3, 1, dichiarate=0), False, 4),
        ("zero discrepanze ma codice d'uscita 1", 1, _finta(3, 0), False, 3),
    ]
    print("AUTOPROVA — l'esame sa gridare E sa tacere (D18 punto 2)")
    tutto = True
    for nome, codice, uscita, atteso_verde, atteso_den in casi:
        verde, den, motivo = giudica(codice, uscita)
        bene = (verde == atteso_verde) and (den == atteso_den)
        tutto = tutto and bene
        print("  %-46s -> %-5s den=%-3d %s" % (nome[:46], "VERDE" if verde else "rosso", den,
                                               "OK" if bene else "⛔ ATTESO DIVERSO"))
        if motivo and not verde:
            print("        perche': %s" % motivo[:100])
    print("")
    print("VERDETTO AUTOPROVA: %s" % ("l'esame distingue i sei casi"
                                      if tutto else "⛔ NON DISTINGUE: non fidarsi"))
    return 0 if tutto else 1


# --------------------------------------------------------------------------------------
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--autoprova" in argv:
        return autoprova()

    print("=" * 92)
    # ⛔ Il titolo mostra la casella LETTA DAL PIANO, non una copia a mano. La prima versione
    #    la ricopiava qui dentro «solo per stampare», e la guardia
    #    `test_LA_CASELLA_NON_E_RICOPIATA_A_MANO` l'ha bocciata al primo giro: aveva ragione
    #    lei. Una copia «solo per stampare» e' comunque una seconda copia dello stesso fatto,
    #    e il giorno che il piano cambia il titolo mente mentre la misura e' giusta -- cioe'
    #    la forma piu' subdola, perche' chi legge crede al titolo.
    try:
        print("L'ESAME DELLE CIFRE PUBBLICHE — «%s»"
              % " ".join(str(testo_della_casella()).split())[:74])
    except Exception:
        print("L'ESAME DELLE CIFRE PUBBLICHE — (casella non leggibile dal piano)")
    print("=" * 92)

    fuori = precondizioni()
    print("PRECONDIZIONI (l'attrezzo misura prima se stesso)")
    for voce, esito, dett in fuori:
        print("  %-40s %-3s %s" % (voce[:40], "OK" if esito else "NO", str(dett)[:44]))
    if not all(e for _, e, _ in fuori):
        print("")
        print("⛔ PRECONDIZIONI NON SODDISFATTE: mi fermo e NON scrivo nella scheda.")
        return 2

    if "--da-file" in argv:
        p = argv[argv.index("--da-file") + 1]
        uscita = io.open(p, encoding="utf-8", errors="replace").read()
        codice = 1 if RIGA_KO.search(uscita) else 0
        print("\nletto da file: %s" % p)
    else:
        print("\nESEGUO collaudi/audit_millimetrico.py ...")
        codice, uscita = esegui_audit()
        print("  codice d'uscita LETTO DIRETTO: %d" % codice)

    if "--con-guasto" in argv:
        uscita = uscita + "\n  [!!] guasto iniettato apposta   atteso=X trovato=Y\n"
        uscita = RIGA_VERDETTO.sub("VERDETTO: 1 DISCREPANZE", uscita)
        codice = 1
        print("  ⚠️  --con-guasto: uscita storta apposta. Deve gridare, e NON scrivere.")

    verde, denominatore, motivo = giudica(codice, uscita)

    print("")
    print("MISURA")
    print("  confronti eseguiti (il denominatore, CONTATO dall'uscita) : %d" % denominatore)
    print("  discrepanze                                              : %d"
          % len(RIGA_KO.findall(uscita)))
    print("  esito                                                    : %s"
          % ("VERDE" if verde else "ROSSO"))
    if motivo:
        print("  perche'                                                  : %s" % motivo)

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
