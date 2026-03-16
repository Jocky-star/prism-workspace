"""
daily-brief 管线插件 — 薄包装 src/services/generators/daily_brief.py
"""
import sys
from pathlib import Path
from typing import Any, Dict, List

_WORKSPACE = Path(__file__).resolve().parents[3]
if str(_WORKSPACE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE))

from prism.plugin_base import PipelinePlugin


class DailyBriefPlugin(PipelinePlugin):
    name = "daily-brief"
    version = "1.0.0"
    required_sources = ["chat"]
    optional_sources = ["audio", "stock", "camera"]

    def setup(self, config: dict) -> bool:
        return True

    def generate(self, date: str, data: Dict[str, List]) -> dict:
        """生成晨间 Brief"""
        try:
            from src.services.generators.daily_brief import generate_brief, format_brief_message
            dry_run = self.config.get("dry_run", False)
            result = generate_brief(date, dry_run=dry_run)
            result["formatted_message"] = format_brief_message(result)
            return result
        except Exception as e:
            return {
                "generator": "daily_brief",
                "date": date,
                "error": str(e),
                "brief": {},
            }

    def format(self, result: dict) -> str:
        return result.get("formatted_message", "")

    def health_check(self) -> dict:
        try:
            from src.services.generators.daily_brief import generate_brief
            return {"status": "ok", "message": "daily_brief module available"}
        except ImportError as e:
            return {"status": "error", "message": str(e)}
