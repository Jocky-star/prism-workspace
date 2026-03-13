"""
内置检测器插件：vision_api — LLM Vision API 人体检测

使用 LLM Vision API（默认 claude-haiku）通过图像判断是否有人。

特点：
- 准确率高，支持坐姿/侧面/低光等困难场景
- 每次调用有 API 成本（建议搭配 frame_diff 前置过滤）
- 自动从 models.json 读取 API 配置，零额外配置

prism_config.yaml 配置示例：
    detectors:
      - plugin: vision_api
        enabled: true
        config:
          scene: "办公桌前"     # 场景描述，嵌入 prompt
          model: ""            # 空=自动选择（pa/claude-haiku-4-5）
          timeout: 15          # API 超时秒数

与 frame_diff 搭配使用（推荐）：
    detectors:
      - plugin: frame_diff     # 先跑帧差
        config:
          skip_vision_below: 0.005
      - plugin: vision_api     # 帧差低时自动跳过
        config:
          scene: "办公桌前"
"""

import base64
import io
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .. import DetectorPlugin

log = logging.getLogger("prism.detector.vision_api")

# 默认回退模型（与原始 daemon.py 保持一致）
_DEFAULT_MODEL = "pa/claude-haiku-4-5-20251001"


class Plugin(DetectorPlugin):
    """LLM Vision API 人体检测器插件"""

    _DEFAULTS = {
        "scene": "办公桌前",
        "model": "",       # 空 = 自动检测
        "timeout": 15,
    }

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        for k, v in self._DEFAULTS.items():
            if k not in self.config:
                self.config[k] = v
        self._api_config: Optional[Dict] = None  # 懒加载

    def detect(self, image: "Image.Image", context: Dict[str, Any]) -> Dict[str, Any]:
        """
        用 Vision API 检测图像中是否有人。

        依赖 context（由 frame_diff 写入）：
            context["motion_ratio"] — 帧差比例（仅用于日志）

        返回：
            detected: bool — 是否检测到人
        """
        motion_ratio = context.get("motion_ratio", None)
        detected, answer = self._call_vision_api(image)

        if motion_ratio is not None:
            log.info(
                f"🧠 Vision API: {'✅ 有人' if detected else '❌ 无人'} "
                f"(answer='{answer}', 帧差={motion_ratio:.2%})"
            )
        else:
            log.info(f"🧠 Vision API: {'✅ 有人' if detected else '❌ 无人'} (answer='{answer}')")

        return {
            "detected": detected,
            "confidence": 1.0 if detected else 0.0,
            "reason": f"vision_api answer={answer}",
        }

    def _call_vision_api(self, img: "Image.Image") -> Tuple[bool, str]:
        """
        调用 Vision API，返回 (detected: bool, answer: str)。
        失败时返回 (False, "error_reason")。
        """
        try:
            import requests
        except ImportError:
            log.error("requests 未安装 (pip install requests)")
            return False, "no_requests"

        api_config = self._get_api_config()
        if not api_config.get("base_url"):
            log.warning("Vision API 未配置，跳过检测")
            return False, "no_config"

        try:
            t0 = time.monotonic()
            timeout = int(self.config.get("timeout", 15))
            scene = self.config.get("scene", "办公桌前")
            model = self._resolve_model()

            # 压缩图片到 320×240 JPEG，减少 token 消耗
            buf = io.BytesIO()
            img_small = img.copy()
            img_small.thumbnail((320, 240))
            img_small.save(buf, format="JPEG", quality=60)
            img_b64 = base64.b64encode(buf.getvalue()).decode()

            headers = {
                "Authorization": f"Bearer {api_config['api_key']}",
                "Content-Type": "application/json",
                **api_config.get("headers", {}),
            }

            payload = {
                "model": model,
                "max_tokens": 20,
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
                        },
                        {
                            "type": "text",
                            "text": (
                                f"Is there a real, living person currently at or near the "
                                f"{scene} in this image? "
                                "Look for visible skin (face, hands, arms). "
                                "Clothes on a chair, bags, or other objects do NOT count. "
                                "Reply ONLY 'yes' or 'no'."
                            ),
                        },
                    ],
                }],
            }

            resp = requests.post(
                f"{api_config['base_url']}/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout,
            )

            elapsed_ms = int((time.monotonic() - t0) * 1000)

            if resp.status_code != 200:
                log.warning(f"Vision API 返回 {resp.status_code}: {resp.text[:200]}")
                return False, f"api_error_{resp.status_code}"

            result = resp.json()
            answer = result["choices"][0]["message"]["content"].strip().lower()
            tokens = result.get("usage", {}).get("total_tokens", 0)
            detected = answer.startswith("yes")

            log.debug(f"Vision API {elapsed_ms}ms, {tokens} tokens, answer='{answer}'")
            return detected, answer

        except Exception as e:
            if "timeout" in str(type(e).__name__).lower() or "Timeout" in str(e):
                log.warning("Vision API 超时")
                return False, "timeout"
            log.warning(f"Vision API 异常: {e}")
            return False, f"error: {e}"

    def _get_api_config(self) -> Dict:
        """从 models.json 懒加载 API 配置"""
        if self._api_config is not None:
            return self._api_config

        try:
            models_path = Path.home() / ".openclaw/agents/main/agent/models.json"
            with open(models_path) as f:
                d = json.load(f)
            prov = d["providers"]["litellm"]
            self._api_config = {
                "base_url": prov["baseUrl"],
                "api_key": prov["apiKey"],
                "headers": prov.get("headers", {}),
            }
            log.info("✅ Vision API 配置已加载")
        except Exception as e:
            log.error(f"Vision API 配置加载失败: {e}")
            self._api_config = {}

        return self._api_config

    def _resolve_model(self) -> str:
        """解析使用的模型名，空时回退到默认"""
        model = self.config.get("model", "").strip()
        if model:
            return model
        return _DEFAULT_MODEL
