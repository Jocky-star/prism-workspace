"""Prism 插件注册中心"""
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

WORKSPACE = Path(__file__).resolve().parent.parent
PLUGINS_DIR = WORKSPACE / "plugins"
CONFIG_PATH = WORKSPACE / "config.yaml"

# 插件类型目录映射
PLUGIN_TYPE_DIRS = {
    "source": "sources",
    "pipeline": "pipelines",
    "actuator": "actuators",
}


def _load_yaml(path: Path) -> dict:
    """加载 YAML，优先用 PyYAML，降级为 json"""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")

    # 尝试 PyYAML
    try:
        import yaml
        return yaml.safe_load(text) or {}
    except ImportError:
        pass

    # 降级：尝试 json
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 最后降级：简易 key: value 解析
    data = {}
    current_section = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" ") and stripped.endswith(":"):
            current_section = stripped[:-1].strip()
            data[current_section] = {}
            continue
        if ":" in stripped:
            k, _, v = stripped.partition(":")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if current_section is not None:
                if isinstance(data.get(current_section), dict):
                    data[current_section][k] = v
            else:
                data[k] = v
    return data


def _read_global_config() -> dict:
    """读取全局 config.yaml"""
    return _load_yaml(CONFIG_PATH)


class PluginRegistry:
    """插件注册中心"""

    def __init__(self, plugins_dir: Path = None):
        self.plugins_dir = plugins_dir or PLUGINS_DIR
        self._manifest_cache: Dict[str, dict] = {}
        self._instance_cache: Dict[str, Any] = {}

    # ── 发现 ─────────────────────────────────────────────

    def discover(self) -> List[dict]:
        """扫描所有已安装插件，返回 manifest 列表"""
        results = []
        if not self.plugins_dir.exists():
            return results

        for type_name, type_dir in PLUGIN_TYPE_DIRS.items():
            type_path = self.plugins_dir / type_dir
            if not type_path.exists():
                continue
            for plugin_dir in sorted(type_path.iterdir()):
                if not plugin_dir.is_dir():
                    continue
                if plugin_dir.name.startswith("."):
                    continue
                manifest = self._load_manifest(plugin_dir)
                if manifest:
                    manifest.setdefault("_dir", str(plugin_dir))
                    manifest.setdefault("_type_dir", type_name)
                    results.append(manifest)

        return results

    def discover_by_type(self) -> Dict[str, List[dict]]:
        """按类型分组返回已安装插件"""
        by_type: Dict[str, List[dict]] = {t: [] for t in PLUGIN_TYPE_DIRS}
        for manifest in self.discover():
            ptype = manifest.get("type", manifest.get("_type_dir", "source"))
            by_type.setdefault(ptype, []).append(manifest)
        return by_type

    # ── Manifest ──────────────────────────────────────────

    def _find_plugin_dir(self, plugin_name: str) -> Optional[Path]:
        """根据名称找到插件目录"""
        for type_dir in PLUGIN_TYPE_DIRS.values():
            candidate = self.plugins_dir / type_dir / plugin_name
            if candidate.is_dir():
                return candidate
        return None

    def _load_manifest(self, plugin_dir: Path) -> Optional[dict]:
        """加载插件 manifest"""
        manifest_path = plugin_dir / "manifest.yaml"
        if not manifest_path.exists():
            manifest_path = plugin_dir / "manifest.json"
        if not manifest_path.exists():
            return None

        data = _load_yaml(manifest_path)
        if not data:
            return None

        # 注入目录名作为 fallback id
        data.setdefault("id", plugin_dir.name)
        data.setdefault("name", plugin_dir.name)
        return data

    def get_manifest(self, plugin_name: str) -> Optional[dict]:
        """获取指定插件的 manifest"""
        if plugin_name in self._manifest_cache:
            return self._manifest_cache[plugin_name]

        plugin_dir = self._find_plugin_dir(plugin_name)
        if not plugin_dir:
            return None

        manifest = self._load_manifest(plugin_dir)
        if manifest:
            self._manifest_cache[plugin_name] = manifest
        return manifest

    # ── 加载 ─────────────────────────────────────────────

    def _load_plugin_class(self, plugin_dir: Path) -> Optional[Type]:
        """动态加载插件类"""
        plugin_file = plugin_dir / "plugin.py"
        if not plugin_file.exists():
            return None

        module_name = f"prism_plugin_{plugin_dir.name.replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, plugin_file)
        if not spec:
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            print(f"  ⚠️ 加载插件 {plugin_dir.name} 失败: {e}")
            return None

        # 查找插件类：继承自 PluginBase 的非抽象类
        from prism.plugin_base import PluginBase
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            try:
                if (
                    isinstance(obj, type)
                    and issubclass(obj, PluginBase)
                    and obj is not PluginBase
                    and not getattr(obj, "__abstractmethods__", None)
                ):
                    return obj
            except TypeError:
                continue

        return None

    def _get_plugin_config(self, plugin_name: str) -> dict:
        """从全局 config.yaml 读取该插件的配置"""
        global_cfg = _read_global_config()
        # 尝试 plugins.<name> 或 sources.<name> 等路径
        plugins_cfg = global_cfg.get("plugins", {})
        if plugin_name in plugins_cfg:
            return plugins_cfg[plugin_name]
        # 也尝试 sources/pipelines/actuators 下的配置
        for section in ("sources", "pipelines", "actuators"):
            section_cfg = global_cfg.get(section, {})
            if isinstance(section_cfg, dict) and plugin_name in section_cfg:
                return section_cfg[plugin_name]
        return {}

    def load(self, plugin_name: str) -> Optional[Any]:
        """加载并实例化指定插件"""
        if plugin_name in self._instance_cache:
            return self._instance_cache[plugin_name]

        plugin_dir = self._find_plugin_dir(plugin_name)
        if not plugin_dir:
            print(f"❌ 未找到插件: {plugin_name}")
            return None

        plugin_class = self._load_plugin_class(plugin_dir)
        if not plugin_class:
            print(f"❌ 无法加载插件类: {plugin_name}")
            return None

        config = self._get_plugin_config(plugin_name)
        instance = plugin_class(config=config)
        self._instance_cache[plugin_name] = instance
        return instance

    def load_all(self, plugin_type: str = None) -> Dict[str, Any]:
        """加载所有（或指定类型的）插件，返回 {name: instance}"""
        results = {}
        for manifest in self.discover():
            ptype = manifest.get("type", manifest.get("_type_dir", ""))
            if plugin_type and ptype != plugin_type:
                continue
            name = manifest.get("id", manifest.get("name", ""))
            if name:
                instance = self.load(name)
                if instance:
                    results[name] = instance
        return results

    # ── 验证 ─────────────────────────────────────────────

    def verify(self, plugin_name: str, config: dict = None) -> bool:
        """验证插件配置是否有效"""
        instance = self.load(plugin_name)
        if not instance:
            return False

        cfg = config or self._get_plugin_config(plugin_name)
        try:
            result = instance.setup(cfg)
            return bool(result)
        except Exception as e:
            print(f"  ❌ 插件 {plugin_name} 验证异常: {e}")
            return False

    # ── 能力汇总 ──────────────────────────────────────────

    def get_capabilities(self) -> dict:
        """汇总所有插件的能力（skills + mcp）"""
        capabilities = {
            "skills": [],
            "mcp": [],
            "by_plugin": {},
        }

        for manifest in self.discover():
            plugin_name = manifest.get("id", manifest.get("name", ""))
            caps = manifest.get("capabilities", {})
            plugin_caps = {}

            # Skills
            skills = caps.get("skills", [])
            if isinstance(skills, str):
                skills = [skills]
            if skills:
                plugin_caps["skills"] = skills
                capabilities["skills"].extend(skills)

            # MCP
            mcp = caps.get("mcp", {})
            if mcp:
                plugin_caps["mcp"] = mcp
                capabilities["mcp"].append(mcp)

            if plugin_caps:
                capabilities["by_plugin"][plugin_name] = plugin_caps

        return capabilities

    # ── 状态检测 ──────────────────────────────────────────

    def _get_plugin_status(self, manifest: dict) -> str:
        """根据配置判断插件状态"""
        plugin_name = manifest.get("id", manifest.get("name", ""))
        global_cfg = _read_global_config()

        # 检查 config.yaml 中是否有该插件的配置
        plugin_cfg = self._get_plugin_config(plugin_name)

        # 检查 enabled 字段
        if isinstance(plugin_cfg, dict):
            enabled = plugin_cfg.get("enabled", None)
            if enabled is True or str(enabled).lower() == "true":
                return "enabled"
            elif enabled is False or str(enabled).lower() == "false":
                return "disabled"

        # 检查是否有实质性配置（非空字典）
        if plugin_cfg and isinstance(plugin_cfg, dict):
            return "configured"

        return "unconfigured"
