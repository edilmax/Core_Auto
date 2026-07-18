#!/usr/bin/env sh
# Casa VIP - backup ATOMICO dei DB SQLite + retention. Gira sul VPS (cron) o in un
# container sidecar. Usa l'Online Backup di SQLite (snapshot consistente anche con WAL).
# Uso:  BACKUP_DIR=/data/backup DATA_DIR=/data sh deploy/backup_casavip.sh
set -eu

DATA_DIR="${DATA_DIR:-/data}"
BACKUP_DIR="${BACKUP_DIR:-$DATA_DIR/backup}"
RETENTION="${RETENTION:-14}"          # quanti backup tenere per ogni DB
TS="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"

# SCOPERTA AUTOMATICA: ogni *.db in DATA_DIR viene salvato. Prima la lista era FISSA
# e scritta a mano -> un DB nuovo (es. finanza.db del giornale contabile) NON veniva
# salvato finché qualcuno non si ricordava di aggiungerlo. Ora nessun archivio può
# essere dimenticato: il backup segue i dati, non una lista. (backup/ e i -wal/-shm
# sono esclusi: gli snapshot .backup li consolidano già.)
for src in "$DATA_DIR"/*.db; do
  [ -f "$src" ] || continue                     # nessun .db -> il glob resta letterale
  db="$(basename "$src" .db)"
  dst="$BACKUP_DIR/$db-$TS.db"
  # snapshot consistente (NON una semplice copia: rispetta il WAL)
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$src" ".backup '$dst'"
  else
    python3 -c "import sqlite3,sys;s=sqlite3.connect(sys.argv[1]);d=sqlite3.connect(sys.argv[2]);s.backup(d);d.close();s.close()" "$src" "$dst" \
      || python -c "import sqlite3,sys;s=sqlite3.connect(sys.argv[1]);d=sqlite3.connect(sys.argv[2]);s.backup(d);d.close();s.close()" "$src" "$dst"
  fi
  gzip -f "$dst"
  # CHECKSUM del backup, accanto all'archivio: il PULL offsite lo riverifica (catena
  # di integrità end-to-end origine->copia). sha256 dell'archivio gzippato.
  ( cd "$BACKUP_DIR" && { sha256sum "$db-$TS.db.gz" 2>/dev/null \
      || shasum -a 256 "$db-$TS.db.gz" 2>/dev/null; } > "$db-$TS.db.gz.sha256" || true )
  # retention: tieni solo gli ultimi N (archivio + suo checksum)
  ls -1t "$BACKUP_DIR/$db-"*.db.gz 2>/dev/null | tail -n +"$((RETENTION+1))" | while read -r vecchio; do
    rm -f "$vecchio" "$vecchio.sha256"
  done
  echo "backup ok: $dst.gz"
done

# MANIFESTO del giro: elenco archivi + checksum, per un colpo d'occhio del restore.
{
  echo "# backup manifest $TS"
  ls -1 "$BACKUP_DIR"/*-"$TS".db.gz 2>/dev/null | while read -r f; do
    echo "$(basename "$f")"
  done
} > "$BACKUP_DIR/MANIFEST-$TS.txt" 2>/dev/null || true
ls -1t "$BACKUP_DIR"/MANIFEST-*.txt 2>/dev/null | tail -n +"$((RETENTION+1))" | xargs -r rm -f
