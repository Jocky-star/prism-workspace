#!/usr/bin/env python3
"""
pi_generate_insights.py — 洞察生成器

从理解层数据中持续产出洞察推送：
  - 模式偏离检测（异常加班/运动缺失/社交异常）
  - 意图跟进提醒（高优 intent 超过7天未跟进）
  - 关系变化提醒（互动频率变化）
  - 周期性总结（每日 brief / 周报触发）

可独立运行也可被 pi_daily_pipeline.py 调用。

用法：
  python3 pi_generate_insights.py           # 生成今日洞察
  python3 pi_generate_insights.py --date 20260312
  python3 pi_generate_insights.py --check-intents   # 只检查意图
  python3 pi_generate_insights.py --check-patterns   # 只检查模式偏离
"""

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

TZ = timezone(timedelta(hours=8))
WORKSPACE = Path(os.path.expanduser("~/.openclaw/workspace"))
INTEL_DIR = WORKSPACE / "memory" / "intelligence"

PROFILE_FILE = INTEL_DIR / "profile.json"
RELATIONSHIPS_FILE = INTEL_DIR / "relationships.json"
PATTERNS_FILE = INTEL_DIR / "patterns.json"
INTENTS_FILE = INTEL_DIR / "intents.json"
CONTEXTS_FILE = INTEL_DIR / "contexts.jsonl"
INSIGHTS_FILE = INTEL_DIR / "insights.jsonl"


def load_json(path, default=None):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default if default is not None else {}


def load_jsonl(path) -> list:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    return records


def get_existing_insight_ids() -> set:
    existing = load_jsonl(INSIGHTS_FILE)
    return {e.get("id") for e in existing}


def append_insight(insight: dict, existing_ids: set) -> bool:
    if insight["id"] in existing_ids:
        return False
    with open(INSIGHTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(insight, ensure_ascii=False) + "\n")
    existing_ids.add(insight["id"])
    return True


def check_stale_intents(existing_ids: set) -> int:
    """Find high-priority intents not followed up in 7+ days.
    
    Only tracks intents with:
    - Explicit type (todo/plan), NOT unknown
    - Seriousness >= 4
    - Text length >= 10 (filter out transcription fragments)
    """
    intents = load_json(INTENTS_FILE, {})
    now = datetime.now(TZ)
    now_str = now.strftime("%Y-%m-%d")
    count = 0

    ACTIONABLE_TYPES = {"todo", "plan"}

    for intent in intents.get("active", []):
        # Only track explicitly typed, high-seriousness intents
        if intent.get("type", "unknown") not in ACTIONABLE_TYPES:
            continue
        if intent.get("seriousness", 0) < 4:
            continue
        # Filter out short transcription fragments
        if len(intent.get("text", "")) < 10:
            continue

        created = intent.get("created_at", "")
        try:
            created_date = date.fromisoformat(created)
            days_old = (now.date() - created_date).days
        except Exception:
            continue

        if days_old < 14:  # raised from 7 to 14 days
            continue

        # Stale high-priority intent
        iid = f"stale_intent_{intent.get('id', '')}_{now_str}"
        added = append_insight({
            "id": iid,
            "date": now_str,
            "type": "intent_stale",
            "priority": 3 if intent.get("seriousness", 0) >= 5 else 2,
            "text": f"意图 {days_old}天未跟进: {intent['text'][:40]}",
            "intent_id": intent.get("id"),
            "pushed": False,
        }, existing_ids)
        if added:
            count += 1

        # Limit to avoid spam
        if count >= 2:
            break

    return count


def check_pattern_deviation(target_date: str, existing_ids: set) -> int:
    """Check if today deviates from established patterns."""
    patterns = load_json(PATTERNS_FILE, {})
    profile = load_json(PROFILE_FILE, {})
    contexts = load_jsonl(CONTEXTS_FILE)

    fmt_date = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:]}"
    today_ctx = [c for c in contexts if c.get("date") == fmt_date and c.get("type") != "narrative"]

    if not today_ctx:
        return 0

    count = 0

    # 1. Late start detection
    starts = []
    for c in today_ctx:
        t = c.get("start", "")
        try:
            h, m = int(t[11:13]), int(t[14:16])
            starts.append(h * 60 + m)
        except Exception:
            pass

    if starts:
        earliest = min(starts)
        median_wake = profile.get("schedule", {}).get("wake_up_median", "09:00")
        try:
            wh, wm = map(int, median_wake.split(":"))
            normal_start = wh * 60 + wm
            if earliest > normal_start + 90:  # 1.5h later than usual
                iid = f"late_start_{target_date}"
                added = append_insight({
                    "id": iid,
                    "date": fmt_date,
                    "type": "anomaly",
                    "priority": 1,
                    "text": f"今天 {earliest//60:02d}:{earliest%60:02d} 才有活动，比平时晚 {(earliest-normal_start)//60}h",
                    "pushed": False,
                }, existing_ids)
                if added:
                    count += 1
        except Exception:
            pass

    # 2. Meeting overload
    meeting_count = sum(1 for c in today_ctx if c.get("activity") == "meeting")
    if meeting_count > 6:
        iid = f"meeting_overload_{target_date}"
        added = append_insight({
            "id": iid,
            "date": fmt_date,
            "type": "anomaly",
            "priority": 2,
            "text": f"今天 {meeting_count} 个会议，密度较高",
            "pushed": False,
        }, existing_ids)
        if added:
            count += 1

    # 3. No break detection
    work_contexts = sorted(
        [c for c in today_ctx if c.get("activity") in ("work", "meeting")],
        key=lambda c: c.get("start", "")
    )
    if len(work_contexts) >= 3:
        max_streak = 0
        current_streak = 0
        prev_end = None
        for c in work_contexts:
            t = c.get("start", "")
            try:
                h, m = int(t[11:13]), int(t[14:16])
                start_min = h * 60 + m
            except Exception:
                continue

            if prev_end is not None and start_min - prev_end < 15:
                current_streak += 1
            else:
                current_streak = 1

            e = c.get("end", "")
            try:
                h, m = int(e[11:13]), int(e[14:16])
                prev_end = h * 60 + m
            except Exception:
                prev_end = start_min + 30

            max_streak = max(max_streak, current_streak)

        if max_streak >= 5:
            iid = f"no_break_{target_date}"
            added = append_insight({
                "id": iid,
                "date": fmt_date,
                "type": "reminder",
                "priority": 2,
                "text": f"连续 {max_streak} 个工作/会议场景无休息",
                "pushed": False,
            }, existing_ids)
            if added:
                count += 1

    return count


def check_relationship_changes(existing_ids: set) -> int:
    """Detect significant changes in relationship patterns."""
    relationships = load_json(RELATIONSHIPS_FILE, {})
    now_str = datetime.now(TZ).strftime("%Y-%m-%d")
    count = 0

    for name, rel in relationships.items():
        stats = rel.get("interaction_stats", {})
        last_seen = stats.get("last_seen", "")
        total = stats.get("total_scenes", 0)

        if total < 10:
            continue

        # Check if frequent contact has gone silent (30+ days)
        if last_seen:
            try:
                last = date.fromisoformat(last_seen) if "-" in last_seen else \
                    date(int(last_seen[:4]), int(last_seen[4:6]), int(last_seen[6:]))
                days_since = (date.today() - last).days
            except Exception:
                continue

            # Frequent contact (>50 scenes) gone silent >30 days
            if total > 50 and days_since > 30:
                iid = f"contact_silent_{name}_{now_str}"
                added = append_insight({
                    "id": iid,
                    "date": now_str,
                    "type": "observation",
                    "priority": 1,
                    "text": f"与{name}已 {days_since}天无交互（之前 {total}次）",
                    "pushed": False,
                }, existing_ids)
                if added:
                    count += 1
                    if count >= 2:
                        break

    return count


def main():
    parser = argparse.ArgumentParser(description="PI 洞察生成器")
    parser.add_argument("--date", help="目标日期 YYYYMMDD")
    parser.add_argument("--check-intents", action="store_true")
    parser.add_argument("--check-patterns", action="store_true")
    parser.add_argument("--check-relationships", action="store_true")
    args = parser.parse_args()

    run_all = not any([args.check_intents, args.check_patterns, args.check_relationships])

    target_date = args.date or datetime.now(TZ).strftime("%Y%m%d")
    existing_ids = get_existing_insight_ids()

    print(f"💡 洞察生成 ({target_date})")
    total = 0

    if run_all or args.check_intents:
        n = check_stale_intents(existing_ids)
        if n:
            print(f"  📋 {n} 条意图提醒")
        total += n

    if run_all or args.check_patterns:
        n = check_pattern_deviation(target_date, existing_ids)
        if n:
            print(f"  📊 {n} 条模式偏离")
        total += n

    if run_all or args.check_relationships:
        n = check_relationship_changes(existing_ids)
        if n:
            print(f"  👥 {n} 条关系变化")
        total += n

    if total > 0:
        print(f"\n✅ 共生成 {total} 条洞察")
    else:
        print("  ✅ 无新洞察")


if __name__ == "__main__":
    main()
