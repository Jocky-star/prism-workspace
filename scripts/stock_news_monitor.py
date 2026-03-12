#!/home/mi/.openclaw/skills/a-share-monitor/.venv/bin/python3
# -*- coding: utf-8 -*-
"""
股票消息面监控脚本
- 获取持仓股票的个股新闻和公告
- 获取市场重要快讯
- 重要性过滤 + 去重
- 输出格式兼容高频盯盘系统

快速模式 (--quick):
- 只扫高优先级突发关键词（停牌、重组、退市、ST、监管处罚等）
- 只看最近 1 小时的新闻
- 输出更精简，仅 high 优先级消息
"""

import argparse
import json
import hashlib
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import akshare as ak
import requests
import pandas as pd

# ============ 配置 ============

# 持仓列表（从 JSON 文件读取，单一数据源）
POSITION_FILE = "/home/mi/.openclaw/workspace/data/current_position.json"

def _load_portfolio():
    try:
        with open(POSITION_FILE) as f:
            data = json.load(f)
        a, hk = [], []
        for p in data.get("positions", []):
            if p.get("market") == "hk":
                hk.append({"code": p["code"], "name": p["name"]})
            else:
                mkt = "sz" if p["code"].startswith(("0", "1", "3")) else "sh"
                a.append({"code": p["code"], "name": p["name"], "market": mkt})
        return a, hk
    except Exception as e:
        print(f"⚠️ 读取持仓失败: {e}", file=sys.stderr)
        return [], []

PORTFOLIO, HK_PORTFOLIO = _load_portfolio()

# 状态文件（去重用）
STATE_FILE = "/home/mi/.openclaw-2/workspace/data/stock_news_state.json"

# 快速模式专用高优先级关键词（突发、重大事件）
QUICK_MODE_KEYWORDS = [
    "停牌", "复牌",
    "重组", "并购", "借壳",
    "退市", "退市风险", "*ST", "ST",
    "监管处罚", "行政处罚", "处罚决定", "立案调查", "立案",
    "监管函", "关注函", "监管问询", "问询函",
    "业绩暴雷", "业绩大幅下滑", "业绩预亏",
    "实控人变更", "控制权变更",
    "重大合同", "重大资产",
    "诉讼", "仲裁",
    "股权冻结", "账户冻结",
    "分拆上市",
]

# 高优先级公告关键词
HIGH_PRIORITY_KEYWORDS = [
    "年报", "半年报", "季报", "业绩预告", "业绩快报",
    "重大事项", "股权激励", "回购", "增持", "减持",
    "并购", "重组", "停牌", "复牌", "退市",
    "诉讼", "仲裁", "处罚", "违规", "风险提示",
    # 2026-03-11 补充
    "定增", "非公开发行",
    "实控人变更", "控制权变更",
    "监管问询", "监管函", "关注函",
    "大宗交易",
    "战略合作", "签署合同",
    "分拆上市",
    "股权质押",
    "退市风险", "*ST",
]

# 中优先级关键词
MEDIUM_PRIORITY_KEYWORDS = [
    "产销快报", "投资", "战略合作", "中标", "签约",
    "新产品", "专利", "研发", "分红", "配股",
]

# 忽略的低优先级关键词
IGNORE_KEYWORDS = [
    "证券变动月报", "章程修订", "会议通知", "董事会决议",
    "监事会决议", "独立董事意见", "法律意见书",
    # 2026-03-11 补充
    "投资者关系活动",
    "可转债",
    "限售股解禁",
]


# ============ 状态管理 ============

def load_state():
    """加载已推送的消息 hash"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
            # 清理超过 7 天的记录
            cutoff = time.time() - 7 * 86400
            data = {k: v for k, v in data.items() if v > cutoff}
            return data
        except Exception:
            return {}
    return {}


def save_state(state):
    """保存状态"""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def make_hash(text):
    """生成文本 hash"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]


def is_new(state, text):
    """检查是否是新消息"""
    h = make_hash(text)
    if h in state:
        return False
    state[h] = time.time()
    return True


# ============ 数据获取 ============

def fetch_stock_news(code, name):
    """获取个股新闻（东方财富）"""
    results = []
    try:
        df = ak.stock_news_em(symbol=code)
        if df is not None and not df.empty:
            for _, row in df.head(10).iterrows():
                title = str(row.get("新闻标题", ""))
                source = str(row.get("文章来源", ""))
                pub_time = str(row.get("发布时间", ""))
                content = str(row.get("新闻内容", ""))[:200]
                results.append({
                    "type": "news",
                    "stock": name,
                    "code": code,
                    "title": title,
                    "source": source,
                    "time": pub_time,
                    "summary": content,
                })
    except Exception as e:
        pass  # 静默失败，不影响其他股票
    return results


def fetch_announcements_em(code, name):
    """通过东方财富 API 获取公告"""
    results = []
    try:
        url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
        params = {
            "sr": -1,
            "page_size": 10,
            "page_index": 1,
            "ann_type": "SHA,SZA",
            "client_source": "web",
            "stock_list": code,
            "f_node": 0,
            "s_node": 0,
        }
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        data = resp.json()
        
        for item in data.get("data", {}).get("list", []):
            title = item.get("title", "")
            ann_date = item.get("notice_date", "")
            if ann_date:
                ann_date = ann_date[:10]
            results.append({
                "type": "announcement",
                "stock": name,
                "code": code,
                "title": title,
                "time": ann_date,
                "source": "巨潮资讯",
                "summary": "",
            })
    except Exception:
        pass
    return results



# ── 巨潮资讯 API 相关 ──────────────────────────────────────────────────
# 巨潮使用 orgId（而非直接股票代码）查询公告；先用 suggest API 解析 orgId。
_cninfo_orgid_cache: dict = {}  # 简单内存缓存，避免重复请求


def _cninfo_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": "http://www.cninfo.com.cn",
    }


def _get_cninfo_orgid(code: str) -> tuple[str, str]:
    """
    返回 (orgId, column)。
    column: 'szse' 为深交所/创业板/北交所，'sse' 为上交所/科创板。
    失败时返回 ('', '')。
    """
    if code in _cninfo_orgid_cache:
        return _cninfo_orgid_cache[code]
    try:
        url = "http://www.cninfo.com.cn/new/information/topSearch/query"
        resp = requests.post(
            url,
            data={"keyWord": code, "maxNum": 5},
            headers=_cninfo_headers(),
            timeout=8,
        )
        items = resp.json()
        # 精确匹配 code
        for item in items:
            if item.get("code") == code:
                org_id = item.get("orgId", "")
                # 根据 orgId 前缀判断交易所
                if org_id.startswith("gssh") or code.startswith("6") or code.startswith("9"):
                    column = "sse"
                else:
                    column = "szse"
                _cninfo_orgid_cache[code] = (org_id, column)
                return org_id, column
    except Exception:
        pass
    _cninfo_orgid_cache[code] = ("", "")
    return "", ""


def fetch_cninfo_announcements(code: str, name: str) -> list[dict]:
    """
    从巨潮资讯网获取指定股票的最新公告（最多 10 条）。
    - 使用公开的 hisAnnouncement/query 接口（无需登录）
    - 反爬处理：User-Agent + Referer
    - 失败静默返回空列表，不影响东财流程
    """
    results = []
    try:
        org_id, column = _get_cninfo_orgid(code)
        if not org_id:
            return results  # 无法解析 orgId，跳过

        url = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
        data = {
            "stock": f"{code},{org_id}",
            "tabName": "fulltext",
            "pageSize": 10,
            "pageNum": 1,
            "column": column,
            "category": "",
            "plate": "",
            "seDate": "",
            "searchkey": "",
            "secid": "",
            "sortName": "time",
            "sortType": "desc",
            "isHLtitle": "true",
        }
        resp = requests.post(
            url,
            data=data,
            headers=_cninfo_headers(),
            timeout=10,
        )
        result = resp.json()
        announcements = result.get("announcements") or []
        for ann in announcements:
            title = ann.get("announcementTitle", "")
            ts = ann.get("announcementTime")
            ann_date = (
                datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
                if ts else ""
            )
            results.append({
                "type": "announcement",
                "stock": name,
                "code": code,
                "title": title,
                "time": ann_date,
                "source": "巨潮资讯",
                "summary": "",
            })
    except Exception:
        pass  # 静默失败，不影响主流程
    return results
# ────────────────────────────────────────────────────────────────────────


def fetch_market_news():
    """获取市场快讯"""
    results = []
    try:
        df = ak.stock_info_global_em()
        if df is not None and not df.empty:
            for _, row in df.head(15).iterrows():
                title = str(row.get("标题", ""))
                pub_time = str(row.get("发布时间", ""))
                summary = str(row.get("摘要", ""))[:150]
                results.append({
                    "type": "market",
                    "stock": "市场",
                    "code": "",
                    "title": title,
                    "source": "东方财富",
                    "time": pub_time,
                    "summary": summary,
                })
    except Exception:
        pass
    return results


def fetch_hk_news(code, name):
    """港股新闻（通过东方财富搜索）"""
    results = []
    try:
        # 用东方财富搜索 API
        url = f"https://search-api-web.eastmoney.com/search/jsonp"
        params = {
            "cb": "jQuery",
            "param": json.dumps({
                "uid": "",
                "keyword": name,
                "type": ["cmsArticleWebOld"],
                "client": "web",
                "clientType": "web",
                "clientVersion": "curr",
                "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "default", "pageIndex": 1, "pageSize": 5}},
            }),
        }
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://so.eastmoney.com/"}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        text = resp.text
        # 解析 JSONP
        if text.startswith("jQuery"):
            json_str = text[text.index("(") + 1:text.rindex(")")]
            data = json.loads(json_str)
            items = data.get("result", {}).get("cmsArticleWebOld", {}).get("list", [])
            for item in items:
                title = item.get("title", "").replace("<em>", "").replace("</em>", "")
                pub_time = item.get("date", "")
                results.append({
                    "type": "news",
                    "stock": name,
                    "code": code,
                    "title": title,
                    "source": "东方财富",
                    "time": pub_time,
                    "summary": "",
                })
    except Exception:
        pass
    return results


# ============ 过滤和分析 ============

def get_priority(item):
    """判断消息优先级：high/medium/low/ignore
    
    顺序：HIGH_PRIORITY 先于 IGNORE，避免重要消息被误杀。
    """
    title = item.get("title", "")

    # 高优先级优先检查（避免被 IGNORE 误杀）
    for kw in HIGH_PRIORITY_KEYWORDS:
        if kw in title:
            return "high"

    # 再检查忽略
    for kw in IGNORE_KEYWORDS:
        if kw in title:
            return "ignore"

    # 中优先级
    for kw in MEDIUM_PRIORITY_KEYWORDS:
        if kw in title:
            return "medium"

    return "low"


def filter_items(items, state):
    """过滤：去重 + 优先级筛选"""
    filtered = []
    for item in items:
        priority = get_priority(item)
        if priority == "ignore":
            continue
        
        # 去重：用 title + stock 做 hash
        key = f"{item['stock']}:{item['title']}"
        if not is_new(state, key):
            continue
        
        item["priority"] = priority
        filtered.append(item)
    
    # 按优先级排序
    priority_order = {"high": 0, "medium": 1, "low": 2}
    filtered.sort(key=lambda x: priority_order.get(x["priority"], 3))
    
    return filtered


def is_within_hours(time_str, hours=1):
    """判断时间字符串是否在最近 N 小时内"""
    if not time_str:
        return True  # 无时间信息，默认包含
    try:
        # 尝试多种时间格式
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(time_str.strip(), fmt)
                cutoff = datetime.now() - timedelta(hours=hours)
                return dt >= cutoff
            except ValueError:
                continue
    except Exception:
        pass
    return True  # 解析失败，默认包含


def filter_items_quick(items, state):
    """快速模式过滤：只保留高优先级突发关键词 + 最近 1 小时"""
    filtered = []
    for item in items:
        title = item.get("title", "")
        # 只看快速模式关键词
        matched = any(kw in title for kw in QUICK_MODE_KEYWORDS)
        if not matched:
            continue
        
        # 只看最近 1 小时
        if not is_within_hours(item.get("time", ""), hours=1):
            continue
        
        # 去重（快速模式用独立前缀避免影响正常模式 state）
        key = f"quick:{item['stock']}:{item['title']}"
        if not is_new(state, key):
            continue
        
        item["priority"] = "high"
        filtered.append(item)
    
    return filtered


def format_output_quick(items):
    """快速模式精简输出"""
    if not items:
        return None
    
    lines = [f"⚡ 快速监控 [{datetime.now().strftime('%H:%M')}] 发现 {len(items)} 条重大消息\n"]
    for item in items:
        emoji = "📢" if item["type"] == "announcement" else "📰"
        lines.append(f"{emoji} 【{item['stock']}】{item['title']}")
        if item.get("summary"):
            lines.append(f"   └─ {item['summary'][:80]}")
    lines.append("\n⚠️ 快速模式·仅高优先级·最近1小时")
    
    return "\n".join(lines)


# ============ 输出格式化 ============

def format_output(items):
    """格式化输出"""
    if not items:
        return None
    
    lines = ["📰 消息面监控提醒\n"]
    
    # 按类型分组
    high_items = [i for i in items if i["priority"] == "high"]
    medium_items = [i for i in items if i["priority"] == "medium"]
    news_items = [i for i in items if i["priority"] == "low" and i["type"] == "news"]
    market_items = [i for i in items if i["type"] == "market"]
    
    if high_items:
        lines.append("🔴 **重要公告/新闻**")
        for item in high_items:
            emoji = "📢" if item["type"] == "announcement" else "📰"
            lines.append(f"  {emoji} 【{item['stock']}】{item['title']}")
            if item.get("summary"):
                lines.append(f"     └─ {item['summary'][:100]}")
        lines.append("")
    
    if medium_items:
        lines.append("🟡 **值得关注**")
        for item in medium_items:
            lines.append(f"  📌 【{item['stock']}】{item['title']}")
        lines.append("")
    
    if news_items:
        lines.append("📋 **个股动态**")
        for item in news_items[:5]:  # 最多显示 5 条
            lines.append(f"  • 【{item['stock']}】{item['title']}")
        if len(news_items) > 5:
            lines.append(f"  ... 还有 {len(news_items) - 5} 条")
        lines.append("")
    
    if market_items:
        lines.append("🌐 **市场快讯**")
        for item in market_items[:3]:  # 最多 3 条
            lines.append(f"  • {item['title']}")
        lines.append("")
    
    lines.append("⚠️ 以上为自动采集的消息面信息，仅供参考。")
    
    return "\n".join(lines)


# ============ 主入口 ============

def main():
    parser = argparse.ArgumentParser(description="股票消息面监控")
    parser.add_argument("--quick", action="store_true",
                        help="快速模式：只扫高优先级突发关键词，只看最近1小时，输出精简")
    args = parser.parse_args()

    state = load_state()
    all_items = []
    
    if args.quick:
        # ── 快速模式：只拉公告（最快、最权威），跳过新闻和市场快讯 ──
        for stock in PORTFOLIO:
            items = fetch_announcements_em(stock["code"], stock["name"])
            all_items.extend(items)
            time.sleep(0.2)

        # 巨潮公告（快速模式同样拉，权威性更高）
        for stock in PORTFOLIO:
            try:
                items = fetch_cninfo_announcements(stock["code"], stock["name"])
                all_items.extend(items)
            except Exception:
                pass
            time.sleep(0.3)
        
        # 也拉个股新闻（head(5) 已在函数里限制）
        for stock in PORTFOLIO:
            items = fetch_stock_news(stock["code"], stock["name"])
            all_items.extend(items)
            time.sleep(0.3)
        
        filtered = filter_items_quick(all_items, state)
        save_state(state)
        
        if filtered:
            output = format_output_quick(filtered)
            if output:
                print(output)
            else:
                print("HEARTBEAT_OK")
        else:
            print("HEARTBEAT_OK")
        return

    # ── 正常模式 ──
    # 1. A 股个股新闻
    for stock in PORTFOLIO:
        items = fetch_stock_news(stock["code"], stock["name"])
        all_items.extend(items)
        time.sleep(0.5)  # 避免请求过快
    
    # 2. A 股公告（东方财富）
    for stock in PORTFOLIO:
        items = fetch_announcements_em(stock["code"], stock["name"])
        all_items.extend(items)
        time.sleep(0.3)

    # 3. A 股公告（巨潮资讯，官方数据源，与东财合并去重）
    for stock in PORTFOLIO:
        try:
            items = fetch_cninfo_announcements(stock["code"], stock["name"])
            all_items.extend(items)
        except Exception:
            pass
        time.sleep(0.4)
    
    # 4. 港股新闻
    for stock in HK_PORTFOLIO:
        items = fetch_hk_news(stock["code"], stock["name"])
        all_items.extend(items)
    
    # 5. 市场快讯
    market = fetch_market_news()
    all_items.extend(market)
    
    # 6. 过滤（去重由 filter_items 内的 is_new 处理，东财+巨潮同标题自动合并）
    filtered = filter_items(all_items, state)
    
    # 7. 保存状态
    save_state(state)
    
    # 8. 输出
    if filtered:
        output = format_output(filtered)
        if output:
            print(output)
        else:
            print("HEARTBEAT_OK")
    else:
        print("HEARTBEAT_OK")


if __name__ == "__main__":
    main()
