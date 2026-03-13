"""
plugin_loader.py — Prism 三层插件加载器

从 prism_config.yaml 动态加载三类插件：
  sensors   → SensorPlugin   — 采集图像/信号
  detectors → DetectorPlugin — 判断是否有人
  devices   → DevicePlugin   — 控制设备

核心函数：
  load_sensors(config)   → List[SensorPlugin]
  load_detectors(config) → List[DetectorPlugin]
  load_devices(config)   → List[DevicePlugin]

  capture_image(sensors)            → Optional[Image]
  run_detection(detectors, img, ctx) → bool
  trigger_present(devices, hour)
  trigger_absent(devices)

加载失败只 warning，不崩溃。
"""

import importlib
import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .plugins import SensorPlugin, DetectorPlugin, DevicePlugin

log = logging.getLogger("prism.plugin_loader")

# 插件目录
_PLUGINS_DIR = Path(__file__).resolve().parent / "plugins"


# ── 通用插件加载函数 ──────────────────────────────────────────────────────────

def _load_plugin_module(plugin_name: str, subdir: str):
    """
    动态加载插件模块。
    先尝试包路径 src.screen.plugins.{subdir}.{name}，
    再 fallback 到文件路径加载。
    失败返回 None。
    """
    # 尝试包路径
    try:
        mod = importlib.import_module(
            f".plugins.{subdir}.{plugin_name}",
            package="src.screen"
        )
        return mod
    except (ImportError, ModuleNotFoundError):
        pass

    # fallback：从文件路径加载
    plugin_file = _PLUGINS_DIR / subdir / f"{plugin_name}.py"
    if not plugin_file.exists():
        log.warning(f"插件文件不存在: {plugin_file}")
        return None

    try:
        spec = importlib.util.spec_from_file_location(
            f"prism_plugin_{subdir}_{plugin_name}", plugin_file
        )
        mod = importlib.util.module_from_spec(spec)
        # 确保插件能 import 到基类
        parent_dir = str(_PLUGINS_DIR.parent)
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        log.warning(f"插件 {subdir}/{plugin_name} 加载失败: {e}")
        return None


def _load_plugins_of_type(plugin_list: List[Dict], subdir: str, base_class):
    """
    从配置列表加载指定类型的插件。
    返回成功加载的插件实例列表。
    """
    loaded = []
    for item in (plugin_list or []):
        plugin_name = item.get("plugin", "").strip()
        enabled = item.get("enabled", True)
        plugin_config = item.get("config") or {}

        if not plugin_name:
            log.warning(f"{subdir} 里有空的 plugin 名称，跳过")
            continue

        if not enabled:
            log.info(f"插件 {subdir}/{plugin_name} 已禁用，跳过")
            continue

        mod = _load_plugin_module(plugin_name, subdir)
        if mod is None:
            continue

        if not hasattr(mod, "Plugin"):
            log.warning(f"插件 {subdir}/{plugin_name} 没有 Plugin 类，跳过")
            continue

        plugin_cls = mod.Plugin
        if not issubclass(plugin_cls, base_class):
            log.warning(
                f"插件 {subdir}/{plugin_name}.Plugin 没有继承 {base_class.__name__}，跳过"
            )
            continue

        try:
            instance = plugin_cls(plugin_config)
            # 调用 setup/on_init
            if hasattr(instance, "setup"):
                try:
                    instance.setup()
                except Exception as e:
                    log.warning(f"插件 {plugin_name}.setup() 异常（继续加载）: {e}")
            elif hasattr(instance, "on_init"):
                try:
                    instance.on_init()
                except Exception as e:
                    log.warning(f"插件 {plugin_name}.on_init() 异常（继续加载）: {e}")

            loaded.append(instance)
            log.info(f"✅ 插件已加载: {subdir}/{plugin_name}")

        except Exception as e:
            log.warning(f"插件 {subdir}/{plugin_name} 实例化失败（跳过）: {e}")

    return loaded


# ── 三种插件加载函数 ──────────────────────────────────────────────────────────

def load_sensors(config) -> List[SensorPlugin]:
    """从配置加载感知源插件列表"""
    sensor_list = getattr(config, "sensors", None)
    if sensor_list is None:
        # 旧格式兼容：没有 sensors 字段，使用默认 rpicam
        log.info("配置中无 sensors 字段，使用默认 rpicam")
        sensor_list = [{"plugin": "rpicam", "enabled": True, "config": {}}]

    result = _load_plugins_of_type(sensor_list, "sensors", SensorPlugin)
    log.info(f"感知源插件加载完成，共 {len(result)} 个")
    return result


def load_detectors(config) -> List[DetectorPlugin]:
    """从配置加载检测器插件列表"""
    detector_list = getattr(config, "detectors", None)
    if detector_list is None:
        # 旧格式兼容：使用默认 frame_diff + vision_api
        log.info("配置中无 detectors 字段，使用默认 frame_diff + vision_api")
        detector_list = [
            {"plugin": "frame_diff",  "enabled": True, "config": {}},
            {"plugin": "vision_api",  "enabled": True, "config": {}},
        ]

    result = _load_plugins_of_type(detector_list, "detectors", DetectorPlugin)
    log.info(f"检测器插件加载完成，共 {len(result)} 个")
    return result


def load_devices(config) -> List[DevicePlugin]:
    """从配置加载执行器插件列表（支持新旧两种格式）"""
    # 优先读新格式 devices（三层管线）
    device_list = getattr(config, "devices", None)
    if device_list is None:
        log.info("配置中无 devices 字段，使用默认 mijia_lamp")
        device_list = [{"plugin": "mijia_lamp", "enabled": True, "config": {}}]

    # 尝试从旧的 plugins/ 根目录加载（向后兼容）
    # 旧插件继承 PrismDevicePlugin（= DevicePlugin 的别名），可以直接用
    result = _load_plugins_of_type(device_list, "devices", DevicePlugin)

    # 如果 devices/ 里没有，尝试旧的 plugins 根目录
    if not result:
        log.info("devices/ 目录未加载到插件，尝试旧版 plugins 根目录")
        result = _load_plugins_of_type(device_list, "", DevicePlugin)

    log.info(f"执行器插件加载完成，共 {len(result)} 个")
    return result


# ── 管线执行函数 ─────────────────────────────────────────────────────────────

def capture_image(sensors: List[SensorPlugin]) -> Optional["Image.Image"]:
    """
    按顺序尝试每个 sensor，第一个成功的返回。
    全部失败返回 None。
    """
    for sensor in sensors:
        try:
            img = sensor.capture()
            if img is not None:
                return img
        except Exception as e:
            log.warning(f"Sensor {sensor.__class__.__name__}.capture() 异常: {e}")
    log.warning("所有 sensor 均失败，返回 None")
    return None


def run_detection(
    detectors: List[DetectorPlugin],
    image: "Image.Image",
    context: Dict[str, Any],
) -> bool:
    """
    链式执行检测器管线。

    规则：
    - 从前到后依次执行每个检测器
    - 任一检测器返回 skip=True → 中断，使用该检测器的 detected 结果
    - 全部执行完 → 最后一个检测器的 detected 作为最终结果
    - 任一检测器设 detected=True → 认为有人（OR 策略）
      （注：最终结果取最后非 skip 的检测器，或触发 skip 的检测器）

    返回：bool — 是否有人
    """
    detected = False

    for detector in detectors:
        try:
            result = detector.detect(image, context)
            detected = result.get("detected", False)
            skip = result.get("skip", False)
            reason = result.get("reason", "")

            if skip:
                log.info(
                    f"检测器 {detector.__class__.__name__} skip=True "
                    f"(detected={detected}, reason={reason!r}) → 中断管线"
                )
                return detected

        except Exception as e:
            log.warning(f"检测器 {detector.__class__.__name__}.detect() 异常: {e}")
            # 异常时保持 detected 不变（沿用上一个结果）

    return detected


def trigger_present(devices: List[DevicePlugin], hour: int):
    """检测到有人 → 触发所有执行器插件的 on_present"""
    for device in devices:
        try:
            device.on_present(hour)
        except Exception as e:
            log.warning(f"设备 {device.__class__.__name__}.on_present 异常: {e}")


def trigger_absent(devices: List[DevicePlugin]):
    """确认无人 → 触发所有执行器插件的 on_absent"""
    for device in devices:
        try:
            device.on_absent()
        except Exception as e:
            log.warning(f"设备 {device.__class__.__name__}.on_absent 异常: {e}")


def shutdown_plugins(devices: List[DevicePlugin]):
    """daemon 关闭时通知所有执行器插件"""
    for device in devices:
        try:
            device.on_shutdown()
        except Exception as e:
            log.warning(f"设备 {device.__class__.__name__}.on_shutdown 异常: {e}")


# ── 向后兼容：旧版 plugin_loader API ─────────────────────────────────────────
# daemon.py 旧版直接调用 trigger_present(hour) 和 trigger_absent()
# 保留这两个模块级函数以避免破坏旧代码

_compat_devices: Optional[List[DevicePlugin]] = None
_compat_initialized = False


def _compat_load():
    """旧版兼容：懒加载 devices（从配置读取）"""
    global _compat_devices, _compat_initialized
    if _compat_initialized:
        return
    try:
        from .config_loader import get_config
        cfg = get_config()
        _compat_devices = load_devices(cfg)
    except Exception as e:
        log.warning(f"旧版兼容加载失败: {e}")
        _compat_devices = []
    _compat_initialized = True
