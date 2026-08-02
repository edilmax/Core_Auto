# -*- coding: utf-8 -*-
"""⛔ NON SI SALVA MENTRE UN GIRO DI MUTAZIONE E' APERTO.

PERCHE' ESISTE, e non e' teoria: il 2026-08-02 tre cicli di mutazione sono stati interrotti
e OGNI VOLTA hanno lasciato un guasto dentro un file di PRODUZIONE. L'ultimo faceva
rispondere alla macchina «questa penale era gia' stata stornata» anche quando non era vero.

Il giudice rompe il codice di proposito, prova, e RIPARA. Se viene ucciso fra il «rompi» e
il «ripara», il file resta rotto. La rete di recupero ha la copia buona -- ma ripristina al
giro SUCCESSIVO. Fra l'interruzione e il giro dopo c'e' una finestra in cui un `git add -A`
porta il guasto nel salvataggio, poi su GitHub, poi sul server, **con tutti i controlli
verdi**: quei punti sono scoperti per definizione, e' il motivo per cui li stiamo mutando.

Oggi ci ha protetto il fatto che me ne sono ricordato tre volte su tre. E' esattamente cio'
che la DIRETTIVA D18 rifiuta: «uno strumento che misura deve avere un controllo MECCANICO
che gli impedisca di barare» -- e un controllo che dipende da qualcuno che si ricordi non e'
un controllo. La memoria umana non e' una strategia.

COME SI USA
    python collaudi/guardia_commit.py        # 0 = si puo' salvare, 1 = fermo
Lo chiama da solo il gancio `deploy/hooks/pre-commit` (vedi `deploy/installa_hook.sh`).
"""
import os
import sys
import tempfile

# ⛔ LA CONSOLE DI WINDOWS (cp1252) NON REGGE I SIMBOLI. Senza questa riga il blocco
# ESPLODE invece di spiegarsi: git legge comunque l'uscita diversa da zero e ferma il
# commit, quindi SEMBRA funzionare -- ma chi lo usa vede un traceback al posto delle
# istruzioni, e un blocco che non dice come si sblocca e' un blocco che verra' aggirato.
# Provato il 2026-08-02: e' successo davvero, al primo tentativo.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# La stessa cartella che il giudice apre prima di rompere un file (vedi `_TRACCIA` in
# `collaudi/mutazione_prodotto.py`). Se esiste, un giro e' aperto O e' stato interrotto.
TRACCIA = os.path.join(tempfile.gettempdir(), "bookinvip_mutazione_in_corso")


def mutazione_in_corso(traccia=None):
    """(aperta, quale_file). `aperta` e' True se un giro di mutazione non e' stato chiuso."""
    t = traccia or TRACCIA
    if not os.path.isdir(t):
        return False, ""
    quale = ""
    try:
        with open(os.path.join(t, "quale.txt"), encoding="utf-8", errors="replace") as f:
            quale = f.read().strip()
    except Exception:
        pass
    return True, quale


def main(argv=None):
    aperta, quale = mutazione_in_corso()
    if not aperta:
        return 0
    print("=" * 78)
    print("⛔ SALVATAGGIO BLOCCATO — un giro di mutazione risulta APERTO")
    print("=" * 78)
    print("Il giudice della mutazione rompe un file di produzione, prova, e lo ripara.")
    print("Questa traccia dice che un giro NON e' stato chiuso: il file qui sotto potrebbe")
    print("contenere un guasto messo di proposito, e finirebbe nel salvataggio.")
    print("")
    print("  file coinvolto: %s" % (quale or "(non indicato)"))
    print("  traccia:        %s" % TRACCIA)
    print("")
    print("COSA FARE, in ordine:")
    print("  1. guarda cosa e' cambiato:   git diff HEAD -- <il file qui sopra>")
    print("  2. rimetti a posto:           git checkout HEAD -- <il file qui sopra>")
    print("     ⛔ `git checkout -- <file>` NON BASTA: quello ripristina dall'area di")
    print("        salvataggio, e se il guasto e' gia' stato messo li' (un `git add -A`")
    print("        lo fa) non ripara niente. Ci vuole `HEAD`. Scoperto il 2026-08-02")
    print("        seguendo queste stesse istruzioni, che prima erano sbagliate.")
    print("  3. controlla che sia tornato identico:")
    print("        git diff HEAD --stat -- <il file qui sopra>     (deve essere vuoto)")
    print("  4. togli la traccia:          rimuovi la cartella indicata")
    print("     (oppure fai ripartire il giudice: ripristina e lo dice da solo)")
    print("")
    print("Se sei sicuro che il file sia a posto e vuoi salvare lo stesso, la traccia va")
    print("tolta A MANO: e' voluto. Un blocco che si aggira con un'opzione non blocca.")
    print("=" * 78)
    return 1


if __name__ == "__main__":
    sys.exit(main())
