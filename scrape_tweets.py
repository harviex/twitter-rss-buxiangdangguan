#!/usr/bin/env python3
"""
抓取 @buxiangdangguan 主页推文文本
- 无需登录，Playwright 无头模式
- 多选择器容错、详细调试日志（输出到 stdout，Actions 步骤日志可见）
- 增量写入 data/tweets.json
- 无新推文也正常退出
"""
import json
import sys
import re
import traceback
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

USER = "BAIGUANXINGSHU"
URL = f"https://x.com/{USER}"
DATA_FILE = Path("data/tweets.json")
DATA_FILE.parent.mkdir(exist_ok=True)

SELECTORS = {
    "tweet_article": [
        "article[data-tweet-id]",
        "article[itemprop='hasPart']",
        "article[role='article']",
        "article",
    ],
    "tweet_text": [
        "[itemprop='articleBody']",
        "div[data-testid='tweetText']",
        "div[lang]",
        "span[lang]",
    ],
}

def log(msg):
    print(msg, flush=True)

def load_existing():
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def save_all(tweets):
    DATA_FILE.write_text(json.dumps(tweets, ensure_ascii=False, indent=2), encoding="utf-8")

def find_elements(page, selectors, name=""):
    for sel in selectors:
        try:
            els = page.query_selector_all(sel)
            if els:
                log(f"[DEBUG] {name}: found {len(els)} with selector '{sel}'")
                return els
        except Exception as e:
            log(f"[DEBUG] {name}: selector '{sel}' error: {e}")
    log(f"[WARN] {name}: no elements found with any selector")
    return []

def extract_tweets(page):
    log(f"[DEBUG] Page title: {page.title()}")
    log(f"[DEBUG] Page URL: {page.url}")
    
    # 等待任意推文选择器出现
    for sel in SELECTORS["tweet_article"]:
        try:
            page.wait_for_selector(sel, timeout=5000)
            log(f"[DEBUG] Waited for tweet article: '{sel}'")
            break
        except Exception:
            continue
    else:
        log("[WARN] No tweet article selector matched within timeout")
        # 保存页面 HTML 用于调试
        html = page.content()
        Path("debug_page.html").write_text(html, encoding="utf-8")
        log(f"[DEBUG] Saved page HTML ({len(html)} chars) to debug_page.html")
        # 打印前 2000 字符看结构
        log(f"[DEBUG] Page preview: {html[:2000]}")
        return []

    articles = find_elements(page, SELECTORS["tweet_article"], "tweet_article")
    results = []
    
    for i, art in enumerate(articles[:15]):
        try:
            # 推文文本
            text = ""
            for text_sel in SELECTORS["tweet_text"]:
                text_el = art.query_selector(text_sel)
                if text_el:
                    # 先试 inner_text
                    text = text_el.inner_text().strip()
                    # 如果是 meta 标签，读 content 属性
                    if not text and text_el.evaluate("el => el.tagName.toLowerCase()") == "meta":
                        text = text_el.get_attribute("content") or ""
                    if text:
                        log(f"[DEBUG] Tweet {i}: text via '{text_sel}' = {text[:80]}...")
                        break
            
            # 时间链接 - 从 meta[itemprop] 取
            dt = ""
            link = ""
            tweet_id = ""
            # 先从 article 的 data-tweet-id 取
            tweet_id = art.get_attribute("data-tweet-id") or ""
            if tweet_id:
                link = f"/{USER}/status/{tweet_id}"
            
            # 从 meta[itemprop='datePublished'] 或 dateCreated 取时间
            date_el = art.query_selector("meta[itemprop='datePublished'], meta[itemprop='dateCreated']")
            if date_el:
                dt = date_el.get_attribute("content") or ""
            
            # 从 meta[itemprop='url'] 取链接
            url_el = art.query_selector("meta[itemprop='url']")
            if url_el:
                href = url_el.get_attribute("content") or ""
                if href and not link:
                    link = href.replace(f"https://x.com", "")
                    if not tweet_id:
                        tweet_id = link.split("/")[-1]
            
            # 备选：从 article 直接找 status 链接
            if not tweet_id or not link:
                status_link = art.query_selector("a[href*='/status/']")
                if status_link:
                    link = status_link.get_attribute("href") or ""
                    if link and not tweet_id:
                        tweet_id = link.split("/")[-1]
            
            if text and tweet_id:
                results.append({
                    "id": tweet_id,
                    "text": text,
                    "datetime": dt,
                    "url": f"https://x.com{link}" if link else f"https://x.com/{USER}/status/{tweet_id}",
                    "scraped_at": datetime.now(timezone.utc).isoformat()
                })
                log(f"[OK] Tweet {len(results)}: id={tweet_id}, text={text[:80]}...")
            elif text:
                log(f"[WARN] Found text but no ID: {text[:80]}...")
            else:
                log(f"[DEBUG] Article {i}: no text extracted")
                
        except Exception as e:
            log(f"[WARN] Error extracting tweet {i}: {e}")
            continue
    
    return results

def main():
    existing = load_existing()
    existing_ids = {t["id"] for t in existing}
    log(f"[INFO] Loaded {len(existing)} existing tweets")

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
            
            log(f"[INFO] Navigating to {URL}")
            page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            # 不要等 networkidle，X.com 永远不会 idle；直接等推文选择器
            page.wait_for_timeout(3000)
            
            # 滚动触发懒加载
            page.mouse.wheel(0, 1000)
            page.wait_for_timeout(2000)
            
            new_tweets = extract_tweets(page)
            browser.close()
            
    except Exception as e:
        log(f"[ERROR] Scraping failed: {e}")
        traceback.print_exc()
        new_tweets = []

    # 去重 + 合并
    merged = []
    for t in new_tweets:
        if t["id"] not in existing_ids:
            merged.append(t)
            existing_ids.add(t["id"])
    merged.extend(existing)
    merged = merged[:200]

    save_all(merged)

    new_count = len(merged) - len(existing)
    log(f"::set-output name=new_count::{new_count}")
    
    if new_count > 0:
        for t in merged[:new_count]:
            log(f"NEW: {t['id']} | {t['text'][:80]}...")
    else:
        log("No new tweets.")
    
    sys.exit(0)

if __name__ == "__main__":
    main()