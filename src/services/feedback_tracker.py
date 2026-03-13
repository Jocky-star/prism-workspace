#!/usr/bin/env python3
"""
反馈追踪引擎 — 记录建议与用户反馈，为偏好学习提供数据基础。

用法：
  # 记录一条建议
  from src.services.feedback_tracker import log_suggestion
  sid = log_suggestion(
      category="travel",
      content="你提了三次想去福州 → 帮你查了直飞航班，最便宜 ¥420",
      options=["帮你锁航班", "再等等", "不去了"],
  )

  # 记录用户反馈
  from src.services.feedback_tracker import log_feedback
  log_feedback(sid, "adopted", "帮我锁航班")

  # 查看偏好统计
  from src.services.feedback_tracker import get_preference_stats
  stats = get_preference_stats()

  # CLI
  python3 src/services/feedback_tracker.py --log-suggestion --category travel --content "想去福州" --options "帮你锁,再等等,不去"
  python3 src/services/feedback_tracker.py --log-feedback --id <uuid> --type adopted --response "帮我锁"
  python3 src/services/feedback_tracker.py --stats
  python3 src/services/feedback_tracker.py --history --days 7
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

_tz = timezone(timedelta(hours=8))

FEEDBACK_DIR = Path(__file__).resolve().parent.parent.parent / "memory" / "feedback"
SUGGESTIONS_FILE = FEEDBACK_DIR / "suggestions.jsonl"
RESPONSES_FILE = FEEDBACK_DIR / "responses.jsonl"

FEEDBACK_TYPES = {"adopted", "follow_up", "ignored", "rejected"}
VALID_STATUSES = {"pending", "adopted", "rejected", "ignored", "follow_up"}


def _now_iso() -> str:
    return datetime.now(_tz).isoformat()


def _ensure_dirs() -> None:
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    """读取 JSONL 文件，容错处理损坏行。"""
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    """追加一条记录到 JSONL 文件。"""
    _ensure_dirs()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _update_suggestion_status(
    suggestion_id: str,
    status: str,
    feedback_at: str,
    user_response: Optional[str],
) -> bool:
    """更新 suggestions.jsonl 中指定记录的状态（重写文件）。"""
    records = _read_jsonl(SUGGESTIONS_FILE)
    updated = False
    for r in records:
        if r.get("id") == suggestion_id:
            r["status"] = status
            r["feedback_at"] = feedback_at
            r["user_response"] = user_response
            updated = True
            break
    if updated:
        _ensure_dirs()
        with open(SUGGESTIONS_FILE, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return updated


# ── 公开 API ────────────────────────────────────────────────────────────────


def log_suggestion(
    category: str,
    content: str,
    options: Optional[List[str]] = None,
    suggestion_id: Optional[str] = None,
) -> str:
    """记录一条建议（proactive/recommendation）。

    Args:
        category: 建议类别，如 travel/food/health/work/entertainment
        content:  建议的完整文本（包含洞察 + 行动 + 选项前缀）
        options:  供用户选择的选项列表，如 ["帮你预定", "看看别的", "不用了"]
        suggestion_id: 可手动指定 ID，默认自动生成 UUID

    Returns:
        suggestion_id (str)
    """
    sid = suggestion_id or str(uuid.uuid4())
    record: Dict[str, Any] = {
        "id": sid,
        "timestamp": _now_iso(),
        "category": category,
        "content": content,
        "options": options or [],
        "status": "pending",
        "feedback_at": None,
        "user_response": None,
    }
    _append_jsonl(SUGGESTIONS_FILE, record)
    return sid


def log_feedback(
    suggestion_id: str,
    feedback_type: str,
    user_response: Optional[str] = None,
) -> Dict[str, Any]:
    """记录用户对某条建议的反馈。

    Args:
        suggestion_id: log_suggestion 返回的 ID
        feedback_type: adopted / follow_up / ignored / rejected
        user_response: 用户的具体回复文本（可选）

    Returns:
        反馈记录 dict
    """
    if feedback_type not in FEEDBACK_TYPES:
        raise ValueError(f"feedback_type 必须是 {FEEDBACK_TYPES}，实际收到: {feedback_type!r}")

    now = _now_iso()
    response_record: Dict[str, Any] = {
        "suggestion_id": suggestion_id,
        "timestamp": now,
        "feedback_type": feedback_type,
        "user_response": user_response,
    }
    _append_jsonl(RESPONSES_FILE, response_record)

    # 同步更新 suggestions 里的状态
    _update_suggestion_status(
        suggestion_id=suggestion_id,
        status=feedback_type,
        feedback_at=now,
        user_response=user_response,
    )

    return response_record


def get_preference_stats() -> Dict[str, Any]:
    """统计各类建议的采纳率。

    Returns:
        {
          "total_suggestions": int,
          "total_feedbacks": int,
          "overall_adoption_rate": float,
          "category_stats": {
            "travel": {"suggested": N, "adopted": N, "rate": float}
          }
        }
    """
    suggestions = _read_jsonl(SUGGESTIONS_FILE)
    responses = _read_jsonl(RESPONSES_FILE)

    total = len(suggestions)
    total_fb = len(responses)

    category_map: Dict[str, Dict[str, int]] = {}
    for s in suggestions:
        cat = s.get("category", "unknown")
        if cat not in category_map:
            category_map[cat] = {"suggested": 0, "adopted": 0}
        category_map[cat]["suggested"] += 1
        if s.get("status") == "adopted":
            category_map[cat]["adopted"] += 1

    category_stats: Dict[str, Any] = {}
    for cat, vals in category_map.items():
        suggested = vals["suggested"]
        adopted = vals["adopted"]
        rate = round(adopted / suggested, 3) if suggested > 0 else 0.0
        category_stats[cat] = {
            "suggested": suggested,
            "adopted": adopted,
            "rate": rate,
        }

    total_adopted = sum(1 for s in suggestions if s.get("status") == "adopted")
    overall_rate = round(total_adopted / total, 3) if total > 0 else 0.0

    return {
        "total_suggestions": total,
        "total_feedbacks": total_fb,
        "overall_adoption_rate": overall_rate,
        "category_stats": category_stats,
    }


def get_suggestion_history(days: int = 30) -> List[Dict[str, Any]]:
    """查看最近 N 天的历史建议 + 反馈。

    Args:
        days: 往前看多少天，默认 30

    Returns:
        建议列表，每条附带对应的反馈记录
    """
    cutoff = datetime.now(_tz) - timedelta(days=days)
    suggestions = _read_jsonl(SUGGESTIONS_FILE)
    responses = _read_jsonl(RESPONSES_FILE)

    # 构建 suggestion_id → responses 索引
    resp_index: Dict[str, List[Dict[str, Any]]] = {}
    for r in responses:
        sid = r.get("suggestion_id", "")
        resp_index.setdefault(sid, []).append(r)

    result: List[Dict[str, Any]] = []
    for s in suggestions:
        ts_str = s.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=_tz)
        except ValueError:
            continue
        if ts < cutoff:
            continue
        entry = dict(s)
        entry["feedbacks"] = resp_index.get(s.get("id", ""), [])
        result.append(entry)

    return sorted(result, key=lambda x: x.get("timestamp", ""), reverse=True)


# ── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="反馈追踪引擎")
    sub = parser.add_subparsers(dest="cmd")

    # log-suggestion
    p_sug = sub.add_parser("log-suggestion", help="记录一条建议")
    p_sug.add_argument("--category", required=True, help="类别 (travel/food/health/...)")
    p_sug.add_argument("--content", required=True, help="建议内容")
    p_sug.add_argument(
        "--options", default="", help="选项（逗号分隔），如 '帮你预定,再等等,不用了'"
    )
    p_sug.add_argument("--id", dest="suggestion_id", default=None, help="手动指定 ID")

    # log-feedback
    p_fb = sub.add_parser("log-feedback", help="记录用户反馈")
    p_fb.add_argument("--id", dest="suggestion_id", required=True, help="建议 ID")
    p_fb.add_argument(
        "--type",
        dest="feedback_type",
        required=True,
        choices=list(FEEDBACK_TYPES),
        help="反馈类型",
    )
    p_fb.add_argument("--response", default=None, help="用户回复文本")

    # stats
    sub.add_parser("stats", help="查看偏好统计")

    # history
    p_hist = sub.add_parser("history", help="查看历史建议")
    p_hist.add_argument("--days", type=int, default=30, help="往前几天")

    args = parser.parse_args()

    if args.cmd == "log-suggestion":
        options = [o.strip() for o in args.options.split(",") if o.strip()] if args.options else []
        sid = log_suggestion(
            category=args.category,
            content=args.content,
            options=options,
            suggestion_id=getattr(args, "suggestion_id", None),
        )
        print(f"✅ 已记录建议 ID: {sid}")

    elif args.cmd == "log-feedback":
        record = log_feedback(
            suggestion_id=args.suggestion_id,
            feedback_type=args.feedback_type,
            user_response=args.response,
        )
        print(f"✅ 已记录反馈: {json.dumps(record, ensure_ascii=False)}")

    elif args.cmd == "stats":
        stats = get_preference_stats()
        print(json.dumps(stats, ensure_ascii=False, indent=2))

    elif args.cmd == "history":
        history = get_suggestion_history(days=args.days)
        if not history:
            print("（无记录）")
        else:
            for entry in history:
                ts = entry.get("timestamp", "")[:16]
                cat = entry.get("category", "")
                status = entry.get("status", "")
                content = entry.get("content", "")[:50]
                fbs = entry.get("feedbacks", [])
                print(f"  [{status}] [{cat}] {content}... ({ts}) — {len(fbs)} 条反馈")

    else:
        parser.print_help()
