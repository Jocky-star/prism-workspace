#!/usr/bin/env python3
"""wellness_check.py - 健康关怀助手

拍照 → Gemini 分析身体状态 → 输出关怀建议
配合 cron 使用，由 LLM agent 决定是否发送提醒

防骚扰：
- 同类提醒间隔 >= 45 分钟
- 状态文件记录上次提醒时间
"""

import os, sys, json, base64, subprocess, shutil, requests
from datetime import datetime, timedelta
from pathlib import Path

# === Config ===
API_KEY = os.environ.get("GEMINI_API_KEY", "sk-pWBDE3R7o4PNKp9W9QoNghhwaIfcm7S8yPG2Lof75aYoICr2")
BASE_URL = os.environ.get("GEMINI_BASE_URL", "http://model.mify.ai.srv/v1")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
PROVIDER_ID = os.environ.get("GEMINI_PROVIDER_ID", "vertex_ai")

WORKSPACE = os.environ.get("OPENCLAW_WORKSPACE", os.path.expanduser("~/.openclaw/workspace"))
CAMERA_DIR = os.path.join(WORKSPACE, "camera")
STATE_FILE = "/tmp/wellness_state.json"
REMINDER_COOLDOWN_MIN = 45

WELLNESS_PROMPT = """你是一个关心用户健康的AI助手。分析这张办公室摄像头照片，评估用户的身体状态。

请用 JSON 格式回答（不要 markdown 包裹，只输出纯 JSON）：

{
  "person_present": true/false,
  "analysis": {
    "posture": {
      "status": "good/slouching/leaning/too_close_to_screen/lying_down",
      "detail": "具体描述"
    },
    "fatigue": {
      "level": "none/mild/moderate/severe",
      "signs": ["具体疲劳迹象，如：眼睛半闭、打哈欠、揉眼睛、趴桌"]
    },
    "complexion": {
      "status": "normal/pale/flushed/tired",
      "detail": "面色描述"
    },
    "mood": {
      "status": "focused/relaxed/stressed/bored/frustrated",
      "detail": "情绪判断依据"
    },
    "hydration": {
      "water_visible": true/false,
      "cup_status": "drinking/untouched/not_visible/empty",
      "detail": "水杯状态"
    },
    "lighting": {
      "status": "good/too_dark/too_bright/glare",
      "detail": "光线情况"
    },
    "activity": {
      "status": "working/resting/chatting/on_phone/eating/away",
      "detail": "当前在做什么"
    }
  },
  "concerns": [
    {
      "type": "sedentary/fatigue/posture/hydration/lighting/stress",
      "severity": "low/medium/high",
      "suggestion": "自然轻松的中文建议，像朋友提醒一样"
    }
  ],
  "overall_status": "看起来状态不错/需要注意/建议休息",
  "scene_description": "场景简述"
}

评估标准：
- 只有真正需要关心的时候才给 concerns，状态正常就空数组
- suggestion 要自然随意，像朋友提醒，不要像健康APP
- 如果看不清人脸，fatigue 和 complexion 给 "unable_to_assess"
- 注意：图片可能是倒置的（天花板在下方），先判断方向

只输出 JSON。"""


def take_photo(save_path, width=1920, height=1080, retries=3):
    import time
    last_err = None
    for attempt in range(retries + 1):
        try:
            if attempt > 0:
                # Find imx708 node ID dynamically and pause it to release camera
                try:
                    import re
                    wp_out = subprocess.run(["wpctl", "status"], capture_output=True, text=True, timeout=5)
                    for line in wp_out.stdout.splitlines():
                        m = re.search(r'(\d+)\.\s+imx708.*\[libcamera\]', line)
                        if m:
                            subprocess.run(["wpctl", "set-pause", m.group(1)],
                                           capture_output=True, timeout=5)
                            break
                except Exception:
                    pass
                time.sleep(2)
            env = dict(os.environ, LIBCAMERA_LOG_LEVELS="*:ERROR")
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
    print(json.dumps({"success": False, "error": f"拍照失败（重试{retries}次后）: {last_err}"}))
    return False


def analyze(image_path):
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

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
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": WELLNESS_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                ]}],
                "temperature": 0.3,
            },
            timeout=90
        )
    except Exception as e:
        return {"error": f"API failed: {e}"}

    if resp.status_code != 200:
        return {"error": f"API {resp.status_code}: {resp.text[:200]}"}

    content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"error": f"JSON parse failed: {content[:300]}"}


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"last_reminders": {}, "sedentary_start": None, "observations": []}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False)


def should_remind(concern_type, state):
    """检查是否应该提醒（冷却时间）"""
    last = state.get("last_reminders", {}).get(concern_type)
    if not last:
        return True
    try:
        last_time = datetime.fromisoformat(last)
        return datetime.now() - last_time > timedelta(minutes=REMINDER_COOLDOWN_MIN)
    except:
        return True


def check_sedentary(state, person_present):
    """久坐检测：连续在位超过 60 分钟"""
    now = datetime.now()
    concerns = []

    if person_present:
        if not state.get("sedentary_start"):
            state["sedentary_start"] = now.isoformat()
        else:
            try:
                start = datetime.fromisoformat(state["sedentary_start"])
                minutes = (now - start).total_seconds() / 60
                if minutes >= 60 and should_remind("sedentary", state):
                    concerns.append({
                        "type": "sedentary",
                        "severity": "medium" if minutes < 90 else "high",
                        "suggestion": f"你已经坐了 {int(minutes)} 分钟了，起来走走吧～",
                        "duration_minutes": int(minutes)
                    })
            except:
                state["sedentary_start"] = now.isoformat()
    else:
        # 人不在 = 久坐计时器重置
        state["sedentary_start"] = None

    return concerns


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--status", action="store_true", help="只看当前状态")
    p.add_argument("--reset", action="store_true", help="重置状态")
    args = p.parse_args()

    state = load_state()

    if args.reset:
        save_state({"last_reminders": {}, "sedentary_start": None, "observations": []})
        print(json.dumps({"action": "reset", "done": True}))
        return

    if args.status:
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return

    Path(CAMERA_DIR).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    photo_path = os.path.join(CAMERA_DIR, f"wellness_{ts}.jpg")

    if not take_photo(photo_path):
        return

    result = analyze(photo_path)

    if "error" in result:
        # 清理照片
        os.remove(photo_path)
        print(json.dumps({"success": False, **result}))
        return

    person_present = result.get("person_present", False)

    # 合并 Gemini concerns + 久坐检测
    all_concerns = list(result.get("concerns", []))
    sedentary_concerns = check_sedentary(state, person_present)
    all_concerns.extend(sedentary_concerns)

    # 过滤冷却中的提醒
    active_concerns = []
    for c in all_concerns:
        if should_remind(c["type"], state):
            active_concerns.append(c)

    # 更新提醒时间
    now_iso = datetime.now().isoformat()
    for c in active_concerns:
        state.setdefault("last_reminders", {})[c["type"]] = now_iso

    # 记录观察（保留最近 20 条）
    state.setdefault("observations", []).append({
        "timestamp": now_iso,
        "person_present": person_present,
        "overall": result.get("overall_status", ""),
        "activity": result.get("analysis", {}).get("activity", {}).get("status", ""),
    })
    state["observations"] = state["observations"][-20:]

    save_state(state)

    # 清理wellness照片（不保留，省空间）
    os.remove(photo_path)

    output = {
        "success": True,
        "person_present": person_present,
        "overall_status": result.get("overall_status", ""),
        "analysis": result.get("analysis", {}),
        "active_concerns": active_concerns,
        "should_notify": len(active_concerns) > 0,
        "scene": result.get("scene_description", ""),
        "timestamp": ts,
    }
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
