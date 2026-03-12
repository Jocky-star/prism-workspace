#!/usr/bin/env python3
"""
prism_weather.py — Prism 天气数据缓存脚本

从 wttr.in 拉取北京天气数据，缓存到 memory/prism_weather.json。
可直接运行（cron/daemon 调用），也可 import get_weather_cached()。

用法：
  python3 prism_weather.py          # 立即拉取并缓存
  from prism_weather import get_weather_cached  # import 使用
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
WEATHER_FILE = Path(os.path.expanduser("~/.openclaw/workspace/memory/prism_weather.json"))
LOCATION = "Beijing"
CACHE_MAX_AGE_HOURS = 2  # 超过 2 小时视为过期

# 天气描述 → emoji 映射（模糊匹配，以关键字为准）
WEATHER_EMOJI_MAP = [
    ("晴",   "☀️"),
    ("多云",  "⛅"),
    ("阴",   "☁️"),
    ("霾",   "😷"),
    ("雾",   "🌫️"),
    ("大雨",  "⛈️"),
    ("中雨",  "🌧️"),
    ("小雨",  "🌦️"),
    ("雷",   "⛈️"),
    ("雪",   "❄️"),
    ("冰",   "🌨️"),
    ("沙",   "🌪️"),
    ("尘",   "🌪️"),
]


def _pick_emoji(description: str) -> str:
    """根据中文天气描述选择最合适的 emoji"""
    for keyword, emoji in WEATHER_EMOJI_MAP:
        if keyword in description:
            return emoji
    return "🌡️"


def fetch_weather() -> dict | None:
    """
    从 wttr.in 拉取北京天气，返回格式化字典。
    失败返回 None。
    """
    try:
        import requests
        url = f"https://wttr.in/{LOCATION}?format=j1&lang=zh"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        current = data["current_condition"][0]
        temp = current["temp_C"]
        feels = current["FeelsLikeC"]
        humidity = current["humidity"]

        # 中文天气描述
        desc = ""
        lang_zh = current.get("lang_zh", [])
        if lang_zh:
            desc = lang_zh[0].get("value", "")
        if not desc:
            # 英文兜底
            desc = current.get("weatherDesc", [{}])[0].get("value", "未知")

        emoji = _pick_emoji(desc)

        return {
            "temperature": f"{temp}°C",
            "description": desc,
            "emoji": emoji,
            "feels_like": f"{feels}°C",
            "humidity": f"{humidity}%",
            "updated_at": datetime.now(TZ).isoformat(),
        }
    except Exception as e:
        print(f"[prism_weather] 拉取天气失败: {e}", file=sys.stderr)
        return None


def save_weather(data: dict):
    """写入缓存文件"""
    try:
        WEATHER_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = WEATHER_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(WEATHER_FILE)
        print(f"[prism_weather] 已缓存: {data['temperature']} {data['description']} {data['emoji']}")
    except Exception as e:
        print(f"[prism_weather] 写缓存失败: {e}", file=sys.stderr)


def get_weather_cached() -> dict | None:
    """
    读取缓存天气数据。
    - 若文件不存在或过期（>2小时）→ 返回 None
    - 否则返回缓存数据
    供 prism_display.py 等模块 import 使用。
    """
    if not WEATHER_FILE.exists():
        return None
    try:
        data = json.loads(WEATHER_FILE.read_text(encoding="utf-8"))
        updated_at_str = data.get("updated_at", "")
        if not updated_at_str:
            return None
        updated_at = datetime.fromisoformat(updated_at_str)
        age_hours = (datetime.now(TZ) - updated_at).total_seconds() / 3600
        if age_hours > CACHE_MAX_AGE_HOURS:
            return None  # 数据过期
        return data
    except Exception:
        return None


def main():
    """直接运行时：拉取天气并缓存"""
    print(f"[prism_weather] 正在拉取 {LOCATION} 天气...")
    data = fetch_weather()
    if data:
        save_weather(data)
        print(f"[prism_weather] ✅ {data['temperature']} {data['description']} {data['emoji']} "
              f"(体感 {data['feels_like']}, 湿度 {data['humidity']})")
    else:
        print("[prism_weather] ❌ 天气拉取失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
