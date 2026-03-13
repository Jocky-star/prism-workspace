"""
内置执行器插件：spi_screen — SPI 屏幕显示

持续刷新 framebuffer 屏幕，根据存在状态切换显示模式：
- 有人 → 状态板（NOW/DONE/NOTE）或便签摘要
- 无人 → 暗屏（时间+日期）

支持事件闪屏、模式渐变过渡、SPI 健康自恢复。

prism_config.yaml 配置示例：
    devices:
      - plugin: spi_screen
        enabled: true
        config:
          fb_path: "/dev/fb0"
          display_interval: 10    # 刷新间隔秒数
          spi_health_check: 120   # SPI 健康检查间隔
          spi_recover_cooldown: 300

没有 SPI 屏幕的用户不配这项就行，daemon 不会报错。
"""

import logging
import os
import sys
import time
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict

from .. import DevicePlugin

log = logging.getLogger("prism.device.spi_screen")

TZ = timezone(timedelta(hours=8))


class Plugin(DevicePlugin):
    """SPI 屏幕设备插件 — 自带显示线程"""

    _DEFAULTS = {
        "fb_path": "/dev/fb0",
        "display_interval": 10,
        "spi_health_check": 120,
        "spi_recover_cooldown": 300,
    }

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        for k, v in self._DEFAULTS.items():
            if k not in self.config:
                self.config[k] = v

        self._present = True
        self._display_thread = None
        self._display_module = None
        self._lock = threading.Lock()

    # ── DevicePlugin 接口 ──

    def on_init(self):
        """daemon 启动时调用 — 启动显示线程"""
        fb = self.config["fb_path"]
        if not os.path.exists(fb):
            log.warning(f"framebuffer {fb} 不存在，spi_screen 插件不启动")
            return
        self._start_display_thread()
        log.info(f"SPI 屏幕插件已启动 (fb={fb}, interval={self.config['display_interval']}s)")

    def on_present(self, hour: int):
        with self._lock:
            self._present = True

    def on_absent(self):
        with self._lock:
            self._present = False

    def on_shutdown(self):
        log.info("SPI 屏幕插件关闭")

    @property
    def is_alive(self) -> bool:
        return self._display_thread is not None and self._display_thread.is_alive()

    # ── 显示线程 ──

    def _start_display_thread(self):
        self._display_thread = threading.Thread(
            target=self._thread_wrapper, daemon=True, name="spi_screen"
        )
        self._display_thread.start()

    def _thread_wrapper(self):
        try:
            self._thread_loop()
        except Exception as e:
            import traceback
            log.error(f"🚨 SPI 屏幕线程致命错误: {e}\n{traceback.format_exc()}")

    def _get_display(self):
        """懒加载 display 模块"""
        if self._display_module is None:
            scripts_dir = Path(__file__).resolve().parents[2]  # plugins/devices/../../ = screen/
            if str(scripts_dir) not in sys.path:
                sys.path.insert(0, str(scripts_dir))
            import display as prism_display
            self._display_module = prism_display
        return self._display_module

    def _thread_loop(self):
        fb_path = self.config["fb_path"]
        interval = self.config["display_interval"]
        spi_check_interval = self.config["spi_health_check"]
        spi_cooldown = self.config["spi_recover_cooldown"]

        last_display_time = 0.0
        last_spi_check = 0.0
        spi_recover_until = 0.0
        consecutive_errors = 0
        last_mode = None
        last_frame = None

        while True:
            try:
                now = time.monotonic()

                # ── 事件闪屏 ──
                try:
                    display = self._get_display()
                    pending = self._get_pending_events()
                    if pending:
                        ev = pending[0]
                        log.info(f"⚡ 事件: [{ev.get('type','')}] {ev.get('text','')}")
                        self._mark_event_processed(ev)
                        self._do_flash(display, ev, fb_path)
                        last_display_time = 0.0
                        last_mode = None
                        last_frame = None
                except Exception as e:
                    log.error(f"事件闪屏异常: {e}")

                # ── 屏幕刷新 ──
                if now - last_display_time >= interval:
                    last_display_time = now
                    try:
                        display = self._get_display()
                        hour = datetime.now(TZ).hour
                        state = display.load_prism_state() if hasattr(display, 'load_prism_state') else {}
                        dismissed = state.get("summary_dismissed", False)

                        with self._lock:
                            is_present = self._present

                        if not is_present:
                            current_mode = "dim"
                            img = display.render_dim_frame()
                        elif 18 <= hour < 20 and not dismissed:
                            current_mode = "summary"
                            img = display.render_summary_frame()
                        else:
                            current_mode = "normal"
                            img = display.render_frame()
                            if hour >= 20 and dismissed:
                                state["summary_dismissed"] = False
                                if hasattr(display, 'save_prism_state'):
                                    display.save_prism_state(state)

                        # 模式切换渐变
                        if last_mode is not None and current_mode != last_mode and last_frame is not None:
                            try:
                                from prism_transition import fade_transition
                                log.info(f"🎞️ {last_mode} → {current_mode} 渐变")
                                fade_transition(last_frame, img, fb_path, steps=8, duration=0.5)
                            except Exception:
                                display.write_to_framebuffer(img, fb_path)
                        else:
                            display.write_to_framebuffer(img, fb_path)

                        last_mode = current_mode
                        last_frame = img
                        consecutive_errors = 0
                        log.info(f"🖥️ 屏幕已刷新 ({current_mode} 模式)")

                    except FileNotFoundError:
                        log.warning(f"framebuffer {fb_path} 不存在")
                        last_mode = None
                        last_frame = None
                    except Exception as e:
                        log.error(f"屏幕渲染异常: {e}")

                # ── SPI 健康检查 ──
                if now - last_spi_check >= spi_check_interval and now > spi_recover_until:
                    last_spi_check = now
                    if not self._check_spi_health(fb_path):
                        if self._recover_spi():
                            spi_recover_until = time.monotonic() + spi_cooldown
                            last_display_time = 0

                time.sleep(1)

            except Exception as e:
                consecutive_errors += 1
                import traceback
                log.error(f"屏幕线程异常 (第{consecutive_errors}次): {e}\n{traceback.format_exc()}")
                if consecutive_errors >= 20:
                    log.error("🚨 屏幕线程异常过多，退出")
                    return
                time.sleep(min(5 * consecutive_errors, 30))

    # ── 事件系统 ──

    def _get_pending_events(self):
        import json
        workspace = Path(__file__).resolve().parents[4]
        events_file = workspace / "memory" / "prism_events.json"
        if not events_file.exists():
            return []
        try:
            events = json.loads(events_file.read_text(encoding="utf-8"))
            return [e for e in events if not e.get("processed")]
        except Exception:
            return []

    def _mark_event_processed(self, event):
        import json
        workspace = Path(__file__).resolve().parents[4]
        events_file = workspace / "memory" / "prism_events.json"
        try:
            events = json.loads(events_file.read_text(encoding="utf-8"))
            for e in events:
                if e.get("id") == event.get("id"):
                    e["processed"] = True
            events_file.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _do_flash(self, display, event, fb_path):
        """事件闪屏"""
        colors = {"alert": (255, 60, 60), "info": (60, 120, 255), "done": (60, 200, 100)}
        color = colors.get(event.get("type", ""), (60, 120, 255))
        text = event.get("text", "")
        try:
            img = display.render_event_frame(text, color) if hasattr(display, 'render_event_frame') else None
            if img:
                display.write_to_framebuffer(img, fb_path)
                time.sleep(3)
        except Exception as e:
            log.warning(f"事件闪屏渲染失败: {e}")

    # ── SPI 健康 ──

    def _check_spi_health(self, fb_path):
        try:
            if not os.path.exists(fb_path):
                return False
            with open(fb_path, 'r+b') as fb:
                fb.read(1)
            return True
        except Exception:
            return False

    def _recover_spi(self):
        import subprocess
        try:
            log.warning("🔧 SPI 异常，尝试重载驱动")
            subprocess.run(["sudo", "modprobe", "-r", "fbtft_device"], capture_output=True, timeout=10)
            time.sleep(1)
            subprocess.run(["sudo", "modprobe", "fbtft_device"], capture_output=True, timeout=10)
            time.sleep(2)
            log.info("✅ SPI 驱动已重载")
            return True
        except Exception as e:
            log.error(f"SPI 恢复失败: {e}")
            return False
