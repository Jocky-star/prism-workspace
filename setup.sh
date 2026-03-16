#!/bin/bash
# Prism Workspace 初始化脚本
# 用法: bash setup.sh
#
# 新用户 clone 后运行一次，完成目录创建、依赖安装、配置初始化

set -e

WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "📁 工作目录: $WORKSPACE"
echo ""

# ── 1. 创建运行时数据目录（这些被 gitignore，需要手动创建）──────────────────
echo "📂 创建数据目录..."
mkdir -p "$WORKSPACE/memory/intelligence"
mkdir -p "$WORKSPACE/memory/action_log"
mkdir -p "$WORKSPACE/memory/feedback"
mkdir -p "$WORKSPACE/memory/habits/summaries"
mkdir -p "$WORKSPACE/memory/services"
mkdir -p "$WORKSPACE/memory/visual"
mkdir -p "$WORKSPACE/memory/daily-digest"
mkdir -p "$WORKSPACE/memory/weekly-reviews"
mkdir -p "$WORKSPACE/data/daily-reports"
mkdir -p "$WORKSPACE/data/ai_news"
mkdir -p "$WORKSPACE/logs"
mkdir -p "$WORKSPACE/camera"
mkdir -p "$WORKSPACE/diary"
echo "  ✅ 目录创建完成"

# ── 2. 安装 Python 依赖 ────────────────────────────────────────────────────────
echo ""
echo "📦 安装 Python 依赖..."
if command -v pip3 &>/dev/null; then
    pip3 install -r "$WORKSPACE/requirements.txt" --quiet
    echo "  ✅ 依赖安装完成"
else
    echo "  ⚠️  pip3 未找到，请手动运行: pip3 install -r requirements.txt"
fi

# ── 3. 创建配置文件 ────────────────────────────────────────────────────────────
echo ""
echo "⚙️  初始化配置..."
if [ ! -f "$WORKSPACE/config.yaml" ]; then
    if [ -f "$WORKSPACE/config.example.yaml" ]; then
        cp "$WORKSPACE/config.example.yaml" "$WORKSPACE/config.yaml"
        echo "  ✅ config.yaml 已创建（从 config.example.yaml 复制）"
        echo "  ⚠️  请编辑 config.yaml，填入你的 API Key 和飞书配置"
    else
        echo "  ℹ️  未找到 config.example.yaml，跳过"
    fi
else
    echo "  ✅ config.yaml 已存在，跳过"
fi

# ── 4. 检查 OpenClaw ───────────────────────────────────────────────────────────
echo ""
echo "🔍 检查 OpenClaw..."
if command -v openclaw &>/dev/null; then
    echo "  ✅ OpenClaw 已安装: $(openclaw --version 2>/dev/null || echo '版本未知')"
else
    echo "  ❌ OpenClaw 未安装"
    echo "     安装方法: npm install -g openclaw"
    echo "     文档: https://github.com/openclaw/openclaw"
fi

# ── 5. 可选：设置 cron 任务 ────────────────────────────────────────────────────
echo ""
read -p "🕐 要设置定时任务吗？(y/n) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    bash "$WORKSPACE/setup_crons.sh"
else
    echo "  ℹ️  跳过。之后可以运行: bash setup_crons.sh"
fi

# ── 完成 ───────────────────────────────────────────────────────────────────────
echo ""
echo "🎉 初始化完成！"
echo ""
echo "下一步："
echo "  1. 编辑 config.yaml，填入 API Key 和飞书配置"
echo "  2. 阅读 README.md 了解项目架构"
echo "  3. 运行 python3 src/services/pipeline.py --help 验证管线"
echo ""
