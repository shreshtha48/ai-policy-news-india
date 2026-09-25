"""GDELT DOC 2.0 API (no key). Secondary source.

Observed 2026-09-25: strict rate limit (plain-text 'Please limit requests to
one every 5 seconds' instead of JSON), `{}` for no-result queries (possibly
for quoted phrases - unverified), articles in all Indian languages (we keep
English). If the main query returns nothing, the unquoted fallback is tried.
The DOC API only searches roughly the last 3 months.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from .. import http
from ..models import RawArticle
from ..plan import Call
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


def _query(cfg: dict, q: str, since: str) -> list[RawArticle] | None:
    start = max(datetime.fromisoformat(since), datetime.utcnow() - timedelta(days=89))
    params = {"query": q, "mode": "artlist", "format": "json", "maxrecords": 250, "sort": "datedesc",
              "startdatetime": start.strftime("%Y%m%d000000")}
    for attempt in range(3):
        r = http.get(cfg["base"], params=params, min_interval=cfg["min_interval_s"])
        if r.text.startswith("Please limit"):
            log.warning("gdelt rate limited, waiting (attempt %d)", attempt + 1)
            time.sleep(15 * (attempt + 1)); continue
        return parse(r.json() if r.text.strip() else {}, "", q)
    raise RuntimeError("gdelt rate limited 3 times")


def plan(code: str, state_name: str, cfg: dict, since: str) -> list[Call]:
    def run():
        got = _query(cfg, cfg["query"].format(state=state_name), since) or []
        if not got and cfg.get("fallback_query"):
            log.info("gdelt %s: main query empty, trying fallback", code)
            got = _query(cfg, cfg["fallback_query"].format(state=state_name), since) or []
        for a in got:
            a.state_hint = code
        return got
    return [Call(api="gdelt", state=code, key=f"gdelt|{code}", run=run)]
