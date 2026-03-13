#!/usr/bin/env python3
"""
prism_daemon.py — Prism 自动刷新守护进程

功能：
  - 每 10 秒读取 prism_state.json 并刷新屏幕
  - 每 30 秒拍照，用 Vision API (Haiku) 检测是否有人（帧差法辅助）
  - 有人 → 完整状态界面；无人 → 暗屏模式
  - 检测结果写入 prism_presence.json
  - 健壮：文件读取/渲染异常不崩溃

启动：
  python3 prism_daemon.py          # 前台运行
  python3 prism_daemon.py --daemon # nohup 后台
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Camera lock to prevent contention with cron scripts
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sources" / "camera"))
from lock import camera_lock
import logging

# ── 路径配置 ────────────────────────────────────────────────────────────────
WORKSPACE = Path(os.path.expanduser("~/.openclaw/workspace"))
MEMORY_DIR = WORKSPACE / "memory"
SCRIPTS_DIR = WORKSPACE / "src" / "screen"

STATE_FILE    = MEMORY_DIR / "prism_state.json"
PRESENCE_FILE = MEMORY_DIR / "prism_presence.json"
PREV_THUMB_FILE = MEMORY_DIR / ".prism_prev_thumb.jpg"
EVENTS_FILE   = MEMORY_DIR / "prism_events.json"
LOG_FILE = WORKSPACE / "logs" / "prism_daemon.log"

FB_PATH = "/dev/fb0"

TZ = timezone(timedelta(hours=8))

# ── 检测参数 ─────────────────────────────────────────────────────────────────
MOTION_THRESHOLD = 0.05      # 帧差比例阈值（5% 像素变化 = 有运动）
ABSENT_TIMEOUT = 300         # 连续 5 分钟无检测 = 离开
CAMERA_INTERVAL = 30         # 拍照间隔（秒）
DISPLAY_INTERVAL = 10        # 屏幕刷新间隔（秒）
THUMB_W, THUMB_H = 160, 120  # 缩略图大小（帧差用）

# SPI 自动恢复参数
SPI_HEALTH_INTERVAL = 120    # 每 120 秒检查一次 SPI 健康
SPI_RECOVER_COOLDOWN = 300   # 恢复后冷却 5 分钟再检查

# Vision API 检测参数
VISION_API_MODEL = "pa/claude-haiku-4-5-20251001"
VISION_API_TIMEOUT = 15      # API 超时秒数

# ── 日志 ─────────────────────────────────────────────────────────────────────
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.root.handlers.clear()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("prism")

# ── 懒加载显示模块 ────────────────────────────────────────────────────────────
_display_module = None

def get_display():
    global _display_module
    if _display_module is None:
        sys.path.insert(0, str(SCRIPTS_DIR))
        import display as prism_display
        _display_module = prism_display
    return _display_module


# ── 懒加载米家联动模块 ────────────────────────────────────────────────────────
_mijia_module = None

def _get_mijia():
    global _mijia_module
    if _mijia_module is None:
        try:
            if str(SCRIPTS_DIR) not in sys.path:
                sys.path.insert(0, str(SCRIPTS_DIR))
            import mijia as prism_mijia
            _mijia_module = prism_mijia
        except Exception as e:
            log.warning(f"米家模块加载失败: {e}")
    return _mijia_module


def _trigger_presence_change(present: bool):
    """安全触发米家存在联动，失败静默"""
    try:
        mijia = _get_mijia()
        if mijia:
            mijia.on_presence_change(present)
    except Exception as e:
        log.warning(f"米家联动异常: {e}")


# ── Vision API 人体检测器 ─────────────────────────────────────────────────
_vision_api_config = None


def _get_vision_api_config() -> dict:
    """从 models.json 懒加载 API 配置"""
    global _vision_api_config
    if _vision_api_config is None:
        try:
            models_path = Path.home() / ".openclaw/agents/main/agent/models.json"
            with open(models_path) as f:
                d = json.load(f)
            prov = d["providers"]["litellm"]
            _vision_api_config = {
                "base_url": prov["baseUrl"],
                "api_key": prov["apiKey"],
                "headers": prov.get("headers", {}),
            }
            log.info("✅ Vision API 配置已加载")
        except Exception as e:
            log.error(f"Vision API 配置加载失败: {e}")
            _vision_api_config = {}
    return _vision_api_config


def detect_person_vision(img) -> tuple[bool, str]:
    """
    用 Vision API (Haiku) 检测是否有人。
    返回 (detected: bool, description: str)。
    比 HOG/级联检测准确得多，尤其对坐姿/侧面/低光。
    """
    import base64
    import io
    import requests

    config = _get_vision_api_config()
    if not config.get("base_url"):
        log.warning("Vision API 未配置，跳过检测")
        return False, "no_config"

    try:
        t0 = time.monotonic()

        # 压缩图片到 JPEG，降低 token 消耗
        buf = io.BytesIO()
        img_small = img.copy()
        img_small.thumbnail((320, 240))
        img_small.save(buf, format="JPEG", quality=60)
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        headers = {
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json",
            **config["headers"],
        }

        payload = {
            "model": VISION_API_MODEL,
            "max_tokens": 20,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                    {"type": "text", "text": "Is there a person in this image? Reply ONLY 'yes' or 'no'."},
                ],
            }],
        }

        resp = requests.post(
            f"{config['base_url']}/chat/completions",
            headers=headers,
            json=payload,
            timeout=VISION_API_TIMEOUT,
        )

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        if resp.status_code != 200:
            log.warning(f"Vision API 返回 {resp.status_code}: {resp.text[:200]}")
            return False, f"api_error_{resp.status_code}"

        result = resp.json()
        answer = result["choices"][0]["message"]["content"].strip().lower()
        tokens = result.get("usage", {}).get("total_tokens", 0)
        detected = answer.startswith("yes")

        log.info(f"🧠 Vision API: {'✅ 有人' if detected else '❌ 无人'} "
                 f"(answer='{answer}', {elapsed_ms}ms, {tokens} tokens)")
        return detected, answer

    except requests.exceptions.Timeout:
        log.warning("Vision API 超时")
        return False, "timeout"
    except Exception as e:
        log.warning(f"Vision API 异常: {e}")
        return False, f"error: {e}"


# ── 帧差法检测运动 ────────────────────────────────────────────────────────────

def compute_frame_diff(img_new) -> float:
    """对比新帧和上一帧缩略图，返回差异比例 0.0~1.0"""
    from PIL import Image
    try:
        thumb_new = img_new.convert("L").resize((THUMB_W, THUMB_H))
        if not PREV_THUMB_FILE.exists():
            # 没有历史帧，保存并返回「有运动」（保守策略）
            thumb_new.save(str(PREV_THUMB_FILE))
            return 1.0

        thumb_old = Image.open(str(PREV_THUMB_FILE)).convert("L").resize((THUMB_W, THUMB_H))
        pixels_new = thumb_new.tobytes()
        pixels_old = thumb_old.tobytes()

        total = len(pixels_new)
        diffs = sum(1 for n, o in zip(pixels_new, pixels_old) if abs(n - o) > 20)
        ratio = diffs / total

        # 保存新帧（无论有无运动都更新参考帧，避免背景漂移）
        thumb_new.save(str(PREV_THUMB_FILE))
        return ratio
    except Exception as e:
        log.warning(f"帧差计算失败: {e}")
        return 0.0


def take_photo_for_detection() -> "Image or None":
    """拍一张低分辨率照片用于检测，返回 PIL Image"""
    try:
        from PIL import Image
        import io
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp_path = tmp.name
        tmp.close()

        env = dict(os.environ, LIBCAMERA_LOG_LEVELS="*:ERROR")
        with camera_lock(timeout=10):
            result = subprocess.run(
                ["rpicam-still", "-o", tmp_path,
                 "--width", "640", "--height", "480",
                 "--timeout", "1000", "--nopreview",
                 "--rotation", "180"],  # camera is physically inverted
                capture_output=True, timeout=15, env=env
            )
        if result.returncode != 0:
            log.warning(f"rpicam-still 失败: {result.stderr.decode()[:100]}")
            os.unlink(tmp_path)
            return None

        img = Image.open(tmp_path)
        # rotation handled by --rotation 180 in rpicam-still
        img.load()              # 确保数据加载后再删文件
        os.unlink(tmp_path)
        return img
    except Exception as e:
        log.warning(f"拍照失败: {e}")
        return None


# ── 存在状态管理 ──────────────────────────────────────────────────────────────

class PresenceTracker:
    """
    双保险检测策略：
      1. HOG 检测到人体 → 肯定有人，重置计时器
      2. HOG 未检测到 + 帧差率高 → 可能有人（延长计时器，不立刻判离开）
      3. HOG 未检测到 + 帧差率低 → 开始计时，超过 ABSENT_TIMEOUT → 离开
    """

    def __init__(self):
        self.last_seen_mono = time.monotonic()
        self.present = True
        self._load()

    def _load(self):
        """从文件恢复上次状态"""
        if PRESENCE_FILE.exists():
            try:
                data = json.loads(PRESENCE_FILE.read_text(encoding="utf-8"))
                self.present = data.get("present", True)
                log.info(f"恢复存在状态: present={self.present}")
            except Exception:
                pass

    def update(self, vision_detected: bool, motion_ratio: float) -> bool:
        """
        根据 Vision API 结果和帧差率更新状态。
        返回是否有人。
        """
        now_mono = time.monotonic()

        if vision_detected:
            # Vision API 检测到人 → 确认有人，重置计时
            self.last_seen_mono = now_mono
            self.present = True
            log.info(f"👤 Vision 检测到人 → present=True (帧差={motion_ratio:.2%})")
        elif motion_ratio > MOTION_THRESHOLD:
            # Vision 未检测到人，但帧差显示有运动 → 延长计时
            self.last_seen_mono = now_mono
            log.info(f"🔄 Vision 未检测到人，但帧差高 {motion_ratio:.2%} → 延长计时")
        else:
            # Vision 未检测到 + 帧差率低 → 开始倒计时
            elapsed = now_mono - self.last_seen_mono
            remaining = ABSENT_TIMEOUT - elapsed
            if elapsed > ABSENT_TIMEOUT:
                self.present = False
                log.info(f"🌑 连续 {elapsed/60:.1f} 分钟未检测到人 → present=False")
            else:
                log.info(
                    f"⏳ Vision 未检测到人，帧差低 {motion_ratio:.2%}，"
                    f"已 {elapsed:.0f}s / {ABSENT_TIMEOUT}s（还剩 {remaining:.0f}s 判离开）"
                )

        self._save()
        return self.present

    def _save(self):
        now_iso = datetime.now(TZ).isoformat()
        # 有人时更新 last_seen；无人时保留最后一次看到的时间
        if self.present:
            last_seen = now_iso
        else:
            last_seen = self._last_seen_iso()

        data = {
            "present": self.present,
            "last_seen": last_seen,
            "last_check": now_iso,
        }
        try:
            PRESENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = PRESENCE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(PRESENCE_FILE)
        except Exception as e:
            log.warning(f"写 presence 文件失败: {e}")

    def _last_seen_iso(self) -> str:
        if PRESENCE_FILE.exists():
            try:
                data = json.loads(PRESENCE_FILE.read_text(encoding="utf-8"))
                return data.get("last_seen", datetime.now(TZ).isoformat())
            except Exception:
                pass
        return datetime.now(TZ).isoformat()


# ── 主循环 ────────────────────────────────────────────────────────────────────


# ── 事件闪屏（Event Flash）────────────────────────────────────────────────────

def _read_events_safe() -> list:
    """读取 prism_events.json，返回事件列表，失败返回 []"""
    if not EVENTS_FILE.exists():
        return []
    try:
        import fcntl
        with open(EVENTS_FILE, "r", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                data = json.load(f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        return data.get("events", [])
    except Exception as e:
        log.debug(f"读取事件文件失败: {e}")
        return []


def _write_events_safe(events: list):
    """原子写回 prism_events.json（带文件锁）"""
    try:
        import fcntl
        EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = EVENTS_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                json.dump({"events": events}, f, ensure_ascii=False, indent=2)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        tmp.replace(EVENTS_FILE)
    except Exception as e:
        log.warning(f"写入事件文件失败: {e}")


def _get_pending_events() -> list[dict]:
    """
    读取事件列表，自动清理过期事件，返回待处理（未 processed 且未过期）事件。
    同时写回清理结果。
    """
    from datetime import datetime as _dt
    now_iso = _dt.now(TZ)
    events = _read_events_safe()
    clean = []
    pending = []
    for ev in events:
        # 过期检查
        ts_str = ev.get("timestamp", "")
        ttl = ev.get("ttl", 30)
        try:
            ts = _dt.fromisoformat(ts_str)
            age = (now_iso - ts).total_seconds()
        except Exception:
            age = 0
        if age > ttl:
            log.debug(f"事件已过期，丢弃: {ev.get('text','')}")
            continue
        clean.append(ev)
        if not ev.get("processed", False):
            pending.append(ev)
    # 回写清理后的列表
    if len(clean) != len(events):
        _write_events_safe(clean)
    return pending


def _mark_event_processed(event: dict):
    """将某条事件标记为已处理"""
    events = _read_events_safe()
    for ev in events:
        if (ev.get("text") == event.get("text") and
                ev.get("timestamp") == event.get("timestamp")):
            ev["processed"] = True
    _write_events_safe(events)


def _do_flash(display, event: dict, fb_path: str):
    """
    执行闪屏动画：亮-暗-亮-暗-亮，共 3 秒。
    在调用线程同步执行（已在独立显示线程中，不阻塞主循环）。
    """
    try:
        flash_img = display.render_flash_frame(event)
        # 暗帧：纯黑
        from PIL import Image as _PILImage
        dark_img = _PILImage.new("RGB", (480, 320), (0, 0, 0))

        # 闪 3 次：亮(0.5s) 暗(0.2s) 亮(0.5s) 暗(0.2s) 亮(0.6s) = 2.0s
        # 然后静止停留 1 秒 → 总计 3 秒
        sequence = [
            (flash_img, 0.5),
            (dark_img,  0.2),
            (flash_img, 0.5),
            (dark_img,  0.2),
            (flash_img, 0.5),
            (dark_img,  0.1),
        ]
        for frm, dur in sequence:
            display.write_to_framebuffer(frm, fb_path)
            time.sleep(dur)
        log.info(f"⚡ 事件闪屏完成: [{event.get('type','')}] {event.get('text','')}")
    except Exception as e:
        log.error(f"事件闪屏渲染失败: {e}")


def check_spi_health() -> bool:
    """检查 fb0 是否可写"""
    try:
        if not os.path.exists(FB_PATH):
            return False
        with open(FB_PATH, 'r+b') as fb:
            fb.seek(0)
            fb.write(b'\x00\x00')  # 写一个像素测试
            fb.seek(0)
        return True
    except (IOError, OSError) as e:
        log.warning(f"SPI 健康检查失败: {e}")
        return False


def recover_spi():
    """尝试恢复屏幕显示（不卸载内核模块，只记录告警）"""
    log.warning("🔧 SPI/fb0 异常检测，记录告警等待人工干预或重启恢复")
    # 不再 rmmod/modprobe——卸载模块会导致 fb0 消失且可能卡死
    # 只记录日志，下次重启自动恢复
    return False


def _display_thread_func(tracker_ref):
    """独立线程：每 DISPLAY_INTERVAL 秒刷新屏幕，不受摄像头/auto_status 阻塞影响"""
    last_display_time = 0.0
    last_spi_check = 0.0
    spi_recover_until = 0.0

    # ── 渐变过渡状态追踪 ──────────────────────────────────────────────────────
    last_mode = None    # "normal" / "dim" / "summary"
    last_frame = None   # 上一次渲染的 PIL Image，用于 blend 起点

    while True:
        try:
            now = time.monotonic()
            # ── 事件闪屏检查（每次循环都检查，优先级最高）──
            try:
                display = get_display()
                pending = _get_pending_events()
                if pending:
                    ev = pending[0]
                    log.info(f"⚡ 收到事件: [{ev.get('type','')}] {ev.get('text','')}")
                    _mark_event_processed(ev)
                    _do_flash(display, ev, FB_PATH)
                    # 闪屏后立刻强制刷新正常画面，同时重置帧缓存（闪屏已破坏上一帧）
                    last_display_time = 0.0
                    last_mode = None
                    last_frame = None
            except Exception as e:
                log.error(f"事件闪屏检查异常: {e}")

            # ── 屏幕刷新 ──
            if now - last_display_time >= DISPLAY_INTERVAL:
                last_display_time = now
                try:
                    display = get_display()
                    from datetime import datetime, timezone, timedelta
                    _tz = timezone(timedelta(hours=8))
                    _hour = datetime.now(_tz).hour
                    _state = display.load_prism_state() if hasattr(display, 'load_prism_state') else {}
                    _dismissed = _state.get("summary_dismissed", False)

                    tracker = tracker_ref()
                    is_present = tracker.present if tracker else True

                    # ── 决定当前模式并渲染新帧 ──
                    if not is_present:
                        current_mode = "dim"
                        img = display.render_dim_frame()
                    elif 18 <= _hour < 20 and not _dismissed:
                        current_mode = "summary"
                        img = display.render_summary_frame()
                    else:
                        current_mode = "normal"
                        img = display.render_frame()
                        if _hour >= 20 and _dismissed:
                            _state["summary_dismissed"] = False
                            display.save_prism_state(_state) if hasattr(display, 'save_prism_state') else None

                    # ── 渐变过渡 or 直接写入 ──
                    if last_mode is not None and current_mode != last_mode and last_frame is not None:
                        # 模式发生变化 → 渐变过渡
                        try:
                            from prism_transition import fade_transition
                            log.info(f"🎞️ 模式切换 {last_mode} → {current_mode}，执行渐变过渡")
                            fade_transition(last_frame, img, FB_PATH, steps=8, duration=0.5)
                        except Exception as te:
                            # 渐变失败时降级为直接写入，不影响正常运行
                            log.warning(f"渐变过渡失败，降级直接写入: {te}")
                            display.write_to_framebuffer(img, FB_PATH)
                    else:
                        # 同模式内定时刷新 → 直接写入
                        display.write_to_framebuffer(img, FB_PATH)

                    # ── 更新帧缓存 ──
                    last_mode = current_mode
                    last_frame = img

                    log.debug(f"屏幕已刷新 ({current_mode} 模式)")
                except FileNotFoundError:
                    log.warning(f"framebuffer {FB_PATH} 不存在，等待重启恢复")
                    last_mode = None   # 重置缓存，重连后重建基线
                    last_frame = None
                except Exception as e:
                    log.error(f"屏幕渲染/写入异常: {e}")

            # ── SPI 健康检查（每 120 秒）──
            if now - last_spi_check >= SPI_HEALTH_INTERVAL and now > spi_recover_until:
                last_spi_check = now
                if not check_spi_health():
                    if recover_spi():
                        spi_recover_until = time.monotonic() + SPI_RECOVER_COOLDOWN
                        last_display_time = 0

            time.sleep(1)  # 1秒轮询精度足够
        except Exception as e:
            log.error(f"显示线程异常: {e}")
            time.sleep(5)


def main_loop():
    log.info("🚀 Prism daemon 启动")
    tracker = PresenceTracker()

    # 启动独立显示线程（用 weakref 避免循环引用）
    import weakref
    tracker_weakref = weakref.ref(tracker)
    display_thread = threading.Thread(target=_display_thread_func, args=(tracker_weakref,), daemon=True)
    display_thread.start()
    log.info("🖥️ 显示线程已启动（独立于主循环）")

    last_camera_time = 0.0
    last_auto_status = 0.0
    last_weather_update = 0.0

    AUTO_STATUS_INTERVAL = 30  # 每 30 秒自动感知一次
    WEATHER_UPDATE_INTERVAL = 1800  # 每 30 分钟更新天气

    while True:
        now = time.monotonic()

        # ── 摄像头检测（每 30 秒）──────────────────────────────────────────
        if now - last_camera_time >= CAMERA_INTERVAL:
            last_camera_time = now
            try:
                img = take_photo_for_detection()
                if img is not None:
                    # 帧差法（快速预筛）
                    motion_ratio = compute_frame_diff(img)

                    # Vision API 人体检测（主检测）
                    t0 = time.monotonic()
                    vision_detected, vision_answer = detect_person_vision(img)
                    vision_ms = int((time.monotonic() - t0) * 1000)

                    log.info(
                        f"📷 检测完成 — Vision: {'✅ 有人' if vision_detected else '❌ 无人'} "
                        f"({vision_ms}ms)，帧差: {motion_ratio:.2%}"
                    )

                    was_present = tracker.present
                    is_present = tracker.update(vision_detected, motion_ratio)
                    if was_present != is_present:
                        log.info(f"🔔 存在状态变化: {'有人 🟢' if is_present else '无人 ⚫'}")
                        _trigger_presence_change(is_present)
                else:
                    # 拍照失败时保守策略：维持当前状态（不改变）
                    log.debug("拍照失败，跳过本次检测")
            except Exception as e:
                log.error(f"摄像头检测异常: {e}")

        # ── 自动状态感知（每 30 秒）───────────────────────────────────────────
        if now - last_auto_status >= AUTO_STATUS_INTERVAL:
            last_auto_status = now
            try:
                subprocess.run(
                    [sys.executable, str(SCRIPTS_DIR / "auto_status.py")],
                    capture_output=True, timeout=15
                )
            except Exception as e:
                log.debug(f"自动状态感知异常: {e}")

        # ── 天气更新（每 30 分钟）─────────────────────────────────────────────
        if now - last_weather_update >= WEATHER_UPDATE_INTERVAL:
            last_weather_update = now
            try:
                subprocess.Popen(
                    [sys.executable, str(SCRIPTS_DIR / "weather.py")],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                log.debug("天气更新已触发（异步）")
            except Exception as e:
                log.debug(f"天气更新触发失败（不影响主循环）: {e}")

        # ── 屏幕刷新已移至独立线程（_display_thread_func），不再阻塞主循环 ──

        # ── sleep：等待下次摄像头检测 ────────────────────────────
        now2 = time.monotonic()
        next_camera = last_camera_time + CAMERA_INTERVAL
        sleep_secs = max(0.5, next_camera - now2)
        time.sleep(sleep_secs)


def main():
    parser = argparse.ArgumentParser(description="Prism 屏幕守护进程")
    parser.add_argument("--daemon", action="store_true", help="以 nohup 后台模式启动（自我 daemonize）")
    args = parser.parse_args()

    if args.daemon:
        # 简单 daemonize：fork 后台运行
        pid = os.fork()
        if pid > 0:
            print(f"✅ Prism daemon 已在后台启动 (pid={pid})")
            sys.exit(0)
        # 子进程
        os.setsid()
        sys.stdin = open(os.devnull, "r")

    main_loop()


if __name__ == "__main__":
    main()
