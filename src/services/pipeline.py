"""
服务管线 — Service Pipeline
编排数据源 → 生成器 → 输出

三条管线：
  run_daily(date)         — 每日数据收集（建议 23:50 跑）
  run_morning_push(date)  — 晨间推送（建议 08:30 跑）
  run_weekly(date)        — 周度人际洞察（建议周日跑）

运行方式：
  python3 src/services/pipeline.py --date 2026-03-12 --dry-run
  python3 src/services/pipeline.py --date 2026-03-12 --pipeline morning
  python3 src/services/pipeline.py --date 2026-03-12 --pipeline daily
  python3 src/services/pipeline.py --date 2026-03-12 --pipeline weekly
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys as _sys
from pathlib import Path as _Path
_ws = _Path(__file__).resolve()
while _ws.name != "src" and _ws != _ws.parent:
    _ws = _ws.parent
if _ws.name == "src":
    _sys.path.insert(0, str(_ws.parent))

from src.services.config import WORKSPACE, MEMORY_DIR, SERVICES_OUTPUT_DIR
sys.path.insert(0, str(WORKSPACE))

from src.services.data_sources import DataSourceRegistry
from src.services.preferences import ServicePreferences
from src.services.generators.daily_brief import generate_brief, save_brief
from src.services.generators.meeting_insight import generate_meeting_insights, save_insights
from src.services.generators.intent_tracker import generate_intent_tracking, save_result as save_intents
from src.services.generators.emotion_care import generate_emotion_care, save_result as save_care
from src.services.generators.social_insight import generate_social_insight, save_result as save_social

OUTPUT_DIR = SERVICES_OUTPUT_DIR


class PipelineResult:
    def __init__(self, pipeline: str, date: str):
        self.pipeline = pipeline
        self.date = date
        self.started_at = datetime.now().isoformat()
        self.steps: List[Dict[str, Any]] = []
        self.errors: List[str] = []
        self.output_path: Optional[Path] = None

    def add_step(self, name: str, result: Dict, saved_path: Optional[Path] = None) -> None:
        self.steps.append({
            "name": name,
            "success": not result.get("error"),
            "result_keys": list(result.keys()),
            "saved": str(saved_path) if saved_path else None,
        })

    def add_error(self, step: str, error: str) -> None:
        self.errors.append(f"{step}: {error}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pipeline": self.pipeline,
            "date": self.date,
            "started_at": self.started_at,
            "completed_at": datetime.now().isoformat(),
            "steps": self.steps,
            "errors": self.errors,
            "success": len(self.errors) == 0,
        }

    def save_manifest(self) -> Path:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        manifest_path = OUTPUT_DIR / f"{self.date}.json"

        existing: Dict[str, Any] = {}
        if manifest_path.exists():
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                pass

        existing[f"_pipeline_{self.pipeline}"] = self.to_dict()

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

        self.output_path = manifest_path
        return manifest_path


def run_daily(date: str, dry_run: bool = False, prefs: Optional[ServicePreferences] = None) -> PipelineResult:
    """
    每日数据收集管线（建议 23:50 触发）
    - 意图追踪
    - 情绪检测
    - 会议洞察
    """
    if prefs is None:
        prefs = ServicePreferences()

    pipeline = PipelineResult("daily", date)
    print(f"\n🔄 Running DAILY pipeline for {date}")

    # 1. Meeting insight
    if prefs.is_subscribed("meeting_insight"):
        print("  [1/3] Meeting insight...")
        try:
            result = generate_meeting_insights(date, dry_run=dry_run)
            saved = None if dry_run else save_insights(result, date)
            pipeline.add_step("meeting_insight", result, saved)
            print(f"       ✓ {result.get('meeting_count', 0)} meetings")
        except Exception as e:
            pipeline.add_error("meeting_insight", str(e))
            print(f"       ✗ {e}")
    else:
        print("  [1/3] meeting_insight skipped (disabled)")

    # 2. Intent tracking
    if prefs.is_subscribed("intent_tracker"):
        print("  [2/3] Intent tracker...")
        try:
            result = generate_intent_tracking(date, dry_run=dry_run)
            saved = None if dry_run else save_intents(result, date)
            pipeline.add_step("intent_tracker", result, saved)
            print(f"       ✓ {result.get('intent_count', 0)} intents")
        except Exception as e:
            pipeline.add_error("intent_tracker", str(e))
            print(f"       ✗ {e}")
    else:
        print("  [2/3] intent_tracker skipped (disabled)")

    # 3. Emotion care
    if prefs.is_subscribed("emotion_care"):
        print("  [3/3] Emotion care...")
        try:
            sensitivity = prefs.get_service("emotion_care").get("sensitivity", "normal")
            result = generate_emotion_care(date, sensitivity=sensitivity, dry_run=dry_run)
            saved = None if dry_run else save_care(result, date)
            pipeline.add_step("emotion_care", result, saved)
            triggered = result.get("triggered", False)
            print(f"       ✓ triggered={triggered}, score={result.get('signal_score',0)}")
        except Exception as e:
            pipeline.add_error("emotion_care", str(e))
            print(f"       ✗ {e}")
    else:
        print("  [3/3] emotion_care skipped (disabled)")

    manifest_path = pipeline.save_manifest() if not dry_run else None
    if not dry_run:
        print(f"\n  📁 Manifest saved: {manifest_path}")
    return pipeline


def run_morning_push(date: str, dry_run: bool = False, prefs: Optional[ServicePreferences] = None) -> PipelineResult:
    """
    晨间推送管线（建议 08:30 触发）
    - 加载昨天的处理结果
    - 生成晨间简报
    - （可扩展）发送到 Feishu
    """
    if prefs is None:
        prefs = ServicePreferences()

    # Brief uses previous day's data
    yesterday = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    pipeline = PipelineResult("morning", date)
    print(f"\n🌅 Running MORNING PUSH pipeline for {date} (data: {yesterday})")

    if prefs.is_quiet_now():
        print("  ⏸ Quiet hours — skipping push")
        pipeline.add_error("morning_push", "quiet_hours")
        return pipeline

    # 1. Daily brief
    if prefs.is_subscribed("daily_brief"):
        print("  [1/1] Daily brief...")
        try:
            result = generate_brief(yesterday, dry_run=dry_run)
            saved = None if dry_run else save_brief(result, date)
            pipeline.add_step("daily_brief", result, saved)
            brief = result.get("brief", {})
            print(f"       ✓ greeting: {brief.get('greeting','')[:50]}...")
        except Exception as e:
            pipeline.add_error("daily_brief", str(e))
            print(f"       ✗ {e}")
    else:
        print("  [1/1] daily_brief skipped (disabled)")

    manifest_path = pipeline.save_manifest() if not dry_run else None
    if not dry_run:
        print(f"\n  📁 Manifest saved: {manifest_path}")
    return pipeline


def run_weekly(date: str, dry_run: bool = False, prefs: Optional[ServicePreferences] = None) -> PipelineResult:
    """
    周度管线（建议周日跑）
    - 社交/人际洞察
    """
    if prefs is None:
        prefs = ServicePreferences()

    pipeline = PipelineResult("weekly", date)
    print(f"\n📅 Running WEEKLY pipeline for week ending {date}")

    # 1. Social insight
    if prefs.is_subscribed("social_insight"):
        print("  [1/1] Social insight...")
        try:
            result = generate_social_insight(date, dry_run=dry_run)
            saved = None if dry_run else save_social(result, date)
            pipeline.add_step("social_insight", result, saved)
            insight = result.get("insight", {})
            print(f"       ✓ events_analyzed={result.get('events_analyzed',0)}")
            print(f"       summary: {insight.get('week_summary','')[:80]}")
        except Exception as e:
            pipeline.add_error("social_insight", str(e))
            print(f"       ✗ {e}")
    else:
        print("  [1/1] social_insight skipped (disabled)")

    manifest_path = pipeline.save_manifest() if not dry_run else None
    if not dry_run:
        print(f"\n  📁 Manifest saved: {manifest_path}")
    return pipeline


def run_all(date: str, dry_run: bool = False) -> Dict[str, PipelineResult]:
    """Run all pipelines for the given date."""
    prefs = ServicePreferences()
    return {
        "daily": run_daily(date, dry_run=dry_run, prefs=prefs),
        "morning": run_morning_push(date, dry_run=dry_run, prefs=prefs),
        "weekly": run_weekly(date, dry_run=dry_run, prefs=prefs),
    }


if __name__ == "__main__":
    import logging as _logging
    _log_dir = WORKSPACE / "logs"
    _log_dir.mkdir(parents=True, exist_ok=True)
    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            _logging.FileHandler(_log_dir / "pipeline.log", encoding="utf-8"),
            _logging.StreamHandler(sys.stderr),
        ],
    )
    _log = _logging.getLogger("pipeline")

    parser = argparse.ArgumentParser(description="Service pipeline orchestrator")
    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Date to process (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--pipeline",
        choices=["daily", "morning", "weekly", "all"],
        default="all",
        help="Which pipeline to run",
    )
    parser.add_argument("--dry-run", action="store_true", help="Don't call LLM or save files")
    parser.add_argument(
        "--check-prefs",
        action="store_true",
        help="Show current preferences and exit",
    )
    args = parser.parse_args()

    if args.check_prefs:
        prefs = ServicePreferences()
        print(prefs.generate_menu())
        sys.exit(0)

    try:
        prefs = ServicePreferences()

        # First-run onboarding check
        if prefs.is_first_run() and not args.dry_run:
            print("\n" + "="*50)
            print("FIRST RUN — Showing onboarding menu")
            print("="*50)
            print(prefs.generate_onboarding_message())
            prefs.mark_onboarded()
            print("\n(Proceeding with default settings — all enabled)")
            print("="*50 + "\n")

        results: Dict[str, PipelineResult] = {}

        if args.pipeline == "all":
            results = run_all(args.date, dry_run=args.dry_run)
        elif args.pipeline == "daily":
            results["daily"] = run_daily(args.date, dry_run=args.dry_run, prefs=prefs)
        elif args.pipeline == "morning":
            results["morning"] = run_morning_push(args.date, dry_run=args.dry_run, prefs=prefs)
        elif args.pipeline == "weekly":
            results["weekly"] = run_weekly(args.date, dry_run=args.dry_run, prefs=prefs)

        # Summary
        print("\n" + "="*50)
        print("PIPELINE SUMMARY")
        print("="*50)
        has_errors = False
        for name, p in results.items():
            d = p.to_dict()
            status = "✅" if d["success"] else "⚠️"
            print(f"{status} {name}: {len(d['steps'])} steps, {len(d['errors'])} errors")
            for err in d.get("errors", []):
                print(f"     ✗ {err}")
                _log.warning(f"Pipeline step error [{name}]: {err}")
            if not d["success"]:
                has_errors = True
        print("="*50)

        # ── 写入 action_log ───────────────────────────────────
        try:
            from src.services.action_log import log_action as _log_action
            _pipeline_names = list(results.keys())
            _success_count = sum(1 for p in results.values() if p.to_dict()["success"])
            _log_action(
                "pipeline",
                f"服务管线执行完成",
                f"管线: {', '.join(_pipeline_names)}，成功 {_success_count}/{len(results)} 条",
                source="pipeline",
            )
        except Exception as _e:
            _log.warning(f"action_log 写入失败: {_e}")
        # ─────────────────────────────────────────────────────

        sys.exit(1 if has_errors else 0)

    except Exception as e:
        _log.error(f"Pipeline fatal error: {e}", exc_info=True)
        print(f"❌ Pipeline fatal error: {e}", file=sys.stderr)
        sys.exit(1)
