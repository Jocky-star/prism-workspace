#!/bin/bash
# Prism 系统 crontab 兜底运行器
# 用于在 openclaw cron 不可靠时，通过系统 cron 直接跑关键脚本
#
# 使用方法：
#   bash prism_cron_runner.sh daily_pipeline    # 跑每日管线
#   bash prism_cron_runner.sh morning_push      # 跑晨间推送
#   bash prism_cron_runner.sh audio_fetch       # 跑录音拉取
#   bash prism_cron_runner.sh weekly_refine     # 跑周精炼
#   bash prism_cron_runner.sh action_check      # 跑行动检查
#
# 特性：
#   - 执行结果写入 logs/prism_cron.log
#   - 失败时通过 openclaw message 通知用户（best effort）
#   - 进程锁：同一任务不重叠执行

set -euo pipefail

WORKSPACE="/home/mi/.openclaw/workspace"
LOG_FILE="$WORKSPACE/logs/prism_cron.log"
LOCK_DIR="/tmp/prism_cron_locks"
TASK="${1:-}"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

mkdir -p "$LOCK_DIR"

log() {
    echo "[$TIMESTAMP] [$TASK] $1" | tee -a "$LOG_FILE"
}

notify_error() {
    local msg="$1"
    log "ERROR: $msg"
    # 尝试通过 openclaw 通知用户（失败不影响脚本退出状态）
    openclaw message send \
        --to "user:ou_f305f404023133b798c664548d5a4304" \
        --text "⚠️ Prism cron 失败 [$TASK]: $msg" \
        2>/dev/null || true
}

# 进程锁
LOCK_FILE="$LOCK_DIR/$TASK.lock"
if [ -f "$LOCK_FILE" ]; then
    OLD_PID=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        log "SKIP: $TASK 已在运行 (PID=$OLD_PID)"
        exit 0
    fi
fi
echo $$ > "$LOCK_FILE"
trap "rm -f '$LOCK_FILE'" EXIT

log "START: $TASK"

cd "$WORKSPACE"
# 激活 venv（如果存在）
[ -f "$WORKSPACE/.venv/bin/activate" ] && source "$WORKSPACE/.venv/bin/activate" || true

case "$TASK" in
  daily_pipeline)
    # ⚠️ 已迁移至新版 services/pipeline.py（2026-03-16）
    # 旧版 src/actions/planning/daily_pipeline.py 已停用
    TODAY=$(date '+%Y-%m-%d')
    if python3 src/services/pipeline.py --date "$TODAY" --pipeline daily 2>&1 | tee -a "$LOG_FILE"; then
        log "OK: daily_pipeline (new: services/pipeline.py) done"
    else
        notify_error "daily_pipeline 执行失败 ($TODAY)"
        exit 1
    fi
    ;;

  morning_push)
    if python3 src/services/morning_push.py 2>&1 | tee -a "$LOG_FILE"; then
        log "OK: morning_push done"
    else
        notify_error "morning_push 执行失败"
        exit 1
    fi
    ;;

  audio_fetch)
    if python3 src/sources/audio/fetch.py --range 3 2>&1 | tee -a "$LOG_FILE"; then
        log "OK: audio_fetch done"
    else
        notify_error "audio_fetch 执行失败"
        exit 1
    fi
    ;;

  weekly_refine)
    if python3 src/intelligence/weekly_refine.py 2>&1 | tee -a "$LOG_FILE"; then
        log "OK: weekly_refine done"
    else
        notify_error "weekly_refine 执行失败"
        exit 1
    fi
    ;;

  action_check)
    if python3 src/actions/planning/action.py 2>&1 | tee -a "$LOG_FILE"; then
        log "OK: action_check done"
    else
        notify_error "action_check 执行失败"
        exit 1
    fi
    ;;

  services_pipeline)
    TODAY=$(date '+%Y-%m-%d')
    if python3 src/services/pipeline.py --date "$TODAY" --pipeline daily 2>&1 | tee -a "$LOG_FILE"; then
        log "OK: services_pipeline done"
    else
        notify_error "services_pipeline 执行失败"
        exit 1
    fi
    ;;

  *)
    log "ERROR: 未知任务 '$TASK'"
    echo "可用任务: daily_pipeline | morning_push | audio_fetch | weekly_refine | action_check | services_pipeline"
    exit 1
    ;;
esac

log "END: $TASK"
