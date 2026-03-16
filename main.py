#!/usr/bin/env python3
"""Prism — 你的个人智能秘书

统一入口：配置引导 / 系统状态 / Brief 生成推送
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent
CONFIG_PATH = WORKSPACE / "config.yaml"
CONFIG_EXAMPLE = WORKSPACE / "config.example.yaml"


# ── 简易 YAML 读写（零依赖）──────────────────────────────

def _read_yaml(path: Path) -> dict:
    """最简 YAML 解析（只支持 key: value 和一层嵌套）"""
    data = {}
    current_section = None
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" ") and stripped.endswith(":") and ":" == stripped[-1]:
            current_section = stripped[:-1].strip()
            data[current_section] = {}
            continue
        if ":" in stripped:
            k, v = stripped.split(":", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if current_section:
                data[current_section][k] = v
            else:
                data[k] = v
    return data


# ── 配置引导 ─────────────────────────────────────────────

def cmd_setup():
    """配置引导：复制 config.example.yaml 到 config.yaml，告知需要填写的字段。"""
    if CONFIG_PATH.exists():
        print(f"\n✅ config.yaml 已存在：{CONFIG_PATH}")
        print("\n需要修改配置？直接编辑 config.yaml，或删除后重新运行 setup。")
        print("\n当前状态：")
        cmd_status()
        return

    if not CONFIG_EXAMPLE.exists():
        print("❌ 未找到 config.example.yaml，请确认项目完整 clone。")
        sys.exit(1)

    import shutil
    shutil.copy(CONFIG_EXAMPLE, CONFIG_PATH)
    print(f"\n✅ 已从模板创建 config.yaml")
    print("""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📝 请编辑 config.yaml，填入以下必填项：

   【LLM 配置】
   llm.endpoint   — LLM API 地址（兼容 OpenAI 格式）
   llm.api_key    — API Key

   【飞书 Bot 配置】
   feishu.app_id              — 飞书应用 App ID
   feishu.app_secret          — 飞书应用 App Secret
   feishu.target_user_open_id — 推送目标用户的 Open ID

获取飞书配置：https://open.feishu.cn → 创建自建应用 → 凭证与基础信息
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

填完之后运行：
   python3 main.py status          验证配置
   python3 main.py brief --dry-run 预览第一份 Brief
""")


# ── 系统状态 ──────────────────────────────────────────────

def cmd_status():
    print("\n🌟 Prism 系统状态\n")

    # 配置
    print("📊 配置")
    cfg = _read_yaml(CONFIG_PATH)
    feishu = cfg.get("feishu", {})
    llm = cfg.get("llm", {})

    # 占位符检测
    _PH = {"your", "xxx", "example", "placeholder", "here", "填入", "替换"}
    def _is_real(val: str) -> bool:
        if not val:
            return False
        v = val.lower().replace("-", "").replace("_", "")
        return not any(p in v for p in _PH)

    app_id = feishu.get("app_id", "")
    if _is_real(app_id):
        print(f"   飞书应用: ✅ 已配置 ({app_id[:12]}...)")
    else:
        print("   飞书应用: ❌ 未配置 → 编辑 config.yaml 填入 feishu.app_id")

    target_id = feishu.get("target_user_open_id", "")
    if not target_id:
        # 兼容旧格式
        targets_str = feishu.get("target_user_ids", "")
        target_ids = [t.strip() for t in targets_str.split(",") if t.strip()] if targets_str else []
    else:
        target_ids = [t.strip() for t in target_id.split(",") if t.strip()]
    real_targets = [t for t in target_ids if _is_real(t)]
    print(f"   推送目标: {'✅' if real_targets else '❌'} {len(real_targets)} 个用户")

    api_key = llm.get("api_key", "")
    model = llm.get("default_model", "") or llm.get("model", "")
    if _is_real(api_key) and _is_real(model):
        print(f"   LLM: ✅ {model}")
    elif _is_real(api_key):
        print(f"   LLM: ⚠️ API Key 已填，模型未配置")
    else:
        print("   LLM: ❌ 未配置 → 编辑 config.yaml 填入 llm.api_key")

    tenant = feishu.get("tenant_domain", "")
    if _is_real(tenant):
        print(f"   租户域名: ✅ {tenant}")
    else:
        print("   租户域名: ⚠️ 未配置（可选，用于修复飞书链接）")

    # 数据
    print("\n📁 数据")
    data_dir = WORKSPACE / "data" / "daily-reports"
    if data_dir.exists():
        reports = sorted([f.stem for f in data_dir.glob("*.json")])
        if reports:
            print(f"   录音数据: {len(reports)} 天 ({reports[0]} ~ {reports[-1]})")
        else:
            print("   录音数据: 0 天")
    else:
        print("   录音数据: 目录不存在")

    action_log_dir = WORKSPACE / "memory" / "action_log"
    if action_log_dir.exists():
        logs = sorted(action_log_dir.glob("*.jsonl"))
        total_entries = 0
        latest = "无"
        for lf in logs:
            count = sum(1 for line in lf.read_text().splitlines() if line.strip())
            total_entries += count
        if logs:
            latest = logs[-1].stem
        print(f"   行动日志: {total_entries} 条 (最近: {latest})")
    else:
        print("   行动日志: 目录不存在")

    intel_dir = WORKSPACE / "memory" / "intelligence"
    intel_files = ["entities.json", "events.jsonl", "profile.json", "insights.jsonl"]
    intel_status = []
    for f in intel_files:
        name = f.split(".")[0]
        exists = (intel_dir / f).exists() if intel_dir.exists() else False
        intel_status.append(f"{name} {'✅' if exists else '❌'}")
    print(f"   智能数据: {' | '.join(intel_status)}")

    mem_dir = WORKSPACE / "memory"
    if mem_dir.exists():
        mem_days = len(list(mem_dir.glob("2???-??-??.md")))
        print(f"   记忆文件: {mem_days} 天")

    # 服务状态
    print("\n🔄 服务")
    briefs_dir = WORKSPACE / "memory" / "services"
    if briefs_dir.exists():
        brief_files = sorted(briefs_dir.glob("*.json"))
        if brief_files:
            latest_brief = brief_files[-1]
            mtime = datetime.fromtimestamp(latest_brief.stat().st_mtime)
            print(f"   最近 Brief: {latest_brief.stem} {mtime.strftime('%H:%M')} ✅")
        else:
            print("   最近 Brief: 无记录")
    else:
        print("   最近 Brief: 无记录")

    # 建议
    print("\n💡 建议")
    if not app_id:
        print("   • 运行 python3 main.py setup 配置飞书和 LLM")
    if not real_targets:
        print("   • 配置飞书推送目标（Open ID）")
    print("   • 确保录音数据定期同步到 data/daily-reports/")
    print("   • 设置 cron 每日自动推送 Brief")
    print()


# ── Brief 生成 ────────────────────────────────────────────

def cmd_brief(dry_run=False, date=None):
    if not CONFIG_PATH.exists():
        if dry_run:
            print("""
⚠️ 未找到 config.yaml，无法预览 Brief。

请先完成配置：
   python3 main.py setup   复制配置模板
   # 编辑 config.yaml，填入飞书和 LLM 配置
   python3 main.py status  验证配置

配置完成后再运行：
   python3 main.py brief --dry-run
""")
        else:
            print("⚠️ 未找到 config.yaml，请先运行 python3 main.py setup")
        sys.exit(1)

    if date is None:
        date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    args = ["python3", str(WORKSPACE / "src" / "services" / "morning_push.py"), "--date", date]
    if dry_run:
        # 使用 daily_brief 的 dry-run
        args = ["python3", "-c", f"""
import sys; sys.path.insert(0, '{WORKSPACE}')
from src.services.generators.daily_brief import generate_brief, format_brief_message
result = generate_brief('{date}', dry_run=True)
print(format_brief_message(result))
"""]

    os.execvp(args[0], args)


# ── 配置引导 (guide) ──────────────────────────────────────

def cmd_guide():
    """输出分阶段配置引导，帮助用户配置数据源、管线和硬件扩展。"""
    print("""
🌟 Prism 配置引导

你已完成基础配置。以下是进阶配置：

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📡 第一步：数据源

目前支持以下数据源，按需开启：

  1. 录音数据（推荐）
     在 config.yaml 中设置：
     sources.audio.enabled: true
     sources.audio.api_url: "你的转写服务地址"
     sources.audio.api_key: "你的 API Key"

  2. 对话记录（自动）
     从 OpenClaw memory/ 目录自动读取，无需配置

  3. 股票监控
     sources.stock.enabled: true
     sources.stock.watchlist: ["600519", "000858"]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🧠 第二步：智能管线

配置完数据源后，需要设置定时任务让管线自动运行。
让你的 Agent 执行：

  python3 main.py cron-setup

这会自动创建以下 cron 任务：
  • 22:45 — 拉取录音数据
  • 23:10 — 每日智能管线（感知→理解→摘要）
  • 23:20 — 服务管线（Brief 生成）
  • 08:30 — 晨间 Brief 推送
  • 周日 20:00 — 周精炼

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔌 第三步：硬件扩展（可选）

  1. 摄像头感知
     features.camera.enabled: true
     features.camera.rotation: 180  # 如果物理倒置

  2. 米家智能家居
     features.mijia.enabled: true
     features.mijia.username: "手机号"
     features.mijia.password: "密码"

  3. SPI 屏幕（Prism 显示屏）
     features.screen.enabled: true
     需要：树莓派 + MHS35 3.5寸 SPI 屏

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ 配置完毕后运行 python3 main.py status 验证
""")


# ── 定时任务设置 (cron-setup) ─────────────────────────────

def cmd_cron_setup():
    """自动写入 crontab，幂等操作（重复运行不会重复添加）。"""
    import subprocess

    python = sys.executable
    workspace = str(WORKSPACE)

    # 每条 cron 任务定义：(标记, 时间表达式, 命令, 描述)
    cron_entries = [
        (
            "prism:audio-fetch",
            "45 22 * * *",
            f"cd {workspace} && {python} src/sources/audio/fetch.py",
            "录音数据拉取",
        ),
        (
            "prism:daily-pipeline",
            "10 23 * * *",
            f"cd {workspace} && {python} src/intelligence/perception.py && {python} src/intelligence/understand.py && {python} src/intelligence/daily_digest.py",
            "每日智能管线",
        ),
        (
            "prism:service-pipeline",
            "20 23 * * *",
            f"cd {workspace} && {python} src/services/pipeline.py",
            "服务管线",
        ),
        (
            "prism:morning-push",
            "30 8 * * *",
            f"cd {workspace} && {python} main.py brief",
            "晨间 Brief 推送",
        ),
        (
            "prism:weekly-refine",
            "0 20 * * 0",
            f"cd {workspace} && {python} src/intelligence/weekly_refine.py",
            "周精炼",
        ),
    ]

    print("\n📅 设置定时任务...\n")

    # 读取现有 crontab
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        existing = result.stdout if result.returncode == 0 else ""
    except FileNotFoundError:
        print("❌ 未找到 crontab 命令，请确认系统已安装 cron。")
        sys.exit(1)

    # 删除旧的 prism: 标记行（幂等）
    lines = [line for line in existing.splitlines() if "# prism:" not in line]
    # 去掉尾部多余空行
    while lines and not lines[-1].strip():
        lines.pop()

    # 追加新条目
    if lines:
        lines.append("")  # 空行分隔
    for tag, schedule, command, _ in cron_entries:
        lines.append(f"{schedule} {command}  # {tag}")

    new_crontab = "\n".join(lines) + "\n"

    # 写入 crontab
    proc = subprocess.run(["crontab", "-"], input=new_crontab, text=True, capture_output=True)
    if proc.returncode != 0:
        print(f"❌ 写入 crontab 失败：{proc.stderr}")
        sys.exit(1)

    # 输出结果
    print("已添加：")
    labels = {
        "prism:audio-fetch":     "22:45 — 录音数据拉取",
        "prism:daily-pipeline":  "23:10 — 每日智能管线",
        "prism:service-pipeline":"23:20 — 服务管线",
        "prism:morning-push":    "08:30 — 晨间 Brief 推送",
        "prism:weekly-refine":   "周日 20:00 — 周精炼",
    }
    for tag, _, _, _ in cron_entries:
        print(f"  ✅ {labels[tag]}")

    # 验证写入结果
    verify = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    prism_lines = [l for l in verify.stdout.splitlines() if "# prism:" in l]
    if prism_lines:
        print("\n当前 crontab（Prism 条目）：")
        for line in prism_lines:
            print(f"  {line}")

    print("\n修改时间？编辑 config.yaml 的 schedule 段，然后重新运行 python3 main.py cron-setup\n")


# ── 主入口 ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="🌟 Prism — 你的个人智能秘书",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
子命令：
  setup              初始化配置文件
  status             查看系统状态
  guide              分阶段配置引导（数据源/管线/硬件）
  cron-setup         自动设置所有定时任务
  brief              生成并推送 Brief
  brief --dry-run    预览 Brief（不推送）

首次使用？运行 python3 main.py setup
完成基础配置后运行 python3 main.py guide 查看进阶配置
""",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("setup", help="初始化配置文件")
    sub.add_parser("status", help="查看系统状态")
    sub.add_parser("guide", help="分阶段配置引导（数据源/管线/硬件）")
    sub.add_parser("cron-setup", help="自动设置所有定时任务")

    brief_p = sub.add_parser("brief", help="生成并推送 Brief")
    brief_p.add_argument("--dry-run", action="store_true", help="预览不推送")
    brief_p.add_argument("--date", default=None, help="日期 YYYY-MM-DD（默认昨天）")

    args = parser.parse_args()

    if args.command == "setup":
        cmd_setup()
    elif args.command == "status":
        cmd_status()
    elif args.command == "guide":
        cmd_guide()
    elif args.command == "cron-setup":
        cmd_cron_setup()
    elif args.command == "brief":
        cmd_brief(dry_run=args.dry_run, date=args.date)
    elif args.command is None:
        # 首次运行：检查是否有配置
        if CONFIG_PATH.exists():
            cmd_status()
        else:
            print("""
🌟 Prism — 你的个人智能秘书

首次使用需要配置。请按以下步骤操作：

1. 复制配置文件
   cp config.example.yaml config.yaml

2. 编辑 config.yaml，填入：
   • 飞书 App ID 和 App Secret（从 open.feishu.cn 获取）
   • 飞书 Open ID（推送目标用户）
   • LLM API 地址和 Key

3. 验证配置
   python3 main.py status

4. 预览第一份 Brief
   python3 main.py brief --dry-run

详细说明见 README.md
""")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
