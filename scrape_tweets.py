#!/usr/bin/env python3
"""
抓取 @BAIGUANXINGSHU 推文，增量写入 data/tweets.json
- 使用 fxtwitter RSS 源（无需登录，稳定可靠）
- 仅抓取 BAIGUANXINGSHU（buxiangdangguan 已移除：账号保护，无法抓取）
"""

import json
import re
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from email.utils import parsedate_to_datetime

USERS = ["BAIGUANXINGSHU"]
DATA_FILE = Path("data/tweets.json")
DATA_FILE.parent.mkdir(exist_ok=True)

RSS_URL = "https://fxtwitter.com/{username}/feed.xml"

# ⚠️ fxtwitter 的 RSS 响应量随机波动（实测 39/59/90 条三种），
# 单次抓取可能拿到截断的不完整响应 → 新推文漏抓。
# 实测事故：Actions 连续 4 次拿到同一份过期数据，2 条新推文全漏，
# 而 pubDate bug 把 staleness 伪装成「每小时都在更新」，肉眼完全看不出来。
MAX_FETCH_ATTEMPTS = 3
RETRY_DELAY_SEC = 3

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

def fetch_rss(username):
    url = RSS_URL.format(username=username)
    log(f"[INFO] Fetching RSS from {url}")
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; RSSBot/1.0)"})
        with urlopen(req, timeout=30) as resp:
            content = resp.read().decode("utf-8")
        log(f"[INFO] Got RSS content ({len(content)} chars)")
        return content
    except HTTPError as e:
        if e.code == 404:
            log(f"[WARN] User {username} not found on fxtwitter (404)")
        else:
            log(f"[WARN] HTTP {e.code} fetching RSS for {username}: {e.reason}")
        return None
    except URLError as e:
        log(f"[WARN] URL error fetching RSS for {username}: {e.reason}")
        return None
    except Exception as e:
        log(f"[ERROR] Failed to fetch RSS for {username}: {e}")
        return None

def parse_rss(content, username):
    if not content:
        return []

    results = []
    item_pattern = re.compile(r"<item>.*?</item>", re.DOTALL)
    items = item_pattern.findall(content)
    log(f"[DEBUG] Found {len(items)} items in RSS")

    for item in items:
        try:
            title_match = re.search(r"<title><!CDATA\[(.*?)\]\]></title>", item)
            if not title_match:
                title_match = re.search(r"<title>(.*?)</title>", item)
            title = title_match.group(1) if title_match else ""

            link_match = re.search(r"<link>(.*?)</link>", item)
            if not link_match:
                link_match = re.search(r"<link><!CDATA\[(.*?)\]\]></link>", item)
            link = link_match.group(1) if link_match else ""

            tweet_id_match = re.search(r"/status/(\d+)", link)
            tweet_id = tweet_id_match.group(1) if tweet_id_match else ""

            pubdate_match = re.search(r"<pubDate>(.*?)</pubDate>", item)
            if not pubdate_match:
                pubdate_match = re.search(r"<pubDate><!CDATA\[(.*?)\]\]></pubDate>", item)
            pubdate = pubdate_match.group(1) if pubdate_match else ""

            desc_match = re.search(r"<description><!CDATA\[(.*?)\]\]></description>", item)
            if not desc_match:
                desc_match = re.search(r"<description>(.*?)</description>", item)
            description = desc_match.group(1) if desc_match else ""

            # 清理 HTML 标签
            text = re.sub(r"<[^>]+>", "", description)
            text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
            text = text.strip()

            if not text:
                text = title

            if tweet_id and text:
                results.append({
                    "id": tweet_id,
                    "text": text,
                    "datetime": pubdate,
                    "url": link,
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                    "user": username
                })
                log(f"[OK] Tweet {len(results)}: id={tweet_id}, user={username}, text={text[:80]}...")
            elif text:
                log(f"[WARN] Found text but no ID: {text[:80]}...")
        except Exception as e:
            log(f"[WARN] Error parsing item: {e}")
            continue

    return results

def newest_datetime(tweets):
    """返回列表里最新的推文时间；无法解析的忽略，全失败返回 None。"""
    best = None
    for t in tweets:
        try:
            dt = parsedate_to_datetime(t.get("datetime", ""))
            if dt is None:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if best is None or dt > best:
                best = dt
        except Exception:
            continue
    return best


def fetch_rss_best(username, existing_tweets, attempts=MAX_FETCH_ATTEMPTS):
    """多次抓取，返回「最好」的那次结果。

    评分 = (最新推文时间, 条数)，元组比较。
    合格判据：响应的最新推文时间 >= 已有数据的最新推文时间
      —— 说明没有漏掉比已知更晚的推文。
    只要拿到合格响应就提前停止，否则重试到 attempts 次，最后取最优。

    ⚠️ 不会丢数据：合并逻辑是「新抓的在前、旧的在后」，截断响应只是少抓，
    不影响已存数据；这个重试只解决「漏抓新推文」。
    """
    existing_newest = newest_datetime(existing_tweets)
    if existing_newest:
        log(f"[INFO] 已有数据最新推文: {existing_newest}")

    best_tweets = []
    best_score = None

    for attempt in range(1, attempts + 1):
        content = fetch_rss(username)
        if not content:
            log(f"[WARN] 第 {attempt}/{attempts} 次抓取失败"
                + ("，等待重试" if attempt < attempts else "，放弃"))
            if attempt < attempts:
                time.sleep(RETRY_DELAY_SEC)
            continue

        tweets = parse_rss(content, username)
        if not tweets:
            log(f"[WARN] 第 {attempt}/{attempts} 次解析出 0 条"
                + ("，等待重试" if attempt < attempts else "，放弃"))
            if attempt < attempts:
                time.sleep(RETRY_DELAY_SEC)
            continue

        newest = newest_datetime(tweets)
        score = (newest or datetime.min.replace(tzinfo=timezone.utc), len(tweets))

        if best_score is None or score > best_score:
            best_tweets, best_score = tweets, score

        if existing_newest is None:
            good = True                      # 首次抓取，没有可比基线
        else:
            good = newest is not None and newest >= existing_newest

        log(f"[INFO] 第 {attempt}/{attempts} 次: {len(tweets)} 条 · 最新推文 "
            f"{newest or '解析失败'} → {'✅ 合格' if good else '⚠️ 不完整（漏了新推文）'}")

        if good:
            log("[INFO] 拿到合格响应，停止重试")
            break
        if attempt < attempts:
            log(f"[INFO] {RETRY_DELAY_SEC}s 后重试…")
            time.sleep(RETRY_DELAY_SEC)

    return best_tweets


def main():
    existing = load_existing()
    existing_ids = {t["id"] for t in existing}
    log(f"[INFO] Loaded {len(existing)} existing tweets")

    all_new_tweets = []

    for user in USERS:
        log(f"[INFO] Processing user: {user}")
        new_tweets = fetch_rss_best(user, existing)
        if new_tweets:
            all_new_tweets.extend(new_tweets)
            log(f"[INFO] User {user}: 采用 {len(new_tweets)} tweets")
        else:
            log(f"[WARN] User {user}: {MAX_FETCH_ATTEMPTS} 次尝试后仍无有效数据")

    # 去重 + 合并（新抓取的优先，然后旧的）
    merged = []
    seen_ids = set()

    for t in all_new_tweets:
        if t["id"] not in seen_ids:
            merged.append(t)
            seen_ids.add(t["id"])

    for t in existing:
        if t["id"] not in seen_ids:
            merged.append(t)
            seen_ids.add(t["id"])

    # 限制条目数（保留最新的 200 条）
    merged = merged[:200]

    save_all(merged)

    # 计算新增数量
    merged_ids = {t["id"] for t in merged}
    existing_ids_now = {t["id"] for t in existing}
    added_ids = merged_ids - existing_ids_now
    new_count = len(added_ids)
    import os
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"new_count={new_count}\n")

    if new_count > 0:
        for t in [t for t in merged if t["id"] in added_ids][:new_count]:
            log(f"NEW: {t['id']} | user={t.get('user', 'unknown')} | {t['text'][:80]}...")
    else:
        log("No new tweets.")

    sys.exit(0)

if __name__ == "__main__":
    main()
