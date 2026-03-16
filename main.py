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

    app_id = feishu.get("app_id", "")
    if app_id:
        print(f"   飞书应用: ✅ 已配置 ({app_id[:12]}...)")
    else:
        print("   飞书应用: ❌ 未配置 → python3 main.py setup")

    targets = feishu.get("target_user_ids", "")
    n_targets = len([t for t in targets.split(",") if t.strip()]) if targets else 0
    print(f"   推送目标: {'✅' if n_targets else '❌'} {n_targets} 个用户")

    model = llm.get("model", "未配置")
    print(f"   LLM: {'✅' if llm.get('api_key') else '❌'} {model}")

    tenant = feishu.get("tenant_domain", "未配置")
    print(f"   租户域名: {tenant}")

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
    if n_targets == 0:
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


# ── 主入口 ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="🌟 Prism — 你的个人智能秘书",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
子命令：
  setup              初始化配置文件
  status             查看系统状态
  brief              生成并推送 Brief
  brief --dry-run    预览 Brief（不推送）

首次使用？运行 python3 main.py setup
""",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("setup", help="初始化配置文件")
    sub.add_parser("status", help="查看系统状态")

    brief_p = sub.add_parser("brief", help="生成并推送 Brief")
    brief_p.add_argument("--dry-run", action="store_true", help="预览不推送")
    brief_p.add_argument("--date", default=None, help="日期 YYYY-MM-DD（默认昨天）")

    args = parser.parse_args()

    if args.command == "setup":
        cmd_setup()
    elif args.command == "status":
        cmd_status()
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
