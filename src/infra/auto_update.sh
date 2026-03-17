#!/bin/bash
# auto_update.sh — 自动更新 OpenClaw + Skills
# 由系统 crontab 调用（在 gateway 外部执行）
# 流程：检查新版本 → 停 gateway → npm 更新 → 启 gateway → 更新 skills
set -euo pipefail

export PATH="/home/mi/.nvm/versions/node/v22.22.0/bin:$PATH"
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export HOME="/home/mi"

LOG_DIR="$HOME/.openclaw/workspace/logs"
LOG_FILE="$LOG_DIR/auto-update.log"
mkdir -p "$LOG_DIR"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "========== Auto-update start =========="

# ── 1. 检查 OpenClaw 新版本 ──
CURRENT=$(openclaw --version 2>/dev/null | grep -oP '[\d.]+' | head -1 || echo "unknown")
LATEST=$(npm view openclaw version 2>/dev/null || echo "unknown")
log "Current: $CURRENT, Latest: $LATEST"

OC_UPDATED=false
if [ "$CURRENT" != "$LATEST" ] && [ "$LATEST" != "unknown" ]; then
  log "New version available: $CURRENT → $LATEST"
  
  # 停 gateway
  log "Stopping gateway..."
  systemctl --user stop openclaw-gateway.service 2>/dev/null || true
  sleep 3
  
  # 确认已停
  if systemctl --user is-active --quiet openclaw-gateway.service; then
    log "⚠️ Gateway still running, force killing..."
    systemctl --user kill openclaw-gateway.service 2>/dev/null || true
    sleep 2
  fi
  
  # npm 更新
  log "Installing openclaw@latest..."
  if npm install -g openclaw@latest 2>&1 | tee -a "$LOG_FILE"; then
    OC_UPDATED=true
    NEW_VER=$(openclaw --version 2>/dev/null | grep -oP '[\d.]+' | head -1 || echo "unknown")
    log "✅ Updated: $CURRENT → $NEW_VER"
  else
    log "❌ npm install failed"
  fi
  
  # 重装 gateway service（确保 ExecStart 路径正确）
  if [ "$OC_UPDATED" = true ]; then
    log "Reinstalling gateway service..."
    openclaw gateway install --force 2>&1 | tee -a "$LOG_FILE" || true
    systemctl --user daemon-reload
  fi
  
  # 启 gateway
  log "Starting gateway..."
  systemctl --user start openclaw-gateway.service
  sleep 5
  
  if systemctl --user is-active --quiet openclaw-gateway.service; then
    log "✅ Gateway is active"
  else
    log "❌ Gateway failed to start!"
    # watchdog 会兜底
  fi

  # 也重启 gateway2（如果存在）
  if systemctl --user list-unit-files openclaw-gateway2.service &>/dev/null; then
    systemctl --user restart openclaw-gateway2.service 2>/dev/null || true
    log "Gateway2 restarted"
  fi
else
  log "Already on latest ($CURRENT), skipping OpenClaw update"
fi

# ── 2. 更新 Skills ──
log "Updating skills..."
if npx clawhub update --all 2>&1 | tee -a "$LOG_FILE"; then
  log "✅ Skills updated"
else
  log "⚠️ Skills update had issues (see above)"
fi

# ── 3. 汇总 ──
if [ "$OC_UPDATED" = true ]; then
  log "🎉 Update complete: OpenClaw $CURRENT → $NEW_VER + skills refreshed"
else
  log "✅ Update check complete: OpenClaw $CURRENT (no change) + skills refreshed"
fi

log "========== Auto-update end =========="
