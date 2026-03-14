#!/usr/bin/env python3
"""
pi_weekly_refine.py — 每周 LLM 精炼 + 报告生成

每周运行：
  1. LLM 精炼（人物合并/关系/价值观/意图清理）
  2. 生成周报摘要
  3. 写入 insights 供推送

用法：
  python3 pi_weekly_refine.py              # 完整周流程
  python3 pi_weekly_refine.py --report-only # 只生成报告
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
WORKSPACE = Path(os.environ.get(
    "WORKSPACE",
    os.environ.get(
        "OPENCLAW_WORKSPACE",
        os.path.expanduser("~/.openclaw/workspace")
    )
))
SRC = WORKSPACE / "src"
INTEL_DIR = WORKSPACE / "memory" / "intelligence"
MODELS_JSON = Path(os.path.expanduser("~/.openclaw/agents/main/agent/models.json"))

PROFILE_FILE = INTEL_DIR / "profile.json"
RELATIONSHIPS_FILE = INTEL_DIR / "relationships.json"
PATTERNS_FILE = INTEL_DIR / "patterns.json"
INTENTS_FILE = INTEL_DIR / "intents.json"
INSIGHTS_FILE = INTEL_DIR / "insights.jsonl"
WEEKLY_DIR = INTEL_DIR / "weekly"
STATE_FILE = INTEL_DIR / "pipeline_state.json"

WEEKLY_DIR.mkdir(parents=True, exist_ok=True)


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


def load_api_config(model="pa/claude-haiku-4-5-20251001"):
    try:
        cfg = json.loads(MODELS_JSON.read_text())
        lm = cfg["providers"]["litellm"]
        return {
            "base_url": lm["baseUrl"],
            "api_key": lm["apiKey"],
            "headers": lm.get("headers", {}),
            "model": model,
        }
    except Exception:
        return None


def call_llm(prompt, api, max_tokens=3000):
    url = f"{api['base_url']}/chat/completions"
    payload = {
        "model": api["model"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api['api_key']}",
        **api.get("headers", {}),
    }
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"].strip()
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt * 3)
    return None


def run_refine():
    """Run pi_refine.py for full LLM refinement."""
    cmd = [sys.executable, str(SRC / "intelligence" / "refine.py")]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(WORKSPACE))
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return result.returncode == 0
    except Exception as e:
        print(f"  ❌ 精炼失败: {e}")
        return False


def generate_weekly_report(api):
    """Generate a weekly summary report using LLM."""
    profile = load_json(PROFILE_FILE, {})
    relationships = load_json(RELATIONSHIPS_FILE, {})
    patterns = load_json(PATTERNS_FILE, {})
    intents = load_json(INTENTS_FILE, {})

    # Compact data for LLM
    compact = {
        "schedule": profile.get("schedule", {}),
        "activity_hours": profile.get("activity_distribution", {}),
        "values": profile.get("preferences", {}).get("values", []),
        "top_topics": profile.get("preferences", {}).get("top_topics", [])[:5],
        "thinking_style": profile.get("thinking_style", ""),
        "decision_style": profile.get("decision_style", ""),
        "key_traits": profile.get("key_traits", []),
        "exercise_weekly": profile.get("health", {}).get("exercise_freq_weekly"),
        "top_relationships": {},
        "weekly_patterns": patterns.get("weekly_patterns", {}),
        "anomalies": patterns.get("anomalies_recent", []),
        "active_intents": len(intents.get("active", [])),
        "intent_types": {},
    }

    # Top 5 relationships
    sorted_rels = sorted(relationships.items(),
                        key=lambda x: -x[1].get("interaction_stats", {}).get("total_scenes", 0))
    for name, r in sorted_rels[:5]:
        compact["top_relationships"][name] = {
            "type": r["type"],
            "scenes": r["interaction_stats"]["total_scenes"],
            "hours": round(r["interaction_stats"]["total_minutes"] / 60, 1),
        }

    # Intent type distribution
    from collections import Counter
    compact["intent_types"] = dict(Counter(i["type"] for i in intents.get("active", [])))

    # Recent high-priority intents
    high_intents = [i for i in intents.get("active", []) if i.get("seriousness", 0) >= 4]
    compact["high_priority_intents"] = [i["text"][:60] for i in high_intents[:10]]

    prompt = f"""基于以下用户画像数据，生成一份简洁的周度洞察报告。
要求：
1. 用中文
2. 不超过 500 字
3. 聚焦：本周异常 / 值得注意的趋势 / 未跟进的重要意图 / 健康提醒
4. 语气：轻松但专业，像一个了解你的助理在做周回顾
5. 不要空洞的描述，只说有价值的发现

数据：
{json.dumps(compact, ensure_ascii=False, indent=2)}

直接输出报告正文，不要标题和格式标记。"""

    report = call_llm(prompt, api, max_tokens=1500)
    if not report:
        return None

    # Save report
    now = datetime.now(TZ)
    week_id = now.strftime("%Y-W%V")
    report_data = {
        "week": week_id,
        "generated_at": now.isoformat(),
        "report": report,
        "data_snapshot": compact,
    }

    report_file = WEEKLY_DIR / f"{week_id}.json"
    atomic_write_json(report_file, report_data)

    # Also write as insight for push
    with open(INSIGHTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "id": f"weekly_report_{week_id}",
            "date": now.strftime("%Y-%m-%d"),
            "type": "weekly_report",
            "priority": 4,
            "text": report[:200],
            "full_report": report,
            "pushed": False,
        }, ensure_ascii=False) + "\n")

    return report


def main():
    parser = argparse.ArgumentParser(description="PI 周精炼+报告")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--model", default="pa/claude-haiku-4-5-20251001")
    args = parser.parse_args()

    print(f"📅 周度精炼 (model: {args.model})")

    if not args.report_only:
        print("\n🧠 运行 LLM 精炼...")
        ok = run_refine()
        if not ok:
            print("  ⚠️ 精炼有问题，继续生成报告")

    api = load_api_config(args.model)
    if not api:
        print("❌ 无法加载 API")
        return

    print("\n📝 生成周报...")
    report = generate_weekly_report(api)
    if report:
        print(f"\n{'='*50}")
        print(report)
        print(f"{'='*50}")
        print("\n✅ 周报已保存")
    else:
        print("  ❌ 周报生成失败")


if __name__ == "__main__":
    main()
