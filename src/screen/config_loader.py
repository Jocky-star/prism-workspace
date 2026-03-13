"""
config_loader.py — Prism 配置加载器

读取 prism_config.yaml，不存在时用默认值（零配置也能跑）。
提供 get_config() 函数给 daemon 和其他模块使用。

支持新的三层管线格式（sensors / detectors / devices）。
同时向后兼容只有 devices 字段的旧格式。

workspace 路径自动检测：
  环境变量 PRISM_WORKSPACE → 相对路径推断 → OpenClaw 默认路径
"""

import os
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("prism.config")

# ── Workspace 自动检测 ────────────────────────────────────────────────────────

def _find_workspace() -> Path:
    """按优先级查找 workspace 目录"""
    env = os.environ.get("PRISM_WORKSPACE")
    if env:
        return Path(env)
    here = Path(__file__).resolve().parent
    candidate = here.parent.parent  # src/screen/../../ = workspace
    if (candidate / "memory").exists():
        return candidate
    default = Path.home() / ".openclaw" / "workspace"
    if default.exists():
        return default
    return candidate


WORKSPACE = _find_workspace()
CONFIG_FILE = WORKSPACE / "prism_config.yaml"

# ── 默认配置 ─────────────────────────────────────────────────────────────────

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
    # 三层管线默认值（新格式）
    "sensors": [
        {
            "plugin": "rpicam",
            "enabled": True,
            "config": {
                "rotation": 180,
                "width": 640,
                "height": 480,
            },
        }
    ],
    "detectors": [
        {
            "plugin": "frame_diff",
            "enabled": True,
            "config": {
                "threshold": 0.005,
                "skip_vision_below": 0.005,
            },
        },
        {
            "plugin": "vision_api",
            "enabled": True,
            "config": {
                "scene": "办公桌前",
                "model": "",
                "timeout": 15,
            },
        },
    ],
    "devices": [
        {
            "plugin": "mijia_lamp",
            "enabled": True,
            "config": {},
        }
    ],
}


# ── 配置对象 ─────────────────────────────────────────────────────────────────

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

    属性访问：
        cfg.presence.scene          # "办公桌前"
        cfg.presence.absent_timeout # 300
        cfg.presence.motion_threshold # 0.005
        cfg.vision.model            # ""
        cfg.screen.fb_path          # "/dev/fb0"
        cfg.sensors                 # list of sensor dicts
        cfg.detectors               # list of detector dicts
        cfg.devices                 # list of device dicts
        cfg.workspace               # workspace Path
    """

    def __init__(self, raw: Dict[str, Any]):
        self.presence = _Namespace({
            **_DEFAULTS["presence"],
            **raw.get("presence", {}),
        })
        self.vision = _Namespace({
            **_DEFAULTS["vision"],
            **raw.get("vision", {}),
        })
        self.screen = _Namespace({
            **_DEFAULTS["screen"],
            **raw.get("screen", {}),
        })

        # ── 三层管线（新格式）──
        self.sensors: List[Dict[str, Any]] = raw.get("sensors", _DEFAULTS["sensors"])
        self.detectors: List[Dict[str, Any]] = raw.get("detectors", _DEFAULTS["detectors"])
        self.devices: List[Dict[str, Any]] = raw.get("devices", _DEFAULTS["devices"])

        # ── 旧版 vision_api 配置同步到 detectors（向后兼容）──────────────
        # 如果 yaml 里没有 detectors 但有 vision 配置，把 vision 参数注入默认 detector
        if "detectors" not in raw and raw.get("vision"):
            for det in self.detectors:
                if det.get("plugin") == "vision_api":
                    det["config"] = det.get("config", {})
                    if raw["vision"].get("model"):
                        det["config"]["model"] = raw["vision"]["model"]
                    if raw["vision"].get("timeout"):
                        det["config"]["timeout"] = raw["vision"]["timeout"]
                    if raw.get("presence", {}).get("scene"):
                        det["config"]["scene"] = raw["presence"]["scene"]

        # ── presence.scene 同步到 vision_api detector（如果有）──────────
        if "detectors" not in raw:
            scene = raw.get("presence", {}).get("scene", _DEFAULTS["presence"]["scene"])
            for det in self.detectors:
                if det.get("plugin") == "vision_api":
                    det.setdefault("config", {})
                    det["config"].setdefault("scene", scene)

        self.workspace: Path = WORKSPACE

    def __repr__(self):
        return (
            f"PrismConfig("
            f"sensors={[s.get('plugin') for s in self.sensors]}, "
            f"detectors={[d.get('plugin') for d in self.detectors]}, "
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
    - 文件不存在时静默使用默认值（zero-config 模式）
    - reload=True 强制重新读取文件
    """
    global _cached_config

    if _cached_config is not None and not reload:
        return _cached_config

    raw = {}  # 从空白开始，PrismConfig 内部会填充默认值

    if CONFIG_FILE.exists():
        try:
            import yaml
            with open(CONFIG_FILE, encoding="utf-8") as f:
                user_cfg = yaml.safe_load(f) or {}
            raw = user_cfg
            log.info(f"✅ prism_config.yaml 已加载: {CONFIG_FILE}")
        except ImportError:
            log.warning("PyYAML 未安装，使用默认配置（pip install pyyaml 可启用配置文件）")
        except Exception as e:
            log.warning(f"prism_config.yaml 解析失败，使用默认配置: {e}")
    else:
        log.info("prism_config.yaml 不存在，使用默认配置（zero-config 模式）")

    _cached_config = PrismConfig(raw)
    return _cached_config
