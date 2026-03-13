"""
晨间简报生成器 — Daily Brief v2
核心逻辑：不给建议，给结果。

从多数据源提取昨天的事件，按三类输出：
1. 已完成的交付（"帮你做了什么"）
2. 意图捕捉并执行（"你说的这些我记住了并已行动"）
3. 已准备好的内容（"你今天可能用到的，我已经备好了"）

运行方式：
  python3 src/services/generators/daily_brief.py --date 2026-03-12
  python3 src/services/generators/daily_brief.py --date 2026-03-12 --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys as _sys
from pathlib import Path as _Path
_ws = _Path(__file__).resolve()
while _ws.name != "src" and _ws != _ws.parent:
    _ws = _ws.parent
if _ws.name == "src":
    _sys.path.insert(0, str(_ws.parent))

from src.services.config import WORKSPACE, MEMORY_DIR, SERVICES_OUTPUT_DIR
sys.path.insert(0, str(WORKSPACE))

from src.services.data_sources import DataSourceRegistry
from src.services.llm_client import llm_complete

OUTPUT_DIR = SERVICES_OUTPUT_DIR


def _load_user_profile() -> Dict[str, Any]:
    """Load user profile for personalization."""
    profile_path = MEMORY_DIR / "intelligence" / "profile.json"
    if profile_path.exists():
        with open(profile_path) as f:
            return json.load(f)
    return {}


def _load_memory_context(date: str) -> str:
    """Load recent daily memory for context."""
    mem_path = MEMORY_DIR / f"{date}.md"
    if mem_path.exists():
        with open(mem_path) as f:
            content = f.read()
        # Truncate to last 3000 chars
        return content[-3000:] if len(content) > 3000 else content
    return ""


def _load_todo_context() -> str:
    """Load current todo list."""
    todo_path = MEMORY_DIR / "todo.md"
    if todo_path.exists():
        with open(todo_path) as f:
            return f.read()[:2000]
    return ""


def _build_data_summary(data: Dict[str, Any]) -> str:
    """Build comprehensive data summary from all sources."""
    parts: List[str] = []

    # Audio: detailed scene-by-scene
    audio = data.get("audio", {})
    if audio.get("available"):
        scenes_text = []
        for sc in audio.get("scenes", []):
            summary = sc.get("summary", "")
            activity = sc.get("activity", "unknown")
            time = sc.get("start_time", "")
            quotes = [q.get("text", "") for q in sc.get("key_quotes", []) if q.get("text")]
            participants = sc.get("participants", [])
            scenes_text.append(
                f"[{time}] ({activity}) {summary}\n"
                f"  参与者: {participants}\n"
                f"  关键原话: {quotes[:3]}"
            )
        parts.append("=== 录音场景 ===\n" + "\n".join(scenes_text))

        # Macro frames
        for mf in audio.get("macro_frames", []):
            frame_type = mf.get("frame_type", "")
            topics = mf.get("key_topics", [])
            mood = mf.get("mood_or_tone", "")
            outcomes = mf.get("outcomes", [])
            parts.append(
                f"[宏观-{frame_type}] 话题={topics}, 情绪={mood}, 成果={outcomes}"
            )

    # Chat: user's actual messages
    chat = data.get("chat", {})
    if chat.get("available"):
        user_msgs = [m for m in chat.get("messages", []) if m.get("source") == "chat"]
        if user_msgs:
            chat_texts = [f"[{m.get('timestamp','')[11:16]}] {m.get('text','')[:200]}" for m in user_msgs[:30]]
            parts.append("=== 飞书对话 ===\n" + "\n".join(chat_texts))

    # Vision
    vision = data.get("vision", {})
    if vision.get("available") and vision.get("observation_count", 0) > 0:
        parts.append(
            f"=== 摄像头 ===\n"
            f"观察{vision.get('observation_count',0)}次, "
            f"表情={vision.get('moods_seen',[])}"
        )

    # Habit
    habit = data.get("habit", {})
    if habit.get("available"):
        rules = habit.get("behavior_rules", {})
        rule_texts = [r.get("rule", "") for r in rules.get("rules", [])[:5]]
        parts.append(f"=== 行为模式 ===\n规则: {rule_texts}")

    return "\n\n".join(parts)


def generate_brief(date: str, dry_run: bool = False) -> Dict[str, Any]:
    """
    Generate action-oriented daily brief.
    
    The brief should contain:
    1. deliveries: things already done for the user
    2. captured_intents: what was captured and acted upon
    3. prepared: content/drafts ready for the user
    4. tracking: items being tracked with status
    """
    reg = DataSourceRegistry()
    data = reg.get_all_data(date)
    
    data_summary = _build_data_summary(data)
    memory_context = _load_memory_context(date)
    todo_context = _load_todo_context()
    profile = _load_user_profile()

    system_prompt = """你是星星，用户饭团的私人AI助理。你在生成晨间简报。

核心原则：**不给建议，给结果**。
- 不说"建议你去做XX" → 说"我已经帮你做了XX"或"我准备了XX给你"
- 不说"你可能需要关注" → 说"这个事情的进展是..."
- 不说"记得去做" → 说"我已经设了提醒"或"我帮你拟好了"

你的能力（可以承诺做到的）：
- 写文档/方案（飞书文档）
- 搜索信息（网页、票务、天气等）
- 设置提醒和跟踪
- 分析数据、生成报告
- 给同事/朋友拟消息草稿
- 整理会议要点和行动项

输出 JSON：
{
  "deliveries": [
    {"title": "做了什么", "detail": "具体结果/链接", "source": "基于什么数据"}
  ],
  "captured_intents": [
    {"quote": "用户原话", "action_taken": "我做了什么", "status": "done/in_progress/prepared"}
  ],
  "prepared_for_today": [
    {"title": "准备了什么", "content": "具体内容（消息草稿/方案/数据等）"}
  ],
  "tracking": [
    {"item": "跟踪项", "status": "进展", "next_action": "下一步我会做什么"}
  ],
  "status_note": "一句基于摄像头/录音的状态观察（自然、不刻意）"
}

注意：
- deliveries 要有具体成果，不是"我帮你总结了"而是把总结内容写出来
- captured_intents 里的 action_taken 要么是已完成的，要么是"我正在做"
- prepared_for_today 里要有可以直接用的内容（比如拟好的消息、查好的信息）
- tracking 是正在跟进的长线事项
- 如果数据不足以产生某个分类，就留空数组，不要编造
"""

    user_prompt = f"""日期：{date}

=== 多源数据 ===
{data_summary[:8000]}

=== 当天记忆日志 ===
{memory_context[:2000]}

=== 当前待办 ===
{todo_context[:1000]}

请基于以上数据生成行动导向的晨间简报。记住：给结果，不给建议。"""

    if dry_run:
        brief_content = {
            "deliveries": [{"title": "[DRY-RUN]", "detail": "测试模式", "source": "test"}],
            "captured_intents": [],
            "prepared_for_today": [],
            "tracking": [],
            "status_note": "[DRY-RUN] 数据加载正常",
        }
    else:
        raw_response = llm_complete(
            prompt=user_prompt,
            system=system_prompt,
            max_tokens=4000,
            temperature=0.5,
        )

        raw = raw_response.strip()
        # Handle markdown code blocks
        if "```json" in raw:
            raw = raw.split("```json", 1)[1]
            raw = raw.split("```", 1)[0]
        elif "```" in raw:
            raw = raw.split("```", 1)[1]
            raw = raw.split("```", 1)[0]
        raw = raw.strip()
        try:
            brief_content = json.loads(raw)
        except json.JSONDecodeError:
            # Try to find JSON object in the response
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    brief_content = json.loads(raw[start:end])
                except json.JSONDecodeError:
                    brief_content = {"raw_response": raw_response[:500], "parse_error": True}
            else:
                brief_content = {"raw_response": raw_response[:500], "parse_error": True}

    result = {
        "generator": "daily_brief_v2",
        "date": date,
        "generated_at": datetime.now().isoformat(),
        "dry_run": dry_run,
        "data_sources": {
            name: {"available": d.get("available"), "size": len(str(d))}
            for name, d in data.items()
        },
        "brief": brief_content,
    }

    return result


def format_brief_message(brief: Dict[str, Any]) -> str:
    """Format brief into a readable message for Feishu."""
    b = brief.get("brief", {})
    parts: List[str] = []
    date = brief.get("date", "")
    
    parts.append(f"☀️ 晨间 Brief | {date}\n")

    # Deliveries
    deliveries = b.get("deliveries", [])
    if deliveries:
        parts.append("**昨天帮你推进了这些事**\n")
        for d in deliveries:
            parts.append(f"📌 {d['title']}")
            if d.get("detail"):
                parts.append(f"→ {d['detail']}")
            parts.append("")

    # Captured intents
    intents = b.get("captured_intents", [])
    if intents:
        parts.append("**你说的这些我记住并行动了**\n")
        for i in intents:
            status_icon = {"done": "✅", "in_progress": "🔄", "prepared": "📋"}.get(i.get("status"), "📝")
            parts.append(f"{status_icon} \"{i.get('quote', '')}\"")
            parts.append(f"   → {i.get('action_taken', '')}")
            parts.append("")

    # Prepared
    prepared = b.get("prepared_for_today", [])
    if prepared:
        parts.append("**今天可以直接用的**\n")
        for p in prepared:
            parts.append(f"📎 {p['title']}")
            if p.get("content"):
                parts.append(f"   {p['content']}")
            parts.append("")

    # Tracking
    tracking = b.get("tracking", [])
    if tracking:
        parts.append("**正在跟踪**\n")
        for t in tracking:
            parts.append(f"🔄 {t['item']} — {t.get('status', '...')}")
            if t.get("next_action"):
                parts.append(f"   下一步: {t['next_action']}")
            parts.append("")

    # Status note
    note = b.get("status_note", "")
    if note:
        parts.append(f"💭 {note}")

    return "\n".join(parts)


def save_brief(result: Dict[str, Any], date: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{date}.json"
    existing: Dict[str, Any] = {}
    if out_path.exists():
        try:
            with open(out_path, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass
    existing["daily_brief"] = result
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate action-oriented daily brief")
    parser.add_argument(
        "--date",
        default=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        help="Date (YYYY-MM-DD), default: yesterday",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--format", action="store_true", help="Print formatted message")
    args = parser.parse_args()

    print(f"Generating daily brief for {args.date} (dry_run={args.dry_run})...\n")
    result = generate_brief(args.date, dry_run=args.dry_run)

    if args.format or not args.dry_run:
        print(format_brief_message(result))
    else:
        print(json.dumps(result["brief"], ensure_ascii=False, indent=2))

    print(f"\n📊 Data sources:")
    for name, info in result["data_sources"].items():
        avail = "✓" if info["available"] else "✗"
        print(f"  {avail} {name}: {info['size']} chars")

    if args.save and not args.dry_run:
        path = save_brief(result, args.date)
        print(f"\n✅ Saved to {path}")
