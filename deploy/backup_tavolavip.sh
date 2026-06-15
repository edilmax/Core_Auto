#!/usr/bin/env bash
# Backup automatico del DB Tavola VIP: snapshot CONSISTENTE (Online Backup API) +
# retention SIZE-CAP (lo spazio totale non supera mai BACKUP_MAX_BYTES). Idempotente,
# non distruttivo. Pensato per il CRON (vedi DEPLOY.md).
#
# Uso (host):      BACKUP_DIR=/var/backup ./deploy/backup_tavolavip.sh
# Uso (container): docker compose -f docker-compose.tavolavip.yml exec -T booking \
#                    env BACKUP_DIR=/data/backup bash deploy/backup_tavolavip.sh
set -euo pipefail

export DB_PATH="${DB_PATH:-/data/tavolavip.db}"
export BACKUP_DIR="${BACKUP_DIR:-/data/backup}"
export BACKUP_MAX_BYTES="${BACKUP_MAX_BYTES:-524288000}"   # 500 MB di tetto totale

cd "$(dirname "$0")/.."
python -m fase38_backup
