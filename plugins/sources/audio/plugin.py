"""
audio 数据源插件 — 薄包装 src/sources/audio/fetch.py
"""
import sys
from pathlib import Path
from typing import Any, Dict, List

# 确保 workspace 根目录在 sys.path 中
_WORKSPACE = Path(__file__).resolve().parents[3]
if str(_WORKSPACE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE))

from prism.plugin_base import SourcePlugin


class AudioSourcePlugin(SourcePlugin):
    name = "audio"
    version = "1.0.0"

    def setup(self, config: dict) -> bool:
        api_url = config.get("api_url", "")
        api_key = config.get("api_key", "")
        if not api_url or not api_key:
            print("  ⚠️  audio: 需要配置 api_url 和 api_key")
            return False
        return True

    def fetch(self, date: str) -> List[Dict[str, Any]]:
        """拉取指定日期的录音转写数据"""
        try:
            from src.sources.audio.fetch import fetch_audio_data
            data = fetch_audio_data(date)
            return [data] if data else []
        except ImportError:
            # 直接调用核心逻辑
            return self._fetch_direct(date)
        except Exception as e:
            return [{"date": date, "available": False, "error": str(e)}]

    def _fetch_direct(self, date: str) -> List[Dict[str, Any]]:
        """直接调用 fetch.py 的逻辑（兼容不同入口方式）"""
        try:
            import importlib.util
            fetch_path = _WORKSPACE / "src" / "sources" / "audio" / "fetch.py"
            spec = importlib.util.spec_from_file_location("audio_fetch", fetch_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "fetch_audio_data"):
                data = mod.fetch_audio_data(date)
                return [data] if data else []
        except Exception as e:
            pass
        return [{"date": date, "available": False, "error": "module not found"}]

    def health_check(self) -> dict:
        api_url = self.config.get("api_url", "")
        api_key = self.config.get("api_key", "")
        if not api_url or not api_key:
            return {"status": "error", "message": "Missing api_url or api_key"}
        return {"status": "ok", "message": "Config looks good"}
