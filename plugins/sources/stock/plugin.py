"""
stock 数据源插件 — 薄包装 src/sources/stock/
"""
import sys
from pathlib import Path
from typing import Any, Dict, List

_WORKSPACE = Path(__file__).resolve().parents[3]
if str(_WORKSPACE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE))

from prism.plugin_base import SourcePlugin


class StockSourcePlugin(SourcePlugin):
    name = "stock"
    version = "1.0.0"

    def setup(self, config: dict) -> bool:
        watchlist = config.get("watchlist", [])
        if not watchlist:
            print("  ⚠️  stock: watchlist 为空，请配置自选股代码列表")
            return False
        return True

    def fetch(self, date: str) -> List[Dict[str, Any]]:
        """拉取指定日期的股票行情数据"""
        watchlist = self.config.get("watchlist", [])
        try:
            from src.sources.stock.news_monitor import fetch_stock_data
            data = fetch_stock_data(date, watchlist=watchlist)
            return [data] if data else []
        except ImportError:
            return self._fetch_direct(date, watchlist)
        except Exception as e:
            return [{"date": date, "available": False, "error": str(e)}]

    def _fetch_direct(self, date: str, watchlist: list) -> List[Dict[str, Any]]:
        """尝试直接调用 stock 模块中可用的函数"""
        stock_dir = _WORKSPACE / "src" / "sources" / "stock"
        results = []
        for py_file in stock_dir.glob("*.py"):
            if py_file.stem.startswith("_"):
                continue
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location(f"stock_{py_file.stem}", py_file)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                for fn_name in ("fetch_stock_data", "get_quotes", "get_today_data"):
                    fn = getattr(mod, fn_name, None)
                    if fn:
                        data = fn(date) if fn_name == "get_today_data" else fn(date, watchlist=watchlist)
                        if data:
                            results.append(data)
                        break
            except Exception:
                pass
        return results or [{"date": date, "available": False, "error": "stock module unavailable"}]

    def health_check(self) -> dict:
        watchlist = self.config.get("watchlist", [])
        if not watchlist:
            return {"status": "error", "message": "watchlist is empty"}
        try:
            import akshare
            return {"status": "ok", "message": f"akshare available, {len(watchlist)} stocks configured"}
        except ImportError:
            return {"status": "error", "message": "akshare not installed (pip install akshare)"}
