"""
intent-tracker 管线插件 — 薄包装 src/services/generators/intent_tracker.py
"""
import sys
from pathlib import Path
from typing import Any, Dict, List

_WORKSPACE = Path(__file__).resolve().parents[3]
if str(_WORKSPACE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE))

from prism.plugin_base import PipelinePlugin


class IntentTrackerPlugin(PipelinePlugin):
    name = "intent-tracker"
    version = "1.0.0"
    required_sources = []
    optional_sources = ["audio", "chat"]

    def setup(self, config: dict) -> bool:
        return True

    def generate(self, date: str, data: Dict[str, List]) -> dict:
        """提取并追踪意图"""
        try:
            from src.services.generators.intent_tracker import generate_intent_tracking
            dry_run = self.config.get("dry_run", False)
            return generate_intent_tracking(date, dry_run=dry_run)
        except Exception as e:
            return {
                "generator": "intent_tracker",
                "date": date,
                "error": str(e),
                "intents": [],
                "by_type": {},
            }

    def health_check(self) -> dict:
        try:
            from src.services.generators.intent_tracker import generate_intent_tracking
            return {"status": "ok", "message": "intent_tracker module available"}
        except ImportError as e:
            return {"status": "error", "message": str(e)}
