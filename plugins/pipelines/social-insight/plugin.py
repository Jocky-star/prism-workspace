"""
social-insight 管线插件 — 薄包装 src/services/generators/social_insight.py
"""
import sys
from pathlib import Path
from typing import Any, Dict, List

_WORKSPACE = Path(__file__).resolve().parents[3]
if str(_WORKSPACE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE))

from prism.plugin_base import PipelinePlugin


class SocialInsightPlugin(PipelinePlugin):
    name = "social-insight"
    version = "1.0.0"
    required_sources = []
    optional_sources = ["chat", "audio"]

    def setup(self, config: dict) -> bool:
        return True

    def generate(self, date: str, data: Dict[str, List]) -> dict:
        """生成本周人际洞察"""
        try:
            from src.services.generators.social_insight import generate_social_insight
            dry_run = self.config.get("dry_run", False)
            return generate_social_insight(date, dry_run=dry_run)
        except Exception as e:
            return {
                "generator": "social_insight",
                "date": date,
                "error": str(e),
                "insight": {},
                "events_analyzed": 0,
            }

    def health_check(self) -> dict:
        try:
            from src.services.generators.social_insight import generate_social_insight
            return {"status": "ok", "message": "social_insight module available"}
        except ImportError as e:
            return {"status": "error", "message": str(e)}
