#!/usr/bin/env python3
"""
双因子月度调仓信号监控脚本
利率方向 × 通胀方向 → 主配资产建议

因子1 利率方向：国债ETF 511010 收盘价 vs MA20
  收盘 > MA20 → 利率下行（宽松）
  收盘 < MA20 → 利率上行（紧缩）

因子2 通胀方向：有色金属ETF 512400 + 白银ETF 159869（备选黄金ETF 518880）的20日动量均值
  均值 > 3% → 高通胀
  均值 ≤ 3% → 低通胀
"""

import json
import urllib.request
import urllib.error
from datetime import datetime, date

# ─── 配置 ───────────────────────────────────────────
FUZZY_THRESHOLD = 0.005   # ±0.5% 信号模糊区间
INFLATION_THRESHOLD = 0.03  # 3% 通胀分界线
MA_PERIOD = 20
MOMENTUM_PERIOD = 20

# ETF secid
SECID_BOND_ETF    = "1.511010"   # 国债ETF（上海）
SECID_METAL_ETF   = "1.512400"   # 有色金属ETF（上海）
SECID_SILVER_ETF  = "0.159869"   # 白银ETF（深圳，可能无数据）
SECID_GOLD_ETF    = "1.518880"   # 黄金ETF（上海，备选）

# 当前持仓（从 JSON 文件读取，单一数据源）
POSITION_FILE = "/home/mi/.openclaw/workspace/data/current_position.json"

def _load_positions():
    try:
        with open(POSITION_FILE) as f:
            data = json.load(f)
        return [{"name": p["name"], "code": p["code"] + (".HK" if p.get("market") == "hk" else ""), "shares": p.get("shares", 0)} for p in data.get("positions", [])]
    except Exception:
        return []

CURRENT_POSITIONS = _load_positions()

# 四象限配置建议
SIGNAL_MAP = {
    ("宽松", "高通胀"): {
        "asset": "黄金",
        "etf": "518880（黄金ETF）",
        "monthly_return": "+5.35%",
        "win_rate": "83%",
    },
    ("紧缩", "高通胀"): {
        "asset": "有色金属/商品",
        "etf": "512400（有色金属ETF）",
        "monthly_return": "+12.33%",
        "win_rate": "100%",
    },
    ("宽松", "低通胀"): {
        "asset": "30年国债",
        "etf": "511090（30年国债ETF）",
        "monthly_return": "+2.34%",
        "win_rate": "83%",
    },
    ("紧缩", "低通胀"): {
        "asset": "股票（沪深300）",
        "etf": "510300（沪深300ETF）",
        "monthly_return": "+2.35%",
        "win_rate": "—",
    },
}

# ─── 数据获取 ────────────────────────────────────────
def fetch_kline(secid: str, limit: int = 30) -> list[dict]:
    """从东财拉日K线，返回最近 limit 根，每条含 date/close"""
    today_str = datetime.now().strftime("%Y%m%d")
    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={secid}"
        f"&fields1=f1,f2,f3,f4,f5,f6"
        f"&fields2=f51,f52,f53,f54,f55,f56"
        f"&klt=101&fqt=1"
        f"&end={today_str}"
        f"&lmt={limit}"
    )
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://finance.eastmoney.com/",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return []

    klines = data.get("data", {})
    if not klines:
        return []
    raw_list = klines.get("klines", [])
    result = []
    for item in raw_list:
        parts = item.split(",")
        if len(parts) >= 3:
            try:
                result.append({"date": parts[0], "close": float(parts[2])})
            except ValueError:
                pass
    return result


def calc_ma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def calc_momentum(closes: list[float], period: int) -> float | None:
    """动量 = (最新收盘 - period天前收盘) / period天前收盘"""
    if len(closes) <= period:
        return None
    old = closes[-(period + 1)]
    if old == 0:
        return None
    return (closes[-1] - old) / old


# ─── 主逻辑 ──────────────────────────────────────────
def main():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = []
    lines.append(f"📊 **双因子月度调仓信号** | {now_str}")
    lines.append("=" * 40)

    # ── 因子1：利率方向 ──────────────────────────────
    bond_bars = fetch_kline(SECID_BOND_ETF, limit=30)
    if len(bond_bars) < MA_PERIOD + 1:
        lines.append("⚠️ 国债ETF(511010) 数据不足，无法计算利率因子")
        rate_signal = None
        rate_fuzzy = False
    else:
        bond_closes = [b["close"] for b in bond_bars]
        bond_close  = bond_closes[-1]
        bond_ma20   = calc_ma(bond_closes, MA_PERIOD)
        diff_ratio  = (bond_close - bond_ma20) / bond_ma20

        if abs(diff_ratio) <= FUZZY_THRESHOLD:
            rate_signal = None
            rate_fuzzy  = True
            rate_desc   = f"模糊({diff_ratio:+.2%}，在±0.5%内)"
        elif bond_close > bond_ma20:
            rate_signal = "宽松"
            rate_fuzzy  = False
            rate_desc   = f"下行/宽松（收盘{bond_close:.4f} > MA20 {bond_ma20:.4f}，偏{diff_ratio:+.2%}）"
        else:
            rate_signal = "紧缩"
            rate_fuzzy  = False
            rate_desc   = f"上行/紧缩（收盘{bond_close:.4f} < MA20 {bond_ma20:.4f}，偏{diff_ratio:+.2%}）"

        lines.append(f"\n**因子1 利率方向**：{rate_desc}")
        lines.append(f"  国债ETF 511010 最新：{bond_close:.4f}  MA20：{bond_ma20:.4f}")

    # ── 因子2：通胀方向 ──────────────────────────────
    metal_bars  = fetch_kline(SECID_METAL_ETF,  limit=30)
    silver_bars = fetch_kline(SECID_SILVER_ETF, limit=30)
    gold_bars   = fetch_kline(SECID_GOLD_ETF,   limit=30)

    momentum_list = []
    momentum_labels = []

    # 有色金属
    if len(metal_bars) > MOMENTUM_PERIOD:
        mc = [b["close"] for b in metal_bars]
        m  = calc_momentum(mc, MOMENTUM_PERIOD)
        if m is not None:
            momentum_list.append(m)
            momentum_labels.append(f"有色金属512400={m:+.2%}")

    # 白银（优先），无数据则用黄金
    if len(silver_bars) > MOMENTUM_PERIOD:
        sc = [b["close"] for b in silver_bars]
        m  = calc_momentum(sc, MOMENTUM_PERIOD)
        if m is not None:
            momentum_list.append(m)
            momentum_labels.append(f"白银159869={m:+.2%}")
    elif len(gold_bars) > MOMENTUM_PERIOD:
        gc = [b["close"] for b in gold_bars]
        m  = calc_momentum(gc, MOMENTUM_PERIOD)
        if m is not None:
            momentum_list.append(m)
            momentum_labels.append(f"黄金518880(备选)={m:+.2%}")

    if not momentum_list:
        lines.append("\n⚠️ 通胀因子数据不足")
        inflation_signal = None
        inflation_fuzzy  = False
    else:
        avg_momentum = sum(momentum_list) / len(momentum_list)
        diff_from_threshold = avg_momentum - INFLATION_THRESHOLD

        if abs(diff_from_threshold) <= FUZZY_THRESHOLD:
            inflation_signal = None
            inflation_fuzzy  = True
            inf_desc         = f"模糊（均值{avg_momentum:+.2%}，在3%±0.5%内）"
        elif avg_momentum > INFLATION_THRESHOLD:
            inflation_signal = "高通胀"
            inflation_fuzzy  = False
            inf_desc         = f"高通胀（20日动量均值{avg_momentum:+.2%} > 3%）"
        else:
            inflation_signal = "低通胀"
            inflation_fuzzy  = False
            inf_desc         = f"低通胀（20日动量均值{avg_momentum:+.2%} ≤ 3%）"

        lines.append(f"\n**因子2 通胀方向**：{inf_desc}")
        lines.append(f"  分量：{' | '.join(momentum_labels)}")

    # ── 综合信号 ─────────────────────────────────────
    lines.append("\n" + "=" * 40)
    any_fuzzy = rate_fuzzy or inflation_fuzzy

    if any_fuzzy or rate_signal is None or inflation_signal is None:
        lines.append("\n⚠️ **信号模糊，建议维持现有配置**")
        if rate_fuzzy:
            lines.append("  - 利率因子在分界线±0.5%以内")
        if inflation_fuzzy:
            lines.append("  - 通胀因子在3%±0.5%以内")
        if rate_signal is None and not rate_fuzzy:
            lines.append("  - 利率因子数据不足")
        if inflation_signal is None and not inflation_fuzzy:
            lines.append("  - 通胀因子数据不足")
        recommended_asset = None
        signal_info = None
    else:
        signal_key  = (rate_signal, inflation_signal)
        signal_info = SIGNAL_MAP[signal_key]
        recommended_asset = signal_info["asset"]

        lines.append(f"\n🎯 **当前信号：{rate_signal} × {inflation_signal}**")
        lines.append(f"   建议主配资产：**{recommended_asset}**（{signal_info['etf']}）")
        lines.append(f"   历史月均收益：{signal_info['monthly_return']}  胜率：{signal_info['win_rate']}")

    # ── 当前持仓 vs 建议 ─────────────────────────────
    lines.append("\n" + "─" * 40)
    lines.append("**当前持仓**")
    for p in CURRENT_POSITIONS:
        lines.append(f"  • {p['name']} {p['code']}  {p['shares']:,}股/份")

    if signal_info:
        lines.append("\n**调仓建议**")
        etf_code = signal_info["etf"].split("（")[0].strip()

        # 判断当前持仓里有没有目标标的
        target_codes = {
            "黄金":          ["518880", "519888"],
            "有色金属/商品": ["512400", "162412"],
            "30年国债":      ["511090", "511060"],
            "股票（沪深300）": ["510300", "159919"],
        }
        held_targets = []
        need_codes   = target_codes.get(recommended_asset, [])
        for p in CURRENT_POSITIONS:
            if any(nc in p["code"] for nc in need_codes):
                held_targets.append(p["name"])

        if held_targets:
            lines.append(f"  ✅ 已持有目标资产：{', '.join(held_targets)}")
            lines.append(f"  → 可适当加仓 {signal_info['etf']} 或维持不动")
        else:
            lines.append(f"  📌 目标资产未配置：{recommended_asset}")
            lines.append(f"  → 建议买入：{signal_info['etf']}")

        # 检查非目标持仓
        non_target = []
        for p in CURRENT_POSITIONS:
            if not any(nc in p["code"] for nc in need_codes):
                non_target.append(p["name"])
        if non_target:
            lines.append(f"  ⚖️  非目标持仓：{', '.join(non_target)}")
            lines.append(f"  → 视涨跌情况逐步减仓，资金转入{recommended_asset}")
    else:
        lines.append("\n**调仓建议**：信号模糊，维持现有仓位，下月再看")

    lines.append("\n" + "=" * 40)
    lines.append("📝 注：本信号基于20日均线/动量，月度参考，非日内操作依据")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
