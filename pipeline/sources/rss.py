"""Generic RSS 2.0 parsing (stdlib only) shared by Google News and outlet feeds."""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse


def _text(el) -> str:
    return html.unescape((el.text or "").strip()) if el is not None else ""


def strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(s or ""))).strip()


def rfc822_to_iso(s: str) -> str:
    try:
        return parsedate_to_datetime(s.strip()).isoformat()
    except Exception:
        return ""


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def parse_rss(xml_text: str) -> list[dict]:
    """Return [{title, link, published, description, source_name, source_url, categories}]."""
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    items = []
    for it in root.iter("item"):
        src = it.find("source")
        items.append({
            "title": _text(it.find("title")),
            "link": _text(it.find("link")),
            "published": rfc822_to_iso(_text(it.find("pubDate"))),
            "description": strip_tags(_text(it.find("description"))),
            "source_name": _text(src),
            "source_url": (src.get("url") if src is not None else "") or "",
            "categories": [_text(c) for c in it.findall("category")],
        })
    return items
