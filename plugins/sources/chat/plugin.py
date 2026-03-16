"""
chat 数据源插件 — 薄包装 src/sources/chat/extract.py
"""
import sys
from pathlib import Path
from typing import Any, Dict, List

_WORKSPACE = Path(__file__).resolve().parents[3]
if str(_WORKSPACE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE))

from prism.plugin_base import SourcePlugin


class ChatSourcePlugin(SourcePlugin):
    name = "chat"
    version = "1.0.0"

    def setup(self, config: dict) -> bool:
        # 零配置，只检查 memory/ 目录是否存在
        memory_dir = _WORKSPACE / "memory"
        if not memory_dir.exists():
            print(f"  ⚠️  chat: memory/ 目录不存在: {memory_dir}")
            return False
        return True

    def fetch(self, date: str) -> List[Dict[str, Any]]:
        """提取指定日期的对话记录"""
        try:
            from src.sources.chat.extract import extract_chat_data
            data = extract_chat_data(date)
            return [data] if data else []
        except ImportError:
            return self._fetch_direct(date)
        except Exception as e:
            return [{"date": date, "available": False, "error": str(e)}]

    def _fetch_direct(self, date: str) -> List[Dict[str, Any]]:
        try:
            import importlib.util
            extract_path = _WORKSPACE / "src" / "sources" / "chat" / "extract.py"
            spec = importlib.util.spec_from_file_location("chat_extract", extract_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            fn = getattr(mod, "extract_chat_data", None) or getattr(mod, "get_today_data", None)
            if fn:
                data = fn(date)
                return [data] if data else []
        except Exception as e:
            pass
        # 最小降级：直接读 memory 文件
        memory_file = _WORKSPACE / "memory" / f"{date}.md"
        if memory_file.exists():
            content = memory_file.read_text(encoding="utf-8")
            return [{"date": date, "available": True, "raw_memory": content, "messages": []}]
        return [{"date": date, "available": False, "error": "no memory file"}]

    def health_check(self) -> dict:
        memory_dir = _WORKSPACE / "memory"
        if not memory_dir.exists():
            return {"status": "error", "message": f"memory/ not found: {memory_dir}"}
        return {"status": "ok", "message": "memory/ accessible"}
