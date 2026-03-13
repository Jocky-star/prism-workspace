"""
米家台灯插件 — 把 src/screen/mijia.py 的联动逻辑迁移为插件格式。

实际控制代码在 src/actions/integrations/mijia_lamp.py，本插件只是调用它。
不需要在 config 里填任何参数（从 device_preferences.json 自动读取时段偏好）。
"""

import logging
import sys
from pathlib import Path
from typing import Any, Dict

from . import PrismDevicePlugin

log = logging.getLogger("prism.plugin.mijia_lamp")

# 确保 src/actions/integrations 在 sys.path 中（支持不同工作目录）
def _ensure_integrations_path():
    here = Path(__file__).resolve()
    # plugins/ → screen/ → src/ → workspace/
    workspace = here.parent.parent.parent.parent
    integrations = workspace / "src" / "actions" / "integrations"
    if str(integrations) not in sys.path:
        sys.path.insert(0, str(integrations))


class Plugin(PrismDevicePlugin):
    """米家台灯设备联动插件"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        _ensure_integrations_path()

    def on_present(self, hour: int):
        """有人来了 → 根据时段开灯"""
        try:
            from mijia_lamp import set_scene, determine_scene
            scene = determine_scene(True, hour)
            log.info(f"存在状态 → 有人, 时段={hour}:00, 场景={scene}")
            success = set_scene(scene)
            if success:
                log.info(f"台灯已切换: {scene}")
            else:
                log.warning(f"台灯切换失败: {scene}")
        except Exception as e:
            log.warning(f"米家台灯 on_present 异常: {e}")

    def on_absent(self):
        """人走了 → 关灯"""
        try:
            from mijia_lamp import set_scene, determine_scene
            hour = __import__('datetime').datetime.now(
                __import__('datetime').timezone(
                    __import__('datetime').timedelta(hours=8)
                )
            ).hour
            scene = determine_scene(False, hour)
            log.info(f"存在状态 → 无人, 时段={hour}:00, 场景={scene}")
            success = set_scene(scene)
            if success:
                log.info(f"台灯已切换: {scene}")
            else:
                log.warning(f"台灯切换失败: {scene}")
        except Exception as e:
            log.warning(f"米家台灯 on_absent 异常: {e}")

    def on_init(self):
        log.info("米家台灯插件已初始化")

    def on_shutdown(self):
        log.info("米家台灯插件已关闭")
