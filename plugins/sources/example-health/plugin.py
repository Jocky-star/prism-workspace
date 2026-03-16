"""example-health 插件 — 示例健康数据源（返回 mock 数据）"""
import random
from datetime import datetime
from typing import Any, Dict, List

# 将 workspace 加入路径
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from prism.plugin_base import SourcePlugin


class ExampleHealthPlugin(SourcePlugin):
    """示例健康数据源，返回随机 mock 健康数据"""

    name = "example-health"
    version = "1.0.0"

    def setup(self, config: dict) -> bool:
        """示例插件无需真实配置，直接返回 True"""
        self.config = config or {}
        self._enabled = True
        return True

    def health_check(self) -> dict:
        """健康检查"""
        return {
            "status": "ok",
            "plugin": self.name,
            "version": self.version,
            "mock_mode": self.config.get("mock_mode", True),
        }

    def fetch(self, date: str) -> List[Dict[str, Any]]:
        """返回指定日期的 mock 健康数据"""
        # 用日期字符串作为随机种子，保证同一天的数据一致
        seed = int(datetime.strptime(date, "%Y-%m-%d").timestamp())
        rng = random.Random(seed)

        record = {
            "date": date,
            "source": "example-health",
            "steps": rng.randint(4000, 15000),
            "sleep_score": rng.randint(60, 95),
            "heart_rate_avg": rng.randint(58, 85),
            "calories": rng.randint(1800, 2800),
            "active_minutes": rng.randint(20, 120),
            "sleep_hours": round(rng.uniform(5.5, 9.0), 1),
            "water_ml": rng.randint(1200, 3000),
        }
        return [record]
