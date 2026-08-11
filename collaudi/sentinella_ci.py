"""Sorveglia i job della CI sulla richiesta di unione e stampa l'esito quando hanno FINITO.

Copre TUTTI gli esiti terminali, non solo il verde: un sorvegliante che aspetta solo
`success` resta muto davanti a un fallimento, e il silenzio sembra identico a "sta ancora
girando".

LA CHIAVE NON SI STAMPA MAI (regola ferrea 14): si legge dal gestore credenziali di git,
si usa, e non compare in nessuna riga di uscita.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

REPO = "edilmax/Core_Auto"
# ⛔ RICAVATA, NON CABLATA. Qui c'era `C:\Users\MaxDanno\Desktop\Core_Auto`: un percorso
# che vale su un computer solo. Questo file sta in `collaudi/`, quindi il progetto e' la
# cartella padre.
CARTELLA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TERMINALI = ("completed",)


def gettone():
    p = subprocess.run(["git", "credential", "fill"], cwd=CARTELLA,
                       input="protocol=https\nhost=github.com\n\n",
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    for riga in p.stdout.splitlines():
        if riga.startswith("password="):
            return riga[len("password="):]
    return ""


def leggi(tok, sha):
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/commits/%s/check-runs?per_page=100" % (REPO, sha),
        headers={"Authorization": "Bearer " + tok, "User-Agent": "bookinvip",
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    tok = gettone()
    if not tok:
        print("NESSUNA CREDENZIALE: non posso interrogare la CI")
        return 1
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=CARTELLA,
                         stdout=subprocess.PIPE, text=True).stdout.strip()
    dati = {}
    for _ in range(180):                       # fino a 90 minuti
        try:
            dati = leggi(tok, sha)
        except Exception as e:
            print("(interrogazione fallita, riprovo: %s)" % type(e).__name__)
            time.sleep(30)
            continue
        job = dati.get("check_runs", [])
        aperti = [j for j in job if j.get("status") not in TERMINALI]
        if job and not aperti:
            break
        time.sleep(30)

    job = sorted(dati.get("check_runs", []), key=lambda j: j.get("name", ""))
    print("=== ESITO CI SU %s (commit %s) ===" % (REPO, sha[:7]))
    rossi = []
    for j in job:
        esito = j.get("conclusion") or "-"
        print("  %-52s %-11s %s" % (j.get("name", "?")[:52], j.get("status", "?"), esito))
        if esito not in ("success", "skipped", "neutral"):
            rossi.append("%s -> %s" % (j.get("name"), esito))
    print("")
    print("job totali: %d  ·  NON riusciti: %d" % (len(job), len(rossi)))
    for r in rossi:
        print("   ROSSO: " + r)
    print("VERDETTO CI: " + ("VERDE" if (job and not rossi) else "ROSSO O INCOMPLETO"))
    return 0 if (job and not rossi) else 1


if __name__ == "__main__":
    sys.exit(main())
