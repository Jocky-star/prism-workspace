#!/usr/bin/env python3
"""
跨平台比价 POC - 用 Selenium + Firefox 搜索 1688 和京东，对比价格差
使用方法: python3 price_compare_poc.py "蓝牙耳机"
"""

import sys
import json
import time
import re
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def create_driver():
    """创建 headless Firefox"""
    opts = Options()
    opts.add_argument("--headless")
    opts.set_preference("general.useragent.override",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0")
    svc = Service("/usr/local/bin/geckodriver")
    driver = webdriver.Firefox(options=opts, service=svc)
    driver.set_page_load_timeout(30)
    driver.implicitly_wait(5)
    return driver


def search_jd(driver, keyword):
    """京东搜索，提取商品名+价格"""
    results = []
    try:
        url = f"https://search.jd.com/Search?keyword={keyword}&enc=utf-8"
        driver.get(url)
        time.sleep(3)
        
        # 滚动加载
        driver.execute_script("window.scrollTo(0, 2000)")
        time.sleep(2)
        
        items = driver.find_elements(By.CSS_SELECTOR, ".gl-item, .gl-i-wrap, li.gl-item")
        if not items:
            # 京东新版布局
            items = driver.find_elements(By.CSS_SELECTOR, "[data-sku]")
        
        for item in items[:20]:
            try:
                # 价格
                price_el = item.find_element(By.CSS_SELECTOR, ".p-price i, .p-price .J_price")
                price = float(price_el.text.strip())
                # 商品名
                name_el = item.find_element(By.CSS_SELECTOR, ".p-name em, .p-name a")
                name = name_el.text.strip()[:60]
                # SKU
                sku = item.get_attribute("data-sku") or ""
                
                if name and price > 0:
                    results.append({
                        "platform": "京东",
                        "name": name,
                        "price": price,
                        "sku": sku,
                        "url": f"https://item.jd.com/{sku}.html" if sku else ""
                    })
            except:
                continue
    except Exception as e:
        print(f"[JD] 搜索失败: {e}", file=sys.stderr)
    
    return results


def search_1688(driver, keyword):
    """1688 搜索，提取商品名+价格"""
    results = []
    try:
        url = f"https://s.1688.com/selloffer/offer_search.htm?keywords={keyword}"
        driver.get(url)
        time.sleep(5)
        
        # 可能有验证码，尝试等待
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".offer-list-row, .sm-offer-item, [class*='offer']"))
            )
        except:
            pass
        
        driver.execute_script("window.scrollTo(0, 2000)")
        time.sleep(2)
        
        # 1688 新版布局
        items = driver.find_elements(By.CSS_SELECTOR, ".sm-offer-item, .offer-list-row .offer-list-item, [class*='OfferCard']")
        if not items:
            items = driver.find_elements(By.CSS_SELECTOR, "[data-aplus-clk]")
        
        for item in items[:20]:
            try:
                # 价格
                price_text = ""
                for sel in [".sm-offer-priceNum", ".price em", "[class*='price'] em", "[class*='Price']"]:
                    try:
                        el = item.find_element(By.CSS_SELECTOR, sel)
                        price_text = el.text.strip()
                        if price_text:
                            break
                    except:
                        continue
                
                if not price_text:
                    continue
                price = float(re.search(r'[\d.]+', price_text).group())
                
                # 商品名
                name = ""
                for sel in [".sm-offer-title", ".offer-title", "a[title]", "[class*='title'] a"]:
                    try:
                        el = item.find_element(By.CSS_SELECTOR, sel)
                        name = (el.get_attribute("title") or el.text).strip()[:60]
                        if name:
                            break
                    except:
                        continue
                
                if name and price > 0:
                    results.append({
                        "platform": "1688",
                        "name": name,
                        "price": price,
                        "url": ""
                    })
            except:
                continue
    except Exception as e:
        print(f"[1688] 搜索失败: {e}", file=sys.stderr)
    
    return results


def search_pdd(driver, keyword):
    """拼多多搜索"""
    results = []
    try:
        url = f"https://mobile.yangkeduo.com/search_result.html?search_key={keyword}"
        driver.get(url)
        time.sleep(5)
        
        driver.execute_script("window.scrollTo(0, 2000)")
        time.sleep(2)
        
        items = driver.find_elements(By.CSS_SELECTOR, "[class*='goods-item'], [class*='search-item']")
        
        for item in items[:20]:
            try:
                price_el = item.find_element(By.CSS_SELECTOR, "[class*='price']")
                price_text = price_el.text.strip()
                price = float(re.search(r'[\d.]+', price_text).group())
                
                name_el = item.find_element(By.CSS_SELECTOR, "[class*='name'], [class*='title']")
                name = name_el.text.strip()[:60]
                
                if name and price > 0:
                    results.append({
                        "platform": "拼多多",
                        "name": name,
                        "price": price,
                        "url": ""
                    })
            except:
                continue
    except Exception as e:
        print(f"[PDD] 搜索失败: {e}", file=sys.stderr)
    
    return results


def find_arbitrage(jd_items, source_items, source_name, min_margin=0.3):
    """找价差套利机会
    min_margin: 最低利润率（0.3 = 30%）
    """
    opportunities = []
    
    for src in source_items:
        for jd in jd_items:
            # 简单的名称相似度匹配（关键词重叠）
            src_words = set(re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9]+', src["name"].lower()))
            jd_words = set(re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9]+', jd["name"].lower()))
            overlap = len(src_words & jd_words)
            total = max(len(src_words | jd_words), 1)
            similarity = overlap / total
            
            if similarity > 0.3 and src["price"] > 0:
                margin = (jd["price"] - src["price"]) / src["price"]
                if margin >= min_margin:
                    opportunities.append({
                        "source": f"{source_name}: {src['name']}",
                        "source_price": src["price"],
                        "retail": f"京东: {jd['name']}",
                        "retail_price": jd["price"],
                        "margin": f"{margin:.0%}",
                        "profit_per_unit": round(jd["price"] - src["price"], 2),
                        "similarity": f"{similarity:.0%}"
                    })
    
    # 按利润率排序
    opportunities.sort(key=lambda x: x["profit_per_unit"], reverse=True)
    return opportunities


def main():
    keyword = sys.argv[1] if len(sys.argv) > 1 else "蓝牙耳机"
    print(f"\n🔍 搜索关键词: {keyword}")
    print("=" * 60)
    
    driver = create_driver()
    
    try:
        # 搜索各平台
        print(f"\n📦 搜索京东...")
        jd_items = search_jd(driver, keyword)
        print(f"  找到 {len(jd_items)} 个商品")
        
        print(f"\n🏭 搜索 1688...")
        ali_items = search_1688(driver, keyword)
        print(f"  找到 {len(ali_items)} 个商品")
        
        print(f"\n🛒 搜索拼多多...")
        pdd_items = search_pdd(driver, keyword)
        print(f"  找到 {len(pdd_items)} 个商品")
        
        # 价格概览
        print("\n" + "=" * 60)
        print("📊 价格概览")
        for platform, items in [("京东", jd_items), ("1688", ali_items), ("拼多多", pdd_items)]:
            if items:
                prices = [i["price"] for i in items]
                print(f"\n  {platform}: {len(items)} 个商品")
                print(f"    最低价: ¥{min(prices):.2f}")
                print(f"    最高价: ¥{max(prices):.2f}")
                print(f"    均价: ¥{sum(prices)/len(prices):.2f}")
                print(f"    前3个:")
                for i in sorted(items, key=lambda x: x["price"])[:3]:
                    print(f"      ¥{i['price']:.2f} | {i['name'][:40]}")
        
        # 寻找套利机会
        print("\n" + "=" * 60)
        print("💰 套利机会分析（1688 进货 → 京东/拼多多零售价参考）")
        
        if ali_items and jd_items:
            opps = find_arbitrage(jd_items, ali_items, "1688", min_margin=0.3)
            if opps:
                for i, opp in enumerate(opps[:10]):
                    print(f"\n  [{i+1}] {opp['source']}")
                    print(f"      进货价: ¥{opp['source_price']:.2f}")
                    print(f"      零售参考: ¥{opp['retail_price']:.2f} ({opp['retail'][:30]})")
                    print(f"      毛利率: {opp['margin']} | 单件利润: ¥{opp['profit_per_unit']}")
                    print(f"      名称匹配度: {opp['similarity']}")
            else:
                print("  未找到明显套利机会（可能需要更精确的商品匹配）")
        else:
            print("  数据不足，无法分析")
        
        # 保存原始数据
        output = {
            "keyword": keyword,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "jd": jd_items[:20],
            "ali1688": ali_items[:20],
            "pdd": pdd_items[:20]
        }
        outfile = f"/home/mi/.openclaw/workspace/src/actions/analysis/price_data_{keyword.replace(' ','_')}.json"
        with open(outfile, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n📁 原始数据已保存: {outfile}")
        
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
