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


def _build_intelligence_summary(data: Dict[str, Any]) -> str:
    """从 intelligence 数据源提取'我对你的长期理解'摘要。"""
    intel = data.get("intelligence", {})
    if not intel.get("available"):
        return "（暂无长期理解数据）"

    parts: List[str] = []

    # 用户画像
    profile = intel.get("profile", {})
    if profile:
        prefs = profile.get("preferences", {})
        top_topics = prefs.get("top_topics", [])[:6]
        values = prefs.get("values", [])[:5]
        comm_style = prefs.get("communication_style", "")
        schedule = profile.get("schedule", {})
        parts.append(
            f"【用户画像】\n"
            f"关注领域: {', '.join(top_topics)}\n"
            f"核心价值观: {', '.join(values)}\n"
            f"沟通风格: {comm_style}\n"
            f"作息: 起床 {schedule.get('wake_up_median','')} / 睡觉 {schedule.get('sleep_median','')} / 日均工作 {schedule.get('work_hours_avg','')}h"
        )

    # 行为模式（只提关键信息）
    patterns = intel.get("patterns", {})
    if patterns:
        peak_hours = []
        routine = patterns.get("daily_routine", {}).get("weekday", {})
        for hour_range, info in routine.items():
            if info.get("top_activity") in ("work", "meeting") and info.get("avg_minutes", 0) > 20:
                peak_hours.append(f"{hour_range}时({info['top_activity']})")
        if peak_hours:
            parts.append(f"【工作高峰】{', '.join(peak_hours[:4])}")

    # 活跃意图（高优先级）
    intents = intel.get("intents", {})
    active_intents = intents.get("active", []) if intents else []
    high_priority = [i for i in active_intents if i.get("seriousness", 0) >= 4][:8]
    if high_priority:
        intent_texts = [f"- [{i.get('type','?')}] {i.get('text','')[:60]}" for i in high_priority]
        parts.append("【高优先级待跟进】\n" + "\n".join(intent_texts))

    # 最近洞察（最新5条）
    insights = intel.get("insights", [])
    if insights:
        recent_insights = [i for i in insights if i.get("priority", 0) >= 3][-5:]
        if recent_insights:
            insight_texts = [f"- {i.get('text','')[:80]}" for i in recent_insights]
            parts.append("【近期洞察】\n" + "\n".join(insight_texts))

    return "\n\n".join(parts) if parts else "（intelligence 数据存在但解析为空）"


def _build_conversation_summary(data: Dict[str, Any]) -> str:
    """从 conversation 数据源提取'最近你关注什么'的直接证据。"""
    conv = data.get("conversation", {})
    if not conv.get("available"):
        return "（暂无近期对话数据）"

    parts: List[str] = []

    # 近期用户聊天消息（最重要的直接证据）
    recent_msgs = conv.get("recent_chat_messages", [])
    if recent_msgs:
        # 按日期分组，只取最近3天，每天最多10条
        from collections import defaultdict
        by_date: Dict[str, List] = defaultdict(list)
        for m in recent_msgs:
            d = (m.get("date") or m.get("timestamp", ""))[:10]
            by_date[d].append(m)
        msg_parts: List[str] = []
        for d in sorted(by_date.keys(), reverse=True)[:3]:
            msgs = by_date[d][-10:]
            lines = [f"  [{m.get('time','')[0:5] or m.get('timestamp','')[11:16]}] {m.get('text','')[:150]}" for m in msgs]
            msg_parts.append(f"[{d}]\n" + "\n".join(lines))
        parts.append("【近期对话（用户原话）】\n" + "\n\n".join(msg_parts))

    # 记忆日志（最近2天的，提供上下文）
    memories = conv.get("recent_memories", [])
    if memories:
        recent_2 = memories[:2]  # 最近2天
        mem_parts = []
        for m in recent_2:
            snippet = m.get("content", "")
            # 从记忆日志中提取有信息量的片段（避免纯模板内容）
            lines = [l.strip() for l in snippet.split("\n") if l.strip() and not l.startswith("#") and len(l.strip()) > 10]
            if lines:
                mem_parts.append(f"[{m['date']}] " + " / ".join(lines[:5]))
        if mem_parts:
            parts.append("【近期记忆摘要】\n" + "\n".join(mem_parts))

    # 用户反馈偏好（有明确态度的才有价值）
    feedback = conv.get("feedback", {})
    adopted = feedback.get("adopted_suggestions", [])
    ignored = feedback.get("ignored_suggestions", [])
    pref_model = feedback.get("preference_model", {})

    if adopted or ignored or pref_model:
        fb_parts: List[str] = []
        if adopted:
            adopted_texts = [f"  ✓ {s.get('content','')[:60]} → 回应: {s.get('user_response','')}" for s in adopted[-5:]]
            fb_parts.append("用户接受的建议:\n" + "\n".join(adopted_texts))
        if ignored:
            ignored_texts = [f"  ✗ {s.get('content','')[:60]}" for s in ignored[-3:]]
            fb_parts.append("用户忽略的建议（以后少做）:\n" + "\n".join(ignored_texts))
        if pref_model:
            liked = pref_model.get("liked_categories", [])
            disliked = pref_model.get("disliked_categories", [])
            if liked or disliked:
                fb_parts.append(f"偏好模型: 喜欢={liked}, 不喜欢={disliked}")
        parts.append("【用户反馈偏好】\n" + "\n".join(fb_parts))

    return "\n\n".join(parts) if parts else "（对话数据存在但解析为空）"


def _build_action_log_summary(data: Dict[str, Any]) -> str:
    """从 action_log 数据源提取'昨天实际完成的事'的事实摘要。"""
    al = data.get("action_log", {})
    if not al.get("available"):
        # 也尝试从旧的 action_log 模块读取
        return "（无行动日志数据）"

    parts: List[str] = []

    yesterday_actions = al.get("yesterday_actions", [])
    today_actions = al.get("today_actions", [])

    if yesterday_actions:
        lines = [f"  [{a.get('category','?')}] {a.get('title','')} — {a.get('detail','')[:80]}" for a in yesterday_actions[-20:]]
        parts.append("【昨日行动】\n" + "\n".join(lines))

    if today_actions:
        lines = [f"  [{a.get('category','?')}] {a.get('title','')} — {a.get('detail','')[:80]}" for a in today_actions[-10:]]
        parts.append("【今日早间行动】\n" + "\n".join(lines))

    if not parts:
        return "（行动日志为空 — deliveries 和 proactive 应为空数组）"

    return "\n\n".join(parts)


def _build_supplementary_summary(data: Dict[str, Any]) -> str:
    """构建补充数据摘要（audio/chat/vision/habit/weather）。"""
    parts: List[str] = []

    # Audio: 录音场景
    audio = data.get("audio", {})
    if audio.get("available"):
        scenes_text = []
        for sc in (audio.get("scenes", []) or [])[:5]:
            summary = sc.get("summary", "")
            activity = sc.get("activity", "unknown")
            time = sc.get("start_time", "")
            quotes = [q.get("text", "") for q in sc.get("key_quotes", []) if q.get("text")]
            scenes_text.append(f"[{time}]({activity}) {summary} | 原话: {quotes[:2]}")
        if scenes_text:
            parts.append("【录音场景】\n" + "\n".join(scenes_text))

        for mf in (audio.get("macro_frames", []) or [])[:3]:
            topics = mf.get("key_topics", [])
            mood = mf.get("mood_or_tone", "")
            outcomes = mf.get("outcomes", [])
            parts.append(f"[宏观] 话题={topics}, 情绪={mood}, 成果={outcomes}")

    # Vision
    vision = data.get("vision", {})
    if vision.get("available") and vision.get("observation_count", 0) > 0:
        parts.append(
            f"【摄像头】观察{vision.get('observation_count',0)}次, 状态={vision.get('moods_seen',[])}"
        )

    # Habit
    habit = data.get("habit", {})
    if habit.get("available"):
        rules = habit.get("behavior_rules", {})
        rule_texts = [r.get("rule", "") for r in (rules.get("rules", []) or [])[:3]]
        if rule_texts:
            parts.append(f"【行为规律】{rule_texts}")

    # Weather
    weather = data.get("weather", {})
    if weather.get("available"):
        wd = weather.get("data", {})
        temp = wd.get("temperature", wd.get("temp", ""))
        desc = wd.get("description", wd.get("condition", ""))
        if temp or desc:
            parts.append(f"【天气】{desc} {temp}")

    return "\n".join(parts) if parts else "（无补充数据）"


def _build_data_summary(data: Dict[str, Any]) -> str:
    """Build comprehensive data summary from all sources.

    已被细分为4个专项函数，此函数保留向后兼容，返回完整摘要。
    """
    return _build_supplementary_summary(data)


def generate_brief(date: str, dry_run: bool = False) -> Dict[str, Any]:
    """
    Generate action-oriented daily brief.
    
    核心原则：Brief 只汇报真正做过的事情，基于对用户的长期理解生成有价值的内容。
    - intelligence 数据：了解用户是谁，他关注什么
    - conversation 数据：最近他在关注/讨论什么
    - action_log：系统昨天实际做了什么（真实依据）
    - audio/chat/vision：补充信号
    """
    reg = DataSourceRegistry()
    data = reg.get_all_data(date)

    # 分层构建数据摘要
    intelligence_summary = _build_intelligence_summary(data)
    conversation_summary = _build_conversation_summary(data)
    action_log_summary = _build_action_log_summary(data)
    supplementary_summary = _build_supplementary_summary(data)

    system_prompt = """你是私人秘书星星。基于对老板的长期理解和最近的互动，生成今日简报。

## 铁律（违反任何一条直接删掉该条目）
1. **只写结论，不写过程** — "发现了X，它能做Y，对你的价值是Z"，不写"已开始研究X"
2. **每条必须有具体名称+具体结果** — "发现了重磅项目"是废话，"发现了 Qwen3-235B 开源，reasoning 能力超 DeepSeek-R1，可用于替换本地推理模型"才是结论
3. **自检：这条删掉老板会损失信息吗？** — 如果不会，直接删
4. **禁止词：待评估、待调研、需确认、待跟进、进行中、已开始** — 包含这些词的条目一律删除，如果你不知道结论就别写
5. **只汇报真实发生的事** — 行动日志里有的才写 deliveries/proactive，没有就空数组
6. **300字以内** — 超过就裁，留最重要的

## 输出结构
输出 JSON，严格按下面的格式：
{
  "key_conclusions": [
    "XXX 已完成：具体结果是 Y，对你意味着 Z"
  ],
  "minor_updates": [
    "XX 小进展：一句话说清楚"
  ],
  "decisions_needed": [
    {"item": "事项名", "option_a": "A方案（优点）", "option_b": "B方案（优点）"}
  ],
  "system_status": "一切正常",
  "deliveries": [{"title": "做了什么", "detail": "具体结果"}],
  "proactive": [{"insight": "注意到...", "action": "帮你做了...", "result": "结果"}],
  "captured_intents": [{"quote": "用户说的话≤30字", "action_taken": "具体做了什么+结果", "status": "done/blocked/prepared"}],
  "tracking": [{"item": "跟踪项", "status": "具体结论", "next_action": "下一步"}]
}

## 字段规则
- **key_conclusions**: 最重要的 1-3 条结论，影响老板决策或需要他知道的大事。每条必须包含具体事实和 so what。格式："X事项：查了/做了Y，结论是Z"。不写"需确认""待跟进"——如果你不知道结论，先去查再写。
- **minor_updates**: 次要但值得一提的进展，3-5 条。一句话点到即止。
- **decisions_needed**: 真正需要老板拍板的，给清晰的 A/B 选项。如果你能先做调研再问，就先做。
- **system_status**: 一行，"一切正常"或具体异常。
- **deliveries**: 只从 action_log 有记录的生成，没有就空数组。
- **proactive**: 只从 action_log 有记录的生成，没有就空数组。
- **captured_intents**: 从最近对话中提取用户表达的意图/需求。action_taken 必须写具体做了什么+结果，不能写"已开始"。
- **tracking**: 基于用户高优先级意图，汇报具体进展。不写"进行中"——写清楚到了哪一步、卡在什么地方。

## 生成要求
1. 基于对老板的长期理解（画像、价值观、工作风格），判断哪些信息对他有价值
2. 结合最近对话中他关注的事情，给出进展结论
3. 如果有他之前的反馈（比如忽略了某类建议），这次要体现改进（不再重复）
4. 所有结论都要有具体内容，不是空洞的状态描述
5. 300字以内，宁缺勿滥

⚠️ 宁可整个 Brief 只有1条结论甚至0条，也绝不输出模糊的废话。Brief 的信任感 > 内容丰富度。
⚠️ 最终输出前逐条自检：这条包含"待评估/待调研/需确认/待跟进/进行中/已开始/发现了XX（但没说是什么）"吗？包含就删。"""

    user_prompt = f"""## 你对老板的理解
{intelligence_summary}

## 最近的对话和反馈
{conversation_summary[:3000]}

## 昨天实际完成的事
{action_log_summary}

## 补充数据
{supplementary_summary[:2000]}

生成今日晨间简报。deliveries 和 proactive 只能基于行动日志，不能编造。"""

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
        "generator": "daily_brief_v3",
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

    # ---------- 🔴 重要结论 ----------
    key_conclusions: List[str] = b.get("key_conclusions", [])
    # 兼容旧版 conclusions 字段
    if not key_conclusions:
        key_conclusions = b.get("conclusions", [])

    # 硬过滤：删掉废话条目
    _VAGUE_WORDS = ["待评估", "待调研", "需确认", "待跟进", "进行中", "已开始", "待详细", "需要评估", "有待", "尚未", "待启动", "待完成", "待推进", "待确认", "待定", "待处理"]
    key_conclusions = [c for c in key_conclusions if not any(w in c for w in _VAGUE_WORDS)]

    if key_conclusions:
        parts.append("🔴 重要")
        for c in key_conclusions:
            parts.append(f"- {c}")
        parts.append("")

    # ---------- 🔵 常规跟进 ----------
    minor_updates: List[str] = b.get("minor_updates", [])
    # fallback: 从 tracking/intents 中拼
    if not minor_updates:
        for t in b.get("tracking", []):
            item = t.get("item", "")
            status = t.get("status", "")
            boring = {"进行中", "已开始", "进行中...", "开始了", "还在进行", "需确认"}
            if item and status and status not in boring:
                minor_updates.append(f"{item}：{status}")
        for i in b.get("captured_intents", []):
            if i.get("status") == "done":
                quote = i.get("quote", "")[:30]
                action = i.get("action_taken", "")
                if quote and action:
                    minor_updates.append(f"{quote} → {action}")

    # 同样过滤废话
    minor_updates = [m for m in minor_updates if not any(w in m for w in _VAGUE_WORDS)]

    if minor_updates:
        parts.append("🔵 跟进")
        for m in minor_updates:
            parts.append(f"- {m}")
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
