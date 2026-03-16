"""
spi-screen 执行器插件 — 薄包装 src/screen/plugins/devices/spi_screen.py
"""
import sys
from pathlib import Path
from typing import Any, Dict, List

_WORKSPACE = Path(__file__).resolve().parents[3]
if str(_WORKSPACE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE))

from prism.plugin_base import ActuatorPlugin


class SpiScreenPlugin(ActuatorPlugin):
    name = "spi-screen"
    version = "1.0.0"

    _DEFAULTS = {
        "fb_path": "/dev/fb0",
        "display_interval": 10,
        "spi_health_check": 120,
        "spi_recover_cooldown": 300,
    }

    def setup(self, config: dict) -> bool:
        import os
        fb_path = config.get("fb_path", self._DEFAULTS["fb_path"])
        if not os.path.exists(fb_path):
            print(f"  ⚠️  spi-screen: framebuffer {fb_path} 不存在（仅 Raspberry Pi SPI 屏幕支持）")
            return False
        return True

    def execute(self, action: str, params: dict) -> bool:
        """执行屏幕动作"""
        try:
            # 委托给 screen 模块的 update.py
            if action == "update_task":
                import subprocess
                task = params.get("task", "")
                note = params.get("note", "")
                cmd = ["python3", str(_WORKSPACE / "src" / "screen" / "update.py"), "--task", task]
                if note:
                    cmd += ["--note", note]
                result = subprocess.run(cmd, capture_output=True, timeout=10)
                return result.returncode == 0
            elif action in ("render_normal", "render_dim", "render_summary", "flash_event"):
                return self._delegate_to_device(action, params)
        except Exception as e:
            print(f"  ❌ spi-screen execute error: {e}")
            return False
        return True

    def _delegate_to_device(self, action: str, params: dict) -> bool:
        """委托给原有 spi_screen.py 设备插件"""
        try:
            import importlib.util
            device_path = (_WORKSPACE / "src" / "screen" / "plugins" / "devices" / "spi_screen.py")
            spec = importlib.util.spec_from_file_location("spi_screen_device", device_path)
            mod = importlib.util.module_from_spec(spec)
            # 注入 DevicePlugin 基类
            sys.path.insert(0, str(_WORKSPACE / "src" / "screen" / "plugins"))
            spec.loader.exec_module(mod)
            plugin = mod.Plugin(config=self.config)
            return True
        except Exception as e:
            print(f"  ⚠️  spi_screen delegate failed: {e}")
            return False

    def get_capabilities(self) -> List[str]:
        return ["render_normal", "render_dim", "render_summary", "flash_event", "update_task"]

    def health_check(self) -> dict:
        import os
        fb_path = self.config.get("fb_path", self._DEFAULTS["fb_path"])
        if not os.path.exists(fb_path):
            return {"status": "error", "message": f"framebuffer not found: {fb_path}"}
        return {"status": "ok", "message": f"framebuffer accessible: {fb_path}"}
