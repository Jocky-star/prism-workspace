#!/usr/bin/env python3
"""
prism_daemon.py — Prism 自动刷新守护进程（插件化重构版）

架构：
  三层管线：感知 (Sensor) → 检测 (Detector) → 执行 (Device)
  daemon 只负责调度，不知道任何具体实现。

功能：
  - 每 10 秒刷新屏幕
  - 每 30 秒采集传感器数据，运行检测器管线判断是否有人
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
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 配置加载 ─────────────────────────────────────────────────────────────────
_SCREEN_DIR = Path(__file__).resolve().parent
_SRC_DIR = _SCREEN_DIR.parent
if str(_SRC_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR.parent))

from src.screen.config_loader import get_config as _get_prism_config
_cfg = _get_prism_config()

# ── 路径配置 ─────────────────────────────────────────────────────────────────
WORKSPACE = _cfg.workspace
MEMORY_DIR = WORKSPACE / "memory"
SCRIPTS_DIR = WORKSPACE / "src" / "screen"

STATE_FILE    = MEMORY_DIR / "prism_state.json"
PRESENCE_FILE = MEMORY_DIR / "prism_presence.json"
EVENTS_FILE   = MEMORY_DIR / "prism_events.json"
LOG_FILE = WORKSPACE / "logs" / "prism_daemon.log"

FB_PATH = _cfg.screen.fb_path
TZ = timezone(timedelta(hours=8))

# ── 参数（从配置读取）────────────────────────────────────────────────────────
ABSENT_TIMEOUT   = _cfg.presence.absent_timeout
CAMERA_INTERVAL  = _cfg.presence.camera_interval
DISPLAY_INTERVAL = _cfg.screen.display_interval

# SPI 自动恢复参数
SPI_HEALTH_INTERVAL = 120
SPI_RECOVER_COOLDOWN = 300

# ── 日志 ─────────────────────────────────────────────────────────────────────
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
import logging
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

# ── 懒加载显示模块 ───────────────────────────────────────────────────────────
_display_module = None

def get_display():
    global _display_module
    if _display_module is None:
        sys.path.insert(0, str(SCRIPTS_DIR))
        import display as prism_display
        _display_module = prism_display
    return _display_module


# ── 插件加载 ─────────────────────────────────────────────────────────────────
from src.screen.plugin_loader import (
    load_sensors,
    load_detectors,
    load_devices,
    capture_image,
    run_detection,
    trigger_present,
    trigger_absent,
)


# ── 存在状态管理 ─────────────────────────────────────────────────────────────

class PresenceTracker:
    """
    存在状态追踪器。

    策略：
    - 检测到人 → 重置计时器，present=True
    - 未检测到人 + 帧差高 → 延长计时器（可能有人但检测器漏了）
    - 未检测到人 + 帧差低 → 开始倒计时，超过 ABSENT_TIMEOUT → present=False
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

    def update(self, detected: bool, motion_ratio: float) -> bool:
        """
        根据检测结果和帧差率更新状态。
        返回是否有人。
        """
        now_mono = time.monotonic()
        motion_threshold = _cfg.presence.motion_threshold

        if detected:
            # 检测到人 → 确认有人，重置计时
            self.last_seen_mono = now_mono
            self.present = True
            log.info(f"👤 检测到人 → present=True (帧差={motion_ratio:.2%})")
        elif motion_ratio > motion_threshold:
            # 未检测到人，但帧差显示有运动 → 延长计时
            self.last_seen_mono = now_mono
            log.info(f"🔄 未检测到人，但帧差高 {motion_ratio:.2%} → 延长计时")
        else:
            # 未检测到 + 帧差率低 → 开始倒计时
            elapsed = now_mono - self.last_seen_mono
            remaining = ABSENT_TIMEOUT - elapsed
            if elapsed > ABSENT_TIMEOUT:
                self.present = False
                log.info(f"🌑 连续 {elapsed/60:.1f} 分钟未检测到人 → present=False")
            else:
                log.info(
                    f"⏳ 未检测到人，帧差低 {motion_ratio:.2%}，"
                    f"已 {elapsed:.0f}s / {ABSENT_TIMEOUT}s（还剩 {remaining:.0f}s 判离开）"
                )

        self._save()
        return self.present

    def _save(self):
        now_iso = datetime.now(TZ).isoformat()
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


# ── 事件闪屏 ─────────────────────────────────────────────────────────────────

def _read_events_safe() -> list:
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
    from datetime import datetime as _dt
    now_iso = _dt.now(TZ)
    events = _read_events_safe()
    clean = []
    pending = []
    for ev in events:
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
    if len(clean) != len(events):
        _write_events_safe(clean)
    return pending


def _mark_event_processed(event: dict):
    events = _read_events_safe()
    for ev in events:
        if (ev.get("text") == event.get("text") and
                ev.get("timestamp") == event.get("timestamp")):
            ev["processed"] = True
    _write_events_safe(events)


def _do_flash(display, event: dict, fb_path: str):
    try:
        flash_img = display.render_flash_frame(event)
        from PIL import Image as _PILImage
        dark_img = _PILImage.new("RGB", (480, 320), (0, 0, 0))

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
    try:
        if not os.path.exists(FB_PATH):
            return False
        with open(FB_PATH, 'r+b') as fb:
            fb.seek(0)
            fb.write(b'\x00\x00')
            fb.seek(0)
        return True
    except (IOError, OSError) as e:
        log.warning(f"SPI 健康检查失败: {e}")
        return False


def recover_spi():
    log.warning("🔧 SPI/fb0 异常检测，记录告警等待人工干预或重启恢复")
    return False


def _display_thread_func(tracker_ref):
    try:
        _display_thread_loop(tracker_ref)
    except Exception as e:
        import traceback
        log.error(f"🚨 显示线程致命错误退出: {e}\n{traceback.format_exc()}")


def _display_thread_loop(tracker_ref):
    last_display_time = 0.0
    last_spi_check = 0.0
    spi_recover_until = 0.0
    consecutive_errors = 0

    last_mode = None
    last_frame = None

    while True:
        try:
            now = time.monotonic()
            # ── 事件闪屏检查 ──
            try:
                display = get_display()
                pending = _get_pending_events()
                if pending:
                    ev = pending[0]
                    log.info(f"⚡ 收到事件: [{ev.get('type','')}] {ev.get('text','')}")
                    _mark_event_processed(ev)
                    _do_flash(display, ev, FB_PATH)
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
                    _hour = datetime.now(TZ).hour
                    _state = display.load_prism_state() if hasattr(display, 'load_prism_state') else {}
                    _dismissed = _state.get("summary_dismissed", False)

                    tracker = tracker_ref()
                    is_present = tracker.present if tracker else True

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
                        try:
                            from prism_transition import fade_transition
                            log.info(f"🎞️ 模式切换 {last_mode} → {current_mode}，执行渐变过渡")
                            fade_transition(last_frame, img, FB_PATH, steps=8, duration=0.5)
                        except Exception as te:
                            log.warning(f"渐变过渡失败，降级直接写入: {te}")
                            display.write_to_framebuffer(img, FB_PATH)
                    else:
                        display.write_to_framebuffer(img, FB_PATH)

                    last_mode = current_mode
                    last_frame = img

                    consecutive_errors = 0
                    log.info(f"🖥️ 屏幕已刷新 ({current_mode} 模式)")
                except FileNotFoundError:
                    log.warning(f"framebuffer {FB_PATH} 不存在，等待重启恢复")
                    last_mode = None
                    last_frame = None
                except Exception as e:
                    log.error(f"屏幕渲染/写入异常: {e}")

            # ── SPI 健康检查 ──
            if now - last_spi_check >= SPI_HEALTH_INTERVAL and now > spi_recover_until:
                last_spi_check = now
                if not check_spi_health():
                    if recover_spi():
                        spi_recover_until = time.monotonic() + SPI_RECOVER_COOLDOWN
                        last_display_time = 0

            time.sleep(1)
        except Exception as e:
            consecutive_errors += 1
            import traceback
            log.error(f"显示线程异常 (连续第{consecutive_errors}次): {e}\n{traceback.format_exc()}")
            if consecutive_errors >= 20:
                log.error("🚨 显示线程连续异常过多，退出等待看门狗拉起")
                return
            time.sleep(min(5 * consecutive_errors, 30))


def _start_display_thread(tracker_weakref):
    t = threading.Thread(target=_display_thread_func, args=(tracker_weakref,), daemon=True, name="display")
    t.start()
    log.info("🖥️ 显示线程已启动（独立于主循环）")
    return t


# ── 主循环 ───────────────────────────────────────────────────────────────────

def main_loop():
    log.info("🚀 Prism daemon 启动（插件化架构）")

    # 1. 加载配置和插件
    config = _get_prism_config()
    sensors = load_sensors(config)
    detectors = load_detectors(config)
    devices = load_devices(config)
    tracker = PresenceTracker()

    log.info(f"📦 插件加载完成: {len(sensors)} sensors, {len(detectors)} detectors, {len(devices)} devices")

    # 2. 启动显示线程
    import weakref
    tracker_weakref = weakref.ref(tracker)
    display_thread = _start_display_thread(tracker_weakref)
    display_watchdog_interval = 30
    last_display_watchdog = time.monotonic()
    display_crash_count = 0

    # 3. 主循环变量
    last_camera_time = 0.0
    last_auto_status = 0.0
    last_weather_update = 0.0

    AUTO_STATUS_INTERVAL = 30
    WEATHER_UPDATE_INTERVAL = 1800

    while True:
        now = time.monotonic()

        # ── 感知 → 检测 → 判定 → 执行 ──────────────────────────────────
        if now - last_camera_time >= CAMERA_INTERVAL:
            last_camera_time = now
            try:
                # 1. 感知：采集图像
                image = capture_image(sensors)
                if image is None:
                    log.debug("所有 sensor 均失败，跳过本次检测")
                    continue

                # 2. 检测：运行检测器管线
                context = {"prev_present": tracker.present}
                detected = run_detection(detectors, image, context)

                # 3. 判定：更新存在状态
                motion_ratio = context.get("motion_ratio", 0.0)
                was_present = tracker.present
                is_present = tracker.update(detected, motion_ratio)

                # 4. 执行：状态变化时触发设备
                if was_present != is_present:
                    log.info(f"🔔 存在状态变化: {'有人 🟢' if is_present else '无人 ⚫'}")
                    hour = datetime.now(TZ).hour
                    if is_present:
                        trigger_present(devices, hour)
                    else:
                        trigger_absent(devices)

            except Exception as e:
                log.error(f"检测管线异常: {e}")

        # ── 自动状态感知 ──────────────────────────────────────────────
        if now - last_auto_status >= AUTO_STATUS_INTERVAL:
            last_auto_status = now
            try:
                subprocess.run(
                    [sys.executable, str(SCRIPTS_DIR / "auto_status.py")],
                    capture_output=True, timeout=15
                )
            except Exception as e:
                log.debug(f"自动状态感知异常: {e}")

        # ── 天气更新 ──────────────────────────────────────────────────
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

        # ── 显示线程看门狗 ────────────────────────────────────────────
        if now - last_display_watchdog >= display_watchdog_interval:
            last_display_watchdog = now
            if not display_thread.is_alive():
                display_crash_count += 1
                log.warning(f"⚠️ 显示线程已死亡，第 {display_crash_count} 次自动拉起")
                display_thread = _start_display_thread(tracker_weakref)
                if display_crash_count >= 10:
                    log.error(f"🚨 显示线程已崩溃 {display_crash_count} 次，可能存在系统问题")

        # ── sleep ─────────────────────────────────────────────────────
        now2 = time.monotonic()
        next_camera = last_camera_time + CAMERA_INTERVAL
        sleep_secs = max(0.5, next_camera - now2)
        time.sleep(sleep_secs)


def main():
    parser = argparse.ArgumentParser(description="Prism 屏幕守护进程")
    parser.add_argument("--daemon", action="store_true", help="以 nohup 后台模式启动（自我 daemonize）")
    args = parser.parse_args()

    if args.daemon:
        pid = os.fork()
        if pid > 0:
            print(f"✅ Prism daemon 已在后台启动 (pid={pid})")
            sys.exit(0)
        os.setsid()
        sys.stdin = open(os.devnull, "r")

    main_loop()


if __name__ == "__main__":
    main()
