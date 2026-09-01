#!/usr/bin/env python3
"""
data/tweets.json → feed.xml (RSS 2.0)
@BAIGUANXINGSHU only. No <link> per item.
"""
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
    text = TCO_PATTERN.sub("", text)
    return re.sub(r"\s+", " ", text).strip()

def replace_special(text: str) -> str:
    return text.replace("三个喝茶的标志", "被调查")

def build_rss(tweets):
    rss = ET.Element("rss", version="2.0", attrib={
        "xmlns:atom": "http://www.w3.org/2005/Atom",
        "xmlns:content": "http://purl.org/rss/1.0/modules/content/"
    })
    ch = ET.SubElement(rss, "channel")
    ET.SubElement(ch, "title").text = "@BAIGUANXINGSHU 官方推文"
    ET.SubElement(ch, "link").text = "https://harviex.github.io/twitter-rss-buxiangdangguan/"
    ET.SubElement(ch, "description").text = "官方账号 @BAIGUANXINGSHU 推文 RSS（北京时间）"
    ET.SubElement(ch, "language").text = "zh-CN"
    bj_now = datetime.utcnow() + timedelta(hours=8)
    ET.SubElement(ch, "lastBuildDate").text = bj_now.strftime("%a, %d %b %Y %H:%M:%S +0800")
    ET.SubElement(ch, "atom:link", href="https://harviex.github.io/twitter-rss-buxiangdangguan/feed.xml", rel="self", type="application/rss+xml")

    for t in tweets:
        clean_text = strip_tco(t["text"])
        clean_text = replace_special(clean_text)

        # 跳过"已官宣"类推文
        if clean_text.startswith("已官宣"):
            continue

        item = ET.SubElement(ch, "item")

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
        ET.SubElement(item, "title").text = title_text[:200]
        ET.SubElement(item, "guid", isPermaLink="false").text = t["id"]
        ET.SubElement(item, "description").text = ""
        ET.SubElement(item, "pubDate").text = pub_rfc
        # NOTE: no <link> tag per item

    ET.indent(rss, space="  ")
    OUT_FILE.write_text(ET.tostring(rss, encoding="unicode", xml_declaration=True), encoding="utf-8")
    print(f"Generated {OUT_FILE} with {len(tweets)} items")

if __name__ == "__main__":
    tweets = json.loads(DATA_FILE.read_text(encoding="utf-8")) if DATA_FILE.exists() else []

    # 统一解析 datetime 以便正确排序
    for t in tweets:
        dt_str = t.get("datetime", "")
        for fmt in ["%Y-%m-%dT%H:%M:%S.%fZ", "%a, %d %b %Y %H:%M:%S GMT", "%a, %d %b %Y %H:%M:%S %Z"]:
            try:
                t["_parsed"] = datetime.strptime(dt_str, fmt)
                break
            except:
                continue

    tweets.sort(key=lambda x: x.get("_parsed", datetime.min), reverse=True)
    build_rss(tweets)
