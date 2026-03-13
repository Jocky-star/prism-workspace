"""
用户服务偏好管理
- load / save preferences  →  memory/service_preferences.json
- 默认全开
- generate_menu()          →  生成人类可读的可选菜单
- is_subscribed(name)      →  检查是否订阅了某服务
- update(name, **kwargs)   →  更新某服务的偏好设置
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import sys as _sys
from pathlib import Path as _Path
_ws = _Path(__file__).resolve()
while _ws.name != "src" and _ws != _ws.parent:
    _ws = _ws.parent
if _ws.name == "src":
    _sys.path.insert(0, str(_ws.parent))

from src.services.config import WORKSPACE, MEMORY_DIR, SERVICES_OUTPUT_DIR
PREFS_FILE = MEMORY_DIR / "service_preferences.json"

DEFAULT_PREFS: Dict[str, Any] = {
    "version": 1,
    "services": {
        "daily_brief": {
            "enabled": True,
            "time": "08:30",
            "channel": "feishu",
            "description": "晨间简报 — 昨天关键事件、今天天气、待办提醒",
        },
        "meeting_insight": {
            "enabled": True,
            "with_brief": True,
            "description": "会议洞察 — 每场会议的分歧、决策、行动项",
        },
        "intent_tracker": {
            "enabled": True,
            "auto_search_wish": True,
            "description": "意图追踪 — 从对话/录音中提取愿望/待办/想法/计划",
        },
        "emotion_care": {
            "enabled": True,
            "sensitivity": "normal",
            "description": "情绪关怀 — 多信号叠加检测负面情绪，适时关心",
        },
        "social_insight": {
            "enabled": True,
            "frequency": "weekly",
            "description": "人际洞察 — 本周人际动态、关系变化摘要（周度）",
        },
        "interest_learning": {
            "enabled": True,
            "description": "兴趣学习 — 从行为数据中发现并推送你感兴趣的内容",
        },
        "anomaly_detection": {
            "enabled": True,
            "description": "异常检测 — 发现作息/行为异常，提前预警",
        },
    },
    "quiet_hours": {"start": "23:00", "end": "08:00"},
    "first_run": True,
    "updated_at": None,
}

# Human-readable service display order
_SERVICE_ORDER = [
    "daily_brief",
    "meeting_insight",
    "intent_tracker",
    "emotion_care",
    "social_insight",
    "interest_learning",
    "anomaly_detection",
]


class ServicePreferences:
    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or PREFS_FILE
        self._prefs: Dict[str, Any] = {}
        self.load()

    # ── I/O ──────────────────────────────────────

    def load(self) -> None:
        """Load from disk; fall back to defaults if missing."""
        if self._path.exists():
            try:
                with open(self._path, encoding="utf-8") as f:
                    saved = json.load(f)
                # Merge: keep user settings, fill missing keys from defaults
                merged = _deep_merge(DEFAULT_PREFS, saved)
                self._prefs = merged
                return
            except Exception:
                pass
        # Fresh install — use defaults
        self._prefs = json.loads(json.dumps(DEFAULT_PREFS))

    def save(self) -> None:
        """Persist to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._prefs["updated_at"] = datetime.now().isoformat()
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._prefs, f, ensure_ascii=False, indent=2)

    # ── Query ─────────────────────────────────────

    def is_subscribed(self, service_name: str) -> bool:
        svc = self._prefs.get("services", {}).get(service_name, {})
        return bool(svc.get("enabled", False))

    def get_service(self, service_name: str) -> Dict[str, Any]:
        return self._prefs.get("services", {}).get(service_name, {})

    def is_first_run(self) -> bool:
        return bool(self._prefs.get("first_run", True))

    def mark_onboarded(self) -> None:
        self._prefs["first_run"] = False
        self.save()

    def quiet_hours(self) -> Dict[str, str]:
        return self._prefs.get("quiet_hours", {"start": "23:00", "end": "08:00"})

    def is_quiet_now(self) -> bool:
        """Returns True if current time is within quiet hours."""
        now = datetime.now()
        qh = self.quiet_hours()
        start_h, start_m = map(int, qh["start"].split(":"))
        end_h, end_m = map(int, qh["end"].split(":"))
        now_min = now.hour * 60 + now.minute
        start_min = start_h * 60 + start_m
        end_min = end_h * 60 + end_m
        if start_min > end_min:  # crosses midnight
            return now_min >= start_min or now_min < end_min
        return start_min <= now_min < end_min

    # ── Mutations ─────────────────────────────────

    def update(self, service_name: str, **kwargs: Any) -> None:
        """Update settings for a service. Does NOT auto-save."""
        svc = self._prefs.setdefault("services", {}).setdefault(service_name, {})
        svc.update(kwargs)

    def set_enabled(self, service_name: str, enabled: bool) -> None:
        self.update(service_name, enabled=enabled)
        self.save()

    def set_all_enabled(self, enabled: bool) -> None:
        for name in self._prefs.get("services", {}):
            self._prefs["services"][name]["enabled"] = enabled
        self.save()

    # ── Menu generation ──────────────────────────

    def generate_menu(self) -> str:
        """Generate a human-readable subscription menu (Feishu-flavored markdown)."""
        services = self._prefs.get("services", {})
        lines = [
            "## ⚙️ 星星服务菜单",
            "",
            "以下是我能为你提供的服务，你可以随时订阅或取消：",
            "",
        ]
        for name in _SERVICE_ORDER:
            cfg = services.get(name, {})
            enabled = cfg.get("enabled", False)
            icon = "✅" if enabled else "⬜"
            desc = cfg.get("description", name)
            lines.append(f"{icon} **{name}** — {desc}")

        lines += [
            "",
            f"🔕 **安静时段**: {self._prefs['quiet_hours']['start']} – {self._prefs['quiet_hours']['end']}",
            "",
            "---",
            "回复 `订阅 <服务名>` 或 `取消 <服务名>` 来调整。",
            "例如：`取消 social_insight`",
        ]
        return "\n".join(lines)

    def generate_onboarding_message(self) -> str:
        """First-run message asking user to choose services."""
        return (
            "👋 **首次使用星星服务系统！**\n\n"
            "我会根据录音、对话、摄像头等数据主动为你提供各种服务。\n"
            "**默认已全部开启**，你也可以按需关闭不需要的。\n\n"
            + self.generate_menu()
            + "\n\n> 如果你现在不想改，什么都不用做，系统会正常运行 ✨"
        )


# ── Helpers ──────────────────────────────────────

def _deep_merge(base: Dict, override: Dict) -> Dict:
    """Recursively merge override into base (override wins on conflicts)."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# ── CLI ──────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Manage service preferences")
    parser.add_argument("--show-menu", action="store_true", help="Print subscription menu")
    parser.add_argument("--show-prefs", action="store_true", help="Print current preferences JSON")
    parser.add_argument("--enable", metavar="SERVICE", help="Enable a service")
    parser.add_argument("--disable", metavar="SERVICE", help="Disable a service")
    parser.add_argument("--reset", action="store_true", help="Reset to defaults")
    args = parser.parse_args()

    prefs = ServicePreferences()

    if args.reset:
        import shutil
        if PREFS_FILE.exists():
            shutil.copy(PREFS_FILE, str(PREFS_FILE) + ".bak")
        prefs._prefs = json.loads(json.dumps(DEFAULT_PREFS))
        prefs.save()
        print("✓ Preferences reset to defaults")

    if args.enable:
        prefs.set_enabled(args.enable, True)
        print(f"✓ Enabled: {args.enable}")

    if args.disable:
        prefs.set_enabled(args.disable, False)
        print(f"✓ Disabled: {args.disable}")

    if args.show_prefs:
        print(json.dumps(prefs._prefs, ensure_ascii=False, indent=2))

    if args.show_menu or not any([args.reset, args.enable, args.disable, args.show_prefs]):
        print(prefs.generate_menu())
        print(f"\nQuiet now: {prefs.is_quiet_now()}")
        print(f"First run: {prefs.is_first_run()}")
