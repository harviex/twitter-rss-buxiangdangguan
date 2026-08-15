#!/usr/bin/env python3
"""data/tweets.json → feed.xml (RSS 2.0)"""
import json
import re
from pathlib import Path
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

DATA_FILE = Path("data/tweets.json")
OUT_FILE = Path("feed.xml")

# 去掉 t.co 短链接
TCO_PATTERN = re.compile(r"https?://t\.co/\w+")

def strip_tco(text: str) -> str:
    """移除文本中的 t.co 链接并清理多余空白"""
    text = TCO_PATTERN.sub("", text)
    return re.sub(r"\s+", " ", text).strip()

def build_rss(tweets):
    rss = ET.Element("rss", version="2.0", attrib={
        "xmlns:atom": "http://www.w3.org/2005/Atom",
        "xmlns:content": "http://purl.org/rss/1.0/modules/content/"
    })
    ch = ET.SubElement(rss, "channel")
    USER = "buxiangdangguan"
    ET.SubElement(ch, "title").text = f"@{USER} - X Timeline"
    ET.SubElement(ch, "link").text = f"https://x.com/{USER}"
    ET.SubElement(ch, "description").text = f"自动抓取 @{USER} 公开推文"
    ET.SubElement(ch, "language").text = "zh-CN"
    # 使用北京时间 (UTC+8)
    bj_now = datetime.utcnow() + timedelta(hours=8)
    ET.SubElement(ch, "lastBuildDate").text = bj_now.strftime("%a, %d %b %Y %H:%M:%S +0800")
    ET.SubElement(ch, "atom:link", href="https://harviex.github.io/twitter-rss-buxiangdangguan/feed.xml", rel="self", type="application/rss+xml")

    for t in tweets:
        clean_text = strip_tco(t["text"])
        
        # 跳过"已官宣"类推文（不生成单独条目）
        if clean_text.startswith("已官宣"):
            continue
        
        item = ET.SubElement(ch, "item")
        
        # 解析发布时间 (北京时间)
        try:
            dt = datetime.fromisoformat(t["datetime"].replace("Z", "+00:00"))
            bj_dt = dt + timedelta(hours=8)
            pub_str = bj_dt.strftime("%Y-%m-%d %H:%M")
            pub_rfc = bj_dt.strftime("%a, %d %b %Y %H:%M:%S +0800")
        except Exception:
            bj_now = datetime.utcnow() + timedelta(hours=8)
            pub_str = bj_now.strftime("%Y-%m-%d %H:%M")
            pub_rfc = bj_now.strftime("%a, %d %b %Y %H:%M:%S +0800")

        title_text = f"{clean_text} {pub_str}"

        # 标题截断（RSS 规范建议）
        ET.SubElement(item, "title").text = title_text[:200]
        # 去掉每条的 link
        ET.SubElement(item, "guid", isPermaLink="false").text = t["id"]
        # description 留空（按需求）
        ET.SubElement(item, "description").text = ""
        ET.SubElement(item, "pubDate").text = pub_rfc

    ET.indent(rss, space="  ")
    OUT_FILE.write_text(ET.tostring(rss, encoding="unicode", xml_declaration=True), encoding="utf-8")
    print(f"Generated {OUT_FILE} with {len(tweets)} items")

if __name__ == "__main__":
    tweets = json.loads(DATA_FILE.read_text(encoding="utf-8")) if DATA_FILE.exists() else []
    build_rss(tweets)