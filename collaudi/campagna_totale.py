"""CAMPAGNA TOTALE — ogni collaudo ripetuto 5 volte, esito riassunto.

Regola del fondatore: "ogni singola cosa testata almeno 4/5 volte, si salva solo quando
e' funzionale alla perfezione". Qui si esegue OGNI collaudo esistente 5 volte di fila e
si pretende che TUTTE le ripetizioni siano identiche e verdi. Una sola ripetizione rossa
= campagna fallita (e un collaudo che a volte passa e a volte no e' un collaudo che NON
garantisce niente: l'instabilita' e' essa stessa un difetto).
"""
import os
import subprocess
import sys
import time

QUI = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIPETIZIONI = 10

COLLAUDI_TUTTI = [
    ("caccia ai finti verdi", ["caccia_finti_verdi.py"]),
    ("plausibilita' del dato (i numeri hanno senso?)", ["plausibilita.py"]),
    ("occhio del fondatore (cosa legge una persona?)", ["occhio_del_fondatore.py"]),
    ("mutazione del motore (i test vedono i guasti veri?)", ["mutazione_prodotto.py"]),
    ("neuroni marca temporale (con rete vera)",
     ["collaudo_neuroni_marca.py", "--giri=1", "--con-rete"]),
    ("super collaudo: giudice OpenSSL (con rete vera)",
     ["super_collaudo_marca.py", "--con-rete"]),
    ("neuroni legale (consensi/identita/scaglioni/dossier)",
     ["collaudo_neuroni_legale.py"]),
    ("collaudo finale totale (7 metodi)", ["collaudo_finale_totale.py"]),
    ("rampa commissioni multi-metodo", ["collaudo_rampa_totale.py"]),
    ("neuroni recensione", ["collaudo_neuroni_recensione.py"]),
    ("flusso end-to-end recensione", ["e2e_recensione.py"]),
    ("stress recensioni (gara/corrotti/token falsi)",
     ["stress_test_recensioni.py", "--race-condition", "--payload-corrupt",
      "--invalid-token", "--rounds", "10"]),
    ("audit coerenza tariffe (tutti i file)", ["audit_coerenza_tariffe.py"]),
    ("audit millimetrico documenti vs motore", ["audit_millimetrico.py"]),
]


COLLAUDI = COLLAUDI_TUTTI


def esegui(argomenti):
    amb = dict(os.environ, PYTHONIOENCODING="utf-8")
    t0 = time.time()
    p = subprocess.run([sys.executable, os.path.join(QUI, argomenti[0])] + argomenti[1:],
                       cwd=REPO, env=amb, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, timeout=1800)
    return p.returncode, p.stdout.decode("utf-8", "replace"), time.time() - t0


if __name__ == "__main__":
    print("=" * 78)
    print("CAMPAGNA TOTALE — %d ripetizioni per ogni collaudo" % RIPETIZIONI)
    print("=" * 78)
    falliti = []
    t0 = time.time()
    for nome, argomenti in COLLAUDI:
        if not os.path.exists(os.path.join(QUI, argomenti[0])):
            print("\n%-52s ASSENTE (saltato)" % nome)
            continue
        esiti, durate = [], []
        print("\n%s" % nome)
        for r in range(1, RIPETIZIONI + 1):
            try:
                rc, uscita, dur = esegui(argomenti)
            except subprocess.TimeoutExpired:
                rc, uscita, dur = -9, "TIMEOUT", 1800.0
            esiti.append(rc)
            durate.append(dur)
            print("   ripetizione %d/%d  ->  %s  (%.1fs)"
                  % (r, RIPETIZIONI, "OK" if rc == 0 else "FALLITA (rc=%d)" % rc, dur))
            if rc != 0:
                falliti.append((nome, r, uscita[-2500:]))
        stabile = len(set(esiti)) == 1 and esiti[0] == 0
        print("   => %s  |  tempi %.1f-%.1fs"
              % ("STABILE E VERDE su %d/%d" % (RIPETIZIONI, RIPETIZIONI) if stabile
                 else "INSTABILE O ROSSO: %s" % esiti, min(durate), max(durate)))
    print("\n" + "=" * 78)
    print("durata totale: %.1f minuti" % ((time.time() - t0) / 60.0))
    if falliti:
        print("COLLAUDI FALLITI: %d" % len(falliti))
        for nome, r, coda in falliti[:6]:
            print("\n--- %s (ripetizione %d) ---\n%s" % (nome, r, coda))
        sys.exit(1)
    print("TUTTI I COLLAUDI: VERDI E STABILI su %d ripetizioni ciascuno" % RIPETIZIONI)
    sys.exit(0)