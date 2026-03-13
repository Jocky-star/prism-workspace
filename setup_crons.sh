#!/bin/bash
# Prism 定时任务安装脚本
# 用法: bash setup_crons.sh
#
# 安装以下定时任务到 OpenClaw：
# - 晨间 Brief: 每天 8:30 推送昨天的 Brief
# - Daily Pipeline: 每天 23:40 跑管线（会议/意图/情绪）
# - Weekly Pipeline: 每周日 21:00 跑人际洞察

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "📁 项目目录: $SCRIPT_DIR"

# 检查 openclaw 是否可用
if ! command -v openclaw &> /dev/null; then
    echo "❌ openclaw 命令未找到，请先安装 OpenClaw"
    echo "   https://github.com/openclaw/openclaw"
    exit 1
fi

echo ""
echo "📋 将安装以下定时任务："
echo "  1. 晨间 Brief    — 每天 8:30"
echo "  2. Daily Pipeline — 每天 23:40"
echo "  3. Weekly Pipeline — 每周日 21:00"
echo ""

# 1. 晨间 Brief
echo "🌅 安装: 晨间 Brief (每天 8:30)..."
openclaw cron add \
  --name "晨间Brief推送" \
  --cron "30 8 * * *" \
  --message "执行晨间 Brief 推送：cd $SCRIPT_DIR && python3 src/services/morning_push.py 2>/dev/null。把输出的 Brief 文本完整发给用户。" \
  --model "litellm/pa/claude-sonnet-4-6" \
  --announce \
  --timeout-seconds 300 \
  --tz "Asia/Shanghai" \
  2>/dev/null && echo "  ✅ 已安装" || echo "  ⚠️ 安装失败（可能已存在）"

# 2. Daily Pipeline
echo "🔄 安装: Daily Pipeline (每天 23:40)..."
openclaw cron add \
  --name "每日服务管线" \
  --cron "40 23 * * *" \
  --message "执行每日服务管线：cd $SCRIPT_DIR && python3 -c \"import sys; sys.path.insert(0,'.'); from src.services.pipeline import run_daily; from datetime import datetime, timezone, timedelta; d=datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d'); r=run_daily(d); print(f'Done: {len(r.errors)} errors')\"。如果有 errors 汇报给用户。" \
  --model "litellm/pa/claude-sonnet-4-6" \
  --no-deliver \
  --timeout-seconds 300 \
  --tz "Asia/Shanghai" \
  2>/dev/null && echo "  ✅ 已安装" || echo "  ⚠️ 安装失败（可能已存在）"

# 3. Weekly Pipeline
echo "📊 安装: Weekly Pipeline (每周日 21:00)..."
openclaw cron add \
  --name "每周人际洞察" \
  --cron "0 21 * * 0" \
  --message "执行每周人际洞察：cd $SCRIPT_DIR && python3 -c \"import sys; sys.path.insert(0,'.'); from src.services.pipeline import run_weekly; from datetime import datetime, timezone, timedelta; d=datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d'); r=run_weekly(d); print(f'Done: {len(r.errors)} errors')\"。把结果总结发给用户。" \
  --model "litellm/pa/claude-sonnet-4-6" \
  --announce \
  --timeout-seconds 300 \
  --tz "Asia/Shanghai" \
  2>/dev/null && echo "  ✅ 已安装" || echo "  ⚠️ 安装失败（可能已存在）"

echo ""
echo "✅ 定时任务安装完成！"
echo ""
echo "管理命令："
echo "  openclaw cron list          # 查看所有定时任务"
echo "  openclaw cron disable <id>  # 禁用某个任务"
echo "  openclaw cron enable <id>   # 启用某个任务"
echo "  openclaw cron run <id>      # 手动触发一次"
