#!/usr/bin/env python3
"""
pi_understand.py — 个人智能理解系统·理解层

从感知层存储中聚合统计，生成：
  - profile.json    用户画像
  - relationships.json  社交图谱
  - patterns.json   行为模式

用法：
  python3 pi_understand.py              # 全量重算
  python3 pi_understand.py --stats      # 打印摘要
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from statistics import median

TZ = timezone(timedelta(hours=8))
WORKSPACE = Path(os.environ.get(
    "WORKSPACE",
    os.environ.get(
        "OPENCLAW_WORKSPACE",
        os.path.expanduser("~/.openclaw/workspace")
    )
))
INTEL_DIR = WORKSPACE / "memory" / "intelligence"

ENTITIES_FILE = INTEL_DIR / "entities.json"
EVENTS_FILE = INTEL_DIR / "events.jsonl"
INTENTS_FILE = INTEL_DIR / "intents.json"
CONTEXTS_FILE = INTEL_DIR / "contexts.jsonl"
PROFILE_FILE = INTEL_DIR / "profile.json"
RELATIONSHIPS_FILE = INTEL_DIR / "relationships.json"
PATTERNS_FILE = INTEL_DIR / "patterns.json"


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


def atomic_write_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def parse_time(t: str) -> datetime | None:
    """Parse ISO-ish time string to datetime."""
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(t, fmt)
        except ValueError:
            continue
    # Try with timezone offset
    try:
        return datetime.fromisoformat(t)
    except Exception:
        return None


def time_to_minutes(t: str) -> int | None:
    """Extract hour*60+minute from time string."""
    dt = parse_time(t)
    if dt:
        return dt.hour * 60 + dt.minute
    return None


def hour_bucket(minutes: int) -> str:
    """Convert minutes since midnight to 2-hour bucket string."""
    h = minutes // 60
    bucket_start = (h // 2) * 2
    bucket_end = bucket_start + 2
    return f"{bucket_start:02d}-{bucket_end:02d}"


def date_to_weekday(date_str: str) -> int:
    """Return weekday (0=Mon) from YYYY-MM-DD string."""
    try:
        return date.fromisoformat(date_str).weekday()
    except Exception:
        return 0


def is_recent(date_str: str, days: int) -> bool:
    """Check if date is within last N days."""
    try:
        d = date.fromisoformat(date_str)
        return (date.today() - d).days <= days
    except Exception:
        return False


# ── 用户画像引擎 ──────────────────────────────────────────

def build_profile(entities: dict, events: list, intents: dict, contexts: list) -> dict:
    profile = {
        "identity": {"inferred_name": None, "occupation": None, "confidence": 0},
        "schedule": {},
        "preferences": {"top_topics": [], "values": [], "communication_style": None},
        "health": {"exercise_freq_weekly": None, "known_issues": []},
        "activity_distribution": {},
        "active_projects": [],
        "updated_at": datetime.now(TZ).isoformat(),
        "version": 1,
    }

    # Identity: find user's aliases
    people = entities.get("people", {})
    for name, data in people.items():
        if name == "用户" or data.get("id", "").startswith("global_p") and "用户" in data.get("aliases", []):
            aliases = data.get("aliases", [])
            real_names = [a for a in aliases if a not in ("我", "本人", "用户") and len(a) >= 2]
            if real_names:
                profile["identity"]["inferred_name"] = real_names[0]
            break

    # Schedule from contexts
    scene_contexts = [c for c in contexts if c.get("type") != "narrative"]

    # Group by date
    by_date = defaultdict(list)
    for c in scene_contexts:
        by_date[c.get("date", "")].append(c)

    wake_times = []
    sleep_times = []
    commute_starts = []
    work_hours_per_day = []

    for d, day_contexts in by_date.items():
        times = []
        for c in day_contexts:
            m = time_to_minutes(c.get("start", ""))
            if m is not None:
                times.append(m)
        if times:
            wake_times.append(min(times))
            sleep_times.append(max(times))

        # Commute
        commute_times = [time_to_minutes(c["start"]) for c in day_contexts
                        if c.get("activity") == "commute" and time_to_minutes(c.get("start", "")) is not None]
        if commute_times:
            commute_starts.append(min(commute_times))

        # Work hours
        work_mins = 0
        for c in day_contexts:
            if c.get("activity") == "work":
                s = time_to_minutes(c.get("start", ""))
                e = time_to_minutes(c.get("end", ""))
                if s is not None and e is not None and e > s:
                    work_mins += (e - s)
        if work_mins > 0:
            work_hours_per_day.append(work_mins / 60.0)

    if wake_times:
        med = int(median(wake_times))
        profile["schedule"]["wake_up_median"] = f"{med // 60:02d}:{med % 60:02d}"
    if sleep_times:
        med = int(median(sleep_times))
        profile["schedule"]["sleep_median"] = f"{med // 60:02d}:{med % 60:02d}"
    if commute_starts:
        med = int(median(commute_starts))
        profile["schedule"]["commute_start_median"] = f"{med // 60:02d}:{med % 60:02d}"
    if work_hours_per_day:
        profile["schedule"]["work_hours_avg"] = round(sum(work_hours_per_day) / len(work_hours_per_day), 1)

    # Activity distribution (hours)
    act_minutes = Counter()
    for c in scene_contexts:
        act = c.get("activity", "")
        if not act:
            continue
        s = time_to_minutes(c.get("start", ""))
        e = time_to_minutes(c.get("end", ""))
        if s is not None and e is not None and e > s:
            act_minutes[act] += (e - s)
    profile["activity_distribution"] = {
        k: round(v / 60.0, 1) for k, v in act_minutes.most_common(15)
    }

    # Top topics from events (narrative type has highest quality key_topics)
    # Also pull from entities.json topics category (projects_or_topics)
    SCENE_NOISE = re.compile(
        r"(环境|室内|室外|安静|嘈杂|噪音|噪声|户外|空间|场所|氛围|"
        r"金属碰撞|嗡嗡|静默|静止|休息|案头工作|无语音|驾车|通勤|"
        r"整理物品|收拾|等待|夜间|睡眠|起床|离开|未知活动|独立工作|"
        r"低频|声音|碰撞声|嘈杂声)"
    )
    topic_counter = Counter()
    for e in events:
        if e.get("type") == "narrative":
            for t in e.get("topics", []):
                if t and not SCENE_NOISE.search(t):
                    topic_counter[t] += 1
    # Also gather from entities topics category
    for tname in entities.get("topics", {}):
        if tname.startswith("_"):
            continue
        if not SCENE_NOISE.search(tname):
            topic_counter[tname] += 1
    profile["preferences"]["top_topics"] = [t for t, _ in topic_counter.most_common(10)]

    # Health: exercise frequency
    exercise_days = set()
    for c in scene_contexts:
        if c.get("activity") == "exercise":
            exercise_days.add(c.get("date", ""))
    total_days = len(by_date)
    if total_days > 0:
        weeks = max(1, total_days / 7.0)
        profile["health"]["exercise_freq_weekly"] = round(len(exercise_days) / weeks, 1)

    # Active projects from intents
    active_intents = intents.get("active", [])
    project_topics = Counter()
    for intent in active_intents:
        text = intent.get("text", "")
        if len(text) > 5:
            project_topics[text[:20]] += 1
    profile["active_projects"] = [t for t, _ in project_topics.most_common(5)]

    return profile


# ── 关系图谱引擎 ──────────────────────────────────────────

def build_relationships(entities: dict, contexts: list) -> dict:
    relationships = {}
    people = entities.get("people", {})

    for name, data in people.items():
        if name.startswith("_") or name == "用户":
            continue

        interactions = data.get("interactions", {})
        if not interactions:
            continue

        total_scenes = 0
        total_minutes = 0
        first_seen = None
        last_seen = None
        topic_counter = Counter()
        activity_counter = Counter()
        recent_7d = 0
        recent_30d = 0

        for day, day_data in interactions.items():
            scenes = day_data.get("scenes", 0)
            minutes = day_data.get("minutes", 0)
            total_scenes += scenes
            total_minutes += minutes

            if first_seen is None or day < first_seen:
                first_seen = day
            if last_seen is None or day > last_seen:
                last_seen = day

            for t in day_data.get("topics", []):
                topic_counter[t] += 1
            for a in day_data.get("activities", []):
                activity_counter[a] += 1

            if is_recent(day, 7):
                recent_7d += scenes
            if is_recent(day, 30):
                recent_30d += scenes

        # Relationship type inference (rules)
        rel_type = "unknown"
        rel_confidence = 0.0

        # Check aliases for family indicators
        aliases = data.get("aliases", [])
        name_lower = name.lower()
        # "哥"/"姐" at end of name are often honorifics (e.g. 超哥, 小姐), not family markers
        # Only keep unambiguous family words
        family_keywords = ["妈", "爸", "老婆", "老公", "媳妇", "母亲", "父亲", "妻子", "丈夫"]
        if any(kw in name_lower or any(kw in a for a in aliases) for kw in family_keywords):
            rel_type = "family"
            rel_confidence = 0.9
        elif total_scenes >= 3:
            work_ratio = activity_counter.get("work", 0) + activity_counter.get("meeting", 0)
            social_ratio = activity_counter.get("meal", 0) + activity_counter.get("social", 0) + activity_counter.get("entertainment", 0)
            total_acts = sum(activity_counter.values()) or 1

            if (work_ratio / total_acts) > 0.7:
                rel_type = "colleague"
                rel_confidence = 0.7
            elif (social_ratio / total_acts) > 0.5:
                rel_type = "friend"
                rel_confidence = 0.6
            else:
                rel_type = "acquaintance"
                rel_confidence = 0.4

        # Trend
        trend = "stable"
        if recent_30d > 0:
            avg_per_week = total_scenes / max(1, len(interactions)) * 7
            recent_per_week = recent_7d
            if recent_per_week > avg_per_week * 1.5:
                trend = "growing"
            elif recent_per_week < avg_per_week * 0.3 and recent_7d == 0:
                trend = "declining"

        relationships[name] = {
            "type": rel_type,
            "type_confidence": rel_confidence,
            "interaction_stats": {
                "total_scenes": total_scenes,
                "total_minutes": round(total_minutes, 1),
                "first_seen": first_seen,
                "last_seen": last_seen,
                "last_7d_scenes": recent_7d,
                "last_30d_scenes": recent_30d,
            },
            "top_topics": [t for t, _ in topic_counter.most_common(5)],
            "co_activities": dict(activity_counter.most_common(10)),
            "trend": trend,
        }

    return relationships


# ── 模式识别引擎 ──────────────────────────────────────────

def build_patterns(contexts: list) -> dict:
    scene_contexts = [c for c in contexts if c.get("type") != "narrative"]

    # Daily routine by weekday/weekend
    weekday_buckets = defaultdict(lambda: Counter())
    weekend_buckets = defaultdict(lambda: Counter())
    weekday_minutes = defaultdict(lambda: defaultdict(float))
    weekend_minutes = defaultdict(lambda: defaultdict(float))

    by_date = defaultdict(list)
    for c in scene_contexts:
        by_date[c.get("date", "")].append(c)

    for d, day_contexts in by_date.items():
        wd = date_to_weekday(d)
        is_weekend = wd >= 5

        for c in day_contexts:
            s = time_to_minutes(c.get("start", ""))
            e = time_to_minutes(c.get("end", ""))
            act = c.get("activity", "")
            if s is None or not act:
                continue
            bucket = hour_bucket(s)
            if is_weekend:
                weekend_buckets[bucket][act] += 1
                if e is not None and e > s:
                    weekend_minutes[bucket][act] += (e - s)
            else:
                weekday_buckets[bucket][act] += 1
                if e is not None and e > s:
                    weekday_minutes[bucket][act] += (e - s)

    def format_routine(buckets, minutes_data):
        result = {}
        for bucket in sorted(buckets.keys()):
            top_act = buckets[bucket].most_common(1)
            if top_act:
                act_name = top_act[0][0]
                total_mins = minutes_data[bucket].get(act_name, 0)
                count = buckets[bucket][act_name]
                result[bucket] = {
                    "top_activity": act_name,
                    "avg_minutes": round(total_mins / max(1, count), 0),
                }
        return result

    # Weekly patterns
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    overtime_counter = Counter()
    exercise_counter = Counter()
    social_counter = Counter()

    for d, day_contexts in by_date.items():
        wd = date_to_weekday(d)
        work_mins = sum(
            max(0, (time_to_minutes(c.get("end", "")) or 0) - (time_to_minutes(c.get("start", "")) or 0))
            for c in day_contexts if c.get("activity") == "work"
        )
        if work_mins > 600:  # > 10 hours
            overtime_counter[weekday_names[wd]] += 1

        if any(c.get("activity") == "exercise" for c in day_contexts):
            exercise_counter[weekday_names[wd]] += 1

        social_mins = sum(
            max(0, (time_to_minutes(c.get("end", "")) or 0) - (time_to_minutes(c.get("start", "")) or 0))
            for c in day_contexts if c.get("activity") in ("social", "meal", "entertainment")
        )
        if social_mins > 60:
            social_counter[weekday_names[wd]] += 1

    # Anomaly detection (recent 14 days)
    anomalies = []
    recent_work = []
    for d, day_contexts in by_date.items():
        if not is_recent(d, 30):
            continue
        work_mins = sum(
            max(0, (time_to_minutes(c.get("end", "")) or 0) - (time_to_minutes(c.get("start", "")) or 0))
            for c in day_contexts if c.get("activity") == "work"
        )
        recent_work.append((d, work_mins))

    if len(recent_work) >= 7:
        work_values = [w for _, w in recent_work]
        avg_work = sum(work_values) / len(work_values)
        for d, w in recent_work[-7:]:
            if w > avg_work * 1.5 and w > 480:
                anomalies.append({
                    "date": d,
                    "type": "overtime",
                    "detail": f"工作 {w/60:.1f}h，均值 {avg_work/60:.1f}h"
                })

    return {
        "daily_routine": {
            "weekday": format_routine(weekday_buckets, weekday_minutes),
            "weekend": format_routine(weekend_buckets, weekend_minutes),
        },
        "weekly_patterns": {
            "overtime_days": [d for d, _ in overtime_counter.most_common(3)] if overtime_counter else [],
            "exercise_days": [d for d, _ in exercise_counter.most_common(3)] if exercise_counter else [],
            "social_peak_day": social_counter.most_common(1)[0][0] if social_counter else None,
        },
        "anomalies_recent": anomalies[-10:],
        "decision_style": {"fast_contexts": [], "slow_contexts": []},
        "updated_at": datetime.now(TZ).isoformat(),
    }


# ── 打印摘要 ──────────────────────────────────────────────

def print_stats():
    profile = load_json(PROFILE_FILE, {})
    rels = load_json(RELATIONSHIPS_FILE, {})
    patterns = load_json(PATTERNS_FILE, {})

    print("\n📊 理解层摘要")
    print("\n── 用户画像 ──")
    sched = profile.get("schedule", {})
    print(f"  起床: {sched.get('wake_up_median', '?')} / 就寝: {sched.get('sleep_median', '?')}")
    print(f"  通勤: {sched.get('commute_start_median', '?')} / 日均工作: {sched.get('work_hours_avg', '?')}h")
    print(f"  运动频率: {profile.get('health', {}).get('exercise_freq_weekly', '?')} 次/周")
    topics = profile.get("preferences", {}).get("top_topics", [])
    if topics:
        print(f"  高频话题: {', '.join(topics[:5])}")
    dist = profile.get("activity_distribution", {})
    if dist:
        top3 = list(dist.items())[:3]
        print(f"  活动分布: {', '.join(f'{k}={v}h' for k, v in top3)}")

    print(f"\n── 社交图谱 ({len(rels)} 人) ──")
    for name, r in sorted(rels.items(), key=lambda x: -x[1]["interaction_stats"]["total_scenes"])[:8]:
        stats = r["interaction_stats"]
        print(f"  {name}: {r['type']}({r['type_confidence']:.1f}) "
              f"| {stats['total_scenes']}次 {stats['total_minutes']:.0f}min "
              f"| 趋势:{r['trend']}")

    print(f"\n── 行为模式 ──")
    wp = patterns.get("weekly_patterns", {})
    if wp.get("overtime_days"):
        print(f"  加班高发: {', '.join(wp['overtime_days'])}")
    if wp.get("exercise_days"):
        print(f"  运动日: {', '.join(wp['exercise_days'])}")
    if wp.get("social_peak_day"):
        print(f"  社交高峰: {wp['social_peak_day']}")
    anomalies = patterns.get("anomalies_recent", [])
    if anomalies:
        print(f"  近期异常: {len(anomalies)} 条")
        for a in anomalies[-3:]:
            print(f"    {a['date']} {a['type']}: {a['detail']}")


# ── 主流程 ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="PI 理解层")
    parser.add_argument("--stats", action="store_true", help="打印摘要")
    args = parser.parse_args()

    if args.stats:
        print_stats()
        return

    print("🧠 理解层：加载感知数据...")
    entities = load_json(ENTITIES_FILE, {})
    events = load_jsonl(EVENTS_FILE)
    intents = load_json(INTENTS_FILE, {})
    contexts = load_jsonl(CONTEXTS_FILE)

    if not events and not contexts:
        print("⚠️ 感知层数据为空，请先运行 pi_perception.py")
        return

    print(f"  加载完成: {len(events)} events, {len(contexts)} contexts")

    print("  构建用户画像...")
    profile = build_profile(entities, events, intents, contexts)
    atomic_write_json(PROFILE_FILE, profile)

    print("  构建社交图谱...")
    relationships = build_relationships(entities, contexts)
    atomic_write_json(RELATIONSHIPS_FILE, relationships)

    print("  构建行为模式...")
    patterns = build_patterns(contexts)
    atomic_write_json(PATTERNS_FILE, patterns)

    print("\n✅ 理解层完成")
    print_stats()

    # ── 写入 action_log ───────────────────────────────────
    try:
        from src.services.action_log import log_action as _log_action
        _log_action(
            "pipeline",
            "理解层分析完成",
            "用户画像、社交图谱、行为模式已更新",
            source="understand",
        )
    except Exception as _e:
        print(f"  ⚠️ action_log 写入失败: {_e}", file=sys.stderr)
    # ─────────────────────────────────────────────────────


if __name__ == "__main__":
    main()
