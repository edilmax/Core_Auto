"""QUALI MODULI LA PRODUZIONE ACCENDE DAVVERO — sola lettura.

A COSA SERVE, e cosa vede che nessun altro vede. L'appendice 23 («COSTRUITO ≠ COLLEGATO»)
ha una guardia che conta gli IMPORTATORI di ogni `fase*.py`: se sono zero, il modulo e'
orfano. Ma quella guardia **non puo' vedere un grappolo di moduli morti che si importano a
vicenda**: ognuno ha i suoi importatori, quindi passano tutti.

Misurato il 2026-08-09: **88 moduli raggiungibili su 151, 63 NO** — il 42%. Fra i morti
c'era `fase35_pagamenti` (importato solo da `fase36_booking_api` e `fase41_admin_panel`,
morti anche loro) e `fase15_idempotency`. Dei 15 moduli in cima alla tabella «dove attaccare»
del censimento di mutazione, **8 erano morti**: quella tabella e' meta' rumore finche' non
dichiara la raggiungibilita'.

BIAS DICHIARATO (D18 punto 3), ed e' voluto: **GENEROSO**. Conta un import ovunque compaia
nel file — anche dentro una funzione (import pigro) e anche dentro un `try/except`. Quindi
puo' dichiarare VIVO qualcosa che di fatto non parte mai; ma se dice **MORTO, e' morto
davvero**. E' il verso giusto in cui sbagliare: meglio non accorgersi di un cadavere che
seppellire un vivo.

⛔ COSA NON FA: non esegue niente, non risolve gli import dinamici costruiti a stringa
(`importlib.import_module(nome)` con `nome` calcolato), non guarda i file statici. Un modulo
raggiunto SOLO cosi' risulterebbe morto a torto: prima di dichiarare morto qualcosa si
guarda anche con `grep`.

USO:   python collaudi/raggiungibilita.py
"""
import os
import re
import sys

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARTENZA = "main_casavip.py"

# 'import faseNN_x' oppure 'from faseNN_x import ...'
RIF = re.compile(r"\b(?:from|import)\s+(fase\d+[A-Za-z0-9_]*)")


def moduli_citati(percorso):
    try:
        with open(percorso, "r", encoding="utf-8", errors="replace") as f:
            testo = f.read()
    except OSError:
        return set()
    return set(RIF.findall(testo))


def cammina(radice=RADICE, partenza=PARTENZA):
    """(vivi, morti, tutti): i moduli raggiungibili dal punto di accensione, e gli altri."""
    tutti = {n[:-3] for n in os.listdir(radice)
             if re.fullmatch(r"fase\d+[A-Za-z0-9_]*\.py", n)}
    da_visitare = list(moduli_citati(os.path.join(radice, partenza)) & tutti)
    vivi = set(da_visitare)
    while da_visitare:
        m = da_visitare.pop()
        for nuovo in moduli_citati(os.path.join(radice, m + ".py")) & tutti:
            if nuovo not in vivi:
                vivi.add(nuovo)
                da_visitare.append(nuovo)
    return vivi, tutti - vivi, tutti


def main():
    vivi, morti, tutti = cammina()
    print("=" * 78)
    print("RAGGIUNGIBILITA' DAL PUNTO DI ACCENSIONE DELLA PRODUZIONE")
    print("  partenza: %s -> import transitivi, bias GENEROSO (se dice MORTO, e' morto)"
          % PARTENZA)
    print("=" * 78)
    print("  moduli fase*.py sul disco ............ %d" % len(tutti))
    print("  RAGGIUNGIBILI dalla produzione ....... %d" % len(vivi))
    print("  NON raggiungibili (codice morto) ..... %d" % len(morti))
    print()
    print("  I NON RAGGIUNGIBILI, in ordine:")
    for m in sorted(morti):
        print("     ", m)
    print()
    print("  ⚠️  Un modulo morto NON e' un difetto: puo' essere roba costruita e mai")
    print("      collegata. Diventa un problema quando qualcuno lo collauda credendo di")
    print("      collaudare il prodotto, o quando DOVEVA essere acceso (es. adempimenti")
    print("      di legge). Si guarda l'elenco, non si cancella niente a scatola chiusa.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
