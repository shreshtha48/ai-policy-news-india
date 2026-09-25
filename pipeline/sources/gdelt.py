"""GDELT DOC 2.0 API (no key). Secondary / backfill source.

Observed 2026-09-25: strict rate limit (plain-text 'Please limit requests to one
every 5 seconds' instead of JSON, sometimes even when spaced), `{}` for
no-result queries, and articles in all Indian languages (we request English).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from .. import http
from ..models import RawArticle
from .rss import domain_of

log = logging.getLogger(__name__)
KIND = "gdelt"


def seendate_to_iso(s: str) -> str:
    try:
        return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
    except Exception:
        return ""


def parse(payload: dict, state_hint: str = "", query: str = "") -> list[RawArticle]:
    now = datetime.now(timezone.utc).isoformat()
    out = []
    for a in payload.get("articles", []) or []:
        if a.get("language") and a["language"] != "English":
            continue
        out.append(RawArticle(
            source_kind=KIND, title=(a.get("title") or "").strip(), url=a.get("url", ""),
            source_name=a.get("domain", ""), source_domain=domain_of(a.get("url", "")),
            published=seendate_to_iso(a.get("seendate", "")),
            state_hint=state_hint, query=query, fetched_at=now,
        ))
    return out


def fetch(state_code: str, state_name: str, cfg: dict, retries: int = 3) -> list[RawArticle]:
    q = cfg["query"].format(state=state_name)
    params = {"query": q, "mode": "artlist", "format": "json", "maxrecords": 250,
              "timespan": cfg["timespan"], "sort": "datedesc"}
    for attempt in range(retries):
        try:
            r = http.get(cfg["base"], params=params, min_interval=cfg["min_interval_s"])
            if r.text.startswith("Please limit"):
                raise RuntimeError("rate limited")
            payload = r.json() if r.text.strip() else {}
            got = parse(payload, state_code, q)
            log.info("gdelt %s -> %d", state_code, len(got))
            return got
        except Exception as e:
            log.warning("gdelt %s attempt %d: %s", state_code, attempt + 1, e)
            time.sleep(10 * (attempt + 1))
    return []
