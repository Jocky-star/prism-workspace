"""
示例执行器插件 — 展示如何写一个自定义 Device

使用方法：
1. 复制这个文件，改名为你的设备名（例如 yeelight.py）
2. 实现 on_present 和 on_absent
3. 在 prism_config.yaml 的 devices 里注册：
     devices:
       - plugin: yeelight
         enabled: true
         config:
           ip: "192.168.1.100"
           night_mode_hour: 22

Device 约定：
- 文件名 = plugin 字段的值（不含 .py）
- 包含名为 Plugin 的类，继承 DevicePlugin
- on_present / on_absent 失败时只 log warning，不 raise
- config 字段的内容由你自己决定，会原样传入 __init__
"""

import logging
from typing import Any, Dict

from .. import DevicePlugin

log = logging.getLogger("prism.device.example")


class Plugin(DevicePlugin):
    """
    示例执行器插件（Yeelight 骨架）

    你可以控制任何设备：
    - 智能灯（Yeelight、Hue、LIFX）
    - 智能插座
    - Home Assistant 实体
    - MQTT 消息
    - 任意 HTTP Webhook
    - 自定义脚本
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # 从 config 读取你的设备参数
        self.device_ip = config.get("ip", "192.168.1.100")
        self.night_mode_hour = config.get("night_mode_hour", 22)
        log.info(f"[示例设备] 初始化: ip={self.device_ip}")

    def on_present(self, hour: int):
        """有人来了！根据时段控制设备。hour 是 0-23 的整数。"""
        log.info(f"[示例设备] 有人来了！现在是 {hour} 点")

        if hour >= self.night_mode_hour or hour < 6:
            brightness = 30   # 夜间模式：低亮度
        elif 6 <= hour < 8:
            brightness = 60   # 早晨：中等亮度
        else:
            brightness = 100  # 白天：全亮

        # 你的设备控制代码...
        # 例如：requests.get(f"http://{self.device_ip}/on?brightness={brightness}")
        log.info(f"[示例设备] 开灯，亮度: {brightness}%")

    def on_absent(self):
        """人走了，关闭或待机设备"""
        log.info("[示例设备] 人走了，关闭设备")
        # 你的设备关闭代码...
        # 例如：requests.get(f"http://{self.device_ip}/off")

    def on_init(self):
        """可选：daemon 启动时初始化连接"""
        log.info(f"[示例设备] 初始化完成，设备 IP: {self.device_ip}")
        # 例如：测试连接、检查设备在线状态

    def on_shutdown(self):
        """可选：daemon 关闭时清理资源"""
        log.info("[示例设备] 已关闭")
