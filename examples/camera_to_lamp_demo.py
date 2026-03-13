#!/usr/bin/env python3
"""
🎯 端到端示例：摄像头 → 人体检测 → 台灯控制

展示 Prism 的核心链路：拍一张照片 → 判断有没有人 → 自动控制台灯。

运行方式：
  python3 examples/camera_to_lamp_demo.py          # 检测一次
  python3 examples/camera_to_lamp_demo.py --loop    # 持续检测（Ctrl+C 退出）
  python3 examples/camera_to_lamp_demo.py --dry-run # 只检测，不真的控制台灯

前置条件：
  - 有摄像头（树莓派 rpicam-still，或改 CAMERA_CMD 用你的）
  - LLM API 已配置（环境变量或 models.json）
  - 有米家台灯（没有的话用 --dry-run 看效果）
"""

import argparse
import base64
import io
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 确保项目根目录在 path 里
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

TZ = timezone(timedelta(hours=8))


# ═══════════════════════════════════════════════════════════════════
# Step 1: 读配置
# ═══════════════════════════════════════════════════════════════════

def load_config():
    """从 prism_config.yaml 读配置，没有就用默认值"""
    from src.screen.config_loader import get_config
    cfg = get_config()
    print(f"📋 配置已加载")
    print(f"   场景描述: {cfg.presence.scene}")
    print(f"   离开超时: {cfg.presence.absent_timeout}s")
    print(f"   帧差阈值: {cfg.presence.motion_threshold}")
    print(f"   Vision model: {cfg.vision.model or '(自动检测)'}")
    print()
    return cfg


# ═══════════════════════════════════════════════════════════════════
# Step 2: 拍照
# ═══════════════════════════════════════════════════════════════════

# 你的摄像头命令。树莓派用 rpicam-still，其他系统改成你的。
# 比如 USB 摄像头：["fswebcam", "-r", "640x480", "--no-banner", "{output}"]
CAMERA_CMD = ["rpicam-still", "--rotation", "180", "-o", "{output}",
              "--width", "640", "--height", "480", "-t", "1000"]

def take_photo() -> "PIL.Image":
    """拍一张照片，返回 PIL Image"""
    from PIL import Image
    tmp = "/tmp/prism_demo_capture.jpg"
    
    cmd = [c.replace("{output}", tmp) for c in CAMERA_CMD]
    print(f"📷 拍照中...")
    result = subprocess.run(cmd, capture_output=True, timeout=10)
    
    if result.returncode != 0:
        raise RuntimeError(f"拍照失败: {result.stderr.decode()[:200]}")
    
    img = Image.open(tmp)
    print(f"   ✅ 拍到了 ({img.size[0]}x{img.size[1]})")
    return img


# ═══════════════════════════════════════════════════════════════════
# Step 3: Vision API 检测是否有人
# ═══════════════════════════════════════════════════════════════════

def detect_person(img, config) -> bool:
    """
    用 Vision API 判断照片里有没有人。
    
    关键设计：
    - prompt 用配置的 scene 描述（"办公桌前" / "客厅沙发" / ...）
    - 要求看到真实皮肤特征，衣服/包/椅子不算
    - 返回 bool
    """
    import requests
    
    # 获取 API 配置（自动从 models.json 或环境变量读取）
    api_config = _get_api_config()
    if not api_config:
        print("   ⚠️ Vision API 未配置，跳过检测")
        return False
    
    # 压缩图片，省 token
    buf = io.BytesIO()
    small = img.copy()
    small.thumbnail((320, 240))
    small.save(buf, format="JPEG", quality=60)
    img_b64 = base64.b64encode(buf.getvalue()).decode()
    
    scene = config.presence.scene
    prompt = (
        f"Is there a real, living person currently at or near the {scene} "
        f"in this image? Look for visible skin (face, hands, arms). "
        f"Clothes on a chair, bags, or other objects do NOT count. "
        f"Reply ONLY 'yes' or 'no'."
    )
    
    print(f"🧠 Vision API 检测中...")
    print(f"   场景: {scene}")
    
    t0 = time.monotonic()
    resp = requests.post(
        f"{api_config['base_url']}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_config['api_key']}",
            "Content-Type": "application/json",
            **api_config.get("headers", {}),
        },
        json={
            "model": api_config["model"],
            "max_tokens": 20,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
        },
        timeout=config.vision.timeout,
    )
    elapsed = int((time.monotonic() - t0) * 1000)
    
    result = resp.json()
    answer = result["choices"][0]["message"]["content"].strip().lower()
    tokens = result.get("usage", {}).get("total_tokens", 0)
    detected = answer.startswith("yes")
    
    print(f"   {'✅ 有人' if detected else '❌ 无人'} (answer='{answer}', {elapsed}ms, {tokens} tokens)")
    return detected


def _get_api_config() -> dict:
    """从 models.json 或环境变量获取 Vision API 配置"""
    # 方式一：环境变量
    base_url = os.environ.get("LLM_BASE_URL")
    api_key = os.environ.get("LLM_API_KEY")
    model = os.environ.get("LLM_MODEL", "")
    if base_url and api_key:
        return {"base_url": base_url, "api_key": api_key, "model": model, "headers": {}}
    
    # 方式二：models.json（OpenClaw 用户）
    models_file = Path.home() / ".openclaw" / "agents" / "main" / "agent" / "models.json"
    if models_file.exists():
        try:
            data = json.loads(models_file.read_text())
            providers = data.get("providers", {})
            # providers 可能是 dict（按 id 索引）或 list
            if isinstance(providers, dict):
                p = providers.get("litellm", {})
            else:
                p = next((x for x in providers if x.get("id") == "litellm"), {})
            if p.get("baseUrl"):
                # 找一个视觉能力的轻量模型（优先 haiku）
                model_id = ""
                for m in p.get("models", []):
                    mid = m if isinstance(m, str) else m.get("id", "")
                    if "haiku" in mid:
                        model_id = mid
                        break
                if not model_id:
                    model_id = "pa/claude-haiku-4-5-20251001"  # fallback
                return {
                    "base_url": p["baseUrl"].rstrip("/"),
                    "api_key": p.get("apiKey", ""),
                    "model": model_id,
                    "headers": p.get("headers", {}),
                }
        except Exception:
            pass
    return {}


# ═══════════════════════════════════════════════════════════════════
# Step 4: 控制台灯
# ═══════════════════════════════════════════════════════════════════

def control_lamp(present: bool, dry_run: bool = False):
    """
    根据检测结果控制台灯。
    
    使用插件系统 — 实际调用的是 prism_config.yaml 里配置的设备插件。
    """
    hour = datetime.now(TZ).hour
    
    # 通过 Prism 插件系统触发（跟 daemon 用的同一套）
    from src.screen.plugin_loader import trigger_present, trigger_absent
    
    if dry_run:
        print(f"💡 Dry-run: {'有人' if present else '无人'}, 时段={hour}:00")
        print(f"   如果不是 dry-run，会触发所有已注册的设备插件")
        return
    
    if present:
        print(f"💡 有人 → 触发设备联动 (时段={hour}:00)")
        trigger_present(hour)
    else:
        print(f"💡 无人 → 触发设备联动")
        trigger_absent()
    
    print(f"   ✅ 设备联动完成")


# ═══════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════

def run_once(config, dry_run=False):
    """跑一次完整链路"""
    print("=" * 50)
    print(f"⏰ {datetime.now(TZ).strftime('%H:%M:%S')}")
    print()
    
    # 拍照
    img = take_photo()
    print()
    
    # 检测
    present = detect_person(img, config)
    print()
    
    # 控制
    control_lamp(present, dry_run=dry_run)
    print()


def main():
    parser = argparse.ArgumentParser(description="Prism 端到端示例：摄像头 → 检测 → 台灯")
    parser.add_argument("--loop", action="store_true", help="持续检测（每30秒一次）")
    parser.add_argument("--dry-run", action="store_true", help="只检测，不真的控制台灯")
    parser.add_argument("--interval", type=int, default=30, help="loop 模式的检测间隔（秒）")
    args = parser.parse_args()
    
    print("🔌 Prism 端到端示例")
    print("   摄像头 → Vision API → 台灯控制")
    print()
    
    config = load_config()
    
    if args.loop:
        print(f"🔁 持续检测模式（每 {args.interval} 秒），Ctrl+C 退出")
        print()
        try:
            while True:
                run_once(config, dry_run=args.dry_run)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n👋 退出")
    else:
        run_once(config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
