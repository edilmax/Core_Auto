#!/bin/sh
# Prepara i due pacchetti PER LA CHIAVETTA, presi DAL SERVER VIVO (non dal computer):
# e' l'unica copia che e' davvero girata da qualche parte.
#
# Uso, sul VPS:   sh /var/www/bookinvip/deploy/impacchetta.sh
set -e

# Si legge PRIMA del `cd`: subito dopo, `$0` non porterebbe piu' da nessuna parte.
QUI=$(cd "$(dirname "$0")" && pwd)

cd /var/www/bookinvip
rm -f /root/clone_progetto.tgz /root/clone_dati.tgz

# CODICE + CONFIGURAZIONE (comprese le chiavi vere in .env.casavip: senza, la copia non
# rimette online niente). Fuori cio' che si rigenera e pesa: ambiente Python, compilati, log.
# FUORI ANCHE I VIDEO (283 MB): stanno a parte in clone_video.tgz per scelta -- non servono
# a rimettere online il sito, ma rifarli costa ore di rendering, quindi si conservano.
tar czf /root/clone_progetto.tgz \
    --exclude=./venv --exclude=./.git --exclude='*/__pycache__' --exclude=./__pycache__ \
    --exclude='*.pyc' --exclude=./logs --exclude='*.log' --exclude=./.mypy_cache \
    --exclude=./video_pubblici --exclude=./log_linker.txt .

# DATI: dal VOLUME, dentro il container. Sull'host ce ne sono 18 vecchi: prenderli da li'
# darebbe un "backup ok" con sette archivi mancanti.
#
# ⛔ E SI COPIANO CON L'API DI BACKUP DI SQLITE, MAI CON UN `tar *.db`.
#    Fino al 2026-08-07 questa parte era una riga sola:
#        docker exec casavip_app sh -c 'cd /data && tar czf /tmp/d.tgz *.db'
#    che ha esattamente il difetto di `cp`: prende il file `.db` e lascia fuori il `-wal`
#    accanto, dove SQLite tiene cio' che e' appena stato scritto. Quel giorno i file `-wal`
#    erano 0, quindi il tar prendeva tutto -- PER FORTUNA, NON PER COSTRUZIONE. Con traffico
#    vero la prenotazione in corso nell'istante del tar sparisce dal backup senza un errore,
#    e lo si scopre il giorno del ripristino. Il perche' per esteso sta in copia_db.py.
#
#    Lo strumento entra dallo STANDARD INPUT e non come file: cosi' non resta niente dentro
#    il container, e soprattutto non resta un file di proprieta' di root che l'applicazione
#    (utente `app`, uid 10001) non potrebbe piu' cancellare da `/tmp`, che ha lo sticky bit.
docker exec -i casavip_app python3 - < "$QUI/copia_db.py"
docker exec casavip_app sh -c 'cd /tmp/bk_chiavetta && tar czf /tmp/d.tgz *.db'
docker cp casavip_app:/tmp/d.tgz /root/clone_dati.tgz
docker exec casavip_app rm -rf /tmp/d.tgz /tmp/bk_chiavetta

echo "COMMIT: $(git rev-parse --short HEAD)"
echo "clone_progetto.tgz: $(stat -c%s /root/clone_progetto.tgz) byte, $(tar tzf /root/clone_progetto.tgz | wc -l) voci"
echo "  moduli fase: $(tar tzf /root/clone_progetto.tgz | grep -cE '^\./fase[0-9]+.*\.py$')"
echo "  file di test: $(tar tzf /root/clone_progetto.tgz | grep -cE '^\./test_.*\.py$')"
echo "  .env.casavip dentro: $(tar tzf /root/clone_progetto.tgz | grep -c '^\./\.env\.casavip$')"
echo "clone_dati.tgz: $(stat -c%s /root/clone_dati.tgz) byte, $(tar tzf /root/clone_dati.tgz | grep -c '\.db$') database"
