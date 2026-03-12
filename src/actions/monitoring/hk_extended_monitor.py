#!/usr/bin/env python3
"""
港股监控脚本 - 中烟香港 (06055)
数据源: 腾讯行情 API
功能: 实时报价、盈亏计算、异常告警
"""

import json
import sys
import urllib.request
import urllib.error
import re
from datetime import datetime, timezone, timedelta

# ── 配置（从 JSON 文件读取持仓） ──────────────────────
import json as _json
POSITION_FILE = "/home/mi/.openclaw/workspace/data/current_position.json"

def _load_hk():
    try:
        with open(POSITION_FILE) as f:
            data = _json.load(f)
        for p in data.get("positions", []):
            if p.get("market") == "hk":
                return p["code"], p["name"], p.get("shares", 0)
    except Exception:
        pass
    return "06055", "中烟香港", 9000  # fallback

STOCK_CODE, STOCK_NAME, POSITION = _load_hk()

# 腾讯行情接口
REALTIME_URL = f"https://qt.gtimg.cn/q=r_hk{STOCK_CODE}"
KLINE_URL = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=hk{STOCK_CODE},day,,,60,qfq"

# 告警阈值
CHANGE_ALERT_PCT = 2.0       # 涨跌幅 > 2% 触发告警
VOLUME_ALERT_RATIO = 2.0     # 成交量 > 均量 2 倍触发告警
VOLUME_AVG_DAYS = 20         # 均量计算天数

# ── 放量突破策略参数（回测胜率88%）──
STRATEGY_ENABLED = True
BASE_POSITION = 2000         # 底仓（不动）
SWING_POSITION = 1000        # 波段仓位
LOT_SIZE = 200               # 港股1手=200股
# 买入条件：量比>2x 且 当日涨>2%
STRATEGY_BUY_VOL_RATIO = 2.0
STRATEGY_BUY_CHANGE_PCT = 2.0
# 卖出条件：放量跌>3%
STRATEGY_SELL_VOL_RATIO = 2.0
STRATEGY_SELL_CHANGE_PCT = -3.0
# 硬止损：跌破MA60全部减到底仓
MA60_STOP_LOSS = True

# 港股交易时段 (HKT = UTC+8)
HKT = timezone(timedelta(hours=8))
SESSIONS = [
    ("盘前竞价", 9, 0, 9, 30),
    ("上午盘",   9, 30, 12, 0),
    ("午间休市", 12, 0, 13, 0),
    ("下午盘",   13, 0, 16, 0),
    ("收市竞价", 16, 0, 16, 10),
]


def get_current_session():
    """判断当前交易时段"""
    now = datetime.now(HKT)
    weekday = now.weekday()  # 0=Mon, 6=Sun
    if weekday >= 5:
        return "周末休市"

    t = now.hour * 60 + now.minute
    for name, h1, m1, h2, m2 in SESSIONS:
        start = h1 * 60 + m1
        end = h2 * 60 + m2
        if start <= t < end:
            return name

    if t < 9 * 60:
        return "盘前"
    elif t >= 16 * 60 + 10:
        return "盘后"
    return "非交易时段"


def fetch_url(url, encoding="gbk"):
    """通用 URL 请求"""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Linux; rv:109.0) Gecko/20100101 Firefox/115.0",
        "Referer": "https://stockapp.finance.qq.com/",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode(encoding, errors="replace")
    except urllib.error.URLError as e:
        return None


def parse_realtime_quote():
    """
    解析腾讯实时报价 (港股格式)
    v_r_hk06055="100~中烟香港~06055~39.300~39.060~38.900~1656296.0~...~..."
    字段索引 (港股):
      0=市场代码, 1=名称, 2=代码, 3=现价, 4=昨收, 5=今开,
      6=成交量, 29=成交量(重复), 30=行情时间,
      31=涨跌额, 32=涨跌幅%, 33=最高, 34=最低,
      35=现价(重复), 36=成交量(重复), 37=成交额
    """
    raw = fetch_url(REALTIME_URL)
    if not raw:
        return None

    # 提取引号内的数据
    m = re.search(r'"([^"]+)"', raw)
    if not m:
        return None

    fields = m.group(1).split("~")
    if len(fields) < 38:
        return None

    try:
        current_price = float(fields[3]) if fields[3] else 0
        prev_close = float(fields[4]) if fields[4] else 0
        open_price = float(fields[5]) if fields[5] else 0
        volume = float(fields[6]) if fields[6] else 0       # 成交量（股）
        high = float(fields[33]) if fields[33] else 0
        low = float(fields[34]) if fields[34] else 0
        turnover = float(fields[37]) if fields[37] else 0   # 成交额（港元）
        change = float(fields[31]) if fields[31] else 0
        change_pct = float(fields[32]) if fields[32] else 0

        return {
            "code": STOCK_CODE,
            "name": fields[1] if len(fields) > 1 else STOCK_NAME,
            "current_price": current_price,
            "prev_close": prev_close,
            "open": open_price,
            "high": high,
            "low": low,
            "change": round(change, 3),
            "change_pct": round(change_pct, 2),
            "volume": int(volume),
            "turnover": round(turnover, 2),
        }
    except (ValueError, IndexError):
        return None


def fetch_kline_data():
    """获取日K线数据，用于计算均量"""
    raw = fetch_url(KLINE_URL, encoding="utf-8")
    if not raw:
        return []

    try:
        data = json.loads(raw)
        kline = data.get("data", {}).get(f"hk{STOCK_CODE}", {})
        # 尝试多种 key
        days = kline.get("qfqday") or kline.get("day") or []
        return days
    except (json.JSONDecodeError, AttributeError):
        return []


def calc_avg_volume(kline_data, days=VOLUME_AVG_DAYS):
    """计算近 N 日平均成交量"""
    if not kline_data:
        return 0
    recent = kline_data[-days:]
    volumes = []
    for row in recent:
        if len(row) >= 6:
            try:
                volumes.append(float(row[5]))
            except (ValueError, TypeError):
                pass
    return sum(volumes) / len(volumes) if volumes else 0


def calc_ma60(kline_data):
    """计算MA60"""
    if len(kline_data) < 60:
        return None
    closes = []
    for row in kline_data[-60:]:
        try:
            closes.append(float(row[2]))  # 收盘价
        except (ValueError, TypeError, IndexError):
            pass
    return sum(closes) / len(closes) if closes else None


def check_strategy_signal(quote, avg_volume, kline_data):
    """
    放量突破策略（回测胜率88%，回撤12%）
    - 底仓2000股不动
    - 波段1000股：放量+涨>2%加仓，放量跌>3%减仓
    - 硬止损：跌破MA60全部减到底仓
    """
    if not STRATEGY_ENABLED:
        return None

    signals = []
    vol_ratio = quote["volume"] / avg_volume if avg_volume > 0 else 0
    change_pct = quote["change_pct"]

    # MA60 止损检查
    if MA60_STOP_LOSS:
        ma60 = calc_ma60(kline_data)
        if ma60 and quote["current_price"] < ma60:
            signals.append({
                "type": "strategy_stop_loss",
                "level": "critical",
                "action": "减仓至底仓",
                "message": f"🚨 跌破MA60({ma60:.3f})！建议减仓至底仓{BASE_POSITION}股",
                "detail": f"现价{quote['current_price']:.3f} < MA60({ma60:.3f})，趋势转空",
            })
            return signals  # 止损优先级最高

    # 放量突破买入信号
    if vol_ratio >= STRATEGY_BUY_VOL_RATIO and change_pct >= STRATEGY_BUY_CHANGE_PCT:
        buy_shares = min(SWING_POSITION, LOT_SIZE * 3)  # 最多加3手
        signals.append({
            "type": "strategy_buy",
            "level": "info",
            "action": f"可加仓{buy_shares}股",
            "message": f"🟢 放量突破信号：量比{vol_ratio:.1f}x + 涨{change_pct:+.1f}%",
            "detail": f"回测胜率88%的买入条件触发。波段仓位可加{buy_shares}股（{buy_shares}×{quote['current_price']:.2f}=HK${buy_shares*quote['current_price']:,.0f}）",
        })

    # 放量下跌卖出信号
    if vol_ratio >= STRATEGY_SELL_VOL_RATIO and change_pct <= STRATEGY_SELL_CHANGE_PCT:
        sell_shares = min(SWING_POSITION, LOT_SIZE * 3)
        signals.append({
            "type": "strategy_sell",
            "level": "warning",
            "action": f"建议减{sell_shares}股",
            "message": f"🔴 放量下跌信号：量比{vol_ratio:.1f}x + 跌{change_pct:.1f}%",
            "detail": f"波段仓位建议减{sell_shares}股，保留底仓{BASE_POSITION}股",
        })

    return signals if signals else None


def check_alerts(quote, avg_volume):
    """检查是否需要告警"""
    alerts = []

    # 涨跌幅告警
    if abs(quote["change_pct"]) >= CHANGE_ALERT_PCT:
        direction = "📈 大涨" if quote["change_pct"] > 0 else "📉 大跌"
        alerts.append({
            "type": "price_change",
            "level": "warning",
            "message": f"{direction} {quote['change_pct']:+.2f}%",
        })

    # 成交量异常
    if avg_volume > 0 and quote["volume"] > 0:
        vol_ratio = quote["volume"] / avg_volume
        if vol_ratio >= VOLUME_ALERT_RATIO:
            alerts.append({
                "type": "volume_spike",
                "level": "warning",
                "message": f"🔥 成交量异常: 当前 {quote['volume']:,} 股，均量 {int(avg_volume):,} 股，{vol_ratio:.1f}倍",
            })

    return alerts


def build_result(quote, avg_volume, alerts, session):
    """构建输出结果"""
    now = datetime.now(HKT)

    # 盈亏计算
    pnl = POSITION * quote["change"] if quote["change"] else 0
    pnl_from_open = POSITION * (quote["current_price"] - quote["open"]) if quote["open"] else 0

    result = {
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "session": session,
        "stock": {
            "code": quote["code"],
            "name": quote["name"],
            "price": quote["current_price"],
            "prev_close": quote["prev_close"],
            "open": quote["open"],
            "high": quote["high"],
            "low": quote["low"],
            "change": quote["change"],
            "change_pct": quote["change_pct"],
            "volume": quote["volume"],
            "turnover": quote["turnover"],
            "avg_volume_20d": int(avg_volume) if avg_volume else None,
        },
        "position": {
            "shares": POSITION,
            "market_value": round(POSITION * quote["current_price"], 2),
            "pnl_today": round(pnl, 2),
            "pnl_from_open": round(pnl_from_open, 2),
        },
        "alerts": alerts,
        "has_alert": len(alerts) > 0,
    }
    return result


def format_human(result):
    """人类可读格式输出"""
    s = result["stock"]
    p = result["position"]
    lines = [
        f"{'='*44}",
        f"  {s['name']} ({s['code']})  |  {result['session']}",
        f"  {result['timestamp']}",
        f"{'='*44}",
        f"",
        f"  💰 现价: {s['price']:.3f} HKD",
        f"  📊 涨跌: {s['change']:+.3f} ({s['change_pct']:+.2f}%)",
        f"  📈 今开: {s['open']:.3f}  最高: {s['high']:.3f}  最低: {s['low']:.3f}",
        f"  📉 昨收: {s['prev_close']:.3f}",
        f"  🔄 成交量: {s['volume']:,} 股",
        f"  💵 成交额: {s['turnover']:,.0f} HKD",
    ]

    if s["avg_volume_20d"]:
        vol_ratio = s["volume"] / s["avg_volume_20d"] if s["avg_volume_20d"] > 0 else 0
        lines.append(f"  📊 20日均量: {s['avg_volume_20d']:,} 股 (今日 {vol_ratio:.1f}x)")

    lines += [
        f"",
        f"  ── 持仓 ({p['shares']} 股) ──",
        f"  💼 市值: {p['market_value']:,.2f} HKD",
        f"  {'🟢' if p['pnl_today'] >= 0 else '🔴'} 今日盈亏: {p['pnl_today']:+,.2f} HKD",
    ]

    if result["alerts"]:
        lines += [f"", f"  ⚠️  告警:"]
        for a in result["alerts"]:
            lines.append(f"    • {a['message']}")

    lines.append(f"{'='*44}")
    return "\n".join(lines)


def main():
    human_mode = "--human" in sys.argv

    session = get_current_session()

    # 获取实时报价
    quote = parse_realtime_quote()
    if not quote:
        err = {"error": "无法获取实时报价", "timestamp": datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")}
        if human_mode:
            print("❌ 无法获取实时报价，请检查网络或稍后重试")
        else:
            print(json.dumps(err, ensure_ascii=False))
        sys.exit(1)

    # 获取K线计算均量
    kline = fetch_kline_data()
    avg_volume = calc_avg_volume(kline)

    # 检查告警
    alerts = check_alerts(quote, avg_volume)

    # 检查策略信号
    strategy_signals = check_strategy_signal(quote, avg_volume, kline)
    if strategy_signals:
        alerts.extend(strategy_signals)

    # 构建结果
    result = build_result(quote, avg_volume, alerts, session)

    if human_mode:
        print(format_human(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
