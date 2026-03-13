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


# ── Registry ─────────────────────────────────────────────────────

# All known data source classes — add new ones here
ALL_SOURCES = [
    AudioDataSource,
    ChatDataSource,
    VisionDataSource,
    HabitDataSource,
    WeatherDataSource,
    MemoryDataSource,
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
