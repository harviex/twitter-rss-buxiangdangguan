#!/usr/bin/env python3
"""data/tweets.json → feed.xml (RSS 2.0)"""
import json
from pathlib import Path
from datetime import datetime
from xml.etree import ElementTree as ET

DATA_FILE = Path("data/tweets.json")
OUT_FILE = Path("feed.xml")

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
    ET.SubElement(ch, "lastBuildDate").text = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
    ET.SubElement(ch, "atom:link", href="https://harviex.github.io/twitter-rss-buxiangdangguan/feed.xml", rel="self", type="application/rss+xml")

    for t in tweets:
        item = ET.SubElement(ch, "item")
        ET.SubElement(item, "title").text = t["text"][:100]
        ET.SubElement(item, "link").text = t["url"]
        ET.SubElement(item, "guid", isPermaLink="false").text = t["id"]
        ET.SubElement(item, "description").text = t["text"]
        # parse datetime
        try:
            dt = datetime.fromisoformat(t["datetime"].replace("Z", "+00:00"))
            ET.SubElement(item, "pubDate").text = dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
        except Exception:
            ET.SubElement(item, "pubDate").text = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")

    ET.indent(rss, space="  ")
    OUT_FILE.write_text(ET.tostring(rss, encoding="unicode", xml_declaration=True), encoding="utf-8")
    print(f"Generated {OUT_FILE} with {len(tweets)} items")

if __name__ == "__main__":
    tweets = json.loads(DATA_FILE.read_text(encoding="utf-8")) if DATA_FILE.exists() else []
    build_rss(tweets)