#!/usr/bin/env python3
"""
抓取多个 X/Twitter 用户推文，合并去重
- 使用 fxtwitter RSS 源（无需登录，稳定可靠）
- 增量写入 data/tweets.json
- 支持 BAIGUANXINGSHU（有公开 RSS）和 buxiangdangguan（需登录，暂时无法抓取）
"""

import json
import sys
import re
import traceback
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# 目标用户列表
USERS = ["buxiangdangguan", "BAIGUANXINGSHU"]
DATA_FILE = Path("data/tweets.json")
DATA_FILE.parent.mkdir(exist_ok=True)

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
    """从 fxtwitter 获取用户的 RSS feed"""
    url = f"https://fxtwitter.com/{username}/feed.xml"
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
    """解析 RSS XML，提取推文"""
    if not content:
        return []
    
    results = []
    
    # 简单的 XML 解析（不依赖外部库）
    # 匹配每个 <item>...</item>
    import re
    item_pattern = re.compile(r"<item>.*?</item>", re.DOTALL)
    items = item_pattern.findall(content)
    
    log(f"[DEBUG] Found {len(items)} items in RSS")
    
    for item in items:
        try:
            # 提取 title (推文内容)
            title_match = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>", item)
            if not title_match:
                title_match = re.search(r"<title>(.*?)</title>", item)
            title = title_match.group(1) if title_match else ""
            
            # 提取 link (推文 URL)
            link_match = re.search(r"<link><!\[CDATA\[(.*?)\]\]></link>", item)
            if not link_match:
                link_match = re.search(r"<link>(.*?)</link>", item)
            link = link_match.group(1) if link_match else ""
            
            # 从 link 提取 tweet ID
            tweet_id_match = re.search(r"/status/(\d+)", link)
            tweet_id = tweet_id_match.group(1) if tweet_id_match else ""
            
            # 提取 pubDate
            pubdate_match = re.search(r"<pubDate><!\[CDATA\[(.*?)\]\]></pubDate>", item)
            if not pubdate_match:
                pubdate_match = re.search(r"<pubDate>(.*?)</pubDate>", item)
            pubdate = pubdate_match.group(1) if pubdate_match else ""
            
            # 提取 description (可能包含更多内容)
            desc_match = re.search(r"<description><!\[CDATA\[(.*?)\]\]></description>", item)
            if not desc_match:
                desc_match = re.search(r"<description>(.*?)</description>", item)
            description = desc_match.group(1) if desc_match else ""
            
            # 清理 HTML 标签
            text = re.sub(r"<[^>]+>", "", description)
            text = text.replace("<", "<").replace(">", ">").replace("&", "&")
            text = text.strip()
            
            # 如果 description 为空，用 title
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

def main():
    existing = load_existing()
    existing_ids = {t["id"] for t in existing}
    log(f"[INFO] Loaded {len(existing)} existing tweets")
    
    all_new_tweets = []
    
    for user in USERS:
        log(f"[INFO] Processing user: {user}")
        
        # buxiangdangguan 没有公开 RSS（账号保护），跳过
        if user == "buxiangdangguan":
            log(f"[INFO] Skipping {user} - no public RSS (account protected)")
            continue
            
        rss_content = fetch_rss(user)
        if rss_content:
            new_tweets = parse_rss(rss_content, user)
            all_new_tweets.extend(new_tweets)
            log(f"[INFO] User {user}: obtained {len(new_tweets)} tweets from RSS")
        else:
            log(f"[WARN] User {user}: failed to fetch RSS")
    
    # 去重 + 合并（新抓取的优先，然后旧的）
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
    
    # 计算新增数量
    merged_ids = {t["id"] for t in merged}
    existing_ids = {t["id"] for t in existing}
    added_ids = merged_ids - existing_ids
    new_count = len(added_ids)
    log(f"::set-output name=new_count::{new_count}")
    
    if new_count > 0:
        added_tweets = [t for t in merged if t["id"] in added_ids]
        for t in added_tweets[:new_count]:
            log(f"NEW: {t['id']} | user={t.get('user', 'unknown')} | {t['text'][:80]}...")
    else:
        log("No new tweets.")
    
    sys.exit(0)

if __name__ == "__main__":
    main()