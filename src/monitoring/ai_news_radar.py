#!/usr/bin/env python3
"""
ai_news_radar.py - AI 新闻雷达 v2
多源采集 + 24h新鲜度过滤 + 全局去重 + 模式评分
"""

import json
import os
import sys
import re
import hashlib
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

DATA_DIR = os.path.expanduser("~/.openclaw/workspace/data/ai_news")
SEEN_FILE = os.path.join(DATA_DIR, "seen_urls.json")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
NOW = datetime.now(timezone.utc)
CUTOFF = NOW - timedelta(hours=25)  # 25h window — daily run with overlap

AI_KEYWORDS = [
    r"(?<![a-z])ai(?![a-z])", r"artificial intelligence", r"\bllm\b", r"\bgpt[-\s]?\d*\b",
    r"\bclaude\b", r"\bgemini\b", r"\bopenai\b", r"\banthropic\b", r"\bdeepmind\b",
    "机器学习", "深度学习", "大模型", "人工智能",
    r"\btransformer\b", r"\bchatbot\b", r"\bcopilot\b", r"\bmidjourney\b",
    r"\bstable diffusion\b", r"(?<![a-z])agent(?:s|ic)?(?![a-z])", r"\brag\b", r"fine.tun",
    r"\bneural\b", r"\bmachine learning\b", r"\bdiffusion model",
    r"\breasoning\b", r"\bmultimodal\b", r"\bvision model", r"\bfoundation model",
    r"(?<![a-z])ai safety", r"\balignment\b", r"\breinforcement learning\b",
    "生成式", "智能体",
]

# --- Scoring patterns (additive, cap at 10) ---
SCORE_PATTERNS = [
    # (regex, points, description)
    (r"(?:launch|release|发布|推出|上线)\w{0,10}(?:model|版本|模型)", 5, "new model launch"),
    (r"open.?sourc|开源", 3, "open source"),
    (r"acqui(?:re|sition)|收购|并购", 4, "acquisition"),
    (r"\$\d+\s*[bmBM]|billion|融资|估值", 4, "big money"),
    (r"regulat|监管|policy|法规|ban(?:ned|s)?", 2, "regulation"),
    (r"(?:CEO|CTO|founder|创始人|首席)\s", 3, "exec news"),
    (r"breakthrough|突破|first.ever|史上首次", 4, "breakthrough"),
    (r"shutdown|关停|layoff|裁员", 3, "shutdown/layoff"),
    (r"safety|alignment|安全|对齐", 2, "safety"),
    (r"partner|合作|collaborat", 2, "partnership"),
]


def fetch(url, timeout=12):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [WARN] fetch failed: {url} — {e}", file=sys.stderr)
        return None


def url_hash(url):
    return hashlib.md5(url.encode()).hexdigest()[:12]


def is_ai_related(text, strict=False):
    """Check if text is AI-related. strict=True requires stronger signal (for noisy sources)."""
    t = text.lower()
    if strict:
        strong_kw = [
            r"(?<![a-z])ai(?![a-z])", r"\bllm\b", r"\bgpt[-\s]?\d*\b", r"\bclaude\b", r"\bgemini\b",
            r"\bopenai\b", r"\banthropic\b", r"\bdeepmind\b",
            "大模型", "人工智能", r"\bchatbot\b", r"\bcopilot\b", r"\bmidjourney\b",
            r"\bstable diffusion\b", r"(?<![a-z])agent(?:s|ic)?(?![a-z])", r"\btransformer\b",
            "机器学习", "深度学习", "生成式", "智能体",
            r"\bfoundation model", r"\bvision model", r"\bmultimodal\b",
        ]
        return any(re.search(kw, t) for kw in strong_kw)
    return any(re.search(kw, t) for kw in AI_KEYWORDS)


def parse_time(s):
    """Try to parse various date formats to UTC datetime."""
    if not s:
        return None
    s = s.strip()
    # RFC 2822 (RSS pubDate)
    try:
        return parsedate_to_datetime(s)
    except Exception:
        pass
    # ISO 8601 variants
    for fmt in ["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def is_fresh(pub_str):
    """Return True if article is within CUTOFF or time can't be parsed."""
    dt = parse_time(pub_str)
    if dt is None:
        return True  # conservative: keep if can't parse
    return dt >= CUTOFF


def calc_score(title, summary="", hn_points=0):
    text = (title + " " + summary).lower()
    score = 3
    for pattern, pts, _ in SCORE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            score += pts
    if hn_points >= 300:
        score += 4
    elif hn_points >= 100:
        score += 2
    return min(score, 10)


# --- Load/save global seen URLs ---
def load_seen():
    if not os.path.exists(SEEN_FILE):
        return {}
    try:
        with open(SEEN_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_seen(seen):
    os.makedirs(DATA_DIR, exist_ok=True)
    # Clean entries older than 7 days
    cutoff_str = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    cleaned = {k: v for k, v in seen.items() if v >= cutoff_str}
    with open(SEEN_FILE, "w") as f:
        json.dump(cleaned, f)


def mark_seen(seen, url):
    seen[url_hash(url)] = datetime.now().strftime("%Y-%m-%d")


def is_seen(seen, url):
    return url_hash(url) in seen


# --- Fetchers ---
def fetch_hn(limit=50):
    results = []
    data = fetch("https://hacker-news.firebaseio.com/v0/topstories.json")
    if not data:
        return results
    ids = json.loads(data)[:limit]
    for sid in ids:
        item_data = fetch(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
        if not item_data:
            continue
        obj = json.loads(item_data)
        title = obj.get("title", "")
        ts = obj.get("time", 0)
        pub = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else ""
        if not is_ai_related(title):
            continue
        if not is_fresh(pub):
            continue
        url = obj.get("url", f"https://news.ycombinator.com/item?id={sid}")
        points = obj.get("score", 0)
        results.append({
            "title": title, "source": "HackerNews", "url": url,
            "summary": "", "published_at": pub,
            "importance_score": calc_score(title, "", points),
        })
    return results


def fetch_rss(url, source_name, strict_filter=False):
    results = []
    data = fetch(url)
    if not data:
        return results
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return results

    ns = {"atom": "http://www.w3.org/2005/Atom"}

    # RSS 2.0
    for item in root.findall(".//item")[:50]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = item.findtext("description") or ""
        pub = item.findtext("pubDate") or ""
        if not is_fresh(pub):
            continue
        filter_text = title if strict_filter else (title + " " + desc)
        if not is_ai_related(filter_text, strict=strict_filter):
            continue
        score_text = "" if strict_filter else desc[:500]
        results.append({
            "title": title, "source": source_name, "url": link,
            "summary": re.sub(r"<[^>]+>", "", desc)[:200].strip(),
            "published_at": pub,
            "importance_score": calc_score(title, score_text),
        })

    # Atom
    for entry in root.findall(".//atom:entry", ns)[:50]:
        title = (entry.findtext("atom:title", "", ns) or "").strip()
        link_el = entry.find("atom:link", ns)
        link = link_el.get("href", "") if link_el is not None else ""
        summary = entry.findtext("atom:summary", "", ns) or entry.findtext("atom:content", "", ns) or ""
        pub = entry.findtext("atom:published", "", ns) or entry.findtext("atom:updated", "", ns) or ""
        if not is_fresh(pub):
            continue
        atom_filter_text = title if strict_filter else (title + " " + summary)
        if not is_ai_related(atom_filter_text, strict=strict_filter):
            continue
        results.append({
            "title": title, "source": source_name, "url": link.strip(),
            "summary": re.sub(r"<[^>]+>", "", summary)[:200].strip(),
            "published_at": pub,
            "importance_score": calc_score(title, "" if strict_filter else summary[:500]),
        })

    return results


RSS_SOURCES = [
    ("https://techcrunch.com/category/artificial-intelligence/feed/", "TechCrunch", False),
    ("https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "TheVerge", False),
    ("https://feeds.arstechnica.com/arstechnica/index", "ArsTechnica", False),
    ("https://www.technologyreview.com/feed/", "MIT-TechReview", False),
    ("https://openai.com/blog/rss.xml", "OpenAI-Blog", False),
    ("https://blog.google/technology/ai/rss/", "Google-AI", False),
    ("https://36kr.com/feed", "36kr", True),  # strict: title-only AI filter
]


def collect_all():
    seen = load_seen()
    all_news = []

    # HN
    try:
        hn = fetch_hn(100)
        all_news.extend(hn)
        print(f"  [OK] HN: {len(hn)} items", file=sys.stderr)
    except Exception as e:
        print(f"  [ERR] HN: {e}", file=sys.stderr)

    # RSS sources
    for rss_url, name, strict in RSS_SOURCES:
        try:
            items = fetch_rss(rss_url, name, strict_filter=strict)
            all_news.extend(items)
            print(f"  [OK] {name}: {len(items)} items", file=sys.stderr)
        except Exception as e:
            print(f"  [ERR] {name}: {e}", file=sys.stderr)

    # Dedupe by URL
    url_seen_local = set()
    unique = []
    for n in all_news:
        url = n.get("url", "")
        if not url or url in url_seen_local:
            continue
        url_seen_local.add(url)
        unique.append(n)

    # Filter out globally seen
    new_items = [n for n in unique if not is_seen(seen, n["url"])]

    # Mark all as seen
    for n in unique:
        mark_seen(seen, n["url"])
    save_seen(seen)

    # Sort by score
    new_items.sort(key=lambda x: x.get("importance_score", 0), reverse=True)

    # Tag breaking
    for n in new_items:
        n["is_breaking"] = n.get("importance_score", 0) >= 7

    # Save daily file (append new only)
    save_daily(new_items)

    return new_items


def save_daily(news):
    os.makedirs(DATA_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    filepath = os.path.join(DATA_DIR, f"{today}.json")

    existing = []
    if os.path.exists(filepath):
        try:
            with open(filepath) as f:
                existing = json.load(f)
        except Exception:
            pass

    existing_urls = {n.get("url") for n in existing}
    truly_new = [n for n in news if n.get("url") not in existing_urls]
    merged = existing + truly_new

    with open(filepath, "w") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    return len(truly_new)


def fmt_time(pub_str):
    dt = parse_time(pub_str)
    if not dt:
        return ""
    local = dt.astimezone(timezone(timedelta(hours=8)))
    return local.strftime("%m-%d %H:%M")


def human_output(news, breaking_only=False):
    if breaking_only:
        news = [n for n in news if n.get("is_breaking")]

    if not news:
        print("无新增新闻")
        return

    print(f"📡 AI 新闻雷达 | {len(news)} 条{'重磅' if breaking_only else '新'}新闻")
    print()

    for i, n in enumerate(news[:20], 1):
        score = n.get("importance_score", 0)
        icon = "🔥" if score >= 7 else "📰"
        time_str = fmt_time(n.get("published_at", ""))
        time_tag = f" ({time_str})" if time_str else ""
        print(f"{icon} {n['title']}")
        if n.get("summary"):
            print(f"   {n['summary'][:100]}")
        print(f"   [{n['source']}]{time_tag}")
        print(f"   🔗 {n.get('url', '')}")
        print()


if __name__ == "__main__":
    news = collect_all()
    breaking = "--breaking-only" in sys.argv
    if "--human" in sys.argv:
        human_output(news, breaking)
    else:
        out = news if not breaking else [n for n in news if n.get("is_breaking")]
        print(json.dumps(out, ensure_ascii=False, indent=2))
