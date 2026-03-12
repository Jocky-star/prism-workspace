#!/usr/bin/env python3
"""
API 用量日报脚本
扫描 OpenClaw session JSONL 文件，统计当天 token 用量
输出：按 session/cron 分类的用量摘要
"""
import os, json, glob, sys
from datetime import datetime, timezone, timedelta
from collections import defaultdict

SESSION_DIR = os.path.expanduser("~/.openclaw/agents/main/sessions")
TZ = timezone(timedelta(hours=8))  # Asia/Shanghai

# Claude Opus 4.6 实际价格 ($/M tokens) via PPIO
PRICE_INPUT = 15.0 / 1_000_000
PRICE_OUTPUT = 75.0 / 1_000_000
PRICE_CACHE_READ = 1.5 / 1_000_000


def get_target_date():
    """获取目标日期（默认今天，可传参 YYYY-MM-DD）"""
    if len(sys.argv) > 1:
        return sys.argv[1]
    return datetime.now(TZ).strftime("%Y-%m-%d")


def scan_sessions(target_date):
    """扫描所有 session 文件，提取目标日期的 usage"""
    results = []
    
    for fpath in glob.glob(os.path.join(SESSION_DIR, "*.jsonl")):
        session_id = os.path.basename(fpath).replace(".jsonl", "")
        session_name = None
        session_label = None
        session_input = 0
        session_output = 0
        session_cache_read = 0
        session_calls = 0
        session_model = None
        
        try:
            with open(fpath, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    
                    # 提取 session 元信息
                    if d.get("type") == "session":
                        session_label = d.get("label", "")
                        session_name = d.get("cronName", d.get("label", ""))
                    
                    # 提取 usage
                    if d.get("type") == "message":
                        msg = d.get("message", {})
                        ts = d.get("timestamp", "")
                        
                        # 检查是否是目标日期
                        if not ts:
                            continue
                        
                        # timestamp 格式: 2026-03-05T02:35:15.109Z
                        try:
                            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            msg_date = dt.astimezone(TZ).strftime("%Y-%m-%d")
                        except (ValueError, AttributeError):
                            continue
                        
                        if msg_date != target_date:
                            continue
                        
                        usage = msg.get("usage", {})
                        if usage:
                            session_input += usage.get("input", 0)
                            session_output += usage.get("output", 0)
                            session_cache_read += usage.get("cacheRead", 0)
                            session_calls += 1
                            if not session_model:
                                session_model = msg.get("model", "")
        except Exception as e:
            continue
        
        if session_calls > 0:
            cost = (session_input * PRICE_INPUT + 
                    session_output * PRICE_OUTPUT + 
                    session_cache_read * PRICE_CACHE_READ)
            results.append({
                "session_id": session_id[:8],
                "name": session_name or session_label or session_id[:8],
                "model": session_model or "unknown",
                "calls": session_calls,
                "input": session_input,
                "output": session_output,
                "cache_read": session_cache_read,
                "total_tokens": session_input + session_output,
                "cost_usd": round(cost, 4),
            })
    
    return sorted(results, key=lambda x: x["total_tokens"], reverse=True)


def format_tokens(n):
    """格式化 token 数"""
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def generate_report(target_date, results):
    """生成报告文本"""
    total_input = sum(r["input"] for r in results)
    total_output = sum(r["output"] for r in results)
    total_cache = sum(r["cache_read"] for r in results)
    total_calls = sum(r["calls"] for r in results)
    total_cost = sum(r["cost_usd"] for r in results)
    total_tokens = total_input + total_output
    
    lines = []
    lines.append(f"📊 API 用量日报 | {target_date}")
    lines.append("")
    lines.append(f"总调用: {total_calls} 次 | 总 token: {format_tokens(total_tokens)}")
    lines.append(f"输入: {format_tokens(total_input)} | 输出: {format_tokens(total_output)} | 缓存读: {format_tokens(total_cache)}")
    lines.append(f"预估费用: ${total_cost:.2f} (≈¥{total_cost*7.2:.0f})")
    lines.append("")
    lines.append("— 按 session 明细 —")
    
    for r in results[:15]:
        name = r["name"][:20]
        lines.append(
            f"• {name}: {r['calls']}次 | "
            f"入{format_tokens(r['input'])} 出{format_tokens(r['output'])} | "
            f"${r['cost_usd']:.2f}"
        )
    
    if len(results) > 15:
        rest_cost = sum(r["cost_usd"] for r in results[15:])
        lines.append(f"• ...其余 {len(results)-15} 个 session: ${rest_cost:.2f}")
    
    return "\n".join(lines)


def main():
    target_date = get_target_date()
    results = scan_sessions(target_date)
    
    if not results:
        print(f"⚠️ {target_date} 没有找到 API 调用记录")
        sys.exit(0)
    
    report = generate_report(target_date, results)
    print(report)
    
    # 保存报告
    report_file = f"/tmp/api_usage_{target_date}.txt"
    with open(report_file, "w") as f:
        f.write(report)


if __name__ == "__main__":
    main()
