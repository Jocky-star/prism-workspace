#!/usr/bin/env python3
"""
pi_daily_pipeline.py — 每日智能管线

每天自动运行：
  1. 检查今天是否有新录音数据
  2. 运行感知层处理
  3. 运行理解层更新
  4. 生成当日洞察

用法：
  python3 pi_daily_pipeline.py              # 处理最近2天
  python3 pi_daily_pipeline.py --date 20260312  # 指定日期
  python3 pi_daily_pipeline.py --force       # 强制重跑（即使已处理）
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
WORKSPACE = Path(os.path.expanduser("~/.openclaw/workspace"))
SRC = WORKSPACE / "src"
INTEL_DIR = WORKSPACE / "memory" / "intelligence"
DATA_DIR = WORKSPACE / "data" / "daily-reports"
STATE_FILE = INTEL_DIR / "pipeline_state.json"
INSIGHTS_FILE = INTEL_DIR / "insights.jsonl"

INTEL_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path, default=None):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default if default is not None else {}


def atomic_write_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def run_script(script_path: str, args: list, timeout: int = 120) -> tuple[bool, str]:
    """Run a Python script by relative path from src/, return (success, output)."""
    full_path = SRC / script_path
    cmd = [sys.executable, str(full_path)] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(WORKSPACE))
        output = result.stdout + result.stderr
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)


def get_recent_dates(n: int = 2) -> list[str]:
    """Get dates for the last N days that have data files."""
    dates = []
    now = datetime.now(TZ)
    for i in range(n):
        d = now - timedelta(days=i)
        date_str = d.strftime("%Y%m%d")
        if (DATA_DIR / f"{date_str}.json").exists():
            dates.append(date_str)
    return dates


def generate_daily_insights(date_str: str):
    """Generate insights from today's data compared to patterns."""
    profiles = load_json(INTEL_DIR / "profile.json", {})
    patterns = load_json(INTEL_DIR / "patterns.json", {})
    contexts_file = INTEL_DIR / "contexts.jsonl"
    intents_file = INTEL_DIR / "intents.json"

    fmt_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

    # Load today's contexts
    today_contexts = []
    if contexts_file.exists():
        for line in contexts_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    ctx = json.loads(line)
                    if ctx.get("date") == fmt_date:
                        today_contexts.append(ctx)
                except Exception:
                    pass

    if not today_contexts:
        return 0

    insights = []

    # 1. Check work hours vs average
    work_minutes = 0
    for c in today_contexts:
        if c.get("activity") == "work":
            s = c.get("start", "")
            e = c.get("end", "")
            try:
                sh, sm = int(s[11:13]), int(s[14:16])
                eh, em = int(e[11:13]), int(e[14:16])
                work_minutes += (eh * 60 + em) - (sh * 60 + sm)
            except Exception:
                pass

    avg_work = profiles.get("schedule", {}).get("work_hours_avg", 4) * 60
    if work_minutes > avg_work * 1.5 and work_minutes > 360:
        insights.append({
            "id": f"work_overtime_{date_str}",
            "date": fmt_date,
            "type": "anomaly",
            "priority": 3,
            "text": f"今天工作 {work_minutes/60:.1f}h，超过均值 {avg_work/60:.1f}h 的 50%",
            "pushed": False,
        })

    # 2. Check if exercise happened
    exercised = any(c.get("activity") == "exercise" for c in today_contexts)
    weekday = datetime.strptime(date_str, "%Y%m%d").weekday()
    exercise_days = patterns.get("weekly_patterns", {}).get("exercise_days", [])
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    expected_exercise = weekday_names[weekday] in exercise_days

    if expected_exercise and not exercised:
        insights.append({
            "id": f"no_exercise_{date_str}",
            "date": fmt_date,
            "type": "reminder",
            "priority": 2,
            "text": f"今天是{weekday_names[weekday]}（常运动日），还没运动",
            "pushed": False,
        })

    # 3. New intents from today
    intents = load_json(intents_file, {})
    today_intents = [i for i in intents.get("active", []) if i.get("created_at") == fmt_date]
    high_intents = [i for i in today_intents if i.get("seriousness", 0) >= 4]
    if high_intents:
        texts = [i["text"][:30] for i in high_intents[:3]]
        insights.append({
            "id": f"new_intents_{date_str}",
            "date": fmt_date,
            "type": "info",
            "priority": 2,
            "text": f"今日高优意图: {'; '.join(texts)}",
            "pushed": False,
        })

    # 4. Social anomaly: no one talked to today
    social_scenes = sum(1 for c in today_contexts if c.get("participants", 0) > 1)
    if len(today_contexts) > 10 and social_scenes == 0:
        insights.append({
            "id": f"isolated_{date_str}",
            "date": fmt_date,
            "type": "observation",
            "priority": 1,
            "text": "今天似乎没有和人交流",
            "pushed": False,
        })

    # Write insights
    if insights:
        existing = []
        if INSIGHTS_FILE.exists():
            for line in INSIGHTS_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        existing.append(json.loads(line))
                    except Exception:
                        pass

        existing_ids = {e.get("id") for e in existing}
        new_insights = [i for i in insights if i["id"] not in existing_ids]

        if new_insights:
            with open(INSIGHTS_FILE, "a", encoding="utf-8") as f:
                for i in new_insights:
                    f.write(json.dumps(i, ensure_ascii=False) + "\n")

    return len(insights)


def main():
    parser = argparse.ArgumentParser(description="PI 每日管线")
    parser.add_argument("--date", help="指定日期 (YYYYMMDD)")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    state = load_json(STATE_FILE, {"processed_dates": [], "last_run": None})

    # Determine dates
    if args.date:
        dates = [args.date]
    else:
        dates = get_recent_dates(2)

    if not dates:
        print("📭 没有新数据")
        return

    # Filter already processed
    if not args.force:
        dates = [d for d in dates if d not in state.get("processed_dates", [])]

    if not dates:
        print("✅ 最近数据已处理")
        return

    print(f"🔄 每日管线：处理 {len(dates)} 天 ({', '.join(dates)})")

    # Step 0: Chat data extraction
    print("\n💬 对话数据采集...")
    ok, output = run_script("sources/chat/extract.py", ["--recent", "2", "--feed-perception"])
    if ok:
        for line in output.splitlines():
            if "Extracted" in line or "提取" in line:
                print(f"  ✅ {line.strip()}")
    else:
        print(f"  ⚠️ 对话采集: {output[:100]}")

    # Step 1: Perception (audio data)
    print("\n📡 感知层...")
    for date_str in dates:
        ok, output = run_script("intelligence/perception.py", [date_str, "--no-llm"])
        if ok:
            print(f"  ✅ {date_str}")
        else:
            print(f"  ❌ {date_str}: {output[:100]}")
            return

    # Step 2: Understanding
    print("\n🧠 理解层...")
    ok, output = run_script("intelligence/understand.py", [])
    if ok:
        print("  ✅ 统计更新")
    else:
        print(f"  ❌ {output[:200]}")

    # Step 3: Insights (built-in + generator)
    print("\n💡 洞察生成...")
    total_insights = 0
    for date_str in dates:
        n = generate_daily_insights(date_str)
        total_insights += n
        if n > 0:
            print(f"  💡 {date_str}: {n} 条洞察（内置检测）")

    # Step 4: Advanced insight generator
    ok, output = run_script("intelligence/generate_insights.py", ["--date", dates[-1]])
    if ok:
        for line in output.splitlines():
            if "条" in line and ("提醒" in line or "偏离" in line or "变化" in line):
                print(f"  {line.strip()}")
    else:
        print(f"  ⚠️ 高级洞察: {output[:100]}")

    # Step 5: Action layer
    print("\n🎬 行动执行...")
    ok, output = run_script("intelligence/action.py", [])
    if ok:
        for line in output.splitlines():
            if line.strip().startswith("✅") or line.strip().startswith("⏭️"):
                print(f"  {line.strip()}")
    else:
        print(f"  ⚠️ 行动层: {output[:100]}")

    # Update state
    processed = state.get("processed_dates", [])
    processed.extend(dates)
    # Keep only last 90 days
    processed = sorted(set(processed))[-90:]
    state["processed_dates"] = processed
    state["last_run"] = datetime.now(TZ).isoformat()
    state["last_dates"] = dates
    state["last_insights"] = total_insights
    atomic_write_json(STATE_FILE, state)

    print(f"\n✅ 管线完成：{len(dates)} 天处理，{total_insights} 条洞察")


if __name__ == "__main__":
    main()
