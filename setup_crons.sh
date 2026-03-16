#!/bin/bash
# Prism 定时任务安装脚本（更新于 2026-03-16）
# 用法: bash setup_crons.sh
#
# 安装推荐的定时任务到 OpenClaw cron。
# 每个任务都有开关，可以按需选择安装。

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "📁 项目目录: $SCRIPT_DIR"

# 检查 openclaw 是否可用
if ! command -v openclaw &>/dev/null; then
    echo "❌ openclaw 命令未找到，请先安装 OpenClaw"
    echo "   npm install -g openclaw"
    exit 1
fi

echo ""
echo "📋 可安装的定时任务："
echo ""
echo "  [核心任务]"
echo "  1. 晨间 Brief 推送     — 每天 08:30，整合昨日数据发给你"
echo "  2. 每日数据管线        — 每天 23:40，收集并处理当日数据"
echo "  3. AI 新闻日报         — 每天 09:00，推送 AI 领域最新动态"
echo "  4. 录音数据拉取        — 每天 23:00，拉取当日录音数据"
echo ""
echo "  [周期任务]"
echo "  5. 周度人际洞察        — 每周日 21:00，生成人际关系洞察"
echo "  6. 习惯规则进化        — 每周一 05:00，更新行为预测规则"
echo ""
echo "  [辅助任务]"
echo "  7. 习惯观察摘要        — 每天 18:00，生成行为观察摘要"
echo "  8. 每晚自主学习        — 每天 00:30，自动学习研究"
echo "  9. API 用量日报        — 每天 23:20，统计 token 消耗"
echo ""

read -p "安装所有推荐任务？(y=全部, n=手动选择) " -n 1 -r INSTALL_ALL
echo ""

install_job() {
    local num="$1"
    local name="$2"
    if [[ "$INSTALL_ALL" =~ ^[Yy]$ ]]; then
        return 0  # 全部安装
    fi
    read -p "  安装 $num. $name？(y/n) " -n 1 -r
    echo ""
    [[ $REPLY =~ ^[Yy]$ ]]
}

# ── 1. 晨间 Brief 推送 ────────────────────────────────────────────────────────
if install_job "1" "晨间 Brief 推送（每天 08:30）"; then
    echo "🌅 安装: 晨间 Brief..."
    openclaw cron add \
        --name "晨间Brief推送" \
        --cron "30 8 * * *" \
        --tz "Asia/Shanghai" \
        --message "执行晨间 Brief 推送：cd $SCRIPT_DIR && python3 src/services/morning_push.py 2>/dev/null。把输出的 Brief 文本完整发给用户。" \
        --model "litellm/pa/claude-sonnet-4-6" \
        --announce \
        --timeout-seconds 300 \
        2>/dev/null && echo "  ✅ 已安装" || echo "  ⚠️ 可能已存在"
fi

# ── 2. 每日数据管线 ───────────────────────────────────────────────────────────
if install_job "2" "每日数据管线（每天 23:40）"; then
    echo "🔄 安装: 每日数据管线..."
    openclaw cron add \
        --name "每日服务管线" \
        --cron "40 23 * * *" \
        --tz "Asia/Shanghai" \
        --message "运行智能系统每日管线：TODAY=\$(date +%Y-%m-%d); cd $SCRIPT_DIR && python3 src/services/pipeline.py --date \$TODAY --pipeline daily 2>&1 | tail -20 && python3 src/services/generators/daily_brief.py --date \$TODAY --save 2>&1 | tail -10。如有洞察产出简要汇报。" \
        --model "litellm/pa/claude-sonnet-4-6" \
        --no-deliver \
        --timeout-seconds 300 \
        2>/dev/null && echo "  ✅ 已安装" || echo "  ⚠️ 可能已存在"
fi

# ── 3. AI 新闻日报 ────────────────────────────────────────────────────────────
if install_job "3" "AI 新闻日报（每天 09:00）"; then
    echo "📰 安装: AI 新闻日报..."
    openclaw cron add \
        --name "AI新闻日报" \
        --cron "0 9 * * *" \
        --message "python3 $SCRIPT_DIR/src/actions/monitoring/ai_news_radar.py --human" \
        --model "litellm/pa/claude-sonnet-4-6" \
        --announce \
        --timeout-seconds 480 \
        2>/dev/null && echo "  ✅ 已安装" || echo "  ⚠️ 可能已存在"
fi

# ── 4. 录音数据拉取 ───────────────────────────────────────────────────────────
if install_job "4" "录音数据拉取（每天 23:00）"; then
    echo "🎙️  安装: 录音数据拉取..."
    openclaw cron add \
        --name "daily-report-fetch" \
        --cron "0 23 * * *" \
        --tz "Asia/Shanghai" \
        --message "运行日报拉取脚本：python3 $SCRIPT_DIR/skills/audio-daily-insight/scripts/fetch_daily.py $SCRIPT_DIR/skills/audio-daily-insight 2>&1 | tail -5。成功且有新数据则简短汇报，无数据则 HEARTBEAT_OK。" \
        --model "litellm/pa/claude-haiku-4-5-20251001" \
        --timeout-seconds 60 \
        2>/dev/null && echo "  ✅ 已安装" || echo "  ⚠️ 可能已存在"
fi

# ── 5. 周度人际洞察 ───────────────────────────────────────────────────────────
if install_job "5" "周度人际洞察（每周日 21:00）"; then
    echo "📊 安装: 周度人际洞察..."
    openclaw cron add \
        --name "PI周精炼" \
        --cron "0 21 * * 0" \
        --tz "Asia/Shanghai" \
        --message "运行智能系统周精炼：cd $SCRIPT_DIR && python3 src/intelligence/weekly_refine.py 2>&1 | tail -30。把周报摘要发给用户。" \
        --model "litellm/pa/claude-sonnet-4-6" \
        --no-deliver \
        --timeout-seconds 600 \
        2>/dev/null && echo "  ✅ 已安装" || echo "  ⚠️ 可能已存在"
fi

# ── 6. 习惯规则进化 ───────────────────────────────────────────────────────────
if install_job "6" "习惯规则进化（每周一 05:00）"; then
    echo "🧠 安装: 习惯规则进化..."
    openclaw cron add \
        --name "habit-rules-evolve" \
        --cron "0 5 * * 1" \
        --tz "Asia/Shanghai" \
        --message "运行 python3 $SCRIPT_DIR/skills/habit-predictor/scripts/evolve_rules.py 自动进化行为规则。如有变更，简短通知用户规则更新了什么。无变更则不打扰。" \
        --model "litellm/pa/claude-sonnet-4-6" \
        --timeout-seconds 300 \
        2>/dev/null && echo "  ✅ 已安装" || echo "  ⚠️ 可能已存在"
fi

# ── 7. 习惯观察摘要 ───────────────────────────────────────────────────────────
if install_job "7" "习惯观察摘要（每天 18:00）"; then
    echo "👁️  安装: 习惯观察摘要..."
    openclaw cron add \
        --name "habit-predictor 每日观察摘要" \
        --cron "0 18 * * *" \
        --tz "Asia/Shanghai" \
        --message "执行 habit-predictor 每日观察摘要：bash $SCRIPT_DIR/skills/habit-predictor/scripts/daily_summary_cron.sh，读取生成的摘要，若有观察给用户发不超过 120 字的简短分析。" \
        --model "litellm/pa/claude-sonnet-4-6" \
        --timeout-seconds 120 \
        2>/dev/null && echo "  ✅ 已安装" || echo "  ⚠️ 可能已存在"
fi

# ── 8. 每晚自主学习 ───────────────────────────────────────────────────────────
if install_job "8" "每晚自主学习（每天 00:30）"; then
    echo "📚 安装: 每晚自主学习..."
    openclaw cron add \
        --name "每晚自主学习" \
        --cron "30 0 * * *" \
        --tz "Asia/Shanghai" \
        --message "你是私人 AI 助手。现在是自主学习时段（00:30-06:00）。先读 $SCRIPT_DIR/USER.md 和 MEMORY.md 了解主人，再读 memory/learning-log.md 避免重复。自己判断今晚学什么（关注主人的项目和领域），每个主题 15-30 分钟，学完写入 memory/learning-log.md，有价值的发现追加到 memory/learning-findings.md。不发消息打扰。学完一个接下一个，充分利用学习时段。" \
        --model "litellm/pa/claude-sonnet-4-6" \
        --no-deliver \
        --timeout-seconds 25200 \
        2>/dev/null && echo "  ✅ 已安装" || echo "  ⚠️ 可能已存在"
fi

# ── 9. API 用量日报 ───────────────────────────────────────────────────────────
if install_job "9" "API 用量日报（每天 23:20）"; then
    echo "📈 安装: API 用量日报..."
    openclaw cron add \
        --name "API用量日报" \
        --cron "20 23 * * *" \
        --tz "Asia/Shanghai" \
        --message "查看今日 API 用量和 token 消耗，用 session_status 获取用量数据，整理成简洁日报（总 token 数、活跃 session 数、cron 运行情况、异常记录）发飞书给用户。" \
        --model "litellm/pa/claude-sonnet-4-6" \
        --timeout-seconds 120 \
        2>/dev/null && echo "  ✅ 已安装" || echo "  ⚠️ 可能已存在"
fi

echo ""
echo "✅ 定时任务安装完成！"
echo ""
echo "管理命令："
echo "  openclaw cron list          # 查看所有定时任务"
echo "  openclaw cron disable <id>  # 禁用某个任务"
echo "  openclaw cron enable <id>   # 启用某个任务"
echo "  openclaw cron run <id>      # 手动触发一次"
