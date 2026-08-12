#!/usr/bin/env python3
"""
抓取 @buxiangdangguan 主页推文文本
- 无需登录，Playwright 无头模式
- 多选择器容错、详细调试日志
- 增量写入 data/tweets.json
- 无新推文也正常退出（不报错）
"""
import json
import sys
import re
import traceback
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

USER = "buxiangdangguan"
URL = f"https://x.com/{USER}"
DATA_FILE = Path("data/tweets.json")
DATA_FILE.parent.mkdir(exist_ok=True)

# 多套选择器容错（Twitter 常改 class）
SELECTORS = {
    "tweet_article": [
        "article[data-testid='tweet']",
        "article[role='article']",
        "div[data-testid='tweet']",
    ],
    "tweet_text": [
        "div[data-testid='tweetText']",
        "div[lang]",
        "span[lang]",
    ],
    "time_link": [
        "a time",
        "time a",
        "a[href*='/status/'] time",
    ],
}

def load_existing():
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def save_all(tweets):
    DATA_FILE.write_text(json.dumps(tweets, ensure_ascii=False, indent=2), encoding="utf-8")

def find_element(page, selectors, description=""):
    """尝试多个选择器，返回第一个匹配的元素"""
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el:
                return el
        except Exception:
            continue
    return None

def find_elements(page, selectors):
    """尝试多个选择器，返回第一个匹配的列表"""
    for sel in selectors:
        try:
            els = page.query_selector_all(sel)
            if els:
                return els
        except Exception:
            continue
    return []

def extract_tweets(page):
    """从页面提取推文：文本 + 时间 + 链接"""
    print(f"[DEBUG] Page title: {page.title()}")
    print(f"[DEBUG] Page URL: {page.url}")
    
    # 等待任意推文选择器出现
    tweet_found = False
    for sel in SELECTORS["tweet_article"]:
        try:
            page.wait_for_selector(sel, timeout=5000)
            tweet_found = True
            print(f"[DEBUG] Found tweets with selector: {sel}")
            break
        except Exception:
            continue
    
    if not tweet_found:
        print("[WARN] No tweet articles found with any selector")
        # 保存页面 HTML 用于调试
        html = page.content()
        Path("debug_page.html").write_text(html, encoding="utf-8")
        print("[DEBUG] Saved page HTML to debug_page.html")
        return []

    articles = find_elements(page, SELECTORS["tweet_article"])
    print(f"[DEBUG] Found {len(articles)} tweet articles")
    
    results = []
    for i, art in enumerate(articles[:15]):  # 多抓几条防漏
        try:
            # 推文文本 - 尝试多个选择器
            text = ""
            for text_sel in SELECTORS["tweet_text"]:
                text_el = art.query_selector(text_sel)
                if text_el:
                    text = text_el.inner_text().strip()
                    if text:
                        break
            
            # 时间链接
            dt = ""
            link = ""
            tweet_id = ""
            for time_sel in SELECTORS["time_link"]:
                time_el = art.query_selector(time_sel)
                if time_el:
                    dt = time_el.get_attribute("datetime") or ""
                    link = time_el.get_attribute("href") or ""
                    if link:
                        tweet_id = link.split("/")[-1]
                    break
            
            # 备选：从 article 直接找 status 链接
            if not tweet_id:
                status_link = art.query_selector("a[href*='/status/']")
                if status_link:
                    link = status_link.get_attribute("href") or ""
                    tweet_id = link.split("/")[-1] if link else ""
            
            if text and tweet_id:
                results.append({
                    "id": tweet_id,
                    "text": text,
                    "datetime": dt,
                    "url": f"https://x.com{link}" if link else f"https://x.com/{USER}/status/{tweet_id}",
                    "scraped_at": datetime.now(timezone.utc).isoformat()
                })
                print(f"[DEBUG] Tweet {len(results)}: id={tweet_id}, text={text[:80]}...")
            elif text:
                print(f"[DEBUG] Found text but no ID: {text[:80]}...")
                
        except Exception as e:
            print(f"[WARN] Error extracting tweet {i}: {e}")
            continue
    
    return results

def main():
    existing = load_existing()
    existing_ids = {t["id"] for t in existing}
    print(f"[INFO] Loaded {len(existing)} existing tweets")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True, 
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720},
                locale="zh-CN",
            )
            page = context.new_page()
            
            print(f"[INFO] Navigating to {URL}")
            page.goto(URL, wait_until="domcontentloaded", timeout=45000)
            
            # 等待网络空闲
            page.wait_for_load_state("networkidle", timeout=15000)
            page.wait_for_timeout(5000)  # 额外等待 JS 渲染
            
            # 尝试滚动一下触发懒加载
            page.mouse.wheel(0, 1000)
            page.wait_for_timeout(2000)
            
            new_tweets = extract_tweets(page)
            browser.close()
            
    except Exception as e:
        print(f"[ERROR] Scraping failed: {e}")
        traceback.print_exc()
        # 不抛出异常，让工作流继续（生成 RSS 可能还是有旧数据）
        new_tweets = []

    # 去重 + 合并（新在前）
    merged = []
    for t in new_tweets:
        if t["id"] not in existing_ids:
            merged.append(t)
            existing_ids.add(t["id"])
    merged.extend(existing)
    # 只保留最近 200 条防膨胀
    merged = merged[:200]

    save_all(merged)

    new_count = len(merged) - len(existing)
    print(f"::set-output name=new_count::{new_count}")
    
    if new_count > 0:
        for t in merged[:new_count]:
            print(f"NEW: {t['id']} | {t['text'][:80]}...")
    else:
        print("No new tweets.")
    
    # 即使抓取失败也返回成功，避免工作流红标
    # 只有真正的 Python 异常才会让步骤失败
    sys.exit(0)

if __name__ == "__main__":
    main()