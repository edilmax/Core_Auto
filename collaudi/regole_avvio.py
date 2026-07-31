# -*- coding: utf-8 -*-
"""LE REGOLE SI LEGGONO SEMPRE, PRIMA DI FARE QUALUNQUE COSA.

Lo esegue un hook `SessionStart` (vedi `.claude/settings.json`): la sua uscita entra nel
contesto della sessione PRIMA di ogni altra cosa, quindi non dipende da nessuno che si
ricordi di leggere.

PERCHE' ESISTE. Il 2026-07-31 ho violato la REGOLA FERREA 15 -- una regola scritta da me
stesso -- perche' stava nell'appendice del registro invece che nel file che si ricarica a
ogni sessione. La ricerca lo aveva perfino previsto: «LA COMPATTAZIONE E' AMNESIA: dopo un
riassunto sopravvive solo CLAUDE.md, tutto cio' che sta altrove viene perso». Un regolamento
di testo dipende da un lettore che si ricordi di leggerlo; questo strumento toglie di mezzo
quella dipendenza.

FA DUE COSE, E LA SECONDA CONTA PIU' DELLA PRIMA:
  1. stampa la MAPPA degli obblighi -- dove stanno e quando vanno letti;
  2. CONTA le regole nei file e le confronta con i numeri dichiarati nel regolamento.
     Se divergono, GRIDA. Un regolamento che mente sul proprio conteggio e' esattamente
     una guardia che non guarda -- ed e' cosi' che oggi ho perso una regola.

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


def _leggi(percorso):
    with io.open(percorso, encoding="utf-8", errors="replace") as f:
        return f.read()


def conta_regole():
    """I numeri VERI, contati dai file. Mai a memoria: e' la REGOLA ZERO n.4."""
    c = _leggi(CLAUDE)
    zero = c.split("# ⚙️ REGOLA FERREA")[0]
    ferrea = c.split("# ⚙️ REGOLA FERREA")[-1].split("# 🔟 REGOLA DEI 10 COLLAUDI")[0]
    collaudi = c.split("# 🔟 REGOLA DEI 10 COLLAUDI")[-1].split("# DIRETTIVA OPERATIVA")[0]
    direttiva = c.split("# DIRETTIVA OPERATIVA")[-1]
    appendice = _leggi(REGISTRO).split("# 📚 APPENDICE")[-1]
    return {
        "regola_zero": len(re.findall(r"^\*\*\d+\.", zero, re.M)),
        "regola_ferrea": len(re.findall(r"^\*\*\d+\.", ferrea, re.M)),
        "modi_di_rompersi": len(re.findall(r"^\| \d+ \|", collaudi.split("I 10 COLLAUDI")[0], re.M)),
        "collaudi": len(re.findall(r"^\| \d+ \|", collaudi.split("I 10 COLLAUDI")[-1], re.M)),
        "direttiva_finale": len(re.findall(r"^\*\*\d+\.", direttiva, re.M)),
        "appendice_totale": len(re.findall(r"^\*\*\d+\. ", appendice, re.M)),
    }


def dichiarati():
    """Cosa dice il regolamento di se stesso, per poterlo smentire."""
    c = _leggi(CLAUDE)
    m = re.search(r"GLI OBBLIGHI SONO \*\*(\d+)\*\*", c)
    f = re.search(r"REGOLA FERREA \(qui sotto\) \| \*\*(\d+)\*\*", c)
    return (int(m.group(1)) if m else None, int(f.group(1)) if f else None)


def main():
    n = conta_regole()
    # l'appendice contiene TUTTE le regole della ricerca; quelle promosse in CLAUDE.md
    # sono le "ferree", quindi le esclusive dell'appendice sono la differenza.
    solo_appendice = max(0, n["appendice_totale"] - n["regola_ferrea"])
    totale = (n["regola_zero"] + n["regola_ferrea"] + n["modi_di_rompersi"]
              + n["collaudi"] + n["direttiva_finale"] + solo_appendice)
    tot_dich, ferrea_dich = dichiarati()

    print("=" * 78)
    print("⛔ REGOLE DEL PROGETTO — si leggono PRIMA di fare qualunque cosa")
    print("=" * 78)
    print("  CLAUDE.md   REGOLA ZERO ............. %2d   (fonti di verita', niente .md nuovi,"
          " numeri verificati nel codice)" % n["regola_zero"])
    print("  CLAUDE.md   REGOLA FERREA .......... %2d   (chirurgia · zero verdi finti · "
          "documenti allineati · mani in tasca ·" % n["regola_ferrea"])
    print("                                            pulizia dopo la prova · suite INTERA "
          "anche per un .md · esito letto diretto ·")
    print("                                            CI giudice · osservabile forte · "
          "allarmi nelle due direzioni · difetto nel")
    print("                                            chiamante · simulare prima di "
          "distruggere · contenuto non date · chiavi mai")
    print("                                            stampate · SCOPO DICHIARATO PRIMA E "
          "VERIFICATO DOPO)")
    print("  CLAUDE.md   modi di rompersi ....... %2d   (dati effimeri, cablaggio mancante, "
          "ambiente diverso, ...)" % n["modi_di_rompersi"])
    print("  CLAUDE.md   collaudi obbligatori ... %2d   (in ordine, mutazione per ULTIMA)"
          % n["collaudi"])
    print("  CLAUDE.md   direttiva finale ....... %2d" % n["direttiva_finale"])
    print("  REGISTRO    appendice, SOLO li' .... %2d   (con prova, fonte e come si verifica)"
          % solo_appendice)
    print("  " + "-" * 74)
    print("  TOTALE OBBLIGHI: %d  —  valgono TUTTI. Non chiamare «le regole» un sottoinsieme:"
          % totale)
    print("  e' cosi' che si perdono. (Successo il 2026-07-31: dissi «le 14» e violai la 15.)")
    print()
    print("  L'APPENDICE VA LETTA **PRIMA** DI INIZIARE, QUANDO:")
    print("   · collaudi o tocchi la MUTAZIONE          · modifichi CODICE ESISTENTE")
    print("   · la sessione e' lunga o RIASSUNTA        · stai per dire «FATTO»")
    print()

    guasti = []
    if tot_dich is not None and tot_dich != totale:
        guasti.append("il regolamento dichiara %d obblighi ma nei file ce ne sono %d"
                      % (tot_dich, totale))
    if ferrea_dich is not None and ferrea_dich != n["regola_ferrea"]:
        guasti.append("la tabella dichiara %d regole ferree ma ne sono numerate %d"
                      % (ferrea_dich, n["regola_ferrea"]))
    numeri = re.findall(r"^\*\*(\d+)\.",
                        _leggi(CLAUDE).split("# ⚙️ REGOLA FERREA")[-1]
                        .split("# 🔟 REGOLA DEI 10 COLLAUDI")[0], re.M)
    if [int(x) for x in numeri] != list(range(1, len(numeri) + 1)):
        guasti.append("le regole ferree non sono numerate 1..%d senza salti: %s"
                      % (len(numeri), numeri))

    if guasti:
        print("  🔴 IL REGOLAMENTO NON DICE IL VERO SU SE STESSO:")
        for g in guasti:
            print("     · %s" % g)
        print("     Va corretto PRIMA di lavorare: un regolamento che sbaglia il proprio")
        print("     conteggio e' una guardia che non guarda.")
    else:
        print("  ✅ Il regolamento dice il vero su se stesso (conteggi verificati adesso).")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    # ⛔ UN HOOK NON PUO' MAI ROMPERE LA SESSIONE. Se questo strumento esplode (file
    # spostato, permessi, console esotica) deve DIRLO e uscire 0, non impedire di lavorare.
    # Il silenzio no: un promemoria che sparisce senza avvisare e' la stessa forma di
    # guasto che stiamo combattendo -- lo strumento che tace mentre e' rotto.
    try:
        sys.exit(main())
    except Exception as _e:                                    # pragma: no cover
        print("REGOLE NON MOSTRATE (%s: %s) -- leggi CLAUDE.md a mano PRIMA di lavorare."
              % (type(_e).__name__, _e))
        sys.exit(0)
