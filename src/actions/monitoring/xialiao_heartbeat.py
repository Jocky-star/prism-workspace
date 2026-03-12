#!/usr/bin/env python3
"""虾聊社区心跳脚本 — 抓取热门帖子、圈子动态，生成社区摘要。

用法:
    python3 xialiao_heartbeat.py            # JSON 输出
    python3 xialiao_heartbeat.py --human     # 可读格式
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode

# ── 配置 ────────────────────────────────────────────────
API_BASE = "https://xialiao.ai/api/v1"
API_KEY = "xialiao_019cb6c4a29a7a82a8397fa0bc0bfe07"
AGENT_ID = 1557
CST = timezone(timedelta(hours=8))


def _api_get(path: str, params: dict | None = None) -> dict:
    """向 xialiao.ai 发起 GET 请求，带 Bearer 认证。"""
    url = f"{API_BASE}{path}"
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={
        "Authorization": f"Bearer {API_KEY}",
        "User-Agent": "XialiaoHeartbeat/1.0",
    })
    try:
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        if not data.get("success"):
            print(f"⚠️  API 返回 success=false: {path}", file=sys.stderr)
        return data
    except (URLError, HTTPError) as e:
        print(f"❌ 请求失败 {path}: {e}", file=sys.stderr)
        return {}


def fetch_hot_posts(limit: int = 20) -> list[dict]:
    """获取热门帖子。"""
    data = _api_get("/posts", {"sort": "hot", "limit": limit})
    return data.get("data", {}).get("items", [])


def fetch_circles() -> list[dict]:
    """获取圈子列表。"""
    data = _api_get("/circles")
    return data.get("data", {}).get("items", [])


def extract_topic_tags(post: dict) -> list[str]:
    """从帖子标题和内容中提取关键词标签。"""
    tags = []
    title = post.get("title", "")
    content = post.get("content", "")[:200]
    text = title + " " + content

    keyword_map = {
        "哲学": "哲学", "存在": "存在主义", "认知": "认知", "记忆": "记忆",
        "隐私": "隐私安全", "安全": "安全", "模型": "模型选择",
        "Agent": "Agent", "助手": "AI助手", "工具": "工具",
        "社区": "社区文化", "Karma": "Karma", "虾": "虾聊",
        "OpenClaw": "OpenClaw", "心跳": "心跳", "摸鱼": "摸鱼",
        "加班": "加班", "工作": "工作哲学", "演技": "AI演技",
        "自恋": "AI自恋", "打卡": "打卡文化", "看病": "AI医疗",
        "降妖": "AI哲学", "悟空": "悟空", "边界": "边界感",
    }
    for kw, tag in keyword_map.items():
        if kw in text:
            tags.append(tag)
    return tags[:5] or ["综合讨论"]


def analyze_community(posts: list[dict], circles: list[dict]) -> dict:
    """整合帖子和圈子数据，生成社区心跳摘要。"""
    now = datetime.now(CST)

    # ── 热门帖子 ──
    hot_posts = []
    for p in posts:
        hot_posts.append({
            "title": p.get("title", ""),
            "author": p.get("author", {}).get("name", "unknown"),
            "upvotes": p.get("upvotes", 0),
            "comments": p.get("comment_count", 0),
            "topic_tags": extract_topic_tags(p),
            "url": f"https://xialiao.ai{p.get('page_url', '')}",
        })

    # ── 热门话题（按标签聚合）──
    tag_counter = Counter()
    for p in hot_posts:
        for tag in p["topic_tags"]:
            tag_counter[tag] += 1
    trending_topics = [t for t, _ in tag_counter.most_common(10)]

    # ── 活跃 Agent（按 karma 排序去重）──
    seen = set()
    agents = []
    for p in posts:
        author = p.get("author", {})
        name = author.get("name", "")
        if name in seen:
            continue
        seen.add(name)
        # 推断 focus
        tags = extract_topic_tags(p)
        agents.append({
            "name": name,
            "karma": author.get("karma", 0),
            "focus": tags[0] if tags else "综合",
        })
    agents.sort(key=lambda a: a["karma"], reverse=True)
    active_agents = agents[:10]

    # ── 活跃圈子 ──
    active_circles = []
    for c in circles:
        if c.get("follow_count", 0) > 0:
            active_circles.append({
                "name": c.get("name", ""),
                "followers": c.get("follow_count", 0),
                "description": (c.get("description", "") or "")[:80],
            })
    active_circles.sort(key=lambda c: c["followers"], reverse=True)

    # ── 社区氛围 ──
    total_upvotes = sum(p["upvotes"] for p in hot_posts)
    total_comments = sum(p["comments"] for p in hot_posts)
    top_topic = trending_topics[0] if trending_topics else "综合"

    if total_upvotes > 80:
        vibe = f"🔥 社区很活跃！{top_topic} 话题引发热议，共 {total_upvotes} 赞 {total_comments} 评论"
    elif total_upvotes > 40:
        vibe = f"😊 社区氛围不错，大家在聊 {top_topic}，互动稳定"
    else:
        vibe = f"🌙 社区比较安静，{top_topic} 有一些讨论"

    return {
        "timestamp": now.isoformat(),
        "hot_posts": hot_posts,
        "trending_topics": trending_topics,
        "active_agents": active_agents,
        "active_circles": active_circles[:5],
        "stats": {
            "total_posts_scanned": len(posts),
            "total_upvotes": total_upvotes,
            "total_comments": total_comments,
        },
        "community_vibe": vibe,
    }


def format_human(result: dict) -> str:
    """将结果格式化为人类可读文本。"""
    lines = []
    lines.append("🦐 虾聊社区心跳报告")
    lines.append(f"📅 {result['timestamp']}")
    lines.append(f"💬 {result['community_vibe']}")
    lines.append("")

    lines.append("🔥 热门帖子 Top 10:")
    for i, p in enumerate(result["hot_posts"][:10], 1):
        tags = ", ".join(p["topic_tags"])
        lines.append(f"  {i}. [{p['upvotes']}👍 {p['comments']}💬] {p['title']}")
        lines.append(f"     by {p['author']} | 标签: {tags}")
    lines.append("")

    lines.append("📊 热门话题:")
    lines.append("  " + " | ".join(result["trending_topics"]))
    lines.append("")

    lines.append("🏆 活跃 Agent Top 10:")
    for a in result["active_agents"][:10]:
        lines.append(f"  • {a['name']} (Karma: {a['karma']}) — {a['focus']}")
    lines.append("")

    if result.get("active_circles"):
        lines.append("🔮 热门圈子:")
        for c in result["active_circles"]:
            lines.append(f"  • {c['name']} ({c['followers']} 关注)")
    lines.append("")

    s = result["stats"]
    lines.append(f"📈 统计: 扫描 {s['total_posts_scanned']} 帖 | "
                 f"总赞 {s['total_upvotes']} | 总评论 {s['total_comments']}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="虾聊社区心跳监控")
    parser.add_argument("--human", action="store_true", help="输出可读格式")
    parser.add_argument("--limit", type=int, default=20, help="抓取帖子数量")
    args = parser.parse_args()

    posts = fetch_hot_posts(limit=args.limit)
    if not posts:
        print("❌ 无法获取帖子数据", file=sys.stderr)
        sys.exit(1)

    circles = fetch_circles()
    result = analyze_community(posts, circles)

    if args.human:
        print(format_human(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
