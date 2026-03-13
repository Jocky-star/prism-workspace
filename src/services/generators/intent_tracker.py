"""
意图追踪器 — Intent Tracker
输入：录音 key_quotes + 对话中的意图表达
处理：LLM 分类 wish/todo/idea/plan → 生成响应
  - wish → 记录，可触发搜索
  - todo → 写入跟踪文件
  - idea → 记录到 idea capture
  - plan → 记录并跟踪

运行方式：
  python3 src/services/generators/intent_tracker.py --date 2026-03-12 --dry-run
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

from src.services.data_sources import AudioDataSource, ChatDataSource
from src.services.llm_client import llm_complete

OUTPUT_DIR = SERVICES_OUTPUT_DIR
INTENTS_TRACKING_FILE = MEMORY_DIR / "intelligence" / "intents.json"
IDEAS_FILE = MEMORY_DIR / "idea-capture.md"
TODO_FILE = MEMORY_DIR / "todo.md"


INTENT_TYPES = ["wish", "todo", "idea", "plan", "preference", "observation"]


def extract_raw_quotes(date: str, audio_data: Dict, chat_data: Dict) -> List[str]:
    """Collect candidate quotes/messages for intent analysis."""
    candidates: List[str] = []

    # From audio key quotes
    for q in audio_data.get("key_quotes", []):
        text = q.get("text", "").strip()
        if len(text) > 5:
            candidates.append(f"[录音] {text}")

    # From chat user messages
    for m in chat_data.get("messages", []):
        if m.get("source") == "chat":
            text = m.get("text", "").strip()
            if 5 < len(text) < 300:
                candidates.append(f"[对话] {text}")

    return candidates


def classify_intents(quotes: List[str], dry_run: bool = False) -> List[Dict[str, Any]]:
    """Use LLM to classify a batch of quotes into intent types."""
    if not quotes:
        return []

    # Batch into chunks of 20
    all_intents: List[Dict] = []
    chunk_size = 20

    for i in range(0, len(quotes), chunk_size):
        chunk = quotes[i: i + chunk_size]
        quotes_text = "\n".join(f"{j+1}. {q}" for j, q in enumerate(chunk))

        system_prompt = (
            "你是一个意图分析器。"
            "分析用户的话语，提取有意义的意图。\n"
            "意图类型：\n"
            "  wish — 愿望（想要某物/想去某地/想体验某事）\n"
            "  todo — 待办（需要去做的具体任务）\n"
            "  idea — 想法/创意（值得记录的灵感）\n"
            "  plan — 计划（较长期的规划）\n"
            "  preference — 习惯/偏好（设备使用习惯、时间偏好、环境偏好等，如'中午不开灯'、'晚上喜欢暖光'）\n"
            "  observation — 无意图，跳过\n"
            "输出 JSON 数组，每项包含：\n"
            '  {"quote": "原文", "type": "意图类型", "content": "提炼后的意图", "confidence": 0-1}\n'
            "只提取 confidence > 0.6 的项。"
            "只输出 JSON 数组，不要其他内容。"
        )

        user_prompt = f"以下是用户的话语，请提取意图：\n\n{quotes_text}"

        raw = llm_complete(
            prompt=user_prompt,
            system=system_prompt,
            max_tokens=800,
            temperature=0.3,
            dry_run=dry_run,
        )

        if dry_run:
            all_intents.append({
                "quote": chunk[0] if chunk else "",
                "type": "todo",
                "content": "[DRY-RUN] 示例待办",
                "confidence": 0.9,
            })
            continue

        # Parse
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            items = json.loads(raw)
            if isinstance(items, list):
                all_intents.extend(items)
        except json.JSONDecodeError:
            pass

    return all_intents


def process_intents(intents: List[Dict], date: str, dry_run: bool = False) -> Dict[str, List]:
    """Route intents to appropriate handlers."""
    by_type: Dict[str, List] = {t: [] for t in INTENT_TYPES}

    for intent in intents:
        t = intent.get("type", "observation")
        if t in by_type:
            by_type[t].append(intent)

    if not dry_run:
        _append_todos(by_type.get("todo", []), date)
        _append_ideas(by_type.get("idea", []), date)
        _apply_preferences(by_type.get("preference", []), date)
        _update_intents_file(intents, date)

    return by_type


def _append_todos(todos: List[Dict], date: str) -> None:
    if not todos:
        return
    lines = [f"\n<!-- {date} from intent_tracker -->"]
    for t in todos:
        lines.append(f"- [ ] {t.get('content', '')}")
    with open(TODO_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _append_ideas(ideas: List[Dict], date: str) -> None:
    if not ideas:
        return
    lines = [f"\n## {date} (from intent_tracker)"]
    for idea in ideas:
        lines.append(f"- {idea.get('content', '')}")
    with open(IDEAS_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _apply_preferences(prefs: List[Dict], date: str) -> None:
    """Apply preference intents to device/service configuration."""
    if not prefs:
        return
    try:
        from src.services.device_preferences import add_lamp_rule
        from src.services.llm_client import llm_complete
        
        for pref in prefs:
            content = pref.get("content", "")
            # Use LLM to parse preference into structured rule
            raw = llm_complete(
                prompt=f"用户偏好: \"{content}\"\n\n"
                       f"解析为 JSON：\n"
                       f'{{"device": "lamp"|"other", "hours": [13,14], "scene": "off"|"focus"|"relax"|"night"|"normal", "reason": "简短描述"}}\n'
                       f"如果不是设备偏好，返回 {{\"device\": \"other\"}}。只输出 JSON。",
                system="你是一个偏好解析器。从自然语言中提取设备控制规则。",
                max_tokens=200,
                temperature=0.1,
            )
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```json", 1)[-1].split("```", 1)[0] if "```json" in raw else raw.split("```", 1)[1].split("```", 1)[0]
            import json
            parsed = json.loads(raw.strip())
            
            if parsed.get("device") == "lamp" and parsed.get("hours"):
                target_scene = parsed.get("scene", "off")
                add_lamp_rule(
                    hours=parsed["hours"],
                    scene=target_scene,
                    reason=parsed.get("reason", content),
                    source=f"intent:{date}",
                )
                print(f"  ✅ 已应用偏好: 台灯 {parsed['hours']} → {target_scene} ({parsed.get('reason','')})")
                
                # 立即执行：如果当前时间在偏好范围内，马上切换台灯
                try:
                    from datetime import datetime, timezone, timedelta
                    current_hour = datetime.now(timezone(timedelta(hours=8))).hour
                    if current_hour in parsed["hours"]:
                        import importlib
                        sys_path_bak = sys.path[:]
                        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'actions', 'integrations'))
                        from mijia_lamp import set_scene
                        sys.path[:] = sys_path_bak
                        ok = set_scene(target_scene)
                        print(f"  ⚡ 立即执行: set_scene('{target_scene}') → {'成功' if ok else '失败'}")
                except Exception as ex:
                    print(f"  ⚠️ 立即执行失败（偏好已保存，下次检测时生效）: {ex}")
    except Exception as e:
        print(f"  ⚠️ 偏好应用失败: {e}")


def _update_intents_file(intents: List[Dict], date: str) -> None:
    existing: Dict = {}
    if INTENTS_TRACKING_FILE.exists():
        try:
            with open(INTENTS_TRACKING_FILE, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    records = existing.get("records", [])
    records.append({
        "date": date,
        "intents": intents,
        "processed_at": datetime.now().isoformat(),
    })
    # Keep last 30 days
    records = records[-30:]
    existing["records"] = records
    existing["last_updated"] = datetime.now().isoformat()

    with open(INTENTS_TRACKING_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def generate_intent_tracking(date: str, dry_run: bool = False) -> Dict[str, Any]:
    audio_src = AudioDataSource()
    chat_src = ChatDataSource()

    audio_data = audio_src.get_today_data(date)
    chat_data = chat_src.get_today_data(date)

    quotes = extract_raw_quotes(date, audio_data, chat_data)

    result: Dict[str, Any] = {
        "generator": "intent_tracker",
        "date": date,
        "generated_at": datetime.now().isoformat(),
        "dry_run": dry_run,
        "input_quote_count": len(quotes),
        "intents": [],
        "by_type": {},
    }

    if not quotes:
        result["note"] = "No quotes found for this date"
        return result

    intents = classify_intents(quotes, dry_run=dry_run)
    result["intents"] = intents
    result["intent_count"] = len(intents)

    by_type = process_intents(intents, date, dry_run=dry_run)
    result["by_type"] = {k: len(v) for k, v in by_type.items() if v}

    return result


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
    existing["intent_tracker"] = result
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Track intents from audio and chat")
    parser.add_argument(
        "--date",
        default=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        help="Date (YYYY-MM-DD)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    print(f"Running intent tracker for {args.date} (dry_run={args.dry_run})...")
    result = generate_intent_tracking(args.date, dry_run=args.dry_run)

    print(f"\n📝 Input quotes: {result.get('input_quote_count', 0)}")
    print(f"🎯 Intents found: {result.get('intent_count', 0)}")
    print(f"📊 By type: {result.get('by_type', {})}")

    for intent in result.get("intents", [])[:5]:
        t = intent.get("type", "?")
        content = intent.get("content", "")
        conf = intent.get("confidence", 0)
        print(f"  [{t}] {content} ({conf:.0%})")

    if args.save and not args.dry_run:
        path = save_result(result, args.date)
        print(f"\n✅ Saved to {path}")
