#!/usr/bin/env bash
# REQ-922 — Generate systemd unit files from podman containers
set -euo pipefail

UNIT_DIR="/etc/systemd/system"
PROJECT_NAME="${PROJECT_NAME:-aion-bulletin}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# --- Pre-flight checks -----------------------------------------------------
if ! command -v podman &>/dev/null; then
    log "ERROR: podman is not installed or not in PATH."
    exit 1
fi

if [[ $EUID -ne 0 ]]; then
    log "ERROR: This script must be run as root (writes to ${UNIT_DIR})."
    exit 1
fi

# --- Discover running containers for this project --------------------------
CONTAINERS=$(podman ps --format '{{.Names}}' | grep "^${PROJECT_NAME}" || true)

if [[ -z "$CONTAINERS" ]]; then
    log "ERROR: No running containers found matching project '${PROJECT_NAME}'."
    log "       Start the stack with 'podman-compose up -d' first."
    exit 1
fi

# --- Generate unit files ----------------------------------------------------
log "Generating systemd unit files for project '${PROJECT_NAME}'…"

for CONTAINER in $CONTAINERS; do
    UNIT_FILE="${UNIT_DIR}/container-${CONTAINER}.service"
    log "  Generating unit for container: ${CONTAINER}"

    podman generate systemd --name "$CONTAINER" --restart-policy=always --new \
        > "$UNIT_FILE"

    # Ensure Restart=always is present (belt-and-suspenders)
    if ! grep -q '^Restart=always' "$UNIT_FILE"; then
        sed -i '/^\[Service\]/a Restart=always' "$UNIT_FILE"
    fi

    log "  Written: ${UNIT_FILE}"
done

# --- Reload systemd --------------------------------------------------------
systemctl daemon-reload
log "systemd daemon reloaded."

# --- Print instructions ----------------------------------------------------
echo ""
echo "======================================================================"
echo "  Systemd units generated. To enable and start on boot:"
echo ""
for CONTAINER in $CONTAINERS; do
    echo "    systemctl enable --now container-${CONTAINER}.service"
done
echo ""
echo "  Useful commands:"
echo "    systemctl status container-${PROJECT_NAME}-*"
echo "    journalctl -u container-${PROJECT_NAME}-api-1 -f"
echo "======================================================================"

exit 0
