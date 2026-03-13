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

try:
    from src.services.feedback_tracker import log_suggestion
    _FEEDBACK_TRACKER_AVAILABLE = True
except ImportError:
    _FEEDBACK_TRACKER_AVAILABLE = False

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
    
    核心原则：Brief 只汇报真正做过的事情。
    - action_log 有记录 → 直接写进 Brief，不需要 LLM 编
    - action_log 为空 → deliveries/proactive 为空，不编造
    - LLM 只负责：从录音/对话中提取 captured_intents 和 tracking
    """
    reg = DataSourceRegistry()
    data = reg.get_all_data(date)
    
    data_summary = _build_data_summary(data)
    memory_context = _load_memory_context(date)
    todo_context = _load_todo_context()
    profile = _load_user_profile()
    
    # 读取行动日志 — Brief 的真实依据
    try:
        from src.services.action_log import get_actions, get_actions_summary
        actions = get_actions(date)
        action_summary = get_actions_summary(date)
    except Exception:
        actions = []
        action_summary = ""

    system_prompt = """你是一个私人助理，给用户做每日汇报。

**最重要的规则：只汇报真正做过的事。没做过的，一个字都不要编。**

你会收到两种数据：
1. **行动日志（action_log）**：这是已经真正执行过的事情。直接写进 deliveries / proactive。
2. **多源数据（录音/对话/行为等）**：用来提取 captured_intents 和 tracking。

汇报原则：
- 行动日志里有的 → 如实汇报
- 行动日志里没有的 → deliveries 和 proactive 留空数组，**绝对不编造**
- 不暴露技术细节（不提日期、数据源、pipeline、模型、脚本）
- 语气自然，像朋友汇报工作

输出 JSON：
{
  "deliveries": [
    {"title": "做了什么", "detail": "具体结果"}
  ],
  "proactive": [
    {"insight": "我注意到你最近...", "action": "所以我帮你...", "result": "结果（可选）"}
  ],
  "captured_intents": [
    {"quote": "用户提到的事（≤30字）", "action_taken": "做了什么/还没做", "status": "done/in_progress/prepared"}
  ],
  "prepared_for_today": [
    {"title": "准备了什么", "content": "可以直接用的内容"}
  ],
  "tracking": [
    {"item": "跟踪项", "status": "进展", "next_action": "下一步"}
  ],
  "status_note": "一句自然的状态观察（可选，空字符串也行）"
}

字段规则：
- **deliveries**: 只从 action_log 中 category=delivery 的记录生成。没有就空数组。
- **proactive**: 只从 action_log 中 category=proactive 的记录生成。没有就空数组。每条精简：insight ≤ 20字，action ≤ 30字。
- **captured_intents**: 从录音/对话中提取用户提到但可能还没被执行的意图。如果 action_log 里有对应的 intent_followup 记录，status 标 done。
- **prepared_for_today**: 有可以直接用的交付物才写，没有就空数组。如果涉及飞书文档，content 里必须包含完整链接（格式：https://ccnq3wnum0kr.feishu.cn/docx/{doc_token}）。
- **tracking**: 长线事项的进展。

⚠️ 宁可 deliveries 和 proactive 为空，也绝不编造。Brief 的信任感比内容丰富度重要 100 倍。
"""

    # 行动日志是 Brief 的核心依据
    action_log_text = action_summary if action_summary else "（无行动记录 — deliveries 和 proactive 应为空数组）"
    
    user_prompt = f"""=== 行动日志（真正执行过的，如实汇报）===
{action_log_text}

=== 多源数据（用于提取 intents 和 tracking）===
{data_summary[:6000]}

=== 当天记忆日志 ===
{memory_context[:2000]}

=== 当前待办 ===
{todo_context[:1000]}

生成晨间简报。deliveries 和 proactive 只能基于行动日志，不能编造。"""

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


def _format_proactive_entry(p: Dict[str, Any]) -> tuple[str, Optional[str]]:
    """格式化一条 proactive 建议，返回 (文本, suggestion_id)。

    格式示例：
      💡 你提了三次想去福州 → 帮你查了直飞航班，最便宜 ¥420。要帮你锁航班吗？还是再等等？
    """
    insight = p.get("insight", "")
    action = p.get("action", "")
    result = p.get("result", "")
    options: List[str] = p.get("options", [])
    category: str = p.get("category", "general")

    # 拼接正文
    parts = []
    if insight and action:
        parts.append(f"{insight} → {action}")
    elif insight:
        parts.append(insight)
    elif action:
        parts.append(action)
    if result:
        parts.append(result)
    body = "。".join(parts) if parts else ""

    # 拼接自然语言选项
    if options:
        opts_text = "，还是".join(options)
        full_text = f"💡 {body}。{opts_text}？"
    else:
        full_text = f"💡 {body}"

    # 记录到 feedback_tracker
    suggestion_id: Optional[str] = None
    if _FEEDBACK_TRACKER_AVAILABLE and body:
        try:
            suggestion_id = log_suggestion(
                category=category,
                content=full_text,
                options=options,
            )
            # suggestion_id 内部追踪用，不暴露给用户
        except Exception:
            pass

    return full_text, suggestion_id


def format_brief_message(brief: Dict[str, Any]) -> str:
    """Format brief into a natural, human-friendly message.
    
    不要暴露技术细节（日期、数据源、pipeline），像秘书一样汇报：
    - 我帮你做了什么
    - 根据你的习惯/偏好我做了什么
    - 需要你拍板的事
    """
    b = brief.get("brief", {})
    parts: List[str] = []

    parts.append("☀️ 早上好\n")

    # Deliveries — 我帮你做了什么
    deliveries = b.get("deliveries", [])
    if deliveries:
        parts.append("**最近帮你搞定了这些**\n")
        for d in deliveries:
            parts.append(f"📌 **{d['title']}**")
            if d.get("detail"):
                parts.append(f"  {d['detail']}")
            parts.append("")

    # Proactive — 我注意到...所以帮你做了...
    proactive = b.get("proactive", [])
    if proactive:
        parts.append("**注意到你最近的状态，我主动做了这些**\n")
        for p in proactive:
            entry_text, _sid = _format_proactive_entry(p)
            parts.append(entry_text)
            parts.append("")

    # Captured intents — 你提到的我记住了
    intents = b.get("captured_intents", [])
    if intents:
        parts.append("**你提到的这些我都跟进了**\n")
        for i in intents:
            status_icon = {"done": "✅", "in_progress": "🔄", "prepared": "📋"}.get(i.get("status"), "📝")
            quote = i.get("quote", "")
            # 截短引用，不要太长
            if len(quote) > 40:
                quote = quote[:37] + "..."
            parts.append(f'{status_icon} "{quote}"')
            parts.append(f"   → {i.get('action_taken', '')}")
            parts.append("")

    # Prepared — 根据你的情况准备好的
    prepared = b.get("prepared_for_today", [])
    if prepared:
        parts.append("**根据你的情况提前准备了**\n")
        for p in prepared:
            parts.append(f"📎 **{p['title']}**")
            if p.get("content"):
                # 截取前 200 字，避免太长
                content = p["content"]
                # 自动把裸 doc_token 或不完整链接转成带租户域名的完整链接
                import re
                # 修复 feishu.cn/docx/xxx → ccnq3wnum0kr.feishu.cn/docx/xxx
                content = re.sub(
                    r'https?://feishu\.cn/(docx|base|wiki)/',
                    r'https://ccnq3wnum0kr.feishu.cn/\1/',
                    content
                )
                if len(content) > 200:
                    content = content[:197] + "..."
                parts.append(f"  {content}")
            parts.append("")

    # Tracking — 需要你关注/拍板的
    tracking = b.get("tracking", [])
    if tracking:
        parts.append("**需要你关注的**\n")
        for t in tracking:
            parts.append(f"🔄 **{t['item']}**")
            status = t.get("status", "")
            if status:
                parts.append(f"  {status}")
            if t.get("next_action"):
                parts.append(f"  👉 {t['next_action']}")
            parts.append("")

    # Status note — 补充观察
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
