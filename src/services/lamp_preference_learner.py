"""
台灯偏好学习器 — 从行为数据中提炼规则，自动优化台灯场景

数据流：
  memory/lamp_log.jsonl         （行为记录）
       ↓ analyze()
  memory/lamp_preference_suggestions.json   （建议规则）
       ↓ apply_suggestions()（可选）
  memory/device_preferences.json            （生效规则）

使用方式：
  python3 -m src.services.lamp_preference_learner        # 分析 + 输出建议
  python3 -m src.services.lamp_preference_learner apply  # 分析 + 自动应用高置信度规则

也可被 cron / heartbeat 定期调用（建议每周一次）。
"""

import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("prism.lamp_learner")

# 路径
_HERE = Path(__file__).resolve()
_WORKSPACE = _HERE.parents[2]
LAMP_LOG = _WORKSPACE / "memory" / "lamp_log.jsonl"
SUGGESTIONS_FILE = _WORKSPACE / "memory" / "lamp_preference_suggestions.json"
DEVICE_PREFS_FILE = _WORKSPACE / "memory" / "device_preferences.json"

# 阈值
MIN_CONFIDENCE = 0.7    # 最低置信度（可自动应用）
MIN_SAMPLES = 3         # 最少样本数（可自动应用）
SIMILAR_BRIGHTNESS_THRESHOLD = 15   # 亮度相似阈值（±15%）
SIMILAR_COLOR_TEMP_THRESHOLD = 300  # 色温相似阈值（±300K）


# ─── 数据加载 ───────────────────────────────────────────────────────────────

def load_logs() -> List[Dict[str, Any]]:
    """读取 lamp_log.jsonl，返回所有记录"""
    if not LAMP_LOG.exists():
        return []
    records = []
    with open(LAMP_LOG, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


# ─── 模式分析 ───────────────────────────────────────────────────────────────

def _is_similar(a: Optional[float], b: Optional[float], threshold: float) -> bool:
    """判断两个数值是否相似"""
    if a is None or b is None:
        return True  # 缺失值不计入差异
    return abs(a - b) <= threshold


def analyze(logs: Optional[List[Dict]] = None) -> List[Dict[str, Any]]:
    """分析手动操作日志，提炼偏好规则建议
    
    Args:
        logs: 日志列表（None 时自动从文件加载）
    
    Returns:
        建议规则列表
    """
    if logs is None:
        logs = load_logs()
    
    # 只看手动操作
    manual_logs = [r for r in logs if r.get("source") == "manual" and r.get("on")]
    
    if not manual_logs:
        log.info("没有手动操作记录，无法提炼偏好")
        return []
    
    # 按 hour 分组
    hour_groups: Dict[int, List[Dict]] = defaultdict(list)
    for record in manual_logs:
        hour = record.get("hour")
        if hour is not None:
            hour_groups[int(hour)].append(record)
    
    suggestions = []
    
    for hour, records in sorted(hour_groups.items()):
        if len(records) < MIN_SAMPLES:
            continue
        
        # 统计亮度和色温的分布
        brightness_values = [r["brightness"] for r in records if r.get("brightness") is not None]
        color_temp_values = [r["color_temp"] for r in records if r.get("color_temp") is not None]
        
        if not brightness_values:
            continue
        
        avg_brightness = sum(brightness_values) / len(brightness_values)
        avg_color_temp = (sum(color_temp_values) / len(color_temp_values)) if color_temp_values else None
        
        # 计算相似度：有多少次调整是"相似"的
        similar_count = sum(
            1 for r in records
            if _is_similar(r.get("brightness"), avg_brightness, SIMILAR_BRIGHTNESS_THRESHOLD)
            and _is_similar(r.get("color_temp"), avg_color_temp, SIMILAR_COLOR_TEMP_THRESHOLD)
        )
        
        confidence = similar_count / len(records)
        
        if confidence < 0.5 or similar_count < 2:
            continue
        
        # 推断最适合的场景名
        suggested_scene = _infer_scene(avg_brightness, avg_color_temp)
        
        # 生成原因描述
        brightness_pct = int(avg_brightness)
        color_temp_k = int(avg_color_temp) if avg_color_temp else None
        temp_desc = f"{color_temp_k}K" if color_temp_k else "未知色温"
        
        reason = (
            f"最近{len(records)}次{hour}点你都手动调到"
            f"{brightness_pct}%亮度 {temp_desc}"
        )
        
        suggestion = {
            "hours": [hour],
            "suggested_scene": suggested_scene,
            "suggested_brightness": brightness_pct,
            "suggested_color_temp": color_temp_k,
            "confidence": round(confidence, 2),
            "sample_count": len(records),
            "similar_count": similar_count,
            "reason": reason,
        }
        suggestions.append(suggestion)
    
    # 合并相邻时段（相同场景的连续小时合并）
    suggestions = _merge_adjacent_hours(suggestions)
    
    # 按置信度排序
    suggestions.sort(key=lambda x: x["confidence"], reverse=True)
    
    return suggestions


def _infer_scene(brightness: float, color_temp: Optional[float]) -> str:
    """根据亮度和色温推断最接近的场景名"""
    if brightness >= 90:
        return "focus"
    elif brightness >= 70:
        return "normal"
    elif brightness >= 30:
        return "relax"
    else:
        return "night"


def _merge_adjacent_hours(suggestions: List[Dict]) -> List[Dict]:
    """合并相邻时段且场景相同的建议"""
    if len(suggestions) <= 1:
        return suggestions
    
    # 按 hour 排序
    by_hour = sorted(suggestions, key=lambda x: x["hours"][0])
    merged = []
    
    for s in by_hour:
        if (
            merged
            and merged[-1]["suggested_scene"] == s["suggested_scene"]
            and abs(merged[-1]["suggested_brightness"] - s["suggested_brightness"]) <= SIMILAR_BRIGHTNESS_THRESHOLD
            and merged[-1]["hours"][-1] + 1 == s["hours"][0]
        ):
            # 合并到前一个
            merged[-1]["hours"].append(s["hours"][0])
            merged[-1]["sample_count"] += s["sample_count"]
            # 重新计算平均置信度
            merged[-1]["confidence"] = round(
                (merged[-1]["confidence"] + s["confidence"]) / 2, 2
            )
            # 更新 reason
            h_range = f"{merged[-1]['hours'][0]}-{merged[-1]['hours'][-1]}"
            merged[-1]["reason"] = (
                f"最近{merged[-1]['sample_count']}次{h_range}点你都手动调到"
                f"{merged[-1]['suggested_brightness']}%亮度"
            )
        else:
            merged.append(dict(s))
    
    return merged


# ─── 建议输出 ────────────────────────────────────────────────────────────────

def save_suggestions(suggestions: List[Dict]) -> None:
    """保存建议规则到 lamp_preference_suggestions.json"""
    SUGGESTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "total": len(suggestions),
        "suggestions": suggestions,
    }
    with open(SUGGESTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    log.info(f"已保存 {len(suggestions)} 条偏好建议到 {SUGGESTIONS_FILE}")


# ─── 自动应用 ────────────────────────────────────────────────────────────────

def apply_suggestions(suggestions: Optional[List[Dict]] = None, dry_run: bool = False) -> List[Dict]:
    """将高置信度建议写入 device_preferences.json
    
    Args:
        suggestions: 建议列表（None 时自动分析）
        dry_run: 仅返回待应用的规则，不写文件
    
    Returns:
        实际应用的规则列表
    """
    if suggestions is None:
        suggestions = analyze()
    
    # 筛选高置信度建议
    high_conf = [
        s for s in suggestions
        if s["confidence"] >= MIN_CONFIDENCE and s["sample_count"] >= MIN_SAMPLES
    ]
    
    if not high_conf:
        log.info("没有足够置信度的建议可以应用")
        return []
    
    if dry_run:
        log.info(f"[dry_run] 将应用 {len(high_conf)} 条规则（未实际写入）")
        return high_conf
    
    # 读取现有偏好
    existing = {}
    if DEVICE_PREFS_FILE.exists():
        with open(DEVICE_PREFS_FILE, encoding="utf-8") as f:
            existing = json.load(f)
    
    if "lamp_rules" not in existing:
        existing["lamp_rules"] = []
    
    applied = []
    for suggestion in high_conf:
        for hour in suggestion["hours"]:
            # 检查是否已有该时段规则（来源为 learned）
            existing_rule = next(
                (r for r in existing["lamp_rules"] if r.get("hour") == hour and r.get("source", "").startswith("learned")),
                None
            )
            
            new_rule = {
                "hour": hour,
                "scene": suggestion["suggested_scene"],
                "brightness": suggestion["suggested_brightness"],
                "color_temp": suggestion["suggested_color_temp"],
                "confidence": suggestion["confidence"],
                "sample_count": suggestion["sample_count"],
                "reason": suggestion["reason"],
                "source": f"learned:{datetime.now().strftime('%Y-%m-%d')}",
            }
            
            if existing_rule:
                # 更新已有规则
                idx = existing["lamp_rules"].index(existing_rule)
                existing["lamp_rules"][idx] = new_rule
            else:
                existing["lamp_rules"].append(new_rule)
            
            applied.append(new_rule)
    
    # 保存
    existing["updated_at"] = datetime.now().isoformat()
    DEVICE_PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DEVICE_PREFS_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    
    log.info(f"已应用 {len(applied)} 条学习规则到 device_preferences.json")
    return applied


# ─── 主入口 ──────────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    
    # 分析
    logs = load_logs()
    print(f"📊 读取到 {len(logs)} 条台灯日志（手动: {sum(1 for r in logs if r.get('source')=='manual')}）")
    
    suggestions = analyze(logs)
    
    if not suggestions:
        print("📭 暂无足够的手动操作数据，继续使用中...")
        return
    
    # 保存建议
    save_suggestions(suggestions)
    
    print(f"\n💡 发现 {len(suggestions)} 条偏好建议：")
    for s in suggestions:
        hours_str = f"{s['hours'][0]}" if len(s['hours']) == 1 else f"{s['hours'][0]}-{s['hours'][-1]}"
        print(f"  • {hours_str}:00 → {s['suggested_scene']} ({s['suggested_brightness']}%) "
              f"[置信度 {s['confidence']:.0%}, 样本 {s['sample_count']}]")
        print(f"    {s['reason']}")
    
    # 如果指定 apply 参数，自动应用
    if len(sys.argv) > 1 and sys.argv[1] == "apply":
        applied = apply_suggestions(suggestions)
        print(f"\n✅ 已将 {len(applied)} 条规则写入 device_preferences.json")
    else:
        high_conf = [s for s in suggestions if s["confidence"] >= MIN_CONFIDENCE and s["sample_count"] >= MIN_SAMPLES]
        if high_conf:
            print(f"\n👉 有 {len(high_conf)} 条高置信度建议可自动应用，运行时加 apply 参数：")
            print("   python3 -m src.services.lamp_preference_learner apply")


if __name__ == "__main__":
    main()
