"""
会议洞察生成器 — Meeting Insight
输入：录音数据中 activity=meeting 的 scenes
输出：每场会议的分歧/决策/行动项

运行方式：
  python3 src/services/generators/meeting_insight.py --date 2026-03-12 --dry-run
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

from src.services.data_sources import AudioDataSource
from src.services.llm_client import llm_complete

OUTPUT_DIR = SERVICES_OUTPUT_DIR


def extract_meeting_scenes(audio_data: Dict[str, Any]) -> List[Dict]:
    """Extract scenes with activity label 'meeting'."""
    scenes = audio_data.get("scenes", [])
    return [
        s for s in scenes
        if s.get("activity", {}).get("label") in ("meeting", "group_discussion", "call")
    ]


def analyze_meeting(scene: Dict, dry_run: bool = False) -> Dict[str, Any]:
    """Analyze a single meeting scene with LLM."""
    key_quotes = scene.get("key_quotes", [])
    quotes_text = "\n".join(
        f"  [{q.get('speaker','?')}] {q.get('text','')}"
        for q in key_quotes
    )

    start = scene.get("start_time") or f"{scene.get('start_sec',0)}s"
    end = scene.get("end_time") or f"{scene.get('end_sec',0)}s"
    duration_min = (scene.get("end_sec", 0) - scene.get("start_sec", 0)) // 60

    system_prompt = (
        "你是一个会议助理，负责提炼会议要点。"
        "输出 JSON，包含：\n"
        '  "topic": 会议主题（简短）\n'
        '  "decisions": 已做出的决策（list of str）\n'
        '  "disagreements": 出现的分歧或争议（list of str）\n'
        '  "action_items": 行动项，格式 "谁 → 做什么"（list of str）\n'
        '  "summary": 一段话总结（2-3句）\n'
        "只输出 JSON。"
    )

    user_prompt = (
        f"会议时间：{start} — {end}（约{duration_min}分钟）\n"
        f"关键引语：\n{quotes_text or '（无引语数据）'}\n\n"
        "请提炼这场会议的要点。"
    )

    raw = llm_complete(
        prompt=user_prompt,
        system=system_prompt,
        max_tokens=600,
        dry_run=dry_run,
    )

    if dry_run:
        return {
            "scene_id": scene.get("id"),
            "duration_min": duration_min,
            "topic": "[DRY-RUN] 会议主题",
            "decisions": ["[DRY-RUN] 决策示例"],
            "disagreements": [],
            "action_items": ["[DRY-RUN] 行动项示例"],
            "summary": "[DRY-RUN] 会议摘要",
        }

    # Parse JSON
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
        "scene_id": scene.get("id"),
        "start_time": start,
        "end_time": end,
        "duration_min": duration_min,
        **content,
    }


def generate_meeting_insights(date: str, dry_run: bool = False) -> Dict[str, Any]:
    audio_src = AudioDataSource()
    audio_data = audio_src.get_today_data(date)

    result: Dict[str, Any] = {
        "generator": "meeting_insight",
        "date": date,
        "generated_at": datetime.now().isoformat(),
        "dry_run": dry_run,
        "audio_available": audio_data.get("available", False),
        "meetings": [],
    }

    if not audio_data.get("available"):
        result["note"] = audio_data.get("error", "No audio data")
        return result

    meeting_scenes = extract_meeting_scenes(audio_data)
    result["meeting_count"] = len(meeting_scenes)

    for scene in meeting_scenes:
        insight = analyze_meeting(scene, dry_run=dry_run)
        result["meetings"].append(insight)

    return result


def save_insights(result: Dict[str, Any], date: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{date}.json"
    existing: Dict[str, Any] = {}
    if out_path.exists():
        try:
            with open(out_path, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass
    existing["meeting_insight"] = result
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate meeting insights")
    parser.add_argument(
        "--date",
        default=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        help="Date (YYYY-MM-DD)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    print(f"Generating meeting insights for {args.date} (dry_run={args.dry_run})...")
    result = generate_meeting_insights(args.date, dry_run=args.dry_run)

    print(f"\n🗓 Found {result.get('meeting_count', 0)} meeting(s)")
    for i, m in enumerate(result.get("meetings", []), 1):
        print(f"\nMeeting {i}: {m.get('topic','?')} ({m.get('duration_min','?')} min)")
        for ai in m.get("action_items", []):
            print(f"  → {ai}")

    if args.save and not args.dry_run:
        path = save_insights(result, args.date)
        print(f"\n✅ Saved to {path}")
