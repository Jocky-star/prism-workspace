"""
Shared LLM client for service generators.

配置优先级：
  1. 环境变量 LLM_BASE_URL + LLM_API_KEY + LLM_MODEL
  2. ~/.openclaw/agents/main/agent/models.json (litellm provider，兼容现有环境)
  3. config.yaml 的 llm.model（只影响 model 名称，不影响 endpoint）
  4. 报错提示配置方法

快速开始（新用户）：
  export LLM_BASE_URL=https://your-api-endpoint/v1
  export LLM_API_KEY=your-api-key
  export LLM_MODEL=claude-haiku-4-5-20251001
  python3 src/services/morning_push.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import urllib.request
import urllib.error

MODELS_CONFIG = Path.home() / ".openclaw" / "agents" / "main" / "agent" / "models.json"


def _get_default_model() -> str:
    """从 config 读取默认模型名称（延迟导入，避免循环依赖）。"""
    # 环境变量最高优先
    env_val = os.environ.get("LLM_MODEL", "")
    if env_val:
        return env_val

    # 再从 config.yaml 读
    try:
        from src.services.config import get_llm_model
        model = get_llm_model()
        if model and model != "auto":
            return model
    except ImportError:
        pass

    return "claude-haiku-4-5-20251001"


def _load_api_config() -> Dict[str, Any]:
    """加载 API 配置，按优先级：环境变量 → models.json → 报错提示。"""
    # 优先级 1：环境变量
    base_url = os.environ.get("LLM_BASE_URL", "").rstrip("/")
    api_key = os.environ.get("LLM_API_KEY", "")
    if base_url and api_key:
        return {
            "base_url": base_url,
            "api_key": api_key,
            "headers": {},
            "model_prefix": "",  # 环境变量用户直接提供完整 model 名
        }

    # 优先级 2：models.json（litellm provider）
    if MODELS_CONFIG.exists():
        try:
            with open(MODELS_CONFIG, encoding="utf-8") as f:
                d = json.load(f)
            provider = d.get("providers", {}).get("litellm", {})
            pbase = provider.get("baseUrl", "").rstrip("/")
            pkey = provider.get("apiKey", "")
            if pbase and pkey:
                # 从已有模型列表推断前缀（如 "pa/"）
                models = provider.get("models", [])
                model_ids = [m["id"] if isinstance(m, dict) else m for m in models]
                prefix = ""
                if model_ids and "/" in model_ids[0]:
                    prefix = model_ids[0].rsplit("/", 1)[0] + "/"
                return {
                    "base_url": pbase,
                    "api_key": pkey,
                    "headers": provider.get("headers", {}),
                    "model_prefix": prefix,  # 例如 "pa/"
                }
        except Exception:
            pass

    # 优先级 3：报错并给出配置指引
    raise RuntimeError(
        "LLM 未配置。请选择以下任意一种方式：\n\n"
        "方式一（环境变量，推荐新用户）：\n"
        "  export LLM_BASE_URL=https://your-api-endpoint/v1\n"
        "  export LLM_API_KEY=your-api-key\n"
        "  export LLM_MODEL=claude-haiku-4-5-20251001\n\n"
        "方式二（OpenClaw 已安装用户）：\n"
        "  确保 ~/.openclaw/agents/main/agent/models.json 包含 litellm provider 配置\n"
    )


def llm_complete(
    prompt: str,
    system: str = "",
    model: Optional[str] = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    dry_run: bool = False,
) -> str:
    """调用 LLM 并返回 assistant 的回复文本。

    Args:
        prompt: 用户消息
        system: 系统提示词（可选）
        model: 覆盖默认 model。使用 models.json 环境时可传带前缀的 model 名；
               使用环境变量时直接传 model 名。
        max_tokens: 最大生成 token 数
        temperature: 采样温度
        dry_run: True 时不实际调用 API，返回占位符字符串

    Returns:
        LLM 返回的文本内容
    """
    effective_model = model or _get_default_model()

    if dry_run:
        return f"[DRY-RUN: would call {effective_model} with {len(prompt)} chars prompt]"

    cfg = _load_api_config()
    base_url = cfg["base_url"]
    api_key = cfg["api_key"]
    extra_headers = cfg["headers"]

    # 自动添加 model 前缀（如 "pa/" for litellm provider）
    prefix = cfg.get("model_prefix", "")
    if prefix and not effective_model.startswith(prefix):
        effective_model = prefix + effective_model

    messages: List[Dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = json.dumps({
        "model": effective_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            **extra_headers,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM API error {e.code}: {body}") from e


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LLM client config check")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually call LLM")
    parser.add_argument("--test-call", action="store_true", help="Make a test call to the LLM")
    args = parser.parse_args()

    print("=== LLM Client Config Check ===\n")

    base_url_env = os.environ.get("LLM_BASE_URL", "")
    api_key_env = os.environ.get("LLM_API_KEY", "")
    default_model = _get_default_model()

    if base_url_env and api_key_env:
        print("✅ Config source: 环境变量 (LLM_BASE_URL + LLM_API_KEY)")
        print(f"   base_url: {base_url_env}")
        print(f"   model: {default_model}")
    elif MODELS_CONFIG.exists():
        print(f"✅ Config source: models.json ({MODELS_CONFIG})")
        print(f"   model: {default_model}")
    else:
        print("❌ 未找到配置")
        print("   请设置环境变量 LLM_BASE_URL 和 LLM_API_KEY")
        print(f"   或确保 {MODELS_CONFIG} 存在")

    if args.dry_run or args.test_call:
        resp = llm_complete("Say hello in 5 words.", dry_run=args.dry_run)
        print(f"\nLLM response: {resp}")
