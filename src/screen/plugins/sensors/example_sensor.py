"""
示例感知源插件 — 展示如何写一个自定义 Sensor

使用方法：
1. 复制这个文件，改名为你的传感器名（例如 usb_camera.py）
2. 实现 capture() 方法
3. 在 prism_config.yaml 的 sensors 里注册：
     sensors:
       - plugin: usb_camera
         enabled: true
         config:
           device: /dev/video0
           width: 1280
           height: 720

Sensor 约定：
- 文件名 = plugin 字段的值（不含 .py）
- 包含名为 Plugin 的类，继承 SensorPlugin
- capture() 失败返回 None（不要 raise），daemon 会处理
"""

import logging
from typing import Any, Dict, Optional

from .. import SensorPlugin

log = logging.getLogger("prism.sensor.example")


class Plugin(SensorPlugin):
    """
    示例感知源插件（USB 摄像头骨架）

    你可以：
    - 替换成任何采集图像的方式（OpenCV、picamera2、网络摄像头 RTSP、截图 etc.）
    - 返回任何 PIL Image 对象
    - 非图像传感器（毫米波雷达等）可以在 capture() 里返回特殊 Image 或 None，
      然后在对应的 DetectorPlugin 里处理
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.device = config.get("device", "/dev/video0")
        self.width = config.get("width", 640)
        self.height = config.get("height", 480)
        self._cap = None  # OpenCV VideoCapture（懒加载）

    def setup(self):
        """初始化：打开摄像头设备"""
        log.info(f"[示例传感器] 初始化，设备: {self.device}")
        # 示例：用 OpenCV 打开 USB 摄像头
        # try:
        #     import cv2
        #     self._cap = cv2.VideoCapture(self.device)
        #     if not self._cap.isOpened():
        #         log.warning(f"无法打开设备 {self.device}")
        # except ImportError:
        #     log.warning("OpenCV 未安装 (pip install opencv-python-headless)")

    def capture(self) -> Optional["Image.Image"]:
        """
        采集一帧，返回 PIL Image。
        失败返回 None（daemon 会跳过并尝试下一个 sensor）。
        """
        log.info("[示例传感器] capture() 被调用（这是示例，返回 None）")

        # ── 示例 A：OpenCV 摄像头 ──────────────────────────────────────
        # try:
        #     import cv2
        #     from PIL import Image
        #     if self._cap is None or not self._cap.isOpened():
        #         return None
        #     ret, frame = self._cap.read()
        #     if not ret:
        #         return None
        #     # BGR → RGB → PIL
        #     rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        #     return Image.fromarray(rgb).resize((self.width, self.height))
        # except Exception as e:
        #     log.warning(f"OpenCV 拍照失败: {e}")
        #     return None

        # ── 示例 B：截图（桌面监控场景）─────────────────────────────────
        # try:
        #     from PIL import ImageGrab
        #     return ImageGrab.grab()
        # except Exception as e:
        #     log.warning(f"截图失败: {e}")
        #     return None

        # 示例文件：直接返回 None
        return None

    def cleanup(self):
        """清理：关闭摄像头设备"""
        if self._cap is not None:
            try:
                self._cap.release()
                log.info("[示例传感器] 摄像头已关闭")
            except Exception:
                pass
