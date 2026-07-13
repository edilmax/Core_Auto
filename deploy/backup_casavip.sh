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

# TUTTI gli archivi durevoli col valore vero (non solo catalogo/inventario): account host,
# accettazioni firmate (valore legale), payout, crediti referral, hold, escrow, tasse, ecc.
# I DB assenti vengono saltati ([ -f ] più sotto).
for db in catalogo inventario registro_host accettazioni payout viral pendenti garanzia tassa_comunale domanda messaggi; do
  src="$DATA_DIR/$db.db"
  [ -f "$src" ] || continue
  dst="$BACKUP_DIR/$db-$TS.db"
  # snapshot consistente (NON una semplice copia: rispetta il WAL)
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$src" ".backup '$dst'"
  else
    python3 -c "import sqlite3,sys;s=sqlite3.connect(sys.argv[1]);d=sqlite3.connect(sys.argv[2]);s.backup(d);d.close();s.close()" "$src" "$dst" \
      || python -c "import sqlite3,sys;s=sqlite3.connect(sys.argv[1]);d=sqlite3.connect(sys.argv[2]);s.backup(d);d.close();s.close()" "$src" "$dst"
  fi
  gzip -f "$dst"
  # retention: tieni solo gli ultimi N
  ls -1t "$BACKUP_DIR/$db-"*.db.gz 2>/dev/null | tail -n +"$((RETENTION+1))" | xargs -r rm -f
  echo "backup ok: $dst.gz"
done
