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


def _write_yaml(path: Path, data: dict):
    lines = ["# Prism 配置文件（由 main.py setup 生成）\n"]
    for section, values in data.items():
        if isinstance(values, dict):
            lines.append(f"{section}:")
            for k, v in values.items():
                lines.append(f'  {k}: "{v}"')
            lines.append("")
        else:
            lines.append(f'{section}: "{values}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── 配置引导 ─────────────────────────────────────────────

def cmd_setup():
    print("""
🌟 欢迎使用 Prism — 你的个人智能秘书

   Prism 通过分析你的录音、对话和行为数据，
   理解你的生活和工作，主动帮你做事。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")
    config = {}

    # 1. 飞书
    print("1️⃣  飞书应用配置")
    print("   Prism 通过飞书推送每日 Brief。")
    print("   获取方式：https://open.feishu.cn → 创建应用 → 凭证信息\n")
    app_id = input("   App ID: ").strip()
    app_secret = input("   App Secret: ").strip()

    print("\n2️⃣  推送目标")
    print("   你的飞书 Open ID（接收 Brief 的用户）")
    print("   获取方式：飞书管理后台 → 通讯录 → 你的账号\n")
    open_id = input("   Open ID: ").strip()

    print("\n3️⃣  飞书租户域名")
    print("   格式：xxx.feishu.cn（从飞书文档链接中可看到）\n")
    tenant = input("   租户域名 [留空跳过]: ").strip() or ""

    config["feishu"] = {
        "app_id": app_id,
        "app_secret": app_secret,
        "target_user_ids": open_id,
    }
    if tenant:
        config["feishu"]["tenant_domain"] = tenant

    # 2. LLM
    print("\n4️⃣  LLM 配置")
    print("   Prism 需要 LLM 来理解数据和生成 Brief。")
    print("   支持任何 OpenAI 兼容 API。\n")
    api_base = input("   API Base URL [https://api.openai.com/v1]: ").strip() or "https://api.openai.com/v1"
    api_key = input("   API Key: ").strip()
    model = input("   Model [claude-sonnet-4-6]: ").strip() or "claude-sonnet-4-6"

    config["llm"] = {
        "api_base": api_base,
        "api_key": api_key,
        "model": model,
    }

    # 3. Brief
    config["brief"] = {
        "push_time": "08:30",
        "max_chars": "0",
    }

    # 验证飞书凭证
    if app_id and app_secret:
        print("\n⏳ 验证飞书凭证...", end=" ")
        try:
            import urllib.request
            req = urllib.request.Request(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                data=json.dumps({"app_id": app_id, "app_secret": app_secret}).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
            if result.get("code") == 0:
                print("✅ 飞书凭证有效")
            else:
                print(f"⚠️ 飞书返回错误：{result.get('msg', '未知')}")
        except Exception as e:
            print(f"⚠️ 验证失败：{e}")

    # 写配置
    _write_yaml(CONFIG_PATH, config)
    print(f"\n✅ 配置已保存到 {CONFIG_PATH.name}")

    print("""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🚀 下一步：
   python3 main.py status            查看系统状态
   python3 main.py brief --dry-run   预览第一份 Brief
   python3 main.py brief             生成并推送到飞书

   设置每日自动推送：
   crontab -e
   30 8 * * * cd {WORKSPACE} && python3 main.py brief >> logs/brief.log 2>&1
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
  setup              交互式配置引导
  status             查看系统状态
  brief              生成并推送 Brief
  brief --dry-run    预览 Brief（不推送）

首次使用？运行 python3 main.py setup
""",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("setup", help="交互式配置引导")
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
            cmd_setup()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
