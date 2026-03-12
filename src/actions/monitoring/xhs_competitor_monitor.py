#!/usr/bin/env python3
"""小红书 AI 科技博主竞品监控脚本 — 抓取 AI 热点话题，生成选题建议。

数据源:
  1. 东方财富快讯 API（实时财经新闻，过滤 AI 相关）
  2. DuckDuckGo HTML 搜索（小红书 AI 博主热门趋势，限 1-2 次）
  3. 36kr/少数派等科技媒体公开页面（备选）

用法:
    python3 xhs_competitor_monitor.py            # JSON 输出
    python3 xhs_competitor_monitor.py --human     # 可读格式
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from html import unescape
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import quote

CST = timezone(timedelta(hours=8))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def _http_get(url: str, timeout: int = 15) -> str:
    """通用 HTTP GET，返回文本。"""
    req = Request(url, headers={"User-Agent": UA})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (URLError, HTTPError) as e:
        print(f"⚠️  请求失败 {url[:80]}...: {e}", file=sys.stderr)
        return ""


# ─────────────────────────────────────────────────────────
# 数据源 1: 东方财富快讯
# ─────────────────────────────────────────────────────────
def fetch_eastmoney_news(max_items: int = 50) -> list[dict]:
    """从东方财富快讯 API 获取最新新闻，筛选 AI 相关。"""
    url = f"https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_{max_items}_1_.html"
    raw = _http_get(url)
    if not raw:
        return []

    # 响应格式: var ajaxResult={...}
    match = re.search(r"var ajaxResult\s*=\s*(\{.+\})\s*$", raw, re.DOTALL)
    if not match:
        print("⚠️  无法解析东方财富响应", file=sys.stderr)
        return []

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        print("⚠️  东方财富 JSON 解析失败", file=sys.stderr)
        return []

    ai_keywords = [
        "AI", "人工智能", "大模型", "GPT", "机器人", "自动驾驶",
        "智能", "算力", "芯片", "半导体", "量子", "深度学习",
        "AIGC", "生成式", "具身智能", "人形机器人", "无人机",
        "千问", "DeepSeek", "OpenAI", "Claude", "Gemini",
        "数据中心", "云计算", "6G", "物联网", "智驾",
    ]

    results = []
    for item in data.get("LivesList", []):
        title = unescape(item.get("title", ""))
        digest = unescape(item.get("digest", ""))
        text = title + " " + digest

        matched_kws = [kw for kw in ai_keywords if kw.lower() in text.lower()]
        if not matched_kws:
            continue

        results.append({
            "title": title,
            "digest": digest[:200],
            "url": item.get("url_w", ""),
            "time": item.get("showtime", ""),
            "comments": int(item.get("commentnum", 0)),
            "matched_keywords": matched_kws,
        })

    return results


# ─────────────────────────────────────────────────────────
# 数据源 2: DuckDuckGo 搜索
# ─────────────────────────────────────────────────────────
def search_duckduckgo(query: str) -> list[dict]:
    """DuckDuckGo HTML 搜索，提取结果标题和摘要。"""
    url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
    html = _http_get(url, timeout=20)
    if not html:
        return []

    results = []
    # 提取搜索结果: <a class="result__a" href="...">title</a>
    # <a class="result__snippet" ...>snippet</a>
    title_pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
        re.DOTALL
    )
    snippet_pattern = re.compile(
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        re.DOTALL
    )

    titles = title_pattern.findall(html)
    snippets = snippet_pattern.findall(html)

    for i, (href, raw_title) in enumerate(titles[:10]):
        title = re.sub(r"<[^>]+>", "", raw_title).strip()
        title = unescape(title)
        snippet = ""
        if i < len(snippets):
            snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip()
            snippet = unescape(snippet)

        if title:
            results.append({
                "title": title,
                "snippet": snippet[:200],
                "url": href,
            })

    return results


# ─────────────────────────────────────────────────────────
# 分析与选题建议
# ─────────────────────────────────────────────────────────

# AI 话题到小红书内容角度的映射
TOPIC_ANGLES = {
    "大模型": "测评/对比类：「实测 XX 大模型，结果出乎意料」",
    "AI": "科普/体验类：「AI 能做到这些事了？普通人也能用」",
    "机器人": "趋势解读：「人形机器人离我们还有多远？」",
    "自动驾驶": "体验分享：「坐了一次无人驾驶，说说真实感受」",
    "芯片": "科普类：「一文看懂 AI 芯片为什么这么重要」",
    "智驾": "体验测评：「XX 智驾实测，这个功能太惊艳了」",
    "量子": "前沿科普：「量子计算到底有多厉害？说人话版」",
    "算力": "行业解读：「算力大爆发，普通人能抓住什么机会？」",
    "OpenAI": "热点跟踪：「OpenAI 最新动态，对我们有啥影响」",
    "千问": "国产 AI 体验：「阿里千问 VS ChatGPT，谁更懂中文？」",
    "DeepSeek": "国产 AI 评测：「DeepSeek 深度体验，真的能替代 GPT？」",
    "AIGC": "创作教程：「用 AI 生成内容的 N 种玩法」",
    "具身智能": "前沿科普：「具身智能是什么？为什么大厂都在抢」",
    "无人机": "科技体验：「无人机黑科技盘点」",
    "数据中心": "行业趋势：「数据中心建设潮背后的投资机会」",
    "6G": "前沿科普：「6G 来了！它和 5G 到底差在哪」",
}

DEFAULT_ANGLE = "热点解读：结合时事，用通俗语言讲清楚技术意义"


def generate_suggestions(news: list[dict], ddg_results: list[dict]) -> dict:
    """综合所有数据源，生成今日选题建议。"""
    today = datetime.now(CST).strftime("%Y-%m-%d")

    # ── 从新闻中提取热门话题 ──
    topic_scores: dict[str, dict] = {}

    for item in news:
        for kw in item["matched_keywords"]:
            if kw not in topic_scores:
                topic_scores[kw] = {
                    "topic": kw,
                    "heat_score": 0,
                    "source": "东方财富快讯",
                    "sample_title": item["title"],
                    "content_angle": TOPIC_ANGLES.get(kw, DEFAULT_ANGLE),
                }
            topic_scores[kw]["heat_score"] += 1 + item["comments"] * 0.5

    # 按热度排序
    hot_topics = sorted(topic_scores.values(), key=lambda t: t["heat_score"], reverse=True)

    # ── 从 DDG 结果提取竞品信息 ──
    competitor_highlights = []
    for r in ddg_results[:8]:
        if any(kw in r["title"] + r["snippet"] for kw in ["小红书", "AI", "科技", "博主"]):
            competitor_highlights.append(f"{r['title']} — {r['snippet'][:100]}")

    if not competitor_highlights:
        competitor_highlights = ["暂未抓到竞品动态，建议手动刷一下小红书发现页"]

    # ── 内容建议 ──
    content_suggestions = []

    # 基于热度 Top 话题生成建议
    for t in hot_topics[:5]:
        suggestion = f"围绕「{t['topic']}」做内容 — {t['content_angle']}"
        content_suggestions.append(suggestion)

    # 通用建议
    evergreen = [
        "AI 工具合集类：「2026 年最值得收藏的 AI 工具清单」",
        "个人体验类：「作为科技博主，我每天用 AI 做这 5 件事」",
        "避坑指南：「AI 产品那么多，哪些是智商税？」",
    ]
    # 补充到至少 5 条
    while len(content_suggestions) < 5 and evergreen:
        content_suggestions.append(evergreen.pop(0))

    return {
        "date": today,
        "hot_topics": [
            {
                "topic": t["topic"],
                "heat_score": round(t["heat_score"], 1),
                "source": t["source"],
                "sample_title": t.get("sample_title", ""),
                "content_angle": t["content_angle"],
            }
            for t in hot_topics[:15]
        ],
        "competitor_highlights": competitor_highlights[:10],
        "content_suggestions": content_suggestions[:8],
        "data_sources": {
            "eastmoney_ai_news": len(news),
            "duckduckgo_results": len(ddg_results),
        },
    }


def format_human(result: dict) -> str:
    """格式化为人类可读输出。"""
    lines = []
    lines.append("📱 小红书 AI 科技博主 · 每日选题参考")
    lines.append(f"📅 {result['date']}")
    lines.append("")

    lines.append("🔥 AI 热门话题 (按热度排序):")
    for i, t in enumerate(result["hot_topics"][:10], 1):
        lines.append(f"  {i}. {t['topic']} (热度: {t['heat_score']}) — {t['source']}")
        lines.append(f"     📰 {t.get('sample_title', '')[:60]}")
        lines.append(f"     🎯 {t['content_angle']}")
    lines.append("")

    lines.append("👀 竞品动态:")
    for h in result["competitor_highlights"][:5]:
        lines.append(f"  • {h[:120]}")
    lines.append("")

    lines.append("💡 今日选题建议:")
    for i, s in enumerate(result["content_suggestions"], 1):
        lines.append(f"  {i}. {s}")
    lines.append("")

    ds = result["data_sources"]
    lines.append(f"📊 数据来源: 东方财富 AI 新闻 {ds['eastmoney_ai_news']} 条 | "
                 f"DuckDuckGo 结果 {ds['duckduckgo_results']} 条")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="小红书 AI 科技博主竞品监控")
    parser.add_argument("--human", action="store_true", help="输出可读格式")
    parser.add_argument("--no-ddg", action="store_true", help="跳过 DuckDuckGo 搜索（避免限流）")
    args = parser.parse_args()

    print("📡 正在获取东方财富 AI 新闻...", file=sys.stderr)
    news = fetch_eastmoney_news(max_items=50)
    print(f"  → 找到 {len(news)} 条 AI 相关新闻", file=sys.stderr)

    ddg_results = []
    if not args.no_ddg:
        print("🔍 正在搜索小红书 AI 博主趋势...", file=sys.stderr)
        ddg_results = search_duckduckgo("小红书 AI 科技 博主 热门 2026")
        print(f"  → 找到 {len(ddg_results)} 条搜索结果", file=sys.stderr)

    result = generate_suggestions(news, ddg_results)

    if args.human:
        print(format_human(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
