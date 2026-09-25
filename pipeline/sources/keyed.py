"""Keyed news APIs: GNews, NewsAPI.org, NewsData.io.

All three free tiers only reach the recent past (GNews 30 days, NewsAPI 1
month, NewsData 48 h), so they are used for RECENT enrichment: outlet URLs
and descriptions that Google News lacks, plus independent confirmation.
One call per state per day each; skipped (not failed) when the key is unset.
Response shapes follow the providers' docs; not yet verified live.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from .. import http
from ..models import RawArticle
from ..plan import Call
from .rss import domain_of

log = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc)


def _from_date(cfg: dict, since: str) -> str:
    start = max(datetime.fromisoformat(since).replace(tzinfo=timezone.utc),
                _now() - timedelta(days=cfg.get("lookback_days", 29)))
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------- parsers (pure; tested with fixtures) ----------------
def parse_gnews(payload: dict, state_hint: str = "", query: str = "") -> list[RawArticle]:
    now = _now().isoformat()
    return [RawArticle(
        source_kind="gnews", title=a.get("title", ""), url=a.get("url", ""),
        source_name=(a.get("source") or {}).get("name", ""),
        source_domain=domain_of(a.get("url", "")),
        published=a.get("publishedAt", ""), excerpt=a.get("description", "") or "",
        state_hint=state_hint, query=query, fetched_at=now,
    ) for a in payload.get("articles", [])]


def parse_newsapi(payload: dict, state_hint: str = "", query: str = "") -> list[RawArticle]:
    if payload.get("status") == "error":
        raise RuntimeError(f"newsapi: {payload.get('code')}: {payload.get('message')}")
    now = _now().isoformat()
    return [RawArticle(
        source_kind="newsapi", title=a.get("title") or "", url=a.get("url") or "",
        source_name=(a.get("source") or {}).get("name") or "",
        source_domain=domain_of(a.get("url") or ""),
        published=a.get("publishedAt") or "", excerpt=a.get("description") or "",
        state_hint=state_hint, query=query, fetched_at=now,
    ) for a in payload.get("articles", []) if a.get("title") and a.get("title") != "[Removed]"]


def parse_newsdata(payload: dict, state_hint: str = "", query: str = "") -> list[RawArticle]:
    if payload.get("status") != "success":
        raise RuntimeError(f"newsdata: {payload.get('results') or payload}")
    now = _now().isoformat()
    out = []
    for a in payload.get("results", []) or []:
        pub = a.get("pubDate") or ""
        if pub and "T" not in pub:                   # "2026-09-24 10:00:00", UTC per docs
            tz = (a.get("pubDateTZ") or "UTC").upper()
            pub = pub.replace(" ", "T") + ("+00:00" if tz == "UTC" else "")
        out.append(RawArticle(
            source_kind="newsdata", title=a.get("title") or "", url=a.get("link") or "",
            source_name=a.get("source_name") or a.get("source_id") or "",
            source_domain=domain_of(a.get("source_url") or a.get("link") or ""),
            published=pub, excerpt=a.get("description") or "",
            state_hint=state_hint, query=query, fetched_at=now,
        ))
    return out


# ---------------- planning ----------------
def _keyed_call(api: str, code: str, cfg: dict, params: dict, parser, key_param: str | None,
                headers_key: str | None = None) -> Call:
    key = os.environ.get(cfg["env_key"], "").strip()
    q = params.get("q", "")

    def run():
        p = dict(params)
        if key_param:
            p[key_param] = key
        hdrs = {headers_key: key} if headers_key else None
        r = http.get(cfg["base"], params=p, min_interval=1.5, headers=hdrs)
        if r.status_code in (401, 403, 426, 429):
            raise RuntimeError(f"{api} HTTP {r.status_code}: {r.text[:200]}")
        r.raise_for_status()
        return parser(r.json(), code, q)

    return Call(api=api, state=code, key=f"{api}|{code}|{q}", run=run, keyed=True,
                skip_reason="" if key else f"{cfg['env_key']} not set", meta={"q": q})


def plan_gnews(code: str, state_name: str, cfg: dict, since: str) -> list[Call]:
    q = cfg["query"].format(state=f'"{state_name}"')
    params = {"q": q, "lang": "en", "country": "in", "max": 10, "in": "title,description",
              "sortby": "publishedAt", "from": _from_date(cfg, since)}
    return [_keyed_call("gnews", code, cfg, params, parse_gnews, "apikey")]


def plan_newsapi(code: str, state_name: str, cfg: dict, since: str) -> list[Call]:
    q = cfg["query"].format(state=f'"{state_name}"')
    params = {"q": q, "language": "en", "searchIn": "title,description", "sortBy": "publishedAt",
              "pageSize": 100, "from": _from_date(cfg, since)[:10], "domains": ",".join(cfg["domains"])}
    return [_keyed_call("newsapi", code, cfg, params, parse_newsapi, None, headers_key="X-Api-Key")]


def plan_newsdata(code: str, state_name: str, cfg: dict, since: str) -> list[Call]:
    q = cfg["query"].format(state=f'"{state_name}"')
    params = {"q": q, "country": "in", "language": "en"}
    return [_keyed_call("newsdata", code, cfg, params, parse_newsdata, "apikey")]
