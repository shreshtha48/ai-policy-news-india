"""Google News RSS search (no key). Primary source.

+ free, India edition, supports OR/quotes/`when:` operators, one feed per query.
- ~100 items max per query; links are news.google.com redirect URLs (we keep
  the outlet name/domain from <source>, but NOT the final article URL: decoding
  it needs an extra request per article and the format changes often).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from .. import http
from ..models import RawArticle
from .rss import domain_of, parse_rss

log = logging.getLogger(__name__)
KIND = "google_news_rss"


def clean_title(title: str, source_name: str) -> str:
    """Google appends ' - Outlet' to titles."""
    if source_name and title.endswith(" - " + source_name):
        return title[: -len(source_name) - 3].strip()
    return title


def parse(xml_text: str, state_hint: str = "", query: str = "") -> list[RawArticle]:
    now = datetime.now(timezone.utc).isoformat()
    out = []
    for it in parse_rss(xml_text):
        out.append(RawArticle(
            source_kind=KIND,
            title=clean_title(it["title"], it["source_name"]),
            url=it["link"],
            source_name=it["source_name"] or "Unknown",
            source_domain=domain_of(it["source_url"]) if it["source_url"] else "",
            published=it["published"],
            excerpt="",                   # Google's description is just title+outlet
            state_hint=state_hint, query=query, fetched_at=now,
        ))
    return out


def build_queries(cfg: dict, state_name: str, metros: list[str]) -> list[str]:
    qs = []
    for tpl in cfg["queries_per_state"]:
        if "{metro}" in tpl:
            qs += [tpl.format(metro=m) for m in metros]
        else:
            qs.append(tpl.format(state=f'"{state_name}"'))
    return [f'{q} {cfg["window"]}' for q in qs]


def fetch(state_code: str, state_name: str, metros: list[str], cfg: dict) -> list[RawArticle]:
    out = []
    for q in build_queries(cfg, state_name, metros):
        try:
            r = http.get(cfg["base"], params={"q": q, **cfg["params"]}, min_interval=2.0)
            r.raise_for_status()
            got = parse(r.text, state_code, q)
            log.info("google_news %s %r -> %d", state_code, q, len(got))
            out += got
        except Exception as e:                       # one bad query never kills the run
            log.warning("google_news %s failed for %r: %s", state_code, q, e)
    return out
