"""
emotion-care 管线插件 — 薄包装 src/services/generators/emotion_care.py
"""
import sys
from pathlib import Path
from typing import Any, Dict, List

_WORKSPACE = Path(__file__).resolve().parents[3]
if str(_WORKSPACE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE))

from prism.plugin_base import PipelinePlugin


class EmotionCarePlugin(PipelinePlugin):
    name = "emotion-care"
    version = "1.0.0"
    required_sources = []
    optional_sources = ["audio", "camera"]

    def setup(self, config: dict) -> bool:
        sensitivity = config.get("sensitivity", "normal")
        if sensitivity not in ("low", "normal", "high"):
            print(f"  ⚠️  emotion-care: sensitivity 值无效: {sensitivity}")
            return False
        return True

    def generate(self, date: str, data: Dict[str, List]) -> dict:
        """检测情绪状态，必要时生成关怀消息"""
        try:
            from src.services.generators.emotion_care import generate_emotion_care
            sensitivity = self.config.get("sensitivity", "normal")
            dry_run = self.config.get("dry_run", False)
            return generate_emotion_care(date, sensitivity=sensitivity, dry_run=dry_run)
        except Exception as e:
            return {
                "generator": "emotion_care",
                "date": date,
                "error": str(e),
                "triggered": False,
                "signal_score": 0,
            }

    def health_check(self) -> dict:
        try:
            from src.services.generators.emotion_care import generate_emotion_care
            return {"status": "ok", "message": "emotion_care module available"}
        except ImportError as e:
            return {"status": "error", "message": str(e)}
