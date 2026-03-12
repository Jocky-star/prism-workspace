#!/usr/bin/env python3
"""
api_usage_tracker.py - OpenClaw API 用量统计
从 session JSONL 文件解析 token 消耗
"""

import json
import os
import sys
import glob
from datetime import datetime, date
from pathlib import Path

SESSIONS_DIR = os.path.expanduser("~/.openclaw/agents/main/sessions")
# Anthropic Opus 官方价格
PRICE_INPUT = 15.0 / 1_000_000   # $15/1M tokens
PRICE_OUTPUT = 75.0 / 1_000_000  # $75/1M tokens


def parse_session_file(filepath):
    """解析 session JSONL 文件，提取 usage 信息"""
    total_in = 0
    total_out = 0
    cache_read = 0
    session_type = "unknown"
    model = "unknown"
    name = os.path.basename(filepath).replace(".jsonl", "")
    
    try:
        with open(filepath, 'r') as f:
            first_user_msg = None
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except:
                    continue
                
                msg = entry.get("message", entry)  # 新格式在 message 字段里
                
                # 识别会话类型
                role = msg.get("role", "")
                if role == "user" and first_user_msg is None:
                    content = ""
                    if isinstance(msg.get("content"), str):
                        content = msg["content"]
                    elif isinstance(msg.get("content"), list):
                        for c in msg["content"]:
                            if isinstance(c, dict) and c.get("type") == "text":
                                content += c.get("text", "")
                    first_user_msg = content
                    if "[cron:" in content:
                        session_type = "cron"
                        try:
                            name = content.split("[cron:")[1].split("]")[0].split(" ", 1)[-1]
                        except:
                            pass
                    elif "[Subagent" in content or "子代理" in content:
                        session_type = "subagent"
                    else:
                        session_type = "main"
                
                # 提取 usage（每条 assistant 消息都有独立 usage）
                usage = msg.get("usage", {})
                if usage:
                    total_in += usage.get("input", 0)
                    total_out += usage.get("output", 0)
                    cache_read += usage.get("cacheRead", 0)
                
                if msg.get("model"):
                    model = msg["model"]
    except Exception as e:
        pass
    
    return {
        "name": name,
        "type": session_type,
        "model": model,
        "input_tokens": total_in,
        "output_tokens": total_out,
        "cache_read": cache_read,
    }


def get_today_sessions(target_date=None):
    """获取指定日期的所有 session"""
    if target_date is None:
        target_date = date.today()
    
    sessions = []
    if not os.path.isdir(SESSIONS_DIR):
        return sessions
    
    for filepath in glob.glob(os.path.join(SESSIONS_DIR, "*.jsonl")):
        mtime = datetime.fromtimestamp(os.path.getmtime(filepath)).date()
        # 只看今天修改过的文件
        if mtime == target_date:
            info = parse_session_file(filepath)
            if info["input_tokens"] > 0 or info["output_tokens"] > 0:
                sessions.append(info)
    
    return sessions


def generate_report(target_date=None):
    if target_date is None:
        target_date = date.today()
    
    sessions = get_today_sessions(target_date)
    
    total_in = sum(s["input_tokens"] for s in sessions)
    total_out = sum(s["output_tokens"] for s in sessions)
    cost = total_in * PRICE_INPUT + total_out * PRICE_OUTPUT
    
    # 按类型分组
    breakdown = {}
    for s in sessions:
        key = f"{s['type']}_{s['name']}"
        if key not in breakdown:
            breakdown[key] = {"type": s["type"], "name": s["name"], "input": 0, "output": 0, "model": s["model"]}
        breakdown[key]["input"] += s["input_tokens"]
        breakdown[key]["output"] += s["output_tokens"]
    
    # 计算每项成本
    for k, v in breakdown.items():
        v["cost_usd"] = round(v["input"] * PRICE_INPUT + v["output"] * PRICE_OUTPUT, 4)
    
    # 排序
    sorted_breakdown = sorted(breakdown.values(), key=lambda x: x["cost_usd"], reverse=True)
    
    # 建议
    recommendations = []
    if total_in > 5_000_000:
        recommendations.append("日 input tokens 超过 500 万，考虑启用 light-context 模式减少上下文加载")
    cron_cost = sum(v["cost_usd"] for v in breakdown.values() if v["type"] == "cron")
    if cron_cost > cost * 0.5 and cost > 0:
        recommendations.append(f"Cron 任务占总消耗 {cron_cost/cost*100:.0f}%，考虑纯脚本预处理减少 LLM 调用")
    if total_out > 500_000:
        recommendations.append("输出 token 较多，检查是否有不必要的长回复")
    
    return {
        "date": str(target_date),
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "estimated_cost_usd": round(cost, 4),
        "estimated_cost_cny": round(cost * 7.2, 2),
        "session_count": len(sessions),
        "breakdown": sorted_breakdown,
        "recommendations": recommendations,
    }


def human_output(report):
    print(f"{'='*50}")
    print(f"  💰 API 用量日报  |  {report['date']}")
    print(f"{'='*50}")
    print(f"\n  📊 总计:")
    print(f"     Input:  {report['total_input_tokens']:>12,} tokens")
    print(f"     Output: {report['total_output_tokens']:>12,} tokens")
    print(f"     会话数: {report['session_count']}")
    print(f"     💵 估算成本: ${report['estimated_cost_usd']:.4f} (≈¥{report['estimated_cost_cny']:.2f})")
    
    print(f"\n  📋 明细 (按成本排序):")
    for item in report["breakdown"]:
        type_icon = {"cron": "⏰", "subagent": "🤖", "main": "💬"}.get(item["type"], "❓")
        print(f"     {type_icon} {item['name']}")
        print(f"        In: {item['input']:>10,}  Out: {item['output']:>10,}  💵 ${item['cost_usd']:.4f}")
    
    if report["recommendations"]:
        print(f"\n  💡 优化建议:")
        for r in report["recommendations"]:
            print(f"     • {r}")
    
    print(f"{'='*50}")


if __name__ == "__main__":
    report = generate_report()
    if "--human" in sys.argv:
        human_output(report)
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
