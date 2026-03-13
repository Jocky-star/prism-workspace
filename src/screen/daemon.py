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
LOG_FILE = WORKSPACE / "logs" / "prism_daemon.log"

TZ = timezone(timedelta(hours=8))

# ── 参数（从配置读取）────────────────────────────────────────────────────────
ABSENT_TIMEOUT   = _cfg.presence.absent_timeout
CAMERA_INTERVAL  = _cfg.presence.camera_interval

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


# ── 主循环 ───────────────────────────────────────────────────────────────────

def _acquire_pidlock() -> bool:
    """
    PID 锁：同一时间只允许一个 daemon 实例运行。
    
    如果已有另一个 daemon 在跑，打日志并退出，不会静默地双开。
    锁文件：memory/.prism_daemon.pid
    """
    pidfile = MEMORY_DIR / ".prism_daemon.pid"
    
    if pidfile.exists():
        try:
            old_pid = int(pidfile.read_text().strip())
            # 检查旧进程是否还活着
            os.kill(old_pid, 0)  # 不发信号，只检查
            if old_pid != os.getpid():
                log.error(f"🚨 另一个 daemon 已在运行 (PID {old_pid})，退出")
                log.error(f"   如果那个进程已经死了，删除 {pidfile} 后重试")
                return False
        except (ProcessLookupError, ValueError):
            # 旧进程已死，清理
            pass
        except PermissionError:
            log.error(f"🚨 无法检查 PID {pidfile.read_text().strip()}，退出")
            return False
    
    # 写入当前 PID
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    pidfile.write_text(str(os.getpid()))
    log.info(f"🔒 PID 锁已获取 (PID {os.getpid()})")
    return True


def _release_pidlock():
    """释放 PID 锁"""
    pidfile = MEMORY_DIR / ".prism_daemon.pid"
    try:
        if pidfile.exists():
            stored_pid = int(pidfile.read_text().strip())
            if stored_pid == os.getpid():
                pidfile.unlink()
                log.info("🔓 PID 锁已释放")
    except Exception:
        pass


def main_loop():
    # PID 锁：防止双开
    if not _acquire_pidlock():
        sys.exit(1)
    
    import atexit
    atexit.register(_release_pidlock)
    
    log.info("🚀 Prism daemon 启动（插件化架构）")

    # 1. 加载配置和插件
    config = _get_prism_config()
    sensors = load_sensors(config)
    detectors = load_detectors(config)
    devices = load_devices(config)
    tracker = PresenceTracker()

    log.info(f"📦 插件加载完成: {len(sensors)} sensors, {len(detectors)} detectors, {len(devices)} devices")

    # 启动时同步一次设备状态（防止外部脚本改了设备但 daemon 不知道）
    try:
        hour = datetime.now(TZ).hour
        if tracker.present:
            log.info(f"🔌 启动同步：当前有人 → 触发 on_present (时段={hour}:00)")
            trigger_present(devices, hour)
        else:
            log.info(f"🔌 启动同步：当前无人 → 触发 on_absent")
            trigger_absent(devices)
    except Exception as e:
        log.warning(f"启动同步设备状态失败: {e}")

    # 2. 设备插件已在 load_devices() 时自动调用 on_init()
    #    spi_screen 的 on_init 会启动显示线程

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
