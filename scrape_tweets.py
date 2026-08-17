#!/usr/bin/env python3
"""
抓取多个 X/Twitter 用户主页推文文本，合并去重
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

# 目标用户列表
USERS = ["buxiangdangguan", "BAIGUANXINGSHU"]
# 为每个用户生成对应的 URL，但在抓取循环中处理
DATA_FILE = Path("data/tweets.json")
DATA_FILE.parent.mkdir(exist_ok=True)

# 扩展选择器：覆盖原推、转推、引用推、推广推文等结构
SELECTORS = {
    "tweet_article": [
        "article[data-testid='tweet']",           # 现代 X.com 结构
        "article[data-tweet-id]",                  # 旧结构
        "article[itemprop='hasPart']",             # Schema.org
        "article[role='article']",                 # ARIA
        "div[data-testid='cellInnerDiv'] article", # 列表项内
        "article",                                 # 兜底
    ],
    "tweet_text": [
        "[data-testid='tweetText']",               # 现代结构
        "[itemprop='articleBody']",                # Schema.org
        "div[lang]",                               # 语言标记
        "span[lang]",                              # 语言标记
        "div[dir='auto']",                         # 自动方向文本
    ],
    "tweet_time": [
        "time[datetime]",                          # 标准 time 标签
        "meta[itemprop='datePublished']",
        "meta[itemprop='dateCreated']",
    ],
    "tweet_link": [
        "a[href*='/status/']",                     # 状态链接
        "meta[itemprop='url']",
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

def extract_tweet_id(art):
    """从 article 提取 tweet ID，多种方式兜底"""
    # 1. data-testid='tweet' 的 data-tweet-id
    tweet_id = art.get_attribute("data-tweet-id")
    if tweet_id:
        return tweet_id
    # 2. 从链接提取
    status_link = art.query_selector("a[href*='/status/']")
    if status_link:
        href = status_link.get_attribute("href") or ""
        match = re.search(r"/status/(\d+)", href)
        if match:
            return match.group(1)
    # 3. 从 article id 属性
    art_id = art.get_attribute("id")
    if art_id and art_id.isdigit():
        return art_id
    return ""

def extract_tweet_text(art):
    """提取推文文本，处理多种结构"""
    for text_sel in SELECTORS["tweet_text"]:
        text_el = art.query_selector(text_sel)
        if text_el:
            text = text_el.inner_text().strip()
            if not text and text_el.evaluate("el => el.tagName.toLowerCase()") == "meta":
                text = text_el.get_attribute("content") or ""
            if text:
                return text
    return ""

def extract_tweet_datetime(art):
    """提取发布时间"""
    for time_sel in SELECTORS["tweet_time"]:
        time_el = art.query_selector(time_sel)
        if time_el:
            dt = time_el.get_attribute("datetime") or time_el.get_attribute("content")
            if dt:
                return dt
    return ""

def extract_tweets(page, username):
    log(f"[DEBUG] Page title: {page.title()}")
    log(f"[DEBUG] Page URL: {page.url}")

    # 等待任意推文选择器出现
    for sel in SELECTORS["tweet_article"]:
        try:
            page.wait_for_selector(sel, timeout=15000)
            log(f"[DEBUG] Waited for tweet article: '{sel}'")
            break
        except Exception:
            continue
    else:
        log("[WARN] No tweet article selector matched within timeout")
        html = page.content()
        Path(f"debug_page_{username}.html").write_text(html, encoding="utf-8")
        log(f"[DEBUG] Saved page HTML ({len(html)} chars) to debug_page_{username}.html")
        log(f"[DEBUG] Page preview: {html[:3000]}")
        return []

    # 多次滚动加载更多推文
    max_scrolls = 10
    for scroll_i in range(max_scrolls):
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(2000)
        articles = find_elements(page, SELECTORS["tweet_article"], "tweet_article")
        log(f"[DEBUG] After scroll {scroll_i+1}: found {len(articles)} articles")
        if scroll_i > 2:
            prev_count = len(find_elements(page, SELECTORS["tweet_article"], "tweet_article"))
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(2000)
            new_count = len(find_elements(page, SELECTORS["tweet_article"], "tweet_article"))
            if new_count == prev_count:
                log(f"[DEBUG] No new articles after scroll, stopping early")
                break

    page.wait_for_timeout(3000)
    articles = find_elements(page, SELECTORS["tweet_article"], "tweet_article")
    log(f"[INFO] Total articles found: {len(articles)}")

    results = []

    # 处理所有找到的文章
    for i, art in enumerate(articles):
        try:
            # 打印前 5 篇的 HTML 结构用于调试
            if i < 5:
                html = art.evaluate("el => el.outerHTML")
                log(f"[DEBUG] Article {i} HTML preview: {html[:500]}...")

            tweet_id = extract_tweet_id(art)
            text = extract_tweet_text(art)
            dt = extract_tweet_datetime(art)

            if text and tweet_id:
                link = f"https://x.com/{username}/status/{tweet_id}"
                results.append({
                    "id": tweet_id,
                    "text": text,
                    "datetime": dt,
                    "url": link,
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                    "user": username  # 记录来源用户，便于调试
                })
                log(f"[OK] Tweet {len(results)}: id={tweet_id}, user={username}, text={text[:80]}...")
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

    all_new_tweets = []
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
            for user in USERS:
                url = f"https://x.com/{user}"
                log(f"[INFO] Navigating to {url}")
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=60000)

                # 等待推文选择器出现
                for sel in SELECTORS["tweet_article"]:
                    try:
                        page.wait_for_selector(sel, timeout=15000)
                        log(f"[DEBUG] Waited for tweet article: '{sel}'")
                        break
                    except Exception:
                        continue
                else:
                    log("[WARN] No tweet article selector matched within timeout")
                    html = page.content()
                    Path(f"debug_page_{user}.html").write_text(html, encoding="utf-8")
                    log(f"[DEBUG] Saved page HTML ({len(html)} chars) to debug_page_{user}.html")
                    page.close()
                    continue

                # 多次滚动加载更多推文
                max_scrolls = 10
                for scroll_i in range(max_scrolls):
                    page.mouse.wheel(0, 2500)
                    page.wait_for_timeout(2000)
                    articles = find_elements(page, SELECTORS["tweet_article"], "tweet_article")
                    log(f"[DEBUG] After scroll {scroll_i+1}: found {len(articles)} articles")
                    if scroll_i > 2:
                        prev_count = len(find_elements(page, SELECTORS["tweet_article"], "tweet_article"))
                        page.mouse.wheel(0, 2500)
                        page.wait_for_timeout(2000)
                        new_count = len(find_elements(page, SELECTORS["tweet_article"], "tweet_article"))
                        if new_count == prev_count:
                            log(f"[DEBUG] No new articles after scroll, stopping early")
                            break

                page.wait_for_timeout(3000)

                new_tweets = extract_tweets(page, user)
                all_new_tweets.extend(new_tweets)
                page.close()
                log(f"[INFO] User {user}: obtained {len(new_tweets)} tweets")

            browser.close()

    except Exception as e:
        log(f"[ERROR] Scraping failed: {e}")
        traceback.print_exc()
        all_new_tweets = []

    # 去重 + 合并（按 tweet id 去重，保留最新的（即新抓到的在前，后面追加旧的，所以新的会覆盖旧的？我们采用：新抓到的在前，然后加入旧的，但如果旧的 id 在新的里也出现，我们希望保留新的（因为可能有更新如更多互动？但推文内容一般不变）。为了简单，我们按 id 去重，保留第一次出现的（即新抓到的在前，所以新的优先）。）
    merged = []
    seen_ids = set()
    # 先处理新抓到的
    for t in all_new_tweets:
        if t["id"] not in seen_ids:
            merged.append(t)
            seen_ids.add(t["id"])
    # 再处理旧的
    for t in existing:
        if t["id"] not in seen_ids:
            merged.append(t)
            seen_ids.add(t["id"])
    # 限制条目数（保留最新的 200 条）
    merged = merged[:200]

    save_all(merged)

    new_count = len([t for t in merged if t["id"] not in {e["id"] for e in existing}])  # 实际上就是 all_new_tweets 去重后的数量
    # 重新计算：比较 merged 和 existing 的 id 集合
    merged_ids = {t["id"] for t in merged}
    existing_ids = {t["id"] for t in existing}
    added_ids = merged_ids - existing_ids
    new_count = len(added_ids)
    log(f"::set-output name=new_count::{new_count}")

    if new_count > 0:
        # 为了日志，展示新增的前几条
        added_tweets = [t for t in merged if t["id"] in added_ids]
        for t in added_tweets[:new_count]:
            log(f"NEW: {t['id']} | user={t.get('user', 'unknown')} | {t['text'][:80]}...")
    else:
        log("No new tweets.")

    sys.exit(0)

if __name__ == "__main__":
    main()
