#!/bin/bash
# Post-update gateway restart script
# Called after OpenClaw auto-update to reload new code
# Usage: ./post_update_restart.sh [old_version]

set -euo pipefail

LOG_DIR="$HOME/.openclaw/workspace/logs"
LOG_FILE="$LOG_DIR/auto-update.log"
mkdir -p "$LOG_DIR"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# Ensure systemctl --user works in cron/non-interactive context
export XDG_RUNTIME_DIR="/run/user/$(id -u)"

OLD_VERSION="${1:-unknown}"
NEW_VERSION=$(openclaw --version 2>/dev/null || echo "unknown")

if [ "$OLD_VERSION" = "$NEW_VERSION" ]; then
  log "No version change ($OLD_VERSION), skipping gateway restart"
  exit 0
fi

log "Version changed: $OLD_VERSION → $NEW_VERSION"

# Restart primary gateway
log "Restarting openclaw-gateway.service..."
if systemctl --user restart openclaw-gateway.service; then
  log "✅ openclaw-gateway.service restarted"
else
  log "❌ Failed to restart openclaw-gateway.service"
fi

sleep 5

# Restart secondary gateway
log "Restarting openclaw-gateway2.service..."
if systemctl --user restart openclaw-gateway2.service; then
  log "✅ openclaw-gateway2.service restarted"
else
  log "❌ Failed to restart openclaw-gateway2.service"
fi

sleep 3

# Verify both are running
for svc in openclaw-gateway.service openclaw-gateway2.service; do
  if systemctl --user is-active --quiet "$svc"; then
    log "✅ $svc is active"
  else
    log "⚠️ $svc is NOT active"
  fi
done

log "Post-update restart complete"
