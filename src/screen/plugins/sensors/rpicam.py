"""
内置感知源插件：rpicam — 树莓派摄像头

使用 rpicam-still 命令拍照，返回 PIL Image。

prism_config.yaml 配置示例：
    sensors:
      - plugin: rpicam
        enabled: true
        config:
          rotation: 180    # 旋转角度（0/90/180/270）
          width: 640       # 分辨率宽
          height: 480      # 分辨率高
          timeout: 1000    # 快门等待 ms（越小越快，最低 ~500）

复制改写成自定义摄像头插件：
1. 复制本文件到 sensors/your_sensor.py
2. 修改 capture() 里的拍照逻辑
3. 在 prism_config.yaml 里改 plugin 字段
"""

import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from .. import SensorPlugin

log = logging.getLogger("prism.sensor.rpicam")

# 摄像头锁（防止多个进程同时操作摄像头）
def _get_camera_lock():
    """懒加载 camera_lock，允许在没有锁文件时降级"""
    try:
        # src/sources/camera/lock.py
        lock_dir = Path(__file__).resolve().parents[4] / "sources" / "camera"
        if str(lock_dir) not in sys.path:
            sys.path.insert(0, str(lock_dir))
        from lock import camera_lock
        return camera_lock
    except ImportError:
        # 降级：不加锁（单进程场景下安全）
        from contextlib import contextmanager

        @contextmanager
        def _noop_lock(timeout=10):
            yield

        log.warning("camera_lock 不可用，使用无锁模式")
        return _noop_lock


class Plugin(SensorPlugin):
    """树莓派摄像头感知源插件（使用 rpicam-still）"""

    # 默认配置
    _DEFAULTS = {
        "rotation": 180,
        "width": 640,
        "height": 480,
        "timeout": 1000,
    }

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # 合并默认值
        for k, v in self._DEFAULTS.items():
            if k not in self.config:
                self.config[k] = v
        self._camera_lock = None  # 懒加载

    def setup(self):
        """检查 rpicam-still 是否可用"""
        try:
            result = subprocess.run(
                ["rpicam-still", "--version"],
                capture_output=True, timeout=5
            )
            log.info("✅ rpicam-still 可用")
        except FileNotFoundError:
            log.warning("rpicam-still 未找到，摄像头功能可能不可用")
        except Exception as e:
            log.warning(f"rpicam-still 检查失败: {e}")

    def capture(self) -> Optional["Image.Image"]:
        """
        用 rpicam-still 拍一张照片，返回 PIL Image。
        失败（摄像头不可用、超时等）返回 None。
        """
        try:
            from PIL import Image
        except ImportError:
            log.error("Pillow 未安装，无法处理图像 (pip install Pillow)")
            return None

        tmp_path = None
        try:
            # 从 config 读取参数
            rotation = int(self.config.get("rotation", 180))
            width = int(self.config.get("width", 640))
            height = int(self.config.get("height", 480))
            timeout_ms = int(self.config.get("timeout", 1000))

            # 创建临时文件
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            tmp_path = tmp.name
            tmp.close()

            # 调用 rpicam-still
            env = dict(os.environ, LIBCAMERA_LOG_LEVELS="*:ERROR")
            camera_lock = self._get_camera_lock()
            cmd = [
                "rpicam-still",
                "-o", tmp_path,
                "--width", str(width),
                "--height", str(height),
                "--timeout", str(timeout_ms),
                "--nopreview",
                "--rotation", str(rotation),
            ]

            with camera_lock(timeout=10):
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=15,
                    env=env,
                )

            if result.returncode != 0:
                log.warning(f"rpicam-still 失败 (rc={result.returncode}): "
                            f"{result.stderr.decode()[:100]}")
                return None

            # 加载图像
            img = Image.open(tmp_path)
            img.load()  # 确保数据加载后再删文件
            return img

        except subprocess.TimeoutExpired:
            log.warning("rpicam-still 超时")
            return None
        except Exception as e:
            log.warning(f"拍照失败: {e}")
            return None
        finally:
            # 清理临时文件
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    def _get_camera_lock(self):
        """懒加载摄像头锁"""
        if self._camera_lock is None:
            self._camera_lock = _get_camera_lock()
        return self._camera_lock
