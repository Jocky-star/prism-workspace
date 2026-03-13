"""
示例插件 — 展示如何写一个设备联动插件

使用方法：
1. 复制这个文件，改名为你的设备名（例如 yeelight.py）
2. 实现 on_present 和 on_absent
3. 在 prism_config.yaml 的 devices 里注册：
     - plugin: yeelight
       enabled: true
       config:
         ip: "192.168.1.100"

插件必须：
- 文件名就是 plugin 字段的值（不含 .py）
- 包含名为 Plugin 的类，继承 PrismDevicePlugin
- 实现 on_present(hour) 和 on_absent()

config 字段的内容由你自己决定，会原样传入 __init__。
"""

import logging
from typing import Any, Dict

from . import PrismDevicePlugin

log = logging.getLogger("prism.plugin.example")


class Plugin(PrismDevicePlugin):
    """示例设备插件"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # 从 config 读取你的设备参数
        self.device_ip = config.get("ip", "192.168.1.100")
        self.brightness = config.get("default_brightness", 80)
        log.info(f"示例插件初始化: ip={self.device_ip}, brightness={self.brightness}")

    def on_present(self, hour: int):
        """有人来了！根据时段控制设备。hour 是 0-23 的整数。"""
        log.info(f"[示例插件] 有人来了！现在是 {hour} 点")
        # 你的设备控制代码...
        # 例如：requests.get(f"http://{self.device_ip}/on?brightness={self.brightness}")

    def on_absent(self):
        """人走了，关闭或待机设备"""
        log.info("[示例插件] 人走了，关闭设备")
        # 你的设备关闭代码...
        # 例如：requests.get(f"http://{self.device_ip}/off")

    def on_init(self):
        """可选：daemon 启动时初始化连接等"""
        log.info(f"[示例插件] 初始化完成，设备 IP: {self.device_ip}")

    def on_shutdown(self):
        """可选：daemon 关闭时清理资源"""
        log.info("[示例插件] 已关闭")
