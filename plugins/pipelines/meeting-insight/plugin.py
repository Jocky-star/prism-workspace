"""
meeting-insight 管线插件 — 薄包装 src/services/generators/meeting_insight.py
"""
import sys
from pathlib import Path
from typing import Any, Dict, List

_WORKSPACE = Path(__file__).resolve().parents[3]
if str(_WORKSPACE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE))

from prism.plugin_base import PipelinePlugin


class MeetingInsightPlugin(PipelinePlugin):
    name = "meeting-insight"
    version = "1.0.0"
    required_sources = ["audio"]
    optional_sources = []

    def setup(self, config: dict) -> bool:
        return True

    def generate(self, date: str, data: Dict[str, List]) -> dict:
        """分析当日会议录音"""
        try:
            from src.services.generators.meeting_insight import generate_meeting_insights
            dry_run = self.config.get("dry_run", False)
            return generate_meeting_insights(date, dry_run=dry_run)
        except Exception as e:
            return {
                "generator": "meeting_insight",
                "date": date,
                "error": str(e),
                "meetings": [],
                "meeting_count": 0,
            }

    def health_check(self) -> dict:
        try:
            from src.services.generators.meeting_insight import generate_meeting_insights
            return {"status": "ok", "message": "meeting_insight module available"}
        except ImportError as e:
            return {"status": "error", "message": str(e)}
