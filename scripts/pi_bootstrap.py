#!/usr/bin/env python3
"""
pi_bootstrap.py — 智能系统冷启动

用法：
  python3 pi_bootstrap.py              # 全量处理（纯规则）
  python3 pi_bootstrap.py --dry-run    # 只统计，不写入
  python3 pi_bootstrap.py --force      # 强制重跑（忽略已有数据警告）
  python3 pi_bootstrap.py --with-llm   # 全量处理后再跑一次带 LLM 意图分类
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ─── 路径配置 ──────────────────────────────────────────────
BASE = Path(os.path.expanduser("~/.openclaw/workspace"))
SCRIPTS = BASE / "scripts"
INTELLIGENCE = BASE / "memory" / "intelligence"
LOGS = BASE / "logs"

PERCEPTION_SCRIPT = SCRIPTS / "pi_perception.py"
UNDERSTAND_SCRIPT = SCRIPTS / "pi_understand.py"

# intelligence 目录下的关键文件
KEY_FILES = [
    "entities.json",
    "events.jsonl",
    "intents.json",
    "contexts.jsonl",
    "profile.json",
    "relationships.json",
    "patterns.json",
    "insights.jsonl",
]


# ─── 工具函数 ──────────────────────────────────────────────

def _print(msg: str, level: str = "info"):
    icons = {"info": "ℹ️", "ok": "✅", "warn": "⚠️", "error": "❌", "step": "🔹", "done": "🎉"}
    icon = icons.get(level, "•")
    print(f"{icon}  {msg}", flush=True)


def check_existing_data() -> bool:
    """检查 intelligence 目录是否已有数据，返回 True 表示有"""
    INTELLIGENCE.mkdir(parents=True, exist_ok=True)
    existing = [f for f in KEY_FILES if (INTELLIGENCE / f).exists()]
    if existing:
        _print(f"已有数据文件: {', '.join(existing)}", "warn")
        return True
    return False


def count_jsonl_lines(path: Path) -> int:
    """统计 .jsonl 文件的行数"""
    if not path.exists():
        return 0
    count = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                count += 1
    return count


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def run_script(script: Path, args: list[str], dry_run: bool = False) -> tuple[bool, str, str]:
    """
    用 subprocess 运行 Python 脚本，捕获 stdout/stderr。
    返回 (success, stdout, stderr)
    """
    if not script.exists():
        return False, "", f"脚本不存在: {script}"

    cmd = [sys.executable, str(script)] + args
    if dry_run:
        cmd.append("--dry-run")

    _print(f"运行: {' '.join(cmd[2:])}", "step")  # 只打印脚本名和参数

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=600,  # 最多 10 分钟
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "超时（>600s）"
    except Exception as e:
        return False, "", str(e)


def print_output(stdout: str, stderr: str):
    """打印脚本的输出（截断超长内容）"""
    if stdout:
        lines = stdout.strip().splitlines()
        if len(lines) > 30:
            for line in lines[:15]:
                print(f"    {line}")
            print(f"    ... (省略 {len(lines) - 30} 行) ...")
            for line in lines[-15:]:
                print(f"    {line}")
        else:
            for line in lines:
                print(f"    {line}")
    if stderr:
        lines = stderr.strip().splitlines()
        for line in lines[:20]:
            print(f"    [stderr] {line}", file=sys.stderr)


def collect_stats() -> dict:
    """从 intelligence 目录收集统计摘要"""
    stats = {}

    # ─── entities ───
    entities_data = load_json(INTELLIGENCE / "entities.json", {})
    people = entities_data.get("people", {})
    places = entities_data.get("places", {})
    topics = entities_data.get("topics", {})
    stats["entities"] = {
        "people": len(people),
        "places": len(places),
        "topics": len(topics),
    }

    # ─── events ───
    stats["events"] = count_jsonl_lines(INTELLIGENCE / "events.jsonl")

    # ─── intents ───
    intents_data = load_json(INTELLIGENCE / "intents.json", {})
    active = len(intents_data.get("active", []))
    completed = len(intents_data.get("completed", []))
    expired = len(intents_data.get("expired", []))
    stats["intents"] = {
        "total": active + completed + expired,
        "active": active,
        "completed": completed,
        "expired": expired,
    }

    # ─── contexts ───
    stats["contexts"] = count_jsonl_lines(INTELLIGENCE / "contexts.jsonl")

    # ─── profile ───
    profile = load_json(INTELLIGENCE / "profile.json")
    stats["profile"] = "已生成" if profile else "未生成"

    # ─── relationships ───
    rel = load_json(INTELLIGENCE / "relationships.json", {})
    stats["relationships"] = len(rel)

    # ─── patterns ───
    patterns = load_json(INTELLIGENCE / "patterns.json")
    stats["patterns"] = "已生成" if patterns else "未生成"

    # ─── 处理天数 ───
    # 从 events.jsonl 中统计唯一日期数
    events_path = INTELLIGENCE / "events.jsonl"
    dates = set()
    if events_path.exists():
        with open(events_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    if "date" in ev:
                        dates.add(ev["date"])
                except Exception:
                    pass
    stats["days_processed"] = len(dates)

    return stats


def print_summary(stats: dict):
    """打印统计摘要"""
    print()
    print("=" * 50)
    print("📊  冷启动统计摘要")
    print("=" * 50)

    days = stats.get("days_processed", 0)
    print(f"  处理天数:       {days} 天")

    e = stats.get("entities", {})
    print(f"  entities:       {e.get('people', 0)} 人 / {e.get('places', 0)} 地点 / {e.get('topics', 0)} 话题")

    print(f"  events:         {stats.get('events', 0)} 条")

    i = stats.get("intents", {})
    print(f"  intents:        {i.get('total', 0)} 条"
          f"  (active={i.get('active', 0)} / completed={i.get('completed', 0)} / expired={i.get('expired', 0)})")

    print(f"  contexts:       {stats.get('contexts', 0)} 条")
    print(f"  profile:        {stats.get('profile', '未生成')}")
    print(f"  relationships:  {stats.get('relationships', 0)} 个人物")
    print(f"  patterns:       {stats.get('patterns', '未生成')}")
    print("=" * 50)
    print()


def main():
    parser = argparse.ArgumentParser(
        description="pi_bootstrap.py — 个人智能系统冷启动",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写入")
    parser.add_argument("--force", action="store_true", help="强制重跑，忽略已有数据警告")
    parser.add_argument("--with-llm", action="store_true", help="处理完后再跑一次带 LLM 的意图分类")
    parser.add_argument("--no-understand", action="store_true", help="跳过 pi_understand.py（只跑感知层）")
    args = parser.parse_args()

    print()
    _print(f"个人智能系统冷启动  {'[DRY-RUN]' if args.dry_run else ''}", "info")
    _print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "info")
    print()

    # ─── Step 1: 检查已有数据 ───────────────────────────────
    _print("Step 1/4: 检查 intelligence 目录", "step")
    has_data = check_existing_data()
    if has_data and not args.force and not args.dry_run:
        _print("已有数据！使用 --force 覆盖，或 --dry-run 只查看统计", "warn")
        _print("提示: python3 pi_bootstrap.py --force", "info")
        # 直接打印当前统计并退出
        stats = collect_stats()
        print_summary(stats)
        return
    if not has_data:
        _print("intelligence 目录为空，开始全量处理", "ok")
    elif args.dry_run:
        _print("dry-run 模式：只统计现有数据", "info")
        stats = collect_stats()
        print_summary(stats)
        return
    else:
        _print("--force 模式：覆盖现有数据", "warn")

    # ─── Step 2: 感知层（纯规则，不调 LLM）───────────────────
    _print("Step 2/4: 运行 pi_perception.py --all --no-llm", "step")

    if not PERCEPTION_SCRIPT.exists():
        _print(f"pi_perception.py 不存在，跳过感知层 ({PERCEPTION_SCRIPT})", "warn")
        _print("提示: 请先实现 pi_perception.py", "info")
    else:
        perception_args = ["--all", "--no-llm"]
        ok, stdout, stderr = run_script(PERCEPTION_SCRIPT, perception_args, dry_run=args.dry_run)
        print_output(stdout, stderr)
        if ok:
            _print("感知层（纯规则）完成", "ok")
        else:
            _print(f"感知层运行失败，继续后续步骤", "warn")
            if stderr:
                _print(f"错误: {stderr[:200]}", "error")

    # ─── Step 3: 理解层（全量统计）──────────────────────────
    if not args.no_understand:
        _print("Step 3/4: 运行 pi_understand.py", "step")

        if not UNDERSTAND_SCRIPT.exists():
            _print(f"pi_understand.py 不存在，跳过理解层 ({UNDERSTAND_SCRIPT})", "warn")
            _print("提示: 请先实现 pi_understand.py", "info")
        else:
            understand_args = []
            ok, stdout, stderr = run_script(UNDERSTAND_SCRIPT, understand_args, dry_run=args.dry_run)
            print_output(stdout, stderr)
            if ok:
                _print("理解层完成", "ok")
            else:
                _print("理解层运行失败", "warn")
                if stderr:
                    _print(f"错误: {stderr[:200]}", "error")
    else:
        _print("Step 3/4: 跳过理解层（--no-understand）", "step")

    # ─── Step 4: 可选 LLM 意图分类 ──────────────────────────
    if args.with_llm and PERCEPTION_SCRIPT.exists():
        _print("Step 4/4: 运行 pi_perception.py --all（带 LLM 意图分类）", "step")
        perception_args_llm = ["--all"]  # 不加 --no-llm
        ok, stdout, stderr = run_script(PERCEPTION_SCRIPT, perception_args_llm, dry_run=args.dry_run)
        print_output(stdout, stderr)
        if ok:
            _print("感知层（含 LLM 意图分类）完成", "ok")
        else:
            _print("感知层 LLM 运行失败", "warn")
    else:
        _print("Step 4/4: 跳过 LLM 意图分类（使用 --with-llm 启用）", "step")

    # ─── 统计摘要 ────────────────────────────────────────────
    stats = collect_stats()
    print_summary(stats)
    _print("冷启动完成！", "done")


if __name__ == "__main__":
    main()
