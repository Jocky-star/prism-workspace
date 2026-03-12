#!/usr/bin/env python3
"""
prism_intelligence.py — 预测驱动的智能内容生成

基于行为预测 + 规则引擎生成当前时刻的智能屏幕内容。
只依赖标准库 + 已有 prism_display 模块，不需要新包。
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
WORKSPACE = Path(os.path.expanduser("~/.openclaw/workspace"))
HABITS_DIR = WORKSPACE / "memory" / "habits"
PREDICTIONS_DIR = HABITS_DIR / "predictions"
RULES_FILE = HABITS_DIR / "behavior_rules.json"


def _load_json(path: Path) -> dict:
    """安全读取 JSON，失败返回空 dict"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_today_predictions() -> dict:
    now = datetime.now(TZ)
    today = now.strftime("%Y-%m-%d")
    return _load_json(PREDICTIONS_DIR / f"{today}.json")


def _load_rules() -> list:
    data = _load_json(RULES_FILE)
    return data.get("rules", [])


def _get_time_bucket(hour: int) -> str:
    """将小时映射到时段名"""
    if 5 <= hour < 9:
        return "morning"
    elif 9 <= hour < 12:
        return "late-morning"
    elif 12 <= hour < 14:
        return "noon"
    elif 14 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    elif 21 <= hour < 24:
        return "night"
    else:
        return "late-night"


def _get_weekday_zh(weekday: int) -> str:
    return ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][weekday]


def _truncate(text: str, max_len: int = 12) -> str:
    """截断到 max_len 个字符（含省略号）"""
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + ".."


# ── 规则匹配 ──────────────────────────────────────────────────────────────────

def _match_rules(rules: list, now: datetime) -> list:
    """返回当前时刻匹配的规则 id 列表"""
    matched = []
    hour = now.hour
    weekday = now.weekday()

    for r in rules:
        rid = r.get("id", "")
        rule_text = r.get("rule", "")

        if rid == "tuesday-sprint-mode" and weekday == 1:
            matched.append(rid)
        elif rid == "weekend-lightweight" and weekday >= 5:
            matched.append(rid)
        elif rid == "deep-work-window":
            if 5 <= hour < 8 or 21 <= hour < 24 or 0 <= hour < 5:
                matched.append(rid)
        elif rid in ("schedule-priority", "evening-caution-evening") and 17 <= hour < 21:
            matched.append(rid)
        elif rid == "evening-caution-afternoon" and 12 <= hour < 17:
            matched.append(rid)

    return matched


# ── 内容生成 ──────────────────────────────────────────────────────────────────

def _content_from_predictions(preds: dict, now: datetime) -> dict | None:
    """从预测数据中提取当前最相关的内容"""
    predictions = preds.get("predictions", [])
    hour = now.hour
    bucket = _get_time_bucket(hour)
    weekday = now.weekday()
    weekday_zh = _get_weekday_zh(weekday)

    now_text = None
    note_text = None

    for p in predictions:
        ptype = p.get("type", "")
        desc = p.get("description", "")
        conf = p.get("confidence", 0)

        if ptype == "activity" and conf >= 0.7:
            if "高活跃" in desc:
                now_text = f"{weekday_zh} 高峰期"
            elif "较低" in desc or "低" in desc:
                now_text = f"{weekday_zh} 活跃低谷"

        elif ptype == "topic_by_time" and conf >= 0.5:
            # 提取话题词
            topic_raw = desc.split("最常讨论:")[-1].strip() if "最常讨论:" in desc else ""
            if not topic_raw:
                topic_raw = desc.split(":")[-1].strip() if ":" in desc else ""
            topic_map = {
                "xhs-content": "小红书内容",
                "system-ops": "系统运维",
                "execution-quality": "执行质量",
                "habit-engine": "习惯引擎",
                "ai-research": "AI研究",
            }
            topic_zh = topic_map.get(topic_raw, topic_raw)
            if topic_zh and not note_text:
                note_text = f"常聊 {topic_zh}"

        elif ptype == "behavior" and "催进度" in desc and conf >= 0.7:
            if not note_text:
                note_text = "进度汇报 高发"

        elif ptype == "interruptibility":
            level_map = {
                "ok": "可沟通",
                "careful": "谨慎打扰",
                "low": "专注勿扰",
            }
            for k, v in level_map.items():
                if k in desc and not note_text:
                    note_text = v
                    break

        elif ptype == "weekday":
            # 周日维度描述，优先级较高
            if weekday_zh in desc and conf >= 0.6 and not now_text:
                short = desc.replace(weekday_zh, "").strip()
                if len(short) > 8:
                    short = short[:8]
                now_text = f"{weekday_zh} {short}"

    return {"now_text": now_text, "note_text": note_text} if (now_text or note_text) else None


def _content_from_rules(rules: list, now: datetime) -> dict:
    """从规则生成时段文案"""
    hour = now.hour
    weekday = now.weekday()
    weekday_zh = _get_weekday_zh(weekday)
    matched = _match_rules(rules, now)

    now_text = None
    note_text = None

    if "tuesday-sprint-mode" in matched:
        now_text = "冲刺日·深度执行"
        note_text = "响应延迟最低"
    elif "weekend-lightweight" in matched:
        now_text = f"{weekday_zh} 轻量模式"
        note_text = "低优先级巡检"
    elif "deep-work-window" in matched:
        if hour < 8:
            now_text = "清晨·深度执行"
        else:
            now_text = "深夜·深度执行"
        note_text = "集中处理耗时任务"
    elif "schedule-priority" in matched or "evening-caution-evening" in matched:
        if 17 <= hour < 21:
            now_text = "晚间·响应优先"
            note_text = "5分钟检查进展"
    elif "evening-caution-afternoon" in matched:
        now_text = "下午·保持就绪"
        note_text = "催进度高发时段"
    else:
        # 纯时段文案兜底
        bucket = _get_time_bucket(hour)
        bucket_map = {
            "morning":      "清晨·轻量开始",
            "late-morning": "上午·开始执行",
            "noon":         "午间·充电时刻",
            "afternoon":    "下午·执行时段",
            "evening":      "傍晚·收口阶段",
            "night":        "夜晚·深度时段",
            "late-night":   "深夜·静默运行",
        }
        now_text = bucket_map.get(bucket, f"{weekday_zh} 待命")

    return {"now_text": now_text, "note_text": note_text}


def get_intelligent_content() -> dict | None:
    """
    基于预测+规则生成当前时刻的智能内容。

    返回 {"now_text": str, "note_text": str | None}
    或 None（数据不足时）。

    文字已截断到 ≤12 字。
    """
    try:
        now = datetime.now(TZ)
        preds = _load_today_predictions()
        rules = _load_rules()

        result = {"now_text": None, "note_text": None}

        # 优先用规则（更确定）
        if rules:
            rule_content = _content_from_rules(rules, now)
            result["now_text"] = rule_content.get("now_text")
            result["note_text"] = rule_content.get("note_text")

        # 用预测数据补充或覆盖（更具体）
        if preds:
            pred_content = _content_from_predictions(preds, now)
            if pred_content:
                if pred_content.get("now_text"):
                    result["now_text"] = pred_content["now_text"]
                if pred_content.get("note_text"):
                    result["note_text"] = pred_content["note_text"]

        # 截断
        if result.get("now_text"):
            result["now_text"] = _truncate(result["now_text"], 12)
        if result.get("note_text"):
            result["note_text"] = _truncate(result["note_text"], 12)

        return result if result.get("now_text") else None

    except Exception:
        return None


# ── CLI 调试 ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    content = get_intelligent_content()
    if content:
        print(f"NOW : {content.get('now_text')}")
        print(f"NOTE: {content.get('note_text')}")
    else:
        print("(无智能内容)")
