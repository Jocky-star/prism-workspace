"""
Prism 设备插件接口。

写一个新插件只需要：
1. 在 src/screen/plugins/ 下创建 .py 文件
2. 实现 PrismDevicePlugin 子类，命名为 Plugin
3. 在 prism_config.yaml 的 devices 里注册

示例见 mijia_lamp.py 和 example_plugin.py
"""

from abc import ABC, abstractmethod
from typing import Any, Dict


class PrismDevicePlugin(ABC):
    """设备联动插件基类"""

    def __init__(self, config: Dict[str, Any]):
        """初始化，config 来自 prism_config.yaml 中该 plugin 的 config 字段"""
        self.config = config or {}

    @abstractmethod
    def on_present(self, hour: int):
        """检测到有人时调用。hour 是当前小时(0-23)"""
        pass

    @abstractmethod
    def on_absent(self):
        """确认无人时调用"""
        pass

    def on_init(self):
        """daemon 启动时调用（可选）"""
        pass

    def on_shutdown(self):
        """daemon 关闭时调用（可选）"""
        pass
