"""
config_loader.py — Prism 配置加载器

读取 prism_config.yaml，不存在时用默认值（零配置也能跑）。
提供 get_config() 函数给 daemon 和其他模块使用。

workspace 路径自动检测（同 auto_status.py 的逻辑）：
  环境变量 PRISM_WORKSPACE → 相对路径推断 → OpenClaw 默认路径
"""

import os
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("prism.config")

# ── Workspace 自动检测（与 auto_status.py 保持一致）──────────────────────────

def _find_workspace() -> Path:
    """按优先级查找 workspace 目录"""
    # 1. 环境变量
    env = os.environ.get("PRISM_WORKSPACE")
    if env:
        return Path(env)
    # 2. 相对于本文件 (src/screen/config_loader.py → workspace root)
    here = Path(__file__).resolve().parent
    candidate = here.parent.parent  # src/screen/../../ = workspace
    if (candidate / "memory").exists():
        return candidate
    # 3. OpenClaw 默认 workspace
    default = Path.home() / ".openclaw" / "workspace"
    if default.exists():
        return default
    return candidate  # fallback


WORKSPACE = _find_workspace()
CONFIG_FILE = WORKSPACE / "prism_config.yaml"

# ── 默认配置（与 daemon.py 原始硬编码保持一致）──────────────────────────────

_DEFAULTS = {
    "presence": {
        "scene": "办公桌前",
        "absent_timeout": 300,
        "motion_threshold": 0.005,
        "camera_interval": 30,
    },
    "vision": {
        "model": "",
        "timeout": 15,
    },
    "screen": {
        "display_interval": 10,
        "fb_path": "/dev/fb0",
    },
    "devices": [
        {
            "plugin": "mijia_lamp",
            "enabled": True,
            "config": {},
        }
    ],
}


# ── 配置对象（提供属性访问，方便 daemon 读取）────────────────────────────────

class _Namespace:
    """简单的属性访问命名空间，支持 config.presence.scene 风格"""
    def __init__(self, data: Dict[str, Any]):
        for k, v in data.items():
            if isinstance(v, dict):
                setattr(self, k, _Namespace(v))
            else:
                setattr(self, k, v)

    def __repr__(self):
        attrs = {k: v for k, v in self.__dict__.items()}
        return f"_Namespace({attrs})"

    def get(self, key, default=None):
        return getattr(self, key, default)


class PrismConfig:
    """
    Prism 配置对象。
    
    用法：
        cfg = get_config()
        cfg.presence.scene          # "办公桌前"
        cfg.presence.absent_timeout # 300
        cfg.vision.model            # ""
        cfg.screen.fb_path          # "/dev/fb0"
        cfg.devices                 # list of device dicts
        cfg.workspace               # workspace Path
    """

    def __init__(self, raw: Dict[str, Any]):
        self.presence = _Namespace(raw.get("presence", _DEFAULTS["presence"]))
        self.vision = _Namespace(raw.get("vision", _DEFAULTS["vision"]))
        self.screen = _Namespace(raw.get("screen", _DEFAULTS["screen"]))
        self.devices: List[Dict[str, Any]] = raw.get("devices", _DEFAULTS["devices"])
        self.workspace: Path = WORKSPACE

    def __repr__(self):
        return (
            f"PrismConfig("
            f"scene={self.presence.scene!r}, "
            f"absent_timeout={self.presence.absent_timeout}, "
            f"motion_threshold={self.presence.motion_threshold}, "
            f"fb_path={self.screen.fb_path!r}, "
            f"devices={[d.get('plugin') for d in self.devices]}"
            f")"
        )


# ── 加载逻辑 ─────────────────────────────────────────────────────────────────

def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并，override 覆盖 base，缺少的字段保留 base 默认值"""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


_cached_config: Optional[PrismConfig] = None


def get_config(reload: bool = False) -> PrismConfig:
    """
    获取 Prism 配置。

    - 首次调用时从 prism_config.yaml 加载
    - 文件不存在时静默使用默认值
    - reload=True 强制重新读取文件
    """
    global _cached_config

    if _cached_config is not None and not reload:
        return _cached_config

    raw = dict(_DEFAULTS)  # 从默认值开始

    if CONFIG_FILE.exists():
        try:
            import yaml  # PyYAML，标准库没有，但 Raspberry Pi 通常已装
            with open(CONFIG_FILE, encoding="utf-8") as f:
                user_cfg = yaml.safe_load(f) or {}
            raw = _deep_merge(_DEFAULTS, user_cfg)
            log.info(f"✅ prism_config.yaml 已加载: {CONFIG_FILE}")
        except ImportError:
            log.warning("PyYAML 未安装，使用默认配置（pip install pyyaml 可启用配置文件）")
        except Exception as e:
            log.warning(f"prism_config.yaml 解析失败，使用默认配置: {e}")
    else:
        log.info("prism_config.yaml 不存在，使用默认配置（zero-config 模式）")

    _cached_config = PrismConfig(raw)
    return _cached_config
