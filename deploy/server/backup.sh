#!/usr/bin/env bash
# Daily backup: database dump + uploaded files, 14 days kept.
# cron:  15 3 * * * /opt/stravica-social/deploy/server/backup.sh >> /var/log/stravica-social-backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/../.."
COMPOSE=(docker compose -f docker-compose.yml -f deploy/server/docker-compose.server.yml)
BACKUPS=/var/backups/stravica-social
mkdir -p "$BACKUPS"; chmod 700 "$BACKUPS"
STAMP=$(date +%F_%H%M)
"${COMPOSE[@]}" exec -T db pg_dump -U stravica -Fc stravica > "$BACKUPS/db_$STAMP.dump"
"${COMPOSE[@]}" exec -T api tar -C /data -czf - storage > "$BACKUPS/storage_$STAMP.tar.gz"
find "$BACKUPS" -type f -mtime +14 -delete
echo "$(date -Is) backup ok: $STAMP"
