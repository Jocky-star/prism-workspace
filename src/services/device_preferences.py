"""
设备偏好管理 — 从理解层到设备控制的桥梁

存储用户的设备使用偏好（从对话/录音中提取），
供 determine_scene() 等设备控制逻辑读取。

偏好格式 (memory/device_preferences.json):
{
  "lamp_rules": [
    {"hours": [13, 14], "scene": "off", "reason": "用户习惯午休不开灯", "source": "chat:2026-03-13"}
  ],
  "updated_at": "2026-03-13T13:25:00"
}
"""

import json
import os
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

from src.services.config import MEMORY_DIR

PREFS_FILE = MEMORY_DIR / "device_preferences.json"


def load() -> Dict[str, Any]:
    """Load device preferences. Returns empty structure if not exists."""
    if PREFS_FILE.exists():
        with open(PREFS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"lamp_rules": [], "updated_at": None}


def save(prefs: Dict[str, Any]) -> None:
    """Save device preferences."""
    prefs["updated_at"] = datetime.now().isoformat()
    PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PREFS_FILE, "w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)


def add_lamp_rule(hours: List[int], scene: str, reason: str, source: str = "") -> Dict:
    """Add a lamp rule from user preference."""
    prefs = load()
    
    # Check if rule for same hours already exists, update it
    existing = [r for r in prefs["lamp_rules"] if set(r["hours"]) == set(hours)]
    if existing:
        existing[0]["scene"] = scene
        existing[0]["reason"] = reason
        existing[0]["source"] = source
        existing[0]["updated_at"] = datetime.now().isoformat()
    else:
        prefs["lamp_rules"].append({
            "hours": hours,
            "scene": scene,
            "reason": reason,
            "source": source,
            "created_at": datetime.now().isoformat(),
        })
    
    save(prefs)
    return prefs


def get_lamp_scene_override(hour: int) -> Optional[str]:
    """Check if user has a preference override for this hour.
    Returns scene name if override exists, None otherwise."""
    prefs = load()
    for rule in prefs.get("lamp_rules", []):
        if hour in rule.get("hours", []):
            return rule["scene"]
    return None


def remove_lamp_rule(hours: List[int]) -> bool:
    """Remove a lamp rule by hours."""
    prefs = load()
    before = len(prefs["lamp_rules"])
    prefs["lamp_rules"] = [r for r in prefs["lamp_rules"] if set(r["hours"]) != set(hours)]
    if len(prefs["lamp_rules"]) < before:
        save(prefs)
        return True
    return False


def list_rules() -> List[Dict]:
    """List all device preference rules."""
    return load().get("lamp_rules", [])


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Device preferences manager")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--add-lamp", nargs=3, metavar=("HOURS", "SCENE", "REASON"),
                        help="Add lamp rule. HOURS=13,14 SCENE=off REASON='午休'")
    parser.add_argument("--remove-lamp", metavar="HOURS", help="Remove lamp rule by hours, e.g. 13,14")
    args = parser.parse_args()
    
    if args.list:
        rules = list_rules()
        if not rules:
            print("暂无设备偏好规则")
        for r in rules:
            print(f"  台灯 {r['hours']} → {r['scene']} ({r['reason']})")
    elif args.add_lamp:
        hours = [int(h) for h in args.add_lamp[0].split(",")]
        add_lamp_rule(hours, args.add_lamp[1], args.add_lamp[2])
        print(f"✅ 已添加: 台灯 {hours} → {args.add_lamp[1]}")
    elif args.remove_lamp:
        hours = [int(h) for h in args.remove_lamp.split(",")]
        if remove_lamp_rule(hours):
            print(f"✅ 已删除: {hours}")
        else:
            print(f"❌ 未找到: {hours}")
