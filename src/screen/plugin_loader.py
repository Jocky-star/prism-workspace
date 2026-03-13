"""
plugin_loader.py — Prism 设备插件加载器

从 prism_config.yaml 的 devices 列表动态加载插件，
提供 trigger_present(hour) 和 trigger_absent() 给 daemon 调用。

插件约定：
  - 文件放在 src/screen/plugins/{name}.py
  - 包含名为 Plugin 的类，继承 PrismDevicePlugin
  - 加载失败只 warning，不崩溃
"""

import importlib
import logging
import sys
from pathlib import Path
from typing import List

from .plugins import PrismDevicePlugin

log = logging.getLogger("prism.plugin_loader")

_plugins: List[PrismDevicePlugin] = []
_initialized = False


def _load_plugins():
    """从配置加载所有启用的插件（懒加载，首次调用时执行）"""
    global _plugins, _initialized

    if _initialized:
        return

    from .config_loader import get_config
    cfg = get_config()

    devices = cfg.devices or []
    loaded = []

    # 确保 plugins 目录在 sys.path 里（支持相对 import）
    plugins_dir = Path(__file__).resolve().parent / "plugins"

    for device_cfg in devices:
        plugin_name = device_cfg.get("plugin", "")
        enabled = device_cfg.get("enabled", True)
        plugin_config = device_cfg.get("config") or {}

        if not plugin_name:
            log.warning("devices 里有空的 plugin 名称，跳过")
            continue

        if not enabled:
            log.info(f"插件 {plugin_name} 已禁用，跳过")
            continue

        try:
            # 动态 import src.screen.plugins.{name}
            module_path = f"src.screen.plugins.{plugin_name}"

            # 先尝试相对包路径，再 fallback 到直接 import
            try:
                mod = importlib.import_module(f".plugins.{plugin_name}", package="src.screen")
            except (ImportError, ModuleNotFoundError):
                # fallback：从文件路径直接加载
                plugin_file = plugins_dir / f"{plugin_name}.py"
                if not plugin_file.exists():
                    log.warning(f"插件文件不存在: {plugin_file}")
                    continue
                spec = importlib.util.spec_from_file_location(
                    f"prism_plugin_{plugin_name}", plugin_file
                )
                mod = importlib.util.module_from_spec(spec)
                # 确保插件能 import . 里的基类
                if str(plugins_dir) not in sys.path:
                    sys.path.insert(0, str(plugins_dir.parent))
                spec.loader.exec_module(mod)

            if not hasattr(mod, "Plugin"):
                log.warning(f"插件 {plugin_name} 没有 Plugin 类，跳过")
                continue

            plugin_cls = mod.Plugin
            if not issubclass(plugin_cls, PrismDevicePlugin):
                log.warning(f"插件 {plugin_name}.Plugin 没有继承 PrismDevicePlugin，跳过")
                continue

            instance = plugin_cls(plugin_config)
            try:
                instance.on_init()
            except Exception as e:
                log.warning(f"插件 {plugin_name}.on_init() 异常（继续加载）: {e}")

            loaded.append(instance)
            log.info(f"✅ 插件已加载: {plugin_name}")

        except Exception as e:
            log.warning(f"插件 {plugin_name} 加载失败（跳过）: {e}")

    _plugins = loaded
    _initialized = True
    log.info(f"插件加载完成，共 {len(_plugins)} 个")


def trigger_present(hour: int):
    """检测到有人 → 触发所有插件的 on_present"""
    _load_plugins()
    for plugin in _plugins:
        try:
            plugin.on_present(hour)
        except Exception as e:
            log.warning(f"插件 {plugin.__class__.__name__}.on_present 异常: {e}")


def trigger_absent():
    """确认无人 → 触发所有插件的 on_absent"""
    _load_plugins()
    for plugin in _plugins:
        try:
            plugin.on_absent()
        except Exception as e:
            log.warning(f"插件 {plugin.__class__.__name__}.on_absent 异常: {e}")


def shutdown_plugins():
    """daemon 关闭时调用，通知所有插件"""
    for plugin in _plugins:
        try:
            plugin.on_shutdown()
        except Exception as e:
            log.warning(f"插件 {plugin.__class__.__name__}.on_shutdown 异常: {e}")
