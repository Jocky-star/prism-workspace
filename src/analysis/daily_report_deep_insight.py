#!/usr/bin/env python3
"""
daily_report_deep_insight.py — 深度分析饭团（黄智勋）的行为规律和个人特征
内部洞察文档，供星星（AI助手）使用
"""

import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path(os.path.expanduser("~/.openclaw/workspace/data/daily-reports"))
OUTPUT = DATA_DIR / "deep_insight.md"


def load_all():
    records = []
    for f in sorted(DATA_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            if data.get("count", 0) > 0:
                content = data["items"][0]["content"]
                # 注入文件名作为 date 备用
                if not content.get("date"):
                    content["date"] = f.stem
                records.append(content)
        except Exception as e:
            print(f"  ⚠️ {f.name}: {e}")
    return records


def parse_time(s):
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except:
        return None


def weekday_cn(dt):
    names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return names[dt.weekday()] if dt else "?"


def is_workday(dt):
    return dt.weekday() < 5 if dt else True


def get_hour(s):
    dt = parse_time(s)
    return dt.hour if dt else None


def get_all_scenes(records):
    """返回所有 scene，附带日期信息"""
    all_scenes = []
    for rec in records:
        date_str = rec.get("date", "")
        scenes = rec.get("scenes", [])
        for s in scenes:
            s["_date"] = date_str
            all_scenes.append(s)
    return all_scenes


def get_all_macro_frames(records):
    all_frames = []
    for rec in records:
        date_str = rec.get("date", "")
        frames = rec.get("macro_frames", [])
        if isinstance(frames, list):
            for f in frames:
                f["_date"] = date_str
                all_frames.append(f)
    return all_frames


def extract_topics(records):
    """从 macro_frames.key_topics 提取所有话题"""
    topics = []
    for rec in records:
        frames = rec.get("macro_frames", [])
        if isinstance(frames, list):
            for f in frames:
                topics.extend(f.get("key_topics", []))
    return topics


def extract_key_quotes(records):
    """从 scenes.key_quotes 提取所有引用"""
    quotes = []
    for rec in records:
        date_str = rec.get("date", "")
        scenes = rec.get("scenes", [])
        for s in scenes:
            for q in s.get("key_quotes", []):
                q["_date"] = date_str
                q["_scene_activity"] = s.get("activity", {}).get("label", "")
                quotes.append(q)
    return quotes


def extract_outcomes(records):
    """从 macro_frames.outcomes 提取所有结果"""
    outcomes = []
    for rec in records:
        frames = rec.get("macro_frames", [])
        if isinstance(frames, list):
            for f in frames:
                outcomes.extend(f.get("outcomes", []))
    return [o for o in outcomes if o]


def extract_moods(records):
    moods = []
    for rec in records:
        frames = rec.get("macro_frames", [])
        if isinstance(frames, list):
            for f in frames:
                m = f.get("mood_or_tone", "")
                if m:
                    moods.append(m)
    return moods


def extract_svo_bullets(records):
    svos = []
    for rec in records:
        scenes = rec.get("scenes", [])
        for s in scenes:
            for svo in s.get("svo_bullets", []):
                svos.append(svo.get("text", ""))
    return [s for s in svos if s]


def get_people_map(rec):
    """返回 {person_id: canonical_name} 字典"""
    ec = rec.get("entity_canon", {})
    people = ec.get("people", [])
    return {p["id"]: p.get("canonical", p["id"]) for p in people}


def get_location_map(rec):
    ec = rec.get("entity_canon", {})
    places = ec.get("places", [])
    return {p["id"]: p.get("canonical", p["id"]) for p in places}


def resolve_locations(scene, loc_map):
    loc = scene.get("location", {})
    if not loc:
        return []
    candidates = loc.get("candidates", [])
    if candidates:
        return [c["name"] for c in candidates]
    place_id = loc.get("place_id", "")
    return [loc_map.get(place_id, place_id)] if place_id else []


def analyze_schedule(records):
    """分析作息节奏"""
    workday_starts = []
    workday_ends = []
    weekend_starts = []
    weekend_ends = []
    daily_stats = []
    hour_activity = Counter()  # 每小时有多少 scenes
    late_days = []  # 超过 22:00 还有 scenes 的日子

    for rec in records:
        date_str = rec.get("date", "")
        audio = rec.get("audio", {})
        start_str = audio.get("start_time", "")
        dt_start = parse_time(start_str)
        
        scenes = rec.get("scenes", [])
        if not scenes:
            continue

        # 从 scenes 中找最早/最晚时间
        scene_times = []
        for s in scenes:
            st = parse_time(s.get("start_time", ""))
            et = parse_time(s.get("end_time", ""))
            if st:
                scene_times.append(st)
                hour_activity[st.hour] += 1
            if et:
                scene_times.append(et)

        if not scene_times:
            continue

        earliest = min(scene_times)
        latest = max(scene_times)

        if dt_start:
            is_wd = is_workday(dt_start)
            if is_wd:
                workday_starts.append(earliest.hour + earliest.minute / 60)
                workday_ends.append(latest.hour + latest.minute / 60)
            else:
                weekend_starts.append(earliest.hour + earliest.minute / 60)
                weekend_ends.append(latest.hour + latest.minute / 60)

        if latest.hour >= 22:
            late_days.append((date_str, latest.strftime("%H:%M")))

        daily_stats.append({
            "date": date_str,
            "earliest": earliest.strftime("%H:%M"),
            "latest": latest.strftime("%H:%M"),
            "scene_count": len(scenes)
        })

    return {
        "workday_starts": workday_starts,
        "workday_ends": workday_ends,
        "weekend_starts": weekend_starts,
        "weekend_ends": weekend_ends,
        "daily_stats": daily_stats,
        "hour_activity": hour_activity,
        "late_days": late_days
    }


def analyze_work_style(records):
    """分析工作风格"""
    participant_counts = []  # 每个 scene 的参与者数量
    meeting_hours = []  # 会议发生的小时
    meeting_scene_count_per_day = []
    tech_topics = []
    overtime_days = []
    scene_activities = Counter()
    work_scene_activities_by_hour = defaultdict(list)

    for rec in records:
        date_str = rec.get("date", "")
        scenes = rec.get("scenes", [])
        day_meetings = 0
        
        for s in scenes:
            participants = s.get("participants", [])
            participant_counts.append(len(participants))
            
            activity = s.get("activity", {}).get("label", "")
            scene_activities[activity] += 1
            
            st = parse_time(s.get("start_time", ""))
            
            if activity in ["meeting", "call"]:
                day_meetings += 1
                if st:
                    meeting_hours.append(st.hour)
            
            # 找加班（19:00 之后还有 work/meeting 场景）
            if st and st.hour >= 19 and activity in ["meeting", "work", "coding", "discussion"]:
                if date_str not in overtime_days:
                    overtime_days.append(date_str)
        
        meeting_scene_count_per_day.append(day_meetings)

    # 从 macro_frames 提取技术话题
    for rec in records:
        frames = rec.get("macro_frames", [])
        if isinstance(frames, list):
            for f in frames:
                topics = f.get("key_topics", [])
                activity = f.get("primary_activity", "")
                if activity in ["work", "meeting"]:
                    tech_topics.extend(topics)

    return {
        "participant_counts": participant_counts,
        "meeting_hours": meeting_hours,
        "avg_meetings_per_day": sum(meeting_scene_count_per_day) / len(meeting_scene_count_per_day) if meeting_scene_count_per_day else 0,
        "scene_activities": scene_activities,
        "overtime_days": overtime_days,
        "tech_topics": tech_topics
    }


def analyze_social(records):
    """分析社交模式"""
    # 统计经常出现的人名
    people_freq = Counter()
    lunch_companions = []
    scene_people_pairs = []  # (activity, people_names)
    
    for rec in records:
        people_map = get_people_map(rec)
        loc_map = get_location_map(rec)
        scenes = rec.get("scenes", [])
        
        for s in scenes:
            participants = s.get("participants", [])
            activity = s.get("activity", {}).get("label", "")
            st_h = get_hour(s.get("start_time", ""))
            
            # 解析人名（排除"用户"本人和未知人物）
            names = [people_map.get(p, p) for p in participants 
                     if people_map.get(p, p) not in ["用户", "未知人物", "未知", ""]]
            
            for n in names:
                if n and n not in ["用户", "未知人物", "未知"]:
                    people_freq[n] += 1
            
            # 午餐场景（11:00-14:00，餐饮相关活动）
            locs = resolve_locations(s, loc_map)
            loc_str = " ".join(locs).lower()
            summary = s.get("summary", "").lower()
            
            is_meal_scene = (
                activity in ["meal", "lunch", "dinner", "breakfast", "eating"] or
                any(k in loc_str for k in ["食堂", "餐厅", "饭", "午餐", "外卖"]) or
                any(k in summary for k in ["午餐", "吃饭", "食堂", "外卖", "餐"])
            )
            
            if is_meal_scene and st_h and 11 <= st_h <= 14:
                lunch_companions.extend(names)
            
            if names:
                scene_people_pairs.append((activity, names))
    
    return {
        "people_freq": people_freq,
        "lunch_companions": Counter(lunch_companions),
        "scene_people_pairs": scene_people_pairs
    }


def analyze_interests(records):
    """分析兴趣与关注点"""
    all_topics = extract_topics(records)
    all_svos = extract_svo_bullets(records)
    all_outcomes = extract_outcomes(records)
    all_quotes = extract_key_quotes(records)
    
    # 技术关键词分类
    ai_keywords = ["AI", "机器学习", "ML", "模型", "LLM", "GPT", "Gemini", "Claude", 
                   "大模型", "深度学习", "神经网络", "embedding", "推理", "训练", 
                   "微调", "RAG", "向量", "智能体", "Agent"]
    frontend_keywords = ["前端", "React", "Vue", "CSS", "UI", "用户界面", "交互设计", "H5"]
    backend_keywords = ["后端", "API", "数据库", "服务器", "微服务", "接口", "部署", "运维"]
    product_keywords = ["产品", "需求", "PRD", "用户体验", "功能设计", "原型", "迭代", "版本"]
    
    topic_text = " ".join(all_topics + all_svos)
    
    tech_counts = {
        "AI/ML": sum(1 for k in ai_keywords if k.lower() in topic_text.lower()),
        "前端/UI": sum(1 for k in frontend_keywords if k.lower() in topic_text.lower()),
        "后端/系统": sum(1 for k in backend_keywords if k.lower() in topic_text.lower()),
        "产品设计": sum(1 for k in product_keywords if k.lower() in topic_text.lower()),
    }
    
    # 非工作兴趣
    leisure_keywords = {
        "运动/健身": ["运动", "健身", "跑步", "游泳", "球", "锻炼", "体育"],
        "影视娱乐": ["电影", "视频", "剧", "综艺", "看片", "追剧"],
        "游戏": ["游戏", "打游戏", "steam", "王者"],
        "阅读": ["书", "阅读", "文章", "论文"],
        "音乐": ["音乐", "歌", "听歌"],
    }
    
    leisure_counts = {}
    combined_text = " ".join(all_topics + all_svos + [q.get("text", "") for q in all_quotes])
    for category, keywords in leisure_keywords.items():
        leisure_counts[category] = sum(1 for k in keywords if k.lower() in combined_text.lower())
    
    return {
        "all_topics": all_topics,
        "tech_counts": tech_counts,
        "leisure_counts": leisure_counts,
        "outcomes": all_outcomes,
        "quote_texts": [q.get("text", "") for q in all_quotes if q.get("text")]
    }


def analyze_commute_life(records):
    """分析通勤与生活"""
    location_freq = Counter()
    meal_times =