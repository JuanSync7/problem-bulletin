#!/usr/bin/env bash
# REQ-914 — Database backup with retention policy
# Env vars: PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD, BACKUP_DIR
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/data/backups}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DAY_OF_WEEK="$(date +%u)"  # 1=Monday … 7=Sunday

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# --- Validate required vars ------------------------------------------------
for var in PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD; do
    if [[ -z "${!var:-}" ]]; then
        log "ERROR: Required environment variable $var is not set."
        exit 1
    fi
done

# --- Ensure backup directory exists ----------------------------------------
mkdir -p "${BACKUP_DIR}/daily" "${BACKUP_DIR}/weekly"

# --- Run pg_dump -----------------------------------------------------------
DAILY_FILE="${BACKUP_DIR}/daily/${PGDATABASE}_${TIMESTAMP}.sql.gz"
log "Starting backup of database '${PGDATABASE}' on ${PGHOST}:${PGPORT}"

if pg_dump -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" \
    --no-password --clean --if-exists | gzip > "$DAILY_FILE"; then
    log "Backup written to ${DAILY_FILE} ($(du -h "$DAILY_FILE" | cut -f1))"
else
    log "ERROR: pg_dump failed."
    rm -f "$DAILY_FILE"
    exit 1
fi

# --- Promote Sunday backup to weekly ---------------------------------------
if [[ "$DAY_OF_WEEK" -eq 7 ]]; then
    WEEKLY_FILE="${BACKUP_DIR}/weekly/${PGDATABASE}_${TIMESTAMP}.sql.gz"
    cp "$DAILY_FILE" "$WEEKLY_FILE"
    log "Weekly backup promoted: ${WEEKLY_FILE}"
fi

# --- Retention: keep 7 daily, 4 weekly ------------------------------------
log "Applying retention policy (7 daily, 4 weekly)…"

# Delete daily backups older than the most recent 7
ls -1t "${BACKUP_DIR}/daily/"*.sql.gz 2>/dev/null | tail -n +8 | while read -r old; do
    log "  Removing old daily backup: $(basename "$old")"
    rm -f "$old"
done

# Delete weekly backups older than the most recent 4
ls -1t "${BACKUP_DIR}/weekly/"*.sql.gz 2>/dev/null | tail -n +5 | while read -r old; do
    log "  Removing old weekly backup: $(basename "$old")"
    rm -f "$old"
done

log "Backup completed successfully."
exit 0
