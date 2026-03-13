"""
内置执行器插件：mijia_lamp — 米家台灯联动

根据存在状态控制米家台灯的亮度和色温。
实际设备控制代码在 src/actions/integrations/mijia_lamp.py，
本插件只负责调用它（不直接控制设备）。

prism_config.yaml 配置示例：
    devices:
      - plugin: mijia_lamp
        enabled: true
        config: {}     # 所有参数从 device_preferences.json 自动读取

时段偏好（亮度/色温）在 device_preferences.json 里配置，
本插件不需要额外 config 参数。
"""

import logging
import sys
from pathlib import Path
from typing import Any, Dict

from .. import DevicePlugin

log = logging.getLogger("prism.device.mijia_lamp")


def _ensure_integrations_path():
    """确保 src/actions/integrations 在 sys.path 中（支持不同工作目录启动）"""
    here = Path(__file__).resolve()
    # plugins/devices/mijia_lamp.py → plugins → screen → src → workspace
    workspace = here.parents[4]
    integrations = workspace / "src" / "actions" / "integrations"
    if str(integrations) not in sys.path:
        sys.path.insert(0, str(integrations))


class Plugin(DevicePlugin):
    """米家台灯执行器插件"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        _ensure_integrations_path()

    def on_present(self, hour: int):
        """有人来了 → 根据时段开灯/调光"""
        try:
            from mijia_lamp import set_scene, determine_scene
            scene = determine_scene(True, hour)
            log.info(f"存在状态 → 有人, 时段={hour}:00, 场景={scene}")
            success = set_scene(scene)
            if success:
                log.info(f"✅ 台灯已切换: {scene}")
            else:
                log.warning(f"台灯切换失败: {scene}")
        except ImportError:
            log.warning("mijia_lamp 模块未找到，跳过台灯控制")
        except Exception as e:
            log.warning(f"米家台灯 on_present 异常: {e}")

    def on_absent(self):
        """人走了 → 关灯"""
        try:
            from mijia_lamp import set_scene, determine_scene
            import datetime
            _tz = datetime.timezone(datetime.timedelta(hours=8))
            hour = datetime.datetime.now(_tz).hour
            scene = determine_scene(False, hour)
            log.info(f"存在状态 → 无人, 时段={hour}:00, 场景={scene}")
            success = set_scene(scene)
            if success:
                log.info(f"✅ 台灯已切换: {scene}")
            else:
                log.warning(f"台灯切换失败: {scene}")
        except ImportError:
            log.warning("mijia_lamp 模块未找到，跳过台灯控制")
        except Exception as e:
            log.warning(f"米家台灯 on_absent 异常: {e}")

    def on_init(self):
        log.info("✅ 米家台灯插件已初始化")

    def on_shutdown(self):
        log.info("米家台灯插件已关闭")
