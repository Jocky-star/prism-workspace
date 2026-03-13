#!/usr/bin/env python3
"""
晨间 Brief 推送脚本

每天早上自动执行：
1. 用昨天的数据生成 Brief
2. 格式化为人类可读文本
3. 输出到 stdout（由 cron/agent 负责发送）

用法：
  # 直接运行（用昨天数据）
  python3 src/services/morning_push.py

  # 指定日期
  python3 src/services/morning_push.py --date 2026-03-12

  # 输出到文件
  python3 src/services/morning_push.py --output memory/services/brief_today.txt

设置为定时任务（推荐）：
  OpenClaw cron: 每天 8:30 执行本脚本
  脚本输出 Brief 文本，cron 的 announce 会自动发送给用户
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 确保可以从项目根目录导入
_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_root))

from src.services.generators.daily_brief import generate_brief, format_brief_message
from src.services.pipeline import run_daily


def get_yesterday(tz_offset: int = 8) -> str:
    """获取昨天的日期字符串"""
    tz = timezone(timedelta(hours=tz_offset))
    return (datetime.now(tz) - timedelta(days=1)).strftime("%Y-%m-%d")


def main():
    parser = argparse.ArgumentParser(description="晨间 Brief 推送")
    parser.add_argument("--date", help="数据日期 (默认: 昨天)", default=None)
    parser.add_argument("--output", help="输出文件路径 (默认: stdout)")
    parser.add_argument("--run-daily-first", action="store_true", default=True,
                        help="先跑 daily pipeline 再生成 brief (默认: true)")
    parser.add_argument("--skip-daily", action="store_true",
                        help="跳过 daily pipeline，直接生成 brief")
    parser.add_argument("--dry-run", action="store_true",
                        help="不调 LLM，输出模拟数据")
    args = parser.parse_args()

    date = args.date or get_yesterday()
    print(f"📅 生成 Brief: {date} 数据", file=sys.stderr)

    # 1. 先跑 daily pipeline（会议/意图/情绪）
    if not args.skip_daily:
        print(f"🔄 Running daily pipeline for {date}...", file=sys.stderr)
        daily_result = run_daily(date, dry_run=args.dry_run)
        if daily_result.errors:
            print(f"⚠️ Daily pipeline errors: {daily_result.errors}", file=sys.stderr)
        else:
            print(f"✅ Daily pipeline done", file=sys.stderr)

    # 2. 生成 Brief
    print(f"🌅 Generating brief...", file=sys.stderr)
    result = generate_brief(date, dry_run=args.dry_run)
    msg = format_brief_message(result)

    # 3. 输出
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(msg, encoding="utf-8")
        print(f"✅ Brief saved to {args.output}", file=sys.stderr)
    else:
        # stdout 输出 brief 文本（cron announce 会读取这个）
        print(msg)


if __name__ == "__main__":
    main()
