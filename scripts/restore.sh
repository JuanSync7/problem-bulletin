#!/usr/bin/env bash
# REQ-914 — Database restore from backup file
# Usage: ./restore.sh <path-to-backup.sql.gz>
set -euo pipefail

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# --- Validate arguments ----------------------------------------------------
if [[ $# -lt 1 ]]; then
    log "ERROR: Usage: $0 <backup_file.sql.gz>"
    exit 1
fi

BACKUP_FILE="$1"

if [[ ! -f "$BACKUP_FILE" ]]; then
    log "ERROR: Backup file not found: ${BACKUP_FILE}"
    exit 1
fi

# --- Validate required env vars --------------------------------------------
for var in PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD; do
    if [[ -z "${!var:-}" ]]; then
        log "ERROR: Required environment variable $var is not set."
        exit 1
    fi
done

# --- Restore ---------------------------------------------------------------
log "Restoring database '${PGDATABASE}' from ${BACKUP_FILE}"

if gunzip -c "$BACKUP_FILE" | psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" --no-password -q; then
    log "SQL restore completed."
else
    log "ERROR: Restore failed."
    exit 1
fi

# --- Verify by checking table count ----------------------------------------
TABLE_COUNT=$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" \
    --no-password -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';")

if [[ "$TABLE_COUNT" -gt 0 ]]; then
    log "Verification passed: ${TABLE_COUNT} table(s) found in public schema."
else
    log "ERROR: Verification failed — no tables found after restore."
    exit 1
fi

log "Restore completed successfully."
exit 0
