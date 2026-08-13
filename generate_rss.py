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
    ET.SubElement(ch, "title").text = "@buxiangdangguan - X Timeline"
    ET.SubElement(ch, "link").text = "https://x.com/buxiangdangguan"
    ET.SubElement(ch, "description").text = "自动抓取 @buxiangdangguan 公开推文"
    ET.SubElement(ch, "language").text = "zh-CN"
    # 使用北京时间 (UTC+8)
    bj_now = datetime.utcnow() + timedelta(hours=8)
    ET.SubElement(ch, "lastBuildDate").text = bj_now.strftime("%a, %d %b %Y %H:%M:%S +0800")
    ET.SubElement(ch, "atom:link", href="https://harviex.github.io/twitter-rss-buxiangdangguan/feed.xml", rel="self", type="application/rss+xml")

    for t in tweets:
        item = ET.SubElement(ch, "item")
        clean_text = strip_tco(t["text"])
        ET.SubElement(item, "title").text = clean_text[:100]
        # 去掉每条的 link
        ET.SubElement(item, "guid", isPermaLink="false").text = t["id"]
        # description: 纯文本 + 发布时间 (北京时间)
        try:
            dt = datetime.fromisoformat(t["datetime"].replace("Z", "+00:00"))
            bj_dt = dt + timedelta(hours=8)
            pub_str = bj_dt.strftime("%Y-%m-%d %H:%M")
            pub_rfc = bj_dt.strftime("%a, %d %b %Y %H:%M:%S +0800")
        except Exception:
            bj_now = datetime.utcnow() + timedelta(hours=8)
            pub_str = bj_now.strftime("%Y-%m-%d %H:%M")
            pub_rfc = bj_now.strftime("%a, %d %b %Y %H:%M:%S +0800")
        ET.SubElement(item, "description").text = f"{clean_text}\n\n{pub_str}"
        ET.SubElement(item, "pubDate").text = pub_rfc

    ET.indent(rss, space="  ")
    OUT_FILE.write_text(ET.tostring(rss, encoding="unicode", xml_declaration=True), encoding="utf-8")
    print(f"Generated {OUT_FILE} with {len(tweets)} items")

if __name__ == "__main__":
    tweets = json.loads(DATA_FILE.read_text(encoding="utf-8")) if DATA_FILE.exists() else []
    build_rss(tweets)