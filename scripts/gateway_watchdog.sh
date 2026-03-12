#!/bin/bash
# Gateway 健康检查 + 自动恢复（双 OpenClaw 版）
# crontab: */2 * * * * /home/mi/.openclaw/workspace/scripts/gateway_watchdog.sh

LOG="/home/mi/.openclaw/workspace/logs/watchdog.log"
mkdir -p "$(dirname "$LOG")"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# 只保留最近 500 行日志
if [ -f "$LOG" ] && [ $(wc -l < "$LOG") -gt 500 ]; then
    tail -200 "$LOG" > "${LOG}.tmp" && mv "${LOG}.tmp" "$LOG"
fi

check_gateway() {
    local NAME="$1"
    local PORT="$2"
    local SERVICE="$3"
    local NEED_RESTART=0

    # 检查1: 端口监听
    if ! ss -tlnp 2>/dev/null | grep -q ":${PORT}"; then
        echo "$TIMESTAMP [ALERT] $NAME: Port $PORT not listening" >> "$LOG"
        NEED_RESTART=1
    fi

    # 检查2: HTTP 响应（仅端口正常时检查）
    if [ "$NEED_RESTART" -eq 0 ]; then
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "http://127.0.0.1:${PORT}/" 2>/dev/null)
        if [ "$HTTP_CODE" = "000" ] || [ -z "$HTTP_CODE" ]; then
            echo "$TIMESTAMP [ALERT] $NAME: HTTP not responding (code=$HTTP_CODE)" >> "$LOG"
            NEED_RESTART=1
        fi
    fi

    # 重启
    if [ "$NEED_RESTART" -eq 1 ]; then
        echo "$TIMESTAMP [ACTION] $NAME: Restarting $SERVICE ..." >> "$LOG"
        systemctl --user restart "$SERVICE"
        sleep 15
        if ss -tlnp 2>/dev/null | grep -q ":${PORT}"; then
            echo "$TIMESTAMP [OK] $NAME: Restarted successfully" >> "$LOG"
        else
            echo "$TIMESTAMP [CRITICAL] $NAME: Restart FAILED!" >> "$LOG"
        fi
    fi
}

# 主 OpenClaw — 端口 18789
check_gateway "OpenClaw-Main" 18789 "openclaw-gateway.service"

# 第二个 OpenClaw — 端口 18793
check_gateway "OpenClaw-2" 18793 "openclaw-gateway2.service"
