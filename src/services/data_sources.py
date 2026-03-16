"""
多数据源适配器 — 插件注册制

每个数据源实现：
  - get_today_data(date) → dict
  - is_available() → bool  (检查数据是否存在)
  - description → str      (给用户看的说明)
  - data_path → str        (数据目录/文件路径)

DataSourceRegistry 自动扫描只注册可用的数据源。
新数据源只需继承 DataSource 并加到 ALL_SOURCES 列表。
"""

from __future__ import annotations

import glob
import json
import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys as _sys
from pathlib import Path as _Path
_ws = _Path(__file__).resolve()
while _ws.name != "src" and _ws != _ws.parent:
    _ws = _ws.parent
if _ws.name == "src":
    _sys.path.insert(0, str(_ws.parent))

from src.services.config import WORKSPACE, MEMORY_DIR, INTELLIGENCE_DIR


class DataSource(ABC):
    """Abstract data-source adapter."""

    name: str = "unknown"
    description: str = "未知数据源"

    @abstractmethod
    def get_today_data(self, date: str) -> Dict[str, Any]:
        """Load data for date (YYYY-MM-DD). Never raises."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this data source has data in the current environment."""

    @property
    def data_path(self) -> str:
        """Return the data path for display."""
        return ""


# ── Audio (录音 JSON) ──────────────────────────────────────────────

class AudioDataSource(DataSource):
    name = "audio"
    description = "录音数据（mf_scene_v2.x JSON）"

    RAW_JSON_DIR = WORKSPACE / "skills" / "audio-daily-insight" / "raw_json"

    def is_available(self) -> bool:
        return self.RAW_JSON_DIR.exists() and bool(list(self.RAW_JSON_DIR.glob("*.json")))

    @property
    def data_path(self) -> str:
        return str(self.RAW_JSON_DIR)

    def get_today_data(self, date: str) -> Dict[str, Any]:
        base = {"source": self.name, "date": date, "available": False}
        try:
            compact = date.replace("-", "")
            files = sorted(glob.glob(str(self.RAW_JSON_DIR / f"{compact}*.json")))
            if not files:
                return base

            with open(files[-1], encoding="utf-8") as f:
                raw = json.load(f)

            scenes = raw.get("scenes", [])
            macro_frames = raw.get("macro_frames", [])

            key_quotes: List[Dict] = []
            for s in scenes:
                for q in s.get("key_quotes", []):
                    key_quotes.append({
                        "scene_id": s.get("id"),
                        "activity": s.get("activity", {}).get("label") if isinstance(s.get("activity"), dict) else s.get("activity"),
                        "speaker": q.get("speaker"),
                        "text": q.get("text", ""),
                    })

            moods = [mf.get("mood_or_tone", "") for mf in macro_frames if mf.get("mood_or_tone")]
            activities: Dict[str, int] = {}
            for s in scenes:
                act = s.get("activity", {})
                label = act.get("label", "unknown") if isinstance(act, dict) else str(act)
                activities[label] = activities.get(label, 0) + 1

            return {
                **base, "available": True, "file": files[-1],
                "version": raw.get("version"),
                "macro_frames": macro_frames, "scenes": scenes,
                "key_quotes": key_quotes, "moods": moods,
                "activities": activities, "scene_count": len(scenes),
            }
        except Exception as e:
            base["error"] = str(e)
            return base


# ── Chat (对话记录) ───────────────────────────────────────────────

class ChatDataSource(DataSource):
    name = "chat"
    description = "对话记录（chat_messages.jsonl）"

    MESSAGES_FILE = INTELLIGENCE_DIR / "chat_messages.jsonl"

    def is_available(self) -> bool:
        return self.MESSAGES_FILE.exists() and self.MESSAGES_FILE.stat().st_size > 0

    @property
    def data_path(self) -> str:
        return str(self.MESSAGES_FILE)

    @staticmethod
    def _read_jsonl_for_date(path: Path, date: str) -> List[Dict]:
        results = []
        if not path.exists():
            return results
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    obj_date = (obj.get("date") or obj.get("timestamp", ""))[:10]
                    if obj_date == date:
                        results.append(obj)
                except json.JSONDecodeError:
                    continue
        return results

    def get_today_data(self, date: str) -> Dict[str, Any]:
        base = {"source": self.name, "date": date, "available": False}
        try:
            messages = self._read_jsonl_for_date(self.MESSAGES_FILE, date)
            if not messages:
                return base
            user_msgs = [m for m in messages if m.get("source") == "chat"]
            return {
                **base, "available": True,
                "message_count": len(messages),
                "user_message_count": len(user_msgs),
                "messages": messages,
            }
        except Exception as e:
            base["error"] = str(e)
            return base


# ── Vision (摄像头) ──────────────────────────────────────────────

class VisionDataSource(DataSource):
    name = "vision"
    description = "摄像头观察记录（visual/YYYY-MM-DD.jsonl）"

    VISUAL_DIR = MEMORY_DIR / "visual"

    def is_available(self) -> bool:
        return self.VISUAL_DIR.exists() and bool(list(self.VISUAL_DIR.glob("*.jsonl")))

    @property
    def data_path(self) -> str:
        return str(self.VISUAL_DIR)

    def get_today_data(self, date: str) -> Dict[str, Any]:
        base = {"source": self.name, "date": date, "available": False}
        try:
            jsonl_path = self.VISUAL_DIR / f"{date}.jsonl"
            observations: List[Dict] = []
            if jsonl_path.exists():
                with open(jsonl_path, encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            try:
                                observations.append(json.loads(line))
                            except json.JSONDecodeError:
                                continue

            if not observations:
                return base

            moods_seen = [o.get("mood") for o in observations if o.get("mood")]
            return {
                **base, "available": True,
                "observation_count": len(observations),
                "observations": observations,
                "moods_seen": moods_seen,
            }
        except Exception as e:
            base["error"] = str(e)
            return base


# ── Habit (行为数据) ─────────────────────────────────────────────

class HabitDataSource(DataSource):
    name = "habit"
    description = "行为预测数据（habits/behavior_rules.json）"

    HABITS_DIR = MEMORY_DIR / "habits"

    def is_available(self) -> bool:
        return self.HABITS_DIR.exists() and (self.HABITS_DIR / "behavior_rules.json").exists()

    @property
    def data_path(self) -> str:
        return str(self.HABITS_DIR)

    def get_today_data(self, date: str) -> Dict[str, Any]:
        base = {"source": self.name, "date": date, "available": False}
        try:
            result: Dict[str, Any] = {**base, "available": True}
            for fname, key in [("behavior_rules.json", "behavior_rules"), ("profile.json", "habit_profile")]:
                fp = self.HABITS_DIR / fname
                if fp.exists():
                    with open(fp, encoding="utf-8") as f:
                        result[key] = json.load(f)
            return result
        except Exception as e:
            base["error"] = str(e)
            return base


# ── Weather (天气) ───────────────────────────────────────────────

class WeatherDataSource(DataSource):
    name = "weather"
    description = "天气数据（weather.json）"

    def is_available(self) -> bool:
        return any(p.exists() for p in self._candidates())

    @property
    def data_path(self) -> str:
        for p in self._candidates():
            if p.exists():
                return str(p)
        return str(MEMORY_DIR / "weather.json")

    def _candidates(self) -> List[Path]:
        return [MEMORY_DIR / "weather.json", MEMORY_DIR / "prism_weather.json"]

    def get_today_data(self, date: str) -> Dict[str, Any]:
        base = {"source": self.name, "date": date, "available": False}
        try:
            for p in self._candidates():
                if p.exists():
                    with open(p, encoding="utf-8") as f:
                        return {**base, "available": True, "data": json.load(f)}
            return base
        except Exception as e:
            base["error"] = str(e)
            return base


# ── Memory (每日记忆) ────────────────────────────────────────────

class MemoryDataSource(DataSource):
    name = "memory"
    description = "每日记忆日志（memory/YYYY-MM-DD.md）"

    def is_available(self) -> bool:
        return bool(list(MEMORY_DIR.glob("20??-??-??.md")))

    @property
    def data_path(self) -> str:
        return str(MEMORY_DIR)

    def get_today_data(self, date: str) -> Dict[str, Any]:
        base = {"source": self.name, "date": date, "available": False}
        try:
            path = MEMORY_DIR / f"{date}.md"
            if not path.exists():
                return base
            with open(path, encoding="utf-8") as f:
                content = f.read()
            return {**base, "available": True, "content": content, "size": len(content)}
        except Exception as e:
            base["error"] = str(e)
            return base


# ── Intelligence (长期理解层) ─────────────────────────────────────

class IntelligenceDataSource(DataSource):
    """读取 memory/intelligence/ 下的所有理解层产出 — 对用户的长期理解。

    这些数据不是按天的，而是持续积累的快照，每次生成 Brief 都应该作为背景参考。
    get_today_data 返回最新的完整数据，忽略 date 参数。
    """

    name = "intelligence"
    description = "用户长期理解（profile/patterns/intents/insights）"

    def is_available(self) -> bool:
        return INTELLIGENCE_DIR.exists() and (
            (INTELLIGENCE_DIR / "profile.json").exists()
            or (INTELLIGENCE_DIR / "patterns.json").exists()
            or (INTELLIGENCE_DIR / "insights.jsonl").exists()
        )

    @property
    def data_path(self) -> str:
        return str(INTELLIGENCE_DIR)

    def get_today_data(self, date: str) -> Dict[str, Any]:
        base = {"source": self.name, "date": date, "available": False}
        try:
            result: Dict[str, Any] = {**base}

            # profile.json — 用户画像
            profile_path = INTELLIGENCE_DIR / "profile.json"
            if profile_path.exists():
                with open(profile_path, encoding="utf-8") as f:
                    result["profile"] = json.load(f)

            # relationships.json — 社交关系图谱
            rel_path = INTELLIGENCE_DIR / "relationships.json"
            if rel_path.exists():
                with open(rel_path, encoding="utf-8") as f:
                    result["relationships"] = json.load(f)

            # patterns.json — 行为模式
            pat_path = INTELLIGENCE_DIR / "patterns.json"
            if pat_path.exists():
                with open(pat_path, encoding="utf-8") as f:
                    result["patterns"] = json.load(f)

            # intents.json — 历史意图（todo/wish/idea/plan）
            int_path = INTELLIGENCE_DIR / "intents.json"
            if int_path.exists():
                with open(int_path, encoding="utf-8") as f:
                    result["intents"] = json.load(f)

            # insights.jsonl — 洞察记录（最近 30 条）
            ins_path = INTELLIGENCE_DIR / "insights.jsonl"
            if ins_path.exists():
                insights: List[Dict] = []
                with open(ins_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                insights.append(json.loads(line))
                            except json.JSONDecodeError:
                                continue
                result["insights"] = insights[-30:]  # 只取最近30条

            # pipeline_state.json — 管线状态
            ps_path = INTELLIGENCE_DIR / "pipeline_state.json"
            if ps_path.exists():
                with open(ps_path, encoding="utf-8") as f:
                    result["pipeline_state"] = json.load(f)

            # 判断是否有任何有效数据
            has_data = any(
                k in result for k in ("profile", "patterns", "intents", "insights")
            )
            result["available"] = has_data
            return result
        except Exception as e:
            base["error"] = str(e)
            return base


# ── Conversation (对话历史) ──────────────────────────────────────

class ConversationDataSource(DataSource):
    """读取用户和星星的对话历史：每日记忆日志、聊天消息、反馈记录。

    这是"最近你关注什么"的直接证据。
    """

    name = "conversation"
    description = "对话历史与反馈（近7日记忆日志+聊天消息+用户反馈）"

    FEEDBACK_DIR = MEMORY_DIR / "feedback"
    CHAT_MESSAGES_FILE = INTELLIGENCE_DIR / "chat_messages.jsonl"
    CHAT_EVENTS_FILE = INTELLIGENCE_DIR / "chat_events.jsonl"

    def is_available(self) -> bool:
        return (
            self.CHAT_MESSAGES_FILE.exists()
            or bool(list(MEMORY_DIR.glob("20??-??-??.md")))
            or self.FEEDBACK_DIR.exists()
        )

    @property
    def data_path(self) -> str:
        return str(MEMORY_DIR)

    @staticmethod
    def _read_jsonl_all(path: Path) -> List[Dict]:
        """读取 jsonl 全部内容。"""
        results: List[Dict] = []
        if not path.exists():
            return results
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            results.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except Exception:
            pass
        return results

    def get_today_data(self, date: str) -> Dict[str, Any]:
        base = {"source": self.name, "date": date, "available": False}
        try:
            result: Dict[str, Any] = {**base}

            # 最近7天的记忆日志（含对话记录）
            from datetime import datetime as _dt, timedelta as _td
            date_dt = _dt.strptime(date, "%Y-%m-%d")
            recent_memories: List[Dict[str, str]] = []
            for delta in range(7):
                d = (date_dt - _td(days=delta)).strftime("%Y-%m-%d")
                mem_path = MEMORY_DIR / f"{d}.md"
                if mem_path.exists():
                    try:
                        with open(mem_path, encoding="utf-8") as f:
                            content = f.read()
                        # 截取最多 1500 字，保留后半段（更新内容）
                        recent_memories.append({
                            "date": d,
                            "content": content[-1500:] if len(content) > 1500 else content,
                        })
                    except Exception:
                        continue
            result["recent_memories"] = recent_memories

            # 聊天消息（最近 3 天的，最多 100 条用户消息）
            all_msgs = self._read_jsonl_all(self.CHAT_MESSAGES_FILE)
            from datetime import datetime as _dt2, timedelta as _td2
            cutoff = (_dt2.strptime(date, "%Y-%m-%d") - _td2(days=3)).strftime("%Y-%m-%d")
            recent_msgs = [
                m for m in all_msgs
                if (m.get("date") or m.get("timestamp", ""))[:10] >= cutoff
                and m.get("source") == "chat"
            ]
            # 只保留最近 100 条
            result["recent_chat_messages"] = recent_msgs[-100:]

            # 聊天事件（最近 2 天）
            all_events = self._read_jsonl_all(self.CHAT_EVENTS_FILE)
            cutoff2 = (_dt2.strptime(date, "%Y-%m-%d") - _td2(days=2)).strftime("%Y-%m-%d")
            recent_events = [
                e for e in all_events
                if (e.get("date") or e.get("timestamp", ""))[:10] >= cutoff2
            ]
            result["recent_chat_events"] = recent_events[-50:]

            # 用户反馈：suggestions（adopted/ignored）+ responses
            feedback: Dict[str, Any] = {}
            sugg_path = self.FEEDBACK_DIR / "suggestions.jsonl"
            if sugg_path.exists():
                suggestions = self._read_jsonl_all(sugg_path)
                # 有明确回应的才有价值
                feedback["adopted_suggestions"] = [
                    s for s in suggestions if s.get("status") == "adopted"
                ][-20:]
                feedback["ignored_suggestions"] = [
                    s for s in suggestions if s.get("status") == "ignored"
                ][-10:]
            resp_path = self.FEEDBACK_DIR / "responses.jsonl"
            if resp_path.exists():
                responses = self._read_jsonl_all(resp_path)
                feedback["responses"] = responses[-20:]
            pref_path = self.FEEDBACK_DIR / "preference_model.json"
            if pref_path.exists():
                try:
                    with open(pref_path, encoding="utf-8") as f:
                        feedback["preference_model"] = json.load(f)
                except Exception:
                    pass
            result["feedback"] = feedback

            has_data = bool(recent_memories or result["recent_chat_messages"] or feedback)
            result["available"] = has_data
            return result
        except Exception as e:
            base["error"] = str(e)
            return base


# ── ActionLog (行动记录) ─────────────────────────────────────────

class ActionLogDataSource(DataSource):
    """读取 memory/action_log/ 的行动记录 — 系统实际做了什么的证据。

    按日期读取当天及前一天的行动日志（早晨的 Brief 主要反映昨天的行动）。
    """

    name = "action_log"
    description = "行动日志（memory/action_log/YYYY-MM-DD.jsonl）"

    ACTION_LOG_DIR = MEMORY_DIR / "action_log"

    def is_available(self) -> bool:
        return self.ACTION_LOG_DIR.exists() and bool(
            list(self.ACTION_LOG_DIR.glob("*.jsonl"))
        )

    @property
    def data_path(self) -> str:
        return str(self.ACTION_LOG_DIR)

    def _load_actions_for_date(self, date: str) -> List[Dict]:
        """加载指定日期的行动记录。"""
        path = self.ACTION_LOG_DIR / f"{date}.jsonl"
        if not path.exists():
            return []
        actions: List[Dict] = []
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            actions.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except Exception:
            pass
        return actions

    def get_today_data(self, date: str) -> Dict[str, Any]:
        base = {"source": self.name, "date": date, "available": False}
        try:
            # 读当天行动
            actions = self._load_actions_for_date(date)

            # 如果是早晨生成 Brief，date 通常是今天，
            # 但更多的行动发生在昨天 — 同时加载昨天的记录
            from datetime import datetime as _dt, timedelta as _td
            yesterday = (_dt.strptime(date, "%Y-%m-%d") - _td(days=1)).strftime("%Y-%m-%d")
            yesterday_actions = self._load_actions_for_date(yesterday)

            all_actions = yesterday_actions + actions
            if not all_actions:
                return base

            # 按分类汇总
            by_category: Dict[str, List[Dict]] = {}
            for a in all_actions:
                cat = a.get("category", "misc")
                by_category.setdefault(cat, []).append(a)

            return {
                **base,
                "available": True,
                "total_count": len(all_actions),
                "today_actions": actions,
                "yesterday_actions": yesterday_actions,
                "by_category": by_category,
                "categories": list(by_category.keys()),
            }
        except Exception as e:
            base["error"] = str(e)
            return base


# ── Registry ─────────────────────────────────────────────────────

# All known data source classes — add new ones here
ALL_SOURCES = [
    AudioDataSource,
    ChatDataSource,
    VisionDataSource,
    HabitDataSource,
    WeatherDataSource,
    MemoryDataSource,
    IntelligenceDataSource,   # 长期用户理解
    ConversationDataSource,   # 对话历史与反馈
    ActionLogDataSource,      # 行动记录
]


class DataSourceRegistry:
    """
    自动发现并注册可用数据源。
    
    用法:
        reg = DataSourceRegistry()          # 自动注册可用数据源
        reg = DataSourceRegistry(all=True)  # 注册所有（包括不可用的）
        data = reg.get_all_data('2026-03-12')
    """

    def __init__(self, register_all: bool = False) -> None:
        self._sources: Dict[str, DataSource] = {}
        self._all_sources: Dict[str, DataSource] = {}
        for cls in ALL_SOURCES:
            src = cls()
            self._all_sources[src.name] = src
            if register_all or src.is_available():
                self._sources[src.name] = src

    def register(self, source: DataSource) -> None:
        self._sources[source.name] = source
        self._all_sources[source.name] = source

    def get(self, name: str) -> Optional[DataSource]:
        return self._sources.get(name)

    def get_all_data(self, date: str) -> Dict[str, Dict[str, Any]]:
        return {name: src.get_today_data(date) for name, src in self._sources.items()}

    def list_sources(self) -> List[str]:
        return list(self._sources.keys())

    def discover(self) -> Dict[str, Dict[str, Any]]:
        """Report all known sources and their availability."""
        result = {}
        for name, src in self._all_sources.items():
            result[name] = {
                "available": src.is_available(),
                "description": src.description,
                "data_path": src.data_path,
            }
        return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Data source discovery and test")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--discover", action="store_true", help="Show all sources availability")
    args = parser.parse_args()

    reg = DataSourceRegistry()

    if args.discover:
        print("=== 数据源发现 ===\n")
        for name, info in reg.discover().items():
            icon = "✅" if info["available"] else "❌"
            print(f"  {icon} {name} — {info['description']}")
            print(f"     路径: {info['data_path']}")
        print(f"\n已注册: {reg.list_sources()}")
    else:
        print(f"已注册数据源: {reg.list_sources()}")
        print(f"加载 {args.date} 数据...\n")
        data = reg.get_all_data(args.date)
        for name, d in data.items():
            avail = "✓" if d.get("available") else "✗"
            size = len(str(d))
            err = f" [{d.get('error','')}]" if d.get("error") else ""
            print(f"  {avail} {name}: {size} chars{err}")
            if args.verbose and d.get("available"):
                print(f"     keys: {[k for k in d if k not in ('source','date','available')]}")
