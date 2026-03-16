#!/usr/bin/env python3
"""
idea_capture.py — 从 daily-report 数据中捕捉饭团的灵感和创意

用法：
  python3 idea_capture.py                # 扫描今天
  python3 idea_capture.py 20260129       # 扫描指定日期
  python3 idea_capture.py --all          # 扫描所有历史数据

输出：追加到 memory/idea-capture.md
"""

import json
import sys
import os
import time
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
import urllib.request
import urllib.error

WORKSPACE = Path(os.path.expanduser("~/.openclaw/workspace"))
DATA_DIR = WORKSPACE / "data" / "daily-reports"
CAPTURE_FILE = WORKSPACE / "memory" / "idea-capture.md"
MODELS_JSON = Path(os.path.expanduser("~/.openclaw/agents/main/agent/models.json"))

TZ = timezone(timedelta(hours=8))


def load_api_config():
    """从 models.json 读取 litellm provider 配置"""
    try:
        config = json.loads(MODELS_JSON.read_text())
        providers = config.get("providers", {})
        p = providers.get("litellm", {}) if isinstance(providers, dict) else {}
        if not p:
            for item in (providers if isinstance(providers, list) else []):
                if isinstance(item, dict) and item.get("id") == "litellm":
                    p = item
                    break
        if p:
            return {
                "base_url": p.get("baseUrl", "http://model.mify.ai.srv/v1"),
                "api_key": p.get("apiKey", ""),
                "headers": p.get("headers", {}),
                "model": "pa/claude-haiku-4-5-20251001",
            }
    except Exception:
        pass
    return {"base_url": "http://model.mify.ai.srv/v1", "api_key": "", "headers": {}, "model": "pa/claude-haiku-4-5-20251001"}


def call_llm(prompt: str, api: dict, max_tokens: int = 800) -> str | None:
    """调用 LLM 过滤想法"""
    headers = {"Content-Type": "application/json"}
    if api["api_key"]:
        headers["Authorization"] = f"Bearer {api['api_key']}"
    headers.update(api.get("headers", {}))

    body = json.dumps({
        "model": api["model"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }).encode()

    req = urllib.request.Request(f"{api['base_url']}/chat/completions", data=body, headers=headers)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                print(f"  LLM 调用失败: {e}", file=sys.stderr)
    return None


def load_daily_report(date_str: str) -> dict | None:
    """加载 YYYYMMDD.json"""
    f = DATA_DIR / f"{date_str}.json"
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text())
        if data.get("count", 0) > 0:
            return data["items"][0]["content"]
    except Exception:
        pass
    return None


def extract_quotes(content: dict) -> list[dict]:
    """提取饭团的所有发言"""
    quotes = []
    for s in content.get("scenes", []):
        context = s.get("summary", "")[:200]
        for q in s.get("key_quotes", []):
            speaker = q.get("speaker", "")
            text = q.get("text", "")
            if speaker in ("p1", "SPEAKER_00") and len(text) > 15:
                quotes.append({"text": text, "context": context})
    return quotes


FILTER_PROMPT = """从以下发言中，找出属于"想法/灵感/创意/产品构想/技术方案构思"的条目。
只保留创造性的、前瞻性的想法，排除纯工作指令、日常闲聊、bug讨论。

发言列表：
{quotes_text}

请逐条判断。对于是"想法/灵感"的条目，输出如下格式（每条一行）：
IDEA: [原文摘要（30字以内）] | [简要说明这个想法是什么]

如果没有任何想法类发言，输出：NONE

注意：只保留真正有创造性的想法，不要把普通工作讨论也算进去。"""


def load_existing_ideas() -> set:
    """加载已有的想法避免重复"""
    if not CAPTURE_FILE.exists():
        return set()
    content = CAPTURE_FILE.read_text(encoding="utf-8")
    ideas = set()
    for line in content.split("\n"):
        if line.startswith("- **"):
            # 提取关键词做去重
            ideas.add(line[:80])
    return ideas


def run(date_str: str):
    """处理单天数据"""
    content = load_daily_report(date_str)
    if not content:
        print(f"  {date_str}: 无数据", file=sys.stderr)
        return []

    quotes = extract_quotes(content)
    if not quotes:
        print(f"  {date_str}: 无发言", file=sys.stderr)
        return []

    # 组装发言文本
    quotes_text = ""
    for i, q in enumerate(quotes):
        quotes_text += f"[{i+1}] 「{q['text']}」\n    背景：{q['context']}\n\n"

    api = load_api_config()
    prompt = FILTER_PROMPT.format(quotes_text=quotes_text)
    result = call_llm(prompt, api)

    if not result or "NONE" in result:
        print(f"  {date_str}: 无新想法", file=sys.stderr)
        return []

    # 解析 LLM 输出
    ideas = []
    d = content.get("date", date_str)
    formatted_date = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d

    for line in result.split("\n"):
        line = line.strip()
        if line.startswith("IDEA:"):
            idea_text = line[5:].strip()
            ideas.append(f"- **[{formatted_date}]** {idea_text}")

    print(f"  {date_str}: 发现 {len(ideas)} 个想法")
    return ideas


def append_ideas(ideas: list[str]):
    """追加到 idea-capture.md"""
    existing = load_existing_ideas()
    new_ideas = [i for i in ideas if i[:80] not in existing]

    if not new_ideas:
        print("  无新增想法（已存在）")
        return

    CAPTURE_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not CAPTURE_FILE.exists():
        CAPTURE_FILE.write_text("# 饭团的想法捕捉\n\n> 自动从录音数据中提取的灵感和创意\n\n", encoding="utf-8")

    with open(CAPTURE_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(new_ideas) + "\n")

    print(f"  ✅ 新增 {len(new_ideas)} 条到 {CAPTURE_FILE}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--all":
        # 扫描所有历史数据
        all_ideas = []
        for f in sorted(DATA_DIR.glob("*.json")):
            date_str = f.stem
            ideas = run(date_str)
            all_ideas.extend(ideas)
        if all_ideas:
            append_ideas(all_ideas)
        else:
            print("所有数据中未发现新想法")
    else:
        # 单天
        if len(sys.argv) > 1:
            date_str = sys.argv[1]
        else:
            date_str = datetime.now(TZ).strftime("%Y%m%d")
        ideas = run(date_str)
        if ideas:
            append_ideas(ideas)


if __name__ == "__main__":
    main()
