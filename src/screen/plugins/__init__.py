"""
Prism 插件接口 — 三层管线

感知 (Sensor): 采集原始数据（图像、雷达信号等）
检测 (Detector): 从原始数据判断有没有人
执行 (Device): 根据判定结果控制设备

写新插件：
1. 在对应目录下创建 .py 文件
2. 实现 Plugin 类（继承对应基类）
3. 在 prism_config.yaml 中注册

目录：
  sensors/   — 感知源插件（rpicam, usb_camera, mmwave, ...）
  detectors/ — 检测器插件（vision_api, frame_diff, local_yolo, ...）
  devices/   — 执行器插件（mijia_lamp, yeelight, homeassistant, ...）
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

try:
    from PIL import Image
except ImportError:
    Image = None  # 允许在没有 Pillow 的环境里 import 基类


class SensorPlugin(ABC):
    """
    感知源插件基类 — 采集原始数据

    实现要点：
    - capture() 失败时返回 None（不要 raise），让调度器跳过
    - 如果硬件需要初始化，在 setup() 里做
    - setup() 由 plugin_loader 在加载时调用
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}

    @abstractmethod
    def capture(self) -> "Optional[Image.Image]":
        """
        采集一帧，返回 PIL Image。
        失败（硬件不可用、拍照超时等）返回 None。
        """
        pass

    def setup(self):
        """初始化（可选）：打开设备、分配资源等"""
        pass

    def cleanup(self):
        """清理（可选）：关闭设备、释放资源等"""
        pass


class DetectorPlugin(ABC):
    """
    检测器插件基类 — 判断是否有人

    检测器组成链式管线，从前往后依次执行。
    某个检测器可以通过返回 skip=True 中断后续检测器（短路优化）。

    实现要点：
    - detect() 失败时返回 {"detected": False}（不要 raise）
    - 可通过 context 获取前序检测器的结果
    - 设 skip=True 跳过后续检测器（例如帧差极低时跳过 Vision API）
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}

    @abstractmethod
    def detect(self, image: "Image.Image", context: Dict[str, Any]) -> Dict[str, Any]:
        """
        检测是否有人。

        参数：
            image:   传感器采集的图像（PIL Image）
            context: 上下文信息，供检测器读写共享状态
                - prev_present: bool — 上一次的判定结果
                - motion_ratio: float — 帧差比例（由 frame_diff 写入）
                - [任意其他检测器写入的字段]

        返回 dict（只有 detected 是必须的）：
            - detected:    bool  — 是否检测到人（必须）
            - confidence:  float — 置信度 0-1（可选）
            - skip:        bool  — True 则跳过后续所有检测器（可选）
            - reason:      str   — 跳过/检测的原因，用于日志（可选）
        """
        pass


class DevicePlugin(ABC):
    """
    执行器插件基类 — 根据检测结果控制设备

    实现要点：
    - on_present / on_absent 失败时只 log warning，不 raise
    - on_init 由 plugin_loader 在加载时调用
    - on_shutdown 由 daemon 关闭时调用
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}

    @abstractmethod
    def on_present(self, hour: int):
        """有人时触发。hour 是当前小时 (0-23)。"""
        pass

    @abstractmethod
    def on_absent(self):
        """无人时触发（人离开后）"""
        pass

    def on_init(self):
        """启动时调用（可选）：建立连接、检查设备状态等"""
        pass

    def on_shutdown(self):
        """关闭时调用（可选）：优雅断开连接等"""
        pass


# ── 向后兼容：保留旧的 PrismDevicePlugin 别名 ───────────────────────────────
# 旧版 plugin_loader 用这个基类，新版用 DevicePlugin
# 两者功能等价，都能用
PrismDevicePlugin = DevicePlugin
