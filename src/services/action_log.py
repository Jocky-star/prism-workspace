#!/usr/bin/env python3
"""
行动日志 — 记录真正执行过的事情

Brief 只汇报 action_log 里有记录的事。没记录 = 没做 = 不汇报。

用法：
  # 记录一次行动
  from src.services.action_log import log_action
  log_action(
      category="proactive",       # delivery / proactive / intent_followup
      title="查了福州机票",
      detail="清明假期直飞，最便宜 ¥420 南航晚班",
      insight="你提了三次想去福州",   # proactive 类才需要
  )

  # 读取今天的行动日志
  from src.services.action_log import get_actions
  actions = get_actions("2026-03-13")

  # CLI
  python3 src/services/action_log.py --log --category proactive --title "查了福州机票" --detail "..."
  python3 src/services/action_log.py --list               # 列出今天的
  python3 src/services/action_log.py --list --date 2026-03-12
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

# 将项目根目录加入路径，使 src.services.config 可导入
_pkg_root = Path(__file__).resolve().parent.parent.parent
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

from src.services.config import MEMORY_DIR

_tz = timezone(timedelta(hours=8))
ACTION_LOG_DIR = MEMORY_DIR / "action_log"


def log_action(
    category: str,
    title: str,
    detail: str = "",
    insight: str = "",
    date: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """记录一次真实执行的行动。
    
    Args:
        category: delivery（帮用户做了什么）/ proactive（主动洞察并行动）/ intent_followup（跟进用户意图）
        title: 简短标题（20 字以内）
        detail: 具体内容/结果
        insight: 洞察（proactive 类用，"我注意到你..."）
        date: 日期，默认今天
        extra: 其他元数据
    """
    if date is None:
        date = datetime.now(_tz).strftime("%Y-%m-%d")
    
    ACTION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = ACTION_LOG_DIR / f"{date}.jsonl"
    
    record = {
        "timestamp": datetime.now(_tz).isoformat(),
        "category": category,
        "title": title,
        "detail": detail,
    }
    if insight:
        record["insight"] = insight
    if extra:
        record.update(extra)
    
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    return record


def get_actions(date: Optional[str] = None) -> List[Dict[str, Any]]:
    """读取指定日期的行动日志。"""
    if date is None:
        date = datetime.now(_tz).strftime("%Y-%m-%d")
    
    log_file = ACTION_LOG_DIR / f"{date}.jsonl"
    if not log_file.exists():
        return []
    
    actions = []
    for line in log_file.read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            try:
                actions.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return actions


def get_actions_summary(date: Optional[str] = None) -> str:
    """生成行动日志的文本摘要，供 Brief 使用。"""
    actions = get_actions(date)
    if not actions:
        return ""
    
    parts = []
    for a in actions:
        cat = a.get("category", "")
        title = a.get("title", "")
        detail = a.get("detail", "")
        insight = a.get("insight", "")
        
        if cat == "proactive" and insight:
            parts.append(f"[主动] {insight} → {title}: {detail}")
        elif cat == "intent_followup":
            parts.append(f"[跟进] {title}: {detail}")
        else:
            parts.append(f"[完成] {title}: {detail}")
    
    return "\n".join(parts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="行动日志")
    parser.add_argument("--log", action="store_true", help="记录一条行动")
    parser.add_argument("--list", action="store_true", help="列出行动日志")
    parser.add_argument("--date", default=None, help="日期 (YYYY-MM-DD)")
    parser.add_argument("--category", default="delivery")
    parser.add_argument("--title", default="")
    parser.add_argument("--detail", default="")
    parser.add_argument("--insight", default="")
    args = parser.parse_args()
    
    if args.log:
        if not args.title:
            print("❌ --title 必填", file=sys.stderr)
            sys.exit(1)
        record = log_action(
            category=args.category,
            title=args.title,
            detail=args.detail,
            insight=args.insight,
            date=args.date,
        )
        print(f"✅ 已记录: {json.dumps(record, ensure_ascii=False)}")
    
    elif args.list:
        actions = get_actions(args.date)
        if not actions:
            print("（无记录）")
        else:
            for a in actions:
                ts = a.get("timestamp", "")[:16]
                cat = a.get("category", "")
                title = a.get("title", "")
                print(f"  [{cat}] {title} ({ts})")
    
    else:
        parser.print_help()
