"""Prism 插件基类"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pathlib import Path


class PluginBase(ABC):
    """所有插件的基类"""
    name: str = ""
    plugin_type: str = ""  # source | pipeline | actuator
    version: str = "1.0.0"

    def __init__(self, config: dict = None):
        self.config = config or {}
        self._enabled = False

    @abstractmethod
    def setup(self, config: dict) -> bool:
        """验证配置是否有效，返回 True/False"""
        pass

    @abstractmethod
    def health_check(self) -> dict:
        """健康检查，返回 {"status": "ok"|"error", ...}"""
        pass

    def teardown(self):
        """清理资源（可选覆盖）"""
        pass


class SourcePlugin(PluginBase):
    """数据源插件基类"""
    plugin_type = "source"

    @abstractmethod
    def fetch(self, date: str) -> List[Dict[str, Any]]:
        """拉取指定日期的数据，返回标准格式列表"""
        pass

    def fetch_range(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """拉取日期范围的数据（默认逐天调用 fetch）"""
        from datetime import datetime, timedelta
        results = []
        current = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        while current <= end:
            results.extend(self.fetch(current.strftime("%Y-%m-%d")))
            current += timedelta(days=1)
        return results


class PipelinePlugin(PluginBase):
    """服务管线插件基类"""
    plugin_type = "pipeline"
    required_sources: List[str] = []
    optional_sources: List[str] = []

    @abstractmethod
    def generate(self, date: str, data: Dict[str, List]) -> dict:
        """基于数据生成报告/服务结果"""
        pass

    def format(self, result: dict) -> str:
        """格式化输出（默认返回 JSON）"""
        import json
        return json.dumps(result, ensure_ascii=False, indent=2)


class ActuatorPlugin(PluginBase):
    """执行器插件基类"""
    plugin_type = "actuator"

    @abstractmethod
    def execute(self, action: str, params: dict) -> bool:
        """执行动作，返回是否成功"""
        pass

    def get_capabilities(self) -> List[str]:
        """返回支持的动作列表"""
        return []
