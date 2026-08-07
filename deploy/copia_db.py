"""Copia i 25 database con l'API DI BACKUP di sqlite3, non con tar/cp.

PERCHE'. `tar czf ... *.db` (e `cp`) copiano il file cosi' com'e' sul disco. Se in
quell'istante c'e' una transazione aperta, le pagine nuove stanno nel file `-wal`
accanto, e quel file non viene preso: il backup risulta "riuscito" e ha perso
l'ultima prenotazione, in silenzio. L'API di backup invece legge ATTRAVERSO il
motore sqlite, quindi vede anche cio' che sta nel WAL, e produce uno snapshot
coerente anche mentre qualcuno scrive.

Fa anche il `PRAGMA integrity_check` su ogni copia: un archivio che non si apre
non e' un archivio, e lo si scopre adesso e non il giorno del guasto.

DOVE GIRA. Sul VPS, dentro il container: `impacchetta.sh` lo ci copia dentro con
`docker cp` e lo lancia con `python3`. I valori predefiniti qui sotto sono quelli
del server, quindi laggiu' non cambia niente.

PERCHE' I DUE PERCORSI SI POSSONO SOVRASCRIVERE. Non e' una comodita': serve alla
guardia `TestGliStrumentiDiSalvataggioNONVIVONOSOLOSULSERVER` (test_backup_completo.py)
per ESEGUIRE questo strumento su un database di prova col WAL sporco, invece di
limitarsi a cercarne il testo con un `grep`. Una guardia che legge il codice non si
accorgerebbe mai che la copia ha perso delle righe -- e quello e' l'unico difetto
che conta qui.
"""
import glob
import os
import sqlite3
import sys

SORGENTE = os.environ.get("COPIA_DB_SORGENTE", "/data")
DESTINAZIONE = os.environ.get("COPIA_DB_DESTINAZIONE", "/tmp/bk_chiavetta")

os.makedirs(DESTINAZIONE, exist_ok=True)
for vecchio in glob.glob(os.path.join(DESTINAZIONE, "*")):
    os.remove(vecchio)

archivi = sorted(glob.glob(os.path.join(SORGENTE, "*.db")))
if not archivi:
    print("NESSUN DATABASE TROVATO IN %s -- mi fermo" % SORGENTE)
    sys.exit(1)

rotti = []
print("%-26s %12s %12s  %s" % ("database", "byte_orig", "byte_copia", "integrita"))
for src in archivi:
    nome = os.path.basename(src)
    dst = os.path.join(DESTINAZIONE, nome)
    # sola lettura sull'originale: non si tocca cio' che sta servendo il sito
    orig = sqlite3.connect("file:%s?mode=ro" % src, uri=True)
    copia = sqlite3.connect(dst)
    try:
        orig.backup(copia)          # <- l'API vera: vede anche il WAL
    finally:
        copia.close()
        orig.close()
    # la copia si APRE e si controlla, non si guarda solo la data
    c = sqlite3.connect(dst)
    try:
        esito = c.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        c.close()
    if esito != "ok":
        rotti.append(nome)
    print("%-26s %12d %12d  %s" % (nome, os.path.getsize(src), os.path.getsize(dst), esito))

print("---")
print("database copiati: %d" % len(archivi))
print("integrita' NON ok: %d %s" % (len(rotti), rotti if rotti else ""))
sys.exit(1 if rotti else 0)
