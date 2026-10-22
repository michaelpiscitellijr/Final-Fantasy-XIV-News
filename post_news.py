import html
import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
LIMIT = 3  # newest posts to consider per feed
STATE_FILE = Path("posted.json")
UA = "Mozilla/5.0 (ffxiv-news-webhook)"
GENERIC_IMAGE_ID = "nxpYJrU9cbhAORBcM9FbZgG2rs"  # Lodestone's default site image

FEEDS = {
    "Topics": "https://na.finalfantasyxiv.com/lodestone/news/topics.xml",
}


def fetch(url, data=None, headers=None):
    h = {"User-Agent": UA, **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def local(tag):
    return tag.split("}")[-1]


class TextExtractor(HTMLParser):
    """Turns HTML into plain text, keeping paragraph breaks."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("p", "div", "li", "h1", "h2", "h3", "h4"):
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def to_text(raw, limit=350):
    if not raw:
        return ""
    # Feed bodies are often HTML that has been escaped; unescape until tags appear.
    if "<" not in raw:
        raw = html.unescape(raw)
    p = TextExtractor()
    p.feed(raw)
    text = html.unescape("".join(p.parts))
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text).strip()
    text = re.sub(r"\n{2,}", "\n", text)
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(".,;:!? ") + "…"
    return text


def find_image(raw):
    if not raw:
        return None
    if "<" not in raw:
        raw = html.unescape(raw)
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw)
    return m.group(1) if m else None


def og_image(page_url):
    try:
        page = fetch(page_url).decode("utf-8", "ignore")
    except Exception:
        return None
    for pat in (
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    ):
        m = re.search(pat, page)
        if m and GENERIC_IMAGE_ID not in m.group(1):
            return html.unescape(m.group(1))
    return None


def to_iso(value):
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)  # RSS dates
    except Exception:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))  # Atom dates
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


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
        if not link:
            continue
        raw = f.get("content") or f.get("encoded") or f.get("summary") or f.get("description") or ""
        items.append({
            "id": f.get("id") or f.get("guid") or link,
            "title": html.unescape(f.get("title", "(untitled)")),
            "link": link,
            "raw": raw,
            "date": to_iso(f.get("updated") or f.get("pubDate") or f.get("published")),
        })
    return items


def post(label, item):
    desc = to_text(item["raw"])
    if desc.strip().lower() == item["title"].strip().lower():
        desc = ""  # don't repeat the title

    embed = {
        "title": item["title"][:256],
        "url": item["link"],
        "color": 0x5865F2,
        "footer": {"text": f"FFXIV Lodestone · {label}"},
    }
    if desc:
        embed["description"] = desc
    if item["date"]:
        embed["timestamp"] = item["date"]

    # Image: use one from the feed body, else the article's og:image (Topics only)
    image = find_image(item["raw"])
    if not image and label == "Topics":
        image = og_image(item["link"])
    if image:
        embed["image"] = {"url": image}

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
