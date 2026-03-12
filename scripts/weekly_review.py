#!/usr/bin/env python3
"""
weekly_review.py — 每周行为回顾，生成简短关怀消息

用法：
  python3 weekly_review.py           # 回顾过去7天
  python3 weekly_review.py --dry-run # 只打印，不存档

输出：stdout（消息文本），供 cron 发送给饭团
存档：memory/weekly-reviews/YYYY-WXX.md
"""

import json
import sys
import time
import os
from datetime import datetime, date, timedelta
from pathlib import Path
import urllib.request
import urllib.error

# ── 路径配置 ──────────────────────────────────────────────
WORKSPACE = Path(os.path.expanduser("~/.openclaw/workspace"))
DIGEST_DIR = WORKSPACE / "memory" / "daily-digest"
HABITS_DIR = WORKSPACE / "memory" / "habits"
REVIEWS_DIR = WORKSPACE / "memory" / "weekly-reviews"
MODELS_JSON = Path(os.path.expanduser("~/.openclaw/agents/main/agent/models.json"))

REVIEWS_DIR.mkdir(parents=True, exist_ok=True)


# ── API 配置 ──────────────────────────────────────────────
def load_api_config():
    try:
        cfg = json.loads(MODELS_JSON.read_text())
        lm = cfg["providers"]["litellm"]
        return {
            "base_url": lm["baseUrl"],
            "api_key": lm["apiKey"],
            "headers": lm.get("headers", {}),
            "model": "pa/claude-haiku-4-5-20251001",
        }
    except Exception as e:
        print(f"⚠️  读取 models.json 失败: {e}", file=sys.stderr)
        return None


def call_llm(prompt: str, api: dict, max_tokens: int = 300) -> str | None:
    url = f"{api['base_url']}/chat/completions"
    payload = {
        "model": api["model"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.5,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api['api_key']}",
        **api.get("headers", {}),
    }
    data = json.dumps(payload).encode("utf-8")

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:200]
            print(f"  LLM HTTP错误 {e.code} (尝试{attempt+1}/3): {body}", file=sys.stderr)
            if e.code in (429, 503):
                time.sleep(2 ** attempt * 5)
            else:
                break
        except Exception as e:
            print(f"  LLM调用失败 (尝试{attempt+1}/3): {e}", file=sys.stderr)
            time.sleep(2 ** attempt * 3)
    return None


# ── 数据加载 ──────────────────────────────────────────────
def load_digests(days: int = 7) -> list[dict]:
    """加载过去 N 天的 daily-digest"""
    results = []
    today = date.today()
    for i in range(1, days + 1):
        d = today - timedelta(days=i)
        path = DIGEST_DIR / f"{d.strftime('%Y-%m-%d')}.md"
        if path.exists():
            results.append({
                "date": d,
                "date_str": d.strftime("%Y-%m-%d"),
                "content": path.read_text(encoding="utf-8"),
            })
    return results


def load_habits_observations(days: int = 7) -> list[dict]:
    """加载 habit-predictor 观察数据"""
    observations = []
    patterns_file = HABITS_DIR / "patterns.jsonl"
    if not patterns_file.exists():
        return observations

    today = date.today()
    cutoff = today - timedelta(days=days)
    try:
        for line in patterns_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                ts = obj.get("timestamp", "")
                if ts:
                    obs_date = datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
                    if obs_date >= cutoff:
                        observations.append(obj)
            except Exception:
                pass
    except Exception as e:
        print(f"⚠️  读取 habits patterns 失败: {e}", file=sys.stderr)
    return observations


# ── 规则统计 ──────────────────────────────────────────────
def parse_digest_stats(digests: list[dict]) -> dict:
    """从 digest 内容中提取关键统计"""
    stats = {
        "days_count": len(digests),
        "overtime_days": 0,
        "mood_counts": {},
        "exercise_days": 0,
        "dates": [],
    }

    for d in digests:
        stats["dates"].append(d["date_str"])
        content = d["content"]

        # 加班
        if "⚠️ 加班" in content:
            stats["overtime_days"] += 1

        # 情绪
        for mood in ["stressed", "tired", "negative", "focused", "positive", "neutral"]:
            if mood in content:
                stats["mood_counts"][mood] = stats["mood_counts"].get(mood, 0) + 1
                break

        # 运动（从活动标签中检测）
        if "exercise" in content or "运动" in content or "健身" in content:
            stats["exercise_days"] += 1

    return stats


def compare_weeks(this_week: dict, last_week: dict) -> list[str]:
    """对比两周变化，返回显著差异列表"""
    changes = []

    ot_diff = this_week["overtime_days"] - last_week.get("overtime_days", 0)
    if ot_diff > 0:
        changes.append(f"加班 {this_week['overtime_days']} 天，比上周多 {ot_diff} 天")
    elif ot_diff < 0:
        changes.append(f"加班 {this_week['overtime_days']} 天，比上周少 {abs(ot_diff)} 天")

    ex_diff = this_week["exercise_days"] - last_week.get("exercise_days", 0)
    if ex_diff < -1:
        changes.append(f"运动只有 {this_week['exercise_days']} 次，比上周少了")
    elif ex_diff > 1:
        changes.append(f"运动 {this_week['exercise_days']} 次，比上周多！")
    elif this_week["exercise_days"] == 0:
        changes.append("这周没有运动记录")

    # 情绪倾向
    negative_moods = sum(this_week["mood_counts"].get(m, 0) for m in ["stressed", "tired", "negative"])
    if negative_moods >= 3:
        changes.append(f"情绪偏疲惫，连续 {negative_moods} 天状态不太好")

    return changes


# ── LLM 生成消息 ─────────────────────────────────────────
REVIEW_PROMPT = """你是星星，饭团（黄智勋）的AI助理。性格轻松随意，说话像朋友。

本周（{date_range}）行为数据摘要：
{stats_summary}

请生成一条发给饭团的**简短关怀消息**，要求：
1. 最多 2 句话
2. 提 1-2 个最显著的变化（加班、运动、情绪）
3. 结尾带一句关心（"你还好吗？"、"注意休息"、"这周辛苦了"等）
4. 语气要像朋友，不像报告
5. 直接输出消息文本，不要加引号或前缀

示例风格："这周加班了 4 天比上周多 1 天，运动也少了——你还好吗？"
"""


def build_stats_summary(stats: dict, changes: list[str]) -> str:
    lines = [
        f"有数据的天数：{stats['days_count']} 天",
        f"加班天数：{stats['overtime_days']} 天",
        f"有运动记录：{stats['exercise_days']} 天",
    ]
    if changes:
        lines.append(f"对比上周变化：{'; '.join(changes)}")
    return "\n".join(lines)


def generate_fallback_message(stats: dict, changes: list[str]) -> str:
    """LLM 失败时的规则兜底消息"""
    if not changes:
        return f"这周数据看完了，整体还不错，继续保持～"

    parts = changes[:2]
    msg = "、".join(parts) + "。"

    stress_days = stats["mood_counts"].get("stressed", 0) + stats["mood_counts"].get("tired", 0)
    if stats["overtime_days"] >= 4 or stress_days >= 3:
        msg += "注意休息，别太累了。"
    else:
        msg += "你还好吗？"

    return msg


# ── 主流程 ───────────────────────────────────────────────
def run(dry_run: bool = False) -> str:
    today = date.today()
    iso_week = today.isocalendar()
    week_label = f"{iso_week[0]}-W{iso_week[1]:02d}"

    print(f"📊 生成每周回顾 {week_label}...", file=sys.stderr)

    # 本周数据
    this_digests = load_digests(7)
    last_digests = load_digests(14)[7:]  # 上上周

    if not this_digests:
        msg = "这周的录音数据还没分析，先跳过周回顾～"
        print(msg)
        return msg

    this_stats = parse_digest_stats(this_digests)
    last_stats = parse_digest_stats(last_digests) if last_digests else {}

    changes = compare_weeks(this_stats, last_stats)
    stats_summary = build_stats_summary(this_stats, changes)

    print(f"  统计：{stats_summary}", file=sys.stderr)

    # 日期范围
    dates = sorted(d["date_str"] for d in this_digests)
    date_range = f"{dates[0]} ~ {dates[-1]}" if dates else "本周"

    # LLM 生成消息
    api = load_api_config()
    message = None
    if api:
        prompt = REVIEW_PROMPT.format(date_range=date_range, stats_summary=stats_summary)
        message = call_llm(prompt, api, max_tokens=200)

    if not message:
        message = generate_fallback_message(this_stats, changes)
        print(f"  ⚠️  LLM 失败，使用规则生成", file=sys.stderr)

    print(f"  消息：{message}", file=sys.stderr)

    # 存档
    if not dry_run:
        archive_path = REVIEWS_DIR / f"{week_label}.md"
        archive_content = f"""# 周回顾 {week_label}

## 发给饭团的消息
{message}

## 数据摘要
{stats_summary}

## 对比变化
{chr(10).join('- ' + c for c in changes) if changes else '- 无显著变化'}

---
*生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}*
"""
        archive_path.write_text(archive_content, encoding="utf-8")
        print(f"  ✅ 存档到 {archive_path}", file=sys.stderr)

    # 输出到 stdout（供 cron 发送）
    print(message)
    return message


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    run(dry_run=dry_run)
