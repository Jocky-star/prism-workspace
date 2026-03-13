"""
情绪关怀生成器 — Emotion Care
输入：录音 mood_or_tone + 摄像头状态 + 行为数据
检测多信号叠加 → 生成关怀消息

运行方式：
  python3 src/services/generators/emotion_care.py --date 2026-03-12 --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import sys as _sys
from pathlib import Path as _Path
_ws = _Path(__file__).resolve()
while _ws.name != "src" and _ws != _ws.parent:
    _ws = _ws.parent
if _ws.name == "src":
    _sys.path.insert(0, str(_ws.parent))

from src.services.config import WORKSPACE, MEMORY_DIR, SERVICES_OUTPUT_DIR
sys.path.insert(0, str(WORKSPACE))

from src.services.data_sources import AudioDataSource, VisionDataSource, HabitDataSource
from src.services.llm_client import llm_complete

OUTPUT_DIR = SERVICES_OUTPUT_DIR

# Mood keywords that signal negative / stressed state
NEGATIVE_MOOD_SIGNALS = {
    "tired", "stressed", "anxious", "sad", "frustrated",
    "疲惫", "疲倦", "累", "压力", "焦虑", "难过", "沮丧", "烦躁",
    "不开心", "郁闷", "负面", "低沉", "消极", "担忧",
}

SENSITIVITY_THRESHOLDS = {
    "low": 3,       # 3+ negative signals to trigger
    "normal": 2,    # 2+ negative signals
    "high": 1,      # any negative signal
}


def score_mood_signals(
    audio_data: Dict,
    vision_data: Dict,
    habit_data: Dict,
) -> Tuple[int, List[str]]:
    """
    Score negative mood signals across data sources.
    Returns (score, list of signal descriptions).
    """
    score = 0
    signals: List[str] = []

    # Audio moods
    for mood in audio_data.get("moods", []):
        mood_lower = mood.lower()
        for neg in NEGATIVE_MOOD_SIGNALS:
            if neg in mood_lower:
                score += 1
                signals.append(f"录音情绪: {mood}")
                break

    # Vision moods
    for mood in vision_data.get("moods_seen", []):
        mood_lower = mood.lower()
        for neg in NEGATIVE_MOOD_SIGNALS:
            if neg in mood_lower:
                score += 1
                signals.append(f"摄像头观察: {mood}")
                break

    # Habit profile — check for recent anomalies
    profile = habit_data.get("habit_profile", {})
    anomalies = profile.get("anomalies", [])
    for a in anomalies[:2]:
        score += 1
        signals.append(f"行为异常: {a}")

    return score, signals


def generate_care_message(
    signals: List[str],
    score: int,
    dry_run: bool = False,
) -> str:
    """Generate a caring message based on detected signals."""
    if dry_run:
        return f"[DRY-RUN] 检测到 {score} 个负面信号，应发送关怀消息"

    system_prompt = (
        "你是用户的私人助理星星。"
        "用户当前可能情绪不佳或比较疲惫。"
        "请发一条温暖、简短（1-2句）的关怀消息。"
        "语气轻松自然，像朋友一样，不要过度煽情或说教。"
        "不要问太多问题。"
        "只输出关怀消息文本，不要其他内容。"
    )

    user_prompt = (
        f"检测到的信号：\n" + "\n".join(f"  - {s}" for s in signals) +
        f"\n\n信号强度：{score}\n请生成关怀消息。"
    )

    return llm_complete(
        prompt=user_prompt,
        system=system_prompt,
        max_tokens=150,
        temperature=0.8,
        dry_run=dry_run,
    )


def generate_emotion_care(
    date: str,
    sensitivity: str = "normal",
    dry_run: bool = False,
) -> Dict[str, Any]:
    audio_data = AudioDataSource().get_today_data(date)
    vision_data = VisionDataSource().get_today_data(date)
    habit_data = HabitDataSource().get_today_data(date)

    score, signals = score_mood_signals(audio_data, vision_data, habit_data)
    threshold = SENSITIVITY_THRESHOLDS.get(sensitivity, 2)
    should_care = score >= threshold

    result: Dict[str, Any] = {
        "generator": "emotion_care",
        "date": date,
        "generated_at": datetime.now().isoformat(),
        "dry_run": dry_run,
        "sensitivity": sensitivity,
        "threshold": threshold,
        "signal_score": score,
        "signals": signals,
        "triggered": should_care,
        "care_message": None,
    }

    if should_care or dry_run:
        result["care_message"] = generate_care_message(signals, score, dry_run=dry_run)

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
    existing["emotion_care"] = result
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Emotion care detector")
    parser.add_argument(
        "--date",
        default=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        help="Date (YYYY-MM-DD)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sensitivity", choices=["low", "normal", "high"], default="normal")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    print(f"Running emotion care for {args.date} (dry_run={args.dry_run})...")
    result = generate_emotion_care(args.date, sensitivity=args.sensitivity, dry_run=args.dry_run)

    print(f"\n📊 Signal score: {result['signal_score']} / threshold: {result['threshold']}")
    for s in result.get("signals", []):
        print(f"  ⚡ {s}")
    if result.get("triggered"):
        print(f"\n💬 Care message: {result.get('care_message', '')}")
    else:
        print("\n✅ 情绪状态正常，无需关怀")

    if args.save and not args.dry_run:
        path = save_result(result, args.date)
        print(f"\n✅ Saved to {path}")
