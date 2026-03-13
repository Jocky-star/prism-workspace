"""
示例检测器插件 — 展示如何写一个自定义 Detector

使用方法：
1. 复制这个文件，改名为你的检测器名（例如 local_yolo.py）
2. 实现 detect() 方法
3. 在 prism_config.yaml 的 detectors 里注册：
     detectors:
       - plugin: local_yolo
         enabled: true
         config:
           model_path: /home/pi/yolov8n.pt
           confidence: 0.5

Detector 约定：
- 文件名 = plugin 字段的值（不含 .py）
- 包含名为 Plugin 的类，继承 DetectorPlugin
- detect() 必须返回包含 "detected" 键的 dict
- detect() 失败时返回 {"detected": False}（不要 raise）
- 可通过 context 与其他检测器共享数据
- 设 skip=True 可跳过后续所有检测器（短路优化）

管线顺序：
  detectors 列表里的顺序就是执行顺序。
  通常把快速检测器（frame_diff）放前面，慢速检测器（vision_api）放后面。
"""

import logging
from typing import Any, Dict, Optional

from .. import DetectorPlugin

log = logging.getLogger("prism.detector.example")


class Plugin(DetectorPlugin):
    """
    示例检测器插件（本地 YOLO 骨架）

    你可以替换成任何检测逻辑：
    - 本地 ML 模型（YOLOv8, MobileNet etc.）
    - 毫米波雷达数据处理
    - 红外传感器信号解析
    - 自定义规则引擎
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.model_path = config.get("model_path", "")
        self.confidence = float(config.get("confidence", 0.5))
        self._model = None  # 懒加载模型

    def setup(self):
        """可选：预加载模型（避免第一次 detect 时的延迟）"""
        log.info(f"[示例检测器] 初始化，模型: {self.model_path or '（未配置）'}")
        # 示例：加载 YOLOv8 模型
        # if self.model_path:
        #     try:
        #         from ultralytics import YOLO
        #         self._model = YOLO(self.model_path)
        #         log.info(f"YOLOv8 模型已加载: {self.model_path}")
        #     except Exception as e:
        #         log.warning(f"模型加载失败: {e}")

    def detect(self, image: "Image.Image", context: Dict[str, Any]) -> Dict[str, Any]:
        """
        检测图像中是否有人。

        参数：
            image:   PIL Image（来自 sensor）
            context: 共享上下文，前序检测器的结果都在这里
                     - context.get("motion_ratio") — 帧差比例（由 frame_diff 写入）
                     - context.get("prev_present") — 上一次判定结果

        返回：
            必须包含 "detected": bool
            可选包含：
              - "confidence": float (0-1)
              - "skip": bool (True = 跳过后续检测器)
              - "reason": str (日志用)
        """
        log.info("[示例检测器] detect() 被调用（这是示例，返回 False）")

        # ── 示例 A：YOLOv8 本地推理 ───────────────────────────────────────
        # if self._model is not None:
        #     try:
        #         results = self._model(image, conf=self.confidence, classes=[0])  # 0=person
        #         detected = len(results[0].boxes) > 0
        #         return {
        #             "detected": detected,
        #             "confidence": float(results[0].boxes.conf.max()) if detected else 0.0,
        #             "reason": f"yolo_persons={len(results[0].boxes)}",
        #         }
        #     except Exception as e:
        #         log.warning(f"YOLO 推理失败: {e}")
        #         return {"detected": False}

        # ── 示例 B：基于 motion_ratio 的简单规则 ─────────────────────────
        # motion_ratio = context.get("motion_ratio", 0)
        # detected = motion_ratio > 0.02  # 运动超过 2% 就认为有人
        # return {
        #     "detected": detected,
        #     "skip": detected,  # 检测到人就跳过后续检测器
        #     "reason": f"motion_ratio={motion_ratio:.2%}",
        # }

        # 示例文件：返回 False，不影响正常运行
        return {
            "detected": False,
            "confidence": 0.0,
            "reason": "example_detector_placeholder",
        }
