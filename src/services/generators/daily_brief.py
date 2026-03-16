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

    system_prompt = """你是一个私人秘书，每天早上给老板做一句话简报。

## 铁律
1. **只写结论，不写过程** — "发现了X项目，它能做Y，对你的价值是Z"，不写"已开始研究X"
2. **每条信息必须回答 so what** — 没结论的不写，宁可空着
3. **只汇报真实发生的事** — 行动日志里有的才写 deliveries/proactive，没有就空数组
4. **300字以内** — 超过就裁，留最重要的

## 输出结构
输出 JSON，严格按下面的格式：
{
  "conclusions": [
    "XXX项目研究完毕：它能做Y，建议你Z（一句话，含具体名称和结论）",
    "XX任务已完成：结果是Y"
  ],
  "decisions_needed": [
    {"item": "事项名", "option_a": "A方案及优点", "option_b": "B方案及优点"}
  ],
  "system_status": "一切正常",
  "deliveries": [{"title": "做了什么", "detail": "具体结果"}],
  "proactive": [{"insight": "注意到...", "action": "帮你做了...", "result": "结果"}],
  "captured_intents": [{"quote": "用户说的话≤30字", "action_taken": "做了/还没做", "status": "done/in_progress/prepared"}],
  "prepared_for_today": [{"title": "准备了什么", "content": "可直接用的内容"}],
  "tracking": [{"item": "跟踪项", "status": "进展一句话", "next_action": "下一步"}]
}

## 字段规则
- **conclusions**: 从 deliveries + intents + tracking 中提炼真正的结论。格式："X事项：结论是Y"。没结论的不写。
- **decisions_needed**: 需要用户拍板的事，给A/B选项而不是"等待中"。能先做的先做，只有真正需要决策的才放这里。
- **system_status**: 一行，"一切正常"或具体异常。
- **deliveries**: 只从 action_log category=delivery 生成，没有就空数组。
- **proactive**: 只从 action_log category=proactive 生成，没有就空数组。
- **captured_intents**: 从录音/对话提取，若 action_log 有 intent_followup 对应记录则 status=done。
- **prepared_for_today**: 有可直接用的交付物才写，飞书文档必须含完整链接。
- **tracking**: 长线事项，状态必须是结论性的（"完成了X"），不写"进行中"。

⚠️ 宁可 conclusions 只有1条，也绝不编造。Brief 的信任感 > 内容丰富度。
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
    """Format brief into a conclusion-first, secretary-style message.

    结构：
      ☀️ 早安 Brief | M月D日
      📌 结论速览（每条一句话结论）
      🎯 需要你选（A/B 决策项）
      📊 系统状态（一行）
    原则：没结论不写，不超过 300 字。
    """
    import re
    b = brief.get("brief", {})
    date_str = brief.get("date", "")
    parts: List[str] = []

    # 标题
    if date_str:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            title_date = f"{dt.month}月{dt.day}日"
        except Exception:
            title_date = date_str
    else:
        title_date = ""
    parts.append(f"☀️ 早安 Brief{' | ' + title_date if title_date else ''}\n")

    # ---------- 📌 结论速览 ----------
    # 优先用 LLM 生成的 conclusions 字段
    conclusions: List[str] = b.get("conclusions", [])

    # 若 LLM 没输出 conclusions，从 deliveries/intents/tracking 中拼凑
    if not conclusions:
        for d in b.get("deliveries", []):
            title = d.get("title", "")
            detail = d.get("detail", "")
            if title and detail:
                conclusions.append(f"{title}：{detail}")
            elif title:
                conclusions.append(title)
        for i in b.get("captured_intents", []):
            if i.get("status") == "done":
                quote = i.get("quote", "")[:30]
                action = i.get("action_taken", "")
                if quote and action:
                    conclusions.append(f"{quote} → {action}")
        for t in b.get("tracking", []):
            item = t.get("item", "")
            status = t.get("status", "")
            # 过滤掉空洞进展描述
            boring = {"进行中", "已开始", "进行中...", "开始了", "还在进行"}
            if item and status and status not in boring:
                conclusions.append(f"{item}：{status}")

    if conclusions:
        parts.append("📌 结论速览")
        for c in conclusions:
            parts.append(f"- {c}")
        parts.append("")

    # ---------- 🎯 需要你选 ----------
    decisions = b.get("decisions_needed", [])
    # 也从 tracking.next_action 中提取需要决策的项
    for t in b.get("tracking", []):
        na = t.get("next_action", "")
        if na and ("？" in na or "?" in na or "还是" in na or "要不要" in na):
            decisions.append({"item": t.get("item", ""), "option_a": na, "option_b": ""})

    if decisions:
        parts.append("🎯 需要你选")
        for d in decisions:
            item = d.get("item", "")
            oa = d.get("option_a", "")
            ob = d.get("option_b", "")
            if oa and ob:
                parts.append(f"- {item}：{oa} vs {ob}，你选哪个？")
            elif oa:
                parts.append(f"- {item}：{oa}")
        parts.append("")

    # ---------- 📊 系统状态 ----------
    # 优先用 LLM 的 system_status，fallback 到 status_note
    sys_status = b.get("system_status", "") or b.get("status_note", "")
    # 修复飞书链接域名
    if sys_status:
        sys_status = re.sub(
            r'https?://feishu\.cn/(docx|base|wiki)/',
            r'https://ccnq3wnum0kr.feishu.cn/\1/',
            sys_status
        )
    parts.append(f"📊 系统状态")
    parts.append(f"- {sys_status if sys_status else '一切正常'}")

    msg = "\n".join(parts)

    # 硬截断到 300 字（保留标题完整性）
    if len(msg) > 300:
        msg = msg[:297] + "..."

    return msg


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
