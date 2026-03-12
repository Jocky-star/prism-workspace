#!/usr/bin/env python3
"""
汇率监控脚本 - CNY/HKD
功能: 实时汇率、历史记录、波动告警、港股持仓汇率影响
"""

import json
import sys
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

# ── 配置 ──────────────────────────────────────────────
HISTORY_FILE = "/tmp/forex_history.json"
ALERT_PCT = 0.3  # 日波动 > 0.3% 触发告警

# 港股持仓（用于计算汇率影响）
HK_POSITION_SHARES = 3000
HK_POSITION_PRICE = 38.92  # 参考价 HKD
HK_POSITION_VALUE = HK_POSITION_SHARES * HK_POSITION_PRICE  # 总 HKD 价值

HKT = timezone(timedelta(hours=8))

# 数据源列表（按优先级排列）
FOREX_SOURCES = [
    {
        "name": "exchangerate-api",
        "url": "https://open.er-api.com/v6/latest/CNY",
        "parser": "er_api",
    },
    {
        "name": "exchangerate-api-v4",
        "url": "https://api.exchangerate-api.com/v4/latest/CNY",
        "parser": "er_api",
    },
]


def fetch_url(url, encoding="utf-8"):
    """通用 URL 请求"""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Linux; rv:109.0) Gecko/20100101 Firefox/115.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode(encoding, errors="replace")
    except (urllib.error.URLError, OSError):
        return None


def parse_er_api(raw):
    """解析 exchangerate-api 格式 (CNY 为基准)"""
    try:
        data = json.loads(raw)
        rates = data.get("rates", {})
        hkd = rates.get("HKD")
        if hkd:
            return {
                "cny_to_hkd": round(hkd, 6),
                "hkd_to_cny": round(1.0 / hkd, 6),
            }
    except (json.JSONDecodeError, TypeError, ZeroDivisionError):
        pass
    return None


PARSERS = {
    "er_api": parse_er_api,
}


def fetch_forex():
    """尝试多个数据源获取汇率"""
    for source in FOREX_SOURCES:
        raw = fetch_url(source["url"])
        if not raw:
            continue
        parser = PARSERS.get(source["parser"])
        if not parser:
            continue
        result = parser(raw)
        if result:
            result["source"] = source["name"]
            return result
    return None


def load_history():
    """加载历史汇率"""
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_history(history):
    """保存历史汇率"""
    # 只保留最近 90 天
    cutoff = (datetime.now(HKT) - timedelta(days=90)).strftime("%Y-%m-%d")
    history = [h for h in history if h.get("date", "") >= cutoff]
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except IOError:
        pass


def update_history(history, rate_data):
    """更新历史记录（每天只保留一条）"""
    today = datetime.now(HKT).strftime("%Y-%m-%d")
    now_str = datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")

    # 查找今天的记录
    today_record = None
    for h in history:
        if h.get("date") == today:
            today_record = h
            break

    if today_record:
        # 更新今天的记录
        today_record["cny_to_hkd"] = rate_data["cny_to_hkd"]
        today_record["hkd_to_cny"] = rate_data["hkd_to_cny"]
        today_record["updated_at"] = now_str
        # 追踪日内高低
        today_record["high"] = max(today_record.get("high", rate_data["cny_to_hkd"]), rate_data["cny_to_hkd"])
        today_record["low"] = min(today_record.get("low", rate_data["cny_to_hkd"]), rate_data["cny_to_hkd"])
    else:
        history.append({
            "date": today,
            "cny_to_hkd": rate_data["cny_to_hkd"],
            "hkd_to_cny": rate_data["hkd_to_cny"],
            "high": rate_data["cny_to_hkd"],
            "low": rate_data["cny_to_hkd"],
            "updated_at": now_str,
        })

    return history


def check_alerts(rate_data, history):
    """检查汇率告警"""
    alerts = []
    today = datetime.now(HKT).strftime("%Y-%m-%d")

    # 找到昨天（或最近一个交易日）的汇率
    prev_rate = None
    for h in reversed(history):
        if h.get("date") != today:
            prev_rate = h
            break

    if prev_rate:
        prev_cny_hkd = prev_rate["cny_to_hkd"]
        curr_cny_hkd = rate_data["cny_to_hkd"]
        day_change_pct = ((curr_cny_hkd - prev_cny_hkd) / prev_cny_hkd) * 100

        if abs(day_change_pct) >= ALERT_PCT:
            direction = "💹 人民币升值" if day_change_pct > 0 else "💱 人民币贬值"
            alerts.append({
                "type": "forex_swing",
                "level": "warning",
                "message": f"{direction} CNY/HKD 日波动 {day_change_pct:+.3f}%",
                "change_pct": round(day_change_pct, 4),
            })

        # 计算汇率变化对持仓的影响
        # 持仓 HKD 价值不变，但换算成 CNY 会变
        # hkd_to_cny 变大 = 人民币贬值 = 持仓 CNY 价值上升
        prev_cny_value = HK_POSITION_VALUE * prev_rate["hkd_to_cny"]
        curr_cny_value = HK_POSITION_VALUE * rate_data["hkd_to_cny"]
        fx_impact = curr_cny_value - prev_cny_value

        return alerts, {
            "prev_date": prev_rate["date"],
            "prev_cny_to_hkd": prev_cny_hkd,
            "day_change_pct": round(day_change_pct, 4),
            "fx_impact_cny": round(fx_impact, 2),
            "position_cny_value": round(curr_cny_value, 2),
        }

    return alerts, None


def build_result(rate_data, history, alerts, comparison):
    """构建输出"""
    now = datetime.now(HKT)

    result = {
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "forex": {
            "cny_to_hkd": rate_data["cny_to_hkd"],
            "hkd_to_cny": rate_data["hkd_to_cny"],
            "source": rate_data.get("source", "unknown"),
        },
        "position_impact": {
            "hk_shares": HK_POSITION_SHARES,
            "hk_ref_price": HK_POSITION_PRICE,
            "hk_value_hkd": round(HK_POSITION_VALUE, 2),
            "hk_value_cny": round(HK_POSITION_VALUE * rate_data["hkd_to_cny"], 2),
        },
        "alerts": alerts,
        "has_alert": len(alerts) > 0,
    }

    if comparison:
        result["comparison"] = comparison

    # 近 7 天汇率趋势
    recent = [h for h in history[-7:]]
    if recent:
        result["trend_7d"] = [
            {"date": h["date"], "cny_to_hkd": h["cny_to_hkd"]}
            for h in recent
        ]

    return result


def format_human(result):
    """人类可读格式"""
    fx = result["forex"]
    pos = result["position_impact"]
    lines = [
        f"{'='*44}",
        f"  汇率监控  |  {result['timestamp']}",
        f"{'='*44}",
        f"",
        f"  💱 CNY → HKD: {fx['cny_to_hkd']:.4f}",
        f"  💱 HKD → CNY: {fx['hkd_to_cny']:.4f}",
        f"  📡 数据源: {fx['source']}",
    ]

    comp = result.get("comparison")
    if comp:
        pct = comp["day_change_pct"]
        arrow = "↑" if pct > 0 else "↓" if pct < 0 else "→"
        lines += [
            f"",
            f"  ── 日变化 (vs {comp['prev_date']}) ──",
            f"  {arrow} 波动: {pct:+.4f}%",
            f"  {'🟢' if comp['fx_impact_cny'] >= 0 else '🔴'} 汇率影响: {comp['fx_impact_cny']:+,.2f} CNY",
        ]

    lines += [
        f"",
        f"  ── 港股持仓换算 ──",
        f"  📦 {pos['hk_shares']}股 × {pos['hk_ref_price']} HKD = {pos['hk_value_hkd']:,.2f} HKD",
        f"  💰 ≈ {pos['hk_value_cny']:,.2f} CNY",
    ]

    trend = result.get("trend_7d", [])
    if trend:
        lines += [f"", f"  ── 近期趋势 ──"]
        for t in trend:
            lines.append(f"    {t['date']}: {t['cny_to_hkd']:.4f}")

    if result["alerts"]:
        lines += [f"", f"  ⚠️  告警:"]
        for a in result["alerts"]:
            lines.append(f"    • {a['message']}")

    lines.append(f"{'='*44}")
    return "\n".join(lines)


def main():
    human_mode = "--human" in sys.argv

    # 获取汇率
    rate_data = fetch_forex()
    if not rate_data:
        err = {"error": "无法获取汇率数据", "timestamp": datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")}
        if human_mode:
            print("❌ 无法获取汇率数据，请检查网络或稍后重试")
        else:
            print(json.dumps(err, ensure_ascii=False))
        sys.exit(1)

    # 加载并更新历史
    history = load_history()
    history = update_history(history, rate_data)
    save_history(history)

    # 检查告警
    alerts, comparison = check_alerts(rate_data, history)

    # 构建结果
    result = build_result(rate_data, history, alerts, comparison)

    if human_mode:
        print(format_human(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
