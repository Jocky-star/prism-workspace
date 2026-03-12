#!/usr/bin/env python3
"""
daily_digest.py — 每日录音分析，生成星星的理解笔记

用法：
  python3 daily_digest.py           # 分析今天
  python3 daily_digest.py 20260311  # 分析指定日期

输出：memory/daily-digest/YYYY-MM-DD.md
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
DATA_DIR = WORKSPACE / "data" / "daily-reports"
DIGEST_DIR = WORKSPACE / "memory" / "daily-digest"
MODELS_JSON = Path(os.path.expanduser("~/.openclaw/agents/main/agent/models.json"))

DIGEST_DIR.mkdir(parents=True, exist_ok=True)

# ── API 配置 ──────────────────────────────────────────────
def load_api_config():
    """从 models.json 读取 litellm provider 配置"""
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


def call_llm(prompt: str, api: dict, max_tokens: int = 1500) -> str | None:
    """调用 LLM，最多重试 3 次（指数退避）"""
    url = f"{api['base_url']}/chat/completions"
    payload = {
        "model": api["model"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.3,
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
def load_daily_report(date_str: str) -> dict | None:
    """加载 YYYYMMDD.json，返回 content 字段"""
    path = DATA_DIR / f"{date_str}.json"
    if not path.exists():
        print(f"⚠️  找不到文件: {path}", file=sys.stderr)
        return None
    try:
        raw = json.loads(path.read_text())
        if raw.get("count", 0) == 0 or not raw.get("items"):
            print(f"⚠️  {date_str} 无数据", file=sys.stderr)
            return None
        return raw["items"][0]["content"]
    except Exception as e:
        print(f"⚠️  解析 {date_str} 失败: {e}", file=sys.stderr)
        return None


# ── 规则提取（LLM 失败时的兜底）─────────────────────────────
def extract_rule_based(content: dict) -> dict:
    """纯规则提取，不依赖 LLM"""
    outcomes = []
    mood_counts = {}
    activities = {}
    quotes = []
    social = []

    for mf in content.get("macro_frames", []):
        outcomes.extend(mf.get("outcomes", []))
        mood = mf.get("mood_or_tone", "")
        if mood:
            mood_counts[mood] = mood_counts.get(mood, 0) + 1
        act = mf.get("primary_activity", "")
        if act:
            activities[act] = activities.get(act, 0) + 1

    for scene in content.get("scenes", []):
        for q in scene.get("key_quotes", []):
            if q.get("text"):
                quotes.append(q["text"])
        for p in scene.get("participants", []):
            if p != "p1" and p not in social:
                social.append(p)

    dominant_mood = max(mood_counts, key=mood_counts.get) if mood_counts else "neutral"

    return {
        "outcomes": outcomes,
        "mood": dominant_mood,
        "activities": activities,
        "quotes": quotes[:10],
        "social_count": len(social),
    }


def is_overtime(content: dict) -> bool:
    """工作场景结束时间 > 20:00 视为加班"""
    for mf in content.get("macro_frames", []):
        if mf.get("primary_activity") in ("work", "meeting"):
            time_range = mf.get("time_range", [])
            if len(time_range) >= 2:
                try:
                    end_str = time_range[1]
                    end_str = end_str.replace("Z", "+00:00")
                    end_dt = datetime.fromisoformat(end_str)
                    if end_dt.hour >= 20:
                        return True
                except Exception:
                    pass
    return False


# ── LLM 分析 ────────────────────────────────────────────
ANALYSIS_PROMPT = """你是星星，一个了解饭团（黄智勋，男性）的AI助理。
下面是饭团今天的录音数据摘要（场景总结、关键引言、结果）。注意：饭团是男性，用"他"而非"她"。

请帮我整理今天对饭团的理解，用中文，格式如下：

**新想法/灵感**（如果有，逐条列出；没有就写"无"）：
- [内容]

**待办/计划提到的**（如果有；没有就写"无"）：
- [内容]

**情绪判断**（一句话）：
[今天整体情绪和状态]

**值得记住的细节**（最多2条，对理解饭团这个人有价值的信息）：
- [细节]

以下是录音数据：

---
{data_summary}
---

注意：只提取真实存在于数据中的内容，不要编造。"""


def build_data_summary(content: dict) -> str:
    """把 JSON 数据浓缩成 LLM 可读的文本摘要"""
    lines = []

    # 场景摘要
    scenes = content.get("scenes", [])
    if scenes:
        lines.append(f"【场景数量】{len(scenes)} 个")
        for s in scenes[:8]:  # 最多 8 个场景
            summary = s.get("summary", "")
            if summary:
                act = s.get("activity", {}).get("label", "")
                lines.append(f"- [{act}] {summary[:150]}")
            # 关键引言
            for q in s.get("key_quotes", [])[:2]:
                if q.get("text"):
                    lines.append(f"  引言：「{q['text']}」")

    # macro frames outcomes
    outcomes = []
    for mf in content.get("macro_frames", []):
        outcomes.extend(mf.get("outcomes", []))
    if outcomes:
        lines.append(f"\n【今日结果/决策】")
        for o in outcomes:
            lines.append(f"- {o}")

    # key topics
    topics = []
    for mf in content.get("macro_frames", []):
        topics.extend(mf.get("key_topics", []))
    if topics:
        lines.append(f"\n【话题关键词】{', '.join(topics[:10])}")

    return "\n".join(lines) if lines else "今天录音内容较少，无足够信息。"


# ── 组装 Markdown 输出 ───────────────────────────────────
def build_digest_md(date_str: str, content: dict, llm_result: str | None, rule_data: dict) -> str:
    """组装最终的 digest markdown"""
    dt = datetime.strptime(date_str, "%Y%m%d")
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    wday = weekdays[dt.weekday()]
    date_fmt = dt.strftime("%Y-%m-%d")

    # 活动统计
    acts = rule_data.get("activities", {})
    act_str = "、".join(f"{k}×{v}" for k, v in acts.items()) if acts else "无记录"

    # 加班判断
    overtime_flag = "⚠️ 加班" if is_overtime(content) else "正常"

    # 音频时长
    audio_duration = content.get("audio", {}).get("total_duration_sec", 0)
    if audio_duration:
        hrs = int(audio_duration // 3600)
        mins = int((audio_duration % 3600) // 60)
        duration_str = f"{hrs}h{mins:02d}m" if hrs else f"{mins}分钟"
    else:
        duration_str = "无"

    lines = [
        f"# 日记 {date_fmt}（{wday}）",
        f"",
        f"## 今日快照",
        f"- 情绪：{rule_data.get('mood', 'neutral')}",
        f"- 活动：{act_str}",
        f"- 录音时长：{duration_str}",
        f"- 社交互动：{rule_data.get('social_count', 0)} 人",
        f"- 加班状态：{overtime_flag}",
        f"",
        f"## 关键决策 / 结果",
    ]

    outcomes = rule_data.get("outcomes", [])
    if outcomes:
        for o in outcomes:
            lines.append(f"- {o}")
    else:
        lines.append("- （无记录）")

    lines.append("")
    lines.append("## LLM 分析")

    if llm_result:
        lines.append(llm_result)
    else:
        lines.append("（LLM 分析失败，仅保留规则提取结果）")
        quotes = rule_data.get("quotes", [])
        if quotes:
            lines.append("")
            lines.append("**原始引言摘选**：")
            for q in quotes[:5]:
                lines.append(f"- 「{q}」")

    lines.append("")
    lines.append(f"---")
    lines.append(f"*生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}*")

    return "\n".join(lines)


# ── 主流程 ───────────────────────────────────────────────
def run(date_str: str):
    print(f"📖 分析 {date_str}...")

    content = load_daily_report(date_str)
    if content is None:
        print(f"❌ {date_str} 无可用数据，跳过", file=sys.stderr)
        return False

    rule_data = extract_rule_based(content)
    data_summary = build_data_summary(content)

    # 尝试 LLM 分析
    api = load_api_config()
    llm_result = None
    if api:
        prompt = ANALYSIS_PROMPT.format(data_summary=data_summary)
        print("  调用 LLM 分析...")
        llm_result = call_llm(prompt, api)
        if llm_result:
            print("  ✅ LLM 分析完成")
        else:
            print("  ⚠️  LLM 失败，降级为规则输出", file=sys.stderr)
    else:
        print("  ⚠️  无法加载 API 配置，降级为规则输出", file=sys.stderr)

    md = build_digest_md(date_str, content, llm_result, rule_data)

    dt = datetime.strptime(date_str, "%Y%m%d")
    out_path = DIGEST_DIR / f"{dt.strftime('%Y-%m-%d')}.md"
    out_path.write_text(md, encoding="utf-8")
    print(f"  ✅ 已写入 {out_path}")
    return True


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        # 默认分析今天（或昨天，如果今天还没数据）
        today = date.today()
        target = today.strftime("%Y%m%d")
        if not (DATA_DIR / f"{target}.json").exists():
            yesterday = today - timedelta(days=1)
            target = yesterday.strftime("%Y%m%d")
            print(f"今天数据不存在，改为分析昨天 {target}")

    success = run(target)
    sys.exit(0 if success else 1)
