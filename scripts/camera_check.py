#!/usr/bin/env python3
"""camera_check.py — 拍照 + Gemini 智能分析 + 三层视觉记忆

记忆分层：
  短期: camera/ 原图(7天) + memory/visual/YYYY-MM-DD.jsonl 每日日志(30天)
  长期: memory/visual_summary.md — 蒸馏后的规律趋势(每周更新)
  永久: memory/people.md — 人物身份特征(只增不减)

用法：
  python3 camera_check.py                    # 拍照+分析+记录
  python3 camera_check.py --no-fix           # 不修正旋转
  python3 camera_check.py --no-log           # 不写日志
  python3 camera_check.py --cleanup          # 只做清理
  python3 camera_check.py --digest           # 输出蒸馏建议(给LLM用)
"""

import os
import sys
import json
import base64
import subprocess
import shutil
import glob
import requests
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from camera_lock import camera_lock
from pathlib import Path

# === Config ===
API_KEY = os.environ.get("GEMINI_API_KEY", "sk-pWBDE3R7o4PNKp9W9QoNghhwaIfcm7S8yPG2Lof75aYoICr2")
BASE_URL = os.environ.get("GEMINI_BASE_URL", "http://model.mify.ai.srv/v1")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
PROVIDER_ID = os.environ.get("GEMINI_PROVIDER_ID", "vertex_ai")

WORKSPACE = "/home/mi/.openclaw/workspace"
CAMERA_DIR = f"{WORKSPACE}/camera"
VISUAL_LOG_DIR = f"{WORKSPACE}/memory/visual"
PEOPLE_FILE = f"{WORKSPACE}/memory/people.md"
SUMMARY_FILE = f"{WORKSPACE}/memory/visual_summary.md"

# Retention
PHOTO_RETENTION_DAYS = 7
LOG_RETENTION_DAYS = 30

ANALYSIS_PROMPT = """请分析这张摄像头拍摄的图片，用 JSON 格式回答（不要 markdown 包裹，只输出纯 JSON）：

{
  "is_upside_down": true/false,
  "rotation_needed": 0/90/180/270,
  "scene": "简短场景描述",
  "lighting": "光线条件",
  "people": [
    {
      "id": "person_1",
      "is_fantuan": true/false,
      "confidence": 0.0-1.0,
      "description": "外貌描述（性别、年龄、眼镜、发型、衣着）",
      "action": "正在做什么",
      "position": "画面中的位置"
    }
  ],
  "objects": ["显著物体列表"],
  "mood": "整体氛围",
  "notable_changes": "有什么特别的"
}

判断 is_fantuan 的标准：戴眼镜的年轻东亚男性，短黑发，透明框眼镜。
只输出 JSON。"""


def take_photo(save_path: str, width=1920, height=1080, retries=3) -> bool:
    import time
    last_err = None
    for attempt in range(retries + 1):
        try:
            # Release PipeWire camera node if it's holding the lock
            if attempt > 0:
                subprocess.run(
                    ["wpctl", "set-pause", "82"],
                    capture_output=True, timeout=5
                )
                time.sleep(1)
            env = dict(os.environ, LIBCAMERA_LOG_LEVELS="*:ERROR")
            with camera_lock(timeout=15):
                subprocess.run(
                    ["rpicam-still", "-o", save_path,
                     "--width", str(width), "--height", str(height),
                     "-t", "2000", "--nopreview",
                     "--rotation", "180"],  # camera is physically inverted
                    capture_output=True, timeout=15, check=True, env=env
                )
            return True
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(3)
    print(json.dumps({"success": False, "error": f"拍照失败（重试{retries}次后）: {last_err}"}), flush=True)
    return False


def analyze_with_gemini(image_path: str) -> dict:
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    mime = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"

    try:
        resp = requests.post(
            f"{BASE_URL}/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {API_KEY}",
                "X-Model-Provider-Id": PROVIDER_ID,
            },
            json={
                "model": MODEL,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": ANALYSIS_PROMPT},
                        {"type": "inline_data", "inline_data": {"mime_type": mime, "data": img_b64}}
                    ]
                }],
                "temperature": 0,
            },
            timeout=90
        )
    except Exception as e:
        return {"error": f"Gemini API 失败: {e}"}

    if resp.status_code != 200:
        return {"error": f"Gemini {resp.status_code}: {resp.text[:200]}"}

    content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"error": f"JSON 解析失败: {content[:300]}"}


def fix_rotation(image_path: str, degrees: int, output_path: str) -> str:
    if degrees == 0:
        if image_path != output_path:
            shutil.copy2(image_path, output_path)
        return output_path
    from PIL import Image
    img = Image.open(image_path)
    img_rotated = img.rotate(-degrees if degrees != 180 else 180)
    img_rotated.save(output_path, quality=95)
    return output_path


def write_daily_log(entry: dict):
    """写入当日视觉日志（短期层）"""
    os.makedirs(VISUAL_LOG_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(VISUAL_LOG_DIR, f"{today}.jsonl")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def cleanup(photo_days=PHOTO_RETENTION_DAYS, log_days=LOG_RETENTION_DAYS):
    """清理过期的照片和日志"""
    now = datetime.now()

    # 清理照片
    for f in glob.glob(os.path.join(CAMERA_DIR, "photo_*.jpg")):
        try:
            date_str = os.path.basename(f).split("_")[1]
            if datetime.strptime(date_str, "%Y%m%d") < now - timedelta(days=photo_days):
                os.remove(f)
        except (IndexError, ValueError):
            pass

    # 清理旧日志
    for f in glob.glob(os.path.join(VISUAL_LOG_DIR, "*.jsonl")):
        try:
            date_str = os.path.basename(f).replace(".jsonl", "")
            if datetime.strptime(date_str, "%Y-%m-%d") < now - timedelta(days=log_days):
                os.remove(f)
        except ValueError:
            pass


def digest():
    """输出最近7天的视觉日志摘要（给 LLM 蒸馏用）"""
    entries = []
    for f in sorted(glob.glob(os.path.join(VISUAL_LOG_DIR, "*.jsonl")))[-7:]:
        with open(f, "r") as fh:
            for line in fh:
                try:
                    entries.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    pass

    if not entries:
        print(json.dumps({"entries": 0, "message": "没有最近的视觉日志"}))
        return

    # 统计
    fantuan_times = []
    clothing = []
    total_people = 0

    for e in entries:
        for p in e.get("people", []):
            total_people += 1
            if p.get("is_fantuan"):
                fantuan_times.append(e.get("timestamp", "")[:16])
                desc = p.get("description", "")
                if desc:
                    clothing.append({"time": e.get("timestamp", "")[:10], "desc": desc})

    summary = {
        "period": f"{entries[0].get('timestamp', '')[:10]} ~ {entries[-1].get('timestamp', '')[:10]}",
        "total_observations": len(entries),
        "total_people_seen": total_people,
        "fantuan_appearances": len(fantuan_times),
        "fantuan_times": fantuan_times,
        "fantuan_clothing": clothing,
        "scenes": list(set(e.get("scene", "") for e in entries if e.get("scene"))),
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--save-dir", default=CAMERA_DIR)
    parser.add_argument("--no-fix", action="store_true")
    parser.add_argument("--no-log", action="store_true")
    parser.add_argument("--no-analyze", action="store_true")
    parser.add_argument("--cleanup", action="store_true", help="只做清理")
    parser.add_argument("--digest", action="store_true", help="输出蒸馏摘要")
    args = parser.parse_args()

    if args.cleanup:
        cleanup()
        print(json.dumps({"action": "cleanup", "done": True}))
        return

    if args.digest:
        digest()
        return

    save_dir = Path(args.save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = str(save_dir / f"raw_{timestamp}.jpg")
    final_path = str(save_dir / f"photo_{timestamp}.jpg")

    # 1. 拍照
    if not take_photo(raw_path):
        return

    if args.no_analyze:
        print(json.dumps({"success": True, "image_path": raw_path}))
        return

    # 2. Gemini 分析
    analysis = analyze_with_gemini(raw_path)

    if "error" in analysis:
        shutil.copy2(raw_path, final_path)
        os.remove(raw_path)
        print(json.dumps({"success": False, "image_path": final_path, **analysis}))
        return

    # 3. 修正旋转
    rotation = analysis.get("rotation_needed", 0)
    if rotation and not args.no_fix:
        fix_rotation(raw_path, rotation, final_path)
        os.remove(raw_path)
    else:
        shutil.move(raw_path, final_path)

    # 4. 识别饭团
    people = analysis.get("people", [])
    fantuan_detected = any(
        p.get("is_fantuan") and p.get("confidence", 0) >= 0.8
        for p in people
    )

    # 5. 写短期日志
    if not args.no_log:
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "image": os.path.basename(final_path),
            "scene": analysis.get("scene", ""),
            "lighting": analysis.get("lighting", ""),
            "people": people,
            "objects": analysis.get("objects", []),
            "mood": analysis.get("mood", ""),
            "notable_changes": analysis.get("notable_changes", ""),
            "fantuan_detected": fantuan_detected,
            "rotation_applied": rotation,
        }
        write_daily_log(log_entry)

    # 6. 顺手清理过期文件
    cleanup()

    # 7. 输出
    result = {
        "success": True,
        "image_path": final_path,
        "needs_rotation": bool(rotation),
        "rotation_degrees": rotation,
        "fantuan_detected": fantuan_detected,
        "people_count": len(people),
        "people": people,
        "scene": analysis.get("scene", ""),
        "mood": analysis.get("mood", ""),
        "objects": analysis.get("objects", []),
        "timestamp": timestamp,
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
