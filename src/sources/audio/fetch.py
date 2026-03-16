#!/usr/bin/env python3
"""
Daily Report 数据拉取与存储
从 daily-report 系统拉取 Gemini 音频转写数据，存入本地 JSON。

用法：
  python3 daily_report_fetch.py                    # 拉取昨天
  python3 daily_report_fetch.py --date 20260129    # 拉取指定日期
  python3 daily_report_fetch.py --range 7          # 拉取最近7天
  python3 daily_report_fetch.py --summary          # 输出摘要（不存文件）
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.parse import urlencode
from pathlib import Path

BASE_URL = "http://daily-report.prodx.srv/api/external/gemini/scripts/by-date"
TOKEN = "KAKG%XvEJfw9sc*3j2j%2oMv$6M*AbOVUcWlwuj%*zQ$D1GH"
DEFAULT_USER = "huangzhixun"
DATA_DIR = Path(os.path.expanduser("~/.openclaw/workspace/data/daily-reports"))


def fetch_date(date_str: str, user_id: str = DEFAULT_USER) -> dict | None:
    """拉取指定日期的日报数据"""
    params = urlencode({
        "user_id": user_id,
        "date": date_str,
        "traversal_token": TOKEN,
    })
    url = f"{BASE_URL}?{params}"
    try:
        req = Request(url)
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            if data.get("count", 0) > 0:
                return data
            return None
    except Exception as e:
        print(f"  ❌ 拉取 {date_str} 失败: {e}", file=sys.stderr)
        return None


def save_report(date_str: str, data: dict):
    """存储日报数据到本地"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # 标准化日期格式
    if "-" in date_str:
        date_str = date_str.replace("-", "")
    filepath = DATA_DIR / f"{date_str}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return filepath


def summarize(data: dict) -> str:
    """生成简短摘要"""
    item = data["items"][0]["content"]
    audio = item.get("audio", {})
    duration_min = audio.get("total_duration_sec", 0) // 60
    chunks = audio.get("chunks", 0)
    scenes = item.get("scenes", [])
    mframes = item.get("macro_frames", [])

    lines = [
        f"📅 {item.get('date', '?')} | 🎙 {duration_min}分钟 ({chunks}段) | 🎬 {len(scenes)}场景",
        ""
    ]

    for mf in mframes:
        tr = mf.get("time_range", ["", ""])
        start = tr[0].split("T")[1][:5] if "T" in str(tr[0]) else "?"
        end = tr[1].split("T")[1][:5] if "T" in str(tr[1]) else "?"
        lines.append(f"⏰ {start}-{end} {mf['title']}")
        activity = mf.get("primary_activity", "")
        topics = mf.get("key_topics", [])
        if topics:
            lines.append(f"  话题: {', '.join(topics[:3])}")
        outcomes = mf.get("outcomes", [])
        if outcomes:
            lines.append(f"  成果: {', '.join(outcomes[:2])}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="拉取 Daily Report 数据")
    parser.add_argument("--date", help="指定日期 YYYYMMDD 或 YYYY-MM-DD")
    parser.add_argument("--range", type=int, help="拉取最近 N 天")
    parser.add_argument("--user", default=DEFAULT_USER, help="用户ID")
    parser.add_argument("--summary", action="store_true", help="只输出摘要")
    parser.add_argument("--no-save", action="store_true", help="不存文件")
    args = parser.parse_args()

    import logging as _logging
    _log_dir = DATA_DIR.parent.parent / "logs"
    _log_dir.mkdir(parents=True, exist_ok=True)
    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            _logging.FileHandler(_log_dir / "audio_fetch.log", encoding="utf-8"),
            _logging.StreamHandler(sys.stderr),
        ],
    )
    _log = _logging.getLogger("audio_fetch")

    try:
        dates = []
        if args.range:
            today = datetime.now()
            for i in range(1, args.range + 1):
                d = today - timedelta(days=i)
                dates.append(d.strftime("%Y%m%d"))
        elif args.date:
            dates = [args.date.replace("-", "")]
        else:
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
            dates = [yesterday]

        fetched = 0
        skipped = 0
        errors = 0
        for date_str in dates:
            # 检查是否已存在
            existing = DATA_DIR / f"{date_str}.json"
            if existing.exists() and not args.summary:
                print(f"  ⏭ {date_str} 已存在，跳过")
                skipped += 1
                continue

            print(f"  📥 拉取 {date_str}...", end=" ")
            try:
                data = fetch_date(date_str, args.user)
            except Exception as e:
                _log.error(f"fetch_date({date_str}) exception: {e}")
                print(f"❌ 异常: {e}")
                errors += 1
                continue

            if data:
                print(f"✅ {data['count']} 条记录")
                if args.summary:
                    print(summarize(data))
                if not args.no_save:
                    try:
                        path = save_report(date_str, data)
                        print(f"  💾 存储到 {path}")
                    except Exception as e:
                        _log.error(f"save_report({date_str}) error: {e}")
                        print(f"  ⚠️ 存储失败: {e}")
                fetched += 1
            else:
                print("无数据")

        print(f"\n完成: {fetched} 拉取, {skipped} 跳过, {len(dates) - fetched - skipped - errors} 无数据, {errors} 错误")
        sys.exit(1 if errors > 0 else 0)

    except Exception as e:
        import logging
        logging.getLogger("audio_fetch").error(f"Fatal error: {e}", exc_info=True)
        print(f"❌ Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
