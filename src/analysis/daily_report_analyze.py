#!/usr/bin/env python3
"""
daily_report_analyze.py — 分析所有日报数据，生成综合报告
"""

import json
import os
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(os.path.expanduser("~/.openclaw/workspace/data/daily-reports"))
OUTPUT = DATA_DIR / "analysis_report.md"


def load_all():
    records = []
    for f in sorted(DATA_DIR.glob("*.json")):
        if f.name == "analysis_report.md":
            continue
        try:
            data = json.loads(f.read_text())
            if data.get("count", 0) > 0:
                content = data["items"][0]["content"]
                records.append(content)
        except Exception as e:
            print(f"  ⚠️ {f.name}: {e}")
    return records


def parse_time(s):
    """解析 ISO 时间字符串"""
    if not s:
        return None
    try:
        # 处理各种格式
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except:
        return None


def weekday_cn(dt):
    names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return names[dt.weekday()] if dt else "?"


def is_workday(dt):
    return dt.weekday() < 5 if dt else True


def duration_str(secs):
    if secs < 60:
        return f"{secs:.0f}秒"
    if secs < 3600:
        return f"{secs/60:.0f}分钟"
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    return f"{h}h{m:02d}m"


def main():
    records = load_all()
    if not records:
        print("无数据")
        return

    lines = [f"# 日报数据分析报告\n",
             f"**数据范围**: {records[0].get('date','?')} ~ {records[-1].get('date','?')}",
             f"**总天数**: {len(records)} 天\n",
             f"---\n"]

    # ═══ 1. 时间模式 ═══
    lines.append("## 1. 时间模式\n")
    lines.append("| 日期 | 星期 | 开始 | 结束 | 录音时长 | 段数 | 场景数 |")
    lines.append("|------|------|------|------|----------|------|--------|")

    late_nights = 0  # 22:00+
    workday_starts = []
    workday_ends = []
    weekend_count = 0
    total_duration = 0

    for r in records:
        date = r.get("date", "?")
        audio = r.get("audio", {})
        dur = audio.get("total_duration_sec", 0)
        total_duration += dur
        chunks = audio.get("chunks", 0)
        scenes = len(r.get("scenes", []))

        start_t = parse_time(audio.get("start_time", ""))
        # 找最晚的场景结束时间
        end_t = None
        for s in r.get("scenes", []):
            et = parse_time(s.get("end_time", ""))
            if et and (end_t is None or et > end_t):
                end_t = et

        start_str = start_t.strftime("%H:%M") if start_t else "?"
        end_str = end_t.strftime("%H:%M") if end_t else "?"
        wd = weekday_cn(start_t)

        if start_t and not is_workday(start_t):
            weekend_count += 1

        if start_t and is_workday(start_t):
            workday_starts.append(start_t.hour + start_t.minute / 60)
        if end_t and is_workday(end_t):
            workday_ends.append(end_t.hour + end_t.minute / 60)

        if end_t and end_t.hour >= 22:
            late_nights += 1

        lines.append(f"| {date} | {wd} | {start_str} | {end_str} | {duration_str(dur)} | {chunks} | {scenes} |")

    lines.append("")
    lines.append(f"**总录音时长**: {duration_str(total_duration)}")
    lines.append(f"**工作日**: {len(records) - weekend_count} 天 | **周末**: {weekend_count} 天")
    if workday_starts:
        avg_start = sum(workday_starts) / len(workday_starts)
        lines.append(f"**工作日平均开始**: {int(avg_start)}:{int((avg_start%1)*60):02d}")
    if workday_ends:
        avg_end = sum(workday_ends) / len(workday_ends)
        lines.append(f"**工作日平均结束**: {int(avg_end)}:{int((avg_end%1)*60):02d}")
    lines.append(f"**加班频率（22:00+）**: {late_nights}/{len(records)} 天 ({late_nights/len(records)*100:.0f}%)\n")

    # ═══ 2. 活动分布 ═══
    lines.append("---\n")
    lines.append("## 2. 活动分布\n")

    activity_count = Counter()
    activity_duration = defaultdict(float)

    for r in records:
        for mf in r.get("macro_frames", []):
            act = mf.get("primary_activity", "unknown")
            activity_count[act] += 1
            tr = mf.get("time_range", [])
            if len(tr) == 2:
                t1 = parse_time(tr[0])
                t2 = parse_time(tr[1])
                if t1 and t2:
                    activity_duration[act] += (t2 - t1).total_seconds()

    total_acts = sum(activity_count.values()) or 1
    lines.append("| 活动类型 | 出现次数 | 占比 | 总时长 |")
    lines.append("|----------|----------|------|--------|")
    for act, cnt in activity_count.most_common():
        pct = cnt / total_acts * 100
        dur = duration_str(activity_duration.get(act, 0))
        lines.append(f"| {act} | {cnt} | {pct:.1f}% | {dur} |")
    lines.append("")

    # ═══ 3. 项目/话题热度 ═══
    lines.append("---\n")
    lines.append("## 3. 项目/话题热度 Top 15\n")

    topic_counter = Counter()
    topic_dates = defaultdict(set)

    for r in records:
        date = r.get("date", "?")
        # 从 entity_canon
        for pt in r.get("entity_canon", {}).get("projects_or_topics", []):
            name = pt.get("canonical", "")
            if name:
                topic_counter[name] += 1
                topic_dates[name].add(date)
        # 从 macro_frames.key_topics
        for mf in r.get("macro_frames", []):
            for topic in mf.get("key_topics", []):
                if topic:
                    topic_counter[topic] += 1
                    topic_dates[topic].add(date)

    lines.append("| 话题 | 出现次数 | 涉及天数 | 日期范围 |")
    lines.append("|------|----------|----------|----------|")
    for topic, cnt in topic_counter.most_common(15):
        dates = sorted(topic_dates[topic])
        days = len(dates)
        range_str = f"{dates[0]}~{dates[-1]}" if len(dates) > 1 else dates[0]
        lines.append(f"| {topic} | {cnt} | {days} | {range_str} |")
    lines.append("")

    # ═══ 4. 协作网络 ═══
    lines.append("---\n")
    lines.append("## 4. 协作网络\n")

    people_counter = Counter()
    people_dates = defaultdict(set)

    for r in records:
        date = r.get("date", "?")
        for p in r.get("entity_canon", {}).get("people", []):
            name = p.get("canonical", "")
            if name:
                people_counter[name] += 1
                people_dates[name].add(date)

    lines.append("| 人物 | 出现天数 | 日期 |")
    lines.append("|------|----------|------|")
    for name, cnt in people_counter.most_common(15):
        dates = sorted(people_dates[name])
        lines.append(f"| {name} | {len(dates)} | {', '.join(dates[:5])}{'...' if len(dates)>5 else ''} |")
    lines.append("")

    # ═══ 5. 关键引用/金句 ═══
    lines.append("---\n")
    lines.append("## 5. 关键引用/金句 Top 20\n")

    quotes = []
    for r in records:
        date = r.get("date", "?")
        for scene in r.get("scenes", []):
            conf = scene.get("confidence", 0)
            summary = scene.get("summary", "")[:50]
            for q in scene.get("key_quotes", []):
                text = q.get("text", "")
                if len(text) > 10:  # 过滤太短的
                    quotes.append({
                        "date": date,
                        "text": text,
                        "speaker": q.get("speaker", "?"),
                        "confidence": conf,
                        "context": summary,
                    })

    quotes.sort(key=lambda x: -x["confidence"])
    for i, q in enumerate(quotes[:20], 1):
        lines.append(f"**{i}. [{q['date']}]** ({q['speaker']})")
        lines.append(f"> {q['text']}")
        lines.append(f"*场景: {q['context']}*\n")

    # ═══ 6. 待办事项 ═══
    lines.append("---\n")
    lines.append("## 6. 待办事项汇总\n")

    todos = []
    for r in records:
        date = r.get("date", "?")
        for scene in r.get("scenes", []):
            for todo in scene.get("todos", []):
                text = todo if isinstance(todo, str) else todo.get("text", str(todo))
                if text:
                    todos.append({"date": date, "text": text})

    if todos:
        current_date = ""
        for t in todos:
            if t["date"] != current_date:
                current_date = t["date"]
                lines.append(f"\n### {current_date}")
            lines.append(f"- {t['text']}")
    else:
        lines.append("*录音中未提取到明确的待办事项*\n")

    # ═══ 7. 每日一句话总结 ═══
    lines.append("\n---\n")
    lines.append("## 7. 每日一句话总结\n")

    for r in records:
        date = r.get("date", "?")
        mfs = r.get("macro_frames", [])
        if mfs:
            titles = [mf.get("title", "") for mf in mfs if mf.get("title")]
            outcomes = []
            for mf in mfs:
                outcomes.extend(mf.get("outcomes", []))
            summary = " → ".join(titles[:3])
            if outcomes:
                summary += f" 【成果: {outcomes[0]}】"
            lines.append(f"- **{date}**: {summary}")
        else:
            lines.append(f"- **{date}**: (无宏观帧数据)")

    # 写入
    report = "\n".join(lines)
    OUTPUT.write_text(report, encoding="utf-8")
    print(f"✅ 报告已生成: {OUTPUT}")
    print(f"   {len(records)} 天数据，{len(report)} 字符")


if __name__ == "__main__":
    main()
