"""
人际洞察生成器 — Social Insight
输入：关系数据 (memory/people.md, intelligence/relationships.json) + 本周事件
输出：本周人际动态、关系变化摘要（周度生成）

运行方式：
  python3 src/services/generators/social_insight.py --date 2026-03-12 --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

import sys as _sys
from pathlib import Path as _Path
_ws = _Path(__file__).resolve()
while _ws.name != "src" and _ws != _ws.parent:
    _ws = _ws.parent
if _ws.name == "src":
    _sys.path.insert(0, str(_ws.parent))

from src.services.config import WORKSPACE, MEMORY_DIR, SERVICES_OUTPUT_DIR
sys.path.insert(0, str(WORKSPACE))

from src.services.data_sources import ChatDataSource, AudioDataSource
from src.services.llm_client import llm_complete

OUTPUT_DIR = SERVICES_OUTPUT_DIR
RELATIONSHIPS_FILE = MEMORY_DIR / "intelligence" / "relationships.json"
PEOPLE_FILE = MEMORY_DIR / "people.md"


def load_relationships() -> Dict:
    if RELATIONSHIPS_FILE.exists():
        try:
            with open(RELATIONSHIPS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def load_people_notes() -> str:
    if PEOPLE_FILE.exists():
        try:
            with open(PEOPLE_FILE, encoding="utf-8") as f:
                return f.read()[:2000]
        except Exception:
            pass
    return ""


def collect_week_events(end_date: str) -> List[Dict]:
    """Collect audio + chat data for the past 7 days."""
    audio_src = AudioDataSource()
    chat_src = ChatDataSource()
    events: List[Dict] = []

    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    for i in range(7):
        d = (end_dt - timedelta(days=i)).strftime("%Y-%m-%d")

        audio = audio_src.get_today_data(d)
        if audio.get("available"):
            for q in audio.get("key_quotes", []):
                events.append({
                    "date": d,
                    "source": "audio",
                    "text": q.get("text", ""),
                    "speaker": q.get("speaker"),
                })

        chat = chat_src.get_today_data(d)
        if chat.get("available"):
            for m in chat.get("messages", [])[:20]:
                if m.get("source") == "chat":
                    events.append({
                        "date": d,
                        "source": "chat",
                        "text": m.get("text", "")[:200],
                    })

    return events


def generate_social_insight(date: str, dry_run: bool = False) -> Dict[str, Any]:
    relationships = load_relationships()
    people_notes = load_people_notes()
    week_events = collect_week_events(date)

    # Sample events for LLM (limit context)
    event_sample = week_events[:40]
    events_text = "\n".join(
        f"[{e['date']} {e['source']}] {e['text']}"
        for e in event_sample
    )

    rel_summary = json.dumps(relationships, ensure_ascii=False)[:500]

    system_prompt = (
        "你是用户的私人助理，负责整理本周的人际动态。\n"
        "分析以下数据，输出 JSON：\n"
        '  "week_summary": 本周人际互动总体概况（1-2句）\n'
        '  "key_interactions": 重要的互动或对话（list of {person, event, note}）\n'
        '  "relationship_changes": 关系状态变化或值得关注的动态（list of str）\n'
        '  "suggestions": 下周可以做的人际维护建议（list of str，1-3条）\n'
        "只输出 JSON，不要其他内容。"
    )

    user_prompt = (
        f"日期范围：{date} 前一周\n\n"
        f"本周对话/录音摘要：\n{events_text or '（无数据）'}\n\n"
        f"已知关系数据：\n{rel_summary or '（无数据）'}\n\n"
        f"人物备注：\n{people_notes or '（无数据）'}\n\n"
        "请生成本周人际洞察。"
    )

    raw = llm_complete(
        prompt=user_prompt,
        system=system_prompt,
        max_tokens=700,
        dry_run=dry_run,
    )

    if dry_run:
        content = {
            "week_summary": "[DRY-RUN] 本周人际互动正常",
            "key_interactions": [],
            "relationship_changes": [],
            "suggestions": ["[DRY-RUN] 示例建议"],
        }
    else:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            content = json.loads(raw)
        except json.JSONDecodeError:
            content = {"raw_response": raw, "parse_error": True}

    return {
        "generator": "social_insight",
        "date": date,
        "generated_at": datetime.now().isoformat(),
        "dry_run": dry_run,
        "events_analyzed": len(week_events),
        "insight": content,
    }


def save_result(result: Dict[str, Any], date: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{date}.json"
    existing: Dict[str, Any] = {}
    if out_path.exists():
        try:
            with open(out_path, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass
    existing["social_insight"] = result
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate weekly social insight")
    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="End date for the week (YYYY-MM-DD)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    print(f"Generating social insight up to {args.date} (dry_run={args.dry_run})...")
    result = generate_social_insight(args.date, dry_run=args.dry_run)

    print(f"\n📊 Events analyzed: {result.get('events_analyzed', 0)}")
    insight = result.get("insight", {})
    print(f"📋 Summary: {insight.get('week_summary', '')}")
    for s in insight.get("suggestions", []):
        print(f"  💡 {s}")

    if args.save and not args.dry_run:
        path = save_result(result, args.date)
        print(f"\n✅ Saved to {path}")
