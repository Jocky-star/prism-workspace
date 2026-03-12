"""
prism_transition.py — 屏幕模式切换渐变过渡

提供 fade_transition(old_img, new_img, fb_path, steps=8, duration=0.5) 函数：
- old_img, new_img: PIL Image (480x320)
- 在 duration 秒内，从 old_img 渐变到 new_img
- 每一步 blend 两帧，写入 framebuffer
- steps=8 表示 8 帧过渡（每帧约 62ms）

也提供 fade_from_black(new_img) 和 fade_to_black(old_img) 快捷方法。

颜色映射（与 prism_display.py 一致）：
  RGB888 → RGB565 big-endian: ((b>>3)<<11) | ((r>>2)<<5) | (g>>3)
"""

import os
import sys
import time

from PIL import Image

# ── 确保 prism_display 可导入 ─────────────────────────────────────────────────
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)


def fade_transition(old_img: Image.Image, new_img: Image.Image,
                    fb_path: str = "/dev/fb0",
                    steps: int = 8, duration: float = 0.5):
    """
    渐变过渡：从 old_img 平滑变换到 new_img。

    Args:
        old_img:  起始帧（PIL Image，480×320 RGB）
        new_img:  目标帧（PIL Image，480×320 RGB）
        fb_path:  framebuffer 设备路径
        steps:    过渡帧数（默认 8 帧）
        duration: 总过渡时长（秒，默认 0.5s）
    """
    from display import write_to_framebuffer

    # 保证两帧尺寸一致（保险措施）
    if old_img.size != new_img.size:
        new_img = new_img.resize(old_img.size, Image.LANCZOS)

    # 保证 RGB 模式（blend 要求）
    if old_img.mode != "RGB":
        old_img = old_img.convert("RGB")
    if new_img.mode != "RGB":
        new_img = new_img.convert("RGB")

    interval = duration / max(steps, 1)
    for i in range(1, steps + 1):
        alpha = i / steps
        blended = Image.blend(old_img, new_img, alpha)
        write_to_framebuffer(blended, fb_path)
        time.sleep(interval)


def fade_to_black(old_img: Image.Image,
                  fb_path: str = "/dev/fb0",
                  steps: int = 6, duration: float = 0.3):
    """渐隐到黑（与 prism_display 暗屏底色保持一致：(8, 8, 12)）"""
    black = Image.new("RGB", old_img.size, (8, 8, 12))
    fade_transition(old_img, black, fb_path, steps, duration)


def fade_from_black(new_img: Image.Image,
                    fb_path: str = "/dev/fb0",
                    steps: int = 6, duration: float = 0.3):
    """从黑渐入"""
    black = Image.new("RGB", new_img.size, (8, 8, 12))
    fade_transition(black, new_img, fb_path, steps, duration)
