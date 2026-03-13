"""
Shared LLM client for service generators.

配置优先级：
  1. 环境变量 LLM_BASE_URL + LLM_API_KEY + LLM_MODEL
  2. ~/.openclaw/agents/main/agent/models.json (litellm provider, 兼容现有环境)
  3. 报错提示配置方法
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import urllib.request
import urllib.error

MODELS_CONFIG = Path.home() / ".openclaw" / "agents" / "main" / "agent" / "models.json"

# 通用默认 model（不带 pa/ 前缀，新用户友好）
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "claude-haiku-4-5-20251001")


def _load_api_config() -> Dict[str, Any]:
    """
    Load API config following priority:
    1. Environment variables: LLM_BASE_URL + LLM_API_KEY
    2. models.json litellm provider (legacy/current environment)
    3. Raise with helpful error message
    """
    # Priority 1: Environment variables
    base_url = os.environ.get("LLM_BASE_URL", "").rstrip("/")
    api_key = os.environ.get("LLM_API_KEY", "")
    if base_url and api_key:
        return {
            "base_url": base_url,
            "api_key": api_key,
            "headers": {},
            "model_prefix": "",  # env var users provide full model name
        }

    # Priority 2: models.json (litellm provider)
    if MODELS_CONFIG.exists():
        try:
            with open(MODELS_CONFIG, encoding="utf-8") as f:
                d = json.load(f)
            provider = d.get("providers", {}).get("litellm", {})
            pbase = provider.get("baseUrl", "").rstrip("/")
            pkey = provider.get("apiKey", "")
            if pbase and pkey:
                # Detect model prefix from available models
                models = provider.get("models", [])
                model_ids = [m["id"] if isinstance(m, dict) else m for m in models]
                prefix = ""
                if model_ids and "/" in model_ids[0]:
                    prefix = model_ids[0].rsplit("/", 1)[0] + "/"
                return {
                    "base_url": pbase,
                    "api_key": pkey,
                    "headers": provider.get("headers", {}),
                    "model_prefix": prefix,  # e.g. "pa/" for litellm
                }
        except Exception:
            pass  # Fall through to error

    # Priority 3: Error with helpful message
    raise RuntimeError(
        "LLM 未配置。请设置环境变量：\n"
        "  export LLM_BASE_URL=https://your-api-endpoint/v1\n"
        "  export LLM_API_KEY=your-api-key\n"
        "  export LLM_MODEL=claude-haiku-4-5-20251001  # 可选，默认此值\n"
        "\n"
        "或者确保 ~/.openclaw/agents/main/agent/models.json 存在且包含 litellm provider 配置。"
    )


def llm_complete(
    prompt: str,
    system: str = "",
    model: Optional[str] = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    dry_run: bool = False,
) -> str:
    """
    Call the LLM and return the assistant message text.
    In dry_run mode returns a placeholder string without making API calls.

    model: 覆盖默认 model。如果使用 models.json 环境，可传入带前缀的 model 名。
           如果使用环境变量，直接传 model 名即可。
    """
    effective_model = model or DEFAULT_MODEL

    if dry_run:
        return f"[DRY-RUN: would call {effective_model} with {len(prompt)} chars prompt]"

    cfg = _load_api_config()
    base_url = cfg["base_url"]
    api_key = cfg["api_key"]
    extra_headers = cfg["headers"]
    
    # Auto-add model prefix if needed (e.g. "pa/" for litellm provider)
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
    # Quick sanity test: show config source and optionally call LLM
    import argparse
    parser = argparse.ArgumentParser(description="LLM client config check")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually call LLM")
    parser.add_argument("--test-call", action="store_true", help="Make a test call to the LLM")
    args = parser.parse_args()

    print("=== LLM Client Config Check ===\n")

    # Show config source
    base_url_env = os.environ.get("LLM_BASE_URL", "")
    api_key_env = os.environ.get("LLM_API_KEY", "")

    if base_url_env and api_key_env:
        print("✅ Config source: 环境变量 (LLM_BASE_URL + LLM_API_KEY)")
        print(f"   base_url: {base_url_env}")
        print(f"   model: {DEFAULT_MODEL}")
    elif MODELS_CONFIG.exists():
        print(f"✅ Config source: models.json ({MODELS_CONFIG})")
        print(f"   model: {DEFAULT_MODEL}")
    else:
        print("❌ 未找到配置")
        print("   请设置环境变量 LLM_BASE_URL 和 LLM_API_KEY")
        print("   或确保 ~/.openclaw/agents/main/agent/models.json 存在")

    if args.dry_run or args.test_call:
        resp = llm_complete("Say hello in 5 words.", dry_run=args.dry_run)
        print(f"\nLLM response: {resp}")
