#!/usr/bin/env python3
"""
股票消息面爬取工具
直接抓取财经网站，不需要任何 API key
来源：东方财富、新浪财经、财联社
"""

import urllib.request
import urllib.parse
import json
import re
import html as htmlmod
import sys
import time

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

POSITION_FILE = "/home/mi/.openclaw/workspace/data/current_position.json"

def _load_stock_map():
    try:
        with open(POSITION_FILE) as f:
            data = json.load(f)
        m = {}
        for p in data.get("positions", []):
            if p.get("market") == "hk":
                m[p["name"]] = {"code": p["code"], "market": "hk", "sina": "hk" + p["code"]}
            else:
                prefix = "sz" if p["code"].startswith(("0", "1", "3")) else "sh"
                m[p["name"]] = {"code": p["code"], "market": "sh", "sina": prefix + p["code"]}
        return m
    except Exception:
        return {}

STOCK_MAP = _load_stock_map()


def fetch_url(url, timeout=10):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            for enc in ['utf-8', 'gbk', 'gb2312', 'gb18030']:
                try:
                    return data.decode(enc)
                except:
                    continue
            return data.decode('utf-8', errors='replace')
    except Exception as e:
        return None


def get_eastmoney_news(stock_name, stock_info, limit=5):
    """从东方财富搜索 API 获取新闻"""
    results = []
    kw = urllib.parse.quote(stock_name)
    url = f"https://search-api-web.eastmoney.com/search/jsonp?cb=jQuery&param=%7B%22uid%22%3A%22%22%2C%22keyword%22%3A%22{kw}%22%2C%22type%22%3A%5B%22cmsArticleWebOld%22%5D%2C%22client%22%3A%22web%22%2C%22clientType%22%3A%22web%22%2C%22clientVersion%22%3A%22curr%22%2C%22param%22%3A%7B%22cmsArticleWebOld%22%3A%7B%22searchScope%22%3A%22default%22%2C%22sort%22%3A%22default%22%2C%22pageIndex%22%3A1%2C%22pageSize%22%3A{limit}%2C%22preTag%22%3A%22%22%2C%22postTag%22%3A%22%22%7D%7D%7D"
    content = fetch_url(url)
    if content:
        try:
            json_str = re.search(r'jQuery\((.*)\)', content)
            if json_str:
                data = json.loads(json_str.group(1))
                articles = data.get("result", {}).get("cmsArticleWebOld", [])
                if isinstance(articles, dict):
                    articles = articles.get("list", [])
                for item in articles[:limit]:
                    title = re.sub(r'<[^>]+>', '', item.get("title", ""))
                    results.append({
                        "title": htmlmod.unescape(title),
                        "source": "东方财富",
                        "url": item.get("url", ""),
                        "time": item.get("date", ""),
                    })
        except:
            pass
    return results[:limit]


def get_cls_news(stock_name, stock_info, limit=5):
    """从财联社获取新闻"""
    results = []
    url = f"https://www.cls.cn/api/sw?app=CailianpressWeb&os=web&q={urllib.parse.quote(stock_name)}&page=1&rn={limit}&type=article"
    content = fetch_url(url)
    if content:
        try:
            data = json.loads(content)
            for item in data.get("data", {}).get("article", {}).get("data", [])[:limit]:
                results.append({
                    "title": item.get("title", "") or item.get("brief", ""),
                    "source": "财联社",
                    "url": f"https://www.cls.cn/detail/{item.get('id', '')}",
                    "time": str(item.get("ctime", "")),
                })
        except:
            pass
    return results[:limit]


def get_sina_search(stock_name, limit=5):
    """从新浪搜索获取新闻"""
    results = []
    url = f"https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&k={urllib.parse.quote(stock_name)}&num={limit}&page=1"
    content = fetch_url(url)
    if content:
        try:
            data = json.loads(content)
            for item in data.get("result", {}).get("data", [])[:limit]:
                title = item.get("title", "")
                if stock_name[:2] in title:
                    results.append({
                        "title": title,
                        "source": "新浪财经",
                        "url": item.get("url", ""),
                        "time": item.get("ctime", ""),
                    })
        except:
            pass
    return results[:limit]


def fetch_stock_news(stock_name, limit=5):
    stock_info = STOCK_MAP.get(stock_name)
    if not stock_info:
        return []

    all_news = []
    for func in [get_eastmoney_news, get_cls_news, get_sina_search]:
        try:
            if func == get_sina_search:
                news = func(stock_name, limit=3)
            else:
                news = func(stock_name, stock_info, limit=3)
            all_news.extend(news)
        except:
            pass

    seen = set()
    unique = []
    for n in all_news:
        if n["title"] not in seen and n["title"]:
            seen.add(n["title"])
            unique.append(n)
    return unique[:limit]


if __name__ == "__main__":
    stocks = sys.argv[1:] if len(sys.argv) > 1 else list(STOCK_MAP.keys())
    
    for stock in stocks:
        print(f"\n{'='*50}")
        print(f"📰 {stock} 最新消息")
        print(f"{'='*50}")
        news = fetch_stock_news(stock, limit=5)
        if news:
            for i, n in enumerate(news, 1):
                print(f"  {i}. [{n['source']}] {n['title']}")
                if n.get('time'):
                    print(f"     ⏰ {n['time']}")
        else:
            print(f"  暂未获取到新闻")
        time.sleep(0.3)
