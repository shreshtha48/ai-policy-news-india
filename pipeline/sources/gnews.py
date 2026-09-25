"""GNews.io API (needs GNEWS_API_KEY). Optional third source.

STUB-ish: implemented against the documented response shape but NOT verified
live (no key in this environment). Skipped silently if the key is missing.
Free tier is small (~100 req/day, few articles per request), which is enough
for 6 states x 1 query.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from .. import http
from ..models import RawArticle
from .rss import domain_of

log = logging.getLogger(__name__)
KIND = "gnews"


def parse(payload: dict, state_hint: str = "", query: str = "") -> list[RawArticle]:
    now = datetime.now(timezone.utc).isoformat()
    return [RawArticle(
        source_kind=KIND, title=a.get("title", ""), url=a.get("url", ""),
        source_name=(a.get("source") or {}).get("name", ""),
        source_domain=domain_of((a.get("source") or {}).get("url", "") or a.get("url", "")),
        published=a.get("publishedAt", ""), excerpt=a.get("description", "") or "",
        state_hint=state_hint, query=query, fetched_at=now,
    ) for a in payload.get("articles", [])]


def fetch(state_code: str, state_name: str, cfg: dict) -> list[RawArticle]:
    key = os.environ.get(cfg["env_key"])
    if not key:
        log.info("gnews skipped for %s: %s not set", state_code, cfg["env_key"])
        return []
    q = cfg["query"].format(state=f'"{state_name}"')
    try:
        r = http.get(cfg["base"], params={"q": q, "lang": "en", "country": "in", "max": 10,
                                          "apikey": key}, min_interval=1.5)
        r.raise_for_status()
        return parse(r.json(), state_code, q)
    except Exception as e:
        log.warning("gnews %s failed: %s", state_code, e)
        return []
