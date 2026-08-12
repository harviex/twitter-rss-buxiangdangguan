#!/usr/bin/env python3
"""
抓取 @buxiangdangguan 主页前 ~5 条推文文本
- 无需登录，Playwright 无头模式
- 增量写入 data/tweets.json
- 返回新增条目供 RSS 生成用
"""
import json
import sys
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

USER = "buxiangdangguan"
URL = f"https://x.com/{USER}"
DATA_FILE = Path("data/tweets.json")
DATA_FILE.parent.mkdir(exist_ok=True)

def load_existing():
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return []

def save_all(tweets):
    DATA_FILE.write_text(json.dumps(tweets, ensure_ascii=False, indent=2), encoding="utf-8")

def extract_tweets(page):
    """从页面提取推文：文本 + 时间 + 链接"""
    page.wait_for_selector("article[data-testid='tweet']", timeout=15000)
    articles = page.query_selector_all("article[data-testid='tweet']")
    results = []
    for art in articles[:10]:  # 多抓几条防漏
        try:
            # 推文文本
            text_el = art.query_selector("div[data-testid='tweetText']")
            text = text_el.inner_text().strip() if text_el else ""
            # 时间链接
            time_el = art.query_selector("a time")
            dt = time_el.get_attribute("datetime") if time_el else ""
            link = time_el.get_attribute("href") if time_el else ""
            tweet_id = link.split("/")[-1] if link else ""
            if text and tweet_id:
                results.append({
                    "id": tweet_id,
                    "text": text,
                    "datetime": dt,
                    "url": f"https://x.com{link}" if link else "",
                    "scraped_at": datetime.now(timezone.utc).isoformat()
                })
        except Exception:
            continue
    return results

def main():
    existing = load_existing()
    existing_ids = {t["id"] for t in existing}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        page.goto(URL, wait_until="networkidle", timeout=30000)
        # 等待推文渲染
        page.wait_for_timeout(3000)
        new_tweets = extract_tweets(page)
        browser.close()

    # 去重 + 合并（新在前）
    merged = []
    for t in new_tweets:
        if t["id"] not in existing_ids:
            merged.append(t)
            existing_ids.add(t["id"])
    merged.extend(existing)  # 旧的追在后面
    # 只保留最近 200 条防膨胀
    merged = merged[:200]

    save_all(merged)

    # 输出新增给 GitHub Actions 用
    if merged != existing:
        new_count = len(merged) - len(existing)
        print(f"::set-output name=new_count::{new_count}")
        for t in merged[:new_count]:
            print(f"NEW: {t['id']} | {t['text'][:60]}...")
    else:
        print("::set-output name=new_count::0")
        print("No new tweets.")

if __name__ == "__main__":
    main()