#!/usr/bin/env python3
"""
pi_action.py — 个人智能理解系统·行动层

基于洞察和意图，自主执行有价值的行动：
  - 信息搜集（用户提到想去某地 → 查机票天气）
  - 主动提醒（意图超期 → 推送提醒）
  - 环境编排（模式偏离 → Prism/米家联动）
  - 内容推荐（匹配用户兴趣的新闻/工具）

行动分级：
  L0 无声：写日志，不打扰（默认）
  L1 轻触：Prism 闪屏
  L2 推送：飞书消息
  L3 主动：执行具体任务（搜索、文件操作等）

用法：
  python3 pi_action.py                 # 检查并执行待处理行动
  python3 pi_action.py --plan          # 只生成行动计划，不执行
  python3 pi_action.py --execute <id>  # 执行指定行动
  python3 pi_action.py --stats         # 查看行动历史
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
WORKSPACE = Path(os.path.expanduser("~/.openclaw/workspace"))
INTEL_DIR = WORKSPACE / "memory" / "intelligence"
SCRIPTS = WORKSPACE / "scripts"
MODELS_JSON = Path(os.path.expanduser("~/.openclaw/agents/main/agent/models.json"))

INTENTS_FILE = INTEL_DIR / "intents.json"
PROFILE_FILE = INTEL_DIR / "profile.json"
PATTERNS_FILE = INTEL_DIR / "patterns.json"
RELATIONSHIPS_FILE = INTEL_DIR / "relationships.json"
INSIGHTS_FILE = INTEL_DIR / "insights.jsonl"
ACTIONS_FILE = INTEL_DIR / "actions.jsonl"
FEEDBACK_FILE = INTEL_DIR / "feedback.jsonl"
PRISM_EVENTS_FILE = WORKSPACE / "memory" / "prism_events.json"

MAX_DAILY_ACTIONS = 5
MAX_L2_DAILY = 2  # Max feishu pushes
MAX_L3_DAILY = 1  # Max autonomous tasks


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


def append_jsonl(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def atomic_write_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_api_config(model="pa/claude-haiku-4-5-20251001"):
    try:
        cfg = json.loads(MODELS_JSON.read_text())
        lm = cfg["providers"]["litellm"]
        return {"base_url": lm["baseUrl"], "api_key": lm["apiKey"],
                "headers": lm.get("headers", {}), "model": model}
    except Exception:
        return None


def call_llm(prompt, api, max_tokens=2000):
    url = f"{api['base_url']}/chat/completions"
    payload = {"model": api["model"], "messages": [{"role": "user", "content": prompt}],
               "max_tokens": max_tokens, "temperature": 0.2}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api['api_key']}",
               **api.get("headers", {})}
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"].strip()
        except Exception:
            if attempt < 2:
                time.sleep(2 ** attempt * 3)
    return None


def is_quiet_hours():
    hour = datetime.now(TZ).hour
    return hour >= 23 or hour < 8


def today_str():
    return datetime.now(TZ).strftime("%Y-%m-%d")


def today_action_counts() -> dict:
    """Count today's actions by level."""
    today = today_str()
    actions = load_jsonl(ACTIONS_FILE)
    counts = {"L0": 0, "L1": 0, "L2": 0, "L3": 0, "total": 0}
    for a in actions:
        if a.get("date") == today and a.get("status") == "executed":
            level = a.get("level", "L0")
            counts[level] = counts.get(level, 0) + 1
            counts["total"] += 1
    return counts


# ── 行动规划器 ────────────────────────────────────────────

def plan_actions(api=None) -> list:
    """Generate action plans from current intelligence state."""
    now = datetime.now(TZ)
    today = today_str()
    hour = now.hour
    weekday = now.weekday()
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

    profile = load_json(PROFILE_FILE, {})
    patterns = load_json(PATTERNS_FILE, {})
    intents = load_json(INTENTS_FILE, {})
    insights = load_jsonl(INSIGHTS_FILE)
    relationships = load_json(RELATIONSHIPS_FILE, {})

    actions = []
    existing_actions = load_jsonl(ACTIONS_FILE)
    existing_ids = {a.get("id") for a in existing_actions}

    # ── 1. 运动提醒（运动日 17-20 点）──────────────────────
    exercise_days = patterns.get("weekly_patterns", {}).get("exercise_days", [])
    if weekday_names[weekday] in exercise_days and 17 <= hour <= 20:
        aid = f"exercise_reminder_{today}"
        if aid not in existing_ids:
            actions.append({
                "id": aid, "type": "exercise_reminder", "level": "L1",
                "text": f"今天是{weekday_names[weekday]}（运动日）💪",
                "reason": "行为模式显示今天通常运动", "priority": 2,
            })

    # ── 1b. 运动断档提醒（非运动日但已连续2天没运动）─────────
    if weekday_names[weekday] not in exercise_days and 18 <= hour <= 20:
        # Check recent actions for exercise
        recent_exercise = False
        for a in existing_actions:
            if a.get("type") == "exercise_reminder" and a.get("status") == "executed":
                try:
                    from datetime import date as D
                    if (now.date() - D.fromisoformat(a.get("date", "2000-01-01"))).days <= 2:
                        recent_exercise = True
                except Exception:
                    pass
        if not recent_exercise:
            aid = f"exercise_gap_{today}"
            if aid not in existing_ids:
                actions.append({
                    "id": aid, "type": "exercise_gap", "level": "L1",
                    "text": "已经2天没运动了，今晚去一趟？",
                    "reason": "运动频率低于周均 2.6 次", "priority": 2,
                })

    # ── 2. 社交日提醒（社交高峰日 11-14 点）────────────────
    social_peak = patterns.get("weekly_patterns", {}).get("social_peak_day")
    if social_peak == weekday_names[weekday] and 11 <= hour <= 14:
        aid = f"social_suggestion_{today}"
        if aid not in existing_ids:
            actions.append({
                "id": aid, "type": "social_suggestion", "level": "L2",
                "text": f"今天{weekday_names[weekday]}，你的社交高峰日。约人吃饭/聊天？",
                "reason": "历史数据显示今天社交活动最多", "priority": 2,
            })

    # ── 3. 加班预警（加班高发日 19 点）─────────────────────
    overtime_days = patterns.get("weekly_patterns", {}).get("overtime_days", [])
    if weekday_names[weekday] in overtime_days and 19 <= hour <= 20:
        aid = f"overtime_warning_{today}"
        if aid not in existing_ids:
            actions.append({
                "id": aid, "type": "overtime_warning", "level": "L1",
                "text": f"{weekday_names[weekday]}是加班高发日⚠️ 该收了",
                "reason": "历史模式显示今天加班概率高", "priority": 2,
            })

    # ── 4. 意图跟进（高优 >7天 每天最多推 1 条）──────────────
    active_intents = intents.get("active", [])
    stale_high = []
    for intent in active_intents:
        if intent.get("seriousness", 0) >= 4 and intent.get("type") in ("todo", "plan"):
            created = intent.get("created_at", "")
            try:
                from datetime import date as D
                days_old = (now.date() - D.fromisoformat(created)).days
                if days_old >= 7:
                    stale_high.append((intent, days_old))
            except Exception:
                pass

    if stale_high and 10 <= hour <= 20:
        # Rotate: pick one per day based on day-of-year
        day_of_year = now.timetuple().tm_yday
        stale_sorted = sorted(stale_high, key=lambda x: -x[1])
        pick = stale_sorted[day_of_year % len(stale_sorted)]
        intent, days = pick
        aid = f"intent_nudge_{intent.get('id', '')}_{today}"
        if aid not in existing_ids:
            actions.append({
                "id": aid, "type": "intent_nudge", "level": "L2",
                "text": f"📋 {days}天前说的：{intent['text'][:50]}\n还要跟进吗？回复「不用了」我就标完成",
                "reason": f"高优意图超 {days} 天", "priority": 3,
                "intent_id": intent.get("id"),
            })

    # ── 5. 休息提醒（22 点后还活跃）──────────────────────
    sleep_median = profile.get("schedule", {}).get("sleep_median", "23:00")
    try:
        sleep_h = int(sleep_median.split(":")[0])
    except Exception:
        sleep_h = 23
    if hour >= sleep_h and hour < 24:
        aid = f"sleep_nudge_{today}"
        if aid not in existing_ids:
            actions.append({
                "id": aid, "type": "sleep_nudge", "level": "L1",
                "text": "到点了💤",
                "reason": f"通常 {sleep_median} 后进入休息", "priority": 1,
            })

    # ── 6. 明日预判（21-22 点生成明日预测）──────────────────
    if 21 <= hour <= 22:
        tomorrow_wd = (weekday + 1) % 7
        tomorrow_name = weekday_names[tomorrow_wd]
        tips = []

        if tomorrow_name in exercise_days:
            tips.append("运动日")
        if tomorrow_name in overtime_days:
            tips.append("加班高发")
        if social_peak == tomorrow_name:
            tips.append("社交高峰")

        routine = patterns.get("daily_routine", {})
        day_type = "weekend" if tomorrow_wd >= 5 else "weekday"
        morning = routine.get(day_type, {}).get("08-10", {})
        if morning:
            tips.append(f"早上通常{morning.get('top_activity', '?')}")

        if tips:
            aid = f"tomorrow_preview_{today}"
            if aid not in existing_ids:
                actions.append({
                    "id": aid, "type": "tomorrow_preview", "level": "L1",
                    "text": f"明天{tomorrow_name}：{'，'.join(tips)}",
                    "reason": "基于行为模式预判", "priority": 1,
                })

    # ── 7. 洞察推送（未推的高优洞察）──────────────────────
    unpushed = [i for i in insights if not i.get("pushed") and i.get("priority", 0) >= 3]
    for insight in unpushed[:1]:
        aid = f"push_insight_{insight.get('id', '')}_{today}"
        if aid not in existing_ids:
            level = "L2" if insight.get("priority", 0) >= 4 else "L1"
            actions.append({
                "id": aid, "type": "insight_push", "level": level,
                "text": insight.get("text", "")[:100],
                "reason": "高优洞察待推送", "priority": insight.get("priority", 2),
                "insight_id": insight.get("id"),
            })

    # ── 8. 周末活动推荐（周五 10-14 点）──────────────────
    if weekday == 4 and 10 <= hour <= 14:
        aid = f"weekend_plan_{today}"
        if aid not in existing_ids:
            actions.append({
                "id": aid, "type": "weekend_plan", "level": "L2",
                "text": "周末有什么安排？要我帮你找点活动吗？",
                "reason": "周五午间推送周末计划", "priority": 2,
            })

    return actions


# ── 行动执行器 ────────────────────────────────────────────

def execute_action(action: dict) -> dict:
    """Execute a single action, return result."""
    level = action.get("level", "L0")
    action_type = action.get("type", "")
    text = action.get("text", "")
    now = datetime.now(TZ)

    result = {
        "id": action["id"],
        "date": today_str(),
        "level": level,
        "type": action_type,
        "text": text,
        "timestamp": now.isoformat(),
    }

    try:
        if level == "L0":
            # Just log
            result["status"] = "executed"
            result["method"] = "log_only"

        elif level == "L1":
            # Prism flash
            events = load_json(PRISM_EVENTS_FILE, {"events": []})
            etype = "info"
            if action_type in ("reminder", "overtime_warning"):
                etype = "alert"
            events.setdefault("events", []).append({
                "type": etype,
                "text": text[:30],
                "timestamp": now.isoformat(),
                "ttl": 30,
                "source": "pi_action",
            })
            atomic_write_json(PRISM_EVENTS_FILE, events)
            result["status"] = "executed"
            result["method"] = "prism_flash"

        elif level == "L2":
            # Write to pending notifications for heartbeat to pick up
            notif_file = INTEL_DIR / "pending_notifications.json"
            notifications = load_json(notif_file, {"items": []})
            notifications["items"].append({
                "text": text,
                "priority": action.get("priority", 2),
                "action_id": action["id"],
                "action_type": action_type,
                "timestamp": now.isoformat(),
                "source": "pi_action",
            })
            notifications["items"] = notifications["items"][-50:]
            atomic_write_json(notif_file, notifications)
            result["status"] = "executed"
            result["method"] = "notification_queue"

        elif level == "L3":
            # Autonomous task execution
            # For now, limited to safe read-only operations
            result["status"] = "skipped"
            result["method"] = "l3_not_implemented"
            result["reason"] = "L3 autonomous execution pending Phase 3.2"

        else:
            result["status"] = "skipped"
            result["reason"] = f"Unknown level: {level}"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


def should_execute(action: dict, counts: dict) -> bool:
    """Check if action should execute given daily limits."""
    level = action.get("level", "L0")

    if counts["total"] >= MAX_DAILY_ACTIONS:
        return False
    if level == "L2" and counts.get("L2", 0) >= MAX_L2_DAILY:
        return False
    if level == "L3" and counts.get("L3", 0) >= MAX_L3_DAILY:
        return False
    if is_quiet_hours() and level in ("L2", "L3"):
        return False

    return True


# ── 反馈系统 ──────────────────────────────────────────────

def record_feedback(action_id: str, feedback_type: str, detail: str = ""):
    """Record user feedback on an action."""
    append_jsonl(FEEDBACK_FILE, {
        "action_id": action_id,
        "feedback": feedback_type,  # positive/negative/dismiss/ignore
        "detail": detail,
        "timestamp": datetime.now(TZ).isoformat(),
    })


def get_feedback_stats() -> dict:
    """Aggregate feedback statistics."""
    feedbacks = load_jsonl(FEEDBACK_FILE)
    from collections import Counter
    types = Counter(f.get("feedback") for f in feedbacks)
    return {
        "total": len(feedbacks),
        "positive": types.get("positive", 0),
        "negative": types.get("negative", 0),
        "dismiss": types.get("dismiss", 0),
        "ignore": types.get("ignore", 0),
        "acceptance_rate": types.get("positive", 0) / max(1, len(feedbacks)),
    }


# ── 主流程 ────────────────────────────────────────────────

def print_stats():
    actions = load_jsonl(ACTIONS_FILE)
    feedback_stats = get_feedback_stats()
    today = today_str()
    today_actions = [a for a in actions if a.get("date") == today]
    from collections import Counter

    print("\n📊 行动层统计")
    print(f"  总行动: {len(actions)}")
    print(f"  今日: {len(today_actions)}")

    level_dist = Counter(a.get("level") for a in actions)
    print(f"  级别分布: {dict(level_dist)}")

    type_dist = Counter(a.get("type") for a in actions)
    print(f"  类型分布: {dict(type_dist)}")

    status_dist = Counter(a.get("status") for a in actions)
    print(f"  状态分布: {dict(status_dist)}")

    print(f"\n  反馈统计: {feedback_stats}")


def main():
    parser = argparse.ArgumentParser(description="PI 行动层")
    parser.add_argument("--plan", action="store_true", help="只生成计划")
    parser.add_argument("--execute", metavar="ID", help="执行指定行动")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--feedback", nargs=2, metavar=("ID", "TYPE"), help="记录反馈")
    args = parser.parse_args()

    if args.stats:
        print_stats()
        return

    if args.feedback:
        record_feedback(args.feedback[0], args.feedback[1])
        print(f"✅ 反馈已记录: {args.feedback[0]} → {args.feedback[1]}")
        return

    # Plan actions
    actions = plan_actions()

    if not actions:
        print("✅ 当前无待执行行动")
        return

    counts = today_action_counts()

    if args.plan:
        print(f"📋 行动计划 ({len(actions)} 条):")
        for a in actions:
            executable = "✅" if should_execute(a, counts) else "⏭️"
            print(f"  {executable} [{a['level']}] {a['type']}: {a['text'][:60]}")
            print(f"     原因: {a.get('reason', '')}")
        return

    # Execute
    print(f"🎬 行动执行 ({len(actions)} 条计划)")
    executed = 0
    for action in actions:
        if not should_execute(action, counts):
            print(f"  ⏭️ [{action['level']}] {action['text'][:40]} (限额/安静时间)")
            continue

        result = execute_action(action)
        append_jsonl(ACTIONS_FILE, result)

        if result["status"] == "executed":
            print(f"  ✅ [{action['level']}] {action['text'][:40]} → {result['method']}")
            executed += 1
            counts[action["level"]] = counts.get(action["level"], 0) + 1
            counts["total"] += 1
        else:
            print(f"  ⚠️ [{action['level']}] {result.get('reason', result.get('error', ''))}")

    print(f"\n✅ 执行完成: {executed}/{len(actions)}")


if __name__ == "__main__":
    main()
