"""
内置检测器插件：frame_diff — 帧差运动检测

通过对比当前帧与历史帧的像素差异来判断是否有运动。

特点：
- 速度极快（纯 CPU，毫秒级）
- 无 API 调用，零成本
- 适合作为 Vision API 的前置过滤器：
  帧差极低时直接判定"无运动"，跳过昂贵的 Vision API

prism_config.yaml 配置示例：
    detectors:
      - plugin: frame_diff
        enabled: true
        config:
          threshold: 0.005         # 帧差高于此值 → 认为有运动
          skip_vision_below: 0.005 # 帧差低于此值 → skip=True，跳过后续检测器
          prev_thumb_path: ""      # 历史帧保存路径（默认自动）

管线使用建议：
  detectors:
    - plugin: frame_diff   # 先跑帧差（快）
    - plugin: vision_api   # 再跑 Vision（慢但准）
  
  帧差极低时 frame_diff 会设 skip=True，vision_api 不会被调用。
  帧差有变化时两者都跑，Vision API 做最终判定。
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from .. import DetectorPlugin

log = logging.getLogger("prism.detector.frame_diff")

# 缩略图尺寸（用于帧差计算，不需要全分辨率）
_THUMB_W, _THUMB_H = 160, 120
# 像素变化阈值（abs 差值超过此值才算"变化像素"）
_PIXEL_DIFF_THRESHOLD = 20


class Plugin(DetectorPlugin):
    """帧差运动检测器插件"""

    _DEFAULTS = {
        "threshold": 0.005,          # 高于此比例视为有运动
        "skip_vision_below": 0.005,  # 低于此比例时 skip=True 跳过后续检测器
        "prev_thumb_path": "",       # 历史帧路径（空=自动）
    }

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        for k, v in self._DEFAULTS.items():
            if k not in self.config:
                self.config[k] = v

        # 确定历史帧路径
        if self.config["prev_thumb_path"]:
            self._prev_thumb = Path(self.config["prev_thumb_path"])
        else:
            # 默认：workspace/memory/.prism_prev_thumb.jpg
            self._prev_thumb = self._default_thumb_path()

    def _default_thumb_path(self) -> Path:
        """推断默认历史帧保存路径"""
        # plugins/detectors/frame_diff.py → plugins → screen → src → workspace
        here = Path(__file__).resolve()
        workspace = here.parents[4]
        memory_dir = workspace / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        return memory_dir / ".prism_prev_thumb.jpg"

    def detect(self, image: "Image.Image", context: Dict[str, Any]) -> Dict[str, Any]:
        """
        计算帧差比例，写入 context["motion_ratio"]。

        返回：
            detected = True  if motion_ratio >= threshold
            skip = True      if motion_ratio < skip_vision_below
        """
        try:
            motion_ratio = self._compute_diff(image)
        except Exception as e:
            log.warning(f"帧差计算失败: {e}")
            motion_ratio = 0.0

        # 写入 context 让后续检测器读取
        context["motion_ratio"] = motion_ratio

        threshold = float(self.config.get("threshold", 0.005))
        skip_below = float(self.config.get("skip_vision_below", 0.005))

        detected = motion_ratio >= threshold
        skip = motion_ratio < skip_below

        if skip:
            log.info(f"📷 帧差极低 {motion_ratio:.2%} (< {skip_below:.2%}) → skip=True，跳过后续检测器")
        else:
            log.info(f"📷 帧差 {motion_ratio:.2%}，detected={detected}")

        return {
            "detected": detected,
            "confidence": min(motion_ratio / threshold, 1.0) if threshold > 0 else 0.0,
            "skip": skip,
            "reason": f"motion_ratio={motion_ratio:.3%}",
        }

    def _compute_diff(self, img_new: "Image.Image") -> float:
        """对比新帧与历史帧缩略图，返回差异比例 0.0~1.0"""
        from PIL import Image

        thumb_new = img_new.convert("L").resize((_THUMB_W, _THUMB_H))

        if not self._prev_thumb.exists():
            # 没有历史帧：保存当前帧，返回「有运动」（保守策略）
            thumb_new.save(str(self._prev_thumb))
            log.debug("首次帧差：无历史帧，返回 1.0（保守）")
            return 1.0

        thumb_old = Image.open(str(self._prev_thumb)).convert("L").resize((_THUMB_W, _THUMB_H))

        pixels_new = thumb_new.tobytes()
        pixels_old = thumb_old.tobytes()

        total = len(pixels_new)
        diffs = sum(1 for n, o in zip(pixels_new, pixels_old)
                    if abs(n - o) > _PIXEL_DIFF_THRESHOLD)
        ratio = diffs / total

        # 保存新帧作为下次对比的基准
        # 无论有无运动都更新，避免背景漂移导致误判
        thumb_new.save(str(self._prev_thumb))

        return ratio
