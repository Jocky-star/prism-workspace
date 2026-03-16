"""
mijia-lamp 执行器插件 — 薄包装 src/screen/plugins/devices/mijia_lamp.py
"""
import sys
from pathlib import Path
from typing import Any, Dict, List

_WORKSPACE = Path(__file__).resolve().parents[3]
if str(_WORKSPACE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE))

from prism.plugin_base import ActuatorPlugin


class MijiaLampPlugin(ActuatorPlugin):
    name = "mijia-lamp"
    version = "1.0.0"

    def setup(self, config: dict) -> bool:
        username = config.get("username", "")
        password = config.get("password", "")
        if not username or not password:
            print("  ⚠️  mijia-lamp: 需要配置 username 和 password（小米账号）")
            return False
        return True

    def execute(self, action: str, params: dict) -> bool:
        """执行台灯动作"""
        try:
            integrations_path = _WORKSPACE / "src" / "actions" / "integrations"
            if str(integrations_path) not in sys.path:
                sys.path.insert(0, str(integrations_path))

            from mijia_lamp import set_scene, determine_scene
            scene = params.get("scene", action)
            if action == "auto":
                import datetime
                tz = datetime.timezone(datetime.timedelta(hours=8))
                hour = datetime.datetime.now(tz).hour
                present = params.get("present", True)
                scene = determine_scene(present, hour)
            success = set_scene(scene)
            return success
        except ImportError:
            print("  ⚠️  mijia_lamp 模块未找到（需要配置米家账号）")
            return False
        except Exception as e:
            print(f"  ❌ mijia-lamp execute error: {e}")
            return False

    def get_capabilities(self) -> List[str]:
        return ["off", "focus", "relax", "night", "normal", "auto"]

    def health_check(self) -> dict:
        username = self.config.get("username", "")
        password = self.config.get("password", "")
        if not username or not password:
            return {"status": "error", "message": "Missing username or password"}
        try:
            integrations_path = _WORKSPACE / "src" / "actions" / "integrations"
            if str(integrations_path) not in sys.path:
                sys.path.insert(0, str(integrations_path))
            import mijia_lamp  # noqa: F401
            return {"status": "ok", "message": "mijia_lamp module available"}
        except ImportError:
            return {"status": "error", "message": "mijia_lamp module not found"}
