#!/usr/bin/env python3
"""
pi_check_notifications.py — 检查待推送通知

供 heartbeat 或主 session 调用，返回待推送的智能系统通知。

用法：
  python3 pi_check_notifications.py         # 检查并输出
  python3 pi_check_notifications.py --clear  # 输出后清空
  python3 pi_check_notifications.py --json   # JSON 格式输出
"""

import argparse
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
INTEL_DIR = Path(os.path.expanduser("~/.openclaw/workspace/memory/intelligence"))
NOTIF_FILE = INTEL_DIR / "pending_notifications.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clear", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_out")
    args = parser.parse_args()

    if not NOTIF_FILE.exists():
        if args.json_out:
            print("[]")
        return

    try:
        data = json.loads(NOTIF_FILE.read_text(encoding="utf-8"))
    except Exception:
        return

    items = data.get("items", [])
    if not items:
        if args.json_out:
            print("[]")
        return

    if args.json_out:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        print(f"📬 {len(items)} 条智能系统通知:")
        for i, item in enumerate(items):
            prio = "🔴" if item.get("priority", 0) >= 4 else "🟡" if item.get("priority", 0) >= 3 else "⚪"
            print(f"  {prio} {item.get('text', '')[:80]}")

    if args.clear:
        data["items"] = []
        data["cleared_at"] = datetime.now(TZ).isoformat()
        tmp = NOTIF_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(NOTIF_FILE)


if __name__ == "__main__":
    main()
