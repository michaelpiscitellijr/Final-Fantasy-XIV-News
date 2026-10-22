import json
import os
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
LIMIT = 3  # newest posts to consider per feed
STATE_FILE = Path("posted.json")
UA = "Mozilla/5.0 (ffxiv-news-webhook)"

FEEDS = {
    "News": "https://na.finalfantasyxiv.com/lodestone/news/news.xml",
    "Topics": "https://na.finalfantasyxiv.com/lodestone/news/topics.xml",
}


def fetch(url, data=None, headers=None):
    h = {"User-Agent": UA, **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def local(tag):
    return tag.split("}")[-1]


def parse(xml_bytes):
    """Handles both RSS (<item>) and Atom (<entry>) feeds."""
    items = []
    for el in ET.fromstring(xml_bytes).iter():
        if local(el.tag) not in ("item", "entry"):
            continue
        f = {}
        for c in el:
            name = local(c.tag)
            if name == "link":
                f["link"] = c.attrib.get("href") or (c.text or "").strip()
            else:
                f.setdefault(name, (c.text or "").strip())
        link = f.get("link", "")
        if link:
            items.append({
                "id": f.get("id") or f.get("guid") or link,
                "title": f.get("title", "(untitled)"),
                "link": link,
                "summary": f.get("summary") or f.get("description") or "",
            })
    return items


def post(label, item):
    embed = {
        "title": item["title"][:256],
        "url": item["link"],
        "color": 0x5865F2,
        "footer": {"text": f"FFXIV Lodestone · {label}"},
    }
    if item["summary"]:
        embed["description"] = item["summary"][:300]
    body = json.dumps({"embeds": [embed]}).encode()
    fetch(WEBHOOK_URL, data=body, headers={"Content-Type": "application/json"})


def main():
    posted = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else []
    for label, url in FEEDS.items():
        newest = parse(fetch(url))[:LIMIT]
        for item in reversed(newest):  # oldest first
            if item["id"] in posted:
                continue
            post(label, item)
            posted.append(item["id"])
            print("Posted:", item["title"])
    STATE_FILE.write_text(json.dumps(posted[-200:], indent=2))


if __name__ == "__main__":
    main()
