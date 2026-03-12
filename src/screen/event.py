#!/usr/bin/env python3
"""
prism_event.py — Prism 事件闪屏触发工具

命令行用法：
  python3 prism_event.py alert "比亚迪涨停！"
  python3 prism_event.py done  "日报已发布"
  python3 prism_event.py info  "天气转晴"

Python import 用法：
  from prism_event import trigger_event
  trigger_event("alert", "比亚迪涨停！")
  trigger_event("done", "日报已发布", ttl=60)
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
EVENTS_FILE = Path(os.path.expanduser("~/.openclaw/workspace/memory/prism_events.json"))

VALID_TYPES = {"alert", "info", "done"}


def trigger_event(event_type: str, text: str, ttl: int = 30) -> bool:
    """
    向 prism_events.json 写入一条事件，供 prism_daemon.py 消费。

    参数：
      event_type: "alert" | "info" | "done"
      text:       显示文本（最多10字，超出截断）
      ttl:        过期秒数（默认 30 秒）

    返回：
      True 写入成功，False 失败
    """
    try:
        import fcntl
    except ImportError:
        # Windows 不支持 fcntl，回退到无锁写入
        fcntl = None

    if event_type not in VALID_TYPES:
        print(f"⚠️ 未知事件类型 {event_type!r}，合法值: {VALID_TYPES}，改用 info", file=sys.stderr)
        event_type = "info"

    if len(text) > 10:
        text = text[:10]

    event = {
        "type": event_type,
        "text": text,
        "timestamp": datetime.now(TZ).isoformat(),
        "ttl": ttl,
    }

    try:
        EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)

        # 读取现有事件（带共享锁）
        events = []
        if EVENTS_FILE.exists():
            try:
                with open(EVENTS_FILE, "r", encoding="utf-8") as f:
                    if fcntl:
                        fcntl.flock(f, fcntl.LOCK_SH)
                    try:
                        events = json.load(f).get("events", [])
                    finally:
                        if fcntl:
                            fcntl.flock(f, fcntl.LOCK_UN)
            except Exception:
                events = []

        events.append(event)

        # 原子写回（带排他锁）
        tmp = EVENTS_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            if fcntl:
                fcntl.flock(f, fcntl.LOCK_EX)
            try:
                json.dump({"events": events}, f, ensure_ascii=False, indent=2)
            finally:
                if fcntl:
                    fcntl.flock(f, fcntl.LOCK_UN)
        tmp.replace(EVENTS_FILE)

        print(f"⚡ 事件已写入: [{event_type}] {text} (ttl={ttl}s)")
        return True

    except Exception as e:
        print(f"❌ 写入事件失败: {e}", file=sys.stderr)
        return False


def _usage():
    print(
        "用法：\n"
        "  python3 prism_event.py <type> <text> [ttl]\n"
        "  type: alert | info | done\n"
        "  ttl:  可选，过期秒数（默认 30）\n"
        "\n"
        "示例：\n"
        "  python3 prism_event.py alert '比亚迪涨停！'\n"
        "  python3 prism_event.py done  '日报已发布'\n"
        "  python3 prism_event.py info  '天气转晴' 60\n"
    )


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        _usage()
        sys.exit(0)

    if len(args) < 2:
        print("❌ 缺少参数", file=sys.stderr)
        _usage()
        sys.exit(1)

    event_type = args[0].lower()
    text = args[1]
    ttl = int(args[2]) if len(args) >= 3 else 30

    ok = trigger_event(event_type, text, ttl)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
