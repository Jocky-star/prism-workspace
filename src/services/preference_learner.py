#!/usr/bin/env python3
"""
偏好学习引擎 — 基于反馈历史分析用户偏好，生成建议策略。

用法：
  # 分析偏好并保存模型
  from src.services.preference_learner import analyze_preferences
  model = analyze_preferences()

  # 获取当前建议策略
  from src.services.preference_learner import get_suggestion_strategy
  strategy = get_suggestion_strategy()

  # 判断某类建议现在该不该发
  from src.services.preference_learner import should_suggest
  if should_suggest("travel"):
      print("可以发旅行建议")

  # CLI
  python3 src/services/preference_learner.py --analyze
  python3 src/services/preference_learner.py --strategy
  python3 src/services/preference_learner.py --check --category travel
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

_tz = timezone(timedelta(hours=8))

FEEDBACK_DIR = Path(__file__).resolve().parent.parent.parent / "memory" / "feedback"
PREFERENCE_MODEL_FILE = FEEDBACK_DIR / "preference_model.json"

# 建议策略调参常数
HIGH_ADOPTION_THRESHOLD = 0.5      # 采纳率 ≥ 这个 → preferred
LOW_ADOPTION_THRESHOLD = 0.2       # 采纳率 < 这个 → deprioritized
MIN_SAMPLES_FOR_JUDGMENT = 3       # 至少这么多样本才做判断
DEFAULT_MAX_DAILY = 3              # 默认每天最多几条建议
MAX_DAILY_SUGGESTIONS_CEILING = 5  # 上限


def _now_iso() -> str:
    return datetime.now(_tz).isoformat()


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


def _load_suggestions() -> List[Dict[str, Any]]:
    return _read_jsonl(FEEDBACK_DIR / "suggestions.jsonl")


def _load_responses() -> List[Dict[str, Any]]:
    return _read_jsonl(FEEDBACK_DIR / "responses.jsonl")


def _load_model() -> Dict[str, Any]:
    """加载已有偏好模型，若不存在返回空模型。"""
    if PREFERENCE_MODEL_FILE.exists():
        try:
            return json.loads(PREFERENCE_MODEL_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_model(model: Dict[str, Any]) -> None:
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    PREFERENCE_MODEL_FILE.write_text(
        json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── 时间段分析辅助 ────────────────────────────────────────────────────────────


def _hour_block(ts_str: str) -> str:
    """把 ISO 时间戳分成 morning/afternoon/evening/night 四段。"""
    try:
        ts = datetime.fromisoformat(ts_str)
    except ValueError:
        return "unknown"
    h = ts.hour
    if 6 <= h < 12:
        return "morning"
    elif 12 <= h < 18:
        return "afternoon"
    elif 18 <= h < 23:
        return "evening"
    else:
        return "night"


# ── 核心功能 ─────────────────────────────────────────────────────────────────


def analyze_preferences() -> Dict[str, Any]:
    """基于反馈历史分析用户偏好，更新并保存偏好模型。

    分析维度：
    - 各类别采纳率
    - 什么时间段用户更愿意互动
    - 什么类型的建议命中率高

    Returns:
        偏好模型 dict，格式与 preference_model.json 一致
    """
    suggestions = _load_suggestions()
    responses = _load_responses()

    total_sug = len(suggestions)
    total_fb = len(responses)

    # ── 1. 各类别统计 ──────────────────────────────────────────────────────
    category_raw: Dict[str, Dict[str, int]] = defaultdict(lambda: {"suggested": 0, "adopted": 0, "follow_up": 0, "rejected": 0, "ignored": 0})
    for s in suggestions:
        cat = s.get("category", "unknown")
        status = s.get("status", "pending")
        category_raw[cat]["suggested"] += 1
        if status in ("adopted", "rejected", "ignored", "follow_up"):
            category_raw[cat][status] += 1

    category_stats: Dict[str, Any] = {}
    for cat, vals in category_raw.items():
        n = vals["suggested"]
        adopted = vals["adopted"]
        rate = round(adopted / n, 3) if n > 0 else 0.0
        category_stats[cat] = {
            "suggested": n,
            "adopted": adopted,
            "rate": rate,
        }

    # ── 2. 时间段分析（看什么时候用户愿意反馈） ───────────────────────────
    time_block_adoption: Dict[str, Dict[str, int]] = defaultdict(lambda: {"count": 0, "adopted": 0})
    for s in suggestions:
        block = _hour_block(s.get("timestamp", ""))
        status = s.get("status", "pending")
        time_block_adoption[block]["count"] += 1
        if status == "adopted":
            time_block_adoption[block]["adopted"] += 1

    time_stats: Dict[str, Any] = {}
    for block, vals in time_block_adoption.items():
        n = vals["count"]
        adopted = vals["adopted"]
        time_stats[block] = {
            "count": n,
            "adopted": adopted,
            "rate": round(adopted / n, 3) if n > 0 else 0.0,
        }

    # ── 3. 整体采纳率 ──────────────────────────────────────────────────────
    total_adopted = sum(1 for s in suggestions if s.get("status") == "adopted")
    overall_rate = round(total_adopted / total_sug, 3) if total_sug > 0 else 0.0

    # ── 4. 建议策略生成 ────────────────────────────────────────────────────
    preferred: List[str] = []
    deprioritized: List[str] = []
    notes_parts: List[str] = []

    for cat, stats in category_stats.items():
        n = stats["suggested"]
        rate = stats["rate"]
        if n < MIN_SAMPLES_FOR_JUDGMENT:
            continue
        if rate >= HIGH_ADOPTION_THRESHOLD:
            preferred.append(cat)
        elif rate < LOW_ADOPTION_THRESHOLD:
            deprioritized.append(cat)
            notes_parts.append(f"用户对「{cat}」建议采纳率低（{rate:.0%}），减少频率")

    # 最佳推送时间段
    best_block = max(time_stats, key=lambda b: time_stats[b].get("rate", 0), default=None)
    if best_block and time_stats.get(best_block, {}).get("count", 0) >= MIN_SAMPLES_FOR_JUDGMENT:
        notes_parts.append(f"用户在「{best_block}」时段对建议更感兴趣")

    # 每天条数：采纳率高 → 可以多发，低 → 保守
    if overall_rate >= 0.5:
        max_daily = min(DEFAULT_MAX_DAILY + 1, MAX_DAILY_SUGGESTIONS_CEILING)
    elif overall_rate < 0.2 and total_sug >= MIN_SAMPLES_FOR_JUDGMENT:
        max_daily = max(DEFAULT_MAX_DAILY - 1, 1)
    else:
        max_daily = DEFAULT_MAX_DAILY

    strategy: Dict[str, Any] = {
        "max_daily_suggestions": max_daily,
        "preferred_categories": preferred,
        "deprioritized_categories": deprioritized,
        "best_time_blocks": (
            [best_block] if best_block and time_stats.get(best_block, {}).get("count", 0) >= MIN_SAMPLES_FOR_JUDGMENT else []
        ),
        "notes": "；".join(notes_parts) if notes_parts else "暂无足够数据生成个性化策略",
    }

    model: Dict[str, Any] = {
        "updated_at": _now_iso(),
        "total_suggestions": total_sug,
        "total_feedbacks": total_fb,
        "category_stats": category_stats,
        "time_stats": time_stats,
        "overall_adoption_rate": overall_rate,
        "strategy": strategy,
    }

    _save_model(model)
    return model


def get_suggestion_strategy() -> Dict[str, Any]:
    """返回当前建议策略。如果模型不存在，先分析一次再返回。

    Returns:
        strategy dict，包含 max_daily_suggestions / preferred_categories /
        deprioritized_categories / notes
    """
    model = _load_model()
    if not model:
        model = analyze_preferences()
    return model.get("strategy", {})


def should_suggest(category: str) -> bool:
    """判断某类建议现在该不该发。

    规则：
    1. 在 deprioritized_categories 中 → False
    2. 在 preferred_categories 中 → True（优先级高）
    3. 其他 → True（默认允许，保守策略）

    Args:
        category: 建议类别

    Returns:
        bool
    """
    strategy = get_suggestion_strategy()
    if category in strategy.get("deprioritized_categories", []):
        return False
    return True


# ── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="偏好学习引擎")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("analyze", help="分析偏好并更新模型")
    sub.add_parser("strategy", help="查看当前建议策略")

    p_check = sub.add_parser("check", help="判断某类建议是否应该发")
    p_check.add_argument("--category", required=True, help="类别")

    args = parser.parse_args()

    if args.cmd == "analyze":
        model = analyze_preferences()
        print(json.dumps(model, ensure_ascii=False, indent=2))
        print(f"\n✅ 模型已保存到 {PREFERENCE_MODEL_FILE}")

    elif args.cmd == "strategy":
        strategy = get_suggestion_strategy()
        print(json.dumps(strategy, ensure_ascii=False, indent=2))

    elif args.cmd == "check":
        result = should_suggest(args.category)
        icon = "✅" if result else "🚫"
        print(f"{icon} category={args.category!r} → should_suggest={result}")

    else:
        parser.print_help()
