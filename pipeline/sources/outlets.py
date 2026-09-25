"""Direct outlet sources: section RSS feeds + an HTML scraper.

* rss            - outlet section feeds (The Hindu state feeds, WordPress tag
                   feeds). Only the latest ~50-100 items, all topics: the AI
                   filter runs later. Coverage grows because raw results are
                   appended on every run.
* tt_tag_scrape  - Telangana Today's /tag/artificial-intelligence/page/N
                   listing (verified 2026-09-25): `.small-news li > h3 > a` +
                   `.excerpt`. The listing has NO dates, so each new article
                   page is fetched once for <meta property="article:published_time">.
                   If that fails the date stays empty (date_precision=unknown).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from .. import http
from ..models import RawArticle
from .rss import domain_of, parse_rss

log = logging.getLogger(__name__)


def parse_outlet_rss(xml_text: str, name: str, state_hint: str, feed_url: str) -> list[RawArticle]:
    now = datetime.now(timezone.utc).isoformat()
    return [RawArticle(
        source_kind="outlet_rss", title=it["title"], url=it["link"], source_name=name,
        source_domain=domain_of(it["link"]), published=it["published"],
        excerpt=it["description"][:500], state_hint=state_hint, query=feed_url, fetched_at=now,
        extra={"categories": it["categories"]},
    ) for it in parse_rss(xml_text)]


def parse_tt_listing(html_text: str, state_hint: str, page_url: str) -> list[RawArticle]:
    soup = BeautifulSoup(html_text, "html.parser")
    now = datetime.now(timezone.utc).isoformat()
    out, seen = [], set()
    for li in soup.select(".small-news li"):
        a = li.select_one("h3 a")
        if not a or not a.get("href") or a["href"] in seen:
            continue
        seen.add(a["href"])
        ex = li.select_one(".excerpt")
        out.append(RawArticle(
            source_kind="outlet_scrape", title=(a.get("title") or a.get_text()).strip(),
            url=a["href"], source_name="Telangana Today", source_domain="telanganatoday.com",
            published="", excerpt=ex.get_text(" ", strip=True) if ex else "",
            state_hint=state_hint, query=page_url, fetched_at=now,
        ))
    return out


def parse_published_meta(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "html.parser")
    for sel in ['meta[property="article:published_time"]', 'meta[name="publish-date"]',
                'meta[itemprop="datePublished"]']:
        m = soup.select_one(sel)
        if m and m.get("content"):
            return m["content"].strip()
    t = soup.select_one("time[datetime]")
    return t["datetime"].strip() if t else ""


def fetch(state_code: str, outlets: list[dict], known_urls: set[str],
          max_date_lookups: int = 40) -> list[RawArticle]:
    out: list[RawArticle] = []
    for o in outlets:
        try:
            if o["kind"] == "rss":
                r = http.get(o["url"]); r.raise_for_status()
                got = parse_outlet_rss(r.text, o["name"], state_code, o["url"])
            elif o["kind"] == "tt_tag_scrape":
                got = []
                for p in range(1, o.get("pages", 3) + 1):
                    url = o["url"].format(page=p)
                    r = http.get(url, min_interval=3.0); r.raise_for_status()
                    page = parse_tt_listing(r.text, state_code, url)
                    if not page:
                        break
                    got += page
                lookups = 0
                for a in got:            # date enrichment, only for unseen URLs
                    if a.url in known_urls or lookups >= max_date_lookups:
                        continue
                    lookups += 1
                    try:
                        a.published = parse_published_meta(http.get(a.url, min_interval=3.0).text)
                    except Exception as e:
                        log.debug("date lookup failed %s: %s", a.url, e)
            else:
                log.warning("unknown outlet kind %s", o["kind"]); continue
            log.info("outlet %s %s -> %d", state_code, o["url"], len(got))
            out += got
        except Exception as e:
            log.warning("outlet %s %s failed: %s", state_code, o["url"], e)
    return out
