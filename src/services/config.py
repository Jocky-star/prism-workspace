"""
服务系统统一配置

所有路径、飞书配置、LLM 配置从这里获取。
新用户只需修改这个文件（或创建 config.yaml），不需要改其他代码。

配置优先级（从高到低）：
  1. 环境变量（BRIEF_TARGET_USER_ID、FEISHU_TENANT_DOMAIN 等）
  2. config.yaml（src/services/config.yaml，从 config.example.yaml 复制）
  3. 代码里的默认值

快速开始：
  1. cp src/services/config.example.yaml src/services/config.yaml
  2. 编辑 config.yaml，填入你的飞书 open_id 和租户域名
  3. 运行 python3 src/services/morning_push.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

# ── 路径配置 ────────────────────────────────────────────────────────

# Workspace 自动检测
# 优先级：环境变量 WORKSPACE → OPENCLAW_WORKSPACE → 默认路径
WORKSPACE = Path(os.environ.get(
    "WORKSPACE",
    os.environ.get(
        "OPENCLAW_WORKSPACE",
        str(Path.home() / ".openclaw" / "workspace")
    )
))

# 数据目录
MEMORY_DIR = WORKSPACE / "memory"
SERVICES_OUTPUT_DIR = MEMORY_DIR / "services"
INTELLIGENCE_DIR = MEMORY_DIR / "intelligence"

# 确保输出目录存在
SERVICES_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ── 配置文件加载 ─────────────────────────────────────────────────────

_CONFIG_YAML_PATH = Path(__file__).parent / "config.yaml"
_CONFIG_EXAMPLE_PATH = Path(__file__).parent / "config.example.yaml"

_yaml_config: Optional[Dict[str, Any]] = None


def _load_yaml_config() -> Dict[str, Any]:
    """加载 config.yaml（如果存在）。懒加载，只读一次。"""
    global _yaml_config
    if _yaml_config is not None:
        return _yaml_config

    if _CONFIG_YAML_PATH.exists():
        try:
            # 使用标准库解析简单 YAML（不依赖 PyYAML）
            _yaml_config = _parse_simple_yaml(_CONFIG_YAML_PATH.read_text(encoding="utf-8"))
        except Exception:
            _yaml_config = {}
    else:
        _yaml_config = {}
    return _yaml_config


def _parse_simple_yaml(text: str) -> Dict[str, Any]:
    """解析简单的两级 YAML（不依赖 PyYAML）。

    支持格式：
      section:
        key: value
        key2: "quoted value"
      # comments
    不支持：列表、多行值、锚点等复杂特性。
    如果系统已安装 PyYAML，自动使用它。
    """
    # 优先使用 PyYAML
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except ImportError:
        pass

    result: Dict[str, Any] = {}
    current_section: Optional[str] = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        # 跳过注释和空行
        if not line or line.lstrip().startswith("#"):
            continue
        # 跳过注释的配置行（被 # 注释掉的键）
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue

        # 检测缩进
        indent = len(raw_line) - len(raw_line.lstrip())
        if indent == 0 and line.endswith(":"):
            # 顶级 section
            current_section = line[:-1].strip()
            if current_section not in result:
                result[current_section] = {}
        elif indent > 0 and ":" in line and current_section:
            # 子键
            key_part, _, val_part = line.partition(":")
            key = key_part.strip()
            val_raw = val_part.strip()
            # 去掉行尾注释
            if "  #" in val_raw:
                val_raw = val_raw[:val_raw.index("  #")].strip()
            # 去掉引号
            if (val_raw.startswith('"') and val_raw.endswith('"')) or \
               (val_raw.startswith("'") and val_raw.endswith("'")):
                val_raw = val_raw[1:-1]
            # 跳过空值（配置项未填）
            if val_raw and not val_raw.startswith("#"):
                result[current_section][key] = val_raw

    return result


def _cfg(section: str, key: str, default: Any = None) -> Any:
    """从 config.yaml 读取一个值，若不存在返回 default。"""
    cfg = _load_yaml_config()
    return cfg.get(section, {}).get(key, default)


# ── 飞书配置 ─────────────────────────────────────────────────────────

def get_feishu_target_user_ids() -> list[str]:
    """返回 Brief 推送目标的飞书 open_id 列表。

    配置方式（任选其一）：
    1. 环境变量 BRIEF_TARGET_USER_ID（逗号分隔多个）
    2. config.yaml 的 brief.target_user_id
    3. 若未配置，返回空列表（Brief 只输出到 stdout，不发飞书）
    """
    # 环境变量优先
    env_val = os.environ.get("BRIEF_TARGET_USER_ID", "")
    if env_val:
        return [uid.strip() for uid in env_val.split(",") if uid.strip()]

    # config.yaml
    yaml_val = _cfg("brief", "target_user_id", "")
    if yaml_val and yaml_val != "ou_xxx":
        return [uid.strip() for uid in str(yaml_val).split(",") if uid.strip()]

    # 未配置 → 无推送目标（降级到 stdout）
    return []


def get_feishu_tenant_domain() -> str:
    """返回飞书租户域名，如 'ccnq3wnum0kr.feishu.cn'。

    配置方式：
    1. 环境变量 FEISHU_TENANT_DOMAIN
    2. config.yaml 的 feishu.tenant_domain
    3. 默认 'open.feishu.cn'（通用域名，部分 URL 场景可能需要租户域名）
    """
    env_val = os.environ.get("FEISHU_TENANT_DOMAIN", "")
    if env_val:
        return env_val.rstrip("/")

    yaml_val = _cfg("feishu", "tenant_domain", "")
    if yaml_val and yaml_val != "xxx.feishu.cn":
        return str(yaml_val).rstrip("/")

    return "open.feishu.cn"


def get_feishu_app_id() -> str:
    """返回飞书 App ID。

    配置方式：
    1. 环境变量 FEISHU_APP_ID
    2. config.yaml 的 feishu.app_id
    3. openclaw.json（自动读取）
    """
    env_val = os.environ.get("FEISHU_APP_ID", "")
    if env_val:
        return env_val

    yaml_val = _cfg("feishu", "app_id", "")
    if yaml_val:
        return str(yaml_val)

    # 从 openclaw.json 自动读取
    return _read_openclaw_feishu_field("appId")


def get_feishu_app_secret() -> str:
    """返回飞书 App Secret。

    配置方式：
    1. 环境变量 FEISHU_APP_SECRET
    2. config.yaml 的 feishu.app_secret（不推荐，有安全风险）
    3. openclaw.json（推荐，自动读取）
    """
    env_val = os.environ.get("FEISHU_APP_SECRET", "")
    if env_val:
        return env_val

    yaml_val = _cfg("feishu", "app_secret", "")
    if yaml_val:
        return str(yaml_val)

    return _read_openclaw_feishu_field("appSecret")


def get_openclaw_json_path() -> Path:
    """返回 openclaw.json 的路径。

    配置方式：
    1. 环境变量 OPENCLAW_JSON
    2. config.yaml 的 feishu.openclaw_json
    3. 默认 ~/.openclaw/openclaw.json
    """
    env_val = os.environ.get("OPENCLAW_JSON", "")
    if env_val:
        return Path(env_val)

    yaml_val = _cfg("feishu", "openclaw_json", "")
    if yaml_val:
        return Path(yaml_val).expanduser()

    return Path.home() / ".openclaw" / "openclaw.json"


def _read_openclaw_feishu_field(field: str) -> str:
    """从 openclaw.json 读取飞书配置字段（appId 或 appSecret）。"""
    try:
        path = get_openclaw_json_path()
        cfg = json.loads(path.read_text(encoding="utf-8"))
        val = cfg.get("channels", {}).get("feishu", {}).get(field, "")
        return val or ""
    except Exception:
        return ""


# ── Brief 配置 ───────────────────────────────────────────────────────

def get_brief_push_time() -> str:
    """返回 Brief 推送时间，格式 'HH:MM'。

    配置方式：
    1. 环境变量 BRIEF_PUSH_TIME
    2. config.yaml 的 brief.push_time
    3. 默认 '08:30'
    """
    env_val = os.environ.get("BRIEF_PUSH_TIME", "")
    if env_val:
        return env_val

    yaml_val = _cfg("brief", "push_time", "")
    if yaml_val:
        return str(yaml_val)

    return "08:30"


def get_brief_max_chars() -> int:
    """返回 Brief 内容字数限制（0 表示不限制）。

    配置方式：
    1. 环境变量 BRIEF_MAX_CHARS
    2. config.yaml 的 brief.max_chars
    3. 默认 0（不限制）
    """
    env_val = os.environ.get("BRIEF_MAX_CHARS", "")
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            pass

    yaml_val = _cfg("brief", "max_chars", "")
    if yaml_val:
        try:
            return int(yaml_val)
        except ValueError:
            pass

    return 0


# ── LLM 配置 ────────────────────────────────────────────────────────

def get_llm_model() -> str:
    """返回 LLM 模型名称。

    配置方式：
    1. 环境变量 LLM_MODEL
    2. config.yaml 的 llm.model
    3. 默认 'claude-haiku-4-5-20251001'（经济实惠的默认选项）

    注意：使用 litellm provider（models.json）时会自动添加前缀（如 'pa/'）。
    使用环境变量配置时，直接填入 provider 支持的完整 model 名即可。
    """
    env_val = os.environ.get("LLM_MODEL", "")
    if env_val:
        return env_val

    yaml_val = _cfg("llm", "model", "")
    if yaml_val and yaml_val != "auto":
        return str(yaml_val)

    return "claude-haiku-4-5-20251001"
