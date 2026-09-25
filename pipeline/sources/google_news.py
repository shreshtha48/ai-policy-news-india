"""Google News RSS search (no key). Primary source, and the only one that
reaches back to January 2026.

+ free, India edition, supports OR/quotes/site:/after:/before: operators.
- ~100 items max per query -> every query is sliced by MONTH (see plan.py).
- links are news.google.com redirect URLs (not the outlet URL); the real URL
  is borrowed from API/feed copies of the same article during dedupe, or
  decoded later by `python -m pipeline.run resolve`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from .. import http
from ..models import RawArticle
from ..plan import Call, month_slices
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


def base_queries(cfg: dict, code: str, state_name: str, metros: list[str]) -> list[str]:
    qs = []
    for tpl in cfg["queries_per_state"]:
        if "{metro}" in tpl:
            qs += [tpl.format(metro=m) for m in metros]
        else:
            qs.append(tpl.format(state=f'"{state_name}"'))
    qs += cfg.get("entity_queries", {}).get(code, [])
    sites = cfg.get("site_queries", {}).get(code, [])
    if sites:
        qs.append(cfg["site_query_template"].format(
            state=f'"{state_name}"', sites=" OR ".join(f"site:{s}" for s in sites)))
    return qs


def plan(code: str, state_name: str, metros: list[str], cfg: dict, since: str) -> list[Call]:
    calls = []
    for q in base_queries(cfg, code, state_name, metros):
        for after, before, closed in month_slices(since):
            full = f"{q} after:{after} before:{before}"
            calls.append(Call(api="google_news", state=code, key=f"google_news|{full}",
                              run=_runner(full, code, cfg), permanent=closed))
    return calls


def _runner(q: str, code: str, cfg: dict):
    def run() -> list[RawArticle]:
        r = http.get(cfg["base"], params={"q": q, **cfg["params"]}, min_interval=cfg.get("min_interval_s", 2.0))
        r.raise_for_status()
        return parse(r.text, code, q)
    return run
